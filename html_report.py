"""
html_report.py
US Top Gainers Screening — HTML 리포트 생성 모듈
build_html(passed, mkt, wl)  →  us_market_screening_latest.html 저장
send_telegram_html(passed, mkt)  →  텔레그램 전송
"""

import os, json, requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_OUT  = os.path.join(BASE_DIR, 'us_market_screening_latest.html')
TODAY     = datetime.now().strftime('%Y-%m-%d')

BOT_TOKEN = "8702268897:AAEhRnt0nuBnYCJeMdhofbX_h-D_YBTJxCE"
CHAT_ID   = "7371637453"

# ── watchlist status helper (screening.py 와 동일 로직) ──────────────
def _days_since(date_str):
    try:
        return (datetime.now() - datetime.strptime(date_str, '%Y-%m-%d')).days
    except Exception:
        return 0

def _watch_status(days, appearances, ql_pos):
    if days == 0:   return "신규 등장"
    if days <= 2:   return f"{days}일차 — 베이스 형성 대기"
    if days <= 7:
        return f"{days}일차 — 진입 가능 (b 선호)" if ql_pos == 'b' else f"{days}일차 — 진입 가능 구간"
    if days <= 15:  return f"{days}일차 — 최적진입구간 트리거 대기"
    return f"{days}일차 — 재평가 필요"

# ── 데이터 직렬화 ─────────────────────────────────────────────────────
def _build_data_json(passed, mkt, wl):
    """screening.py 결과물을 HTML에 주입할 JSON 형태로 변환"""
    today_set = {s['ticker'] for s in passed}

    watchlist_out = {}
    for tk, e in (wl.get('tickers', {}) if wl else {}).items():
        days = _days_since(e.get('first_seen', TODAY))
        watchlist_out[tk] = {
            'first_seen':    e.get('first_seen', TODAY),
            'last_seen':     e.get('last_seen', TODAY),
            'days':          days,
            'appearances':   e.get('appearances', 1),
            'last_score':    e.get('last_score', 0),
            'last_ql_pos':   e.get('last_ql_pos', 'c'),
            'last_ql_desc':  e.get('last_ql_desc', ''),
            'status':        _watch_status(days, e.get('appearances', 1), e.get('last_ql_pos', 'c')),
            'name':          e.get('name', tk),
            'sector':        e.get('sector', ''),
            'industry':      e.get('industry', ''),
            'last_price':    e.get('last_price', 0),
            'isToday':       tk in today_set,
            'last_rsi':      e.get('last_rsi', 0),
            'last_adx':      e.get('last_adx', 0),
            'last_macd_bull': e.get('last_macd_bull', False),
            'last_52w_pct':  e.get('last_52w_pct', 0),
            'last_ytd':      e.get('last_ytd', 0),
        }

    passed_out = []
    for s in passed:
        passed_out.append({
            'ticker':        s.get('ticker', ''),
            'name':          s.get('name', ''),
            'sector':        s.get('sector', ''),
            'change_pct':    round(s.get('change_pct', 0), 2),
            'price':         round(s.get('price', 0), 2),
            'rsi':           round(s.get('rsi', 0), 1),
            'adx':           round(s.get('adx', 0), 1),
            'score':         s.get('score', 0),
            'ql_pos':        s.get('ql_pos', 'c'),
            'ql_desc':       s.get('ql_desc', ''),
            'ytd':           round(s.get('ytd', 0), 1),
            '52w_pct':       round(s.get('52w_pct', 0), 1),
            '52w_high':      round(s.get('52w_high', 0), 2),
            '200ma':         round(s.get('200ma', 0), 2),
            'adr':           round(s.get('adr', 0), 1),
            'macd_bull':     bool(s.get('macd_bull', False)),
            'above_200ma':   bool(s.get('above_200ma', False)),
            'vol_ratio':     round(s.get('vol_ratio', 0), 1),
            'vol_trend':     s.get('vol_trend', ''),
            'pe_forward':    round(s.get('pe_forward') or 0, 1),
            'rev_growth':    s.get('rev_growth'),
            'analyst_rec':   s.get('analyst_rec', ''),
            'analyst_target': round(s.get('analyst_target') or 0, 2),
            'catalysts':     (s.get('catalysts') or [])[:3],
            'risks':         (s.get('risks') or []),
            'summary':       (s.get('korean_desc') or s.get('summary') or '')[:300],
        })

    market_keys = ['spy', 'qqq', 'vix', 'smh', 'xlk', 'xlv', 'xle', 'xli']
    market_out = {k: mkt.get(k, {'price': 0, 'chg': 0, 'week': 0}) for k in market_keys}

    return json.dumps({
        'date':    TODAY,
        'market':  market_out,
        'passed':  passed_out,
        'watchlist': watchlist_out,
    }, ensure_ascii=False)


