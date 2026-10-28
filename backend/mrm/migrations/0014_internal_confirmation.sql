-- 1.7.0: an enquiry is confirmed inside the company before it goes to IPRS / PRS; a second person verifies a
-- reconciliation; a catalogue import records how the catalogue was received.
--   * Internal: the preparer forwards the enquiry to a colleague (any active person), who views the reports and
--     confirms or returns them - or the preparer records a confirmation given outside the application (a live
--     demonstration of the report, a text message, a call, a meeting) with who confirmed it and when. Only then can the
--     text be copied and the sending to IPRS / PRS be recorded.
--   * External: after the sending, reminders every 7 days (the same mail again, 3 times), the 4th a call that is
--     escalated to the IPRS CEO. These are follow-ups (enquiry_actions); no column is needed for them.

ALTER TABLE enquiries ADD COLUMN review_requested_from BIGINT REFERENCES app_user;   -- forwarded to (in the application)
ALTER TABLE enquiries ADD COLUMN review_requested_at   TIMESTAMPTZ;
ALTER TABLE enquiries ADD COLUMN confirmation_method   TEXT CHECK (confirmation_method IN (
  'IN_APPLICATION', 'LIVE_DEMO', 'TEXT', 'PHONE', 'MEETING', 'OTHER'));
ALTER TABLE enquiries ADD COLUMN confirmed_by_name     TEXT;                         -- who confirmed the report
ALTER TABLE enquiries ADD COLUMN confirmed_at          TIMESTAMPTZ;                  -- when (date and time)
ALTER TABLE enquiries ADD COLUMN confirmation_note     TEXT;

-- approvals before 1.7.0 were given in the application
UPDATE enquiries e SET confirmation_method = 'IN_APPLICATION', confirmed_at = e.approved_at,
       confirmed_by_name = (SELECT name FROM app_user u WHERE u.id = e.approved_by)
 WHERE e.approved_by IS NOT NULL;

ALTER TABLE reconciliation_runs ADD COLUMN verified_by  BIGINT REFERENCES app_user;   -- the second person
ALTER TABLE reconciliation_runs ADD COLUMN verified_at  TIMESTAMPTZ;
ALTER TABLE reconciliation_runs ADD COLUMN verify_note  TEXT;
ALTER TABLE reconciliation_runs ADD CONSTRAINT reconciliation_runs_verified_by_other
  CHECK (verified_by IS NULL OR verified_by <> started_by);

ALTER TABLE catalogue_imports ADD COLUMN received_via  TEXT CHECK (received_via IN ('EMAIL', 'WHATSAPP', 'OTHER'));
ALTER TABLE catalogue_imports ADD COLUMN received_from TEXT;

-- a completed run keeps its numbers; the only change it takes is the second person's verification, once
CREATE OR REPLACE FUNCTION reconciliation_run_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'reconciliation runs are kept' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.status <> 'RUNNING' THEN
    IF OLD.verified_by IS NULL AND NEW.verified_by IS NOT NULL
       AND (to_jsonb(NEW) - 'verified_by' - 'verified_at' - 'verify_note')
           = (to_jsonb(OLD) - 'verified_by' - 'verified_at' - 'verify_note') THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'reconciliation run % is complete and cannot change - run a new one', OLD.run_reference
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
