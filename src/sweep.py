#!/usr/bin/env python3
"""扫出「打扰预算 vs 检出率」曲线。这是本项目的核心产出。

  python src/sweep.py data/guardian_2026xxxx.csv
  python src/sweep.py data/xxx.csv --ts 15,30,45,60,90,120,180

做法：把录好的数据按不同静默阈值 T 重放一遍状态机，统计
  · 正常静坐/躺着时的误问候  -> 折算成「次 / 24 小时」
  · 屏息事件的检出率与延迟
  · 开门离场时的误问候（应该恒为 0）
这就是「别人报一个识别率，我报一条前沿」的那条前沿。
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardian import Config, Guardian        # noqa: E402

STILL_LABELS = {"sit", "still"}
EVENT_LABELS = {"breathhold", "exit"}


def load(path):
    sessions = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s = r["session"]
            sessions.setdefault(s, []).append({
                "t": float(r["t"]),
                "label": r.get("label", ""),
                "phase": r.get("phase", "pre"),
                "state": int(float(r.get("state") or 0)),
                "door": int(float(r.get("door") or 0)),
                "event_at": float(r["event_at"]) if r.get("event_at") else None,
            })
    for v in sessions.values():
        v.sort(key=lambda x: x["t"])
    return sessions


def run(sessions, T):
    """重放一遍，返回各项指标。

    分开统计四类，因为它们的含义完全不同，混在一起会得出错误结论：
      · sit/still  静坐时的误问候 —— 这是「打扰预算」的分子
      · lie        躺倒但正常呼吸时的问候 —— 这是雷达能力的上限证明
                   如果这里出 ask，说明雷达丢了本该看到的人，属于严重问题
      · empty      空房间里的问候 —— 屋里没人还在说话，是灾难性误报
      · breathhold 屏息事件 —— 检出与否，决定这条路成不成立
    """
    asks_still = 0
    still_sec = 0.0
    detects = misses = 0
    lat = []
    exit_fa = 0
    empty_fa = 0
    lie_asks = 0

    for name, rows in sessions.items():
        if not rows:
            continue
        g = Guardian(Config(silence=T, answer_window=30), t0=rows[0]["t"])
        label = rows[0]["label"]
        event_at = next((r["event_at"] for r in rows if r["event_at"]), None)
        dur = rows[-1]["t"] - rows[0]["t"]
        if label in STILL_LABELS:
            still_sec += dur

        first_ask_after = None
        for r in rows:
            ev = g.update(r["t"], seen=(r["state"] != 0), door_open=bool(r["door"]))
            for kind, _ in ev:
                if kind != "ask":
                    continue
                if label in STILL_LABELS:
                    asks_still += 1
                if label == "lie":
                    lie_asks += 1
                if label == "empty":
                    empty_fa += 1
                if label == "exit" and (event_at is None or r["t"] >= event_at):
                    exit_fa += 1
                if label == "breathhold" and event_at and r["t"] >= event_at \
                        and first_ask_after is None:
                    first_ask_after = r["t"]

        if label == "breathhold" and event_at:
            if first_ask_after is None:
                misses += 1
            else:
                detects += 1
                lat.append(first_ask_after - event_at)

    hours = still_sec / 3600.0
    per_day = (asks_still / hours * 24) if hours > 0 else 0.0
    rate = detects / (detects + misses) if (detects + misses) else float("nan")
    mean_lat = sum(lat) / len(lat) if lat else float("nan")
    return per_day, rate, mean_lat, exit_fa, empty_fa, lie_asks, still_sec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--ts", default="15,30,45,60,90,120,180")
    ap.add_argument("--out", default="sweep_result.csv")
    args = ap.parse_args()

    sessions = load(args.csv)
    ts = [float(x) for x in args.ts.split(",")]

    print("会话数 %d，标签：%s" % (len(sessions), sorted({v[0]["label"] for v in sessions.values()})))
    missing = [x for x in ("empty", "sit", "breathhold", "lie", "exit")
               if x not in {v[0]["label"] for v in sessions.values()}]
    if missing:
        why = {"empty": "定不了底噪", "sit": "没有打扰预算的分子",
               "breathhold": "不知道这条路成不成立", "lie": "证明不了「不做跌倒检测」",
               "exit": "验证不了门磁否决"}
        print("缺少会话：%s" % "，".join("%s（%s）" % (m, why[m]) for m in missing))
    print()
    print("  T(s) | 静坐误问候/24h | 屏息检出率 | 平均延迟(s) | 离场误问候 | 空房误问候 | 躺平误问候")
    print("-------+-----------------+------------+-------------+------------+------------+------------")
    rows = []
    for T in ts:
        per_day, rate, lat, fa, empty_fa, lie_asks, _ = run(sessions, T)
        print(" %5.0f | %15.1f | %9s | %11s | %10d | %10d | %10d"
              % (T, per_day,
                 ("%.0f%%" % (rate * 100)) if rate == rate else "n/a",
                 ("%.1f" % lat) if lat == lat else "n/a",
                 fa, empty_fa, lie_asks))
        rows.append([T, round(per_day, 2),
                     round(rate, 3) if rate == rate else "",
                     round(lat, 1) if lat == lat else "", fa, empty_fa, lie_asks])

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["T_sec", "asks_per_24h_still", "detect_rate", "mean_latency_s",
                    "exit_false_alarm", "empty_false_alarm", "lie_asks"])
        w.writerows(rows)
    print()
    print("已写入 %s。用它画双纵轴折线图，标出你选的 T。" % args.out)
    print("选点的原则不是「检出率最高」，是「在可接受的打扰次数里，检出率最高」。")
    longest = max((v[-1]["t"] - v[0]["t"]) for v in sessions.values() if v)
    print("注意：本次最长会话 %.0f 秒。T 超过会话时长的一半时，那一行没有意义"
          "（窗口填不满），补数据或去掉这几个 T。" % longest)

    _, _, _, _, _, _, still_sec = run(sessions, ts[0])
    print()
    print("【读这一行，别读上面的表】静坐样本合计 %.0f 秒（%.1f 分钟）。"
          % (still_sec, still_sec / 60))
    if still_sec < 1800:
        print("  不到 30 分钟。「误问候/24h」这一列是从这几分钟外推的，")
        print("  外推倍数 = %.0f 倍。5 分钟 0 次，不能代表 24 小时 0 次。"
              % (86400.0 / max(still_sec, 1)))
        print("  答辩时请直接报「N 分钟里误问候几次」，不要报「每天几次」。")
        print("  想报每天，就把 sit 补到 2 小时以上（可以边干别的边录）。")
    print("  空房误问候与躺平误问候必须为 0；不为 0 说明雷达在你没动的房间里丢了人，")
    print("  这比误问候更严重，先查摆放距离（0.8m 以内是盲区）。")


if __name__ == "__main__":
    main()
