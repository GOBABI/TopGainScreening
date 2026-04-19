"""
US Market Top Gainers Screening
Thales LREP + Qullamaggie Framework
v6 — 경로 고정 / API 호환성 개선 / 버그 수정
"""

import sys, os, json, warnings, requests
from datetime import datetime
warnings.filterwarnings('ignore')

# ── 경로 설정 (환경에 관계없이 고정) ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_R   = os.path.join(BASE_DIR, 'PretendardVariable.ttf')
FONT_B   = os.path.join(BASE_DIR, 'PretendardVariable.ttf')
FONT_SB  = os.path.join(BASE_DIR, 'PretendardVariable.ttf')
PDF_OUT       = os.path.join(BASE_DIR, 'us_market_screening_latest.pdf')
JSON_OUT      = os.path.join(BASE_DIR, 'screening_result.json')
WATCHLIST_FILE = os.path.join(BASE_DIR, 'watchlist.json')

BOT_TOKEN  = "8702268897:AAEhRnt0nuBnYCJeMdhofbX_h-D_YBTJxCE"
CHAT_ID    = "7371637453"
TODAY      = datetime.now().strftime('%Y-%m-%d')

GITHUB_TOKEN = "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"
GITHUB_REPO  = "GOBABI/TopGainScreening"
GITHUB_API   = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
GH_HEADERS   = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# ── 한국어 매핑 ────────────────────────────────────────────────────────
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
    'Specialty Chemicals': '특수화학', 'REIT—Industrial': '산업 리츠',
}
REC_KO = {'strong_buy':'강력매수','buy':'매수','hold':'보유',
           'underperform':'비중축소','sell':'매도'}
