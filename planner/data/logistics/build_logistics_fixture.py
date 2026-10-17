"""Build data/demo/trial_logistics.json: the demo trial enriched with public logistics data.

Reads the packaged synthetic demo (data/demo/trial.json) and replaces its flat lane
assumptions with:

1. Public holidays (python `holidays` library) for the origin (US) and each destination.
2. Customs days per destination anchored to World Bank LPI 2023 aviation import dwell
   time at airports (Cargo iQ tracking data), with a best / likely / worst range.
3. Real gateway airports (OurAirports coordinates) and transit days from a simple,
   documented distance model, also as a best / likely / worst range.

Regulatory rules, events and the trial itself are left exactly as they are.
The base fixture and the default demo are not modified.

Run from the repository root:
    pip install holidays
    python data/logistics/build_logistics_fixture.py
"""
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

try:
    import holidays as holiday_lib
except ImportError as error:  # pragma: no cover - build-time dependency only
    raise SystemExit("Install the build-time dependency first: pip install holidays") from error

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "data" / "demo" / "trial.json"
OUT = ROOT / "data" / "demo" / "trial_logistics.json"
RETRIEVED = "2026-10-17"
ORIGIN = "US"

LPI_URL = "https://lpi.worldbank.org/aviation"
HOLIDAYS_URL = "https://pypi.org/project/holidays/"
OURAIRPORTS_URL = "https://ourairports.com/data/"
MOF_URL = "https://www.mof.go.jp/policy/customs_tariff/trade/facilitation/ka20240626.htm"

# Transit model (simulated; documented so reviewers can challenge each assumption).
ORIGIN_HANDLING_DAYS = 1      # export screening and build-up at BOS
LONG_HAUL_KM = 7000           # beyond this, flight plus recovery takes a second day
HUB_CONNECTION_DAYS = 1       # standard routing connects through a hub
BEST_OFFSET, WORST_OFFSET = -1, 2   # early arrival / offload or missed connection


def load_csv(name):
    with open(HERE / name, encoding="utf-8") as handle:
        return {row["iso2"]: row for row in csv.DictReader(handle)}


def km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)))


def spread(likely, best=None, worst=None):
    best = max(0 if likely == 0 else 1, likely + BEST_OFFSET) if best is None else best
    worst = likely + WORST_OFFSET if worst is None else worst
    return {"best": min(best, likely), "likely": likely, "worst": max(worst, likely)}


def customs_range(code, lpi):
    if code == ORIGIN:
        return {"best": 0, "likely": 0, "worst": 0}
    row = lpi[code]
    median, mean, iqr = float(row["dwell_median_days"]), float(row["dwell_mean_days"]), float(row["dwell_iqr_days"])
    likely = max(1, math.ceil(median))
    return spread(likely, best=max(1, math.ceil(min(median, mean))), worst=math.ceil(median + iqr))


def transit_range(distance_km, via_hub):
    if distance_km == 0:  # domestic US: truck or domestic air from Boston
        return spread(2 if via_hub else 1)
    flight = 1 if distance_km < LONG_HAUL_KM else 2
    return spread(ORIGIN_HANDLING_DAYS + flight + (HUB_CONNECTION_DAYS if via_hub else 0))


def holiday_dates(code, start, end):
    years = range(start.year, end.year + 1)
    days = set()
    for country in {ORIGIN, code}:
        for day in holiday_lib.country_holidays(country, years=years):
            if start <= day <= end and day.weekday() < 5:
                days.add(day.isoformat())
    return sorted(days)


