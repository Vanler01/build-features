-- Schema per REQUIREMENTS.md §10, adjusted to match the `Term`/`Sense` split
-- Phase 0 actually shipped (types.ts, seed.ts, seed.json): `source` and
-- `verified` are per-*term* provenance, not per-sense — a term entered the
-- store in one write, from one origin, and REQUIREMENTS §1's miss path
-- ("ask Claude → write to the store as unverified") is a term-level miss.
-- The SQL sketch in REQUIREMENTS §10 predates that refinement; the shipped,
-- tested code is the authority here.

CREATE TABLE terms (
  id INTEGER PRIMARY KEY,
  term TEXT NOT NULL UNIQUE,
  normalised TEXT NOT NULL,
  register TEXT NOT NULL CHECK (register IN ('genz', 'genalpha', 'both')),
  source TEXT NOT NULL CHECK (source IN ('manual_seed', 'claude', 'user_report')),
  verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  -- The check this schema exists to enforce (CLAUDE.md rule 2): a model's
  -- guess may never arrive at this table already marked verified.
  CHECK (NOT (source = 'claude' AND verified = 1))
);

CREATE INDEX idx_terms_normalised ON terms (normalised);

CREATE TABLE senses (
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES terms (id) ON DELETE CASCADE,
  definition TEXT NOT NULL,
  example TEXT,
  confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  content_flags TEXT NOT NULL, -- JSON array of ContentFlag
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);

CREATE INDEX idx_senses_term ON senses (term_id);

CREATE TABLE aliases (
  term_id INTEGER NOT NULL REFERENCES terms (id) ON DELETE CASCADE,
  variant TEXT NOT NULL,
  normalised TEXT NOT NULL,
  PRIMARY KEY (term_id, variant)
);

CREATE INDEX idx_aliases_normalised ON aliases (normalised);

-- Term + timestamp only — never a user id, message body, page or URL.
-- See CLAUDE.md rule 19.
CREATE TABLE lookups (
  id INTEGER PRIMARY KEY,
  term_id INTEGER REFERENCES terms (id) ON DELETE SET NULL,
  looked_up_at TEXT NOT NULL,
  found_locally INTEGER NOT NULL CHECK (found_locally IN (0, 1))
);

-- References terms, not senses, to match verification's granularity above.
-- A /report can name which sense prompted it in `note` without that being
-- what gets reviewed and promoted.
CREATE TABLE review_queue (
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES terms (id) ON DELETE CASCADE,
  reason TEXT NOT NULL CHECK (reason IN ('unverified', 'decayed', 'reported')),
  note TEXT,
  queued_at TEXT NOT NULL,
  resolved_at TEXT
);
