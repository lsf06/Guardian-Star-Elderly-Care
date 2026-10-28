#!/usr/bin/env python3
"""无硬件跑完整剧本。虚拟时钟，1 秒一步，几秒钟看完 10 分钟的行为。

  python src/mock_run.py
  python src/mock_run.py --verbose      # 逐秒打印内部状态
  python src/mock_run.py --silence 90   # 用产品参数跑（约 10 分钟虚拟时间）

剧本：
  0-20    上电，房间没人          -> 启动自检提示
  20-80   老人坐下看电视          -> 武装
  80-120  屏息/被毯子盖住         -> 触发问候 -> 按键消解
  120-150 开门 30 秒             -> 离家模式，不判、不问
  150-180 门关、人还在外面
  180-200 人回来
  200-600 人又不见了（门关着）    -> 问候 -> 不按键 -> 推送
  300-600 继续静默                -> 必须 0 事件（锁存回归测试）
  600     按键                    -> 消解已升级的事件
  620     再按键                  -> 唤醒对话（冷却已过）

退出码：回归测试不通过时非 0。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardian import Config, Guardian            # noqa: E402


def build_script():
    """返回 [(t_start, t_end, seen, door_open)]，按时间排序的区间。"""
    return [
        (0, 20, False, False),
        (20, 80, True, False),
        (80, 120, False, False),
        (120, 150, False, True),     # 门开着，10 秒后判离家
        (150, 180, False, False),    # 门关了，人还在外面
        (180, 200, True, False),     # 人回来
        (200, 600, False, False),    # 又不见了，没人按键
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--silence", type=float, default=20.0,
                    help="静默阈值（默认 20s 演示；产品用 90）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = Config(
        silence=args.silence,
        answer_window=8.0,
        second_ask_after=4.0,
        away_confirm=10.0,
        suppress_short=20.0,
        heartbeat=5.0,
        startup_check=5.0,
        speech_freeze=2.0,
    )
    g = Guardian(cfg, t0=0.0)

    presses = {101, 600, 620}    # 101 消解问候；600 消解已升级；620 唤醒对话
    script = build_script()

    log = []
    for t in range(0, 720):
        seen, door = False, False
        for a, b, s, d in script:
            if a <= t < b:
                seen, door = s, d
                break
        ev = g.update(float(t), seen=seen, door_open=door, pressed=(t in presses))
        for kind, text in ev:
            log.append((t, kind, text))
            print("[%04d] %-10s %s" % (t, kind, text))
        if args.verbose and t % 10 == 0:
            print("        %s" % g.snapshot())

    print("\n统计: 问候 %d 次 / 推送 %d 次 / 对话 %d 次"
          % (g.counts["ask"], g.counts["escalate"], g.counts["chat"]))

    # ---- 回归测试：锁存是否生效 ----------------------------------------
    asks = [x for x in log if x[1] in ("ask", "ask_again")]
    esc = [x for x in log if x[1] == "escalate"]
    first_esc = esc[0][0] if esc else None
    after = [x for x in log if x[1] in ("ask", "ask_again", "escalate")
             and first_esc is not None and x[0] > first_esc and x[0] < 600]
    ok = True

    # 剧本里有两段静默：96 秒那段被按键消解，216 秒那段升级。每段最多问 2 句。
    if len(asks) > 4:
        print("FAIL: 一共问了 %d 句，锁存失效（两段静默 × 每段 2 句 = 4）" % len(asks))
        ok = False
    if len(esc) > 1:
        print("FAIL: 推送 %d 次，升级未锁存（应 <= 1）" % len(esc))
        ok = False
    if after:
        print("FAIL: 升级之后仍在重复打扰：%r" % (after,))
        ok = False
    if not any(x[1] == "away" for x in log):
        print("FAIL: 门开 30 秒没有进入离家模式")
        ok = False
    if any(x[1] == "ask" and 120 <= x[0] < 200 for x in log):
        print("FAIL: 离家期间触发了问候")
        ok = False
    if not any(x[1] == "startup" for x in log):
        print("FAIL: 上电无人没有给出摆放提示")
        ok = False

    # ---- 回归测试：消解之后不能永久沉默（漏报是最坏的失效）------------
    # 老人在第 45 秒拍键说「我没事」，随后真的倒下，雷达再也看不到他。
    # 安静期一过必须再问一次。这里曾经写成「resolved 永久挂起」，
    # 结果按键之后系统从此一句话不说，而且它发生在设备刚被证明正常之后。
    qcfg = Config(silence=20, answer_window=8, away_confirm=10,
                  suppress_short=20, after_resolve_quiet=100,
                  max_asks_per_visit=2)
    gq = Guardian(qcfg, t0=0.0)
    qlog = []
    tt = 0
    while tt < 40:
        for k, _ in gq.update(float(tt), seen=True):
            qlog.append((tt, k))
        tt += 1
    while tt < 400:
        for k, _ in gq.update(float(tt), seen=False, pressed=(tt == 45)):
            qlog.append((tt, k))
        tt += 1
    later = [x for x in qlog if x[1] == "ask" and x[0] > 60]
    if not later:
        print("FAIL: 按键消解后系统永久沉默，老人此时真的出事也不会被发现（漏报）")
        ok = False

    # ---- 回归测试：人在场但动不了，点名必须在有界时间内发现 -------------
    # 这是整个项目最危险的洞。倒地不起、仍在呼吸的人，雷达一直看得见，
    # 静默判定永远不触发。没有点名，设备对最危险的场景一句话都不会说 ——
    # 而「买它干什么」这个问题，正是从这里来的。
    ccfg = Config(silence=20, answer_window=8, suppress_short=20)
    gc = Guardian(ccfg, t0=0.0)
    clog = []
    t = 0.0
    for minute in range(8 * 60, 21 * 60):      # 08:00 -> 21:00，一分钟一步
        for k, _ in gc.update(t, seen=True, now_tod=float(minute * 60)):
            clog.append((minute, k))
        t += 60.0
    first_ci = [x for x in clog if x[1] == "checkin"]
    if not first_ci:
        print("FAIL: 全天人在场但没有点名 —— 人倒地不动时设备永久沉默")
        ok = False
    elif first_ci[0][0] > 9 * 60 + 5:
        print("FAIL: 点名没有在 09:00 附近发生（实际 %02d:%02d）"
              % (first_ci[0][0] // 60, first_ci[0][0] % 60))
        ok = False
    if not any(x[1] == "escalate" for x in clog):
        print("FAIL: 点名无人应答，却没有推送家属")
        ok = False

    # ---- 回归测试：点名时按了键，不能推送，且要留下「今日平安」------------
    gb = Guardian(ccfg, t0=0.0)
    blog = []
    t = 0.0
    for minute in range(8 * 60, 10 * 60):
        pressed = (minute == 9 * 60 + 1)       # 点名后一分钟内按下去了
        for k, _ in gb.update(t, seen=True, pressed=pressed,
                              now_tod=float(minute * 60)):
            blog.append((minute, k))
        t += 60.0
    if any(x[1] == "escalate" for x in blog):
        print("FAIL: 老人按时按了键，仍然推送了家属（误报）")
        ok = False
    if gb.counts["checkin_ok"] != 1:
        print("FAIL: 点名后按键没有计入 checkin_ok —— 家属端看不到「今日平安」，")
        print("      也就无法通过「今天没收到平安」发现设备被拔了")
        ok = False

    print("回归测试: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
