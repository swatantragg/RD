-- 1.0.5: no separate approval step. The person who prepares a report publishes it, and review choices that move money
-- apply at once. The Approver (and the old Sender) role goes; who published what stays recorded (approved_by is the
-- publisher, checked_by is left empty) and every action is still in the audit log.
ALTER TABLE rd_build DROP CONSTRAINT rd_build_check;               -- publisher had to differ from the preparer
ALTER TABLE rd_decision DROP CONSTRAINT rd_decision_check;         -- checker had to differ from the maker
ALTER TABLE rd_decision DROP CONSTRAINT rd_decision_check1;        -- money-moving decisions needed a checker

-- reports that were waiting for an approver go back to "ready to publish"
UPDATE rd_build SET state = 'CHECKED', submitted_by = NULL, submitted_at = NULL
 WHERE state = 'SUBMITTED' AND approved_by IS NULL;

-- changes that were waiting for an approver apply now (the newest one per song wins)
UPDATE rd_decision a SET state = 'SUPERSEDED'
 WHERE a.state = 'ACTIVE' AND EXISTS (SELECT 1 FROM rd_decision w WHERE w.state = 'WAITING_APPROVAL'
                                        AND w.client_id = a.client_id AND w.kind = a.kind
                                        AND w.subject_key = a.subject_key);
UPDATE rd_decision SET state = 'REJECTED'
 WHERE state = 'WAITING_APPROVAL'
   AND id NOT IN (SELECT max(id) FROM rd_decision WHERE state = 'WAITING_APPROVAL' GROUP BY client_id, kind, subject_key);
UPDATE rd_decision SET state = 'ACTIVE' WHERE state = 'WAITING_APPROVAL';

-- people who were only Approvers (or Senders) keep access as Viewers
INSERT INTO user_role (user_id, role)
SELECT DISTINCT user_id, 'viewer' FROM user_role r
 WHERE role IN ('approver', 'sender')
   AND NOT EXISTS (SELECT 1 FROM user_role o WHERE o.user_id = r.user_id AND o.role NOT IN ('approver', 'sender'))
ON CONFLICT DO NOTHING;
DELETE FROM user_role WHERE role IN ('approver', 'sender');
ALTER TABLE user_role DROP CONSTRAINT user_role_role_check;
ALTER TABLE user_role ADD CONSTRAINT user_role_role_check
  CHECK (role IN ('admin', 'importer', 'rights_reviewer', 'accounts', 'viewer'));
