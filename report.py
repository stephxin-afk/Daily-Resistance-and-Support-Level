# -*- coding: utf-8 -*-

import os
import sys
import traceback
from datetime import datetime, timezone
from typing import List, Dict

import requests
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt


TITLE = "Daily Pivot Levels (Ticker + Peers)"
SUB   = "P=(H+L+C)/3; S1=2P−H; S2=P−(H−L); R1=2P−L; R2=P+(H−L)"
PDF_OUT = "report.pdf"
CSV_OUT = "table.csv"
HTML_OUT = "index.html"

# -------- utilities --------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip()

def csv_to_list(csv_text: str) -> List[str]:
    if not csv_text:
        return []
    items = [x.strip().upper() for x in csv_text.split(",")]
    items = [x for x in items if x]
    # 去重且保序
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

# -------- data: peers + quotes --------
def get_peers_from_finnhub(seed: str, limit: int = 6) -> List[str]:
    key = get_env("FINNHUB_API_KEY")
    if not key:
        return []
    url = f"https://finnhub.io/api/v1/stock/peers?symbol={seed}&token={key}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        peers = []
        for x in data:
            if isinstance(x, str):
                u = x.strip().upper()
                if u and u != seed and u not in peers:
                    peers.append(u)
            if len(peers) >= limit:
                break
        return peers
    except Exception as e:
        log(f"[Finnhub] {seed} peers error: {e}")
        return []

def pivots(h: float, l: float, c: float):
    P = (h + l + c) / 3.0
    R1 = 2 * P - l
    S1 = 2 * P - h
    R2 = P + (h - l)
    S2 = P - (h - l)
    return P, S1, S2, R1, R2

