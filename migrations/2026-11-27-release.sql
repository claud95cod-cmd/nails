BEGIN;
ALTER TABLE booking.profile
    ADD COLUMN IF NOT EXISTS lead_hours integer NOT NULL DEFAULT 0
    CHECK (lead_hours BETWEEN 0 AND 168);
ALTER TABLE booking.visits
    ADD COLUMN IF NOT EXISTS comment text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS consent_version text,
    ADD COLUMN IF NOT EXISTS consented_at timestamptz;
COMMIT;
