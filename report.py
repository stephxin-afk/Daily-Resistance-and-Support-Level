# -*- coding: utf-8 -*-
"""
Generates:
- report.pdf   (A4 cover + landscape table)
- index.html   (mobile-friendly responsive table)
- table.csv    (raw data download)

Env (optional):
- TICKERS            e.g. "NVDA,AAPL,TSM"  # 手动输入想看的股票（workflow_dispatch）
- FINNHUB_API_KEY    # 自动补全同业
- REPORT_URL         e.g. https://<user>.github.io/<repo>/report.pdf
- SITE_URL           e.g. https://<user>.github.io/<repo>/
- WECHAT_SCT_SENDKEY # Server酱 Turbo
- PUSHPLUS_TOKEN     # PushPlus

Deps: yfinance, pandas, matplotlib, requests
"""

import os
import sys
import traceback
from datetime import datetime

import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# -------------------- Config --------------------
TITLE = "Daily Pivot Levels (Ticker + Peers)"
SUB   = "Formulas: P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
OUT   = "report.pdf"

# fallback 当无 API 或 peers 拉取失败
FALLBACK_TICKERS = ["NVDA", "AMD", "TSM", "AVGO", "INTC"]

# 避免中文字体缺失导致 PDF 乱码（英文 UI）
matplotlib.rcParams["axes.unicode_minus"] = False

# -------------------- Utils --------------------
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return (v or default).strip()

def parse_tickers_env():
    """
    Read TICKERS env like 'NVDA,AAPL; TSM' -> ['NVDA','AAPL','TSM']
    """
    s = get_env("TICKERS")
    if not s:
        return []
    parts = [p.strip().upper() for p in s.replace(";", ",").split(",") if p.strip()]
    # 去重并限量，避免页面过宽
    return list(dict.fromkeys(parts))[:20]

# -------------------- Data: peers + quotes --------------------
def get_peers_from_finnhub(symbol="NVDA"):
    """Fetch peers via Finnhub company-peers API. Returns list[str] or []."""
    key = get_env("FINNHUB_API_KEY")
    if not key:
        log("FINNHUB_API_KEY not set; use fallback peers.")
        return []
    url = f"https://finnhub.io/api/v1/stock/peers?symbol={symbol}&token={key}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        peers = r.json()
        if isinstance(peers, list):
            peers = [p for p in peers if isinstance(p, str) and p.upper() != symbol.upper()]
            log(f"Finnhub peers for {symbol}: {peers[:10]}")
            return peers
        log("Finnhub peers response not a list; fallback.")
        return []
    except Exception as e:
        log(f"Finnhub peers error: {e}")
        return []

def pivots(h, l, c):
    P = (h + l + c) / 3.0
    R1 = 2 * P - l
    S1 = 2 * P - h
    R2 = P + (h - l)
    S2 = P - (h - l)
    return P, S1, S2, R1, R2

def fetch_latest_row(ticker: str):
    """
    Return dict with High/Low/Close/PrevClose/%Chg for the most recent daily bar.
    拉最近 10 天，取倒数第二/第一根做涨跌幅（若只有 1 根则不算 %Chg）。
    """
    df = yf.download(ticker, period="10d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")

    # 取最后一根作为今日，倒数第二根作为前收
    if len(df) >= 2:
        last = df.tail(1).reset_index(drop=False).iloc[0]
        prev = df.tail(2).reset_index(drop=False).iloc[0]
        prev_close = float(prev["Close"])
    else:
        last = df.tail(1).reset_index(drop=False).iloc[0]
        prev_close = None

    h = float(last["High"])
    l = float(last["Low"])
    c = float(last["Close"])

    # 日期字段兼容
    dt = last["Date"] if "Date" in last else last.get("index", None)
    if dt is None:
        try:
            dt = df.index[-1]
        except Exception:
            dt = datetime.now()
    date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]

    pct = ""
    if prev_close and prev_close != 0:
        pct_val = (c - prev_close) / prev_close * 100.0
        pct = round(pct_val, 2)

    return {
        "Ticker": ticker,
        "Date": date_str,
        "High": round(h, 2),
        "Low": round(l, 2),
        "Close": round(c, 2),
        "PrevClose": round(prev_close, 2) if prev_close else "",
        "% Chg": pct if pct != "" else "",
    }

def build_table(tickers):
    rows = []
    for t in tickers:
        try:
            r = fetch_latest_row(t)
            P, S1, S2, R1, R2 = pivots(r["High"], r["Low"], r["Close"])
            r.update({
                "Pivot P": round(P, 2), "S1": round(S1, 2), "S2": round(S2, 2),
                "R1": round(R1, 2), "R2": round(R2, 2),
            })
            rows.append(r)
        except Exception as e:
            log(f"Fetch failed for {t}: {e}")
    if not rows:
        raise RuntimeError("No rows collected. Check network or tickers.")
    cols = ["Ticker", "Date", "High", "Low", "Close", "PrevClose", "% Chg", "Pivot P", "S1", "S2", "R1", "R2"]
    return pd.DataFrame(rows)[cols].sort_values(["Ticker"], ascending=True).reset_index(drop=True)

