-- 1.1.0: exactly three application roles, held on the account itself: SUPER_ADMIN, ADMIN and USER.
-- The old role rows (user_role) are kept as the record of how each account was set up before; the application no
-- longer reads them. Accounts are switched off or soft-deleted, never removed, so every recorded action stays
-- traceable to a person.

ALTER TABLE app_user
  ADD COLUMN role                  TEXT,
  ADD COLUMN must_change_password  BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN created_by            BIGINT REFERENCES app_user,
  ADD COLUMN updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN deleted_at            TIMESTAMPTZ,
  ADD COLUMN deleted_by            BIGINT REFERENCES app_user;

-- old roles -> new: the earliest active administrator becomes the Super Admin, other administrators become Admins,
-- everyone else (preparers, reviewers, accounts, viewers) becomes a User
UPDATE app_user u SET role = 'ADMIN'
 WHERE EXISTS (SELECT 1 FROM user_role r WHERE r.user_id = u.id AND r.role = 'admin');
UPDATE app_user SET role = 'SUPER_ADMIN'
 WHERE id = (SELECT min(u.id) FROM app_user u JOIN user_role r ON r.user_id = u.id AND r.role = 'admin' WHERE u.active);
UPDATE app_user SET role = 'USER' WHERE role IS NULL;

-- Viewers used to see every client; as Users they keep seeing every client that exists today
INSERT INTO client_grant (user_id, client_id)
SELECT DISTINCT r.user_id, c.id FROM user_role r CROSS JOIN client c
 WHERE r.role = 'viewer' AND NOT EXISTS (SELECT 1 FROM user_role a WHERE a.user_id = r.user_id AND a.role = 'admin')
ON CONFLICT DO NOTHING;

ALTER TABLE app_user ALTER COLUMN role SET DEFAULT 'USER', ALTER COLUMN role SET NOT NULL;
ALTER TABLE app_user ADD CONSTRAINT app_user_role_check CHECK (role IN ('SUPER_ADMIN', 'ADMIN', 'USER'));
ALTER TABLE app_user ADD CONSTRAINT app_user_deleted_is_inactive CHECK (deleted_at IS NULL OR NOT active);
COMMENT ON TABLE user_role IS 'Superseded in 1.1.0 by app_user.role; kept as the record of the earlier role assignments.';

-- The Super Admin is protected by the database itself, whatever the application asks for:
--   * it can never be deleted;
--   * the last active Super Admin can never be demoted, switched off or soft-deleted;
--   * a second Super Admin can only be created through the recovery procedure (python -m mrm.cli recover-super-admin),
--     which sets app.recovery for its own transaction and is audited.
CREATE FUNCTION super_admin_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  recovery BOOLEAN := coalesce(current_setting('app.recovery', true), '') = 'on';
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.role = 'SUPER_ADMIN' THEN
      RAISE EXCEPTION 'the Super Admin account cannot be deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.role = 'SUPER_ADMIN' AND (TG_OP = 'INSERT' OR OLD.role <> 'SUPER_ADMIN') AND NOT recovery
     AND EXISTS (SELECT 1 FROM app_user WHERE role = 'SUPER_ADMIN' AND active AND deleted_at IS NULL AND id <> NEW.id) THEN
    RAISE EXCEPTION 'there is already a Super Admin; another one can only be set up through the recovery procedure'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.role = 'SUPER_ADMIN' AND OLD.active AND OLD.deleted_at IS NULL
     AND (NEW.role <> 'SUPER_ADMIN' OR NOT NEW.active OR NEW.deleted_at IS NOT NULL)
     AND NOT EXISTS (SELECT 1 FROM app_user WHERE role = 'SUPER_ADMIN' AND active AND deleted_at IS NULL
                     AND id <> NEW.id) THEN
    RAISE EXCEPTION 'the last active Super Admin cannot be demoted, switched off or deleted'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER super_admin_guard BEFORE INSERT OR UPDATE OR DELETE ON app_user FOR EACH ROW
  EXECUTE FUNCTION super_admin_guard();
