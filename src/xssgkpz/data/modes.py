"""Mode and game-setup constants; this module contains no game resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Difficulty(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    HARD = "hard"


class HeroSelectionMethod(StrEnum):
    FREE_CHOICE = "free_choice"
    RANDOM_THREE_CHOOSE_ONE = "random_three_choose_one"
    FULL_RANDOM = "full_random"


class Identity(StrEnum):
    LORD = "lord"
    LOYALIST = "loyalist"
    REBEL = "rebel"
    TURNCOAT = "turncoat"


@dataclass(frozen=True, slots=True)
class ModeDefinition:
    mode_id: str
    name: str
    player_count: int
    ai_count: int
    seat_order: tuple[str, ...]
    opening_actor: str
    starting_hand_sizes: tuple[int, ...]
    random_seating: bool
    initial_seat_distance: int | None = None
    player_current_hp_delta: int = 0
    player_max_hp_delta: int = 0
    lord_current_hp_delta: int = 0
    lord_max_hp_delta: int = 0
    duel_first_turn_draw_count: int | None = None
    lord_skills_enabled: bool = True
    identity_counts: tuple[tuple[Identity, int], ...] = ()
    identity_options: tuple[str, ...] = ()
    public_identity: bool = False


MODES: tuple[ModeDefinition, ...] = (
    ModeDefinition(
        mode_id="duel", name="斗将：1v1", player_count=2, ai_count=1,
        seat_order=("player", "ai_1"), opening_actor="random",
        starting_hand_sizes=(4, 4), random_seating=False, initial_seat_distance=1,
        duel_first_turn_draw_count=1, lord_skills_enabled=False,
    ),
    ModeDefinition(
        mode_id="two_heroes", name="力敌双雄：1v2", player_count=3, ai_count=2,
        seat_order=("player", "ai_1", "ai_2"), opening_actor="player",
        starting_hand_sizes=(5, 4, 4), random_seating=False, initial_seat_distance=1,
        player_current_hp_delta=1, player_max_hp_delta=1,
        lord_skills_enabled=False, public_identity=True,
    ),
    ModeDefinition(
        mode_id="five_player_identity", name="尔虞我诈：五人身份局",
        player_count=5, ai_count=4,
        seat_order=("player", "seat_2", "seat_3", "seat_4", "seat_5"),
        opening_actor="lord", starting_hand_sizes=(4, 4, 4, 4, 4),
        random_seating=True, lord_current_hp_delta=1, lord_max_hp_delta=1,
        identity_counts=((Identity.LORD, 1), (Identity.LOYALIST, 1),
                         (Identity.REBEL, 2), (Identity.TURNCOAT, 1)),
        identity_options=("player_selects_identity", "random_identity_assignment"),
    ),
)

MODE_BY_ID = {mode.mode_id: mode for mode in MODES}


@dataclass(frozen=True, slots=True)
class DifficultyDefinition:
    difficulty: Difficulty
    label: str


DIFFICULTIES = (
    DifficultyDefinition(Difficulty.SIMPLE, "简单"),
    DifficultyDefinition(Difficulty.MEDIUM, "中等"),
    DifficultyDefinition(Difficulty.HARD, "困难"),
)
