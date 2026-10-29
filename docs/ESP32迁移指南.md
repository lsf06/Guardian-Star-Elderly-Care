# ESP32-S3 迁移指南（量产形态）

> **这份文档回答一个问题**：把主控从树莓派 5 换成 ESP32-S3，需要买什么、接什么、改什么、会失去什么。
>
> **但不要现在做。** 前提条件写在第一节。这份文档的作用是：现在就能下单、能装环境，但代码等 L1（11/12）交付后再动。

---

## 一、什么时候动

| 阶段 | 做什么 | 时间 |
|---|---|---|
| **现在** | 下单、装 PlatformIO、把开发板点灯跑通 | 半天，不影响 L1 |
| **L1 交付后** | 移植雷达解析 + 状态机 + 音频，七步验收 | 3–5 天 |
| **L2 之后** | 加语音命令词、接真实用户 | — |

**不要现在写 ESP32 的业务代码。** 两套代码并行维护，会让你连 L1 都交不出来。

---

## 二、买什么

| 件 | 型号 | 搜索关键词 | 价格 | 备注 |
|---|---|---|---|---|
| 主控 | **ESP32-S3-DevKitC-1 N16R8** | `ESP32-S3-DevKitC-1 N16R8 开发板` | 45–60 | **必须 N16R8**（16 MB flash + 8 MB PSRAM）。N8R2 存不下音频 + 后续模型 |
| 功放 | **MAX98357A** I2S 功放 | `MAX98357A I2S 音频功放模块` | 6–10 | 不要买 PAM8403（那是模拟输入，要 DAC） |
| 喇叭 | 4Ω 3W 小喇叭 | `4欧3W 腔体喇叭 小` | 4–8 | 带腔体的比裸喇叭好听一倍 |
| RTC（可选） | DS3231 | `DS3231 时钟模块` | 5–8 | 断网时靠它守住"9 点 / 20 点" |
| 电源 | 5V/2A | `5V2A 电源适配器 DC` | 8–12 | 雷达 + 功放峰值电流会超 USB 口 |

已有件全部沿用：LD2410C、MC-38 门磁、Ø60 按键 ×2、ABS 外壳、铜箔、100 µF 电容。

**整机成本估算**：主控 55 + 功放 8 + 喇叭 6 + 雷达 30 + 门磁 5 + 按键 20 + 外壳 15 + 杂项 10 ≈ **约 150 元**。

> 注意：这比"树莓派方案 720 元"低一个数量级，但比文档里写的"增量 100–150 元"略高——因为这次算的是**整机**。答辩时要说清口径，别混。

---

## 三、装什么

**推荐 PlatformIO（VS Code 插件）**，比 ESP-IDF 好上手，比 Arduino IDE 好管依赖。

```
# platformio.ini
[env:esp32-s3-devkitc-1]
platform  = espressif32
board     = esp32-s3-devkitc-1
framework = arduino
board_build.flash_size = 16MB
board_build.partitions = partitions.csv
monitor_speed = 115200
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_CDC_ON_BOOT=1
```

```
# partitions.csv —— 默认分区不够放 6 句 WAV，必须自定义
# Name,   Type, SubType, Offset,  Size
nvs,      data, nvs,     0x9000,  0x5000
otadata,  data, ota,     0xe000,  0x2000
app0,     app,  ota_0,   0x10000, 0x300000
spiffs,   data, spiffs,  0x310000,0x400000
coredump, data, coredump,0x710000,0x10000
```

**如果坚持用 Arduino IDE**：工具 → 分区方案选 "16M Flash (3MB APP/9.9MB FATFS)"，但那样就没有 LittleFS，建议还是 PlatformIO。

---

## 四、怎么接（引脚已避开所有雷区）

ESP32-S3 的 GPIO 有大量坑，下表全部避开了：

| 信号 | ESP32-S3 GPIO | 说明 |
|---|---|---|
| 雷达 TX → | **GPIO18**（UART1 RX） | 交叉 |
| 雷达 RX ← | **GPIO17**（UART1 TX） | 交叉；雷达 RX 是 3.3V 逻辑，安全 |
| 门磁 DO | **GPIO4** | 输入，`INPUT_PULLUP` |
| 绿键 | **GPIO5** | 输入，`INPUT_PULLUP`，另一端接 GND |
| 红键（SOS） | **GPIO6** | 同上 |
| I2S BCLK | **GPIO15** | → MAX98357A BCLK |
| I2S LRC | **GPIO16** | → MAX98357A LRC |
| I2S DIN | **GPIO7** | → MAX98357A DIN |

**绝对不能用的引脚**（用了就烧不进去 / 起不来）：

