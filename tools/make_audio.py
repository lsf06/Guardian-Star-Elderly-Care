#!/usr/bin/env python3
"""一次性生成安全语音，用于快递到货前先跑通。

  python tools/make_audio.py

需要 edge-tts，且需要联网。生成的是机器音，够用来验证链路，
但**答辩前请换成真人录音**（见 audio/README.md）。
这个脚本只在准备阶段跑一次；运行时不依赖它——设备播的是本地的 WAV。

注意：它会**覆盖 audio/ 下的同名文件**。真人录音录好之后就不要再跑了。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_kit import KITS, convert   # noqa: E402

# 文案以 audio_kit.KITS 为准，避免两处不一致；只有 SOS 单独写，
# 因为 TTS 会把「120」念成「一百二十」，紧急时刻要念「一二零」。
TEXTS = {k: t for k, _f, t, _l, _h in KITS}
TEXTS["sos"] = "紧急求助！请帮帮这位老人，请帮忙拨打一二零，或者联系家属。"

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio")


async def main():
    try:
        import edge_tts
    except ImportError:
        print("没有安装 edge-tts。先跑：pip install edge-tts")
        print("或者跳过这一步，直接手机录音放进 audio/。")
        return 1

    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for key, text in TEXTS.items():
        mp3 = os.path.join(OUT, key + ".mp3")
        try:
            await edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural").save(mp3)
        except Exception as e:
            print("  %-10s 合成失败：%s" % (key, e))
            continue
        rc = convert(mp3, key)          # 转 16k 单声道 WAV，成功即删 mp3
        if rc == 0:
            os.remove(mp3)
            ok += 1
        else:
            print("  %-10s 留在 %s，未转成 WAV" % (key, os.path.basename(mp3)))

    print()
    print("生成 %d/%d 段。验证：python tools/audio_kit.py" % (ok, len(TEXTS)))
    print("全部 OK 就说明文件本身没问题；能不能出声要到树莓派上才知道")
    print("（电脑上没有 aplay，用 voice.speak 验证会假报 missing）。")
    return 0 if ok == len(TEXTS) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