def main():
    data = json.loads(BASE.read_text(encoding="utf-8"))
    lpi, gateways = load_csv("lpi2023_aviation_import_dwell.csv"), load_csv("gateways.csv")
    origin = gateways[ORIGIN]
    origin_point = (float(origin["latitude"]), float(origin["longitude"]))
    names = {j["id"]: j["name"] for j in data["jurisdictions"]}
    as_of = date.fromisoformat(data["as_of"])

    data["id"] = data["id"] + "-logistics"
    data["trial"]["name"] += " · public logistics data"

    for plan in data["country_plans"]:
        plan["holidays"] = holiday_dates(plan["jurisdiction"], as_of, as_of + timedelta(days=365))
        plan["holiday_source"] = f"python holidays {holiday_lib.__version__}: national holidays of US (origin) and {plan['jurisdiction']} (destination), weekdays only"

    for route in data["routes"]:
        code = route["jurisdiction"]
        via_hub = route["preferred"]  # standard = qualified hub, express = priority direct
        gateway = gateways["NL"] if code == "DE" and not route["preferred"] else gateways[code]
        customs_country = "NL" if gateway["iso2"] == "NL" and code == "DE" else code
        point = (float(gateway["latitude"]), float(gateway["longitude"]))
        distance = 0 if code == ORIGIN else km(origin_point, point)
        transit, customs = transit_range(distance, via_hub), customs_range(customs_country, lpi)
        route.update(transit_days=transit["likely"], customs_days=customs["likely"],
                     transit_days_range=transit, customs_days_range=customs,
                     gateway_airport=gateway["iata"], great_circle_km=distance)
        if code == ORIGIN:
            route["name"] = f"BOS → {names[code]} depot · {'domestic hub' if via_hub else 'domestic priority'}"
            route["legs"] = [{"origin": "Boston (BOS)", "destination": f"{names[code]} depot", "mode": "domestic air/ground"}]
        else:
            route["name"] = f"BOS → {gateway['iata']} → {names[code]} depot · {'qualified hub' if via_hub else 'priority direct'}"
            route["legs"] = [{"origin": "Boston (BOS)", "destination": f"{gateway['airport']} ({gateway['iata']})", "mode": "air"},
                             {"origin": gateway["iata"], "destination": f"{names[code]} depot", "mode": "qualified ground transport"}]
        customs_note = ("no import clearance (domestic)" if code == ORIGIN else
                        f"World Bank LPI 2023 aviation import dwell time for {lpi[customs_country]['economy']}: median {lpi[customs_country]['dwell_median_days']} d, "
                        f"mean {lpi[customs_country]['dwell_mean_days']} d, IQR {lpi[customs_country]['dwell_iqr_days']} d ({LPI_URL})")
        route["source"] = (f"Customs {customs['best']}/{customs['likely']}/{customs['worst']} business days (best/likely/worst): {customs_note}. "
                           f"Transit {transit['best']}/{transit['likely']}/{transit['worst']} business days: SIMULATED distance model, BOS→{gateway['iata']} {distance} km "
                           f"(OurAirports coordinates), {'+1 hub connection day' if via_hub else 'direct priority'}. "
                           f"Gateway: {gateway['selection_basis']} ({gateway['evidence_url']}). Depot and last-mile days remain synthetic.")
        route["data_quality"] = {
            "customs_days": "not_applicable" if code == ORIGIN else "public_benchmark",
            "transit_days": "simulated", "gateway_airport": "public_reference",
            "depot_days": "simulated", "last_mile_days": "simulated", "retrieved_at": RETRIEVED}
        route["synthetic"] = True  # transit/depot/last-mile are still modelled, not measured

    data.setdefault("sources", [])
    for source_id, title, url, publisher, tier, note in (
        ("logistics-lpi-aviation", "World Bank LPI 2023: aviation import dwell time at airports", LPI_URL, "World Bank (Cargo iQ / IATA tracking data)", "authoritative_secondary",
         "Customs day ranges per destination. Dwell time runs from ready-for-pickup notification to delivery out of the airport; calendar days, rounded up to business days."),
        ("logistics-japan-mof", "Japan MOF: 13th import clearance time survey (2024)", MOF_URL, "Ministry of Finance, Japan", "official",
         "Validation check for Japan: average declaration-to-permit time for air cargo is 0.3 hours. It covers only the customs step, so it is far shorter than LPI dwell time, which also includes pickup and delivery."),
        ("logistics-holidays", "python holidays library (national public holidays)", HOLIDAYS_URL, "vacanza/holidays project", "authoritative_secondary",
         "Holiday calendars for origin and destination; excluded from all business-day calculations."),
        ("logistics-ourairports", "OurAirports airport data", OURAIRPORTS_URL, "OurAirports (public domain)", "authoritative_secondary",
         "Gateway airport coordinates used for great-circle distances."),
    ):
        data["sources"].append({"id": source_id, "jurisdiction_id": None, "title": title, "canonical_url": url, "publisher": publisher,
                                "retrieved_at": RETRIEVED + "T00:00:00Z", "content_hash": "logistics-" + source_id, "snapshot_path": None,
                                "source_tier": tier, "content": note, "enabled": False})

    data["config"]["logistics"] = {
        "model": "Business-day schedule with best / likely / worst ranges on transit and customs; the likely value drives the main plan.",
        "transit_assumptions": {"origin_handling_days": ORIGIN_HANDLING_DAYS, "long_haul_km": LONG_HAUL_KM,
                                "hub_connection_days": HUB_CONNECTION_DAYS, "best_offset_days": BEST_OFFSET, "worst_offset_days": WORST_OFFSET},
        "customs_assumptions": "likely = ceil(LPI median dwell), best = ceil(min(median, mean)), worst = ceil(median + IQR); US destinations are domestic (0).",
        "retrieved_at": RETRIEVED}

    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(data['routes'])} routes, {len(data['country_plans'])} country plans")


if __name__ == "__main__":
    main()
