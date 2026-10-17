"""Clinical supply shipment planner (simulated data only).

Reads simulated investigational insulin shipment records and estimates
whether each shipment will arrive on time given its transit schedule and
an optional disruption delay.
"""

import json
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "shipments.json"

REQUIRED_FIELDS = (
    "shipment_id",
    "drug_name",
    "shipping_date",
    "estimated_transit_days",
    "required_delivery_date",
)

DATE_FORMAT = "%Y-%m-%d"


class ShipmentDataError(Exception):
    """Raised when shipment data is missing, malformed, or incomplete."""


def load_shipments(path=DATA_PATH):
    """Load shipment records from a JSON file.

    Returns a list of shipment dicts. Raises ShipmentDataError with a
    readable message if the file is missing, not valid JSON, or does not
    have the expected shape.
    """
    path = Path(path)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ShipmentDataError(f"Shipment data file not found: {path}") from exc
    except OSError as exc:
        raise ShipmentDataError(f"Could not read shipment data file {path}: {exc}") from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ShipmentDataError(f"Shipment data file {path} is not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        shipments = data.get("shipments")
    else:
        shipments = data

    if not isinstance(shipments, list):
        raise ShipmentDataError(
            f"Shipment data file {path} must contain a list of shipments "
            '(either as the top-level JSON value or under a "shipments" key).'
        )

    return shipments


def _parse_date(value, field_name, shipment_id):
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except (TypeError, ValueError) as exc:
        raise ShipmentDataError(
            f"Shipment '{shipment_id}' has an invalid {field_name} "
            f"(expected YYYY-MM-DD, got {value!r})"
        ) from exc


def calculate_shipment(shipment, delay_days=0):
    """Calculate arrival/risk details for a single shipment record.

    Returns a new dict containing the original fields plus:
      - estimated_arrival_date (date)
      - required_delivery_date (date, parsed)
      - shipping_date (date, parsed)
      - buffer_days (int, positive means arriving early/on time)
      - at_risk (bool)
    """
    if not isinstance(shipment, dict):
        raise ShipmentDataError(f"Shipment record must be an object, got {type(shipment).__name__}")

    shipment_id = shipment.get("shipment_id", "<unknown>")

    missing = [field for field in REQUIRED_FIELDS if field not in shipment]
    if missing:
        raise ShipmentDataError(
            f"Shipment '{shipment_id}' is missing required field(s): {', '.join(missing)}"
        )

    shipping_date = _parse_date(shipment["shipping_date"], "shipping_date", shipment_id)
    required_delivery_date = _parse_date(
        shipment["required_delivery_date"], "required_delivery_date", shipment_id
    )

    transit_days = shipment["estimated_transit_days"]
    if not isinstance(transit_days, int) or isinstance(transit_days, bool):
        raise ShipmentDataError(
            f"Shipment '{shipment_id}' has an invalid estimated_transit_days "
            f"(expected an integer, got {transit_days!r})"
        )

    if not isinstance(delay_days, int) or isinstance(delay_days, bool):
        raise ShipmentDataError(f"delay_days must be an integer, got {delay_days!r}")

    estimated_arrival_date = shipping_date + timedelta(days=transit_days + delay_days)
    buffer_days = (required_delivery_date - estimated_arrival_date).days
    at_risk = estimated_arrival_date > required_delivery_date

    result = dict(shipment)
    result["shipping_date"] = shipping_date
    result["required_delivery_date"] = required_delivery_date
    result["estimated_arrival_date"] = estimated_arrival_date
    result["buffer_days"] = buffer_days
    result["at_risk"] = at_risk
    return result


def _format_summary(result):
    status = "AT RISK" if result["at_risk"] else "ON TRACK"
    return (
        f"[{status}] {result.get('shipment_id', '<unknown>')} - "
        f"{result.get('drug_name', 'Unknown drug')}\n"
        f"    Ship date:          {result['shipping_date'].isoformat()}\n"
        f"    Estimated arrival:  {result['estimated_arrival_date'].isoformat()}\n"
        f"    Required by:        {result['required_delivery_date'].isoformat()}\n"
        f"    Buffer days:        {result['buffer_days']}"
    )


def main():
    try:
        shipments = load_shipments()
    except ShipmentDataError as exc:
        print(f"Error loading shipment data: {exc}")
        return

    if not shipments:
        print("No shipments found.")
        return

    print(f"Loaded {len(shipments)} shipment(s) from {DATA_PATH}\n")

    for shipment in shipments:
        try:
            result = calculate_shipment(shipment)
        except ShipmentDataError as exc:
            print(f"Error processing shipment: {exc}\n")
            continue
        print(_format_summary(result))
        print()


class CalculateShipmentTests(unittest.TestCase):
    def setUp(self):
        self.base_shipment = {
            "shipment_id": "TEST-001",
            "drug_name": "Investigational Insulin Glargine",
            "shipping_date": "2026-10-01",
            "estimated_transit_days": 5,
            "required_delivery_date": "2026-10-10",
        }

    def test_on_time_delivery(self):
        result = calculate_shipment(self.base_shipment, delay_days=0)
        self.assertEqual(result["estimated_arrival_date"], date(2026, 10, 6))
        self.assertEqual(result["buffer_days"], 4)
        self.assertFalse(result["at_risk"])

    def test_five_day_disruption_causes_risk(self):
        result = calculate_shipment(self.base_shipment, delay_days=5)
        self.assertEqual(result["estimated_arrival_date"], date(2026, 10, 11))
        self.assertEqual(result["buffer_days"], -1)
        self.assertTrue(result["at_risk"])

    def test_missing_field_raises(self):
        incomplete = dict(self.base_shipment)
        del incomplete["estimated_transit_days"]
        with self.assertRaises(ShipmentDataError):
            calculate_shipment(incomplete)

    def test_load_shipments_missing_file(self):
        with self.assertRaises(ShipmentDataError):
            load_shipments(Path("/nonexistent/path/shipments.json"))


if __name__ == "__main__":
    main()