SECTOR_LABEL = {
    'spy':'S&P 500', 'qqq':'NASDAQ 100', 'vix':'VIX',
    'smh':'반도체(SMH)', 'xlk':'기술(XLK)', 'xlv':'헬스케어(XLV)',
    'xle':'에너지(XLE)', 'xli':'산업재(XLI)', 'xlf':'금융(XLF)',
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ── 한국어 기업 설명 생성 ─────────────────────────────────────────────
def korean_desc(detail, ta, q):
    name     = detail.get('longName') or q.get('shortName', '')
    sector   = detail.get('sector', '')
    industry = detail.get('industry', '')
    s_ko     = SECTOR_KO.get(sector, sector)
    i_ko     = INDUSTRY_KO.get(industry, industry)
    rev_g    = detail.get('revenueGrowth') or 0
    pe_fwd   = detail.get('forwardPE') or 0
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

# ── 데이터 수집 ───────────────────────────────────────────────────────
def fetch_gainers():
    import yfinance as yf
    log("Top Gainers 수집 중...")

    # yf.screen() 우선 시도, 실패 시 직접 스크리너 URL 호출
    try:
        result = yf.screen("day_gainers", count=50)
        quotes = result.get('quotes', [])
        if not quotes:
            raise ValueError("빈 결과")
    except Exception as e:
        log(f"yf.screen 실패({e}), 대체 방법 시도...")
        quotes = _fetch_gainers_fallback()

    FIELDS = ['symbol','shortName','regularMarketPrice','regularMarketChangePercent',
              'regularMarketVolume','averageDailyVolume3Month','marketCap',
              'fiftyTwoWeekHigh','twoHundredDayAverage']
    return [{k: q.get(k) or 0 for k in FIELDS} for q in quotes]

def _fetch_gainers_fallback():
    """yf.screen 실패 시 Yahoo Finance 스크리너 직접 호출"""
    url = ("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
           "?formatted=false&lang=en-US&region=US&scrIds=day_gainers&count=50")
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        return data['finance']['result'][0].get('quotes', [])
    except Exception as e2:
        log(f"폴백도 실패({e2}), 빈 목록 반환")
        return []

def fetch_market():
    import yfinance as yf
    out = {}
    symbols = [
        ('SPY','spy'), ('QQQ','qqq'), ('^VIX','vix'), ('SMH','smh'),
        ('XLK','xlk'), ('XLV','xlv'), ('XLE','xle'), ('XLI','xli'), ('XLF','xlf'),
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

# ── 기술적 지표 계산 ──────────────────────────────────────────────────
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
        return 'b', '신고가권 타이트 횡보 (LREP 최적)'
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
    ytd   = round((price - float(ytd_h['Close'].iloc[0])) / float(ytd_h['Close'].iloc[0]) * 100, 1) \
            if len(ytd_h) > 0 else 0

    ql_pos, ql_desc = qullamaggie_position(price, ma200v, high52, ytd)

    vol_trend = 'N/A'
    if len(h) >= 20:
        avg_vol_20 = float(h['Volume'][-20:].mean())
        avg_vol_5  = float(h['Volume'][-5:].mean())
        vol_trend  = '증가' if avg_vol_5 > avg_vol_20 * 1.2 else ('감소' if avg_vol_5 < avg_vol_20 * 0.8 else '보합')

    return {
        '200ma':       round(ma200v, 2),
        'above_200ma': bool(price > ma200v),
        'rsi':         round(rsi, 1),
        'adx':         round(adx, 1),
        'macd_bull':   bool(macd_bull),
        '52w_pct':     pct52,
        '52w_high':    round(high52, 2),
        'ytd':         ytd,
        'adr':         adr,
        'ql_pos':      ql_pos,      # str: 'a' | 'b' | 'c'
        'ql_desc':     ql_desc,     # str
        'vol_trend':   vol_trend,
    }

AI_SECTORS = {'technology','semiconductor','defense','energy','aerospace'}

def score_stock(ta, sector, industry):
    s = 0
    if ta['adx'] > 25:            s += 2
    if 40 <= ta['rsi'] <= 75:     s += 2
    if ta['macd_bull']:            s += 2
    if ta['52w_pct'] >= 90:       s += 1
    if ta['ytd'] >= 50:            s += 1
    combo = (sector + industry).lower()
    if any(k in combo for k in AI_SECTORS): s += 1
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
    beta = detail.get('beta') or 0
    if beta and beta > 2:
        risks.append(f"Beta {beta:.1f} — 시장 변동 시 과대 반응 가능")
    if not risks:
        risks.append("주요 기술적 리스크 없음 — 손절 원칙 준수")
    return risks

# ── 스크리닝 메인 로직 ────────────────────────────────────────────────
def run_screening(gainers):
    p1 = [q for q in gainers
          if q['regularMarketChangePercent'] >= 10
          and q['regularMarketPrice'] >= 10
          and (q['regularMarketVolume'] >= (q['averageDailyVolume3Month'] or 0) * 1.5
               or q['regularMarketVolume'] >= 300_000)
          and 0 < q['marketCap'] < 50_000_000_000]
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

        # rev_growth: None 안전 처리
        rev_g_raw = detail.get('revenueGrowth')
        rev_growth = round(rev_g_raw * 100, 1) if rev_g_raw is not None else None

        catalysts = [n['title'] for n in detail.get('news', []) if n.get('title')]

        passed.append({
            'ticker':       ticker,
            'exchange':     q.get('exchange', 'NMS'),
            'name':         q.get('shortName') or '',
            'full_name':    detail.get('longName') or q.get('shortName') or '',
            'price':        round(q['regularMarketPrice'], 2),
            'change_pct':   round(q['regularMarketChangePercent'], 2),
            'volume':       q['regularMarketVolume'],
            'avg_vol':      avg_vol,
            'vol_ratio':    round(q['regularMarketVolume'] / avg_vol, 1),
            'market_cap':   q['marketCap'],
            'sector':       sector,
            'industry':     industry,
            'summary':      detail.get('longBusinessSummary') or '',
            'korean_desc':  korean_desc(detail, ta, q),
            'analyst_target': detail.get('targetMeanPrice') or 0,
            'analyst_rec':    detail.get('recommendationKey') or '',
            'analyst_cnt':    detail.get('numberOfAnalystOpinions') or 0,
            'pe_trailing':    detail.get('trailingPE') or 0,
            'pe_forward':     detail.get('forwardPE') or 0,
            'rev_growth':     rev_growth,
            'catalysts':    catalysts,
            'risks':        auto_risks(ta, detail),
            **ta,
            'score': sc,
        })

    passed.sort(key=lambda x: x['score'], reverse=True)
    log(f"2차 통과: {len(passed)}개")
    return passed

# ── GitHub watchlist 동기화 ───────────────────────────────────────────
def github_pull_watchlist():
    """GitHub에서 watchlist.json 다운로드. 없으면 스킵."""
    import base64
    try:
        r = requests.get(f"{GITHUB_API}/watchlist.json", headers=GH_HEADERS, timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()['content']).decode('utf-8')
            with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            log("GitHub watchlist.json pull 완료")
        else:
            log("GitHub watchlist.json 없음 — 신규 시작")
    except Exception as e:
        log(f"GitHub pull 실패 (무시): {e}")

def github_push_watchlist():
    """watchlist.json을 GitHub에 업로드 (있으면 업데이트)."""
    import base64
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        # 기존 파일 SHA 조회 (업데이트 시 필요)
        r = requests.get(f"{GITHUB_API}/watchlist.json", headers=GH_HEADERS, timeout=10)
        sha = r.json().get('sha') if r.status_code == 200 else None

        payload = {
            "message": f"watchlist update {TODAY}",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(f"{GITHUB_API}/watchlist.json",
                          headers=GH_HEADERS, json=payload, timeout=10)
        if r2.status_code in (200, 201):
            log("GitHub watchlist.json push 완료")
        else:
            log(f"GitHub push 실패: {r2.status_code} {r2.text[:100]}")
    except Exception as e:
        log(f"GitHub push 실패 (무시): {e}")

# ── 관심종목 워치리스트 ────────────────────────────────────────────────
def load_watchlist():
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
        return f"{days}일차 — LREP 트리거 대기", "teal"
    else:
        return f"{days}일차 — 재평가 필요", "red"

def update_watchlist(passed):
    wl = load_watchlist()
    tickers = wl.get("tickers", {})

    for s in passed:
        tk = s['ticker']
        if tk in tickers:
            e = tickers[tk]
            if e.get('last_seen') != TODAY:
                e['appearances'] = e.get('appearances', 1) + 1
            e['last_seen']       = TODAY
            e['last_price']      = s['price']
            e['last_change_pct'] = s['change_pct']
            e['last_score']      = s['score']
            e['last_ql_pos']     = s['ql_pos']
            e['last_ql_desc']    = s['ql_desc']
            e['name']            = s['name']
            e['sector']          = s['sector']
            e['exchange']        = s.get('exchange', e.get('exchange', 'NMS'))
        else:
            tickers[tk] = {
                'first_seen':      TODAY,
                'last_seen':       TODAY,
                'appearances':     1,
                'last_price':      s['price'],
                'last_change_pct': s['change_pct'],
                'last_score':      s['score'],
                'last_ql_pos':     s['ql_pos'],
                'last_ql_desc':    s['ql_desc'],
                'name':            s['name'],
                'sector':          s['sector'],
                'exchange':        s.get('exchange', 'NMS'),
            }

    wl['tickers'] = tickers
    save_watchlist(wl)
    log(f"관심종목 트래커 업데이트: {len(tickers)}개 누적")
    return wl

# ── PDF 생성 ──────────────────────────────────────────────────────────
def build_pdf(passed, mkt, wl=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    # Pretendard 폰트 없으면 시스템 폰트로 대체 (macOS Arial → Linux DejaVu)
    _font_paths = [
        (FONT_R,  ['/System/Library/Fonts/Supplemental/Arial.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']),
        (FONT_B,  ['/System/Library/Fonts/Supplemental/Arial Bold.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']),
        (FONT_SB, ['/System/Library/Fonts/Supplemental/Arial Bold.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']),
    ]
    for custom, fallbacks in _font_paths:
        if not os.path.exists(custom):
            import shutil
            for fallback in fallbacks:
                if os.path.exists(fallback):
                    shutil.copy(fallback, custom)
                    break
    pdfmetrics.registerFont(TTFont('PT',   FONT_R))
    pdfmetrics.registerFont(TTFont('PTB',  FONT_B))
    pdfmetrics.registerFont(TTFont('PTSB', FONT_SB))

    C = dict(
        bg=colors.HexColor('#0f1923'),    panel=colors.HexColor('#1c2b3a'),
        accent=colors.HexColor('#e94560'), gold=colors.HexColor('#f0c040'),
        green=colors.HexColor('#00c897'),  red=colors.HexColor('#ff5252'),
        blue=colors.HexColor('#4fc3f7'),   gray=colors.HexColor('#888888'),
        lgray=colors.HexColor('#f4f6f8'),  mgray=colors.HexColor('#dddddd'),
        dgray=colors.HexColor('#555555'),  white=colors.white,
        teal=colors.HexColor('#00acc1'),   purple=colors.HexColor('#ab47bc'),
    )

    def S(size, bold=False, sb=False, color=None, align=TA_LEFT):
        return ParagraphStyle('s',
            fontName='PTB' if bold else ('PTSB' if sb else 'PT'),
            fontSize=size, textColor=color or C['dgray'],
            alignment=align, leading=size*1.6, wordWrap='CJK')

    def P(text, size=9, bold=False, sb=False, color=None, align=TA_LEFT):
        return Paragraph(str(text), S(size, bold, sb, color, align))

    _tv_exchange_map = {
        'NMS': 'NASDAQ', 'NGM': 'NASDAQ', 'NCM': 'NASDAQ',
        'NYQ': 'NYSE',   'ASE': 'AMEX',   'PCX': 'AMEX',
    }

    def tv_link(ticker, exchange_code, is_today=False):
        exch  = _tv_exchange_map.get(exchange_code, 'NASDAQ')
        url   = f"https://www.tradingview.com/chart/?symbol={exch}:{ticker}"
        color = "#4caf50" if is_today else "#00acc1"
        return Paragraph(
            f'<a href="{url}"><font color="{color}"><b>{ticker}</b></font></a>',
            S(7.5, align=TA_CENTER)
        )

    def HR(c=None, t=1, sp=3):
        return HRFlowable(width='100%', thickness=t, color=c or C['mgray'],
                          spaceBefore=sp, spaceAfter=sp)

    doc = SimpleDocTemplate(PDF_OUT, pagesize=A4,
                            topMargin=13*mm, bottomMargin=13*mm,
                            leftMargin=14*mm, rightMargin=14*mm)
    st = []

    spy = mkt.get('spy', {}); qqq = mkt.get('qqq', {})
    vix = mkt.get('vix', {}); smh = mkt.get('smh', {})
    spy_chg = spy.get('chg', 0); qqq_chg = qqq.get('chg', 0)
    vix_chg = vix.get('chg', 0); smh_week = smh.get('week', 0)

    st += [
        P("미국 주식 Top Gainers 스크리닝 보고서", 17, bold=True, color=C['bg'], align=TA_CENTER),
        Spacer(1, 1*mm),
        P("Thales LREP + Qullamaggie Framework  v6", 10, sb=True, color=C['dgray'], align=TA_CENTER),
        P(f"분석일: {TODAY}  |  생성: {datetime.now().strftime('%H:%M')} KST", 8, color=C['gray'], align=TA_CENTER),
        HR(C['accent'], t=2.5, sp=5),
    ]

    mkt_status = ("약세" if spy_chg < -0.5 and qqq_chg < -0.5
                  else "강세" if spy_chg > 0.5 and qqq_chg > 0.5 else "혼조")
    mkt_brief = (
        f"오늘 미국 증시는 <b>SPY {spy_chg:+.2f}% / QQQ {qqq_chg:+.2f}%</b>로 "
        f"<b>{mkt_status} 마감</b>했습니다. "
        f"공포지수 VIX는 <b>{vix.get('price',0):.1f}p ({vix_chg:+.1f}%)</b>로 "
        f"{'하락하며 투자심리가 다소 안정됐습니다' if vix_chg < 0 else '상승하며 변동성이 확대됐습니다'}. "
        f"반도체 ETF(SMH) 주간 성과는 <b>{smh_week:+.1f}%</b>로 "
        f"{'AI·반도체가 시장을 리드하는 흐름' if smh_week > 3 else '섹터별 차별화 장세'}입니다."
    )

    idx_rows = [['지수 / ETF', '현재가', '당일', '주간']]
    for key, label in [('spy','S&P 500 (SPY)'), ('qqq','NASDAQ 100 (QQQ)'),
                        ('vix','변동성지수 (VIX)'), ('smh','반도체 ETF (SMH)')]:
        d   = mkt.get(key, {})
        chg = d.get('chg', 0)
        sym = '▲' if chg >= 0 else '▼'
        idx_rows.append([label,
                          f"{'$' if key!='vix' else ''}{d.get('price',0):.2f}{'p' if key=='vix' else ''}",
                          f"{sym} {chg:+.2f}%", f"{d.get('week',0):+.1f}%"])

    mt = Table(idx_rows, colWidths=[62*mm, 30*mm, 30*mm, 28*mm])
    _ms = [
        ('BACKGROUND',(0,0),(-1,0),C['bg']), ('TEXTCOLOR',(0,0),(-1,0),C['gold']),
        ('FONTNAME',(0,0),(-1,-1),'PT'), ('FONTNAME',(0,0),(-1,0),'PTB'),
        ('FONTSIZE',(0,0),(-1,-1),8), ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[C['lgray'],C['white']]),
        ('GRID',(0,0),(-1,-1),0.4,C['mgray']),
        ('TOPPADDING',(0,0),(-1,-1),4), ('BOTTOMPADDING',(0,0),(-1,-1),4),
    ]
    for ri, key in enumerate(['spy','qqq','vix','smh'], 1):
        chg  = mkt.get(key,{}).get('chg',0)
        good = (chg < 0) if key == 'vix' else (chg >= 0)
        _ms += [('TEXTCOLOR',(2,ri),(2,ri), C['green'] if good else C['red']),
                ('FONTNAME',(2,ri),(2,ri),'PTSB')]
    mt.setStyle(TableStyle(_ms))

    sector_keys = [('xlk','기술 XLK'), ('smh','반도체 SMH'), ('xlv','헬스케어 XLV'),
                   ('xle','에너지 XLE'), ('xli','산업재 XLI'), ('xlf','금융 XLF')]
    sec_row = []
    for key, label in sector_keys:
        d   = mkt.get(key, {})
        chg = d.get('chg', 0)
        clr = C['green'] if chg >= 0 else C['red']
        cell = Paragraph(
            f"<b>{label}</b><br/>{chg:+.2f}%",
            ParagraphStyle('sc', fontName='PTSB', fontSize=7.5,
                           textColor=clr, alignment=TA_CENTER, leading=12, wordWrap='CJK')
        )
        sec_row.append(cell)
    sec_tbl = Table([sec_row], colWidths=[27*mm]*6)
    sec_tbl.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,-1),'PT'), ('FONTSIZE',(0,0),(-1,-1),7.5),
        ('ALIGN',(0,0),(-1,-1),'CENTER'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BACKGROUND',(0,0),(-1,-1),C['panel']),
        ('TOPPADDING',(0,0),(-1,-1),5), ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('GRID',(0,0),(-1,-1),0.3,C['mgray']),
    ]))

    st += [
        P("[1]  오늘의 미국 증시 현황", 12, bold=True, color=C['bg']),
        HR(sp=2), Spacer(1,2*mm),
        P(mkt_brief, 9), Spacer(1,3*mm), mt,
        Spacer(1,3*mm),
        P("섹터 ETF 당일 성과", 8, sb=True, color=C['dgray']),
        Spacer(1,1*mm), sec_tbl, Spacer(1,5*mm),
    ]

    st += [
        HR(C['accent'], t=1.5, sp=2), Spacer(1,2*mm),
        P("[2]  스크리닝 결과 요약", 12, bold=True, color=C['bg']),
        Spacer(1,2*mm),
        P(f"Yahoo Finance Top 50 → Qullamaggie 1차 → Thales 2차 → <b>최종 {len(passed)}개</b> 선별", 9),
        Spacer(1,3*mm),
    ]

    if passed:
        hdr = ['티커','종목명','등락률','현재가','거래량비','200MA','RSI','ADX','QU위치','점수']
        cw  = [17*mm, 40*mm, 16*mm, 18*mm, 14*mm, 18*mm, 13*mm, 13*mm, 18*mm, 13*mm]
        rows = [hdr]
        for s in passed:
            rows.append([
                s['ticker'],
                (s['name'][:20]+'..') if len(s['name'])>20 else s['name'],
                f"+{s['change_pct']:.1f}%", f"${s['price']:.2f}",
                f"{s['vol_ratio']:.1f}x",
                '상단 V' if s['above_200ma'] else '하단 X',
                f"{s['rsi']:.1f}", f"{s['adx']:.1f}",
                s['ql_pos'], f"{s['score']}/9"
            ])
        t = Table(rows, colWidths=cw)
        ts = [
            ('BACKGROUND',(0,0),(-1,0),C['bg']), ('TEXTCOLOR',(0,0),(-1,0),C['white']),
            ('FONTNAME',(0,0),(-1,-1),'PT'), ('FONTNAME',(0,0),(-1,0),'PTB'),
            ('FONTSIZE',(0,0),(-1,-1),7.5), ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C['lgray'],C['white']]),
            ('GRID',(0,0),(-1,-1),0.4,C['mgray']),
            ('TOPPADDING',(0,0),(-1,-1),4), ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]
        for i in range(1, len(rows)):
            s = passed[i-1]
            ts += [
                ('TEXTCOLOR',(2,i),(2,i), C['green']), ('FONTNAME',(2,i),(2,i),'PTSB'),
                ('TEXTCOLOR',(5,i),(5,i), C['green'] if s['above_200ma'] else C['red']),
                ('TEXTCOLOR',(9,i),(9,i),
                 C['green'] if s['score']>=5 else C['gold'] if s['score']>=3 else C['red']),
                ('FONTNAME',(9,i),(9,i),'PTSB'),
            ]
        t.setStyle(TableStyle(ts))
        st += [t, Spacer(1,6*mm)]

    if passed:
        st += [HR(C['accent'],t=1.5,sp=2), Spacer(1,2*mm),
               P("[3]  통과 종목 상세 분석", 12, bold=True, color=C['bg'])]

        for rank, s in enumerate(passed, 1):
            rec_ko    = REC_KO.get(s['analyst_rec'], s['analyst_rec'] or 'N/A')
            rec_color = {'강력매수':C['green'],'매수':C['blue']}.get(rec_ko, C['gray'])
            target    = s['analyst_target']
            upside    = round((target - s['price']) / s['price'] * 100, 1) if target and s['price'] else 0
            market_cap_b = round(s['market_cap'] / 1e9, 1) if s['market_cap'] else 0

            hrow = [[
                P(f"#{rank}  {s['ticker']}", 12, bold=True, color=C['white']),
                P(f"{s['full_name'][:32]}", 8, color=C['mgray']),
                P(f"애널: {rec_ko}  ({s['analyst_cnt']}명)", 8, sb=True, color=rec_color, align=TA_RIGHT),
            ]]
            ht = Table(hrow, colWidths=[30*mm, 95*mm, 55*mm])
            ht.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,-1),C['panel']),
                ('FONTNAME',(0,0),(-1,-1),'PT'),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7),
                ('LEFTPADDING',(0,0),(0,-1),8), ('RIGHTPADDING',(-1,0),(-1,-1),8),
                ('LINEABOVE',(0,0),(-1,0),2.5,C['accent']),
            ]))

            rev_g_str = f"{s['rev_growth']:+.1f}%" if s['rev_growth'] is not None else 'N/A'
            basic_info = [
                ['섹터', s['sector'] or 'N/A', '업종', s['industry'] or 'N/A'],
                ['시가총액', f"${market_cap_b:.1f}B",
                 'P/E (Fwd)', f"{s['pe_forward']:.1f}x" if s['pe_forward'] else 'N/A'],
                ['매출성장', rev_g_str,
                 '52주고점비', f"{s['52w_pct']:.1f}%  (고점 ${s['52w_high']:.2f})"],
                ['YTD',  f"{s['ytd']:+.1f}%",
                 'ADR',  f"{s['adr']:.1f}%"],
                ['거래량비율', f"{s['vol_ratio']:.1f}x (평균대비)",
                 '거래량추세', s['vol_trend']],
            ]
            bt = Table(basic_info, colWidths=[22*mm, 50*mm, 22*mm, 86*mm])
            bt.setStyle(TableStyle([
                ('FONTNAME',(0,0),(-1,-1),'PT'), ('FONTSIZE',(0,0),(-1,-1),8),
                ('FONTNAME',(0,0),(0,-1),'PTSB'), ('FONTNAME',(2,0),(2,-1),'PTSB'),
                ('TEXTCOLOR',(0,0),(0,-1),C['dgray']), ('TEXTCOLOR',(2,0),(2,-1),C['dgray']),
                ('ROWBACKGROUNDS',(0,0),(-1,-1),[C['lgray'],C['white']]),
                ('GRID',(0,0),(-1,-1),0.3,C['mgray']),
                ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
                ('ALIGN',(0,0),(-1,-1),'LEFT'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ]))

            summary_text = s.get('korean_desc') or f"{s['sector']} / {s['industry']} 섹터 기업"

            catalyst_items = []
            for i, c_txt in enumerate(s['catalysts'][:4], 1):
                catalyst_items.append(P(f"  {i}. {c_txt}", 8, color=C['dgray']))
            if not catalyst_items:
                catalyst_items.append(P("  - 최근 주요 뉴스 없음 (기술적 모멘텀 중심)", 8, color=C['gray']))

            risk_items = [P(f"  ! {r}", 8, color=C['dgray']) for r in s['risks']]

            checks = [
                ['지표', '값', '판정', '비고'],
                ['200MA', f"${s['200ma']:.2f}", 'V 상단' if s['above_200ma'] else 'X 하단', f"현재가 ${s['price']:.2f}"],
                ['RSI',   f"{s['rsi']:.1f}", 'V 양호' if 40<=s['rsi']<=75 else '! 고RSI', '40~75 이상적'],
                ['ADX',   f"{s['adx']:.1f}", 'V 강추세' if s['adx']>25 else '△ 약추세', 'ADX>25 선호'],
                ['MACD',  '매수' if s['macd_bull'] else '중립', 'V' if s['macd_bull'] else '-', 'Signal 상향돌파'],
                ['52주고점', f"{s['52w_pct']:.1f}%", 'V 신고가권' if s['52w_pct']>=90 else '△', '90% 이상 선호'],
                ['YTD',   f"{s['ytd']:+.1f}%", 'V 강세' if s['ytd']>=50 else '△' if s['ytd']>=0 else 'X', '+50% 이상'],
                ['Qullamaggie', s['ql_pos'], s['ql_desc'][:28], 'b 구간 최선호'],
                ['목표가', f"${target:.1f}" if target else 'N/A',
                 f"{upside:+.1f}% 업사이드" if target else '-', f"{s['analyst_cnt']}명 컨센서스"],
                ['종합점수', f"{s['score']}/9", '★ 우선' if s['score']>=5 else '△ 관심', 'Thales 기준'],
            ]
            ct = Table(checks, colWidths=[26*mm, 28*mm, 50*mm, 76*mm])
            cs = [
                ('BACKGROUND',(0,0),(-1,0),C['dgray']), ('TEXTCOLOR',(0,0),(-1,0),C['white']),
                ('FONTNAME',(0,0),(-1,-1),'PT'), ('FONTNAME',(0,0),(-1,0),'PTB'),
                ('FONTSIZE',(0,0),(-1,-1),7.5), ('ALIGN',(0,0),(-1,-1),'CENTER'),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[C['lgray'],C['white']]),
                ('GRID',(0,0),(-1,-1),0.3,C['mgray']),
                ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
                ('TEXTCOLOR',(2,1),(2,1), C['green'] if s['above_200ma'] else C['red']),
                ('TEXTCOLOR',(2,2),(2,2), C['green'] if 40<=s['rsi']<=75 else C['gold']),
                ('TEXTCOLOR',(2,3),(2,3), C['green'] if s['adx']>25 else C['gold']),
                ('TEXTCOLOR',(2,4),(2,4), C['green'] if s['macd_bull'] else C['gray']),
                ('TEXTCOLOR',(2,5),(2,5), C['green'] if s['52w_pct']>=90 else C['gold']),
                ('TEXTCOLOR',(2,6),(2,6), C['green'] if s['ytd']>=50 else C['gold'] if s['ytd']>=0 else C['red']),
                ('TEXTCOLOR',(2,8),(2,8), C['green'] if upside>20 else C['red'] if upside<0 else C['gold']),
                ('TEXTCOLOR',(2,9),(2,9), C['green'] if s['score']>=5 else C['gold'] if s['score']>=3 else C['red']),
                ('FONTNAME',(2,1),(2,9),'PTSB'),
                ('ALIGN',(3,0),(3,-1),'LEFT'),
            ]
            ct.setStyle(TableStyle(cs))

            st += [
                Spacer(1,4*mm), ht, Spacer(1,2*mm), bt,
                Spacer(1,3*mm),
                P("[기업 개요]", 8.5, bold=True, color=C['bg']),
                Spacer(1,1*mm), P(summary_text, 8.5), Spacer(1,3*mm),
                P("[상승 촉매 - 최근 뉴스]", 8.5, bold=True, color=C['teal']),
                Spacer(1,1*mm),
            ] + catalyst_items + [
                Spacer(1,3*mm),
                P("[리스크 체크]", 8.5, bold=True, color=C['accent']),
                Spacer(1,1*mm),
            ] + risk_items + [
                Spacer(1,3*mm), ct,
            ]

        st.append(Spacer(1,6*mm))

    if passed:
        lhdr = ['순위','티커','QU위치','진입 조건','진입가','손절가','추천']
        lcw  = [12*mm, 16*mm, 20*mm, 58*mm, 24*mm, 24*mm, 26*mm]
        lrows = [lhdr]
        rec_map = {9:'★★★ 최우선',8:'★★★',7:'★★☆ 우선',6:'★★☆',5:'★☆☆ 관심',4:'★☆☆'}
        for i, s in enumerate(passed[:3], 1):
            conds = [c for c, ok in [
                ("200MA 상단", s['above_200ma']),
                (f"ADX {s['adx']:.0f} 강추세", s['adx']>25),
                (f"RSI {s['rsi']:.0f} 양호", 40<=s['rsi']<=75),
                ("MACD 매수", s['macd_bull']),
            ] if ok] or ["기본 조건 충족"]
            lrows.append([f"#{i}", s['ticker'], s['ql_pos'],
                          ", ".join(conds) + "\n거래량 급증 확인",
                          f"${s['price']:.2f}\n스몰캔들 상단",
                          "스몰캔들 하단\n(최대 -1.5%)",
                          rec_map.get(s['score'], '★☆☆')])
        lt = Table(lrows, colWidths=lcw)
        ls = [
            ('BACKGROUND',(0,0),(-1,0),C['panel']), ('TEXTCOLOR',(0,0),(-1,0),C['gold']),
            ('FONTNAME',(0,0),(-1,-1),'PT'), ('FONTNAME',(0,0),(-1,0),'PTB'),
            ('FONTSIZE',(0,0),(-1,-1),7.5), ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C['lgray'],C['white']]),
            ('GRID',(0,0),(-1,-1),0.4,C['mgray']),
            ('TOPPADDING',(0,0),(-1,-1),5), ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ]
        for i in range(1, len(lrows)):
            sc = passed[i-1]['score']
            lc = C['green'] if sc>=5 else C['gold'] if sc>=3 else C['red']
            ls += [('TEXTCOLOR',(6,i),(6,i),lc), ('FONTNAME',(6,i),(6,i),'PTSB')]
        lt.setStyle(TableStyle(ls))
        st += [
            HR(C['accent'],t=1.5,sp=2), Spacer(1,2*mm),
            P("[4]  LREP 진입 시나리오 (상위 3종목)", 12, bold=True, color=C['bg']),
            Spacer(1,1*mm),
            P("스몰캔들 형성 확인 후 진입 - 아래는 참고용 시나리오입니다.", 8, color=C['gray']),
            Spacer(1,2*mm), lt, Spacer(1,6*mm),
        ]

    advice = [(
        "① 시장 먼저, 종목은 그 다음",
        f"지수는 현재 <b>{mkt_status} 국면</b>. "
        f"{'VIX 하락으로 공포심 완화 중이나 ' if vix_chg < 0 else 'VIX 상승으로 변동성 주의. '}"
        f"신규 진입 전 200MA 회복 여부와 SPY/QQQ 방향성을 반드시 확인하세요. "
        f"{'지수 강세 구간 - 모멘텀 전략 유효.' if mkt_status=='강세' else '확신 없는 장세 - 포지션 50~70%로 축소 권장.'}"
    )]
    for s in passed[:3]:
        rec_ko = REC_KO.get(s['analyst_rec'], '')
        target = s['analyst_target']
        upside = round((target - s['price']) / s['price'] * 100, 1) if target and s['price'] else 0
        idx = passed.index(s)
        num = '②③④'[idx] if idx < 3 else '④'
        if target and s['price'] > target:
            tip = f"현재가(${s['price']:.0f})가 목표가(${target:.0f}) 초과 - 추격보다 <b>눌림목 대기</b>."
        elif upside > 30:
            tip = f"목표가 대비 <b>+{upside:.0f}% 업사이드</b>. 분할 매수 관점 접근."
        else:
            tip = (f"RSI {s['rsi']:.0f} / ADX {s['adx']:.0f} / {s['ql_pos']} - "
                   f"{'추세 강도 충분. 스몰캔들 눌림 대기.' if s['adx']>25 else '추세 약함. 추가 확인 후 진입.'}")
        advice.append((f"{num}  {s['ticker']} ({s['name'][:18]})", tip))

    advice.append(("⑤ 손절 원칙은 절대적",
                   "<b>손절 최대 1~1.5%, 절대 2% 초과 금지.</b> "
                   "좋은 종목 + 좋은 타이밍 + 좋은 시장 - 셋 다 맞아야 진입입니다."))

    st += [HR(C['accent'],t=1.5,sp=2), Spacer(1,2*mm),
           P("[5]  오늘의 투자 조언", 12, bold=True, color=C['bg']), Spacer(1,3*mm)]
    for title, body in advice:
        st += [KeepTogether([
            P(f"<b>{title}</b>", 9.5, color=C['bg']),
            Spacer(1,1*mm), P(body, 8.5), Spacer(1,4*mm),
        ])]

    if wl and wl.get('tickers'):
        tks = wl['tickers']
        today_set = {s['ticker'] for s in passed}
        sorted_tks = sorted(
            tks.items(),
            key=lambda x: days_since_date(x[1].get('first_seen', TODAY))
        )

        wl_hdr = ['티커', '종목명', '첫 등장', '경과일', '재등장', '최근가', '점수', '관망 판단']
        wl_cw  = [15*mm, 36*mm, 20*mm, 14*mm, 14*mm, 18*mm, 13*mm, 50*mm]
        wl_rows = [wl_hdr]
        wl_colors = []

        for ri, (tk, e) in enumerate(sorted_tks, 1):
            d        = days_since_date(e.get('first_seen', TODAY))
            apps     = e.get('appearances', 1)
            ql       = e.get('last_ql_pos', '')
            status_txt, color_key = watch_status(d, apps, ql)
            is_today = tk in today_set
            reapp_txt = f"+{apps}회" if apps > 1 else "첫 등장"

            wl_rows.append([
                tv_link(tk, e.get('exchange', 'NMS'), is_today),
                (e.get('name','')[:18] + '..') if len(e.get('name','')) > 18 else e.get('name',''),
                e.get('first_seen', TODAY),
                f"{d}일" if d > 0 else "오늘",
                reapp_txt,
                f"${e.get('last_price', 0):.2f}",
                f"{e.get('last_score', 0)}/9",
                status_txt,
            ])
            wl_colors.append((ri, color_key, is_today))

        wlt = Table(wl_rows, colWidths=wl_cw)
        wl_style = [
            ('BACKGROUND', (0,0), (-1,0), C['bg']),
            ('TEXTCOLOR',  (0,0), (-1,0), C['gold']),
            ('FONTNAME',   (0,0), (-1,-1), 'PT'),
            ('FONTNAME',   (0,0), (-1,0),  'PTB'),
            ('FONTSIZE',   (0,0), (-1,-1), 7.5),
            ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
            ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [C['lgray'], C['white']]),
            ('GRID',       (0,0), (-1,-1), 0.4, C['mgray']),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]
        color_map = {
            'orange': C['accent'], 'gold': C['gold'],
            'green':  C['green'],  'teal': C['teal'], 'red': C['red'],
        }
        for ri, color_key, is_today in wl_colors:
            clr = color_map.get(color_key, C['dgray'])
            wl_style += [
                ('TEXTCOLOR', (7, ri), (7, ri), clr),
                ('FONTNAME',  (7, ri), (7, ri), 'PTSB'),
            ]
            if is_today:
                wl_style += [
                    ('BACKGROUND', (0, ri), (0, ri), colors.HexColor('#1a3a1a')),
                ]
        wlt.setStyle(TableStyle(wl_style))

        st += [
            HR(C['accent'], t=1.5, sp=2), Spacer(1, 2*mm),
            P("[6]  누적 관심종목 관망 현황", 12, bold=True, color=C['bg']),
            Spacer(1, 1*mm),
            P(
                f"총 <b>{len(tks)}개</b> 누적 추적 중. "
                f"탑게이너 당일 매수 금지 - 3~15일 스몰캔들 베이스 형성 후 LREP 진입. "
                f"<b>오늘 신규 통과 티커는 초록 강조.</b>",
                8.5, color=C['dgray']
            ),
            Spacer(1, 2*mm),
            wlt,
            Spacer(1, 5*mm),
        ]

    st += [
        HR(sp=3),
        P("LREP 원칙: 지수>섹터>종목 / ADR 50%이하 / 2~4일 스몰캔들 / 거래량 감소 / 손절 최대 1.5%", 7.5, color=C['gray']),
        Spacer(1,1*mm),
        P(f"투자 참고용. 최종 책임은 본인에게 있습니다.  |  {datetime.now().strftime('%Y-%m-%d %H:%M')} 생성",
          7, color=C['mgray'], align=TA_CENTER),
    ]

    doc.build(st)
    log(f"PDF 생성 완료: {PDF_OUT}")

