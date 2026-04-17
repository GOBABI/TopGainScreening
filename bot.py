"""
Telegram Bot - /report, /pre 명령어 수신 시 실행
실행: python3 bot.py
"""

import time
import json
import os
import sys
import subprocess
import requests

BOT_TOKEN = "8654658267:AAEWsIE8MbM-V_9mR77LIymdfsb_cEDFJug"
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")

# 기본 스캔 대상 (watchlist에 없을 경우 폴백)
DEFAULT_SYMBOLS = [
    "AAPL","MSFT","NVDA","AMD","META","GOOGL","AMZN","TSLA","PLTR","SMCI",
    "MARA","RIOT","COIN","SOFI","HOOD","RBLX","SNAP","UBER","LYFT","SHOP",
    "NFLX","CRM","ORCL","AVGO","ARM","MU","INTC","QCOM","TSM","ASML",
]


def get_updates(offset=None):
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        print(f"[getUpdates 오류] {e}")
        return []


def send_message(chat_id, text):
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        print(f"[sendMessage 오류] {e}")


def run_screening(chat_id):
    send_message(chat_id, "⏳ 스크리닝 시작 중... 잠시 기다려 주세요.")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "screening.py")],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            send_message(chat_id, "✅ 스크리닝 완료 — 리포트와 분석이 전송되었습니다.")
        else:
            err = (result.stderr or result.stdout)[-500:]
            send_message(chat_id, f"❌ 스크리닝 오류\n<pre>{err}</pre>")
    except subprocess.TimeoutExpired:
        send_message(chat_id, "⚠️ 타임아웃: 스크리닝이 5분을 초과했습니다.")
    except Exception as e:
        send_message(chat_id, f"❌ 실행 오류: {e}")


def scan_premarket(chat_id):
    import yfinance as yf

    send_message(chat_id, "⏳ 프리마켓 갭 스캔 중...")

    # watchlist + 기본 심볼 합산
    symbols = list(DEFAULT_SYMBOLS)
    if os.path.exists(WATCHLIST_FILE):
        try:
            wl = json.load(open(WATCHLIST_FILE))
            symbols = list(set(symbols + list(wl.get("tickers", {}).keys())))
        except Exception:
            pass

    results = []
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            pre_price  = info.get("preMarketPrice") or 0
            pre_chg    = info.get("preMarketChangePercent") or 0
            reg_close  = info.get("regularMarketPreviousClose") or 0
            volume     = info.get("preMarketVolume") or 0
            avg_vol    = info.get("averageDailyVolume3Month") or 1
            name       = info.get("shortName", sym)

            if pre_price <= 0 or reg_close <= 0:
                continue

            gap_pct = pre_chg * 100 if abs(pre_chg) > 1 else pre_chg
            vol_ratio = volume / avg_vol if avg_vol else 0

            if gap_pct >= 3.0:
                results.append({
                    "sym": sym, "name": name,
                    "gap": gap_pct, "price": pre_price,
                    "vol_ratio": vol_ratio,
                })
        except Exception:
            continue

    if not results:
        send_message(chat_id, "📭 갭 +3% 이상 종목이 없습니다.")
        return

    results.sort(key=lambda x: x["gap"], reverse=True)

    lines = ["<b>📈 프리마켓 갭 상승 종목</b>\n"]
    for r in results[:20]:
        vol_tag = f"  🔥 거래량 {r['vol_ratio']:.1f}x" if r["vol_ratio"] >= 2 else ""
        lines.append(
            f"<b>{r['sym']}</b> ({r['name']})\n"
            f"  갭 +{r['gap']:.1f}%  |  ${r['price']:.2f}{vol_tag}"
        )

    send_message(chat_id, "\n\n".join(lines))
    print(f"[bot] /pre 완료 — {len(results)}개 종목 전송")


def main():
    print("[bot] 텔레그램 봇 시작 — /report, /pre 대기 중...")
    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = msg.get("chat", {}).get("id")
            if not chat_id:
                continue

            if text == "/report" or text.startswith("/report@"):
                print(f"[bot] /report 수신 (chat_id={chat_id})")
                run_screening(chat_id)
            elif text == "/pre" or text.startswith("/pre@"):
                print(f"[bot] /pre 수신 (chat_id={chat_id})")
                scan_premarket(chat_id)
            elif text == "/start":
                send_message(
                    chat_id,
                    "안녕하세요!\n\n"
                    "/report — 미국 주식 스크리닝 리포트 생성 및 전송\n"
                    "/pre — 프리마켓 갭 상승 종목 스캔 (갭 +3% 이상)"
                )
        time.sleep(1)


if __name__ == "__main__":
    main()
