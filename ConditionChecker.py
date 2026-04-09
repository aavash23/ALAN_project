"""
LIGHT Team Night-Decision Dashboard — Data Fetcher
Weber State University ALAN and Migration Study
=====================================================
Fetches all forecast inputs needed by the decision model.
Run this in Colab, then open light_dashboard.html in a browser (or serve it).

Install:
    !pip install requests

Usage in Colab:
    Run all cells. Edit CONFIG at the top.
"""

import requests
import json
import math
import random
from datetime import datetime, date, timedelta

# ─────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────
# W impact site coordinates (decimal degrees, west longitude negative)
SITE_LAT  = 41.195081
SITE_LON  = -111.930968
SITE_NAME = "W Impact Site"

# BirdCast API — set your token if you have one; otherwise uses demo mode
BIRDCAST_API_KEY = ""   # leave blank for demo / manual override

# Season: "spring" (Mar–Jun) or "fall" (Jul–Nov)
SEASON = "spring"

# Treatment tracking — update counts after each completed usable night
TREATMENT_COUNTS = {
    "Dark":     {"ON": 0, "OFF": 0, "PURPLE": 0},
    "Moderate": {"ON": 0, "OFF": 0, "PURPLE": 0},
    "Bright":   {"ON": 0, "OFF": 0, "PURPLE": 0},
}

# Readiness flags — set before each deployment
STAFFING_READY   = True
EQUIPMENT_READY  = True
FACILITIES_READY = True

HEADERS = {
    "User-Agent": (
        "LIGHT-Dashboard/1.0 Weber State University "
        "contact: research@weber.edu"
    )
}

# ─────────────────────────────────────────────────────────────────
#  1. NWS WEATHER FORECAST
# ─────────────────────────────────────────────────────────────────
def fetch_nws(lat, lon):
    """Fetch hourly + gridded forecast from NOAA NWS."""
    out = {
        "source": "NOAA/NWS",
        "forecast_temperature_f": None,
        "forecast_wind_speed_mph": None,
        "forecast_wind_gust_mph": None,
        "forecast_wind_direction_deg": None,
        "forecast_precipitation_probability": None,
        "forecast_precipitation_amount": None,
        "forecast_thunderstorm_risk": False,
        "forecast_visibility_mi": None,
        "forecast_pressure_mb": None,
        "forecast_surface_icing_risk": False,
        "raw_periods": [],
        "error": None,
    }
    try:
        # Step 1: resolve grid
        r = requests.get(
            f"https://api.weather.gov/points/{lat},{lon}",
            headers=HEADERS, timeout=12
        )
        r.raise_for_status()
        props = r.json()["properties"]

        # Step 2: hourly forecast (use ~7–10 PM window = periods 0–5 approx)
        rh = requests.get(props["forecastHourly"], headers=HEADERS, timeout=12)
        rh.raise_for_status()
        periods = rh.json()["properties"]["periods"]

        # Find periods in 7 PM – 10 PM window tonight
        tonight = date.today()
        window = []
        for p in periods:
            start = datetime.fromisoformat(p["startTime"])
            if start.date() == tonight and 19 <= start.hour <= 22:
                window.append(p)

        target_periods = window if window else periods[:4]

        # Aggregate window values
        temps, winds, gusts, precips = [], [], [], []
        for p in target_periods:
            if p.get("temperature"):
                temps.append(p["temperature"])
            ws_str = p.get("windSpeed", "0 mph")
            import re
            nums = re.findall(r"\d+", str(ws_str))
            if nums:
                winds.append(int(nums[-1]))  # take max if range
            prec = p.get("probabilityOfPrecipitation", {})
            if prec and prec.get("value") is not None:
                precips.append(prec["value"])
            fc = p.get("shortForecast", "").lower()
            if any(x in fc for x in ["thunder", "storm", "t-storm"]):
                out["forecast_thunderstorm_risk"] = True
            if any(x in fc for x in ["ice", "freezing", "sleet", "glaze"]):
                out["forecast_surface_icing_risk"] = True

        out["forecast_temperature_f"]             = round(sum(temps)/len(temps)) if temps else None
        out["forecast_wind_speed_mph"]            = max(winds) if winds else None
        out["forecast_precipitation_probability"] = round(sum(precips)/len(precips)) if precips else 0
        out["forecast_precipitation_amount"]      = 0  # populated from gridData below

        # Gusts from first window period
        gust_str = target_periods[0].get("windSpeed", "") if target_periods else ""
        nums = re.findall(r"\d+", str(gust_str))
        out["forecast_wind_gust_mph"] = int(nums[-1]) + 5 if nums else None  # estimate

        # Wind direction — from first period wind direction string → degrees
        wd_str = target_periods[0].get("windDirection", "N") if target_periods else "N"
        out["forecast_wind_direction_deg"] = compass_to_deg(wd_str)

        # Step 3: gridded data for pressure + precip amount + visibility
        rg = requests.get(props["forecastGridData"], headers=HEADERS, timeout=12)
        rg.raise_for_status()
        gdata = rg.json()["properties"]

        # Pressure (convert Pa → mb)
        pressure_vals = gdata.get("pressure", {}).get("values", [])
        if pressure_vals:
            out["forecast_pressure_mb"] = round(pressure_vals[-1]["value"] / 100, 1)

        # Visibility (convert m → miles)
        vis_vals = gdata.get("visibility", {}).get("values", [])
        if vis_vals:
            out["forecast_visibility_mi"] = round(vis_vals[-1]["value"] * 0.000621371, 1)

        # Precip amount (mm → inches)
        qa = gdata.get("quantitativePrecipitation", {}).get("values", [])
        if qa:
            out["forecast_precipitation_amount"] = round(qa[-1]["value"] * 0.0393701, 2)

        # Save raw periods
        out["raw_periods"] = [
            {
                "name": p.get("name", ""),
                "temperature": p.get("temperature"),
                "windSpeed": p.get("windSpeed"),
                "windDirection": p.get("windDirection"),
                "shortForecast": p.get("shortForecast"),
                "precipPct": p.get("probabilityOfPrecipitation", {}).get("value", 0),
                "startTime": p.get("startTime"),
            }
            for p in periods[:8]
        ]

    except Exception as e:
        out["error"] = str(e)
        print(f"  [NWS] Error: {e}")

    return out


