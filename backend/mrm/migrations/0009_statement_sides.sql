-- 1.3.0: the side of a statement in a reconciliation is who sent it (statement_source), never the file's layout.
--   CLIENT = the client's statements: the source revenue (per ISRC and month, or per work as in a royalty statement)
--   IPRS   = statements received from IPRS: the IPRS royalty the source revenue is compared with
-- The same stored file can be on both sides (the client's copy and IPRS's copy), once per side.
ALTER TABLE statements DROP CONSTRAINT statements_file_id_key;
ALTER TABLE statements ADD CONSTRAINT statements_file_source_key UNIQUE (file_id, statement_source);
CREATE INDEX statements_side ON statements (client_id, statement_source, platform_id, usage_period_start);

-- the normalised records say which side their statement is on (new last column)
CREATE OR REPLACE VIEW client_revenue_records WITH (security_invoker = true) AS
SELECT st.id AS statement_id, pl.file_id, pl.line_no, pl.row_no AS source_row_number, st.client_id, st.platform_id,
       ir.work_id, rec.id AS recording_id, nullif(pl.isrc, '') AS isrc, pl.title AS reported_title, pl.album, pl.upc,
       pl.month AS usage_period_start, (pl.month + interval '1 month' - interval '1 day')::date AS usage_period_end,
       st.territory, st.currency, pl.amount AS reported_amount,
       CASE WHEN st.revenue_basis = 'GROSS' THEN pl.amount END AS gross_amount,
       CASE WHEN st.revenue_basis = 'NET' THEN pl.amount END AS net_amount,
       NULL::NUMERIC AS deductions_amount, st.revenue_basis, st.statement_reference AS source_reference,
       CASE WHEN coalesce(pl.isrc, '') = '' THEN 'NO_ISRC'
            ELSE coalesce(ir.mapping_status, 'UNKNOWN') END AS mapping_status,
       CASE WHEN pl.amount IS NULL THEN 'BLANK_AMOUNT'
            WHEN pl.month IS NULL THEN 'NO_MONTH'
            WHEN coalesce(pl.isrc, '') = '' THEN 'NO_ISRC'
            WHEN pl.isrc !~ '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$' THEN 'INVALID_ISRC'
            ELSE 'OK' END AS validation_status,
       st.import_status, st.statement_source
  FROM rd_platform_line pl
  JOIN statements st ON st.file_id = pl.file_id AND st.record_type = 'RECORDING_REVENUE'
  LEFT JOIN isrc_resolution ir ON ir.client_id = st.client_id AND ir.isrc = pl.isrc
  LEFT JOIN recordings rec ON rec.isrc = pl.isrc;

CREATE OR REPLACE VIEW iprs_royalty_records WITH (security_invoker = true) AS
SELECT st.id AS statement_id, rl.file_id, rl.line_no, rl.row_no AS source_row_number, st.client_id, w.id AS work_id,
       rl.work_no AS internal_work_number, rl.raw_work, rl.title AS reported_title, rl.language,
       rl.party AS party_name, rl.role, rl.own_pct AS ownership_share, rl.coll_pct AS collection_share,
       rl.pool AS pool_reference, rl.source AS source_reference, rl.amount AS royalty_amount, rl.usage,
       st.currency, st.usage_period_start, st.usage_period_end, st.territory, st.platform_id, st.category,
       st.statement_reference,
       CASE WHEN rl.work_no IS NULL THEN 'NO_WORK_NUMBER'
            WHEN w.id IS NULL THEN 'WORK_NOT_FOUND'
            ELSE 'MATCHED' END AS mapping_status,
       CASE WHEN rl.work_no IS NULL THEN 'NO_WORK_NUMBER' ELSE 'OK' END AS validation_status,
       st.import_status, st.statement_source
  FROM rd_royalty_line rl
  JOIN statements st ON st.file_id = rl.file_id AND st.record_type = 'WORK_ROYALTY'
  LEFT JOIN works w ON w.client_id = st.client_id AND w.internal_work_number = rl.work_no AND w.deleted_at IS NULL;

-- a reconciliation compares one usage period (PERIOD) or one Indian financial year (YEAR, with the year before)
ALTER TABLE reconciliation_runs
  ADD COLUMN run_kind TEXT NOT NULL DEFAULT 'PERIOD' CHECK (run_kind IN ('PERIOD', 'YEAR')),
  ADD COLUMN compared_months JSONB,                 -- months both sides cover and that were compared
  ADD COLUMN previous_period_start DATE,            -- YEAR: the same months one year earlier
  ADD COLUMN previous_period_end DATE;
ALTER TABLE reconciliation_items
  ADD COLUMN previous_revenue NUMERIC,              -- YEAR: source revenue in the same months a year earlier
  ADD COLUMN previous_iprs_royalty NUMERIC;         -- YEAR: IPRS royalty in the same months a year earlier
