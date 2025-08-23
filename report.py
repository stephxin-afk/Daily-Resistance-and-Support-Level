# -*- coding: utf-8 -*-
"""
Generates:
- report.pdf   (A4 cover + landscape table page)
- index.html   (mobile-friendly responsive table)
- table.csv    (raw data download)

Optional env:
- FINNHUB_API_KEY   to fetch dynamic peers
- REPORT_URL        e.g. https://<user>.github.io/<repo>/report.pdf
- SITE_URL          e.g. https://<user>.github.io/<repo>/
- WECHAT_SCT_SENDKEY (ServerChan Turbo)
- PUSHPLUS_TOKEN     (PushPlus)

Deps: yfinance, pandas, matplotlib, requests
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime

import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# -------------------- Config --------------------
TITLE = "NVDA & Peers: Daily Support/Resistance (Pivot Method)"
SUB   = "Formulas: P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
OUT   = "report.pdf"

# Fallback peers when no API key or API fails
FALLBACK_TICKERS = ["NVDA", "AMD", "TSM", "AVGO", "INTC"]

# Make minus signs render
matplotlib.rcParams["axes.unicode_minus"] = False


# -------------------- Utils --------------------
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_env(name, default=""):
    v = os.getenv(name, default)
    if v is None:
        v = default
    return v.strip()


# -------------------- Data: peers + quotes --------------------
def get_peers_from_finnhub(symbol="NVDA"):
    """Fetch peers via Finnhub company-peers API.
    Returns list[str] tickers or [] if unavailable.
    """
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
            # Finnhub may return the symbol itself in the list; ensure unique + keep reasonable length
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


def fetch_latest_row(ticker):
    """Return dict with High/Low/Close for the most recent daily bar."""
    df = yf.download(ticker, period="7d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    last = df.tail(1).reset_index(drop=False).iloc[0]
    # Convert to float explicitly (avoid FutureWarning)
    h = float(last["High"])
    l = float(last["Low"])
    c = float(last["Close"])
    # Date string
    dt = last["Date"] if "Date" in last else df.index[-1]
    date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
    return {"Ticker": ticker, "Date": date_str, "High": h, "Low": l, "Close": c}


def build_table(tickers):
    rows = []
    for t in tickers:
        try:
            r = fetch_latest_row(t)
            P, S1, S2, R1, R2 = pivots(r["High"], r["Low"], r["Close"])
            r.update({
                "Pivot P": round(P, 2), "S1": round(S1, 2), "S2": round(S2, 2),
                "R1": round(R1, 2), "R2": round(R2, 2),
                "High": round(r["High"], 2), "Low": round(r["Low"], 2), "Close": round(r["Close"], 2)
            })
            rows.append(r)
        except Exception as e:
            log(f"Fetch failed for {t}: {e}")
    if not rows:
        raise RuntimeError("No rows collected. Check network or tickers.")
    cols = ["Ticker", "Date", "High", "Low", "Close", "Pivot P", "S1", "S2", "R1", "R2"]
    return pd.DataFrame(rows)[cols].sort_values(["Ticker"], ascending=True).reset_index(drop=True)


# -------------------- Outputs: PDF / HTML / CSV --------------------
def write_pdf(df, path):
    """A4 cover (portrait) + table page (landscape), tighter margins for readability."""
    with PdfPages(path) as pdf:
        # Cover (A4 portrait: 8.27 x 11.69 inches)
        plt.figure(figsize=(8.27, 11.69))
        plt.axis("off")
        plt.text(0.5, 0.80, TITLE, ha="center", fontsize=20, fontweight="bold")
        plt.text(0.5, 0.73, SUB, ha="center", fontsize=10)
        plt.text(0.5, 0.68, f'Generated: {datetime.now():%Y-%m-%d %H:%M}', ha="center", fontsize=9)
        pdf.savefig(bbox_inches="tight"); plt.close()

        # Table (A4 landscape: 11.69 x 8.27 inches)
        plt.figure(figsize=(11.69, 8.27))
        plt.axis("off")
        table = plt.table(cellText=df.values, colLabels=df.columns, loc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1.2, 1.4)  # enlarge for small screens
        pdf.savefig(bbox_inches="tight"); plt.close()


def write_html(df, pdf_url):
    """Responsive, mobile-friendly index.html with sticky header and horizontal scroll."""
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
        { "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in df.values) }
      </tbody>
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
        # 1) Tickers: Finnhub peers (optional) + fallback
        peers = get_peers_from_finnhub("NVDA")
        tickers = ["NVDA"] + peers[:5] if peers else FALLBACK_TICKERS
        log(f"Tickers: {tickers}")

        # 2) Build table
        df = build_table(tickers)
        log(f"Rows: {len(df)}")

        # 3) Outputs
        # CSV for reuse / download
        df.to_csv("table.csv", index=False)
        log("Wrote table.csv")

        # PDF (cover + landscape table)
        write_pdf(df, OUT)
        log(f"Wrote {OUT}")

        # HTML (mobile-friendly)
        report_url = get_env("REPORT_URL") or "report.pdf"
        write_html(df, report_url)
        log("Wrote index.html")

        # 4) Notifications
        site_url = get_env("SITE_URL")  # optional homepage
        title = "NVDA & Peers — Daily Pivot Levels"

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

    except Exception as e:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        # Re-raise to fail the workflow, so你能第一时间看到错误
        raise
