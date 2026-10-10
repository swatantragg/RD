-- 1.0.4: a run that never reached publication can be deleted. It is hidden from every list; its rows stay as history,
-- and published reports can never be deleted (rd_build_guard).
ALTER TABLE rd_run DROP CONSTRAINT rd_run_state_check;
ALTER TABLE rd_run ADD CONSTRAINT rd_run_state_check CHECK (state IN ('OPEN', 'ARCHIVED', 'DELETED'));
ALTER TABLE rd_run ADD COLUMN deleted_at TIMESTAMPTZ, ADD COLUMN deleted_by BIGINT REFERENCES app_user;
