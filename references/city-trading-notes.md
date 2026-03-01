# City-Specific Weather Trading Notes

Each Kalshi weather city has unique microclimates, seasonal patterns, and common
mispricings. This reference helps clawdbot understand city-specific factors that
create edge.

---

## New York City (KNYC — Central Park)

### Station Characteristics
- Central Park is an urban heat island — typically 2-3°F warmer than surrounding areas
- Sheltered from direct ocean influence by Manhattan's buildings
- Winter: can be 3-5°F warmer than JFK or LaGuardia stations
- Summer: concrete radiation keeps nighttime lows higher

### Common Edge Sources
- **Coastal vs. inland divergence**: When an onshore flow is forecast, many models
  overestimate cooling in Central Park because the park is buffered. The lower
  brackets get overpriced.
- **Spring/Fall transitions**: Sharp warm/cold fronts can cause 10°F swings mid-day.
  If a front passes at 3 PM, the high may already be locked in. Traders who see
  "colder afternoon" in forecasts may not realize the morning was warm enough.
- **Winter inversions**: Strong inversions can trap warm air. If the inversion is
  breaking down, models may underestimate the afternoon high.

### Seasonal Ranges
- Winter (Dec-Feb): Highs typically 35-45°F, brackets tight
- Spring (Mar-May): Highs 50-70°F, high variance = more edge
- Summer (Jun-Aug): Highs 80-90°F, urban heat makes extremes more likely
- Fall (Sep-Nov): Highs 55-75°F, frontal passages create mispricings

---

## Chicago (KMDW — Midway Airport)

### Station Characteristics
- **Midway, NOT O'Hare** — this is the #1 mistake traders make
- Midway is closer to the city center, typically 1-2°F warmer than O'Hare
- Lake Michigan has massive influence in spring/summer (lake breeze effect)
- In winter, lake effect clouds can suppress highs

### Common Edge Sources
- **Lake breeze**: In spring/summer, an afternoon lake breeze can drop temps 5-10°F
  at lakefront stations. Midway is far enough inland that the lake breeze often
  doesn't reach it, OR it arrives late. Models that predict cooling from lake breeze
  may overshoot for Midway specifically.
- **Winter arctic outbreaks**: When polar vortex events hit, models sometimes
  underestimate how cold it gets. But Midway's urban location buffers extremes.
  Edge: lower brackets may be overpriced if models use raw GFS output.
- **O'Hare confusion**: Casual traders checking "Chicago weather" may get O'Hare
  temps. If O'Hare is 67°F but Midway (settlement) is 70°F, there's a 3°F gap
  that creates edge.

### Seasonal Ranges
- Winter (Dec-Feb): Highs 25-40°F, arctic air events create extreme brackets
- Spring (Mar-May): Highs 45-70°F, highest variance season
- Summer (Jun-Aug): Highs 78-92°F, lake breeze is the key variable
- Fall (Sep-Nov): Highs 45-65°F, transition weather = model uncertainty

---

## Miami (KMIA — Miami International Airport)

### Station Characteristics
- Airport is inland from the coast, 5 miles from the beach
- Sea breeze is the dominant afternoon weather feature
- Very consistent summer highs (88-92°F), less variance than other cities
- Winter "cold" fronts may only drop highs to 72-75°F

### Common Edge Sources
- **Sea breeze timing**: On days when the sea breeze arrives early (before 1 PM),
  afternoon highs are suppressed. On days it arrives late or not at all, temps
  can spike 3-5°F above forecast. Model disagreement on sea breeze timing = edge.
- **Summer consistency bias**: Because Miami summer highs are so consistent (89-91°F),
  traders may underprice the edge brackets. A day when highs hit 94°F or only 85°F
  has cheap brackets because traders assume "it's always 90 in Miami."
- **Winter cold fronts**: Post-frontal mornings can be cool (60s) with rapid warming.
  The daily high often occurs right before the front or the morning after. Traders
  who see "cold front" may underprice the high bracket.
- **Humidity and feels-like confusion**: Traders may confuse "feels like" temperature
  with actual temperature. Heat index doesn't affect settlement.

### Seasonal Ranges
- Winter (Dec-Feb): Highs 75-82°F, post-front variability
- Spring (Mar-May): Highs 82-88°F, transition to rainy season
- Summer (Jun-Aug): Highs 88-93°F, most consistent, least edge
- Fall (Sep-Nov): Highs 82-88°F, hurricane season adds uncertainty (avoid)

---

## Austin (KAUS — Austin-Bergstrom International Airport)

### Station Characteristics
- Airport is southeast of the city, slightly warmer than downtown in summer
- No significant water body to moderate temperature
- Can see extreme heat in summer (100°F+)
- Blue northers (cold fronts) can cause 30°F drops in hours

### Common Edge Sources
- **Blue northers**: A cold front blowing through mid-afternoon can cause the high
  to have already occurred by noon, then temps crash. Models usually show this, but
  Kalshi traders may not check timing closely. If the front passes at 2 PM, the
  higher bracket may already be locked in before traders react.
- **Summer extremes**: Austin regularly hits 100-105°F in summer. Traders from
  northern cities may underprice extreme heat brackets.
- **Cloud cover disagreements**: Central Texas is at the boundary of Gulf moisture
  and dry continental air. Cloud cover forecasts vary wildly between models.
  A cloudy day might top at 85°F while a clear day hits 95°F in the same week.
