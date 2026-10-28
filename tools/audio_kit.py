#!/usr/bin/env python3
"""录音体检 + 转码。检查只依赖标准库；转码二选一（系统 ffmpeg 或 pip 的 av）。

为什么需要它：
  audio/README.md 里的 `voice.speak(...)` 验证命令在**电脑上一定返回 missing**，
  因为播放依赖 aplay / ffplay，Windows 上没有。用这个脚本验，不会误判。

用法：
  python tools/audio_kit.py                       # 体检 audio/ 下的六个文件
  python tools/audio_kit.py 我的录音.m4a ask      # 转成 audio/ask.wav（16k 单声道）
  python tools/audio_kit.py 我的录音.m4a ask 2.5  # 顺便剪掉开头 2.5 秒
"""
import array
import os
import shutil
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.environ.get("GUARDIAN_AUDIO_DIR") or os.path.join(ROOT, "audio")

# 键 -> (文件名, 内容, 最短秒, 最长秒)
KITS = [
    ("ask",       "ask.wav",       "奶奶，有一阵子没看到您了，您还好吗？", 2.0, 12.0),
    ("ask_again", "ask_again.wav", "我有点担心，您按一下手边的键好吗？",   1.5, 10.0),
    ("resolved",  "resolved.wav",  "好的，您没事就好。",                 0.8, 8.0),
    ("fault",     "fault.wav",     "设备好像有点问题，我让人来看看。",    1.5, 10.0),
    ("away",      "away.wav",      "出门了呀，那我不打扰了。",            0.8, 8.0),
    ("sos",       "sos.wav",       "紧急求助！请帮忙拨打 120 或联系家属！", 1.5, 12.0),
]

# 可选项：录了就用，没录会自动退回 ask.wav。
# 但不录它，每日点名听起来就像「有一阵子没看到您了」——早上九点说这句很奇怪。
OPTIONAL = [
    ("checkin",   "checkin.wav",   "奶奶，我来看看您。您拍一下手边的键，我就放心了。", 2.0, 12.0),
]


def probe(path):
    """返回 (ok, 描述, 详情 dict)。只读 WAV 头，不需要解码库。"""
    if not os.path.exists(path):
        return False, "缺失", {}
    with open(path, "rb") as f:
        head = f.read(12)
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return False, "不是 WAV（改后缀不算转换）", {}
    try:
        with wave.open(path, "rb") as w:
            ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
    except Exception as e:
        return False, "WAV 头损坏：%s" % e, {}

    dur = n / float(rate or 1)
    peak = rms = 0
    if sw == 2 and raw:
        a = array.array("h")
        a.frombytes(raw[: len(raw) - len(raw) % 2])
        if sys.byteorder == "big":
            a.byteswap()
        peak = max((abs(x) for x in a), default=0)
        if a:
            rms = int((sum(x * x for x in a) / len(a)) ** 0.5)
    return True, "可读", {"ch": ch, "sw": sw, "rate": rate, "dur": dur,
                          "peak": peak, "rms": rms}


def check():
    print("录音体检（只检查文件本身，不试播）\n")
    print("文件               状态  采样率  声道   时长   问题")
    print("-" * 80)
    bad = 0
    for group, optional in ((KITS, False), (OPTIONAL, True)):
        for key, fn, text, lo, hi in group:
            path = os.path.join(AUDIO, fn)
            ok, msg, d = probe(path)
            issues = []
            if not ok:
                issues.append(msg)
            else:
                if d["rate"] != 16000:
                    issues.append("采样率 %d（建议 16000）" % d["rate"])
                if d["ch"] != 1:
                    issues.append("%d 声道（建议单声道）" % d["ch"])
                if d["sw"] != 2:
                    issues.append("%d 字节/样本（建议 16 bit）" % d["sw"])
                if not (lo <= d["dur"] <= hi):
                    issues.append("时长 %.1fs 超出 %.1f–%.1fs" % (d["dur"], lo, hi))
                if d["sw"] == 2:
                    if d["peak"] == 0:
                        issues.append("整段静音")
                    elif d["peak"] >= 32000:
                        issues.append("削波（录爆了，站远一点）")
                    elif d["peak"] < 1200:
                        issues.append("音量过小（峰值 %d，靠近手机或大声点）" % d["peak"])
            if issues:
                if optional and issues == [msg] and msg == "缺失":
                    # 可选项没录不算不合格，运行时会自动退回 ask.wav
                    print("%-18s %-5s %-7s %-5s %-6s %s" % (
                        fn, "缺(可选)", "-", "-", "-", "未录，点名将用 ask.wav 代替"))
                    continue
                bad += 1
            print("%-18s %-5s %-7s %-5s %-6s %s" % (
                fn, "OK" if not issues else "!!",
                d.get("rate", "-") if ok else "-",
                d.get("ch", "-") if ok else "-",
                ("%.1fs" % d["dur"]) if ok else "-",
                "；".join(issues) if issues else text[:16] + "…"))
    print("-" * 78)
    if bad == 0:
        print("%d 个必需文件全部合格。拷到树莓派 audio/ 下，设备就能出声。" % len(KITS))
    else:
        print("有 %d 个文件需要处理。转换：python tools/audio_kit.py 你的录音.m4a <键名>" % bad)
        print("键名：%s" % " / ".join([k for k, _f, _t, _l, _h in KITS]
                                      + ["%s(可选)" % k for k, _f, _t, _l, _h in OPTIONAL]))
    return 0 if bad == 0 else 1


def convert(src, key, trim=None):
    names = {k: f for k, f, _t, _l, _h in KITS}
    names.update({k: f for k, f, _t, _l, _h in OPTIONAL})
    if key not in names:
        print("键名只能是：%s" % " / ".join(names))
        return 2
    if not os.path.exists(src):
        print("找不到源文件：%s" % src)
        return 2
    out = os.path.join(AUDIO, names[key])
    os.makedirs(AUDIO, exist_ok=True)

    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        if trim:
            cmd += ["-ss", str(trim)]
        cmd += ["-i", src, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                "-map_metadata", "-1", out]
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print("ffmpeg 转换失败，退出码 %d" % r.returncode)
            return 1
    elif _convert_with_av(src, out, trim):
        pass
    else:
        print("没有可用的转码器。二选一：")
        print("  1) 装 ffmpeg（推荐）：winget install Gyan.FFmpeg")
        print("  2) 纯 Python：pip install av   然后重跑本命令")
        return 1

    ok, msg, d = probe(out)
    if ok:
        print("已生成 %s（%.1fs, %d Hz, %d 声道）" % (names[key], d["dur"], d["rate"], d["ch"]))
    else:
        print("生成了但读不出来：%s" % msg)
        return 1
    return 0


def _convert_with_av(src, out, trim):
    """PyAV 自带 ffmpeg 二进制，不需要系统安装。"""
    try:
        import av
        from av.audio.resampler import AudioResampler
    except ImportError:
        return False
    with av.open(src) as container:
        stream = container.streams.audio[0]
        res = AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        for frame in container.decode(stream):
            if trim and frame.time is not None and frame.time < float(trim):
                continue
            for f in res.resample(frame):
                chunks.append(bytes(f.planes[0]))
        for f in res.resample(None):
            chunks.append(bytes(f.planes[0]))
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(chunks))
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(check())
    if len(a) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(convert(a[0], a[1], a[2] if len(a) > 2 else None))
