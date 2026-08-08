-- 002 — webhook delivery dedupe, and persistent reminder state.
--
-- Both tables exist because of the same realisation: the transport layer
-- retries, and neither the sync model nor the scheduler was protected against
-- it.
--
-- processed_events: Telegram and LINE both redeliver an update when the
-- webhook does not answer 2xx quickly enough. Reprocessing the same message
-- parses it again, which mints a *new* entry UUID, so the drink is logged
-- twice. The client-generated UUIDs in `logs` protect against a client
-- replaying the same entry; they do nothing about the server producing two
-- different entries from one message. The platform's own event id is the only
-- stable key for that, so it is recorded here before the message is handled.
--
-- reminder_state: the scheduler needs to know when it last messaged someone.
-- Holding that in memory means a restart re-sends every reminder in the
-- current window — on LINE that spends real quota, at 300 pushes a month.

CREATE TABLE processed_events (
    platform      TEXT NOT NULL,        -- 'telegram' | 'line'
    event_id      TEXT NOT NULL,        -- update_id / webhookEventId
    processed_at  TEXT NOT NULL,        -- ISO-8601 UTC
    PRIMARY KEY (platform, event_id)
);

-- Supports pruning old rows; the table would otherwise grow forever.
CREATE INDEX idx_processed_events_time ON processed_events(processed_at);

CREATE TABLE reminder_state (
    user_id       TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_sent_at  TEXT
);
