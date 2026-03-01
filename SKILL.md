---
name: weather-trading
description: >
  Daily weather market trading on Kalshi. Use this skill whenever clawdbot needs to
  evaluate, analyze, or trade any Kalshi weather market including daily high temperature,
  daily low temperature, precipitation, snowfall, or any climate-related contract.
  Trigger on ANY mention of weather trading, temperature markets, weather betting,
  Kalshi weather, NWS forecast, daily high, daily low, precipitation markets, weather
  edge, weather models, or temperature brackets. Also trigger when asked about weather
  forecasts in the context of trading or when comparing NWS data to Kalshi prices.
  clawdbot trades daily temperature markets ONLY. No monthly or seasonal climate markets.
---

# Weather Trading — clawdbot Knowledge Base

This skill contains everything clawdbot needs to trade daily weather markets on Kalshi
profitably. The edge comes from comparing professional weather forecasts and raw NWS
model data against Kalshi prices set by casual traders who are essentially guessing.

**Before evaluating any weather market, read this file and the references completely.**

---

## 1. WHY WEATHER MARKETS ARE PROFITABLE

Most Kalshi weather traders are casual participants who glance at their phone's weather
app and buy the bracket that matches. They don't check multiple forecast models, don't
understand the specific NWS station that determines settlement, and don't track
intraday temperature trends.

clawdbot's edge comes from:
- Pulling the actual NWS hourly forecast for the exact settlement station
- Comparing multiple weather models (GFS, ECMWF/Euro, NAM, HRRR) for divergence
- Understanding microclimates: airport stations vs. city center vs. park readings
- Tracking intraday observations to detect when temps are running hot/cold vs. forecast
- Exploiting the 10-15¢ mispricings that exist when models disagree with consensus

**Key advantage over sports betting:** There is no "sharp book" in weather. The NWS
forecast IS the sharp line, and it's free. Kalshi traders routinely misprice by 10¢+
relative to what the NWS is saying.

---

## 2. KALSHI WEATHER MARKET STRUCTURE

### Available Cities and Settlement Stations

| City | NWS Station | Station ID | Notes |
|------|------------|------------|-------|
| New York City | Central Park | KNYC | Urban heat island effects |
| Chicago | Midway Airport | KMDW | Lake effect in winter, NOT O'Hare |
| Miami | Miami International Airport | KMIA | Sea breeze impacts afternoon highs |
| Austin | Austin-Bergstrom Airport | KAUS | Can spike hot, airport is south of city |
| Los Angeles | Downtown LA (USC) | KCQT | Marine layer crucial factor |
| Philadelphia | Philadelphia Intl Airport | KPHL | Added more recently |
| Denver | Denver Intl Airport | KDEN | Altitude effects, chinook winds |

⚠️ **CRITICAL: Always confirm the exact station in the market rules.** The station
determines settlement. A 3°F difference between downtown and the airport station is
common and will determine whether you win or lose.

### Market Structure

- **6 brackets** per market, typically:
  - 2 edge brackets (everything below X°F, everything above Y°F)
  - 4 center brackets, each 2°F wide
- Center brackets are usually built around the forecast high
- Markets launch at **10 AM local time the day before**
- Settlement based on **NWS Daily Climate Report (CLI)** released the next morning

### Settlement Rules

- Source: Final NWS Daily Climate Report (CLI) for the specific station
- Time window: The CLI uses **Local Standard Time (LST)**, NOT daylight saving time
- During DST: The recording period runs **1:00 AM to 12:59 AM the next day** in LST
- This means a late-night temperature spike can count as the day's high during DST
- **Only the NWS CLI determines the outcome** — AccuWeather, Apple Weather, Google
  Weather, etc. are irrelevant for settlement

### Fee Structure

- Trading fee: ~1% per contract
- Settlement fee: ~10% of profit (only on winning contracts)
- Withdrawal fee: 2%
- Factor fees into edge calculations — you need at least 3-4¢ of raw edge to be
  profitable after fees

---

