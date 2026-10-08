"""Information-limited player and AI observation projection."""

from __future__ import annotations

from dataclasses import dataclass

from xssgkpz.core.state import GamePhase, GameState, ZoneKind


@dataclass(frozen=True, slots=True)
class PublicActionRecord:
    """A public action summary with no physical card id or private context."""

    turn_number: int
    actor_id: str
    kind_id: str
    target_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservedPlayer:
    player_id: str
    seat_index: int
    control: str
    hero_id: str
    identity: str | None
    hp: int
    max_hp: int
    alive: bool
    hand_count: int
    own_hand_card_ids: tuple[str, ...] | None
    equipment_card_ids: tuple[str, ...]
    judgment_card_ids: tuple[str, ...]
    public_marks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationView:
    viewer_id: str
    mode_id: str
    phase: GamePhase
    current_player_id: str | None
    turn_number: int
    players: tuple[ObservedPlayer, ...]
    discard_card_ids: tuple[str, ...]
    draw_pile_count: int
    legal_action_ids: tuple[str, ...] = ()
    public_actions: tuple[PublicActionRecord, ...] = ()
    distances_from_viewer: tuple[tuple[str, int], ...] = ()


def make_observation(
    state: GameState,
    viewer_id: str,
    *,
    public_actions: tuple[PublicActionRecord, ...] = (),
    distances_from_viewer: tuple[tuple[str, int], ...] = (),
) -> ObservationView:
    viewer = next((player for player in state.players if player.player_id == viewer_id), None)
    if viewer is None:
        raise ValueError(f"unknown viewer: {viewer_id}")

    observed_players: list[ObservedPlayer] = []
    for player in state.players:
        hand = state.zones[player.hand_zone_id].card_ids
        equipment = state.zones[player.equipment_zone_id].card_ids
        judgment = state.zones[player.judgment_zone_id].card_ids
        own_hand = tuple(hand) if player.player_id == viewer_id else None
        visible_identity = (
            player.identity
            if player.player_id == viewer_id or player.identity_public or not player.alive
            else None
        )
        observed_players.append(ObservedPlayer(
            player_id=player.player_id,
            seat_index=player.seat_index,
            control=player.control.value,
            hero_id=player.hero_id,
            identity=visible_identity,
            hp=player.hp,
            max_hp=player.max_hp,
            alive=player.alive,
            hand_count=len(hand),
            own_hand_card_ids=own_hand,
            equipment_card_ids=tuple(equipment),
            judgment_card_ids=tuple(judgment),
            public_marks=tuple(sorted(player.public_marks)),
        ))

    draw_zone = next((zone for zone in state.zones.values() if zone.kind is ZoneKind.DRAW_PILE), None)
    discard_zone = next((zone for zone in state.zones.values() if zone.kind is ZoneKind.DISCARD_PILE), None)
    return ObservationView(
        viewer_id=viewer_id,
        mode_id=state.mode_id,
        phase=state.phase,
        current_player_id=state.current_player_id,
        turn_number=state.turn_number,
        players=tuple(observed_players),
        discard_card_ids=tuple(discard_zone.card_ids) if discard_zone else (),
        draw_pile_count=len(draw_zone.card_ids) if draw_zone else 0,
        public_actions=public_actions,
        distances_from_viewer=distances_from_viewer,
    )
