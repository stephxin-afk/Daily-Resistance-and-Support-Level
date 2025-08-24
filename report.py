# -*- coding: utf-8 -*-
"""
Generates:
- report.pdf   (A4 cover + landscape table page)
- index.html   (mobile-friendly responsive table)
- table.csv    (raw data download)

Optional env (set via GitHub Actions Secrets/Vars):
- FINNHUB_API_KEY        to fetch dynamic peers
- WECHAT_SCT_SENDKEY     (ServerChan Turbo)
- PUSHPLUS_TOKEN         (PushPlus)
- SITE_URL               e.g. https://<user>.github.io/<repo>/
- REPORT_URL             e.g. https://<user>.github.io/<repo>/report.pdf

Deps: yfinance, pandas, matplotlib, requests
"""

import os
import sys
import re
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
TITLE = "NVDA & Peers: Daily Support / Resistance (Pivot Method)"
SUB   = "Formulas: P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
OUT_PDF = "report.pdf"
OUT_HTML = "index.html"
OUT_CSV  = "table.csv"

# Fallback peers when no API key or API fails
FALLBACK_TICKERS = ["NVDA", "AMD", "TSM", "AVGO", "INTC"]

# Make minus signs render
matplotlib.rcParams["axes.unicode_minus"] = False


# -------------------- Utils --------------------
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    if v is None:
        v = default
    return str(v).strip()


def build_site_base() -> str:
    """
    Build base site url for absolute links.
    Priority:
      1) SITE_URL (if provided)
      2) https://<owner>.github.io/<repo> derived from GITHUB_REPOSITORY
    """
    site = get_env("SITE_URL")
    if site:
        return site.rstrip("/")

    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, reponame = repo.split("/", 1)
        return f"https://{owner}.github.io/{reponame}".rstrip("/")
    return ""


def absolutize(url_like: str, site_base: str) -> str:
    """Turn a relative path into an absolute URL; keep http(s) as-is."""
    if not url_like:
        return ""
    if re.match(r"^https?://", url_like, re.I):
        return url_like
    if site_base:
        return f"{site_base}/{url_like.lstrip('/')}"
    return url_like


# -------------------- Data: peers + quotes --------------------
def get_peers_from_finnhub(symbol: str = "NVDA"):
    """Fetch peers via Finnhub company-peers API. Returns list[str]."""
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


def pivots(h: float, l: float, c: float):
    P  = (h + l + c) / 3.0
    R1 = 2 * P - l
    S1 = 2 * P - h
    R2 = P + (h - l)
    S2 = P - (h - l)
    return P, S1, S2, R1, R2


def fetch_latest_row(ticker: str):
    """
    Return dict:
      {Ticker, Date, High, Low, Close, PrevClose, Change%, ...}
    Using last two daily bars to compute % change.
    """
    df = yf.download(ticker, period="10d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty or len(df) < 1:
        raise RuntimeError(f"yfinance returned empty for {ticker}")

    dfl = df.dropna()
    last = dfl.tail(1)
    # If available, get previous close for change%
    prev = dfl.tail(2).head(1) if len(dfl) >= 2 else None

    # Use iloc[0] to avoid FutureWarning
    last_row = last.reset_index(drop=False).iloc[0]

    h = float(last_row["High"])
    l = float(last_row["Low"])
    c = float(last_row["Close"])
    prev_close = float(prev["Close"].iloc[0]) if prev is not None and not prev.empty else float("nan")

    # Date string
    dt = last_row["Date"] if "Date" in last_row else last.index[-1]
    date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]

    # Change %
    chg_pct = None
    if prev is not None and not pd.isna(prev_close) and prev_close != 0:
        chg_pct = round((c - prev_close) / prev_close * 100.0, 2)

    return {
        "Ticker": ticker,
        "Date": date_str,
        "High": h,
        "Low": l,
        "Close": c,
        "Prev Close": prev_close,
        "Chg %": chg_pct,
    }


