# 守护星 Guardian — 判定状态机
#
# 这一层不碰硬件、不碰时间：所有输入都是 (now, seen, door_open, pressed)，
# 所有输出都是事件列表。所以它能在没有树莓派的情况下被完整测试。
#
# 设计要点（每一条都对应一个真实的翻车方式）：
#   1. 锁存：一次静默只问一次、只推一次。人重新出现或门开才解锁。
#      —— 没有它，else 分支里一句 last_seen = now 就会变成每 T 秒轮询骚扰。
#   2. 心跳：超过 heartbeat 秒没收到任何帧 -> 设备异常，而不是「人消失」。
#      —— 没有它，USB 松一下就把「家里有人」报成「老人失踪」。
#   3. 武装：必须在本次在家期间真的看到过人，才允许触发。
#      —— 没有它，家里根本没人时会一直问候空气。
#   4. 出门：门开 >= away_confirm 判离家；短时开关门压制 suppress_short 秒。
#      —— 没有它，一次拿快递就让系统误判一整天。
#   5. 启动自检：上电后迟迟看不到人 -> 提示摆放位置，而不是安静地什么都不做。
#   6. 占比判定：用「窗口内无人的帧占比」而不是「连续多少秒没看到」。
#      —— 没有它，一次偶发误检就把计时器清零，真正的屏息永远触发不了。
#         这个坑是真跑数据才会发现的：8% 的杂散帧足以让连续判定彻底失效。

from collections import deque
from dataclasses import dataclass


@dataclass
class Config:
    silence: float = 90.0            # 观察窗口长度（产品 90s，演示 20s）
    absent_ratio: float = 0.2        # 窗口内「看得到」的帧占比低于此值，判为消失
    answer_window: float = 30.0      # 问候后等多久算无应答（不要用 15s，老人找眼镜都不够）
    away_confirm: float = 10.0       # 门开超过多久判为离家。必须 < silence，否则问候会抢在门磁前面
    suppress_short: float = 120.0    # 短时开关门后压制多久
    after_resolve_quiet: float = 600.0
    #   按键消解后的安静期。按键是老人明确说「我没事」，不能 20 秒后又问一遍。
    #   但它不是永久免疫：安静期一过，若仍持续看不到人，还是要再问一次，
    #   否则就成了「老人拍完键、随后真的倒下，系统从此沉默」。
    #   这两个数（quiet 与 max_asks_per_visit）一起兜住这个两难。
    heartbeat: float = 5.0           # 多久收不到帧判设备异常
    speech_freeze: float = 3.0       # 播报后冻结判定多久（防自激）
    startup_check: float = 60.0      # 上电多久未检测到人给出提示
    max_asks_per_visit: int = 2      # 同一次在家最多问候几次。
    #   设成 2：第一次问，没回应就升级；之后再问也不会有新信息，
    #   只会变成骚扰。它同时兜住「按键消解 -> 冷却到 -> 再问」这个环路，
    #   否则老人每按一次键，20 秒后又被问一句「您还好吗」。
    ask_text: str = "奶奶，有一阵子没看到您了，您还好吗？"
    ask_text_again: str = "您还好吗？拍拍这个按钮就行。"
    resolved_text: str = "好的，您没事就好。"
    push_text: str = "老人较长时间未活动且未回应问候，建议致电确认。"


