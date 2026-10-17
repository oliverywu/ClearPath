import { useEffect, useState } from "react";
import "./App.css";
import { fetchDashboard, fetchScenarios } from "./api";
import Header from "./components/Header";
import OverviewCards from "./components/OverviewCards";
import ScenarioSelector from "./components/ScenarioSelector";
import ShipmentTable from "./components/ShipmentTable";
import RegulatoryPanel from "./components/RegulatoryPanel";
import AlertsPanel from "./components/AlertsPanel";

export default function App() {
  const [scenarios, setScenarios] = useState([]);
  const [scenarioId, setScenarioId] = useState("baseline");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchScenarios()
      .then(setScenarios)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchDashboard(scenarioId)
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scenarioId]);

  return (
    <div className="app">
      <Header notice={data?.simulated_data_notice} />
      <main className="app-main">
        {error && (
          <div className="banner banner-error">
            Could not reach the API backend: {error}. Is <code>uvicorn api:app --reload</code> running
            on port 8000?
          </div>
        )}

        <ScenarioSelector
          scenarios={scenarios}
          selected={scenarioId}
          onSelect={setScenarioId}
          activeScenario={data?.scenario}
        />

        <OverviewCards overview={data?.overview} loading={loading} />

        <div className="panel-grid">
          <ShipmentTable rows={data?.shipments} scenarioId={scenarioId} loading={loading} />
          <div className="side-panels">
            <RegulatoryPanel regulatory={data?.regulatory} />
            <AlertsPanel alerts={data?.alerts} />
          </div>
        </div>

        <footer className="app-footer">
          Cleared for Takeoff — hackathon demo. All shipments, regulations, and alerts shown here are
          simulated; nothing here is a legal compliance determination, and no message has been sent.
        </footer>
      </main>
    </div>
  );
}
