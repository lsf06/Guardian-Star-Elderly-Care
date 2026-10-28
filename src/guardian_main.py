#!/usr/bin/env python3
"""硬件入口：串口 + GPIO + 语音 + 推送。

  python src/guardian_main.py --port /dev/ttyAMA0 --pin-door 18 --pin-button 17
  python src/guardian_main.py --port /dev/ttyAMA0 --chat-mode voice

安全路径（问候 / 消解 / 升级）只依赖本地：串口 + GPIO + 本地 WAV。
网络只影响「陪聊」，不影响守护。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ld2410 import Decoder                 # noqa: E402
from guardian import Config, Guardian      # noqa: E402
import voice                               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=256000)
    ap.add_argument("--pin-door", type=int, default=18)
    ap.add_argument("--pin-button", type=int, default=17)
    ap.add_argument("--door-open-level", type=int, default=1, choices=[0, 1],
                    help="开门时 DO 的电平。用 test_door.py 实测后再设，不要凭猜")
    ap.add_argument("--silence", type=float, default=90.0)
    ap.add_argument("--chat-mode", choices=["off", "text", "voice"], default="text")
    ap.add_argument("--no-gpio", action="store_true", help="无 GPIO 时只跑雷达")
    args = ap.parse_args()

    import serial
    ser = serial.Serial(args.port, args.baud, timeout=0.2)

    door = button = None
    pressed = {"flag": False}
    if not args.no_gpio:
        from gpiozero import Button   # Pi5 必须用 gpiozero；RPi.GPIO 在 Pi5 上会直接崩
        door = Button(args.pin_door, pull_up=None, active_state=None, bounce_time=0.2)
        button = Button(args.pin_button, pull_up=True, bounce_time=0.05)

        def _on_press():
            pressed["flag"] = True
        button.when_pressed = _on_press

    cfg = Config(silence=args.silence)
    g = Guardian(cfg, t0=time.time())
    dec = Decoder()
    last_state = 0

    print("启动。silence=%.0fs，门磁 Pin%d，按键 Pin%d" % (cfg.silence, args.pin_door, args.pin_button))
    try:
        while True:
            now = time.time()
            chunk = ser.read(256)
            frames = dec.feed(chunk) if chunk else []

            door_open = False
            if door is not None:
                level = 1 if door.is_active else 0
                door_open = (level == args.door_open_level)

            for f in frames:
                last_state = f["state"]

            hit = pressed["flag"]
            pressed["flag"] = False

            events = g.update(now, seen=(last_state != 0), door_open=door_open,
                              pressed=hit, frame_ok=bool(frames))

            for kind, text in events:
                if kind == "ask":
                    voice.speak(cfg.ask_text, "ask")
                elif kind == "resolved":
                    voice.speak(cfg.resolved_text, "resolved")
                elif kind == "escalate":
                    voice.push_family(cfg.push_text)
                elif kind == "fault":
                    voice.speak("我这边的雷达好像没连上，请看一下线。", "fault")
                elif kind == "startup":
                    print("[提示] " + text)
                elif kind == "away":
                    print("[状态] " + text)
                elif kind == "chat":
                    do_chat(args)
                else:
                    print("[%s] %s" % (kind, text))

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n退出。统计：%r" % (g.counts,))
    finally:
        ser.close()


def do_chat(args):
    """陪聊。失败绝不影响守护。"""
    if args.chat_mode == "off":
        return
    if args.chat_mode == "text":
        try:
            q = input("（对话）您说：").strip()
        except (EOFError, KeyboardInterrupt):
            return
    else:
        q = record_once()
        if not q:
            return
    if not q:
        return
    ans = voice.chat(q)
    voice.speak(ans)


def record_once(seconds=5):
    """录一段并识别。离线识别需要可选依赖，没装就明确告诉用户，不要假装能用。"""
    import subprocess
    import tempfile

    wav = os.path.join(tempfile.gettempdir(), "guardian_stt.wav")
    try:
        subprocess.run(["arecord", "-q", "-d", str(seconds), "-f", "S16_LE",
                        "-r", "16000", "-c", "1", wav], check=True, timeout=seconds + 5)
    except Exception as e:
        print("[录音失败] %s（确认已接 USB 麦克风，且安装 alsa-utils）" % e)
        return ""

    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        print("[提示] 未安装离线语音识别。二选一：")
        print("       pip install sherpa-onnx  + 下载中文模型（离线，推荐）")
        print("       或接入云端 ASR（需要联网，注意隐私）")
        print("       当前可用 --chat-mode text 先用键盘验证链路。")
        return ""
    return _sherpa_transcribe(wav)


def _sherpa_transcribe(wav):
    """占位：sherpa-onnx 的模型路径按你的下载位置填写。"""
    print("[提示] 请在此处填入 sherpa-onnx 模型路径后启用离线识别。")
    return ""


if __name__ == "__main__":
    main()
