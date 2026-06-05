"""
SOXX 반도체 순환매/상대강도 일일 모니터링

매일 1회 실행해서 SOXX의 주도권 유지/상실 신호를 정량 판단.
결과: 콘솔 출력 + signals_log.csv 누적 + Telegram HTML 텍스트 반환.

cron 등록 (장 마감 30분 후 ET 기준):
  30 16 * * 1-5  /usr/bin/python3 /path/to/soxx_monitor.py >> /path/to/semi.log 2>&1

launchd (macOS) — ~/Library/LaunchAgents/com.soxx.monitor.plist 참고:
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>/path/to/soxx_monitor.py</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
"""

import os
import sys
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_LOG  = os.path.join(BASE_DIR, "signals_log.csv")

# ── 조정 가능 설정 ──────────────────────────────────────────────────────
CONFIG = {
    # 기존 파라미터
    "lookback_period":   "2y",   # yfinance 기간 (약 500 거래일)
    "high_window":        60,    # 신고가 판정 거래일
    "trim_window":        10,    # TRIM 이력 조회 거래일
    "trim_min_days":       5,    # TRIM 판정 최소 음의 다이버전스 일수 (기본/순풍)
    "mom_1m":             21,    # 1개월 수익률 거래일
    "mom_3m":             63,    # 3개월 수익률 거래일
    "ma_ratio_short":     20,    # RS 비율선 단기 SMA
    "ma_ratio_long":      50,    # RS 비율선 장기 SMA
    "ma_mansfield_200":  200,    # Mansfield RS 장기 MA
    "ma_mansfield_50":    50,    # Mansfield RS 단기 MA
    "rotate_min_sectors":  2,    # 순환매 판단 최소 아웃퍼폼 섹터 수

    # ── 스타일 로테이션 필터 파라미터 ───────────────────────────────────
    "style_ma_short":     20,    # SPYG/SPYV 비율의 단기 SMA
    "style_ma_long":      50,    # SPYG/SPYV 비율의 장기 SMA (역풍 판정 기준)
    "style_low_window":   20,    # 최근 저점 룩백 거래일 (가치 로테이션 확증용)
    "trim_min_watch":      3,    # watch(주의) 시 완화된 TRIM 트리거 일수
    "trim_min_headwind":   2,    # headwind(역풍) 시 더 민감한 TRIM 트리거 일수
}

MAIN    = "SOXX"
SECTORS = {
    "XLF": "금융",
    "XLE": "에너지",
    "IGV": "소프트웨어",
    "XLK": "테크",
    "XLV": "헬스케어",
    "XLI": "산업재",
}
# SPYG(성장), SPYV(가치) 추가
ALL_TICKERS = [MAIN, "SPY", "MTUM", "SPYG", "SPYV"] + list(SECTORS.keys())

SIGNAL_EMOJI = {
    "EXIT_ALL": "🔴",
    "REDUCE":   "🟠",
    "TRIM":     "🟡",
    "ROTATE":   "🔵",
    "HOLD":     "🟢",
}
SIGNAL_LABEL = {
    "EXIT_ALL": "전량 정리",
    "REDUCE":   "축소",
    "TRIM":     "절반 익절",
    "ROTATE":   "섹터 교체 검토",
    "HOLD":     "보유 유지",
}
STYLE_EMOJI = {
    "tailwind": "🌤️",
    "watch":    "⛅",
    "headwind": "🌧️",
    "unknown":  "❓",
}
STYLE_LABEL = {
    "tailwind": "순풍",
    "watch":    "주의",
    "headwind": "역풍",
    "unknown":  "데이터없음",
}


# ── 데이터 수집 ────────────────────────────────────────────────────────
def _fetch_data() -> dict:
    """모든 티커 일봉 종가를 dict[sym -> pd.Series]로 반환. 실패 시 경고만."""
    closes = {}
    for sym in ALL_TICKERS:
        try:
            h = yf.Ticker(sym).history(period=CONFIG["lookback_period"])
            if h.empty or len(h) < 100:
                print(f"[WARN] {sym}: 데이터 부족", file=sys.stderr)
                continue
            closes[sym] = h["Close"].dropna()
        except Exception as e:
            print(f"[WARN] {sym}: 수신 실패 — {e}", file=sys.stderr)
    return closes


