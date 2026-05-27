"""
KR Market Top Gainers Screening
한국 주식(KOSPI) 상위 급등주 스크리닝
수동 실행 전용 — 자동 스케줄 없음
데이터 소스: 한국투자증권 KIS API (1차) → Yahoo Finance (폴백)
"""

import sys, os, json, warnings, requests
from html_report import build_html, send_telegram_html
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
JSON_OUT       = os.path.join(BASE_DIR, 'screening_result_kr.json')
WATCHLIST_FILE = os.path.join(BASE_DIR, 'watchlist_kr.json')
HTML_OUT_KR    = os.path.join(BASE_DIR, 'kr_market_screening_latest.html')

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = "7371637453"

def _report_date():
    now = datetime.now()
    if now.weekday() == 6:
        now = now - timedelta(days=1)
    return now.strftime('%Y-%m-%d')

TODAY = _report_date()

GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO     = "GOBABI/TopGainScreening"
GITHUB_API      = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
GH_HEADERS      = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
DATA_BRANCH      = "data"
GITHUB_PAGES_URL = "https://gobabi.github.io/TopGainScreening"
ARCHIVE_PATH_KR  = os.path.join(BASE_DIR, 'archive_kr.json')

# ── 한국투자증권 KIS API ──────────────────────────────────────────────
KIS_APP_KEY    = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
KIS_BASE       = "https://openapi.koreainvestment.com:9443"
_KIS_TOKEN_CACHE: dict = {"token": None, "expires": 0.0}
_KIS_DIAG: dict = {"token_ok": None, "token_msg": "", "api_rt": "", "api_msg": "", "api_items": -1, "api_keys": []}

SECTOR_KO = {
    'Healthcare': '헬스케어', 'Technology': '기술·IT',
    'Financial Services': '금융', 'Consumer Cyclical': '경기소비재',
    'Communication Services': '커뮤니케이션', 'Industrials': '산업재',
    'Energy': '에너지', 'Basic Materials': '소재',
    'Consumer Defensive': '필수소비재', 'Real Estate': '부동산',
    'Utilities': '유틸리티', 'Semiconductor': '반도체',
}
INDUSTRY_KO = {
    'Biotechnology': '바이오테크', 'Drug Manufacturers—Specialty & Generic': '제약',
    'Medical Devices': '의료기기', 'Diagnostics & Research': '진단·연구',
    'Semiconductors': '반도체', 'Software—Application': '응용 소프트웨어',
    'Software—Infrastructure': '인프라 소프트웨어', 'Internet Content & Information': '인터넷·정보',
    'Electronic Components': '전자부품', 'Communication Equipment': '통신장비',
    'Banks—Diversified': '종합 은행', 'Insurance': '보험',
    'Aerospace & Defense': '항공·방산', 'Oil & Gas E&P': '석유·가스 탐사',
    'Specialty Chemicals': '특수화학',
}
REC_KO = {'strong_buy':'강력매수','buy':'매수','hold':'보유',
           'underperform':'비중축소','sell':'매도'}

KR_SECTOR_LABEL = {
    'kospi': 'KOSPI', 'kosdaq': 'KOSDAQ', 'ks200': 'KOSPI 200',
}

_PYKRX_AVAILABLE = None

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default