# ── HTML 템플릿 ───────────────────────────────────────────────────────
# __DATA_JSON__ 자리표시자에 실제 데이터 주입
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>US Top Gainers Screening — __DATE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet" />
<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body { background: #f4f1ec; color: #111827; font-family: 'Noto Sans KR', sans-serif; font-size: 14px; line-height: 1.6; min-height: 100vh; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: #f4f1ec; }
  ::-webkit-scrollbar-thumb { background: #d1c9bc; border-radius: 3px; }
  a { color: #0891b2; text-decoration: none; }
  a:hover { color: #2563eb; }
</style>
</head>
<body>
<div id="root"></div>
<script type="text/babel">
const DATA = __DATA_JSON__;
const ARCHIVE_DATES = __ARCHIVE_DATES__;

const C = {
  bg: '#f4f1ec', panel: '#ffffff', panel2: '#f8f6f2',
  accent: '#d63651', gold: '#b45309', green: '#059669',
  red: '#dc2626', blue: '#2563eb', teal: '#0891b2',
  gray: '#9ca3af', lgray: '#6b7280', white: '#111827',
  border: '#e5e0d8'
};

const isMobile = window.innerWidth < 640;
const REC_MAP = { strong_buy: '강력매수', buy: '매수', hold: '보유', underperform: '비중축소', sell: '매도', none: '없음' };
const SECTOR_KO = { Healthcare: '헬스케어', Technology: '기술·IT', Industrials: '산업재', 'Basic Materials': '소재', 'Consumer Cyclical': '경기소비재', 'Financial Services': '금융', 'Communication Services': '커뮤니케이션', Energy: '에너지', 'Real Estate': '부동산' };
const tvLink = (ticker) => `https://www.tradingview.com/chart/?symbol=NASDAQ:${ticker}`;

const Badge = ({ label, color }) => (
  <span style={{ background: color + '22', color, border: `1px solid ${color}44`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700, letterSpacing: '0.04em' }}>{label}</span>
);

const ScoreBar = ({ score, max = 9 }) => {
  const pct = score / max * 100;
  const col = score >= 7 ? C.green : score >= 5 ? C.gold : score >= 3 ? C.blue : C.gray;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: '#e5e0d8', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: col, borderRadius: 3, transition: 'width 0.6s ease' }} />
      </div>
      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: col, fontWeight: 700, minWidth: 36, textAlign: 'right' }}>{score}/{max}</span>
    </div>
  );
};

const QlBadge = ({ pos }) => {
  const map = { a: [C.accent, 'A'], b: [C.green, 'B'], c: [C.gold, 'C'] };
  const [col, label] = map[pos] || [C.gray, '?'];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 24, height: 24, borderRadius: 6, background: col + '22', color: col, border: `1.5px solid ${col}55`, fontWeight: 800, fontSize: 13, fontFamily: 'JetBrains Mono' }}>{label}</span>
  );
};

// ── Archive Nav ───────────────────────────────────────────────────────
const ArchiveNav = ({ dates, today }) => {
  if (!dates || dates.length === 0) return null;
  const sorted = [...dates].sort((a, b) => b.localeCompare(a));
  const handleChange = (e) => {
    const val = e.target.value;
    window.location.href = val === today ? './' : `./${val}.html`;
  };
  return (
    <select onChange={handleChange} defaultValue={today}
      style={{ background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '4px 10px', fontSize: 11, color: C.lgray, cursor: 'pointer', fontFamily: 'JetBrains Mono', outline: 'none' }}>
      {sorted.map(d => (
        <option key={d} value={d}>{d}{d === today ? ' ★' : ''}</option>
      ))}
    </select>
  );
};

// ── Market ────────────────────────────────────────────────────────────
const IndexCard = ({ label, data, isVix }) => {
  const good = isVix ? data.chg < 0 : data.chg >= 0;
  const col = good ? C.green : C.red;
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: '16px 20px', flex: 1, minWidth: 140 }}>
      <div style={{ fontSize: 11, color: C.lgray, fontWeight: 500, letterSpacing: '0.08em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 22, fontWeight: 700, color: C.white, marginBottom: 4 }}>
        {isVix ? '' : '$'}{data.price.toFixed(2)}{isVix ? 'p' : ''}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ color: col, fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 600 }}>{data.chg >= 0 ? '▲' : '▼'} {data.chg > 0 ? '+' : ''}{data.chg.toFixed(2)}%</span>
        <span style={{ color: C.gray, fontSize: 12 }}>주간 {data.week > 0 ? '+' : ''}{data.week.toFixed(1)}%</span>
      </div>
    </div>
  );
};

