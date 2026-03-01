# NWS API Reference — Weather Trading Data Pipeline

## Overview

The National Weather Service API (api.weather.gov) is FREE, requires NO API key, and
provides the exact forecast data from the same organization that determines Kalshi
weather market settlement. This is the most important data source for weather trading.

**Base URL:** `https://api.weather.gov`

**Required Headers:**
```
User-Agent: clawdbot-weather-trading (your@email.com)
Accept: application/geo+json
```

The NWS requires a User-Agent header identifying your application. Without it,
requests may be blocked.

---

## Station Setup (One-Time)

For each Kalshi city, get the grid coordinates:

### New York City (Central Park)

```
GET https://api.weather.gov/points/40.7829,-73.9654
```

Response contains:
```json
{
  "properties": {
    "gridId": "OKX",
    "gridX": 33,
    "gridY": 37,
    "forecast": "https://api.weather.gov/gridpoints/OKX/33,37/forecast",
    "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,37/forecast/hourly",
    "forecastGridData": "https://api.weather.gov/gridpoints/OKX/33,37",
    "observationStations": "https://api.weather.gov/gridpoints/OKX/33,37/stations"
  }
}
```

### All Cities — Grid Coordinates

| City | Lat,Lon | Office | Grid X,Y | Station ID |
|------|---------|--------|----------|------------|
| NYC | 40.7829,-73.9654 | OKX | 33,37 | KNYC |
| Chicago | 41.7868,-87.7522 | LOT | 75,72 | KMDW |
| Miami | 25.7959,-80.2870 | MFL | 76,50 | KMIA |
| Austin | 30.1975,-97.6664 | EWX | 156,91 | KAUS |
| Los Angeles | 34.0236,-118.2912 | LOX | 154,44 | KCQT |
| Philadelphia | 39.8721,-75.2411 | PHI | 49,74 | KPHL |
| Denver | 39.8561,-104.6737 | BOU | 62,60 | KDEN |

**NOTE:** Grid coordinates should be verified on first use. Call the /points endpoint
and cache the results. They don't change.

---

## Hourly Forecast

The most useful endpoint for daily high temperature prediction.

```
GET https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast/hourly
```

**Example for NYC:**
```
GET https://api.weather.gov/gridpoints/OKX/33,37/forecast/hourly
```

**Response format (simplified):**
```json
{
  "properties": {
    "periods": [
      {
        "number": 1,
        "startTime": "2026-03-01T14:00:00-05:00",
        "endTime": "2026-03-01T15:00:00-05:00",
        "temperature": 67,
        "temperatureUnit": "F",
        "windSpeed": "10 mph",
        "windDirection": "SW",
        "shortForecast": "Partly Cloudy",
        "probabilityOfPrecipitation": {
          "value": 10
        },
        "relativeHumidity": {
          "value": 45
        }
      }
    ]
  }
}
```

**To find the forecast high:**
```python
def get_forecast_high(periods, target_date):
    """
    Extract the maximum temperature for a target date.
    
    IMPORTANT: During DST, the NWS CLI recording window is
    1:00 AM LST to 12:59 AM LST the next day.
    During standard time: midnight to midnight.
    
    For simplicity, scan all hours of the target date.
    """
    max_temp = None
    for period in periods:
        period_date = parse_date(period["startTime"])
        if period_date == target_date:
            temp = period["temperature"]
            if max_temp is None or temp > max_temp:
                max_temp = temp
    return max_temp
```

---

## Raw Gridpoint Data

More detailed than hourly forecast. Returns all forecast parameters as time series.

```
GET https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}
```

**Key properties in response:**
```json
{
  "properties": {
    "temperature": {
      "values": [
        {
          "validTime": "2026-03-01T14:00:00+00:00/PT1H",
          "value": 19.4
        }
      ]
    },
    "maxTemperature": {
      "values": [
        {
          "validTime": "2026-03-01T07:00:00+00:00/PT13H",
          "value": 20.0
        }
      ]
    }
  }
}
```

**⚠️ Temperatures in gridpoint data are in CELSIUS.** Convert to Fahrenheit:
```
°F = (°C × 9/5) + 32
```

The `maxTemperature` field directly gives the forecast daily high, but verify
against the hourly data for consistency.

---

## Current Observations

Real-time temperature at the exact settlement station. Critical for intraday trading.

```
GET https://api.weather.gov/stations/{stationId}/observations/latest
```

**Example for NYC:**
```
GET https://api.weather.gov/stations/KNYC/observations/latest
```

**Key fields in response:**
```json
{
  "properties": {
    "timestamp": "2026-03-01T19:53:00+00:00",
    "temperature": {
      "value": 18.9,
      "unitCode": "wmoUnit:degC"
    },
    "windSpeed": {
      "value": 4.1,
      "unitCode": "wmoUnit:km_h-1"
    },
    "textDescription": "Partly Cloudy"
  }
}
```

