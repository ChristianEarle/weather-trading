---
name: weather-trading-v2
description: Advanced weather temperature trading skill for Kalshi prediction markets. Use this skill whenever the user wants to trade weather markets, analyze temperature forecasts for Kalshi, find edge on daily high temperature contracts, set up weather trading automation, check weather trading performance, or retrain calibration models. Also trigger when the user mentions Kalshi temperature, weather betting, NWS forecasts for trading, daily high temp markets, or wants to compare weather model forecasts against Kalshi prices. This replaces the v1 NWS-only weather skill entirely.
---

# Weather Trading Skill v2.1 — NWS-Anchored Multi-Model Ensemble

Trade daily high temperature bracket contracts on Kalshi using a multi-model ensemble approach anchored to the NWS settlement source, with adaptive learning from trade history.

## Rule #1: NWS Is the Settlement Source

Kalshi temperature contracts settle **exclusively** on the NWS Daily Climate Report (CLI). Not METAR. Not AccuWeather. Not any model output. The NWS forecast predicts the CLI value directly, so it gets privileged weighting. Every other model (GFS, ECMWF, ICON) adds value for uncertainty estimation but must be subordinate to NWS.

When NWS disagrees with the ensemble by >3°F, elevate NWS weight from 35% to 50%. If NWS is unavailable, halve position sizes — you're trading blind on the settlement source.

## Architecture

```
NWS Forecast (PRIMARY) ──┐
                          ├── NWS-Anchored Blend ──→ NGR Calibration ──→ P(bracket) ──→ Edge Detection ──→ Trade
Open-Meteo Ensemble ──────┘       ↑                                         ↑                   │
  (GFS 31 + ECMWF 51 members)    │                                         │                   ▼
                                  │                                    EWMA Bias            Quarter-Kelly
                          Adaptive Learning ◄── Settlement Recording ◄── Correction         + FLB Adjust
                          (per-model CLI accuracy tracking)
```

## How to Use This Skill

The skill's Python module lives at `scripts/weather_trading_skill.py`. Read it to understand the full implementation. Here is how to invoke it:

### Quick Start — Analyze a City
```python
from weather_trading_skill import WeatherTradingSkill

skill = WeatherTradingSkill(bankroll=75.0)

result = skill.analyze_city(
    city_key="nyc",
    target_date="2026-03-02",
    bracket_thresholds=[(60, 62), (62, 64), (64, 66)],
    market_prices={
        "KXHIGHNY-26MAR02-B61": 0.25,
        "KXHIGHNY-26MAR02-B63": 0.35,
        "KXHIGHNY-26MAR02-B65": 0.20,
    }
)

# Trade signals are in result["signals"]
for signal in result["signals"]:
    print(f"{signal['side']} {signal['ticker']} @ {signal['entry_price']}")
    print(f"  Edge: {signal['effective_edge']:.1%}")
    print(f"  NWS forecast: {result['forecast']['nws_forecast']}°F")
```

### After Settlement — Record and Learn
```python
skill.record_settlement(
    trade=signal,
    actual_temperature=63.0,   # CLI-reported value
    settled_yes=True,
    model_forecasts={          # Track each model vs CLI
        "nws": 63.0,
        "gfs_seamless": 62.5,
        "ecmwf_ifs025": 64.1,
    }
)
```

### Weekly — Retrain Calibration
```python
skill.retrain_calibration("nyc")
```

### Anytime — Check Performance
```python
print(skill.get_status_report())
```

## Data Sources

### NWS (PRIMARY — Settlement Source)
- `api.weather.gov` hourly forecast → predicts CLI directly
- `forecastGridData` → NWS's own uncertainty ranges
- METAR via `aviationweather.gov` → real-time intraday monitoring
- **Free, no API key required**

### Open-Meteo (Ensemble & Uncertainty)
- Deterministic: HRRR (3km), GFS (13km), ECMWF (9km), ICON
- Ensemble: GFS 31-member + ECMWF 51-member = 82 total members
- Previous Runs API: historical forecast-vs-actual for calibration training
- **Free, no API key required** (10K calls/day)

### NOAA NCEI (Historical Calibration)
- GHCN-Daily TMAX/TMIN observations for long-term bias analysis
- **Free, requires token** (set `NOAA_TOKEN` env var)

## Core Math

### NWS-Anchored Ensemble Mean
```
Normal:          anchored_mean = 0.35 × NWS + 0.65 × raw_ensemble_mean
High disagreement: anchored_mean = 0.50 × NWS + 0.50 × raw_ensemble_mean  (when gap > 3°F)
NWS unavailable: anchored_mean = raw_ensemble_mean  (halve position sizes!)
```