def _market_status() -> str:
    """현재 미국 시장 상태: 'pre' | 'open' | 'after' | 'closed'"""
    et  = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return "closed"
    hm = now.hour * 100 + now.minute
    if 400  <= hm < 930:  return "pre"
    if 930  <= hm < 1600: return "open"
    if 1600 <= hm < 2000: return "after"
    return "closed"


def _fetch_current_price(sym: str) -> dict:
    """시장 상태에 맞는 현재가 반환.
    정규장 → regularMarketPrice,  프리마켓 → preMarketPrice,
    애프터 → postMarketPrice,     휴장    → 마지막 종가(일봉)
    """
    status = _market_status()
    try:
        info       = yf.Ticker(sym).info
        reg_price  = info.get("regularMarketPrice") or 0
        reg_chg    = info.get("regularMarketChangePercent") or 0
        prev_close = info.get("regularMarketPreviousClose") or reg_price

        if status == "open":
            price   = reg_price
            chg_pct = reg_chg
            label   = "정규장"
        elif status == "pre":
            price = info.get("preMarketPrice") or reg_price
            raw   = info.get("preMarketChangePercent")
            chg_pct = raw if raw is not None else (
                (price / prev_close - 1) * 100 if prev_close else 0)
            label = "프리마켓"
        elif status == "after":
            price = info.get("postMarketPrice") or reg_price
            raw   = info.get("postMarketChangePercent")
            chg_pct = raw if raw is not None else (
                (price / prev_close - 1) * 100 if prev_close else 0)
            label = "애프터마켓"
        else:
            price   = reg_price
            chg_pct = reg_chg
            label   = "마지막 종가"

        if not price:
            return {}
        return {
            "price":   float(price),
            "chg_pct": float(chg_pct),
            "label":   label,
            "status":  status,
        }
    except Exception as e:
        print(f"[WARN] {sym} 현재가 조회 실패 — {e}", file=sys.stderr)
        return {}


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


# ── 1) RS 비율선 ────────────────────────────────────────────────────────
def _calc_rs_ratio(closes: dict) -> dict:
    """SOXX/SPY, SOXX/MTUM 비율선 · SMA · 50일 SMA 하향이탈 여부"""
    soxx = closes.get(MAIN)
    if soxx is None:
        return {}
    result = {}
    for bench in ["SPY", "MTUM"]:
        b = closes.get(bench)
        if b is None:
            continue
        ratio = soxx / b.reindex(soxx.index, method="ffill")
        sma20 = _sma(ratio, CONFIG["ma_ratio_short"])
        sma50 = _sma(ratio, CONFIG["ma_ratio_long"])
        last_sma50 = sma50.dropna().iloc[-1] if not sma50.dropna().empty else None
        below_50 = bool(ratio.iloc[-1] < last_sma50) if last_sma50 is not None else False
        result[bench] = {
            "ratio":     ratio,
            "ratio_now": float(ratio.iloc[-1]),
            "sma20_now": float(sma20.dropna().iloc[-1]) if not sma20.dropna().empty else None,
            "sma50_now": float(last_sma50) if last_sma50 is not None else None,
            "below_50":  below_50,
        }
    return result


