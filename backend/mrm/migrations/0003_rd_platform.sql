-- Royalty processing platform (Docs/PHASE-1-AUDIT-AND-PLAN.md, Architecture V3): clients with rights holders and
-- user grants, uploaded files and their source lines, processing runs, builds, decisions and reports.
-- Every table carries client_id; row-level security limits the application login to the clients of the signed-in
-- person (app.client_ids, set by the server for every transaction). Without that setting nothing is visible.

ALTER TABLE client ADD COLUMN settings JSONB NOT NULL DEFAULT '{}';
ALTER TABLE client ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE FUNCTION rd_scope() RETURNS BIGINT[] LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN coalesce(current_setting('app.client_ids', true), '') = '' THEN '{}'::BIGINT[]
              ELSE string_to_array(current_setting('app.client_ids', true), ',')::BIGINT[] END
$$;

-- ------------------------------------------------------------------ clients: rights holders and who may see them
CREATE TABLE client_holder (
  id           BIGSERIAL PRIMARY KEY,
  client_id    BIGINT NOT NULL REFERENCES client,
  society      TEXT NOT NULL DEFAULT 'IPRS',
  member_no    TEXT NOT NULL,
  name         TEXT NOT NULL,
  ipi_name_no  TEXT,
  ipi_base_no  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, society, member_no)
);

CREATE TABLE client_grant (
  user_id     BIGINT NOT NULL REFERENCES app_user ON DELETE CASCADE,
  client_id   BIGINT NOT NULL REFERENCES client,
  granted_by  BIGINT REFERENCES app_user,
  granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, client_id)
);

-- ------------------------------------------------------------------ uploaded files (originals are write-once objects)
CREATE TABLE rd_file (
  id           BIGSERIAL PRIMARY KEY,
  client_id    BIGINT NOT NULL REFERENCES client,
  sha256       TEXT NOT NULL,
  filename     TEXT NOT NULL,
  bytes        BIGINT NOT NULL,
  object_key   TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('STATEMENT', 'SONG_LIST', 'REVIEW_LIST', 'PLATFORM_REVENUE',
                                             'PLATFORM_USAGE', 'PREVIOUS_OUTPUT', 'UNKNOWN')),
  kind_source  TEXT NOT NULL DEFAULT 'detected',
  layout       TEXT,
  why          TEXT,
  facts        JSONB NOT NULL DEFAULT '{}',
  overrides    JSONB NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL CHECK (status IN ('READY', 'NEEDS_REVIEW', 'UNSUPPORTED', 'ERROR', 'LEFT_OUT')),
  label        TEXT,
  meta         JSONB NOT NULL DEFAULT '{}',
  meta_source  JSONB NOT NULL DEFAULT '{}',
  problems     JSONB NOT NULL DEFAULT '[]',
  summary      JSONB NOT NULL DEFAULT '{}',
  file_date    DATE,
  uploaded_by  BIGINT REFERENCES app_user,
  uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, sha256)
);

CREATE TABLE rd_royalty_line (
  file_id    BIGINT NOT NULL REFERENCES rd_file,
  client_id  BIGINT NOT NULL REFERENCES client,
  line_no    INT NOT NULL,
  row_no     INT NOT NULL,
  work_no    TEXT,
  raw_work   TEXT,
  title      TEXT,
  language   TEXT,
  party      TEXT,
  role       TEXT,
  own_pct    NUMERIC,
  coll_pct   NUMERIC,
  pool       TEXT,
  source     TEXT,
  usage      JSONB,
  amount     NUMERIC NOT NULL,
  PRIMARY KEY (file_id, line_no)
);
CREATE INDEX rd_royalty_line_work ON rd_royalty_line (client_id, work_no);

CREATE TABLE rd_platform_line (
  file_id    BIGINT NOT NULL REFERENCES rd_file,
  client_id  BIGINT NOT NULL REFERENCES client,
  line_no    INT NOT NULL,
  row_no     INT NOT NULL,
  month      DATE,
  isrc       TEXT,
  title      TEXT,
  album      TEXT,
  upc        TEXT,
  amount     NUMERIC,                       -- NULL = blank in the file (unknown, never zero)
  plays      NUMERIC,
  PRIMARY KEY (file_id, line_no)
);
CREATE INDEX rd_platform_line_isrc ON rd_platform_line (client_id, isrc);

