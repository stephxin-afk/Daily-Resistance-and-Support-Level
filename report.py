# -*- coding: utf-8 -*-
"""
Per-seed grouped daily pivot report (web + pdf + csv)

What you get:
- index.html   ✅ 响应式网页（分组表格，下拉筛选；种子行浅蓝；S1/R1 贴近浅黄）
- report.pdf   ✅ 封面 + 每组一页的表格（横向）
- table.csv    ✅ 原始数据（含 Group 列；不含内部样式列）

Env (all optional):
- TICKERS               你的种子股票（逗号分隔，如：AMD,HD,TOL,GOOGL,AMZN）
- DEFAULT_TICKERS       当 TICKERS 为空时的默认列表
- FINNHUB_API_KEY       用于自动补全“同业”
- REPORT_URL            PDF 的在线地址（用于通知）
- SITE_URL              网页地址（用于通知）
- WECHAT_SCT_SENDKEY    ServerChan Turbo key
- PUSHPLUS_TOKEN        PushPlus token

Deps: yfinance, pandas, matplotlib, requests
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime
from typing import Dict, List

import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

TITLE = "Daily Pivot Levels (Ticker + Peers)"
SUB   = "P=(H+L+C)/3; S1=2P−H; S2=P−(H−L); R1=2P−L; R2=P+(H−L)"

# 画布：渲染减号
matplotlib.rcParams["axes.unicode_minus"] = False


# -------------------- utils --------------------
def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    if v is None:
        v = default
    return v.strip()

def parse_csv_str(s: str) -> List[str]:
    """解析 'a,b, c' -> ['A','B','C']，过滤空串"""
    if not s:
        return []
    return [x.strip().upper() for x in s.split(",") if x.strip()]


# -------------------- data fetch --------------------
def get_peers_from_finnhub(symbol: str) -> List[str]:
    """Finnhub peers（无 key 或失败则返回 []）"""
    key = get_env("FINNHUB_API_KEY")
    if not key:
        log("FINNHUB_API_KEY not set; skip peers.")
        return []
    url = f"https://finnhub.io/api/v1/stock/peers?symbol={symbol}&token={key}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        peers = r.json()
        if isinstance(peers, list):
            peers = [p.upper() for p in peers if isinstance(p, str)]
            peers = [p for p in peers if p != symbol.upper()]
            log(f"[{symbol}] peers: {peers[:10]}")
            return peers
        return []
    except Exception as e:
        log(f"[{symbol}] peers error: {e}")
        return []

def pivots(h: float, l: float, c: float):
    P  = (h + l + c) / 3.0
    S1 = 2 * P - h
    S2 = P - (h - l)
    R1 = 2 * P - l
    R2 = P + (h - l)
    return P, S1, S2, R1, R2

def fetch_one_row(ticker: str) -> Dict:
    """最新日线一行：High/Low/Close/PrevClose/%Chg + Pivot"""
    df = yf.download(ticker, period="10d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance empty: {ticker}")
    last = df.tail(1).reset_index(drop=False).iloc[0]
    h = float(last["High"]); l = float(last["Low"]); c = float(last["Close"])
    # prev close：往前一根
    if len(df) >= 2:
        prevc = float(df["Close"].iloc[-2])
    else:
        prevc = c
    chg = (c - prevc) / prevc * 100 if prevc else 0.0

    dt = last["Date"] if "Date" in last else df.index[-1]
    date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]

    P, S1, S2, R1, R2 = pivots(h, l, c)
    return {
        "Ticker": ticker.upper(),
        "Date": date_str,
        "High": round(h, 2),
        "Low": round(l, 2),
        "Close": round(c, 2),
        "PrevClose": round(prevc, 2),
        "% Chg": round(chg, 2),
        "Pivot P": round(P, 2),
        "S1": round(S1, 2),
        "S2": round(S2, 2),
        "R1": round(R1, 2),
        "R2": round(R2, 2),
    }


# -------------------- build groups (★ 种子置顶 + IsSeed 标记) --------------------
def build_group(seed: str) -> pd.DataFrame:
    peers = get_peers_from_finnhub(seed)
    tickers = [seed] + peers
    rows = []
    for t in tickers:
        try:
            r = fetch_one_row(t)
            r["Group"]  = f"{seed} + Peers"
            r["IsSeed"] = (t.upper() == seed.upper())
            rows.append(r)
        except Exception as e:
            log(f"[{seed}] fetch {t} failed: {e}")
    if not rows:
        raise RuntimeError(f"[{seed}] no valid rows")
    df = pd.DataFrame(rows)
    cols = ["Group", "IsSeed", "Ticker", "Date", "High", "Low", "Close", "PrevClose", "% Chg", "Pivot P", "S1", "S2", "R1", "R2"]
    df = df[cols]
    # 种子行置顶，其余按 Ticker 排序
    df = pd.concat([df[df["IsSeed"]], df[~df["IsSeed"]].sort_values(["Ticker"])], ignore_index=True)
    log(f"[{seed}] rows={len(df)}")
    return df


# -------------------- outputs --------------------
def write_csv(df_all: pd.DataFrame, path: str) -> None:
    out = df_all.drop(columns=["IsSeed"], errors="ignore")
    out.to_csv(path, index=False)
    log(f"Wrote {path}")

def write_pdf(grouped: Dict[str, pd.DataFrame], path: str) -> None:
    with PdfPages(path) as pdf:
        # 封面
        plt.figure(figsize=(8.27, 11.69))
        plt.axis("off")
        plt.text(0.5, 0.75, TITLE, ha="center", fontsize=22, fontweight="bold")
        plt.text(0.5, 0.68, SUB, ha="center", fontsize=11)
        plt.text(0.5, 0.62, f"Generated: {datetime.now():%Y-%m-%d %H:%M}", ha="center", fontsize=10)
        pdf.savefig(bbox_inches="tight"); plt.close()

        # 每组一页
        for seed, df in grouped.items():
            df_show = df.drop(columns=["Group", "IsSeed"])  # 去掉内部列
            plt.figure(figsize=(11.69, 8.27))
            plt.axis("off")
            plt.title(f"{seed} + Peers", fontsize=16, pad=12, loc="left")
            table = plt.table(cellText=df_show.values, colLabels=df_show.columns, loc="center")
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1.1, 1.3)
            pdf.savefig(bbox_inches="tight"); plt.close()
    log(f"Wrote {path}")

def write_html(grouped: Dict[str, pd.DataFrame], pdf_url: str, csv_name: str, path: str) -> None:
    def esc(t: str) -> str:
        return (t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                  .replace('"',"&quot;").replace("'","&#39;"))

    # 下拉选项
    options = ["<option value='__ALL__'>All groups</option>"]
    for seed in grouped.keys():
        options.append(f"<option value='{esc(seed)}'>{esc(seed)} + Peers</option>")

    sections = []
    for seed, df in grouped.items():
        sec_id = f"sec_{seed}"
        show_cols = [c for c in df.columns if c not in ("Group", "IsSeed")]
        thead = "".join(f"<th>{esc(c)}</th>" for c in show_cols)

        rows_html = []
        for _, row in df.iterrows():
            is_seed = bool(row.get("IsSeed", False))
            row_style = ' style="background:#eef6ff;"' if is_seed else ""

            close = float(row["Close"])
            s1 = float(row["S1"]); r1 = float(row["R1"])
            hit_s1 = abs(close - s1) / close < 0.02
            hit_r1 = abs(close - r1) / close < 0.02

            tds = []
            for col in show_cols:
                val = row[col]
                cell = f"{val}"
                if col == "% Chg":
                    color = "#1a7f37" if float(val) >= 0 else "#cc0000"
                    cell = f'<span style="color:{color}">{val}%</span>'
                style = ""
                if col == "S1" and hit_s1: style = ' style="background:#fff7cc;"'
                if col == "R1" and hit_r1: style = ' style="background:#fff7cc;"'
                tds.append(f"<td{style}>{cell}</td>")

            rows_html.append(f"<tr{row_style}>" + "".join(tds) + "</tr>")

        sections.append(f"""
