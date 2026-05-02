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

BOT_TOKEN       = "8702268897:AAEhRnt0nuBnYCJeMdhofbX_h-D_YBTJxCE"
BASE_URL        = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE  = os.path.join(BASE_DIR, "watchlist.json")
PRE_RESULT_FILE = os.path.join(BASE_DIR, "pre_result.json")
OFFSET_FILE     = os.path.join(BASE_DIR, ".bot_offset")
PID_FILE        = os.path.join(BASE_DIR, ".bot.pid")
CHAT_ID         = "7371637453"

_screening_running = False


def _acquire_single_instance():
    """이전 인스턴스가 있으면 종료하고 현재 PID 등록"""
    import signal
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGTERM)
                time.sleep(1)
                print(f"[bot] 이전 인스턴스 종료 (PID {old_pid})")
        except (ProcessLookupError, ValueError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_single_instance():
    try:
        os.remove(PID_FILE)
    except Exception:
        pass

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


def _market_status():
    """현재 미국 시장 상태 반환: 'open' | 'pre' | 'after' | 'closed'"""
    from datetime import datetime
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return 'closed'
    hm = now.hour * 100 + now.minute
    if 400 <= hm < 930:
        return 'pre'
    if 930 <= hm < 1600:
        return 'open'
    if 1600 <= hm < 2000:
        return 'after'
    return 'closed'


LOCK_FILE = os.path.join(BASE_DIR, ".screening_lock")

def _acquire_screening_lock():
    """10분 이내 중복 실행 방지 (인스턴스 간 공유)"""
    import time as _time
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                ts = float(f.read().strip())
            if _time.time() - ts < 600:  # 10분
                return False
        with open(LOCK_FILE, "w") as f:
            f.write(str(_time.time()))
        return True
    except Exception:
        return True

def _release_screening_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass


def run_screening(chat_id, sent_flags=None, force=False):
    global _screening_running
    if _screening_running:
        send_message(chat_id, "⚠️ 이미 스크리닝이 실행 중입니다. 완료 후 다시 시도하세요.")
        return
    if not force and not _acquire_screening_lock():
        send_message(chat_id, "⚠️ 10분 이내 이미 실행됐습니다. 잠시 후 다시 시도하세요.")
        return

    status = _market_status()
    if not force and status == 'closed':
        send_message(chat_id, "📭 현재 미국 장이 열리지 않는 시간입니다 (주말 또는 심야).\n데이터가 없어 스크리닝을 실행할 수 없습니다.")
        return

    _screening_running = True
    if sent_flags is not None:
        from datetime import datetime
        import pytz
        today = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d")
        sent_flags["report"] = today
    try:
        if status == 'pre':
            send_message(chat_id, "🔄 스크리닝 중입니다... (프리마켓 데이터 기준)")
        elif status == 'after':
            send_message(chat_id, "🔄 스크리닝 중입니다... (장 마감 후 데이터 기준)")
        else:
            send_message(chat_id, "🔄 스크리닝 중입니다...")
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
    finally:
        _screening_running = False
        _release_screening_lock()


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




def run_refresh(chat_id):
    global _screening_running
    if _screening_running:
        send_message(chat_id, "⚠️ 스크리닝 실행 중 — 완료 후 시도하세요.")
        return
    _screening_running = True
    try:
        send_message(chat_id, "⏳ 리포트 재생성 중...")
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "refresh_report.py")],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            send_message(chat_id, "✅ 리포트 재생성 완료 — Netlify 반영됐습니다.")
        else:
            err = (result.stderr or result.stdout)[-500:]
            send_message(chat_id, f"❌ 재생성 오류\n<pre>{err}</pre>")
    except subprocess.TimeoutExpired:
        send_message(chat_id, "⚠️ 타임아웃: 2분 초과")
    except Exception as e:
        send_message(chat_id, f"❌ 실행 오류: {e}")
    finally:
        _screening_running = False


def _auto_schedule(sent_flags: dict):
    """정규장 마감 후 report, 개장 전 pre 자동 전송"""
    from datetime import datetime
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)

    # 주말 자동 스케줄 스킵 (수동 /report, /refresh는 항상 허용)
    if now.weekday() >= 5:
        return

    hm = now.hour * 100 + now.minute
    today = now.strftime("%Y-%m-%d")

    # 정규장 마감 후 (16:05 ~ 16:10) — report 자동 전송
    if 1605 <= hm <= 1610 and sent_flags.get("report") != today:
        print(f"[bot] 자동 report 전송 ({now.strftime('%H:%M')} ET)")
        run_screening(CHAT_ID, sent_flags)
        sent_flags["report"] = today

    # 개장 30분 전 (09:00 ~ 09:05) — pre 자동 전송
    if 900 <= hm <= 905 and sent_flags.get("pre") != today:
        print(f"[bot] 자동 pre 전송 ({now.strftime('%H:%M')} ET)")
        scan_premarket(CHAT_ID)
        sent_flags["pre"] = today


