/**
 * Morphological variants — Phase 4, "aliases and variants".
 *
 * Aliases are curated: a person decided that "nocap" and "🧢" mean "cap".
 * Variants are the mechanical cases nobody should have to type out — someone
 * highlights "capping" or "bussin'" or "no-cap" and means an entry that is
 * already in the store under a slightly different shape.
 *
 * Two properties keep this safe:
 *
 * 1. **Variants never create anything.** They are extra keys tried against
 *    the store *after* an exact and an alias match have both missed. A wrong
 *    guess misses and falls through to the normal Claude path; it cannot
 *    invent an entry or a definition.
 * 2. **Conservative over clever.** No general stemmer. Over-matching is the
 *    failure mode this project is most afraid of (rule 7), and mapping a word
 *    onto the wrong entry produces a confidently wrong answer, which is worse
 *    than a miss. Only endings that are near-unambiguous in English are
 *    stripped, and each candidate must still hit a real row to matter.
 *
 * The rule curated aliases have to obey, learned the hard way: **an alias must
 * mean the same thing, not merely be related.** "no cap" shipped as an alias of
 * "cap" and inverted the answer — someone asking what "no cap" meant was told
 * `"cap" = A lie, or exaggeration`, under a headword they had not typed. An
 * alias is a second spelling of one meaning; a negation, an antonym or a
 * derived phrase is a different meaning and gets its own term. `addAlias`
 * cannot catch this — nothing mechanical can tell "nocap" from "no cap" — so it
 * is a rule for whoever runs `review -- alias`.
 *
 * Deliberately *not* here: recording which variant a user typed. That is the
 * user's own text, and `lookups` holds a term id and a timestamp, nothing else
 * (rule 19). Turning a frequently-hit variant into a permanent alias is a
 * human's job, via `npm run review -- alias`.
 */

import { normalise } from './types.js';

/**
 * Strip the separators that distinguish spellings of one phrase.
 *
 * Exported because matching has to work in *both* directions: "no-cap" can
 * generate "nocap", but "nocap" cannot generate "no cap" — nothing tells you
 * where the space belongs. So the lookup compares collapsed query against
 * collapsed stored key, and this is the function that defines "collapsed".
 */
export function collapse(key: string): string {
  return key.replace(/[\s-]+/g, '');
}

/** Candidate keys for `raw`, most-likely first, without the exact form. */
export function variantsOf(raw: string): string[] {
  const base = normalise(raw);
  if (base === '') return [];

  const candidates: string[] = [];
  const add = (candidate: string): void => {
    if (candidate !== '' && candidate !== base && !candidates.includes(candidate)) {
      candidates.push(candidate);
    }
  };

  // "no cap" / "no-cap" → "nocap". normalise() keeps hyphens (they are in its
  // allowed set, so a hyphen survives as itself), which means collapsing
  // whitespace alone is not enough — the hyphen has to go too.
  add(collapse(base));

  // Trailing apostrophe forms: "bussin'" → "bussin". normalise() keeps
  // apostrophes because they carry meaning inside a word ("ain't").
  add(base.replace(/['’]+$/u, ''));

  // Possessive: "rizz's" → "rizz".
  add(base.replace(/['’]s$/u, ''));

  for (const stem of stemsOf(base)) add(stem);

  return candidates;
}

/**
 * Plural and verb endings, stripped only where English makes it unambiguous.
 *
 * Each rule is one a reader would accept instantly — "capping" is "cap",
 * "slaps" is "slap". Anything requiring a dictionary to get right (irregular
 * plurals, "-er" comparatives that are also agent nouns) is left alone rather
 * than guessed at.
 */
function stemsOf(base: string): string[] {
  const out: string[] = [];
  const push = (s: string): void => {
    // Two characters is where stripping stops being a variant and starts being
    // a coincidence — "ads" → "ad" is fine, but nothing shorter is trustworthy.
    if (s.length >= 2) out.push(s);
  };

  // "vibes" → "vibe", "slaps" → "slap". Not "-ss" ("mess" is not "mes").
  if (base.endsWith('s') && !base.endsWith('ss')) {
    push(base.slice(0, -1));
    // "vibes" → "vibe" is covered above; "catches" → "catch" needs the -es.
    if (base.endsWith('es')) push(base.slice(0, -2));
  }

  // "capping" → "capp" → "cap"; "vibing" → "vib" → "vibe" is *not* attempted,
  // because restoring a dropped 'e' guesses at spelling rather than stripping.
  if (base.endsWith('ing')) {
    const stem = base.slice(0, -3);
    push(stem);
    push(undouble(stem));
  }

  // "capped" → "capp" → "cap". "ate" is left alone: it does not end in "ed".
  if (base.endsWith('ed')) {
    const stem = base.slice(0, -2);
    push(stem);
    push(undouble(stem));
  }

  return out;
}

/** "capp" → "cap". Only for a doubled final consonant, which is the case that arises. */
function undouble(stem: string): string {
  const last = stem.slice(-1);
  const penultimate = stem.slice(-2, -1);
  const isVowel = /[aeiou]/.test(last);
  return last === penultimate && !isVowel ? stem.slice(0, -1) : stem;
}