def compass_to_deg(s):
    """Convert compass string (NW, SSE, etc.) to degrees."""
    mapping = {
        "N":0,"NNE":22,"NE":45,"ENE":67,"E":90,"ESE":112,"SE":135,"SSE":157,
        "S":180,"SSW":202,"SW":225,"WSW":247,"W":270,"WNW":292,"NW":315,"NNW":337,
    }
    return mapping.get(s.strip().upper(), 0)


# ─────────────────────────────────────────────────────────────────
#  2. AVIATION WEATHER CENTER (AWC) — METAR + TAF at KOGD
# ─────────────────────────────────────────────────────────────────
def fetch_awc():
    """Fetch METAR and TAF from Aviation Weather Center for KOGD."""
    out = {
        "source": "AWC",
        "station": "KOGD",
        "metar_raw": None,
        "taf_raw": None,
        "metar_wind_speed_kt": None,
        "metar_wind_gust_kt": None,
        "metar_wind_dir_deg": None,
        "metar_visibility_sm": None,
        "metar_ceiling_ft": None,
        "metar_present_weather": None,
        "error": None,
    }
    try:
        import re
        # METAR
        mr = requests.get(
            "https://aviationweather.gov/api/data/metar?ids=KOGD&format=raw",
            headers=HEADERS, timeout=10
        )
        if mr.status_code == 200:
            raw = mr.text.strip()
            out["metar_raw"] = raw
            # Parse wind: e.g. 27012KT or 27012G18KT
            wm = re.search(r"(\d{3})(\d{2,3})(?:G(\d{2,3}))?KT", raw)
            if wm:
                out["metar_wind_dir_deg"]  = int(wm.group(1))
                out["metar_wind_speed_kt"] = int(wm.group(2))
                out["metar_wind_gust_kt"]  = int(wm.group(3)) if wm.group(3) else None
            # Visibility: e.g. 10SM
            vm = re.search(r"(\d+(?:/\d+)?)\s*SM", raw)
            if vm:
                out["metar_visibility_sm"] = float(vm.group(1))
            # Ceiling: BKN or OVC layer
            cm = re.search(r"(?:BKN|OVC)(\d{3})", raw)
            if cm:
                out["metar_ceiling_ft"] = int(cm.group(1)) * 100
            # Present weather
            pw_codes = re.findall(r"\b(TS|RA|SN|FG|BR|DZ|SQ|GR|GS|PL|IC|UP|FZRA|FZDZ)\b", raw)
            out["metar_present_weather"] = " ".join(pw_codes) if pw_codes else "None"

        # TAF
        tr = requests.get(
            "https://aviationweather.gov/api/data/taf?ids=KOGD&format=raw",
            headers=HEADERS, timeout=10
        )
        if tr.status_code == 200:
            out["taf_raw"] = tr.text.strip()[:500]  # truncate for display

    except Exception as e:
        out["error"] = str(e)
        print(f"  [AWC] Error: {e}")

    return out