# ── 데이터 수집 ───────────────────────────────────────────────────────
def _get_kis_token():
    """KIS OAuth 토큰 발급 (23시간 캐시)"""
    import time
    cache = _KIS_TOKEN_CACHE
    if cache["token"] and time.time() < cache["expires"]:
        _KIS_DIAG["token_ok"] = True
        return cache["token"]
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        log("KIS API 키 미설정 — Railway Variables에 KIS_APP_KEY / KIS_APP_SECRET 추가 필요")
        _KIS_DIAG["token_ok"] = False
        _KIS_DIAG["token_msg"] = "키 미설정"
        return ""
    try:
        r = requests.post(f"{KIS_BASE}/oauth2/tokenP",
            json={"grant_type": "client_credentials",
                  "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET},
            timeout=15)
        data = r.json()
        log(f"KIS 토큰 응답: HTTP {r.status_code}, rt_cd={data.get('rt_cd','?')}, msg={str(data.get('msg',''))[:60]}")
        token = data.get("access_token", "")
        if token:
            cache["token"]   = token
            cache["expires"] = time.time() + 3600 * 23
            log("KIS 토큰 발급 성공")
            _KIS_DIAG["token_ok"]  = True
            _KIS_DIAG["token_msg"] = "발급 성공"
        else:
            msg = str(data.get("msg", data.get("msg1", "")))[:80]
            log(f"KIS 토큰 없음 — 전체 응답: {str(data)[:300]}")
            _KIS_DIAG["token_ok"]  = False
            _KIS_DIAG["token_msg"] = f"HTTP {r.status_code} / {msg}"
        return token
    except Exception as e:
        log(f"KIS 토큰 오류: {e}")
        _KIS_DIAG["token_ok"]  = False
        _KIS_DIAG["token_msg"] = str(e)[:80]
        return ""

def _kis_fluctuation_request(token, mrkt_code, iscd, suffix):
    """KIS 변동률순위 API 호출 — KOSPI/KOSDAQ 공통"""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey":    KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id":     "FHPST01700000",
        "custtype":  "P",
    }
    params = {
        "fid_cond_mrkt_div_code":  mrkt_code,  # "J"=KOSPI, "Q"=KOSDAQ
        "fid_cond_scr_div_code":   "20170",
        "fid_input_iscd":          iscd,        # "0001"=KOSPI, "1001"=KOSDAQ
        "fid_rank_sort_cls_code":  "0",  # 0=상승률순(상위), 1=하락률순
        "fid_input_cnt_1":         "50",        # 최대 50개
        "fid_prc_cls_code":        "0",
        "fid_input_price_1":       "",
        "fid_input_price_2":       "",
        "fid_vol_cnt":             "0",
        "fid_trgt_cls_code":       "0",
        "fid_trgt_exls_cls_code":  "0000000000",
        "fid_div_cls_code":        "0",
        "fid_rsfl_rate1":          "5",   # 등락률 하한 5% (5%↑ 종목만 반환)
        "fid_rsfl_rate2":          "",
    }
    r = requests.get(f"{KIS_BASE}/uapi/domestic-stock/v1/ranking/fluctuation",
                     headers=headers, params=params, timeout=20)
    data = r.json()
    items = data.get("output", data.get("output1", []))
    rt_cd = data.get('rt_cd', '?')
    api_msg = str(data.get('msg1', data.get('msg', '')))[:80]
    item_cnt = len(items) if isinstance(items, list) else -1
    log(f"KIS [{mrkt_code}] 응답: HTTP {r.status_code}, rt_cd={rt_cd}, 항목={item_cnt}")
    results = []
    for s in (items if isinstance(items, list) else []):
        # 필드명 fallback: KIS API 버전에 따라 다를 수 있음
        ticker = (
            s.get("mksc_shrn_iscd") or
            s.get("stck_shrn_iscd") or
            s.get("iscd") or
            ""
        ).strip()
        if not ticker:
            continue
        price   = _safe_float(s.get("stck_prpr",  0))
        chg     = _safe_float(s.get("prdy_ctrt",  0))
        vol     = int(_safe_float(s.get("acml_vol",  0)))
        avg_vol = int(_safe_float(s.get("avrg_vol",  0)))
        shares  = int(_safe_float(s.get("lstn_stcn", 0)))
        results.append({
            "symbol":                     ticker + suffix,
            "shortName":                  s.get("hts_kor_isnm", ticker),
            "regularMarketPrice":         price,
            "regularMarketChangePercent": chg,
            "regularMarketVolume":        vol,
            "averageDailyVolume3Month":   avg_vol,
            "marketCap":                  price * shares,
            "fiftyTwoWeekHigh":           0,
            "twoHundredDayAverage":       0,
        })
    return results, rt_cd, api_msg, item_cnt, data.keys(), items


def _fetch_gainers_kis():
    """한국투자증권 API — KOSPI 상승률 상위 50개 (FHPST01700000)"""
    token = _get_kis_token()
    if not token:
        log("KIS 토큰 없음")
        return []
    try:
        results, rt_cd, api_msg, item_cnt, data_keys, items = _kis_fluctuation_request(
            token, "J", "0001", ".KS")
        _KIS_DIAG["api_rt"]    = f"HTTP 200 / rt_cd={rt_cd}"
        _KIS_DIAG["api_msg"]   = api_msg
        _KIS_DIAG["api_items"] = item_cnt
        _KIS_DIAG["api_keys"]  = list(data_keys)
        first_item_keys = list(items[0].keys()) if isinstance(items, list) and items else []
        _KIS_DIAG["item_keys"] = first_item_keys
        first_item_sample = str(items[0])[:200] if isinstance(items, list) and items else ""
        _KIS_DIAG["item_sample"] = first_item_sample
        if items:
            log(f"KIS 첫 항목 keys: {first_item_keys}")
            log(f"KIS 첫 항목 샘플: {first_item_sample}")
            ticker_summary = ", ".join(
                f"{s.get('hts_kor_isnm','?')}({s.get('stck_shrn_iscd','?')}) {s.get('prdy_ctrt','?')}%"
                for s in (items[:20] if isinstance(items, list) else [])
            )
            _KIS_DIAG["ticker_summary"] = ticker_summary
            log(f"KIS 상위 20개: {ticker_summary}")
        log(f"KIS KOSPI 상승률 순위: {len(results)}개")
        return results
    except Exception as e:
        log(f"KIS 변동률 순위 오류: {e}")
        _KIS_DIAG["api_rt"]  = "오류"
        _KIS_DIAG["api_msg"] = str(e)[:80]
        return []

def _check_pykrx():
    global _PYKRX_AVAILABLE
    if _PYKRX_AVAILABLE is None:
        try:
            import pykrx  # noqa: F401
            _PYKRX_AVAILABLE = True
        except ImportError:
            _PYKRX_AVAILABLE = False
    return _PYKRX_AVAILABLE

def _fetch_gainers_pykrx():
    """pykrx로 KOSPI 당일 상승률 상위 50개 반환 (KIS API 실패 시 최후 폴백)"""
    try:
        from pykrx import stock
        date_str = datetime.now().strftime('%Y%m%d')
        results = []
        for market, suffix in [('KOSPI', '.KS')]:
            try:
                df = stock.get_market_ohlcv_by_ticker(date_str, market=market)
                if df is None or df.empty:
                    continue
                df = df[df['거래량'] > 50000].copy()
                chg_col = '등락률' if '등락률' in df.columns else None
                if chg_col:
                    df['change_pct'] = df[chg_col]
                else:
                    df['change_pct'] = (df['종가'] - df['시가']) / df['시가'] * 100
                df = df[df['change_pct'] >= 5].sort_values('change_pct', ascending=False).head(30)
                for ticker_code, row in df.iterrows():
                    sym = str(ticker_code) + suffix
                    try:
                        name = stock.get_market_ticker_name(str(ticker_code))
                    except Exception:
                        name = str(ticker_code)
                    results.append({
                        'symbol': sym,
                        'shortName': name,
                        'regularMarketPrice': float(row['종가']),
                        'regularMarketChangePercent': float(row['change_pct']),
                        'regularMarketVolume': int(row['거래량']),
                        'averageDailyVolume3Month': 0,
                        'marketCap': 0,
                        'fiftyTwoWeekHigh': float(row['고가']),
                        'twoHundredDayAverage': 0,
                    })
            except Exception as e:
                log(f"  pykrx {market} 오류: {e}")
        results.sort(key=lambda x: x['regularMarketChangePercent'], reverse=True)
        return results[:50]
    except Exception as e:
        log(f"pykrx 전체 오류: {e}")
        return []

