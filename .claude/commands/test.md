Run a quick diagnostic test of the screening pipeline. Execute this bash command:

```bash
cd ~/TopGainScreening && python3 -c "
import yfinance as yf

# 1. Yahoo Finance 연결 테스트
print('=== 1. Yahoo Finance 연결 테스트 ===')
try:
    result = yf.screen('day_gainers', count=50)
    quotes = result.get('quotes', [])
    print(f'day_gainers 수집: {len(quotes)}개')
    for q in quotes[:5]:
        print(f'  {q.get(\"symbol\")} {q.get(\"regularMarketChangePercent\",0):.1f}%')
except Exception as e:
    print(f'yf.screen 실패: {e}')

# 2. 1차 필터 테스트
print()
print('=== 2. 1차 필터 (10%+ 조건) ===')
try:
    p1 = [q for q in quotes
          if q.get('regularMarketChangePercent', 0) >= 10
          and q.get('regularMarketPrice', 0) >= 10
          and 0 < (q.get('marketCap') or 0) < 50_000_000_000]
    print(f'10%+ 통과: {len(p1)}개')
    print(f'5%+ 통과: {len([q for q in quotes if q.get(\"regularMarketChangePercent\",0) >= 5])}개')
    print(f'3%+ 통과: {len([q for q in quotes if q.get(\"regularMarketChangePercent\",0) >= 3])}개')
except Exception as e:
    print(f'필터 오류: {e}')

# 3. SPY 시장 데이터 테스트
print()
print('=== 3. 시장 데이터 (SPY) ===')
try:
    h = yf.Ticker('SPY').history(period='5d')
    print(f'SPY 데이터: {len(h)}일치')
    if len(h) >= 1:
        print(f'  최근 종가: {h[\"Close\"].iloc[-1]:.2f}')
except Exception as e:
    print(f'SPY 오류: {e}')

print()
print('=== 테스트 완료 ===')
"
```

Report the full output to the user so they can see exactly what's working and what's failing.
