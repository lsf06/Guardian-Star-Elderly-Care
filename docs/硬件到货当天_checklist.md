# 硬件到货当天：会撞上什么，按什么顺序解决

> 写于 2026-11-09，硬件尚未到货。**这是从代码里逐行读出来的预判，不是实测记录。**
> 每条都标了「可能性」和「症状」，到货后按顺序验，遇到问题直接跳到对应条目。

---

## 一句话结论

**代码可以照用，但不能「不改就用」。** 我读完全部源码后修掉了两处硬伤，
这两处的共同点是：**仿真跑一万遍都发现不了，接上硬件当场就废**。

| # | 问题 | 严重度 | 状态 |
|---|---|---|---|
| 1 | `Button(pull_up=None, active_state=None)` 直接抛异常，程序起不来 | **致命** | 已修（`f5e9a46`） |
| 2 | 播报结束后串口积压帧把事件取消，**漏报** | **致命** | 已修（`f5e9a46`） |
| 3 | 串口设备名用错（`serial0` vs `ttyAMA0`） | 高 | 文档已纠正 |
| 4 | 声卡没配，全程无声但程序不报错 | 高 | 需要你现场配 |
| 5 | 门磁电平反相 | 中 | 用参数解决，不用改代码 |
| 6 | 雷达 TX/RX 接反 | 中 | 接线时注意 |
| 7 | 按键四脚接错对 | 中 | 用 test_door 试 |

---

## 1（已修）程序启动就崩

**症状**：`python src/guardian_main.py ...` 第一行就抛

```
gpiozero.exc.PinInvalidState: Pin GPIO18 is defined as floating,
but "active_state" is not defined
```

**原因**：gpiozero 源码里写死了——`pull_up=None` 表示引脚悬空，
此时必须显式给出 `active_state`。两个都给 `None` 就是矛盾配置，直接抛。

```
pull = {None: 'floating', True: 'up', False: 'down'}[pull_up]
if pull_up is None:
    if active_state is None:
        raise PinInvalidState(...)
```

**影响范围**：3 个文件都有这行，全改了。

- `src/guardian_main.py:50`（主程序）
- `src/test_door.py:28`（门磁测试）
- `src/capture.py:48`（数据采集）

**改法**：`pull_up=True`。门磁和按键都是「一端接 GPIO、一端接 GND」，
本身就是内部上拉接法，**电气语义没变**，只是把矛盾参数去掉。

**为什么仿真测不出**：`mock_run.py` 不导入 gpiozero，`--no-gpio` 也跳过
这段代码。你会以为一切正常，插上硬件才发现起不来。

---

## 2（已修）播报之后，人出事了没人知道

这条比第 1 条更危险，因为它**不报错**，只是静静地不工作。

**症状**：设备开口问了「您还好吗」，老人没回应，
但家属**永远收不到推送**。日志上看事件「自己消失了」。

**链条**：

1. `aplay` 是**前台阻塞**的，播 8 秒主循环就停 8 秒
2. 这 8 秒里串口一直在收，OS 缓冲区积压几十帧
3. 喇叭振动被同一颗雷达读成「有人」，这些帧全是 `state != 0`
4. 播完，主循环恢复，第一次 `read()` 把积压帧**一次性**读进来
5. 状态机看到 `seen=True` → 判定「人回来了」→ 取消静默事件
6. 不推送。老人躺在地上，家属一无所知

**原来的修法为什么不够**：

`18b1637` 已经意识到「冻结时长要用音频真实长度」，改了 `speech_freeze`
从常数 3 秒改成读 WAV 头。但**起点用错了**——它用「播报开始前的 `now`」
加音频时长：

```python
now = time.time()        # t=0
g.update(now, ...)       # 触发 ask
_announce(g, now, ...)   # 内部：speak() 阻塞 8 秒 → speaking_for(now, 8)
```

算出的 `speech_end = 0 + 8 = 8`，而这时真实时间**已经是 8**。
冻结剩余 = 0，等于没设防。

**现在的修法（两道防线）**：