def _fetch_gainers_yf_kr():
    """Yahoo Finance REST로 KR 당일 급등주 조회"""
    url = ("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
           "?formatted=false&lang=ko-KR&region=KR&scrIds=day_gainers&count=50")
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        return data['finance']['result'][0].get('quotes', [])
    except Exception as e:
        log(f"Yahoo KR 폴백 실패({e})")
        return []

def fetch_gainers_kr():
    log("한국 Top Gainers (KOSPI) 수집 중...")
    FIELDS = ['symbol','shortName','regularMarketPrice','regularMarketChangePercent',
              'regularMarketVolume','averageDailyVolume3Month','marketCap',
              'fiftyTwoWeekHigh','twoHundredDayAverage']

    if KIS_APP_KEY and KIS_APP_SECRET:
        quotes = _fetch_gainers_kis()
        if quotes:
            return quotes
        log("  KIS API 실패 — Yahoo 폴백 시도")

    import yfinance as yf

    quotes = []
    try:
        result = yf.screen("day_gainers", count=50)
        raw = result.get('quotes', [])
        quotes = [q for q in raw if str(q.get('symbol','')).endswith('.KS')]
        if quotes:
            log(f"  yf.screen KR 결과: {len(quotes)}개")
    except Exception as e:
        log(f"  yf.screen 실패({e})")

    if not quotes:
        raw2 = _fetch_gainers_yf_kr()
        quotes = [q for q in raw2 if str(q.get('symbol','')).endswith('.KS')]
        log(f"  Yahoo KR REST 결과: {len(quotes)}개")

    if not quotes and _check_pykrx():
        log("  pykrx 폴백 시도...")
        quotes = _fetch_gainers_pykrx()
        return quotes

    return [{k: q.get(k) or 0 for k in FIELDS} for q in quotes]

def fetch_market_kr():
    import yfinance as yf
    out = {}
    symbols = [
        ('^KS11', 'kospi'),
        ('^KQ11', 'kosdaq'),
        ('^KS200', 'ks200'),
    ]
    for sym, key in symbols:
        try:
            h = yf.Ticker(sym).history(period='5d')
            if len(h) < 2:
                continue
            p, p1 = float(h['Close'].iloc[-1]), float(h['Close'].iloc[-2])
            pw = float(h['Close'].iloc[0])
            out[key] = {
                'price': round(p, 2),
                'chg':   round((p - p1) / p1 * 100, 2),
                'week':  round((p - pw) / pw * 100, 2),
            }
        except Exception as e:
            log(f"  시장 데이터 오류 {sym}: {e}")
    return out

def fetch_ticker_detail(ticker):
    import yfinance as yf
    t = yf.Ticker(ticker)
    FIELDS = ['longName','shortName','longBusinessSummary','sector','industry',
              'targetMeanPrice','recommendationKey','numberOfAnalystOpinions',
              'trailingPE','forwardPE','revenueGrowth','earningsGrowth',
              'shortPercentOfFloat','beta']
    try:
        info = t.info
        data = {k: info.get(k) for k in FIELDS}
    except Exception:
        data = {k: None for k in FIELDS}
    try:
        news_raw = t.news or []
        data['news'] = [
            {'title': n.get('content', {}).get('title', '') or n.get('title', ''),
             'publisher': n.get('content', {}).get('provider', {}).get('displayName', '') or n.get('publisher', '')}
            for n in news_raw[:5]
            if (n.get('content', {}).get('title') or n.get('title'))
        ]
    except Exception:
        data['news'] = []
    return data

# ── 기술적 지표 계산 ────────────────────────────────────────────────
def calc_rsi(prices, p=14):
    d = prices.diff()
    g = d.where(d > 0, 0).rolling(p).mean()
    l = -d.where(d < 0, 0).rolling(p).mean()
    return float((100 - 100 / (1 + g / (l + 1e-10))).iloc[-1])

def calc_adx(high, low, close, p=14):
    import pandas as pd
    hi = high.reset_index(drop=True)
    lo = low.reset_index(drop=True)
    cl = close.reset_index(drop=True)
    tr, dp, dm = [], [], []
    for i in range(1, len(cl)):
        tr.append(max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1])))
        u, d_ = hi[i]-hi[i-1], lo[i-1]-lo[i]
        dp.append(u if u > d_ and u > 0 else 0)
        dm.append(d_ if d_ > u and d_ > 0 else 0)
    tr_s  = pd.Series(tr).ewm(alpha=1/p, adjust=False).mean()
    di_p  = 100 * pd.Series(dp).ewm(alpha=1/p, adjust=False).mean() / (tr_s + 1e-10)
    di_m  = 100 * pd.Series(dm).ewm(alpha=1/p, adjust=False).mean() / (tr_s + 1e-10)
    dx    = 100 * (di_p - di_m).abs() / (di_p + di_m + 1e-10)
    return float(dx.ewm(alpha=1/p, adjust=False).mean().iloc[-1])

