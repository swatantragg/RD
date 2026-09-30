-- Sangam prototype schema (SQLite). Mirrors architecture §15 table for table where the
-- prototype needs it. Rules kept from the spec:
--   * one fact, one row - an amount lives once in royalty_line / platform_line
--   * no pipe strings   - every '|' list is a child table with an ordinal (§16)
--   * builds are immutable - a correction is a new build_run with parent_build_id
--   * decisions are data - merge_decision rows, never edited cells
-- Money is stored as SQLite REAL (IEEE-754 double), which round-trips Python floats
-- exactly; every sum and every rounding happens in Python through penny_fix.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS society (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS category (
    code TEXT PRIMARY KEY, label TEXT NOT NULL, matcher_regex TEXT NOT NULL,
    ordinal INTEGER NOT NULL);

-- ------------------------------------------------------------------ intake
CREATE TABLE IF NOT EXISTS ingest_batch (
    id INTEGER PRIMARY KEY, label TEXT NOT NULL, note TEXT,
    created_at TEXT NOT NULL, created_by TEXT);

CREATE TABLE IF NOT EXISTS source_file (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
    sha256 TEXT NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL,
    stored_path TEXT NOT NULL, upload_seq INTEGER NOT NULL,
    detected_kind TEXT NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL,              -- uploaded | extracted | quarantined | failed
    sniff_json TEXT, meta_json TEXT, override_json TEXT, error TEXT,
    created_at TEXT NOT NULL, extracted_at TEXT,
    UNIQUE (batch_id, sha256));

CREATE TABLE IF NOT EXISTS ingest_anomaly (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, sheet_row INTEGER, detail TEXT NOT NULL);

-- ------------------------------------------------------------------ TYPE A / B statements
CREATE TABLE IF NOT EXISTS statement (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL UNIQUE REFERENCES source_file(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
    s_no INTEGER NOT NULL, dist_no TEXT NOT NULL,
    category_code TEXT NOT NULL, category TEXT NOT NULL, section TEXT NOT NULL,
    schema TEXT NOT NULL CHECK (schema IN ('Standard', 'Overseas')),
    society_code TEXT, society TEXT, country TEXT,
    p_start TEXT, p_end TEXT, fy TEXT, period TEXT NOT NULL, stmt_date TEXT,
    redistribution INTEGER NOT NULL DEFAULT 0,
    member_no TEXT, member_name TEXT, ipi_name TEXT, ipi_base TEXT,
    file_total REAL, extracted_total REAL NOT NULL, subtotal_total REAL,
    subtotal_lines INTEGER NOT NULL DEFAULT 0, line_count INTEGER NOT NULL,
    block_count INTEGER NOT NULL, work_count INTEGER NOT NULL,
    recon_diff REAL, reconciled INTEGER NOT NULL, checks_json TEXT,
    header_row INTEGER, stop_row INTEGER, footer_json TEXT);

CREATE TABLE IF NOT EXISTS statement_block (          -- one carry-forward block = one work occurrence
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statement(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, sheet_row INTEGER NOT NULL,
    work_no TEXT NOT NULL, raw_no TEXT, synthetic INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL, name_key TEXT NOT NULL, av TEXT, language TEXT,
    amount REAL NOT NULL, money_lines INTEGER NOT NULL,
    UNIQUE (statement_id, ordinal));
CREATE INDEX IF NOT EXISTS ix_block_work ON statement_block(work_no);

CREATE TABLE IF NOT EXISTS royalty_line (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statement(id) ON DELETE CASCADE,
    block_id INTEGER NOT NULL REFERENCES statement_block(id) ON DELETE CASCADE,
    sheet_row INTEGER NOT NULL, work_no TEXT NOT NULL,
    party TEXT, role TEXT, society TEXT, own REAL, coll REAL, pool TEXT, source TEXT,
    buckets_json TEXT, amount REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_line_stmt ON royalty_line(statement_id);

-- ------------------------------------------------------------------ TYPE C / F song sheets
CREATE TABLE IF NOT EXISTS user_sheet (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL UNIQUE REFERENCES source_file(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
    label TEXT NOT NULL, s_no INTEGER, header_fp TEXT NOT NULL, header_row INTEGER NOT NULL,
    header_json TEXT, proposal_json TEXT, row_count INTEGER NOT NULL DEFAULT 0,
    is_catalogue INTEGER NOT NULL DEFAULT 0,
    mapping_status TEXT NOT NULL CHECK (mapping_status IN ('proposed', 'confirmed')),
    created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_sheet_fp ON user_sheet(header_fp);

CREATE TABLE IF NOT EXISTS user_sheet_column_map (
    sheet_id INTEGER NOT NULL REFERENCES user_sheet(id) ON DELETE CASCADE,
    field TEXT NOT NULL CHECK (field IN ('song_name', 'internal_no', 'isrc', 'amount', 'period')),
    col_index INTEGER NOT NULL, confidence REAL NOT NULL, confirmed_by TEXT,
    PRIMARY KEY (sheet_id, field));

CREATE TABLE IF NOT EXISTS user_sheet_entry (
    id INTEGER PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES user_sheet(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, sheet_row INTEGER NOT NULL,
    name TEXT NOT NULL, name_key TEXT NOT NULL,
    raw_no TEXT,                                       -- 'NEED TO REGISTER' survives here
    amount REAL, period TEXT,
    UNIQUE (sheet_id, ordinal));
CREATE INDEX IF NOT EXISTS ix_entry_name ON user_sheet_entry(sheet_id, name_key);

CREATE TABLE IF NOT EXISTS user_sheet_entry_work (      -- internal numbers, exploded
    entry_id INTEGER NOT NULL REFERENCES user_sheet_entry(id) ON DELETE CASCADE,
    work_no TEXT NOT NULL, ordinal INTEGER NOT NULL,
    PRIMARY KEY (entry_id, work_no));

CREATE TABLE IF NOT EXISTS user_sheet_entry_isrc (      -- the '|' list, exploded; 0 = primary
    entry_id INTEGER NOT NULL REFERENCES user_sheet_entry(id) ON DELETE CASCADE,
    isrc TEXT NOT NULL, ordinal INTEGER NOT NULL,
    PRIMARY KEY (entry_id, isrc));
CREATE INDEX IF NOT EXISTS ix_entry_isrc ON user_sheet_entry_isrc(isrc);

-- ------------------------------------------------------------------ TYPE D / E platform reports
CREATE TABLE IF NOT EXISTS platform_report (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL UNIQUE REFERENCES source_file(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('REVENUE', 'USAGE')),
    client TEXT NOT NULL, label TEXT NOT NULL, month_from TEXT, month_to TEXT,
    line_count INTEGER NOT NULL, isrc_count INTEGER NOT NULL, total REAL NOT NULL);

CREATE TABLE IF NOT EXISTS platform_line (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES platform_report(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, sheet_row INTEGER NOT NULL, month TEXT NOT NULL,
    isrc TEXT NOT NULL, content_name TEXT, album TEXT, upc TEXT, content_type TEXT,
    value REAL NOT NULL);                              -- revenue (REVENUE) or streams (USAGE)
CREATE INDEX IF NOT EXISTS ix_pline_report ON platform_line(report_id, isrc);

-- ------------------------------------------------------------------ builds (SKV)
CREATE TABLE IF NOT EXISTS build_run (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
    parent_build_id INTEGER REFERENCES build_run(id),
    root_build_id INTEGER, generation INTEGER NOT NULL, label TEXT NOT NULL,
    status TEXT NOT NULL, config_json TEXT NOT NULL, layout_json TEXT, stats_json TEXT,
    invariants_json TEXT, decision_ids_json TEXT NOT NULL DEFAULT '[]',
    catalogue_sheet_id INTEGER, row_count INTEGER, total_amount REAL, total_mrm REAL,
    created_at TEXT NOT NULL, created_by TEXT);

CREATE TABLE IF NOT EXISTS build_statement (
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    statement_id INTEGER NOT NULL REFERENCES statement(id) ON DELETE CASCADE,
    PRIMARY KEY (build_id, statement_id));

CREATE TABLE IF NOT EXISTS build_report (
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    report_id INTEGER NOT NULL REFERENCES platform_report(id) ON DELETE CASCADE,
    PRIMARY KEY (build_id, report_id));

CREATE TABLE IF NOT EXISTS rd_row (
    id INTEGER PRIMARY KEY,
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,                  -- stable across the builds of one lineage
    ordinal INTEGER NOT NULL,               -- sort order in the matrix
    origin TEXT NOT NULL CHECK (origin IN ('catalogue', 'statement', 'platform', 'usage')),
    name TEXT NOT NULL, name_key TEXT NOT NULL, name_key2 TEXT NOT NULL,
    catalogue_entry_id INTEGER,
    total_amount REAL NOT NULL, total_mrm REAL NOT NULL, total_usage REAL NOT NULL,
    status TEXT NOT NULL, status_code TEXT NOT NULL, booked_note TEXT,
    basis_json TEXT NOT NULL DEFAULT '[]', notes_json TEXT NOT NULL DEFAULT '[]',
    merged_keys_json TEXT NOT NULL DEFAULT '[]', merged_from_decision INTEGER,
    UNIQUE (build_id, row_key));
CREATE INDEX IF NOT EXISTS ix_rdrow_build ON rd_row(build_id, ordinal);

CREATE TABLE IF NOT EXISTS rd_row_isrc (
    row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    isrc TEXT NOT NULL, ordinal INTEGER NOT NULL,
    registered INTEGER NOT NULL,            -- 1 = in the catalogue, 0 = reported only by a platform
    via TEXT, PRIMARY KEY (row_id, isrc));
CREATE INDEX IF NOT EXISTS ix_rdisrc ON rd_row_isrc(isrc);

CREATE TABLE IF NOT EXISTS rd_row_work (
    row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    work_no TEXT NOT NULL, ordinal INTEGER NOT NULL, registered INTEGER NOT NULL,
    PRIMARY KEY (row_id, work_no));

CREATE TABLE IF NOT EXISTS rd_row_amount (             -- one cell per (row, statement)
    row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    statement_id INTEGER NOT NULL, amount REAL NOT NULL, raw REAL NOT NULL,
    PRIMARY KEY (row_id, statement_id));

CREATE TABLE IF NOT EXISTS rd_row_mrm (                -- one cell per (row, month)
    row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    month TEXT NOT NULL, amount REAL NOT NULL, raw REAL NOT NULL,
    PRIMARY KEY (row_id, month));

CREATE TABLE IF NOT EXISTS rd_row_fy (
    row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    fy TEXT NOT NULL, amount REAL NOT NULL, PRIMARY KEY (row_id, fy));

CREATE TABLE IF NOT EXISTS rd_row_mrm_isrc (           -- which ISRC brought revenue, and how
    row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    isrc TEXT NOT NULL, basis TEXT NOT NULL, revenue REAL NOT NULL, title TEXT, album TEXT,
    PRIMARY KEY (row_id, isrc));

-- ------------------------------------------------------------------ §12 merge review
CREATE TABLE IF NOT EXISTS merge_candidate (
    id INTEGER PRIMARY KEY,
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('SAME_NAME_DIFF_ISRC', 'SAME_NAME_DIFF_INTERNAL_NO',
                                       'SAME_NAME_NO_IDENTIFIER', 'VERSION_VARIANT')),
    name_key TEXT NOT NULL, display_name TEXT NOT NULL,
    confidence REAL NOT NULL, band TEXT NOT NULL, signals_json TEXT NOT NULL,
    default_survivor INTEGER, status TEXT NOT NULL DEFAULT 'open',
    UNIQUE (build_id, kind, name_key));

CREATE TABLE IF NOT EXISTS merge_candidate_member (
    candidate_id INTEGER NOT NULL REFERENCES merge_candidate(id) ON DELETE CASCADE,
    rd_row_id INTEGER NOT NULL REFERENCES rd_row(id) ON DELETE CASCADE,
    PRIMARY KEY (candidate_id, rd_row_id));

CREATE TABLE IF NOT EXISTS merge_decision (               -- keyed to the lineage, by stable row keys
    id INTEGER PRIMARY KEY,
    root_build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    source_build_id INTEGER NOT NULL, candidate_id INTEGER,
    kind TEXT NOT NULL, name_key TEXT NOT NULL, display_name TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('MERGE', 'NOT_THE_SAME')),
    survivor_key TEXT, confidence REAL, evidence_json TEXT,
    decided_by TEXT NOT NULL, decided_at TEXT NOT NULL, note TEXT,
    active INTEGER NOT NULL DEFAULT 1, revoked_by TEXT, revoked_at TEXT);

CREATE TABLE IF NOT EXISTS merge_decision_member (
    decision_id INTEGER NOT NULL REFERENCES merge_decision(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL, PRIMARY KEY (decision_id, row_key));

-- ------------------------------------------------------------------ §11 coverage audit
CREATE TABLE IF NOT EXISTS coverage_run (
    id INTEGER PRIMARY KEY,
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    sheet_id INTEGER NOT NULL REFERENCES user_sheet(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('STRICT', 'RESOLVED')),
    sources_json TEXT NOT NULL, period_from TEXT, period_to TEXT,
    min_amount REAL NOT NULL DEFAULT 0, status TEXT NOT NULL,
    finding_count INTEGER, strict_count INTEGER, resolved_count INTEGER,
    revenue_at_risk REAL, royalty_received REAL, name_present_count INTEGER,
    stats_json TEXT, invariants_json TEXT, created_at TEXT NOT NULL, created_by TEXT);

CREATE TABLE IF NOT EXISTS coverage_row (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES coverage_run(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, song_name TEXT NOT NULL, name_key TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK (evidence IN ('IDENTIFIERS ABSENT', 'NAME PRESENT, IDENTIFIERS DIFFER')),
    present_in TEXT NOT NULL CHECK (present_in IN ('statement', 'platform', 'both')),
    royalty REAL NOT NULL DEFAULT 0, platform_rev REAL NOT NULL DEFAULT 0,
    streams REAL NOT NULL DEFAULT 0, detail_json TEXT NOT NULL,
    UNIQUE (run_id, ordinal));

CREATE TABLE IF NOT EXISTS coverage_row_isrc (
    row_id INTEGER NOT NULL REFERENCES coverage_row(id) ON DELETE CASCADE,
    isrc TEXT NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY (row_id, isrc));

CREATE TABLE IF NOT EXISTS coverage_row_work (
    row_id INTEGER NOT NULL REFERENCES coverage_row(id) ON DELETE CASCADE,
    work_no TEXT NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY (row_id, work_no));

CREATE TABLE IF NOT EXISTS coverage_exclusion (          -- why a record is NOT a finding
    run_id INTEGER NOT NULL REFERENCES coverage_run(id) ON DELETE CASCADE,
    src_kind TEXT NOT NULL CHECK (src_kind IN ('statement_work', 'platform_isrc')),
    src_ref TEXT NOT NULL, src_name TEXT,
    rung TEXT NOT NULL CHECK (rung IN ('E1', 'E2', 'E3', 'E4')),
    matched_entry INTEGER REFERENCES user_sheet_entry(id), via TEXT,
    amount REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, src_kind, src_ref));

-- ------------------------------------------------------------------ §13 mismatch report
CREATE TABLE IF NOT EXISTS mismatch_run (
    id INTEGER PRIMARY KEY,
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    sheet_id INTEGER NOT NULL REFERENCES user_sheet(id) ON DELETE CASCADE,
    sources_json TEXT NOT NULL, period_from TEXT, period_to TEXT, status TEXT NOT NULL,
    row_count INTEGER, counts_json TEXT, totals_json TEXT, invariants_json TEXT,
    created_at TEXT NOT NULL, created_by TEXT);

CREATE TABLE IF NOT EXISTS mismatch (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES mismatch_run(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('Different ISRC', 'Different Internal Number', 'Different Song Name')),
    main_src TEXT NOT NULL, main_ref INTEGER NOT NULL, main_name TEXT, main_no TEXT,
    royalty REAL NOT NULL DEFAULT 0, gross REAL NOT NULL DEFAULT 0,
    UNIQUE (run_id, main_src, main_ref, kind));

CREATE TABLE IF NOT EXISTS mismatch_main_isrc (
    mismatch_id INTEGER NOT NULL REFERENCES mismatch(id) ON DELETE CASCADE,
    isrc TEXT NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY (mismatch_id, isrc));

CREATE TABLE IF NOT EXISTS mismatch_value (
    mismatch_id INTEGER NOT NULL REFERENCES mismatch(id) ON DELETE CASCADE,
    value_key TEXT NOT NULL, value_text TEXT NOT NULL,
    PRIMARY KEY (mismatch_id, value_key));

CREATE TABLE IF NOT EXISTS mismatch_source (
    mismatch_id INTEGER NOT NULL REFERENCES mismatch(id) ON DELETE CASCADE,
    source TEXT NOT NULL, PRIMARY KEY (mismatch_id, source));

-- ------------------------------------------------------------------ exports + jobs
CREATE TABLE IF NOT EXISTS export_artifact (
    id INTEGER PRIMARY KEY,
    build_id INTEGER NOT NULL REFERENCES build_run(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, ref_id INTEGER, filename TEXT NOT NULL, path TEXT NOT NULL,
    size INTEGER NOT NULL, sha256 TEXT NOT NULL, rows INTEGER, created_at TEXT NOT NULL,
    created_by TEXT);

CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
    batch_id INTEGER, build_id INTEGER, ref_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    progress REAL NOT NULL DEFAULT 0, message TEXT, log TEXT NOT NULL DEFAULT '',
    result_json TEXT, error TEXT, created_at TEXT NOT NULL, started_at TEXT,
    finished_at TEXT, created_by TEXT);
