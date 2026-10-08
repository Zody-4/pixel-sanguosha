"""Shared non-battle surfaces, using the approved tent and v12 ornaments."""

from xssgkpz.resource_paths import RESOURCE_ROOT

import pygame
from xssgkpz.menu_buttons import MenuButtons

ROOT = RESOURCE_ROOT
INK = (238, 220, 183)
MUTED = (180, 169, 143)
GOLD = (221, 186, 123)
PANEL = (20, 33, 27)
FACTION = {"蜀": (117, 200, 143), "魏": (126, 173, 225),
           "吴": (220, 139, 121), "群": (173, 145, 204)}


class ShellTheme:
    def __init__(self) -> None:
        self.buttons = MenuButtons()
        self.skin = None
        self.background = None
        self.backdrops = {}
        self.plates = {}

    def backdrop(self, surface: pygame.Surface) -> None:
        if self.background is None:
            self.background = pygame.image.load(ROOT / "assets/runtime/shell/command-pavilion-secondary-v01.png").convert()
        size = surface.get_size()
        if size not in self.backdrops:
            self.backdrops[size] = pygame.transform.smoothscale(self.background, size)
        surface.blit(self.backdrops[size], (0, 0))

    def plate(self, surface: pygame.Surface, rect: pygame.Rect, kind="panel", *,
              selected=False, disabled=False, hover=False) -> None:
        if kind in {"button", "primary"}:
            self.buttons.draw(surface, rect, primary=kind == "primary", selected=selected, enabled=not disabled, hover=hover)
            return
        if kind == "panel":
            key = (rect.size, "quiet_pavilion_panel")
            art = self.plates.get(key)
            if art is None:
                art = pygame.Surface(rect.size, pygame.SRCALPHA)
                art.fill((15, 29, 24, 242))
                edge = max(1, round(min(rect.size) / 220))
                pygame.draw.rect(art, (116, 88, 46), art.get_rect(), edge)
                pygame.draw.rect(art, (44, 48, 34), art.get_rect().inflate(-6,-6), 1)
                self.plates[key] = art
            surface.blit(art, rect)
            return
        if self.skin is None:
            self.skin = pygame.image.load(ROOT / "assets/runtime/battle/v12/skin.png").convert_alpha()
        key = (rect.size, kind, selected, disabled, hover)
        art = self.plates.get(key)
        if art is None:
            sources = {"panel": (285, 737, 187, 90), "heading": (18, 1, 539, 61),
                       "button": (1181, 594, 163, 59), "primary": (1011, 594, 159, 59)}
            source = pygame.Rect(sources[kind])
            edge = min(12 if kind == "heading" else 8, max(1, rect.w // 3), max(1, rect.h // 3))
            # Keep the original corners; stretch only edges and the quiet centre.
            xs = (source.x, source.x + edge, source.right - edge, source.right)
            ys = (source.y, source.y + edge, source.bottom - edge, source.bottom)
            dx = (0, edge, rect.w - edge, rect.w)
            dy = (0, edge, rect.h - edge, rect.h)
            art = pygame.Surface(rect.size, pygame.SRCALPHA)
            for row in range(3):
                for col in range(3):
                    part = self.skin.subsurface((xs[col], ys[row], xs[col+1]-xs[col], ys[row+1]-ys[row]))
                    target = pygame.Rect(dx[col], dy[row], dx[col+1]-dx[col], dy[row+1]-dy[row])
                    art.blit(pygame.transform.smoothscale(part, target.size), target)
            if kind in {"button", "primary"}:
                corner = min(7, edge)
                mask = pygame.Surface(rect.size, pygame.SRCALPHA)
                w, h = rect.size
                points = ((corner, 0), (w-corner, 0), (w, corner), (w, h-corner),
                          (w-corner, h), (corner, h), (0, h-corner), (0, corner))
                pygame.draw.polygon(mask, (255, 255, 255), points)
                art.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                if selected:
                    pygame.draw.polygon(art, GOLD, points, 2)
                if disabled:
                    art.fill((145, 145, 145, 255), special_flags=pygame.BLEND_RGBA_MULT)
                elif hover:
                    art.fill((16, 13, 7, 0), special_flags=pygame.BLEND_RGBA_ADD)
            self.plates[key] = art
        surface.blit(art, rect)
