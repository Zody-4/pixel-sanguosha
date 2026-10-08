"""The approved v12 table, driven by engine observations and legal intents."""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections import OrderedDict
from math import hypot, cos, pi, sin
from xssgkpz.resource_paths import RESOURCE_ROOT
from typing import TYPE_CHECKING

import pygame
from xssgkpz.fonts import ui_font

from xssgkpz.core.gameplay import PresentationEvent
from xssgkpz.data.assets import ASSET_BY_KEY
from xssgkpz.data.cards import CARD_BY_ID, CARD_KIND_BY_NAME
from xssgkpz.data.heroes import HERO_BY_ID, SKILL_BY_ID
from xssgkpz.data.modes import MODE_BY_ID
from xssgkpz.data.settings import AiDisplaySpeed, Settings, SkillAnimation
from xssgkpz.persistence import save_settings

if TYPE_CHECKING:
    from xssgkpz.app import Stage1App

ROOT = RESOURCE_ROOT
STAGE = (1672, 941)
INK = (238, 220, 183)
GOLD = (221, 186, 123)
MUTED = (180, 169, 143)
FACTION = {"蜀": (117, 200, 143), "魏": (126, 173, 225),
           "吴": (220, 139, 121), "群": (173, 145, 204)}
SLOTS = ("weapon", "armor", "horse_plus_one", "horse_minus_one", "judgment")