def fetch_one_row(ticker: str) -> Dict[str, float]:
    # 取 14 天，确保能拿到至少两根日K
    df = yf.download(ticker, period="14d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"empty data for {ticker}")
    df = df.dropna()
    if len(df) < 1:
        raise RuntimeError(f"no valid row for {ticker}")
    last = df.iloc[-1]
    # 价格
    h = float(last["High"])
    l = float(last["Low"])
    c = float(last["Close"])
    # 前收（若有上一根）
    if len(df) >= 2:
        prev = float(df.iloc[-2]["Close"])
    else:
        prev = c
    chg_pct = ((c - prev) / prev * 100.0) if prev != 0 else 0.0
    # 日期
    try:
        idx = df.index[-1]
        day = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
    except Exception:
        day = datetime.now().date().isoformat()
    P, S1, S2, R1, R2 = pivots(h, l, c)
    return {
        "Ticker": ticker,
        "Date": day,
        "High": round(h, 2),
        "Low": round(l, 2),
        "Close": round(c, 2),
        "PrevClose": round(prev, 2),
        "% Chg": round(chg_pct, 2),
        "Pivot P": round(P, 2),
        "S1": round(S1, 2),
        "S2": round(S2, 2),
        "R1": round(R1, 2),
        "R2": round(R2, 2),
    }

def build_group(seed: str) -> pd.DataFrame:
    peers = get_peers_from_finnhub(seed)
    tickers = [seed] + peers  # 不再混入跨行业锚点
    rows = []
    for t in tickers:
        try:
            r = fetch_one_row(t)
            r["Group"] = f"{seed} + Peers"
            rows.append(r)
        except Exception as e:
            log(f"[{seed}] fetch {t} failed: {e}")
    if not rows:
        raise RuntimeError(f"[{seed}] no valid rows")
    df = pd.DataFrame(rows)
    # 固定列顺序
    cols = ["Group", "Ticker", "Date", "High", "Low", "Close", "PrevClose", "% Chg", "Pivot P", "S1", "S2", "R1", "R2"]
    df = df[cols].sort_values(["Ticker"]).reset_index(drop=True)
    log(f"[{seed}] rows={len(df)}")
    return df

# -------- outputs: CSV / PDF / HTML --------
def write_csv(df_all: pd.DataFrame, path: str) -> None:
    df_all.to_csv(path, index=False)
    log(f"Wrote {path}")

def _table_to_pdf_page(df: pd.DataFrame, title: str, pdf: PdfPages) -> None:
    plt.figure(figsize=(11.69, 8.27))  # A4 landscape
    plt.axis("off")
    plt.title(title, fontsize=16, pad=12, loc="left")
    table = plt.table(cellText=df.values, colLabels=df.columns, loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.1, 1.3)
    pdf.savefig(bbox_inches="tight")
    plt.close()

def write_pdf(grouped: Dict[str, pd.DataFrame], path: str) -> None:
    with PdfPages(path) as pdf:
        # 封面
        plt.figure(figsize=(8.27, 11.69))  # A4 portrait
        plt.axis("off")
        plt.text(0.5, 0.75, TITLE, ha="center", fontsize=22, fontweight="bold")
        plt.text(0.5, 0.68, SUB, ha="center", fontsize=11)
        plt.text(0.5, 0.62, f"Generated: {datetime.now():%Y-%m-%d %H:%M}", ha="center", fontsize=10)
        pdf.savefig(bbox_inches="tight")
        plt.close()
        # 每个种子一页
        for seed, df in grouped.items():
            # 去掉 Group 列，页面标题已经体现
            df_show = df.drop(columns=["Group"])
            _table_to_pdf_page(df_show, f"{seed} + Peers", pdf)
    log(f"Wrote {path}")

def _html_escape(t: str) -> str:
    return (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

def write_html(grouped: Dict[str, pd.DataFrame], pdf_url: str, csv_name: str, path: str) -> None:
    # 顶部 chips 导航 + 每个种子一个 section
    chips = []
    sections = []

    for seed, df in grouped.items():
        sec_id = f"sec_{seed}"
        chips.append(f'<a class="chip" href="#{sec_id}">{_html_escape(seed)}</a>')

        # 行着色：涨跌幅正绿负红
        thead = "".join(f"<th>{_html_escape(c)}</th>" for c in df.drop(columns=["Group"]).columns)
        body_rows = []
        for _, row in df.drop(columns=["Group"]).iterrows():
            chg = row["% Chg"]
            color = "#1a7f37" if chg >= 0 else "#cc0000"
            tds = []
            for col in df.drop(columns=["Group"]).columns:
                val = row[col]
                s = f"{val}"
                if col == "% Chg":
                    s = f'<span style="color:{color}">{val}%</span>'
                tds.append(f"<td>{s}</td>")
            body_rows.append("<tr>" + "".join(tds) + "</tr>")
        table_html = (
            "<div class='table-wrap'><table>"
            f"<thead><tr>{thead}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table></div>"
        )
        sections.append(
            f"<section id='{sec_id}'><h2>{_html_escape(seed)} + Peers</h2>{table_html}</section>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html_escape(TITLE)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "Noto Sans", sans-serif; margin: 16px; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 8px; }}
  h2 {{ font-size: 1.1rem; margin: 20px 0 10px; }}
  .sub {{ color:#666; font-size:.85rem; margin-bottom:12px; }}
  .bar {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; align-items:center; }}
  .btn {{ text-decoration:none; padding:10px 14px; border-radius:10px; border:1px solid #ddd; }}
  .chips {{ display:flex; gap:8px; flex-wrap:wrap; margin:4px 0 10px; }}
  .chip {{ padding:6px 10px; border-radius:999px; border:1px solid #ddd; background:#fafafa; text-decoration:none; color:#333; }}
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
  <h1>{_html_escape(TITLE)}</h1>
  <div class="sub">{_html_escape(SUB)}</div>

  <div class="bar">
    <a class="btn" href="{_html_escape(pdf_url)}">📄 Download PDF</a>
    <a class="btn" href="{_html_escape(csv_name)}">⬇️ Download CSV</a>
  </div>

  <div class="chips">
    {''.join(chips)}
  </div>

  {''.join(sections)}

  <div class="sub" style="margin-top:10px;color:#888;">Updated at: {datetime.now():%Y-%m-%d %H:%M}</div>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Wrote {path}")

# -------- notifications (optional) --------
def push_serverchan(sendkey: str, title: str, content_md: str) -> bool:
    if not sendkey:
        return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                          data={"title": title, "desp": content_md}, timeout=15)
        log(f"[SCT] {r.status_code} {r.text[:120]}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[SCT] error: {e}")
        return False

def push_pushplus(token: str, title: str, content_html: str) -> bool:
    if not token:
        return False
    try:
        r = requests.post("https://www.pushplus.plus/send",
                          json={"token": token, "title": title, "content": content_html, "template": "html"},
                          timeout=15)
        log(f"[PushPlus] {r.status_code} {r.text[:120]}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[PushPlus] error: {e}")
        return False

# -------- main --------
def main() -> None:
    # 读取种子：优先 TICKERS，其次 DEFAULT_TICKERS
    seeds = csv_to_list(get_env("TICKERS"))
    if not seeds:
        seeds = csv_to_list(get_env("DEFAULT_TICKERS", "NVDA"))
    if not seeds:
        raise RuntimeError("no seeds provided")

    log(f"Seeds: {seeds}")

    grouped = {}
    all_rows = []
    for seed in seeds:
        df = build_group(seed)
        grouped[seed] = df
        all_rows.append(df)

    df_all = pd.concat(all_rows, ignore_index=True)
    write_csv(df_all, CSV_OUT)

    # 输出 PDF
    write_pdf(grouped, PDF_OUT)

    # 输出 HTML
    report_url = get_env("REPORT_URL") or PDF_OUT
    write_html(grouped, report_url, CSV_OUT, HTML_OUT)

    # 推送（可选）
    site_url = get_env("SITE_URL")  # 主页（可选）
    title = "Daily Pivot Levels"
    md_msg = f"**{title}**\n\n"
    if site_url:
        md_msg += f"[📱 Online view]({site_url})\n\n"
    md_msg += f"[📄 Download PDF]({report_url})"

    html_msg = f"<b>{title}</b><br>"
    if site_url:
        html_msg += f"<a href=\"{site_url}\">📱 Online view</a><br>"
    html_msg += f"<a href=\"{report_url}\">📄 Download PDF</a>"

    ok_sct = push_serverchan(get_env("WECHAT_SCT_SENDKEY"), title, md_msg)
    ok_pp  = push_pushplus(get_env("PUSHPLUS_TOKEN"), title, html_msg)
    log(f"[Notify] ServerChan={ok_sct} PushPlus={ok_pp}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        raise