# ── 2) Mansfield RS ─────────────────────────────────────────────────────
def _calc_mansfield(closes: dict) -> dict:
    """Weinstein 방식 Mansfield RS: 200일·50일 기반 + 0선 돌파 감지"""
    soxx = closes.get(MAIN)
    spy  = closes.get("SPY")
    if soxx is None or spy is None:
        return {}

    rp = soxx / spy.reindex(soxx.index, method="ffill")

    def _mansfield_series(rp, n):
        ma = _sma(rp, n).dropna()
        rp_a = rp.reindex(ma.index)
        return (rp_a / ma - 1) * 100

    def _crossover(series: pd.Series):
        s = series.dropna()
        if len(s) < 2:
            return float(s.iloc[-1]) if len(s) else 0.0, False, False
        cur, prev = float(s.iloc[-1]), float(s.iloc[-2])
        return cur, (prev < 0 and cur >= 0), (prev >= 0 and cur < 0)

    m200 = _mansfield_series(rp, CONFIG["ma_mansfield_200"])
    m50  = _mansfield_series(rp, CONFIG["ma_mansfield_50"])

    m200_now, m200_up, m200_down = _crossover(m200)
    m50_now,  m50_up,  m50_down  = _crossover(m50)

    return {
        "mansfield_200":      m200_now,
        "mansfield_200_up":   m200_up,
        "mansfield_200_down": m200_down,
        "mansfield_50":       m50_now,
        "mansfield_50_up":    m50_up,
        "mansfield_50_down":  m50_down,
    }


# ── 3) 신고가 다이버전스 ─────────────────────────────────────────────────
def _calc_divergence(closes: dict, rs_ratio: dict) -> dict:
    """가격 신고가이면서 RS 비율은 신고가 아닌 경우 = 음의 다이버전스"""
    soxx = closes.get(MAIN)
    if soxx is None or "SPY" not in rs_ratio:
        return {"divergence": False, "div_count_10": 0, "trim_flag": False}

    w  = CONFIG["high_window"]
    tw = CONFIG["trim_window"]
    ratio = rs_ratio["SPY"]["ratio"]

    soxx_max  = soxx.rolling(w,  min_periods=w).max()
    ratio_max = ratio.rolling(w, min_periods=w).max()

    # 최근 trim_window 일간 음의 다이버전스 이력
    div_days = 0
    for i in range(-tw, 0):
        try:
            p_new = soxx.iloc[i]  >= soxx_max.iloc[i]
            r_new = ratio.iloc[i] >= ratio_max.iloc[i]
            if p_new and not r_new:
                div_days += 1
        except Exception:
            pass

    today_div = (
        soxx.iloc[-1]  >= soxx_max.iloc[-1] and
        ratio.iloc[-1] < ratio_max.iloc[-1]
        if not (pd.isna(soxx_max.iloc[-1]) or pd.isna(ratio_max.iloc[-1]))
        else False
    )

    return {
        "divergence":   bool(today_div),
        "div_count_10": div_days,
        # trim_flag는 style 조정 전 raw 값 — _decide_signal에서 style_state 반영
        "div_days_raw": div_days,
    }


# ── 4) 모멘텀 스프레드 ───────────────────────────────────────────────────
def _calc_momentum(closes: dict) -> dict:
    """1개월·3개월 수익률 및 SPY/MTUM 스프레드, 섹터 비교"""
    m1 = CONFIG["mom_1m"]
    m3 = CONFIG["mom_3m"]

    def _ret(sym, n):
        s = closes.get(sym)
        if s is None or len(s) <= n:
            return None
        return float(s.iloc[-1] / s.iloc[-(n + 1)] - 1) * 100

    soxx_1m = _ret(MAIN, m1);  soxx_3m = _ret(MAIN, m3)
    spy_1m  = _ret("SPY",  m1); spy_3m  = _ret("SPY",  m3)
    mtum_1m = _ret("MTUM", m1); mtum_3m = _ret("MTUM", m3)

    def _spread(a, b):
        return round(a - b, 2) if a is not None and b is not None else None

    sector_1m = {sym: r for sym in SECTORS if (r := _ret(sym, m1)) is not None}
    outperform = {k: v for k, v in sector_1m.items() if soxx_1m is not None and v > soxx_1m}

    return {
        "soxx_1m": soxx_1m, "soxx_3m": soxx_3m,
        "spy_1m":  spy_1m,  "spy_3m":  spy_3m,
        "mtum_1m": mtum_1m, "mtum_3m": mtum_3m,
        "spread_1m_spy":  _spread(soxx_1m, spy_1m),
        "spread_3m_spy":  _spread(soxx_3m, spy_3m),
        "spread_1m_mtum": _spread(soxx_1m, mtum_1m),
        "spread_3m_mtum": _spread(soxx_3m, mtum_3m),
        "sector_1m":  sector_1m,
        "outperform": outperform,
    }