## 3. DATA SOURCES (Priority Order)

### Primary: NWS API (FREE, no key needed)

The NWS API is the single most important data source. It provides forecasts from the
same organization that produces the settlement data.

**Step 1: Get the grid coordinates for each station**

```
GET https://api.weather.gov/points/{latitude},{longitude}
```

Station coordinates:
- NYC (Central Park): 40.7829,-73.9654
- Chicago (Midway): 41.7868,-87.7522
- Miami (MIA): 25.7959,-80.2870
- Austin (AUS): 30.1975,-97.6664
- Los Angeles (USC): 34.0236,-118.2912
- Philadelphia (PHL): 39.8721,-75.2411
- Denver (DEN): 39.8561,-104.6737

The response contains `forecastHourly` and `forecastGridData` URLs.

**Step 2: Get the hourly forecast**

```
GET https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast/hourly
```

This returns hourly temperature forecasts for the next 7 days. The high for any day
is the maximum temperature across all hours in that day's recording window.

**Step 3: Get raw gridpoint data (more granular)**

```
GET https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}
```

This returns the raw numerical forecast data including temperature, dewpoint, wind,
cloud cover, precipitation probability — all as time series. This is more detailed
than the hourly endpoint.

**Step 4: Get current observations (intraday tracking)**

```
GET https://api.weather.gov/stations/{stationId}/observations/latest
```

Use this throughout the day to see the current temperature at the exact settlement
station. If it's running hotter or colder than the forecast, that's actionable
information.

### Secondary: Weather Model Comparison

Check multiple models for convergence or divergence:

| Model | Update Frequency | Strengths |
|-------|-----------------|-----------|
| GFS (Global Forecast System) | Every 6 hours | Good baseline, widely available |
| ECMWF (Euro) | Every 12 hours | Most accurate 3-7 day, gold standard |
| NAM (North American Mesoscale) | Every 6 hours | Better for short-range (< 48hr) |
| HRRR (High-Res Rapid Refresh) | Every hour | Best for same-day, 15-hour window |

Access these via:
- **Ventusky.com** — visual comparison of all models on one map
- **Weather.gov gridpoint data** — already includes NWS blend of models
- **Open-Meteo API** (free) — programmatic access to GFS, ECMWF, and others

### Tertiary: Wethr.net

Wethr.net is purpose-built for Kalshi weather trading. It shows:
- Real-time METAR observations for settlement stations
- NWS CLI reports as soon as they're published
- Historical high/low data
- DSM (Daily Summary Message) data

Use this to cross-reference, especially for settlement verification.

---

## 4. THE WEATHER EDGE FRAMEWORK

### Step 1: Establish the NWS Forecast High

Pull the NWS hourly forecast for the target city and date. Find the maximum
temperature across all hours in the recording window. This is the "forecast high."

```
forecast_high = max(hourly_temps for hours in recording_window)
```

### Step 2: Map to Kalshi Brackets

Kalshi's 6 brackets will be centered around the expected high. Determine which
bracket the NWS forecast high falls into.

```
Example:
NWS forecast high: 67°F
Kalshi brackets:
  <62°F    → price: 3¢
  62-63°F  → price: 12¢
  64-65°F  → price: 22¢
  66-67°F  → price: 38¢  ← NWS forecast lands here
  68-69°F  → price: 20¢
  ≥70°F    → price: 5¢
```

### Step 3: Check Model Agreement

If all models agree with NWS (forecast high 66-68°F across GFS, Euro, NAM, HRRR):
- The market is likely fairly priced at 38¢ for that bracket
- Probably no tradeable edge
- Move to the next city

If models DISAGREE (NWS says 67°F, but HRRR says 70°F, Euro says 69°F):
- The market may be underpricing the higher brackets
- The ≥70°F bracket at 5¢ might be worth 15-20¢ if two models support it
- **This divergence IS the edge**

### Step 4: Calculate the Edge

For each bracket, estimate the true probability based on model consensus:

