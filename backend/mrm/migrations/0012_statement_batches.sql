-- 1.5.2: statements are listed by upload batch: the files uploaded together under one tab (Platform reports, Client
-- statements, IPRS statements) form one batch, numbered per client and tab ("Batch 1 · Spotify · Oct 2025 - Mar 2026").
CREATE TABLE statement_batches (
  id                BIGSERIAL PRIMARY KEY,
  client_id         BIGINT NOT NULL REFERENCES client,
  statement_source  TEXT NOT NULL CHECK (statement_source IN ('PLATFORM', 'CLIENT', 'IPRS')),
  batch_no          INT NOT NULL,
  batch_key         TEXT NOT NULL,                  -- chosen by the screen for one upload (several files)
  created_by        BIGINT REFERENCES app_user,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, statement_source, batch_no),
  UNIQUE (client_id, batch_key)
);
ALTER TABLE statements ADD COLUMN batch_id BIGINT REFERENCES statement_batches;
CREATE INDEX statements_batch ON statements (batch_id);

ALTER TABLE statement_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY client_scope ON statement_batches USING (client_id = ANY (rd_scope()))
  WITH CHECK (client_id = ANY (rd_scope()));

-- statements uploaded before: one batch per tab and person for uploads less than 10 minutes apart
CREATE TEMP TABLE _sb ON COMMIT DROP AS
WITH o AS (
  SELECT id, client_id, statement_source, uploaded_by, uploaded_at,
         CASE WHEN lag(uploaded_at) OVER w IS NULL OR uploaded_at - lag(uploaded_at) OVER w > interval '10 minutes'
              THEN 1 ELSE 0 END AS brk
    FROM statements WINDOW w AS (PARTITION BY client_id, statement_source, uploaded_by ORDER BY uploaded_at, id)),
g AS (
  SELECT *, sum(brk) OVER (PARTITION BY client_id, statement_source, uploaded_by ORDER BY uploaded_at, id) AS grp FROM o)
SELECT id, client_id, statement_source, uploaded_by, grp,
       min(uploaded_at) OVER (PARTITION BY client_id, statement_source, uploaded_by, grp) AS started FROM g;

INSERT INTO statement_batches (client_id, statement_source, batch_no, batch_key, created_by, created_at)
SELECT client_id, statement_source,
       row_number() OVER (PARTITION BY client_id, statement_source ORDER BY started, uploaded_by),
       'before-1.5.2:' || statement_source || ':' || coalesce(uploaded_by::TEXT, '-') || ':' || grp, uploaded_by, started
  FROM (SELECT DISTINCT client_id, statement_source, uploaded_by, grp, started FROM _sb) x;

UPDATE statements s SET batch_id = b.id
  FROM _sb JOIN statement_batches b ON b.client_id = _sb.client_id
   AND b.batch_key = 'before-1.5.2:' || _sb.statement_source || ':' || coalesce(_sb.uploaded_by::TEXT, '-') || ':' || _sb.grp
 WHERE s.id = _sb.id;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mrm_app') THEN
    EXECUTE 'GRANT SELECT, INSERT ON statement_batches TO mrm_app';
    EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE statement_batches_id_seq TO mrm_app';
  END IF;
END $$;
