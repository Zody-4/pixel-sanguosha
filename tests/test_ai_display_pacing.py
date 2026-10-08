from __future__ import annotations

import unittest
from unittest.mock import patch

import _support
import pygame
from xssgkpz.app import AI_DISPLAY_PAUSE_MS, Stage1App
from xssgkpz.core.ai import make_ai_policies
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import create_match, resolve_roster
from xssgkpz.core.state import GamePhase, Visibility, snapshot_game_state
from xssgkpz.data.cards import CARD_BY_ID
from xssgkpz.data.settings import AiDisplaySpeed, Settings


class AiDisplayPacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.font.init()
        pygame.display.init()
        cls.screen = pygame.display.set_mode((1280, 720), pygame.HIDDEN)

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.display.quit()
        pygame.font.quit()

    @staticmethod
    def make_ai_engine(*, display_pacing: bool = True) -> GameEngine:
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=98231)
        state = create_match(roster, human_player_ids=frozenset())
        state.current_player_id = "AI1"
        policies = make_ai_policies(state.players, seed=roster.seed,
                                    difficulty=roster.difficulty)
        engine = GameEngine(state, ai_by_player=policies, auto_turn_limit=1,
                            display_pacing_enabled=display_pacing)
        engine.start()
        return engine

    def test_speed_timers_are_relative_nonblocking_and_keep_current_pause_duration(self) -> None:
        self.assertEqual(AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.NORMAL], 1_800)
        self.assertEqual(AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.FAST], 800)
        self.assertEqual(AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.INSTANT], 10)
        self.assertGreater(AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.NORMAL],
                           AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.FAST])
        self.assertGreater(AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.FAST],
                           AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.INSTANT])
        self.assertEqual(AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.INSTANT], 10)

        for speed, duration in AI_DISPLAY_PAUSE_MS.items():
            with self.subTest(speed=speed):
                app = Stage1App(self.screen, Settings(ai_display_speed=speed))
                app.page = "game"
                app.engine = self.make_ai_engine()
                self.assertTrue(app.engine.display_waiting)
                before_pause = snapshot_game_state(app.engine.state)
                app._after_engine_step()
                self.assertEqual(app.ai_display_delay_ms, duration)
                app._mark_ai_display_step_presented(now_ms=1_000)
                self.assertEqual(app.ai_display_deadline_ms, 1_000 + duration)
                self.assertFalse(app._advance_ai_display_step(now_ms=999 + duration))
                self.assertTrue(app.engine.display_waiting)
                self.assertEqual(snapshot_game_state(app.engine.state), before_pause)

                # A pause/settings overlay does not run the rules generator.
                app.pause_open = True
                self.assertFalse(app._advance_ai_display_step(now_ms=2_000))
                self.assertTrue(app.engine.display_waiting)
                self.assertEqual(snapshot_game_state(app.engine.state), before_pause)
                app.pause_open = False
                self.assertTrue(app._advance_ai_display_step(now_ms=app.ai_display_deadline_ms))
                self.assertTrue(app.engine.display_waiting)
                self.assertEqual(app.ai_display_delay_ms, duration)

    def test_speed_change_only_applies_to_the_next_display_pause(self) -> None:
        app = Stage1App(self.screen, Settings(ai_display_speed=AiDisplaySpeed.NORMAL))
        app.page = "game"
        app.engine = self.make_ai_engine()
        self.assertTrue(app.engine.display_waiting)
        state_before = snapshot_game_state(app.engine.state)
        random_before = app.engine.state.random_stream.snapshot()
        app.selected_choices = {"preserve-this-choice"}
        setup_seed_before = app.setup_seed
        app._after_engine_step()
        app._mark_ai_display_step_presented(now_ms=100)
        old_deadline = 100 + AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.NORMAL]

        app._open_page("settings")
        with patch.object(app, "_configure_display"), patch("xssgkpz.app.save_settings"):
            app._cycle_setting("cycle_ai_speed")
        self.assertEqual(app.settings.ai_display_speed, AiDisplaySpeed.FAST)
        self.assertEqual(app.ai_display_delay_ms, AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.NORMAL])
        self.assertEqual(app.ai_display_deadline_ms, old_deadline)
        self.assertEqual(snapshot_game_state(app.engine.state), state_before)
        self.assertEqual(app.engine.state.random_stream.snapshot(), random_before)
        self.assertEqual(app.selected_choices, {"preserve-this-choice"})
        self.assertEqual(app.setup_seed, setup_seed_before)

        app._activate(("back",))
        self.assertTrue(app.pause_open)
        self.assertFalse(app._advance_ai_display_step(now_ms=old_deadline))
        app._activate(("resume",))
        self.assertTrue(app._advance_ai_display_step(now_ms=app.ai_display_deadline_ms))
        self.assertEqual(app.ai_display_delay_ms, AI_DISPLAY_PAUSE_MS[AiDisplaySpeed.FAST])

    def test_window_events_are_processed_while_an_ai_display_pause_is_pending(self) -> None:
        app = Stage1App(self.screen, Settings())
        app.engine = self.make_ai_engine()
        app.page = "game"
        app._after_engine_step()
        self.assertIsNotNone(app.ai_display_delay_ms)
        initial_state = snapshot_game_state(app.engine.state)

        drawn_text: list[str] = []
        draw_text = app.battle_ui.text

        def capture_text(value: str, *args, **kwargs) -> None:
            drawn_text.append(value)
            draw_text(value, *args, **kwargs)

        with patch.object(app.battle_ui, "text", side_effect=capture_text):
            app._draw()
        self.assertIn("正在结算", drawn_text)
        app.battle_ui.log_open = True
        with patch.object(app.battle_ui, "text", side_effect=capture_text):
            app._draw()
        latest_visible_log = app.engine.private_logs_for("P1")[-1]
        self.assertIn(latest_visible_log.text, "\n".join(drawn_text))
        app.battle_ui.log_open = False
        self.assertTrue(any(text.endswith("/" + str(player.max_hp))
                            for player in app.engine.state.players
                            for text in drawn_text))

        event_frames = (
            [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)],
            [pygame.event.Event(pygame.QUIT)],
        )
        with patch("pygame.event.get", side_effect=event_frames):
            app.run()
        self.assertTrue(app.pause_open)
        self.assertTrue(app.engine.display_waiting)
        self.assertEqual(snapshot_game_state(app.engine.state), initial_state)

    def test_paced_ai_turn_matches_unpaced_actions_logs_state_and_random_stream(self) -> None:
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=98231)
        results = []
        for paced in (False, True):
            state = create_match(roster, human_player_ids=frozenset())
            state.current_player_id = "AI1"
            policies = make_ai_policies(state.players, seed=roster.seed,
                                        difficulty=roster.difficulty)
            engine = GameEngine(state, ai_by_player=policies, auto_turn_limit=1,
                                display_pacing_enabled=paced)
            engine.start()
            resumes = 0
            while engine.display_waiting:
                engine.resume_display()
                resumes += 1
                self.assertLess(resumes, 40, "display pacing failed to resume the engine")
            self.assertTrue(engine.finished)
            results.append((engine, resumes))

        ordinary, _ordinary_resumes = results[0]
        paced, paced_resumes = results[1]
        self.assertEqual(paced_resumes, len(paced.public_action_history))
        self.assertEqual(paced.public_action_history, ordinary.public_action_history)
        self.assertEqual(paced.logs, ordinary.logs)
        self.assertEqual(snapshot_game_state(paced.state), snapshot_game_state(ordinary.state))
        self.assertEqual(paced.state.random_stream.snapshot(), ordinary.state.random_stream.snapshot())

    def test_player_response_window_is_not_a_display_pause(self) -> None:
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=8821)
        state = create_match(roster)
        state.current_player_id = "AI1"
        state.phase = GamePhase.PLAY

        def move_card_named(engine: GameEngine, name: str, owner_id: str) -> str:
            player = engine._player(owner_id)
            card_id = next(card_id for card_id, card in engine.state.cards.items()
                           if CARD_BY_ID[card.definition_id].name == name)
            engine._move(card_id, player.hand_zone_id, owner_id=owner_id,
                         controller_id=owner_id, visibility=Visibility.OWNER_ONLY)
            return card_id

        engine = GameEngine(state, display_pacing_enabled=True)
        kill_id = move_card_named(engine, "杀", "AI1")
        move_card_named(engine, "闪", "P1")
        random_before_response = engine.state.random_stream.snapshot()

        class _AttackPlayerAI:
            def choose_action(self, _view, actions):
                return next(action for action in actions
                            if action.intent.card_id == kill_id
                            and action.intent.target_ids == ("P1",))

            def choose_option(self, _view, request):
                return next((option.choice_id for option in request.options
                             if option.category == "pass"), request.options[0].choice_id)

        engine.ai_by_player["AI1"] = _AttackPlayerAI()
        engine._drive(engine._run_ai_play(engine._player("AI1")))
        request = engine.pending_request
        self.assertIsNotNone(request)
        self.assertEqual(request.player_id, "P1")
        self.assertEqual(request.kind, "flash")
        self.assertFalse(engine.display_waiting)

        engine.resume_display()
        self.assertIs(engine.pending_request, request)
        self.assertEqual(engine.state.random_stream.snapshot(), random_before_response)

    def test_spectator_fast_forward_bypasses_ai_display_pacing(self) -> None:
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=98231)
        state = create_match(roster, human_player_ids=frozenset())
        state.current_player_id = "AI1"
        policies = make_ai_policies(state.players, seed=roster.seed,
                                    difficulty=roster.difficulty)
        engine = GameEngine(state, ai_by_player=policies, auto_turn_limit=1,
                            display_pacing_enabled=True)
        engine.spectator_waiting = True
        engine.continue_spectator(fast_forward=True)
        self.assertFalse(engine.display_waiting)
        self.assertTrue(engine.finished)


if __name__ == "__main__":
    unittest.main()