# ── 5) 스타일 로테이션 역풍 필터 ────────────────────────────────────────
def _calc_style_filter(closes: dict) -> dict:
    """
    SPYG(성장)/SPYV(가치) 비율로 스타일 로테이션 방향을 감지.

    판정 기준:
    - headwind(역풍): style_ratio가 50일 SMA 하향이탈 AND 20일 저점도 하향 돌파
    - watch(주의):   위 두 조건 중 하나만 충족
    - tailwind(순풍): 두 조건 모두 미충족
    - unknown:       SPYG 또는 SPYV 데이터 없을 때 (기존 신호는 정상 작동)
    """
    spyg = closes.get("SPYG")
    spyv = closes.get("SPYV")
    if spyg is None or spyv is None:
        return {
            "style_state":         "unknown",
            "style_ratio":         None,
            "style_ratio_50ma":    None,
            "below_50ma":          False,
            "below_20d_low":       False,
            "spyg_1m":             None,
            "spyv_1m":             None,
            "spyg_minus_spyv_1m":  None,
        }

    m1 = CONFIG["mom_1m"]
    idx = spyg.index.intersection(spyv.index)
    spyg_a = spyg.reindex(idx)
    spyv_a = spyv.reindex(idx)

    ratio    = spyg_a / spyv_a
    sma20    = _sma(ratio, CONFIG["style_ma_short"])
    sma50    = _sma(ratio, CONFIG["style_ma_long"])

    last_ratio = float(ratio.iloc[-1])
    last_sma50 = float(sma50.dropna().iloc[-1]) if not sma50.dropna().empty else None

    # 조건 ①: 비율이 50일 SMA 하향이탈
    below_50ma = bool(last_sma50 is not None and last_ratio < last_sma50)

    # 조건 ②: 최근 20일 저점 하향 돌파 (오늘 포함 제외, 직전 20일의 최솟값)
    lw = CONFIG["style_low_window"]
    if len(ratio) > lw + 1:
        recent_low = float(ratio.iloc[-(lw + 1):-1].min())
        below_20d_low = bool(last_ratio < recent_low)
    else:
        below_20d_low = False

    # 판정
    n_conds = int(below_50ma) + int(below_20d_low)
    if n_conds == 2:
        state = "headwind"
    elif n_conds == 1:
        state = "watch"
    else:
        state = "tailwind"

    # SPYG / SPYV 1M 수익률
    def _ret1m(s):
        if s is None or len(s) <= m1:
            return None
        return float(s.iloc[-1] / s.iloc[-(m1 + 1)] - 1) * 100

    spyg_1m = _ret1m(spyg)
    spyv_1m = _ret1m(spyv)
    diff_1m = round(spyg_1m - spyv_1m, 2) if spyg_1m is not None and spyv_1m is not None else None

    return {
        "style_state":         state,
        "style_ratio":         round(last_ratio, 4),
        "style_ratio_50ma":    round(last_sma50, 4) if last_sma50 else None,
        "below_50ma":          below_50ma,
        "below_20d_low":       below_20d_low,
        "spyg_1m":             round(spyg_1m, 2) if spyg_1m is not None else None,
        "spyv_1m":             round(spyv_1m, 2) if spyv_1m is not None else None,
        "spyg_minus_spyv_1m":  diff_1m,
    }


