-- 1.5.0: three kinds of statement, each with its own tab under Statements (statement_source):
--   PLATFORM = the platform's reports (for example MRM's Spotify report): revenue and usage per ISRC and month. Revenue
--              and usage may come in one file or in two; they are combined by ISRC (and song name) month by month.
--   CLIENT   = the client's statements per platform (per work, in the IPRS layout): what the client's statements show
--   IPRS     = the statements received from IPRS: what IPRS paid
-- A reconciliation compares, per work and period: the platform revenue (and 4 % of it, the indicative reference), the
-- client's statement and what IPRS paid, and flags works that IPRS underpaid.
ALTER TABLE statements DROP CONSTRAINT statements_statement_source_check;
ALTER TABLE statements ADD CONSTRAINT statements_statement_source_check
  CHECK (statement_source IN ('PLATFORM', 'CLIENT', 'IPRS'));
ALTER TABLE statements DROP CONSTRAINT statements_record_type_check;
ALTER TABLE statements ADD CONSTRAINT statements_record_type_check
  CHECK (record_type IN ('WORK_ROYALTY', 'RECORDING_REVENUE', 'RECORDING_USAGE'));
ALTER TABLE statements ADD COLUMN total_usage NUMERIC;          -- plays / streams in the report (NULL = none)

-- per-ISRC revenue reports belong to the platform side now (one copy per file; any other copy is left out)
UPDATE statements s SET statement_source = 'PLATFORM', updated_at = now()
 WHERE s.record_type = 'RECORDING_REVENUE'
   AND s.id = (SELECT min(t.id) FROM statements t WHERE t.file_id = s.file_id AND t.record_type = 'RECORDING_REVENUE')
   AND NOT EXISTS (SELECT 1 FROM statements t WHERE t.file_id = s.file_id AND t.statement_source = 'PLATFORM');
UPDATE statements SET import_status = 'EXCLUDED', updated_at = now(),
       status_reason = 'A per-ISRC report is a platform report since 1.5.0; its copy under Platform reports counts.'
 WHERE record_type = 'RECORDING_REVENUE' AND statement_source <> 'PLATFORM';

-- usage lines (plays) of the platform reports, linked to works through the ISRC like the revenue
CREATE OR REPLACE VIEW platform_usage_records WITH (security_invoker = true) AS
SELECT st.id AS statement_id, pl.file_id, pl.line_no, pl.row_no AS source_row_number, st.client_id, st.platform_id,
       ir.work_id, nullif(pl.isrc, '') AS isrc, pl.title AS reported_title, pl.album, pl.upc,
       pl.month AS usage_period_start, (pl.month + interval '1 month' - interval '1 day')::date AS usage_period_end,
       pl.plays, st.record_type,
       CASE WHEN coalesce(pl.isrc, '') = '' THEN 'NO_ISRC'
            ELSE coalesce(ir.mapping_status, 'UNKNOWN') END AS mapping_status,
       st.import_status, st.statement_source
  FROM rd_platform_line pl
  JOIN statements st ON st.file_id = pl.file_id AND st.record_type IN ('RECORDING_USAGE', 'RECORDING_REVENUE')
  LEFT JOIN isrc_resolution ir ON ir.client_id = st.client_id AND ir.isrc = pl.isrc
 WHERE pl.plays IS NOT NULL;

-- reconciliation: the platform's usage and the client's statement beside the revenue and what IPRS paid
ALTER TABLE reconciliation_items
  ADD COLUMN usage_plays NUMERIC,                   -- plays in the period (NULL = no usage report for those months)
  ADD COLUMN usage_lines INT NOT NULL DEFAULT 0,
  ADD COLUMN client_statement_amount NUMERIC,       -- what the client's statements show (NULL = no line)
  ADD COLUMN client_statement_lines INT NOT NULL DEFAULT 0,
  ADD COLUMN client_iprs_difference NUMERIC;        -- client statement - IPRS paid
ALTER TABLE reconciliation_sources DROP CONSTRAINT reconciliation_sources_source_type_check;
ALTER TABLE reconciliation_sources ADD CONSTRAINT reconciliation_sources_source_type_check
  CHECK (source_type IN ('CLIENT_REVENUE', 'PLATFORM_REVENUE', 'PLATFORM_USAGE', 'CLIENT_STATEMENT', 'IPRS_ROYALTY'));
ALTER TABLE reconciliation_exceptions DROP CONSTRAINT reconciliation_exceptions_exception_type_check;
ALTER TABLE reconciliation_exceptions ADD CONSTRAINT reconciliation_exceptions_exception_type_check
  CHECK (exception_type IN (
    'MISSING_IPRS_ENTRY', 'UNKNOWN_ISRC', 'CONFLICTING_ISRC_MAPPING', 'WORK_NOT_FOUND', 'AMBIGUOUS_WORK_MATCH',
    'MISSING_USAGE_PERIOD', 'MISSING_CURRENCY', 'REVENUE_BASIS_UNCLEAR', 'CLIENT_INTEREST_UNCLEAR',
    'DUPLICATE_STATEMENT', 'AMOUNT_MISMATCH', 'SOURCE_VALIDATION_ERROR', 'LATER_STATEMENT_REVIEW_REQUIRED',
    'MAPPING_NOT_VERIFIED', 'UNDERPAID', 'NO_PLATFORM_REVENUE'));
CREATE INDEX IF NOT EXISTS reconciliation_exceptions_run ON reconciliation_exceptions (reconciliation_run_id,
                                                                                       exception_type);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mrm_app') THEN
    EXECUTE 'GRANT SELECT ON platform_usage_records TO mrm_app';
  END IF;
END $$;
