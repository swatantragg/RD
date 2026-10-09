-- MRM Royalty Comparison - schema (Docs/MRM_Royalty_Comparison_Flowchart_for_Swatantra.pdf, approval draft v1.0).
-- Money is NUMERIC; a missing amount is NULL, never 0 ("missing data is not zero").
-- Every figure keeps the file and source row it came from ("report figures trace to source rows").

-- ------------------------------------------------------------------ people (page 9 roles)
CREATE TABLE app_user (
  id             BIGSERIAL PRIMARY KEY,
  email          TEXT NOT NULL UNIQUE,
  name           TEXT NOT NULL,
  password_hash  TEXT NOT NULL,
  active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at  TIMESTAMPTZ
);

CREATE TABLE user_role (
  user_id  BIGINT NOT NULL REFERENCES app_user ON DELETE CASCADE,
  role     TEXT NOT NULL CHECK (role IN ('admin', 'importer', 'rights_reviewer', 'accounts', 'approver', 'sender', 'viewer')),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE app_session (
  token_sha256  TEXT PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES app_user ON DELETE CASCADE,
  csrf          TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL,
  revoked_at    TIMESTAMPTZ
);

CREATE TABLE login_attempt (
  id     BIGSERIAL PRIMARY KEY,
  email  TEXT NOT NULL,
  ok     BOOLEAN NOT NULL,
  at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ clients and mandates (page 5 D2, page 13 scope)
CREATE TABLE client (
  id                BIGSERIAL PRIMARY KEY,
  code              TEXT NOT NULL UNIQUE,
  name              TEXT NOT NULL,
  kind              TEXT NOT NULL CHECK (kind IN ('PUBLISHER', 'LABEL', 'PUBLISHER_AND_LABEL')),
  society           TEXT NOT NULL DEFAULT 'IPRS',
  member_id         TEXT,                                    -- publishing beneficiary / member ID
  beneficiary_name  TEXT,
  mandate_verified  BOOLEAN NOT NULL DEFAULT FALSE,          -- verified publishing authority
  mandate_ref       TEXT,
  mandate_from      DATE,
  mandate_to        DATE,
  territories       TEXT[] NOT NULL DEFAULT '{}',
  controlled_share  NUMERIC(9,6),                            -- NULL = not evidenced (never assume 100%)
  collection_route  TEXT NOT NULL DEFAULT 'IPRS' CHECK (collection_route IN ('IPRS', 'PRS', 'DIRECT')),
  contact_email     TEXT,
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE batch (
  id          BIGSERIAL PRIMARY KEY,
  client_id   BIGINT NOT NULL REFERENCES client,
  code        TEXT NOT NULL,
  label       TEXT NOT NULL,
  created_by  BIGINT REFERENCES app_user,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, code)
);

-- ------------------------------------------------------------------ A. classify + B. validate (pages 2-3)
CREATE TABLE source_file (
  id                       BIGSERIAL PRIMARY KEY,
  client_id                BIGINT NOT NULL REFERENCES client,
  batch_id                 BIGINT NOT NULL REFERENCES batch,
  filename                 TEXT NOT NULL,
  sha256                   TEXT NOT NULL,
  bytes                    BIGINT NOT NULL,
  object_key               TEXT NOT NULL,
  format                   TEXT NOT NULL DEFAULT 'UNKNOWN',
  income_type              TEXT CHECK (income_type IN ('PUBLISHING', 'RECORDING', 'USAGE', 'IDENTITY', 'OTHER')),
  classified_by            TEXT,                             -- detected | operator
  status                   TEXT NOT NULL CHECK (status IN ('UPLOADED', 'CLASSIFICATION_HOLD', 'FILE_EXCEPTION',
                             'DATA_EXCEPTION', 'RECONCILIATION_HOLD', 'DUPLICATE_REVIEW', 'VALIDATED', 'SUPERSEDED',
                             'EXCLUDED')),
  gate                     TEXT,                             -- A2, B2 .. B5 - where it stopped
  hold_reason              TEXT,
  meta                     JSONB NOT NULL DEFAULT '{}',      -- sender, payer, platform, territory, currency, basis, ...
  meta_source              JSONB NOT NULL DEFAULT '{}',      -- field -> filename | content | operator
  checks                   JSONB NOT NULL DEFAULT '[]',
  mapping                  JSONB,
  printed_total            NUMERIC(20,8),
  lines_total              NUMERIC(20,8),
  control_total            NUMERIC(20,8),                    -- approved alternative control (no printed total)
  control_ref              TEXT,
  control_by               BIGINT REFERENCES app_user,
  bridge                   JSONB,                            -- evidenced reconciliation bridge items
  rows_total               INT NOT NULL DEFAULT 0,
  rows_invalid             INT NOT NULL DEFAULT 0,
  row_exceptions_accepted  BIGINT REFERENCES app_user,
  decisions                JSONB NOT NULL DEFAULT '{}',      -- overlap / row-duplicate / exception decisions
  supersedes_id            BIGINT REFERENCES source_file,
  supersession_approved_by BIGINT REFERENCES app_user,
  file_date                DATE,
  uploaded_by              BIGINT REFERENCES app_user,
  uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, sha256)
);

CREATE TABLE publishing_line (
  id               BIGSERIAL PRIMARY KEY,
  file_id          BIGINT NOT NULL REFERENCES source_file ON DELETE CASCADE,
  row_no           INT NOT NULL,                              -- sheet row in the original
  sheet            TEXT,
  work_code        TEXT,
  title            TEXT,
  member_id        TEXT,
  party            TEXT,
  role             TEXT,
  own_pct          NUMERIC(12,6),
  coll_pct         NUMERIC(12,6),
  pool             TEXT,
  source           TEXT,
  platform         TEXT,                                      -- underlying platform (from SOURCE), not the sender
  use_type         TEXT,
  right_scope      TEXT,                                      -- PERFORMING | MECHANICAL | UNKNOWN
  amount           NUMERIC(20,8),
  currency         TEXT,
  is_valid         BOOLEAN NOT NULL DEFAULT TRUE,
  invalid_reason   TEXT,
  duplicate_state  TEXT NOT NULL DEFAULT 'NONE' CHECK (duplicate_state IN ('NONE', 'CANDIDATE', 'LEGITIMATE', 'SUPPRESSED'))
);
CREATE INDEX publishing_line_file_ix ON publishing_line (file_id, work_code);

CREATE TABLE recording_line (
  id               BIGSERIAL PRIMARY KEY,
  file_id          BIGINT NOT NULL REFERENCES source_file ON DELETE CASCADE,
  row_no           INT NOT NULL,
  sheet            TEXT,
  isrc             TEXT,
  title            TEXT,
  album            TEXT,
  upc              TEXT,
  content_type     TEXT,
  platform         TEXT,
  territory        TEXT,
  month            DATE,
  amount           NUMERIC(20,8),
  currency         TEXT,
  basis            TEXT,
  share            NUMERIC(9,6),
  is_valid         BOOLEAN NOT NULL DEFAULT TRUE,
  invalid_reason   TEXT,
  duplicate_state  TEXT NOT NULL DEFAULT 'NONE' CHECK (duplicate_state IN ('NONE', 'CANDIDATE', 'LEGITIMATE', 'SUPPRESSED'))
);
CREATE INDEX recording_line_file_ix ON recording_line (file_id, isrc);

CREATE TABLE usage_line (
  id               BIGSERIAL PRIMARY KEY,
  file_id          BIGINT NOT NULL REFERENCES source_file ON DELETE CASCADE,
  row_no           INT NOT NULL,
  sheet            TEXT,
  isrc             TEXT,
  title            TEXT,
  album            TEXT,
  platform         TEXT,
  territory        TEXT,
  month            DATE,
  streams          BIGINT,
  metric           TEXT,
  is_valid         BOOLEAN NOT NULL DEFAULT TRUE,
  invalid_reason   TEXT,
  duplicate_state  TEXT NOT NULL DEFAULT 'NONE' CHECK (duplicate_state IN ('NONE', 'CANDIDATE', 'LEGITIMATE', 'SUPPRESSED'))
);
CREATE INDEX usage_line_file_ix ON usage_line (file_id, isrc);

CREATE TABLE catalogue_line (
  id              BIGSERIAL PRIMARY KEY,
  file_id         BIGINT NOT NULL REFERENCES source_file ON DELETE CASCADE,
  row_no          INT NOT NULL,
  title           TEXT,
  work_codes      TEXT[] NOT NULL DEFAULT '{}',
  isrcs           TEXT[] NOT NULL DEFAULT '{}',
  raw_work        TEXT,
  film            TEXT,
  composer        TEXT,
  lyricist        TEXT,
  performer       TEXT,
  note            TEXT,
  is_valid        BOOLEAN NOT NULL DEFAULT TRUE,
  invalid_reason  TEXT
);

-- ------------------------------------------------------------------ C. identities (page 4)
CREATE TABLE composition (
  id            BIGSERIAL PRIMARY KEY,
  client_id     BIGINT NOT NULL REFERENCES client,
  work_code     TEXT NOT NULL,
  iswc          TEXT,
  title         TEXT NOT NULL,
  film          TEXT,
  composer      TEXT,
  lyricist      TEXT,
  canonical_id  BIGINT REFERENCES composition,               -- set by a "same entity" decision
  source        TEXT,
  UNIQUE (client_id, work_code)
);

CREATE TABLE recording (
  id            BIGSERIAL PRIMARY KEY,
  client_id     BIGINT NOT NULL REFERENCES client,
  isrc          TEXT NOT NULL,
  title         TEXT NOT NULL,
  version       TEXT,
  performer     TEXT,
  canonical_id  BIGINT REFERENCES recording,
  source        TEXT,
  UNIQUE (client_id, isrc)
);

CREATE TABLE work_link (
  id              BIGSERIAL PRIMARY KEY,
  client_id       BIGINT NOT NULL REFERENCES client,
  composition_id  BIGINT NOT NULL REFERENCES composition,
  recording_id    BIGINT NOT NULL REFERENCES recording,
  basis           TEXT NOT NULL CHECK (basis IN ('CATALOGUE', 'REVIEWER')),
  evidence        JSONB NOT NULL DEFAULT '{}',
  allocation      NUMERIC(9,6),                              -- medley / multi-work split; NULL = whole recording
  status          TEXT NOT NULL CHECK (status IN ('APPROVED', 'PROPOSED', 'REJECTED')),
  proposed_by     BIGINT REFERENCES app_user,
  decided_by      BIGINT REFERENCES app_user,
  decided_at      TIMESTAMPTZ,
  reason          TEXT,
  UNIQUE (composition_id, recording_id)
);

CREATE TABLE identity_issue (
  id           BIGSERIAL PRIMARY KEY,
  client_id    BIGINT NOT NULL REFERENCES client,
  kind         TEXT NOT NULL,
  subject_key  TEXT NOT NULL,
  title        TEXT,
  detail       JSONB NOT NULL DEFAULT '{}',
  amount       NUMERIC(20,8),
  status       TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED', 'DEFERRED')),
  resolution   TEXT,
  resolved_by  BIGINT REFERENCES app_user,
  resolved_at  TIMESTAMPTZ,
  UNIQUE (client_id, kind, subject_key)
);

CREATE TABLE duplicate_candidate (
  id          BIGSERIAL PRIMARY KEY,
  client_id   BIGINT NOT NULL REFERENCES client,
  entity      TEXT NOT NULL CHECK (entity IN ('COMPOSITION', 'RECORDING')),
  a_id        BIGINT NOT NULL,
  b_id        BIGINT NOT NULL,
  score       NUMERIC(6,3) NOT NULL,
  basis       TEXT NOT NULL,
  differences JSONB NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SAME', 'SEPARATE', 'DEFERRED')),
  decided_by  BIGINT REFERENCES app_user,
  decided_at  TIMESTAMPTZ,
  reason      TEXT,
  UNIQUE (client_id, entity, a_id, b_id)
);

CREATE TABLE identity_version (
  id           BIGSERIAL PRIMARY KEY,
  client_id    BIGINT NOT NULL REFERENCES client,
  version_no   INT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('APPROVED', 'SUPERSEDED')),
  checks       JSONB NOT NULL DEFAULT '[]',
  counts       JSONB NOT NULL DEFAULT '{}',
  note         TEXT,
  approved_by  BIGINT NOT NULL REFERENCES app_user,
  approved_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, version_no)
);

