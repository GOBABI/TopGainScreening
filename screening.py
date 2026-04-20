"""
US Market Top Gainers Screening
US Market Screening Framework
v6 — 경로 고정 / API 호환성 개선 / 버그 수정
"""

import sys, os, json, warnings, requests
from html_report import build_html, send_telegram_html
from datetime import datetime
warnings.filterwarnings('ignore')

# ── 경로 설정 (환경에 관계없이 고정) ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_R   = os.path.join(BASE_DIR, 'PretendardVariable.ttf')
FONT_B   = os.path.join(BASE_DIR, 'PretendardVariable.ttf')
FONT_SB  = os.path.join(BASE_DIR, 'PretendardVariable.ttf')
JSON_OUT      = os.path.join(BASE_DIR, 'screening_result.json')
WATCHLIST_FILE = os.path.join(BASE_DIR, 'watchlist.json')

BOT_TOKEN  = "8702268897:AAEhRnt0nuBnYCJeMdhofbX_h-D_YBTJxCE"
CHAT_ID    = "7371637453"
def _report_date():
    now = datetime.now()
    # 일요일(6)은 미국 장 없음 → 토요일(1일 전) 날짜 사용
    if now.weekday() == 6:
        from datetime import timedelta
        now = now - timedelta(days=1)
    return now.strftime('%Y-%m-%d')

TODAY      = _report_date()

GITHUB_TOKEN   = "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"
GITHUB_REPO    = "GOBABI/TopGainScreening"
GITHUB_API     = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
GH_HEADERS     = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
GITHUB_PAGES_URL = "https://gobabi.github.io/TopGainScreening"
ARCHIVE_PATH     = os.path.join(BASE_DIR, 'archive.json')

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

def _is_after_market_close():
    """미국 ET 기준 정규장 마감(16:00) 이후인지 확인"""
    import pytz
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return True  # 주말은 전날 마감 기준
    return now.hour >= 16

def load_archive_dates():
    # GitHub에서 먼저 가져오기
    import base64
    try:
        r = requests.get(f"{GITHUB_API}/archive.json", headers=GH_HEADERS, timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()['content']).decode('utf-8')
            with open(ARCHIVE_PATH, 'w') as f:
                f.write(content)
            log("GitHub archive.json pull 완료")
    except Exception as e:
        log(f"GitHub archive pull 실패 (무시): {e}")

    if os.path.exists(ARCHIVE_PATH):
        with open(ARCHIVE_PATH, 'r') as f:
            return json.load(f).get('dates', [])
    return []

def save_archive_dates(dates):
    with open(ARCHIVE_PATH, 'w') as f:
        json.dump({'dates': dates}, f)
    # GitHub에 동기화
    import base64
    try:
        with open(ARCHIVE_PATH, 'r') as f:
            content = f.read()
        encoded = base64.b64encode(content.encode()).decode()
        r = requests.get(f"{GITHUB_API}/archive.json", headers=GH_HEADERS, timeout=10)
        sha = r.json().get('sha') if r.status_code == 200 else None
        payload = {"message": f"archive update {TODAY}", "content": encoded}
        if sha:
            payload["sha"] = sha
        requests.put(f"{GITHUB_API}/archive.json", headers=GH_HEADERS, json=payload, timeout=10)
        log("GitHub archive.json push 완료")
    except Exception as e:
        log(f"GitHub archive push 실패 (무시): {e}")

