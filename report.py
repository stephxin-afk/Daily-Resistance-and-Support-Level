# -*- coding: utf-8 -*-
"""
Daily Pivot Levels (seed + peers)
Outputs:
  - table.csv      : flat table for all groups
  - report.pdf     : one page per group
  - index.html     : one section per seed, with filter & highlighting

Env (optional):
  TICKERS           CSV of seed tickers, e.g. "NVDA,TSLA,HD"
  DEFAULT_TICKERS   fallback when TICKERS empty
  FINNHUB_API_KEY   peer API (optional)
  SITE_URL          e.g. https://<user>.github.io/<repo>/
  REPORT_URL        e.g. https://<user>.github.io/<repo>/report.pdf
"""

from __future__ import annotations
import os
import sys
import math
import json
import time
import textwrap
from datetime import datetime
from typing import List, Dict, Tuple

import requests
import pandas as pd
import numpy as np
import yfinance as yf

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


TITLE = "Daily Pivot Levels (Ticker + Peers)"
SUB   = "Formulas: P=(H+L+C)/3; S1=2P−H; S2=P−(H−L); R1=2P−L; R2=P+(H−L)"

OUT_CSV  = "table.csv"
OUT_PDF  = "report.pdf"
OUT_HTML = "index.html"


# ------------------------ utilities ------------------------

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def env_csv(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


# ------------------------ peers ------------------------

# 少量安全锚点（当 Finnhub 不可用时）
FALLBACK_PEERS: Dict[str, List[str]] = {
    "NVDA": ["AMD", "AVGO", "QCOM", "MU", "TXN", "ADI", "INTC", "MRVL", "MPWR"],
    "TSLA": ["GM", "F", "RIVN", "LCID", "NWTN", "THO", "WGO"],
    "HD":   ["LOW", "FND", "TTSH", "GRWG", "POLCQ"],
    "TOL":  ["DHI", "LEN", "PHM", "NVR", "BLD", "IBP", "TMHC", "MTH", "KBH", "SKY"],
    "GOOGL":["META", "RDDT", "PINS", "SNAP", "MTCH", "DJT", "CARG", "RUM", "GRND"],
    "AMD":  ["NVDA", "AVGO", "TXN", "QCOM", "MU", "ADI", "INTC", "MRVL", "MPWR"],
    "AMZN": ["CPNG", "EBAY", "DDS", "OLLI", "ETSY", "M", "KSS", "GRPN", "LOGC"],
    "ADBE": ["PLTR", "CRM", "INTU", "APP", "SNPS", "MSTR", "CDNS", "ADSK", "WDAY", "ROP"],
    "ASML": ["ASML.AS", "ASM.AS", "BESI.AS"],
    "COST": ["WMT", "TGT", "DG", "DLTR", "BJ", "PSMT", "OBDP"],
    "STZ":  ["BF.B", "MGPI", "CWGL", "BLNE", "WVVI", "AMZE", "SBEV", "CASK", "RSAU"],
    "NIO":  ["XPEV", "1958.HK", "600006.SS", "000550.SZ", "000980.SZ", "000572.SZ",
             "ZK", "300825.SZ", "301322.SZ", "600303.SS"],
}

def finnhub_peers(seed: str, api_key: str) -> List[str]:
    """Try Finnhub peers; return [] on failure."""
    try:
        url = "https://finnhub.io/api/v1/stock/peers"
        params = {"symbol": seed.upper(), "token": api_key}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            # 保守过滤（英文字母和点）
            peers = [x.upper() for x in data if isinstance(x, str) and len(x) <= 12]
            # 去掉自己
            peers = [p for p in peers if p != seed.upper()]
            return peers[:20]
    except Exception as e:
        log(f"[Peers] fallback for {seed}: {e}")
    return []


def get_peers(seed: str, api_key: str | None) -> List[str]:
    peers: List[str] = []
    if api_key:
        peers = finnhub_peers(seed, api_key)
    if not peers:
        peers = FALLBACK_PEERS.get(seed.upper(), [])
    return peers


# ------------------------ data & pivots ------------------------

def latest_row(symbol: str, period: str = "14d") -> Tuple[bool, Dict[str, float] | str]:
    """Fetch latest OHLC + prev close for one ticker. Return (ok, data or reason)."""
    try:
        # 使用单票 history，避免 yfinance download 的 MultiIndex 细节
        df = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
        if df is None or df.empty or not all(col in df.columns for col in ("High", "Low", "Close")):
            return False, f"yfinance empty for {symbol}"
        # 取最近两条（用倒数第一作为最新，倒数第二为 prev）
        df = df.tail(2)
        if df.shape[0] == 1:
            h = float(df["High"].iloc[-1])
            l = float(df["Low"].iloc[-1])
            c = float(df["Close"].iloc[-1])
            prev = c  # 没有前一日就等于自身，后续 %Chg=0
        else:
            h = float(df["High"].iloc[-1])
            l = float(df["Low"].iloc[-1])
            c = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])

        # 保护
        h = float(h); l = float(l); c = float(c); prev = float(prev)

        # Pivot
        p = (h + l + c) / 3.0
        s1 = 2 * p - h
        s2 = p - (h - l)
        r1 = 2 * p - l
        r2 = p + (h - l)
        denom = prev if abs(prev) > 1e-12 else 1.0
        chg = (c - prev) / denom * 100.0

        return True, {
            "Date": datetime.utcnow().strftime("%Y-%m-%d"),
            "High": round(h, 2),
            "Low": round(l, 2),
            "Close": round(c, 2),
            "PrevClose": round(prev, 2),
            "% Chg": round(chg, 2),
            "Pivot P": round(p, 2),
            "S1": round(s1, 2),
            "S2": round(s2, 2),
            "R1": round(r1, 2),
            "R2": round(r2, 2),
        }
    except Exception as e:
        # yfinance 会偶现 missing error
        if "possibly delisted" in str(e):
            return False, f"yfinance empty for {symbol}"
        return False, f"{type(e).__name__}: {e}"


