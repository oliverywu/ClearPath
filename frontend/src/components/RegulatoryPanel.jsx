function StatusBadge({ status }) {
  return (
    <span className={`status-badge ${status === "CANDIDATE_GROUP" ? "candidate" : "needs-review"}`}>
      {status === "CANDIDATE_GROUP" ? "Candidate group" : "Needs review"}
    </span>
  );
}

export default function RegulatoryPanel({ regulatory }) {
  if (!regulatory) {
    return (
      <section className="panel regulatory-panel" aria-label="Regulatory panel">
        <h2>Regulatory review</h2>
        <p className="muted">Loading…</p>
      </section>
    );
  }

  return (
    <section className="panel regulatory-panel" aria-label="Regulatory panel">
      <h2>Regulatory review</h2>
      <p className="scope-line">
        Scope: <strong>{regulatory.scope.join(", ")}</strong> · Excluded:{" "}
        <strong>{regulatory.excluded_jurisdictions.join(", ")}</strong>
      </p>

      <div className="simulated-change-box">
        <span className="pill pill-simulated">{regulatory.simulated_regulatory_change.label}</span>
        <strong>{regulatory.simulated_regulatory_change.change_id}</strong>
        <p>{regulatory.simulated_regulatory_change.description}</p>
      </div>

      {regulatory.candidate_groups_after_change.length === 0 && (
        <p className="muted">No candidate label groups (need 2+ in-scope shipments of the same product).</p>
      )}

      {regulatory.candidate_groups_after_change.map((group) => {
        const before = regulatory.candidate_groups_before_change.find(
          (g) => g.drug_name === group.drug_name
        );
        return (
          <div className="candidate-group" key={group.drug_name}>
            <div className="candidate-group-header">
              <h3>{group.drug_name}</h3>
              <StatusBadge status={group.status} />
            </div>
            <p className="muted small">
              Shipments: {group.shipment_ids.join(", ")} · Jurisdictions: {group.jurisdictions.join(", ")}
            </p>

            {before && before.status !== group.status && (
              <p className="status-transition">
                Before simulated change: <StatusBadge status={before.status} />
              </p>
            )}

            {group.reasons.length > 0 && (
              <details open>
                <summary>{group.reasons.length} review reason(s)</summary>
                <ul className="reason-list">
                  {group.reasons.map((reason) => (
                    <li key={reason} className={reason.includes("SIMULATED") ? "reason-simulated" : ""}>
                      {reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {group.sources.length > 0 && (
              <div className="source-links">
                {group.sources.map((url) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer">
                    source ↗
                  </a>
                ))}
              </div>
            )}
          </div>
        );
      })}

      <p className="disclaimer">{regulatory.disclaimer}</p>
    </section>
  );
}
