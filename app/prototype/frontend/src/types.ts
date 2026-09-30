// Shapes returned by the API. Pipe columns are always arrays (architecture §16/§18.1).

export interface Invariant {
  id: string;
  label: string;
  expected: string | number;
  actual: string | number;
  passed: boolean;
  detail?: string;
}

export interface Job {
  id: number;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  message: string | null;
  log?: string;
  error?: string | null;
  result?: Record<string, any>;
  batch_id?: number | null;
  build_id?: number | null;
  created_at: string;
}

export interface Batch {
  id: number;
  label: string;
  note?: string | null;
  created_at: string;
  files: number;
  statements: number;
  failed_recon: number;
  statement_total: number;
  pending: number;
  by_kind: { kind: string; status: string; n: number }[];
  last_build: { id: number; label: string; status: string } | null;
}

export interface SourceFile {
  id: number;
  filename: string;
  sha256: string;
  size: number;
  kind: string;
  detected_kind: string;
  kind_label: string;
  status: string;
  error: string | null;
  meta: Record<string, any>;
  override: Record<string, any>;
  sniff: any[][];
  statement: any | null;
  sheet: any | null;
  report: any | null;
  anomalies: number;
  upload_seq: number;
}

export interface Section {
  key: string;
  kind: "statement" | "platform";
  section: string;
  title: string;
  band: string;
  tint: string;
  statements?: { id: number; s_no: number; sheet: string; dist_no: string; date: string; period: string; category: string; file: string; total: number }[];
  months?: { month: string; label: string; date: string; dist: string; total: number }[];
}

export interface Layout {
  sections: Section[];
  fy_keys: string[];
  fy_labels: Record<string, string>;
  fy_totals: Record<string, number>;
  cat_label: string;
  client: string;
  statement_count: number;
  total_amount: number;
  total_mrm: number;
  row_count: number;
  basis_labels: Record<string, string>;
}

export interface Build {
  id: number;
  batch_id: number;
  label: string;
  generation: number;
  status: string;
  parent_build_id: number | null;
  root_build_id: number;
  row_count: number;
  total_amount: number;
  total_mrm: number;
  created_at: string;
  created_by?: string;
  config: Record<string, any>;
  layout: Layout;
  stats: Record<string, any>;
  invariants: Invariant[];
  decision_ids: number[];
  sheet?: { id: number; label: string; s_no: number | null } | null;
  lineage?: { id: number; label: string; generation: number; parent_build_id: number | null; status: string; row_count: number; created_at: string }[];
}

export interface BuildListItem {
  id: number;
  batch_id: number;
  label: string;
  generation: number;
  status: string;
  row_count: number;
  total_amount: number;
  total_mrm: number;
  parent_build_id: number | null;
  created_at: string;
  decisions: number;
}

export interface MatrixRow {
  id: number;
  o: number;
  key: string;
  origin: string;
  name: string;
  isrcs: string[];
  unreg: string[];
  works: string[];
  works_unreg: string[];
  d: number;
  e: number;
  u: number;
  s: string;
  a: Record<string, number>;
  m: Record<string, number>;
  f: Record<string, number>;
  b: string[];
  notes: number;
  booked: boolean;
  bn: string | null;
  merged: number;
  dec: number | null;
}

export interface Meta {
  version: string;
  kinds: Record<string, string>;
  categories: { code: string; label: string; matcher_regex: string; ordinal: number }[];
  societies: { code: string; name: string; country: string }[];
  statuses: { code: string; template: string; colour: string }[];
  basis: Record<string, string>;
  signals: Record<string, { weight: number; label: string }>;
  artifacts: Record<string, { label: string; scope: string; section: string }>;
  roles: string[];
  decider_roles: string[];
  thresholds: { suggest: number; review: number; recon_tolerance: number };
  reference: { coverage: any; mismatch: any; inputs_available: boolean };
}

export interface CoverageRun {
  id: number;
  build_id: number;
  sheet_id: number;
  mode: "STRICT" | "RESOLVED";
  sources: string[];
  period_from: string | null;
  period_to: string | null;
  min_amount: number;
  status: string;
  finding_count: number;
  strict_count: number;
  resolved_count: number;
  revenue_at_risk: number;
  royalty_received: number;
  name_present_count: number;
  stats: Record<string, any>;
  invariants: Invariant[];
  sheet: { id: number; label: string } | null;
  exports: { id: number; filename: string; size: number; sha256: string; created_at: string }[];
  created_at: string;
}

export interface CoverageRow {
  id: number;
  ordinal: number;
  song_name: string;
  name_key: string;
  evidence: string;
  present_in: "statement" | "platform" | "both";
  royalty: number;
  platform_rev: number;
  streams: number;
  isrcs: string[];
  work_nos: string[];
  statements: Record<string, number>;
  months: Record<string, number>;
  fy: Record<string, number>;
  spellings: string[];
  albums: string[];
}

export interface Candidate {
  id: number;
  kind: string;
  name_key: string;
  display_name: string;
  confidence: number;
  band: "suggested" | "review" | "unlikely";
  status: "open" | "merged" | "not_same";
  default_survivor: number;
  signals: { code: string; weight: number; label: string }[];
  members: CandidateMember[];
  decision: { id: number; verdict: string; decided_by: string; decided_at: string; survivor_key: string; note: string | null } | null;
}

export interface CandidateMember {
  id: number;
  key: string;
  name: string;
  origin: string;
  status: string;
  d: number;
  e: number;
  u: number;
  isrcs: { isrc: string; registered: number; via: string }[];
  works: { work_no: string; registered: number }[];
  by_section: Record<string, number>;
  months: Record<string, number>;
  albums: string[];
  titles: string[];
  basis: string[];
}