| GPIO | 为什么 |
|---|---|
| 19, 20 | USB D- / D+，接了 USB 就废 |
| 26–32 | SPI flash 专用 |
| 33–37 | **N16R8 的 Octal PSRAM 占用**（这是 N16R8 特有的坑） |
| 0, 3, 45, 46 | strapping 脚，上电电平决定启动模式 |
| 43, 44 | UART0，日志输出用 |

**供电**：雷达 VCC → **5V**（模块内部有 LDO，接 3.3V 不工作）；MAX98357A VIN → 5V，GND 共地；100 µF 并在雷达 5V 就近。

---

## 五、代码怎么迁（三个文件，一一对应）

| 树莓派 | ESP32 | 难度 |
|---|---|---|
| `src/ld2410.py` 帧解析 | 直接翻译成 C，逻辑不变 | 低 |
| `src/guardian.py` 状态机 | 逻辑照搬，容器换成定长数组 | 中（见下面 5.2） |
| `src/voice.py` 播放 | 换成 I2S 直出 WAV | 中 |
| `src/capture.py` / `sweep.py` / `tools/plot_sweep.py` | **不迁**，留在电脑上跑 | 无 |

### 5.1 帧解析：偏移直接用，别重新推导

下面是 `src/ld2410.py` 里已核对过的**整帧绝对偏移**（23 字节基本帧）：

```
0-3    帧头 F4 F3 F2 F1
4-5    数据长度 13 (0D 00)
6      数据类型 0x02
7      数据头 0xAA
8      目标状态  0=无人 1=运动 2=静止 3=运动+静止
9-10   运动目标距离 cm (小端)
11     运动目标能量
12-13  静止目标距离 cm (小端)
14     静止目标能量
15-16  检测距离 cm
17     0x55
18     0x00
19-22  帧尾 F8 F7 F6 F5
```

**注意**：Python 里 `payload` 从偏移 6 开始，所以 `payload[2]` 才是状态；C 里如果你直接存整帧，状态就是 `buf[8]`。**这两种下标差 6，是最容易搞混的一处**，注释里必须写清。

```c
// 逐字节找帧头，再按长度取整帧
static uint8_t buf[64];
static int n = 0;

void feed(uint8_t b) {
    if (n < 4) {
        buf[n++] = b;
        if (n == 4 && memcmp(buf, "\xF4\xF3\xF2\xF1", 4) != 0) { n = 0; }  // 重新同步
        return;
    }
    buf[n++] = b;
    if (n < 6) return;
    int len = buf[4] | (buf[5] << 8);        // 应为 13
    if (n < 6 + len + 4) return;             // 等收满
    if (memcmp(buf + 6 + len, "\xF8\xF7\xF6\xF5", 4) == 0) {
        on_frame(buf, 6 + len);              // buf[8] = 状态
    }
    n = 0;                                   // 无论成败都重置，靠帧头再同步
}
```

### 5.2 状态机：一个关键改写

Python 用的是 `deque` 存 `(t, seen)`，90 秒 × 10 Hz = 900 项。C 里不要照抄，**用定长秒桶，180 字节就够**：

```c
#define BUCKETS 90
static uint8_t seen_cnt[BUCKETS];
static uint8_t total_cnt[BUCKETS];
static int8_t  bucket = -1;

void tick(bool seen) {
    int8_t now_s = (int8_t)(millis() / 1000 % BUCKETS);
    if (now_s != bucket) {                  // 跨秒：清空新桶
        bucket = now_s;
        seen_cnt[now_s] = 0;
        total_cnt[now_s] = 0;
    }
    total_cnt[bucket]++;
    if (seen) seen_cnt[bucket]++;
}

// 等价于 Python 的 occupancy(now)
bool should_ask(void) {
    int seen = 0, total = 0;
    for (int i = 0; i < BUCKETS; i++) { seen += seen_cnt[i]; total += total_cnt[i]; }
    if (total < 60) return false;                    // 窗口没填满（约 6 秒无数据）
    return (float)seen / total <= 0.20f;             // absent_ratio
}
```

**判定式必须和 Python 完全一致**：不是"连续 N 秒没看到人"，而是"**窗口内看到人的帧占比 ≤ 20%**"。这个改动当初把检出率从 0% 救了回来，移植时不要顺手"优化"掉。

**时间的坑（必看）**：

```c
// 正确：无符号差值，49.7 天溢出也安全
if (millis() - last_ask >= 90000UL) { ... }

// 错误：有符号比较，溢出后会变成负数，判定永远不成立
if ((int32_t)(millis() - last_ask) >= 90000) { ... }
```

### 5.3 音频：I2S 直出，不装解码库

