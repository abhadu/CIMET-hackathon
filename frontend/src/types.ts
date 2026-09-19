export type LeadStatus =
  | "PENDING_RECORDING"
  | "TRANSCRIBING"
  | "SCORING"
  | "AUTO_SUBMITTED"
  | "HELD"
  | "QA_REVIEW"
  | "QA_SAMPLED"
  | "RELEASED"
  | "SUBMITTED"
  | "CANCELLED"
  | "FAILED";

export type GateDecision = "AUTO_SUBMIT" | "HOLD" | "QA_REVIEW" | "QA_SAMPLE";
export type CheckOutcome = "PASS" | "FAIL" | "NOTE" | "UNCERTAIN";
export type CheckType = "verbatim" | "factual" | "behaviour";

export interface LeadSummary {
  id: string;
  retailer_id: string;
  agent_id: string;
  campaign: string;
  site: string;
  tl_id: string;
  call_date: string;
  status: LeadStatus;
  status_reason: string | null;
  gate_decision: GateDecision | null;
  critical_fail_count: number | null;
  score_with_fatal: number | null;
  updated_at: string;
}

export interface CheckResult {
  id: number;
  check_code: string;
  check_name: string;
  check_type: CheckType;
  is_critical: boolean;
  weight: number;
  result: CheckOutcome;
  effective_result: CheckOutcome;
  confidence: number;
  quote: string | null;
  start_ms: number | null;
  end_ms: number | null;
  speaker: string | null;
  expected_value: string | null;
  observed_value: string | null;
  reasoning: string;
  overridden: boolean;
}

export interface ScoreRun {
  id: number;
  library_version: string;
  gate_decision: GateDecision;
  gate_reasons: string[];
  score_with_fatal: number;
  score_without_fatal: number;
  critical_fail_count: number;
  uncertain_count: number;
  created_at: string;
  results: CheckResult[];
}

export interface Utterance {
  index: number;
  role: string;
  start: number;
  end: number;
  text: string;
}

export interface Recording {
  id: number;
  source: string;
  has_audio: boolean;
  audio_url: string | null;
  duration_s: number;
  timing: "measured" | "estimated";
  utterances: Utterance[];
  redactions: { kind: string; start_ms: number; end_ms: number; digit_count: number }[];
}

export interface Override {
  id: number;
  check_result_id: number;
  auditor: string;
  original_result: CheckOutcome;
  new_result: CheckOutcome;
  reason: string;
  created_at: string;
}

export interface LeadDetail extends LeadSummary {
  plan_id: string | null;
  plan_name: string | null;
  last_completed_step: string;
  crm_fields: Record<string, unknown>;
  run: ScoreRun | null;
  recording: Recording | null;
  overrides: Override[];
  can_submit: boolean;
}

export interface Alert {
  id: number;
  agent_id: string;
  tl_id: string;
  check_code: string;
  kind: string;
  message: string;
  window_start: string;
  window_end: string;
  created_at: string;
}

export interface GroupStats {
  key: string;
  sales_scored: number;
  auto_submitted: number;
  held: number;
  qa_review: number;
  qa_sampled: number;
  first_pass_yield: number;
  critical_fail_rate: number;
  avg_score_with_fatal: number;
  avg_score_without_fatal: number;
  top_failing_checks: { code: string; name: string; count: number }[];
  auditor_agreement_rate: number | null;
  human_reviews: number;
  repeat_offence_alerts: number;
}

export interface Dashboard {
  period: string;
  group_by: string;
  window_start: string;
  window_end: string;
  groups: GroupStats[];
  series: { day: string; scored: number; held: number }[];
}
