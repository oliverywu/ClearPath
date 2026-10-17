# Public logistics data for the planner

This folder turns the demo's flat, made-up lane numbers into data anchored to public sources, and adds uncertainty ranges so the plan can show a likely and a safe ship-by date. The default demo (`data/demo/trial.json`) is unchanged; the enriched copy is a separate fixture.

## Run it

```bash
python start.py --db .local/logistics.sqlite3 --fixture data/demo/trial_logistics.json
```

Open http://localhost:3000. Add `--reset` to reload the fixture into an existing database.

## Rebuild the fixture

```bash
pip install holidays          # build-time only; the app itself still needs no packages
python data/logistics/build_logistics_fixture.py
```

The script reads `trial.json` and writes `trial_logistics.json`. Rules, events and the trial are copied unchanged; only country holidays and routes are replaced.

## What changed per input

| Planner input | Before | Now | Status |
|---|---|---|---|
| `holidays` per country | empty for all 24 countries | national holidays of the US (origin) and the destination, weekdays only, 12 months from the planning date | public data (python `holidays`) |
| `customs_days` | 3 for almost every country | likely = ceil(LPI median airport import dwell); US = 0 because US sites are domestic | public benchmark (World Bank LPI 2023, Cargo iQ data) |
| Gateway airport | "Boston → United States" | real airport per country (`gateways.csv`), with the reason it was picked | public reference |
| `transit_days` | 5 standard / 3 express everywhere | distance model: 1 day origin handling + 1 or 2 flight days (over 7,000 km) + 1 hub day for standard routes | simulated, documented |
| Ranges | none | `transit_days_range` and `customs_days_range` with best / likely / worst | best/worst rules below |
| Depot and last-mile days | synthetic | unchanged | simulated |

Range rules:

- Customs: best = ceil(min(median, mean)), worst = ceil(median + IQR).
- Transit: best = likely − 1 (minimum 1), worst = likely + 2.

Every route's `source` text and `data_quality` field say which numbers are public and which are simulated.

## Planner change

`packages/planner/engine.py` adds `delivery_range()`. For each shipment it returns:

- `delivery_range`: best / likely / worst delivery dates. The likely date is the existing projected delivery, so the main schedule is unchanged.
- `ship_by`: `likely` is the latest dispatch that meets the target on likely durations; `safe` is the latest dispatch that still meets it if transit and customs hit their worst case.
- `worst_case_slack_days`, plus a reason line when the worst case misses the target.

A route without ranges behaves exactly as before, so the default demo gives the same dates. Risk bands still use the likely schedule (unchanged formula, so Chalk parity holds); the worst case is reported as an explanation, not a new block.

## Sources

- World Bank LPI 2023, aviation import dwell time: https://lpi.worldbank.org/aviation
- LPI 2.0 methodology (definition of dwell time): https://lpi.worldbank.org/en/about/methodology
- Japan MOF clearance time survey, 2024 (validation check for Japan): https://www.mof.go.jp/policy/customs_tariff/trade/facilitation/ka20240626.htm
- python holidays: https://pypi.org/project/holidays/
- OurAirports: https://ourairports.com/data/
- Eurostat avia_gooa (EU gateway choice): https://ec.europa.eu/eurostat/databrowser/view/avia_gooa/default/table
- MLIT Tokyo bureau monthly airport figures (Narita): https://www.cab.mlit.go.jp/tcab/statistics/01.html
- CBSA airports of entry for commercial cargo: https://cbsa-asfc.gc.ca/do-rb/services/aoecargo-eng.html

## Known limits

- The LPI page labels its first time column "median" and the second "mean", but the "median" is usually the larger number, which is unusual for delay data. The values are copied exactly as published; confirm the column labels with the LPI 2023 report before quoting them to judges.
- LPI dwell time is in calendar days and runs from ready-for-pickup notification to delivery out of the airport. It is rounded up to business days, which is conservative.
- The page does not state the measurement period; it belongs to the LPI 2023 edition.
- Transit days are a model, not measured courier times. Real door-to-door IMP times are proprietary to specialist couriers.
- Gateways outside Japan and Canada were picked by hand as each country's largest cargo airport.
