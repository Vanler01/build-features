-- 003 — bearer tokens for the mobile app.
--
-- The app is the first surface that talks to us directly rather than through a
-- messaging platform, so it is the first that needs its own credential. A link
-- code proves "this is the person who was chatting to the bot"; it is
-- single-use and expires in ten minutes, so it cannot also be the thing the
-- app presents on every request. Redeeming one mints a token instead.
--
-- Stored hashed, exactly like link_tokens: a database dump must not hand over
-- live account access. Revocable, so signing out on a lost phone is possible
-- without invalidating the user's other devices.

CREATE TABLE app_tokens (
    token_hash    TEXT PRIMARY KEY,     -- sha256 of the raw token
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT,
    revoked_at    TEXT                  -- NULL while valid
);

CREATE INDEX idx_app_tokens_user ON app_tokens(user_id);