# ── JSON 덤프 ─────────────────────────────────────────────────────────
def dump_json(passed, mkt, wl=None):
    compact = {
        'date': TODAY,
        'market': {k: mkt.get(k,{}) for k in ['spy','qqq','vix','smh','xlk','xlv','xle','xli']},
        'passed': [{
            'ticker': s['ticker'], 'name': s['name'], 'sector': s['sector'],
            'change_pct': s['change_pct'], 'price': s['price'],
            'rsi': s['rsi'], 'adx': s['adx'], 'score': s['score'],
            'ql_pos': s['ql_pos'], 'ql_desc': s['ql_desc'],
            'ytd': s['ytd'], '52w_pct': s['52w_pct'],
            'macd_bull': s['macd_bull'], 'above_200ma': s['above_200ma'],
            'catalysts': s['catalysts'][:3],
            'risks': s['risks'],
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
                    e.get('appearances', 1),
                    e.get('last_ql_pos', '')
                )[0],
            }
            for tk, e in (wl.get('tickers', {}) if wl else {}).items()
        },
    }
    with open(JSON_OUT, 'w', encoding='utf-8') as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    log(f"JSON 덤프: {JSON_OUT}")

# ── 텔레그램 전송 ─────────────────────────────────────────────────────
def send_telegram_pdf(passed, mkt):
    spy = mkt.get('spy', {}); qqq = mkt.get('qqq', {}); vix = mkt.get('vix', {})
    caption = (
        f"US Top Gainers Screening [{TODAY}]\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"SPY {spy.get('chg',0):+.2f}% | QQQ {qqq.get('chg',0):+.2f}% | VIX {vix.get('price',0):.1f} ({vix.get('chg',0):+.1f}%)\n"
        f"최종 통과: {len(passed)}개\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    for s in passed:
        caption += f"• {s['ticker']} +{s['change_pct']:.1f}% | RSI:{s['rsi']:.0f} | {s['ql_pos']} | {s['score']}/9\n"
    if not passed:
        caption += "조건에 맞는 종목 없음\n"
    caption += "투자 책임은 본인에게 있습니다"
    caption = caption[:1024]  # 텔레그램 caption 1024자 제한

    import time
    for attempt in range(3):
        try:
            with open(PDF_OUT, 'rb') as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={'chat_id': CHAT_ID, 'caption': caption},
                    files={'document': (f'US_Screening_{TODAY}.pdf', f, 'application/pdf')},
                    timeout=60
                )
            if r.ok and r.json().get('ok'):
                log("텔레그램 PDF 전송 완료")
                return
            else:
                log(f"텔레그램 PDF 재시도 {attempt+1}: {r.text[:100]}")
        except Exception as e:
            log(f"텔레그램 PDF 재시도 {attempt+1}: {e}")
        time.sleep(5)
    raise RuntimeError("텔레그램 PDF 3회 실패")
    log("텔레그램 PDF 전송 완료")

