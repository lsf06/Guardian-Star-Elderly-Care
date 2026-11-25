#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守护星 · 公开数据采集脚本

只抓公开可访问的页面，只做只读调研。三条线：

  1. 政府采购 —— 中国政府采购网地方公告列表，按关键词过滤「养老/适老化/雷达/监护」，
     从公告正文里抽预算金额、采购人、地域。这是最有价值的一条：
     能拿到真实成交价与采购量，比电商页面上的报价硬得多。
  2. 政策原文 —— 民政部、中国政府网、工信部的公开页面，抽含「养老/适老/监护」的段落。
  3. 竞品线索 —— 从公告标题里反推有哪些厂商在投这个市场。

刻意没做的事：
  - 不抓知乎/小红书/百度/微博：都有反爬，绕过属于对抗，不做。
  - 不做并发、不加代理池、不伪造 UA 之外的任何东西。默认 1.2 秒一条。
  - 不写数据库，只出 CSV + Markdown 报告，方便人工复核每一条。

用法：
    python tools/crawl_market.py                    # 默认：政采 3 页 + 政策 3 站
    python tools/crawl_market.py --pages 8          # 多抓几页
    python tools/crawl_market.py --only policy      # 只抓政策
    python tools/crawl_market.py --dry-run          # 只打印将要访问的 URL

输出到 data/market/：
    ccgp_YYYYMMDD.csv     政采条目（标题/日期/地域/采购人/链接/命中词）
    ccgp_detail.csv       打开过正文的公告（含预算金额）
    policy_YYYYMMDD.md    政策摘录
    README.md             本次运行说明与统计
