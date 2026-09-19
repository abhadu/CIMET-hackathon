import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { CheckResult, LeadDetail, Utterance } from "../types";
import { StatusChip } from "./LeadsPage";

function fmt(ms: number | null): string {
  if (ms === null) return "--:--";
  const s = Math.round(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

const ICON: Record<string, string> = { PASS: "✓", FAIL: "✕", NOTE: "–", UNCERTAIN: "?" };

function flatten(obj: Record<string, unknown>, prefix = ""): [string, unknown][] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? flatten(v as Record<string, unknown>, `${prefix}${k}.`)
      : [[`${prefix}${k}`, v]],
  );
}

export default function LeadPage() {
  const { leadId = "" } = useParams();
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeUtterance, setActiveUtterance] = useState<number | null>(null);
  const [overrideFor, setOverrideFor] = useState<CheckResult | null>(null);
  const [editField, setEditField] = useState<{ path: string; value: string } | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const utteranceRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const reload = useCallback(() => {
    api.lead(leadId).then(setLead).catch((e) => setError(String(e.message)));
  }, [leadId]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (!lead || !["SCORING", "TRANSCRIBING"].includes(lead.status)) return;
    const timer = setInterval(reload, 2000);
    return () => clearInterval(timer);
  }, [lead, reload]);

  const utteranceAt = useMemo(() => {
    const utts = lead?.recording?.utterances ?? [];
    return (ms: number): Utterance | undefined =>
      utts.find((u) => ms / 1000 >= u.start - 0.2 && ms / 1000 <= u.end + 0.2) ??
      utts.reduce<Utterance | undefined>((best, u) => (u.start <= ms / 1000 ? u : best), undefined);
  }, [lead]);

  const jump = (ms: number | null) => {
    if (ms === null) return;
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = ms / 1000;
      void audio.play().catch(() => undefined);
    }
    const utt = utteranceAt(ms);
    if (utt) {
      setActiveUtterance(utt.index);
      utteranceRefs.current[utt.index]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!lead) return <p className="muted">{error ?? "Loading…"}</p>;

  const results = lead.run?.results ?? [];
  const byType = (type: string) => results.filter((r) => r.check_type === type);
  const reviewable = ["QA_REVIEW", "QA_SAMPLED", "HELD"].includes(lead.status);

  return (
    <section className="lead">
      <div className="lead-head">
        <div>
          <p className="eyebrow">
            <Link to="/">Leads</Link> / {lead.retailer_id} · {lead.agent_id} · {lead.campaign} · {lead.call_date}
          </p>
          <h1>
            Lead {lead.id} <StatusChip status={lead.status} />
          </h1>
          <p className="muted">{lead.status_reason}</p>
        </div>
        <div className="actions">
          <button disabled={busy || !lead.can_submit} onClick={() => run(() => api.submit(lead.id))}>
            Submit sale
          </button>
          <button disabled={busy || !lead.recording} onClick={() => run(() => api.rescore(lead.id))}>
            Re-score
          </button>
          {reviewable && (
            <>
              <button
                disabled={busy}
                onClick={() => run(() => api.review(lead.id, { reviewer: "qa-reviewer", decision: "approve" }))}
              >
                Approve
              </button>
              <button
                disabled={busy}
                className="danger"
                onClick={() => run(() => api.review(lead.id, { reviewer: "qa-reviewer", decision: "reject" }))}
              >
                Reject
              </button>
            </>
          )}
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      {lead.run && (
        <div className="scorecard">
          <div>
            <span className="label">Gate</span>
            <strong className={`gate gate-${lead.run.gate_decision.toLowerCase()}`}>{lead.run.gate_decision}</strong>
          </div>
          <div>
            <span className="label">Score (fatal)</span>
            <strong>{lead.run.score_with_fatal}</strong>
          </div>
          <div>
            <span className="label">Score (no fatal)</span>
            <strong>{lead.run.score_without_fatal}</strong>
          </div>
          <div>
            <span className="label">Critical fails</span>
            <strong>{lead.run.critical_fail_count}</strong>
          </div>
          <div>
            <span className="label">Low confidence</span>
            <strong>{lead.run.uncertain_count}</strong>
          </div>
          <div>
            <span className="label">Check library</span>
            <strong>v{lead.run.library_version}</strong>
          </div>
          <div className="reasons">
            {lead.run.gate_reasons.map((r) => (
              <div key={r}>{r}</div>
            ))}
          </div>
        </div>
      )}

      <div className="columns">
        <div className="col">
          {(["verbatim", "factual", "behaviour"] as const).map((type) => (
            <div key={type} className="group">
              <h2>{type === "verbatim" ? "A · Verbatim / script" : type === "factual" ? "B · Factual match" : "C · Behaviour"}</h2>
              {byType(type).map((r) => (
                <div key={r.id} className={`result result-${r.effective_result.toLowerCase()}`}>
                  <div className="result-line">
                    <span className="icon">{ICON[r.effective_result]}</span>
                    <span className="outcome">{r.effective_result}</span>
                    <span className="name">
                      {r.check_name}
                      {r.is_critical && <em> (critical)</em>}
                      {r.overridden && <em className="ov"> overridden from {r.result}</em>}
                    </span>
                    {r.start_ms !== null && (
                      <button className="ts" onClick={() => jump(r.start_ms)}>
                        ▶ {fmt(r.start_ms)}
                      </button>
                    )}
                  </div>
                  <div className="reasoning">{r.reasoning}</div>
                  {(r.expected_value || r.observed_value) && (
                    <div className="compare">
                      {r.observed_value && (
                        <span>
                          Heard: <code>{r.observed_value}</code>
                        </span>
                      )}
                      {r.expected_value && (
                        <span>
                          Record: <code>{r.expected_value}</code>
                        </span>
                      )}
                      <span className="muted">confidence {Math.round(r.confidence * 100)}%</span>
                    </div>
                  )}
                  {r.quote && <blockquote>“{r.quote}”</blockquote>}
                  {lead.run && ["FAIL", "UNCERTAIN", "NOTE"].includes(r.effective_result) && (
                    <button className="link" onClick={() => setOverrideFor(r)}>
                      Challenge / override
                    </button>
                  )}
                </div>
              ))}
            </div>
          ))}

          {overrideFor && (
            <form
              className="panel"
              onSubmit={(e) => {
                e.preventDefault();
                const form = new FormData(e.currentTarget);
                run(() =>
                  api.override(lead.id, overrideFor.id, {
                    auditor: String(form.get("auditor")),
                    new_result: String(form.get("new_result")),
                    reason: String(form.get("reason")),
                  }),
                ).then(() => setOverrideFor(null));
              }}
            >
              <h3>Override “{overrideFor.check_name}”</h3>
              <input name="auditor" placeholder="Auditor / TL id" required defaultValue="tl-01" />
              <select name="new_result" defaultValue="PASS">
                <option value="PASS">PASS</option>
                <option value="FAIL">FAIL</option>
                <option value="NOTE">NOTE</option>
              </select>
              <input name="reason" placeholder="Reason (logged, never dropped)" required />
              <div className="actions">
                <button type="submit" disabled={busy}>
                  Log override
                </button>
                <button type="button" onClick={() => setOverrideFor(null)}>
                  Cancel
                </button>
              </div>
            </form>
          )}

          <div className="group">
            <h2>CRM fields</h2>
            <table className="table compact">
              <tbody>
                {flatten(lead.crm_fields).map(([path, value]) => (
                  <tr key={path}>
                    <td className="muted">{path}</td>
                    <td>{value === null ? "—" : String(value)}</td>
                    <td>
                      <button className="link" onClick={() => setEditField({ path, value: value === null ? "" : String(value) })}>
                        correct
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {editField && (
              <form
                className="panel"
                onSubmit={(e) => {
                  e.preventDefault();
                  run(() =>
                    api.patchCrm(lead.id, { actor: "tl-01", fields: { [editField.path]: editField.value }, rescore: true }),
                  ).then(() => setEditField(null));
                }}
              >
                <h3>Correct {editField.path} and re-score</h3>
                <input value={editField.value} onChange={(e) => setEditField({ ...editField, value: e.target.value })} />
                <div className="actions">
                  <button type="submit" disabled={busy}>
                    Save and re-score
                  </button>
                  <button type="button" onClick={() => setEditField(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>

          {lead.overrides.length > 0 && (
            <div className="group">
              <h2>Override log</h2>
              {lead.overrides.map((o) => (
                <div key={o.id} className="small">
                  {new Date(o.created_at).toLocaleString()} · <strong>{o.auditor}</strong> changed result #{o.check_result_id}{" "}
                  {o.original_result} → {o.new_result}: {o.reason}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="col transcript">
          <h2>Transcript</h2>
          {lead.recording?.has_audio && lead.recording.audio_url && (
            <audio ref={audioRef} controls src={lead.recording.audio_url} className="player" />
          )}
          {lead.recording?.timing === "estimated" && (
            <p className="muted small">Transcript supplied without audio: timestamps are estimated from word count.</p>
          )}
          {lead.recording?.redactions.length ? (
            <p className="redaction-note">
              {lead.recording.redactions.length} card number(s) redacted before storage at{" "}
              {lead.recording.redactions.map((r) => fmt(r.start_ms)).join(", ")}.
            </p>
          ) : null}
          {!lead.recording && <p className="muted">No transcript yet.</p>}
          {lead.recording?.utterances.map((u) => (
            <div
              key={u.index}
              ref={(el) => {
                utteranceRefs.current[u.index] = el;
              }}
              className={`utt utt-${u.role} ${activeUtterance === u.index ? "active" : ""}`}
              onClick={() => jump(u.start * 1000)}
            >
              <span className="utt-meta">
                {fmt(u.start * 1000)} · {u.role}
              </span>
              <span>{u.text}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