# ── 내러티브 생성 및 전송 ─────────────────────────────────────────────
def build_narrative(passed, mkt):
    spy = mkt.get('spy', {}); qqq = mkt.get('qqq', {})
    vix = mkt.get('vix', {}); smh = mkt.get('smh', {})
    spy_chg = spy.get('chg', 0); qqq_chg = qqq.get('chg', 0)
    vix_p   = vix.get('price', 0); vix_chg = vix.get('chg', 0)

    mkt_status = ("약세" if spy_chg < -0.5 and qqq_chg < -0.5
                  else "강세" if spy_chg > 0.5 and qqq_chg > 0.5 else "혼조")

    # 섹터 흐름
    best_sector = max(
        [('XLK', mkt.get('xlk',{}).get('chg',0)),
         ('SMH', mkt.get('smh',{}).get('chg',0)),
         ('XLV', mkt.get('xlv',{}).get('chg',0)),
         ('XLE', mkt.get('xle',{}).get('chg',0)),
         ('XLI', mkt.get('xli',{}).get('chg',0)),
         ('XLF', mkt.get('xlf',{}).get('chg',0))],
        key=lambda x: x[1]
    )

    lines = [
        f"📝 오늘의 스크리닝 분석 코멘트 [{TODAY}]",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "📰 시장 코멘트",
    ]

    mkt_txt = (
        f"미국 증시는 SPY {spy_chg:+.2f}% / QQQ {qqq_chg:+.2f}%로 {mkt_status} 마감했습니다. "
        f"VIX는 {vix_p:.1f}p ({vix_chg:+.1f}%)로 "
        f"{'하락하며 공포심이 완화되는 흐름' if vix_chg < 0 else '상승하며 변동성이 확대'}됐습니다. "
        f"오늘 섹터 중에서는 {best_sector[0]}({best_sector[1]:+.2f}%)가 가장 강했습니다."
    )
    lines.append(mkt_txt)
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")

    if not passed:
        lines.append("❌ 오늘은 조건에 맞는 종목이 없었습니다.")
        lines.append(f"({mkt_status} 장세 속 필터 강화로 통과 종목 없음)")
    else:
        lines.append(f"🔍 통과 종목 분석 (총 {len(passed)}개)")
        lines.append("")
        for i, s in enumerate(passed, 1):
            rec_ko = REC_KO.get(s['analyst_rec'], '')
            catalyst = s['catalysts'][0] if s['catalysts'] else "기술적 모멘텀 중심"
            main_risk = s['risks'][0] if s['risks'] else "손절 원칙 준수"

            lines.append(f"#{i} {s['ticker']} — {s['name']}")
            lines.append(f"• 오늘 +{s['change_pct']:.1f}% 상승. {catalyst[:60]}")
            lines.append(f"• Qullamaggie 위치: {s['ql_pos']} — {s['ql_desc']}")
            lines.append(f"• 기업: {s.get('korean_desc', s['sector'] + ' / ' + s['industry'] + ' 섹터 기업')[:80]}")
            lines.append(f"• 체크: RSI {s['rsi']:.0f} / ADX {s['adx']:.0f} / 점수 {s['score']}/9")
            lines.append(f"• 주의: {main_risk[:60]}")
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("💡 오늘의 한 줄 조언")

    if mkt_status == '약세':
        advice = "지수 약세 구간 — 신규 진입보다 기존 포지션 관리에 집중하고, 현금 비중을 높게 유지하세요."
    elif passed:
        top = passed[0]
        advice = (f"{mkt_status} 장세에서 {top['ticker']}처럼 거래량 급증 + 200MA 상단 종목에 주목하되, "
                  f"탑게이너 당일 추격 매수는 금물 — 스몰캔들 베이스 형성 후 LREP 진입을 기다리세요.")
    else:
        advice = f"{mkt_status} 장세이나 오늘은 조건 충족 종목 없음 — 관망이 최선입니다."

    lines.append(advice)
    lines.append("")
    lines.append("⚠️ 투자 책임은 본인에게 있습니다")

    return "\n".join(lines)

