const DELAY_LABELS = {
  none: "—",
  in_transit_customs_hold: "In-transit customs hold",
  pre_dispatch_labeling_hold: "Pre-dispatch labeling hold",
  regulatory_review_only: "Regulatory review (no delay)",
};

function RiskBadge({ atRisk }) {
  return (
    <span className={`risk-badge ${atRisk ? "at-risk" : "on-track"}`}>
      {atRisk ? "AT RISK" : "ON TRACK"}
    </span>
  );
}

export default function ShipmentTable({ rows, scenarioId, loading }) {
  const showRevised = scenarioId !== "baseline";
  const columnCount = showRevised ? 10 : 7;

  return (
    <section className="panel shipment-table-panel" aria-label="Shipments">
      <h2>Shipments</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Shipment</th>
              <th>Investigational drug</th>
              <th>Destination</th>
              <th>Scope</th>
              <th>Original arrival</th>
              {showRevised && <th>Revised arrival</th>}
              <th>Required delivery</th>
              <th>Original buffer</th>
              {showRevised && <th>Revised buffer</th>}
              <th>Risk status</th>
              {showRevised && <th>Delay source</th>}
            </tr>
          </thead>
          <tbody>
            {loading || !rows ? (
              <tr>
                <td colSpan={columnCount} className="table-loading">
                  Loading…
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.shipment_id} className={row.affected ? "row-affected" : ""}>
                  <td className="mono">{row.shipment_id}</td>
                  <td>{row.drug_name}</td>
                  <td>{row.destination}</td>
                  <td>
                    {row.in_scope ? (
                      <span className="scope-badge in-scope">{row.jurisdiction}</span>
                    ) : (
                      <span className="scope-badge out-of-scope">out of scope</span>
                    )}
                  </td>
                  <td>{row.original_arrival_date}</td>
                  {showRevised && (
                    <td className={row.affected ? "revised-cell changed" : "revised-cell"}>
                      {row.revised_arrival_date}
                    </td>
                  )}
                  <td>{row.required_delivery_date}</td>
                  <td>{row.original_buffer_days}d</td>
                  {showRevised && (
                    <td className={row.affected ? "revised-cell changed" : "revised-cell"}>
                      {row.revised_buffer_days}d
                    </td>
                  )}
                  <td>
                    <RiskBadge atRisk={showRevised ? row.revised_at_risk : row.original_at_risk} />
                    {showRevised && row.original_at_risk !== row.revised_at_risk && (
                      <span className="risk-transition">
                        {row.original_at_risk ? "AT RISK" : "ON TRACK"} →{" "}
                        {row.revised_at_risk ? "AT RISK" : "ON TRACK"}
                      </span>
                    )}
                  </td>
                  {showRevised && (
                    <td>
                      {row.event_or_change ? (
                        <span className="delay-chip" title={row.event_or_change.description}>
                          {DELAY_LABELS[row.delay_type] ?? row.delay_type}
                          {row.delay_days > 0 ? ` · +${row.delay_days}d` : ""}
                        </span>
                      ) : (
                        <span className="delay-chip delay-chip-none">{DELAY_LABELS.none}</span>
                      )}
                      {row.approved_decision && (
                        <span
                          className="approved-chip"
                          title={`Approved by ${row.approved_decision.approved_by?.name ?? "unknown"} (${
                            row.approved_decision.approved_by?.role ?? "unknown role"
                          }) via ${row.approved_decision.channel} at ${row.approved_decision.approved_at}`}
                        >
                          Approved: {row.approved_decision.label}
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {!loading && rows && (
        <p className="table-footnote">
          "Out of scope" destinations (outside US/EU/Japan) are kept visible here but excluded from
          regulatory analysis below.
        </p>
      )}
    </section>
  );
}