# -------------------- Outputs: PDF / HTML / CSV --------------------
def write_pdf(df, path):
    """A4 cover (portrait) + table page (landscape)"""
    with PdfPages(path) as pdf:
        # Cover
        plt.figure(figsize=(8.27, 11.69))
        plt.axis("off")
        plt.text(0.5, 0.80, TITLE, ha="center", fontsize=20, fontweight="bold")
        plt.text(0.5, 0.73, SUB, ha="center", fontsize=10)
        plt.text(0.5, 0.68, f'Generated: {datetime.now():%Y-%m-%d %H:%M}', ha="center", fontsize=9)
        pdf.savefig(bbox_inches="tight"); plt.close()

        # Table
        plt.figure(figsize=(11.69, 8.27))
        plt.axis("off")
        table = plt.table(cellText=df.values, colLabels=df.columns, loc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.1, 1.35)
        pdf.savefig(bbox_inches="tight"); plt.close()

def write_html(df, pdf_url):
    """Responsive, mobile-friendly index.html"""
    def fmt(v):
        return f"{v}%" if isinstance(v, (int, float)) and v == df["% Chg"][df["% Chg"] == v].values[0] else v

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "Noto Sans", sans-serif; margin: 16px; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 8px; }}
  .sub {{ color:#666; font-size:.85rem; margin-bottom:12px; }}
  .bar {{ display:flex; gap:8px; margin:12px 0; flex-wrap:wrap; }}
  a.btn {{ text-decoration:none; padding:10px 14px; border-radius:10px; border:1px solid #ddd; }}
  .table-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid #eee; border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ white-space:nowrap; padding:10px 12px; border-bottom:1px solid #f0f0f0; }}
  th {{ position:sticky; top:0; background:#fafafa; text-align:left; }}
  .neg {{ color:#c0392b; }}
  .pos {{ color:#1e8449; }}
  @media (max-width:480px) {{
    table {{ font-size:13px; }}
    th, td {{ padding:8px 10px; }}
  }}
</style>
</head>
<body>
  <h1>{TITLE}</h1>
  <div class="sub">{SUB}</div>
  <div class="bar">
    <a class="btn" href="{pdf_url}">📄 Download PDF</a>
    <a class="btn" href="table.csv">⬇️ Download CSV</a>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>{"".join(f"<th>{c}</th>" for c in df.columns)}</tr>
      </thead>
      <tbody>
"""
    # 渲染带颜色的 %Chg
    for _, row in df.iterrows():
        tds = []
        for col in df.columns:
            val = row[col]
            if col == "% Chg" and val != "":
                cls = "pos" if float(val) >= 0 else "neg"
                cell = f'<td class="{cls}">{val}%</td>'
            else:
                cell = f"<td>{val}</td>"
            tds.append(cell)
        html += "<tr>" + "".join(tds) + "</tr>\n"

    html += f"""      </tbody>
    </table>
  </div>
  <div class="sub" style="margin-top:10px;color:#888;">Updated at: {datetime.now():%Y-%m-%d %H:%M}</div>
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

# -------------------- Notifications --------------------
def push_serverchan(sendkey, title, content_md):
    if not sendkey:
        log("[SCT] skipped: no key")
        return False
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content_md},
            timeout=15,
        )
        log(f"[SCT] HTTP {r.status_code} | {r.text[:200]}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[SCT] error: {e}")
        return False

def push_pushplus(token, title, content_html):
    if not token:
        log("[PushPlus] skipped: no token")
        return False
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content_html, "template": "html"},
            timeout=15,
        )
        log(f"[PushPlus] HTTP {r.status_code} | {r.text[:200]}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[PushPlus] error: {e}")
        return False

# -------------------- Main --------------------
if __name__ == "__main__":
    try:
        # 1) Tickers: workflow 输入 + peers；否则 NVDA + peers 或 fallback
        base = parse_tickers_env()
        if base:
            expanded = []
            for sym in base:
                expanded.append(sym)
                peers = get_peers_from_finnhub(sym)[:5]  # 每只票最多补 5 个同业
                expanded.extend(peers)
            tickers = list(dict.fromkeys([t.upper() for t in expanded]))[:30]  # 总量限制
        else:
            peers = get_peers_from_finnhub("NVDA")
            tickers = ["NVDA"] + peers[:5] if peers else FALLBACK_TICKERS
        log(f"Tickers: {tickers}")

        # 2) Build table
        df = build_table(tickers)
        log(f"Rows: {len(df)}")

        # 3) Outputs
        df.to_csv("table.csv", index=False); log("Wrote table.csv")
        write_pdf(df, OUT); log(f"Wrote {OUT}")
        report_url = get_env("REPORT_URL") or "report.pdf"
        write_html(df, report_url); log("Wrote index.html")

        # 4) Notifications (可选)
        site_url = get_env("SITE_URL")
        title = "Daily Pivot Levels (Auto Peers)"

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
        log(f"[Notify] ServerChan={ok_sct}  PushPlus={ok_pp}")

    except Exception:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        # 让 workflow fail，便于第一时间看到问题
        raise