CREATE TABLE identity_version_link (
  version_id      BIGINT NOT NULL REFERENCES identity_version ON DELETE CASCADE,
  composition_id  BIGINT NOT NULL REFERENCES composition,
  recording_id    BIGINT NOT NULL REFERENCES recording,
  allocation      NUMERIC(9,6),
  PRIMARY KEY (version_id, composition_id, recording_id)
);

-- ------------------------------------------------------------------ E. rules (page 6, 12)
CREATE TABLE rule_version (
  id                BIGSERIAL PRIMARY KEY,
  client_id         BIGINT REFERENCES client,                 -- NULL = MRM-wide rule
  rule_key          TEXT NOT NULL,
  version_no        INT NOT NULL,
  name              TEXT NOT NULL,
  method            TEXT NOT NULL CHECK (method IN ('MRM_BENCHMARK', 'EVIDENCED')),
  rate              NUMERIC(12,8),                            -- k (0.06 for the MRM benchmark)
  denominator       TEXT,                                     -- what revenue the rate applies to
  revenue_basis     TEXT CHECK (revenue_basis IN ('GROSS', 'NET')),
  share_treatment   TEXT CHECK (share_treatment IN ('BENEFICIARY_SPECIFIC', 'WORK_100_TIMES_SHARE')),
  controlled_share  NUMERIC(9,6),                             -- s, only for WORK_100_TIMES_SHARE
  stream_rate       NUMERIC(20,10),                           -- q, approved publishing rate per stream (blank by default)
  stream_rate_basis TEXT,
  platforms         TEXT[] NOT NULL DEFAULT '{}',
  territories       TEXT[] NOT NULL DEFAULT '{}',
  use_types         TEXT[] NOT NULL DEFAULT '{}',
  currency          TEXT NOT NULL DEFAULT 'INR',
  effective_from    DATE,
  effective_to      DATE,
  evidence_ref      TEXT,                                     -- society / contract reference (EVIDENCED)
  formula           TEXT,
  tolerance         NUMERIC(20,8) NOT NULL DEFAULT 0,          -- monetary review tolerance
  owner_id          BIGINT REFERENCES app_user,
  status            TEXT NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
  reason            TEXT NOT NULL,
  supersedes_id     BIGINT REFERENCES rule_version,
  created_by        BIGINT NOT NULL REFERENCES app_user,
  approved_by       BIGINT REFERENCES app_user,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_at       TIMESTAMPTZ,
  UNIQUE NULLS NOT DISTINCT (client_id, rule_key, version_no),
  CHECK (approved_by IS NULL OR approved_by <> created_by)
);