def calc_macd_signal(prices):
    e12 = prices.ewm(span=12, adjust=False).mean()
    e26 = prices.ewm(span=26, adjust=False).mean()
    m   = e12 - e26
    s   = m.ewm(span=9, adjust=False).mean()
    return bool(m.iloc[-1] > s.iloc[-1] and m.iloc[-2] <= s.iloc[-2])

def qullamaggie_position(price, ma200, high52, ytd):
    pct52      = price / high52 * 100 if high52 > 0 else 0
    above_pct  = (price - ma200) / ma200 * 100 if ma200 > 0 else 0
    if ytd >= 100 and pct52 >= 90:
        return 'a', '급등 초입 모멘텀 (30~100%↑ 초기 단계)'
    elif ytd >= 30 and pct52 < 85:
        return 'b', '1~3개월 조정 후 재돌파 구간 (선호)'
    elif pct52 >= 90 and above_pct < 20:
        return 'b', '신고가권 타이트 횡보 (최적진입구간 최적)'
    elif above_pct > 50:
        return 'a', '200MA 대비 고점권 — 추격 주의'
    else:
        return 'c', '일반 상승 구간'

def analyze(ticker):
    import yfinance as yf
    try:
        h = yf.Ticker(ticker).history(period='2y')
    except Exception as e:
        log(f"    history 오류 {ticker}: {e}")
        return None
    if len(h) < 50:
        return None

    c, hi, lo = h['Close'], h['High'], h['Low']
    ma200  = c.rolling(200).mean()
    ma200v = float(ma200.dropna().iloc[-1]) if len(ma200.dropna()) > 0 else None
    price  = float(c.iloc[-1])
    if not ma200v:
        return None

    rsi       = calc_rsi(c)
    adx       = calc_adx(hi, lo, c)
    macd_bull = calc_macd_signal(c)
    high52    = float(c[-252:].max())
    pct52     = round(price / high52 * 100, 1) if high52 > 0 else 0
    adr       = round(((hi[-20:] / lo[-20:]) - 1).mean() * 100, 1)

    ytd_h = h[h.index >= f"{datetime.now().year}-01-01"]
    ytd = (round((price - float(ytd_h['Close'].iloc[0])) / float(ytd_h['Close'].iloc[0]) * 100, 1)
           if len(ytd_h) > 0 else 0)

    ql_pos, ql_desc = qullamaggie_position(price, ma200v, high52, ytd)

    vol_trend = 'N/A'
    vol_contraction = False
    if len(h) >= 20:
        avg_vol_20 = float(h['Volume'][-20:].mean())
        avg_vol_5  = float(h['Volume'][-5:].mean())
        vol_trend  = '증가' if avg_vol_5 > avg_vol_20 * 1.2 else ('감소' if avg_vol_5 < avg_vol_20 * 0.8 else '보합')
        vols = h['Volume'][-20:].values
        q1 = vols[:5].mean()
        q2 = vols[5:10].mean()
        q3 = vols[10:15].mean()
        q4 = vols[15:].mean()
        vol_contraction = bool((q4 < q3 and q3 < q2) or (q4 < q1 * 0.7))

    return {
        '200ma':           round(ma200v, 2),
        'above_200ma':     bool(price > ma200v),
        'rsi':             round(rsi, 1),
        'adx':             round(adx, 1),
        'macd_bull':       bool(macd_bull),
        '52w_pct':         pct52,
        '52w_high':        round(high52, 2),
        'ytd':             ytd,
        'adr':             adr,
        'ql_pos':          ql_pos,
        'ql_desc':         ql_desc,
        'vol_trend':       vol_trend,
        'vol_contraction': vol_contraction,
    }

AI_SECTORS = {'technology','semiconductor','defense','energy','aerospace',
              '반도체','기술','방산','에너지','바이오'}

def score_stock(ta, sector, industry):
    s = 0
    if ta['adx'] > 25:                                        s += 2
    if 40 <= ta['rsi'] <= 75:                                 s += 2
    if ta['macd_bull']:                                        s += 2
    if ta['52w_pct'] >= 90:                                   s += 1
    if ta['ytd'] >= 50:                                        s += 1
    if ta.get('vol_contraction') and ta['ql_pos'] == 'b':    s += 2
    combo = (sector + industry).lower()
    if any(k in combo for k in AI_SECTORS):                  s += 1
    return s

def auto_risks(ta, detail):
    risks = []
    if ta['rsi'] > 70:
        risks.append(f"RSI {ta['rsi']:.0f} — 단기 과열 구간, 눌림 가능성")
    if ta['adr'] > 5:
        risks.append(f"ADR {ta['adr']:.1f}% — 변동성 큼, 포지션 사이징 주의")
    short_pct = detail.get('shortPercentOfFloat') or 0
    if short_pct and short_pct > 0.1:
        risks.append(f"공매도 비율 {short_pct*100:.1f}% — 숏 스퀴즈 또는 추가 하락 리스크")
    if ta['ql_pos'] == 'a' and ta['ytd'] >= 100:
        risks.append("YTD 100%↑ 급등주 — 차익실현 매물 출회 주의")
    if not ta['macd_bull']:
        risks.append("MACD 아직 매수신호 미발생 — 타이밍 추가 확인 권장")
    if ta['ql_pos'] == 'b' and not ta.get('vol_contraction'):
        risks.append("b 구간이나 거래량 수축 미확인 — 베이스 품질 재점검 필요")
    beta = detail.get('beta') or 0
    if beta and beta > 2:
        risks.append(f"Beta {beta:.1f} — 시장 변동 시 과대 반응 가능")
    if not risks:
        risks.append("주요 기술적 리스크 없음 — 손절 원칙 준수")
    return risks