```
true_prob = weighted_model_consensus(bracket)

Suggested model weights:
  HRRR: 0.35 (same-day forecasts, highest weight for day-of trading)
  NWS blend: 0.30 (official forecast)
  Euro: 0.20 (most accurate medium-range)
  GFS: 0.15 (good baseline)

edge = true_prob - kalshi_price

# For next-day markets (launched day before):
  NWS blend: 0.35
  Euro: 0.30
  GFS: 0.20
  NAM: 0.15
```

### Step 5: Apply Minimum Edge Threshold

```
Minimum edge thresholds:
  Center brackets (most liquid): ≥ 8¢ edge
  Edge brackets (less liquid): ≥ 10¢ edge
  Intraday trades (obs running hot/cold): ≥ 6¢ edge
```

### Step 6: Size the Position

Use the same quarter-Kelly framework as NBA trading:

```
kelly_fraction = edge / (1 - kalshi_price)
bet_size = bankroll * kelly_fraction * 0.25  # quarter-Kelly

Max per trade: 3% of bankroll
Max daily across all weather markets: 10% of bankroll
```

---

## 5. HIGH-EDGE SITUATIONS (When to Be Aggressive)

### Model Divergence
When 2+ major models disagree with Kalshi pricing by 3°F+, edge brackets become
severely mispriced. A bracket priced at 3-5¢ might be worth 15-20¢.

### Microclimate Events
- **Sea breeze in Miami/LA**: Can cap afternoon highs 3-5°F below inland forecasts.
  If the market is priced for inland temps, the lower bracket is underpriced.
- **Lake effect in Chicago**: Winter lake-effect clouds or snow can suppress highs.
  In summer, lake breeze can cool Midway unexpectedly.
- **Urban heat island in NYC**: Central Park can be 2-3°F warmer than suburban
  stations. Traders using wrong-station data will misprice.
- **Chinook winds in Denver**: Can cause sudden 20-30°F temp spikes in winter.
  If a chinook is forecast by models but the market hasn't priced it, huge edge.

### DST Recording Window Traps
During daylight saving time, the NWS CLI records from 1 AM LST to 12:59 AM LST
the next day. This means:
- An early morning warm front arriving at 1 AM can spike the "high" for a day
  that then gets cold
- Late-night temperatures after midnight (in clock time) still count for the
  current day in LST
- Many traders don't understand this and misprice the edge brackets

### Observation Drift (Intraday)
If by 2 PM the observed temperature is already 2°F above the NWS forecast high
and there's still 3+ hours of heating:
- Higher brackets are underpriced
- The forecast high bracket may now be too low
- This is the fastest edge because you're trading on real data vs. stale prices

### Overnight Low Still Counts
A common trap: if the overnight low before the recording day is actually the
highest temperature in the window (e.g., warm front passage at 2 AM followed by
cold front), the "high" for settlement purposes might occur at night. Models
that show this pattern create an edge against traders who only look at afternoon
forecasts.

---

## 6. SITUATIONS TO AVOID

### ⛔ Don't Trade When Models Agree and Market Is Fairly Priced
If NWS, GFS, Euro, and HRRR all agree on the same 2°F range, and Kalshi has
that bracket at 35-45¢, there's no edge. Move on.

### ⛔ Don't Trade Precipitation Markets (Yet)
Precipitation is much harder to forecast accurately than temperature. Rain/no-rain
is binary but the amount thresholds are difficult. Skip these until you have a
proven track record on temperature.

### ⛔ Don't Chase Extreme Weather Events
Hurricanes, severe storms, and polar vortex events create massive uncertainty.
Models diverge wildly. The market knows it's uncertain and prices accordingly.
There's rarely an edge in chaos — the edge exists in normal, boring weather days
where models are accurate and traders are lazy.

### ⛔ Don't Trade Monthly/Seasonal Climate Markets
Same reasoning as NBA futures — too much uncertainty, capital locked too long,
impossible to validate edge. Stick to daily settlement.

