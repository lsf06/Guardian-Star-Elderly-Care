#!/usr/bin/env python3
"""采集，直接写成 data/schema.md 定义的格式。

  python src/capture.py --label sit --minutes 3
  python src/capture.py --label breathhold --minutes 3 --event-at 20
  python src/capture.py --label lie --minutes 3 --event-at 20 --pin-door 18

关键：--label 和 --event-at 在开始时就定好，不要事后补。
事后补的一定错，而 event_at 错了，所有延迟数字全废。
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ld2410 import Decoder, STATE_NAMES        # noqa: E402

HEAD = ["session", "t", "label", "phase", "state", "door",
        "move_dist", "still_dist", "still_energy", "event_at"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=256000)
    ap.add_argument("--label", required=True,
                    choices=["empty", "sit", "moving", "breathhold", "lie", "exit"])
    ap.add_argument("--minutes", type=float, default=3)
    ap.add_argument("--event-at", type=float, default=None,
                    help="第几秒做动作（屏息/躺倒/开门）。事件组必须填")
    ap.add_argument("--pin-door", type=int, default=None, help="接了门磁就填，例如 18")
    ap.add_argument("--door-open-level", type=int, default=1, choices=[0, 1])
    ap.add_argument("--session", default="")
    ap.add_argument("--out", default="data/guardian.csv")
    args = ap.parse_args()

    if args.label in ("breathhold", "lie", "exit") and args.event_at is None:
        print("警告：%s 没给 --event-at，这一组数据算不出延迟。" % args.label)

    import serial
    ser = serial.Serial(args.port, args.baud, timeout=0.2)

    door = None
    if args.pin_door is not None:
        from gpiozero import Button
        door = Button(args.pin_door, pull_up=None, active_state=None, bounce_time=0.2)

    session = args.session or "%s_%s" % (args.label, time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    new = not os.path.exists(args.out)
    f = open(args.out, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    if new:
        w.writerow(HEAD)

    dec = Decoder()

    # 前置自检：3 秒内一帧都没有，就不要假装在采集。
    # 波特率写错（115200 vs 256000）、TX/RX 接反、没共地，
    # 表现都是「安静地跑完 3 分钟，写出 0 行」，然后你才会发现。
    # 那 3 分钟不是最贵的，最贵的是你以为自己采到了。
    print("自检 3 秒，确认雷达在输出……")
    probe = []
    pt = time.time()
    while time.time() - pt < 3.0:
        c = ser.read(256)
        if c:
            probe += dec.feed(c)
    if not probe:
        print()
        print("3 秒内 0 帧。按这个顺序查，不要跳：")
        print("  1. 接线：雷达 TX -> GPIO15(Pin10)，雷达 RX -> GPIO14(Pin8)，交叉接")
        print("  2. 供电：VCC 接 5V（Pin2/4），不是 3.3V")
        print("  3. 共地：雷达 GND 与树莓派 GND 必须连通")
        print("  4. 端口：Pi5 是 /dev/ttyAMA0，不是 /dev/ttyS0 或 /dev/serial0")
        print("  5. 波特率：LD2410 默认 256000，不是 115200")
        print("  6. config.txt 只写 dtparam=uart0=on，不要写 uart0_console")
        print("先跑 python src/test_radar.py 确认能看到帧。")
        ser.close()
        return 3
    print("自检通过：3 秒内 %d 帧。丢弃自检帧，正式计时从现在开始。" % len(probe))

    t0 = time.time()
    total = events = 0
    last_report = -10.0
    last_state = 0
    print("开始 %s，%.1f 分钟，事件 @ %s 秒。Ctrl-C 提前结束。"
          % (session, args.minutes, args.event_at))

    try:
        while True:
            now = time.time()
            t = now - t0
            if t >= args.minutes * 60:
                break
            chunk = ser.read(256)
            for fr in (dec.feed(chunk) if chunk else []):
                last_state = fr["state"]
                door_open = 1 if (door is not None and
                                  (1 if door.is_active else 0) == args.door_open_level) else 0
                phase = "event" if (args.event_at is not None and t >= args.event_at) else "pre"
                w.writerow([session, round(t, 2), args.label, phase, fr["state"], door_open,
                            fr["move_dist"], fr["still_dist"], fr["still_energy"],
                            args.event_at if args.event_at is not None else ""])
                total += 1
                if phase == "event":
                    events += 1
            if t - last_report >= 10:
                last_report = t
                print("  %3.0fs  帧 %5d  当前状态=%s"
                      % (t, total, STATE_NAMES.get(last_state, "?")))
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        f.close()
        ser.close()

    print("写入 %d 行（事件段 %d 行）-> %s" % (total, events, args.out))
    if total == 0:
        print("0 行说明雷达没通，先跑 test_radar.py。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