# ─────────────────────────────────────────────────────────────────
#  3. BIRDCAST — migration forecast category
# ─────────────────────────────────────────────────────────────────
def fetch_birdcast(lat, lon, api_key=""):
    """
    Fetch BirdCast migration forecast category.
    BirdCast's regional forecast API is limited access.
    Falls back to a manual override prompt if no key is available.
    """
    out = {
        "source": "BirdCast",
        "forecast_birdcast_category": None,  # "High", "Medium", "Low"
        "note": "",
        "error": None,
    }

    if not api_key:
        out["note"] = (
            "BirdCast API key not set. "
            "Visit https://birdcast.info to check today's regional forecast, "
            "then set BIRDCAST_CATEGORY manually below."
        )
        out["forecast_birdcast_category"] = BIRDCAST_CATEGORY_OVERRIDE
        return out

    try:
        # BirdCast regional forecast endpoint (requires approved access)
        r = requests.get(
            f"https://birdcast.info/api/forecast?lat={lat}&lon={lon}",
            headers={**HEADERS, "Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        category = data.get("migration_intensity", "Low").capitalize()
        if category not in ("High", "Medium", "Low"):
            category = "Low"
        out["forecast_birdcast_category"] = category
    except Exception as e:
        out["error"] = str(e)
        out["forecast_birdcast_category"] = BIRDCAST_CATEGORY_OVERRIDE
        out["note"] = f"API error — using manual override: {BIRDCAST_CATEGORY_OVERRIDE}"

    return out


# Manual override — set this if BirdCast API is unavailable
# Check https://birdcast.info/migration-tools/live-migration-maps/
BIRDCAST_CATEGORY_OVERRIDE = "Medium"  # "High", "Medium", or "Low"


# ─────────────────────────────────────────────────────────────────
#  4. USNO — LUNAR ILLUMINATION
# ─────────────────────────────────────────────────────────────────
def fetch_usno(lat, lon, target_date=None):
    """Fetch lunar illumination, phase, rise/set from USNO."""
    if target_date is None:
        target_date = date.today()

    out = {
        "source": "USNO",
        "forecast_moon_illumination_pct": None,
        "forecast_moon_phase": None,
        "forecast_moonrise_time": None,
        "forecast_moonset_time": None,
        "lunar_bin": None,
        "error": None,
    }

    try:
        date_str = target_date.strftime("%Y-%m-%d")
        url = (
            f"https://aa.usno.navy.mil/api/rstt/oneday"
            f"?date={date_str}&coords={lat},{lon}&tz=-6&dst=true"
        )
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()

        props = data.get("properties", {})
        data_section = props.get("data", {})

        # Illumination — listed under curphase or fracillum
        illum = data_section.get("fracillum")
        if illum is not None:
            # May be a string like "52%" or a float
            if isinstance(illum, str):
                illum = float(illum.replace("%", ""))
            out["forecast_moon_illumination_pct"] = round(float(illum))
        
        # Phase
        out["forecast_moon_phase"] = data_section.get("curphase", "Unknown")

        # Rise / set times
        moon_data = data_section.get("moondata", [])
        for entry in moon_data:
            phen = entry.get("phen", "")
            time_val = entry.get("time", "")
            if phen == "Rise":
                out["forecast_moonrise_time"] = time_val
            elif phen == "Set":
                out["forecast_moonset_time"] = time_val

        # Assign lunar bin
        illum_pct = out["forecast_moon_illumination_pct"]
        if illum_pct is not None:
            if illum_pct <= 24:
                out["lunar_bin"] = "Dark"
            elif illum_pct <= 74:
                out["lunar_bin"] = "Moderate"
            else:
                out["lunar_bin"] = "Bright"

    except Exception as e:
        out["error"] = str(e)
        print(f"  [USNO] Error: {e}")

    return out


# ─────────────────────────────────────────────────────────────────
#  5. PRESSURE TREND (24h comparison)
# ─────────────────────────────────────────────────────────────────
def fetch_pressure_trend(lat, lon):
    """
    Get current pressure and estimate 24h trend via Open-Meteo
    (free, no key, includes hourly pressure history).
    """
    out = {
        "source": "Open-Meteo",
        "current_pressure_mb": None,
        "pressure_24h_ago_mb": None,
        "pressure_change_24h_mb": None,
        "error": None,
    }
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=surface_pressure"
            f"&past_days=1&forecast_days=1&timezone=auto"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        pressures = data["hourly"]["surface_pressure"]
        times     = data["hourly"]["time"]

        now_hour = datetime.now().hour
        # Current = most recent available
        out["current_pressure_mb"]  = pressures[-(24 - now_hour) - 1] if len(pressures) >= 25 else pressures[-1]
        out["pressure_24h_ago_mb"]  = pressures[max(0, len(pressures) - 25)]
        if out["current_pressure_mb"] and out["pressure_24h_ago_mb"]:
            out["pressure_change_24h_mb"] = round(
                out["current_pressure_mb"] - out["pressure_24h_ago_mb"], 1
            )
    except Exception as e:
        out["error"] = str(e)
        print(f"  [Pressure] Error: {e}")

    return out


# ─────────────────────────────────────────────────────────────────
#  6. SCORING ENGINE
# ─────────────────────────────────────────────────────────────────
def score_migration(weather, birdcast, pressure, season):
    """Apply the Migration Opportunity Score model from the spec."""
    scores = {}
    breakdown = {}

    # A. BirdCast category (max 40)
    cat = birdcast.get("forecast_birdcast_category", "Low")
    bc_score = {"High": 40, "Medium": 25, "Low": 5}.get(cat, 5)
    scores["birdcast"] = bc_score
    breakdown["birdcast"] = f"{cat} → {bc_score}/40"

    # B. Precipitation probability (max 15)
    precip_pct = weather.get("forecast_precipitation_probability", 0) or 0
    if precip_pct < 15:
        pr_score = 15
    elif precip_pct < 35:
        pr_score = 8
    elif precip_pct < 70:
        pr_score = 3
    else:
        pr_score = 0
    scores["precipitation"] = pr_score
    breakdown["precipitation"] = f"{precip_pct}% → {pr_score}/15"

    # C. Wind direction (max 10)
    wd = weather.get("forecast_wind_direction_deg", 0) or 0
    if season.lower() == "spring":
        if 135 <= wd <= 225:
            wd_score = 10
        elif (90 <= wd <= 134) or (226 <= wd <= 270):
            wd_score = 5
        else:
            wd_score = 0
    else:  # fall
        if (315 <= wd <= 360) or (0 <= wd <= 45):
            wd_score = 10
        elif (46 <= wd <= 89) or (271 <= wd <= 314):
            wd_score = 5
        else:
            wd_score = 0
    scores["wind_direction"] = wd_score
    breakdown["wind_direction"] = f"{wd}° → {wd_score}/10"

    # D. Wind speed (max 10)
    ws = weather.get("forecast_wind_speed_mph", 0) or 0
    if ws <= 5:
        ws_score = 2
    elif ws <= 15:
        ws_score = 8
    elif ws <= 25:
        ws_score = 10
    elif ws <= 35:
        ws_score = 5
    else:
        ws_score = 0
    scores["wind_speed"] = ws_score
    breakdown["wind_speed"] = f"{ws} mph → {ws_score}/10"

    # E. Pressure trend (max 10)
    dp = pressure.get("pressure_change_24h_mb")
    if dp is None:
        pt_score = 4  # assume stable
        trend_label = "Unknown (stable assumed)"
    elif dp >= 3.0:
        pt_score = 10; trend_label = f"+{dp} mb — Rising strongly"
    elif dp >= 1.0:
        pt_score = 7;  trend_label = f"+{dp} mb — Rising modestly"
    elif dp >= -0.9:
        pt_score = 4;  trend_label = f"{dp} mb — Stable"
    elif dp >= -2.9:
        pt_score = 2;  trend_label = f"{dp} mb — Falling modestly"
    else:
        pt_score = 0;  trend_label = f"{dp} mb — Falling strongly"
    scores["pressure"] = pt_score
    breakdown["pressure"] = f"{trend_label} → {pt_score}/10"

    # F. Temperature (max 10)
    temp = weather.get("forecast_temperature_f", 50) or 50
    if temp >= 55:
        t_score = 10
    elif temp >= 50:
        t_score = 8
    elif temp >= 45:
        t_score = 6
    elif temp >= 40:
        t_score = 4
    else:
        t_score = 2
    scores["temperature"] = t_score
    breakdown["temperature"] = f"{temp}°F → {t_score}/10"

    total = sum(scores.values())
    if total >= 70:
        interpretation = "Strong migration opportunity"
    elif total >= 50:
        interpretation = "Moderate migration opportunity"
    else:
        interpretation = "Weak migration opportunity"

    return {
        "total": total,
        "max": 95,
        "scores": scores,
        "breakdown": breakdown,
        "interpretation": interpretation,
    }


def assess_field_conditions(weather, awc):
    """Apply the Field Conditions Screen from the spec."""
    hard_stops = []
    field_ratings = {}

    ws   = weather.get("forecast_wind_speed_mph", 0) or 0
    wg   = weather.get("forecast_wind_gust_mph", 0) or 0
    pct  = weather.get("forecast_precipitation_probability", 0) or 0
    vis  = weather.get("forecast_visibility_mi", 10) or 10
    temp = weather.get("forecast_temperature_f", 60) or 60
    thunder = weather.get("forecast_thunderstorm_risk", False)
    icing   = weather.get("forecast_surface_icing_risk", False)

    # Hard stop checks
    if thunder:           hard_stops.append("Thunderstorm risk")
    if ws > 15:           hard_stops.append(f"Sustained wind {ws} mph > 15 mph limit")
    if wg > 25:           hard_stops.append(f"Wind gusts {wg} mph > 25 mph limit")
    if vis < 1.0:         hard_stops.append(f"Visibility {vis} mi < 1.0 mi limit")
    if icing:             hard_stops.append("Surface icing risk")
    if pct >= 70:         hard_stops.append(f"Steady precipitation expected ({pct}%)")
    if not STAFFING_READY:   hard_stops.append("Staffing not ready")
    if not EQUIPMENT_READY:  hard_stops.append("Equipment not ready")
    if not FACILITIES_READY: hard_stops.append("Facilities not ready")

    # Field condition ratings
    def rate(val, good, acceptable):
        if val <= good:    return "Good"
        if val <= acceptable: return "Acceptable"
        return "Unacceptable"

    field_ratings["wind_sustained"] = rate(ws, 10, 15)
    field_ratings["wind_gusts"]     = rate(wg, 15, 25)
    field_ratings["visibility"]     = "Good" if vis >= 5 else ("Acceptable" if vis >= 1 else "Unacceptable")
    field_ratings["precipitation"]  = "Good" if pct < 15 else ("Acceptable" if pct < 35 else "Unacceptable")
    field_ratings["temperature"]    = (
        "Good"         if 40 <= temp <= 75 else
        "Acceptable"   if 30 <= temp <= 85 else
        "Unacceptable"
    )

    return {
        "hard_stops": hard_stops,
        "field_ratings": field_ratings,
        "hard_stop_triggered": len(hard_stops) > 0,
    }


def assign_treatment(lunar_bin, counts):
    """Assign ON / OFF / PURPLE based on treatment balance within lunar bin."""
    bin_counts = counts.get(lunar_bin, {"ON": 0, "OFF": 0, "PURPLE": 0})
    min_count  = min(bin_counts.values())
    candidates = [t for t, c in bin_counts.items() if c == min_count]
    return random.choice(candidates)


def make_decision(migration_score, field, lunar_bin, counts):
    """Apply the Final Night Decision rules from the spec."""
    hard_stop = field["hard_stop_triggered"]
    total     = migration_score["total"]
    treatment = None
    reason    = []

    if hard_stop:
        decision = "NO-GO"
        reason = field["hard_stops"]
    elif total >= 70:
        decision  = "GO"
        treatment = assign_treatment(lunar_bin, counts)
        reason    = [migration_score["interpretation"], "No hard stops triggered"]
    elif total >= 50:
        decision = "REVIEW"
        reason   = [migration_score["interpretation"], "Review for treatment balance / BirdCast / conditions"]
    else:
        decision = "NO-GO"
        reason   = [f"Migration score {total}/95 — {migration_score['interpretation']}"]

    return {
        "decision": decision,
        "treatment": treatment,
        "reason": reason,
        "migration_total": total,
        "lunar_bin": lunar_bin,
    }


# ─────────────────────────────────────────────────────────────────
#  7. RUN ALL
# ─────────────────────────────────────────────────────────────────
def run_dashboard():
    print("=" * 55)
    print("  LIGHT Team Night-Decision Dashboard")
    print(f"  {SITE_NAME}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    print("\n[1/5] Fetching NWS weather forecast…")
    weather = fetch_nws(SITE_LAT, SITE_LON)

    print("[2/5] Fetching AWC METAR/TAF…")
    awc = fetch_awc()

    print("[3/5] Fetching BirdCast forecast…")
    birdcast = fetch_birdcast(SITE_LAT, SITE_LON, BIRDCAST_API_KEY)

    print("[4/5] Fetching USNO lunar data…")
    lunar = fetch_usno(SITE_LAT, SITE_LON)

    print("[5/5] Fetching pressure trend…")
    pressure = fetch_pressure_trend(SITE_LAT, SITE_LON)

    # Score and decide
    migration = score_migration(weather, birdcast, pressure, SEASON)
    field     = assess_field_conditions(weather, awc)
    lunar_bin = lunar.get("lunar_bin", "Moderate")
    decision  = make_decision(migration, field, lunar_bin, TREATMENT_COUNTS)

    # Bundle everything
    result = {
        "timestamp": datetime.now().isoformat(),
        "site": SITE_NAME,
        "lat": SITE_LAT,
        "lon": SITE_LON,
        "season": SEASON,
        "forecast": {
            "weather": weather,
            "awc": awc,
            "birdcast": birdcast,
            "lunar": lunar,
            "pressure": pressure,
        },
        "migration_score": migration,
        "field_conditions": field,
        "decision": decision,
        "treatment_counts": TREATMENT_COUNTS,
    }

    print("\n" + "=" * 55)
    print(f"  DECISION: {decision['decision']}")
    if decision["treatment"]:
        print(f"  TREATMENT: {decision['treatment']}")
    print(f"  Migration Score: {migration['total']}/95 — {migration['interpretation']}")
    print(f"  Lunar Bin: {lunar_bin} ({lunar.get('forecast_moon_illumination_pct','?')}%)")
    if field["hard_stops"]:
        print(f"  HARD STOPS: {', '.join(field['hard_stops'])}")
    print("=" * 55)

    # Save JSON for the HTML dashboard
    with open("dashboard_data.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\n  ✅  Saved dashboard_data.json — open light_dashboard.html to view.")

    return result


# Run
if __name__ == "__main__":
    nws  = fetch_nws(SITE_LAT, SITE_LON)
    awc  = fetch_awc()
    bird = fetch_birdcast(SITE_LAT, SITE_LON, BIRDCAST_API_KEY)
    moon = fetch_usno(SITE_LAT, SITE_LON)

    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "site": SITE_NAME,
        "season": SEASON,
        "nws": nws,
        "awc": awc,
        "birdcast": bird,
        "moon": moon,
        "readiness": {
            "staffing": STAFFING_READY,
            "equipment": EQUIPMENT_READY,
            "facilities": FACILITIES_READY
        },
        "treatments": TREATMENT_COUNTS
    }

    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)

    print("✅ data.json updated")
