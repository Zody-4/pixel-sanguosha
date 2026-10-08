"""Create one physical instance of each canonical card definition."""

from __future__ import annotations

from xssgkpz.core.random_stream import FixedSeedRandom
from xssgkpz.core.state import CardInstance, Visibility, ZoneKind, ZoneState
from xssgkpz.data.cards import CARD_DEFINITIONS


def create_standard_deck(
    random_stream: FixedSeedRandom,
    *,
    shuffle: bool = True,
) -> tuple[dict[str, CardInstance], ZoneState]:
    draw_zone_id = "draw_pile"
    cards = {
        f"card:{definition.definition_id}": CardInstance(
            card_id=f"card:{definition.definition_id}",
            definition_id=definition.definition_id,
            zone_id=draw_zone_id,
            visibility=Visibility.HIDDEN,
        )
        for definition in CARD_DEFINITIONS
    }
    card_ids = list(cards)
    if shuffle:
        random_stream.shuffle(card_ids)
    draw_pile = ZoneState(
        zone_id=draw_zone_id,
        kind=ZoneKind.DRAW_PILE,
        card_ids=card_ids,
    )
    return cards, draw_pile

