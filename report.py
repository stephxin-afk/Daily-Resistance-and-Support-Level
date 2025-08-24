# -*- coding: utf-8 -*-
"""
Generates:
- report.pdf   (A4 cover + one landscape page per seed group)
- index.html   (mobile-friendly, grouped sections, seed row light-blue,
                S1/R1 near-close yellow highlight with adjustable threshold)
- table.csv    (raw data with a 'Group' column = seed, and IsSeed flag)

Env (optional):
- TICKERS            CSV of seed tickers, e.g. "NVDA,TSLA,HD,TOL"
- DEFAULT_TICKERS    fallback seeds when TICKERS is empty
- FINNHUB_API_KEY    peers API key (optional)
- SITE_URL           e.g. https://<user>.github.io/<repo>/
- REPORT_URL         e.g. https://<user>.github.io/<repo>/report.pdf
- WECHAT_SCT_SENDKEY ServerChan Turbo key (optional)
- PUSHPLUS_TOKEN     PushPlus token (optional)

Deps: yfinance, pandas, matplotlib, requests
"""

import os
import sys
import math
import json
import time
import traceback
from datetime import datetime
from typing import Dict, List, Tuple

import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# -------------------- Titles & constants --------------------
TITLE = "Daily Pivot Levels (Ticker + Peers)"
SUB   = "P=(H+L+C)/3; S1=2P−H; S2=P−(H−L); R1=2P−L; R2=P+(H−L)"
OUT_PDF = "report.pdf"
OUT_HTML = "index.html"
OUT_CSV = "table.csv"

# 绝不因负号显示问题导致乱码
matplotlib.rcParams["axes.unicode_minus"] = False

# network 超时
HTTP_TIMEOUT = 12

# peers 上限，避免页面过长；种子本身额外置顶
MAX_PEERS = 12

# -------------------- small utils --------------------
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return (v or "").strip()

def parse_seeds() -> List[str]:
    seeds = get_env("TICKERS")
    if not seeds:
        seeds = get_env("DEFAULT_TICKERS")
    if not seeds:
        # 最终兜底
        seeds = "NVDA,TSLA,HD,TOL"
    arr = [s.strip().upper() for s in seeds.split(",") if s.strip()]
    # 去重保序
    seen = set(); out = []
    for s in arr:
        if s not in seen:
            seen.add(s); out.append(s)
    return out

# -------------------- peers & data --------------------
def get_peers_from_finnhub(seed: str) -> List[str]:
    """Return peers list via Finnhub (may be empty)."""
    key = get_env("FINNHUB_API_KEY")
    if not key:
        return []
    url = f"https://finnhub.io/api/v1/stock/peers?symbol={seed}&token={key}"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        peers = r.json()
        if isinstance(peers, list):
            peers = [p for p in peers if isinstance(p, str)]
            peers = [p.upper() for p in peers if p.upper() != seed.upper()]
            # 限制数量
            return peers[:MAX_PEERS]
        return []
    except Exception as e:
        log(f"[Finnhub] peers error for {seed}: {e}")
        return []

def pivots(h: float, l: float, c: float) -> Tuple[float, float, float, float, float]:
    P = (h + l + c) / 3.0
    R1 = 2 * P - l
    S1 = 2 * P - h
    R2 = P + (h - l)
    S2 = P - (h - l)
    return P, S1, S2, R1, R2

def _as_float(x, default=float("nan")) -> float:
    try:
        return float(x)
    except Exception:
        return default

def fetch_bar(ticker: str) -> Tuple[str, float, float, float, float]:
    """
    Return: (date_str, high, low, close, prev_close)
    使用最近 14 天日线，取最后一根为最新，倒数第二根 close 为前收。
    """
    df = yf.download(ticker, period="14d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty or len(df) < 1:
        raise RuntimeError(f"yfinance empty for {ticker}")

    df = df.reset_index(drop=False)
    # 有些行情列名大小写略有不同，统一处理
    cols = {c.lower(): c for c in df.columns}
    def pick(col):
        c = cols.get(col.lower())
        return df[c] if c in df.columns else df[col]

    last = df.iloc[-1]
    # 日期
    dt = last.get(cols.get("date","Date"), last.name)
    date_str = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]

    # 最新 OHLC
    h = _as_float(last[pick("High")].iloc[0] if isinstance(last[pick("High")], pd.Series) else last[pick("High")])
    l = _as_float(last[pick("Low") ].iloc[0] if isinstance(last[pick("Low") ], pd.Series) else last[pick("Low") ])
    c = _as_float(last[pick("Close")].iloc[0] if isinstance(last[pick("Close")], pd.Series) else last[pick("Close")])

    # 前收：若有倒数第二根，则取其 Close，否则用当前 Close（避免缺失）
    if len(df) >= 2:
        prev = df.iloc[-2]
        prevc = _as_float(prev[pick("Close")].iloc[0] if isinstance(prev[pick("Close")], pd.Series) else prev[pick("Close")])
    else:
        prevc = c

    return date_str, h, l, c, prevc

