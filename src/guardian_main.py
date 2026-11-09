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
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ld2410 import Decoder                 # noqa: E402
from guardian import Config, Guardian      # noqa: E402
import voice                               # noqa: E402

# 陪聊必须是旁路。它一旦阻塞主循环，雷达就不再被读取、状态机就不再推进，
# 而老人按下按键的那一刻，恰恰可能正是他需要被守护的时刻。
_chat_busy = {"flag": False}
_chat_lock = threading.Lock()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=256000)
    ap.add_argument("--pin-door", type=int, default=18)
    ap.add_argument("--pin-button", type=int, default=17)
    ap.add_argument("--pin-sos", type=int, default=None,
                    help="红色求助键。给了才启用；不接就不假装有")
    ap.add_argument("--door-open-level", type=int, default=1, choices=[0, 1],
                    help="开门时 DO 的电平。用 test_door.py 实测后再设，不要凭猜")
    ap.add_argument("--silence", type=float, default=90.0)
    ap.add_argument("--chat-mode", choices=["off", "text", "voice"], default="text")
    ap.add_argument("--no-gpio", action="store_true", help="无 GPIO 时只跑雷达")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        sys.exit("缺少 pyserial：pip3 install pyserial --break-system-packages")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except Exception as e:
        # 这里给出可执行的排查顺序，而不是把底层异常直接甩给用户。
        # 真机上「打不开串口」有 90% 是下面四条之一。
        print("打不开串口 %s（波特率 %d）：%s" % (args.port, args.baud, e))
        print("按顺序排查：")
        print("  1) ls -l /dev/ttyAMA0   —— 不存在说明没开串口")
        print("     Pi 5 需在 /boot/firmware/config.txt 加 dtparam=uart0=on 后重启")
        print("  2) 权限够不够：sudo usermod -aG dialout $USER  然后**重新登录**")
        print("  3) 是不是被控制台占了：ls -l /dev/ttyAMA0 应显示 root dialout，")
        print("     若显示 root tty，删掉 /boot/firmware/cmdline.txt 里的 console=serial0")
        print("  4) 别用 /dev/serial0 —— Pi 5 上它指向 ttyAMA10（debug 排针），不是 GPIO14/15")
        sys.exit(1)

    door = button = None
    pressed = {"flag": False}
    sos = {"flag": False}
    if not args.no_gpio:
        from gpiozero import Button   # Pi5 必须用 gpiozero；RPi.GPIO 在 Pi5 上会直接崩
        door = Button(args.pin_door, pull_up=True, bounce_time=0.2)
        button = Button(args.pin_button, pull_up=True, bounce_time=0.05)

        def _on_press():
            pressed["flag"] = True
        button.when_pressed = _on_press

        if args.pin_sos is not None:
            sos_btn = Button(args.pin_sos, pull_up=True, bounce_time=0.05)
            sos_btn.when_pressed = lambda: sos.__setitem__("flag", True)

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
            hit_sos = sos["flag"]
            sos["flag"] = False

            lt = time.localtime(now)
            now_tod = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
            events = g.update(now, seen=(last_state != 0), door_open=door_open,
                              pressed=hit, frame_ok=bool(frames), now_tod=now_tod)

            # SOS 优先级最高：不看雷达、不看门磁、不看状态机，按下就是按下
            if hit_sos:
                voice.push_family("老人按下了求助键，请立即致电确认；如无应答请拨打 120。")
                _announce(g, ser, "紧急求助！请帮帮这位老人，请帮忙拨打 120 或联系家属！", "sos")
                print("[SOS] 已触发")

            for kind, text in events:
                if kind == "ask":
                    _announce(g, ser, cfg.ask_text, "ask")
                elif kind == "checkin":
                    # 每日点名：雷达看得见人，但不知道他还能不能动。
                    # 这是设备唯一能覆盖「人在、但动不了」的手段。
                    _announce(g, ser, cfg.checkin_text, "checkin")
                elif kind == "ask_again":
                    _announce(g, ser, cfg.ask_text_again, "ask_again")
                elif kind == "resolved":
                    _announce(g, ser, cfg.resolved_text, "resolved")
                elif kind == "escalate":
                    voice.push_family(cfg.push_text)
                elif kind == "fault":
                    _announce(g, ser, "我这边的雷达好像没连上，请看一下线。", "fault")
                elif kind == "startup":
                    print("[提示] " + text)
                elif kind == "away":
                    print("[状态] " + text)
                elif kind == "chat":
                    spawn_chat(args)
                else:
                    print("[%s] %s" % (kind, text))

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n退出。统计：%r" % (g.counts,))
    finally:
        ser.close()


