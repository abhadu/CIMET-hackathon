import { NavLink, Route, Routes } from "react-router-dom";
import LeadsPage from "./pages/LeadsPage";
import LeadPage from "./pages/LeadPage";
import DashboardPage from "./pages/DashboardPage";

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CIMET.</span> / CRM <span className="brand-sub">QA Gate</span>
        </div>
        <nav>
          <NavLink to="/" end>
            Leads
          </NavLink>
          <NavLink to="/queue/tl">TL queue</NavLink>
          <NavLink to="/queue/qa">QA queue</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<LeadsPage mode="all" />} />
          <Route path="/queue/tl" element={<LeadsPage mode="tl" />} />
          <Route path="/queue/qa" element={<LeadsPage mode="qa" />} />
          <Route path="/leads/:leadId" element={<LeadPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
        </Routes>
      </main>
    </div>
  );
}