def make_row(ticker: str) -> Dict[str, object]:
    date_str, h, l, c, prevc = fetch_bar(ticker)
    # 容错：Close <=0 或 NaN，回退为 prevc
    if not (isinstance(c, (int, float)) and math.isfinite(c) and c > 0):
        c = prevc
    P, S1, S2, R1, R2 = pivots(h, l, c)
    chg = (c - prevc) / prevc * 100.0 if (isinstance(prevc, (int,float)) and prevc) else float("nan")
    return {
        "Ticker": ticker,
        "Date": date_str,
        "High": round(h, 2),
        "Low":  round(l, 2),
        "Close": round(c, 2),
        "PrevClose": round(prevc, 2),
        "% Chg": round(chg, 2) if math.isfinite(chg) else "",
        "Pivot P": round(P, 2),
        "S1": round(S1, 2),
        "S2": round(S2, 2),
        "R1": round(R1, 2),
        "R2": round(R2, 2),
    }

def build_group(seed: str) -> pd.DataFrame:
    """
    生成一个分组（种子置顶 + peers）。
    失败的 ticker 自动忽略。
    """
    tickers = [seed] + get_peers_from_finnhub(seed)
    seen = set(); ordered = []
    for t in tickers:
        u = t.upper()
        if u not in seen:
            seen.add(u); ordered.append(u)

    rows = []
    for t in ordered:
        try:
            r = make_row(t)
            r["Group"] = seed
            r["IsSeed"] = (t == seed)
            rows.append(r)
        except Exception as e:
            log(f"[Data] skip {t}: {e}")

    if not rows:
        raise RuntimeError(f"No valid rows for group {seed}")

    cols = ["Ticker","Date","High","Low","Close","PrevClose","% Chg","Pivot P","S1","S2","R1","R2","Group","IsSeed"]
    df = pd.DataFrame(rows)[cols]

    # 种子置顶
    df = df.sort_values(by=["IsSeed","Ticker"], ascending=[False, True]).reset_index(drop=True)
    # 过滤 Close<=0
    df = df[pd.to_numeric(df["Close"], errors="coerce") > 0].reset_index(drop=True)
    return df

def build_all(seeds: List[str]) -> Dict[str, pd.DataFrame]:
    groups: Dict[str, pd.DataFrame] = {}
    for seed in seeds:
        try:
            df = build_group(seed)
            groups[seed] = df
            log(f"[Group] {seed}: {len(df)} rows")
        except Exception as e:
            log(f"[Group] {seed} failed: {e}")
    if not groups:
        raise RuntimeError("No groups built. Check network or seed tickers.")
    return groups

# -------------------- outputs --------------------
def write_csv(groups: Dict[str, pd.DataFrame], path: str):
    frames = []
    for seed, df in groups.items():
        frames.append(df.copy())
    big = pd.concat(frames, ignore_index=True)
    big.to_csv(path, index=False)
    log(f"Wrote {path}")

def _draw_table(ax, df: pd.DataFrame, fontsize=10):
    ax.axis("off")
    table = ax.table(cellText=df.values, colLabels=df.columns, loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)
    table.scale(1.1, 1.3)