- **Airport vs. city**: The airport can be 2-3°F warmer than downtown Austin
  due to the heat island effect of runways and lack of tree cover.

### Seasonal Ranges
- Winter (Dec-Feb): Highs 55-70°F, blue norther events
- Spring (Mar-May): Highs 75-90°F, severe storm season
- Summer (Jun-Aug): Highs 95-105°F, extreme heat = cheap edge brackets
- Fall (Sep-Nov): Highs 75-90°F, Indian summer days create edge

---

## Los Angeles (KCQT — Downtown LA / USC)

### Station Characteristics
- Downtown station, NOT LAX or Burbank
- Marine layer is the single most important weather factor
- Can be 15-20°F warmer than Santa Monica due to marine layer burn-off patterns
- Santa Ana winds in fall/winter create extreme heat events

### Common Edge Sources
- **Marine layer burn-off timing**: This is the #1 edge in LA weather trading.
  If the marine layer burns off by 10 AM, highs can spike 5-10°F above forecast.
  If it persists all day (June Gloom), highs may be 10°F below forecast.
  Models struggle with burn-off timing. When HRRR says "clear by 10 AM" and
  Euro says "overcast until 2 PM", the edge is massive.
- **Santa Ana winds**: Offshore winds bring hot, dry air. These are well-forecast
  2-3 days out, but Kalshi markets launched the day before may underprice the
  extreme heat brackets because traders check the current (pre-Santa Ana) weather.
- **Valley vs. coast confusion**: Traders checking "LA weather" might see Burbank
  or LAX temps. Downtown (KCQT) is distinctly different from both.
- **Night-to-morning minimum**: LA's diurnal range can be huge (50°F morning,
  85°F afternoon). Models that average this out may misstate the daily high.

### Seasonal Ranges
- Winter (Dec-Feb): Highs 65-75°F, rain events create edge
- Spring (Mar-May): Highs 70-82°F, marine layer season starts
- Summer (Jun-Aug): Highs 82-95°F, June Gloom in early summer
- Fall (Sep-Nov): Highs 78-100°F, Santa Ana events = biggest edge

---

## Philadelphia (KPHL — Philadelphia International Airport)

### Station Characteristics
- Airport is southwest of the city near the Delaware River
- Similar climate to NYC but slightly warmer in summer, slightly colder in winter
- Less urban buffering than Central Park station
- River proximity can moderate extremes slightly

### Common Edge Sources
- **NYC correlation**: Traders may assume Philly matches NYC temps. In reality,
  Philly is often 2-3°F warmer in summer and 1-2°F colder in winter. When the
  same front hits both cities, the timing difference creates edge.
- **Less liquid markets**: Fewer traders = wider spreads = more mispricing.
  Philly weather markets are among the easiest to find edge in.
- **Airport exposure**: Being at the airport means more wind exposure than an
  urban station. Cold fronts have sharper impact on the thermometer.

---

## Denver (KDEN — Denver International Airport)

### Station Characteristics
- Airport is 25 miles NORTHEAST of downtown, on the plains
- Elevation: 5,431 feet — altitude affects temperature differently than low-elevation
- DIA can be 5-10°F different from downtown Denver
- Chinook (föhn) winds can cause 30°F temperature spikes in hours

### Common Edge Sources
- **Chinook winds**: The single biggest edge source in Denver. When westerly winds
  are forecast, air compresses and warms as it descends the Front Range. Models
  sometimes miss the timing or magnitude. A chinook arriving at noon vs. 4 PM
  makes a massive difference in the daily high.
- **Airport vs. downtown**: DIA is on flat plains with no urban heat island. In winter
  it can be 10°F colder than downtown. In summer the difference is smaller (3-5°F).
  Traders checking "Denver weather" may be seeing downtown readings.
- **Upslope events**: When winds blow from the east, moist air rises against the
  Rockies, producing clouds and precipitation. This can suppress highs significantly
  below model forecasts that don't capture the mesoscale dynamics well.
- **Extreme diurnal range**: Denver can see 30-40°F swings from low to high in
  a single day. The "high" bracket can be far from the morning temperature,
  and traders may underprice the range.

### Seasonal Ranges
- Winter (Dec-Feb): Highs 35-55°F, chinook events can hit 65°F+
- Spring (Mar-May): Highs 55-75°F, severe weather season
- Summer (Jun-Aug): Highs 85-100°F, afternoon thunderstorms cap highs
- Fall (Sep-Nov): Highs 55-75°F, early season chinooks

---

## Cross-City Correlation Table

When trading multiple cities on the same day, be aware of correlated outcomes:

| City Pair | Correlation | Notes |
|-----------|-------------|-------|
| NYC — Philadelphia | HIGH | Same weather systems, 1-3 hour lag |
| NYC — Chicago | MODERATE | Same fronts but 12-24 hour offset |
| Chicago — Denver | LOW-MODERATE | Can share arctic air masses |
| Miami — Austin | LOW | Different climate zones |
| Miami — NYC | LOW | Only in major east coast events |
| LA — Austin | LOW | Different climate entirely |
| LA — Denver | LOW-MODERATE | Santa Ana events can extend inland |

**Rule:** If correlation is HIGH, reduce position size by 50% in the second city.
If MODERATE, reduce by 25%. If LOW, trade independently.