def korean_desc(detail, ta, q):
    name     = detail.get('longName') or q.get('shortName', '')
    sector   = detail.get('sector', '')
    industry = detail.get('industry', '')
    s_ko     = SECTOR_KO.get(sector, sector)
    i_ko     = INDUSTRY_KO.get(industry, industry)
    _rev_g   = detail.get('revenueGrowth')
    try:
        rev_g = float(_rev_g) if _rev_g is not None else 0
    except (ValueError, TypeError):
        rev_g = 0
    _pe  = detail.get('forwardPE')
    try:
        pe_fwd = float(_pe) if _pe is not None else 0
    except (ValueError, TypeError):
        pe_fwd = 0
    analysts = detail.get('numberOfAnalystOpinions') or 0
    rec      = detail.get('recommendationKey', '')
    rec_ko   = {'strong_buy':'강력매수','buy':'매수','hold':'보유'}.get(rec,'')

    growth_txt = ''
    if rev_g > 0.3:
        growth_txt = f'매출 성장률 {rev_g*100:.0f}%로 고성장 중이며'
    elif rev_g > 0:
        growth_txt = f'매출 성장률 {rev_g*100:.0f}%의 안정적 성장세를 유지하며'
    elif rev_g < 0:
        growth_txt = f'매출이 {abs(rev_g)*100:.0f}% 감소하는 역성장 구간에 있으며'

    val_txt = ''
    if pe_fwd and pe_fwd > 0:
        if pe_fwd < 15:
            val_txt = f'선행 P/E {pe_fwd:.0f}배로 저평가 구간에 위치'
        elif pe_fwd < 35:
            val_txt = f'선행 P/E {pe_fwd:.0f}배의 합리적 밸류에이션'
        else:
            val_txt = f'선행 P/E {pe_fwd:.0f}배로 고성장 프리미엄 반영'

    tech_txt = ''
    if ta['52w_pct'] >= 90:
        tech_txt = '52주 신고가권에서 강한 모멘텀을 보이고 있습니다'
    elif ta['ytd'] >= 50:
        tech_txt = f'연초 대비 {ta["ytd"]:+.0f}%의 강한 YTD 모멘텀을 보유하고 있습니다'
    else:
        tech_txt = '200MA 위에서 상승 추세를 유지하고 있습니다'

    analyst_txt = f'애널리스트 {analysts}명 컨센서스 {rec_ko}.' if analysts and rec_ko else ''
    desc = (f"{name}은(는) {s_ko} / {i_ko} 분야 기업입니다. "
            f"{f'{growth_txt} ' if growth_txt else ''}"
            f"{f'{val_txt}. ' if val_txt else ''}"
            f"{tech_txt}. {analyst_txt}")
    return desc.strip()

# ── 스크리닝 메인 로직 ────────────────────────────────────────────────
KR_MARKET_CAP_MAX = 50_000_000_000_000  # 50조 KRW

def run_screening_kr(gainers):
    def _vol_ok(q):
        avg = q['averageDailyVolume3Month'] or 0
        if avg == 0:
            return q['regularMarketVolume'] >= 50_000
        return q['regularMarketVolume'] >= avg * 1.5

    p1 = [q for q in gainers
          if q['regularMarketChangePercent'] >= 5
          and q['regularMarketPrice'] >= 1000
          and _vol_ok(q)
          and (q['marketCap'] == 0 or q['marketCap'] < KR_MARKET_CAP_MAX)]
    log(f"1차 통과: {len(p1)}개")

    passed = []
    for q in p1:
        ticker = q['symbol']
        log(f"  분석: {ticker}")
        ta = analyze(ticker)
        if not ta or not ta['above_200ma'] or ta['rsi'] >= 80:
            continue

        detail   = fetch_ticker_detail(ticker)
        sector   = detail.get('sector') or ''
        industry = detail.get('industry') or ''
        sc       = score_stock(ta, sector, industry)
        avg_vol  = q['averageDailyVolume3Month'] or 1

        rev_g_raw  = detail.get('revenueGrowth')
        rev_growth = round(rev_g_raw * 100, 1) if rev_g_raw is not None else None
        catalysts  = [n['title'] for n in detail.get('news', []) if n.get('title')]

        passed.append({
            'ticker':         ticker,
            'exchange':       q.get('exchange', 'KRX'),
            'name':           q.get('shortName') or '',
            'full_name':      detail.get('longName') or q.get('shortName') or '',
            'price':          round(q['regularMarketPrice'], 0),
            'change_pct':     round(q['regularMarketChangePercent'], 2),
            'volume':         q['regularMarketVolume'],
            'avg_vol':        avg_vol,
            'vol_ratio':      round(q['regularMarketVolume'] / avg_vol, 1),
            'market_cap':     q['marketCap'],
            'sector':         sector,
            'industry':       industry,
            'summary':        detail.get('longBusinessSummary') or '',
            'korean_desc':    korean_desc(detail, ta, q),
            'analyst_target': detail.get('targetMeanPrice') or 0,
            'analyst_rec':    detail.get('recommendationKey') or '',
            'analyst_cnt':    detail.get('numberOfAnalystOpinions') or 0,
            'pe_trailing':    detail.get('trailingPE') or 0,
            'pe_forward':     detail.get('forwardPE') or 0,
            'rev_growth':     rev_growth,
            'catalysts':      catalysts,
            'risks':          auto_risks(ta, detail),
            **ta,
            'score': sc,
        })

    passed.sort(key=lambda x: x['score'], reverse=True)
    log(f"2차 통과: {len(passed)}개")
    return passed

