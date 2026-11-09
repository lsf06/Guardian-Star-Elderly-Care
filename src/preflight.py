#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境体检：换机器 / 重装系统 / 硬件到货后，先跑这个。

和 src/selftest.py 分工不同，不要混：
  - src/selftest.py  协议层自检：用硬编码报文验证 LD2410 解析偏移对不对。不接硬件也能跑。
  - src/preflight.py 环境体检：包装没装、wav 全不全、串口通不通、声卡有没有。

设计原则：**缺硬件不算失败**。当前还没到货，缺串口/声卡只给 WARN，
退出码仍为 0，这样它可以放进任何自动化流程里而不误报。
只有「代码跑起来必需的东西」缺失（7 个 wav 不全、Python 版本太低）才 FAIL。

用法：
    python src/preflight.py            # 全部检查
    python src/preflight.py --quiet    # 只打印问题项
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 7 句语音是安全功能的一部分：缺一句，那条路径就哑了。这是硬要求。
AUDIO = ["ask", "ask_again", "away", "checkin", "fault", "resolved", "sos"]

# 只有接硬件才需要。没装不算错，因为现在本来就不接。
HARDWARE_ONLY = {"serial": "pyserial"}

# 只影响陪聊，不影响守护。
OPTIONAL = {
    "vosk": "离线语音识别（陪聊用）",
    "edge_tts": "在线语音合成（陪聊回复用）",
    "av": "录音转码（tools/audio_kit.py 用）",
}

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def add(level: str, name: str, detail: str = "") -> None:
    results.append((level, name, detail))


def check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 9):
        add(OK, f"Python {major}.{minor}")
    else:
        add(FAIL, f"Python {major}.{minor}", "需要 3.9 以上")


def check_packages() -> None:
    for mod, pip_name in HARDWARE_ONLY.items():
        if importlib.util.find_spec(mod):
            add(OK, f"依赖 {mod}")
        else:
            # 不接硬件时不需要，所以是 WARN 而不是 FAIL
            add(WARN, f"依赖 {mod}", f"未安装；接硬件前执行 pip install {pip_name}")

    for mod, why in OPTIONAL.items():
        if importlib.util.find_spec(mod):
            add(OK, f"可选 {mod}")
        else:
            add(WARN, f"可选 {mod}", f"未安装（{why}），不影响守护功能")


def check_audio() -> None:
    missing = [n for n in AUDIO if not (ROOT / "audio" / f"{n}.wav").is_file()]
    if missing:
        add(FAIL, "语音素材 7 句", "缺：" + ", ".join(f"{n}.wav" for n in missing))
        return
    add(OK, "语音素材 7 句")

    # 顺手看一眼采样率，16 kHz 单声道是播放链路的前提
    try:
        import wave

        bad = []
        for n in AUDIO:
            with wave.open(str(ROOT / "audio" / f"{n}.wav"), "rb") as wf:
                if wf.getframerate() != 16000 or wf.getnchannels() != 1:
                    bad.append(f"{n}.wav({wf.getframerate()}Hz/{wf.getnchannels()}ch)")
        if bad:
            add(WARN, "语音格式", "应为 16 kHz 单声道：" + ", ".join(bad))
        else:
            add(OK, "语音格式 16 kHz 单声道")
    except Exception as e:  # 读不了就算了，不影响主流程
        add(WARN, "语音格式", f"检查失败：{e}")


def check_model() -> None:
    """Vosk 模型是可选的，但装了就得能加载。默认目录可由环境变量覆盖。"""
    want = os.environ.get("GUARDIAN_VOSK_MODEL", "vosk-model-small-cn-0.15")
    p = ROOT / want
    if p.is_dir():
        add(OK, f"Vosk 模型 {want}")
    else:
        add(WARN, f"Vosk 模型 {want}", "未下载；只影响陪聊。见 requirements.txt 里的 wget 命令")


def check_serial() -> None:
    """Pi 5 上 GPIO14/15 要 dtparam=uart0=on 才会出现 /dev/ttyAMA0。

    注意 /dev/serial0 在 Pi 5 上指向的是 debug 排针（ttyAMA10），
    **不是** GPIO14/15。所以这里只认 ttyAMA0，不认 serial0。
    """
    if os.name == "nt":
        add(WARN, "雷达串口", "Windows 上无 /dev/ttyAMA0，这是正常的（仿真不接线）")
        return

    port = Path("/dev/ttyAMA0")
    if not port.exists():
        add(WARN, "雷达串口 /dev/ttyAMA0",
            "不存在。Pi 5 需在 config.txt 加 dtparam=uart0=on 并重启；"
            "若只有 /dev/ttyAMA10，那是 debug 排针，不是 GPIO14/15")
        return
    if not os.access(port, os.R_OK | os.W_OK):
        add(WARN, "雷达串口权限", "存在但不可读写；执行 sudo usermod -aG dialout $USER 后重新登录")
        return
    add(OK, "雷达串口 /dev/ttyAMA0")


def check_audio_device() -> None:
    """声卡只警告：没有声卡也能跑仿真，只是听不见。"""
    if os.name == "nt" or not shutil.which("aplay"):
        add(WARN, "音频输出", "无 aplay，判定为仿真环境（正常）")
        return
    try:
        r = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            add(OK, "音频输出")
        else:
            add(WARN, "音频输出", "未检测到声卡；Pi 5 无 3.5mm 孔，需 USB 音箱并配置 ~/.asoundrc")
    except Exception:
        add(WARN, "音频输出", "aplay 调用失败")


def check_key_files() -> None:
    need = ["index.html", "requirements.txt", "src/guardian.py", "src/guardian_main.py"]
    missing = [f for f in need if not (ROOT / f).is_file()]
    if missing:
        add(FAIL, "关键文件", "缺：" + ", ".join(missing) + "（是否在仓库根目录运行？）")
    else:
        add(OK, "关键文件")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只打印 WARN / FAIL")
    args = ap.parse_args()

    check_python()
    check_key_files()
    check_packages()
    check_audio()
    check_model()
    check_serial()
    check_audio_device()

    icon = {OK: "  PASS  ", WARN: "  WARN  ", FAIL: "  FAIL  "}
    shown = 0
    for level, name, detail in results:
        if args.quiet and level == OK:
            continue
        line = icon[level] + name
        if detail:
            line += "  -> " + detail
        print(line)
        shown += 1

    fails = sum(1 for lv, _, _ in results if lv == FAIL)
    warns = sum(1 for lv, _, _ in results if lv == WARN)
    total = len(results)

    print()
    if fails:
        print(f"环境体检: FAIL —— {fails} 项必须修，{warns} 项可忽略（共 {total} 项）")
        return 1
    if warns:
        print(f"环境体检: PASS（{warns} 项警告，均为「还没到货」这类正常缺失，共 {total} 项）")
    else:
        print(f"环境体检: PASS（{total} 项全通过）")
    return 0


if __name__ == "__main__":
    if not (ROOT / "src").is_dir():
        sys.exit("请在仓库根目录运行：python src/preflight.py")
    sys.exit(main())