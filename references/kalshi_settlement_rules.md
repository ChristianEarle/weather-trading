# Kalshi Temperature Contract Settlement Rules

## Settlement Source

Kalshi daily high temperature contracts settle **exclusively** on the NWS Daily Climate Report (CLI) for the designated station. The CLI is the official daily weather summary published by each NWS Weather Forecast Office.

## Station-to-City Mapping

| City | CLI Station | ICAO | What It Reports |
|------|------------|------|-----------------|
| New York | Central Park | KNYC | NYC Central Park Observatory |
| Chicago | Midway Airport | KMDW | Chicago Midway ASOS |
| Miami | Miami Intl Airport | KMIA | Miami International ASOS |
| Austin | Bergstrom Intl | KAUS | Austin-Bergstrom ASOS |
| Los Angeles | LAX Airport | KLAX | Los Angeles International ASOS |
| Denver | Denver Intl | KDEN | Denver International ASOS |
| Atlanta | Hartsfield Airport | KATL | Atlanta Hartsfield ASOS |
| Phoenix | Sky Harbor | KPHX | Phoenix Sky Harbor ASOS |

## Settlement Timeline

1. Temperature date occurs (e.g., March 2, 2026)
2. CLI published by NWS the following morning (usually by 8-9 AM local)
3. Kalshi reads CLI at **10:00 AM ET**
4. If CLI high is inconsistent with METAR observations, or if final CLI high is lower than preliminary: settlement delayed to **12:00 PM ET**
5. Contract settles: bracket containing the CLI high → YES at $1.00, all others → $0.00

## Local Standard Time (Critical)

NWS CLIs report in **Local Standard Time year-round**, regardless of whether Daylight Saving Time is in effect. This means:

- **During Standard Time** (Nov-Mar): Midnight-to-midnight measurement window matches civil time
- **During Daylight Saving** (Mar-Nov): The measurement window effectively runs from **1:00 AM local daylight time** to **12:59 AM the next day** in daylight time

This creates an exploitable edge: a late-night temperature spike at 12:30 AM daylight time (which is 11:30 PM standard time) counts toward the **current** CLI day, not the next day. Most casual traders don't account for this.

## ASOS Temperature Measurement

ASOS (Automated Surface Observing System) stations measure temperature in **Celsius** and convert to **Fahrenheit** for CLI reporting. The conversion creates rounding artifacts:

```
Measured: 16.5°C → 61.7°F → rounds to 62°F
Measured: 16.4°C → 61.52°F → rounds to 62°F  
Measured: 16.1°C → 60.98°F → rounds to 61°F
```

At 0.5°C boundaries, a tiny measurement difference can shift the reported Fahrenheit value by 1°F. On bracket boundary temperatures, this 1°F shift can move 20%+ of probability between adjacent contracts.

Key Celsius thresholds that create Fahrenheit rounding cliffs:

| °C | °F (exact) | Rounds to | Watch for |
|----|-----------|-----------|-----------|
| 15.0 | 59.0 | 59 | Clean boundary |
| 15.5 | 59.9 | 60 | 0.1°F from flip |
| 16.0 | 60.8 | 61 | |
| 16.5 | 61.7 | 62 | |
| 20.0 | 68.0 | 68 | Clean boundary |
| 25.0 | 77.0 | 77 | Clean boundary |
| 30.0 | 86.0 | 86 | Clean boundary |
| 32.0 | 89.6 | 90 | 0.4°F from flip |

## Bracket Structure

Kalshi temperature markets use **6 mutually exclusive brackets**, typically:
- 2 open-ended edge brackets (low: "below X°F", high: "above Y°F")
- 4 middle brackets, each 2°F wide, centered around the forecast

Example for NYC with forecast of 63°F:
```
Bracket 1: Below 58°F        (low edge)
Bracket 2: 58°F to 59°F      (2°F wide)
Bracket 3: 60°F to 61°F      (2°F wide)  
Bracket 4: 62°F to 63°F      (2°F wide)
Bracket 5: 64°F to 65°F      (2°F wide)
Bracket 6: 66°F or above     (high edge)
```

Exactly one bracket settles YES at $1.00. All others settle at $0.00.

## Fee Structure

| Type | Formula | Max at 50¢ |
|------|---------|-----------|
| Taker | `round_up(0.07 × C × P × (1-P))` | ~$0.02 |
| Maker | `round_up(0.0175 × C × P × (1-P))` | ~$0.005 |

Maker fees are **4× lower**. Always use limit orders.
No settlement fees.

## API for Market Discovery

```
Base: https://api.elections.kalshi.com/trade-api/v2

# Find today's temperature markets
GET /markets?series_ticker=KXHIGHNY&status=open

# Get orderbook
GET /markets/{ticker}/orderbook?depth=10

# Place limit order (maker)
POST /portfolio/orders
{
  "ticker": "KXHIGHNY-26MAR03-B62",
  "action": "buy",
  "side": "yes",  
  "count": 1,
  "type": "limit",
  "yes_price": 50
}
```

Authentication: RSA-PSS signed requests. Tokens expire every 30 minutes.
Demo environment: `demo-api.kalshi.co`