def _announce(g, ser, text, kind):
    """播一句，并让状态机在播完后的余振期内不采信「看到人」。

    机制要说清楚，否则修错了也看不出来：

    1) **aplay 是前台阻塞的**。播 8 秒，主循环就停 8 秒——不读串口、不调
       update。所以「播报期间状态机看到人」这件事本身不会发生。
    2) 危险在**播完之后那一瞬间**：这 8 秒里串口一直在收，OS 缓冲区积压
       几十帧，全是喇叭振动造成的假「看到人」。恢复后第一次 read 把它们
       一次性读进来 → 状态机判定「人回来了」→ 取消刚发起的静默事件 →
       老人没回应、家属也收不到推送。一次完全静默的漏报。

    两道防线，缺一不可：
      A. ser.reset_input_buffer()：把积压帧整段丢掉（主防线）。
      B. 从**播完那一刻**起再冻结一小段（余振窗），兜住恢复后头几帧
         仍可能读到的振动。起点必须是播完之后，不是播报之前 ——
         播报期间主循环本来就没在跑，那段冻结毫无作用，反而让
         speech_end 提前过期。这正是 18b1637 没修干净的原因：
         用播报前的 now 加音频时长，算出的终点恰好等于播完时刻，零余量。
    """
    dur = voice.phrase_seconds(kind) or g.cfg.speech_freeze
    voice.speak(text, kind, strict=True)      # 前台阻塞，直到播完
    t_done = time.time()

    # A) 丢掉播报期间的积压帧。不做这一步，下面的冻结基本白设。
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    # B) 余振窗：音频长度的 25%，限制在 0.3–1.5 秒。
    #    喇叭停止后振膜还要衰减一会儿，雷达在这几十到几百毫秒里仍可能读到振动。
    tail = min(max(dur * 0.25, 0.3), 1.5)
    g.speaking_for(t_done, tail)


def spawn_chat(args):
    """把陪聊丢到后台线程。主循环必须继续读雷达。

    之前这里直接同步调用 do_chat，一旦用了 --chat-mode text，
    input() 会把整个主循环卡死几十秒：雷达帧积压、状态机停摆、
    问候与升级全部失效。而老人按下按键的那一刻，
    恰恰是他最可能需要被守护的时刻。
    """
    if _chat_busy["flag"]:
        print("[聊天] 上一轮还没结束")
        return
    _chat_busy["flag"] = True
    threading.Thread(target=_chat_worker, args=(args,), daemon=True).start()


def _chat_worker(args):
    try:
        with _chat_lock:
            do_chat(args)
    except Exception as e:
        print("[聊天] 异常：%s" % e)
    finally:
        _chat_busy["flag"] = False


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

    # 麦克风设备名。~/.asoundrc 把默认输出指到 USB 音箱后，arecord 用 "default"
    # 会去打那张只能播的卡，录不到声音。所以允许显式指定：
    #   export GUARDIAN_MIC_DEV=plughw:2,0     （arecord -l 里查到的麦克风卡号）
    cmd = ["arecord", "-q", "-d", str(seconds), "-f", "S16_LE",
           "-r", "16000", "-c", "1"]
    dev = os.environ.get("GUARDIAN_MIC_DEV", "").strip()
    if dev:
        cmd += ["-D", dev]
    cmd.append(wav)
    try:
        subprocess.run(cmd, check=True, timeout=seconds + 5)
    except Exception as e:
        print("[录音失败] %s（确认已接 USB 麦克风，且安装 alsa-utils）" % e)
        print("      若 ~/.asoundrc 已把默认设备指到音箱，需另设麦克风：")
        print("      arecord -l 查到卡号后 export GUARDIAN_MIC_DEV=plughw:<卡号>,0")
        return ""

    # vosk 与 sherpa-onnx 二选一，装了哪个都能往下走。
    # 这里只做能力探测，真正的识别在 _sherpa_transcribe 里。
    try:
        import vosk  # noqa: F401
    except ImportError:
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            print("[提示] 未安装离线语音识别。二选一：")
            print("       pip install vosk --break-system-packages  + 下载中文小模型（推荐，轻）")
            print("       pip install sherpa-onnx  + 下载中文模型（离线，精度更高）")
            print("       当前可用 --chat-mode text 先用键盘验证链路。")
            return ""
    return _sherpa_transcribe(wav)


_VOSK_MODEL = None


def _sherpa_transcribe(wav):
    """离线语音识别（Vosk）。

    模型默认从 ./vosk-model-small-cn-0.15 读，可用 GUARDIAN_VOSK_MODEL 覆盖。
    只在第一次调用时加载（Pi 5 上约 1–2 秒），之后常驻，不会每次按绿键都卡一下。
    识别失败一律返回空字符串，绝不抛异常——陪聊坏了不能影响守护。
    """
    global _VOSK_MODEL
    try:
        import json
        import wave

        import vosk
    except ImportError:
        print("[提示] 未安装 vosk。pip install vosk --break-system-packages")
        return ""

    model_dir = os.environ.get("GUARDIAN_VOSK_MODEL", "vosk-model-small-cn-0.15")
    if not os.path.isdir(model_dir):
        print("[提示] 找不到 Vosk 模型目录：%s" % model_dir)
        print("       wget https://alphacephei.com/vosk/models/vosk-model-small-cn-0.15.zip")
        print("       unzip vosk-model-small-cn-0.15.zip")
        return ""

    try:
        if _VOSK_MODEL is None:
            print("[识别] 首次加载模型，约 1–2 秒…")
            _VOSK_MODEL = vosk.Model(model_dir)
        with wave.open(wav, "rb") as wf:
            rec = vosk.KaldiRecognizer(_VOSK_MODEL, wf.getframerate())
            parts = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    parts.append(json.loads(rec.Result()).get("text", ""))
            parts.append(json.loads(rec.FinalResult()).get("text", ""))
    except Exception as e:
        print("[识别失败] %s" % e)
        return ""

    out = "".join(parts).replace(" ", "")
    print("[识别] %s" % (out or "（没听清）"))
    return out


if __name__ == "__main__":
    main()
