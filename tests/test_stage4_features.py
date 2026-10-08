from __future__ import annotations

import unittest
from unittest.mock import patch

import _support
import pygame
from xssgkpz.app import Stage1App
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import create_match, resolve_roster
from xssgkpz.data.cards import CARD_DEFINITIONS, CardCategory
from xssgkpz.data.settings import Settings
from xssgkpz.data.tutorials import TUTORIALS, TUTORIAL_BY_ID


REQUIRED_TUTORIAL_COVERAGE = {
    "basic": {
        "card_selection": ("选择手牌",),
        "target_selection": ("合法目标",),
        "confirm": ("确认",),
        "cancel": ("取消", "尚未确认"),
        "sha": ("杀",),
        "shan": ("闪",),
        "tao": ("桃", "濒死"),
        "end_phase": ("结束出牌阶段", "弃牌"),
    },
    "advanced": {
        "distance": ("距离", "攻击范围"),
        "equipment": ("装备", "时机"),
        "trick": ("锦囊", "过河拆桥"),
        "judgment": ("判定牌", "鬼才"),
        "near_death": ("濒死", "桃"),
        "skill_timing": ("技能", "触发时机"),
    },
    "modes": {
        "duel_goal": ("斗将", "击败唯一对手"),
        "duel_special": ("先手随机", "只摸一张"),
        "two_heroes_goal": ("同阵营", "击败两人获胜"),
        "two_heroes_special": ("体力各加1", "每回合摸牌数不增加"),
        "identity_roles": ("一主公", "两反贼", "一内奸"),
        "identity_goals": ("主公与忠臣", "内奸获胜"),
        "identity_privacy": ("自己的身份可见", "其他存活者身份保密"),
        "identity_special": ("主公先行动", "击杀反贼摸三张", "误杀忠臣"),
    },
}


