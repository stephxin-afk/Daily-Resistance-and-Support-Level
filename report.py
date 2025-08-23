import os, requests, pandas as pd, yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

# （可选）静默 pandas FutureWarning。若想看警告，把下面两行注释掉即可。
# import warnings
# warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")

TICKERS = ["NVDA", "AMD", "TSM", "AVGO", "INTC"]
TITLE   = "NVDA 及同业：支撑/阻力日报（枢轴法）"
SUB     = "公式：P=(H+L+C)/3; S1=2P-H; S2=P-(H-L); R1=2P-L; R2=P+(H-L)"
OUT     = "report.pdf"  # 固定文件名，方便 GitHub Pages 固定链接

# 字体设置（有中文字体则用，无则回退不报错）
try:
    matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Microsoft YaHei", "Arial Unicode MS"]
    matplotlib.rcParams["axes.unicode_minus"] = False
except Exception:
    pass

def pivots(h, l, c):
    P  = (h + l + c) / 3.0
    R1 = 2 * P - l
    S1 = 2 * P - h
    R2 = P + (h - l)
    S2 = P - (h - l)
    return P, S1, S2, R1, R2

def fetch_latest_row(ticker):
    """
    拉取最近7天的日线，取最后一根K线的 H/L/C。
    做好防御：空数据/字段缺失时返回 None，主流程会过滤。
    """
    try:
        df = yf.download(ticker, period="7d", interval="1d",
                         auto_adjust=False, progress=False)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    # ✅ 关键：对列取值再 iloc[-1]，确保是标量，避免 FutureWarning
    try:
        H = float(df["High"].iloc[-1])
        L = float(df["Low"].iloc[-1])
        C = float(df["Close"].iloc[-1])
    except Exception:
        return None

    # 取日期字符串
    dt = df.index[-1]
    try:
        date_str = dt.date().isoformat()
    except Exception:
        date_str = str(dt)[:10]

    return {
        "Ticker": ticker,
        "Date": date_str,
        "High": H,
        "Low": L,
        "Close": C,
    }

def build_table(rows):
    """计算 P/S1/S2/R1/R2 并整理成 DataFrame。"""
    clean = []
    for r in rows:
        if not r or any(r[k] is None for k in ["High", "Low", "Close"]):
            continue
        P, S1, S2, R1, R2 = pivots(r["High"], r["Low"], r["Close"])
        r.update({
            "Pivot P": round(P, 2),
            "S1": round(S1, 2), "S2": round(S2, 2),
            "R1": round(R1, 2), "R2": round(R2, 2),
            "High": round(r["High"], 2), "Low": round(r["Low"], 2), "Close": round(r["Close"], 2)
        })
        clean.append(r)

    cols = ["Ticker", "Date", "High", "Low", "Close", "Pivot P", "S1", "S2", "R1", "R2"]
    return pd.DataFrame(clean, columns=cols)

def write_pdf(df, path):
    with PdfPages(path) as pdf:
        # 封面
        plt.figure(figsize=(8.5, 11))
        plt.axis("off")
        plt.text(0.5, 0.80, TITLE, ha="center", fontsize=18, fontweight="bold")
        plt.text(0.5, 0.75, SUB, ha="center", fontsize=10)
        plt.text(0.5, 0.70, f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 ha="center", fontsize=9)
        pdf.savefig(); plt.close()

        # 表格页
        plt.figure(figsize=(11, 8.5))
        plt.axis("off")
        if df is not None and not df.empty:
            table = plt.table(cellText=df.values, colLabels=df.columns, loc="center")
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1.0, 1.4)
        else:
            plt.text(0.5, 0.5, "无可用数据", ha="center", va="center", fontsize=12)
        pdf.savefig(); plt.close()

def push_serverchan(sendkey, title, content_md):
    if not sendkey:
        return False
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
    if not token:
        return False
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
    # 1) 拉数据
    rows = [fetch_latest_row(t) for t in TICKERS]
    rows = [r for r in rows if r]  # 过滤 None

    # 2) 计算并生成 PDF
    df = build_table(rows)
    write_pdf(df, OUT)

    # 3) 推送固定下载链接（GitHub Pages）
    report_url = os.getenv("REPORT_URL")  # 例：https://<用户名>.github.io/<仓库名>/report.pdf
    title = "NVDA及同业 支撑/阻力日报"

    if report_url:
        md_msg = f"**{title}**\n\n[下载PDF]({report_url})"
        html_msg = f"<b>{title}</b><br><a href='{report_url}'>下载PDF</a>"
    else:
        md_msg = f"**{title}**\n\n(暂未配置 REPORT_URL)"
        html_msg = f"<b>{title}</b><br>(暂未配置 REPORT_URL)"

    # 二选一或都启用
    _ = push_serverchan(os.getenv("WECHAT_SCT_SENDKEY"), title, md_msg)
    _ = push_pushplus(os.getenv("PUSHPLUS_TOKEN"), title, html_msg)
