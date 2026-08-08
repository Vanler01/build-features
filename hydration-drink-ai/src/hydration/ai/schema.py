"""The structured-output schema for drink parsing.

This schema *is* the contract with Claude: the API constrains the response to
it, so the model cannot return a shape the parser doesn't expect. That removes
the whole class of failure where a prose reply is regexed and quietly
mis-parsed (``../AI_PROJECTS.md`` rule 3).

Note what is deliberately *absent*: numeric bounds. Structured outputs do not
support ``minimum`` / ``maximum``, and a schema-valid parse is not the same as a
plausible one -- "40 coffees" conforms perfectly. Plausibility lives in
``validate.py`` and runs between the parse and the database write.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Temperature(StrEnum):
    """How the drink was served. ``UNKNOWN`` when the user didn't say."""

    HOT = "hot"
    ICED = "iced"
    ROOM = "room"
    UNKNOWN = "unknown"


class TimeOfDay(StrEnum):
    """Roughly when the drink was had, relative to the user's day."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    """How sure the model is about this entry."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ParsedDrink(BaseModel):
    """One drink extracted from a message.

    Every field is required so there is no silent-``None`` contract; "the user
    didn't say" is expressed by an explicit ``unknown`` member rather than by
    omission.
    """

    drink_type: str = Field(
        description="The drink as the user named it, lowercased. e.g. 'latte', "
        "'water', 'iced americano'. Do not normalise to a catalog name."
    )
    temperature: Temperature = Field(
        description="hot, iced, room, or unknown if the user did not say."
    )
    quantity: float = Field(
        description="How many servings. 1 when the user did not say a number."
    )
    size_ml: int | None = Field(
        description="Rough serving size in millilitres if the user indicated one "
        "(e.g. 'large', 'a mug', '500ml'), otherwise null. Never guess."
    )
    time_of_day: TimeOfDay = Field(
        description="When they had it, if stated or clearly implied; otherwise unknown."
    )
    confidence: Confidence = Field(
        description="high when the drink and count are explicit; medium when one "
        "was inferred; low when the message is vague about this entry."
    )


class ParseResult(BaseModel):
    """The full result of parsing one message.

    ``drinks`` is always a list, even for a single drink -- "2 hot coffees this
    morning, an iced latte tonight" is two entries with different times of day,
    and a single-object contract would silently drop one of them.
    """

    drinks: list[ParsedDrink] = Field(
        description="Every drink mentioned. Empty when the message describes no "
        "drink at all."
    )
    needs_clarification: bool = Field(
        description="True when the message is too ambiguous to log accurately. "
        "Prefer asking over guessing."
    )
    clarification_question: str | None = Field(
        description="One short question to resolve the ambiguity, or null when "
        "needs_clarification is false."
    )
