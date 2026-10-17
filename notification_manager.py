"""Disruption-risk alert notifications for Cleared for Takeoff.

Connects impact_analyzer.py's disruption analysis to the existing Photon
messaging bridge (photon_bridge.py). Reuses existing functions rather than
re-implementing them:
  - shipment_planner.load_shipments()
  - impact_analyzer.analyze_disruption_impact() / SIMULATED_DISRUPTION_EVENT
  - photon_bridge.build_photon_client() / send_text_message()

Sending a real Photon message is strictly opt-in. Every entry point here
defaults to dry-run (alerts are generated and printed, never sent). A real
send only happens via an explicit --send flag (CLI) or dry_run=False (API),
and only once PHOTON_PROJECT_ID, PHOTON_ALERT_SPACE_ID, and
PHOTON_ALERT_SENDER_ID are available -- otherwise it safely falls back to
dry-run.

Run:
    python notification_manager.py            # dry run (default): prints alerts only
    python notification_manager.py --send      # also dispatches via Photon
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from impact_analyzer import SIMULATED_DISRUPTION_EVENT, analyze_disruption_impact
from photon_bridge import build_photon_client, send_text_message
from shipment_planner import ShipmentDataError, load_shipments

STATE_PATH = Path(__file__).resolve().parent / ".notification_manager_state.json"


def load_alert_state(path: Path = STATE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"sent_alert_keys": []}


def save_alert_state(state: dict, path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(state), encoding="utf-8")


def find_newly_at_risk(results: list) -> list:
    """Shipments whose risk status flips ON TRACK -> AT RISK under the disruption.

    Shipments the disruption didn't touch, or that were already AT RISK
    beforehand, are excluded -- only a *new* risk caused by this specific
    event is alert-worthy.
    """
    return [
        result
        for result in results
        if result["affected"] and not result["original_at_risk"] and result["new_at_risk"]
    ]


def _alert_key(result: dict) -> str:
    return f"{result['event_id']}:{result['shipment_id']}"


def build_alert_message(result: dict) -> str:
    days_late = (result["updated_arrival_date"] - result["required_delivery_date"]).days
    return (
        f"[{result['event_label']}] {result['event_id']} ALERT -- {result['shipment_id']} "
        f"({result['drug_name']}) is now AT RISK\n"
        f"Disruption:         {result['event_description']}\n"
        f"Original arrival:   {result['original_arrival_date'].isoformat()}\n"
        f"Revised arrival:    {result['updated_arrival_date'].isoformat()}\n"
        f"Required delivery:  {result['required_delivery_date'].isoformat()}\n"
        f"Days late:          {days_late}"
    )


def generate_alerts(shipments: list, disruption_event: dict, already_sent: Optional[set] = None) -> list:
    """Return alert dicts for newly-at-risk shipments, skipping ones already sent.

    Reuses impact_analyzer.analyze_disruption_impact(shipments, disruption_event)
    with its existing signature -- the arrival/buffer/risk math is not
    recomputed here.
    """
    already_sent = already_sent or set()
    results = analyze_disruption_impact(shipments, disruption_event)
    newly_at_risk = find_newly_at_risk(results)

    alerts = []
    for result in newly_at_risk:
        key = _alert_key(result)
        if key in already_sent:
            continue
        alerts.append({"key": key, "result": result, "message": build_alert_message(result)})
    return alerts


def send_alert(photon_client: Any, project_id: str, space_id: str, sender_id: str, alert: dict) -> None:
    send_text_message(
        photon_client,
        project_id,
        space_id=space_id,
        sender_id=sender_id,
        text=alert["message"],
        idempotency_key=f"alert:{alert['key']}",
    )


def run(
    dry_run: bool = True,
    state_path: Path = STATE_PATH,
    photon_client: Any = None,
    project_id: Optional[str] = None,
    space_id: Optional[str] = None,
    sender_id: Optional[str] = None,
) -> list:
    """Load shipments, analyze the simulated disruption, print every newly
    AT RISK alert, and -- only when dry_run=False -- send each one exactly
    once via the existing Photon integration. Returns the alerts generated
    this run.
    """
    shipments = load_shipments()
    state = load_alert_state(state_path)
    already_sent = set(state.get("sent_alert_keys", []))

    alerts = generate_alerts(shipments, SIMULATED_DISRUPTION_EVENT, already_sent)

    if not alerts:
        print("No new ON TRACK -> AT RISK transitions for this disruption. Nothing to alert.")
        return alerts

    for alert in alerts:
        print(alert["message"])
        print()

    if dry_run:
        print(f"[DRY RUN] {len(alerts)} alert(s) generated; Photon send skipped. Pass --send to dispatch.")
        return alerts

    project_id = project_id or os.environ.get("PHOTON_PROJECT_ID")
    space_id = space_id or os.environ.get("PHOTON_ALERT_SPACE_ID")
    sender_id = sender_id or os.environ.get("PHOTON_ALERT_SENDER_ID")
    missing = [
        name
        for name, value in [
            ("PHOTON_PROJECT_ID", project_id),
            ("PHOTON_ALERT_SPACE_ID", space_id),
            ("PHOTON_ALERT_SENDER_ID", sender_id),
        ]
        if not value
    ]
    if missing:
        print(f"Cannot send: missing {', '.join(missing)}. Falling back to dry run -- no message sent.")
        return alerts

    client = photon_client or build_photon_client()
    for alert in alerts:
        try:
            send_alert(client, project_id, space_id, sender_id, alert)
        except Exception as exc:  # network/API failure -- leave unmarked, retried next run
            print(f"[notification_manager] send failed for {alert['key']}: {exc}", file=sys.stderr)
            continue
        state.setdefault("sent_alert_keys", []).append(alert["key"])

    save_alert_state(state, state_path)
    return alerts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate (and optionally send) disruption risk alerts.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually dispatch via Photon. Default is dry-run: alerts are printed only.",
    )
    args = parser.parse_args()

    try:
        run(dry_run=not args.send)
    except ShipmentDataError as exc:
        print(f"Error loading shipment data: {exc}")


if __name__ == "__main__":
    main()
