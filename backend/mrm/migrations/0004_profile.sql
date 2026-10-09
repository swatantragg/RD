-- 1.0.2: each person sees the "what's new" note of an update once (remembered on the server, not in one browser).
ALTER TABLE app_user ADD COLUMN seen_version TEXT;