def build_group(seed: str, anchors: List[str]) -> pd.DataFrame | None:
    tickers = [seed.upper()] + [t for t in anchors if t.upper() != seed.upper()]
    keep_records = []
    for t in tickers:
        ok, data_or_reason = latest_row(t)
        if not ok:
            log(f"[Data] skip {t}: {data_or_reason}")
            continue
        row = {"Ticker": t, **(data_or_reason)}  # type: ignore
        row["Main"] = (t == seed.upper())
        keep_records.append(row)

    if not keep_records:
        log(f"[Group] {seed} failed: No valid rows for group {seed}")
        return None

    df = pd.DataFrame(keep_records)
    # 将主票放第一行
    df.sort_values(by=["Main", "Ticker"], ascending=[False, True], inplace=True)
    df.insert(0, "Group", f"{seed.upper()} + Peers")
    return df


def build_all(seeds: List[str]) -> List[pd.DataFrame]:
    api_key = os.getenv("FINNHUB_API_KEY", "").strip() or None
    groups: List[pd.DataFrame] = []
    for seed in seeds:
        peers = get_peers(seed, api_key)
        df = build_group(seed, peers)
        if df is not None and not df.empty:
            log(f"[Group] {seed} ok: {len(df)} rows")
            groups.append(df)
    if not groups:
        raise RuntimeError("No groups built. Check network or seed tickers.")
    return groups


# ------------------------ write CSV ------------------------

def write_csv(groups: List[pd.DataFrame]) -> None:
    all_df = pd.concat(groups, ignore_index=True)
    all_df.to_csv(OUT_CSV, index=False)
    log(f"Wrote {OUT_CSV}")


# ------------------------ write PDF ------------------------

