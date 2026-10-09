-- Controls the application cannot switch off (page 9: "history retained"; page 13: "rule changes create new
-- versions", "resolving a case retains history").

-- ------------------------------------------------------------------ audit: hash chain computed by the database
CREATE FUNCTION audit_canon(e audit_event) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  SELECT concat_ws('|', e.id::TEXT, to_char(e.at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
                   coalesce(e.actor_id::TEXT, ''), coalesce(e.actor, ''), e.action, coalesce(e.object_kind, ''),
                   coalesce(e.object_id, ''), e.detail::TEXT, e.prev_hash)
$$;

CREATE FUNCTION audit_chain() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(84726001);
  NEW.id := nextval('audit_event_seq');
  NEW.at := clock_timestamp();
  NEW.prev_hash := coalesce((SELECT hash FROM audit_event ORDER BY id DESC LIMIT 1), repeat('0', 64));
  NEW.hash := encode(sha256(convert_to(audit_canon(NEW), 'UTF8')), 'hex');
  RETURN NEW;
END $$;
CREATE TRIGGER audit_chain BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION audit_chain();

CREATE FUNCTION refuse_change() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_event FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER case_event_append_only BEFORE UPDATE OR DELETE ON case_event FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER identity_link_frozen BEFORE UPDATE OR DELETE ON identity_version_link FOR EACH ROW
  EXECUTE FUNCTION refuse_change();

-- ------------------------------------------------------------------ approved identity versions are frozen
CREATE FUNCTION identity_version_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'identity versions are never deleted' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.status = 'SUPERSEDED' AND OLD.status = 'APPROVED'
     AND (NEW.version_no, NEW.checks, NEW.counts, NEW.approved_by, NEW.approved_at)
         IS NOT DISTINCT FROM (OLD.version_no, OLD.checks, OLD.counts, OLD.approved_by, OLD.approved_at) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'identity version % is frozen - approve a new version instead', OLD.version_no
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER identity_version_guard BEFORE UPDATE OR DELETE ON identity_version FOR EACH ROW
  EXECUTE FUNCTION identity_version_guard();

-- ------------------------------------------------------------------ approved rules are frozen (E5)
CREATE FUNCTION rule_version_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status = 'DRAFT' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'approved rule versions are never deleted' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.status = 'DRAFT' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'APPROVED' AND NEW.status = 'RETIRED'
     AND (to_jsonb(NEW) - 'status' - 'effective_to') = (to_jsonb(OLD) - 'status' - 'effective_to') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'rule % v% is % - changes create a new version', OLD.rule_key, OLD.version_no, OLD.status
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER rule_version_guard BEFORE UPDATE OR DELETE ON rule_version FOR EACH ROW
  EXECUTE FUNCTION rule_version_guard();

-- ------------------------------------------------------------------ completed runs and their groups are frozen
CREATE FUNCTION run_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.status <> 'RUNNING' THEN
    RAISE EXCEPTION 'comparison run v% is % and cannot change', OLD.version_no, OLD.status
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER run_guard BEFORE UPDATE OR DELETE ON comparison_run FOR EACH ROW EXECUTE FUNCTION run_guard();

CREATE FUNCTION group_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT status FROM comparison_run WHERE id = coalesce(NEW.run_id, OLD.run_id)) <> 'RUNNING' THEN
    RAISE EXCEPTION 'groups of a completed run cannot change' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN coalesce(NEW, OLD);
END $$;
CREATE TRIGGER group_guard BEFORE INSERT OR UPDATE OR DELETE ON comparison_group FOR EACH ROW
  EXECUTE FUNCTION group_guard();
CREATE TRIGGER run_exception_guard BEFORE INSERT OR UPDATE OR DELETE ON run_exception FOR EACH ROW
  EXECUTE FUNCTION group_guard();

-- ------------------------------------------------------------------ a sent pack is the record of what was sent
CREATE FUNCTION pack_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'report packs are never deleted' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.status = 'SENT' THEN
    RAISE EXCEPTION 'pack v% was sent and cannot change', OLD.version_no USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (NEW.email_subject, NEW.email_body, NEW.sha256, NEW.object_key, NEW.case_codes, NEW.built_by, NEW.run_id)
     IS DISTINCT FROM (OLD.email_subject, OLD.email_body, OLD.sha256, OLD.object_key, OLD.case_codes, OLD.built_by,
                       OLD.run_id) AND OLD.sha256 IS NOT NULL THEN
    RAISE EXCEPTION 'pack contents are fixed - build a new version' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER pack_guard BEFORE UPDATE OR DELETE ON report_pack FOR EACH ROW EXECUTE FUNCTION pack_guard();

-- ------------------------------------------------------------------ source amounts never change after intake
CREATE FUNCTION line_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'duplicate_state' - 'is_valid' - 'invalid_reason')
     <> (to_jsonb(OLD) - 'duplicate_state' - 'is_valid' - 'invalid_reason') THEN
    RAISE EXCEPTION 'source rows are evidence - only their validation and duplicate decision can change'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER publishing_line_guard BEFORE UPDATE ON publishing_line FOR EACH ROW EXECUTE FUNCTION line_guard();
CREATE TRIGGER recording_line_guard BEFORE UPDATE ON recording_line FOR EACH ROW EXECUTE FUNCTION line_guard();
CREATE TRIGGER usage_line_guard BEFORE UPDATE ON usage_line FOR EACH ROW EXECUTE FUNCTION line_guard();

-- ------------------------------------------------------------------ the application login
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mrm_app') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO mrm_app';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mrm_app';
    EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mrm_app';
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_event, case_event, identity_version_link FROM mrm_app';
    EXECUTE 'REVOKE ALL ON schema_migrations FROM mrm_app';
    EXECUTE 'GRANT SELECT ON schema_migrations TO mrm_app';
  END IF;
END $$;
