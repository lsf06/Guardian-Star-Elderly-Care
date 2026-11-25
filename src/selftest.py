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

# ---- 官方文档原文帧（基准，不可改） ----------------------------------------
# 下面两帧逐字节抄自海凌科《LD2410C 串口通信协议 V1.09》2.3 节「上报数据实例」。
# 它们的价值在于**不是我们自己造的**：任何偏移写错，这两帧立刻报错。
# 教训：上一版工程帧测试用的是自己打包的帧，打包和解析错在同一处，
#       所以自检一直是 PASS，而真实雷达的工程模式数据全错。
DOC_BASIC = bytes.fromhex(
    "F4F3F2F1" "0D00"
    "02AA0251000000003B0000"      # 类型/头/状态0x02静止/运动距0x0051/…/探测距
    "5500" "F8F7F6F5")

DOC_ENG = bytes.fromhex(
    "F4F3F2F1" "2300"
    "01AA031E003C00003900000808"
    "3C2205030304030605"          # 9 个运动门
    "000039101306060804"          # 9 个静止门
    "6001"                        # 光敏 0x60 / OUT 0x01
    "5500" "F8F7F6F5")

DOC_ENG_STATE = 3                 # 0x03 运动&静止
DOC_ENG_MOTION = [0x3C, 0x22, 0x05, 0x03, 0x03, 0x04, 0x03, 0x06, 0x05]
DOC_ENG_STATIC = [0x00, 0x00, 0x39, 0x10, 0x13, 0x06, 0x06, 0x08, 0x04]
DOC_ENG_LIGHT = 0x60
DOC_ENG_OUT = 0x01

# 构造器回环用的自造帧（仅作辅助，不能当协议正确性的证据）
ENG_MOTION = [0, 5, 12, 44, 88, 30, 3, 0, 0]
ENG_STATIC = [0, 8, 20, 61, 95, 41, 6, 0, 0]
RAW_ENG = bytes(
    [0xF4, 0xF3, 0xF2, 0xF1, 0x23, 0x00, 0x01, 0xAA,
     0x02, 0x96, 0x00, 0x00, 0x96, 0x00, 48, 0x96, 0x00,
     0x08, 0x08]
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

    print("\n官方文档原文帧 · 基本模式（V1.09 §2.3）：")
    got_doc = Decoder().feed(DOC_BASIC)
    ok &= check("解出 1 帧", len(got_doc) == 1, "解出 %d 帧" % len(got_doc))
    if got_doc:
        gb = got_doc[0]
        ok &= check("状态 = 2 (静止)", gb["state"] == 2, repr(gb["state"]))
        ok &= check("运动距离 = 81cm", gb["move_dist"] == 0x51, repr(gb["move_dist"]))
        ok &= check("静止能量 = 59", gb["still_energy"] == 0x3B, repr(gb["still_energy"]))

    print("\n官方文档原文帧 · 工程模式（V1.09 §2.3）：")
    got_eng = Decoder().feed(DOC_ENG)
    ok &= check("解出 1 帧", len(got_eng) == 1, "解出 %d 帧" % len(got_eng))
    if got_eng:
        de = got_eng[0]
        ok &= check("类型 = 1 (工程模式)", de["type"] == 1, repr(de["type"]))
        ok &= check("状态 = 3 (运动&静止)", de["state"] == DOC_ENG_STATE, repr(de["state"]))
        ok &= check("运动距离 = 30cm", de["move_dist"] == 0x1E, repr(de["move_dist"]))
        ok &= check("运动能量 = 60", de["move_energy"] == 0x3C, repr(de["move_energy"]))
        ok &= check("静止能量 = 57", de["still_energy"] == 0x39, repr(de["still_energy"]))
        ok &= check("9 个运动门能量逐字节一致", de["gates_motion"] == DOC_ENG_MOTION,
                    "得到 %r" % (de.get("gates_motion"),))
        ok &= check("9 个静止门能量逐字节一致", de["gates_static"] == DOC_ENG_STATIC,
                    "得到 %r" % (de.get("gates_static"),))
        ok &= check("光敏 = 96", de["light"] == DOC_ENG_LIGHT, repr(de.get("light")))
        ok &= check("OUT = 1 (有人)", de["out"] == DOC_ENG_OUT, repr(de.get("out")))

    print("\n构造器回环（仅作辅助检查）：")
    f = Decoder().feed(build_frame(state=0, still_dist=88, still_energy=13))
    ok &= check("无人帧状态 = 0", f and f[0]["state"] == 0, repr(f))

    print("\n自检: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