-- ------------------------------------------------------------------ D-G. comparison runs (pages 5-8)
CREATE TABLE comparison_run (
  id                   BIGSERIAL PRIMARY KEY,
  client_id            BIGINT NOT NULL REFERENCES client,
  version_no           INT NOT NULL,
  platform             TEXT NOT NULL,
  territory            TEXT NOT NULL,
  use_type             TEXT NOT NULL,
  right_scope          TEXT NOT NULL,
  period_from          DATE NOT NULL,
  period_to            DATE NOT NULL,
  cutoff               DATE,
  identity_version_id  BIGINT REFERENCES identity_version,
  file_ids             BIGINT[] NOT NULL DEFAULT '{}',
  rule_version_ids     BIGINT[] NOT NULL DEFAULT '{}',
  status               TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETE', 'FAILED')),
  summary              JSONB NOT NULL DEFAULT '{}',
  checks               JSONB NOT NULL DEFAULT '[]',
  error                TEXT,
  created_by           BIGINT NOT NULL REFERENCES app_user,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, version_no)
);

CREATE TABLE comparison_group (
  id               BIGSERIAL PRIMARY KEY,
  run_id           BIGINT NOT NULL REFERENCES comparison_run ON DELETE CASCADE,
  case_code        TEXT NOT NULL,
  group_key        TEXT NOT NULL,
  composition_id   BIGINT REFERENCES composition,
  work_code        TEXT,
  title            TEXT,
  film             TEXT,
  composer         TEXT,
  lyricist         TEXT,
  isrcs            TEXT[] NOT NULL DEFAULT '{}',
  recordings       JSONB NOT NULL DEFAULT '[]',
  mapping_status   TEXT,
  r_amount         NUMERIC(20,8),                            -- R
  n_streams        BIGINT,                                   -- N
  n_definition     TEXT,
  p_amount         NUMERIC(20,8),                            -- P
  p_status         TEXT NOT NULL,                            -- FOUND | EXPLICIT_ZERO | NOT_FOUND | PENDING_CYCLE | MISSING_STATEMENT
  currency         TEXT,
  gates            JSONB NOT NULL DEFAULT '[]',
  rule_version_id  BIGINT REFERENCES rule_version,
  method           TEXT NOT NULL,                            -- EVIDENCED | MRM_BENCHMARK | NO_BENCHMARK | RULE_HOLD | CONFIGURATION_HOLD
  route            TEXT NOT NULL,                            -- MONEY | STREAM | COVERAGE | INSUFFICIENT
  b_amount         NUMERIC(20,8),                            -- B (money route, or stream route when no R)
  b_stream         NUMERIC(20,8),                            -- stream cross-check N x q, shown separately, never added
  variance         NUMERIC(20,8),                            -- V = B - P
  positive_gap     NUMERIC(20,8),
  provisional      BOOLEAN NOT NULL DEFAULT FALSE,
  outcome          TEXT NOT NULL,
  hold_reason      TEXT,
  question         TEXT,
  limitations      TEXT,
  evidence         JSONB NOT NULL DEFAULT '{}',
  UNIQUE (run_id, group_key)
);
CREATE INDEX comparison_group_outcome_ix ON comparison_group (run_id, outcome);

