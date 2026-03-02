"""
╔══════════════════════════════════════════════════════════════════════╗
║  OPENCLAW ADVANCED WEATHER TRADING SKILL v2.0                       ║
║  Multi-Model Ensemble Temperature Trading for Kalshi Markets        ║
║                                                                      ║
║  Replaces: Basic NWS-only weather skill (v1.0)                      ║
║  Author: Christian's clawdbot system                                 ║
║  Strategy: Daily high temperature bracket contracts                  ║
╚══════════════════════════════════════════════════════════════════════╝

ARCHITECTURE OVERVIEW:
  1. Data Layer     → Open-Meteo multi-model + NWS + NOAA historical
  2. Ensemble Layer → Combine HRRR, GFS, ECMWF, NBM forecasts
  3. Calibration    → NGR/EMOS post-processing with rolling training
  4. Pricing Layer  → Calibrated P(high > T) vs Kalshi orderbook
  5. Execution      → Quarter-Kelly sizing with FLB adjustments
  6. Learning Layer → JSON trade journal + EWMA bias tracking

DEPENDENCIES:
  pip install requests numpy scipy
  (No paid API keys needed — Open-Meteo is free, NWS is free)
"""

import os
import json
import uuid
import math
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field

import requests
import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CityConfig:
    """Configuration for a single Kalshi temperature market city."""
    name: str
    lat: float
    lon: float
    timezone: str
    kalshi_series: str       # e.g., "KXHIGHNY"
    ghcnd_station: str       # NOAA station ID for historical data
    icao: str                # ICAO code (settlement source)
    # Calibration parameters (updated by learning loop)
    ngr_alpha: float = 0.0   # Bias intercept
    ngr_beta: float = 1.0    # Ensemble mean coefficient
    ngr_gamma: float = 4.0   # Base variance (σ² floor)
    ngr_delta: float = 1.0   # Ensemble spread coefficient


# All cities Kalshi currently offers temperature markets for
CITIES: Dict[str, CityConfig] = {
    "nyc": CityConfig(
        name="New York", lat=40.7128, lon=-74.0060,
        timezone="America/New_York", kalshi_series="KXHIGHNY",
        ghcnd_station="USW00094728", icao="KNYC"
    ),
    "chicago": CityConfig(
        name="Chicago", lat=41.8781, lon=-87.6298,
        timezone="America/Chicago", kalshi_series="KXHIGHCH",
        ghcnd_station="USW00014819", icao="KMDW"
    ),
    "miami": CityConfig(
        name="Miami", lat=25.7617, lon=-80.1918,
        timezone="America/New_York", kalshi_series="KXHIGHMI",
        ghcnd_station="USW00012839", icao="KMIA"
    ),
    "austin": CityConfig(
        name="Austin", lat=30.2672, lon=-97.7431,
        timezone="America/Chicago", kalshi_series="KXHIGHAU",
        ghcnd_station="USW00013904", icao="KAUS"
    ),
    "los_angeles": CityConfig(
        name="Los Angeles", lat=33.9425, lon=-118.4081,
        timezone="America/Los_Angeles", kalshi_series="KXHIGHLAX",
        ghcnd_station="USW00023174", icao="KLAX"
    ),
    "denver": CityConfig(
        name="Denver", lat=39.8561, lon=-104.6737,
        timezone="America/Denver", kalshi_series="KXHIGHDEN",
        ghcnd_station="USW00003017", icao="KDEN"
    ),
    "atlanta": CityConfig(
        name="Atlanta", lat=33.7490, lon=-84.3880,
        timezone="America/New_York", kalshi_series="KXHIGHATL",
        ghcnd_station="USW00013874", icao="KATL"
    ),
    "phoenix": CityConfig(
        name="Phoenix", lat=33.4484, lon=-112.0740,
        timezone="America/Phoenix", kalshi_series="KXHIGHPHX",
        ghcnd_station="USW00023183", icao="KPHX"
    ),
}

# ─── Trading Parameters ─────────────────────────────────────────────
MIN_EDGE_PERCENT = 0.08       # 8% minimum model edge to trade
KELLY_FRACTION = 0.25         # Quarter-Kelly for safety
MAX_POSITION_PCT = 0.10       # Max 10% of bankroll per trade
FLB_LONGSHOT_PENALTY = 0.05   # Extra 5% edge required for <15¢ contracts
FLB_LONGSHOT_THRESHOLD = 0.15 # Contracts below this trigger FLB adjustment
MIN_EDGE_CENTS = 5            # Minimum edge in cents (absolute floor)

# ─── Ensemble & Calibration ─────────────────────────────────────────
NGR_TRAINING_DAYS = 40        # Rolling window for NGR parameter fitting
EWMA_BETA = 0.92              # Bias tracker decay (≈12-trade window)
ENSEMBLE_MODELS = [
    "gfs_seamless",           # GFS 13km, 16-day range
    "ecmwf_ifs025",           # ECMWF 9km, 15-day range
    "icon_seamless",          # DWD ICON, independent physics
]
ENSEMBLE_PROBABILISTIC = [
    "gfs025_eps",             # 31-member GFS ensemble
    "ecmwf_ifs025_ensemble",  # 51-member ECMWF ensemble
]

# ─── NWS Settlement Source Weighting ─────────────────────────────────
# NWS CLI is the SOLE settlement source for Kalshi temperature contracts.
# NWS forecasts predict the settlement value directly, so they get
# privileged weighting in the ensemble. Other models add value for
# uncertainty estimation but must be anchored to NWS.
NWS_WEIGHT_MULTIPLIER = 2.0   # NWS gets 2× weight vs other models in ensemble mean
NWS_ANCHOR_BLEND = 0.35       # Final estimate = 35% NWS + 65% calibrated ensemble
                               # When NWS disagrees with ensemble by >3°F, raise to 0.50
NWS_DISAGREE_THRESHOLD = 3.0  # °F — triggers elevated NWS anchoring
NWS_DISAGREE_BLEND = 0.50     # Blend when NWS strongly disagrees with ensemble
CLI_SETTLEMENT_TIME = "10:00"  # ET — when Kalshi reads NWS CLI
CLI_DELAYED_TIME = "12:00"     # ET — delayed settlement if CLI inconsistent with METAR
METAR_CHECK_URL = "https://aviationweather.gov/api/data/metar"  # Real-time obs for verification

# ─── File Paths ──────────────────────────────────────────────────────
TRADE_LOG_PATH = os.environ.get("TRADE_LOG_PATH", "./trade_journal.jsonl")
CALIBRATION_DB_PATH = os.environ.get("CALIBRATION_DB_PATH", "./calibration_data.json")
BIAS_TRACKER_PATH = os.environ.get("BIAS_TRACKER_PATH", "./bias_tracker.json")
PERFORMANCE_LOG_PATH = os.environ.get("PERFORMANCE_LOG_PATH", "./performance_stats.json")

