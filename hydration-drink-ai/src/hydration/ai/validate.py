"""Plausibility checks between a parse and a database write.

Schema conformance is not plausibility. A response claiming forty coffees or a
three-litre espresso satisfies the schema perfectly and is still wrong, so every
parse passes through here before it becomes a ``logs`` row (CLAUDE.md rule 11).

Implausible parses are turned into a question for the user, never silently
clamped -- clamping invents data the user never said.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import ParsedDrink, ParseResult

# Bounds are deliberately generous: they exist to catch parse failures and
# prompt injection, not to police anyone's drinking.
MAX_QUANTITY_PER_ENTRY = 20.0
MAX_QUANTITY_PER_MESSAGE = 30.0
MAX_ENTRIES_PER_MESSAGE = 12
MIN_SIZE_ML = 20
MAX_SIZE_ML = 2000
MAX_DRINK_NAME_CHARS = 60


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """The result of checking a parse.

    ``question`` is set when the entries cannot be trusted; the caller asks it
    instead of writing rows.
    """

    drinks: list[ParsedDrink]
    question: str | None

    @property
    def ok(self) -> bool:
        """Whether these entries are safe to write."""
        return self.question is None and bool(self.drinks)


def _implausible(drink: ParsedDrink) -> str | None:
    """Return a reason this entry can't be trusted, or None."""
    if drink.quantity <= 0:
        return f"a non-positive count for {drink.drink_type!r}"
    if drink.quantity > MAX_QUANTITY_PER_ENTRY:
        return f"{drink.quantity:g} servings of {drink.drink_type!r}"
    if drink.size_ml is not None and not (MIN_SIZE_ML <= drink.size_ml <= MAX_SIZE_ML):
        return f"a {drink.size_ml}ml serving of {drink.drink_type!r}"
    if not drink.drink_type.strip():
        return "a drink with no name"
    if len(drink.drink_type) > MAX_DRINK_NAME_CHARS:
        return "a drink name that looks like a sentence rather than a drink"
    return None


def validate(result: ParseResult) -> ValidationOutcome:
    """Check a parse and decide whether it can be written.

    The model's own ``needs_clarification`` is honoured first: if it says it is
    unsure, that is a better signal than any bound here.
    """
    if result.needs_clarification:
        return ValidationOutcome(
            drinks=[],
            question=result.clarification_question
            or "I couldn't tell what you drank — could you say it another way?",
        )

    if not result.drinks:
        return ValidationOutcome(
            drinks=[],
            question="I didn't spot a drink in that — what did you have?",
        )

    if len(result.drinks) > MAX_ENTRIES_PER_MESSAGE:
        return ValidationOutcome(
            drinks=[],
            question=(
                "That looks like a lot of separate drinks — could you send them "
                "in a couple of smaller messages?"
            ),
        )

    for drink in result.drinks:
        reason = _implausible(drink)
        if reason is not None:
            return ValidationOutcome(
                drinks=[],
                question=f"I read that as {reason} — is that right?",
            )

    total = sum(d.quantity for d in result.drinks)
    if total > MAX_QUANTITY_PER_MESSAGE:
        return ValidationOutcome(
            drinks=[],
            question=f"I read that as {total:g} drinks in one message — is that right?",
        )

    return ValidationOutcome(drinks=list(result.drinks), question=None)