# ── 최종 신호 결정 (스타일 필터 반영) ───────────────────────────────────
def _decide_signal(
    mansfield: dict,
    rs_ratio:  dict,
    divergence: dict,
    momentum:  dict,
    style_state: str = "tailwind",
) -> tuple:
    """
    우선순위: EXIT_ALL > REDUCE > TRIM > ROTATE > HOLD

    style_state에 따라 임계값 조정:
    - tailwind: 기본값 그대로
    - watch:    trim_min을 CONFIG["trim_min_watch"]로 완화
    - headwind: trim_min을 CONFIG["trim_min_headwind"]로 더 완화,
                REDUCE는 SPY 비율선만 50MA 이탈해도 발동
    - EXIT_ALL은 style_state와 무관하게 항상 동일

    반환: (signal, adjustments_desc)
    adjustments_desc: 어떤 임계값이 바뀌었는지 설명 문자열 (없으면 "")
    """
    adj = []  # 조정 내역 기록

    # EXIT_ALL: style 무관 — Mansfield RS 200 또는 50이 0선 하향 돌파
    if mansfield.get("mansfield_200_down") or mansfield.get("mansfield_50_down"):
        return "EXIT_ALL", ""

    # REDUCE: headwind면 SPY 하나만 이탈해도 발동 (기본은 SPY or MTUM)
    spy_below  = rs_ratio.get("SPY",  {}).get("below_50", False)
    mtum_below = rs_ratio.get("MTUM", {}).get("below_50", False)
    if style_state == "headwind":
        reduce_triggered = spy_below  # SPY 하나로 충분
        if reduce_triggered and not mtum_below:
            adj.append("REDUCE: SPY 비율선 단독 이탈로 발동 (headwind 완화)")
    else:
        reduce_triggered = spy_below or mtum_below
    if reduce_triggered:
        return "REDUCE", "  |  ".join(adj)

    # TRIM: style_state에 따라 trim_min_days 동적 조정
    div_days = divergence.get("div_days_raw", 0)
    if style_state == "headwind":
        trim_threshold = CONFIG["trim_min_headwind"]
        if trim_threshold != CONFIG["trim_min_days"]:
            adj.append(f"TRIM 기준 {CONFIG['trim_min_days']}일→{trim_threshold}일 (headwind)")
    elif style_state == "watch":
        trim_threshold = CONFIG["trim_min_watch"]
        if trim_threshold != CONFIG["trim_min_days"]:
            adj.append(f"TRIM 기준 {CONFIG['trim_min_days']}일→{trim_threshold}일 (watch)")
    else:
        trim_threshold = CONFIG["trim_min_days"]
    if div_days >= trim_threshold:
        return "TRIM", "  |  ".join(adj)

    # ROTATE: 1M 스프레드 음수 + 아웃퍼폼 섹터 2개 이상
    sp = momentum.get("spread_1m_spy") or 0
    if sp < 0 and len(momentum.get("outperform", {})) >= CONFIG["rotate_min_sectors"]:
        return "ROTATE", "  |  ".join(adj)

    return "HOLD", "  |  ".join(adj)


# ── CSV 로그 ─────────────────────────────────────────────────────────────
def _load_log() -> pd.DataFrame:
    cols = [
        "date", "price", "ratio_spy", "ratio_spy_50ma", "mansfield_200",
        "mansfield_50", "divergence_flag", "spread_1m_spy", "spread_1m_mtum",
        "top_sector", "final_signal",
        # 스타일 필터 컬럼 (기존 뒤에 append)
        "style_ratio", "style_ratio_50ma", "style_state", "spyg_minus_spyv_1m",
    ]
    if os.path.exists(CSV_LOG):
        try:
            df = pd.read_csv(CSV_LOG)
            # 신규 컬럼이 없으면 추가
            for c in cols:
                if c not in df.columns:
                    df[c] = None
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=cols)


