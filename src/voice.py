#!/usr/bin/env python3
"""语音层。安全播报永远不依赖网络。

三级降级：
  1. audio/*.wav   —— 手机录的真人语音，aplay 直接播。延迟最低，断网也能用。
  2. edge-tts      —— 需要联网，音质好，仅用于「陪聊」这类非安全场景。
  3. print         —— 什么都没有时，至少让日志里有记录。

铁律：问候、消解、升级这三句必须走第 1 级。
用云 TTS 播报安全提示，等于把「老人有没有被问到」交给网络。
"""
import os
import subprocess
import time

AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio")

# 键 -> 音频文件名。录制时对着手机念，存成 16kHz 单声道 WAV。
PHRASES = {
    "ask":        "ask.wav",         # 奶奶，有一阵子没看到您了，您还好吗？
    "ask_again":  "ask_again.wav",   # 您还好吗？拍拍这个按钮就行。
    "resolved":   "resolved.wav",    # 好的，您没事就好。
    "fault":      "fault.wav",       # 我这边的雷达好像没连上，请看一下线。
    "away":       "away.wav",        # 您要出门呀？路上慢点。
    "sos":        "sos.wav",         # 紧急求助！请帮忙拨打 120 或联系家属！
    "checkin":    "checkin.wav",     # 奶奶，我来看看您。您拍一下手边的键，我就放心了。
}

# 某一句还没录时的退路。点名用 ask.wav 顶上：内容不完全贴合，
# 但「有人在问」这件事必须发生 —— 不能因为少录一句就让点名变成哑巴。
FALLBACK = {"checkin": "ask"}


