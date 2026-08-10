/**
 * Vocabulary types.
 *
 * The shapes here encode two rules from `CLAUDE.md` that are easy to violate by
 * accident: a term has *senses* rather than one definition, and every sense
 * carries where it came from and whether a person has confirmed it.
 */

/** Where a sense came from. Never a generic value — see CLAUDE.md rule 3. */
export type Source = 'manual_seed' | 'claude' | 'user_report';

/** Which generation's register the term mainly belongs to. */
export type Register = 'genz' | 'genalpha' | 'both';

/** How sure we are. Surfaced to the reader; not a substitute for `verified`. */
export type Confidence = 'high' | 'medium' | 'low';

/**
 * Content warnings, shown *beside* a definition and never used to hide it.
 * See CLAUDE.md rule 12 — somebody asked, so the answer is the product.
 */
export type ContentFlag = 'sexual' | 'vulgar' | 'slur' | 'violent';

/** One meaning of a term. A term may legitimately have several. */
export interface Sense {
  readonly definition: string;
  /**
   * Omitted deliberately for slurs: an example models using the word.
   * That is the one hard rule in the content policy (CLAUDE.md rule 11).
   */
  readonly example?: string;
  readonly confidence: Confidence;
  readonly contentFlags: readonly ContentFlag[];
}

/** A term and everything known about it. */
export interface Term {
  readonly term: string;
  /** Spelling variants that resolve to this term: "no cap" / "nocap" / "🧢". */
  readonly aliases: readonly string[];
  readonly register: Register;
  readonly senses: readonly Sense[];
  readonly source: Source;
  /**
   * Set by a person, never by code. A Claude-written entry is *served* while
   * unverified — that is what the cache is for — but promoting it
   * automatically would launder a guess into a fact (CLAUDE.md rule 2).
   */
  readonly verified: boolean;
}

/**
 * Normalise a term for lookup: case, whitespace, surrounding punctuation.
 * Real emoji (🧢) are kept — an alias like the "cap" emoji would otherwise
 * normalise to the empty string and become permanently unreachable.
 */
export function normalise(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\p{Emoji_Presentation}\s'’-]/gu, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}