<section class="group" id="{esc(sec_id)}" data-group="{esc(seed)}">
  <h2>{esc(seed)} + Peers</h2>
  <div class="table-wrap">
    <table>
      <thead><tr>{thead}</tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
  </div>
</section>""")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(TITLE)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "Noto Sans", sans-serif; margin:16px; }}
  h1 {{ font-size:1.25rem; margin:0 0 8px; }} h2 {{ font-size:1.1rem; margin:20px 0 10px; }}
  .sub {{ color:#666; font-size:.85rem; margin-bottom:12px; }}
  .bar {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; align-items:center; }}
  .btn {{ text-decoration:none; padding:10px 14px; border-radius:10px; border:1px solid #ddd; }}
  select {{ padding:8px 10px; border-radius:8px; border:1px solid #ddd; }}
  .table-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid #eee; border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ white-space:nowrap; padding:10px 12px; border-bottom:1px solid #f0f0f0; }}
  th {{ position:sticky; top:0; background:#fafafa; text-align:left; }}
  @media (max-width:480px) {{ table {{ font-size:13px; }} th, td {{ padding:8px 10px; }} }}
</style>
</head>
<body>
  <h1>{esc(TITLE)}</h1>
  <div class="sub">{esc(SUB)}</div>

  <div class="bar">
    <a class="btn" href="{esc(pdf_url)}">📄 Download PDF</a>
    <a class="btn" href="{esc(csv_name)}">⬇️ Download CSV</a>
    <span style="margin-left:auto;"></span>
    <label for="groupSel" style="font-size:.95rem;color:#555;">Filter:&nbsp;</label>
    <select id="groupSel" onchange="applyFilter()">
      {''.join(options)}
    </select>
  </div>

  {''.join(sections)}

  <div class="sub" style="margin-top:10px;color:#888;">Updated at: {datetime.now():%Y-%m-%d %H:%M}</div>

<script>
function applyFilter() {{
  var val = document.getElementById('groupSel').value;
  var secs = document.querySelectorAll('section.group');
  secs.forEach(function(s) {{
    if (val === '__ALL__' || s.dataset.group === val) s.style.display = 'block';
    else s.style.display = 'none';
  }});
}}
(function initSelectFromHash(){{
  var h = location.hash || '';
  if (h.indexOf('#sec_') === 0) {{
    var seed = h.replace('#sec_','');
    var sel = document.getElementById('groupSel');
    for (var i=0;i<sel.options.length;i++) {{
      if (sel.options[i].value === seed) {{ sel.selectedIndex = i; break; }}
    }}
  }}
  applyFilter();
}})();
</script>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Wrote {path}")


# -------------------- notifications (optional) --------------------
def push_serverchan(sendkey: str, title: str, content_md: str) -> bool:
    if not sendkey: return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                          data={"title": title, "desp": content_md}, timeout=15)
        log(f"[SCT] {r.status_code} {r.text[:200]}")
        r.raise_for_status(); return r.ok
    except Exception as e:
        log(f"[SCT] error: {e}"); return False

def push_pushplus(token: str, title: str, content_html: str) -> bool:
    if not token: return False
    try:
        r = requests.post("https://www.pushplus.plus/send",
                          json={"token": token, "title": title, "content": content_html, "template": "html"},
                          timeout=15)
        log(f"[PushPlus] {r.status_code} {r.text[:200]}")
        r.raise_for_status(); return r.ok
    except Exception as e:
        log(f"[PushPlus] error: {e}"); return False


# -------------------- main --------------------
if __name__ == "__main__":
    try:
        # 1) 读取 seeds（优先 TICKERS，否则 DEFAULT_TICKERS）
        seeds = parse_csv_str(get_env("TICKERS"))
        if not seeds:
            seeds = parse_csv_str(get_env("DEFAULT_TICKERS"))
        if not seeds:
            # 最后兜底
            seeds = ["NVDA", "TSLA", "HD", "TOL", "GOOGL", "AMZN"]
        log(f"Seeds: {seeds}")

        # 2) 分组数据
        grouped: Dict[str, pd.DataFrame] = {}
        for seed in seeds:
            grouped[seed] = build_group(seed)

        # 汇总用于 CSV（带 Group 列，去内部 IsSeed）
        df_all = pd.concat(grouped.values(), ignore_index=True)
        write_csv(df_all, "table.csv")

        # 3) PDF & HTML
        write_pdf(grouped, "report.pdf")
        report_url = get_env("REPORT_URL") or "report.pdf"
        write_html(grouped, report_url, "table.csv", "index.html")

        # 4) 可选通知
        site_url = get_env("SITE_URL")
        title = "Daily Pivot Levels — Ticker & Peers"
        md_msg = (
            f"**{title}**\n\n"
            + (f"[📱 Online view]({site_url})\n\n" if site_url else "")
            + f"[📄 Download PDF]({report_url})"
        )
        html_msg = (
            f"<b>{title}</b><br>"
            + (f"<a href=\"{site_url}\">📱 Online view</a><br>" if site_url else "")
            + f"<a href='{report_url}'>📄 Download PDF</a>"
        )
        ok_sct = push_serverchan(get_env("WECHAT_SCT_SENDKEY"), title, md_msg)
        ok_pp  = push_pushplus(get_env("PUSHPLUS_TOKEN"), title, html_msg)
        log(f"[Notify] ServerChan={ok_sct} PushPlus={ok_pp}")

        log("Done.")
    except Exception:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        raise
