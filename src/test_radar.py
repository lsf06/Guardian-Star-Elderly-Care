#!/usr/bin/env python3
"""识别状态 + 雷达上电自检。

  python src/test_radar.py --port /dev/ttyAMA0
  python src/test_radar.py --port /dev/ttyAMA0 --dump raw.bin   # 存原始字节，方便离线排查

先跑这个，再做实验。看到 10 帧/秒 才算通。
0 帧时按下面的顺序排查，不要瞎改代码。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ld2410 import Decoder, STATE_NAMES        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=256000)
    ap.add_argument("--seconds", type=float, default=0, help="0 表示一直跑")
    ap.add_argument("--dump", default="", help="把原始字节写入文件")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        print("缺少 pyserial： pip install pyserial")
        return 2

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.5)
    except Exception as e:
        print("打开 %s 失败：%s" % (args.port, e))
        print(_hint())
        return 2

    dec = Decoder()
    frames = 0
    t0 = time.time()
    last_report = t0
    dump = open(args.dump, "wb") if args.dump else None

    print("监听 %s @ %d ...  Ctrl-C 结束" % (args.port, args.baud))
    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                if dump:
                    dump.write(chunk)
                for f in dec.feed(chunk):
                    frames += 1
                    print("状态=%-7s 运动距离=%4dcm 静止距离=%4dcm 静止能量=%3d"
                          % (STATE_NAMES.get(f["state"], "?"), f["move_dist"],
                             f["still_dist"], f["still_energy"]))
            now = time.time()
            if now - last_report >= 5:
                fps = frames / max(now - t0, 1e-6)
                print("--- 帧率 %.1f 帧/秒，坏帧 %d ---" % (fps, dec.bad))
                if frames == 0:
                    print(_hint())
                    return 3
                last_report = now
            if args.seconds and now - t0 >= args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if dump:
            dump.close()
        ser.close()
    return 0


def _hint():
    return "\n".join([
        "",
        "0 帧时按这个顺序查（别改代码）：",
        "  1. 接线：雷达 TX -> GPIO15(Pin10)，雷达 RX -> GPIO14(Pin8)，是交叉的",
        "  2. 供电：VCC 必须 5V（Pin2/4），不是 3.3V；电流 >200mA",
        "  3. 共地：雷达 GND 和树莓派 GND 必须连通",
        "  4. 设备名：Pi5 上是 /dev/ttyAMA0，不是 ttyS0，也不是 serial0",
        "  5. config.txt 只有 dtparam=uart0=on，不能有 uart0_console（那会变登录控制台）",
        "  6. 波特率：256000 8N1。先用 --dump 存原始字节，看有没有 F4F3F2F1",
        "",
    ])


if __name__ == "__main__":
    sys.exit(main())
