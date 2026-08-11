-- Phase 2: make human verification expressible.
--
-- 001 enforced CLAUDE.md rule 2 with `CHECK (NOT (source = 'claude' AND
-- verified = 1))`. That is too strong, and it blocked the rule it meant to
-- protect. Rule 2 says a Claude-sourced entry is never *auto*-promoted and that
-- `verified` is set by a person — not that it can never be verified. Under 001
-- no entry in the store could ever be promoted, because every one of them
-- (all 56 seed terms and every live miss) is `source = 'claude'`. Phase 2's
-- whole job was unreachable.
--
-- The constraint becomes: a claude-sourced row may be verified only when a
-- person is named on the row. `verified_by` is the human's name and there is no
-- code path that sets it except an explicit review action, so an automatic
-- promotion still cannot happen — it now fails on a missing reviewer rather
-- than on the source. `source` keeps naming the real origin either way
-- (rule 3): a promoted entry stays `claude`, because that is where it came
-- from. Rewriting it to `manual_seed` on promotion would be the convenient lie
-- seed.ts already refuses to tell.
--
-- SQLite cannot alter a CHECK in place, so this is the standard table rebuild.
-- The migration runner disables foreign keys around migrations for exactly
-- this reason: `DROP TABLE terms` with them on would cascade every sense,
-- alias and queue row into oblivion.

CREATE TABLE terms_new (
  id INTEGER PRIMARY KEY,
  term TEXT NOT NULL UNIQUE,
  normalised TEXT NOT NULL,
  register TEXT NOT NULL CHECK (register IN ('genz', 'genalpha', 'both')),
  source TEXT NOT NULL CHECK (source IN ('manual_seed', 'claude', 'user_report')),
  verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
  -- Who confirmed it, and when. NULL on anything not yet reviewed.
  verified_by TEXT,
  verified_at TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  -- Rule 2, restated so that it constrains automation rather than people:
  -- a model's guess may not be marked verified with nobody's name against it.
  CHECK (NOT (source = 'claude' AND verified = 1 AND verified_by IS NULL)),
  -- An unverified row must not carry reviewer metadata, so the two fields
  -- can never disagree about whether a review actually happened.
  CHECK (verified = 1 OR (verified_by IS NULL AND verified_at IS NULL))
);

INSERT INTO terms_new (id, term, normalised, register, source, verified, first_seen, last_seen)
SELECT id, term, normalised, register, source, verified, first_seen, last_seen FROM terms;

DROP TABLE terms;

ALTER TABLE terms_new RENAME TO terms;

CREATE INDEX idx_terms_normalised ON terms (normalised);

-- Pending-queue reads filter on resolved_at IS NULL on every review command.
CREATE INDEX idx_review_queue_pending ON review_queue (resolved_at, term_id);