def phrase_seconds(key):
    """这句本地语音实际会播多久（秒）。缺失或不是 WAV 时返回 0。

    为什么需要它：喇叭的振动会被同一颗雷达当成微动。播报期间的「看到人」
    必须整段作废，否则设备会把自己说的话当成「人回来了」，把刚发起的事件取消掉。
    而冻结时长不能用一个拍出来的常数——六句录音 5~10 秒不等，差一倍。
    """
    if not key:
        return 0.0
    fn = PHRASES.get(key)
    alt = FALLBACK.get(key)
    for cand in (fn, PHRASES.get(alt) if alt else None):
        if not cand:
            continue
        path = os.path.join(AUDIO_DIR, cand)
        if not os.path.exists(path):
            continue
        try:
            import wave
            with wave.open(path, "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:
            continue
    return 0.0


def play_file(path):
    if not os.path.exists(path):
        return False
    # aplay 只吃 WAV；MP3 交给 ffplay。顺序反了会白跑一次失败。
    if path.lower().endswith(".mp3"):
        cmds = (["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                ["mpg123", "-q", path])
    else:
        cmds = (["aplay", "-q", path],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path])
    for cmd in cmds:
        try:
            subprocess.run(cmd, check=True, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


def speak(text, key=None, strict=False):
    """优先本地音频，其次在线合成，最后打印。返回实际使用的方式。

    strict=True 用于安全路径（问候 / 消解 / 故障 / SOS）：
    此时**绝不回退到联网 TTS**。理由是断网正好是你写在边界里的失效条件，
    而用云 TTS 播报安全提示，等于把「老人有没有被问到」交给网络。
    本地文件缺失时，用最响的方式报错并打印，让问题在调试期暴露，
    而不是在老人家里安静地不发生。
    """
    if key and key in PHRASES:
        if play_file(os.path.join(AUDIO_DIR, PHRASES[key])):
            return "local"
        alt = FALLBACK.get(key)
        if alt and play_file(os.path.join(AUDIO_DIR, PHRASES[alt])):
            print("[提示] audio/%s 缺失，本次用 %s 代替。" % (PHRASES[key], PHRASES[alt]))
            return "local"
        if strict:
            print("[!!] 安全语音缺失：audio/%s —— 这一句没有播出去。"
                  % PHRASES[key])
            print("     请录一段 16kHz 单声道 WAV 放进去。当前只打印，不出声：%s" % text)
            return "missing"
    try:
        import asyncio
        import edge_tts

        os.makedirs(AUDIO_DIR, exist_ok=True)
        out = os.path.join(AUDIO_DIR, "_cache.mp3")
        asyncio.run(edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural").save(out))
        if play_file(out):
            return "edge-tts"
    except Exception:
        pass
    print("[SPEAK] %s" % text)
    return "print"


def chat(text, timeout=20):
    """调用大模型。没有配 API Key 时返回一句兜底话，绝不抛异常。

    注意：这条路径属于「陪伴」，不属于「安全」。
    它挂了、断网了、限流了，设备的守护功能必须完全不受影响。
    """
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return "（未配置 DEEPSEEK_API_KEY）我在呢，您慢慢说。"

    import json
    import urllib.request

    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content":
             "你是一位耐心、语速慢、用词简单的陪伴助手，面对的是七八十岁的老人。"
             "每次回答不超过两句话，不超过 40 个字。不要用专业术语，不要用英文。"
             "如果对方提到身体不适、摔倒、疼痛、胸闷，立刻提醒他按红色求助键或让家人打 120。"},
            {"role": "user", "content": text},
        ],
        "temperature": 0.7,
        "max_tokens": 120,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("[CHAT] 调用失败：%s" % e)
        return "我这边有点听不清，您再说一遍好不好？"


def _push_channels():
    """按优先级列出已配置的通道。两条都配就都发——报警场景宁可重复一条。

    ① WECOM_WEBHOOK —— 企业微信群机器人。官方接口、完全免费、无日限额
       （每分钟 20 条）。家属用个人微信扫码绑定「微信插件」即可收，
       不需要装企业微信。**这是首选**。
    ② PUSHPLUS_TOKEN —— PushPlus 转微信服务号。免费版 200 条/天、
       同内容 1 小时最多 3 条。作为备选，或在只配了它时使用。

    两个环境变量都没有时，只打印。不假装送到。
    """
    chans = []
    hook = os.environ.get("WECOM_WEBHOOK", "").strip()
    if hook:
        chans.append(("wecom", hook))
    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if token:
        chans.append(("pushplus", token))
    return chans


def push_family(text, attempts=3, timeout=10):
    """推送给家属。按已配置的通道逐个发，任一成功即算送达。

    为什么不能只看 HTTP 200：PushPlus 在 token 过期、当日限额、内容被拦截时
    仍然回 200，业务码放在响应体的 `code` 里；企业微信同理，errcode 才是结论。
    只判状态码会把「没送到」记成「已送达」——而这条路径上的下一次调用，
    可能是老人按了红键。

    没配置任何通道就打印，并在文档里写明：此时本设备只有本地语音提醒。
    不要像某些方案那样，明明没有通知动作，却播报「已通知家属」。
    """
    chans = _push_channels()
    if not chans:
        print("[PUSH] %s" % text)
        return False

    errors = []
    for kind, key in chans:
        last = None
        for i in range(max(1, attempts)):
            try:
                if kind == "wecom":
                    _push_wecom(key, text, timeout)
                else:
                    _push_once(key, text, timeout)
                return True                 # 任一通道成功就算送达
            except Exception as e:
                last = e
                if i + 1 < max(1, attempts):
                    time.sleep(2 ** i)      # 1s, 2s
        errors.append("%s: %s" % (kind, last))

    _push_record_failure(text, "; ".join(errors))
    print("[PUSH] 全部通道失败（各重试 %d 次）：%s"
          % (max(1, attempts), "; ".join(errors)))
    return False


def _push_wecom(hook, text, timeout):
    """企业微信群机器人。返回体 errcode != 0 即失败。

    注意：webhook 的 key 等于群钥匙，泄露了谁都能往群里发消息。
    只从环境变量读，不写进仓库、不打印完整 URL。
    """
    import json
    import urllib.request

    body = json.dumps({
        "msgtype": "text",
        "text": {"content": "【守护星】%s" % text},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(hook, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError("HTTP %s" % r.status)
        raw = r.read().decode("utf-8", "replace")
    data = json.loads(raw)
    code = int(data.get("errcode", -1))
    if code != 0:
        raise RuntimeError("errcode %s：%s" % (code, data.get("errmsg")))


def _push_once(token, text, timeout):
    import json
    import urllib.request

    body = json.dumps({"token": token, "title": "居家关怀提醒",
                       "content": text}).encode("utf-8")
    req = urllib.request.Request("https://www.pushplus.plus/send", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError("HTTP %s" % r.status)
        raw = r.read().decode("utf-8", "replace")
    data = json.loads(raw)
    if int(data.get("code", -1)) != 200:
        raise RuntimeError("业务码 %s：%s" % (data.get("code"), data.get("msg")))


def _push_record_failure(text, err):
    """失败落盘，供人工补发与事后取证。写失败不能再抛，否则救不了人还崩程序。"""
    import json
    import time as _t

    try:
        path = os.path.join(os.path.dirname(AUDIO_DIR), "data", "_push_failed.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _t.strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "error": str(err),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

