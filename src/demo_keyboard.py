#!/usr/bin/env python3
"""答辩现场演示：键盘模拟雷达/门磁，跑的是**真状态机**。

  python src/demo_keyboard.py                 # 接真按键（绿 17 / 红 27），默认演示节奏
  python src/demo_keyboard.py --no-gpio       # 只有键盘，没有按键
  python src/demo_keyboard.py --no-audio      # 不出声，只打印（电脑上排练用）

为什么不用一段独立的 demo.py：
  那类脚本通常自己写一套 if/else（3 秒升级、门磁一票否决），
  和仓库里真正的状态机对不上。评委问一句「你代码里是 90 秒，演示怎么 3 秒」
  就答不圆。这里的每个动作都喂给 Guardian.update()，只是把时间常数按比例缩小，
  所以现场看到的问候、补问、升级、消解顺序，和真机完全同一条路径。

按键：
  1  雷达看不见人      2  雷达又看见人
  3  开门              4  关门
  5  绿键（=拍物理键）  6  红键 SOS
  7  立刻触发一次点名   c  说一句话（陪聊）
  f  模拟雷达断流       s  打印当前状态     q  退出
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardian import Config, Guardian      # noqa: E402
import voice                               # noqa: E402

BANNER = """
=========================================================
  守护星 · 现场演示（键盘模拟传感器，逻辑是真的）
---------------------------------------------------------
  1 人消失   2 人出现   3 开门   4 关门
  5 绿键     6 红键SOS  7 点名   c 聊天   s 状态   q 退出
