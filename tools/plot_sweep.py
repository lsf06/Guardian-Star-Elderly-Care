#!/usr/bin/env python3
"""把 sweep_result.csv 画成「打扰预算曲线」SVG。零依赖，不需要 matplotlib。

sweep.py 只输出 CSV 和表格，画图这一步它交给人做。这个脚本补上这一段：

    python tools/plot_sweep.py sweep_result.csv --mark 90 -o docs/figs/sweep_real.svg

--mark 是你最终选定的 T（秒），会在图上画一条竖虚线并标出来。
选点的原则不是「检出率最高」，是「在能接受的打扰次数里，检出率最高」。
"""
import argparse
import csv
import io
import os

W, H = 680, 430
L, R, T, B = 66, 78, 86, 112          # 左、右、上、下边距
PW, PH = W - L - R, H - T - B          # 绘图区宽高
FONT = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif"
C_ASK, C_RATE, C_GRID, C_TXT = "#c0392b", "#1f6fb2", "#e5e7eb", "#374151"


def load(path):
    rows = []
    with io.open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "T": float(r["T_sec"]),
                    "asks": float(r["asks_per_24h_still"]),
                    "rate": float(r["detect_rate"]) * 100.0,
                    "lat": float(r["mean_latency_s"]),
                    "empty": int(float(r["empty_false_alarm"])),
                    "lie": int(float(r["lie_asks"])),
                })
            except (KeyError, ValueError):
                continue
    return rows


def build(rows, mark=None, note=""):
    if not rows:
        raise SystemExit("CSV 里没有可用行，检查列名是否为 T_sec / asks_per_24h_still / detect_rate")

    n = len(rows)
    amax = max(r["asks"] for r in rows)
    amax = max(amax * 1.25, 1.0)                      # 左侧上限，全 0 时留 1.0

    def px(i):                                        # 分类轴：等距，避免 T 间距不均导致的错觉
        return L + (PW / 2.0 if n == 1 else PW * i / (n - 1.0))

    def py_ask(v):
        return T + PH - PH * (v / amax)

    def py_rate(v):
        return T + PH - PH * (v / 100.0)

    s = []
    a = s.append
    a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
      'font-family="%s">' % (W, H, W, H, FONT))
    a('<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H))

    a('<text x="%d" y="28" font-size="15" font-weight="700" fill="#111827">打扰预算曲线：'
      '用多大的打扰，换多快的检出</text>' % L)
    a('<text x="%d" y="46" font-size="10.5" fill="#6b7280">左轴/红线：静坐时每天被误问候的次数'
      '　右轴/蓝线：屏息检出率　横轴：判定阈值 T（秒）　下方灰字：平均检出延迟</text>' % L)

    # 网格 + 左右刻度
    for k in range(6):
        y = T + PH * k / 5.0
        a('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
          % (L, y, L + PW, y, C_GRID))
        a('<text x="%d" y="%.1f" font-size="9" fill="%s" text-anchor="end">%.1f</text>'
          % (L - 8, y + 3.2, C_TXT, amax * (5 - k) / 5.0))
        a('<text x="%d" y="%.1f" font-size="9" fill="%s">%d%%</text>'
          % (L + PW + 8, y + 3.2, C_TXT, 20 * (5 - k)))

    a('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#9ca3af" stroke-width="1.2"/>'
      % (L, T + PH, L + PW, T + PH))

    # 选定的 T
    if mark is not None:
        idx = min(range(n), key=lambda i: abs(rows[i]["T"] - mark))
        x = px(idx)
        a('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1.3" '
          'stroke-dasharray="4 3"/>' % (x, T - 6, x, T + PH, "#111827"))
        a('<text x="%.1f" y="%d" font-size="9.5" font-weight="700" fill="#111827" '
          'text-anchor="middle">选定 T=%ds</text>' % (x, T - 12, rows[idx]["T"]))

    # 两条折线
    for key, py, color in (("asks", py_ask, C_ASK), ("rate", py_rate, C_RATE)):
        pts = " ".join("%.1f,%.1f" % (px(i), py(r[key])) for i, r in enumerate(rows))
        a('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2" '
          'stroke-linejoin="round"/>' % (pts, color))
        for i, r in enumerate(rows):
            a('<circle cx="%.1f" cy="%.1f" r="3.4" fill="#fff" stroke="%s" stroke-width="2"/>'
              % (px(i), py(r[key]), color))

    # 横轴标签 + 延迟
    for i, r in enumerate(rows):
        x = px(i)
        a('<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">%ds</text>'
          % (x, T + PH + 16, C_TXT, r["T"]))
        a('<text x="%.1f" y="%d" font-size="8.5" fill="#9ca3af" text-anchor="middle">'
          '%.0fs</text>' % (x, T + PH + 30, r["lat"]))

    a('<text x="%d" y="%d" font-size="9" fill="#9ca3af">← 平均检出延迟</text>'
      % (L, T + PH + 46))
    a('<text x="%d" y="%d" font-size="9" fill="#9ca3af" text-anchor="end">判定阈值 T →</text>'
      % (L + PW, T + PH + 46))

    # 图例
    ly = T + PH + 68
    a('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.2"/>'
      % (L, ly, L + 18, ly, C_ASK))
    a('<text x="%d" y="%d" font-size="10" fill="%s">静坐误问候（次/24h）</text>'
      % (L + 24, ly + 3.4, C_TXT))
    a('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.2"/>'
      % (L + 176, ly, L + 194, ly, C_RATE))
    a('<text x="%d" y="%d" font-size="10" fill="%s">屏息检出率</text>'
      % (L + 200, ly + 3.4, C_TXT))
    a('<text x="%d" y="%d" font-size="9.5" fill="#9ca3af" text-anchor="end">%s</text>'
      % (L + PW, ly + 3.4, note))

    bad = [r["T"] for r in rows if r["empty"] or r["lie"]]
    if bad:
        a('<text x="%d" y="%d" font-size="9.5" font-weight="700" fill="#b91c1c">'
          '注意：T=%s 出现空房或躺平误问候，这比"多问几次"更严重，先查摆放距离</text>'
          % (L, H - 8, "/".join(str(int(t)) for t in bad)))

    a("</svg>")
    return "\n".join(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default="sweep_result.csv")
    ap.add_argument("--mark", type=float, default=None, help="你选定的 T（秒）")
    ap.add_argument("-o", "--out", default="docs/figs/sweep_real.svg")
    args = ap.parse_args()

    rows = load(args.csv)
    svg = build(rows, args.mark, "sweep_result.csv")
    d = os.path.dirname(args.out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    io.open(args.out, "w", encoding="utf-8").write(svg)
    print("已生成 %s（%d 个 T 点，%d 字节）" % (args.out, len(rows), len(svg)))
    if all(r["asks"] == 0 for r in rows):
        print("提示：静坐误问候全为 0。若 sit 采样不足 2 小时，不要对外说「每天 0 次」。")


if __name__ == "__main__":
    main()
