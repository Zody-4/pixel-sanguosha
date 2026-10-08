"""Compose approved v06 layers using the actual card definition."""
from collections import OrderedDict
from xssgkpz.resource_paths import RESOURCE_ROOT

import pygame

from xssgkpz.data.cards import CardDefinition

ROOT = RESOURCE_ROOT / "assets/runtime/cards/v06/layers"


class CardArt:
    def __init__(self):
        self.cache = OrderedDict()
        self.composed = OrderedDict()

    def surface(self, card: CardDefinition, size: tuple[int, int]) -> pygame.Surface:
        key = (card.kind_id, card.suit.value, card.rank, size)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        source_key = key[:3]
        composed = self.composed.get(source_key)
        if composed is None:
            paths = (
                ROOT / "底图" / f"{card.kind_id}.png",
                ROOT / "文字" / f"{card.kind_id}.png",
                ROOT / "花色" / f"{card.suit.value}.png",
                ROOT / "点数" / f"{card.suit.value}_{card.rank}.png",
            )
            composed = pygame.image.load(str(paths[0])).convert_alpha()
            for path in paths[1:]:
                composed.blit(pygame.image.load(str(path)).convert_alpha(), (0, 0))
            self.composed[source_key] = composed
            # Keep original layers out of the animation loop without retaining all 108 masters.
            while len(self.composed) > 12:
                self.composed.popitem(last=False)
        self.composed.move_to_end(source_key)
        result = pygame.transform.smoothscale(composed, size)
        self.cache[key] = result
        if len(self.cache) > 160:
            self.cache.popitem(last=False)
        return result