const SectorBar = ({ mkt }) => {
  const sectors = [{ key: 'xlk', label: '기술 XLK' }, { key: 'smh', label: '반도체 SMH' }, { key: 'xlv', label: '헬스케어 XLV' }, { key: 'xle', label: '에너지 XLE' }, { key: 'xli', label: '산업재 XLI' }];
  return (
    <div style={{ display: 'flex', background: C.panel2, borderRadius: 8, overflow: 'hidden', border: `1px solid ${C.border}` }}>
      {sectors.map(({ key, label }) => {
        const d = mkt[key]; const pos = d.chg >= 0;
        return (
          <div key={key} style={{ flex: 1, padding: '10px 8px', textAlign: 'center', borderRight: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 10, color: C.lgray, marginBottom: 2 }}>{label}</div>
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 700, color: pos ? C.green : C.red }}>{d.chg > 0 ? '+' : ''}{d.chg.toFixed(2)}%</div>
          </div>
        );
      })}
    </div>
  );
};

const MarketSection = ({ mkt }) => {
  const spy = mkt.spy; const qqq = mkt.qqq;
  const status = (spy.chg > 0.5 && qqq.chg > 0.5) ? '강세' : (spy.chg < -0.5 && qqq.chg < -0.5) ? '약세' : '혼조';
  const statusCol = status === '강세' ? C.green : status === '약세' ? C.red : C.gold;
  return (
    <section style={{ marginBottom: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 11, color: C.lgray, fontWeight: 500, letterSpacing: '0.1em' }}>01 / 시장 현황</span>
        <div style={{ flex: 1, height: 1, background: C.border }} />
        <Badge label={`${status} 마감`} color={statusCol} />
      </div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <IndexCard label="S&P 500 (SPY)" data={mkt.spy} />
        <IndexCard label="NASDAQ 100 (QQQ)" data={mkt.qqq} />
        <IndexCard label="변동성 (VIX)" data={mkt.vix} isVix />
        <IndexCard label="반도체 (SMH)" data={mkt.smh} />
      </div>
      <SectorBar mkt={mkt} />
    </section>
  );
};

// ── Stock Card ────────────────────────────────────────────────────────
const TechRow = ({ label, val, judge, judgeColor, note }) => (
  <tr>
    <td style={{ padding: '6px 10px', color: C.lgray, fontSize: 12, whiteSpace: 'nowrap', width: 90 }}>{label}</td>
    <td style={{ padding: '6px 10px', fontFamily: 'JetBrains Mono', fontSize: 12, color: C.white }}>{val}</td>
    <td style={{ padding: '6px 10px', fontSize: 12, color: judgeColor, fontWeight: 600 }}>{judge}</td>
    <td style={{ padding: '6px 10px', fontSize: 11, color: C.gray }}>{note}</td>
  </tr>
);

