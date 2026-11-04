#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 git 提交按天同步到飞书多维表格的「开发日志」。

在仓库根目录执行：

    python tools/feishu_sync.py              # 同步（已有当天记录就覆盖，没有就新建）
    python tools/feishu_sync.py --dry-run    # 只打印要写什么，不调接口
    python tools/feishu_sync.py --since 2026-10-28

为什么用 lark-cli 而不是直接调开放平台 API：
lark-cli 走的是当前登录用户的身份，不需要建企业自建应用、不需要 app_secret、
也不需要把应用加成表协作者。省掉三处最容易配错的地方。

内容从哪来：
- 「今日工作内容」由 git 提交标题自动生成，不用手写
- 「遇到的问题 / 解决方案」git 里没有，写在下面的 NOTES 里（按日期），
  或者同步后在飞书里补；脚本不猜
- 「变更文件数 / 变更行数」从 --shortstat 汇总
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

from collections import OrderedDict
from pathlib import Path

BASE_TOKEN = "JrX4b3srCaOi9qskFqScAMCPn7f"
TABLE_ID = "tblwgF4f1BtmkxXM"  # 开发日志
REPO_URL = "https://github.com/lsf06/Guardian-Star-Elderly-Care"

# 每天的问题与解决，只能人工写——提交信息里没有这层信息。
# 新的一天忘了写，脚本仍会同步，但那两格留空并提示你补。
NOTES: dict[str, dict[str, str]] = {
    "2026-10-28": {
        "标题": "核心监测功能开发：状态机 + 雷达解析 + 文档体系",
        "问题": (
            "1) 单帧丢包会把「有人」误判成「无人」，静默事件被误触发；\n"
            "2) 按键消解后冷却到期没有回到初始态，之后真出事会永久沉默——最严重的漏报；\n"
            "3) 陪聊用 input() 阻塞主循环，聊天期间雷达不再判定；\n"
            "4) 安全播报在本地音频缺失时会退回联网合成，断网就哑；\n"
            "5) 采集脚本没有前置自检，0 帧也照跑；\n"
            "6) 合成扫描结果放在根目录，容易被当成实测数据引用。"
        ),
        "方案": (
            "1) 判定式由「瞬时值」改为「窗口内有人帧占比 ≤20%」，事件武装时清空历史帧；\n"
            "2) resolved 冷却到期强制回到 None，另加 after_resolve_quiet(600s) 与 max_asks_per_visit(2) 兜住两个极端；\n"
            "3) 陪聊移到后台线程；\n"
            "4) strict=True 用于安全路径，本地 WAV 缺失时明确报错而不联网；\n"
            "5) 采集前 3 秒自检，0 帧直接退出；\n"
            "6) 合成数据加 _synthetic_ 前缀并移入 data/。\n"
            "每条修复都补了对应的 mock_run 回归用例。"
        ),
        "计划": "打通离线语音链路；录制 7 句真人语音替换合成音；出接线图与静默事件时间轴。",
    },
    "2026-10-29": {
        "标题": "离线语音链路打通 + 演示物料完成",
        "问题": (
            "1) 播报自激导致完全静默的漏报：真人录音 5.3–10.3 秒，而 speech_freeze 固定 3.0 秒。"
            "播到第 3 秒解冻后，喇叭振动被同一颗雷达读成「看到人」，状态机判定「人回来了」，"
            "把刚发起的静默事件取消——老人没回应，家属永远收不到推送。只有换成真实音频才暴露；\n"
            "2) record_once 有 import sherpa_onnx 硬门槛，没装就直接 return，装了 Vosk 也听不见；\n"
            "3) arecord 用 default 设备时，若 ~/.asoundrc 指向 USB 音箱，会打开只能播的卡，录到空文件且不报错。"
        ),
        "方案": (
            "1) 不是把常数调大，而是按音频真实长度冻结：voice.phrase_seconds() 读 WAV 头返回时长，"
            "speaking_for() 同时延长 speech_end 与 suppress_until，播完才解冻。"
            "用真实参数复现：旧逻辑推送 0 次，修复后 1 次。另加回归用例；\n"
            "2) 改为 vosk / sherpa-onnx 二选一探测；\n"
            "3) 新增 GUARDIAN_MIC_DEV 显式指定录音设备。"
        ),
        "计划": "评估量产形态（ESP32-S3）；统一十份文档中「语音识别是否可用」的口径。",
    },
    "2026-11-02": {
        "标题": "产品页改版上线：从技术展示改为消费者产品介绍",
        "问题": (
            "1) 成本口径混着说：最初写「120 元的桌面盒子」，但 120 不含主控，读者会误读成整机价；\n"
            "2) GitHub Pages 两次静默掉线：Source 默认选中 GitHub Actions 但仓库无 workflow，零部署不报错；"
            "另一次 Branch 选成 None（等于取消发布），页面仍提示 source saved；\n"
            "3) 首屏先用了 AI 生成图，被判为「像廉价家电」，不具备产品质感；\n"
            "4) 页面整体是技术展示风格，与消费者产品定位不符。"
        ),
        "方案": (
            "1) 成本分三口径：外围器件 157 元 / 整机 DIY 约 720 元 / 量产约 150 元；承诺值标注「设计值」；\n"
            "2) 用接口显式指定 source（branch=main，path=/），并轮询构建状态确认到 built；\n"
            "3) 撤掉生成图，改用真实摄影素材（Pexels 免费商用），下载到本地引用保证断网可演示；\n"
            "4) 页面重做：去掉代码仓库入口，改为产品细节 / 家属端 / 立即预订，新增家属端 App 界面示意与购买承诺区。"
        ),
        "计划": "把仓库过程材料整理进飞书多维表格，供老师查看项目进度。",
    },
    "2026-11-04": {
        "标题": "接入飞书多维表格，建立过程记录",
        "问题": (
            "1) 飞书多维表格与 Git 没有原生同步；硬接开放平台 API 要建企业自建应用、配密钥、"
            "把应用加成表协作者，三处都容易配错；\n"
            "2) 早期提交没有正文，git 里取不到「当时为什么这么做」。"
        ),
        "方案": (
            "1) 改用 lark-cli 以当前登录用户身份直接写表，不需要 app_secret，也不需要加协作者；"
            "按日期 upsert，重复运行不会产生重复记录；\n"
            "2) 为早期提交按仓库现状补写动机，只写能从代码与文档核对到的事实。"
        ),
        "计划": "硬件到货后先跑串口连通与按键/门磁通断，再做六组采集（sit 组 ≥2 小时），回填指标。",
    },
}

