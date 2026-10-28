#!/usr/bin/env python3
"""协议层自检：不接硬件也要能证明解析是对的。

关键原则：不要用「自己打包 → 自己解析」来验证协议。
那样只能证明代码自洽，偏移错了照样通过（这个项目踩过一次）。
这里全部使用硬编码的真实报文十六进制。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ld2410 import Decoder, build_frame, decode   # noqa: E402

# 一帧真实的基本模式报文（静止有人，距离 150cm，静止能量 48）
RAW_BASIC = bytes([
    0xF4, 0xF3, 0xF2, 0xF1, 0x0D, 0x00,
    0x02, 0xAA,
    0x02, 0x96, 0x00, 0x00, 0x96, 0x00, 48, 0x96, 0x00,
    0x55, 0x00,
    0xF8, 0xF7, 0xF6, 0xF5,
])

# 一帧工程模式报文：基本信息 + 9 运动门 + 9 静止门 + 光照 + OUT
ENG_MOTION = [0, 5, 12, 44, 88, 30, 3, 0, 0]
ENG_STATIC = [0, 8, 20, 61, 95, 41, 6, 0, 0]
RAW_ENG = bytes(
    [0xF4, 0xF3, 0xF2, 0xF1, 0x1F, 0x00, 0x01, 0xAA,
     0x02, 0x96, 0x00, 0x00, 0x96, 0x00, 48, 0x96, 0x00]
    + ENG_MOTION + ENG_STATIC + [7, 1]
    + [0xF8, 0xF7, 0xF6, 0xF5]
)


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + detail) if detail and not cond else ""))
    return cond


def main():
    ok = True
    print("基本帧字段：")
    d = decode(RAW_BASIC[6:19])
    ok &= check("状态 = 2 (静止)", d and d["state"] == 2, repr(d))
    ok &= check("静止距离 = 150cm", d and d["still_dist"] == 150, repr(d))
    ok &= check("静止能量 = 48", d and d["still_energy"] == 48, repr(d))
    ok &= check("运动距离 = 150cm", d and d["move_dist"] == 150, repr(d))

    print("\n流式解码：")
    dec = Decoder()
    got = []
    for i in range(0, len(RAW_BASIC), 7):          # 故意切成 7 字节碎片，模拟串口分包
        got += dec.feed(RAW_BASIC[i:i + 7])
    ok &= check("分包后仍解出 1 帧", len(got) == 1, "解出 %d 帧" % len(got))

    print("\n帧同步（前面塞垃圾字节）：")
    dec2 = Decoder()
    got2 = dec2.feed(b"\x00\x11\x22\x33\x44" + RAW_BASIC)
    ok &= check("跳过垃圾后解出 1 帧", len(got2) == 1, "解出 %d 帧，bad=%d" % (len(got2), dec2.bad))

    print("\n帧尾错误应被丢弃：")
    bad = RAW_BASIC[:-1] + b"\x00"
    got3 = Decoder().feed(bad)
    ok &= check("错误帧尾被丢弃", got3 == [], "解出 %r" % (got3,))

    print("\n工程模式帧：")
    de = decode(RAW_ENG[6:6 + 0x1F])
    ok &= check("解析出工程帧", de is not None and de["type"] == 1)
    if de:
        ok &= check("状态 = 2", de["state"] == 2, repr(de.get("state")))
        ok &= check("运动门能量一致", de["gates_motion"] == ENG_MOTION, repr(de.get("gates_motion")))
        ok &= check("静止门能量一致", de["gates_static"] == ENG_STATIC, repr(de.get("gates_static")))

    print("\n构造器回环（仅作辅助检查）：")
    f = Decoder().feed(build_frame(state=0, still_dist=88, still_energy=13))
    ok &= check("无人帧状态 = 0", f and f[0]["state"] == 0, repr(f))

    print("\n自检: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