def send_telegram_narrative(text):
    import time
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={'chat_id': CHAT_ID, 'text': text},
                timeout=30
            )
            if r.ok and r.json().get('ok'):
                log("텔레그램 내러티브 전송 완료")
                return
            else:
                log(f"텔레그램 메시지 재시도 {attempt+1}: {r.text[:100]}")
        except Exception as e:
            log(f"텔레그램 메시지 재시도 {attempt+1}: {e}")
        time.sleep(5)
    raise RuntimeError("텔레그램 메시지 3회 실패")

# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    try:
        github_pull_watchlist()
        gainers = fetch_gainers()
        mkt     = fetch_market()
        passed  = run_screening(gainers)
        wl      = update_watchlist(passed)
        dump_json(passed, mkt, wl)
        build_pdf(passed, mkt, wl)
        send_telegram_pdf(passed, mkt)
        narrative = build_narrative(passed, mkt)
        send_telegram_narrative(narrative)
        github_push_watchlist()
        log(f"완료 — 통과 {len(passed)}개 / 누적 관심 {len(wl.get('tickers',{}))}개")
        print(f"RESULT_JSON={JSON_OUT}")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"오류: {e}\n{tb}")
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={'chat_id': CHAT_ID,
                      'text': f"스크리닝 오류 [{TODAY}]\n{str(e)[:400]}\n\n{tb[-300:]}"},
                timeout=15
            )
        except Exception:
            pass

if __name__ == '__main__':
    main()