def write_pdf(groups: Dict[str, pd.DataFrame], path: str):
    with PdfPages(path) as pdf:
        # 封面（A4 纵向）
        plt.figure(figsize=(8.27, 11.69))
        plt.axis("off")
        plt.text(0.5, 0.78, TITLE, ha="center", fontsize=20, fontweight="bold")
        plt.text(0.5, 0.72, SUB, ha="center", fontsize=11)
        plt.text(0.5, 0.66, f'Generated: {datetime.now():%Y-%m-%d %H:%M}', ha="center", fontsize=9)
        plt.text(0.5, 0.55, "Groups:", ha="center", fontsize=11)
        lines = ", ".join(groups.keys())
        plt.text(0.5, 0.51, lines, ha="center", fontsize=10)
        pdf.savefig(bbox_inches="tight"); plt.close()

        # 每组一页（A4 横向）
        for seed, df in groups.items():
            show_cols = [c for c in df.columns if c not in ("Group","IsSeed")]
            plt.figure(figsize=(11.69, 8.27))
            plt.suptitle(f"{seed} + Peers", fontsize=14, y=0.98)
            ax = plt.gca()
            _draw_table(ax, df[show_cols], fontsize=10)
            pdf.savefig(bbox_inches="tight"); plt.close()
    log(f"Wrote {path}")