logger = logging.getLogger("weather_skill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ═══════════════════════════════════════════════════════════════════════
# 1. DATA LAYER — Multi-Source Weather Data Fetching
# ═══════════════════════════════════════════════════════════════════════

class WeatherDataFetcher:
    """
    Fetches forecasts from multiple sources:
      - NWS hourly forecast (PRIMARY — this is the settlement source)
      - NWS gridpoint probabilistic data (forecastGridData for uncertainty)
      - Open-Meteo deterministic models (HRRR, GFS, ECMWF, ICON, NBM)
      - Open-Meteo ensemble models (GFS 31-member, ECMWF 51-member)
      - Open-Meteo Previous Runs API (for calibration training data)
      - METAR real-time observations (for intraday settlement monitoring)

    IMPORTANT: NWS is NOT just another model — it IS the settlement source.
    Kalshi settles on the NWS Daily Climate Report (CLI). The NWS forecast
    predicts the CLI value directly, so it gets privileged treatment.
    """

    OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
    OPEN_METEO_GFS = "https://api.open-meteo.com/v1/gfs"
    OPEN_METEO_ECMWF = "https://api.open-meteo.com/v1/ecmwf"
    OPEN_METEO_ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
    OPEN_METEO_PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"
    NWS_API = "https://api.weather.gov"
    NOAA_ACCESS = "https://www.ncei.noaa.gov/access/services/data/v1"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "ClawdBot-Weather/2.0 (contact: trading-bot)",
            "Accept": "application/json"
        })

    # ─── Open-Meteo Deterministic Forecasts ──────────────────────────

    def fetch_deterministic_forecasts(
        self, city: CityConfig, target_date: str
    ) -> Dict[str, Optional[float]]:
        """
        Fetch daily high temperature from multiple deterministic models.

        Returns: {"gfs_seamless": 82.1, "ecmwf_ifs025": 83.4, ...}
        """
        results = {}

        # Best-match endpoint (auto-selects highest resolution)
        try:
            resp = self.session.get(self.OPEN_METEO_FORECAST, params={
                "latitude": city.lat, "longitude": city.lon,
                "daily": "temperature_2m_max",
                "temperature_unit": "fahrenheit",
                "timezone": city.timezone,
                "start_date": target_date, "end_date": target_date,
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            tmax = data.get("daily", {}).get("temperature_2m_max", [None])[0]
            results["best_match"] = tmax
        except Exception as e:
            logger.warning(f"Open-Meteo best_match failed for {city.name}: {e}")
            results["best_match"] = None

        # Individual model endpoints
        for model in ENSEMBLE_MODELS:
            try:
                # GFS models use the GFS endpoint, ECMWF uses ECMWF endpoint
                if "ecmwf" in model:
                    base_url = self.OPEN_METEO_ECMWF
                else:
                    base_url = self.OPEN_METEO_GFS

                resp = self.session.get(base_url, params={
                    "latitude": city.lat, "longitude": city.lon,
                    "daily": "temperature_2m_max",
                    "models": model,
                    "temperature_unit": "fahrenheit",
                    "timezone": city.timezone,
                    "start_date": target_date, "end_date": target_date,
                }, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                tmax = data.get("daily", {}).get("temperature_2m_max", [None])[0]
                results[model] = tmax
            except Exception as e:
                logger.warning(f"Open-Meteo {model} failed for {city.name}: {e}")
                results[model] = None

        # NWS forecast (settlement-aligned source)
        try:
            nws_temp = self._fetch_nws_max(city, target_date)
            results["nws"] = nws_temp
        except Exception as e:
            logger.warning(f"NWS forecast failed for {city.name}: {e}")
            results["nws"] = None

        return results

    def _fetch_nws_max(self, city: CityConfig, target_date: str) -> Optional[float]:
        """
        Fetch NWS hourly forecast and compute max temperature for target date.

        This is the SETTLEMENT-ALIGNED forecast — NWS CLI settles Kalshi contracts.
        We fetch from the specific grid point closest to the CLI station (city.icao).
        """
        # Step 1: Get grid point using the CLI station coordinates
        # Use city coordinates (which should map to the CLI station area)
        points_resp = self.session.get(
            f"{self.NWS_API}/points/{city.lat},{city.lon}", timeout=10
        )
        points_resp.raise_for_status()
        props = points_resp.json()["properties"]
        forecast_url = props["forecastHourly"]

        # Step 2: Get hourly forecast
        hourly_resp = self.session.get(forecast_url, timeout=10)
        hourly_resp.raise_for_status()
        periods = hourly_resp.json()["properties"]["periods"]

        # Step 3: Filter to target date and find max
        # NOTE: NWS CLI uses Local Standard Time year-round (NOT daylight saving).
        # During DST, the CLI measurement window is effectively shifted by 1 hour.
        # For trading purposes, we use the calendar date which is close enough
        # for the forecast. The DST edge matters more for late-night boundary cases.
        target_temps = []
        for period in periods:
            period_date = period["startTime"][:10]
            if period_date == target_date:
                target_temps.append(period["temperature"])

        return max(target_temps) if target_temps else None

    def fetch_nws_grid_data(self, city: CityConfig) -> Optional[Dict]:
        """
        Fetch NWS forecastGridData — provides probabilistic temperature ranges.

        This gives us NWS's own uncertainty estimate, which is valuable because
        it represents the settlement source's view of forecast confidence.
        Returns raw grid data dict with maxTemperature values and uncertainty.
        """
        try:
            points_resp = self.session.get(
                f"{self.NWS_API}/points/{city.lat},{city.lon}", timeout=10
            )
            points_resp.raise_for_status()
            props = points_resp.json()["properties"]
            grid_url = props["forecastGridData"]

            grid_resp = self.session.get(grid_url, timeout=10)
            grid_resp.raise_for_status()
            grid_data = grid_resp.json()["properties"]

            return grid_data
        except Exception as e:
            logger.warning(f"NWS grid data failed for {city.name}: {e}")
            return None

    def fetch_metar_observation(self, city: CityConfig) -> Optional[Dict[str, Any]]:
        """
        Fetch latest METAR observation for the CLI settlement station.

        Used for:
          1. Real-time monitoring of current temperature during trading day
          2. Pre-settlement verification (compare METAR max vs forecast)
          3. Post-settlement audit (did CLI match what METAR showed?)

        Returns: {"temp_f": 72.0, "time": "2026-03-01T14:00Z", "raw_metar": "..."}
        """
        try:
            resp = self.session.get(METAR_CHECK_URL, params={
                "ids": city.icao,
                "format": "json",
                "hours": 24,  # Last 24 hours for daily max tracking
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return None

            # Parse METAR observations to find max temperature
            temps = []
            for obs in data if isinstance(data, list) else [data]:
                temp_c = obs.get("temp")
                if temp_c is not None:
                    temp_f = temp_c * 9/5 + 32
                    temps.append({
                        "temp_f": round(temp_f, 1),
                        "time": obs.get("reportTime", ""),
                    })

            if not temps:
                return None

            max_obs = max(temps, key=lambda x: x["temp_f"])
            return {
                "current_max_f": max_obs["temp_f"],
                "observation_time": max_obs["time"],
                "all_observations": temps,
                "n_observations": len(temps),
            }
        except Exception as e:
            logger.warning(f"METAR fetch failed for {city.icao}: {e}")
            return None

    # ─── Open-Meteo Ensemble Forecasts ───────────────────────────────

    def fetch_ensemble_forecasts(
        self, city: CityConfig, target_date: str
    ) -> Dict[str, List[float]]:
        """
        Fetch full ensemble member forecasts for probability computation.

        Returns: {"gfs025_eps": [81.2, 83.4, 82.1, ...], "ecmwf_ifs025_ensemble": [...]}
        Each list contains one value per ensemble member (daily max temp).
        """
        results = {}

        for model in ENSEMBLE_PROBABILISTIC:
            try:
                resp = self.session.get(self.OPEN_METEO_ENSEMBLE, params={
                    "latitude": city.lat, "longitude": city.lon,
                    "daily": "temperature_2m_max",
                    "models": model,
                    "temperature_unit": "fahrenheit",
                    "timezone": city.timezone,
                    "start_date": target_date, "end_date": target_date,
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                # Extract all member values for the target date
                daily = data.get("daily", {})
                members = []
                for key, values in daily.items():
                    if key.startswith("temperature_2m_max_member") and values:
                        val = values[0]
                        if val is not None:
                            members.append(val)

                if members:
                    results[model] = members
                    logger.info(
                        f"  {model}: {len(members)} members, "
                        f"mean={np.mean(members):.1f}°F, "
                        f"std={np.std(members):.1f}°F"
                    )
            except Exception as e:
                logger.warning(f"Ensemble {model} failed for {city.name}: {e}")

        return results

    # ─── Previous Runs API (Calibration Training Data) ───────────────

    def fetch_previous_runs(
        self, city: CityConfig, past_days: int = 40
    ) -> Dict[str, Any]:
        """
        Fetch what models predicted vs what was observed over the past N days.

        The 'previous_day0' column closely matches actual observations (assimilated).
        'previous_day1/2/3' show what the model predicted 1/2/3 days prior.

        Returns raw API data for calibration training pipeline.
        """
        try:
            resp = self.session.get(self.OPEN_METEO_PREVIOUS, params={
                "latitude": city.lat, "longitude": city.lon,
                "daily": (
                    "temperature_2m_max,"
                    "temperature_2m_max_previous_day1,"
                    "temperature_2m_max_previous_day2,"
                    "temperature_2m_max_previous_day3"
                ),
                "temperature_unit": "fahrenheit",
                "timezone": city.timezone,
                "past_days": past_days,
                "forecast_days": 0,
            }, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Previous runs fetch failed for {city.name}: {e}")
            return {}

    # ─── NOAA Historical Observations ────────────────────────────────

    def fetch_noaa_historical(
        self, city: CityConfig, start_date: str, end_date: str,
        noaa_token: Optional[str] = None
    ) -> List[Dict]:
        """
        Fetch historical daily TMAX observations from NOAA NCEI.

        Requires a free NOAA API token (set NOAA_TOKEN env var).
        Returns list of {"date": "2025-01-15", "tmax_f": 42.0}
        """
        token = noaa_token or os.environ.get("NOAA_TOKEN", "")
        if not token:
            logger.warning("No NOAA_TOKEN set. Historical data unavailable.")
            return []

        try:
            resp = self.session.get(self.NOAA_ACCESS, params={
                "dataset": "daily-summaries",
                "stations": city.ghcnd_station,
                "dataTypes": "TMAX",
                "startDate": start_date,
                "endDate": end_date,
                "units": "standard",
                "format": "json",
            }, headers={"token": token}, timeout=30)
            resp.raise_for_status()
            records = resp.json()

            return [
                {
                    "date": rec.get("DATE", "")[:10],
                    "tmax_f": rec.get("TMAX")
                }
                for rec in records if rec.get("TMAX") is not None
            ]
        except Exception as e:
            logger.error(f"NOAA historical fetch failed for {city.name}: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════
# 2. ENSEMBLE PROCESSING & PROBABILITY ENGINE
# ═══════════════════════════════════════════════════════════════════════

class EnsembleProcessor:
    """
    Combines multiple forecast sources into calibrated probability estimates,
    with NWS given privileged weighting as the settlement source.

    Pipeline:
      1. Aggregate ensemble members across GFS (31) + ECMWF (51) = 82 members
      2. Compute raw ensemble statistics (mean, std, percentiles)
      3. Compute NWS-anchored weighted mean (NWS gets 2× weight)
      4. If NWS disagrees with ensemble by >3°F, increase NWS anchor blend
      5. Apply NGR/EMOS calibration to correct underdispersion
      6. Output calibrated P(high > T) for each Kalshi bracket threshold

    WHY NWS IS PRIVILEGED:
      Kalshi settles on the NWS Daily Climate Report (CLI). The NWS forecast
      is literally predicting the settlement value. Other models (GFS, ECMWF)
      are forecasting the atmosphere — but NWS is forecasting the *report
      that determines who gets paid*. When NWS disagrees with the ensemble,
      NWS is more likely to match the settlement outcome.
    """

    def __init__(self):
        pass

    def compute_raw_ensemble_stats(
        self,
        deterministic: Dict[str, Optional[float]],
        ensemble: Dict[str, List[float]]
    ) -> Dict[str, float]:
        """
        Compute ensemble statistics with NWS settlement-source anchoring.

        The ensemble mean is computed in two stages:
          1. Raw ensemble mean from all members (equal weight)
          2. NWS-anchored mean: blend of NWS forecast and raw ensemble mean

        When NWS strongly disagrees with the ensemble (>3°F), the NWS anchor
        weight increases from 35% to 50% because the settlement source's
        own forecast is more likely to predict its own report.

        Returns stats dict including both raw and NWS-anchored values.
        """
        # Collect all ensemble members
        all_members = []
        for model_members in ensemble.values():
            all_members.extend(model_members)

        # Separate NWS from other deterministic forecasts
        nws_forecast = deterministic.get("nws")
        other_det = {k: v for k, v in deterministic.items() if k != "nws" and v is not None}
        det_values = [v for v in deterministic.values() if v is not None]

        if not all_members and not det_values:
            raise ValueError("No forecast data available")

        # ── Stage 1: Raw ensemble statistics ─────────────────────────
        if all_members:
            arr = np.array(all_members)
            raw_ensemble_mean = float(np.mean(arr))
            raw_ensemble_std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 3.0
            stats = {
                "raw_ensemble_mean": raw_ensemble_mean,
                "raw_ensemble_std": raw_ensemble_std,
                "ensemble_min": float(np.min(arr)),
                "ensemble_max": float(np.max(arr)),
                "ensemble_p10": float(np.percentile(arr, 10)),
                "ensemble_p25": float(np.percentile(arr, 25)),
                "ensemble_p50": float(np.percentile(arr, 50)),
                "ensemble_p75": float(np.percentile(arr, 75)),
                "ensemble_p90": float(np.percentile(arr, 90)),
                "n_members": len(arr),
            }
        else:
            arr = np.array(det_values)
            raw_ensemble_mean = float(np.mean(arr))
            raw_ensemble_std = max(float(np.std(arr, ddof=1)), 2.0) if len(arr) > 1 else 3.0
            stats = {
                "raw_ensemble_mean": raw_ensemble_mean,
                "raw_ensemble_std": raw_ensemble_std,
                "ensemble_min": float(np.min(arr)),
                "ensemble_max": float(np.max(arr)),
                "n_members": 0,
            }

        # ── Stage 2: NWS-Anchored Weighting ─────────────────────────
        # NWS is the settlement source. Its forecast directly predicts the
        # CLI value that Kalshi uses. Give it privileged weight.
        if nws_forecast is not None:
            nws_ensemble_gap = abs(nws_forecast - raw_ensemble_mean)

            # Dynamic blend: increase NWS weight when it disagrees with ensemble
            if nws_ensemble_gap > NWS_DISAGREE_THRESHOLD:
                nws_blend = NWS_DISAGREE_BLEND  # 50% NWS when strong disagreement
                logger.info(
                    f"  ⚠ NWS disagrees with ensemble by {nws_ensemble_gap:.1f}°F "
                    f"(>{NWS_DISAGREE_THRESHOLD}°F) → elevating NWS anchor to {nws_blend:.0%}"
                )
            else:
                nws_blend = NWS_ANCHOR_BLEND  # 35% NWS normally

            # NWS-anchored ensemble mean
            anchored_mean = nws_blend * nws_forecast + (1 - nws_blend) * raw_ensemble_mean

            stats["nws_forecast"] = nws_forecast
            stats["nws_ensemble_gap"] = round(nws_ensemble_gap, 1)
            stats["nws_blend_weight"] = nws_blend
            stats["ensemble_mean"] = anchored_mean  # THIS is what gets used for pricing
            stats["ensemble_std"] = raw_ensemble_std  # Spread stays from full ensemble

            logger.info(
                f"  NWS forecast: {nws_forecast:.1f}°F | "
                f"Raw ensemble: {raw_ensemble_mean:.1f}°F | "
                f"Anchored ({nws_blend:.0%} NWS): {anchored_mean:.1f}°F"
            )
        else:
            # NWS unavailable — fall back to raw ensemble (log warning)
            stats["nws_forecast"] = None
            stats["nws_ensemble_gap"] = None
            stats["nws_blend_weight"] = 0.0
            stats["ensemble_mean"] = raw_ensemble_mean
            stats["ensemble_std"] = raw_ensemble_std
            logger.warning(
                "  ⚠ NWS forecast unavailable! Using raw ensemble mean. "
                "Settlement prediction may be less accurate."
            )

        # ── Deterministic model diagnostics ──────────────────────────
        if det_values:
            det_arr = np.array(det_values)
            stats["deterministic_mean"] = float(np.mean(det_arr))
            stats["deterministic_spread"] = float(np.ptp(det_arr))
            if np.mean(det_arr) != 0:
                cv = np.std(det_arr) / abs(np.mean(det_arr))
                stats["model_agreement"] = float(max(0, 1 - cv * 10))
            else:
                stats["model_agreement"] = 0.5

            # Track how far each model is from NWS (settlement source)
            if nws_forecast is not None:
                stats["model_vs_nws"] = {
                    k: round(v - nws_forecast, 1)
                    for k, v in deterministic.items() if v is not None and k != "nws"
                }

        return stats

    def raw_member_probability(
        self, ensemble: Dict[str, List[float]], threshold: float
    ) -> Optional[float]:
        """
        Quick raw probability from counting ensemble members above threshold.

        WARNING: This is uncalibrated and systematically overconfident.
        Use only as a sanity check against NGR output.
        """
        all_members = []
        for members in ensemble.values():
            all_members.extend(members)

        if not all_members:
            return None

        n_above = sum(1 for m in all_members if m > threshold)
        return n_above / len(all_members)


# ═══════════════════════════════════════════════════════════════════════
# 3. NGR CALIBRATION ENGINE (EMOS)
# ═══════════════════════════════════════════════════════════════════════

class NGRCalibrator:
    """
    Non-Homogeneous Gaussian Regression (NGR/EMOS) calibration.

    Fits: Y ~ N(α + β·M, γ + δ·S²)
    where M = ensemble mean, S = ensemble std

    Parameters are fit by minimizing CRPS over a rolling training window.
    This corrects two known problems:
      1. Bias (α adjusts intercept, β adjusts slope)
      2. Underdispersion (γ provides floor variance, δ scales spread)
    """

    @staticmethod
    def crps_gaussian(mu: np.ndarray, sigma: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Closed-form CRPS for Gaussian distribution."""
        sigma = np.maximum(sigma, 0.01)  # prevent division by zero
        z = (y - mu) / sigma
        crps = sigma * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))
        return crps

    @staticmethod
    def fit_ngr(
        M_train: np.ndarray,  # ensemble means
        S_train: np.ndarray,  # ensemble stds
        y_train: np.ndarray,  # observed values
    ) -> Tuple[float, float, float, float]:
        """
        Fit NGR parameters by minimizing mean CRPS.

        Returns: (alpha, beta, gamma, delta)
        """
        def loss(params):
            alpha, beta, gamma, delta = params
            mu = alpha + beta * M_train
            var = np.maximum(gamma + delta * S_train**2, 0.01)
            sigma = np.sqrt(var)
            return np.mean(NGRCalibrator.crps_gaussian(mu, sigma, y_train))

        # Initial guess: unbiased, unit scaling
        x0 = [0.0, 1.0, 4.0, 1.0]
        # Bounds: alpha free, beta positive, gamma positive, delta positive
        bounds = [(-20, 20), (0.5, 1.5), (0.1, 50), (0.01, 10)]

        result = minimize(loss, x0=x0, bounds=bounds, method="L-BFGS-B")

        if result.success:
            alpha, beta, gamma, delta = result.x
            logger.info(
                f"  NGR fit: α={alpha:.2f}, β={beta:.3f}, "
                f"γ={gamma:.2f}, δ={delta:.3f} | CRPS={result.fun:.3f}"
            )
            return tuple(result.x)
        else:
            logger.warning(f"  NGR optimization failed: {result.message}. Using defaults.")
            return (0.0, 1.0, 4.0, 1.0)

    @staticmethod
    def calibrated_probability(
        ensemble_mean: float,
        ensemble_std: float,
        threshold: float,
        alpha: float, beta: float, gamma: float, delta: float
    ) -> float:
        """
        Compute calibrated P(high > threshold) using fitted NGR parameters.

        This is the core pricing function of the entire system.
        """
        mu_cal = alpha + beta * ensemble_mean
        sigma_cal = math.sqrt(max(gamma + delta * ensemble_std**2, 0.01))
        z = (threshold - mu_cal) / sigma_cal
        prob_exceed = 1.0 - norm.cdf(z)
        return float(np.clip(prob_exceed, 0.001, 0.999))

    @staticmethod
    def calibrated_bracket_probability(
        ensemble_mean: float,
        ensemble_std: float,
        bracket_low: float,
        bracket_high: float,
        alpha: float, beta: float, gamma: float, delta: float
    ) -> float:
        """
        Compute P(bracket_low < high ≤ bracket_high) for Kalshi bracket contracts.

        For edge brackets:
          - Low edge: P(high ≤ bracket_high) = Φ(z_high)
          - High edge: P(high > bracket_low) = 1 - Φ(z_low)
        For middle brackets:
          - P = Φ(z_high) - Φ(z_low)
        """
        mu_cal = alpha + beta * ensemble_mean
        sigma_cal = math.sqrt(max(gamma + delta * ensemble_std**2, 0.01))

        if bracket_low == float('-inf'):
            # Low edge bracket: P(high ≤ bracket_high)
            z_high = (bracket_high - mu_cal) / sigma_cal
            return float(np.clip(norm.cdf(z_high), 0.001, 0.999))
        elif bracket_high == float('inf'):
            # High edge bracket: P(high > bracket_low)
            z_low = (bracket_low - mu_cal) / sigma_cal
            return float(np.clip(1.0 - norm.cdf(z_low), 0.001, 0.999))
        else:
            # Middle bracket: P(low < high ≤ high)
            z_low = (bracket_low - mu_cal) / sigma_cal
            z_high = (bracket_high - mu_cal) / sigma_cal
            prob = norm.cdf(z_high) - norm.cdf(z_low)
            return float(np.clip(prob, 0.001, 0.999))


# ═══════════════════════════════════════════════════════════════════════
# 4. ADAPTIVE LEARNING SYSTEM
# ═══════════════════════════════════════════════════════════════════════

class AdaptiveLearner:
    """
    Tracks performance, detects biases, and adjusts future predictions.

    Components:
      1. Trade Journal    — JSONL log of every trade with full context
      2. EWMA Bias Tracker — Exponentially-weighted bias by (city, season, regime)
      3. Calibration Curve — Rolling reliability diagram
      4. Performance Stats — Brier score, log loss, P&L tracking
    """

    def __init__(
        self,
        trade_log_path: str = TRADE_LOG_PATH,
        bias_tracker_path: str = BIAS_TRACKER_PATH,
        performance_path: str = PERFORMANCE_LOG_PATH,
    ):
        self.trade_log_path = trade_log_path
        self.bias_tracker_path = bias_tracker_path
        self.performance_path = performance_path
        self.bias_tracker = self._load_bias_tracker()
        self.performance = self._load_performance()

    # ─── Trade Journal ───────────────────────────────────────────────

    def log_trade(self, trade: Dict[str, Any]) -> None:
        """Append a trade record to the JSONL trade journal."""
        trade["logged_at"] = datetime.now(timezone.utc).isoformat()
        trade["trade_id"] = trade.get("trade_id", str(uuid.uuid4()))

        with open(self.trade_log_path, "a") as f:
            f.write(json.dumps(trade) + "\n")

        logger.info(f"Trade logged: {trade['trade_id'][:8]}... | {trade.get('ticker', 'N/A')}")

    def load_trade_history(self, n_recent: Optional[int] = None) -> List[Dict]:
        """Load trade history from JSONL file."""
        if not os.path.exists(self.trade_log_path):
            return []

        trades = []
        with open(self.trade_log_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        if n_recent:
            trades = trades[-n_recent:]
        return trades

    # ─── EWMA Bias Tracker ───────────────────────────────────────────

    def _load_bias_tracker(self) -> Dict:
        """Load EWMA bias state from disk."""
        if os.path.exists(self.bias_tracker_path):
            with open(self.bias_tracker_path, "r") as f:
                return json.load(f)
        return {"biases": {}, "counts": {}}

    def _save_bias_tracker(self) -> None:
        """Persist EWMA bias state to disk."""
        with open(self.bias_tracker_path, "w") as f:
            json.dump(self.bias_tracker, f, indent=2)

    def update_bias(
        self, city: str, season: str, forecast_error: float,
        beta: float = EWMA_BETA
    ) -> float:
        """
        Update exponentially-weighted moving average bias tracker.

        forecast_error = predicted_probability - actual_outcome (0 or 1)
        Positive = model overestimated probability
        Negative = model underestimated probability

        Returns: current bias estimate (corrected for initialization)
        """
        key = f"{city}|{season}"

        biases = self.bias_tracker["biases"]
        counts = self.bias_tracker["counts"]

        if key not in biases:
            biases[key] = 0.0
            counts[key] = 0

        counts[key] += 1
        biases[key] = beta * biases[key] + (1 - beta) * forecast_error

        # Adam-style bias correction for early estimates
        corrected = biases[key] / (1 - beta ** counts[key])

        self._save_bias_tracker()

        logger.debug(
            f"  Bias update [{key}]: error={forecast_error:.3f}, "
            f"ewma={corrected:.4f}, n={counts[key]}"
        )
        return corrected

    def get_bias_correction(self, city: str, season: str) -> float:
        """
        Get current bias correction for a city/season.

        Returns the probability adjustment to subtract from model estimates.
        E.g., if bias = +0.03, the model tends to overestimate by 3%.
        """
        key = f"{city}|{season}"
        biases = self.bias_tracker.get("biases", {})
        counts = self.bias_tracker.get("counts", {})

        if key not in biases or counts.get(key, 0) < 5:
            return 0.0  # Not enough data for reliable correction

        n = counts[key]
        corrected = biases[key] / (1 - EWMA_BETA ** n)
        return corrected

    def get_season(self, date_str: str) -> str:
        """Classify date into meteorological season."""
        month = int(date_str[5:7])
        if month in (12, 1, 2):
            return "winter"
        elif month in (3, 4, 5):
            return "spring"
        elif month in (6, 7, 8):
            return "summer"
        else:
            return "fall"

    # ─── Performance Metrics ─────────────────────────────────────────

    def _load_performance(self) -> Dict:
        if os.path.exists(self.performance_path):
            with open(self.performance_path, "r") as f:
                return json.load(f)
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "total_pnl": 0.0, "brier_scores": [], "log_losses": [],
            "by_city": {}, "by_season": {},
        }

    def _save_performance(self) -> None:
        with open(self.performance_path, "w") as f:
            json.dump(self.performance, f, indent=2)

    def record_outcome(
        self,
        trade: Dict[str, Any],
        actual_outcome: int,  # 1 = contract settled YES, 0 = NO
        actual_temperature: float,
    ) -> Dict[str, float]:
        """
        Record trade outcome and compute performance metrics.

        Returns dict of computed metrics for this trade.
        """
        predicted_prob = trade["entry"]["predicted_probability"]
        entry_price = trade["entry"]["entry_price"]
        side = trade["entry"]["side"]
        city = trade["market"]["city"]
        target_date = trade["market"]["target_date"]
        season = self.get_season(target_date)

        # Brier score contribution
        brier = (predicted_prob - actual_outcome) ** 2

        # Log loss contribution (clipped for numerical stability)
        p_clipped = np.clip(predicted_prob, 0.01, 0.99)
        if actual_outcome == 1:
            logloss = -math.log(p_clipped)
        else:
            logloss = -math.log(1 - p_clipped)

        # P&L calculation
        if side == "YES":
            if actual_outcome == 1:
                pnl = 1.0 - entry_price
            else:
                pnl = -entry_price
        else:  # NO side
            if actual_outcome == 0:
                pnl = entry_price  # sold at entry_price, settled at 0
            else:
                pnl = -(1.0 - entry_price)

        # Subtract estimated fees
        fee = 0.02  # approximate taker fee at midpoint
        pnl -= fee

        # Update aggregate stats
        self.performance["total_trades"] += 1
        if pnl > 0:
            self.performance["wins"] += 1
        else:
            self.performance["losses"] += 1
        self.performance["total_pnl"] += pnl
        self.performance["brier_scores"].append(brier)
        self.performance["log_losses"].append(logloss)

        # Keep only last 500 scores for rolling metrics
        self.performance["brier_scores"] = self.performance["brier_scores"][-500:]
        self.performance["log_losses"] = self.performance["log_losses"][-500:]

        # By-city stats
        if city not in self.performance["by_city"]:
            self.performance["by_city"][city] = {"trades": 0, "pnl": 0.0, "brier": []}
        self.performance["by_city"][city]["trades"] += 1
        self.performance["by_city"][city]["pnl"] += pnl
        self.performance["by_city"][city]["brier"].append(brier)
        self.performance["by_city"][city]["brier"] = \
            self.performance["by_city"][city]["brier"][-200:]

        # By-season stats
        if season not in self.performance["by_season"]:
            self.performance["by_season"][season] = {"trades": 0, "pnl": 0.0, "brier": []}
        self.performance["by_season"][season]["trades"] += 1
        self.performance["by_season"][season]["pnl"] += pnl
        self.performance["by_season"][season]["brier"].append(brier)
        self.performance["by_season"][season]["brier"] = \
            self.performance["by_season"][season]["brier"][-200:]

        # Update EWMA bias tracker
        forecast_error = predicted_prob - actual_outcome
        self.update_bias(city, season, forecast_error)

        self._save_performance()

        metrics = {
            "brier_score": brier,
            "log_loss": logloss,
            "pnl": pnl,
            "pnl_cumulative": self.performance["total_pnl"],
            "rolling_brier_50": np.mean(self.performance["brier_scores"][-50:]),
            "win_rate": self.performance["wins"] / max(1, self.performance["total_trades"]),
        }

        logger.info(
            f"  Outcome: {'WIN' if pnl > 0 else 'LOSS'} | "
            f"P&L=${pnl:+.2f} | Brier={brier:.3f} | "
            f"Rolling Brier(50)={metrics['rolling_brier_50']:.3f}"
        )

        return metrics

    def get_performance_summary(self) -> Dict:
        """Generate a comprehensive performance report."""
        p = self.performance
        n = max(1, p["total_trades"])
        brier_all = p.get("brier_scores", [])
        ll_all = p.get("log_losses", [])

        summary = {
            "total_trades": p["total_trades"],
            "win_rate": p["wins"] / n,
            "total_pnl": round(p["total_pnl"], 2),
            "avg_pnl_per_trade": round(p["total_pnl"] / n, 4),
            "brier_score_overall": round(np.mean(brier_all), 4) if brier_all else None,
            "brier_score_last_50": round(np.mean(brier_all[-50:]), 4) if len(brier_all) >= 10 else None,
            "log_loss_overall": round(np.mean(ll_all), 4) if ll_all else None,
            "by_city": {},
            "by_season": {},
            "bias_corrections": {},
        }

        # City breakdown
        for city, stats in p.get("by_city", {}).items():
            cn = max(1, stats["trades"])
            summary["by_city"][city] = {
                "trades": stats["trades"],
                "pnl": round(stats["pnl"], 2),
                "avg_brier": round(np.mean(stats["brier"][-100:]), 4) if stats["brier"] else None,
            }

        # Season breakdown
        for season, stats in p.get("by_season", {}).items():
            sn = max(1, stats["trades"])
            summary["by_season"][season] = {
                "trades": stats["trades"],
                "pnl": round(stats["pnl"], 2),
                "avg_brier": round(np.mean(stats["brier"][-100:]), 4) if stats["brier"] else None,
            }

        # Current bias corrections
        for key, bias in self.bias_tracker.get("biases", {}).items():
            count = self.bias_tracker.get("counts", {}).get(key, 0)
            if count >= 5:
                corrected = bias / (1 - EWMA_BETA ** count)
                summary["bias_corrections"][key] = round(corrected, 4)

        return summary


# ═══════════════════════════════════════════════════════════════════════
# 5. TRADE DECISION ENGINE
# ═══════════════════════════════════════════════════════════════════════

class TradeDecisionEngine:
    """
    Core decision logic: compare calibrated model probability against
    Kalshi market prices and determine optimal trade execution.

    Incorporates:
      - NGR-calibrated probability estimates
      - Favourite-longshot bias adjustments
      - EWMA bias corrections from trade history
      - Quarter-Kelly position sizing
      - Minimum edge thresholds
    """

    def __init__(self, learner: AdaptiveLearner):
        self.learner = learner

    def evaluate_contract(
        self,
        model_prob: float,
        market_price: float,
        city: str,
        target_date: str,
        bankroll: float,
        ticker: str = "",
        bracket_desc: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a single Kalshi contract for trading opportunity.

        Args:
            model_prob: Calibrated P(bracket settles YES) from NGR
            market_price: Current Kalshi YES price (0.01 to 0.99)
            city: City key for bias lookup
            target_date: Target date string (YYYY-MM-DD)
            bankroll: Current available bankroll
            ticker: Kalshi contract ticker
            bracket_desc: Human-readable bracket description

        Returns:
            Trade signal dict or None if no trade warranted
        """
        season = self.learner.get_season(target_date)

        # Step 1: Apply EWMA bias correction from trade history
        bias_correction = self.learner.get_bias_correction(city, season)
        adjusted_prob = np.clip(model_prob - bias_correction, 0.001, 0.999)

        # Step 2: Determine optimal side (YES or NO)
        yes_edge = adjusted_prob - market_price
        no_edge = (1 - adjusted_prob) - (1 - market_price)  # equivalent: market_price - adjusted_prob

        # Pick the side with larger absolute edge.
        # Use >= so that when edges are equal (common due to the math),
        # we fall through to NO side which has the positive edge when YES is negative.
        if yes_edge > 0 and (yes_edge >= no_edge):
            side = "YES"
            raw_edge = yes_edge
        elif no_edge > 0:
            side = "NO"
            raw_edge = no_edge
        else:
            return None  # No positive edge on either side

        # Step 3: Apply favourite-longshot bias adjustment
        if side == "YES" and market_price < FLB_LONGSHOT_THRESHOLD:
            # Buying cheap YES contracts — market overprices these
            effective_edge = raw_edge - FLB_LONGSHOT_PENALTY
            flb_applied = True
        elif side == "NO" and market_price < FLB_LONGSHOT_THRESHOLD:
            # Selling overpriced longshots — FLB works in our favor
            effective_edge = raw_edge + 0.02  # Small bonus for FLB tailwind
            flb_applied = True
        else:
            effective_edge = raw_edge
            flb_applied = False

        # Step 4: Check minimum edge requirements
        edge_in_cents = effective_edge * 100
        if effective_edge < MIN_EDGE_PERCENT or edge_in_cents < MIN_EDGE_CENTS:
            return None

        # Step 5: Quarter-Kelly position sizing
        if side == "YES":
            p = adjusted_prob
            b = (1 - market_price) / market_price  # payout ratio
        else:
            p = 1 - adjusted_prob
            b = market_price / (1 - market_price)

        kelly_full = (p * b - (1 - p)) / b
        kelly_fraction = max(0, kelly_full * KELLY_FRACTION)

        # Cap at maximum position size
        position_size = min(kelly_fraction * bankroll, MAX_POSITION_PCT * bankroll)
        n_contracts = max(1, int(position_size / market_price)) if side == "YES" else \
                      max(1, int(position_size / (1 - market_price)))

        # Step 6: Compute expected value
        if side == "YES":
            ev = adjusted_prob * (1 - market_price) - (1 - adjusted_prob) * market_price
        else:
            ev = (1 - adjusted_prob) * market_price - adjusted_prob * (1 - market_price)

        return {
            "ticker": ticker,
            "side": side,
            "entry_price": market_price,
            "predicted_probability": round(adjusted_prob, 4),
            "raw_model_probability": round(model_prob, 4),
            "bias_correction_applied": round(bias_correction, 4),
            "raw_edge": round(raw_edge, 4),
            "effective_edge": round(effective_edge, 4),
            "flb_adjusted": flb_applied,
            "kelly_fraction": round(kelly_fraction, 4),
            "suggested_contracts": n_contracts,
            "expected_value": round(ev, 4),
            "bracket": bracket_desc,
            "city": city,
            "season": season,
            "target_date": target_date,
        }


# ═══════════════════════════════════════════════════════════════════════
# 6. MAIN ORCHESTRATOR — Ties Everything Together
# ═══════════════════════════════════════════════════════════════════════

class WeatherTradingSkill:
    """
    Main entry point for the OpenClaw weather trading skill.

    Call flow:
      1. scan_markets()     → Find today's open temperature contracts
      2. analyze_city()     → Run full ensemble + calibration for one city
      3. generate_signals() → Produce trade signals across all markets
      4. record_settlement() → Post-trade learning after settlement

    The skill is designed to be called periodically (e.g., every 1-4 hours)
    by OpenClaw's scheduler.
    """

    def __init__(self, bankroll: float = 75.0):
        self.bankroll = bankroll
        self.fetcher = WeatherDataFetcher()
        self.processor = EnsembleProcessor()
        self.calibrator = NGRCalibrator()
        self.learner = AdaptiveLearner()
        self.decision_engine = TradeDecisionEngine(self.learner)

    def analyze_city(
        self, city_key: str, target_date: str,
        bracket_thresholds: Optional[List[Tuple[float, float]]] = None,
        market_prices: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Full analysis pipeline for a single city on a target date.

        Args:
            city_key: Key from CITIES dict (e.g., "nyc")
            target_date: "YYYY-MM-DD" format
            bracket_thresholds: List of (low, high) bracket boundaries
            market_prices: Dict of ticker → current YES price

        Returns comprehensive analysis with trade signals.
        """
        city = CITIES[city_key]
        logger.info(f"\n{'='*60}")
        logger.info(f"ANALYZING: {city.name} | Target: {target_date}")
        logger.info(f"{'='*60}")

        # ── Step 1: Fetch all forecast data ──────────────────────────
        logger.info("Step 1: Fetching multi-model forecasts...")
        deterministic = self.fetcher.fetch_deterministic_forecasts(city, target_date)
        ensemble = self.fetcher.fetch_ensemble_forecasts(city, target_date)

        logger.info(f"  Deterministic models: {list(deterministic.keys())}")
        logger.info(f"  Ensemble models: {list(ensemble.keys())}")

        # ── Step 2: Compute ensemble statistics ──────────────────────
        logger.info("Step 2: Computing ensemble statistics...")
        try:
            stats = self.processor.compute_raw_ensemble_stats(deterministic, ensemble)
        except ValueError as e:
            logger.error(f"  No forecast data available: {e}")
            return {"error": str(e)}

        logger.info(
            f"  Ensemble: mean={stats['ensemble_mean']:.1f}°F, "
            f"std={stats['ensemble_std']:.1f}°F, "
            f"n_members={stats['n_members']}"
        )

        # ── Step 3: Get/use NGR calibration parameters ───────────────
        logger.info("Step 3: Applying NGR calibration...")
        alpha = city.ngr_alpha
        beta = city.ngr_beta
        gamma = city.ngr_gamma
        delta = city.ngr_delta
        logger.info(f"  NGR params: α={alpha:.2f}, β={beta:.3f}, γ={gamma:.2f}, δ={delta:.3f}")

        # ── Step 4: Compute bracket probabilities ────────────────────
        analysis = {
            "city": city.name,
            "city_key": city_key,
            "target_date": target_date,
            "forecast": {
                "ensemble_mean": stats["ensemble_mean"],  # NWS-anchored
                "raw_ensemble_mean": stats.get("raw_ensemble_mean"),
                "ensemble_std": stats["ensemble_std"],
                "n_members": stats["n_members"],
                "nws_forecast": stats.get("nws_forecast"),
                "nws_ensemble_gap": stats.get("nws_ensemble_gap"),
                "nws_blend_weight": stats.get("nws_blend_weight"),
                "model_vs_nws": stats.get("model_vs_nws", {}),
                "deterministic": deterministic,
            },
            "brackets": [],
            "signals": [],
        }

        # Warn if NWS is missing — reduced confidence in settlement prediction
        if stats.get("nws_forecast") is None:
            analysis["warnings"] = analysis.get("warnings", [])
            analysis["warnings"].append(
                "NWS forecast unavailable. Settlement prediction relies on "
                "ensemble-only mean without settlement-source anchoring. "
                "Consider reducing position sizes."
            )

        if bracket_thresholds:
            logger.info(f"Step 4: Computing probabilities for {len(bracket_thresholds)} brackets...")

            for bracket_low, bracket_high in bracket_thresholds:
                prob = self.calibrator.calibrated_bracket_probability(
                    stats["ensemble_mean"], stats["ensemble_std"],
                    bracket_low, bracket_high,
                    alpha, beta, gamma, delta
                )

                # Raw ensemble probability for comparison
                if bracket_high != float('inf') and bracket_low != float('-inf'):
                    mid = (bracket_low + bracket_high) / 2
                    raw_prob = self.processor.raw_member_probability(ensemble, mid)
                else:
                    raw_prob = None

                bracket_desc = f"{bracket_low}°F to {bracket_high}°F"
                bracket_info = {
                    "bracket_low": bracket_low,
                    "bracket_high": bracket_high,
                    "description": bracket_desc,
                    "calibrated_probability": round(prob, 4),
                    "raw_ensemble_probability": round(raw_prob, 4) if raw_prob else None,
                }

                # If we have market prices, evaluate for trading
                if market_prices:
                    # Try to find matching ticker
                    for ticker, price in market_prices.items():
                        if self._ticker_matches_bracket(ticker, bracket_low, bracket_high):
                            signal = self.decision_engine.evaluate_contract(
                                model_prob=prob,
                                market_price=price,
                                city=city_key,
                                target_date=target_date,
                                bankroll=self.bankroll,
                                ticker=ticker,
                                bracket_desc=bracket_desc,
                            )
                            if signal:
                                analysis["signals"].append(signal)
                                bracket_info["signal"] = signal
                            bracket_info["market_price"] = price
                            bracket_info["ticker"] = ticker

                analysis["brackets"].append(bracket_info)

        # ── Summary ──────────────────────────────────────────────────
        n_signals = len(analysis["signals"])
        logger.info(f"\nResult: {n_signals} trade signal(s) generated")
        for sig in analysis["signals"]:
            logger.info(
                f"  → {sig['side']} {sig['ticker']} @ {sig['entry_price']:.2f} | "
                f"Edge: {sig['effective_edge']:.1%} | "
                f"Contracts: {sig['suggested_contracts']}"
            )

        return analysis

    def _ticker_matches_bracket(
        self, ticker: str, bracket_low: float, bracket_high: float
    ) -> bool:
        """Heuristic to match a Kalshi ticker to a temperature bracket."""
        # Kalshi tickers look like: KXHIGHNY-26MAR03-B62
        # where B62 means the bracket around 62°F
        # This is a simplified matcher — production should use Kalshi API
        try:
            parts = ticker.split("-")
            bracket_part = parts[-1]  # e.g., "B62"
            if bracket_part.startswith("B"):
                bracket_temp = float(bracket_part[1:])
                return bracket_low <= bracket_temp <= bracket_high
        except (IndexError, ValueError):
            pass
        return False

    def retrain_calibration(self, city_key: str) -> Tuple[float, ...]:
        """
        Retrain NGR parameters using Open-Meteo Previous Runs API data.

        Should be called weekly or when performance degrades.
        Returns: (alpha, beta, gamma, delta) fitted parameters
        """
        city = CITIES[city_key]
        logger.info(f"\nRetraining NGR calibration for {city.name}...")

        # Fetch previous model runs vs observations
        data = self.fetcher.fetch_previous_runs(city, past_days=NGR_TRAINING_DAYS)

        if not data or "daily" not in data:
            logger.warning("  Insufficient data for retraining. Keeping current params.")
            return (city.ngr_alpha, city.ngr_beta, city.ngr_gamma, city.ngr_delta)

        daily = data["daily"]
        dates = daily.get("time", [])
        observed = daily.get("temperature_2m_max", [])  # Day-0 ≈ actual
        forecast_d1 = daily.get("temperature_2m_max_previous_day1", [])

        # Build training arrays (only where all data is present)
        M_train, S_train, y_train = [], [], []
        for i in range(len(dates)):
            obs = observed[i] if i < len(observed) else None
            fc1 = forecast_d1[i] if i < len(forecast_d1) else None

            if obs is not None and fc1 is not None:
                # Use forecast as ensemble mean proxy
                M_train.append(fc1)
                # Estimate spread from forecast-observation gap history
                # (crude but effective — will be replaced with actual ensemble data)
                S_train.append(3.0)  # Default spread; refined with more data
                y_train.append(obs)

        if len(y_train) < 15:
            logger.warning(f"  Only {len(y_train)} training samples. Need ≥15.")
            return (city.ngr_alpha, city.ngr_beta, city.ngr_gamma, city.ngr_delta)

        M_arr = np.array(M_train)
        S_arr = np.array(S_train)
        y_arr = np.array(y_train)

        # Compute actual spread from forecast errors for better S estimation
        errors = y_arr - M_arr
        rolling_std = np.std(errors)
        S_arr = np.full_like(S_arr, rolling_std)

        # Fit NGR
        alpha, beta, gamma, delta = self.calibrator.fit_ngr(M_arr, S_arr, y_arr)

        # Update city config
        city.ngr_alpha = alpha
        city.ngr_beta = beta
        city.ngr_gamma = gamma
        city.ngr_delta = delta

        logger.info(f"  Updated {city.name}: α={alpha:.2f}, β={beta:.3f}, γ={gamma:.2f}, δ={delta:.3f}")
        logger.info(f"  Training RMSE: {np.sqrt(np.mean(errors**2)):.2f}°F")
        logger.info(f"  Training bias: {np.mean(errors):+.2f}°F")

        return (alpha, beta, gamma, delta)

    def record_settlement(
        self,
        trade: Dict[str, Any],
        actual_temperature: float,
        settled_yes: bool,
        model_forecasts: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Record a trade settlement and update the learning system.

        Call this after each Kalshi settlement (10 AM ET daily).

        Args:
            trade: The original trade signal dict
            actual_temperature: The CLI-reported temperature (°F)
            settled_yes: Whether the contract settled YES
            model_forecasts: Optional dict of each model's forecast for this date,
                             used to track which model best predicts CLI settlements.
                             e.g. {"nws": 63.0, "gfs_seamless": 62.5, "ecmwf_ifs025": 63.8}
        """
        actual_outcome = 1 if settled_yes else 0

        # ── Per-model settlement accuracy tracking ───────────────────
        # This is the key learning signal: which model best predicts
        # the NWS CLI value that Kalshi actually settles on?
        model_errors = {}
        if model_forecasts:
            for model_name, forecast_val in model_forecasts.items():
                if forecast_val is not None:
                    error = forecast_val - actual_temperature
                    model_errors[model_name] = round(error, 2)

            # Log which model was closest to settlement
            if model_errors:
                closest_model = min(model_errors, key=lambda k: abs(model_errors[k]))
                logger.info(
                    f"  CLI settlement: {actual_temperature}°F | "
                    f"Closest model: {closest_model} (error: {model_errors[closest_model]:+.1f}°F)"
                )
                if "nws" in model_errors:
                    nws_err = model_errors["nws"]
                    logger.info(
                        f"  NWS forecast error vs CLI: {nws_err:+.1f}°F | "
                        f"{'NWS was closest' if closest_model == 'nws' else f'{closest_model} beat NWS'}"
                    )

        # Build full trade record for journal
        full_record = {
            "trade_id": trade.get("trade_id", str(uuid.uuid4())),
            "market": {
                "ticker": trade.get("ticker", ""),
                "city": trade.get("city", ""),
                "target_date": trade.get("target_date", ""),
                "bracket": trade.get("bracket", ""),
            },
            "entry": {
                "entry_price": trade.get("entry_price", 0),
                "side": trade.get("side", ""),
                "predicted_probability": trade.get("predicted_probability", 0),
                "raw_model_probability": trade.get("raw_model_probability", 0),
                "bias_correction_applied": trade.get("bias_correction_applied", 0),
                "effective_edge": trade.get("effective_edge", 0),
                "kelly_fraction": trade.get("kelly_fraction", 0),
                "flb_adjusted": trade.get("flb_adjusted", False),
            },
            "settlement": {
                "actual_temperature_f": actual_temperature,
                "outcome": "win" if (
                    (trade.get("side") == "YES" and settled_yes) or
                    (trade.get("side") == "NO" and not settled_yes)
                ) else "loss",
                "settled_yes": settled_yes,
                "model_errors_vs_cli": model_errors,  # NEW: per-model error vs settlement
                "closest_model_to_cli": min(model_errors, key=lambda k: abs(model_errors[k])) if model_errors else None,
            },
        }

        # Log the trade
        self.learner.log_trade(full_record)

        # Update performance metrics and bias tracker
        metrics = self.learner.record_outcome(full_record, actual_outcome, actual_temperature)

        # Update per-model bias trackers (learn which models drift from CLI)
        if model_errors:
            city = trade.get("city", "unknown")
            season = self.learner.get_season(trade.get("target_date", "2026-01-01"))
            for model_name, error in model_errors.items():
                # Track each model's error vs CLI separately
                model_key = f"{city}|{season}|{model_name}"
                self.learner.update_bias(
                    city=f"{city}_model_{model_name}",
                    season=season,
                    forecast_error=error / 10.0,  # Normalize temp error to ~probability scale
                )

        return metrics

    def get_status_report(self) -> str:
        """Generate a human-readable status report."""
        summary = self.learner.get_performance_summary()

        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║  WEATHER TRADING SKILL — PERFORMANCE REPORT             ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            f"  Total trades:     {summary['total_trades']}",
            f"  Win rate:         {summary['win_rate']:.1%}",
            f"  Total P&L:        ${summary['total_pnl']:+.2f}",
            f"  Avg P&L/trade:    ${summary['avg_pnl_per_trade']:+.4f}",
            f"  Brier (overall):  {summary.get('brier_score_overall', 'N/A')}",
            f"  Brier (last 50):  {summary.get('brier_score_last_50', 'N/A')}",
            f"  Log loss:         {summary.get('log_loss_overall', 'N/A')}",
            "",
            "  ── BY CITY ──",
        ]

        for city, stats in summary.get("by_city", {}).items():
            lines.append(
                f"    {city:12s}  trades={stats['trades']:3d}  "
                f"P&L=${stats['pnl']:+.2f}  Brier={stats.get('avg_brier', 'N/A')}"
            )

        lines.append("")
        lines.append("  ── BY SEASON ──")
        for season, stats in summary.get("by_season", {}).items():
            lines.append(
                f"    {season:12s}  trades={stats['trades']:3d}  "
                f"P&L=${stats['pnl']:+.2f}  Brier={stats.get('avg_brier', 'N/A')}"
            )

        lines.append("")
        lines.append("  ── ACTIVE BIAS CORRECTIONS ──")
        for key, correction in summary.get("bias_corrections", {}).items():
            direction = "overestimates" if correction > 0 else "underestimates"
            lines.append(f"    {key:20s}  {direction} by {abs(correction):.1%}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 7. OPENCLAW SKILL INTERFACE
# ═══════════════════════════════════════════════════════════════════════

def create_skill_prompt() -> str:
    """
    Returns the system prompt that OpenClaw should use when invoking
    this skill. This defines the AI agent's behavior and decision-making.
    """
    return """You are an expert weather trader operating on Kalshi prediction markets.
Your job is to find and exploit pricing inefficiencies in daily high temperature
bracket contracts using a multi-model ensemble approach ANCHORED TO THE NWS
SETTLEMENT SOURCE.

## ⚠ RULE #1: NWS IS THE SETTLEMENT SOURCE — EVERYTHING ELSE IS SUPPORT

Kalshi temperature contracts settle EXCLUSIVELY on the NWS Daily Climate Report
(CLI). Not METAR. Not AccuWeather. Not any model output. The CLI from the specific
NWS station (e.g., KNYC for NYC Central Park) is the ONLY thing that determines
who gets paid. This has critical implications:

- The NWS forecast is not "just another model" — it is the settlement source's
  own prediction of its own report. Give it privileged weight.
- When NWS disagrees with the ensemble by >3°F, INCREASE NWS weighting to 50%.
  The settlement source is more likely to match its own forecast than ECMWF.
- If NWS is unavailable, REDUCE position sizes by 50%. You're trading blind
  on the settlement source.
- Track NWS forecast errors vs CLI separately from other models. This is your
  primary calibration signal.

## YOUR TRADING PROCESS

1. **NWS First**: Always fetch the NWS hourly forecast for the settlement station
   FIRST. This is your anchor. Then fetch Open-Meteo models for uncertainty.

2. **Multi-Model Ensemble**: Fetch GFS (31-member) and ECMWF (51-member) ensembles
   via Open-Meteo for probability estimation. The ensemble provides uncertainty
   bands that NWS alone cannot.

3. **NWS-Anchored Mean**: The forecast mean used for pricing is a blend:
   - Normal: 35% NWS + 65% calibrated ensemble mean
   - High disagreement (>3°F gap): 50% NWS + 50% ensemble mean
   - NWS unavailable: 100% ensemble mean (reduce position sizes)

4. **NGR Calibration**: Apply Non-Homogeneous Gaussian Regression:
     Y ~ N(α + β·M, γ + δ·S²)
   where M = NWS-anchored ensemble mean, S = ensemble std

5. **Edge Detection**: Compare calibrated P(bracket) vs Kalshi market price.
   - Minimum 8% edge required to trade
   - Extra 5% edge required for contracts priced below 15¢ (FLB adjustment)
   - Prefer selling overpriced longshots (NO side on cheap YES contracts)

6. **Position Sizing**: Use quarter-Kelly criterion, capped at 10% of bankroll.
   ALWAYS use limit orders (maker fees are 4× lower than taker).

7. **Settlement Learning**: After EVERY settlement, record:
   - The actual CLI temperature
   - Each model's forecast error vs CLI (not vs METAR, not vs "truth" — vs CLI)
   - Whether NWS or another model was closest to CLI
   - Update EWMA bias trackers stratified by (city, season, model)

## SETTLEMENT MECHANICS (KNOW THESE COLD)

- CLI is published the morning after the temperature date
- Kalshi reads CLI at 10:00 AM ET; delayed to 12:00 PM if CLI conflicts with METAR
- CLI uses Local Standard Time YEAR-ROUND (not daylight saving time!)
- During DST: measurement window runs 1:00 AM daylight → 12:59 AM next day
- Late-night temperature spikes can count toward the "previous" day during DST
- ASOS stations measure in Celsius → converted to Fahrenheit with rounding
  (0.5°C boundaries create sharp probability cliffs — know the C→F table)

## CRITICAL RULES

- NEVER trade without NWS forecast unless you halve position sizes
- NEVER trade without ensemble data from at least 2 models
- ALWAYS apply the FLB penalty when buying contracts under 15¢
- ALWAYS use limit orders for maker fee rates
- If rolling Brier score (last 50 trades) exceeds 0.25, STOP trading and retrain
- If cumulative P&L drops below -20% of starting bankroll, STOP and alert user

## WHEN TO BE AGGRESSIVE vs CONSERVATIVE

- **Aggressive** (lower edge to 6%): NWS and ensemble agree within 1°F, HRRR
  updated within 2 hours, target within 24h.
- **Conservative** (raise edge to 12%): Frontal passage expected, model spread >4°F,
  OR NWS disagrees with ensemble by >5°F (high uncertainty on settlement value).
- **No trade**: NWS unavailable AND ensemble spread >5°F. Also skip: atmospheric
  rivers, derechos, or severe weather watches creating extreme outlier risk.
"""


# ═══════════════════════════════════════════════════════════════════════
# EXAMPLE USAGE / TESTING
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Quick test: analyze NYC temperature for tomorrow.
    In production, OpenClaw calls analyze_city() with actual Kalshi market data.
    """
    from datetime import date

    skill = WeatherTradingSkill(bankroll=75.0)

    # Tomorrow's date
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # Example bracket thresholds (would come from Kalshi market discovery)
    # These represent typical bracket boundaries: e.g., <58, 58-60, 60-62, 62-64, 64-66, >66
    example_brackets = [
        (float('-inf'), 58),
        (58, 60),
        (60, 62),
        (62, 64),
        (64, 66),
        (66, float('inf')),
    ]

    # Example market prices (would come from Kalshi orderbook API)
    example_prices = {
        "KXHIGHNY-TEST-B56": 0.08,
        "KXHIGHNY-TEST-B59": 0.15,
        "KXHIGHNY-TEST-B61": 0.30,
        "KXHIGHNY-TEST-B63": 0.32,
        "KXHIGHNY-TEST-B65": 0.12,
        "KXHIGHNY-TEST-B67": 0.03,
    }

    # Run full analysis
    result = skill.analyze_city(
        city_key="nyc",
        target_date=tomorrow,
        bracket_thresholds=example_brackets,
        market_prices=example_prices,
    )

    # Print results
    print("\n" + json.dumps(result, indent=2, default=str))

    # Print status report
    print("\n" + skill.get_status_report())

    # Example: retrain calibration
    print("\n--- Retraining NGR calibration ---")
    skill.retrain_calibration("nyc")
