-- 1.6.0: two kinds of statement, and the client's share of the platform revenue.
--   * Statements has two tabs: Platform reports (the platform's revenue and usage) and IPRS statements. The client's
--     statements were IPRS statements forwarded by the client (the IPRS layout), so they join the IPRS statements.
--   * The platform report shows the client's share of a song's revenue (for example Spotify pays the client 52 %). The
--     song's total revenue (100 %) = revenue / client share, and IPRS is expected to pay the IPRS % (for example 7 %)
--     of that total.

-- ---- a file that is under both tabs: its IPRS copy counts; the client's copy stays as it was, left out
UPDATE statements c SET import_status = 'EXCLUDED', batch_id = NULL, related_statement_id = i.id, updated_at = now(),
       status_reason = 'Since 1.6.0 the client''s statements are IPRS statements; the same file is under IPRS statements '
                       || '(#' || i.id || '), which counts.'
  FROM statements i
 WHERE c.statement_source = 'CLIENT' AND i.file_id = c.file_id AND i.statement_source = 'IPRS';

-- ---- the same distribution already received from IPRS: the client's copy is counted once (same entries) or waits
-- for an answer (different entries: a correction, an additional statement, or leave it out)
UPDATE statements c SET
       import_status = CASE WHEN c.content_fingerprint = o.content_fingerprint THEN 'DUPLICATE' ELSE 'NEEDS_REVIEW' END,
       related_statement_id = o.id, relation = NULL, updated_at = now(),
       status_reason = CASE WHEN c.content_fingerprint = o.content_fingerprint
                            THEN 'Same distribution and the same entries as statement #' || o.id || ' (' ||
                                 o.original_filename || '), so it is counted once.'
                            ELSE 'Statement #' || o.id || ' (' || o.original_filename || ') covers the same distribution '
                                 'with different entries. Is this file a correction of it, or an additional statement?'
                       END
  FROM (SELECT DISTINCT ON (x.id) x.id AS cid, i.id, i.original_filename, i.content_fingerprint
          FROM statements x JOIN statements i ON i.client_id = x.client_id AND i.identity_key = x.identity_key
           AND i.statement_source = 'IPRS' AND i.import_status = 'IMPORTED' AND i.record_type = 'WORK_ROYALTY'
         WHERE x.statement_source = 'CLIENT' AND x.import_status = 'IMPORTED' AND x.record_type = 'WORK_ROYALTY'
           AND x.identity_key IS NOT NULL
         ORDER BY x.id, i.id) o
 WHERE c.id = o.cid;

-- ---- every other client statement is an IPRS statement now
UPDATE statements s SET statement_source = 'IPRS', updated_at = now()
 WHERE s.statement_source = 'CLIENT'
   AND NOT EXISTS (SELECT 1 FROM statements i WHERE i.file_id = s.file_id AND i.statement_source = 'IPRS');

-- ---- upload batches: the client tab's batches join the IPRS tab; batches left empty (Delete all statements kept
-- them) go, and each tab is numbered again in upload order
DELETE FROM statement_batches b WHERE NOT EXISTS (SELECT 1 FROM statements s WHERE s.batch_id = b.id);
UPDATE statement_batches SET statement_source = 'IPRS', batch_no = batch_no + 100000 WHERE statement_source = 'CLIENT';
WITH n AS (SELECT id, row_number() OVER (PARTITION BY client_id, statement_source ORDER BY created_at, id) AS no
             FROM statement_batches)
UPDATE statement_batches b SET batch_no = 1000000 + n.no FROM n WHERE b.id = n.id;
UPDATE statement_batches SET batch_no = batch_no - 1000000 WHERE batch_no > 1000000;

-- ---- the client's share of the platform revenue: in the settings (client-wide and per platform), on each run and item
ALTER TABLE reconciliation_settings ADD COLUMN client_share_pct NUMERIC(9,4)
  CHECK (client_share_pct > 0 AND client_share_pct <= 100);   -- NULL = not set: the revenue reported is the total
ALTER TABLE reconciliation_runs ADD COLUMN client_share_pct NUMERIC(9,4);    -- the share used (NULL: before 1.6.0)
ALTER TABLE reconciliation_items ADD COLUMN client_share_pct NUMERIC(9,4);
