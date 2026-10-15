import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./lib/api.js";
import Dashboard from "./pages/Dashboard.jsx";
import NewClaim from "./pages/NewClaim.jsx";
import ClaimDetail from "./pages/ClaimDetail.jsx";

const ConfigContext = createContext({ confidenceThreshold: 80, categories: [], severities: [] });
export const useConfig = () => useContext(ConfigContext);

export default function App() {
  const [config, setConfig] = useState({ confidenceThreshold: 80, categories: [], severities: [] });
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setApiDown(true));
  }, []);

  return (
    <ConfigContext.Provider value={config}>
      <div className="shell">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark">◆</span> Claim Intelligence
          </div>
          <nav>
            <NavLink to="/" end>Dashboard</NavLink>
            <NavLink to="/review">Review Queue</NavLink>
            <NavLink to="/new" className="nav-cta">+ New Claim</NavLink>
          </nav>
          <div className="topbar-meta">
            AI: <b>{config.aiProvider || "…"}</b> · threshold <b>{config.confidenceThreshold}%</b>
          </div>
        </header>
        {apiDown && (
          <div className="alert alert-bad banner">Backend not reachable at the configured API URL. Start it with <code>uvicorn app.main:app --reload</code>.</div>
        )}
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/review" element={<Dashboard reviewQueue />} />
            <Route path="/new" element={<NewClaim />} />
            <Route path="/claims/:claimId" element={<ClaimDetail />} />
          </Routes>
        </main>
      </div>
    </ConfigContext.Provider>
  );
}