def _save_log(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    """당일 행이 이미 있으면 덮어쓰기, 없으면 추가"""
    today = str(row["date"])[:10]
    df = df[~df["date"].astype(str).str.startswith(today)]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(CSV_LOG, index=False)
    return df


# ── 메인 ────────────────────────────────────────────────────────────────
def run_monitor() -> tuple:
    """
    실행 후 (console_text, telegram_html) 반환.
    외부에서 telegram_html을 send_message()에 바로 넘길 수 있음.
    """
    et    = pytz.timezone("America/New_York")
    today = datetime.now(et).strftime("%Y-%m-%d")

    print(f"[soxx] 데이터 수집 중... ({today})")
    closes = _fetch_data()

    # 일봉 마지막 종가 (지표 계산 기준)
    soxx_close = float(closes[MAIN].iloc[-1]) if MAIN in closes else None
    # 시장 상태에 맞는 현재가 (표시용)
    cur = _fetch_current_price(MAIN)
    soxx_price  = cur.get("price") or soxx_close
    soxx_chg    = cur.get("chg_pct")
    soxx_label  = cur.get("label", "")

    rs_ratio   = _calc_rs_ratio(closes)
    mansfield  = _calc_mansfield(closes)
    divergence = _calc_divergence(closes, rs_ratio)
    momentum   = _calc_momentum(closes)
    style      = _calc_style_filter(closes)          # ← 스타일 필터
    style_state = style["style_state"]

    signal, adj_desc = _decide_signal(
        mansfield, rs_ratio, divergence, momentum, style_state
    )

    # 어제 신호 (오늘 이전 마지막 행)
    log_df = _load_log()
    prev_signal = None
    if not log_df.empty:
        before = log_df[~log_df["date"].astype(str).str.startswith(today)]
        if not before.empty:
            prev_signal = str(before.iloc[-1]["final_signal"])

    top_sector = (max(momentum.get("outperform", {}),
                      key=lambda k: momentum["outperform"][k], default=""))

    row = {
        "date":               today,
        "price":              round(soxx_price, 2) if soxx_price else None,
        "ratio_spy":          round(rs_ratio.get("SPY",  {}).get("ratio_now", 0), 4),
        "ratio_spy_50ma":     round(rs_ratio.get("SPY",  {}).get("sma50_now") or 0, 4),
        "mansfield_200":      round(mansfield.get("mansfield_200", 0), 2),
        "mansfield_50":       round(mansfield.get("mansfield_50",  0), 2),
        "divergence_flag":    int(divergence.get("divergence", False)),
        "spread_1m_spy":      round(momentum.get("spread_1m_spy")  or 0, 2),
        "spread_1m_mtum":     round(momentum.get("spread_1m_mtum") or 0, 2),
        "top_sector":         top_sector,
        "final_signal":       signal,
        # 스타일 필터
        "style_ratio":        style["style_ratio"],
        "style_ratio_50ma":   style["style_ratio_50ma"],
        "style_state":        style_state,
        "spyg_minus_spyv_1m": style["spyg_minus_spyv_1m"],
    }
    log_df = _save_log(log_df, row)

    # ── Telegram HTML ────────────────────────────────────────────────────
    emoji  = SIGNAL_EMOJI[signal]
    label  = SIGNAL_LABEL[signal]

    if soxx_price:
        chg_str   = f"  {soxx_chg:+.2f}%" if soxx_chg is not None else ""
        price_str = f"${soxx_price:.2f}{chg_str}  <i>({soxx_label})</i>"
        price_console = f"${soxx_price:.2f}{('  ' + f'{soxx_chg:+.2f}%') if soxx_chg is not None else ''}  ({soxx_label})"
    else:
        price_str     = "N/A"
        price_console = "N/A"

    spy_rs   = rs_ratio.get("SPY",  {})
    mtum_rs  = rs_ratio.get("MTUM", {})

    def _rs_tag(d):
        return "⚠️ 50MA 하향이탈" if d.get("below_50") else "✅ 50MA 위"

    m200     = mansfield.get("mansfield_200", 0)
    m50      = mansfield.get("mansfield_50",  0)
    m200_sfx = ("  🔻 0선 하향돌파!" if mansfield.get("mansfield_200_down")
                 else "  🔺 0선 상향돌파" if mansfield.get("mansfield_200_up") else "")
    m50_sfx  = ("  🔻 0선 하향돌파!" if mansfield.get("mansfield_50_down")
                 else "  🔺 0선 상향돌파" if mansfield.get("mansfield_50_up") else "")

    div_flag  = divergence.get("divergence", False)
    div_days  = divergence.get("div_days_raw", 0)

    sp1  = momentum.get("spread_1m_spy")  or 0
    sm1  = momentum.get("spread_1m_mtum") or 0
    sp3  = momentum.get("spread_3m_spy")  or 0
    sm3  = momentum.get("spread_3m_mtum") or 0
    outperform = momentum.get("outperform", {})

    sector_lines = []
    for sym, ret in sorted(momentum.get("sector_1m", {}).items(), key=lambda x: -x[1]):
        tag = " 🔼" if sym in outperform else ""
        sector_lines.append(f"  {sym}({SECTORS[sym]}): {ret:+.1f}%{tag}")

    # 스타일 필터 표시
    s_emoji = STYLE_EMOJI[style_state]
    s_label = STYLE_LABEL[style_state]
    sr      = style["style_ratio"]
    sr_ma   = style["style_ratio_50ma"]
    sr_str  = f"{sr:.3f}" if sr is not None else "N/A"
    sr_ma_str = f"{sr_ma:.3f}" if sr_ma is not None else "N/A"
    spyg_1m = style.get("spyg_1m")
    spyv_1m = style.get("spyv_1m")
    diff_1m = style.get("spyg_minus_spyv_1m")

    style_cond_lines = []
    if style_state != "unknown":
        c1 = "✅" if not style["below_50ma"]    else "❌"
        c2 = "✅" if not style["below_20d_low"] else "❌"
        style_cond_lines = [
            f"  {c1} 50MA 위: SPYG/SPYV {sr_str} {'≥' if not style['below_50ma'] else '<'} 50MA {sr_ma_str}",
            f"  {c2} 20일 저점 위: {'유지' if not style['below_20d_low'] else '하향 이탈'}",
        ]
        if spyg_1m is not None and spyv_1m is not None:
            diff_str = f"{diff_1m:+.1f}%" if diff_1m is not None else ""
            style_cond_lines.append(
                f"  SPYG 1M: {spyg_1m:+.1f}%  SPYV 1M: {spyv_1m:+.1f}%  (성장-가치: {diff_str})"
            )

    # 조정 내역
    adj_line_tg = (f"\n<i>⚙️ 임계값 조정: {adj_desc}</i>" if adj_desc else "")

    # headwind일 때 HOLD → 추가 경고
    headwind_warn_tg = (
        "\n⚠️ <b>스타일 역풍 — 신규 추가 보류</b>"
        if style_state == "headwind" and signal == "HOLD" else ""
    )

    change_hdr = (f"⚠️ 신호 변경: {prev_signal} → {signal}\n\n"
                  if prev_signal and prev_signal != signal else "")

    tg = "\n".join([
        f"{change_hdr}<b>📡 SOXX 반도체 순환매 모니터링</b>",
        f"<i>{today} ET 기준</i>",
        f"SOXX: <b>{price_str}</b>",
        "",
        f"<b>🎨 스타일 필터: {s_emoji} {style_state.upper()} — {s_label}</b>",
        *style_cond_lines,
        "",
        "<b>① RS 비율선</b>",
        f"  SOXX/SPY:  {spy_rs.get('ratio_now', 0):.4f}  {_rs_tag(spy_rs)}",
        f"  SOXX/MTUM: {mtum_rs.get('ratio_now', 0):.4f}  {_rs_tag(mtum_rs)}",
        "",
        "<b>② Mansfield RS</b>",
        f"  200일: {m200:+.2f}  {'(0선 위✅)' if m200 >= 0 else '(0선 아래❌)'}{m200_sfx}",
        f"   50일: {m50:+.2f}  {'(0선 위✅)' if m50 >= 0 else '(0선 아래❌)'}{m50_sfx}",
        "",
        "<b>③ 신고가 다이버전스 (최근 60일)</b>",
        f"  오늘: {'⚠️ 음의 다이버전스' if div_flag else '✅ 없음'}",
        f"  10일 중: {div_days}일",
        "",
        "<b>④ 모멘텀 스프레드</b>",
        f"  1M: vs SPY {sp1:+.1f}%  /  vs MTUM {sm1:+.1f}%",
        f"  3M: vs SPY {sp3:+.1f}%  /  vs MTUM {sm3:+.1f}%",
        "",
        "<b>섹터 1M 수익률 (🔼=아웃퍼폼)</b>",
        *sector_lines,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"<b>최종 신호: {emoji} {signal} — {label}</b>{adj_line_tg}{headwind_warn_tg}",
        "━━━━━━━━━━━━━━━━━━━━",
    ])

    # ── 콘솔 출력 ────────────────────────────────────────────────────────
    sep = "=" * 52
    headwind_warn_c = (
        "  ⚠️  스타일 역풍 — 신규 추가 보류"
        if style_state == "headwind" and signal == "HOLD" else ""
    )
    adj_line_c = (f"  ⚙️  임계값 조정: {adj_desc}" if adj_desc else "")

    console_parts = [
        *(["⚠️  신호 변경: " + prev_signal + " → " + signal, ""] if prev_signal and prev_signal != signal else []),
        sep,
        f"  SOXX 반도체 모니터링  {today}",
        sep,
        f"  SOXX: {price_console}",
        "",
        f"  스타일: {s_emoji} {style_state.upper()} — {s_label}  |  SPYG/SPYV={sr_str}  (50MA {sr_ma_str})",
    ]
    if adj_line_c:
        console_parts.append(adj_line_c)
    if style_state != "unknown":
        cond_txt = (
            f"  조건: 50MA이탈={'❌' if style['below_50ma'] else '✓'}  "
            f"20일저점이탈={'❌' if style['below_20d_low'] else '✓'}  "
            f"SPYG-SPYV 1M={(f'{diff_1m:+.1f}%') if diff_1m is not None else 'N/A'}"
        )
        console_parts.append(cond_txt)

    console_parts += [
        "",
        "  [1] RS 비율선",
        f"    SOXX/SPY:  {spy_rs.get('ratio_now', 0):.4f}  {'⚠ 50MA하향' if spy_rs.get('below_50') else '✓ 50MA위'}",
        f"    SOXX/MTUM: {mtum_rs.get('ratio_now', 0):.4f}  {'⚠ 50MA하향' if mtum_rs.get('below_50') else '✓ 50MA위'}",
        "",
        "  [2] Mansfield RS",
        f"    200일: {m200:+.2f}  {'0선위' if m200 >= 0 else '0선아래'}{m200_sfx}",
        f"     50일: {m50:+.2f}  {'0선위' if m50 >= 0 else '0선아래'}{m50_sfx}",
        "",
        "  [3] 신고가 다이버전스",
        f"    오늘: {'음의다이버전스' if div_flag else '없음'}  |  10일중 {div_days}일",
        "",
        "  [4] 모멘텀 스프레드",
        f"    1M: vs SPY {sp1:+.1f}%  vs MTUM {sm1:+.1f}%",
        f"    3M: vs SPY {sp3:+.1f}%  vs MTUM {sm3:+.1f}%",
        f"    아웃퍼폼 섹터: {', '.join(outperform.keys()) or '없음'}",
        "",
        sep,
        f"  최종 신호: {emoji} {signal} — {label}",
        *(["", headwind_warn_c] if headwind_warn_c else []),
        sep,
    ]

    console = "\n".join(console_parts)
    print(console)

    return console, tg


if __name__ == "__main__":
    run_monitor()
