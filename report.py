# -*- coding: utf-8 -*-
"""
Daily Pivot Levels (Ticker + Peers) — grouped by each seed

Generates:
- report.pdf   (A4 cover + one landscape page per seed group)
- index.html   (responsive; group dropdown; main row blue, S1/R1 near 2% yellow)
- table.csv    (flat table with a 'Group' column)

Env (optional):
- TICKERS            CSV seeds, e.g. "NVDA,TSLA,HD"
- DEFAULT_TICKERS    fallback seeds when TICKERS empty
- FINNHUB_API_KEY    peers API
- SITE_URL           e.g. https://<user>.github.io/<repo>/
- REPORT_URL         e.g. https://<user>.github.io/<repo>/report.pdf
- WECHAT_SCT_SENDKEY ServerChan Turbo key
- PUSHPLUS_TOKEN     PushPlus token

Deps: yfinance, pandas, matplotlib, requests
"""

import os
import sys
import json
import time
import traceback
from typing import List, Dict, Tuple

import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

# -------------------- Global Config --------------------
TITLE = "Daily Pivot Levels (Ticker + Peers)"
SUB   = "P=(H+L+C)/3; S1=2P−H; S2=P−(H−L); R1=2P−L; R2=P+(H−L)"
OUT_PDF = "report.pdf"
OUT_HTML = "index.html"
OUT_CSV = "table.csv"

# PDF 字体与字符
matplotlib.rcParams["axes.unicode_minus"] = False

# 默认备选（当既没有 TICKERS 也没有 DEFAULT_TICKERS）
FALLBACK_SEEDS = ["NVDA", "TSLA", "HD", "TOL", "GOOGL", "AMD", "AMZN", "ADBE", "ASML", "COST", "STZ", "NIO"]

# -------------------- Utils --------------------
def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return (v if v is not None else default).strip()

def split_csv(s: str) -> List[str]:
    if not s:
        return []
    return [x.strip().upper() for x in s.split(",") if x.strip()]

def _as_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")

# -------------------- Data helpers --------------------
def get_peers_from_finnhub(symbol: str, limit: int = 10) -> List[str]:
    key = get_env("FINNHUB_API_KEY")
    if not key:
        return []
    url = f"https://finnhub.io/api/v1/stock/peers?symbol={symbol}&token={key}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        peers = r.json()
        if not isinstance(peers, list):
            return []
        peers = [p.upper() for p in peers if isinstance(p, str)]
        peers = [p for p in peers if p != symbol.upper()]
        return peers[:limit]
    except Exception as e:
        log(f"[Finnhub] {symbol} peers error: {e}")
        return []

def _flatten_ohlc_cols(df: pd.DataFrame) -> pd.DataFrame:
    """兼容 yfinance 单票也返回 MultiIndex 的情况：
       1) ('High','NVDA')  -> 取第 0 层，得到 High/Low/Close...
       2) ('NVDA','High')  -> 取第 1 层，得到 High/Low/Close...
    """
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    try:
        tuples = list(df.columns)
        lvl0 = {c[0] for c in tuples}
        lvl1 = {c[1] for c in tuples}
        fields = {"Open","High","Low","Close","Adj Close","Volume"}

        if fields & lvl0 and len(lvl1) >= 1:
            # ('Field', 'Ticker')
            df.columns = [c[0] for c in tuples]
            return df
        if fields & lvl1 and len(lvl0) >= 1:
            # ('Ticker', 'Field')
            df.columns = [c[1] for c in tuples]
            return df

        # fallback，优先包含 High 的那一层
        if "High" in lvl0:
            df.columns = [c[0] for c in tuples]
        elif "High" in lvl1:
            df.columns = [c[1] for c in tuples]
        else:
            df.columns = [str(c[0]) for c in tuples]
        return df
    except Exception:
        df.columns = [c[0] if isinstance(c, tuple) else str(c) for c in df.columns]
        return df

