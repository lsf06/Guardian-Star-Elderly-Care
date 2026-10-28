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
    t0 = time.time()
    total = events = 0
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
                door_open = 1 if (door is not None and
                                  (1 if door.is_active else 0) == args.door_open_level) else 0
                phase = "event" if (args.event_at is not None and t >= args.event_at) else "pre"
                w.writerow([session, round(t, 2), args.label, phase, fr["state"], door_open,
                            fr["move_dist"], fr["still_dist"], fr["still_energy"],
                            args.event_at if args.event_at is not None else ""])
                total += 1
                if phase == "event":
                    events += 1
            if int(t) % 10 == 0 and total and int(t) > 0 and abs(t - round(t)) < 0.05:
                print("  %3.0fs  帧 %5d  当前状态=%s"
                      % (t, total, STATE_NAMES.get(fr["state"], "?") if total else "?"))
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