CREATE TABLE run_exception (
  id         BIGSERIAL PRIMARY KEY,
  run_id     BIGINT NOT NULL REFERENCES comparison_run ON DELETE CASCADE,
  kind       TEXT NOT NULL,
  subject    TEXT NOT NULL,
  detail     JSONB NOT NULL DEFAULT '{}',
  amount     NUMERIC(20,8),
  streams    BIGINT,
  currency   TEXT,
  owner      TEXT,
  next_action TEXT
);

-- ------------------------------------------------------------------ H. report packs and cases (page 9)
CREATE TABLE report_pack (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT NOT NULL REFERENCES comparison_run,
  client_id       BIGINT NOT NULL REFERENCES client,
  version_no      INT NOT NULL,
  route           TEXT NOT NULL CHECK (route IN ('IPRS', 'PRS', 'DIRECT')),
  recipient       TEXT,
  status          TEXT NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'REVISION_REQUESTED', 'SENT')),
  email_subject   TEXT NOT NULL,
  email_body      TEXT NOT NULL,
  object_key      TEXT,
  sha256          TEXT,
  case_codes      TEXT[] NOT NULL DEFAULT '{}',
  built_by        BIGINT NOT NULL REFERENCES app_user,
  built_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_by     BIGINT REFERENCES app_user,
  approved_at     TIMESTAMPTZ,
  review_note     TEXT,
  sent_by         BIGINT REFERENCES app_user,
  sent_at         TIMESTAMPTZ,
  sent_reference  TEXT,
  follow_up_date  DATE,
  supersedes_id   BIGINT REFERENCES report_pack,
  UNIQUE (run_id, version_no),
  CHECK (approved_by IS NULL OR approved_by <> built_by)
);

