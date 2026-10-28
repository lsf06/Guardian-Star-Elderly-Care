#!/usr/bin/env python3
"""一次性生成五段安全语音，用于快递到货前先跑通。

  python tools/make_audio.py

需要 edge-tts，且需要联网。生成的是机器音，够用来验证链路，
但**答辩前请换成真人录音**（见 audio/README.md）。
这个脚本只在准备阶段跑一次；运行时不依赖它——设备播的是本地的 WAV。
"""
import asyncio
import os
import sys

TEXTS = {
    "ask":       "奶奶，有一阵子没看到您了，您还好吗？",
    "ask_again": "您还好吗？拍拍这个按钮就行。",
    "resolved":  "好的，您没事就好。",
    "fault":     "我这边的雷达好像没连上，请看一下线。",
    "sos":       "紧急求助！请帮帮这位老人，请帮忙拨打一二零，或者联系家属。",
}

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio")


async def main():
    try:
        import edge_tts
    except ImportError:
        print("没有安装 edge-tts。先跑：pip install edge-tts")
        print("或者跳过这一步，直接手机录五段 WAV 放进 audio/。")
        return 1

    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for key, text in TEXTS.items():
        mp3 = os.path.join(OUT, key + ".mp3")
        wav = os.path.join(OUT, key + ".wav")
        try:
            await edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural").save(mp3)
        except Exception as e:
            print("  %-10s 合成失败：%s" % (key, e))
            continue
        # voice.py 播的是 .wav，这里顺手转好；没装 ffmpeg 就先留着 mp3
        rc = os.system('ffmpeg -y -loglevel quiet -i "%s" -ar 16000 -ac 1 '
                       '-c:a pcm_s16le "%s"' % (mp3, wav))
        if rc == 0 and os.path.exists(wav):
            os.remove(mp3)
            print("  %-10s -> %s.wav" % (key, key))
        else:
            print("  %-10s -> %s.mp3（没装 ffmpeg，voice.py 会用 ffplay 播）" % (key, key))
        ok += 1

    print()
    print("生成 %d/%d 段。验证：python -c \"import sys;sys.path.insert(0,'src');"
          "import voice;print(voice.speak('x','ask',strict=True))\"" % (ok, len(TEXTS)))
    print("打印 local 就说明设备能出声了。")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