class Guardian:
    """状态：mode ∈ {HOME, AWAY, FAULT}；episode ∈ {None, asking, escalated, resolved}"""

    def __init__(self, cfg=None, t0=0.0):
        self.cfg = cfg or Config()
        self.mode = "HOME"
        self.episode = None
        self.boot = t0
        self.last_seen = t0
        self.last_frame = t0
        self.ask_at = 0.0
        self.door_since = None
        self.armed = False          # 本次在家期间见过人
        self.ever_seen = False
        self.visit_asks = 0         # 本次在场已问候次数（每次重新武装清零）
        self.suppress_until = 0.0   # 冷却截止
        self.startup_warned = False
        self.hist = deque()         # (t, seen) 滑动窗口，用来算「看不到人」的占比
        self.counts = {"ask": 0, "escalate": 0, "chat": 0, "fault": 0}

    def occupancy(self, now):
        """返回 (窗口内看得到的帧占比, 窗口实际跨度秒数)。"""
        cfg = self.cfg
        while self.hist and now - self.hist[0][0] > cfg.silence:
            self.hist.popleft()
        if not self.hist:
            return 0.0, 0.0
        span = now - self.hist[0][0]
        seen = sum(1 for _, s in self.hist if s)
        return seen / len(self.hist), span

    # ------------------------------------------------------------------
    def update(self, now, seen=None, door_open=False, pressed=False, frame_ok=True):
        """喂一帧状态，返回事件列表 [(kind, text), ...]。"""
        cfg = self.cfg
        ev = []

        # 1) 心跳 --------------------------------------------------------
        if frame_ok:
            self.last_frame = now
        if now - self.last_frame > cfg.heartbeat:
            if self.mode != "FAULT":
                self.mode = "FAULT"
                self.episode = None
                self.counts["fault"] += 1
                ev.append(("fault", "雷达超过 %d 秒没有输出，设备异常，请检查接线"
                           % int(cfg.heartbeat)))
            return ev
        if self.mode == "FAULT":
            self.mode = "HOME"
            self.armed = False
            ev.append(("recovered", "设备已恢复"))

        if seen is not None:
            seen = bool(seen)
        else:
            seen = False
        self.hist.append((now, seen))

        # 1.5) resolved 冷却到期必须回到 None ------------------------------
        # 按键只证明「那一刻清醒」，不证明「之后没事」。
        # 如果 resolved 一直挂着，那么老人拍完键、随后真的失去意识时，
        # 触发条件里的 episode is None 永远为假，系统会永久沉默。
        # 这是最坏的失效方式：它发生在设备刚刚被证明「工作正常」之后。
        if self.episode == "resolved" and now >= self.suppress_until:
            self.episode = None

        # 2) 门磁 --------------------------------------------------------
        if door_open:
            if self.door_since is None:
                self.door_since = now
            if (now - self.door_since >= cfg.away_confirm) and self.mode != "AWAY":
                self.mode = "AWAY"
                self.episode = None
                self.armed = False
                self.suppress_until = 0.0
                ev.append(("away", "门已开启超过 %d 秒，判定为离家" % int(cfg.away_confirm)))
        else:
            if self.door_since is not None:
                dur = now - self.door_since
                self.door_since = None
                if dur < cfg.away_confirm:
                    self.suppress_until = now + cfg.suppress_short
                    ev.append(("short_door", "短时开关门 %.0f 秒，压制判定 %.0f 秒"
                               % (dur, cfg.suppress_short)))
                elif self.mode == "AWAY":
                    self.mode = "HOME"
                    self.armed = False          # 回家后必须重新看到人，才允许再次武装
                    ev.append(("home", "门已关闭，退出离家模式"))

        # 3) 看到人 ------------------------------------------------------
        if seen:
            if not self.armed:
                # 刚上电，或刚从离家模式回来：窗口里的历史不算数。
                # 不清空的话，上电前那 60 秒「无人」会被算成静默，一看到人就立刻问候。
                self.hist.clear()
                self.hist.append((now, True))
                self.visit_asks = 0          # 新的在场周期，问候配额重置
            self.last_seen = now
            self.armed = True
            self.ever_seen = True
            self.suppress_until = 0.0
            if self.episode is not None:
                self.episode = None              # 人回来了，本次事件结束
            if self.mode == "AWAY":
                self.mode = "HOME"
                ev.append(("home", "雷达看到人，判定已回家"))

        # 4) 按键 --------------------------------------------------------
        if pressed:
            # 按键是「人在」最强的证据——比雷达确定得多：能读到电平，就是有人在按。
            # 不把它计入窗口，就会出现「老人刚拍完键，20 秒后又被问您还好吗」。
            self.hist.append((now, True))
            self.last_seen = now
            self.armed = True
            self.ever_seen = True
            if self.episode in ("asking", "escalated"):
                self.episode = "resolved"
                self.suppress_until = now + cfg.after_resolve_quiet
                self.counts_inc("ask_ok")
                ev.append(("resolved", cfg.resolved_text))
            elif self.mode == "HOME" and (
                    self.episode is None or self.episode == "resolved"):
                # 已消解状态下按键，是老人主动想说话，不该被安全冷却挡住。
                self.counts["chat"] += 1
                # 聊完补一段安静期，但不缩短已有的安全冷却。
                self.suppress_until = max(self.suppress_until,
                                          now + cfg.suppress_short)
                ev.append(("chat", ""))          # 唤醒对话，不属于安全路径

        # 5) 触发 --------------------------------------------------------
        occ, span = self.occupancy(now)
        if (self.mode == "HOME"
                and self.armed
                and self.episode is None
                and self.visit_asks < cfg.max_asks_per_visit
                and now >= self.suppress_until
                and span >= cfg.silence * 0.9        # 窗口必须基本填满
                and occ <= cfg.absent_ratio):        # 而不是「连续 N 秒没看到」
            self.episode = "asking"
            self.ask_at = now
            self.visit_asks += 1
            self.suppress_until = now + cfg.speech_freeze
            self.counts["ask"] += 1
            ev.append(("ask", cfg.ask_text))

        # 6) 无应答升级（只升一次，之后锁存到人出现或门开）-----------------
        elif self.episode == "asking" and now - self.ask_at >= cfg.answer_window:
            self.episode = "escalated"
            self.counts["escalate"] += 1
            ev.append(("escalate", cfg.push_text))

        # 7) 启动自检 ----------------------------------------------------
        if (not self.ever_seen) and (not self.startup_warned) \
                and now - self.boot >= cfg.startup_check and self.mode != "FAULT":
            self.startup_warned = True
            ev.append(("startup", "启动 %d 秒仍未检测到人，请检查摆放位置与雷达朝向"
                       % int(cfg.startup_check)))

        return ev

    # ------------------------------------------------------------------
    def counts_inc(self, k):
        self.counts[k] = self.counts.get(k, 0) + 1

    def snapshot(self):
        return {
            "mode": self.mode,
            "episode": self.episode,
            "armed": self.armed,
            "last_seen": round(self.last_seen, 1),
            "suppress_until": round(self.suppress_until, 1),
        }
