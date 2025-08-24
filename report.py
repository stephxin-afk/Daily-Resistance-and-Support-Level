# -*- coding: utf-8 -*-
"""
Daily generator for:
- report.pdf     (A4 cover + landscape table; default topic: NVDA & peers)
- index.html     (interactive UI: enter tickers to view chosen tickers + their peers)
- table.csv      (full universe data for the day)
- peers.json     (ticker -> peers list; built with Finnhub if API key provided)

Optional env:
- FINNHUB_API_KEY    to fetch dynamic peers
- SITE_URL           e.g. https://<user>.github.io/<repo>/
- REPORT_URL         e.g. https://<user>.github.io/<repo>/report.pdf
- WECHAT_SCT_SENDKEY (ServerChan Turbo)  [optional]
- PUSHPLUS_TOKEN     (PushPlus)           [optional]

Deps: yfinance, pandas, matplotlib, requests
"""

import os, sys, json, traceback
from datetime import datetime

import requests
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ---------- Display texts ----------
TITLE = "Daily Pivot Levels — NVDA & Peers"
SUB   = "P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
PDF_OUT = "report.pdf"

matplotlib.rcParams["axes.unicode_minus"] = False

# ---------- Universe seed ----------
# 作为全量数据的“起点”，每天我们会对这些种子和它们的同业一起抓取数据
SEED_TICKERS = [
    "NVDA","AMD","TSM","AVGO","INTC","QCOM","ASML","MU","ADI","TXN",
    "AMAT","LRCX","NXPI","MRVL","ON","ARM","SNPS","CDNS"
]

# ---------- Utils ----------
def log(s): print(f"[{datetime.now():%H:%M:%S}] {s}", flush=True)
def getenv(name, default=""): return (os.getenv(name) or default).strip()

# ---------- Data ----------
def finnhub_peers(symbol, key, limit=10):
    """Use Finnhub company peers. Returns list or []."""
    if not key: return []
    url = f"https://finnhub.io/api/v1/stock/peers?symbol={symbol}&token={key}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()
        peers = [p.upper() for p in data if isinstance(p, str) and p.upper()!=symbol.upper()]
        return peers[:limit]
    except Exception as e:
        log(f"Finnhub peers error for {symbol}: {e}")
        return []

def build_peers_map(seeds, key):
    """Return dict: ticker -> peers (list)."""
    mp = {}
    for s in seeds:
        ps = finnhub_peers(s, key, limit=10)
        mp[s] = ps
    # 让每个 peer 也有同业（避免页面上只输入 peer 时没有映射）
    if key:
        unique = sorted(set([p for v in mp.values() for p in v]))
        for p in unique:
            if p not in mp:
                mp[p] = finnhub_peers(p, key, limit=10)
    return mp