CREATE TABLE rd_song_entry (
  file_id      BIGINT NOT NULL REFERENCES rd_file,
  client_id    BIGINT NOT NULL REFERENCES client,
  entry_no     INT NOT NULL,
  row_no       INT NOT NULL,
  title        TEXT,
  work_nos     TEXT[] NOT NULL DEFAULT '{}',
  isrcs        TEXT[] NOT NULL DEFAULT '{}',
  other_codes  TEXT[] NOT NULL DEFAULT '{}',
  status_text  TEXT,
  note         TEXT,
  PRIMARY KEY (file_id, entry_no)
);

CREATE TABLE rd_prior (
  file_id    BIGINT PRIMARY KEY REFERENCES rd_file,
  client_id  BIGINT NOT NULL REFERENCES client,
  data       JSONB NOT NULL                 -- the previous report's columns and rows, exactly as read
);

-- ------------------------------------------------------------------ processing runs
CREATE TABLE rd_run (
  id          BIGSERIAL PRIMARY KEY,
  client_id   BIGINT NOT NULL REFERENCES client,
  title       TEXT NOT NULL,
  state       TEXT NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN', 'ARCHIVED')),
  created_by  BIGINT NOT NULL REFERENCES app_user,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rd_run_file (
  run_id     BIGINT NOT NULL REFERENCES rd_run,
  file_id    BIGINT NOT NULL REFERENCES rd_file,
  client_id  BIGINT NOT NULL REFERENCES client,
  added_by   BIGINT REFERENCES app_user,
  added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  removed    BOOLEAN NOT NULL DEFAULT FALSE,
  choice     JSONB NOT NULL DEFAULT '{}',   -- relation (SUPPLEMENTARY) or 'leave out' decided in Check Files
  PRIMARY KEY (run_id, file_id)
);

-- ------------------------------------------------------------------ builds (one per 'Process Files')
CREATE TABLE rd_build (
  id                BIGSERIAL PRIMARY KEY,
  client_id         BIGINT NOT NULL REFERENCES client,
  run_id            BIGINT NOT NULL REFERENCES rd_run,
  version           INT NOT NULL,
  state             TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'CHECKED', 'FAILED', 'SUBMITTED',
                                                   'PUBLISHED', 'SUPERSEDED')),
  stages            JSONB NOT NULL DEFAULT '[]',
  error             TEXT,
  error_detail      TEXT,
  inputs_sha256     TEXT,
  decisions_sha256  TEXT,
  ruleset_version   INT,
  ruleset_sha256    TEXT,
  software_version  TEXT,
  summary           JSONB NOT NULL DEFAULT '{}',
  checks            JSONB NOT NULL DEFAULT '[]',
  notices           JSONB NOT NULL DEFAULT '[]',
  left_out          JSONB NOT NULL DEFAULT '[]',
  inputs            JSONB NOT NULL DEFAULT '[]',
  generation        TEXT,
  generation_no     INT,
  created_by        BIGINT NOT NULL REFERENCES app_user,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at        TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ,
  heartbeat_at      TIMESTAMPTZ,
  submitted_by      BIGINT REFERENCES app_user,
  submitted_at      TIMESTAMPTZ,
  approved_by       BIGINT REFERENCES app_user,
  approved_at       TIMESTAMPTZ,
  published_at      TIMESTAMPTZ,
  returned_reason   TEXT,
  UNIQUE (run_id, version),
  UNIQUE (client_id, generation_no),
  CHECK (approved_by IS NULL OR (approved_by <> created_by AND approved_by <> coalesce(submitted_by, 0))),
  CHECK (state <> 'PUBLISHED' OR (approved_by IS NOT NULL AND generation_no IS NOT NULL))
);