**⚠️ Observation temperatures are also in CELSIUS.** Always convert.

### Polling Strategy

- Morning (pre-market): Poll once to get overnight conditions
- Midday: Poll every 30 minutes to track temperature trend
- Afternoon (2-5 PM): Poll every 15 minutes — this is when the high typically occurs
- Don't poll more than once per minute — NWS may throttle

### Observation History (Full Day)

```
GET https://api.weather.gov/stations/{stationId}/observations?start={ISO_datetime}&end={ISO_datetime}
```

Use this to get all observations for the day and find the running maximum.

---

## Open-Meteo API (FREE, Supplementary Models)

For accessing weather models that the NWS API doesn't directly expose.

**Base URL:** `https://api.open-meteo.com/v1/forecast`

```
GET https://api.open-meteo.com/v1/forecast?latitude=40.7829&longitude=-73.9654&hourly=temperature_2m&models=gfs_seamless,ecmwf_ifs025&temperature_unit=fahrenheit&timezone=America/New_York
```

**Available models:**
- `gfs_seamless` — GFS (NOAA)
- `ecmwf_ifs025` — ECMWF/Euro (highest accuracy for 3-7 day)
- `gfs_hrrr` — HRRR (best for same-day, hourly updates)
- `icon_seamless` — DWD ICON (German model, good for verification)

**Response:**
```json
{
  "hourly": {
    "time": ["2026-03-01T00:00", "2026-03-01T01:00", ...],
    "temperature_2m": [45.2, 44.8, ...]
  }
}
```

Use Open-Meteo to:
1. Pull GFS and ECMWF forecasts for the target city/date
2. Compare their forecast highs to the NWS forecast
3. If they diverge by 3°F+, that's a signal to look for edge

---

## Kalshi API — Weather Markets

Weather markets use the same Kalshi API as NBA markets. See the NBA skill's
`references/kalshi-mechanics.md` for general Kalshi API documentation.

### Finding Weather Markets

```
GET https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY
```

Common weather series tickers:
- `KXHIGHNY` — NYC daily high temperature
- `KXHIGHCHI` — Chicago daily high temperature  
- `KXHIGHMI` — Miami daily high temperature
- `KXHIGHAUS` — Austin daily high temperature
- `KXHIGHLA` — Los Angeles daily high temperature

**NOTE:** Ticker formats may vary. Use the Kalshi events endpoint to discover
current weather markets:

```
GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXHIGH
```

### Matching Brackets to Temperature Ranges

Each market has multiple contracts, one per bracket. The contract ticker includes
the temperature range. Parse the market title/description to determine the range
each contract covers.

---

## Putting It All Together — Daily Pipeline

```
MORNING PIPELINE (run at 8 AM local for each city):

1. For each city in [NYC, Chicago, Miami, Austin, LA, Philly, Denver]:
   
   a. GET NWS hourly forecast → extract forecast high
   b. GET Open-Meteo GFS forecast → extract GFS high
   c. GET Open-Meteo ECMWF forecast → extract Euro high
   d. GET Kalshi markets for that city → get bracket prices
   
   e. model_consensus = weighted_average(
        nws_high * 0.30,
        gfs_high * 0.20,
        ecmwf_high * 0.30,
        hrrr_high * 0.20  # if available (same-day only)
      )
   
   f. For each bracket:
        true_prob = estimate_probability(model_consensus, bracket_range)
        edge = true_prob - kalshi_bracket_price
        
        if edge >= 0.08:
            FLAG for trading
   
   g. Log all data for later analysis

2. For flagged trades:
   - Validate: Do at least 2 models support this bracket?
   - Size: quarter-Kelly, max 3% bankroll
   - Place limit orders (never market orders)

INTRADAY UPDATE (run at 12 PM and 3 PM):

3. For each city:
   a. GET current observation from settlement station
   b. Compare observed temp to forecast high
   c. If observed is already above forecast high by 2°F+:
      - Higher brackets are now underpriced
      - Check if Kalshi has repriced
      - If not, buy the higher bracket
   d. If observed is tracking 2°F+ below forecast:
      - Lower brackets may be underpriced
      - Check and act accordingly
```

---

## Rate Limits and Best Practices

### NWS API
- No hard rate limit published, but be respectful
- Cache grid coordinates (they never change)
- Don't poll observations more than once per minute
- Include User-Agent header always
- If you get 503 errors, back off and retry after 30 seconds

### Open-Meteo
- Free tier: 10,000 requests per day
- More than enough for weather trading (you need ~50 calls/day max)
- No API key required for basic access

### Kalshi API
- Same rate limits as NBA trading
- See `nba-sharp-betting/references/kalshi-mechanics.md` for details
