"""Base in-memory state contracts. Rule resolution is intentionally absent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from xssgkpz.core.random_stream import FixedSeedRandom, RandomStreamSnapshot


class ControlType(StrEnum):
    HUMAN = "human"
    AI = "ai"


class GamePhase(StrEnum):
    PREPARATION = "preparation"
    JUDGMENT = "judgment"
    DRAW = "draw"
    PLAY = "play"
    DISCARD = "discard"
    END = "end"


class ZoneKind(StrEnum):
    DRAW_PILE = "draw_pile"
    DISCARD_PILE = "discard_pile"
    HAND = "hand"
    EQUIPMENT = "equipment"
    JUDGMENT = "judgment"
    RESOLVING = "resolving"
    RESPONSE = "response"
    TEMPORARY = "temporary"


class Visibility(StrEnum):
    PUBLIC = "public"
    OWNER_ONLY = "owner_only"
    HIDDEN = "hidden"


@dataclass(slots=True)
class CardInstance:
    card_id: str
    definition_id: str
    zone_id: str
    owner_id: str | None = None
    controller_id: str | None = None
    visibility: Visibility = Visibility.HIDDEN
    temporary_marks: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ZoneState:
    zone_id: str
    kind: ZoneKind
    owner_id: str | None = None
    card_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlayerState:
    player_id: str
    seat_index: int
    control: ControlType
    hero_id: str
    identity: str | None
    identity_public: bool
    hp: int
    max_hp: int
    alive: bool = True
    hand_zone_id: str = ""
    equipment_zone_id: str = ""
    judgment_zone_id: str = ""
    public_marks: set[str] = field(default_factory=set)


@dataclass(slots=True)
class EventFrame:
    event_id: str
    event_type: str
    actor_id: str | None = None
    target_ids: tuple[str, ...] = ()
    status: str = "pending"
    resume_cursor: int = 0
    parent_event_id: str | None = None


@dataclass(slots=True)
class GameState:
    mode_id: str
    players: list[PlayerState]
    cards: dict[str, CardInstance]
    zones: dict[str, ZoneState]
    random_stream: FixedSeedRandom
    phase: GamePhase = GamePhase.PREPARATION
    current_player_id: str | None = None
    turn_number: int = 0
    event_stack: list[EventFrame] = field(default_factory=list)
    result: str | None = None
    end_reason: str | None = None
    state_version: int = 1


@dataclass(frozen=True, slots=True)
class ZoneSnapshot:
    zone_id: str
    kind: ZoneKind
    owner_id: str | None
    card_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    player_id: str
    seat_index: int
    control: ControlType
    hero_id: str
    identity: str | None
    identity_public: bool
    hp: int
    max_hp: int
    alive: bool
    hand_zone_id: str
    equipment_zone_id: str
    judgment_zone_id: str
    public_marks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    event_id: str
    event_type: str
    actor_id: str | None
    target_ids: tuple[str, ...]
    status: str
    resume_cursor: int
    parent_event_id: str | None


@dataclass(frozen=True, slots=True)
class CardInstanceSnapshot:
    card_id: str
    definition_id: str
    zone_id: str
    owner_id: str | None
    controller_id: str | None
    visibility: Visibility
    temporary_marks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GameStateSnapshot:
    state_version: int
    mode_id: str
    phase: GamePhase
    current_player_id: str | None
    turn_number: int
    players: tuple[PlayerSnapshot, ...]
    cards: tuple[CardInstanceSnapshot, ...]
    zones: tuple[ZoneSnapshot, ...]
    event_stack: tuple[EventSnapshot, ...]
    random_state: RandomStreamSnapshot
    result: str | None
    end_reason: str | None


def assert_card_zone_invariant(state: GameState) -> None:
    """Every registered physical card must be referenced by exactly one zone."""
    seen: dict[str, int] = {}
    for zone_id, zone in state.zones.items():
        if zone.zone_id != zone_id:
            raise ValueError(f"zone key mismatch: {zone_id}")
        for card_id in zone.card_ids:
            if card_id not in state.cards:
                raise ValueError(f"unknown card in zone {zone_id}: {card_id}")
            if state.cards[card_id].zone_id != zone_id:
                raise ValueError(f"card {card_id} zone field does not match {zone_id}")
            seen[card_id] = seen.get(card_id, 0) + 1
    missing = set(state.cards) - set(seen)
    repeated = {card_id for card_id, count in seen.items() if count != 1}
    if missing or repeated:
        raise ValueError(f"card-zone invariant failed; missing={sorted(missing)}, repeated={sorted(repeated)}")
    for player in state.players:
        for zone_id in (player.hand_zone_id, player.equipment_zone_id, player.judgment_zone_id):
            if zone_id not in state.zones:
                raise ValueError(f"player {player.player_id} references unknown zone {zone_id}")


def snapshot_game_state(state: GameState) -> GameStateSnapshot:
    return GameStateSnapshot(
        state_version=state.state_version,
        mode_id=state.mode_id,
        phase=state.phase,
        current_player_id=state.current_player_id,
        turn_number=state.turn_number,
        players=tuple(PlayerSnapshot(
            player_id=player.player_id, seat_index=player.seat_index,
            control=player.control, hero_id=player.hero_id,
            identity=player.identity, identity_public=player.identity_public,
            hp=player.hp, max_hp=player.max_hp, alive=player.alive,
            hand_zone_id=player.hand_zone_id,
            equipment_zone_id=player.equipment_zone_id,
            judgment_zone_id=player.judgment_zone_id,
            public_marks=tuple(sorted(player.public_marks)),
        ) for player in state.players),
        cards=tuple(CardInstanceSnapshot(
            card_id=card.card_id,
            definition_id=card.definition_id,
            zone_id=card.zone_id,
            owner_id=card.owner_id,
            controller_id=card.controller_id,
            visibility=card.visibility,
            temporary_marks=tuple(sorted(card.temporary_marks)),
        ) for card in sorted(state.cards.values(), key=lambda item: item.card_id)),
        zones=tuple(ZoneSnapshot(zone.zone_id, zone.kind, zone.owner_id, tuple(zone.card_ids))
                    for zone in sorted(state.zones.values(), key=lambda item: item.zone_id)),
        event_stack=tuple(EventSnapshot(
            event.event_id, event.event_type, event.actor_id, event.target_ids,
            event.status, event.resume_cursor, event.parent_event_id,
        ) for event in state.event_stack),
        random_state=state.random_stream.snapshot(),
        result=state.result,
        end_reason=state.end_reason,
    )
