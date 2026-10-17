export default function Header({ notice }) {
  return (
    <header className="app-header">
      <div className="app-header-titles">
        <h1>Cleared for Takeoff</h1>
        <p className="app-subtitle">Clinical Trial Supply Intelligence</p>
      </div>
      <div className="simulated-indicator" title={notice || "All data shown is simulated."}>
        <span className="dot" />
        SIMULATED DATA
      </div>
    </header>
  );
}