def fetch_bar(ticker: str) -> Tuple[str, float, float, float, float]:
    """
    Return: (date_str, high, low, close, prev_close)
    兼容 yfinance MultiIndex 列；若没有倒数第二根，则 prev_close = close
    """
    df = yf.download(
        ticker,
        period="14d",
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="column",   # 维持 column 维度，再做拍平
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance empty for {ticker}")

    # 拍平列
    df = _flatten_ohlc_cols(df)

    # reset index，找日期列（Date/Datetime 都兼容）
    df = df.reset_index(drop=False)
    cols_lower = {c.lower(): c for c in df.columns}
    date_col = cols_lower.get("date") or cols_lower.get("datetime")

    last = df.iloc[-1]
    if date_col is not None:
        dt = last[date_col]
    else:
        dt = last.name
    date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]

    def pick(colname: str) -> float:
        # 容错大小写
        for c in df.columns:
            if str(c).lower() == colname.lower():
                return float(last[c])
        raise KeyError(f"column '{colname}' not found in {list(df.columns)}")

    h = _as_float(pick("High"))
    l = _as_float(pick("Low"))
    c = _as_float(pick("Close"))

    if len(df) >= 2:
        prev = df.iloc[-2]
        # 同样容错找 Close
        pc = None
        for ccol in df.columns:
            if str(ccol).lower() == "close":
                pc = float(prev[ccol]); break
        prevc = _as_float(pc if pc is not None else c)
    else:
        prevc = c

    return date_str, h, l, c, prevc

def pivots(h: float, l: float, c: float) -> Tuple[float, float, float, float, float]:
    P = (h + l + c) / 3.0
    S1 = 2 * P - h
    S2 = P - (h - l)
    R1 = 2 * P - l
    R2 = P + (h - l)
    return P, S1, S2, R1, R2

def build_group(seed: str, extra_anchors: List[str] = None) -> pd.DataFrame:
    if extra_anchors is None:
        extra_anchors = []
    group_name = f"{seed.upper()} + Peers"

    peers = get_peers_from_finnhub(seed)
    symbols = [seed.upper()] + [p for p in peers if p] + [a.upper() for a in extra_anchors if a]

    rows = []
    for t in symbols:
        try:
            date_str, h, l, c, prevc = fetch_bar(t)
            P, S1, S2, R1, R2 = pivots(h, l, c)
            chg = (c - prevc) / prevc * 100.0 if (prevc or prevc == 0) and abs(prevc) > 1e-12 else 0.0

            rows.append({
                "Ticker": t,
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
                "Group": group_name,
                "Main": (t == seed.upper()),
            })
        except Exception as e:
            log(f"[Data] skip {t}: {e}")

    if not rows:
        raise RuntimeError(f"No valid rows for group {seed}")

    df = pd.DataFrame(rows)
    df = df.sort_values(by=["Main", "Ticker"], ascending=[False, True]).reset_index(drop=True)
    return df

def build_all(seeds: List[str]) -> List[pd.DataFrame]:
    groups = []
    for s in seeds:
        try:
            df = build_group(s)
            groups.append(df)
            log(f"[Group] {s} ok: {len(df)} rows")
        except Exception as e:
            log(f"[Group] {s} failed: {e}")
    if not groups:
        raise RuntimeError("No groups built. Check network or seed tickers.")
    return groups

# -------------------- Outputs --------------------
def write_csv(groups: List[pd.DataFrame], path: str) -> None:
    all_df = pd.concat(groups, ignore_index=True)
    all_df.to_csv(path, index=False)
    log(f"Wrote {path}")

def write_pdf(groups: List[pd.DataFrame], path: str) -> None:
    with PdfPages(path) as pdf:
        # 封面
        plt.figure(figsize=(8.27, 11.69))
        plt.axis("off")
        plt.text(0.5, 0.80, TITLE, ha="center", fontsize=20, fontweight="bold")
        plt.text(0.5, 0.74, SUB, ha="center", fontsize=10)
        plt.text(0.5, 0.69, f"Generated: {datetime.now():%Y-%m-%d %H:%M}", ha="center", fontsize=9)
        pdf.savefig(bbox_inches="tight"); plt.close()

        # 每个分组一页
        for g in groups:
            plt.figure(figsize=(11.69, 8.27))
            plt.axis("off")
            group_name = g["Group"].iloc[0]
            plt.text(0.02, 0.97, group_name, fontsize=14, fontweight="bold", va="top")
            cols = ["Ticker","Date","High","Low","Close","PrevClose","% Chg","Pivot P","S1","S2","R1","R2"]
            table = plt.table(cellText=g[cols].values, colLabels=cols, loc="center")
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1.2, 1.3)
            pdf.savefig(bbox_inches="tight"); plt.close()
    log(f"Wrote {path}")

