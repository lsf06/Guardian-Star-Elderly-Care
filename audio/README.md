# 语音素材

这个目录里必须放**六个** WAV，否则设备关键时候**一句都不会出声**。

`src/voice.py` 的安全路径是 `strict=True`：本地文件缺失时它不会偷偷联网合成，
只会打印一行 `[!!] 安全语音缺失`。这是故意的——用云 TTS 播报安全提示，
等于把「老人有没有被问到」交给网络，而断网正是你写在边界里的失效条件。

## 要录的六句

| 文件名 | 内容 | 什么时候播 | 必需 |
|---|---|---|---|
| `ask.wav` | 奶奶，有一阵子没看到您了，您还好吗？ | 静默超阈值，第一次问候 | 是 |
| `ask_again.wav` | 我有点担心，您按一下手边的键好吗？ | 二次问候 | 是 |
| `resolved.wav` | 好的，您没事就好。 | 老人按键消解 | 是 |
| `fault.wav` | 设备好像有点问题，我让人来看看。 | 心跳超时 / 雷达断了 | 是 |
| `sos.wav` | 紧急求助！请帮忙拨打 120 或联系家属！ | 按下红键（`--pin-sos`） | **是** |
| `away.wav` | 出门了呀，那我不打扰了。 | 门磁判定离家 | 建议 |

> `sos.wav` 最容易漏，因为它不在「问候」这条线上。但**答辩现场最可能被按的就是红键**——
> 一按下去只有一行 `[!!] 安全语音缺失`，全场都听见了。别让它成为你唯一没录的那句。

## 怎么录

1. 手机自带录音机，安静房间，离嘴 20 cm，**语速比平时慢三分之一**。
   `sos.wav` 例外：要快、要大、要喊出来，那是紧急时刻。
2. 用 `tools/audio_kit.py` 转成 16 kHz 单声道 16 bit PCM：

```bash
python tools/audio_kit.py 我的录音.m4a ask
python tools/audio_kit.py 我的录音.m4a sos
```

不依赖系统装了什么：有 `ffmpeg` 就用 ffmpeg；没有就自动用 `pip install av` 里的解码器。
两个都没有时，它会告诉你装哪个，不会假装转成功。

> 手机录音一般是 `.m4a`，**直接改后缀名成 `.wav` 不是转换**，`aplay` 会报错。
> 体检脚本会明确把它认出来（「不是 WAV（改后缀不算转换）」）。

## 验证（这一步别用 voice.speak）

```bash
python tools/audio_kit.py
```

它只读 WAV 头，不需要声卡，**在 Windows / Mac 上也能跑**。会逐项检查：是否存在、
是不是真 WAV、采样率、声道、位深、时长、音量、是否削波，并给出要改的那一句。

> ⚠️ 不要用 `voice.speak('x','ask',strict=True)` 在电脑上验证。
> 它靠 `aplay` / `ffplay` 出声，Windows 上没有这两个命令，
> **录音完全正确也会返回 `missing`**。你会以为是自己录错了，白折腾一晚。
> 那个命令只在树莓派上（`sudo apt install alsa-utils` 之后）才有意义。

## 拷到树莓派之后

```bash
sudo apt install alsa-utils      # 提供 aplay
python tools/audio_kit.py        # 再体检一次，确认传输没坏
python -c "import sys;sys.path.insert(0,'src');import voice;print(voice.speak('x','ask',strict=True))"
```

打印 `local` = 真的播出来了。打印 `missing` = 文件没拷进去，或名字大小写不对。

## 为什么不用 TTS

树莓派上的 espeak 是机械音，老人听不清；在线 TTS 断网就哑。
真人录音零延迟、断网可用，而且——这是唯一能让老人觉得「这台机器在跟我说话」而不是「在播报」的方式。

## 先跑通再换真人

快递还没到、想先看效果，可以用一次性生成：

```bash
pip install edge-tts
python tools/make_audio.py
```

它会把五句合成到本目录。**能出声就够了，但答辩前请换成真人录音**：
机器音会让「有温度的问候」这个卖点当场失效。

> `make_audio.py` 会**覆盖同名文件**。录完真人语音之后就别再跑它了，
> 跑之前先 `git status` 看一眼——真人的六句是你这个项目里最不可替代的资产。
