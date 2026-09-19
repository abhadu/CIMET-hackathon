import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dashboard } from "../types";

export default function DashboardPage() {
  const [period, setPeriod] = useState("weekly");
  const [groupBy, setGroupBy] = useState("agent");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard(period, groupBy)
      .then(setData)
      .catch((e) => setError(String(e.message)));
  }, [period, groupBy]);

  return (
    <section>
      <div className="lead-head">
        <h1>Dashboard</h1>
        <div className="actions">
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
            <option value="agent">By agent</option>
            <option value="tl">By team lead</option>
            <option value="retailer">By retailer</option>
            <option value="campaign">By campaign</option>
            <option value="site">By site</option>
          </select>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <p className="muted">
            {data.window_start} to {data.window_end}
          </p>
          <div className="bars">
            {data.series.map((p) => (
              <div key={p.day} className="bar" title={`${p.day}: ${p.scored} scored, ${p.held} held`}>
                <div className="bar-fill" style={{ height: `${Math.min(100, p.scored * 12)}%` }}>
                  <div className="bar-held" style={{ height: p.scored ? `${(p.held / p.scored) * 100}%` : 0 }} />
                </div>
                <span>{p.day.slice(5)}</span>
              </div>
            ))}
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{data.group_by}</th>
                <th>Scored</th>
                <th>Auto</th>
                <th>Held</th>
                <th>QA</th>
                <th>First-pass yield</th>
                <th>Critical fail rate</th>
                <th>Score (fatal / no fatal)</th>
                <th>Top failing checks</th>
                <th>Auditor agreement</th>
                <th>Repeat offences</th>
              </tr>
            </thead>
            <tbody>
              {data.groups.map((g) => (
                <tr key={g.key}>
                  <td>
                    <strong>{g.key}</strong>
                  </td>
                  <td>{g.sales_scored}</td>
                  <td>{g.auto_submitted}</td>
                  <td className={g.held ? "bad" : ""}>{g.held}</td>
                  <td>{g.qa_review + g.qa_sampled}</td>
                  <td>{g.first_pass_yield}%</td>
                  <td className={g.critical_fail_rate > 0 ? "bad" : ""}>{g.critical_fail_rate}%</td>
                  <td>
                    {g.avg_score_with_fatal} / {g.avg_score_without_fatal}
                  </td>
                  <td className="small">
                    {g.top_failing_checks.map((c) => (
                      <div key={c.code}>
                        {c.name} × {c.count}
                      </div>
                    ))}
                  </td>
                  <td>{g.auditor_agreement_rate === null ? "–" : `${g.auditor_agreement_rate}% (${g.human_reviews})`}</td>
                  <td className={g.repeat_offence_alerts ? "bad" : ""}>{g.repeat_offence_alerts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