def write_html(groups: List[pd.DataFrame], report_url: str, site_url: str) -> None:
    group_names = [g["Group"].iloc[0] for g in groups]
    seeds = [name.split(" + ")[0] for name in group_names]
    chips_html = "".join([f'<a class="chip" href="#sec_{seed}">{seed}</a>' for seed in seeds])

    def table_html(df: pd.DataFrame) -> str:
        rows = []
        for _, r in df.iterrows():
            close = float(r["Close"])
            def near_2pct(x):
                if close == 0 or abs(close) < 1e-12:
                    return False
                return abs(close - float(x)) / abs(close) < 0.02
            cls_main = ' class="main-row"' if bool(r["Main"]) else ""
            cell_s1_cls = ' class="near-cell"' if near_2pct(r["S1"]) else ""
            cell_r1_cls = ' class="near-cell"' if near_2pct(r["R1"]) else ""

            rows.append(
                "<tr{main}>"
                "<td>{t}</td><td>{d}</td>"
                "<td>{h}</td><td>{l}</td><td>{c}</td><td>{pc}</td>"
                "<td class=\"chg {chgcls}\">{chg:.2f}%</td>"
                "<td>{p}</td>"
                f"<td{cell_s1_cls}>{s1}</td>"
                "<td>{s2}</td>"
                f"<td{cell_r1_cls}>{r1}</td>"
                "<td>{r2}</td>"
                "</tr>".format(
                    main=cls_main,
                    t=r["Ticker"], d=r["Date"],
                    h=r["High"], l=r["Low"], c=r["Close"], pc=r["PrevClose"],
                    chg=float(r["% Chg"]),
                    chgcls=("pos" if float(r["% Chg"])>=0 else "neg"),
                    p=r["Pivot P"], s1=r["S1"], s2=r["S2"], r1=r["R1"], r2=r["R2"]
                )
            )
        header = (
            "<thead><tr>"
            "<th>Ticker</th><th>Date</th><th>High</th><th>Low</th><th>Close</th><th>PrevClose</th>"
            "<th>% Chg</th><th>Pivot P</th><th>S1</th><th>S2</th><th>R1</th><th>R2</th>"
            "</tr></thead>"
        )
        return "<table>{hdr}<tbody>{rows}</tbody></table>".format(hdr=header, rows="".join(rows))

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
  body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "Noto Sans", sans-serif;
         margin: 12px 12px 90px; color: var(--text); }}
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

# -------------------- Notifications --------------------
def push_serverchan(sendkey: str, title: str, content_md: str) -> bool:
    if not sendkey:
        return False
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content_md},
            timeout=15,
        )
        log(f"[SCT] HTTP {r.status_code} | {r.text[:180]}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[SCT] error: {e}")
        return False

def push_pushplus(token: str, title: str, content_html: str) -> bool:
    if not token:
        return False
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content_html, "template": "html"},
            timeout=15,
        )
        log(f"[PushPlus] HTTP {r.status_code} | {r.text[:180]}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[PushPlus] error: {e}")
        return False

# -------------------- Main --------------------
if __name__ == "__main__":
    try:
        # 1) 解析 seeds：TICKERS > DEFAULT_TICKERS > FALLBACK_SEEDS
        seeds = split_csv(get_env("TICKERS"))
        if not seeds:
            seeds = split_csv(get_env("DEFAULT_TICKERS"))
        if not seeds:
            seeds = FALLBACK_SEEDS[:]
        seeds = [s for s in seeds if s]

        log(f"Seeds: {seeds}")

        # 2) 组装数据
        groups = build_all(seeds)

        # 3) 输出 CSV / PDF / HTML
        write_csv(groups, OUT_CSV)
        write_pdf(groups, OUT_PDF)

        report_url = get_env("REPORT_URL") or OUT_PDF
        site_url   = get_env("SITE_URL") or ""
        write_html(groups, report_url=report_url, site_url=site_url)

        # 4) 通知（可选）
        title = "Daily Pivot Levels — updated"
        md_msg = (
            f"**{title}**\n\n"
            + (f"[📱 Online view]({site_url})\n\n" if site_url else "")
            + f"[📄 Download PDF]({report_url})"
        )
        html_msg = (
            f"<b>{title}</b><br>"
            + (f"<a href=\"{site_url}\">📱 Online view</a><br>" if site_url else "")
            + f"<a href=\"{report_url}\">📄 Download PDF</a>"
        )
        ok1 = push_serverchan(get_env("WECHAT_SCT_SENDKEY"), title, md_msg)
        ok2 = push_pushplus(get_env("PUSHPLUS_TOKEN"), title, html_msg)
        log(f"[Notify] ServerChan={ok1} PushPlus={ok2}")

    except Exception:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        raise