TYPE_LABEL = {
    "feat": "功能", "fix": "修复", "docs": "文档", "style": "样式",
    "refactor": "重构", "chore": "工程", "init": "初始化",
}


def git(*args: str) -> str:
    r = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} 失败：{r.stderr.strip()}")
    return r.stdout


def collect(since: str | None) -> "OrderedDict[str, dict]":
    args = ["log", "--pretty=format:@@%h|%ad|%s", "--date=format:%Y-%m-%d", "--shortstat"]
    if since:
        args.append(f"--since={since}")
    raw = git(*args)

    days: "OrderedDict[str, dict]" = OrderedDict()
    for block in raw.split("@@")[1:]:
        block = block.strip()
        if not block:
            continue
        head, _, rest = block.partition("\n")
        h, date, subject = head.split("|", 2)

        m = re.search(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?", rest)
        files = int(m.group(1)) if m else 0
        ins = int(m.group(2) or 0) if m else 0
        dele = int(m.group(3) or 0) if m else 0

        kind_raw = subject.split(":")[0].split("(")[0].strip().lower()
        title = subject.split(":", 1)[1].strip() if ":" in subject else subject
        label = TYPE_LABEL.get(kind_raw, kind_raw or "其他")

        d = days.setdefault(date, {"items": [], "files": 0, "ins": 0, "del": 0, "first_hash": h})
        d["items"].append(f"{label}｜{title}（{h}）")
        d["files"] += files
        d["ins"] += ins
        d["del"] += dele
    return OrderedDict(sorted(days.items()))  # 老日期在前


def build(days) -> dict[str, dict]:
    out = {}
    for date, d in days.items():
        note = NOTES.get(date, {})
        out[date] = {
            "日志标题": note.get("标题") or f"{date} 开发记录",
            "日期": f"{date} 12:00",
            "今日工作内容": "\n".join(f"- {x}" for x in d["items"]),
            "遇到的问题": note.get("问题", ""),
            "解决方案": note.get("方案", ""),
            "明日计划": note.get("计划", ""),
            "变更文件数": d["files"],
            "变更行数": d["ins"] + d["del"],
            "对应提交": f"[{REPO_URL}/commit/{d['first_hash']}]({REPO_URL}/commit/{d['first_hash']})",
        }
    return out


def lark_bin() -> str:
    """定位 lark-cli。

    Windows 上 PATH 里通常只有 lark-cli.cmd 这类包装脚本，
    subprocess 直接调 "lark-cli" 会 WinError 2；这里显式找一下。
    """
    import os
    import shutil

    for name in ("lark-cli", "lark-cli.cmd", "lark-cli.exe"):
        p = shutil.which(name)
        if p:
            return p
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    for cand in (
        home / ".workbuddy/binaries/node/cli-connector-packages/lark-cli.cmd",
        home / ".workbuddy/binaries/node/cli-connector-packages/lark-cli",
    ):
        if cand.exists():
            return str(cand)
    sys.exit("找不到 lark-cli。请确认已在 WorkBuddy 里连接飞书账号。")


def lark(*args: str) -> dict:
    r = subprocess.run([lark_bin(), "base", *args, "--as", "user"],
                       capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"lark-cli 返回无法解析：\n{r.stdout[:400]}\n{r.stderr[:400]}")


def existing_dates() -> dict[str, str]:
    """返回 {日期(YYYY-MM-DD): record_id}

    注意 +record-list 返回的是 manifest 本身（record_file 在顶层），
    不套在 data 里；这里两种形态都兼容一下。
    """
    res = lark("+record-list", "--base-token", BASE_TOKEN, "--table-id", TABLE_ID)
    payload = res.get("data") if isinstance(res.get("data"), dict) else res
    rec_file = payload.get("record_file")
    if not rec_file:
        sys.exit(f"读取已有记录失败：{json.dumps(res, ensure_ascii=False)[:300]}")
    mapping = {}
    with open(rec_file, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            raw_date = str(rec.get("日期") or "")[:10]
            if raw_date:
                mapping[raw_date] = rec["record_id"]

    # lark-cli 会把记录落到工作目录下的 ndjson 与 manifest，读完整理掉，
    # 否则每同步一次仓库根目录就多两个临时文件
    for p in (rec_file, payload.get("manifest_file")):
        if p:
            Path(p).unlink(missing_ok=True)
    return mapping


def main() -> None:
    dry = "--dry-run" in sys.argv
    since = None
    for i, a in enumerate(sys.argv):
        if a == "--since" and i + 1 < len(sys.argv):
            since = sys.argv[i + 1]

    payload = build(collect(since))
    print(f"待同步 {len(payload)} 天：{', '.join(payload)}\n")

    if dry:
        print(json.dumps(payload, ensure_ascii=False, indent=1)[:3000])
        return

    have = existing_dates()
    to_update, to_create = {}, []
    for date, fields in payload.items():
        if date in have:
            to_update[have[date]] = fields
        else:
            to_create.append(fields)

    if to_update:
        body = {"update_records": to_update}
        res = lark("+record-batch-update", "--base-token", BASE_TOKEN,
                   "--table-id", TABLE_ID, "--json", json.dumps(body, ensure_ascii=False))
        print(f"更新 {len(to_update)} 天：{'ok' if res.get('ok') else res}")
    if to_create:
        body = {"records": to_create}
        res = lark("+record-batch-create", "--base-token", BASE_TOKEN,
                   "--table-id", TABLE_ID, "--json", json.dumps(body, ensure_ascii=False))
        print(f"新建 {len(to_create)} 天：{'ok' if res.get('ok') else res}")

    missing = [d for d in payload if d not in NOTES]
    if missing:
        print(f"\n⚠️ {len(missing)} 天没有写「问题 / 方案 / 计划」，那三格是空的：{', '.join(missing)}")
        print("   补到本文件的 NOTES 里再跑一次，或者直接在飞书里填。")


if __name__ == "__main__":
    main()