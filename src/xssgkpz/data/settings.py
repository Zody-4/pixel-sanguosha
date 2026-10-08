"""Versioned settings shape; values mirror the confirmed settings scope."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class WindowMode(StrEnum):
    WINDOWED = "windowed"
    BORDERLESS_FULLSCREEN = "borderless_fullscreen"


class AiDisplaySpeed(StrEnum):
    NORMAL = "normal"
    FAST = "fast"
    INSTANT = "instant"


class SkillAnimation(StrEnum):
    NORMAL = "normal"
    FAST = "fast"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class Settings:
    schema_version: int = 1
    window_mode: WindowMode = WindowMode.WINDOWED
    resolution_width: int = 1280
    resolution_height: int = 720
    ui_scale: float = 1.0
    ai_display_speed: AiDisplaySpeed = AiDisplaySpeed.NORMAL
    skill_animation: SkillAnimation = SkillAnimation.NORMAL
    audio_scale_version: int = 2
    music_volume: float = 0.30
    voice_volume: float = 0.50
    effects_volume: float = 0.50
    card_details_enabled: bool = True
    card_details_size: float = 1.0
    card_details_x: float = 537 / 1672
    card_details_y: float = 232 / 941
    card_details_layouts: tuple[tuple[str, float, float, float], ...] = ()

    def detail_layout(self, mode: str) -> tuple[float, float, float]:
        return next(((size, x, y) for key, size, x, y in self.card_details_layouts if key == mode),
                    (self.card_details_size, self.card_details_x, self.card_details_y))

    def __post_init__(self) -> None:
        seen = set()
        for mode, size, x, y in self.card_details_layouts:
            if mode not in {"duel", "two_heroes", "five_player_identity"} or mode in seen:
                raise ValueError("invalid or duplicate details mode")
            seen.add(mode)
            if not isfinite(size) or not .5 <= size <= 2.5 or any(not isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
                raise ValueError("invalid details layout")
        if any(not isfinite(value) or not 0 <= value <= 1
               for value in (self.music_volume, self.voice_volume, self.effects_volume)):
            raise ValueError("audio volumes must be finite fractions between 0 and 1")
        if self.schema_version < 1:
            raise ValueError("settings schema_version must be positive")
        if self.resolution_width < 1 or self.resolution_height < 1:
            raise ValueError("resolution dimensions must be positive")
        if self.ui_scale <= 0:
            raise ValueError("ui_scale must be positive")
        if not isinstance(self.card_details_enabled, bool):
            raise ValueError("card_details_enabled must be boolean")
        if not isfinite(self.card_details_size) or not 0.5 <= self.card_details_size <= 2.5:
            raise ValueError("card_details_size must be between 0.5 and 2.5")
        if any(not isfinite(value) or not 0 <= value <= 1
               for value in (self.card_details_x, self.card_details_y)):
            raise ValueError("card_details positions must be finite fractions")