=========================================================
"""


def parse_args():
    ap = argparse.ArgumentParser()
    # 演示节奏：产品默认 90 / 30 / 15 / 10 秒，现场站 90 秒没人看。
    # 缩小的是**时间**，不是逻辑：顺序仍是 问候 -> 补问 -> 升级。
    ap.add_argument("--silence", type=float, default=12.0, help="演示用静默阈值（产品 90）")
    ap.add_argument("--answer-window", type=float, default=8.0, help="演示用应答窗（产品 30）")
    ap.add_argument("--second-ask", type=float, default=4.0, help="演示用补问间隔（产品 15）")
    ap.add_argument("--away", type=float, default=4.0, help="演示用离家确认（产品 10）")
    ap.add_argument("--quiet", type=float, default=5.0, help="消解后安静期（产品 600）")
    ap.add_argument("--pin-button", type=int, default=17)
    ap.add_argument("--pin-sos", type=int, default=27)
    ap.add_argument("--no-gpio", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--chat-mode", choices=["off", "text"], default="text")
    return ap.parse_args()


class Sim:
    """键盘与物理键的共同入口：只改标志位，判定全部交给 Guardian。"""

    def __init__(self, args):
        self.args = args
        self.seen = False
        self.door_open = False
        self.frame_ok = True
        self.pressed = False
        self.sos = False
        self.chat_text = None
        self.tod_queue = []          # 用于「立刻点名」：连喂两个 now_tod
        self.running = True
        self.lock = threading.Lock()

    # -- 键盘线程 ------------------------------------------------------
    def listen(self):
        for line in sys.stdin:
            cmd = line.strip()
            if not cmd:
                continue
            with self.lock:
                if cmd == "1":
                    self.seen = False
                    print("  [雷达] 看不见人了")
                elif cmd == "2":
                    self.seen = True
                    print("  [雷达] 又看见人了")
                elif cmd == "3":
                    self.door_open = True
                    self.seen = False
                    print("  [门磁] 门开了")
                elif cmd == "4":
                    self.door_open = False
                    print("  [门磁] 门关了")
                elif cmd == "5":
                    self.pressed = True
                    print("  [按键] 绿键")
                elif cmd == "6":
                    self.sos = True
                    print("  [按键] 红键 SOS")
                elif cmd == "7":
                    # 先喂 9:00 建立 prev，下一秒喂 9:00:01 才算「跨过」
                    self.tod_queue = [9 * 3600, 9 * 3600 + 1]
                    print("  [时钟] 跳到 09:00，触发点名")
                elif cmd == "f":
                    self.frame_ok = not self.frame_ok
                    print("  [雷达] 断流=%s" % (not self.frame_ok))
                elif cmd.startswith("c"):
                    # 直接写成 "c我今天心里有点闷"，不要在这里再调 input()：
                    # 同一个线程已经在遍历 stdin，嵌套读会把后面的指令吞掉。
                    self.chat_text = cmd[1:].strip()
                    if not self.chat_text:
                        print("  用法：c我今天心里有点闷")
                elif cmd == "s":
                    print("  [状态] seen=%s door=%s frames=%s"
                          % (self.seen, self.door_open, self.frame_ok))
                elif cmd in ("q", "quit", "exit"):
                    self.running = False
                    return
                else:
                    print("  ? 未知指令：%s" % cmd)


def make_buttons(args, sim):
    if args.no_gpio:
        return None
    try:
        from gpiozero import Button
    except Exception as e:
        print("[提示] 没有 gpiozero（%s），改用纯键盘：1/2/3/4/5/6" % e)
        return None
    try:
        green = Button(args.pin_button, pull_up=True, bounce_time=0.05)
        red = Button(args.pin_sos, pull_up=True, bounce_time=0.05)

        def on_green():
            with sim.lock:
                sim.pressed = True

        def on_red():
            with sim.lock:
                sim.sos = True

        green.when_pressed = on_green
        red.when_pressed = on_red
        print("物理键已就绪：绿键 GPIO%d / 红键 GPIO%d" % (args.pin_button, args.pin_sos))
        return green, red
    except Exception as e:
        print("[提示] 按键初始化失败（%s），改用键盘 5/6" % e)
        return None


def say(args, text, key=None):
    if args.no_audio:
        print("  [播报] %s" % text)
        return 0.0
    dur = voice.phrase_seconds(key) if key else 0.0
    voice.speak(text, key=key, strict=bool(key))
    return dur


def announce(args, g, text, key):
    """和 guardian_main._announce 同一套时序：播完再冻结一小段余振。"""
    dur = say(args, text, key) or g.cfg.speech_freeze
    g.speaking_for(time.time(), min(max(dur * 0.25, 0.3), 1.5))


def main():
    args = parse_args()
    cfg = Config(
        silence=args.silence,
        answer_window=args.answer_window,
        second_ask_after=args.second_ask,
        away_confirm=args.away,
        after_resolve_quiet=args.quiet,
    )
    g = Guardian(cfg, t0=time.time())
    sim = Sim(args)
    make_buttons(args, sim)
    print(BANNER)
    print("演示参数：静默 %.0fs / 应答 %.0fs / 补问 %.0fs / 离家 %.0fs（产品 90/30/15/10）"
          % (cfg.silence, cfg.answer_window, cfg.second_ask_after, cfg.away_confirm))
    threading.Thread(target=sim.listen, daemon=True).start()

    try:
        while sim.running:
            now = time.time()
            with sim.lock:
                seen, door_open = sim.seen, sim.door_open
                frame_ok, pressed, sos = sim.frame_ok, sim.pressed, sim.sos
                sim.pressed = sim.sos = False
                chat_text = sim.chat_text
                sim.chat_text = None
                if sim.tod_queue:
                    now_tod = sim.tod_queue.pop(0)
                else:
                    lt = time.localtime(now)
                    now_tod = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec

            events = g.update(now, seen=seen, door_open=door_open, pressed=pressed,
                              frame_ok=frame_ok, now_tod=now_tod)

            if sos:
                print("\n>>> [SOS] 红键按下：直接推送，不看雷达、不看门磁")
                voice.push_family("老人按下了求助键，请立即致电确认；如无应答请拨打 120。")
                announce(args, g, "紧急求助！请帮帮这位老人，请帮忙拨打 120 或联系家属！", "sos")

            for kind, text in events:
                print("\n>>> [%s] %s" % (kind, text))
                if kind in ("ask", "ask_again", "checkin", "resolved", "fault"):
                    announce(args, g, text, kind)
                elif kind == "escalate":
                    voice.push_family(cfg.push_text)
                    print(">>> 已推送家属（未配 PUSHPLUS_TOKEN 时只打印，不假装送到）")
                elif kind == "checkin_ok":
                    voice.push_family(text)
                    print(">>> 已推送「今日平安」")
                elif kind == "chat":
                    # 按键只负责「唤醒」，说什么是下一条指令（c 加一句话）。
                    print(">>> 老人想说话了。输入 c 加一句，例如：c我今天心里有点闷")

            if chat_text and args.chat_mode == "text":
                print("\n>>> [陪聊] 老人在说：%s" % chat_text)
                ans = voice.chat(chat_text)
                say(args, ans)

            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n退出。统计：%r" % (g.counts,))


if __name__ == "__main__":
    main()
