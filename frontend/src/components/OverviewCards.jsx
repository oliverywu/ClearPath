const CARD_DEFS = [
  { key: "shipment_count", label: "Shipments tracked", hint: "All shipments on file, in scope or not." },
  { key: "baseline_at_risk_count", label: "Baseline at-risk", hint: "At risk with no scenario applied." },
  { key: "newly_at_risk_count", label: "Newly at-risk (scenario)", hint: "Flipped on-track → at-risk by the selected scenario." },
  { key: "regulatory_alerts_count", label: "Regulatory alerts", hint: "Prepared alerts tied to the simulated regulatory change." },
];

export default function OverviewCards({ overview, loading }) {
  return (
    <section className="overview-grid" aria-label="Overview">
      {CARD_DEFS.map(({ key, label, hint }) => (
        <div className="overview-card" key={key} title={hint}>
          <span className="overview-value">{loading || !overview ? "–" : overview[key]}</span>
          <span className="overview-label">{label}</span>
        </div>
      ))}
    </section>
  );
}
