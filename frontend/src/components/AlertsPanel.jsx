export default function AlertsPanel({ alerts }) {
  if (!alerts) {
    return (
      <section className="panel alerts-panel" aria-label="Alerts panel">
        <h2>Alerts</h2>
        <p className="muted">Loading…</p>
      </section>
    );
  }

  return (
    <section className="panel alerts-panel" aria-label="Alerts panel">
      <h2>Alerts</h2>
      <p className="muted small">
        Prepared notifications only. Sending via Photon is disabled from this dashboard.
      </p>
      {alerts.length === 0 ? (
        <p className="muted">No alerts for this view.</p>
      ) : (
        <ul className="alert-list">
          {alerts.map((alert) => (
            <li key={alert.alert_id} className="alert-item">
              <div className="alert-item-header">
                <span className="pill pill-simulated">{alert.label}</span>
                <span className="alert-source">
                  {alert.source === "customs_disruption" ? "Customs disruption" : "Regulatory change"}
                </span>
                <span className={`sent-badge ${alert.sent ? "sent" : "not-sent"}`}>
                  {alert.sent ? "Sent" : "Not sent"}
                </span>
                {alert.approved_decision && <span className="sent-badge sent">Resolved</span>}
              </div>
              <p className="alert-shipment">
                {alert.shipment_id} — {alert.drug_name}
              </p>
              <p className="alert-message">{alert.message}</p>
              {alert.approved_decision && (
                <p className="alert-message">
                  Approved: {alert.approved_decision.label} by {alert.approved_decision.approved_by?.name}{" "}
                  ({alert.approved_decision.approved_by?.role}) via {alert.approved_decision.channel}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
