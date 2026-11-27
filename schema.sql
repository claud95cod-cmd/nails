CREATE SCHEMA IF NOT EXISTS booking;
CREATE TABLE IF NOT EXISTS profile (
 id integer PRIMARY KEY CHECK (id=1), name text NOT NULL, address text NOT NULL,
 phone text NOT NULL, timezone text NOT NULL, directions text NOT NULL
);
CREATE TABLE IF NOT EXISTS services (id integer PRIMARY KEY, title text NOT NULL, price integer NOT NULL, minutes integer NOT NULL, instructions text NOT NULL);
CREATE TABLE IF NOT EXISTS visits (
 id uuid PRIMARY KEY, request_id uuid UNIQUE NOT NULL, fingerprint text NOT NULL,
 token text UNIQUE NOT NULL, name text NOT NULL, phone text NOT NULL, title text NOT NULL,
 price integer NOT NULL, minutes integer NOT NULL, starts timestamptz NOT NULL, ends timestamptz NOT NULL,
 instructions text NOT NULL, CHECK(ends>starts),
 EXCLUDE USING gist (tstzrange(starts,ends,'[)') WITH &&)
);
CREATE TABLE IF NOT EXISTS subscriptions (endpoint text PRIMARY KEY, info jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS events (id uuid PRIMARY KEY, visit uuid REFERENCES visits(id), message text NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (event uuid REFERENCES events(id), endpoint text REFERENCES subscriptions(endpoint) ON DELETE CASCADE,
 attempts integer NOT NULL DEFAULT 0, due timestamptz NOT NULL DEFAULT now(), accepted timestamptz, PRIMARY KEY(event,endpoint));
CREATE TABLE IF NOT EXISTS limits (bucket text PRIMARY KEY, hits integer NOT NULL, expires timestamptz NOT NULL);
ALTER TABLE profile ADD COLUMN IF NOT EXISTS step integer NOT NULL DEFAULT 60 CHECK(step BETWEEN 1 AND 1440);
ALTER TABLE profile ADD COLUMN IF NOT EXISTS horizon integer NOT NULL DEFAULT 30 CHECK(horizon BETWEEN 1 AND 180);
ALTER TABLE visits ADD COLUMN IF NOT EXISTS social text NOT NULL DEFAULT '';
ALTER TABLE visits ADD COLUMN IF NOT EXISTS cancelled boolean NOT NULL DEFAULT false;
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_constraint WHERE conrelid='visits'::regclass AND conname='active_visit_interval') THEN
   ALTER TABLE visits DROP CONSTRAINT IF EXISTS visits_tstzrange_excl;
   ALTER TABLE visits ADD CONSTRAINT active_visit_interval EXCLUDE USING gist
      (tstzrange(starts,ends,'[)') WITH &&) WHERE (NOT cancelled);
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS addons(id integer PRIMARY KEY, service_id integer REFERENCES services, title text NOT NULL, price integer NOT NULL, minutes integer NOT NULL);
CREATE TABLE IF NOT EXISTS week_hours(weekday integer PRIMARY KEY, opens time, closes time);
CREATE TABLE IF NOT EXISTS exceptions(day date PRIMARY KEY, opens time, closes time);
CREATE TABLE IF NOT EXISTS breaks(id uuid PRIMARY KEY, starts timestamptz NOT NULL, ends timestamptz NOT NULL CHECK(ends>starts));

ALTER TABLE profile ADD COLUMN IF NOT EXISTS specialty text NOT NULL DEFAULT 'Студия маникюра';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS tagline text NOT NULL DEFAULT '';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS links jsonb NOT NULL DEFAULT '[]';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS accent text NOT NULL DEFAULT '#633349';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS background text NOT NULL DEFAULT '#fcf8f5';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS fonts text NOT NULL DEFAULT 'classic';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS avatar text NOT NULL DEFAULT '';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS cover text NOT NULL DEFAULT '';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS cover_x integer NOT NULL DEFAULT 50;
ALTER TABLE profile ADD COLUMN IF NOT EXISTS cover_y integer NOT NULL DEFAULT 50;
ALTER TABLE profile ADD COLUMN IF NOT EXISTS configured boolean NOT NULL DEFAULT false;
ALTER TABLE services ADD COLUMN IF NOT EXISTS category text NOT NULL DEFAULT 'Маникюр';
ALTER TABLE services ADD COLUMN IF NOT EXISTS position integer NOT NULL DEFAULT 0;
ALTER TABLE services ADD COLUMN IF NOT EXISTS visible boolean NOT NULL DEFAULT true;
ALTER TABLE addons ADD COLUMN IF NOT EXISTS visible boolean NOT NULL DEFAULT true;
CREATE TABLE IF NOT EXISTS portfolio (
 id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 image text NOT NULL, caption text NOT NULL, position integer NOT NULL,
 service_id integer REFERENCES services, visible boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS photo_assets (
 key text PRIMARY KEY, full_data bytea NOT NULL, thumb_data bytea NOT NULL
);
CREATE INDEX IF NOT EXISTS deliveries_ready ON deliveries(due) WHERE accepted IS NULL;

ALTER TABLE profile ADD COLUMN IF NOT EXISTS lead_hours integer NOT NULL DEFAULT 0 CHECK(lead_hours BETWEEN 0 AND 168);

ALTER TABLE visits ADD COLUMN IF NOT EXISTS comment text NOT NULL DEFAULT '';
ALTER TABLE visits ADD COLUMN IF NOT EXISTS consent_version text;
ALTER TABLE visits ADD COLUMN IF NOT EXISTS consented_at timestamptz;
