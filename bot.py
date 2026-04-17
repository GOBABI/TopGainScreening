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

BOT_TOKEN      = "8702268897:AAEhRnt0nuBnYCJeMdhofbX_h-D_YBTJxCE"
BASE_URL       = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
PRE_RESULT_FILE = os.path.join(BASE_DIR, "pre_result.json")  # 마지막 /pre 결과 캐시
CHAT_ID        = "7371637453"

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


def _is_regular_market_open():
    from datetime import datetime
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now <= close_t


def scan_premarket(chat_id):
    import yfinance as yf

    regular_open = _is_regular_market_open()
    mode_label = "오늘의 프리마켓" if regular_open else "프리마켓"
    send_message(chat_id, f"⏳ {mode_label} 갭 스캔 중...")

    results = []

    if regular_open:
        # 정규장 중: most_actives 200개 → 시가 기준 갭 계산 (개별 API 호출 불필요)
        try:
            quotes = yf.screen("most_actives", count=200).get("quotes", [])
        except Exception:
            quotes = []
        for q in quotes:
            try:
                sym       = q.get("symbol", "")
                name      = q.get("shortName") or sym
                reg_open  = q.get("regularMarketOpen") or 0
                reg_close = q.get("regularMarketPreviousClose") or 0
                avg_vol   = q.get("averageDailyVolume3Month") or 1
                pre_vol   = q.get("preMarketVolume") or 0

                if reg_open <= 0 or reg_close <= 0:
                    continue

                gap_pct   = (reg_open - reg_close) / reg_close * 100
                vol_ratio = pre_vol / avg_vol if avg_vol else 0

                if gap_pct >= 3.0:
                    results.append({
                        "sym": sym, "name": name,
                        "gap": gap_pct, "price": reg_open,
                        "vol_ratio": vol_ratio,
                        "market_cap": q.get("marketCap") or 0,
                    })
            except Exception:
                continue
    else:
        # 프리마켓 중: watchlist + DEFAULT_SYMBOLS 대상으로 preMarketPrice 조회
        symbols = list(DEFAULT_SYMBOLS)
        if os.path.exists(WATCHLIST_FILE):
            try:
                wl = json.load(open(WATCHLIST_FILE))
                symbols = list(set(symbols + list(wl.get("tickers", {}).keys())))
            except Exception:
                pass
        for sym in symbols:
            try:
                info      = yf.Ticker(sym).info
                pre_price = info.get("preMarketPrice") or 0
                reg_close = info.get("regularMarketPreviousClose") or 0
                avg_vol   = info.get("averageDailyVolume3Month") or 1
                pre_vol   = info.get("preMarketVolume") or 0
                name      = info.get("shortName", sym)

                if pre_price <= 0 or reg_close <= 0:
                    continue

                gap_pct   = (pre_price - reg_close) / reg_close * 100
                vol_ratio = pre_vol / avg_vol if avg_vol else 0

                if gap_pct >= 3.0:
                    results.append({
                        "sym": sym, "name": name,
                        "gap": gap_pct, "price": pre_price,
                        "vol_ratio": vol_ratio,
                        "market_cap": info.get("marketCap") or 0,
                    })
            except Exception:
                continue

    if not results:
        send_message(chat_id, f"📭 {mode_label} 갭 +3% 이상 종목이 없습니다.")
        return

    results.sort(key=lambda x: x["market_cap"], reverse=True)
    results = results[:10]

    # 상위 10개 뉴스 + 섹터 + 첫봉 병렬 조회
    import pytz
    from datetime import datetime, time as dtime
    _et = pytz.timezone("America/New_York")
    _now_et = datetime.now(_et)
    _today  = _now_et.date()
    _hm     = _now_et.hour * 100 + _now_et.minute
    _has_1m = regular_open and _hm >= 931
    _has_5m = regular_open and _hm >= 935

    def _get_first_candle(sym, interval):
        try:
            h = yf.Ticker(sym).history(period="1d", interval=f"{interval}m")
            if h.empty:
                return None
            h.index = h.index.tz_convert(_et)
            first = h[h.index.time >= dtime(9, 30)]
            if first.empty:
                return None
            row = first.iloc[0]
            return {"high": float(row["High"]), "low": float(row["Low"])}
        except Exception:
            return None

    def _fetch_detail(sym):
        news, url, sector, cur, pre_vol_ratio = "", "", "", 0.0, 0.0
        c1, c5 = None, None
        try:
            t = yf.Ticker(sym)
            info = t.info
            sector  = info.get("sector", "") or ""
            cur     = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("preMarketPrice") or 0)
            pre_vol = float(info.get("preMarketVolume") or 0)
            avg_vol = float(info.get("averageDailyVolume3Month") or 1)
            pre_vol_ratio = pre_vol / avg_vol if avg_vol else 0.0
            for n in (t.news or [])[:3]:
                title = (n.get("content", {}).get("title") or n.get("title", ""))
                link  = (n.get("content", {}).get("canonicalUrl", {}).get("url", "")
                         or n.get("link", "") or n.get("url", ""))
                if title:
                    news, url = title[:60], link
                    break
        except Exception:
            pass
        if _has_1m:
            c1 = _get_first_candle(sym, 1)
        if _has_5m:
            c5 = _get_first_candle(sym, 5)
        return news, url, sector, cur, pre_vol_ratio, c1, c5

    # 저장된 프리마켓 거래량 비율 로드 (정규장 중 참조)
    _saved_vr = {}
    try:
        with open(PRE_RESULT_FILE) as f:
            _pf = json.load(f)
        if _pf.get("date") == str(_today):
            _saved_vr = _pf.get("vol_ratios", {})
    except Exception:
        pass

    from concurrent.futures import ThreadPoolExecutor
    syms = [r["sym"] for r in results]
    with ThreadPoolExecutor(max_workers=5) as ex:
        details = dict(zip(syms, ex.map(_fetch_detail, syms)))

    header = f"<b>📈 {mode_label} 갭 상승 종목 (시총 상위 10)</b>"
    if regular_open:
        header += "\n<i>(정규장 시작 후 — 오늘 시가 기준)</i>"
    lines = [header + "\n"]
    def _range_pct(cur, low, high):
        rng = high - low
        if rng <= 0:
            return None
        return (cur - low) / rng * 100

    for r in results:
        news, url, sector, cur, pre_vol_ratio, c1, c5 = details.get(r["sym"], ("", "", "", 0.0, 0.0, None, None))
        vol_ratio  = pre_vol_ratio if pre_vol_ratio > 0 else _saved_vr.get(r["sym"], r["vol_ratio"])
        vol_tag    = f"  🔥 {vol_ratio:.1f}x" if vol_ratio >= 2 else ""
        sector_tag = f"\n  🏷 {sector}" if sector else ""
        news_tag   = f"\n  📰 <a href='{url}'>{news}</a>" if news and url else (f"\n  📰 {news}" if news else "")

        candle_tag = ""
        if regular_open:
            if c1:
                pos = _range_pct(cur, c1["low"], c1["high"]) if cur else None
                pos_str = f"  📍{pos:.0f}%" if pos is not None else ""
                candle_tag += f"\n  🕯1분봉  고 ${c1['high']:.2f} / 저 ${c1['low']:.2f}{pos_str}"
            elif _hm < 931:
                candle_tag += "\n  🕯1분봉  아직 미완성 (9:31 ET 이후)"
            if c5:
                pos = _range_pct(cur, c5["low"], c5["high"]) if cur else None
                pos_str = f"  📍{pos:.0f}%" if pos is not None else ""
                candle_tag += f"\n  🕯5분봉  고 ${c5['high']:.2f} / 저 ${c5['low']:.2f}{pos_str}"
            elif _hm < 935:
                candle_tag += "\n  🕯5분봉  아직 미완성 (9:35 ET 이후)"

        cur_tag = f"  현재 ${cur:.2f}" if cur else ""
        lines.append(
            f"<b>{r['sym']}</b> ({r['name']})\n"
            f"  갭 +{r['gap']:.1f}%{cur_tag}{vol_tag}{sector_tag}{candle_tag}{news_tag}"
        )

    send_message(chat_id, "\n\n".join(lines))

    # 프리마켓 거래량 비율 저장 (정규장 이후 참조용)
    saved = {"date": str(_today), "symbols": [r["sym"] for r in results], "vol_ratios": {}}
    for r in results:
        vr = details.get(r["sym"], ("","","",0.0,0.0,None,None))[4]
        saved["vol_ratios"][r["sym"]] = round(vr if vr > 0 else r["vol_ratio"], 2)
    with open(PRE_RESULT_FILE, "w") as f:
        json.dump(saved, f)
    print(f"[bot] /pre 완료 — {len(results)}개 종목 전송")