@dataclass(frozen=True)
class Seat:
    frame: tuple[int, int, int, int]
    equipment: tuple[int, int, int, int]
    identity: tuple[int, int, int, int]
    name_y: int
    side: str = "bottom"

    @property
    def port(self) -> tuple[float, float]:
        x, y, w, h = self.frame
        if self.side == "right":
            return x + w + 4, y + h / 2
        if self.side == "left":
            return x - 4, y + h / 2
        return x + w / 2, y + h + 8

    @property
    def hand_box(self) -> pygame.Rect:
        x, _, w, _ = self.frame
        return pygame.Rect(x + (w - 112) // 2, self.name_y - 52, 112, 44)


UPPER_LEFT = Seat((434, 37, 242, 242), (682, 51, 88, 224), (443, 42, 103, 32), 249)
UPPER_RIGHT = Seat((977, 36, 240, 251), (883, 54, 87, 232), (1106, 41, 103, 32), 257)
LEFT = Seat((58, 209, 235, 263), (300, 238, 90, 234), (67, 214, 103, 32), 442, "right")
RIGHT = Seat((1391, 211, 226, 258), (1296, 225, 86, 244), (1505, 216, 103, 32), 439, "left")
DUEL = Seat((714, 37, 242, 242), (962, 51, 88, 224), (723, 42, 103, 32), 249)


class BattleUI:
    def __init__(self) -> None:
        self.surface = pygame.Surface(STAGE)
        self.art: dict[str, pygame.Surface] = {}
        self.panels: dict[tuple, pygame.Surface] = {}
        self.fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self.fallback_fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self.portraits: dict[tuple, pygame.Surface] = {}
        self.background: pygame.Surface | None = None
        self.scaled_art = OrderedDict()
        self.text_art = OrderedDict()
        self.text_scale = 1.0
        self.render_scale = 1.0
        self.viewport = pygame.Rect(0, 0, 1280, 720)
        self.reset()

    def reset(self) -> None:
        self.selected_card: str | None = None
        self.selected_skill: str | None = None
        self.costs: list[str] = []
        self.targets: list[str] = []
        self.hand_scroll = 0.0
        self.max_scroll = 0.0
        self.choice_scroll = 0
        self.log_open = False
        self.details_open = False
        self.notice = ""
        self.hover_card: str | None = None
        self.hover_hand: str | None = None
        self.focus_card: str | None = None
        self.hand_ids: tuple[str, ...] = ()
        self.hand_rects: dict[str, pygame.Rect] = {}
        self.hand_motion = {}
        self.frame_delta = 0
        self.origins: dict[str, tuple[float, float]] = {}
        self.seats: dict[str, Seat] = {}
        self.actions = ()
        self._actions_key = None
        self._request = None
        self.event: PresentationEvent | None = None
        self.event_elapsed = 0.0
        self.event_duration = 0.0
        self.last_tick = pygame.time.get_ticks()
        self.main_card: str | None = None
        self.reply_cards: tuple[str, ...] = ()
        self.main_name: str | None = None
        self.event_origin = (835.0, 780.0)
        self.idle_elapsed = 0.0
        self.mouse = (-1.0, -1.0)

    def font(self, size: int, value: str = "", bold=False) -> pygame.font.Font:
        size = max(6, round(size * self.text_scale))
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = ui_font("microsoftyahei", size, bold=bold)
        if value and (any(char in "‹›→↑↓" for char in value)
                      or any(metric is None for metric in self.fonts[key].metrics(value))):
            if key not in self.fallback_fonts:
                self.fallback_fonts[key] = ui_font("microsoftyahei", size, bold=bold)
            return self.fallback_fonts[key]
        return self.fonts[key]

    def image(self, name: str) -> pygame.Surface:
        if name not in self.art:
            self.art[name] = pygame.image.load(ROOT / ASSET_BY_KEY[f"battle.v12.{name}"].relative_path).convert_alpha()
        return self.art[name]

    def _background(self) -> pygame.Surface:
        if self.background is None:
            bg = self.image("skin-header-clean-20261002").copy()
            seats = self.image("skin-seat-clean-20261002").copy()
            pygame.draw.rect(seats, (0, 0, 0, 0), (18, 1, 539, 61))
            bg.blit(seats, (0, 0))
            skin = self.image("skin").copy()
            for box in ((340, 62, 355, 251), (990, 62, 410, 251),
                        (32, 285, 334, 278), (1308, 285, 330, 278), (18, 1, 539, 61)):
                pygame.draw.rect(skin, (0, 0, 0, 0), box)
            bg.blit(skin, (0, 0))
            # The approved background already contains the two button plates.
            # Text and hit areas share their exact positions; no texture patch is needed.
            self.background = bg
        return self.background

    def panel(self, box, source=(285, 737, 187, 90), insets=(8, 8, 8, 8),
              tint=None, seat=False, edges=False) -> None:
        logical_box = pygame.Rect(box)
        box = self.pixel_rect(logical_box)
        key = (box.size, source, insets, tint, seat, edges)
        result = self.panels.get(key)
        if result is None:
            result = pygame.Surface(box.size, pygame.SRCALPHA)
            top, right, bottom, left = insets
            x, y, w, h = source
            sx, sy = (x, x + left, x + w - right, x + w), (y, y + top + (5 if seat else 0), y + h - bottom, y + h)
            pl, pr, pt, pb = (round(v * self.render_scale) for v in (left, right, top, bottom))
            dx, dy = (0, pl, box.w - pr, box.w), (0, pt, box.h - pb, box.h)
            caps = ((1402, 308, 18, 18), (454, 78, 131, 18), (671, 78, 18, 18))
            for row in range(3):
                for col in range(3):
                    if edges and row == col == 1:
                        continue
                    rect = caps[col] if seat and row == 0 else (sx[col], sy[row], sx[col + 1] - sx[col], sy[row + 1] - sy[row])
                    part = self.image("skin").subsurface(rect).copy()
                    if tint and (row != 1 or col != 1):
                        part = pygame.transform.grayscale(part)
                        part.fill((*tint,255), special_flags=pygame.BLEND_RGBA_MULT)
                        part.blit(part.copy(), (0,0), special_flags=pygame.BLEND_RGB_ADD)
                    target = pygame.Rect(dx[col], dy[row], dx[col + 1] - dx[col], dy[row + 1] - dy[row])
                    result.blit(pygame.transform.smoothscale(part, target.size), target)
            # The source image is a full table. Cut the chamfered silhouette rather
            # than importing its rectangular background corners into every plate.
            if source in {(348, 68, 104, 32), (1478, 291, 126, 39)}:
                corner = max(1, round(8 * self.render_scale))
                self._chamfer(result, corner)
            elif source in {(1011, 594, 159, 59), (1181, 594, 163, 59), (1355, 594, 200, 59)}:
                self._chamfer(result, max(1, round(8 * self.render_scale)))
            self.panels[key] = result
        self.surface.blit(result, box)

    @staticmethod
    def _chamfer(surface, corner):
        w, h = surface.get_size()
        mask = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(mask, (255, 255, 255, 255), ((corner, 0), (w-corner, 0), (w, corner), (w, h-corner), (w-corner, h), (corner, h), (0, h-corner), (0, corner)))
        surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    def text(self, value, position, size=20, color=INK, center=False, max_width=None, bold=False) -> pygame.Rect:
        value = str(value).replace("−", "-")
        font = self.font(size, value, bold)
        if max_width:
            while size > 12 and font.size(value)[0] > max_width:
                size -= 1
                font = self.font(size, value, bold)
        native_font = self.font(size * self.render_scale, value, bold)
        key = (value, native_font, tuple(color))
        rendered = self.text_art.get(key)
        if rendered is None:
            rendered = native_font.render(value, True, color)
            self.text_art[key] = rendered
            if len(self.text_art) > 512:
                self.text_art.popitem(last=False)
        else:
            self.text_art.move_to_end(key)
        pixel_position = self.pixel_point(position)
        rect = rendered.get_rect(center=pixel_position) if center else rendered.get_rect(topleft=pixel_position)
        self.surface.blit(rendered, rect)
        return rect

    def wrap(self, value: str, box, size=20, color=INK) -> None:
        box = pygame.Rect(box)
        line, y = "", box.y
        for char in value + "\n":
            if char == "\n" or self.font(size).size(line + char)[0] > box.w:
                if y + self.font(size).get_linesize() > box.bottom:
                    self.text("…", (box.right - size, box.bottom - size), size, color)
                    return
                self.text(line, (box.x, y), size, color)
                y += self.font(size).get_linesize() + 3
                line = "" if char == "\n" else char
            else:
                line += char

    def pixel_point(self, point):
        return round(point[0] * self.render_scale), round(point[1] * self.render_scale)

    def pixel_rect(self, box):
        box = pygame.Rect(box)
        return pygame.Rect(*self.pixel_point(box.topleft), max(1, round(box.w * self.render_scale)), max(1, round(box.h * self.render_scale)))

    def draw_rect(self, color, box, width=0):
        pygame.draw.rect(self.surface, color, self.pixel_rect(box), max(1, round(width * self.render_scale)) if width else 0)

    def draw_circle(self, color, center, radius):
        pygame.draw.circle(self.surface, color, self.pixel_point(center), max(1, round(radius * self.render_scale)))

    def draw_polygon(self, color, points):
        pygame.draw.polygon(self.surface, color, [self.pixel_point(p) for p in points])

    def blit(self, image, position, size=None, special_flags=0):
        size = size or image.get_size()
        target_size = (max(1, round(size[0] * self.render_scale)), max(1, round(size[1] * self.render_scale)))
        if image.get_size() != target_size:
            key = (image, target_size)
            cached = self.scaled_art.get(key)
            if cached is None:
                cached = pygame.transform.smoothscale(image, target_size)
                self.scaled_art[key] = cached
                if len(self.scaled_art) > 64:
                    self.scaled_art.popitem(last=False)
            else:
                self.scaled_art.move_to_end(key)
            image = cached
        self.surface.blit(image, self.pixel_point(position), special_flags=special_flags)

    def canvas_box(self, box) -> pygame.Rect:
        box = pygame.Rect(box)
        return pygame.Rect(round(self.viewport.x + box.x * self.viewport.w / STAGE[0]),
                           round(self.viewport.y + box.y * self.viewport.h / STAGE[1]),
                           max(1, round(box.w * self.viewport.w / STAGE[0])),
                           max(1, round(box.h * self.viewport.h / STAGE[1])))

    def stage_point(self, point) -> tuple[float, float]:
        return ((point[0] - self.viewport.x) * STAGE[0] / self.viewport.w,
                (point[1] - self.viewport.y) * STAGE[1] / self.viewport.h)

    def hit(self, app: Stage1App, box, action, enabled=True) -> None:
        app._register_battle_hit(self.canvas_box(box), action, enabled)

    def button(self, app, box, label, action, enabled=True, selected=False, primary=False, baked=False, plate=False) -> None:
        box = pygame.Rect(box)
        hover = app.mouse_canvas_position is not None and self.canvas_box(box).collidepoint(app.mouse_canvas_position)
        control = action[0] in {"battle_confirm", "answer_prompt", "battle_cancel", "end_play", "battle_pass"}
        app.shell_theme.buttons.draw(self.surface, self.pixel_rect(box), primary=primary,
                                     selected=selected, enabled=enabled, hover=hover, strong_hover=control)
        app.shell_theme.buttons.label(self.surface, self.pixel_rect(box), label,
                                       (24 if baked else 22) * self.render_scale * self.text_scale,
                                       (255, 235, 182) if control and enabled and hover else INK if enabled else (136, 133, 109))
        self.hit(app, box, action, enabled)

    def card(self, app, card_id, box) -> None:
        definition = CARD_BY_ID[app.engine.state.cards[card_id].definition_id]
        box = pygame.Rect(box)
        native_box = self.pixel_rect(box)
        self.surface.blit(app.card_art.surface(definition, native_box.size), native_box)

    def portrait(self, hero_id, box, player=False, hurt_elapsed=-1) -> None:
        box = pygame.Rect(box)
        native_box = self.pixel_rect(box)
        key = (hero_id, native_box.w, player)
        image = self.portraits.get(key)
        if image is None:
            source = pygame.image.load(ROOT / ASSET_BY_KEY[HERO_BY_ID[hero_id].asset_key].relative_path).convert_alpha()
            height = max(1, round(source.get_height() * native_box.w / source.get_width()))
            image = pygame.transform.smoothscale(source, (native_box.w, height))
            self.portraits[key] = image
        old_clip = self.surface.get_clip()
        self.surface.set_clip(native_box)
        offset = round(4 * sin(hurt_elapsed * .045) * max(0, 1 - hurt_elapsed / 420) * self.render_scale) if hurt_elapsed >= 0 else 0
        position = (native_box.x + offset, native_box.bottom - image.get_height() if player else native_box.y - round(8 * self.render_scale))
        self.surface.blit(image, position)
        if 0 <= hurt_elapsed < 320:
            flash = image.copy()
            flash.fill((90, 0, 0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            flash.set_alpha(round(105 * sin(pi * hurt_elapsed / 320)))
            self.surface.blit(flash, position)
        self.surface.set_clip(old_clip)

    def _hurt_elapsed(self, app, player_id) -> int:
        cue = app.engine.presentation_event
        if (app.settings.skill_animation is not SkillAnimation.OFF and cue
                and cue.kind == "damage" and player_id in cue.target_ids):
            return self.event_elapsed
        return -1

    def _health(self, x, y, hp, max_hp) -> None:
        for i in range(max_hp):
            name = "gray" if i >= hp else "red" if hp == 1 else "green"
            self.blit(self.image("health-" + name), (x + i * 20 - 7, y - 3), (32, 32), special_flags=pygame.BLEND_RGB_ADD)

    def _layout(self, observation) -> None:
        ordered = sorted(observation.players, key=lambda p: p.seat_index)
        first = next(i for i, p in enumerate(ordered) if p.player_id == "P1")
        opponents = (ordered[first + 1:] + ordered[:first])
        places = (DUEL,) if len(opponents) == 1 else (UPPER_LEFT, UPPER_RIGHT) if len(opponents) == 2 else (LEFT, UPPER_LEFT, UPPER_RIGHT, RIGHT)
        self.seats = {p.player_id: seat for p, seat in zip(opponents, places)}

    def port(self, player_id) -> tuple[float, float]:
        return (835, 640) if player_id == "P1" else self.seats[player_id].port

    def origin(self, player_id, card_id=None) -> tuple[float, float]:
        if player_id == "P1":
            return self.origins.get(card_id, (835, 780))
        if player_id in self.seats:
            box = self.seats[player_id].hand_box
            return box.x + 28, box.centery
        return 835, 432

    def _base_candidates(self):
        if self.selected_skill:
            return tuple(a for a in self.actions if a.intent.skill_id == self.selected_skill)
        return tuple(a for a in self.actions if self.selected_card and a.intent.card_id == self.selected_card and not a.intent.skill_id)

    def candidates(self):
        return tuple(a for a in self._base_candidates()
                     if all(c in a.intent.cost_card_ids for c in self.costs)
                     and tuple(a.intent.target_ids[:len(self.targets)]) == tuple(self.targets))

    def ready_action(self):
        return next((a for a in self.candidates()
                     if set(a.intent.cost_card_ids) == set(self.costs)
                     and a.intent.target_ids == tuple(self.targets)), None)

    def eligible_targets(self):
        return {a.intent.target_ids[len(self.targets)] for a in self.candidates()
                if len(a.intent.target_ids) > len(self.targets)}

    def _request_cards(self, request):
        return {option.value for option in request.options if isinstance(option.value, str) and option.value in self.hand_ids}

    def cancel(self) -> bool:
        if self.details_open:
            self.details_open = False
        elif self.log_open:
            self.log_open = False
        elif self.targets:
            self.targets.clear()
        elif self.costs:
            self.costs.clear()
        elif self.selected_card or self.selected_skill:
            self.selected_card = self.selected_skill = None
            self.notice = ""
        else:
            return False
        return True

    def _tick(self, app) -> None:
        now = pygame.time.get_ticks()
        delta = min(100, max(0, now - self.last_tick))
        self.frame_delta = delta
        self.last_tick = now
        engine = app.engine
        cue = engine.presentation_event
        if cue and (self.event is None or self.event.serial != cue.serial):
            self.event = cue
            self.event_elapsed = 0
            self.event_origin = self.origin(cue.origin_actor_id or cue.actor_id, cue.card_ids[0] if cue.card_ids else None)
            if cue.kind in {"judgement", "judgement_replace"}:
                self.main_card = cue.card_ids[0]
                self.main_name = None
                self.reply_cards = ()
            if cue.kind == "play":
                self.main_card = cue.card_ids[0] if cue.card_ids else None
                self.main_name = cue.effective_name
                self.reply_cards = cue.card_ids[1:]
            elif cue.kind in {"response", "negate", "rescue"}:
                self.reply_cards = cue.card_ids
            elif cue.kind == "equip":
                self.main_card = cue.card_ids[0]
            elif cue.kind == "result" and self.main_card:
                # Discarded cards remain visible through the collection animation.
                # Installed equipment is already represented in its real slot.
                if engine.state.zones[engine.state.cards[self.main_card].zone_id].kind.value == "equipment":
                    self.main_card = None
            if cue.kind == "negate" and cue.reference_card_id:
                self.main_card = cue.reference_card_id
            self.event_duration = (1250 if cue.kind in {"judgement", "judgement_replace"} else 1460 if cue.kind == "result" else 950 if cue.kind == "retarget"
                                   else 820 if cue.kind == "equip" else 700 if cue.kind == "damage"
                                   else 1510 if cue.kind == "response"
                                   else 1850 if cue.kind == "negate"
                                   else 1470 if cue.target_ids else 780)
            self.idle_elapsed = 0
        paused = app.pause_open or app.confirm_kind or self.details_open or app.page != "game" or not app.window_focused
        if not paused:
            speed = 1
            if cue and cue.actor_id != "P1":
                speed = (1 if app.effective_ai_display_speed is AiDisplaySpeed.NORMAL else
                         2 if app.effective_ai_display_speed is AiDisplaySpeed.FAST else 12)
            if app.settings.skill_animation is SkillAnimation.FAST:
                speed *= 2
            elif app.settings.skill_animation is SkillAnimation.OFF:
                speed = 12
            self.event_elapsed += delta * speed
            if not engine.display_waiting and not engine.pending_request:
                self.idle_elapsed += delta * speed
                if self.idle_elapsed > 460:
                    self.main_card = None
                    self.reply_cards = ()
        if engine.pending_request is not self._request:
            self._request = engine.pending_request
            app.selected_choices.clear()
            self.choice_scroll = 0
            self.selected_card = self.selected_skill = None
            self.targets.clear()
            self.costs.clear()
            self.notice = ""
            if self._request:
                reference = dict(self._request.context).get("trick_card_id")
                if reference:
                    self.main_card = reference
                    kind_id = dict(self._request.context).get("trick_kind_id")
                    self.main_name = next((k.name for k in CARD_KIND_BY_NAME.values() if k.kind_id == kind_id), None)

    @property
    def animation_done(self) -> bool:
        return self.event is None or self.event_elapsed >= self.event_duration

    def draw(self, app: Stage1App) -> None:
        engine = app.engine
        if engine is None:
            return
        self.text_scale = app.settings.ui_scale
        ratio = min(app.screen.get_width() / STAGE[0], app.screen.get_height() / STAGE[1])
        self.viewport = pygame.Rect(0, 0, round(STAGE[0] * ratio), round(STAGE[1] * ratio))
        self.viewport.center = app.screen.get_rect().center
        self.render_scale = self.viewport.w / STAGE[0]
        if self.surface.get_size() != self.viewport.size:
            self.surface = pygame.Surface(self.viewport.size)
        self.mouse = self.stage_point(app.mouse_canvas_position) if app.mouse_canvas_position else (-1, -1)
        observation = engine.observation_for("P1")
        self._layout(observation)
        self._tick(app)
        player = next(p for p in observation.players if p.player_id == "P1")
        dealing = app.deal_started_ms is not None
        if dealing:
            from xssgkpz.battle_transitions import deal_arrived_count
            player = replace(player, hand_count=deal_arrived_count(app, "P1"))
        self.hand_ids = player.own_hand_card_ids or ()
        if self.focus_card not in self.hand_ids:
            self.focus_card = None
        action_key = (observation.turn_number, observation.current_player_id, observation.phase,
                      tuple((p.player_id, p.hp, p.alive, p.hand_count, p.equipment_card_ids, p.judgment_card_ids) for p in observation.players),
                      self.hand_ids, engine.is_human_turn)
        if action_key != self._actions_key:
            self.actions = engine.available_actions("P1") if engine.is_human_turn else ()
            self._actions_key = action_key
        if self.selected_card and self.selected_card not in self.hand_ids:
            self.selected_card = None
            self.targets.clear()
        self.blit(self._background(), (0, 0))
        self.hover_card = None
        active = next((HERO_BY_ID[p.hero_id].name for p in observation.players if p.player_id == observation.current_player_id), "结算")
        phase = {"play": "出牌阶段", "draw": "摸牌阶段", "discard": "弃牌阶段", "judgment": "判定阶段", "preparation": "准备阶段", "end": "结束阶段"}.get(observation.phase.value, "结算")
        mode_label = {"duel": "斗将", "two_heroes": "力敌双雄", "five_player_identity": "五人身份局"}[observation.mode_id]
        pieces = ((mode_label, 20, MUTED), (active + "回合", 23, INK), (phase, 20, GOLD))
        if dealing:
            pieces = ((mode_label, 20, MUTED), ("开局发牌", 23, INK), ("准备中", 20, GOLD))
        heading_width = sum(self.font(size, bold=size == 23).size(value)[0] for value, size, _ in pieces) + 88
        heading_width = min(410, heading_width)
        self.panel((23, 7, heading_width, 49), (23, 7, 526, 49), (18, 18, 18, 18))
        x = 47
        available = heading_width - 88
        natural = sum(self.font(size, bold=size == 23).size(value)[0] for value, size, _ in pieces)
        for i, (value, size, color) in enumerate(pieces):
            width = round(self.font(size, bold=size == 23).size(value)[0] * min(1, available / natural))
            self.text(value, (x + width / 2, 31), size, color, True, width, bold=i == 1)
            x += width
            if i < 2:
                self.draw_rect((123, 104, 69), (x + 10, 20, 1, 23))
                x += 24
        self.button(app, (1381, 12, 127, 47), "日志", ("battle_log",), baked=True)
        self.button(app, (1530, 12, 125, 47), "暂停", ("pause",), baked=True)
        draw_count = observation.draw_pile_count
        if dealing:
            draw_count += sum(p.hand_count - deal_arrived_count(app, p.player_id) for p in observation.players)
        self.text(f"牌堆 {draw_count}  ·  弃牌 {len(observation.discard_card_ids)}", (694, 572), 16, MUTED)
        for opponent in observation.players:
            if opponent.player_id != "P1":
                if dealing:
                    opponent = replace(opponent, hand_count=deal_arrived_count(app, opponent.player_id))
                self._opponent(app, opponent, observation)
        self._player(app, player, observation)
        if not dealing:
            self._exchange(app)
            self._hand(app)
        self._controls(app)
        self._skills(app, player)
        if engine.pending_request:
            self._choices(app, engine.pending_request)
        inspected = self.hover_card
        if inspected and app.settings.card_details_enabled and not app.pause_open and not app.confirm_kind and not self.log_open and not self.details_open and not engine.display_waiting and not getattr(app, "guided_tutorial", None):
            self._inspector(app, inspected)
        if self.log_open:
            self._logs(app)
        if self.details_open:
            self._details_settings(app)
        if getattr(app, "guided_tutorial", None) and not (app.pause_open or app.confirm_kind or self.details_open or self.log_open):
            self._practice_guidance(app)
        app.screen.blit(self.surface, self.viewport)

    def _practice_guidance(self, app) -> None:
        lesson = app.guided_tutorial
        lesson.observe(app)
        # Multi-seat tables reserve the corner above the right-hand player.
        request = app.engine.pending_request
        compact = len(app.engine.state.players) > 2 or bool(request and request.kind in {"dismantle_area", "dismantle_visible_card"})
        box = pygame.Rect(1225, 60, 415, 145) if compact else pygame.Rect(1060, 330, 580, 230)
        self.panel(box)
        self.hit(app, box, ("battle_noop",))
        self.text("教学练习 · 不计战绩", (1220, 31), 20, MUTED, True)
        x, y, width = box.x + 14, box.y + 10, box.w - 28
        self.text(f"{lesson.title} {lesson.index + 1}/{len(lesson.steps)} · {lesson.step.title}",
                  (x, y), 19 if compact else 24, GOLD, max_width=width)
        text = lesson.message or lesson.instruction_for(app)
        self.wrap(text, (x, y + 27 if compact else y + 42, width, 65 if compact else 100), size=16 if compact else 24)
        by, bh = box.bottom - (36 if compact else 58), 28 if compact else 40
        bw = 108 if compact else 145
        self.button(app, (x, by, bw, bh), "重看提示", ("practice_hint",))
        self.button(app, (x + bw + 8, by, bw, bh), "退出教学", ("practice_exit",))
        if lesson.completed:
            label = "完成本段" if lesson.index + 1 == len(lesson.steps) else "下一练习"
            self.button(app, (x + 2 * (bw + 8), by, width - 2 * (bw + 8), bh), label, ("practice_next",), primary=True)
            return
        highlight = None
        if hasattr(lesson.step, "goal"):
            request = app.engine.pending_request
            if lesson.resolution_pass(request):
                highlight = pygame.Rect(1355, 594, 200, 59)
            elif request and request.min_choices <= len(app.selected_choices) <= request.max_choices:
                highlight = pygame.Rect(1011, 594, 159, 59)
            elif request:
                highlight = self.hand_rects.get(lesson.focus_card)
                if highlight is None:
                    # Equipment/area choices use the ordinary response panel.
                    highlight = pygame.Rect(520, 326, 610, 244)
            elif lesson.step.skill_id:
                if self.selected_skill == lesson.step.skill_id:
                    highlight = pygame.Rect(1011, 594, 159, 59)
                else:
                    hero = HERO_BY_ID[app.engine._player("P1").hero_id]
                    skills = [sid.split(".")[-1] for sid in hero.skill_ids]
                    if lesson.step.skill_id in skills:
                        highlight = pygame.Rect(36 + skills.index(lesson.step.skill_id) * 107, 914, 103, 26)
            elif self.selected_card != lesson.focus_card:
                highlight = self.hand_rects.get(lesson.focus_card)
            elif lesson.step.goal == "distance" or lesson.target_id in self.eligible_targets():
                seat = self.seats.get(lesson.target_id)
                highlight = pygame.Rect(seat.frame) if seat else None
            elif self.ready_action():
                highlight = pygame.Rect(1011, 594, 159, 59)
            if highlight and not app.engine.display_waiting:
                self.draw_rect(GOLD, highlight.inflate(6, 6), 2)
            return
        if lesson.index in {0, 4, 7, 8, 9, 11}:
            request = app.engine.pending_request
            if request and request.min_choices <= len(app.selected_choices) <= request.max_choices:
                highlight = pygame.Rect(1011, 594, 159, 59)
            elif lesson.index == 8 and self.selected_card == lesson.focus_card:
                highlight = pygame.Rect(1011, 594, 159, 59)
            else:
                cid = (next((c for c in self.hand_ids if c not in
                             {o.value for o in request.options if o.choice_id in app.selected_choices}), None)
                       if lesson.index == 11 and request else lesson.focus_card)
                highlight = self.hand_rects.get(cid)
        elif lesson.index in {1, 5}:
            seat = self.seats.get("AI1")
            highlight = pygame.Rect(seat.frame) if seat else None
        elif lesson.index in {2, 3}:
            highlight = pygame.Rect(1181, 594, 163, 59)
        elif lesson.index == 6:
            highlight = pygame.Rect(1011, 594, 159, 59)
        elif lesson.index == 10:
            highlight = pygame.Rect(1355, 594, 200, 59)
        if highlight and not app.engine.display_waiting:
            self.draw_rect(GOLD, highlight.inflate(6, 6), 2)

    def _identity(self, app, p) -> str:
        if app.engine.state.mode_id == "duel":
            return "你方" if p.player_id == "P1" else "对手"
        if app.spectator_identity_reveal:
            raw = next(item for item in app.engine.state.players if item.player_id == p.player_id)
            return app._identity_label(raw.identity)
        return app._identity_label(p.identity) if p.identity else "未知"

    def _target(self, app, player_id, box) -> None:
        request = app.engine.pending_request
        options = tuple(o for o in request.options if o.category == "target" and o.value == player_id) if request else ()
        eligible = bool(options) or player_id in self.eligible_targets()
        selected = player_id in self.targets or any(o.choice_id in app.selected_choices for o in options)
        if eligible or selected:
            self.draw_rect(GOLD, pygame.Rect(box).inflate(-3, -3), 3 if selected else 1)
        if options:
            self.hit(app, box, ("battle_option", options[0].choice_id))
        elif eligible or selected:
            self.hit(app, box, ("battle_target", player_id))
        else:
            lesson = getattr(app, "guided_tutorial", None)
            if (lesson and getattr(lesson.step, "goal", None) == "distance"
                    and player_id == lesson.target_id and self.selected_card == lesson.focus_card):
                # Teach an ineligible click without adding it to legal targets.
                self.hit(app, box, ("battle_target", player_id))

    def _opponent(self, app, p, observation) -> None:
        seat = self.seats[p.player_id]
        frame = pygame.Rect(seat.frame)
        hero = HERO_BY_ID[p.hero_id]
        self.panel(frame, (358, 78, 245, 150), (18, 18, 36, 18), FACTION[hero.faction.value], seat=True)
        portrait_box = pygame.Rect(frame.x + 7, frame.y + 17, frame.w - 14, frame.h - 51)
        self.portrait(p.hero_id, portrait_box, hurt_elapsed=self._hurt_elapsed(app, p.player_id))
        self._target(app, p.player_id, portrait_box)
        if observation.current_player_id == p.player_id:
            self.draw_rect(GOLD, frame.inflate(4, 4), 2)
        if not p.alive:
            shade = pygame.Surface(self.pixel_rect(frame).size, pygame.SRCALPHA)
            shade.fill((8, 8, 8, 150))
            self.surface.blit(shade, self.pixel_point(frame.topleft))
            self.text("阵亡", frame.center, 28, MUTED, True)
        self.panel(seat.identity, (348, 68, 104, 32))
        self.text(self._identity(app, p), pygame.Rect(seat.identity).center, 18, center=True)
        self.text(f"{hero.name} {p.hp}/{p.max_hp}", (frame.x + 12, seat.name_y), 20, max_width=frame.w - 28 - p.max_hp * 20)
        self._health(frame.right - 14 - p.max_hp * 20, seat.name_y, p.hp, p.max_hp)
        badge_left = seat.side == "left" or seat == UPPER_RIGHT
        bx = frame.x + 6 if badge_left else frame.right - 33
        self._badge(bx, frame.y + 6, hero.faction.value)
        box = seat.hand_box
        self.panel(box)
        for i in range(min(3, p.hand_count)):
            self.blit(self.image("back"), (box.x + 10 + i * 3, box.y + 4), (26, 36))
        self.text(f"{p.hand_count}张", (box.x + 51, box.y + 10), 20, max_width=53)
        self._equipment(app, p, pygame.Rect(seat.equipment))
        if app.spectator_hand_reveal and box.collidepoint(self.mouse):
            raw = next(item for item in app.engine.state.players if item.player_id == p.player_id)
            ids = app.engine.state.zones[raw.hand_zone_id].card_ids
            names = "、".join(CARD_BY_ID[app.engine.state.cards[cid].definition_id].name for cid in ids) or "无手牌"
            self.panel((493, 474, 695, 99))
            self.wrap(hero.name + " · " + names, (512, 489, 656, 74), 17)

    def _badge(self, x, y, faction) -> None:
        colors = {"蜀": (24, 62, 43), "魏": (34, 56, 81), "吴": (81, 41, 33), "群": (60, 44, 74)}
        size = max(1, round(26.6 * self.render_scale))
        key = ('badge', faction, size)
        art = self.panels.get(key)
        if art is None:
            art = pygame.Surface((76, 76), pygame.SRCALPHA)
            outer = [(a*2,b*2) for a,b in ((5,1),(33,1),(37,5),(37,33),(33,37),(5,37),(1,33),(1,5))]
            inner = [(a*2,b*2) for a,b in ((7,4),(31,4),(34,7),(34,31),(31,34),(7,34),(4,31),(4,7))]
            pygame.draw.polygon(art, colors[faction], outer)
            pygame.draw.polygon(art, (181,153,98), outer, 2)
            pygame.draw.polygon(art, (121,107,70), inner, 1)
            font = ui_font('kaiti',52,bold=True)
            glyph = font.render(faction, True, (243,223,178))
            art.blit(glyph,glyph.get_rect(center=(38,38)))
            art = pygame.transform.smoothscale(art,(size,size))
            self.panels[key] = art
        self.surface.blit(art,self.pixel_point((x,y)))

    def _player(self, app, p, observation) -> None:
        hero = HERO_BY_ID[p.hero_id]
        self.panel((36, 653, 390, 173), (36, 653, 390, 173), (18, 18, 18, 18), FACTION[hero.faction.value], edges=True)
        self.portrait(p.hero_id, (-60, 550, 350, 391), player=True, hurt_elapsed=self._hurt_elapsed(app, p.player_id))
        self.panel((269, 634, 104, 32), (348, 68, 104, 32))
        self.text(self._identity(app, p), (321, 650), 18, center=True)
        self._badge(393, 659, hero.faction.value)
        self.text(f"{hero.name} {p.hp}/{p.max_hp}", (247, 675), 22)
        self._health(291, 704, p.hp, p.max_hp)
        self.panel((285, 737, 187, 90))
        for i in range(min(3, p.hand_count)):
            self.blit(self.image("back"), (313 + i * 5, 756 - i * 3), (30, 42))
        self.text(f"手牌 {p.hand_count}张", (366, 768), 20)
        self._equipment(app, p, pygame.Rect(169, 825, 304, 85), horizontal=True)
        self._target(app, p.player_id, (247, 671, 179, 63))
        if not p.alive:
            self.text("已阵亡 · 旁观", (257, 732), 20, GOLD)

    def equipment_box(self, player_id, slot) -> pygame.Rect:
        if player_id == "P1":
            spots = ((185, 849, 32, 45), (260, 849, 32, 45), (333, 871, 20, 28),
                     (359, 871, 20, 28), (410, 849, 32, 45))
            return pygame.Rect(spots[SLOTS.index(slot)])
        box = pygame.Rect(self.seats[player_id].equipment)
        step = (box.h - 8) / 4
        if slot in {"horse_plus_one", "horse_minus_one"}:
            return pygame.Rect(box.x + box.w / 2 + (-27 if slot == "horse_plus_one" else 9), box.y + 32 + step * 2, 18, 25)
        row = {"weapon": 0, "armor": 1, "judgment": 3}[slot]
        return pygame.Rect(box.x + (box.w - 26) / 2, box.y + 22 + step * row, 26, 36)

    def _equipment(self, app, p, box, horizontal=False) -> None:
        self.panel(box)
        for i, label in enumerate(("武器", "防具", "坐骑", "判定")):
            point = (box.x + 12 + i * 75, box.y) if horizontal else (box.centerx, box.y + 5 + i * (box.h - 8) // 4)
            self.text(label, point, 18 if horizontal else 15, center=not horizontal)
        mapped: dict[str, list[str]] = {slot: [] for slot in SLOTS}
        for cid in p.equipment_card_ids:
            kind = CARD_KIND_BY_NAME[CARD_BY_ID[app.engine.state.cards[cid].definition_id].name]
            if kind.subtype in mapped:
                mapped[kind.subtype].append(cid)
        mapped["judgment"] = list(p.judgment_card_ids)
        for slot, ids in mapped.items():
            rect = self.equipment_box(p.player_id, slot)
            if slot.startswith("horse"):
                self.text("+1" if slot == "horse_plus_one" else "−1", (rect.x, rect.y - 13), 13)
            if not ids:
                self.text("空" if not slot.startswith("horse") else "—", rect.center, 14, MUTED, True)
            for i, cid in enumerate(ids):
                shifted = rect.move(i * 8, 0)
                self.card(app, cid, shifted)
                if shifted.collidepoint(self.mouse):
                    self.hover_card = cid
                request = app.engine.pending_request
                options = tuple(o for o in request.options if o.value == cid) if request else ()
                if options:
                    self.hit(app, shifted, ("battle_option", options[0].choice_id))
                    if any(o.choice_id in app.selected_choices for o in options):
                        self.draw_rect(GOLD, shifted, 2)
                elif self.selected_skill and any(cid in a.intent.cost_card_ids for a in self._base_candidates()):
                    self.hit(app, shifted, ("battle_card", cid))
                    if cid in self.costs:
                        self.draw_rect(GOLD, shifted, 2)

    def _hand(self, app) -> None:
        count = len(self.hand_ids)
        step = max(48, min(150, (1143 - 145) / (count - 1))) if count > 1 else 150
        self.max_scroll = max(0, 145 + max(0, count - 1) * step - 1143)
        self.hand_scroll = min(self.hand_scroll, self.max_scroll)
        clip = pygame.Rect(497, 653, 1143, 241)
        rects = {cid: pygame.Rect(497 + i * step - self.hand_scroll, 691, 145, 203) for i, cid in enumerate(self.hand_ids)}
        previous = {}
        for cid, rect in rects.items():
            x, y = self.hand_motion.get(cid, (rect.x, rect.y))
            resting = pygame.Rect(round(x), rect.y, rect.w, rect.h)
            previous[cid] = resting.union(pygame.Rect(round(x), round(y), rect.w, rect.h))
        top_hover = next((cid for cid in reversed(self.hand_ids) if previous[cid].collidepoint(self.mouse) and clip.collidepoint(self.mouse)), None)
        self.hover_hand = top_hover
        if top_hover:
            self.hover_card = top_hover
        request = app.engine.pending_request
        old_clip = self.surface.get_clip()
        self.surface.set_clip(self.pixel_rect(clip))
        self.hand_rects = {}
        busy = app.engine.display_waiting or app.pause_open or bool(app.confirm_kind)
        for cid, rect in rects.items():
            options = tuple(o for o in request.options if o.value == cid) if request else ()
            selected = cid == self.selected_card or cid in self.costs or any(o.choice_id in app.selected_choices for o in options)
            target_y = rect.y + (-38 if cid in {top_hover, self.focus_card} and not busy else -21 if selected else 0)
            px, py = self.hand_motion.get(cid, (float(rect.x), float(rect.y)))
            amount = 1 - 2.718281828 ** (-self.frame_delta / 55)
            px += (rect.x - px) * amount
            py += (target_y - py) * amount
            self.hand_motion[cid] = (px, py)
            lifted = pygame.Rect(round(px), round(py), rect.w, rect.h)
            self.card(app, cid, lifted)
            usable = bool(options) if request else any(a.intent.card_id == cid and not a.intent.skill_id for a in self.actions)
            if self.selected_skill:
                usable = any(cid in a.intent.cost_card_ids for a in self._base_candidates())
            if selected:
                self.draw_rect(GOLD, lifted, 3)
                self.text("已选", (lifted.x + 4, lifted.y + 171), 14, GOLD)
            elif not usable:
                self.draw_circle((71, 52, 38), (lifted.x + 15, lifted.bottom - 15), 10)
                self.text("×", (lifted.x + 15, lifted.bottom - 15), 16, MUTED, True)
            self.hand_rects[cid] = lifted
            self.origins[cid] = lifted.center
            # Preserve the lower hover footprint vertically, without turning the
            # horizontal animation gap into an invisible clickable card.
            visible = lifted.union(pygame.Rect(lifted.x, rect.y, rect.w, rect.h)).clip(clip)
            if visible.w > 0:
                self.hit(app, visible, ("battle_card", cid), not busy)
        self.surface.set_clip(old_clip)
        self.hand_motion = {cid: self.hand_motion[cid] for cid in self.hand_ids}
        if self.max_scroll:
            self.button(app, (497, 907, 42, 28), "‹", ("battle_scroll", -1))
            self.button(app, (1598, 907, 42, 28), "›", ("battle_scroll", 1))
            first = int(self.hand_scroll / step) + 1
            last = min(count, int((self.hand_scroll + 1143 - 145) / step) + 1)
            self.text(f"{first}–{last} / {count}张", (1069, 921), 16, MUTED, True)

    def _controls(self, app) -> None:
        engine, request = app.engine, app.engine.pending_request
        response_heading = ""
        if request:
            task = self.notice or f"{request.title} · {request.message}"
            context = dict(request.context)
            if not self.notice:
                if request.kind == "rescue":
                    target = next((p for p in engine.state.players if p.player_id == context.get('target_id')), None)
                    if target:
                        task = f"{HERO_BY_ID[target.hero_id].name}体力{target.hp} · 选桃后确认，或放弃响应"
                elif request.kind == "nullification":
                    task = request.message + ("已抵消 · 无懈恢复效果" if context.get('cancelled') else "选无懈抵消，或放弃响应")
                elif request.kind == "guicai":
                    task = "选一张手牌后确认改判，或放弃响应保留原判定"
                elif request.kind == "discard":
                    task = f"须弃{request.min_choices}张 · 已选{len(app.selected_choices)}张，选足后确认"
            count = len(app.selected_choices)
            ready = request.min_choices <= count <= request.max_choices
            if request.kind in {"axe_payment", "ganglie"}:
                ready = app.selected_choices in ({"pass"}, {"damage"}) or count == 2 and all(c.startswith("discard:") for c in app.selected_choices)
            label, action = "确认响应", ("answer_prompt",)
            cancel_enabled = bool(app.selected_choices)
            pass_option = next((o for o in request.options if o.choice_id == "pass"), None)
            last_label = "放弃响应" if pass_option else "不选择并确认" if request.min_choices == 0 else "等待选择"
            last_action = ("battle_pass",)
            last_enabled = bool(pass_option) or request.min_choices == 0
            if request.kind == "rescue":
                response_heading = "轮到你：是否使用【桃】救援？"
            elif request.kind == "nullification":
                response_heading = "轮到你：是否使用【无懈可击】？"
            elif request.kind == "guicai":
                response_heading = "轮到你：是否发动【鬼才】更换判定牌？"
            elif request.kind == "discard":
                response_heading = f"轮到你弃牌：需要{request.min_choices}张，已选{count}张"
            if response_heading and not any(o.choice_id != "pass" for o in request.options):
                task = "没有可用的响应牌 · 点放弃响应继续"
        else:
            candidates, ready_action = self.candidates(), self.ready_action()
            task = (self.notice or "选择一张手牌或技能，再确认出牌") if engine.is_human_turn else "正在结算"
            if self.selected_card or self.selected_skill:
                if ready_action:
                    task = ready_action.label + (" → " + "、".join(HERO_BY_ID[engine._player(t).hero_id].name for t in self.targets) if self.targets else "")
                elif candidates:
                    missing_cost = any(len(a.intent.cost_card_ids) > len(self.costs) for a in candidates)
                    task = "请选择技能使用的牌" if missing_cost else f"请选择第{len(self.targets) + 1}名合法目标"
            if engine.presentation_event:
                cue = engine.presentation_event
                if cue.kind == "damage":
                    names = "、".join(HERO_BY_ID[engine._player(t).hero_id].name for t in cue.target_ids)
                    task = names + "受到伤害"
                else:
                    task = cue.label
            label, action = "出牌", ("battle_confirm",)
            ready = ready_action is not None and engine.is_human_turn
            cancel_enabled = bool(self.selected_card or self.selected_skill or self.targets)
            last_label, last_action, last_enabled = "结束阶段", ("end_play",), engine.is_human_turn
        if app.deal_started_ms is not None:
            task = "起手牌分发中" if pygame.time.get_ticks() - app.deal_started_ms < 2450 else "准备开战"
            ready = cancel_enabled = last_enabled = False
        enabled = not engine.display_waiting and not app.pause_open and not app.confirm_kind
        controls = (
            ((1011, 594, 159, 59), bool(ready and enabled),
             "确认当前选择" if request else "使用所选牌或技能",
             f"请按要求选牌（已选{len(app.selected_choices)}张）" if request else task if self.selected_card or self.selected_skill else "请先选择手牌或技能"),
            ((1181, 594, 163, 59), bool(cancel_enabled and enabled), "取消当前选择，重新选择", "当前没有可取消的选择"),
            ((1355, 594, 200, 59), bool(last_enabled and enabled),
             "放弃本次响应，继续结算" if request and pass_option else "不选牌，确认本次响应" if request else "结束出牌阶段，进入后续阶段",
             "必须按要求选择，不能跳过" if request else "现在不是你的出牌阶段"),
        )
        for box, clickable, description, reason in controls:
            if app.mouse_canvas_position is not None and self.canvas_box(box).collidepoint(app.mouse_canvas_position):
                if not enabled:
                    reason = "请等待当前演出或结算结束"
                elif app.deal_started_ms is not None:
                    reason = "请等待发牌完成"
                task = ("可点击 · " + description) if clickable else ("暂不可点击 · " + reason)
                break
        self.panel((481, 589, 517, 64), (481, 589, 517, 64), (18, 18, 18, 18))
        self._routes(app)
        if response_heading and enabled and app.deal_started_ms is None:
            self.text(response_heading, (747, 607), 21, GOLD, center=True, max_width=477, bold=True)
            self.text(task, (747, 634), 17, INK, center=True, max_width=477)
        elif self.font(22, task).size(task)[0] <= 477:
            self.text(task, (747, 621), 22, center=True)
        else:
            lines, line = [], ""
            for char in task:
                if self.font(18, line + char).size(line + char)[0] > 477:
                    lines.append(line)
                    line = char
                else:
                    line += char
            lines.append(line)
            for i, line in enumerate(lines[:2]):
                self.text(line + ("…" if i == 1 and len(lines) > 2 else ""), (747, 610 + i * 23), 18, center=True, max_width=477)
        self.button(app, (1011, 594, 159, 59), label, action, bool(ready and enabled), primary=True, baked=True)
        self.button(app, (1181, 594, 163, 59), "取消选择" if request else "取消", ("battle_cancel",), bool(cancel_enabled and enabled), baked=True)
        self.button(app, (1355, 594, 200, 59), last_label, last_action, bool(last_enabled and enabled), baked=True)

    def _skills(self, app, p) -> None:
        hero = HERO_BY_ID[p.hero_id]
        skills = [(sid.split(".")[-1], SKILL_BY_ID[sid].name) for sid in hero.skill_ids]
        if any(a.intent.skill_id == "serpent_spear" for a in self.actions):
            skills.append(("serpent_spear", "丈八蛇矛"))
        for i, (skill_id, name) in enumerate(skills):
            box = pygame.Rect(36 + i * 107, 914, 103, 26)
            legal = any(a.intent.skill_id == skill_id for a in self.actions)
            self.button(app, box, name, ("battle_skill", skill_id), legal, self.selected_skill == skill_id, plate=True)
            if box.collidepoint(self.mouse):
                skill = next((SKILL_BY_ID[sid] for sid in hero.skill_ids if sid.endswith("." + skill_id)), None)
                if skill:
                    self.panel((45, 453, 400, 118))
                    status = "可以发动" if legal else "当前不是你的出牌阶段" if not app.engine.is_human_turn else "条件未满足、次数已用或须等待触发时机"
                    self.text(status, (60,463), 15, GOLD)
                    self.wrap(skill.description, (60, 488, 370, 78), 16)

    def _choices(self, app, request) -> None:
        # All engine choices remain available, including ordered/multi-card skills.
        player = next(p for p in app.engine.observation_for("P1").players if p.player_id == "P1")
        visible_card_ids = {*self.hand_ids, *player.equipment_card_ids}
        options = tuple(o for o in request.options if o.choice_id != "pass"
                        and o.category != "target"
                        and not (isinstance(o.value, str) and o.value in visible_card_ids
                                 and sum(other.value == o.value for other in request.options) == 1))
        if not options:
            return
        visible_count = 5
        self.choice_scroll = min(self.choice_scroll, max(0, len(options) - visible_count))
        box = pygame.Rect(520, 326, 610, 244)
        self.panel(box)
        self.text(f"{request.title}  ·  已选{len(app.selected_choices)} / {request.max_choices}", (539, 336), 18, GOLD)
        context = dict(request.context)
        if request.kind == "nullification":
            self.text("当前原效果：" + ("已抵消" if context.get("cancelled") else "待生效"), (882, 337), 16, MUTED)
        public_cards = all(isinstance(o.value, str) and o.value in app.engine.state.cards
                           and app.engine.state.cards[o.value].visibility.value == "public" for o in options)
        if public_cards and len(options) <= visible_count:
            for i, option in enumerate(options):
                rect = pygame.Rect(546 + i * 115, 369, 98, 137)
                self.card(app, option.value, rect)
                self.hit(app, rect, ("battle_option", option.choice_id))
                if option.choice_id in app.selected_choices:
                    self.draw_rect(GOLD, rect, 3)
                if rect.collidepoint(self.mouse):
                    self.hover_card = option.value
                self.text(str(i + 1), (rect.centerx, rect.bottom + 18), 18, MUTED, True)
            return
        for i, option in enumerate(options[self.choice_scroll:self.choice_scroll + visible_count]):
            self.button(app, (539, 369 + i * 36, 544, 32), option.label,
                        ("battle_option", option.choice_id), selected=option.choice_id in app.selected_choices)
        if len(options) > visible_count:
            self.button(app, (1088, 371, 27, 58), "↑", ("battle_choice_scroll", -visible_count), self.choice_scroll > 0)
            self.button(app, (1088, 490, 27, 58), "↓", ("battle_choice_scroll", visible_count), self.choice_scroll + visible_count < len(options))

    def _inspector(self, app, cid) -> None:
        settings = app.settings
        definition = CARD_BY_ID[app.engine.state.cards[cid].definition_id]
        kind = CARD_KIND_BY_NAME[definition.name]
        scale, position_x, position_y = settings.detail_layout(app.engine.state.mode_id)
        w, h = round(605 * scale), round(336 * scale)
        x = min(round(position_x * STAGE[0]), STAGE[0] - w)
        y = min(round(position_y * STAGE[1]), STAGE[1] - h)
        self.card(app, cid, (x, y, round(240 * scale), h))
        panel = pygame.Rect(x + round(260 * scale), y + round(44 * scale), round(330 * scale), round(248 * scale))
        self.draw_rect((22, 37, 29), panel)
        self.draw_rect((123, 110, 75), panel, 1)
        self.text(kind.name, (panel.x + 18 * scale, panel.y + 17 * scale), round(25 * scale), GOLD)
        self.wrap(kind.display_summary, (panel.x + 18 * scale, panel.y + 60 * scale, panel.w - 36 * scale, panel.h - 120 * scale), max(14, round(19 * scale)))
        own = cid in self.hand_ids
        availability = "区域内的公开牌" if not own else "本阶段可使用，选择后点击确认" if any(a.intent.card_id == cid for a in self.actions) else "当前无合法主动出牌动作；响应或技能窗口以提示为准"
        if own and not any(a.intent.card_id == cid and not a.intent.skill_id for a in self.actions):
            player = next(p for p in app.engine.observation_for("P1").players if p.player_id == "P1")
            if definition.name == "桃" and player.hp >= player.max_hp:
                availability = "当前体力已满；濒死救援时按窗口提示使用"
            elif definition.name in {"闪", "无懈可击"}:
                availability = "此牌用于响应窗口，不能主动出牌"
            elif definition.name == "杀" and app.engine.is_human_turn:
                availability = ("本阶段【杀】次数已用完，可结束阶段或选择可用技能" if not app.engine._can_use_kill("P1")
                                else "当前没有满足距离与技能限制的合法目标")
        if app.engine.pending_request and own:
            availability = "此牌可用于当前选择" if cid in self._request_cards(app.engine.pending_request) else "此牌不在当前窗口的合法选项中"
        self.wrap(availability, (panel.x + 18 * scale, panel.bottom - 54 * scale, panel.w - 36 * scale, 49 * scale), max(12, round(14 * scale)), MUTED)

    def _route(self, source, target, progress=1.0, alpha=255) -> None:
        sx, sy = source
        tx, ty = target
        dx, dy = tx - sx, ty - sy
        length = hypot(dx, dy)
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        end = (sx + dx * progress, sy + dy * progress)
        # Match the draft's metal shaft, dark edge, notched head and upper facet.
        # Draw in a small supersampled local layer so diagonals stay clean.
        scale = self.render_scale * 2
        margin = 20
        left, top = min(sx, end[0]) - margin, min(sy, end[1]) - margin
        w, h = max(1, round((abs(end[0]-sx)+margin*2)*scale)), max(1, round((abs(end[1]-sy)+margin*2)*scale))
        layer = pygame.Surface((w,h), pygame.SRCALPHA)
        def point(x,y):
            return round((x-left)*scale), round((y-top)*scale)
        pygame.draw.line(layer, (81,59,35,alpha), point(sx,sy), point(*end), max(1,round(5.2*scale)))
        stops = ((142,102,54),(194,154,88),(227,193,132))
        for i in range(64):
            p, q = i/64, (i+1)/64
            f = p*progress
            lo, hi, amount = (stops[0],stops[1],f/.62) if f < .62 else (stops[1],stops[2],(f-.62)/.38)
            color = tuple(round(a+(b-a)*amount) for a,b in zip(lo,hi))
            pygame.draw.line(layer, (*color,alpha), point(sx+(end[0]-sx)*p,sy+(end[1]-sy)*p), point(sx+(end[0]-sx)*q,sy+(end[1]-sy)*q), max(1,round(3.4*scale)))
        pygame.draw.line(layer, (240,213,152,round(alpha*.65)), point(sx+uy*.6,sy-ux*.6), point(end[0]+uy*.6,end[1]-ux*.6), max(1,round(.9*scale)))
        head = min(32,length*.18) * (.2+.8*min(1,progress*3))
        def local(x,y):
            return point(end[0]+ux*x-uy*y,end[1]+uy*x+ux*y)
        points = (local(0,0),local(-head,14),local(-(head-4),0),local(-head,-14))
        pygame.draw.polygon(layer, (221,186,123,alpha), points)
        pygame.draw.polygon(layer, (81,59,35,alpha), points, max(1,round(1.5*scale)))
        pygame.draw.polygon(layer, (229,196,134,alpha), (local(0,0),local(-head,-13),local(-(head-4),0)))
        layer = pygame.transform.smoothscale(layer,(max(1,w//2),max(1,h//2)))
        self.surface.blit(layer,self.pixel_point((left,top)))

    def _moving_card(self, app, cid, destination, origin, progress, start_scale=1.0, end_scale=1.0) -> None:
        if app.settings.skill_animation is SkillAnimation.OFF:
            progress = 1.0
        progress = min(1, max(0, progress))
        ease = 1 - (1 - progress) ** 3
        center = (origin[0] + (destination[0] - origin[0]) * ease, origin[1] + (destination[1] - origin[1]) * ease)
        scale = start_scale + (end_scale - start_scale) * ease
        rect = pygame.Rect(0, 0, max(1, round(120 * scale)), max(1, round(168 * scale)))
        rect.center = center
        self.card(app, cid, rect)

    def _exchange(self, app) -> None:
        engine, cue = app.engine, self.event
        t = self.event_elapsed
        showing = bool(engine.presentation_event) and cue is not None
        if showing and cue.kind in {"judgement", "judgement_replace"} and self.main_card:
            progress = min(1, t/380)
            center = (836, 430-18*(1-progress))
            flip = min(1, max(0, (t-180)/400))
            width = max(1, round(145*abs(cos(pi*flip))))
            native = self.pixel_rect((0,0,width,203)).size
            if flip < .5 and cue.kind == "judgement":
                image = pygame.transform.scale(self.image('back'), native)
            else:
                definition = CARD_BY_ID[engine.state.cards[self.main_card].definition_id]
                image = pygame.transform.scale(app.card_art.surface(definition, self.pixel_rect((0,0,145,203)).size), native)
            self.surface.blit(image, image.get_rect(center=self.pixel_point(center)))
            return
        if app.settings.skill_animation is SkillAnimation.OFF and showing and cue.kind in {"play", "rescue", "negate", "retarget"}:
            t = 700 if cue.kind == "retarget" else 1100
        if self.main_card:
            if showing and cue.kind == "play":
                self._moving_card(app, self.main_card, (782, 432), self.event_origin, t / 520, 1 if cue.actor_id == "P1" else 26 / 120)
            elif showing and cue.kind == "equip":
                slot = CARD_KIND_BY_NAME[CARD_BY_ID[engine.state.cards[self.main_card].definition_id].name].subtype
                spot = self.equipment_box(cue.actor_id, slot)
                self._moving_card(app, self.main_card, spot.center, (782, 432), max(0, t - 260) / 560, 1, spot.w / 120)
            elif showing and cue.kind == "result":
                zone = engine.state.zones[engine.state.cards[self.main_card].zone_id]
                if zone.kind.value == "judgment" and zone.owner_id:
                    spot = self.equipment_box(zone.owner_id, "judgment")
                    self._moving_card(app, self.main_card, spot.center, (782, 432), max(0, t - 1000) / 460, 1, spot.w / 120)
                else:
                    self._moving_card(app, self.main_card, (835, 567), (782, 432), max(0, t - 1000) / 460, 1, .05)
            else:
                self.card(app, self.main_card, (722, 348, 120, 168))
            if self.main_name and self.main_name != CARD_BY_ID[engine.state.cards[self.main_card].definition_id].name:
                self.text("视为【" + self.main_name + "】", (782, 326), 18, GOLD, True)
        if self.reply_cards:
            for i, cid in enumerate(self.reply_cards):
                progress = min(1, t / (480 if cue and cue.kind == "response" else 520))
                dest = (920 + i * 126, 432)
                if showing and cue.kind in {"response", "rescue", "negate"}:
                    self._moving_card(app, cid, dest, self.event_origin, progress, 1 if cue.actor_id == "P1" else 26 / 120)
                elif showing and cue.kind == "play":
                    self._moving_card(app, cid, dest, self.event_origin, t / 520)
                elif showing and cue.kind == "result":
                    self._moving_card(app, cid, (835, 567), dest, max(0, t - 1000) / 380, 1, .05)
                else:
                    self.card(app, cid, (dest[0] - 60, dest[1] - 84, 120, 168))
        if showing and cue.kind == "damage":
            for target in cue.target_ids:
                if target == "P1":
                    x, y = 274, 596
                else:
                    frame = pygame.Rect(self.seats[target].frame)
                    x, y = frame.centerx, frame.y + 65
                self.text(cue.label, (x, y + 12 - 24 * min(1, t / 700)), 40, (238, 172, 128), True, bold=True)
        # Action, response and result copy has one owner: the lower task panel.

    def _routes(self, app) -> None:
        cue = app.engine.presentation_event
        if cue is None or cue.kind not in {"play", "rescue", "negate", "retarget"}:
            return
        t = self.event_elapsed
        if app.settings.skill_animation is SkillAnimation.OFF:
            t = 700 if cue.kind == "retarget" else 1100
        route_start = 0 if cue.kind == "retarget" else 520
        elapsed = t - route_start
        if not 0 <= elapsed <= 950:
            return
        progress = 1 - (1 - min(1, elapsed / 320)) ** 3
        alpha = round(255 * min(1, elapsed / 120, max(0, (950 - elapsed) / 200)))
        if alpha <= 0:
            return
        # Above the task background, below its copy and prompts/details/pause: the player endpoint
        # at (835, 640) must not disappear behind the lower controls.
        if cue.kind == "negate":
            self._route(self.port(cue.actor_id), (782, 432), progress, alpha)
        else:
            for target in cue.target_ids:
                if target != cue.actor_id:
                    self._route(self.port(cue.actor_id), self.port(target), progress, alpha)

    def _logs(self, app) -> None:
        self.panel((1125, 66, 522, 512))
        self.hit(app, (1125, 66, 522, 512), ("battle_noop",))
        self.text("对局日志", (1149, 83), 25, GOLD)
        self.button(app, (1540, 81, 83, 35), "关闭", ("battle_log",))
        logs = app.engine.private_logs_for("P1")
        end = max(0, len(logs) - app.log_scroll)
        lines = []
        for log in logs[max(0, end - 9):end]:
            lines.append(f"{log.turn_number} · {log.text}")
        self.wrap("\n".join(lines), (1149, 131, 470, 399), 17)
        self.text("滚轮翻看记录", (1149, 545), 16, MUTED)

    def draw_confirm(self, app, title, message) -> None:
        mask = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 155))
        self.surface.blit(mask, (0, 0))
        self.panel((504, 270, 665, 330))
        self.text(title, (541, 294), 30, GOLD)
        self.wrap(message, (541, 354, 591, 115), 21)
        self.button(app, (541, 516, 270, 48), "取消", ("confirm_no",))
        self.button(app, (833, 516, 270, 48), "确认", ("confirm_yes",), primary=True)
        app.screen.blit(self.surface, self.viewport)

    def draw_spectator(self, app) -> None:
        mask = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 155))
        self.surface.blit(mask, (0, 0))
        self.panel((504, 144, 665, 540))
        self.text("你已阵亡 · 旁观模式", (535, 185), 30, GOLD)
        self.button(app, (535, 250, 595, 50), "观看剩余对局 · 自动播放", ("spectator_auto",), primary=True)
        self.button(app, (535, 314, 595, 48), "仅观看下一回合", ("spectator_continue", False))
        identity = "收起身份显示" if app.spectator_identity_reveal else "显示隐藏身份"
        hands = "收起手牌显示" if app.spectator_hand_reveal else "显示所有手牌"
        self.button(app, (535, 378, 595, 48), identity, ("spectator_reveal_identity",), selected=app.spectator_identity_reveal)
        self.button(app, (535, 442, 595, 48), hands, ("spectator_reveal_hands",), selected=app.spectator_hand_reveal)
        self._spectator_speed_controls(app, 506)
        self.button(app, (535, 600, 595, 48), "跳过观战，查看结果", ("confirm", "spectator_exit"))
        app.screen.blit(self.surface, self.viewport)

    def _spectator_speed_controls(self, app, y: int) -> None:
        speed = app.effective_ai_display_speed
        label = {AiDisplaySpeed.NORMAL: "正常", AiDisplaySpeed.FAST: "快速",
                 AiDisplaySpeed.INSTANT: "即时"}[speed]
        self.button(app, (535, y, 150, 42), "减速", ("spectator_speed", -1),
                    enabled=speed is not AiDisplaySpeed.NORMAL)
        self.text(f"观战：{label} · 仅本局", (702, y + 10), 20, GOLD)
        self.button(app, (980, y, 150, 42), "加速", ("spectator_speed", 1),
                    enabled=speed is not AiDisplaySpeed.INSTANT)

    def draw_pause(self, app) -> None:
        mask = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 150))
        self.surface.blit(mask, (0, 0))
        self.panel((504, 204, 665, 505 if app.is_spectating else 445))
        self.text("暂停", (535, 225), 30, GOLD)
        self.button(app, (535, 282, 595, 50), "继续对局", ("resume",), primary=True)
        items = (("规则图鉴", ("open_rules_help",)), ("牌面详情", ("battle_details",)),
                 ("设置", ("open_settings",)), ("认输", ("confirm", "resign")),
                 ("重新开始", ("confirm", "restart")), ("退出主菜单", ("confirm", "exit_to_menu")))
        if app.spectator_auto:
            items = (("改为逐回合观看", ("spectator_manual",)), *items[1:])
        if getattr(app, "guided_tutorial", None):
            items = (("规则图鉴", ("open_rules_help",)), ("牌面详情", ("battle_details",)),
                     ("设置", ("open_settings",)), ("结束练习", ("confirm", "resign")),
                     ("重练当前场景", ("confirm", "restart")), ("退出教学", ("confirm", "exit_to_menu")))
        for i, (label, action) in enumerate(items):
            self.button(app, (535 + i % 2 * 310, 356 + i // 2 * 78, 285, 53), label, action)
        if app.is_spectating:
            self._spectator_speed_controls(app, 608)
        app.screen.blit(self.surface, self.viewport)

    def _details_settings(self, app) -> None:
        app.buttons.clear()
        mask = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 145))
        self.surface.blit(mask, (0, 0))
        self.panel((320, 155, 1032, 550))
        self.text("牌面详情设置", (354, 183), 28, GOLD)
        self.button(app, (1225, 178, 97, 38), "关闭", ("battle_details",))
        settings = app.settings
        self.button(app, (354, 250, 465, 42), "显示详情：" + ("开启" if settings.card_details_enabled else "关闭"), ("battle_setting", "enabled", 0))
        fields = (("size", "显示大小", settings.card_details_size, .05),
                  ("x", "横向位置", settings.card_details_x, .01),
                  ("y", "纵向位置", settings.card_details_y, .01))
        for i, (field, label, value, step) in enumerate(fields):
            y = 326 + i * 72
            self.text(f"{label}   {value * 100:.0f}%", (354, y + 6), 22)
            self.button(app, (634, y, 82, 42), "−", ("battle_setting", field, -step), settings.card_details_enabled)
            self.button(app, (738, y, 82, 42), "＋", ("battle_setting", field, step), settings.card_details_enabled)
        self.button(app, (354, 580, 208, 42), "恢复默认", ("battle_setting", "reset", 0))
        self.text("悬停预览", (885, 250), 22, GOLD)
        from xssgkpz.data.cards import CARD_DEFINITIONS
        preview = pygame.Rect(885, 293, 425, 303)
        self.panel(preview)
        card = CARD_DEFINITIONS[0]
        # Miniature of the actual stage, including the complete inspector width.
        scale = preview.w / STAGE[0]
        stage_h = round(STAGE[1] * scale)
        stage = pygame.Rect(preview.x, preview.y + (preview.h - stage_h) // 2, preview.w, stage_h)
        self.draw_rect((14, 27, 21), stage)
        ratio = settings.card_details_size * scale
        width, height = round(240 * ratio), round(336 * ratio)
        px = stage.x + round(min(settings.card_details_x * STAGE[0], STAGE[0] - 605 * settings.card_details_size) * scale)
        py = stage.y + round(min(settings.card_details_y * STAGE[1], STAGE[1] - 336 * settings.card_details_size) * scale)
        clip = self.surface.get_clip()
        self.surface.set_clip(preview)
        if settings.card_details_enabled:
            self.surface.blit(app.card_art.surface(card, (width, height)), (px, py))
            text_panel = pygame.Rect(px + round(260 * ratio), py + round(44 * ratio), round(330 * ratio), round(248 * ratio))
            self.draw_rect((22, 37, 29), text_panel)
            self.draw_rect((123, 110, 75), text_panel, 1)
            kind = CARD_KIND_BY_NAME[card.name]
            self.text(kind.name, (text_panel.x + 4, text_panel.y + 4), max(8, round(25 * ratio)), GOLD)
            self.wrap(kind.display_summary, (text_panel.x + 4, text_panel.y + max(16, round(51 * ratio)), max(10, text_panel.w - 8), max(12, text_panel.h - 20)), max(8, round(20 * ratio)))
        else:
            self.text("详情已关闭", (960, 420), 22, MUTED)
        self.surface.set_clip(clip)
        self.text("实际大小范围50%–250%；预览按区域缩放", (885, 620), 16, MUTED)
        self.text(app.settings_message or "自动保存；关闭后返回暂停菜单", (354, 657), 16, MUTED)

    def scroll(self, app, amount, position) -> None:
        point = self.stage_point(position)
        if self.details_open:
            return
        if self.log_open and pygame.Rect(1125, 66, 522, 512).collidepoint(point):
            app.log_scroll = max(0, min(max(0, len(app.engine.logs) - 1), app.log_scroll + amount * 3))
        elif pygame.Rect(497, 653, 1143, 282).collidepoint(point):
            self.hand_scroll = max(0, min(self.max_scroll, self.hand_scroll + amount * 160))
        elif app.engine.pending_request:
            self.choice_scroll = max(0, self.choice_scroll + amount)

    def key(self, app, key) -> None:
        if key in (pygame.K_LEFT, pygame.K_RIGHT) and self.hand_ids:
            try:
                index = self.hand_ids.index(self.focus_card)
            except ValueError:
                index = -1 if key == pygame.K_RIGHT else len(self.hand_ids)
            index = max(0, min(len(self.hand_ids) - 1, index + (1 if key == pygame.K_RIGHT else -1)))
            self.focus_card = self.hand_ids[index]
            rect = self.hand_rects.get(self.focus_card)
            if rect and rect.x < 497:
                self.hand_scroll = max(0, self.hand_scroll - (497 - rect.x))
            elif rect and rect.right > 1640:
                self.hand_scroll = min(self.max_scroll, self.hand_scroll + rect.right - 1640)
        elif key == pygame.K_SPACE and self.focus_card and not app.engine.display_waiting:
            self.activate(app, ("battle_card", self.focus_card))
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and not self.details_open and not app.engine.display_waiting:
            if app.engine.pending_request:
                request = app.engine.pending_request
                if request.min_choices <= len(app.selected_choices) <= request.max_choices:
                    app._activate(("answer_prompt",))
            else:
                self.activate(app, ("battle_confirm",))

    def activate(self, app, action) -> None:
        name, *args = action
        engine = app.engine
        lesson = getattr(app, "guided_tutorial", None)
        if lesson and not lesson.allow(app, action):
            return
        if engine.display_waiting and name in {"battle_card", "battle_skill", "battle_target", "battle_confirm", "battle_option", "battle_pass"}:
            return
        if name == "battle_log":
            self.log_open = not self.log_open
        elif name == "battle_details":
            self.details_open = not self.details_open
            app.pause_open = not self.details_open
            app.settings_message = ""
        elif name == "battle_setting":
            field, delta = args
            changes = {}
            if field == "reset":
                defaults = Settings()
                changes = {key: getattr(defaults, key) for key in ("card_details_enabled", "card_details_size", "card_details_x", "card_details_y")}
            elif field == "enabled":
                changes["card_details_enabled"] = not app.settings.card_details_enabled
            else:
                attr = "card_details_" + str(field)
                changes[attr] = max(.5 if field == "size" else 0, min(2.5 if field == "size" else 1, getattr(app.settings, attr) + float(delta)))
            candidate = replace(app.settings, **changes)
            candidate = replace(candidate, card_details_x=min(candidate.card_details_x, 1 - 605 * candidate.card_details_size / 1672),
                                card_details_y=min(candidate.card_details_y, 1 - 336 * candidate.card_details_size / 941))
            app.settings = candidate
            try:
                save_settings(candidate)
                app.settings_message = "已保存"
            except OSError:
                app.settings_message = "本次有效，保存失败"
        elif name == "battle_scroll":
            self.hand_scroll = max(0, min(self.max_scroll, self.hand_scroll + int(args[0]) * 800))
        elif name == "battle_choice_scroll":
            self.choice_scroll = max(0, self.choice_scroll + int(args[0]))
        elif name == "battle_cancel":
            if engine.pending_request:
                app.selected_choices.clear()
            else:
                self.cancel()
        elif name == "battle_option" and engine.pending_request:
            choice = str(args[0])
            if not any(o.choice_id == choice for o in engine.pending_request.options):
                return
            if engine.pending_request.max_choices == 1:
                app.selected_choices.clear() if choice not in app.selected_choices else None
            app._activate(("toggle_choice", choice))
        elif name == "battle_pass" and engine.pending_request:
            request = engine.pending_request
            if any(o.choice_id == "pass" for o in request.options):
                engine.answer_prompt("pass")
            elif request.min_choices == 0:
                engine.answer_prompt(())
            else:
                return
            app.selected_choices.clear()
            app._after_engine_step()
        elif name == "battle_skill":
            self.selected_skill = str(args[0])
            self.selected_card = None
            self.targets.clear()
            self.costs.clear()
            self.notice = ""
        elif name == "battle_card":
            cid = str(args[0])
            if engine.pending_request:
                options = tuple(o for o in engine.pending_request.options if o.value == cid)
                if options:
                    self.activate(app, ("battle_option", options[0].choice_id))
                else:
                    self.notice = "此牌不在当前窗口的合法选项中"
            elif self.selected_skill:
                if cid in self.costs:
                    self.costs.remove(cid)
                elif any(cid in a.intent.cost_card_ids and all(c in a.intent.cost_card_ids for c in self.costs) for a in self._base_candidates()):
                    self.costs.append(cid)
                else:
                    self.notice = "当前技能不能使用这张牌"
                self.targets.clear()
            else:
                self.selected_card = None if self.selected_card == cid else cid
                self.targets.clear()
                self.costs.clear()
                self.notice = "" if self._base_candidates() else "此牌当前没有合法主动出牌动作，请查看详情或选择技能"
        elif name == "battle_target":
            target = str(args[0])
            if target in self.targets:
                self.targets = self.targets[:self.targets.index(target)]
            elif target in self.eligible_targets():
                self.targets.append(target)
        elif name == "battle_confirm":
            selected = self.ready_action()
            if selected and engine.is_human_turn:
                legal = next((a for a in engine.available_actions("P1") if a.intent == selected.intent), None)
                if legal:
                    engine.submit_action(legal.intent)
                    self.selected_card = self.selected_skill = None
                    self.targets.clear()
                    self.costs.clear()
                    self._actions_key = None
                    self.notice = ""
                    app._after_engine_step()
        if lesson:
            lesson.observe(app, str(name))
