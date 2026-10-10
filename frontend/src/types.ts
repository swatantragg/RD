// Shapes returned by the API. Money is exact decimal text.
export type State = { code: string; text: string };

export type Client = {
  id: number; code: string; name: string; active: boolean; output_prefix: string; next_generation: number;
  song_list_name: string; distributors: { name: string; currency: string; basis: string; platforms: string[] }[];
  holders: { id: number; society: string; member_no: string; name: string; ipi_name_no: string | null; ipi_base_no: string | null }[];
  last_published?: string | null; last_published_at?: string | null;
};

export type Problem = { code: string; severity: string; message: string; detail?: string | null };
export type Question = { field: string; message: string; options: { value: string; label: string }[]; required: boolean };

export type FileOut = {
  id: number; filename: string; kind: string; kind_label: string; label: string | null; status: string;
  status_text: string; problems: Problem[]; questions: Question[];
  summary: { total?: string | null; lines?: number; works?: number; recordings?: number; entries?: number; rows?: number };
  meta: Record<string, string>; meta_source: Record<string, string>; uploaded_at: string; bytes: number;
  choice: { relation?: string | null };
};

export type RunIssue = {
  kind: string; blocking: boolean; file_ids: number[]; title: string; message: string;
  actions: { action: string; file_id: number; label: string }[];
};

export type BuildRef = { id: number; version: number; state: string; created_at: string; finished_at: string | null;
  generation: string | null; error: string | null };

export type Run = {
  id: number; title: string; client: Client; created_by: string; created_at: string; updated_at: string;
  files: FileOut[]; counts: { total: number; ready: number; needs_review: number; left_out: number; error: number };
  issues: RunIssue[]; blocked: string[]; can_process: boolean; builds: BuildRef[]; latest_build: number | null;
  changed_since_build: boolean; state: State; closed: boolean;
  can_delete: boolean; delete_note: string | null;
};

export type RunSummary = {
  id: number; title: string; client_id: number; client_code: string; client_name: string; created_by: string;
  updated_at: string; files: number; state: State; latest_build: number | null;
};

export type Issue = {
  no: number; kind: string; severity: string; category: string; title: string; message: string;
  subject: any; actions: string[]; later: boolean; decision: { id: number; kind: string; state: string; text: string } | null;
};

export type Report = {
  id: number; kind: "MASTER" | "MISSING" | "NON_CLIENT"; final: boolean; filename: string; rows: number | null;
  available: boolean; reason: string | null; totals: any; state: { code: string; text: string; reason?: string };
};

export type Decision = {
  id: number; kind: string; text: string; state: string; reason: string | null; made_by: string; made_at: string;
  made_by_id: number; checked_by: string | null; subject: any; value: any; original: any; evidence: any;
  client_code?: string;
};

export type Build = {
  id: number; run_id: number; run_title: string; version: number; state: string; state_text: string; client: Client;
  stages: { name: string; state: string }[]; error: string | null; error_detail: string | null;
  summary: {
    royalty?: string; platform?: Record<string, string>; statements?: number; platform_reports?: number; lines?: number;
    rows?: number; matched_rows?: number; held_rows?: number; held_royalty?: string; held_platform?: string;
    missing?: number; not_ours?: number; unreviewed?: number; distributions?: number; base?: string; grain?: string;
    reconciliation?: { label: string; section: string; total: string; ok: boolean }[]; review_items?: number;
    money_items?: number; matching_items?: number; findings_by_status?: Record<string, number>;
  };
  checks: { id: string; ok: boolean; text: string; detail?: string; blocking?: boolean }[]; notices: string[];
  left_out: { file_id: number; label: string; reason: string; total?: string | null }[];
  generation: string | null; created_by: string; created_at: string; finished_at: string | null;
  published_by: string | null; published_at: string | null; returned_reason: string | null;
  issues: Issue[]; findings: number; reports: Report[]; can_publish: boolean; blocking: number;
  inputs: { file_id: number; filename: string; kind: string; label: string; total: string | null }[];
  publishing: boolean;
};

export type Finding = {
  no: number; title: string; isrcs: string[]; work_nos: string[]; royalty: string; platform: string; status: string;
  status_text: string; status_original: string | null; sources: string; proposal: any;
};