def draw_table_page(pdf: PdfPages, title: str, df: pd.DataFrame) -> None:
    # 生成一个简洁的表格页
    cols = ["Ticker", "Date", "High", "Low", "Close", "PrevClose", "% Chg", "Pivot P", "S1", "S2", "R1", "R2"]
    df_print = df[cols].copy()

    fig, ax = plt.subplots(figsize=(11.0, 7.5))  # 横向 A4 大致比例
    ax.axis("off")
    ax.set_title(title, fontsize=14, loc="left", pad=10)

    # matplotlib table
    tbl = ax.table(cellText=df_print.values,
                   colLabels=df_print.columns,
                   loc="center",
                   cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.3)

    # 高亮主票行
    for i, is_main in enumerate(df["Main"].tolist(), start=1):  # +1 跳过表头行
        if is_main:
            for j in range(len(cols)):
                tbl[(i, j)].set_facecolor("#e8f2ff")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def write_pdf(groups: List[pd.DataFrame]) -> None:
    with PdfPages(OUT_PDF) as pdf:
        # 封面
        fig, ax = plt.subplots(figsize=(11.0, 7.5))
        ax.axis("off")
        ax.text(0.02, 0.92, TITLE, fontsize=20, weight="bold", va="top")
        ax.text(0.02, 0.86, SUB, fontsize=11)
        ax.text(0.02, 0.82, f"Generated: {datetime.now():%Y-%m-%d %H:%M}", fontsize=10, color="#666")
        seeds = [g["Group"].iloc[0].split(" + ")[0] for g in groups]
        chips = "  ".join(seeds)
        ax.text(0.02, 0.74, f"Groups: {chips}", fontsize=11)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        for g in groups:
            draw_table_page(pdf, g["Group"].iloc[0], g)

    log(f"Wrote {OUT_PDF}")


# ------------------------ write HTML ------------------------