你的 WAV 已经是 **16 kHz / 单声道 / 16 bit**，和 I2S 配置天然一致，所以不需要任何解码库，跳过 44 字节头直接写：

```c
#include <LittleFS.h>
#include <driver/i2s.h>

void play_wav(const char *path) {
    File f = LittleFS.open(path, "r");
    if (!f) { Serial.printf("[!!] 缺失 %s\n", path); return; }
    f.seek(44);                              // 跳过 WAV 头
    static int16_t buf[512];
    while (f.available()) {
        size_t got = f.read((uint8_t *)buf, sizeof(buf));
        size_t written;
        i2s_write(I2S_NUM_0, buf, got, &written, portMAX_DELAY);
    }
    f.close();
}
```

六个文件合计约 1 MB（每句 3–5 秒），16 MB flash 绰绰有余。**用工具上传**：

```bash
pio run --target uploadfs        # 把 data/ 目录下的 wav 灌进 LittleFS
```

---

## 六、七步验收（一次只加一个变量）

| 步 | 做什么 | 通过标准 | 失败先查 |
|---|---|---|---|
| 1 | 点灯 + 串口打印 | 每 500 ms 打一行 | USB 线是否数据线、驱动、`ARDUINO_USB_CDC_ON_BOOT` |
| 2 | UART1 读雷达 | **稳定 10 帧/秒**，手挥状态变化 | 波特率 256000、TX/RX 交叉、雷达 5V |
| 3 | 读门磁 + 双键 | 开合/按下有电平翻转 | `INPUT_PULLUP`、是否接 GND、strapping 脚误用 |
| 4 | **只播一句** WAV | 听到 `ask.wav` | 44 字节头、I2S 引脚、功放 SD 脚（增益）、喇叭阻抗 |
| 5 | WiFi + 一条 HTTP | 手机收到测试消息 | 2.4 GHz（S3 不支持 5 GHz）、URL、证书 |
| 6 | 合并状态机 | 静默 90 秒后开口，按键后播 resolved | 时间单位、窗口占比算错 |
| 7 | **拔电 10 次** | 每次都正常启动并自检 | flash 损坏、LittleFS 未挂载、启动时序 |

第 7 步是这个方案相对树莓派**最大的优势**，必须测：树莓派被拔电有 SD 卡损坏风险，ESP32 没有。

---

## 七、会失去什么（必须写进边界）

| 能力 | 树莓派 | ESP32-S3 | 怎么处理 |
|---|---|---|---|
| 离线连续语音识别 | Vosk 可用 | **装不下**（模型 40 MB+） | 换 **ESP-SR** 命令词识别（"我没事""救命"），或录音上传云端 ASR |
| 本地 TTS | edge-tts 可用 | **不可用** | 回复改云端 TTS，或只播预录 + 固定回复 |
| 板上跑 `sweep` | 可以 | 不做 | 原始 CSV 通过 WiFi 传回电脑，分析仍在电脑上 |
| 每日点名的时刻 | NTP | NTP；**断网就漂** | 加 DS3231（5 元），或接受断网时不精确 |
| 安全路径依赖网络 | 否 | **否（更好）** | 本地 WAV + 本地判定，断网完全不影响 |

### 关于 ESP-SR 替换 Vosk

这不是"降级"，是换了一种更合适的思路：

- **Vosk**：连续语音转文字 → 交给大模型理解 → 需要较大算力 + 联网
- **ESP-SR**：识别固定命令词（WakeNet 唤醒 + MultiNet 命令）→ 完全本地、几百 KB、不联网

**对你的场景，命令词比连续识别更合适**：老人不会说长句子，而"我没事""不舒服""救命"这三句覆盖了 90% 的需求，且本地识别不会因为网络差而失败。

诚实说法（答辩用）：

> "换到 ESP32 之后我放弃了连续语音识别，改用本地命令词。因为老人不会说长句子，而命令词识别完全本地、不联网、不会失败。**我把'听懂一切'换成了'听懂三句'，但这个交换让它在断网时也不会哑。**"

---

## 八、原方案里必须同步改的地方

一旦真迁到 ESP32，下面这些文档口径要一起改，否则会出现"文档说树莓派、代码是 ESP32"的矛盾：

- `docs/项目说明书.md` 规格表（主控、功耗、成本口径）
- `docs/项目策划书.md` 成本一节（720 vs 150，必须说清是整机还是增量）
- `README.md` "接真硬件"一节
- `hardware/BOM.md` 主控行
- `docs/答辩问答.md` Q9（断网/断电——ESP32 下断电不再损坏，答案要变好）

**在真正迁移之前，一个都不要改。** 现在改就是给自己造矛盾。