def run_test(chat_id):
    send_message(chat_id, "🔧 진단 테스트 시작...")
    try:
        import yfinance as yf

        lines = []

        # 1. Yahoo Finance 연결
        try:
            result = yf.screen("day_gainers", count=50)
            quotes = result.get("quotes", [])
            lines.append(f"✅ Yahoo Finance 연결 OK — {len(quotes)}개 수집")
            c10 = len([q for q in quotes if (q.get("regularMarketChangePercent") or 0) >= 10])
            c5  = len([q for q in quotes if (q.get("regularMarketChangePercent") or 0) >= 5])
            c3  = len([q for q in quotes if (q.get("regularMarketChangePercent") or 0) >= 3])
            lines.append(f"  10%+ 통과: {c10}개")
            lines.append(f"  5%+  통과: {c5}개")
            lines.append(f"  3%+  통과: {c3}개")
            if quotes:
                top = sorted(quotes, key=lambda q: q.get("regularMarketChangePercent") or 0, reverse=True)[:3]
                lines.append("  상위 3개:")
                for q in top:
                    lines.append(f"    {q.get('symbol')} +{q.get('regularMarketChangePercent',0):.1f}%")
        except Exception as e:
            lines.append(f"❌ Yahoo Finance 실패: {e}")

        # 2. SPY 시장 데이터
        try:
            h = yf.Ticker("SPY").history(period="5d")
            lines.append(f"✅ SPY 데이터 OK — 최근 종가 ${h['Close'].iloc[-1]:.2f}")
        except Exception as e:
            lines.append(f"❌ SPY 데이터 실패: {e}")

        # 3. 시장 상태
        status = _market_status()
        status_label = {"open": "정규장 중", "pre": "프리마켓", "after": "장 마감 후", "closed": "휴장"}.get(status, status)
        lines.append(f"📊 현재 시장: {status_label}")

        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_message(chat_id, f"❌ 테스트 오류: {e}")
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None

