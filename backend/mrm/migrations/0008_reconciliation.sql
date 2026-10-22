-- 1.1.0: MRM royalty reconciliation.
--   platforms        normalised platform names (and the source spellings that mean them)
--   catalogue        works (IPRS internal work numbers), recordings (ISRCs) and the links between them, with history
--   catalogue import preview -> review -> apply, row by row
--   statements       the statement library: one row per uploaded statement file (rd_file keeps the original and its
--                    parsed lines, which never change); client revenue and IPRS royalty records are views over them
--   reconciliation   runs, items, the source lines behind every item, and exceptions
--   enquiries        IPRS enquiries, their items, events, follow-up actions and communications
--   settings         the reference benchmark and the client interest, with their history
-- Money is NUMERIC (exact). A missing amount is NULL, never 0. Every table holding client data carries client_id and
-- is limited by row-level security, like the tables of 0003.

-- ================================================================== platforms (shared vocabulary, no client data)
CREATE TABLE platforms (
  id             BIGSERIAL PRIMARY KEY,
  platform_code  TEXT NOT NULL UNIQUE CHECK (platform_code ~ '^[A-Z][A-Z0-9_]{1,31}$'),
  platform_name  TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
  note           TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE platform_aliases (
  id           BIGSERIAL PRIMARY KEY,
  platform_id  BIGINT NOT NULL REFERENCES platforms,
  alias        TEXT NOT NULL,                      -- as a source writes it
  alias_key    TEXT NOT NULL UNIQUE,               -- lower-case letters and digits only
  created_by   BIGINT REFERENCES app_user,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO platforms (platform_code, platform_name, note) VALUES
  ('SPOTIFY', 'Spotify', NULL),
  ('APPLE_MUSIC', 'Apple Music', NULL),
  ('FACEBOOK', 'Facebook', NULL),
  ('INSTAGRAM', 'Instagram', NULL),
  ('META', 'Meta (one IPRS licence)', 'IPRS reports Facebook, Instagram and WhatsApp use under one Meta licence. It is '
                                       'never merged with, or compared against, Facebook or Instagram revenue alone.'),
  ('YOUTUBE', 'YouTube', NULL),
  ('YOUTUBE_MUSIC', 'YouTube Music', NULL),
  ('JIOSAAVN', 'JioSaavn', NULL),
  ('AMAZON_MUSIC', 'Amazon Music', NULL),
  ('GAANA', 'Gaana', NULL),
  ('WYNK', 'Wynk Music', NULL);

INSERT INTO platform_aliases (platform_id, alias, alias_key)
SELECT p.id, a.alias, a.alias_key FROM (VALUES
  ('SPOTIFY', 'Spotify', 'spotify'), ('SPOTIFY', 'Spotify AB', 'spotifyab'), ('SPOTIFY', 'SPAB', 'spab'),
  ('APPLE_MUSIC', 'Apple Music', 'applemusic'), ('APPLE_MUSIC', 'Apple', 'apple'),
  ('FACEBOOK', 'Facebook', 'facebook'),
  ('INSTAGRAM', 'Instagram', 'instagram'),
  ('META', 'Meta', 'meta'), ('META', 'Facebook / Meta', 'facebookmeta'),
  ('YOUTUBE', 'YouTube', 'youtube'), ('YOUTUBE', 'YouTube Pre-Claims', 'youtubepreclaims'),
  ('YOUTUBE', 'YouTube Post-Claims', 'youtubepostclaims'),
  ('YOUTUBE_MUSIC', 'YouTube Music', 'youtubemusic'),
  ('JIOSAAVN', 'JioSaavn', 'jiosaavn'), ('JIOSAAVN', 'Saavn', 'saavn'),
  ('AMAZON_MUSIC', 'Amazon Music', 'amazonmusic'),
  ('GAANA', 'Gaana', 'gaana'),
  ('WYNK', 'Wynk', 'wynk'), ('WYNK', 'Wynk Music', 'wynkmusic')
) AS a(code, alias, alias_key) JOIN platforms p ON p.platform_code = a.code;

-- ================================================================== catalogue
CREATE TABLE works (
  id                    BIGSERIAL PRIMARY KEY,
  client_id             BIGINT NOT NULL REFERENCES client,
  internal_work_number  TEXT CHECK (internal_work_number ~ '^[0-9]{1,15}$'),   -- NULL = not registered yet
  work_title            TEXT NOT NULL,
  language              TEXT,
  catalogue_status      TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (catalogue_status IN ('ACTIVE', 'TO_REGISTER', 'REVIEW', 'INACTIVE')),
  status_note           TEXT,
  source_import_id      BIGINT,
  created_by            BIGINT REFERENCES app_user,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at            TIMESTAMPTZ
);
-- one work per IPRS work number per client (the same number on several catalogue rows = versions of one work)
CREATE UNIQUE INDEX works_number ON works (client_id, internal_work_number) WHERE internal_work_number IS NOT NULL;
CREATE INDEX works_title ON works (client_id, lower(work_title));

-- an ISRC is one recording identifier, stored once in its normalised form
CREATE TABLE recordings (
  id          BIGSERIAL PRIMARY KEY,
  isrc        TEXT NOT NULL UNIQUE CHECK (isrc ~ '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$'),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE work_recordings (
  id                 BIGSERIAL PRIMARY KEY,
  client_id          BIGINT NOT NULL REFERENCES client,
  work_id            BIGINT NOT NULL REFERENCES works,
  recording_id       BIGINT NOT NULL REFERENCES recordings,
  recording_title    TEXT,                  -- the track name given with this ISRC (versions keep their own names)
  mapping_status     TEXT NOT NULL CHECK (mapping_status IN ('PENDING', 'VERIFIED', 'REJECTED', 'CONFLICT')),
  mapping_source     TEXT NOT NULL CHECK (mapping_source IN ('CLIENT_CATALOGUE', 'MANUAL', 'CORRECTION')),
  source_import_id   BIGINT,
  source_row_number  INT,
  note               TEXT,
  verified_by        BIGINT REFERENCES app_user,
  verified_at        TIMESTAMPTZ,
  valid_from         TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to           TIMESTAMPTZ,           -- NULL = current. A corrected link is closed, never deleted.
  created_by         BIGINT REFERENCES app_user,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (mapping_status <> 'VERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)),
  CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX work_recordings_current ON work_recordings (work_id, recording_id) WHERE valid_to IS NULL;
CREATE INDEX work_recordings_recording ON work_recordings (client_id, recording_id) WHERE valid_to IS NULL;

CREATE TABLE mapping_events (
  id           BIGSERIAL PRIMARY KEY,
  client_id    BIGINT NOT NULL REFERENCES client,
  mapping_id   BIGINT NOT NULL REFERENCES work_recordings,
  event        TEXT NOT NULL,              -- CREATED | VERIFIED | REJECTED | CONFLICT | REOPENED | CLOSED | MOVED
  from_status  TEXT,
  to_status    TEXT,
  note         TEXT,
  actor_id     BIGINT REFERENCES app_user,
  at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX mapping_events_mapping ON mapping_events (mapping_id);

CREATE TABLE catalogue_imports (
  id                       BIGSERIAL PRIMARY KEY,
  client_id                BIGINT NOT NULL REFERENCES client,
  file_id                  BIGINT NOT NULL REFERENCES rd_file,          -- the stored original (write-once)
  original_filename        TEXT NOT NULL,
  file_hash                TEXT NOT NULL,
  status                   TEXT NOT NULL CHECK (status IN ('PREVIEW', 'APPLIED', 'DISCARDED', 'FAILED')),
  source_sheet             TEXT,
  header_row               INT,
  total_rows               INT NOT NULL DEFAULT 0,
  new_works_count          INT NOT NULL DEFAULT 0,
  new_recordings_count     INT NOT NULL DEFAULT 0,
  new_mappings_count       INT NOT NULL DEFAULT 0,
  existing_mappings_count  INT NOT NULL DEFAULT 0,
  conflict_count           INT NOT NULL DEFAULT 0,
  duplicate_rows_count     INT NOT NULL DEFAULT 0,
  invalid_rows_count       INT NOT NULL DEFAULT 0,
  warning_rows_count       INT NOT NULL DEFAULT 0,
  counts                   JSONB NOT NULL DEFAULT '{}',
  catalogue_fingerprint    TEXT,            -- the catalogue the preview was compared with; apply refuses a stale one
  verify_mappings          BOOLEAN,
  uploaded_by              BIGINT REFERENCES app_user,
  uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by              BIGINT REFERENCES app_user,
  reviewed_at              TIMESTAMPTZ,
  applied_at               TIMESTAMPTZ,
  error_summary            TEXT
);
ALTER TABLE works ADD CONSTRAINT works_source_import FOREIGN KEY (source_import_id) REFERENCES catalogue_imports;
ALTER TABLE work_recordings ADD CONSTRAINT work_recordings_source_import
  FOREIGN KEY (source_import_id) REFERENCES catalogue_imports;

CREATE TABLE catalogue_import_rows (
  id                      BIGSERIAL PRIMARY KEY,
  catalogue_import_id     BIGINT NOT NULL REFERENCES catalogue_imports,
  client_id               BIGINT NOT NULL REFERENCES client,
  source_sheet            TEXT,
  source_row_number       INT NOT NULL,
  raw_row_data            JSONB NOT NULL,            -- the title, work number and ISRC cells as written
  normalized_work_number  TEXT,
  normalized_title        TEXT,
  normalized_isrcs        TEXT[] NOT NULL DEFAULT '{}',
  invalid_tokens          TEXT[] NOT NULL DEFAULT '{}',
  proposed_action         TEXT NOT NULL,
  validation_status       TEXT NOT NULL CHECK (validation_status IN ('OK', 'WARNING', 'CONFLICT', 'DUPLICATE', 'INVALID')),
  validation_message      TEXT,
  details                 JSONB NOT NULL DEFAULT '{}',   -- per ISRC: NEW / EXISTING / CONFLICT (+ the other works)
  linked_work_id          BIGINT REFERENCES works,
  applied                 BOOLEAN NOT NULL DEFAULT FALSE,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX catalogue_import_rows_import ON catalogue_import_rows (catalogue_import_id, source_row_number);

-- ================================================================== statement library
CREATE TABLE statements (
  id                        BIGSERIAL PRIMARY KEY,
  client_id                 BIGINT NOT NULL REFERENCES client,
  file_id                   BIGINT NOT NULL UNIQUE REFERENCES rd_file,
  statement_source          TEXT NOT NULL CHECK (statement_source IN ('CLIENT', 'IPRS')),   -- who sent it
  record_type               TEXT NOT NULL CHECK (record_type IN ('WORK_ROYALTY', 'RECORDING_REVENUE')),  -- what it holds
  category                  TEXT,               -- IPRS distribution category / section, e.g. 'Spotify'
  platform_id               BIGINT REFERENCES platforms,
  reported_platform         TEXT,               -- as the source names it
  distributor               TEXT,
  holder_member             TEXT,
  original_filename         TEXT NOT NULL,
  file_hash                 TEXT NOT NULL,
  statement_reference       TEXT,               -- distribution number, or the file's own label
  usage_period_start        DATE,
  usage_period_end          DATE,
  statement_date            DATE,
  statement_date_estimated  BOOLEAN NOT NULL DEFAULT TRUE,
  payment_date              DATE,
  currency                  TEXT,
  currency_source           TEXT,
  revenue_basis             TEXT CHECK (revenue_basis IN ('GROSS', 'NET')),
  territory                 TEXT,
  identity_key              TEXT,
  content_fingerprint       TEXT,
  record_count              INT,
  total_amount              NUMERIC,
  import_status             TEXT NOT NULL CHECK (import_status IN ('IMPORTED', 'NEEDS_REVIEW', 'REJECTED', 'DUPLICATE',
                                                                   'SUPERSEDED', 'EXCLUDED')),
  status_reason             TEXT,
  relation                  TEXT CHECK (relation IN ('CORRECTION', 'SUPPLEMENTARY', 'LEAVE_OUT')),
  related_statement_id      BIGINT REFERENCES statements,   -- duplicate of / corrects / supplements
  superseded_by             BIGINT REFERENCES statements,
  uploaded_by               BIGINT REFERENCES app_user,
  uploaded_at               TIMESTAMPTZ NOT NULL,
  processed_at              TIMESTAMPTZ,
  error_summary             TEXT,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (usage_period_end IS NULL OR usage_period_start IS NULL OR usage_period_end >= usage_period_start)
);
CREATE INDEX statements_lookup ON statements (client_id, record_type, platform_id, usage_period_start);
CREATE INDEX statements_identity ON statements (client_id, identity_key);

-- ================================================================== reconciliation settings (with history)
CREATE TABLE reconciliation_settings (
  id                    BIGSERIAL PRIMARY KEY,
  client_id             BIGINT NOT NULL REFERENCES client,
  platform_id           BIGINT REFERENCES platforms,          -- NULL = every platform of the client
  benchmark_percentage  NUMERIC(9,4) NOT NULL CHECK (benchmark_percentage > 0 AND benchmark_percentage <= 100),
  client_interest_pct   NUMERIC(9,4) CHECK (client_interest_pct > 0 AND client_interest_pct <= 100),  -- NULL = unknown
  revenue_basis         TEXT NOT NULL DEFAULT 'GROSS' CHECK (revenue_basis IN ('GROSS', 'NET')),
  note                  TEXT,
  effective_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
  replaced_at           TIMESTAMPTZ,                          -- NULL = in force
  replaced_by           BIGINT REFERENCES app_user,
  created_by            BIGINT REFERENCES app_user,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX reconciliation_settings_current ON reconciliation_settings (client_id, coalesce(platform_id, 0))
  WHERE replaced_at IS NULL;

-- ================================================================== reconciliation
CREATE TABLE reconciliation_runs (
  id                      BIGSERIAL PRIMARY KEY,
  client_id               BIGINT NOT NULL REFERENCES client,
  run_reference           TEXT NOT NULL UNIQUE,
  platform_id             BIGINT NOT NULL REFERENCES platforms,
  usage_period_start      DATE NOT NULL,
  usage_period_end        DATE NOT NULL,
  benchmark_percentage    NUMERIC(9,4) NOT NULL,
  client_interest_pct     NUMERIC(9,4),
  revenue_basis           TEXT NOT NULL,
  settings_id             BIGINT REFERENCES reconciliation_settings,
  filters_json            JSONB NOT NULL DEFAULT '{}',
  source_snapshot         JSONB NOT NULL DEFAULT '{}',        -- statements used, their file hashes and totals
  source_snapshot_sha256  TEXT,
  summary                 JSONB NOT NULL DEFAULT '{}',
  notes                   JSONB NOT NULL DEFAULT '[]',        -- run-level comparability notes
  status                  TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
  error                   TEXT,
  started_by              BIGINT NOT NULL REFERENCES app_user,
  started_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at            TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (usage_period_end >= usage_period_start)
);

CREATE TABLE reconciliation_items (
  id                          BIGSERIAL PRIMARY KEY,
  reconciliation_run_id       BIGINT NOT NULL REFERENCES reconciliation_runs,
  client_id                   BIGINT NOT NULL REFERENCES client,
  item_no                     INT NOT NULL,
  item_kind                   TEXT NOT NULL CHECK (item_kind IN ('WORK', 'UNMATCHED_RECORDING', 'UNMATCHED_WORK')),
  work_id                     BIGINT REFERENCES works,
  internal_work_number        TEXT,
  work_title                  TEXT,
  isrcs                       TEXT[] NOT NULL DEFAULT '{}',
  platform_id                 BIGINT NOT NULL REFERENCES platforms,
  usage_period_start          DATE NOT NULL,
  usage_period_end            DATE NOT NULL,
  territory                   TEXT,
  currency                    TEXT,
  sound_recording_revenue     NUMERIC,          -- NULL = no revenue record in the uploaded statements (never 0)
  revenue_lines               INT NOT NULL DEFAULT 0,
  eligible_revenue_basis      NUMERIC,
  client_interest_share       NUMERIC(9,4),
  iprs_client_share           NUMERIC(9,4),     -- the client's collection share printed on the IPRS statement
  benchmark_percentage        NUMERIC(9,4),
  reference_benchmark_amount  NUMERIC,
  iprs_royalty_amount         NUMERIC,          -- NULL = no corresponding IPRS entry (never 0)
  iprs_lines                  INT NOT NULL DEFAULT 0,
  observed_percentage         NUMERIC,
  indicative_variance         NUMERIC,
  mapping_status              TEXT NOT NULL,
  data_validation_status      TEXT NOT NULL,
  calculation_status          TEXT NOT NULL CHECK (calculation_status IN ('CALCULATED', 'NOT_CALCULATED',
                                                                           'NOT_COMPARABLE')),
  exception_status            TEXT NOT NULL DEFAULT 'NONE' CHECK (exception_status IN ('NONE', 'OPEN', 'RESOLVED')),
  later_statement_status      TEXT NOT NULL DEFAULT 'NONE' CHECK (later_statement_status IN ('NONE', 'REVIEW_REQUIRED',
                                                                                             'REVIEWED')),
  review_status               TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN ('UNREVIEWED', 'REVIEWED',
                                                                                           'NEEDS_INFO')),
  recommended_action          TEXT,
  reviewed_by                 BIGINT REFERENCES app_user,
  reviewed_at                 TIMESTAMPTZ,
  review_note                 TEXT,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (reconciliation_run_id, item_no)
);
CREATE INDEX reconciliation_items_work ON reconciliation_items (client_id, work_id, platform_id);

CREATE TABLE reconciliation_sources (
  id                      BIGSERIAL PRIMARY KEY,
  reconciliation_item_id  BIGINT NOT NULL REFERENCES reconciliation_items,
  client_id               BIGINT NOT NULL REFERENCES client,
  source_type             TEXT NOT NULL CHECK (source_type IN ('CLIENT_REVENUE', 'IPRS_ROYALTY')),
  statement_id            BIGINT NOT NULL REFERENCES statements,
  file_id                 BIGINT NOT NULL REFERENCES rd_file,
  line_no                 INT NOT NULL,
  source_row_number       INT NOT NULL,
  isrc                    TEXT,
  internal_work_number    TEXT,
  usage_month             DATE,
  contribution_amount     NUMERIC,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX reconciliation_sources_item ON reconciliation_sources (reconciliation_item_id);

CREATE TABLE reconciliation_exceptions (
  id                      BIGSERIAL PRIMARY KEY,
  reconciliation_item_id  BIGINT NOT NULL REFERENCES reconciliation_items,
  reconciliation_run_id   BIGINT NOT NULL REFERENCES reconciliation_runs,
  client_id               BIGINT NOT NULL REFERENCES client,
  exception_type          TEXT NOT NULL CHECK (exception_type IN (
                            'MISSING_IPRS_ENTRY', 'UNKNOWN_ISRC', 'CONFLICTING_ISRC_MAPPING', 'WORK_NOT_FOUND',
                            'AMBIGUOUS_WORK_MATCH', 'MISSING_USAGE_PERIOD', 'MISSING_CURRENCY', 'REVENUE_BASIS_UNCLEAR',
                            'CLIENT_INTEREST_UNCLEAR', 'DUPLICATE_STATEMENT', 'AMOUNT_MISMATCH',
                            'SOURCE_VALIDATION_ERROR', 'LATER_STATEMENT_REVIEW_REQUIRED', 'MAPPING_NOT_VERIFIED')),
  severity                TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'HIGH')),
  description             TEXT NOT NULL,
  status                  TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_REVIEW', 'RESOLVED', 'DISMISSED')),
  assigned_to             BIGINT REFERENCES app_user,
  reviewed_by             BIGINT REFERENCES app_user,
  reviewed_at             TIMESTAMPTZ,
  resolution_note         TEXT,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX reconciliation_exceptions_run ON reconciliation_exceptions (reconciliation_run_id, exception_type);
CREATE INDEX reconciliation_exceptions_item ON reconciliation_exceptions (reconciliation_item_id);

-- ================================================================== enquiries and follow-up
CREATE TABLE enquiries (
  id                    BIGSERIAL PRIMARY KEY,
  client_id             BIGINT NOT NULL REFERENCES client,
  enquiry_reference     TEXT NOT NULL UNIQUE,
  subject               TEXT NOT NULL,
  draft_body            TEXT NOT NULL,
  status                TEXT NOT NULL CHECK (status IN ('NEEDS_REVIEW', 'MAPPING_PENDING', 'DATA_CLARIFICATION_REQUIRED',
                                                        'DRAFT_PREPARED', 'PENDING_APPROVAL', 'APPROVED_TO_SEND',
                                                        'AWAITING_RESPONSE', 'UNDER_INVESTIGATION',
                                                        'PARTIALLY_RESOLVED', 'RESOLVED', 'CLOSED')),
  platform_id           BIGINT REFERENCES platforms,
  usage_period_start    DATE,
  usage_period_end      DATE,
  reconciliation_run_id BIGINT REFERENCES reconciliation_runs,
  assigned_to           BIGINT REFERENCES app_user,
  created_by            BIGINT NOT NULL REFERENCES app_user,
  reviewed_by           BIGINT REFERENCES app_user,
  reviewed_at           TIMESTAMPTZ,
  returned_reason       TEXT,
  approved_by           BIGINT REFERENCES app_user,
  approved_at           TIMESTAMPTZ,
  sent_by               BIGINT REFERENCES app_user,
  sent_at               TIMESTAMPTZ,
  send_channel          TEXT,
  recipient_reference   TEXT,
  last_response_at      TIMESTAMPTZ,
  next_follow_up_at     DATE,
  new_statement_review  BOOLEAN NOT NULL DEFAULT FALSE,
  resolution_status     TEXT CHECK (resolution_status IN ('UNRESOLVED', 'PARTIALLY_RESOLVED', 'RESOLVED', 'WITHDRAWN')),
  resolution_summary    TEXT,
  closed_by             BIGINT REFERENCES app_user,
  closed_at             TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- an enquiry is never sent without an approval, and a draft is never treated as sent
  CHECK (sent_at IS NULL OR (approved_by IS NOT NULL AND sent_by IS NOT NULL)),
  CHECK (status NOT IN ('APPROVED_TO_SEND') OR approved_by IS NOT NULL),
  CHECK (status NOT IN ('AWAITING_RESPONSE', 'UNDER_INVESTIGATION', 'PARTIALLY_RESOLVED', 'RESOLVED')
         OR sent_at IS NOT NULL),
  CHECK (status <> 'CLOSED' OR closed_by IS NOT NULL)
);
CREATE INDEX enquiries_status ON enquiries (client_id, status);

CREATE TABLE enquiry_items (
  enquiry_id              BIGINT NOT NULL REFERENCES enquiries,
  reconciliation_item_id  BIGINT NOT NULL REFERENCES reconciliation_items,
  client_id               BIGINT NOT NULL REFERENCES client,
  work_id                 BIGINT REFERENCES works,
  platform_id             BIGINT REFERENCES platforms,
  usage_period_start      DATE,
  usage_period_end        DATE,
  section                 TEXT NOT NULL CHECK (section IN ('CLARIFICATION', 'VARIANCE')),
  item_status             TEXT NOT NULL DEFAULT 'OPEN' CHECK (item_status IN ('OPEN', 'PARTIALLY_RESOLVED', 'RESOLVED',
                                                                              'NO_CHANGE', 'REMOVED')),
  outcome_note            TEXT,
  added_by                BIGINT REFERENCES app_user,
  added_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (enquiry_id, reconciliation_item_id)
);
CREATE INDEX enquiry_items_subject ON enquiry_items (client_id, work_id, platform_id, usage_period_start);

CREATE TABLE enquiry_events (
  id                 BIGSERIAL PRIMARY KEY,
  enquiry_id         BIGINT NOT NULL REFERENCES enquiries,
  client_id          BIGINT NOT NULL REFERENCES client,
  event_type         TEXT NOT NULL,
  event_description  TEXT NOT NULL,
  from_status        TEXT,
  to_status          TEXT,
  actor_user_id      BIGINT REFERENCES app_user,
  event_timestamp    TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata_json      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX enquiry_events_enquiry ON enquiry_events (enquiry_id, id);

CREATE TABLE enquiry_actions (
  id                  BIGSERIAL PRIMARY KEY,
  enquiry_id          BIGINT NOT NULL REFERENCES enquiries,
  client_id           BIGINT NOT NULL REFERENCES client,
  action_title        TEXT NOT NULL,
  action_description  TEXT,
  assigned_to         BIGINT REFERENCES app_user,
  due_at              DATE,
  status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'DONE', 'CANCELLED')),
  completed_by        BIGINT REFERENCES app_user,
  completed_at        TIMESTAMPTZ,
  completion_note     TEXT,
  created_by          BIGINT REFERENCES app_user,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX enquiry_actions_due ON enquiry_actions (client_id, status, due_at);

CREATE TABLE enquiry_communications (
  id                    BIGSERIAL PRIMARY KEY,
  enquiry_id            BIGINT NOT NULL REFERENCES enquiries,
  client_id             BIGINT NOT NULL REFERENCES client,
  communication_type    TEXT NOT NULL CHECK (communication_type IN ('EMAIL', 'LETTER', 'PORTAL', 'PHONE', 'MEETING',
                                                                    'OTHER')),
  direction             TEXT NOT NULL CHECK (direction IN ('OUTBOUND', 'INBOUND')),
  subject               TEXT,
  summary               TEXT,
  message_reference     TEXT,
  sender_reference      TEXT,
  recipient_reference   TEXT,
  communication_date    DATE NOT NULL,
  attachment_reference  TEXT,
  related_statement_id  BIGINT REFERENCES statements,
  recorded_by           BIGINT NOT NULL REFERENCES app_user,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX enquiry_communications_enquiry ON enquiry_communications (enquiry_id, id);

-- ================================================================== views: normalised records over the source lines
-- The source lines (rd_platform_line, rd_royalty_line) are stored once and never change. Mapping and matching are
-- worked out when read, so a corrected catalogue link applies everywhere at once and no total can drift from its rows.
CREATE VIEW current_work_recordings WITH (security_invoker = true) AS
SELECT wr.*, r.isrc, w.internal_work_number, w.work_title
  FROM work_recordings wr
  JOIN recordings r ON r.id = wr.recording_id
  JOIN works w ON w.id = wr.work_id
 WHERE wr.valid_to IS NULL AND wr.mapping_status <> 'REJECTED' AND w.deleted_at IS NULL;

-- one row per (client, ISRC): which work it belongs to, and how sure we are
CREATE VIEW isrc_resolution WITH (security_invoker = true) AS
SELECT client_id, isrc,
       CASE WHEN count(DISTINCT work_id) > 1 OR bool_or(mapping_status = 'CONFLICT') THEN 'CONFLICT'
            WHEN bool_and(mapping_status = 'VERIFIED') THEN 'VERIFIED'
            ELSE 'PENDING' END AS mapping_status,
       CASE WHEN count(DISTINCT work_id) = 1 AND NOT bool_or(mapping_status = 'CONFLICT') THEN min(work_id) END
         AS work_id,
       array_agg(DISTINCT work_id) AS work_ids
  FROM current_work_recordings
 GROUP BY client_id, isrc;

CREATE VIEW client_revenue_records WITH (security_invoker = true) AS
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
       st.import_status
  FROM rd_platform_line pl
  JOIN statements st ON st.file_id = pl.file_id AND st.record_type = 'RECORDING_REVENUE'
  LEFT JOIN isrc_resolution ir ON ir.client_id = st.client_id AND ir.isrc = pl.isrc
  LEFT JOIN recordings rec ON rec.isrc = pl.isrc;

CREATE VIEW iprs_royalty_records WITH (security_invoker = true) AS
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
       st.import_status
  FROM rd_royalty_line rl
  JOIN statements st ON st.file_id = rl.file_id AND st.record_type = 'WORK_ROYALTY'
  LEFT JOIN works w ON w.client_id = st.client_id AND w.internal_work_number = rl.work_no AND w.deleted_at IS NULL;

-- ================================================================== guards: history is kept, never rewritten
CREATE TRIGGER mapping_events_append_only BEFORE UPDATE OR DELETE ON mapping_events FOR EACH ROW
  EXECUTE FUNCTION refuse_change();
CREATE TRIGGER enquiry_events_append_only BEFORE UPDATE OR DELETE ON enquiry_events FOR EACH ROW
  EXECUTE FUNCTION refuse_change();
CREATE TRIGGER enquiry_communications_append_only BEFORE UPDATE OR DELETE ON enquiry_communications FOR EACH ROW
  EXECUTE FUNCTION refuse_change();
CREATE TRIGGER reconciliation_sources_frozen BEFORE UPDATE OR DELETE ON reconciliation_sources FOR EACH ROW
  EXECUTE FUNCTION refuse_change();

-- a link is never deleted; a closed link never changes again
CREATE FUNCTION work_recordings_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'catalogue links are kept as history - close the link instead'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.valid_to IS NOT NULL THEN
    RAISE EXCEPTION 'a closed catalogue link cannot change' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (NEW.client_id, NEW.work_id, NEW.recording_id, NEW.valid_from, NEW.created_by, NEW.created_at)
     IS DISTINCT FROM (OLD.client_id, OLD.work_id, OLD.recording_id, OLD.valid_from, OLD.created_by, OLD.created_at) THEN
    RAISE EXCEPTION 'a catalogue link''s work and recording never change - close it and make a new one'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER work_recordings_guard BEFORE UPDATE OR DELETE ON work_recordings FOR EACH ROW
  EXECUTE FUNCTION work_recordings_guard();

-- a setting in force is replaced by a new row; an old one is only ever marked replaced
CREATE FUNCTION reconciliation_settings_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.replaced_at IS NOT NULL
     OR (to_jsonb(NEW) - 'replaced_at' - 'replaced_by') <> (to_jsonb(OLD) - 'replaced_at' - 'replaced_by') THEN
    RAISE EXCEPTION 'settings are kept as history - save a new value instead' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reconciliation_settings_guard BEFORE UPDATE OR DELETE ON reconciliation_settings FOR EACH ROW
  EXECUTE FUNCTION reconciliation_settings_guard();

-- a reconciliation run is never overwritten: its numbers are fixed once it completes; only the review fields of an
-- item move
CREATE FUNCTION reconciliation_run_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'reconciliation runs are kept' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.status <> 'RUNNING' THEN
    RAISE EXCEPTION 'reconciliation run % is complete and cannot change - run a new one', OLD.run_reference
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reconciliation_run_guard BEFORE UPDATE OR DELETE ON reconciliation_runs FOR EACH ROW
  EXECUTE FUNCTION reconciliation_run_guard();

CREATE FUNCTION reconciliation_item_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'reconciliation results are kept' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (to_jsonb(NEW) - 'review_status' - 'reviewed_by' - 'reviewed_at' - 'review_note' - 'exception_status'
      - 'later_statement_status' - 'updated_at')
     <> (to_jsonb(OLD) - 'review_status' - 'reviewed_by' - 'reviewed_at' - 'review_note' - 'exception_status'
         - 'later_statement_status' - 'updated_at') THEN
    RAISE EXCEPTION 'calculated reconciliation values cannot change - run a new reconciliation'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reconciliation_item_guard BEFORE UPDATE OR DELETE ON reconciliation_items FOR EACH ROW
  EXECUTE FUNCTION reconciliation_item_guard();

-- ================================================================== client isolation (row-level security)
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['works', 'work_recordings', 'mapping_events', 'catalogue_imports', 'catalogue_import_rows',
                           'statements', 'reconciliation_settings', 'reconciliation_runs', 'reconciliation_items',
                           'reconciliation_sources', 'reconciliation_exceptions', 'enquiries', 'enquiry_items',
                           'enquiry_events', 'enquiry_actions', 'enquiry_communications'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY client_scope ON %I USING (client_id = ANY (rd_scope())) '
                   'WITH CHECK (client_id = ANY (rd_scope()))', t);
  END LOOP;
END $$;

-- ================================================================== the application login
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mrm_app') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON platforms, platform_aliases, works, recordings, work_recordings, '
            'catalogue_imports, catalogue_import_rows, statements, reconciliation_settings, reconciliation_runs, '
            'reconciliation_items, reconciliation_exceptions, enquiries, enquiry_items, enquiry_actions TO mrm_app';
    EXECUTE 'GRANT SELECT, INSERT ON mapping_events, reconciliation_sources, enquiry_events, enquiry_communications '
            'TO mrm_app';
    EXECUTE 'GRANT SELECT ON current_work_recordings, isrc_resolution, client_revenue_records, iprs_royalty_records '
            'TO mrm_app';
    EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mrm_app';
  END IF;
END $$;