def write_html(groups: Dict[str, pd.DataFrame], pdf_url: str, csv_name: str, path: str) -> None:
    def esc(t: str) -> str:
        return (t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                .replace('"',"&quot;").replace("'","&#39;"))

    # 下拉
    options = ["<option value='__ALL__'>All groups</option>"]
    for seed in groups.keys():
        options.append(f"<option value='{esc(seed)}'>{esc(seed)} + Peers</option>")

    # 直达链接
    share_links = []
    for seed in groups.keys():
        share_links.append(f"<a class='mini' data-seed='{esc(seed)}' href='#sec_{esc(seed)}'>{esc(seed)}</a>")

    # 分组段落
    sections = []
    for seed, df in groups.items():
        sec_id = f"sec_{seed}"
        show_cols = [c for c in df.columns if c not in ("Group","IsSeed")]

        thead = "".join(f"<th>{esc(c)}</th>" for c in show_cols)
        rows_html = []
        for _, row in df.iterrows():
            is_seed = bool(row.get("IsSeed", False))
            row_style = ' style="background:#eef6ff;"' if is_seed else ""

            close_val = _as_float(row["Close"], float("nan"))

            def td_cell(col: str, val):
                if col in ("S1","R1"):
                    v = _as_float(val, float("nan"))
                    return (f"<td class='nr' data-col='{col}' "
                            f"data-close='{close_val}' data-val='{v}'>{esc(str(val))}</td>")
                if col == "% Chg":
                    pct = _as_float(val, float("nan"))
                    color = "#1a7f37" if (isinstance(pct, float) and math.isfinite(pct) and pct >= 0) else "#cc0000"
                    return f"<td><span style='color:{color}'>{esc(str(val))}%</span></td>"
                return f"<td>{esc(str(val))}</td>"

            tds = [td_cell(col, row[col]) for col in show_cols]
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
  select, input[type="number"] {{ padding:8px 10px; border-radius:8px; border:1px solid #ddd; }}
  .table-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid #eee; border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ white-space:nowrap; padding:10px 12px; border-bottom:1px solid #f0f0f0; }}
  th {{ position:sticky; top:0; background:#fafafa; text-align:left; }}
  .hl {{ background:#fff7cc; }}
  .shares {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .shares .mini {{ font-size:.92rem; padding:6px 9px; border:1px solid #ddd; border-radius:8px; text-decoration:none; color:#333; }}
  .right {{ margin-left:auto; display:flex; gap:8px; align-items:center; }}
  @media (max-width:480px) {{ table {{ font-size:13px; }} th, td {{ padding:8px 10px; }} }}
</style>
</head>
<body>
  <h1>{esc(TITLE)}</h1>
  <div class="sub">{esc(SUB)}</div>

  <div class="bar">
    <a class="btn" href="{esc(pdf_url)}">📄 Download PDF</a>
    <a class="btn" href="{esc(OUT_CSV)}">⬇️ Download CSV</a>

    <span class="right">
      <label for="groupSel" style="font-size:.95rem;color:#555;">Filter:&nbsp;</label>
      <select id="groupSel" onchange="applyFilter()">
        {''.join(options)}
      </select>

      <label for="thInput" style="font-size:.95rem;color:#555;">Near-threshold (%):&nbsp;</label>
      <input id="thInput" type="number" step="0.1" min="0" value="2">
      <button class="btn" onclick="applyThreshold()">Apply</button>
    </span>
  </div>

  <div class="shares">
    <span style="color:#666;">Share links:</span>
    {''.join(share_links)}
  </div>

  {''.join(sections)}

  <div class="sub" style="margin-top:10px;color:#888;">Updated at: {datetime.now():%Y-%m-%d %H:%M}</div>

<script>
function qparam(name){{
  const u = new URL(location.href);
  const v = u.searchParams.get(name);
  return v;
}}
function setParamAndHash(th, hash){{
  const u = new URL(location.href);
  if (th != null) u.searchParams.set('th', th);
  history.replaceState(null, '', u.toString().split('#')[0] + (hash || ''));
}}
function getThreshold(){{
  const v = parseFloat(qparam('th'));
  return isNaN(v) ? 2.0 : v;
}}
function applyFilter(){{
  var val = document.getElementById('groupSel').value;
  var secs = document.querySelectorAll('section.group');
  secs.forEach(function(s){{
    s.style.display = (val === '__ALL__' || s.dataset.group === val) ? 'block' : 'none';
  }});
}}
function applyThreshold(){{
  const th = parseFloat(document.getElementById('thInput').value || '2');
  const cells = document.querySelectorAll('td.nr[data-col]');
  cells.forEach(function(td){{
    const col = td.dataset.col;
    const close = parseFloat(td.dataset.close);
    const val = parseFloat(td.dataset.val);
    const ok = isFinite(close) && close > 0 && isFinite(val);
    const near = ok ? (Math.abs(close - val) / close * 100.0 < th) : false;
    if (col === 'S1' || col === 'R1'){{
      if (near) td.classList.add('hl'); else td.classList.remove('hl');
    }}
  }});
  setParamAndHash(th, location.hash || '');
}}
function updateShareLinks(){{
  const th = document.getElementById('thInput').value;
  document.querySelectorAll('.shares a.mini').forEach(function(a){{
    const seed = a.dataset.seed;
    const u = new URL(location.href);
    u.searchParams.set('th', th);
    a.href = u.toString().split('#')[0] + '#sec_' + seed;
  }});
}}
(function init(){{
  const th = getThreshold();
  document.getElementById('thInput').value = th;

  var h = location.hash || '';
  if (h.indexOf('#sec_') === 0){{
    var seed = h.replace('#sec_','');
    var sel = document.getElementById('groupSel');
    for (var i=0;i<sel.options.length;i++) {{
      if (sel.options[i].value === seed) {{ sel.selectedIndex = i; break; }}
    }}
  }}
  applyFilter();
  applyThreshold();
  updateShareLinks();
  document.getElementById('thInput').addEventListener('input', updateShareLinks);
}})();
</script>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Wrote {path}")

# -------------------- notifications (optional) --------------------
def push_serverchan(sendkey, title, content_md):
    if not sendkey:
        return False
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": content_md},
            timeout=HTTP_TIMEOUT,
        )
        log(f"[SCT] {r.status_code}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[SCT] error: {e}")
        return False

def push_pushplus(token, title, content_html):
    if not token:
        return False
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content_html, "template": "html"},
            timeout=HTTP_TIMEOUT,
        )
        log(f"[PushPlus] {r.status_code}")
        r.raise_for_status()
        return r.ok
    except Exception as e:
        log(f"[PushPlus] error: {e}")
        return False

# -------------------- main --------------------
if __name__ == "__main__":
    try:
        seeds = parse_seeds()
        log(f"Seeds: {seeds}")

        groups = build_all(seeds)

        # CSV
        write_csv(groups, OUT_CSV)

        # PDF
        write_pdf(groups, OUT_PDF)

        # HTML
        report_url = get_env("REPORT_URL") or OUT_PDF
        write_html(groups, report_url, OUT_CSV, OUT_HTML)

        # Optional push
        site_url = get_env("SITE_URL")
        title = "Daily Pivot Levels — grouped"
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
        ok1 = push_serverchan(get_env("WECHAT_SCT_SENDKEY"), title, md_msg)
        ok2 = push_pushplus(get_env("PUSHPLUS_TOKEN"), title, html_msg)
        log(f"[Notify] ServerChan={ok1} PushPlus={ok2}")

    except Exception:
        log("FATAL ERROR:\n" + "".join(traceback.format_exception(*sys.exc_info())))
        # 让 CI 失败，便于发现问题
        raise
