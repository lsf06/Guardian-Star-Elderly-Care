# 守护星 Guardian — 协议解析层
# LD2410 串口协议：F4F3F2F1 | len(2,LE) | payload | F8F7F6F5
#
# 23 字节基本帧布局（已对照官方文档逐字节核对）：
#   0-3   帧头
#   4-5   数据长度 13 (0D 00)
#   6     数据类型：0x02 基本 / 0x01 工程模式
#   7     数据头 0xAA
#   8     目标状态  0=无人 1=运动 2=静止 3=运动+静止
#   9-10  运动目标距离 cm
#   11    运动目标能量
#   12-13 静止目标距离 cm
#   14    静止目标能量
#   15-16 检测距离 cm
#   17    0x55
#   18    0x00
#   19-22 帧尾
#
# 注意：payload 从偏移 6 开始，所以 payload[0]=类型，payload[1]=0xAA，
#      payload[2]=状态。别把这里的下标和「整帧偏移」搞混——这里差 6。

HDR = b"\xf4\xf3\xf2\xf1"
TAIL = b"\xf8\xf7\xf6\xf5"
DATA_HEAD = 0xAA
MAX_GATES = 9

STATE_NONE, STATE_MOVING, STATE_STILL, STATE_BOTH = 0, 1, 2, 3
STATE_NAMES = {0: "none", 1: "moving", 2: "still", 3: "both"}


def decode(payload):
    """payload = 帧头之后、帧尾之前的字节。返回 dict 或 None。"""
    if len(payload) < 2 or payload[1] != DATA_HEAD:
        return None
    t = payload[0]

    if t == 0x02:                       # 基本目标帧
        if len(payload) < 11:
            return None
        return _basic(payload, gates=None)

    if t == 0x01:                       # 工程模式帧：尾部是光照 + OUT，门能量从尾部反推
        if len(payload) < 11 + 2 * MAX_GATES + 2:
            return None
        static_start = len(payload) - 2 - MAX_GATES
        motion_start = static_start - MAX_GATES
        return _basic(payload, gates=(motion_start, static_start))

    return None


def _basic(p, gates):
    d = {
        "type": p[0],
        "state": p[2],
        "move_dist": p[3] | (p[4] << 8),
        "move_energy": p[5],
        "still_dist": p[6] | (p[7] << 8),
        "still_energy": p[8],
        "detect_dist": p[9] | (p[10] << 8),
        "gates_motion": None,
        "gates_static": None,
    }
    if gates:
        m, s = gates
        d["gates_motion"] = list(p[m:m + MAX_GATES])
        d["gates_static"] = list(p[s:s + MAX_GATES])
    return d


class Decoder:
    """流式解码器。串口可能从帧中间开始接收，必须靠帧头+长度+帧尾重新同步。"""

    def __init__(self):
        self.buf = b""
        self.bad = 0

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            i = self.buf.find(HDR)
            if i < 0:
                self.buf = self.buf[-3:] if len(self.buf) > 3 else self.buf
                break
            if len(self.buf) < i + 6:
                self.buf = self.buf[i:]
                break
            plen = int.from_bytes(self.buf[i + 4:i + 6], "little")
            if plen < 3 or plen > 96:            # 长度不合理，说明假帧头，跳过一个字节重找
                self.buf = self.buf[i + 4:]
                self.bad += 1
                continue
            end = i + 6 + plen + 4
            if len(self.buf) < end:
                self.buf = self.buf[i:]
                break
            payload = self.buf[i + 6:i + 6 + plen]
            tail = self.buf[i + 6 + plen:end]
            self.buf = self.buf[end:]
            if tail != TAIL:
                self.bad += 1
                continue
            f = decode(payload)
            if f is None:
                self.bad += 1
                continue
            out.append(f)
        return out


def build_frame(state=0, move_dist=0, move_energy=0,
                still_dist=0, still_energy=0, detect_dist=0):
    """构造一帧基本模式报文，只用于测试。"""
    pl = bytes([0x02, DATA_HEAD, state,
                move_dist & 0xFF, move_dist >> 8, move_energy & 0xFF,
                still_dist & 0xFF, still_dist >> 8, still_energy & 0xFF,
                detect_dist & 0xFF, detect_dist >> 8, 0x55, 0x00])
    return HDR + len(pl).to_bytes(2, "little") + pl + TAIL
