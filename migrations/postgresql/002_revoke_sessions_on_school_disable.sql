-- Apply after 001_initial.sql to existing PostgreSQL installations.
-- School reactivation must never resurrect previously issued credentials.
BEGIN;
CREATE OR REPLACE FUNCTION revoke_school_sessions_on_disable()
RETURNS TRIGGER LANGUAGE plpgsql AS $revoke$
BEGIN
  IF OLD.active IS TRUE AND NEW.active IS FALSE THEN
    DELETE FROM parent_sessions
      WHERE parent_id IN (SELECT id FROM parent_accounts WHERE school_id=NEW.id);
    DELETE FROM staff_sessions
      WHERE staff_id IN (SELECT id FROM staff_accounts WHERE school_id=NEW.id);
  END IF;
  RETURN NEW;
END;
$revoke$;
DROP TRIGGER IF EXISTS trg_revoke_school_sessions ON schools;
CREATE TRIGGER trg_revoke_school_sessions
AFTER UPDATE OF active ON schools
FOR EACH ROW EXECUTE FUNCTION revoke_school_sessions_on_disable();
COMMIT;
