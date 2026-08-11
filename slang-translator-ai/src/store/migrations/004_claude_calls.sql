-- Phase 5: what the store costs to fill.
--
-- Every miss calls Claude, and a sentence can cost one detect plus one define
-- per candidate. Nothing counted those calls and nothing stopped them, which
-- for a cache-first product is the one number that says whether the cache is
-- working — and the one runaway that can spend real money while nobody is
-- looking. The extension makes it a right-click.
--
-- What this table holds is deliberately thin: which model, what the call was
-- for, and when. **Never the term, never the prompt, never the reply.** Rule
-- 19's discipline is about lookups, but the reasoning carries straight over —
-- what somebody asked about is sensitive, and a cost table is no place to
-- start keeping a second copy of it. If this table leaked it would say how
-- much the thing was used and nothing whatsoever about who used it or why.
--
-- `purpose` is the ai/ module that made the call ('define', 'detect',
-- 'disambiguate'), which is enough to see where the money goes without
-- recording what was said.

CREATE TABLE claude_calls (
  id INTEGER PRIMARY KEY,
  model TEXT NOT NULL,
  purpose TEXT NOT NULL,
  called_at TEXT NOT NULL
);

-- The daily cap counts rows in a date range on every miss, so the index is
-- doing real work rather than anticipating a need.
CREATE INDEX idx_claude_calls_at ON claude_calls (called_at);
