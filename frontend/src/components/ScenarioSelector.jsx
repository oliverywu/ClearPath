export default function ScenarioSelector({ scenarios, selected, onSelect, activeScenario }) {
  return (
    <section className="scenario-selector" aria-label="Scenario selector">
      <div className="scenario-buttons">
        {scenarios.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`scenario-button ${s.id === selected ? "active" : ""}`}
            onClick={() => onSelect(s.id)}
          >
            {s.title}
          </button>
        ))}
      </div>
      {activeScenario && <p className="scenario-description">{activeScenario.description}</p>}
    </section>
  );
}