# ── GitHub 동기화 ─────────────────────────────────────────────────────
def _gh_upsert_data(filename, content_str):
    import base64
    encoded = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
    url = f"{GITHUB_API}/{filename}"
    r = requests.get(url, headers=GH_HEADERS, params={"ref": DATA_BRANCH}, timeout=10)
    sha = r.json().get('sha') if r.status_code == 200 else None
    payload = {"message": f"{filename} update {TODAY}", "content": encoded, "branch": DATA_BRANCH}
    if sha:
        payload["sha"] = sha
    r2 = requests.put(url, headers=GH_HEADERS, json=payload, timeout=15)
    if r2.status_code not in (200, 201):
        log(f"GitHub data push 실패 ({filename}): {r2.status_code} {r2.text[:80]}")

def _gh_read_data(filename):
    import base64
    r = requests.get(f"{GITHUB_API}/{filename}", headers=GH_HEADERS,
                     params={"ref": DATA_BRANCH}, timeout=10)
    if r.status_code == 200:
        return base64.b64decode(r.json()['content']).decode('utf-8')
    return None

def _is_after_kr_market_close():
    """KST 기준 정규장 마감(15:30) 이후인지 확인"""
    import pytz
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.now(kst)
    if now.weekday() >= 5:
        return True
    return (now.hour, now.minute) >= (15, 30)

# ── 워치리스트 ─────────────────────────────────────────────────────────
def load_watchlist():
    try:
        content = _gh_read_data("watchlist_kr.json")
        if content:
            with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            log(f"KR watchlist 로드: {len(json.loads(content).get('tickers',{}))}개")
        else:
            log("KR watchlist data 브랜치 없음 — 로컬 시도")
    except Exception as e:
        log(f"KR watchlist 로드 예외: {e}")
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"tickers": {}}

def save_watchlist(wl):
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(wl, f, ensure_ascii=False, indent=2)

