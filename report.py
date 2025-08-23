import os, requests, pandas as pd, yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

TICKERS = ["NVDA","AMD","TSM","AVGO","INTC"]
TITLE   = "NVDA 及同业：支撑/阻力日报（枢轴法）"
SUB     = "公式：P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
OUT     = "report.pdf"  # 固定文件名，方便持久链接

try:
    matplotlib.rcParams['font.sans-serif'] = ['Noto Sans CJK SC','Microsoft YaHei','Arial Unicode MS']
    matplotlib.rcParams['axes.unicode_minus'] = False
except Exception:
    pass

def pivots(h,l,c):
    P  = (h+l+c)/3
    R1 = 2*P - l; S1 = 2*P - h
    R2 = P + (h-l); S2 = P - (h-l)
    return P,S1,S2,R1,R2

def fetch_latest_row(ticker):
    df = yf.download(ticker, period="7d", interval="1d", auto_adjust=False, progress=False)
    row = df.iloc[-1]
    return {
        "Ticker": ticker,
        "Date": row.name.date().isoformat(),
        "High": float(row["High"]),
        "Low": float(row["Low"]),
        "Close": float(row["Close"]),
    }

def build_table(rows):
    for r in rows:
        P,S1,S2,R1,R2 = pivots(r["High"], r["Low"], r["Close"])
        r.update({
            "Pivot P": round(P,2), "S1": round(S1,2), "S2": round(S2,2),
            "R1": round(R1,2), "R2": round(R2,2),
            "High": round(r["High"],2), "Low": round(r["Low"],2), "Close": round(r["Close"],2)
        })
    cols = ["Ticker","Date","High","Low","Close","Pivot P","S1","S2","R1","R2"]
    return pd.DataFrame(rows)[cols]

def write_pdf(df, path):
    with PdfPages(path) as pdf:
        plt.figure(figsize=(8.5, 11)); plt.axis('off')
        plt.text(0.5,0.80,TITLE,ha='center',fontsize=18,fontweight='bold')
        plt.text(0.5,0.75,SUB,ha='center',fontsize=10)
        plt.text(0.5,0.70,f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}',ha='center',fontsize=9)
        pdf.savefig(); plt.close()

        plt.figure(figsize=(11, 8.5)); plt.axis('off')
        table = plt.table(cellText=df.values, colLabels=df.columns, loc='center')
        table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1.0,1.4)
        pdf.savefig(); plt.close()

def push_serverchan(sendkey, title, content_md):
    if not sendkey: return False
    r = requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                      data={"title":title, "desp":content_md}, timeout=15)
    return r.ok

def push_pushplus(token, title, content_html):
    if not token: return False
    r = requests.post("https://www.pushplus.plus/send",
                      json={"token":token,"title":title,"content":content_html,"template":"html"},
                      timeout=15)
    return r.ok

if __name__ == "__main__":
    rows = [fetch_latest_row(t) for t in TICKERS]
    df = build_table(rows)
    write_pdf(df, OUT)

    # GitHub Pages 固定链接（见第4步配置），例如：
    report_url = os.getenv("REPORT_URL")  # 形如 https://<你的用户名>.github.io/nvda-daily/report.pdf

    title = "NVDA及同业 支撑/阻力日报"
    md_msg = f"**{title}**\n\n[下载PDF]({report_url})" if report_url else f"**{title}**\n\n(暂未配置REPORT_URL)"
    html_msg = f"<b>{title}</b><br><a href='{report_url}'>下载PDF</a>" if report_url else f"<b>{title}</b>"

    # 二选一或都启用
    _ = push_serverchan(os.getenv("WECHAT_SCT_SENDKEY"), title, md_msg)
    _ = push_pushplus(os.getenv("PUSHPLUS_TOKEN"), title, html_msg)
