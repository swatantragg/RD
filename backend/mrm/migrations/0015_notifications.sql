-- 1.7.1: a person is told, in a pop-up in the top-right corner, when someone else hands them work: an enquiry assigned
-- to them, a report to confirm, a follow-up, a reconciliation exception - and, for the preparer, a report returned or
-- confirmed. Opening or dismissing the pop-up marks it read; nothing else changes.
CREATE TABLE notifications (
  id          BIGSERIAL PRIMARY KEY,
  client_id   BIGINT NOT NULL REFERENCES client,
  user_id     BIGINT NOT NULL REFERENCES app_user,          -- who it is for
  kind        TEXT NOT NULL CHECK (kind IN ('ENQUIRY_ASSIGNED', 'CONFIRM_REPORT', 'REPORT_RETURNED', 'REPORT_CONFIRMED',
                                            'FOLLOW_UP_ASSIGNED', 'EXCEPTION_ASSIGNED')),
  title       TEXT NOT NULL,
  body        TEXT,
  link        TEXT,                                         -- the page it opens, e.g. 'enquiries/12'
  created_by  BIGINT REFERENCES app_user,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  read_at     TIMESTAMPTZ
);
CREATE INDEX notifications_unread ON notifications (user_id) WHERE read_at IS NULL;

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY client_scope ON notifications USING (client_id = ANY (rd_scope()))
  WITH CHECK (client_id = ANY (rd_scope()));

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mrm_app') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON notifications TO mrm_app';
    EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE notifications_id_seq TO mrm_app';
  END IF;
END $$;