def analyze_ticker(chat_id, ticker):
    import yfinance as yf
    import pandas as pd
    send_message(chat_id, f"🔍 {ticker} 분석 중...")
    try:
        t   = yf.Ticker(ticker)
        h   = t.history(period="1y")
        if h.empty or len(h) < 60:
            send_message(chat_id, f"❌ {ticker} 데이터 없음 또는 부족")
            return

        info   = t.info
        c      = h["Close"]
        hi     = h["High"]
        lo     = h["Low"]
        vol    = h["Volume"]
        price  = float(c.iloc[-1])
        ma20   = float(c.rolling(20).mean().iloc[-1])
        ma50   = float(c.rolling(50).mean().iloc[-1])
        ma200  = float(c.rolling(200).mean().dropna().iloc[-1]) if len(c) >= 200 else None

        # ADX 계산
        def _adx(hi, lo, c, n=14):
            tr  = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1/n, adjust=False).mean()
            up  = hi.diff(); dn = -lo.diff()
            pdm = up.where((up > dn) & (up > 0), 0.0)
            ndm = dn.where((dn > up) & (dn > 0), 0.0)
            pdi = 100 * pdm.ewm(alpha=1/n, adjust=False).mean() / atr
            ndi = 100 * ndm.ewm(alpha=1/n, adjust=False).mean() / atr
            dx  = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, 1))
            return float(dx.ewm(alpha=1/n, adjust=False).mean().iloc[-1])

        # RSI 계산
        def _rsi(c, n=14):
            d   = c.diff()
            g   = d.where(d > 0, 0.0).ewm(alpha=1/n, adjust=False).mean()
            ls  = (-d.where(d < 0, 0.0)).ewm(alpha=1/n, adjust=False).mean()
            return float(100 - 100 / (1 + g / ls.replace(0, 1e-9)).iloc[-1])

        adx  = _adx(hi, lo, c)
        rsi  = _rsi(c)
        avg_vol = float(vol.tail(20).mean())

        # SPY / QQQ
        spy_h = yf.Ticker("SPY").history(period="5d")["Close"]
        qqq_h = yf.Ticker("QQQ").history(period="5d")["Close"]
        spy_chg = (spy_h.iloc[-1] / spy_h.iloc[-2] - 1) * 100
        qqq_chg = (qqq_h.iloc[-1] / qqq_h.iloc[-2] - 1) * 100

        # 섹터 ETF
        sector = info.get("sector", "")
        SECTOR_ETF = {
            "Technology": "XLK", "Healthcare": "XLV", "Financial Services": "XLF",
            "Energy": "XLE", "Consumer Cyclical": "XLY", "Industrials": "XLI",
            "Communication Services": "XLC", "Basic Materials": "XLB",
            "Consumer Defensive": "XLP", "Real Estate": "XLRE", "Utilities": "XLU",
        }
        etf = SECTOR_ETF.get(sector)
        sector_chg = None
        if etf:
            sh = yf.Ticker(etf).history(period="5d")["Close"]
            sector_chg = (sh.iloc[-1] / sh.iloc[-2] - 1) * 100

        # 눌림 거래량 감소 (최근 5일 거래량 vs 20일 평균)
        recent_vol  = float(vol.tail(5).mean())
        vol_decl    = recent_vol < avg_vol * 0.85

        # MA 눌림 여부 (현재가 MA20 또는 MA50의 ±3% 이내)
        near_ma20 = abs(price - ma20) / ma20 < 0.03
        near_ma50 = abs(price - ma50) / ma50 < 0.03
        ma_riding = near_ma20 or near_ma50

        # 어닝
        earning_warn = False
        earning_str  = "확인 불가"
        try:
            cal = t.calendar
            if cal is not None and not cal.empty:
                from datetime import datetime
                eq = cal.get("Earnings Date")
                if eq is not None and len(eq) > 0:
                    ed = pd.Timestamp(eq[0]).date()
                    days_to = (ed - datetime.now().date()).days
                    earning_str = str(ed)
                    if 0 <= days_to <= 3:
                        earning_warn = True
                        earning_str += f" ({days_to}일 후 ⚠️)"
        except Exception:
            pass

        name = info.get("shortName", ticker)

        # ── 자동 체크 결과 ────────────────────────────────
        auto = []

        # 시장
        spy_ok = spy_chg > 0
        qqq_ok = qqq_chg > 0
        auto.append(("SPY", f"{'✅' if spy_ok else '❌'} SPY {spy_chg:+.1f}%"))
        auto.append(("QQQ", f"{'✅' if qqq_ok else '❌'} QQQ {qqq_chg:+.1f}%"))
        if sector_chg is not None:
            auto.append(("섹터", f"{'✅' if sector_chg > 0 else '❌'} {sector}({etf}) {sector_chg:+.1f}%"))
        else:
            auto.append(("섹터", f"⚠️ 섹터 ETF 확인 불가 ({sector or '미분류'})"))

        # 기본 조건
        if ma200:
            auto.append(("200MA", f"{'✅' if price > ma200 else '❌'} 200MA {'위' if price > ma200 else '아래'} (${price:.2f} / MA200 ${ma200:.2f})"))
            ma_align = ma20 > ma50 > ma200
            auto.append(("정배열", f"{'✅' if ma_align else '❌'} MA 정배열 (20:{ma20:.1f} > 50:{ma50:.1f} > 200:{ma200:.1f})"))
        else:
            auto.append(("200MA", "⚠️ 데이터 부족 (1년 미만)"))
            auto.append(("정배열", "⚠️ 데이터 부족"))

        auto.append(("ADX",  f"{'✅' if adx >= 25 else '❌'} ADX {adx:.0f} ({'뚜렷한 추세' if adx >= 25 else '추세 약함'})"))
        auto.append(("거래량", f"{'✅' if avg_vol >= 500000 else '❌'} 평균 거래량 {avg_vol/1e6:.1f}M주"))
        auto.append(("주가",  f"{'✅' if price >= 5 else '❌'} 주가 ${price:.2f}"))

        # 패턴
        ma_str = []
        if near_ma20: ma_str.append(f"20MA(${ma20:.1f})")
        if near_ma50: ma_str.append(f"50MA(${ma50:.1f})")
        auto.append(("MA눌림", f"{'✅' if ma_riding else '⚠️'} MA 눌림 {'근처 — 반등 확인 필요' if ma_riding else '없음 (' + ', '.join(ma_str) + ')' if ma_str else '없음'}"))
        auto.append(("눌림거래량", f"{'✅' if vol_decl else '⚠️'} 눌림 거래량 {'감소 (정상)' if vol_decl else '감소 없음 — 주의'}"))

        # 위험 신호
        auto.append(("어닝",  f"{'❌ 어닝 임박!' if earning_warn else '✅ 어닝'} {earning_str}"))
        auto.append(("RSI",   f"{'❌' if rsi >= 75 else '⚠️' if rsi >= 65 else '✅'} RSI {rsi:.0f} {'— 과매수 위험' if rsi >= 75 else '— 과열 근접' if rsi >= 65 else ''}"))

        # ── 결과 조합 ──────────────────────────────────────
        lines = [f"<b>📊 ${ticker} — {name}</b>\n"]
        lines.append("━━ 🤖 자동 체크 ━━")
        for _, v in auto:
            lines.append(v)

        lines.append("\n━━ 👁 직접 확인 필요 ━━")
        lines.append("□ FOMC/경제지표 오늘 없는지")
        lines.append("□ VCP / C&H / HTF 패턴 차트 확인")
        lines.append("□ LREP 소형캔들 밀집 구간 확인")
        lines.append("□ ORB: 9:35 이후 5분봉 고/저가 기록")
        lines.append("□ ORB 계산기로 수량·목표가 산출")
        lines.append("□ R:R 1:2 이상 확인")
        lines.append("\n📖 <a href='https://gobabi.github.io/TopGainScreening/guide.html'>체크리스트 항목 해설 보기</a>")

        # 종합 판단
        bad = sum(1 for k, v in auto if v.startswith("❌"))
        warn = sum(1 for k, v in auto if v.startswith("⚠️"))
        if bad == 0 and warn <= 1:
            verdict = "\n🟢 조건 양호 — 패턴·ORB 확인 후 진입 판단"
        elif bad <= 1:
            verdict = f"\n🟡 주의 조건 {bad}개 — 신중하게 접근"
        else:
            verdict = f"\n🔴 부적합 조건 {bad}개 — 진입 재고"
        lines.append(verdict)

        send_message(chat_id, "\n".join(lines))
        print(f"[bot] /${ticker} 분석 완료")

    except Exception as e:
        send_message(chat_id, f"❌ {ticker} 분석 오류: {e}")



    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None