def yq_latest_row(ticker):
    df = yf.download(ticker, period="7d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"Empty from yfinance: {ticker}")
    last = df.tail(2)  # 用两天算涨跌幅
    last = last.reset_index(drop=False)
    cur = last.iloc[-1]; prev = last.iloc[-2] if len(last)>=2 else None
    h, l, c = float(cur["High"]), float(cur["Low"]), float(cur["Close"])
    pclose = float(prev["Close"]) if prev is not None else None
    chg = (c/pclose-1.0)*100 if pclose else None
    dt = cur["Date"] if "Date" in cur else df.index[-1]
    dstr = dt.date().isoformat() if hasattr(dt,"date") else str(dt)[:10]
    return {"Ticker":ticker, "Date":dstr, "High":h, "Low":l, "Close":c, "Change%": (round(chg,2) if chg is not None else None)}

def pivots(h,l,c):
    P  = (h+l+c)/3.0
    R1 = 2*P - l; S1 = 2*P - h
    R2 = P + (h-l); S2 = P - (h-l)
    return P,S1,S2,R1,R2

def build_table(universe):
    rows=[]
    for t in sorted(set(universe)):
        try:
            r = yq_latest_row(t)
            P,S1,S2,R1,R2 = pivots(r["High"],r["Low"],r["Close"])
            r.update({
                "Pivot P": round(P,2), "S1": round(S1,2), "S2": round(S2,2),
                "R1": round(R1,2), "R2": round(R2,2),
                "High": round(r["High"],2), "Low": round(r["Low"],2), "Close": round(r["Close"],2),
            })
            rows.append(r)
        except Exception as e:
            log(f"Fetch failed: {t} | {e}")
    if not rows: raise RuntimeError("No data rows built.")
    cols = ["Ticker","Date","High","Low","Close","Change%","Pivot P","S1","S2","R1","R2"]
    return pd.DataFrame(rows)[cols].sort_values(["Ticker"]).reset_index(drop=True)

# ---------- Outputs ----------
def write_pdf(df, path, default_topic=("NVDA",)):
    """PDF仍然以 NVDA + 同业为主题，网页支持任意选择"""
    # 选出默认主题（NVDA 及其 peers）用于 PDF 表页
    focus = df[df["Ticker"].isin(default_topic)]
    if len(focus) < 1:
        focus = df[df["Ticker"].isin(["NVDA","AMD","TSM","AVGO","INTC"])]

    with PdfPages(path) as pdf:
        # Cover
        plt.figure(figsize=(8.27, 11.69))
        plt.axis("off")
        plt.text(0.5,0.80,TITLE,ha="center",fontsize=20,fontweight="bold")
        plt.text(0.5,0.73,SUB,ha="center",fontsize=10)
        plt.text(0.5,0.68,f'Generated: {datetime.now():%Y-%m-%d %H:%M}',ha="center",fontsize=9)
        pdf.savefig(bbox_inches="tight"); plt.close()

        # Table
        plt.figure(figsize=(11.69, 8.27))
        plt.axis("off")
        table = plt.table(cellText=focus.values, colLabels=focus.columns, loc="center")
        table.auto_set_font_size(False); table.set_fontsize(11); table.scale(1.2,1.4)
        pdf.savefig(bbox_inches="tight"); plt.close()

def write_files(df, peers_map, site_url, report_url):
    # CSV
    df.to_csv("table.csv", index=False)
    log("Wrote table.csv")
    # Peers map
    with open("peers.json","w",encoding="utf-8") as f:
        json.dump(peers_map, f, ensure_ascii=False, indent=2)
    log("Wrote peers.json")

    # HTML（交互式，前端从 table.csv + peers.json 读取，支持 ?tickers=NVDA,TSM）
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pivot Levels — Interactive</title>
<style>
  body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,'Noto Sans',sans-serif; margin: 16px; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 8px; }}
  .sub {{ color:#666; font-size:.85rem; margin-bottom:10px; }}
  .controls {{ display:flex; gap:8px; flex-wrap:wrap; margin:10px 0 14px; }}
  input[type=text] {{ flex:1; min-width:220px; padding:10px 12px; border:1px solid #ddd; border-radius:10px; }}
  button, a.btn {{ padding:10px 14px; border-radius:10px; border:1px solid #ddd; background:#fff; text-decoration:none; cursor:pointer; }}
  .table-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid #eee; border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ white-space:nowrap; padding:10px 12px; border-bottom:1px solid #f0f0f0; text-align:left; }}
  th {{ position:sticky; top:0; background:#fafafa; }}
  .muted {{ color:#888; font-size:.85rem; margin-top:10px; }}
  @media (max-width:480px) {{ table{{font-size:13px}} th,td{{padding:8px 10px}} }}
</style>
</head>
<body>
  <h1>Daily Pivot Levels — Interactive</h1>
  <div class="sub">{SUB}</div>

  <div class="controls">
    <input id="tickersInput" type="text" placeholder="Enter tickers, e.g. NVDA,TSM,AMD">
    <button id="applyBtn">Apply</button>
    <button id="shareBtn">Share link</button>
    <a class="btn" href="{report_url}">📄 PDF</a>
    <a class="btn" href="table.csv">⬇️ CSV</a>
  </div>

  <div class="table-wrap">
    <table id="tbl">
      <thead><tr></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="muted">Updated at: {datetime.now():%Y-%m-%d %H:%M}</div>

<script>
async function fetchCSV(url) {{
  const resp = await fetch(url); const txt = await resp.text();
  const lines = txt.trim().split(/\\r?\\n/);
  const headers = lines[0].split(',');
  const rows = lines.slice(1).map(line => {{
    // 简单 CSV split（本表无逗号字段），够用
    const cols = line.split(',');
    const obj = {{}}; headers.forEach((h,i)=>obj[h]=cols[i]); return obj;
  }});
  return {{ headers, rows }};
}}

async function load() {{
  const urlParams = new URLSearchParams(location.search);
  const initial = urlParams.get('tickers') || 'NVDA';
  document.getElementById('tickersInput').value = initial;

  const peersResp = await fetch('peers.json'); const peersMap = peersResp.ok ? await peersResp.json() : {{}};
  const data = await fetchCSV('table.csv');

  const apply = () => {{
    const raw = document.getElementById('tickersInput').value.toUpperCase().replace(/\\s+/g,'');
    const base = raw ? raw.split(',').filter(Boolean) : [];
    const withPeers = new Set(base);
    base.forEach(t => (peersMap[t]||[]).forEach(p => withPeers.add(p)));
    const want = Array.from(withPeers);
    renderTable(data.headers, data.rows.filter(r => want.includes(r['Ticker'])));
  }};

  const share = () => {{
    const raw = document.getElementById('tickersInput').value.toUpperCase().replace(/\\s+/g,'');
    const u = new URL(location.href);
    if (raw) u.searchParams.set('tickers', raw); else u.searchParams.delete('tickers');
    navigator.clipboard.writeText(u.toString()).then(()=>alert('Link copied!')).catch(()=>prompt('Copy link:', u.toString()));
  }};

  document.getElementById('applyBtn').onclick = apply;
  document.getElementById('shareBtn').onclick = share;

  // init table header
  renderHeader(data.headers);
  apply();
}}

function renderHeader(headers) {{
  const tr = document.querySelector('#tbl thead tr'); tr.innerHTML = '';
  headers.forEach(h => {{
    const th = document.createElement('th'); th.textContent = h; tr.appendChild(th);
  }});
}}

function renderTable(headers, rows) {{
  const tb = document.querySelector('#tbl tbody'); tb.innerHTML = '';
  if (!rows.length) {{
    const tr = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = headers.length; td.textContent = 'No data for selected tickers'; tr.appendChild(td); tb.appendChild(tr);
    return;
  }}
  rows.forEach(r => {{
    const tr = document.createElement('tr');
    headers.forEach(h => {{
      const td = document.createElement('td'); td.textContent = r[h] ?? ''; tr.appendChild(td);
    }});
    tb.appendChild(tr);
  }});
}}

load();
</script>
</body>
</html>"""
    with open("index.html","w",encoding="utf-8") as f:
        f.write(html)
    log("Wrote index.html")

# ---------- Notifications (optional) ----------
def push_serverchan(sendkey, title, content_md):
    if not sendkey: return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                          data={"title":title,"desp":content_md}, timeout=15)
        r.raise_for_status(); return r.ok
    except Exception as e:
        log(f"[SCT] {e}"); return False

def push_pushplus(token, title, content_html):
    if not token: return False
    try:
        r = requests.post("https://www.pushplus.plus/send",
                          json={"token":token,"title":title,"content":content_html,"template":"html"},
                          timeout=15)
        r.raise_for_status(); return r.ok
    except Exception as e:
        log(f"[PushPlus] {e}"); return False

# ---------- Main ----------
if __name__ == "__main__":
    try:
        site_url   = getenv("SITE_URL")   or ""   # for push message
        report_url = getenv("REPORT_URL") or "report.pdf"
        finnhub_key= getenv("FINNHUB_API_KEY")

        # 1) peers.json（不暴露密钥在前端）
        log("Building peers map ...")
        peers_map = build_peers_map(SEED_TICKERS, finnhub_key)

        # 2) 构建当天全量 universe：种子 + 它们同业
        universe = set(SEED_TICKERS)
        for ps in peers_map.values():
            for p in ps: universe.add(p)

        log(f"Universe size: {len(universe)}")
        df = build_table(universe)

        # 3) 文件输出
        write_pdf(df, PDF_OUT, default_topic=("NVDA",) + tuple(peers_map.get("NVDA", [])[:5]))
        write_files(df, peers_map, site_url, report_url)

        # 4) 推送（可选）
        title = "Daily Pivot Levels — Online/CSV/PDF"
        md = f"**{title}**\\n\\n[Online]({site_url})\\n\\n[PDF]({report_url})"
        html = f"<b>{title}</b><br>" + (f"<a href='{site_url}'>Online</a><br>" if site_url else "") + f"<a href='{report_url}'>PDF</a>"
        _ = push_serverchan(getenv("WECHAT_SCT_SENDKEY"), title, md)
        _ = push_pushplus(getenv("PUSHPLUS_TOKEN"), title, html)

        log("Done.")
    except Exception:
        log("FATAL:\\n" + "".join(traceback.format_exception(*sys.exc_info())))
        raise
