# -*- coding: utf-8 -*-
import os
import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

TICKERS = ["NVDA", "AMD", "TSM", "AVGO", "INTC"]
TITLE   = "NVDA & Peers: Daily Support/Resistance (Pivot Method)"
SUB     = "Formulas: P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
OUT     = "report.pdf"  # fixed name for stable Pages link

# Use default Latin-safe fonts; also ensure minus signs render
matplotlib.rcParams["axes.unicode_minus"] = False

def pivots(h, l, c):
    P  = (h + l + c) / 3
    R1 = 2 * P - l;  S1 = 2 * P - h
    R2 = P + (h - l); S2 = P - (h - l)
    return P, S1, S2, R1, R2

def fetch_latest_row(ticker: str):
    df = yf.download(ticker, period="7d", interval="1d", auto_adjust=False, progress=False)
    last = df.tail(1).reset_index(drop=False).iloc[0]  # avoid FutureWarning
    h = float(last["High"]); l = float(last["Low"]); c = float(last["Close"])
    date_str = (last["Date"].date().isoformat()
                if "Date" in last and hasattr(last["Date"], "date")
                else df.index[-1].date().isoformat())
    return {"Ticker": ticker, "Date": date_str, "High": h, "Low": l, "Close": c}

def build_table(rows):
    for r in rows:
        P, S1, S2, R1, R2 = pivots(r["High"], r["Low"], r["Close"])
        r.update({
            "Pivot P": round(P, 2), "S1": round(S1, 2), "S2": round(S2, 2),
            "R1": round(R1, 2), "R2": round(R2, 2),
            "High": round(r["High"], 2), "Low": round(r["Low"], 2), "Close": round(r["Close"], 2)
        })
    cols = ["Ticker", "Date", "High", "Low", "Close", "Pivot P", "S1", "S2", "R1", "R2"]
    return pd.DataFrame(rows)[cols]

def write_pdf(df, path):
    with PdfPages(path) as pdf:
        # Cover
        plt.figure(figsize=(8.5, 11)); plt.axis("off")
        plt.text(0.5, 0.80, TITLE, ha="center", fontsize=22, fontweight="bold")
        plt.text(0.5, 0.73, SUB, ha="center", fontsize=11)
        plt.text(0.5, 0.67, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
                 ha="center", fontsize=10)
        pdf.savefig(); plt.close()

        # Table page
        plt.figure(figsize=(11, 8.5)); plt.axis("off")
        table = plt.table(cellText=df.values, colLabels=df.columns, loc="center")
        table.auto_set_font_size(False); table.set_fontsize(10); table.scale(1.05, 1.35)
        pdf.savefig(); plt.close()

def push_serverchan(sendkey, title, content_md):
    if not sendkey: return False
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content_md},
            timeout=15
        )
        return r.ok
    except Exception:
        return False

def push_pushplus(token, title, content_html):
    if not token: return False
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content_html, "template": "html"},
            timeout=15
        )
        return r.ok
    except Exception:
        return False

if __name__ == "__main__":
    rows = [fetch_latest_row(t) for t in TICKERS]
    df = build_table(rows)
    write_pdf(df, OUT)

    report_url = os.getenv("REPORT_URL")  # e.g. https://<user>.github.io/<repo>/report.pdf

    title = "NVDA & Peers — Daily Pivot Levels"
    md_msg = f"**{title}**\n\n[Download PDF]({report_url})" if report_url else f"**{title}**\n\n(REPORT_URL not set)"
    html_msg = f"<b>{title}</b><br><a href='{report_url}'>Download PDF</a>" if report_url else f"<b>{title}</b>"

    _ = push_serverchan(os.getenv("WECHAT_SCT_SENDKEY"), title, md_msg)
    _ = push_pushplus(os.getenv("PUSHPLUS_TOKEN"), title, html_msg)