def github_pages_deploy(archive_dates):
    """HTML을 gh-pages 브랜치에 배포 (index.html + YYYY-MM-DD.html)"""
    import base64
    try:
        html_path = os.path.join(BASE_DIR, 'us_market_screening_latest.html')
        if not os.path.exists(html_path):
            log("HTML 파일 없음 — GitHub Pages 배포 스킵")
            return

        with open(html_path, 'rb') as f:
            html_bytes = f.read()
        html_b64 = base64.b64encode(html_bytes).decode()

        base_url = f"https://api.github.com/repos/{GITHUB_REPO}"

        # gh-pages 브랜치 없으면 main 기준으로 생성
        r = requests.get(f"{base_url}/git/refs/heads/gh-pages", headers=GH_HEADERS, timeout=10)
        if r.status_code == 404:
            r_main = requests.get(f"{base_url}/git/refs/heads/main", headers=GH_HEADERS, timeout=10)
            if not r_main.ok:
                log("GitHub Pages: main SHA 조회 실패")
                return
            main_sha = r_main.json()["object"]["sha"]
            r_create = requests.post(
                f"{base_url}/git/refs",
                headers=GH_HEADERS,
                json={"ref": "refs/heads/gh-pages", "sha": main_sha},
                timeout=15,
            )
            if not r_create.ok:
                log(f"GitHub Pages: gh-pages 브랜치 생성 실패: {r_create.text[:100]}")
                return
            log("gh-pages 브랜치 생성 완료")

        def _upsert(path, content_b64):
            url = f"{base_url}/contents/{path}"
            r_get = requests.get(url, headers=GH_HEADERS, params={"ref": "gh-pages"}, timeout=15)
            sha = r_get.json().get("sha") if r_get.ok else None
            payload = {"message": f"deploy: {TODAY}", "content": content_b64, "branch": "gh-pages"}
            if sha:
                payload["sha"] = sha
            r_put = requests.put(url, headers=GH_HEADERS, json=payload, timeout=60)
            if not r_put.ok:
                log(f"GitHub Pages 업로드 실패 ({path}): {r_put.status_code} {r_put.text[:100]}")
                return False
            return True

        ok1 = _upsert("index.html", html_b64)
        ok2 = _upsert(f"{TODAY}.html", html_b64)
        if ok1 and ok2:
            log(f"GitHub Pages 배포 완료: {GITHUB_PAGES_URL}")

        # GitHub Pages 활성화 (이미 활성화된 경우 무시)
        requests.post(
            f"{base_url}/pages",
            headers={**GH_HEADERS, "Accept": "application/vnd.github.switcheroo-preview+json"},
            json={"source": {"branch": "gh-pages", "path": "/"}},
            timeout=15,
        )
    except Exception as e:
        log(f"GitHub Pages 배포 실패 (무시): {e}")


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
        return f"{days}일차 — 최적진입구간 트리거 대기", "teal"
    else:
        return f"{days}일차 — 재평가 필요", "red"

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
            e['industry']        = s.get('industry', '')
            e['exchange']        = s.get('exchange', e.get('exchange', 'NMS'))
            e.update(ta_snapshot)
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
                'industry':        s.get('industry', ''),
                'exchange':        s.get('exchange', 'NMS'),
                **ta_snapshot,
            }

    wl['tickers'] = tickers
    save_watchlist(wl)
    log(f"관심종목 트래커 업데이트: {len(tickers)}개 누적")
    return wl

def refresh_watchlist_ta(wl, today_tickers):
    """오늘 스크리닝에 없던 워치리스트 종목의 TA를 현재 시점으로 갱신"""
    import yfinance as yf
    tickers = wl.get('tickers', {})
    stale = [tk for tk in tickers if tk not in today_tickers]
    if not stale:
        return wl
    log(f"워치리스트 현재 지표 갱신: {len(stale)}개")
    for tk in stale:
        log(f"  TA 갱신: {tk}")
        ta = analyze(tk)
        if not ta:
            continue
        e = tickers[tk]
        try:
            price = float(yf.Ticker(tk).history(period='1d')['Close'].iloc[-1])
            e['last_price'] = round(price, 2)
        except Exception:
            pass
        sector   = e.get('sector', '')
        industry = e.get('industry', '')
        e['last_rsi']       = round(ta['rsi'], 1)
        e['last_adx']       = round(ta['adx'], 1)
        e['last_macd_bull'] = bool(ta['macd_bull'])
        e['last_52w_pct']   = round(ta['52w_pct'], 1)
        e['last_ytd']       = round(ta['ytd'], 1)
        e['last_ql_pos']    = ta['ql_pos']
        e['last_ql_desc']   = ta['ql_desc']
        e['last_score']     = score_stock(ta, sector, industry)
        e['last_seen']      = TODAY
    save_watchlist(wl)
    log("워치리스트 TA 갱신 완료")
    return wl

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
            lines.append(f"• 모멘텀 위치: {s['ql_pos']} — {s['ql_desc']}")
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
                  f"탑게이너 당일 추격 매수는 금물 — 스몰캔들 베이스 형성 후 최적진입구간 진입을 기다리세요.")
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
        today_tickers = {s['ticker'] for s in passed}
        wl      = refresh_watchlist_ta(wl, today_tickers)
        dump_json(passed, mkt, wl)
        archive_dates = load_archive_dates()
        # 정규장 마감 이후에만 오늘 날짜를 archive에 등록 (덮어쓰기 방지)
        if _is_after_market_close() and TODAY not in archive_dates:
            archive_dates.append(TODAY)
            save_archive_dates(archive_dates)
        elif TODAY not in archive_dates:
            log("장중 실행 — archive 날짜 등록 스킵 (마감 후 확정)")
        build_html(passed, mkt, wl, archive_dates)
        send_telegram_html(passed, mkt)
        narrative = build_narrative(passed, mkt)
        send_telegram_narrative(narrative)
        github_push_watchlist()
        github_pages_deploy(archive_dates)
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
