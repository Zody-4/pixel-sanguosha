"""Player intents and interruption prompts shared by the engine and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionIntent:
    actor_id: str
    card_id: str | None = None
    skill_id: str | None = None
    target_ids: tuple[str, ...] = ()
    cost_card_ids: tuple[str, ...] = ()
    choice: str | None = None


@dataclass(frozen=True, slots=True)
class GameAction:
    action_id: str
    label: str
    intent: ActionIntent
    target_options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChoiceOption:
    choice_id: str
    label: str
    category: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    kind: str
    player_id: str
    title: str
    message: str
    options: tuple[ChoiceOption, ...]
    min_choices: int = 1
    max_choices: int = 1
    context: tuple[tuple[str, Any], ...] = ()