def write_html(groups: List[pd.DataFrame], report_url: str, site_url: str) -> None:
    group_names = [g["Group"].iloc[0] for g in groups]
    seeds = [name.split(" + ")[0] for name in group_names]
    chips_html = "".join([f'<a class="chip" href="#sec_{seed}">{seed}</a>' for seed in seeds])

    def table_html(df: pd.DataFrame) -> str:
        rows = []
        for _, r in df.iterrows():
            close = float(r["Close"])
            denom = abs(close) if abs(close) > 1e-9 else 1.0

            def near_2pct(x) -> bool:
                try:
                    return abs(close - float(x)) / denom < 0.02
                except Exception:
                    return False

            main_attr    = ' class="main-row"' if bool(r["Main"]) else ""
            s1_cell_attr = ' class="near-cell"' if near_2pct(r["S1"]) else ""
            r1_cell_attr = ' class="near-cell"' if near_2pct(r["R1"]) else ""
            chg = float(r["% Chg"])
            chgcls = "pos" if chg >= 0 else "neg"

            row = (
                f"<tr{main_attr}>"
                f"<td>{r['Ticker']}</td><td>{r['Date']}</td>"
                f"<td>{r['High']}</td><td>{r['Low']}</td><td>{r['Close']}</td><td>{r['PrevClose']}</td>"
                f"<td class=\"chg {chgcls}\">{chg:.2f}%</td>"
                f"<td>{r['Pivot P']}</td>"
                f"<td{s1_cell_attr}>{r['S1']}</td>"
                f"<td>{r['S2']}</td>"
                f"<td{r1_cell_attr}>{r['R1']}</td>"
                f"<td>{r['R2']}</td>"
                "</tr>"
            )
            rows.append(row)

        header = (
            "<thead><tr>"
            "<th>Ticker</th><th>Date</th><th>High</th><th>Low</th>"
            "<th>Close</th><th>PrevClose</th><th>% Chg</th><th>Pivot P</th>"
            "<th>S1</th><th>S2</th><th>R1</th><th>R2</th>"
            "</tr></thead>"
        )
        return f"<table>{header}<tbody>{''.join(rows)}</tbody></table>"

    sections = []
    for g in groups:
        seed = g["Group"].iloc[0].split(" + ")[0]
        sec = (
            f'<section class="group" id="sec_{seed}" data-group="{g["Group"].iloc[0]}">'
            f'<h2>{g["Group"].iloc[0]}</h2>'
            f'{table_html(g)}'
            "</section>"
        )
        sections.append(sec)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<style>
  :root {{
    --blue-soft: #e8f2ff;
    --yellow-soft: #fff6cf;
    --pos: #1a7f37;
    --neg: #b54708;
    --border: #eee;
    --text: #222;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "Noto Sans", sans-serif;
    margin: 12px 12px 90px; color: var(--text);
  }}
  h1 {{ font-size: 1.25rem; margin: 0 0 4px; }}
  .sub {{ color:#666; font-size:.85rem; margin-bottom:10px; }}
  .bar {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }}
  .btn {{ text-decoration:none; padding:9px 12px; border-radius:10px; border:1px solid var(--border); }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 12px; }}
  .chip {{ display:inline-block; padding:6px 10px; border:1px solid var(--border); border-radius:999px; text-decoration:none; }}
  .controls {{ display:flex; gap:8px; align-items:center; margin:8px 0 12px; }}
  select, option {{ font-size: .95rem; }}
  .group {{ margin-top:16px; border-top:1px solid var(--border); padding-top:10px; }}
  h2 {{ font-size:1.05rem; margin:0 0 8px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ white-space:nowrap; padding:8px 10px; border-bottom:1px solid var(--border); text-align:left; }}
  thead th {{ position: sticky; top: 0; background:#fafafa; }}
  tr.main-row td {{ background: var(--blue-soft); }}
  td.near-cell {{ background: var(--yellow-soft); }}
  td.chg.pos {{ color: var(--pos); font-weight:600; }}
  td.chg.neg {{ color: var(--neg); font-weight:600; }}
  .footer {{ margin-top:10px; color:#888; font-size:.85rem; }}
  @media (max-width: 480px) {{
    table {{ font-size:13px; }}
    th, td {{ padding:7px 8px; }}
  }}
</style>
</head>
<body>
  <h1>{TITLE}</h1>
  <div class="sub">{SUB}</div>

  <div class="bar">
    <a class="btn" href="{report_url}">📄 Download PDF</a>
    <a class="btn" href="table.csv">⬇️ Download CSV</a>
  </div>

  <div class="chips">{chips_html}</div>

  <div class="controls">
    <label for="groupSel">Filter group:</label>
    <select id="groupSel">
      <option value="ALL">ALL</option>
      {"".join(f'<option value="{n}">{n}</option>' for n in group_names)}
    </select>
  </div>

  {"".join(sections)}

  <div class="footer">Updated at: {datetime.now():%Y-%m-%d %H:%M}</div>

<script>
  const sel = document.getElementById('groupSel');
  const secs = Array.from(document.querySelectorAll('section.group'));
  sel.addEventListener('change', () => {{
    const v = sel.value;
    secs.forEach(s => {{
      s.style.display = (v === 'ALL' || s.dataset.group === v) ? '' : 'none';
    }});
    if (v !== 'ALL') {{
      const id = '#sec_' + (v.split(' + ')[0]);
      const tgt = document.querySelector(id);
      if (tgt) {{ location.hash = id; }}
    }}
  }});
</script>
</body>
</html>"""
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Wrote {OUT_HTML}")


# ------------------------ main ------------------------

def main() -> None:
    seeds = env_csv("TICKERS")
    if not seeds:
        seeds = env_csv("DEFAULT_TICKERS", "NVDA,TSLA,HD,TOL,GOOGL,AMD,AMZN,ADBE,ASML,COST,STZ,NIO")
    log(f"Seeds: {seeds}")

    groups = build_all(seeds)
    write_csv(groups)

    # report URL / site URL
    site_url   = os.getenv("SITE_URL", "").strip()
    report_url = os.getenv("REPORT_URL", "").strip() or (site_url.rstrip("/") + "/report.pdf" if site_url else "report.pdf")

    write_pdf(groups)
    write_html(groups, report_url=report_url, site_url=site_url)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL ERROR:")
        import traceback
        traceback.print_exc()
        sys.exit(1)