CREATE TABLE rd_issue (
  build_id    BIGINT NOT NULL REFERENCES rd_build,
  client_id   BIGINT NOT NULL REFERENCES client,
  issue_no    INT NOT NULL,
  kind        TEXT NOT NULL,
  severity    TEXT NOT NULL,
  category    TEXT NOT NULL,
  title       TEXT NOT NULL,
  message     TEXT NOT NULL,
  subject     JSONB NOT NULL DEFAULT '{}',
  actions     JSONB NOT NULL DEFAULT '[]',
  later       BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (build_id, issue_no)
);

CREATE TABLE rd_finding (
  build_id         BIGINT NOT NULL REFERENCES rd_build,
  client_id        BIGINT NOT NULL REFERENCES client,
  finding_no       INT NOT NULL,
  row_key          TEXT NOT NULL,
  title            TEXT,
  isrcs            TEXT[] NOT NULL DEFAULT '{}',
  work_nos         TEXT[] NOT NULL DEFAULT '{}',
  royalty          NUMERIC NOT NULL,
  platform         NUMERIC NOT NULL,
  status           TEXT NOT NULL,
  status_original  TEXT,
  sources          TEXT,
  proposal         JSONB,
  PRIMARY KEY (build_id, finding_no)
);

CREATE TABLE rd_report (
  id            BIGSERIAL PRIMARY KEY,
  build_id      BIGINT NOT NULL REFERENCES rd_build,
  client_id     BIGINT NOT NULL REFERENCES client,
  kind          TEXT NOT NULL CHECK (kind IN ('MASTER', 'MISSING', 'NON_CLIENT')),
  final         BOOLEAN NOT NULL DEFAULT FALSE,
  filename      TEXT NOT NULL,
  object_key    TEXT,
  sha256        TEXT,
  bytes         BIGINT,
  rows          INT,
  available     BOOLEAN NOT NULL,
  reason        TEXT,                        -- why a report cannot be downloaded (plain language)
  totals        JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (build_id, kind, final)
);

-- ------------------------------------------------------------------ decisions (keyed by codes, carried into later runs)
CREATE TABLE rd_decision (
  id           BIGSERIAL PRIMARY KEY,
  client_id    BIGINT NOT NULL REFERENCES client,
  kind         TEXT NOT NULL CHECK (kind IN ('LINK', 'NOT_SAME', 'ASSIGN_HELD', 'SONG_STATUS')),
  subject      JSONB NOT NULL,
  subject_key  TEXT NOT NULL,
  value        JSONB NOT NULL,
  original     JSONB NOT NULL DEFAULT '{}',  -- the values as they were when the decision was made
  evidence     JSONB NOT NULL DEFAULT '{}',
  reason       TEXT,
  source       TEXT,
  moves_money  BOOLEAN NOT NULL,
  state        TEXT NOT NULL CHECK (state IN ('WAITING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUPERSEDED', 'REVOKED')),
  made_by      BIGINT NOT NULL REFERENCES app_user,
  made_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_id       BIGINT REFERENCES rd_run,
  build_id     BIGINT REFERENCES rd_build,
  checked_by   BIGINT REFERENCES app_user,
  checked_at   TIMESTAMPTZ,
  check_note   TEXT,
  CHECK (checked_by IS NULL OR checked_by <> made_by),
  CHECK (NOT (moves_money AND state = 'ACTIVE') OR checked_by IS NOT NULL)
);
CREATE INDEX rd_decision_subject ON rd_decision (client_id, kind, subject_key);

-- ------------------------------------------------------------------ background jobs (no client data; not scoped)
CREATE TABLE rd_job (
  id            BIGSERIAL PRIMARY KEY,
  client_id     BIGINT NOT NULL REFERENCES client,
  build_id      BIGINT NOT NULL REFERENCES rd_build,
  state         TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
  attempts      INT NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at    TIMESTAMPTZ,
  heartbeat_at  TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);

-- ------------------------------------------------------------------ evidence never changes
CREATE TRIGGER rd_royalty_line_frozen BEFORE UPDATE OR DELETE ON rd_royalty_line FOR EACH ROW
  EXECUTE FUNCTION refuse_change();
CREATE TRIGGER rd_platform_line_frozen BEFORE UPDATE OR DELETE ON rd_platform_line FOR EACH ROW
  EXECUTE FUNCTION refuse_change();