def _save_offset(offset):
    try:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except Exception:
        pass

def main():
    _acquire_single_instance()
    import atexit
    atexit.register(_release_single_instance)
    print("[bot] 텔레그램 봇 시작 — /report, /pre 대기 중... (자동 스케줄 포함)")
    offset = _load_offset()
    sent_flags: dict = {}
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            _save_offset(offset)
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = msg.get("chat", {}).get("id")
            if not chat_id:
                continue

            if text in ("/report", "/refresh") or text.startswith(("/report@", "/refresh@")):
                print(f"[bot] /report 수신 (chat_id={chat_id})")
                run_screening(chat_id, sent_flags)
            elif text == "/force" or text.startswith("/force@"):
                print(f"[bot] /force 수신 (chat_id={chat_id})")
                send_message(chat_id, "⚡ 강제 실행 — 장 시간 조건 무시")
                run_screening(chat_id, sent_flags, force=True)
            elif text == "/pre" or text.startswith("/pre@"):
                print(f"[bot] /pre 수신 (chat_id={chat_id})")
                scan_premarket(chat_id)
            elif text == "/test" or text.startswith("/test@"):
                print(f"[bot] /test 수신 (chat_id={chat_id})")
                run_test(chat_id)
            elif text == "/start":
                send_message(
                    chat_id,
                    "안녕하세요!\n\n"
                    "/report — 미국 주식 스크리닝 리포트 생성 및 전송\n"
                    "/force — 장 시간 무관하게 강제 스크리닝\n"
                    "/pre — 프리마켓 갭 상승 종목 스캔\n"
                    "/test — 서버 연결 및 데이터 진단\n"
                    "/$티커 — 종목 체크리스트 분석 (예: /NVDA)\n\n"
                    "📅 자동 전송: 장 마감 후 report / 개장 30분 전 pre"
                )
            elif text.startswith("/") and len(text) > 1:
                potential = text[1:].split("@")[0].upper().strip()
                if potential.isalpha() and 1 <= len(potential) <= 6:
                    print(f"[bot] /{potential} 티커 분석 수신 (chat_id={chat_id})")
                    analyze_ticker(chat_id, potential)

        _auto_schedule(sent_flags)
        time.sleep(30)


if __name__ == "__main__":
    main()
