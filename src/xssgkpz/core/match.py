"""Full 25-hero, 108-card match construction for the Stage 2 ruleset."""

from __future__ import annotations

from dataclasses import dataclass

from xssgkpz.core.random_stream import FixedSeedRandom
from xssgkpz.core.state import CardInstance, ControlType, GamePhase, GameState, PlayerState, Visibility, ZoneKind, ZoneState
from xssgkpz.data.cards import CARD_DEFINITIONS
from xssgkpz.data.heroes import HEROES, HERO_BY_ID
from xssgkpz.data.modes import Difficulty, Identity, MODE_BY_ID


HERO_IDS = tuple(hero.hero_id for hero in HEROES)


@dataclass(frozen=True, slots=True)
class MatchRoster:
    mode_id: str
    difficulty: Difficulty
    player_hero_id: str
    hero_ids: tuple[str, ...]
    identities: tuple[tuple[str, str], ...]
    seed: int


def random_hero_candidates(random_stream: FixedSeedRandom) -> tuple[str, str, str]:
    candidates = list(HERO_IDS)
    random_stream.shuffle(candidates)
    return tuple(candidates[:3])  # type: ignore[return-value]


def resolve_roster(
    *, mode_id: str, player_hero_id: str, seed: int,
    player_identity: Identity | None = None,
    difficulty: Difficulty = Difficulty.SIMPLE,
) -> MatchRoster:
    if mode_id not in MODE_BY_ID:
        raise ValueError(f"unknown mode: {mode_id}")
    if player_hero_id not in HERO_IDS:
        raise ValueError("unknown hero")
    mode = MODE_BY_ID[mode_id]
    random_stream = FixedSeedRandom(seed)
    remaining = [hero_id for hero_id in HERO_IDS if hero_id != player_hero_id]
    random_stream.shuffle(remaining)
    hero_ids = (player_hero_id, *remaining[:mode.ai_count])
    player_ids = ("P1", *(f"AI{index}" for index in range(1, mode.ai_count + 1)))
    if mode_id == "five_player_identity":
        roles = [identity for identity, count in (
            (Identity.LORD, 1), (Identity.LOYALIST, 1),
            (Identity.REBEL, 2), (Identity.TURNCOAT, 1),
        ) for _ in range(count)]
        if player_identity is not None:
            if player_identity not in roles:
                raise ValueError("identity is not available in this mode")
            roles.remove(player_identity)
            random_stream.shuffle(roles)
            identity_by_player = {"P1": player_identity}
            identity_by_player.update(zip(player_ids[1:], roles, strict=True))
        else:
            random_stream.shuffle(roles)
            identity_by_player = dict(zip(player_ids, roles, strict=True))
    elif mode_id == "two_heroes":
        identity_by_player = {"P1": "player_side", "AI1": "ai_side", "AI2": "ai_side"}
    else:
        identity_by_player = {player_id: "opposing_side" for player_id in player_ids}
    identities = tuple((player_id, str(identity.value if isinstance(identity, Identity) else identity))
                       for player_id, identity in identity_by_player.items())
    return MatchRoster(mode_id, difficulty, player_hero_id, tuple(hero_ids), identities, seed)


def create_match(
    roster: MatchRoster,
    *, human_player_ids: frozenset[str] = frozenset({"P1"}),
) -> GameState:
    mode = MODE_BY_ID[roster.mode_id]
    random_stream = FixedSeedRandom(roster.seed)
    player_ids = ["P1", *(f"AI{index}" for index in range(1, mode.ai_count + 1))]
    if roster.mode_id == "five_player_identity":
        random_stream.shuffle(player_ids)
    identity_by_player = dict(roster.identities)
    players: list[PlayerState] = []
    canonical_ids = ["P1", *(f"AI{index}" for index in range(1, mode.ai_count + 1))]
    for seat_index, player_id in enumerate(player_ids):
        hero_id = roster.hero_ids[canonical_ids.index(player_id)]
        identity = identity_by_player[player_id]
        hero = HERO_BY_ID[hero_id]
        max_hp = hero.base_hp
        if roster.mode_id == "two_heroes" and player_id == "P1":
            max_hp += 1
        if roster.mode_id == "five_player_identity" and identity == Identity.LORD.value:
            max_hp += 1
        players.append(PlayerState(
            player_id=player_id, seat_index=seat_index,
            control=ControlType.HUMAN if player_id in human_player_ids else ControlType.AI,
            hero_id=hero_id, identity=identity,
            identity_public=(roster.mode_id == "two_heroes" or identity == Identity.LORD.value),
            hp=max_hp, max_hp=max_hp,
            hand_zone_id=f"{player_id}.hand",
            equipment_zone_id=f"{player_id}.equipment",
            judgment_zone_id=f"{player_id}.judgment",
        ))
    zones: dict[str, ZoneState] = {
        "draw_pile": ZoneState("draw_pile", ZoneKind.DRAW_PILE),
        "discard_pile": ZoneState("discard_pile", ZoneKind.DISCARD_PILE),
        "resolving": ZoneState("resolving", ZoneKind.RESOLVING),
        "response": ZoneState("response", ZoneKind.RESPONSE),
    }
    for player in players:
        zones[player.hand_zone_id] = ZoneState(player.hand_zone_id, ZoneKind.HAND, player.player_id)
        zones[player.equipment_zone_id] = ZoneState(player.equipment_zone_id, ZoneKind.EQUIPMENT, player.player_id)
        zones[player.judgment_zone_id] = ZoneState(player.judgment_zone_id, ZoneKind.JUDGMENT, player.player_id)
    cards = {
        f"card:{definition.definition_id}": CardInstance(
            card_id=f"card:{definition.definition_id}", definition_id=definition.definition_id,
            zone_id="draw_pile", visibility=Visibility.HIDDEN,
        ) for definition in CARD_DEFINITIONS
    }
    zones["draw_pile"].card_ids.extend(cards)
    random_stream.shuffle(zones["draw_pile"].card_ids)
    if roster.mode_id == "duel":
        current_player_id = random_stream.choice(tuple(player_ids))
    elif roster.mode_id == "two_heroes":
        current_player_id = "P1"
    else:
        current_player_id = next(player.player_id for player in players if player.identity == Identity.LORD.value)
    state = GameState(
        mode_id=roster.mode_id, players=players, cards=cards, zones=zones,
        random_stream=random_stream, phase=GamePhase.PREPARATION,
        current_player_id=current_player_id,
    )
    for player in players:
        hand_count = 5 if roster.mode_id == "two_heroes" and player.player_id == "P1" else 4
        for _ in range(hand_count):
            card_id = zones["draw_pile"].card_ids.pop(0)
            state.cards[card_id].zone_id = player.hand_zone_id
            state.cards[card_id].owner_id = player.player_id
            state.cards[card_id].controller_id = player.player_id
            state.cards[card_id].visibility = Visibility.OWNER_ONLY
            zones[player.hand_zone_id].card_ids.append(card_id)
    return state