```python
dur = voice.phrase_seconds(kind)      # WAV 真实时长
voice.speak(...)                      # 前台阻塞 8 秒
t_done = time.time()                  # ← 播完才取时间

# A) 主防线：把播报期间积压的帧整段丢掉
ser.reset_input_buffer()

# B) 余振窗：从播完那一刻起再冻结一小段
tail = min(max(dur * 0.25, 0.3), 1.5)
g.speaking_for(t_done, tail)
```

A 是主防线（解决积压帧），B 兜住喇叭振膜衰减的余振。

**怎么验证它真的修好了**：`python src/mock_run.py` 最后一行 `回归测试: PASS`。
我加的两条用例分别验 A 和 B，故意破坏任一道都会 FAIL（已验证过）。

> ⚠️ 这两条用例有个前提：它们替换 `voice.speak` 为「真的 sleep」。
> 如果以后有人把 mock 改成不阻塞，用例会重新变成瞎的。
> 这一点写在用例注释里了。

---

## 3（文档已纠正）串口名

**症状**：`ls /dev/ttyAMA0` 不存在；或存在但一帧数据都收不到。

**正确认知**：

| 设备名 | 在 Pi 5 上是什么 |
|---|---|
| `/dev/ttyAMA0` | **GPIO14/15**，加 `dtparam=uart0=on` 后出现。**接雷达用这个** |
| `/dev/ttyAMA10` | 3 针 debug 排针，不是 GPIO |
| `/dev/serial0` | **在 Pi 5 上指向 `ttyAMA10`**，所以接传感器**不能用它** |

**最阴的地方**：`/dev/serial0` 存在、程序也不报错、接线也对，
**就是收不到数据**——因为你在读 debug 排针。

**检查命令**：

```bash
ls -l /dev/ttyAMA0     # 应显示 crw-rw---- 1 root dialout
ls -l /dev/serial0     # 会显示 -> ttyAMA10，这是正常的，也正说明别用它
```

若 `ttyAMA0` 显示 `root tty` 而非 `root dialout`，说明控制台还占着：

```bash
sudo nano /boot/firmware/cmdline.txt    # 单行文件，删掉 console=serial0,115200
sudo systemctl disable --now serial-getty@ttyAMA0.service
sudo reboot
```

---

## 4（需要你现场做）声卡

**症状**：程序跑得好好的，状态机也触发，**就是没声音**，而且不报错。

**原因**：树莓派 5 **没有 3.5mm 耳机孔**。不插 USB 音箱、不配 `~/.asoundrc`，
`aplay` 会「成功」执行但没有任何输出。

**还有一个更坑的分支**：`~/.asoundrc` 把默认设备指到 USB 音箱后，
`arecord` 用 `default` 会去打那张**只能播不能录**的卡，
录出来是空文件，**也不报错**。

**解决**：

```bash
aplay -l      # 找 USB Audio 的 card 号，记下 X
arecord -l    # 找麦克风的 card 号

# 写 ~/.asoundrc
pcm.!default { type plug; slave.pcm "plughw:X,0" }
ctl.!default { type hw; card X }
```

```bash
alsamixer     # F6 选 USB 声卡，音量推 100
              # 看到红色 MM 就按 M 键，变成绿色 00
```

麦克风单独指定（放在启动命令前）：

```bash
export GUARDIAN_MIC_DEV=plughw:<麦克风卡号>,0
```

**四步验收，全过了才算配好**：

```bash
speaker-test -t sine -f 440 -l 1     # 1) 听「滴——」
arecord -d 5 test.wav                # 2) 5 秒内说话
aplay test.wav                       # 3) 听到刚才那句
aplay audio/ask.wav                  # 4) 听到你自己录的问候
```

第 4 步如果听不到，**后面所有演示都白做**——状态机会正常推进，
但老人听不见任何问候，等于设备不存在。

---

## 5（不用改代码）门磁电平反相

**症状**：开门时报「门关」，关门时报「门开」。
连带后果：离家判定永远不触发，或者人明明在家却被当成出门。

**原因**：MC-38 各家「常开/常闭」标法指的都是**无磁时**的状态，不统一。
买的时候纠结型号没用，只能装上实测。