def days_since_date(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return (datetime.now() - d).days
    except Exception:
        return 0

def watch_status(days, appearances, ql_pos):
    if days == 0:
        return "신규 등장", "orange"
    elif days <= 2:
        return f"{days}일차 — 베이스 형성 대기", "gold"
    elif days <= 7:
        if ql_pos == 'b':
            return f"{days}일차 — 진입 가능 (b 선호)", "green"
        return f"{days}일차 — 진입 가능 구간", "green"
    elif days <= 15:
        return f"{days}일차 — 최적진입구간 트리거 대기", "teal"
    else:
        return f"{days}일차 — 재평가 필요", "red"

def _is_reentry(last_seen_str):
    try:
        last = datetime.strptime(last_seen_str, '%Y-%m-%d').date()
        today = datetime.strptime(TODAY, '%Y-%m-%d').date()
        if today <= last:
            return False
        gap = 0
        cur = last + timedelta(days=1)
        while cur <= today:
            if cur.weekday() < 5:
                gap += 1
            cur += timedelta(days=1)
        return gap > 1
    except Exception:
        return False

def update_watchlist(passed):
    wl = load_watchlist()
    tickers = wl.get("tickers", {})
    for s in passed:
        tk = s['ticker']
        ta_snapshot = {
            'last_rsi':       round(s.get('rsi', 0), 1),
            'last_adx':       round(s.get('adx', 0), 1),
            'last_macd_bull': bool(s.get('macd_bull', False)),
            'last_52w_pct':   round(s.get('52w_pct', 0), 1),
            'last_ytd':       round(s.get('ytd', 0), 1),
        }
        if tk in tickers:
            e = tickers[tk]
            if _is_reentry(e.get('last_seen', TODAY)):
                log(f"  재진입 감지 [{tk}]: first_seen 리셋")
                e['first_seen']  = TODAY
                e['appearances'] = 1
            elif e.get('last_seen') != TODAY:
                e['appearances'] = e.get('appearances', 1) + 1
            e.update({
                'last_seen': TODAY, 'last_price': s['price'],
                'last_change_pct': s['change_pct'], 'last_score': s['score'],
                'last_ql_pos': s['ql_pos'], 'last_ql_desc': s['ql_desc'],
                'name': s['name'], 'sector': s['sector'],
                'industry': s.get('industry', ''),
                'exchange': s.get('exchange', e.get('exchange', 'KRX')),
                **ta_snapshot,
            })
        else:
            tickers[tk] = {
                'first_seen': TODAY, 'last_seen': TODAY, 'appearances': 1,
                'last_price': s['price'], 'last_change_pct': s['change_pct'],
                'last_score': s['score'], 'last_ql_pos': s['ql_pos'],
                'last_ql_desc': s['ql_desc'], 'name': s['name'],
                'sector': s['sector'], 'industry': s.get('industry', ''),
                'exchange': s.get('exchange', 'KRX'),
                **ta_snapshot,
            }
    wl['tickers'] = tickers
    save_watchlist(wl)
    log(f"KR 관심종목 업데이트: {len(tickers)}개 누적")
    return wl

def refresh_watchlist_ta(wl, today_tickers):
    import yfinance as yf
    tickers = wl.get('tickers', {})
    stale = [tk for tk in tickers if tk not in today_tickers]
    if not stale:
        return wl
    log(f"KR 워치리스트 TA 갱신: {len(stale)}개")
    for tk in stale:
        ta = analyze(tk)
        if not ta:
            continue
        e = tickers[tk]
        try:
            price = float(yf.Ticker(tk).history(period='1d')['Close'].iloc[-1])
            e['last_price'] = round(price, 0)
        except Exception:
            pass
        sector = e.get('sector', ''); industry = e.get('industry', '')
        e.update({
            'last_rsi': round(ta['rsi'], 1), 'last_adx': round(ta['adx'], 1),
            'last_macd_bull': bool(ta['macd_bull']),
            'last_52w_pct': round(ta['52w_pct'], 1), 'last_ytd': round(ta['ytd'], 1),
            'last_ql_pos': ta['ql_pos'], 'last_ql_desc': ta['ql_desc'],
            'last_score': score_stock(ta, sector, industry), 'last_seen': TODAY,
        })
    save_watchlist(wl)
    return wl

def push_watchlist():
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        _gh_upsert_data("watchlist_kr.json", content)
        log("GitHub watchlist_kr.json push 완료")
    except Exception as e:
        log(f"GitHub KR watchlist push 실패: {e}")

# ── JSON 덤프 ─────────────────────────────────────────────────────────
def dump_json(passed, mkt, wl=None):
    compact = {
        'date': TODAY,
        'market': {k: mkt.get(k, {}) for k in ['kospi', 'kosdaq', 'ks200']},
        'passed': [{
            'ticker': s['ticker'], 'name': s['name'], 'sector': s['sector'],
            'change_pct': s['change_pct'], 'price': s['price'],
            'rsi': s['rsi'], 'adx': s['adx'], 'score': s['score'],
            'ql_pos': s['ql_pos'], 'ql_desc': s['ql_desc'],
            'ytd': s['ytd'], '52w_pct': s['52w_pct'],
            'macd_bull': s['macd_bull'], 'above_200ma': s['above_200ma'],
            'catalysts': s['catalysts'][:3], 'risks': s['risks'],
            'analyst_rec': s['analyst_rec'], 'analyst_target': s['analyst_target'],
            'summary': (s['summary'] or '')[:200],
        } for s in passed],
        'passed_count': len(passed),
        'watchlist': {
            tk: {
                'first_seen': e.get('first_seen'),
                'days': days_since_date(e.get('first_seen', TODAY)),
                'appearances': e.get('appearances', 1),
                'last_score': e.get('last_score', 0),
                'last_ql_pos': e.get('last_ql_pos', ''),
                'status': watch_status(
                    days_since_date(e.get('first_seen', TODAY)),
                    e.get('appearances', 1), e.get('last_ql_pos', '')
                )[0],
            }
            for tk, e in (wl.get('tickers', {}) if wl else {}).items()
        },
    }
    with open(JSON_OUT, 'w', encoding='utf-8') as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    log(f"JSON 덤프: {JSON_OUT}")

# ── 내러티브 생성 ─────────────────────────────────────────────────────
def build_narrative(passed, mkt):
    kospi = mkt.get('kospi', {}); kosdaq = mkt.get('kosdaq', {})
    kospi_chg  = kospi.get('chg', 0)
    kosdaq_chg = kosdaq.get('chg', 0)
    mkt_status = ("약세" if kospi_chg < -0.5 and kosdaq_chg < -0.5
                  else "강세" if kospi_chg > 0.5 and kosdaq_chg > 0.5 else "혼조")

    lines = [
        f"📝 한국 시장 스크리닝 코멘트 [{TODAY}]",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "📰 시장 코멘트",
        f"코스피 {kospi_chg:+.2f}% / 코스닥 {kosdaq_chg:+.2f}%로 {mkt_status} 마감했습니다.",
        "",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if not passed:
        lines.append("❌ 오늘은 조건에 맞는 종목이 없었습니다.")
    else:
        lines.append(f"🔍 통과 종목 분석 (총 {len(passed)}개)")
        lines.append("")
        for i, s in enumerate(passed, 1):
            catalyst  = s['catalysts'][0] if s['catalysts'] else "기술적 모멘텀 중심"
            main_risk = s['risks'][0] if s['risks'] else "손절 원칙 준수"
            lines.append(f"#{i} {s['ticker']} — {s['name']}")
            lines.append(f"• 오늘 +{s['change_pct']:.1f}% 상승. {catalyst[:60]}")
            lines.append(f"• 모멘텀 위치: {s['ql_pos']} — {s['ql_desc']}")
            lines.append(f"• 체크: RSI {s['rsi']:.0f} / ADX {s['adx']:.0f} / 점수 {s['score']}/9")
            lines.append(f"• 주의: {main_risk[:60]}")
            lines.append("")

    lines += ["━━━━━━━━━━━━━━━━━━", "⚠️ 투자 책임은 본인에게 있습니다"]
    return "\n".join(lines)

def _send_one_message(text):
    import time
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={'chat_id': CHAT_ID, 'text': text},
                timeout=30
            )
            if r.ok and r.json().get('ok'):
                return
        except Exception as e:
            log(f"텔레그램 재시도 {attempt+1}: {e}")
        time.sleep(5)

def send_telegram_narrative(text):
    import time
    LIMIT = 4000
    if len(text) <= LIMIT:
        _send_one_message(text)
        return
    chunks, buf = [], ""
    for line in text.split("\n"):
        candidate = buf + line + "\n"
        if len(candidate) > LIMIT:
            if buf:
                chunks.append(buf.rstrip("\n"))
            buf = line + "\n"
        else:
            buf = candidate
    if buf:
        chunks.append(buf.rstrip("\n"))
    for i, chunk in enumerate(chunks, 1):
        _send_one_message(chunk)
        if i < len(chunks):
            time.sleep(1)

def load_archive_dates():
    try:
        content = _gh_read_data("archive_kr.json")
        if content:
            with open(ARCHIVE_PATH_KR, 'w') as f:
                f.write(content)
    except Exception:
        pass
    if os.path.exists(ARCHIVE_PATH_KR):
        with open(ARCHIVE_PATH_KR, 'r') as f:
            return json.load(f).get('dates', [])
    return []

def save_archive_dates(dates):
    with open(ARCHIVE_PATH_KR, 'w') as f:
        json.dump({'dates': dates}, f)
    try:
        _gh_upsert_data("archive_kr.json", json.dumps({'dates': dates}))
    except Exception as e:
        log(f"KR archive push 실패: {e}")

def github_pages_deploy_kr(archive_dates):
    import base64
    if not os.path.exists(HTML_OUT_KR):
        log("KR HTML 파일 없음 — GitHub Pages 배포 스킵")
        return
    try:
        with open(HTML_OUT_KR, 'rb') as f:
            html_b64 = base64.b64encode(f.read()).decode()
        base_url = f"https://api.github.com/repos/{GITHUB_REPO}"

        def _upsert(path, content_b64):
            url = f"{base_url}/contents/{path}"
            r_get = requests.get(url, headers=GH_HEADERS, params={"ref": "gh-pages"}, timeout=15)
            sha = r_get.json().get("sha") if r_get.ok else None
            payload = {"message": f"deploy kr: {TODAY}", "content": content_b64, "branch": "gh-pages"}
            if sha:
                payload["sha"] = sha
            r_put = requests.put(url, headers=GH_HEADERS, json=payload, timeout=60)
            if not r_put.ok:
                log(f"gh-pages 업로드 실패 [{path}] HTTP {r_put.status_code}: {r_put.text[:200]}")
            return r_put.ok

        if not GITHUB_TOKEN:
            log("❌ GITHUB_TOKEN 미설정 — GitHub Pages 배포 스킵")
            return

        ok1 = _upsert("kr_index.html", html_b64)
        ok2 = _upsert(f"kr_{TODAY}.html", html_b64)
        if ok1 and ok2:
            log("✅ KR GitHub Pages 배포 완료")
        else:
            log(f"⚠️ KR GitHub Pages 업로드 실패 (ok1={ok1}, ok2={ok2})")
    except Exception as e:
        log(f"KR GitHub Pages 배포 실패: {e}")

# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    try:
        gainers  = fetch_gainers_kr()
        mkt      = fetch_market_kr()

        kis_ok = bool(KIS_APP_KEY and KIS_APP_SECRET)
        tok_ok  = _KIS_DIAG.get("token_ok")
        tok_msg = _KIS_DIAG.get("token_msg", "")
        api_rt  = _KIS_DIAG.get("api_rt", "미호출")
        api_msg = _KIS_DIAG.get("api_msg", "")
        api_items   = _KIS_DIAG.get("api_items", -1)
        api_keys    = _KIS_DIAG.get("api_keys", [])
        item_keys   = _KIS_DIAG.get("item_keys", [])
        item_sample = _KIS_DIAG.get("item_sample", "")
        tok_line = (
            f"{'✅' if tok_ok else '❌'} 토큰: {tok_msg}"
            if tok_ok is not None else "⏭ 토큰: 캐시 사용"
        )
        ticker_summary = _KIS_DIAG.get("ticker_summary", "")
        _send_one_message(
            "🔬 KRX 진단\n"
            f"• KIS 키: {'✅ 설정됨' if kis_ok else '❌ 미설정'}\n"
            f"• {tok_line}\n"
            f"• KIS API: {api_rt}\n"
            f"• KIS msg: {api_msg or '(없음)'}\n"
            f"• KIS 항목: {api_items if api_items >= 0 else '미호출'}개\n"
            f"• KIS 상위목록: {ticker_summary[:300] or '(없음)'}\n"
            f"• 수집된 종목: {len(gainers)}개\n"
            f"• 오늘 날짜: {TODAY}"
        )

        passed        = run_screening_kr(gainers)
        wl            = update_watchlist(passed)
        today_tickers = {s['ticker'] for s in passed}
        wl            = refresh_watchlist_ta(wl, today_tickers)
        dump_json(passed, mkt, wl)
        archive_dates = load_archive_dates()
        if _is_after_kr_market_close() and TODAY not in archive_dates:
            archive_dates.append(TODAY)
            save_archive_dates(archive_dates)
        build_html(passed, mkt, wl, archive_dates, currency='KRW', html_out=HTML_OUT_KR)
        send_telegram_html(passed, mkt, currency='KRW')
        narrative = build_narrative(passed, mkt)
        send_telegram_narrative(narrative)
        push_watchlist()
        github_pages_deploy_kr(archive_dates)
        log(f"KR 완료 — 통과 {len(passed)}개 / 누적 관심 {len(wl.get('tickers',{}))}개")
        print(f"RESULT_JSON={JSON_OUT}")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"오류: {e}\n{tb}")
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={'chat_id': CHAT_ID, 'text': f"❌ KRX 스크리닝 오류\n{str(e)[:300]}"},
                timeout=10,
            )
        except Exception:
            pass

if __name__ == '__main__':
    main()