### ⛔ Don't Rely on Phone Weather Apps
AccuWeather, Apple Weather, Google Weather DO NOT determine settlement.
Only the NWS CLI matters. Traders who use phone apps lose money when their app
says 72°F but the NWS station recorded 69°F.

---

## 7. OPERATIONAL CHECKLIST — DAILY WORKFLOW

### Morning (8-10 AM local time for each city)

1. Pull NWS hourly forecast for all active cities
2. Pull current observations from each settlement station
3. Check if any weather models have diverged significantly from NWS forecast
4. Pull current Kalshi prices for all daily temperature markets
5. Compare NWS forecast high to Kalshi bracket pricing
6. Identify any brackets where model consensus differs from market price by ≥ 8¢

### Midday (12-2 PM)

7. Pull latest observations — is the actual temperature running hot or cold?
8. If temp is tracking 2°F+ above/below forecast, check if Kalshi has repriced
9. If Kalshi hasn't adjusted, this is an intraday edge opportunity
10. Place limit orders on underpriced brackets
11. Check HRRR model update (runs hourly) for afternoon temperature trends

### Afternoon (3-5 PM)

12. Pull latest observations again
13. If the high has likely already occurred (temps declining), the winning bracket
    may now be identifiable with high confidence
14. If a bracket is certain to win and priced below 90¢, buy it (guaranteed profit)
15. If still uncertain, hold existing positions

### Evening

16. Markets close. Wait for settlement.

### Next Morning

17. Check NWS CLI report for each city
18. Verify settlement matches expectations
19. Log results: bracket traded, entry price, true outcome, P&L
20. Update any model weight adjustments based on which models were most accurate

---

## 8. RECORD-KEEPING

clawdbot must log for every weather trade:

```json
{
  "timestamp": "2026-03-01T14:30:00Z",
  "city": "NYC",
  "station": "KNYC",
  "market_date": "2026-03-01",
  "bracket": "66-67°F",
  "side": "YES",
  "entry_price": 0.28,
  "contracts": 10,
  "model_forecast_high": 67,
  "nws_forecast_high": 67,
  "model_agreement": "3/4 models agree (HRRR says 69)",
  "edge": 0.10,
  "edge_source": "NWS + 3 models support 66-67 bracket, market underpriced",
  "actual_high": null,
  "result": null,
  "pnl": null,
  "notes": "HRRR dissenting at 69°F but isolated, went with consensus"
}
```

Track model accuracy over time:
- Which model was closest to the actual CLI high for each city?
- Adjust model weights monthly based on performance
- If HRRR is consistently beating Euro for same-day trades, increase its weight

---

## 9. BANKROLL MANAGEMENT (Weather-Specific)

Weather trades should share the same bankroll as NBA trades. Combined rules:

- Max per weather trade: 3% of bankroll
- Max daily weather exposure: 10% of bankroll
- Max total daily exposure (weather + NBA combined): 15% of bankroll
- Never have more than 2 positions in the same city on the same day
- Prefer spreading across multiple cities over concentrating in one

### Correlation Warning

Weather across nearby cities can be correlated (e.g., a cold front hitting both
NYC and Philadelphia on the same day). If you take positions in both cities on
the same bracket direction, treat them as partially correlated and reduce size.

---

## 10. FINAL PRINCIPLES

1. **The NWS forecast is your sharp line.** Respect it. Your edge comes from
   finding where Kalshi traders ignore it, not from outsmarting the NWS.
2. **Model divergence = opportunity.** When models disagree and the market picks
   one side, the other side is often underpriced.
3. **Check the actual station.** Every loss from using the wrong station is a
   completely avoidable mistake.
4. **Intraday observations are gold.** Real data beats forecasts. If it's 3 PM
   and already hotter than the forecast high, act.
5. **Boring weather = best weather for trading.** Clear skies, light winds, no
   fronts = models are most accurate = market mispricings are most exploitable.
6. **The DST recording window trips up most traders.** Understand it, exploit it.
7. **Fees eat thin edges.** After the ~10% settlement fee and trading fees, you
   need raw edge of at least 6-8¢ to be worth the trade.