const StockCard = ({ s, rank, expanded, onToggle }) => {
  const recKo = REC_MAP[s.analyst_rec] || s.analyst_rec;
  const recCol = s.analyst_rec === 'strong_buy' ? C.green : s.analyst_rec === 'buy' ? C.blue : C.gray;
  const upside = s.analyst_target ? ((s.analyst_target - s.price) / s.price * 100) : 0;
  const sectorKo = SECTOR_KO[s.sector] || s.sector;
  const w52 = s['52w_pct'];
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 12, marginBottom: 10, overflow: 'hidden', transition: 'box-shadow 0.2s' }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = `0 0 0 1.5px ${C.accent}44`}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}>
      <div onClick={onToggle} style={{ padding: '16px 20px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: '0 0 auto' }}>
          <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.accent, fontWeight: 700 }}>#{rank}</span>
          <a href={tvLink(s.ticker)} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
            style={{ fontFamily: 'JetBrains Mono', fontSize: 20, fontWeight: 700, color: C.teal, letterSpacing: '-0.02em' }}>{s.ticker}</a>
          <QlBadge pos={s.ql_pos} />
        </div>
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={{ fontSize: 13, color: C.white, fontWeight: 500 }}>{s.name}</div>
          <div style={{ fontSize: 11, color: C.lgray, marginTop: 2 }}>{sectorKo} · {s.ql_desc}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: 18, fontWeight: 700, color: C.white }}>${s.price.toFixed(2)}</div>
            <div style={{ color: C.green, fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 600 }}>+{s.change_pct.toFixed(2)}%</div>
          </div>
          <div style={{ width: 80 }}><ScoreBar score={s.score} /></div>
          {recKo && recKo !== '없음' && <Badge label={recKo} color={recCol} />}
          <span style={{ color: expanded ? C.accent : C.gray, fontSize: 18 }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>
      <div style={{ borderTop: `1px solid ${C.border}`, background: C.panel2 }}>
        {[
          [
            { l: 'RSI',    v: s.rsi.toFixed(1),                               c: (s.rsi >= 40 && s.rsi <= 75) ? C.green : C.gold },
            { l: 'ADX',    v: s.adx.toFixed(1),                               c: s.adx > 25 ? C.green : C.gold },
            { l: '거래량비', v: s.vol_ratio.toFixed(1) + 'x',                 c: C.blue },
            { l: 'MACD',   v: s.macd_bull ? '매수 ✓' : '중립',                c: s.macd_bull ? C.green : C.gray },
          ],
          [
            { l: 'YTD',   v: (s.ytd >= 0 ? '+' : '') + s.ytd.toFixed(1) + '%', c: s.ytd >= 0 ? C.green : C.red },
            { l: '52주%', v: w52.toFixed(1) + '%',                              c: w52 >= 90 ? C.green : C.lgray },
            { l: '목표가', v: s.analyst_target ? `$${s.analyst_target.toFixed(1)}` : 'N/A', c: upside > 20 ? C.green : upside < 0 ? C.red : C.gold },
            { l: '200MA', v: s.above_200ma ? '▲ 상단' : '▼ 하단',              c: s.above_200ma ? C.green : C.red },
          ],
        ].map((row, ri) => (
          <div key={ri} style={{ display: 'flex', borderTop: ri > 0 ? `1px solid ${C.border}` : undefined }}>
            {row.map(({ l, v, c }) => (
              <div key={l} style={{ flex: 1, padding: '7px 6px', textAlign: 'center', borderRight: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 10, color: C.gray, marginBottom: 2 }}>{l}</div>
                <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, fontWeight: 700, color: c }}>{v}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
      {expanded && (
        <div style={{ padding: '20px', borderTop: `1px solid ${C.border}` }}>
          <p style={{ fontSize: 13, color: C.lgray, lineHeight: 1.7, marginBottom: 20, paddingBottom: 16, borderBottom: `1px solid ${C.border}` }}>{s.summary}</p>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div style={{ fontSize: 11, color: C.teal, fontWeight: 700, letterSpacing: '0.08em', marginBottom: 10 }}>상승 촉매 — 최근 뉴스</div>
              {s.catalysts.map((c, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <span style={{ color: C.teal, fontSize: 11, flexShrink: 0 }}>{i + 1}.</span>
                  <span style={{ fontSize: 12, color: C.lgray, lineHeight: 1.5 }}>{c}</span>
                </div>
              ))}
            </div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div style={{ fontSize: 11, color: C.accent, fontWeight: 700, letterSpacing: '0.08em', marginBottom: 10 }}>리스크 체크</div>
              {s.risks.map((r, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <span style={{ color: C.accent, fontSize: 11, flexShrink: 0 }}>!</span>
                  <span style={{ fontSize: 12, color: C.lgray, lineHeight: 1.5 }}>{r}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{ marginTop: 20 }}>
            <div style={{ fontSize: 11, color: C.lgray, fontWeight: 700, letterSpacing: '0.08em', marginBottom: 10 }}>기술적 체크리스트</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', background: C.panel2, borderRadius: 8, overflow: 'hidden' }}>
              <tbody>
                <TechRow label="200MA"   val={`$${s['200ma'].toFixed(2)}`} judge={s.above_200ma ? '▲ 상단' : '▼ 하단'} judgeColor={s.above_200ma ? C.green : C.red} note={`현재가 $${s.price.toFixed(2)}`} />
                <TechRow label="RSI"     val={s.rsi.toFixed(1)}   judge={(s.rsi>=40&&s.rsi<=75)?'✓ 양호':'! 고RSI'}    judgeColor={(s.rsi>=40&&s.rsi<=75)?C.green:C.gold} note="40~75 이상적" />
                <TechRow label="ADX"     val={s.adx.toFixed(1)}   judge={s.adx>25?'✓ 강추세':'△ 약추세'}               judgeColor={s.adx>25?C.green:C.gold}  note="ADX>25 선호" />
                <TechRow label="MACD"    val={s.macd_bull?'매수':'중립'} judge={s.macd_bull?'✓':'—'}                    judgeColor={s.macd_bull?C.green:C.gray} note="Signal 상향돌파" />
                <TechRow label="52주 고점" val={`${w52.toFixed(1)}%`} judge={w52>=90?'✓ 신고가권':'△'}                 judgeColor={w52>=90?C.green:C.gold}   note={`고점 $${s['52w_high'].toFixed(2)}`} />
                <TechRow label="YTD"     val={`${s.ytd>=0?'+':''}${s.ytd.toFixed(1)}%`} judge={s.ytd>=50?'✓ 강세':'△'} judgeColor={s.ytd>=50?C.green:C.gold} note="+50% 이상 선호" />
                <TechRow label="목표가"  val={s.analyst_target?`$${s.analyst_target.toFixed(1)}`:'N/A'} judge={`${upside>=0?'+':''}${upside.toFixed(1)}% 업사이드`} judgeColor={upside>20?C.green:upside<0?C.red:C.gold} note={`QU: ${s.ql_desc}`} />
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

// ── 최적진입구간 ─────────────────────────────────────────────────────────────
const 최적진입구간Section = ({ passed }) => {
  const recStars = (sc) => sc >= 7 ? '★★★' : sc >= 5 ? '★★☆' : '★☆☆';
  return (
    <section style={{ marginBottom: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 11, color: C.lgray, fontWeight: 500, letterSpacing: '0.1em' }}>03 / 최적 진입 구간 시나리오</span>
        <div style={{ flex: 1, height: 1, background: C.border }} />
        {!isMobile && <span style={{ fontSize: 11, color: C.gray }}>상위 3종목 · 스몰캔들 형성 후 진입</span>}
      </div>
      <div style={{ background: C.panel, borderRadius: 12, overflow: 'hidden', border: `1px solid ${C.border}` }}>
        {isMobile ? (
          passed.slice(0, 3).map((s, i) => {
            const stopLoss = (s.price * 0.985).toFixed(2);
            const conds = [s.above_200ma&&'200MA 상단', s.adx>25&&`ADX ${s.adx.toFixed(0)}`, s.rsi>=40&&s.rsi<=75&&`RSI ${s.rsi.toFixed(0)}`, s.macd_bull&&'MACD 매수'].filter(Boolean).join(' · ') || '기본조건 충족';
            const col = s.score >= 7 ? C.green : s.score >= 5 ? C.gold : C.blue;
            return (
              <div key={s.ticker} style={{ padding: '14px 16px', borderBottom: `1px solid ${C.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <span style={{ fontFamily: 'JetBrains Mono', color: C.accent, fontWeight: 700, fontSize: 12 }}>#{i+1}</span>
                  <a href={tvLink(s.ticker)} target="_blank" rel="noreferrer"
                    style={{ fontFamily: 'JetBrains Mono', fontWeight: 700, fontSize: 18, color: C.teal }}>{s.ticker}</a>
                  <QlBadge pos={s.ql_pos} />
                  <span style={{ flex: 1 }} />
                  <span style={{ fontFamily: 'JetBrains Mono', fontSize: 14, color: col, fontWeight: 700 }}>{recStars(s.score)}</span>
                </div>
                <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
                  <div>
                    <div style={{ fontSize: 10, color: C.gray, marginBottom: 2 }}>현재가</div>
                    <div style={{ fontFamily: 'JetBrains Mono', fontWeight: 700, color: C.white }}>${s.price.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: C.gray, marginBottom: 2 }}>손절가</div>
                    <div style={{ fontFamily: 'JetBrains Mono', color: C.red, fontWeight: 600 }}>${stopLoss} <span style={{ fontSize: 10, color: C.gray }}>(-1.5%)</span></div>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: C.lgray }}>{conds}</div>
                <div style={{ fontSize: 11, color: C.gray, marginTop: 2 }}>거래량 급증 · 스몰캔들 상단 돌파 진입</div>
              </div>
            );
          })
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: C.panel2 }}>
                {['순위','티커','QU','현재가','진입 조건','손절가','추천'].map(h => (
                  <th key={h} style={{ padding: '10px 14px', fontSize: 11, color: C.gold, fontWeight: 700, textAlign: 'left', letterSpacing: '0.06em', borderBottom: `1px solid ${C.border}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {passed.slice(0, 3).map((s, i) => {
                const stopLoss = (s.price * 0.985).toFixed(2);
                const conds = [s.above_200ma&&'200MA 상단', s.adx>25&&`ADX ${s.adx.toFixed(0)}`, s.rsi>=40&&s.rsi<=75&&`RSI ${s.rsi.toFixed(0)}`, s.macd_bull&&'MACD 매수'].filter(Boolean).join(' · ') || '기본조건 충족';
                const col = s.score >= 7 ? C.green : s.score >= 5 ? C.gold : C.blue;
                return (
                  <tr key={s.ticker} style={{ borderBottom: `1px solid ${C.border}` }}>
                    <td style={{ padding: '12px 14px', fontFamily: 'JetBrains Mono', color: C.accent, fontWeight: 700 }}>#{i+1}</td>
                    <td style={{ padding: '12px 14px' }}><a href={tvLink(s.ticker)} target="_blank" rel="noreferrer" style={{ fontFamily: 'JetBrains Mono', fontWeight: 700, fontSize: 15, color: C.teal }}>{s.ticker}</a></td>
                    <td style={{ padding: '12px 14px' }}><QlBadge pos={s.ql_pos} /></td>
                    <td style={{ padding: '12px 14px', fontFamily: 'JetBrains Mono', fontWeight: 600, color: C.white }}>${s.price.toFixed(2)}</td>
                    <td style={{ padding: '12px 14px', fontSize: 12, color: C.lgray }}>{conds}<br/><span style={{ fontSize: 11, color: C.gray }}>거래량 급증 · 스몰캔들 상단</span></td>
                    <td style={{ padding: '12px 14px', fontFamily: 'JetBrains Mono', color: C.red }}>${stopLoss}<br/><span style={{ fontSize: 10, color: C.gray }}>최대 -1.5%</span></td>
                    <td style={{ padding: '12px 14px', fontFamily: 'JetBrains Mono', fontSize: 14, color: col, fontWeight: 700 }}>{recStars(s.score)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
};

// ── Watchlist ─────────────────────────────────────────────────────────
const STATUS_COLOR = (st) => {
  if (st.includes('진입 가능')) return C.green;
  if (st.includes('베이스'))    return C.gold;
  if (st.includes('최적진입구간')) return C.teal;
  if (st.includes('재평가'))    return C.red;
  return C.gray;
};

const AI_SECTORS_LIST = ['technology', 'semiconductor', 'defense', 'energy', 'aerospace'];
const isAiSector = (sector, industry) =>
  AI_SECTORS_LIST.some(k => (sector + industry).toLowerCase().includes(k));

const ScoreBreakdown = ({ e, today }) => {
  const stale = e.last_seen !== today;
  const staleDays = stale ? Math.round((new Date(today) - new Date(e.last_seen)) / 86400000) : 0;
  const items = [
    { label: 'ADX',         val: `${(e.last_adx||0).toFixed(1)}`,  cond: '> 25',   met: e.last_adx > 25,                           pts: 2 },
    { label: 'RSI',         val: `${(e.last_rsi||0).toFixed(1)}`,  cond: '40~75',  met: e.last_rsi >= 40 && e.last_rsi <= 75,      pts: 2 },
    { label: 'MACD',        val: e.last_macd_bull ? '매수신호' : '중립', cond: '매수신호', met: e.last_macd_bull,                  pts: 2 },
    { label: '52주 신고가권', val: `${(e.last_52w_pct||0).toFixed(1)}%`, cond: '≥ 90%', met: e.last_52w_pct >= 90,               pts: 1 },
    { label: 'YTD 강세',    val: `${(e.last_ytd||0).toFixed(1)}%`, cond: '≥ +50%', met: e.last_ytd >= 50,                        pts: 1 },
    { label: 'AI·반도체 섹터', val: '',                             cond: '',        met: isAiSector(e.sector, e.industry||''),   pts: 1 },
  ];
  return (
    <div style={{ padding: '14px 16px', background: '#f0ede8', borderTop: `1px solid ${C.border}` }}>
      {stale && (
        <div style={{ marginBottom: 10, padding: '6px 10px', background: '#b4530922', borderRadius: 6, border: `1px solid ${C.gold}44`, fontSize: 11, color: C.gold }}>
          ⚠️ {staleDays}일 전 ({e.last_seen}) 마지막 확인 — 현재 지표와 다를 수 있음
        </div>
      )}
      {!stale && (
        <div style={{ marginBottom: 10, padding: '6px 10px', background: '#05996922', borderRadius: 6, border: `1px solid ${C.green}44`, fontSize: 11, color: C.green }}>
          ✓ 오늘 스크리닝 통과 — 현재 점수
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {items.map(({ label, val, cond, met, pts }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
            <span style={{ color: met ? C.green : C.red, fontWeight: 700, width: 16, textAlign: 'center', flexShrink: 0 }}>{met ? '✓' : '✗'}</span>
            <span style={{ color: C.lgray, minWidth: 100 }}>{label}</span>
            {val && <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.white }}>{val}</span>}
            {cond && <span style={{ fontSize: 10, color: C.gray }}>{cond}</span>}
            <span style={{ marginLeft: 'auto', fontFamily: 'JetBrains Mono', fontSize: 11, color: met ? C.green : C.gray, fontWeight: 700 }}>{met ? `+${pts}` : '+0'}</span>
          </div>
        ))}
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${C.border}`, display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: C.lgray }}>총점</span>
          <span style={{ fontFamily: 'JetBrains Mono', fontSize: 14, fontWeight: 700, color: e.last_score >= 7 ? C.green : e.last_score >= 5 ? C.gold : C.blue }}>{e.last_score}/9</span>
        </div>
      </div>
      {e.last_ql_desc && (
        <div style={{ marginTop: 8, fontSize: 11, color: C.lgray }}>모멘텀 위치: {e.last_ql_desc}</div>
      )}
    </div>
  );
};

const WatchlistSection = ({ watchlist, today }) => {
  const [filter, setFilter]   = React.useState('all');
  const [expandedWL, setExpandedWL] = React.useState({});
  const toggleWL = (tk) => setExpandedWL(prev => ({ ...prev, [tk]: !prev[tk] }));

  const entries = Object.entries(watchlist);
  const todayEntries = entries.filter(([, v]) => v.isToday);
  const sorted  = [...todayEntries, ...entries.filter(([, v]) => !v.isToday)];
  const bStage  = sorted.filter(([, v]) => v.last_ql_pos === 'b');
  const filtered = filter === 'today' ? todayEntries
    : filter === 'entry' ? sorted.filter(([, v]) => v.status.includes('진입'))
    : filter === 'b'     ? bStage
    : sorted;
  const tabs = [
    ['all',   `전체 ${entries.length}`],
    ['today', `오늘 신규${todayEntries.length ? ` ${todayEntries.length}` : ''}`],
    ['entry', '진입 가능'],
    ['b',     `B단계 ${bStage.length}`],
  ];
  return (
    <section style={{ marginBottom: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: C.lgray, fontWeight: 500, letterSpacing: '0.1em' }}>04 / 누적 관심종목</span>
        <div style={{ flex: 1, height: 1, background: C.border }} />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {tabs.map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)}
              style={{ padding: '4px 12px', borderRadius: 6, border: `1px solid ${filter===k?(k==='b'?C.green:C.teal):C.border}`, background: filter===k?(k==='b'?C.green:C.teal)+'22':'transparent', color: filter===k?(k==='b'?C.green:C.teal):C.gray, fontSize: 11, cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s' }}>{l}</button>
          ))}
        </div>
      </div>
      <div style={{ background: C.panel, borderRadius: 12, overflow: 'hidden', border: `1px solid ${C.border}` }}>
        {filtered.map(([ticker, e], idx) => {
          const statusCol = STATUS_COLOR(e.status);
          const isToday   = e.isToday;
          const isOpen    = !!expandedWL[ticker];
          const rowBg     = isToday ? '#05996922' : idx % 2 === 0 ? C.panel2 : 'transparent';
          return (
            <div key={ticker} style={{ borderBottom: `1px solid ${C.border}22` }}>
              <div onClick={() => toggleWL(ticker)} style={{ padding: isMobile ? '12px 14px' : '9px 12px', background: rowBg, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 10, flexWrap: 'wrap' }}
                onMouseEnter={ev => { if (!isToday) ev.currentTarget.style.background = '#ede9e2'; }}
                onMouseLeave={ev => { if (!isToday) ev.currentTarget.style.background = rowBg; }}>
                {/* 티커 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: isMobile ? 0 : 80 }}>
                  <a href={tvLink(ticker)} target="_blank" rel="noreferrer" onClick={ev => ev.stopPropagation()}
                    style={{ fontFamily: 'JetBrains Mono', fontWeight: 700, fontSize: isMobile ? 15 : 13, color: isToday ? C.green : C.teal }}>{ticker}</a>
                  {isToday && <span style={{ fontSize: 9, color: C.green, fontWeight: 700 }}>NEW</span>}
                </div>
                {/* 종목명·섹터 */}
                <div style={{ flex: isMobile ? '1 1 100%' : 1, minWidth: isMobile ? 0 : 100 }}>
                  {isMobile
                    ? <div style={{ fontSize: 12, color: C.lgray }}>{e.name} · {SECTOR_KO[e.sector] || e.sector}</div>
                    : <span style={{ fontSize: 12, color: C.lgray }}>{e.name}</span>}
                </div>
                {!isMobile && <span style={{ fontSize: 11, color: C.gray, minWidth: 60 }}>{SECTOR_KO[e.sector] || e.sector}</span>}
                {!isMobile && <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.gray, minWidth: 76 }}>{e.first_seen}</span>}
                <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: C.white, textAlign: 'center', minWidth: 28 }}>{e.days}일</span>
                <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: e.appearances>=5?C.gold:C.lgray, textAlign: 'center', minWidth: 28 }}>×{e.appearances}</span>
                <span style={{ fontFamily: 'JetBrains Mono', fontSize: 13, color: C.white, fontWeight: 600, minWidth: 60 }}>${e.last_price.toFixed(2)}</span>
                <QlBadge pos={e.last_ql_pos} />
                <div style={{ minWidth: 80 }}><ScoreBar score={e.last_score} /></div>
                <span style={{ fontSize: 11, color: statusCol, fontWeight: 600, minWidth: 80 }}>{e.status}</span>
                <span style={{ color: isOpen ? C.accent : C.gray, fontSize: 14, marginLeft: 4 }}>{isOpen ? '▲' : '▼'}</span>
              </div>
              {isOpen && <ScoreBreakdown e={e} today={today} />}
            </div>
          );
        })}
      </div>
    </section>
  );
};

// ── App ───────────────────────────────────────────────────────────────
function App() {
  const [expanded, setExpanded] = React.useState({});
  const toggle = (tk) => setExpanded(prev => ({ ...prev, [tk]: !prev[tk] }));
  const mkt = DATA.market; const spy = mkt.spy; const qqq = mkt.qqq;
  const mktStatus = (spy.chg > 0.5 && qqq.chg > 0.5) ? '강세' : (spy.chg < -0.5 && qqq.chg < -0.5) ? '약세' : '혼조';
  const mktCol = mktStatus === '강세' ? C.green : mktStatus === '약세' ? C.red : C.gold;
  return (
    <div style={{ minHeight: '100vh', background: C.bg }}>
      <header style={{ background: C.panel, borderBottom: `1px solid ${C.border}`, padding: isMobile ? '0 14px' : '0 24px', position: 'sticky', top: 0, zIndex: 100, boxShadow: '0 1px 8px #00000012' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', alignItems: 'center', height: 52, gap: isMobile ? 8 : 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 15, fontWeight: 700, color: C.accent }}>TGS</span>
            {!isMobile && <span style={{ fontSize: 13, color: C.lgray }}>Top Gainers Screening</span>}
          </div>
          <div style={{ flex: 1 }} />
          <ArchiveNav dates={ARCHIVE_DATES} today={DATA.date} />
          {!isMobile && <Badge label={`시장 ${mktStatus}`} color={mktCol} />}
          <Badge label={`통과 ${DATA.passed.length}종목`} color={C.accent} />
        </div>
      </header>
      <main style={{ maxWidth: 1100, margin: '0 auto', padding: isMobile ? '20px 12px' : '32px 24px' }}>
        <MarketSection mkt={mkt} />
        <section style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <span style={{ fontSize: 11, color: C.lgray, fontWeight: 500, letterSpacing: '0.1em' }}>02 / 스크리닝 결과</span>
            <div style={{ flex: 1, height: 1, background: C.border }} />
            <span style={{ fontSize: 11, color: C.gray }}>Yahoo Finance Top 50 → 모멘텀 필터 → 기술적 2차 필터</span>
          </div>
          {DATA.passed.length === 0
            ? <div style={{ textAlign: 'center', padding: '40px', color: C.lgray }}>오늘은 조건에 맞는 종목이 없습니다</div>
            : DATA.passed.map((s, i) => <StockCard key={s.ticker} s={s} rank={i+1} expanded={!!expanded[s.ticker]} onToggle={() => toggle(s.ticker)} />)
          }
        </section>
        {DATA.passed.length > 0 && <최적진입구간Section passed={DATA.passed} />}
        <WatchlistSection watchlist={DATA.watchlist} today={DATA.date} />
        <footer style={{ paddingTop: 24, borderTop: `1px solid ${C.border}`, textAlign: 'center' }}>
          <p style={{ fontSize: 11, color: C.gray, lineHeight: 1.8 }}>최적 진입 원칙: 지수 &gt; 섹터 &gt; 종목 · ADR 50% 이하 · 2~4일 스몰캔들 · 거래량 감소 · 손절 최대 1.5%</p>
          <p style={{ fontSize: 10, color: C.border, marginTop: 6 }}>투자 참고용. 최종 책임은 본인에게 있습니다.</p>
        </footer>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body>
</html>
"""

# ── 빌더 ─────────────────────────────────────────────────────────────
def build_html(passed, mkt, wl=None, archive_dates=None):
    data_json = _build_data_json(passed, mkt, wl)
    dates_json = json.dumps(sorted(archive_dates or [TODAY], reverse=True))
    html = (HTML_TEMPLATE
            .replace('__DATA_JSON__', data_json)
            .replace('__ARCHIVE_DATES__', dates_json)
            .replace('__DATE__', TODAY))
    with open(HTML_OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[html_report] HTML 생성 완료: {HTML_OUT}")
    return html


# ── 텔레그램 전송 ─────────────────────────────────────────────────────
PAGES_URL = "https://topgain-screening.netlify.app"


def send_telegram_html(passed, mkt):
    import time
    spy = mkt.get('spy', {}); qqq = mkt.get('qqq', {}); vix = mkt.get('vix', {})
    caption = (
        f"📊 US Top Gainers Screening [{TODAY}]\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"SPY {spy.get('chg',0):+.2f}% | QQQ {qqq.get('chg',0):+.2f}% | VIX {vix.get('price',0):.1f} ({vix.get('chg',0):+.1f}%)\n"
        f"최종 통과: {len(passed)}개\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌐 웹 리포트: {PAGES_URL}\n"
    )
    for s in passed:
        caption += f"• {s['ticker']} +{s['change_pct']:.1f}% | RSI:{s['rsi']:.0f} | {s['ql_pos']} | {s['score']}/9\n"
    if not passed:
        caption += "조건에 맞는 종목 없음\n"
    caption = (caption + "투자 책임은 본인에게 있습니다")[:1024]

    for attempt in range(3):
        try:
            with open(HTML_OUT, 'rb') as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={'chat_id': CHAT_ID, 'caption': caption},
                    files={'document': (f'TGS_Report_{TODAY}.html', f, 'text/html')},
                    timeout=60
                )
            if r.ok and r.json().get('ok'):
                print("[html_report] 텔레그램 HTML 전송 완료")
                return
            else:
                print(f"[html_report] 텔레그램 재시도 {attempt+1}: {r.text[:100]}")
        except Exception as e:
            print(f"[html_report] 텔레그램 재시도 {attempt+1}: {e}")
        time.sleep(5)
    raise RuntimeError("텔레그램 HTML 3회 실패")