CREATE TRIGGER rd_song_entry_frozen BEFORE UPDATE OR DELETE ON rd_song_entry FOR EACH ROW
  EXECUTE FUNCTION refuse_change();
CREATE TRIGGER rd_prior_frozen BEFORE UPDATE OR DELETE ON rd_prior FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE FUNCTION rd_file_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'uploaded files are kept as evidence' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (NEW.client_id, NEW.sha256, NEW.filename, NEW.bytes, NEW.object_key, NEW.uploaded_by, NEW.uploaded_at)
     IS DISTINCT FROM (OLD.client_id, OLD.sha256, OLD.filename, OLD.bytes, OLD.object_key, OLD.uploaded_by,
                       OLD.uploaded_at) THEN
    RAISE EXCEPTION 'an uploaded file''s identity never changes' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rd_file_guard BEFORE UPDATE OR DELETE ON rd_file FOR EACH ROW EXECUTE FUNCTION rd_file_guard();

-- a published report is the record of what was published
CREATE FUNCTION rd_build_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'builds are never deleted' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.state IN ('PUBLISHED', 'SUPERSEDED') THEN
    IF OLD.state = 'PUBLISHED' AND NEW.state = 'SUPERSEDED'
       AND (to_jsonb(NEW) - 'state') = (to_jsonb(OLD) - 'state') THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'published report % cannot change - process again to make a new version', OLD.generation
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rd_build_guard BEFORE UPDATE OR DELETE ON rd_build FOR EACH ROW EXECUTE FUNCTION rd_build_guard();

CREATE FUNCTION rd_report_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.final THEN
    RAISE EXCEPTION 'report files are kept as issued' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rd_report_guard BEFORE UPDATE OR DELETE ON rd_report FOR EACH ROW EXECUTE FUNCTION rd_report_guard();

-- a decision's content is fixed; only its state moves forward
CREATE FUNCTION rd_decision_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'decisions are never deleted' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (to_jsonb(NEW) - 'state' - 'checked_by' - 'checked_at' - 'check_note')
     <> (to_jsonb(OLD) - 'state' - 'checked_by' - 'checked_at' - 'check_note') THEN
    RAISE EXCEPTION 'a decision cannot be edited - make a new one' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NOT ((OLD.state = 'WAITING_APPROVAL' AND NEW.state IN ('ACTIVE', 'REJECTED'))
          OR (OLD.state = 'ACTIVE' AND NEW.state IN ('SUPERSEDED', 'REVOKED'))
          OR (OLD.state = NEW.state AND OLD.checked_by IS NOT DISTINCT FROM NEW.checked_by)) THEN
    RAISE EXCEPTION 'decision % cannot go from % to %', OLD.id, OLD.state, NEW.state
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rd_decision_guard BEFORE UPDATE OR DELETE ON rd_decision FOR EACH ROW
  EXECUTE FUNCTION rd_decision_guard();

-- ------------------------------------------------------------------ client isolation (row-level security)
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['client_holder', 'rd_file', 'rd_royalty_line', 'rd_platform_line', 'rd_song_entry',
                           'rd_prior', 'rd_run', 'rd_run_file', 'rd_build', 'rd_issue', 'rd_finding', 'rd_report',
                           'rd_decision'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY client_scope ON %I USING (client_id = ANY (rd_scope())) '
                   'WITH CHECK (client_id = ANY (rd_scope()))', t);
  END LOOP;
END $$;

-- ------------------------------------------------------------------ the application login
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mrm_app') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON client_holder, client_grant, rd_file, rd_run, rd_run_file, '
            'rd_build, rd_issue, rd_finding, rd_report, rd_decision, rd_job TO mrm_app';
    EXECUTE 'GRANT SELECT, INSERT ON rd_royalty_line, rd_platform_line, rd_song_entry, rd_prior TO mrm_app';
    EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mrm_app';
    EXECUTE 'REVOKE DELETE ON rd_file, rd_build, rd_report, rd_decision FROM mrm_app';
  END IF;
END $$;
