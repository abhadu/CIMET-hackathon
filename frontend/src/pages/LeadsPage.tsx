import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Alert, LeadSummary } from "../types";

type Mode = "all" | "tl" | "qa";

const TITLES: Record<Mode, string> = {
  all: "All leads",
  tl: "Team lead queue — held sales",
  qa: "QA queue — low confidence and calibration sample",
};

export function StatusChip({ status }: { status: string }) {
  return <span className={`chip chip-${status.toLowerCase()}`}>{status.replace(/_/g, " ")}</span>;
}

export default function LeadsPage({ mode }: { mode: Mode }) {
  const [leads, setLeads] = useState<LeadSummary[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = mode === "tl" ? api.tlQueue : mode === "qa" ? api.qaQueue : () => api.leads();
    load().then(setLeads).catch((e) => setError(String(e.message)));
    api.alerts().then(setAlerts).catch(() => setAlerts([]));
    const timer = setInterval(() => load().then(setLeads).catch(() => undefined), 4000);
    return () => clearInterval(timer);
  }, [mode]);

  return (
    <section>
      <h1>{TITLES[mode]}</h1>
      {error && <p className="error">{error}</p>}
      {alerts.length > 0 && mode !== "qa" && (
        <div className="alerts">
          {alerts.map((a) => (
            <div key={a.id} className="alert">
              <strong>{a.agent_id}</strong> · {a.check_code} · {a.message}
            </div>
          ))}
        </div>
      )}
      <table className="table">
        <thead>
          <tr>
            <th>Lead</th>
            <th>Retailer</th>
            <th>Agent</th>
            <th>Campaign</th>
            <th>Call date</th>
            <th>Status</th>
            <th>Critical fails</th>
            <th>Score</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => (
            <tr key={lead.id}>
              <td>
                <Link to={`/leads/${lead.id}`}>{lead.id}</Link>
              </td>
              <td>{lead.retailer_id}</td>
              <td>{lead.agent_id}</td>
              <td>{lead.campaign}</td>
              <td>{lead.call_date}</td>
              <td>
                <StatusChip status={lead.status} />
              </td>
              <td className={lead.critical_fail_count ? "bad" : ""}>{lead.critical_fail_count ?? "–"}</td>
              <td>{lead.score_with_fatal ?? "–"}</td>
              <td className="muted small">{lead.status_reason}</td>
            </tr>
          ))}
          {leads.length === 0 && (
            <tr>
              <td colSpan={9} className="muted">
                Nothing here.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
