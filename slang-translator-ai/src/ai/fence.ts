/**
 * Wrapping untrusted text before it reaches a prompt — CLAUDE.md rule 9.
 *
 * Every prompt here tells the model that anything inside `<message>` tags is
 * user text rather than instructions. That promise is only worth something if
 * the user cannot close the tag themselves: a selection containing the literal
 * `</message>` ends the fence early, and everything after it reads as though
 * it came from us.
 *
 * Forced `tool_choice` is the real defence and holds regardless — the model
 * can only answer with the registered schema, so this is not a path to
 * arbitrary output. But a fence that can be walked out of gives false
 * confidence, and the extension made the input surface wider: any text on any
 * page, selected by anyone.
 */

/**
 * Wrap text as a `<message>` block that cannot be escaped from.
 *
 * Only `<` is escaped, which is all it takes to make forging a tag
 * impossible. `&` is deliberately left alone: escaping it too would render a
 * plain ampersand as `&amp;` in the model's view of a user's sentence, and
 * the goal here is to neutralise markup, not to produce valid HTML.
 */
export function fence(text: string): string {
  return `<message>${text.replace(/</g, '&lt;')}</message>`;
}
