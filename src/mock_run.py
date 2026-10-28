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
    asks = [x for x in log if x[1] == "ask"]
    esc = [x for x in log if x[1] == "escalate"]
    after = [x for x in log if x[0] > 300 and x[1] in ("ask", "escalate")]
    ok = True

    if len(asks) > 2:
        print("FAIL: 问候 %d 次，锁存失效（应 <= 2）" % len(asks))
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

    print("回归测试: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
