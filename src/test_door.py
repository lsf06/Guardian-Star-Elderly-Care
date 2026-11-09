#!/usr/bin/env python3
"""门磁实测。不要相信「常开/常闭」的标签，各家标法不统一。

  python src/test_door.py --pin 18

开门、关门各试几次，看终端打印的电平，然后把实际值填进 guardian_main 的
--door-open-level。买错型号的典型症状：开门报「关门」，逻辑整个反掉。
"""
import argparse
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", type=int, default=18)
    ap.add_argument("--seconds", type=float, default=30)
    args = ap.parse_args()

    try:
        from gpiozero import Button
    except ImportError:
        print("缺少 gpiozero（树莓派系统自带）。若在 PC 上运行，请加 --dry-run。")
        return 2

    try:
        # pull_up=True：内部上拉，按键/干簧管一端接 GPIO、另一端接 GND。
        # 不要写 pull_up=None + active_state=None —— gpiozero 会直接抛
        # PinInvalidState（"defined as floating, but active_state is not defined"），
        # 程序根本起不来。这个坑在 guardian_main / capture 里也出现过。
        b = Button(args.pin, pull_up=True, bounce_time=0.2)
    except Exception as e:
        print("打开 GPIO%d 失败：%s" % (args.pin, e))
        print("Pi5 上必须用 gpiozero（底层 lgpio）；RPi.GPIO 会直接崩。")
        return 2

    print("监听 GPIO%d，%.0f 秒。现在去开门、关门各试几次。" % (args.pin, args.seconds))
    t0 = time.time()
    last = None
    while time.time() - t0 < args.seconds:
        cur = 1 if b.is_active else 0
        if cur != last:
            print("  电平 = %d  %s" % (cur, "← 记下这个值，如果是开门时的电平，就填 --door-open-level %d" % cur))
            last = cur
        time.sleep(0.05)

    print("\n结论：把「开门时出现的那个电平」设为 --door-open-level，另一侧就是关门。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