class Stage4NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.font.init()
        pygame.display.init()
        cls.screen = pygame.display.set_mode((1280, 720), pygame.HIDDEN)

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.display.quit()
        pygame.font.quit()

    def make_app(self) -> Stage1App:
        return Stage1App(self.screen, Settings())

    def test_menu_and_independent_lessons_have_live_navigation(self) -> None:
        app = self.make_app()
        original_seed = app.setup_seed
        app._draw()
        actions = {button.action for button in app.buttons}
        for expected in ("open_setup", "open_tutorials", "open_hero_album", "open_card_album",
                         "open_records", "open_settings", "quit"):
            self.assertIn((expected,), actions)

        app._activate(("open_tutorials",))
        self.assertEqual(app.page, "tutorial_index")
        app._activate(("start_tutorial", "advanced"))
        self.assertEqual(app.page, "game")
        self.assertEqual(app.guided_tutorial.title, "进阶规则")
        self.assertIsNotNone(app.engine)
        self.assertGreaterEqual(len(app.guided_tutorial.steps), 5)
        app._activate(("practice_exit",))
        self.assertEqual(app.page, "tutorial_index")
        self.assertEqual(app.setup_seed, original_seed)
        self.assertIsNone(app.engine)

    def test_tutorial_steps_cover_each_required_topic_in_visible_copy(self) -> None:
        lessons = {lesson.lesson_id: lesson for lesson in TUTORIALS}
        self.assertEqual(set(lessons), set(REQUIRED_TUTORIAL_COVERAGE))
        for lesson_id, requirements in REQUIRED_TUTORIAL_COVERAGE.items():
            steps = lessons[lesson_id].steps
            tagged = set().union(*(step.coverage_tags for step in steps))
            self.assertLessEqual(set(requirements), tagged, lesson_id)
            for tag, markers in requirements.items():
                with self.subTest(lesson=lesson_id, topic=tag):
                    candidates = [step for step in steps if tag in step.coverage_tags]
                    self.assertTrue(candidates, f"missing tagged step: {lesson_id}/{tag}")
                    visible_copy = [" ".join((step.title, step.prompt, *step.choices, step.feedback))
                                    for step in candidates]
                    self.assertTrue(
                        any(all(marker in text for marker in markers) for text in visible_copy),
                        f"visible teaching copy missing {markers}: {lesson_id}/{tag}",
                    )

    def test_card_album_filters_the_shared_full_catalog(self) -> None:
        app = self.make_app()
        app._activate(("open_card_album",))
        app._draw()
        self.assertEqual(len(CARD_DEFINITIONS), 108)
        app._activate(("card_category", CardCategory.EQUIPMENT.value))
        self.assertIs(app.card_album_category, CardCategory.EQUIPMENT)
        app._draw()
        self.assertEqual(app.card_album_index, 0)
        self.assertIn(app.selected_card_id, {card.definition_id for card in CARD_DEFINITIONS
                                             if card.category is CardCategory.EQUIPMENT})

    def test_all_stage4_pages_draw_at_the_project_canvas_size(self) -> None:
        app = self.make_app()
        with patch("xssgkpz.app.load_record_summaries", return_value=()):
            for page in ("menu", "tutorial_index", "tutorial", "hero_album", "card_album",
                         "rules_help", "settings", "records"):
                with self.subTest(page=page):
                    app.page = page
                    app._draw()
                    self.assertTrue(app.buttons)
            for lesson in TUTORIALS:
                app.page = "tutorial"
                app.tutorial_id = lesson.lesson_id
                app.tutorial_answered = True
                for index, step in enumerate(lesson.steps):
                    with self.subTest(lesson=lesson.lesson_id, step=index, feedback=True):
                        app.tutorial_step_index = index
                        app.tutorial_selection = step.answer_index
                        app._draw()
                        self.assertTrue(app.buttons)

    def test_settings_preserve_an_active_match_and_report_save_failure(self) -> None:
        app = self.make_app()
        app.page = "game"
        app.pause_open = True
        engine = object()
        pending_state = object()
        app.engine = engine  # type: ignore[assignment]
        app.pending_match_state = pending_state
        app.selected_choices = {"keep-selection"}
        seed = app.setup_seed
        old_settings = app.settings
        app._open_page("settings")
        with patch.object(app, "_configure_display"), patch("xssgkpz.app.save_settings", side_effect=OSError("disk full")):
            app._activate(("cycle_ui_scale",))
        self.assertIs(app.engine, engine)
        self.assertIs(app.pending_match_state, pending_state)
        self.assertEqual(app.selected_choices, {"keep-selection"})
        self.assertEqual(app.setup_seed, seed)
        self.assertEqual(app.settings, old_settings)
        self.assertIn("保存", app.settings_message)
        app._activate(("back",))
        self.assertEqual(app.page, "game")
        self.assertTrue(app.pause_open)
        app._open_page("settings")
        app._escape()
        self.assertEqual(app.page, "game")
        self.assertTrue(app.pause_open)

    def test_exit_to_menu_records_unfinished_and_confirm_is_required(self) -> None:
        app = self.make_app()
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=1234)
        app.roster = roster
        app.engine = GameEngine(create_match(roster))
        app.page = "game"
        app.pause_open = True
        app._activate(("confirm", "exit_to_menu"))
        self.assertEqual(app.page, "game")
        self.assertEqual(app.confirm_kind, "exit_to_menu")
        with patch("xssgkpz.app.append_record_summary") as append:
            app._activate(("confirm_yes",))
        record = append.call_args.args[0]
        self.assertEqual(record.result, "unfinished")
        self.assertEqual(record.end_reason, "exit_to_menu")
        self.assertEqual(app.page, "menu")
        self.assertIsNone(app.engine)

    def test_pause_help_uses_the_active_match_mode_for_skill_availability(self) -> None:
        app = self.make_app()
        roster = resolve_roster(mode_id="two_heroes", player_hero_id="caocao", seed=4321)
        app.engine = GameEngine(create_match(roster))
        app.page = "game"
        app.pause_open = True
        app._activate(("open_rules_help",))
        self.assertEqual(app.help_mode, "two_heroes")
        app._activate(("open_hero_album",))
        self.assertEqual(app.hero_album_mode, "two_heroes")
        app._activate(("back",))
        self.assertEqual(app.page, "rules_help")
        app._activate(("back",))
        self.assertEqual(app.page, "game")
        self.assertTrue(app.pause_open)

    def test_clear_records_has_a_confirmation_and_does_not_touch_settings(self) -> None:
        app = self.make_app()
        settings_before = app.settings
        app.page = "records"
        app._activate(("confirm", "clear_records"))
        self.assertEqual(app.confirm_kind, "clear_records")
        with patch("xssgkpz.app.clear_record_summaries") as clear:
            app._activate(("confirm_yes",))
        clear.assert_called_once_with()
        self.assertEqual(app.settings, settings_before)
        self.assertIn("战绩已清除", app.records_message)


if __name__ == "__main__":
    unittest.main()