CREATE TABLE enquiry_case (
  id              BIGSERIAL PRIMARY KEY,
  client_id       BIGINT NOT NULL REFERENCES client,
  case_code       TEXT NOT NULL UNIQUE,
  group_key       TEXT NOT NULL,
  title           TEXT,
  work_code       TEXT,
  latest_group_id BIGINT REFERENCES comparison_group,
  pack_id         BIGINT REFERENCES report_pack,
  status          TEXT NOT NULL CHECK (status IN ('OPEN', 'AWAITING_REPLY', 'REPLIED', 'ADJUSTMENT_PROMISED',
                    'CLOSED_EXPLAINED', 'CLOSED_CORRECTED')),
  owner_id        BIGINT REFERENCES app_user,
  next_action     TEXT,
  follow_up_date  DATE,
  reply           JSONB NOT NULL DEFAULT '{}',
  payment_status  TEXT NOT NULL DEFAULT 'NONE' CHECK (payment_status IN ('NONE', 'PENDING', 'CREDITED', 'RECEIVED')),
  linked_refs     JSONB NOT NULL DEFAULT '[]',
  close_reason    TEXT,
  close_evidence  TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, group_key)
);

CREATE TABLE case_event (
  id        BIGSERIAL PRIMARY KEY,
  case_id   BIGINT NOT NULL REFERENCES enquiry_case,
  at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_id  BIGINT REFERENCES app_user,
  kind      TEXT NOT NULL,
  detail    JSONB NOT NULL DEFAULT '{}'
);

-- ------------------------------------------------------------------ audit (append-only, hash-chained)
CREATE TABLE audit_event (
  id           BIGINT PRIMARY KEY,
  at           TIMESTAMPTZ NOT NULL,
  actor_id     BIGINT,
  actor        TEXT,
  action       TEXT NOT NULL,
  object_kind  TEXT,
  object_id    TEXT,
  detail       JSONB NOT NULL DEFAULT '{}',
  prev_hash    TEXT NOT NULL,
  hash         TEXT NOT NULL
);
CREATE SEQUENCE audit_event_seq;