"""
import argparse
import csv
import os
import random
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "market")

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 宽松 SSL：部分政府站点证书链不完整。只读 GET，不提交任何数据。
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# ---------------------------------------------------------------- 关键词

# 分三档，命中任意一档就记录，但档位写进 CSV，方便后面筛
# 分两档，且**必须两档同时命中**才记录。
# 之前用「养老/设备/采购」三档、任一命中就记，结果食堂、印刷、拖车全进来了——
# 因为「设备采购」「改造」这种词在任何采购公告里都有。
KW = {
    "养老": ["养老", "适老", "独居", "空巢", "居家照护", "社区养老",
             "敬老院", "福利院", "老年公寓", "日间照料", "长者"],
    "设备": ["毫米波", "雷达", "跌倒", "监护", "看护", "一键呼叫",
             "紧急呼叫", "生命体征", "人体存在", "无感监测", "智能看护"],
}

STRICT = ("养老", "设备")

# 明确排除：标题里带这些的一律丢，即使碰巧命中关键词
EXCLUDE = ["食堂", "印刷", "拖车", "物业服务", "保洁", "绿化", "办公家具",
           "车辆", "电梯加装", "消防维保", "空调", "监控系统", "网络设备"]


def hits(text):
    """返回命中的 (档位, 词) 列表。"""
    got = []
    for tier, words in KW.items():
        for w in words:
            if w in text:
                got.append((tier, w))
    return got


def is_relevant(text):
    if any(x in text for x in EXCLUDE):
        return False
    tiers = {t for t, _ in hits(text)}
    return all(t in tiers for t in STRICT)


# ---------------------------------------------------------------- 抓取

_last = [0.0]


def fetch(url, timeout=20, limit=260000):
    """抓一页。内置节流 + 退避重试。返回 (status, text) 或 (None, 错误说明)。"""
    gap = 1.2 - (time.time() - _last[0])
    if gap > 0:
        time.sleep(gap + random.uniform(0, 0.3))
    _last[0] = time.time()

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                raw = r.read(limit)
                enc = "utf-8"
                m = re.search(rb'charset=["\']?([\w-]+)', raw[:3000])
                if m:
                    enc = m.group(1).decode("ascii", "ignore")
                else:
                    try:
                        raw.decode("utf-8")
                    except UnicodeDecodeError:
                        enc = "gbk"
                return r.status, raw.decode(enc, "replace")
        except Exception as e:
            if attempt == 2:
                return None, "%s: %s" % (type(e).__name__, str(e)[:120])
            time.sleep(1.5 * (attempt + 1))
    return None, "unknown"


def text_of(html):
    """粗粒度去标签。政府站点结构不统一，用正则比引入 bs4 更稳。"""
    t = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = t.replace("&nbsp;", " ").replace("&ensp;", " ")
    t = re.sub(r"&#\d+;", "", t)
    t = re.sub(r"&[a-z]+;", " ", t)
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in t.split("\n")]
    return [x for x in lines if x]


# ---------------------------------------------------------------- 政采列表

CCGP_LIST = "http://www.ccgp.gov.cn/cggg/dfgg/"

# 多个栏目一起抓。中标/成交公告最有价值：里面直接写金额和中标型号。
# 「地方公告」是全量的，另外几个是分类频道，覆盖不同公告类型。
CCGP_CHANNELS = [
    ("地方公告", "http://www.ccgp.gov.cn/cggg/dfgg/"),
    ("地方-中标", "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/"),
    ("中央公告", "http://www.ccgp.gov.cn/cggg/zygg/"),
]

# 列表项：<a href="..." title="标题">标题</a> ... 发布时间：<em>2026-11-25 13:16</em> 地域：<em>云南</em> 采购人：<em>xx</em>
RE_ITEM = re.compile(
    r'<a href="(\./[^"]+\.htm)"[^>]*title="([^"]{6,200})"[^>]*>'
    r'[\s\S]{0,200}?发布时间：<em>([\d\-: ]+)</em>\s*'
    r'地域：<em>([^<]*)</em>\s*采购人：<em>([^<]*)</em>',
    re.S)


def parse_list(html):
    out = []
    for href, title, date, zone, buyer in RE_ITEM.findall(html):
        out.append({
            "title": title.strip(),
            "url": urllib.parse.urljoin(CCGP_LIST, href),
            "date": date.strip()[:10],
            "zone": zone.strip(),
            "buyer": buyer.strip(),
        })
    return out


def crawl_ccgp(pages=3, detail_limit=12, verbose=True):
    """抓各栏目公告列表。站内搜索接口有 IP 级限流（返回「访问过于频繁」），
    所以不走搜索，改成抓列表 + 本地过滤。"""
    rows, seen = [], set()
    for cname, base in CCGP_CHANNELS:
      for p in range(1, pages + 1):
        # 第 1 页是 index.htm，后面是 index_1.htm / index_2.htm ...
        url = base if p == 1 else "%sindex_%d.htm" % (base, p - 1)
        st, body = fetch(url)
        if st is None:
            if verbose:
                print("  [%s P%d] 失败：%s" % (cname, p, body))
            continue
        items = parse_list(body)
        if verbose:
            print("  [%s P%d] %d 条" % (cname, p, len(items)))
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            if not is_relevant(it["title"]):
                continue
            h = hits(it["title"])
            it["tiers"] = "+".join(sorted({t for t, _ in h}))
            it["kw"] = ",".join(w for _, w in h)
            it["relevant"] = "Y"
            it["source"] = "%s P%d" % (cname, p)
            rows.append(it)

    # 只对最相关的若干条打开正文，抽预算金额
    detail = []
    targets = [r for r in rows if r["relevant"] == "Y"][:detail_limit]
    if verbose and targets:
        print("  打开 %d 条正文抽金额…" % len(targets))
    for r in targets:
        st, body = fetch(r["url"])
        if st is None:
            continue
        lines = text_of(body)
        blob = " ".join(lines)
        money = re.findall(r"预算金额[：: ]*([\d,.]+\s*万?元)", blob)
        if not money:
            money = re.findall(r"([\d,.]+\s*万元)", blob)[:3]
        winner = re.findall(r"中标[（(]?成交[)）]?[^。]{0,20}?([\u4e00-\u9fa5]{2,20}(?:公司|科技|集团|有限))", blob)
        detail.append({
            "title": r["title"],
            "date": r["date"],
            "zone": r["zone"],
            "buyer": r["buyer"],
            "budget": money[0] if money else "",
            "winner": winner[0] if winner else "",
            "url": r["url"],
        })
    return rows, detail


# ---------------------------------------------------------------- 政策

POLICY = [
    ("民政部 · 统计数据栏目", "https://www.mca.gov.cn/n156/n2679/index.html"),
    ("民政部 · 2025 养老服务十件大事",
     "https://www.mca.gov.cn/n152/n166/c1662004999980008849/content.html"),
    ("中国政府网 · 政策", "https://www.gov.cn/zhengce/"),
    ("工业和信息化部", "https://www.miit.gov.cn/"),
]

POLICY_KW = ["养老", "适老", "独居", "空巢", "监护", "银发", "老年"]


def crawl_policy(verbose=True):
    """抓政策页，抽含关键词的段落。只留长度 >18 字的句子。"""
    blocks = []
    for name, url in POLICY:
        st, body = fetch(url)
        if st is None:
            if verbose:
                print("  [政策] %s 失败：%s" % (name, body))
            continue
        lines = [x for x in text_of(body) if len(x) > 18]
        keep = [x for x in lines if any(k in x for k in POLICY_KW)]
        if verbose:
            print("  [政策] %s：扫描 %d 段，命中 %d 段" % (name, len(lines), len(keep)))
        if keep:
            blocks.append((name, url, keep[:20]))
    return blocks


# ---------------------------------------------------------------- 输出

def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(description="守护星公开数据采集（只读）")
    ap.add_argument("--only", choices=["ccgp", "policy", "all"], default="all")
    ap.add_argument("--pages", type=int, default=3, help="政采列表抓几页（每页约 20 条）")
    ap.add_argument("--detail", type=int, default=12, help="最多打开几条正文抽金额")
    ap.add_argument("--dry-run", action="store_true", help="只打印目标 URL，不实际访问")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    log = []

    def say(msg):
        print(msg)
        log.append(msg)

    say("守护星 · 公开数据采集  %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    say("输出目录：%s" % OUT)
    say("")

    if args.dry_run:
        print("将访问：")
        for cname, base in CCGP_CHANNELS:
            for p in range(1, args.pages + 1):
                print("  [%s] " % cname + (base if p == 1 else "%sindex_%d.htm" % (base, p - 1)))
        for n, u in POLICY:
            print("  %s  %s" % (n, u))
        print("\n（--dry-run 未实际访问）")
        return

    # ---- 1. 政采
    if args.only in ("ccgp", "all"):
        say("【一】中国政府采购网 · 地方公告")
        rows, detail = crawl_ccgp(pages=args.pages, detail_limit=args.detail)
        say("  「养老 + 设备」同时命中 %d 条（已排除食堂/印刷/物业等无关项）" % len(rows))

        if rows:
            write_csv(os.path.join(OUT, "ccgp_%s.csv" % today), rows,
                      ["date", "zone", "buyer", "title", "tiers", "kw", "source", "url"])
        if detail:
            write_csv(os.path.join(OUT, "ccgp_detail.csv"), detail,
                      ["date", "zone", "buyer", "title", "budget", "winner", "url"])
            say("  打开正文 %d 条，其中 %d 条抽到金额" %
                (len(detail), sum(1 for d in detail if d["budget"])))
        say("")

    # ---- 2. 政策
    if args.only in ("policy", "all"):
        say("【二】政策原文")
        blocks = crawl_policy()
        if blocks:
            p = os.path.join(OUT, "policy_%s.md" % today)
            with open(p, "w", encoding="utf-8") as f:
                f.write("# 政策原文摘录（自动采集，需人工复核）\n\n")
                f.write("采集时间：%s\n\n" % datetime.now().strftime("%Y-%m-%d %H:%M"))
                f.write("> 下面每一段都是从官网页面上直接截下来的原句，未经改写。\n"
                        "> 引用时请自己回原文核对一遍——自动抽取可能截断上下文。\n\n")
                for name, url, lines in blocks:
                    f.write("## %s\n\n<%s>\n\n" % (name, url))
                    for x in lines:
                        f.write("- %s\n" % x)
                    f.write("\n")
            say("  写入 %s（%d 段）" % (os.path.basename(p), sum(len(x[2]) for x in blocks)))
        say("")

    # ---- 3. 说明
    readme = os.path.join(OUT, "README.md")
    with open(readme, "w", encoding="utf-8") as f:
        f.write("# 调研数据目录\n\n")
        f.write("这个目录由 `tools/crawl_market.py` 生成，**只抓公开页面，只读**。\n\n")
        f.write("## 文件\n\n")
        f.write("| 文件 | 内容 | 怎么用 |\n|---|---|---|\n")
        f.write("| `ccgp_YYYYMMDD.csv` | 政采公告列表里命中关键词的条目 | 看有多少地方在买这类东西 |\n")
        f.write("| `ccgp_detail.csv` | 打开过正文的公告，含预算金额与中标方 | **真实成交价，最有价值** |\n")
        f.write("| `policy_YYYYMMDD.md` | 政策原句摘录 | 引数据用，引前必须回原文核对 |\n\n")
        f.write("## 三条使用纪律\n\n")
        f.write("1. **金额必须回原文核对**。正则抽的是「预算金额：」后面第一个数字，\n"
                "   可能抽到分包价、也可能抽到整个项目的总预算（含土建）。\n")
        f.write("2. **不要把这些数字直接当市场规模的证据**。它们是「已发生的采购」，\n"
                "   不是「全部需求」。只能说「这个价位有人真的在买」。\n")
        f.write("3. **不抓个人隐私、不抓社交平台**。知乎/小红书/微博都有反爬，\n"
                "   绕过属于对抗行为，本脚本故意不做。要用户原话只能自己去访谈。\n\n")
        f.write("## 运行记录\n\n```\n" + "\n".join(log) + "\n```\n")
    say("写入 %s" % os.path.basename(readme))


if __name__ == "__main__":
    main()