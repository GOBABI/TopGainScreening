# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

US stock market top-gainers screening system. Each trading day it fetches the top-gaining stocks from Yahoo Finance, applies a two-pass technical filter, scores survivors, and delivers a Korean-language report via Telegram and GitHub Pages.

## Running the System

```bash
# Full screening pipeline (fetch → filter → score → HTML report → Telegram → GitHub Pages)
python3 screening.py

# Telegram bot (long-poll; runs continuously on Heroku as a worker)
python3 bot.py

# Regenerate HTML from existing screening_result.json + redeploy to Netlify
python3 refresh_report.py
```

### Slash commands (Claude Code)
- `/report` — runs `screening.py` and summarises results
- `/test` — quick connectivity diagnostic (Yahoo Finance + SPY data)

### Diagnostic test (manual)
```bash
python3 -c "
import yfinance as yf
result = yf.screen('day_gainers', count=50)
quotes = result.get('quotes', [])
print(f'Gainers: {len(quotes)}, 10%+: {len([q for q in quotes if (q.get(\"regularMarketChangePercent\") or 0) >= 10])}')
h = yf.Ticker('SPY').history(period='5d')
print(f'SPY last close: {h[\"Close\"].iloc[-1]:.2f}')
"
```

## Architecture

### Data flow (screening.py `main()`)
1. **Pull watchlist** from GitHub `data` branch (`github_pull_watchlist`)
2. **Fetch top gainers** via `yf.screen("day_gainers")` with a fallback to Yahoo Finance's screener REST endpoint
3. **Fetch market data** for 9 ETFs (SPY, QQQ, VIX, SMH, XLK, XLV, XLE, XLI, XLF)
4. **Two-pass screening** (`run_screening`):
   - Pass 1 (hard filter): change ≥10%, price ≥$10, volume ≥1.5× 3-month avg or ≥300k, market cap <$50B
   - Pass 2 (technical): above 200MA, RSI <80; then score each survivor
5. **Update watchlist** — tracks first/last seen, appearance count, re-entry detection across trading days
6. **Refresh TA** for watchlist tickers absent from today's results
7. **Dump JSON** → `screening_result.json`
8. **Build HTML** report (`html_report.py`) → `us_market_screening_latest.html`
9. **Send Telegram**: HTML-formatted card per stock, then a Korean narrative summary
10. **Push** watchlist + archive to GitHub `data` branch; deploy HTML to `gh-pages`

### Key modules

| File | Role |
|---|---|
| `screening.py` | Core engine — all fetching, TA calculation, scoring, watchlist logic, GitHub sync |
| `bot.py` | Telegram long-poll bot; dispatches `/report`, `/force`, `/pre`, `/test`, `/$TICKER` |
| `html_report.py` | Generates a self-contained React+Babel HTML report; also sends Telegram card messages |
| `refresh_report.py` | Rebuilds HTML from stored JSON and redeploys to Netlify (triggered by `/refresh` in bot) |

### Technical indicators (`screening.py`)
- **RSI** (14-period, `calc_rsi`)
- **ADX** (14-period EWM, `calc_adx`)
- **MACD** golden-cross signal (`calc_macd_signal`) — true only on the day EMA-12 crosses above EMA-26
- **Qullamaggie position** (`qullamaggie_position`): classifies the momentum stage as `a` (early surge / extended), `b` (preferred — pullback/tight consolidation near high), or `c` (general uptrend)
- **VCP (Volume Contraction Pattern)**: checks whether 20-day volume is decreasing across four 5-day windows
- **ADR** — 20-day average daily range %

### Scoring (`score_stock`) — max 9 points
| Condition | Points |
|---|---|
| ADX > 25 | 2 |
| RSI 40–75 | 2 |
| MACD bullish cross | 2 |
| 52-week high ≥ 90% | 1 |
| YTD ≥ 50% | 1 |
| VCP confirmed + Qullamaggie `b` | 2 |
| Tech/semi/defense/energy sector | 1 |

### Persistent state
- `watchlist.json` — cumulative ticker tracker; read/written both locally and on the GitHub `data` branch
- `archive.json` — list of dates for which a report has been completed; used to populate the date-selector in the HTML report
- `screening_result.json` — latest run output (gitignored, regenerated each run)

### Bot commands
| Command | Behaviour |
|---|---|
| `/report` or `/refresh` | Runs `screening.py` subprocess (blocked during market close unless `/force`) |
| `/force` | Runs screening regardless of market hours |
| `/pre` | Premarket gap scan (≥3% gap-up, market-cap top 10); uses `yf.screen("most_actives")` during regular hours, individual ticker lookup before open |
| `/test` | Diagnostic: Yahoo Finance connectivity + SPY data + market status |
| `/$TICKER` | Single-ticker checklist: 200MA, MA alignment, ADX, RSI, earnings date, volume |

**Auto-schedule** (runs in the `bot.py` poll loop):
- 16:05–16:10 ET weekdays → auto-triggers `/report`
- 09:00–09:05 ET weekdays → auto-triggers `/pre`

A 10-minute lock file (`.screening_lock`) prevents duplicate runs; a PID file (`.bot.pid`) enforces a single bot instance.

### Deployment
- **Heroku worker**: `Procfile` runs `python bot.py` (long-running worker dyno)
- **GitHub Pages** (`gh-pages` branch): `index.html` + `YYYY-MM-DD.html` uploaded via GitHub Contents API after each run
- **Netlify**: alternative/secondary host; deployed by `refresh_report.py` using a deploy-by-digest API call

### Git branches
| Branch | Content |
|---|---|
| `main` | Source code |
| `data` | `watchlist.json`, `archive.json` (data persistence between runs) |
| `gh-pages` | Generated HTML reports |

## Trading Strategy Context

`TRADING_RULES.md` documents the Qullamaggie LREP + Thales framework that this system implements. Key constraints reflected in the screener:
- Prefer **`b`-position** (1–3-month pullback then breakout) over `a` (extended rally)
- **VCP** (decreasing volume during base) is a bonus condition (+2 pts) when combined with `b`
- Scores below 4 are never presented as actionable; scores 7–9 with VCP get max position sizing
- The screener enforces hard stops: above 200MA, RSI <80, volume ≥1.5× avg

## Environment Variables

`GITHUB_TOKEN` must be set at runtime for watchlist sync and GitHub Pages deployment (`os.environ.get("GITHUB_TOKEN", "")`). Without it, GitHub sync silently skips. The Telegram bot token and Netlify token are currently hardcoded in the source files.