def _auto_schedule(sent_flags: dict):
    """정규장 마감 후 report, 개장 전 pre 자동 전송"""
    from datetime import datetime
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)

    # 주말 스킵
    if now.weekday() >= 5:
        return

    hm = now.hour * 100 + now.minute
    today = now.strftime("%Y-%m-%d")

    # 정규장 마감 후 (16:05 ~ 16:10) — report 자동 전송
    if 1605 <= hm <= 1610 and sent_flags.get("report") != today:
        print(f"[bot] 자동 report 전송 ({now.strftime('%H:%M')} ET)")
        run_screening(CHAT_ID)
        sent_flags["report"] = today

    # 개장 30분 전 (09:00 ~ 09:05) — pre 자동 전송
    if 900 <= hm <= 905 and sent_flags.get("pre") != today:
        print(f"[bot] 자동 pre 전송 ({now.strftime('%H:%M')} ET)")
        scan_premarket(CHAT_ID)
        sent_flags["pre"] = today


def main():
    print("[bot] 텔레그램 봇 시작 — /report, /pre 대기 중... (자동 스케줄 포함)")
    offset = None
    sent_flags: dict = {}
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
                    "/pre — 프리마켓 갭 상승 종목 (정규장 시작 후엔 첫 1·5분봉 포함)\n\n"
                    "📅 자동 전송: 장 마감 후 report / 개장 30분 전 pre"
                )

        _auto_schedule(sent_flags)
        time.sleep(30)


if __name__ == "__main__":
    main()