**解决**：不改代码，加参数。

```bash
python src/guardian_main.py ... --door-open-level 0
```

先用测试脚本实测：

```bash
python src/test_door.py --pin 18
# 开门、关门各试几次，看打印的电平
# 把「开门时出现的那个电平」填进 --door-open-level
```

---

## 6（接线）雷达 TX/RX 交叉

**症状**：`ls /dev/ttyAMA0` 存在、权限也对，但 `test_radar.py` 一直是 0 帧。

**接线表**（交叉接，这是最容易错的一处）：

| 雷达 | 树莓派 | 注意 |
|---|---|---|
| VCC | Pin 2 或 4 | **必须 5V**，不是 3.3V |
| GND | Pin 6 / 9 / 14 | 共地，最容易忘 |
| TX | Pin 10 (GPIO15) | **交叉** |
| RX | Pin 8 (GPIO14) | **交叉** |

**0 帧排查顺序**（别乱试，按这个顺序）：

1. 波特率是不是 **256000**（不是 115200）
2. TX/RX 是否交叉接反
3. 雷达供电是不是 **5V**（3.3V 供不起来）
4. GND 有没有和树莓派共地
5. 串口权限：`sudo usermod -aG dialout $USER`，然后**重新登录系统**（不是重开终端）

---

## 7（接线）四脚按键接错对

**症状**：按下按键，程序没反应。

**原因**：四脚轻触开关内部是两组各两个脚相连，**必须跨凹槽接对角**。
接到同一侧的两个脚，等于永远短路或永远断开。

**解决**：无反应就换对角另外两脚。用 `test_door.py --pin 17` 看电平翻转。

**接法**：

- 绿键：Pin 11 (GPIO17) + Pin 9 (GND)
- 红键：Pin 13 (GPIO27) + Pin 9 (GND)

---

## 到货当天的执行顺序

**别跳步**，每一步过了再下一步。跳步的结果是出了问题不知道是哪一环。

```bash
# 0. 环境体检（在树莓派上，仓库根目录）
python src/preflight.py
# 期望：串口 PASS、依赖 PASS、7 句语音 PASS
# 声卡 WARN 可以接受（还没插音箱）

# 1. 串口通了没
ls -l /dev/ttyAMA0          # 应存在且 root dialout

# 2. 雷达有数据没
python src/test_radar.py --port /dev/ttyAMA0
# 期望：10 帧/秒，挥手时状态数字变

# 3. 门磁通断
python src/test_door.py --pin 18
# 记下开门时的电平

# 4. 按键通断
python src/test_door.py --pin 17
# 按绿键看电平翻转

# 5. 声音出来没（四步验收，见上面第 4 节）

# 6. 整机空跑
python src/guardian_main.py --port /dev/ttyAMA0 --pin-door 18 --pin-button 17 --pin-sos 27

# 7. 三个验收动作
#    静坐 90 秒 → 听到 ask
#    按绿键   → 听到 resolved
#    开门 10 秒 → 听到 away
```

第 6 步之前，**不要**先跑采集。采集脚本会写 `data/guardian.csv`，
在链路没验证过之前采的数据不能用。

---

## 如果某一步过不去

先跑 `python src/preflight.py --quiet`，它会把「缺什么」列出来。
再对照上面的编号找对应条目。

实在卡住，把这三样发我：

1. `python src/preflight.py` 的完整输出
2. 出问题那一步的完整报错（不要截半句）
3. `ls -l /dev/ttyAMA0` 和 `ls -l /dev/serial0` 两行

有了这三样，多数问题不用猜。

---

## 最后一句

上面 7 条里，**第 1、2 条是代码本身的硬伤，不修一定出事**；
第 3～7 条是硬件与环境的常见坑，**多数靠参数和接线解决，不用改代码**。

所以你现在手上这版代码，硬件到货后可以照着上面顺序走，
但**必须先 `git pull` 拿到 `f5e9a46` 之后的版本**——
你最初给我的那份，第 1 条会让程序起不来，第 2 条会让你在答辩时
演示「老人没回应、家属也没被通知」这个最不该出现的画面。