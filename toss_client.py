"""
토스증권 Open API 클라이언트

인증 정보는 환경변수에서 읽음 (호스팅 플랫폼의 환경변수 설정에 등록):
  TOSS_CLIENT_ID      - 토스증권 WTS > 설정 > Open API에서 발급
  TOSS_CLIENT_SECRET  - 위와 동일 화면에서 발급
  TOSS_ACCOUNT_ID     - 주문 시 필요한 계좌 식별자 (X-Tossinvest-Account 헤더)
  TOSS_DRY_RUN        - "false"로 설정하지 않으면 항상 모의 주문(dry-run)만 수행 (기본 안전값: true)

주의: 아래 BASE_URL / 엔드포인트 경로는 https://developers.tossinvest.com/docs
공식 문서가 로그인 보호되어 있어 이 세션에서 직접 확인하지 못했다.
실제 연동 전 반드시 개발자센터에서 정확한 경로·요청/응답 스키마를 확인하고
_ENDPOINTS 아래 값을 채워넣을 것 (TODO 표시된 부분).
"""

import os
import time
import requests

BASE_URL = "https://open-api.tossinvest.com"  # TODO: 공식 문서에서 정확한 base URL 확인

TOSS_CLIENT_ID     = os.environ.get("TOSS_CLIENT_ID", "")
TOSS_CLIENT_SECRET = os.environ.get("TOSS_CLIENT_SECRET", "")
TOSS_ACCOUNT_ID    = os.environ.get("TOSS_ACCOUNT_ID", "")
TOSS_DRY_RUN       = os.environ.get("TOSS_DRY_RUN", "true").lower() != "false"

# TODO: 개발자센터에서 확인 후 정확한 경로로 교체
_ENDPOINTS = {
    "token":         "/oauth2/token",          # TODO 확인
    "hourly_candle": "/v1/market/candles",      # TODO 확인 (interval=60 등 파라미터 필요할 수 있음)
    "order_create":  "/v1/orders",              # TODO 확인
}

_TOKEN_CACHE: dict = {"token": None, "expires": 0.0}
_DIAG: dict = {"token_ok": None, "token_msg": ""}


def _get_token() -> str:
    """OAuth2 client_credentials 토큰 발급 (캐시, 만료 60초 전 갱신)"""
    cache = _TOKEN_CACHE
    if cache["token"] and time.time() < cache["expires"]:
        return cache["token"]

    if not TOSS_CLIENT_ID or not TOSS_CLIENT_SECRET:
        _DIAG["token_ok"] = False
        _DIAG["token_msg"] = "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 미설정 (환경변수 확인)"
        return ""

    try:
        r = requests.post(
            f"{BASE_URL}{_ENDPOINTS['token']}",
            data={
                "grant_type":    "client_credentials",
                "client_id":     TOSS_CLIENT_ID,
                "client_secret": TOSS_CLIENT_SECRET,
            },
            timeout=10,
        )
        data = r.json()
        token = data.get("access_token", "")
        if token:
            cache["token"]   = token
            cache["expires"] = time.time() + int(data.get("expires_in", 3600)) - 60
            _DIAG["token_ok"]  = True
            _DIAG["token_msg"] = "발급 성공"
        else:
            _DIAG["token_ok"]  = False
            _DIAG["token_msg"] = f"HTTP {r.status_code} / {data}"
        return token
    except Exception as e:
        _DIAG["token_ok"]  = False
        _DIAG["token_msg"] = str(e)[:120]
        return ""


def _auth_headers() -> dict:
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    if TOSS_ACCOUNT_ID:
        headers["X-Tossinvest-Account"] = TOSS_ACCOUNT_ID
    return headers


def diag() -> dict:
    """/test 등에서 연동 상태 확인용"""
    configured = bool(TOSS_CLIENT_ID and TOSS_CLIENT_SECRET)
    if configured:
        _get_token()
    return {
        "configured": configured,
        "account_set": bool(TOSS_ACCOUNT_ID),
        "dry_run": TOSS_DRY_RUN,
        **_DIAG,
    }


def get_last_closed_hourly_close(symbol: str) -> dict:
    """
    가장 최근에 '마감된' 1시간봉 종가를 반환.
    반환: {"close": float, "time": str} 또는 실패 시 {}

    TODO: _ENDPOINTS["hourly_candle"] 경로/파라미터(interval, count 등)를
    공식 문서 기준으로 확정할 것. 아래는 흔한 캔들 API 형태를 가정한 틀.
    """
    if not TOSS_CLIENT_ID or not TOSS_CLIENT_SECRET:
        print("[toss] TOSS_CLIENT_ID/SECRET 미설정 — 1시간봉 조회 불가")
        return {}
    try:
        r = requests.get(
            f"{BASE_URL}{_ENDPOINTS['hourly_candle']}",
            headers=_auth_headers(),
            params={"symbol": symbol, "interval": "60", "count": 2},  # TODO 파라미터명 확인
            timeout=10,
        )
        data = r.json()
        candles = data.get("candles") or data.get("data") or []
        if len(candles) < 2:
            return {}
        # 마지막 캔들은 진행 중일 수 있으므로 그 이전(=마감된) 캔들 사용
        closed = candles[-2]
        return {
            "close": float(closed.get("close") or closed.get("closePrice")),
            "time":  str(closed.get("time") or closed.get("timestamp") or ""),
        }
    except Exception as e:
        print(f"[toss] {symbol} 1시간봉 조회 실패 — {e}")
        return {}


def place_market_sell_order(symbol: str, qty: float, dry_run: bool = None) -> dict:
    """
    시장가 매도 주문 생성.
    dry_run=None이면 TOSS_DRY_RUN 환경변수 기본값 사용 (기본 True = 실제 주문 안 나감).

    TODO: _ENDPOINTS["order_create"] 요청 바디 스키마를 공식 문서 기준으로 확정할 것.
    """
    if dry_run is None:
        dry_run = TOSS_DRY_RUN

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "message": f"[모의 주문] {symbol} {qty}주 시장가 매도 — 실제 주문 미실행 (TOSS_DRY_RUN=true)",
        }

    if not TOSS_ACCOUNT_ID:
        return {"ok": False, "message": "TOSS_ACCOUNT_ID 미설정 — 환경변수 확인"}

    try:
        r = requests.post(
            f"{BASE_URL}{_ENDPOINTS['order_create']}",
            headers=_auth_headers(),
            json={
                "symbol":    symbol,
                "side":      "SELL",
                "orderType": "MARKET",
                "quantity":  qty,
            },  # TODO 요청 바디 키 이름 확인
            timeout=10,
        )
        data = r.json()
        if r.status_code in (200, 201):
            return {"ok": True, "dry_run": False, "raw": data}
        return {"ok": False, "message": f"HTTP {r.status_code} / {data}"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}