### NGR Calibration (EMOS)
```
Y ~ N(μ_cal, σ_cal²)
μ_cal = α + β × anchored_mean
σ_cal² = γ + δ × ensemble_std²
P(high > threshold) = 1 - Φ((threshold - μ_cal) / σ_cal)
```
Parameters (α, β, γ, δ) are fit by minimizing CRPS over a rolling 40-day window.

### Favourite-Longshot Bias
Contracts under 15¢ are systematically overpriced on Kalshi (confirmed across 300K+ contracts). Require extra 5% edge to buy cheap YES contracts. Prefer selling overpriced longshots (NO side).

### Quarter-Kelly Position Sizing
```
kelly_fraction = max(0, (p × b - (1 - p)) / b) × 0.25
position = min(kelly_fraction × bankroll, 0.10 × bankroll)
```

## Settlement Mechanics (Critical Knowledge)

- CLI published morning after temperature date
- Kalshi reads CLI at **10:00 AM ET**; delayed to 12:00 PM if inconsistent with METAR
- CLI uses **Local Standard Time year-round** (not DST!)
- During DST: measurement window = 1:00 AM daylight → 12:59 AM next day
- ASOS measures in Celsius → F conversion creates rounding cliffs at 0.5°C boundaries
- Late-night temperature spikes can count toward "previous" day during DST months

## Available Cities

| City | ICAO | Station | Kalshi Series |
|------|------|---------|---------------|
| New York | KNYC | Central Park | KXHIGHNY |
| Chicago | KMDW | Midway Airport | KXHIGHCH |
| Miami | KMIA | Miami Intl | KXHIGHMI |
| Austin | KAUS | Bergstrom Intl | KXHIGHAU |
| Los Angeles | KLAX | LAX Airport | KXHIGHLAX |
| Denver | KDEN | Denver Intl | KXHIGHDEN |
| Atlanta | KATL | Hartsfield | KXHIGHATL |
| Phoenix | KPHX | Sky Harbor | KXHIGHPHX |

## Configurable Parameters

Edit at the top of `scripts/weather_trading_skill.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_EDGE_PERCENT` | 0.08 | Minimum 8% edge to trade |
| `KELLY_FRACTION` | 0.25 | Quarter-Kelly sizing |
| `MAX_POSITION_PCT` | 0.10 | Max 10% bankroll per trade |
| `FLB_LONGSHOT_PENALTY` | 0.05 | Extra edge for <15¢ contracts |
| `NWS_ANCHOR_BLEND` | 0.35 | Normal NWS weight in blend |
| `NWS_DISAGREE_THRESHOLD` | 3.0 | °F gap for elevated NWS weight |
| `NWS_DISAGREE_BLEND` | 0.50 | Elevated NWS weight |
| `NGR_TRAINING_DAYS` | 40 | Rolling calibration window |
| `EWMA_BETA` | 0.92 | Bias tracker decay rate |

## Trading Rules

### When to Be Aggressive (lower edge to 6%)
- NWS and ensemble agree within 1°F
- HRRR updated within last 2 hours
- Target within 24 hours

### When to Be Conservative (raise edge to 12%)
- Frontal passage expected
- Model spread >4°F
- NWS disagrees with ensemble by >5°F

### When to NOT Trade
- NWS unavailable AND ensemble spread >5°F
- Severe weather watch active (atmospheric rivers, derechos)
- Rolling Brier score (last 50) exceeds 0.25 → retrain first
- Cumulative P&L below -20% of starting bankroll → stop and alert user

## Adaptive Learning System

The skill automatically maintains these files (created on first run):

| File | Purpose |
|------|---------|
| `trade_journal.jsonl` | Every trade with full context, model diagnostics, settlement outcome |
| `bias_tracker.json` | EWMA bias state by (city, season) and (city, season, model) |
| `performance_stats.json` | Rolling Brier scores, P&L, win rate by city and season |

After each settlement, the system:
1. Logs CLI temperature + each model's error vs CLI
2. Identifies which model was closest to the settlement value
3. Updates EWMA bias trackers (probability-level and temperature-level)
4. Recomputes rolling Brier score and triggers alerts if degrading

The per-model CLI accuracy tracking is the key learning signal — it tells you whether NWS, GFS, or ECMWF most reliably predicts the settlement value for each city/season.

## Dependencies

```bash
pip install requests numpy scipy
```

No paid API keys required. All weather data sources are free.
Optional: `NOAA_TOKEN` for historical calibration data (free at ncdc.noaa.gov/cdo-web/token).

## File Structure

```
weather-trading-v2/
├── SKILL.md                          # This file
├── scripts/
│   └── weather_trading_skill.py      # Complete Python module (all classes)
└── references/
    └── kalshi_settlement_rules.md    # Detailed CLI settlement reference
```