def build_table(tickers):
    rows = []
    for t in tickers:
        try:
            r = fetch_latest_row(t)
            P, S1, S2, R1, R2 = pivots(r["High"], r["Low"], r["Close"])
            r.update({
                "Pivot P": round(P, 2),
                "S1": round(S1, 2),
                "S2": round(S2, 2),
                "R1": round(R1, 2),
                "R2": round(R2, 2),
                "High": round(r["High"], 2),
                "Low": round(r["Low"], 2),
                "Close": round(r["Close"], 2),
                "Prev Close": round(r["Prev Close"], 2) if not pd.isna(r["Prev Close"]) else "",
                "Chg %": r["Chg %"] if r["Chg %"] is not None else "",
            })
            rows.append(r)
        except Exception as e:
            log(f"Fetch failed for {t}: {e}")

    if not rows:
        raise RuntimeError("No rows collected. Check network or tickers.")

    cols = [
        "Ticker", "Date", "High", "Low", "Close", "Prev Close", "Chg %",
        "Pivot P", "S1", "S2", "R1", "R2"
    ]
    return pd.DataFrame(rows)[cols].sort_values(["Ticker"], ascending=True).reset_index(drop=True)


# -------------------- Outputs: PDF / HTML / CSV --------------------
def write_pdf(df: pd.DataFrame, path: str):
    """A4 cover (portrait) + table (landscape)."""
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
        table.set_fontsize(10.5)
        table.scale(1.18, 1.35)  # readable but compact
        pdf.savefig(bbox_inches="tight"); plt.close()


def write_html(df: pd.DataFrame, pdf_url_abs: str):
    """Responsive, mobile-friendly index.html with sticky header & horizontal scroll."""
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<style>
  :root {{ --radius: 12px; }}
  body {{ font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,"Noto Sans",sans-serif; margin: 16px; }}
  h1 {{ font-size: 1.15rem; margin: 0 0 8px; }}
  .sub {{ color:#666; font-size:.85rem; margin-bottom:10px; }}
  .bar {{ display:flex; gap:8px; margin:12px 0; flex-wrap:wrap; }}
  a.btn {{ text-decoration:none; padding:10px 14px; border-radius:var(--radius); border:1px solid #ddd; }}
  .wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid #eee; border-radius:var(--radius); }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ white-space:nowrap; padding:10px 12px; border-bottom:1px solid #f1f1f1; }}
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
    <a class="btn" href="{pdf_url_abs}">📄 Download PDF</a>
    <a class="btn" href="table.csv">⬇️ Download CSV</a>
  </div>
  <div class="wrap">
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
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


# -------------------- Notifications --------------------
def push_serverchan(sendkey: str, title: str, content_md: str):
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


def push_pushplus(token: str, title: str, content_html: str):
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

        # 3) Outputs to workspace
        df.to_csv(OUT_CSV, index=False)
        log(f"Wrote {OUT_CSV}")

        write_pdf(df, OUT_PDF)
        log(f"Wrote {OUT_PDF}")

        # Absolute URLs for notifications & HTML button
        site_base = build_site_base()
        report_url_raw = get_env("REPORT_URL") or OUT_PDF  # may be relative
        report_url_abs = absolutize(report_url_raw, site_base)
        site_url_abs   = absolutize(get_env("SITE_URL") or "/", site_base)

        write_html(df, report_url_abs)
        log(f"Wrote {OUT_HTML}")

        # 4) Notifications (ensure absolute direct link to PDF)
        title = "NVDA & Peers — Daily Pivot Levels"
        md_msg   = f"[📄 Download PDF]({report_url_abs})\n\n{report_url_abs}\n\n[📱 Online view]({site_url_abs})"
        html_msg = f"<a href='{report_url_abs}'>📄 Download PDF</a><br>{report_url_abs}<br><a href='{site_url_abs}'>📱 Online view</a>"

        ok_sct = push_serverchan(get_env("WECHAT_SCT_SENDKEY"), title, md_msg)
        ok_pp  = push_pushplus(get_env("PUSHPLUS_TOKEN"), title, html_msg)
        log(f"[Notify] ServerChan={ok_sct}  PushPlus={ok_pp}")

    except Exception:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        # re-raise to make CI job fail clearly
        raise
