"""Stage 1 pygame interface for setup, a complete match, and a result page."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from dataclasses import dataclass
from xssgkpz.resource_paths import RESOURCE_ROOT
from secrets import randbits

import pygame
from xssgkpz.fonts import ui_font
from xssgkpz import diagnostics

from xssgkpz import APP_VERSION, RULES_VERSION
from xssgkpz.core.actions import ActionIntent, ChoiceOption, DecisionRequest, GameAction
from xssgkpz.core.ai import make_ai_policies
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import HERO_IDS, MatchRoster, create_match, random_hero_candidates, resolve_roster
from xssgkpz.core.random_stream import FixedSeedRandom
from xssgkpz.data.cards import (
    CARD_BY_ID, CARD_DEFINITIONS, CARD_KIND_BY_NAME, CardCategory, CardKindDefinition,
)
from xssgkpz.data.assets import ASSET_BY_KEY
from xssgkpz.card_art import CardArt
from xssgkpz.battle_ui import BattleUI
from xssgkpz.audio import GameAudio
from xssgkpz.shell_theme import ShellTheme, FACTION
from xssgkpz.shell_layout import ShellLayouts
from xssgkpz.data.heroes import HEROES, HERO_BY_ID, SKILL_BY_ID, HeroDefinition
from xssgkpz.data.modes import Difficulty, Identity, MODE_BY_ID, ModeDefinition
from xssgkpz.data.settings import AiDisplaySpeed, Settings, SkillAnimation, WindowMode
from xssgkpz.data.tutorials import TUTORIALS, TUTORIAL_BY_ID
from xssgkpz.guided_tutorial import GuidedTutorial, create_tutorial
from xssgkpz.persistence import (
    append_record_summary, clear_record_summaries, load_record_summaries,
    load_settings, new_record_summary, records_path, save_settings,
)


CANVAS_SIZE = (1280, 720)
PROJECT_ROOT = RESOURCE_ROOT
HERO_SKILL_WRAP_LIMIT = 20
HERO_SKILL_VISIBLE_LINES = 16
BACKGROUND = (20, 33, 27)
PANEL = (20, 33, 27)
PANEL_LIGHT = (31, 42, 34)
INK = (238, 220, 183)
MUTED = (180, 169, 143)
ACCENT = (221, 186, 123)
ACCENT_DARK = (132, 95, 52)
GREEN = (117, 200, 143)
RED = (230, 146, 127)
BLUE = (126, 173, 225)
DIFFICULTY_LABELS = {
    Difficulty.SIMPLE: "简单",
    Difficulty.MEDIUM: "中等",
    Difficulty.HARD: "困难",
}
AI_DISPLAY_PAUSE_MS = {
    AiDisplaySpeed.NORMAL: 1_800,
    AiDisplaySpeed.FAST: 800,
    AiDisplaySpeed.INSTANT: 10,
}


@dataclass(frozen=True, slots=True)
class UIButton:
    rect: pygame.Rect
    label: str
    action: tuple[object, ...]
    enabled: bool = True
    selected: bool = False
    primary: bool = False


class Stage1App:
    def __init__(self, screen: pygame.Surface, settings: Settings) -> None:
        self.display = screen
        self.screen = pygame.Surface(CANVAS_SIZE)
        self.settings = settings
        self.font = ui_font("microsoftyahei", 22)
        self.small_font = ui_font("microsoftyahei", 17)
        self.tiny_font = ui_font("microsoftyahei", 14)
        self.big_font = ui_font("microsoftyahei", 34)
        self.button_font = ui_font("kaiti", 22)
        self.title_font = ui_font("kaiti", 34, bold=True)
        self.audio = GameAudio()
        self.shell_theme = ShellTheme()
        self.shell_layout = ShellLayouts(self)
        from xssgkpz.detail_editor import DetailEditor
        self.detail_editor = DetailEditor(self)
        self.ui_render_scale = 1.0
        self.shell_fonts: dict[tuple[str, int, bool], pygame.font.Font] = {}
        self.page = "menu"
        self.buttons: list[UIButton] = []
        self.selected_mode = "duel"
        self.selected_difficulty = Difficulty.SIMPLE
        self.hero_method = "free_choice"
        self.candidates = HERO_IDS
        self.selected_hero = HERO_IDS[0]
        self.hero_scroll = 0
        self.identity_choice: str | None = None
        self.setup_seed = randbits(32)
        self.roster: Stage1Roster | None = None
        self.pending_match_state = None
        self.engine: GameEngine | None = None
        self.ai_display_deadline_ms: int | None = None
        self.ai_display_delay_ms: int | None = None
        self.ai_presentation_started_ms: int | None = None
        self.recorded_match = False
        self.pause_open = False
        self.confirm_kind: str | None = None
        self.selected_choices: set[str] = set()
        self.action_scroll = 0
        self.prompt_scroll = 0
        self.log_scroll = 0
        self.spectator_identity_reveal = False
        self.spectator_hand_reveal = False
        self.spectator_auto = False
        self.spectator_display_speed: AiDisplaySpeed | None = None
        self.deal_started_ms = None
        self.deal_last_tick_ms = None
        self.outcome_started_ms = None
        self.window_focused = True
        self.focus_lost_ms = None
        self.last_result_text = ""
        self.record_save_error = ""
        self.records_message = ""
        self.settings_message = ""
        self.audio_slider_drag = None
        self.overlay_return = "menu"
        self.page_stack: list[str] = []
        self.hero_album_mode = "all"
        self.hero_album_selection = HEROES[0].hero_id
        self.hero_album_scroll = 0
        self.card_album_category: CardCategory | None = None
        self.card_album_index = 0
        self.selected_card_id = CARD_DEFINITIONS[0].definition_id
        self.records_filter = "all"
        self.records_scroll = 0
        self.help_mode = "duel"
        self.tutorial_id = "basic"
        self.tutorial_step_index = 0
        self.tutorial_selection: int | None = None
        self.tutorial_answered = False
        self.guided_tutorial: GuidedTutorial | None = None
        self._practice_saved: dict[str, object] | None = None
        self._practice_started_ms = 0
        self.card_art = CardArt()
        self.battle_ui = BattleUI()
        self.ai_display_last_tick_ms: int | None = None
        self.hero_portrait_scales: dict[tuple[str, int, int], pygame.Surface] = {}
        self.mouse_canvas_position: tuple[int, int] | None = None

    def run(self) -> None:
        self.audio.start(self.settings)
        clock = pygame.time.Clock()
        running = True
        while running:
            diagnostics.heartbeat(self, 'audio')
            self.audio.update(self)
            diagnostics.heartbeat(self, 'draw')
            self._draw()
            diagnostics.heartbeat(self, 'present')
            self._present()
            diagnostics.heartbeat(self, 'events')
            self._mark_ai_display_step_presented()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if self.detail_editor.drag is not None:
                        self.detail_editor.drag = None
                        self.detail_editor.save()
                    if self.audio_slider_drag:
                        self._set_audio_volume(self.audio_slider_drag, getattr(self.settings, self.audio_slider_drag))
                        self.audio_slider_drag = None
                    running = False
                elif event.type in (pygame.WINDOWFOCUSLOST, pygame.WINDOWMINIMIZED):
                    if self.detail_editor.drag is not None:
                        self.detail_editor.drag = None
                        self.detail_editor.save()
                    if self.window_focused:
                        self.focus_lost_ms = pygame.time.get_ticks()
                    self.window_focused = False
                    if self.page == "game" and self.deal_started_ms is None and self.outcome_started_ms is None:
                        self.pause_open = True
                elif event.type == pygame.WINDOWFOCUSGAINED:
                    now = pygame.time.get_ticks()
                    if self.outcome_started_ms is not None and self.focus_lost_ms is not None:
                        self.outcome_started_ms += max(0, now-self.focus_lost_ms)
                    self.window_focused = True
                    self.focus_lost_ms = None
                elif event.type == pygame.VIDEORESIZE:
                    if self.settings.window_mode is WindowMode.WINDOWED:
                        self.display = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                        self.settings = replace(self.settings, resolution_width=event.w,
                                                resolution_height=event.h)
                        try:
                            save_settings(self.settings)
                            self.settings_message = "窗口大小已保存。"
                        except OSError:
                            self.settings_message = "窗口大小已更改，但设置文件保存失败。"
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    position = self._to_canvas(event.pos)
                    self.mouse_canvas_position = position
                    if event.button == 1:
                        if self.detail_editor.start_drag(position):
                            continue
                        volume_hit = self.shell_layout.volume_at(position)
                        if volume_hit:
                            self.audio_slider_drag = volume_hit[0]
                            self._set_audio_volume(*volume_hit, persist=False)
                            continue
                        button = next((item for item in reversed(self.buttons) if item.rect.collidepoint(position)), None)
                        if button and button.enabled:
                            self._activate(button.action)
                    elif event.button == 4:
                        self._scroll(-1, position)
                    elif event.button == 5:
                        self._scroll(1, position)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if self.detail_editor.drag is not None:
                        self.detail_editor.drag = None
                        self.detail_editor.save()
                    if self.audio_slider_drag:
                        field = self.audio_slider_drag
                        self.audio_slider_drag = None
                        self._set_audio_volume(field, getattr(self.settings, field))
                elif event.type == pygame.MOUSEMOTION:
                    self.mouse_canvas_position = self._to_canvas(event.pos)
                    self.detail_editor.move(self.mouse_canvas_position)
                    if self.audio_slider_drag:
                        hit = self.shell_layout.volume_at(self.mouse_canvas_position, self.audio_slider_drag)
                        if hit:
                            self._set_audio_volume(*hit, persist=False)
                elif event.type == pygame.KEYDOWN:
                    diagnostics.action(self, ('key', pygame.key.name(event.key)))
                    if self.deal_started_ms is not None or self.outcome_started_ms is not None:
                        continue
                    if event.key == pygame.K_ESCAPE:
                        self._escape()
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if self.confirm_kind:
                            self._activate(("confirm_yes",))
                        elif self.page == "game" and self.pause_open:
                            self.pause_open = False
                        elif self.page == "game" and self.engine:
                            self.battle_ui.key(self, event.key)
                    elif self.page == "game" and self.engine and not self.pause_open and not self.confirm_kind:
                        self.battle_ui.key(self, event.key)
            if running:
                diagnostics.heartbeat(self, 'advance_ai')
                self._advance_ai_display_step()
            clock.tick(60)
        self.audio.close()

    def _present(self) -> None:
        width, height = self.display.get_size()
        ratio = min(width / self.screen.get_width(), height / self.screen.get_height())
        size = (max(1, round(self.screen.get_width() * ratio)), max(1, round(self.screen.get_height() * ratio)))
        scaled = self.screen if self.screen.get_size() == size else pygame.transform.smoothscale(self.screen, size)
        self.display.fill((12, 15, 13))
        self.display.blit(scaled, ((width - size[0]) // 2, (height - size[1]) // 2))
        pygame.display.flip()

    def _to_canvas(self, position: tuple[int, int]) -> tuple[int, int]:
        width, height = self.display.get_size()
        canvas = self.screen.get_size() if self.page == "game" else CANVAS_SIZE
        ratio = min(width / canvas[0], height / canvas[1])
        return (round((position[0] - (width - canvas[0] * ratio) / 2) / ratio),
                round((position[1] - (height - canvas[1] * ratio) / 2) / ratio))

    def _clear_ai_display_pause(self) -> None:
        self.ai_display_deadline_ms = None
        self.ai_display_delay_ms = None
        self.ai_display_last_tick_ms = None

    @property
    def is_spectating(self) -> bool:
        return bool(self.engine and not self.engine.finished and not self.guided_tutorial
                    and self.engine.state.mode_id == "five_player_identity"
                    and any(player.player_id == "P1" and not player.alive
                            for player in self.engine.state.players))

    @property
    def effective_ai_display_speed(self) -> AiDisplaySpeed:
        if self.is_spectating and self.spectator_display_speed is not None:
            return self.spectator_display_speed
        return self.settings.ai_display_speed

    def _change_spectator_speed(self, direction: int) -> None:
        if not self.is_spectating:
            return
        options = tuple(AiDisplaySpeed)
        previous = self.effective_ai_display_speed
        index = max(0, min(len(options) - 1, options.index(previous) + direction))
        self.spectator_display_speed = options[index]
        # Rescale an already armed interval without advancing the engine or cue.
        ratio = AI_DISPLAY_PAUSE_MS[options[index]] / AI_DISPLAY_PAUSE_MS[previous]
        if self.ai_display_delay_ms is not None:
            self.ai_display_delay_ms = round(self.ai_display_delay_ms * ratio)
        if self.ai_display_deadline_ms is not None:
            now = pygame.time.get_ticks()
            anchor = self.ai_display_last_tick_ms if self.ai_display_last_tick_ms is not None else now
            self.ai_display_deadline_ms = now + round(max(0, self.ai_display_deadline_ms - anchor) * ratio)
            self.ai_display_last_tick_ms = now

    def _arm_ai_display_pause(self) -> None:
        if (self.engine and self.engine.display_waiting
                and self.ai_display_delay_ms is None):
            cue = self.engine.presentation_event
            if cue and cue.kind == "play":
                self.ai_presentation_started_ms = pygame.time.get_ticks() if cue.actor_id != "P1" else None
            if cue:
                self.ai_display_delay_ms = 0
            else:
                # The configured AI interval includes the action already shown.
                # Do not add another complete interval after its animation.
                elapsed = (pygame.time.get_ticks() - self.ai_presentation_started_ms
                           if self.ai_presentation_started_ms is not None else 0)
                self.ai_display_delay_ms = max(0, AI_DISPLAY_PAUSE_MS[self.effective_ai_display_speed] - elapsed)
                self.ai_presentation_started_ms = None

    def _mark_ai_display_step_presented(self, now_ms: int | None = None) -> None:
        if (not self.engine or not self.engine.display_waiting
                or self.ai_display_delay_ms is None or self.ai_display_deadline_ms is not None):
            return
        now = pygame.time.get_ticks() if now_ms is None else now_ms
        self.ai_display_deadline_ms = now + self.ai_display_delay_ms
        self.ai_display_last_tick_ms = now

    def _advance_ai_display_step(self, now_ms: int | None = None) -> bool:
        now = pygame.time.get_ticks() if now_ms is None else now_ms
        paused = (self.page != "game" or self.pause_open or self.confirm_kind
                  or self.battle_ui.details_open or not self.window_focused)
        if self.outcome_started_ms is not None:
            if not self.window_focused:
                return False
            if now - self.outcome_started_ms >= 3200:
                self.outcome_started_ms = None
                self.page = "result"
            return False
        if self.deal_started_ms is not None:
            if paused and self.deal_last_tick_ms is not None:
                self.deal_started_ms += max(0, now - self.deal_last_tick_ms)
            self.deal_last_tick_ms = now
            if paused or now - self.deal_started_ms < 3000:
                return False
            self.deal_started_ms = self.deal_last_tick_ms = None
            self.engine.start()
            self._after_engine_step()
            return True
        if self.engine and self.engine.spectator_waiting and self.spectator_auto and not paused:
            self.engine.continue_spectator()
            self._after_engine_step()
            return True
        if self.ai_display_deadline_ms is not None and self.ai_display_last_tick_ms is not None and paused:
            self.ai_display_deadline_ms += max(0, now - self.ai_display_last_tick_ms)
            if self.ai_presentation_started_ms is not None:
                self.ai_presentation_started_ms += max(0, now - self.ai_display_last_tick_ms)
        self.ai_display_last_tick_ms = now
        if (not self.engine or not self.engine.display_waiting
                or paused):
            return False
        if self.ai_display_deadline_ms is None:
            return False
        if now < self.ai_display_deadline_ms:
            return False
        if self.engine.presentation_event and not self.battle_ui.animation_done:
            return False
        engine = self.engine
        self._clear_ai_display_pause()
        engine.resume_display()
        self._after_engine_step()
        return True

    def _draw(self) -> None:
        self.buttons = []
        self.ui_render_scale = 1.0 if self.page == "game" else min(
            self.display.get_width() / CANVAS_SIZE[0], self.display.get_height() / CANVAS_SIZE[1])
        render_size = self.display.get_size() if self.page == "game" else tuple(
            max(1, round(side * self.ui_render_scale)) for side in CANVAS_SIZE)
        if self.screen.get_size() != render_size:
            self.screen = pygame.Surface(render_size)
        if self.page != "game":
            self.battle_ui.last_tick = pygame.time.get_ticks()
        self.screen.fill(BACKGROUND)
        if self.page != "game":
            self.shell_theme.backdrop(self.screen)
        if self.page == "menu":
            self._draw_menu()
        elif self.page == "setup":
            self._draw_setup()
        elif self.page == "roster":
            self._draw_roster()
        elif self.page == "identity":
            self._draw_identity()
        elif self.page == "objective":
            self._draw_objective()
        elif self.page == "game":
            self._draw_game()
        elif self.page == "result":
            self._draw_result()
        elif self.page == "tutorial_index":
            self._draw_tutorial_index()
        elif self.page == "tutorial":
            self._draw_tutorial()
        elif self.page == "hero_album":
            self._draw_hero_album()
        elif self.page == "card_album":
            self._draw_card_album()
        elif self.page == "rules_help":
            self._draw_rules_help()
        elif self.page == "settings":
            self._draw_settings()
        elif self.page == "detail_editor":
            self.detail_editor.draw()
        elif self.page == "records":
            self._draw_records()
        if self.page != "game":
            self._draw_version()
        if self.page == "game" and self.engine:
            if self.outcome_started_ms is not None or self.deal_started_ms is not None:
                from xssgkpz.battle_transitions import draw_transition
                self.buttons.clear()
                draw_transition(self)
            elif self.confirm_kind:
                self.buttons.clear()
                self._draw_confirm()
            elif self.pause_open:
                self.buttons.clear()
                self._draw_pause()
            elif self.engine.spectator_waiting and not self.spectator_auto:
                self.buttons.clear()
                self._draw_spectator_wait()
        elif self.confirm_kind:
            self.buttons.clear()
            self._draw_confirm()

    def _draw_menu(self) -> None:
        self.shell_layout.draw("menu")

    def _draw_tutorial_index(self) -> None:
        self.shell_layout.draw("tutorial_index")

    def _draw_tutorial(self) -> None:
        lesson = TUTORIAL_BY_ID[self.tutorial_id]
        step = lesson.steps[self.tutorial_step_index]
        self._heading(lesson.title, f"步骤 {self.tutorial_step_index + 1} / {len(lesson.steps)} · 教学不创建正式对局")
        self._panel(pygame.Rect(190, 150, 900, 432))
        self._text(step.title, (232, 180), self.font, ACCENT)
        self._draw_wrapped(step.prompt, (232, 226), 36, self.font)
        for index, choice in enumerate(step.choices):
            self._button(pygame.Rect(232, 292 + index * 58, 810, 46), choice,
                         ("tutorial_answer", index), selected=self.tutorial_selection == index,
                         enabled=not self.tutorial_answered)
        if self.tutorial_answered:
            correct = self.tutorial_selection == step.answer_index
            self._text("回答正确" if correct else "再看一下规则", (232, 478), self.small_font,
                       GREEN if correct else ACCENT)
            self._draw_wrapped(step.feedback, (232, 508), 54, self.tiny_font)
            label = "完成本段" if self.tutorial_step_index + 1 == len(lesson.steps) else "下一步"
            self._button(pygame.Rect(940, 650, 276, 48), label, ("tutorial_next",), primary=True)
        self._button(pygame.Rect(36, 650, 160, 42), "退出教学", ("back",))

    def _draw_hero_album(self) -> None:
        self.shell_layout.draw("hero_album")

    def _draw_card_album(self) -> None:
        self.shell_layout.draw("card_album")

    def _draw_rules_help(self) -> None:
        self.shell_layout.draw("rules_help")

    def _draw_settings(self) -> None:
        self.shell_layout.draw("settings")

    def _draw_records(self) -> None:
        self.shell_layout.draw("records")

    def _draw_wrapped(self, value: str, position: tuple[int, int], limit: int,
                      font: pygame.font.Font | None = None) -> None:
        font = font or self.small_font
        for index, line in enumerate(self._wrap_lines(value, limit)):
            self._text(line, (position[0], position[1] + index * (font.get_linesize() + 2)), font)

    def _hero_album_lines(
        self, hero: HeroDefinition, mode: ModeDefinition | None, wrap_limit: int = HERO_SKILL_WRAP_LIMIT,
    ) -> list[tuple[str, tuple[int, int, int]]]:
        lines: list[tuple[str, tuple[int, int, int]]] = []
        for skill_id in hero.skill_ids:
            skill = SKILL_BY_ID[skill_id]
            if skill.is_lord_skill and mode and not mode.lord_skills_enabled:
                availability = f"当前模式不可用：{mode.name}不启用主公技。"
            elif skill.skill_id == "daqiao.liuli" and mode and mode.player_count < 3:
                availability = f"当前模式限制：{mode.name}没有第三名角色可转移目标。"
            else:
                availability = "主公技" if skill.is_lord_skill else "技能"
            title = f"{skill.name} · {availability}"
            lines.extend((line, ACCENT) for line in self._wrap_lines(title, wrap_limit))
            lines.extend((line, INK) for line in self._wrap_lines(skill.description, wrap_limit))
        return lines

    def _draw_hero_portrait(self, hero_id: str, target_rect: pygame.Rect) -> bool:
        target_rect = self._shell_rect(target_rect)
        hero = HERO_BY_ID[hero_id]
        asset = ASSET_BY_KEY.get(hero.asset_key)
        if asset is None or asset.relative_path is None:
            return False

        cache_key = (hero.asset_key, target_rect.width, target_rect.height)
        scaled = self.hero_portrait_scales.get(cache_key)
        if scaled is None:
            path = PROJECT_ROOT / asset.relative_path
            try:
                source = pygame.image.load(path).convert_alpha()
            except (OSError, pygame.error):
                return False
            scale = min(target_rect.width / source.get_width(), target_rect.height / source.get_height())
            width = max(1, round(source.get_width() * scale))
            height = max(1, round(source.get_height() * scale))
            scaled = pygame.transform.smoothscale(source, (width, height))
            self.hero_portrait_scales[cache_key] = scaled
            del source
        width, height = scaled.get_size()
        destination = pygame.Rect(0, 0, width, height)
        destination.center = target_rect.center
        self.screen.blit(scaled, destination)
        return True

    @staticmethod
    def _wrap_lines(value: str, limit: int) -> list[str]:
        lines: list[str] = []
        for paragraph in value.splitlines() or [""]:
            while len(paragraph) > limit:
                lines.append(paragraph[:limit])
                paragraph = paragraph[limit:]
            lines.append(paragraph)
        return lines

    @staticmethod
    def _wrap_to_pixel_width(value: str, font: pygame.font.Font, max_width: int) -> list[str]:
        lines: list[str] = []
        for paragraph in value.splitlines() or [""]:
            line = ""
            for character in paragraph:
                candidate = line + character
                if line and font.size(candidate)[0] > max_width:
                    lines.append(line)
                    line = character
                else:
                    line = candidate
            lines.append(line)
        return lines

    def _draw_setup(self) -> None:
        self.shell_layout.draw("setup")

    def _draw_roster(self) -> None:
        self.shell_layout.draw("roster")

    def _draw_identity(self) -> None:
        self.shell_layout.draw("identity")

    def _draw_objective(self) -> None:
        self.shell_layout.draw("objective")

    def _draw_game(self) -> None:
        self.battle_ui.draw(self)

    def _draw_prompt(self, request: DecisionRequest) -> None:
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 155))
        self.screen.blit(overlay, (0, 0))
        self._panel(pygame.Rect(240, 136, 800, 474), color=(52, 65, 66))
        self._text(request.title, (274, 158), self.big_font, ACCENT)
        self._text(self._clip(request.message, 80), (274, 206), self.small_font, INK)
        self._text(f"可选 {request.min_choices}–{request.max_choices} 项", (274, 232), self.tiny_font, MUTED)
        visible_count = 7
        visible = request.options[self.prompt_scroll:self.prompt_scroll + visible_count]
        for index, option in enumerate(visible):
            selected = option.choice_id in self.selected_choices
            label = ("✓ " if selected else "　") + self._clip(option.label, 54)
            self._button(pygame.Rect(274, 262 + index * 38, 720, 32), label,
                         ("toggle_choice", option.choice_id), selected=selected)
        self._button(pygame.Rect(274, 544, 92, 34), "‹ 上页", ("prompt_scroll", -1), enabled=self.prompt_scroll > 0)
        self._button(pygame.Rect(374, 544, 92, 34), "下页 ›", ("prompt_scroll", 1),
                     enabled=self.prompt_scroll + visible_count < len(request.options))
        self._button(pygame.Rect(754, 540, 112, 42), "确认", ("answer_prompt",), primary=True,
                     enabled=request.min_choices <= len(self.selected_choices) <= request.max_choices)
        self._button(pygame.Rect(878, 540, 112, 42), "清除选择", ("clear_choices",))

    def _draw_pause(self) -> None:
        self.battle_ui.draw_pause(self)

    def _draw_confirm(self) -> None:
        offset_x = (self.screen.get_width() - CANVAS_SIZE[0]) // 2 if self.page == "game" else 0
        offset_y = (self.screen.get_height() - CANVAS_SIZE[1]) // 2 if self.page == "game" else 0
        message = {
            "restart": "确认重新开始？当前对局将记录为失败。",
            "resign": "确认认输？当前对局将记录为失败。",
            "exit_to_menu": "确认退出主菜单？当前对局将记录为未完成，不计胜负。",
            "clear_records": "确认清除全部本地战绩？设置不会更改。",
            "abandon_setup": "放弃本次设置并返回标题？尚未开始，不会生成战绩。",
            "reveal_identity": "揭晓后将不能恢复保密旁观。\n仅改变你看到的信息，不影响AI和此前日志。",
            "reveal_hands": "首次显示电脑手牌，只供你旁观查看。\nAI不会获得这些信息；关闭显示后你仍已获知。",
            "spectator_exit": "跳过剩余观战，按完整规则推演至终局。\n完成后保存战绩并显示本局结果。",
        }.get(self.confirm_kind, "确认此操作？")
        if self.guided_tutorial and self.confirm_kind in {"resign", "restart", "exit_to_menu"}:
            message = ("重新练习当前场景？本场景操作将重置，教学不计战绩。"
                       if self.confirm_kind == "restart" else "退出教学并返回章节目录？教学不计战绩。")
        title = "信息展示确认" if self.confirm_kind in {"reveal_identity", "reveal_hands"} else "请确认"
        if self.page == "game":
            self.battle_ui.draw_confirm(self, title, message)
            return
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 155))
        self.screen.blit(overlay, (0, 0))
        self._panel(pygame.Rect(390 + offset_x, 242 + offset_y, 500, 246))
        self._text(title, (428 + offset_x, 266 + offset_y), self.big_font, ACCENT)
        self._draw_wrapped(message, (428 + offset_x, 326 + offset_y), 24, self.small_font)
        self._button(pygame.Rect(428 + offset_x, 418 + offset_y, 152, 44), "取消", ("confirm_no",))
        self._button(pygame.Rect(600 + offset_x, 418 + offset_y, 152, 44), "确认", ("confirm_yes",), primary=True)

    def _draw_spectator_wait(self) -> None:
        self.battle_ui.draw_spectator(self)

    def _draw_result(self) -> None:
        self.shell_layout.draw("result")

    def _draw_version(self) -> None:
        # Version remains available in the window title, outside the game artwork.
        pass

    def _heading(self, title: str, subtitle: str) -> None:
        width = max(290, self.title_font.size(title)[0] + 58)
        self.shell_theme.plate(self.screen, self._shell_rect(pygame.Rect(28, 16, width, 51)), "heading")
        self._text(title, (55, 23), self.title_font, INK)
        subtitle_width = min(1220, self.small_font.size(subtitle)[0] + 24)
        self._panel(pygame.Rect(28, 72, subtitle_width, 30))
        self._text(subtitle, (38, 76), self.small_font, MUTED)

    def _panel(self, rect: pygame.Rect, color: tuple[int, int, int] = PANEL) -> None:
        self.shell_theme.plate(self.screen, self._shell_rect(rect))

    def _shell_rect(self, rect: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(*(round(value * self.ui_render_scale) for value in rect))

    def _shell_font(self, font: pygame.font.Font) -> pygame.font.Font:
        if self.ui_render_scale == 1:
            return font
        name, size, bold = next((spec for original, spec in (
            (self.button_font, ("kaiti", 22, False)),
            (self.font, ("microsoftyahei", 22, False)),
            (self.small_font, ("microsoftyahei", 17, False)),
            (self.tiny_font, ("microsoftyahei", 14, False)),
            (self.big_font, ("microsoftyahei", 34, False)),
            (self.title_font, ("kaiti", 34, True))) if original is font),
            ("microsoftyahei", font.get_height(), False))
        key = (name, max(8, round(size * self.ui_render_scale)), bold)
        if key not in self.shell_fonts:
            self.shell_fonts[key] = ui_font(key[0], key[1], bold=key[2])
        return self.shell_fonts[key]

    def _text(self, value: str, position: tuple[int, int], font: pygame.font.Font | None = None,
              color: tuple[int, int, int] = INK) -> None:
        font = font or self.font
        native_font = self._shell_font(font)
        for index, line in enumerate(value.split("\n")):
            self.screen.blit(native_font.render(line, True, color),
                             (round(position[0] * self.ui_render_scale),
                              round((position[1] + index * (font.get_linesize() + 1)) * self.ui_render_scale)))

    def _register_battle_hit(self, rect: pygame.Rect, action: tuple[object, ...], enabled: bool = True) -> None:
        self.buttons.append(UIButton(rect, "", action, enabled))

    def _button(self, rect: pygame.Rect, label: str, action: tuple[object, ...], *,
                enabled: bool = True, selected: bool = False, primary: bool = False) -> None:
        button = UIButton(rect, label, action, enabled, selected, primary)
        self.buttons.append(button)
        hovered = self.mouse_canvas_position is not None and rect.collidepoint(self.mouse_canvas_position)
        native_rect = self._shell_rect(rect)
        self.shell_theme.plate(self.screen, native_rect, "primary" if primary or selected else "button",
                               selected=selected, disabled=not enabled, hover=hovered)
        self.shell_theme.buttons.label(self.screen, native_rect, label,
                                       24 * self.ui_render_scale, INK if enabled else MUTED)

    def _clip(self, value: str, limit: int) -> str:
        return value if len(value) <= limit else value[:max(1, limit - 1)] + "…"

    def _shown_identity(self, identity: str | None, public: bool, is_player: bool) -> str:
        if is_player or public or self.spectator_identity_reveal:
            names = {"lord": "主公", "loyalist": "忠臣", "rebel": "反贼", "turncoat": "内奸",
                     "player_side": "玩家阵营", "ai_side": "电脑阵营", "opposing_side": "对方阵营"}
            return names.get(identity, "身份未知")
        return "身份未知"

    def _identity_label(self, identity: str | None) -> str:
        return {
            "lord": "主公", "loyalist": "忠臣", "rebel": "反贼", "turncoat": "内奸",
            "player_side": "玩家阵营", "ai_side": "电脑阵营", "opposing_side": "对方阵营",
        }.get(identity, "身份未定")

    def _action_label(self, engine: GameEngine, action: GameAction) -> str:
        label = action.label
        if action.intent.target_ids:
            target = next((item for item in engine.state.players if item.player_id == action.intent.target_ids[0]), None)
            if target:
                label += f" → {HERO_BY_ID[target.hero_id].name}"
        return self._clip(label, 21)

    def _scroll(self, amount: int, position: tuple[int, int]) -> None:
        if self.page == "game" and self.engine:
            if not self.pause_open and not self.confirm_kind:
                self.battle_ui.scroll(self, amount, position)
            return
        self.shell_layout.scroll(amount, position)

    def _escape(self) -> None:
        if self.page == "detail_editor":
            self.detail_editor.close()
            return
        if self.deal_started_ms is not None or self.outcome_started_ms is not None:
            return
        if self.audio_slider_drag:
            field = self.audio_slider_drag
            self.audio_slider_drag = None
            self._set_audio_volume(field, getattr(self.settings, field))
        if self.page == "identity" and self.shell_layout.identity_flipping:
            return
        if self.confirm_kind:
            self.confirm_kind = None
        elif self.page == "tutorial":
            self._back()
        elif self.page in {"tutorial_index", "hero_album", "card_album", "rules_help", "settings", "records"}:
            self._back()
        elif self.pause_open:
            self.pause_open = False
        elif self.page == "game":
            if self.battle_ui.details_open or self.battle_ui.log_open:
                details_was_open = self.battle_ui.details_open
                self.battle_ui.cancel()
                if details_was_open:
                    self.pause_open = True
            elif self.engine and self.engine.pending_request and self.selected_choices:
                self.selected_choices.clear()
            elif self.guided_tutorial and (self.battle_ui.selected_card or self.battle_ui.targets):
                self.battle_ui.activate(self, ("battle_cancel",))
            elif not self.battle_ui.cancel():
                self.pause_open = True
        elif self.page == "setup" and self.shell_layout.setup_stage != "config":
            if self.shell_layout.setup_stage == "readonly":
                self.page = "roster"
            else:
                self.shell_layout.setup_stage = "config"
        elif self.page in {"setup", "roster", "identity", "objective"}:
            self.confirm_kind = "abandon_setup"
        elif self.page == "result":
            self.page = "menu"

    def _activate(self, action: tuple[object, ...]) -> None:
        diagnostics.action(self, action)
        name, *arguments = action
        if self.outcome_started_ms is not None or self.deal_started_ms is not None:
            return
        if self.page == "identity" and self.shell_layout.identity_flipping and name in {"roster_back", "confirm_identity", "show_own_identity"}:
            return
        if self.guided_tutorial and self.page == "game" and not str(name).startswith("battle_"):
            if not self.guided_tutorial.allow(self, action):
                return
        self.audio.play_feedback("ui_click")
        if name in {"open_detail_editor", "battle_details"}:
            self.detail_editor.open()
        elif str(name).startswith("detail_"):
            self.detail_editor.activate(action)
        elif str(name).startswith("battle_") and self.engine:
            self.battle_ui.activate(self, action)
        elif name == "practice_exit":
            self._exit_practice()
        elif name == "practice_hint" and self.guided_tutorial:
            if not self.guided_tutorial.completed:
                self.guided_tutorial.message = ""
        elif name == "practice_next" and self.guided_tutorial:
            if self.guided_tutorial.completed:
                scene = self.guided_tutorial.step.scene
                if self.guided_tutorial.next():
                    if self.guided_tutorial.step.scene != scene:
                        self._load_practice_scene()
                    else:
                        self.guided_tutorial.prepare_step(self.engine)
                else:
                    self._exit_practice()
        elif name == "setup_next" and self.page == "setup":
            self.shell_layout.setup_stage = "hero"
        elif name == "setup_config" and self.page == "setup":
            self.shell_layout.setup_stage = "config"
        elif name == "roster_config" and self.page == "roster":
            self.shell_layout.setup_stage = "readonly"
            self.page = "setup"
        elif name == "roster_back":
            self.page = "roster"
        elif name == "show_own_identity" and self.page == "identity":
            if not self.shell_layout.identity_revealed and not self.shell_layout.identity_flipping:
                self.audio.play_feedback("identity_reveal")
            self.shell_layout.begin_identity_flip()
        elif name == "hero_strip" and self.page == "setup":
            self.hero_scroll = max(0, min(max(0, len(self.candidates) - 5), self.hero_scroll + int(arguments[0])))
        elif name == "select_tutorial" and self.page == "tutorial_index":
            self.tutorial_id = str(arguments[0])
        elif name == "back":
            self._back()
        elif name == "open_tutorials":
            self._open_page("tutorial_index")
        elif name == "start_tutorial":
            if str(arguments[0]) in {"basic", "advanced", "modes"}:
                self._start_practice(str(arguments[0]))
                return
            self.tutorial_id = str(arguments[0])
            self.tutorial_step_index = 0
            self.tutorial_selection = None
            self.tutorial_answered = False
            self._open_page("tutorial")
        elif name == "tutorial_answer":
            if self.page == "tutorial" and not self.tutorial_answered:
                self.tutorial_selection = int(arguments[0])
                self.tutorial_answered = True
        elif name == "tutorial_next":
            lesson = TUTORIAL_BY_ID[self.tutorial_id]
            if self.tutorial_step_index + 1 < len(lesson.steps):
                self.tutorial_step_index += 1
                self.tutorial_selection = None
                self.tutorial_answered = False
            else:
                self.page = "tutorial_index"
                if self.page_stack and self.page_stack[-1] == "tutorial_index":
                    self.page_stack.pop()
                self.tutorial_selection = None
                self.tutorial_answered = False
        elif name == "open_hero_album":
            if self.page == "rules_help" and self.engine:
                self.hero_album_mode = self.engine.state.mode_id
            self._open_page("hero_album")
        elif name == "hero_album_mode":
            self.hero_album_mode = str(arguments[0])
            self.hero_album_scroll = 0
        elif name == "hero_album_select":
            self.hero_album_selection = str(arguments[0])
            self.hero_album_scroll = 0
        elif name == "open_card_album":
            self._open_page("card_album")
        elif name == "card_category":
            category_value = str(arguments[0])
            self.card_album_category = None if category_value == "all" else CardCategory(category_value)
            self.card_album_index = 0
            choices = tuple(card for card in CARD_DEFINITIONS
                            if self.card_album_category is None or card.category is self.card_album_category)
            self.selected_card_id = choices[0].definition_id
        elif name == "card_select":
            self.selected_card_id = str(arguments[0])
            self.shell_layout.card_rule_scroll = 0
        elif name == "card_page":
            filtered = tuple(card for card in CARD_DEFINITIONS
                             if self.card_album_category is None or card.category is self.card_album_category)
            self.card_album_index = max(0, min(max(0, (len(filtered) - 1) // 12),
                                               self.card_album_index + int(arguments[0])))
            visible = filtered[self.card_album_index * 12:self.card_album_index * 12 + 12]
            if visible and not any(card.definition_id == self.selected_card_id for card in visible):
                self.selected_card_id = visible[0].definition_id
        elif name == "open_rules_help":
            if self.page == "game" and self.engine:
                self.help_mode = self.engine.state.mode_id
            self._open_page("rules_help")
        elif name == "help_mode":
            self.help_mode = str(arguments[0])
        elif name == "open_settings":
            self._open_page("settings")
        elif name == "volume_change" and self.page == "settings":
            self._set_audio_volume(str(arguments[0]), getattr(self.settings, str(arguments[0])) + float(arguments[1]))
        elif name == "volume_set" and self.page == "settings":
            self._set_audio_volume(str(arguments[0]), float(arguments[1]))
        elif name.startswith("cycle_"):
            self._cycle_setting(name)
        elif name == "open_records":
            self._open_page("records")
        elif name == "records_filter":
            self.records_filter = str(arguments[0])
            self.records_scroll = 0
        elif name == "records_scroll":
            self.records_scroll = max(0, self.records_scroll + int(arguments[0]))
        elif name == "quit":
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        elif name == "open_setup":
            self.page_stack.clear()
            self._reset_setup()
            self.page = "setup"
        elif name == "mode":
            if self.page == "setup" and self.shell_layout.setup_stage == "config":
                self.selected_mode = str(arguments[0])
        elif name == "difficulty":
            if self.page == "setup" and self.shell_layout.setup_stage == "config":
                self.selected_difficulty = Difficulty(str(arguments[0]))
        elif name == "hero_method":
            if self.page == "setup" and self.shell_layout.setup_stage == "config":
                self._set_hero_method(str(arguments[0]))
        elif name == "hero":
            if self.page == "setup" and self.hero_method != "full_random":
                self.selected_hero = str(arguments[0])
                self.shell_layout.setup_skill_scroll = 0
        elif name == "identity":
            if self.page == "setup":
                self.identity_choice = arguments[0] if arguments[0] is None else str(arguments[0])
        elif name == "start_match":
            self._start_match()
        elif name == "lock_roster":
            self._lock_roster()
        elif name == "reveal_identity" and self.page == "roster":
            if self.roster and self.roster.mode_id == "five_player_identity":
                self.page = "identity"
        elif name == "confirm_identity" and self.page == "identity" and self.shell_layout.identity_revealed:
            self.page = "objective"
        elif name == "show_identity" and self.page == "objective":
            self.page = "identity"
        elif name == "confirm":
            self.confirm_kind = str(arguments[0])
        elif name == "confirm_yes":
            self._confirm_yes()
        elif name == "confirm_no":
            self.confirm_kind = None
        elif name == "pause":
            self.pause_open = True
        elif name == "resume":
            self.pause_open = False
        elif name == "submit_action" and self.engine:
            self.engine.submit_action(arguments[0].intent)  # type: ignore[union-attr]
            self._after_engine_step()
        elif name == "end_play" and self.engine and self.engine.is_human_turn:
            self.engine.end_play_phase()
            self._after_engine_step()
        elif name == "toggle_choice":
            choice_id = str(arguments[0])
            if choice_id in self.selected_choices:
                self.selected_choices.remove(choice_id)
            else:
                request = self.engine.pending_request if self.engine else None
                if request and request.kind in {"axe_payment", "ganglie"}:
                    if choice_id in {"pass", "damage"}:
                        self.selected_choices.clear()
                    elif choice_id.startswith("discard:"):
                        self.selected_choices.difference_update({"pass", "damage"})
                if request and len(self.selected_choices) < request.max_choices:
                    self.selected_choices.add(choice_id)
        elif name == "clear_choices":
            self.selected_choices.clear()
        elif name == "answer_prompt" and self.engine and self.engine.pending_request:
            request = self.engine.pending_request
            choices = tuple(option.choice_id for option in request.options if option.choice_id in self.selected_choices)
            if request.kind in {"axe_payment", "ganglie"}:
                if choices == ("pass",) or choices == ("damage",):
                    pass
                elif len(choices) != 2 or not all(item.startswith("discard:") for item in choices):
                    return
            self.engine.answer_prompt(choices[0] if len(choices) == 1 else choices)
            self.selected_choices.clear()
            self.prompt_scroll = 0
            self._after_engine_step()
        elif name == "action_scroll":
            if self.engine:
                actions = self.engine.available_actions("P1") if self.engine.is_human_turn else ()
                self.action_scroll = max(0, min(max(0, len(actions) - 3), self.action_scroll + int(arguments[0])))
        elif name == "prompt_scroll":
            if self.engine and self.engine.pending_request:
                self.prompt_scroll = max(0, min(max(0, len(self.engine.pending_request.options) - 7),
                                                self.prompt_scroll + int(arguments[0])))
        elif name == "spectator_speed":
            self._change_spectator_speed(int(arguments[0]))
        elif name == "spectator_auto" and self.engine:
            self.spectator_auto = True
            self.engine.continue_spectator()
            self._after_engine_step()
        elif name == "spectator_manual":
            self.spectator_auto = False
            self.pause_open = False
        elif name == "spectator_continue" and self.engine:
            self.spectator_auto = False
            self.engine.continue_spectator(fast_forward=bool(arguments[0]))
            self._after_engine_step()
        elif name == "spectator_reveal_identity":
            if self.engine and self.spectator_identity_reveal:
                self.spectator_identity_reveal = False
            elif self.engine and self.engine.spectator_reveal_identities:
                self.spectator_identity_reveal = True
            elif self.engine:
                self.confirm_kind = "reveal_identity"
        elif name == "spectator_reveal_hands":
            if self.engine and self.spectator_hand_reveal:
                self.spectator_hand_reveal = False
            elif self.engine and self.engine.spectator_reveal_hands:
                self.spectator_hand_reveal = True
            elif self.engine:
                self.confirm_kind = "reveal_hands"
        elif name == "spectator_exit":
            self.confirm_kind = "spectator_exit"
        elif name == "restart_from_result":
            self._restart_match()
        elif name == "to_menu":
            self._clear_ai_display_pause()
            self.engine = None
            self.roster = None
            self.page_stack.clear()
            self.overlay_return = "menu"
            self.page = "menu"

    def _open_page(self, page: str) -> None:
        if not self.page_stack:
            self.overlay_return = self.page
        self.page_stack.append(self.page)
        if self.page == "game":
            self.pause_open = True
        self.page = page

    def _back(self) -> None:
        if self.page == "tutorial":
            self.tutorial_selection = None
            self.tutorial_answered = False
        if self.page_stack:
            self.page = self.page_stack.pop()
        else:
            self.page = self.overlay_return
        if not self.page_stack:
            self.overlay_return = self.page
        if self.page == "game":
            self.pause_open = True
        elif self.page == "menu":
            self.pause_open = False

    def _set_audio_volume(self, field: str, value: float, *, persist: bool = True) -> None:
        if field not in {"music_volume", "voice_volume", "effects_volume"}:
            return
        volume = round(max(0.0, min(1.0, value)), 2)
        candidate = replace(self.settings, **{field: volume})
        self.settings = candidate
        self.audio.apply_settings(candidate)
        if not persist:
            return
        try:
            save_settings(candidate)
            self.settings_message = "音量已保存。"
        except OSError:
            self.settings_message = "音量已生效，保存失败。"

    def _cycle_setting(self, action: str) -> None:
        current = self.settings
        if action == "cycle_window_mode":
            candidate = replace(current, window_mode=(
                WindowMode.BORDERLESS_FULLSCREEN if current.window_mode is WindowMode.WINDOWED
                else WindowMode.WINDOWED))
        elif action == "cycle_resolution":
            options = ((1280, 720), (1600, 900))
            try:
                index = options.index((current.resolution_width, current.resolution_height))
            except ValueError:
                index = -1
            width, height = options[(index + 1) % len(options)]
            candidate = replace(current, resolution_width=width, resolution_height=height)
        elif action == "cycle_ui_scale":
            options = (0.85, 1.0, 1.15, 1.3)
            index = min(range(len(options)), key=lambda i: abs(options[i] - current.ui_scale))
            candidate = replace(current, ui_scale=options[(index + 1) % len(options)])
        elif action == "cycle_ai_speed":
            options = tuple(AiDisplaySpeed)
            candidate = replace(current, ai_display_speed=options[(options.index(current.ai_display_speed) + 1) % len(options)])
        elif action == "cycle_skill_animation":
            options = tuple(SkillAnimation)
            candidate = replace(current, skill_animation=options[(options.index(current.skill_animation) + 1) % len(options)])
        else:
            return
        try:
            self._configure_display(candidate)
            save_settings(candidate)
        except (OSError, pygame.error, ValueError) as error:
            self.settings = current
            try:
                self._configure_display(current)
            except pygame.error:
                pass
            self.settings_message = f"设置未保存：{error}"
            return
        self.settings = candidate
        self.settings_message = "设置已应用并保存。"

    def _configure_display(self, settings: Settings) -> None:
        if settings.window_mode is WindowMode.BORDERLESS_FULLSCREEN:
            info = pygame.display.Info()
            size = (max(1, info.current_w), max(1, info.current_h))
            self.display = pygame.display.set_mode(size, pygame.NOFRAME)
        else:
            self.display = pygame.display.set_mode(
                (settings.resolution_width, settings.resolution_height), pygame.RESIZABLE,
            )
        scale = settings.ui_scale
        self.font = ui_font("microsoftyahei", max(14, round(22 * scale)))
        self.small_font = ui_font("microsoftyahei", max(12, round(17 * scale)))
        self.tiny_font = ui_font("microsoftyahei", max(10, round(14 * scale)))
        self.big_font = ui_font("microsoftyahei", max(22, round(34 * scale)))

    def _reset_setup(self) -> None:
        self.shell_layout.reset()
        self.selected_mode = "duel"
        self.selected_difficulty = Difficulty.SIMPLE
        self.hero_method = "free_choice"
        self.candidates = HERO_IDS
        self.selected_hero = HERO_IDS[0]
        self.hero_scroll = 0
        self.identity_choice = None
        self.setup_seed = randbits(32)
        self.roster = None
        self.pending_match_state = None

    def _lock_roster(self) -> None:
        if self.page != "setup" or self.shell_layout.setup_stage == "readonly":
            return
        player_identity = None
        if self.selected_mode == "five_player_identity" and self.identity_choice:
            player_identity = Identity(self.identity_choice)
        self.roster = resolve_roster(
            mode_id=self.selected_mode,
            player_hero_id=self.selected_hero,
            seed=self.setup_seed,
            player_identity=player_identity,
            difficulty=self.selected_difficulty,
        )
        self.pending_match_state = create_match(self.roster)
        self.recorded_match = False
        self.page = "roster"

    def _set_hero_method(self, method: str) -> None:
        self.hero_method = method
        if method == "random_three_choose_one":
            self.candidates = random_hero_candidates(FixedSeedRandom(self.setup_seed))
            self.selected_hero = self.candidates[0]
            self.hero_scroll = 0
        elif method == "full_random":
            stream = FixedSeedRandom(self.setup_seed)
            self.selected_hero = stream.choice(HERO_IDS)
            self.candidates = (self.selected_hero,)
            self.hero_scroll = 0
        else:
            self.candidates = HERO_IDS
            self.hero_scroll = max(0, min(self.hero_scroll, len(self.candidates) - 9))
            if self.selected_hero not in self.candidates:
                self.selected_hero = self.candidates[0]

    def _start_match(self) -> None:
        if self.roster is None or self.pending_match_state is None:
            return
        if self.roster.mode_id == "five_player_identity":
            if self.page != "objective":
                return
        elif self.page != "roster":
            return
        policies = make_ai_policies(
            self.pending_match_state.players,
            seed=self.roster.seed,
            difficulty=self.roster.difficulty,
        )
        self._clear_ai_display_pause()
        self.engine = GameEngine(self.pending_match_state, ai_by_player=policies,
                                 display_pacing_enabled=True, presentation_enabled=True)
        self.battle_ui.reset()
        self.ai_presentation_started_ms = None
        self.pending_match_state = None
        self.recorded_match = False
        self.record_save_error = ""
        self.pause_open = False
        self.confirm_kind = None
        self.selected_choices.clear()
        self.spectator_identity_reveal = False
        self.spectator_hand_reveal = False
        self.spectator_auto = False
        self.spectator_display_speed = None
        self.outcome_started_ms = None
        self.page = "game"
        self.deal_started_ms = self.deal_last_tick_ms = pygame.time.get_ticks()

    def _start_practice(self, lesson_id: str = "basic") -> None:
        if self.guided_tutorial:
            return
        fields = ("engine", "roster", "pending_match_state", "battle_ui", "recorded_match",
                  "record_save_error", "last_result_text", "pause_open", "confirm_kind",
                  "selected_choices", "action_scroll", "prompt_scroll", "log_scroll",
                  "spectator_identity_reveal", "spectator_hand_reveal", "overlay_return",
                  "ai_display_deadline_ms", "ai_display_delay_ms", "ai_display_last_tick_ms",
                  "ai_presentation_started_ms")
        fields += ("spectator_auto", "spectator_display_speed", "deal_started_ms", "deal_last_tick_ms", "outcome_started_ms")
        self._practice_saved = {field: getattr(self, field) for field in fields}
        self._practice_saved["page_stack"] = list(self.page_stack)
        self._practice_started_ms = pygame.time.get_ticks()
        self.guided_tutorial = create_tutorial(lesson_id)
        self.selected_choices = set()
        self._load_practice_scene()

    def _load_practice_scene(self) -> None:
        if not self.guided_tutorial:
            return
        self._clear_ai_display_pause()
        self.ai_presentation_started_ms = None
        self.roster, self.engine = self.guided_tutorial.create_scene()
        self.battle_ui = BattleUI()
        self.selected_choices.clear()
        self.pause_open = False
        self.confirm_kind = None
        self.recorded_match = False
        self.record_save_error = ""
        self.spectator_identity_reveal = self.spectator_hand_reveal = False
        self.spectator_auto = False
        self.spectator_display_speed = None
        self.deal_started_ms = self.deal_last_tick_ms = self.outcome_started_ms = None
        self.page = "game"
        self.engine.start()
        self._after_engine_step()

    def _exit_practice(self) -> None:
        saved = self._practice_saved
        if saved is None:
            return
        now = pygame.time.get_ticks()
        elapsed = now - self._practice_started_ms
        for field, value in saved.items():
            setattr(self, field, value)
        # Preserve the suspended real match's display interval across practice.
        if self.ai_display_deadline_ms is not None:
            self.ai_display_deadline_ms += elapsed
        if self.ai_presentation_started_ms is not None:
            self.ai_presentation_started_ms += elapsed
        self.ai_display_last_tick_ms = now
        self.battle_ui.last_tick = now
        self.guided_tutorial = None
        self._practice_saved = None
        self.page = "tutorial_index"

    def _restart_practice_scene(self) -> None:
        if not self.guided_tutorial:
            return
        self.guided_tutorial.index = self.guided_tutorial.restart_index()
        self._load_practice_scene()

    def _after_engine_step(self) -> None:
        if self.guided_tutorial:
            self.guided_tutorial.observe(self)
            if self.engine and self.engine.display_waiting:
                self._arm_ai_display_pause()
            else:
                self._clear_ai_display_pause()
            if self.engine and self.engine.finished and not self.guided_tutorial.completed:
                self.guided_tutorial.message = "本练习已结束，可重新练习当前场景或退出教学。"
            return
        if self.engine and self.engine.finished:
            self._clear_ai_display_pause()
            self._persist_result()
            self.last_result_text = next((event.text for event in reversed(self.engine.public_logs())
                                          if "对局结束" in event.text or "平局结束" in event.text or "玩家认输" in event.text),
                                         "对局已经结束。")
            if self.outcome_started_ms is None and self.page != "result":
                self.outcome_started_ms = pygame.time.get_ticks()
            self.spectator_auto = False
            self.spectator_display_speed = None
            self.pause_open = False
            self.confirm_kind = None
        elif self.engine and self.engine.display_waiting:
            self._arm_ai_display_pause()
        else:
            self._clear_ai_display_pause()

    def _persist_result(self) -> None:
        if self.guided_tutorial or not self.engine or self.recorded_match:
            return
        player = next((item for item in self.engine.state.players if item.player_id == "P1"), None)
        record = new_record_summary(
            record_id=f"{self.setup_seed:08x}-{self.engine.state.turn_number}-{randbits(16):04x}",
            mode_id=self.engine.state.mode_id,
            difficulty=(self.roster.difficulty.value if self.roster else Difficulty.SIMPLE.value),
            player_hero_id=player.hero_id if player else None,
            player_identity=player.identity if player else None,
            result=self.engine.player_outcome or "unfinished",
            end_reason=self.engine.state.end_reason or "unknown",
            turn_count=self.engine.state.turn_number,
        )
        try:
            append_record_summary(record)
        except OSError as error:
            self.record_save_error = f"战绩保存失败：{error}。原有记录已保留。"
            self.recorded_match = True
            return
        self.record_save_error = ""
        self.recorded_match = True

    def _restart_match(self) -> None:
        self._clear_ai_display_pause()
        self.engine = None
        self.roster = None
        self.recorded_match = False
        self.pause_open = False
        self.confirm_kind = None
        self._reset_setup()
        self.page = "setup"

    def _confirm_yes(self) -> None:
        kind = self.confirm_kind
        self.confirm_kind = None
        if self.guided_tutorial and kind in {"resign", "restart", "exit_to_menu"}:
            if kind == "restart":
                self._restart_practice_scene()
            else:
                self._exit_practice()
            return
        if kind == "abandon_setup":
            self._reset_setup()
            self.page = "menu"
        elif kind == "resign" and self.engine:
            self.engine.resign()
            self._after_engine_step()
        elif kind == "restart" and self.engine:
            self.engine.resign(end_reason="restart")
            self._persist_result()
            self._restart_match()
        elif kind == "exit_to_menu" and self.engine:
            self.engine.exit_unfinished()
            self._persist_result()
            self._clear_ai_display_pause()
            self.engine = None
            self.roster = None
            self.pause_open = False
            self.page = "menu"
        elif kind == "clear_records":
            try:
                clear_record_summaries()
                self.records_message = "战绩已清除；设置保持不变。"
            except OSError as error:
                self.records_message = f"清除失败：{error}。原有战绩已保留。"
        elif kind == "reveal_identity" and self.engine:
            self.engine.reveal_identities_for_spectator()
            self.spectator_identity_reveal = True
        elif kind == "reveal_hands" and self.engine:
            self.engine.reveal_hands_for_spectator()
            self.spectator_hand_reveal = True
        elif kind == "spectator_exit" and self.engine:
            self.engine.continue_spectator(fast_forward=True)
            self._after_engine_step()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="像素三国卡牌战正式入口")
    parser.add_argument("--smoke-test", action="store_true", help="绘制一次标题页后退出")
    arguments = parser.parse_args(argv)
    diagnostics.start()
    try:
        pygame.init()
        settings = load_settings()
        if settings.window_mode is WindowMode.BORDERLESS_FULLSCREEN:
            info = pygame.display.Info()
            screen = pygame.display.set_mode((max(1, info.current_w), max(1, info.current_h)), pygame.NOFRAME)
        else:
            screen = pygame.display.set_mode(
                (settings.resolution_width, settings.resolution_height), pygame.RESIZABLE,
            )
        pygame.display.set_caption(f"像素三国卡牌战 · {APP_VERSION} · 对局UI v12")
        app = Stage1App(screen, settings)
        app._configure_display(settings)
        app._draw()
        app._present()
        if arguments.smoke_test:
            return 0
        app.run()
        return 0
    except BaseException:
        diagnostics.exception()
        raise
    finally:
        pygame.quit()
        diagnostics.stop()
