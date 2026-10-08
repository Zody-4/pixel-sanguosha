from __future__ import annotations

import unittest
from unittest.mock import patch, Mock

import _support
import pygame
from test_stage2_rules import make_engine, put_hand, set_hero, RouteAI, action
from xssgkpz.app import Stage1App
from xssgkpz.core.actions import ActionIntent
from xssgkpz.core.state import Visibility, snapshot_game_state, assert_card_zone_invariant
from xssgkpz.data.settings import Settings
from xssgkpz.audio import GameAudio


class BattleUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.font.init()
        pygame.display.init()
        cls.display = pygame.display.set_mode((1600, 900), pygame.HIDDEN)

    @classmethod
    def tearDownClass(cls):
        pygame.display.quit()
        pygame.font.quit()

    def app_for(self, engine):
        engine.presentation_enabled = True
        engine.display_pacing_enabled = True
        app = Stage1App(self.display, Settings())
        app.page = "game"
        app.engine = engine
        app._draw()
        return app

    def advance(self, app):
        self.assertTrue(app.engine.display_waiting)
        app._draw()
        app._after_engine_step()
        app.battle_ui.event_elapsed = app.battle_ui.event_duration + 1
        app._mark_ai_display_step_presented()
        self.assertTrue(app._advance_ai_display_step(now_ms=app.ai_display_deadline_ms + 1))
        app._draw()

    def settle(self, app):
        for _ in range(80):
            if app.engine.display_waiting:
                self.advance(app)
            elif app.engine.pending_request:
                app._activate(("battle_pass",))
            else:
                return
        self.fail("UI did not finish the bounded action")

    def clear_hand(self, engine):
        for cid in tuple(engine._zone("P1.hand").card_ids):
            engine._move(cid, "draw_pile", owner_id=None, controller_id=None, visibility=Visibility.HIDDEN)

    def choose_and_confirm(self, app, cid):
        app._draw()
        app._activate(("battle_card", cid))
        app._draw()
        self.assertTrue(app.selected_choices)
        app._activate(("answer_prompt",))
        app._draw()

    def test_two_nullifications_keep_reference_route_and_restore_effect(self):
        engine = make_engine(hero_id="guanyu")
        self.clear_hand(engine)
        trick = put_hand(engine, "P1", "draw_two")
        counters = [put_hand(engine, "P1", "negate") for _ in range(2)]
        app = self.app_for(engine)
        audio = GameAudio()
        audio.available = True
        audio.channel = Mock()
        audio.effects_channel = Mock()
        audio.effects_channels = [audio.effects_channel]
        app._activate(("battle_card", trick))
        app._activate(("battle_confirm",))
        self.advance(app)
        self.assertEqual(engine.pending_request.kind, "nullification")
        for cid in counters:
            self.choose_and_confirm(app, cid)
            self.assertEqual(engine.presentation_event.kind, "negate")
            self.assertEqual(engine.presentation_event.reference_card_id, trick)
            # Exercise audio dispatch from the real committed negate event;
            # device playback is mocked, so this is not a listening verdict.
            with patch.object(audio, 'apply_settings'), patch.object(audio, '_music'), \
                 patch.object(audio, '_enqueue') as voice, patch.object(audio, 'play_feedback'), \
                 patch.object(audio, '_play_queued'), patch('pygame.mixer.music.unpause'):
                audio.update(app)
                audio.update(app)
                self.assertEqual([c.args[0] for c in voice.call_args_list].count('negate'), 1)
            self.assertEqual(app.battle_ui.main_card, trick)
            app.battle_ui.event_elapsed = 900
            with patch.object(app.battle_ui, "_route", wraps=app.battle_ui._route) as route:
                app._draw()
                self.assertEqual(route.call_args.args[1], (782, 432))
            self.advance(app)
        self.settle(app)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), 2)
        self.assertTrue(all(engine.state.cards[cid].zone_id == "discard_pile" for cid in [trick, *counters]))
        assert_card_zone_invariant(engine.state)

    def test_delayed_tricks_fly_to_actual_judgment_slot(self):
        for kind, owner in (('lightning', 'P1'), ('indulgence', 'AI1')):
            with self.subTest(kind=kind):
                engine = make_engine(hero_id='guanyu')
                set_hero(engine, 'AI1', 'guanyu')
                self.clear_hand(engine)
                cid = put_hand(engine, 'P1', kind)
                app = self.app_for(engine)
                app._activate(('battle_card', cid))
                if kind == 'indulgence':
                    app._activate(('battle_target', owner))
                app._activate(('battle_confirm',))
                for _ in range(40):
                    if engine.presentation_event and engine.presentation_event.kind == 'result':
                        break
                    if engine.display_waiting:
                        self.advance(app)
                    elif engine.pending_request:
                        app._activate(('battle_pass',))
                    else:
                        self.fail('No result event for delayed trick')
                self.assertEqual(engine.state.cards[cid].zone_id, engine._player(owner).judgment_zone_id)
                app.battle_ui.event_elapsed = 1200
                with patch.object(app.battle_ui, '_moving_card', wraps=app.battle_ui._moving_card) as move:
                    app._draw()
                    self.assertEqual(move.call_args.args[2], app.battle_ui.equipment_box(owner, 'judgment').center)
                assert_card_zone_invariant(engine.state)

    def test_peach_selection_plays_rescue_then_heals_target(self):
        engine = make_engine(hero_id="guanyu")
        peach = put_hand(engine, "P1", "tao")
        target = engine._player("AI1")
        target.hp = 0
        app = self.app_for(engine)
        engine._drive(engine._rescue("AI1"))
        self.choose_and_confirm(app, peach)
        self.assertEqual(engine.presentation_event.kind, "rescue")
        self.assertEqual(engine.presentation_event.target_ids, ("AI1",))
        self.assertEqual(target.hp, 0)
        self.settle(app)
        self.assertEqual(target.hp, 1)
        self.assertTrue(target.alive)
        self.assertEqual(engine.state.cards[peach].zone_id, "discard_pile")

    def test_judgment_and_guicai_replacement_present_before_final_card(self):
        engine = make_engine(hero_id='simayi')
        set_hero(engine, 'AI1', 'guanyu')
        replacement = put_hand(engine, 'P1', 'sha', suit='hearts')
        original = engine._zone('draw_pile').card_ids[0]
        app = self.app_for(engine)
        results = []
        def resolve():
            final = yield from engine._judge('AI1', '闪电')
            results.append(final)
            engine._discard_card(final)
        engine._drive(resolve())
        app._after_engine_step()
        app._draw()
        self.assertEqual(engine.presentation_event.kind, 'judgement')
        self.assertFalse(results)
        self.advance(app)
        self.assertEqual(engine.pending_request.kind, 'guicai')
        self.choose_and_confirm(app, replacement)
        self.assertEqual(engine.presentation_event.kind, 'judgement_replace')
        self.assertFalse(results)
        self.settle(app)
        self.assertEqual(results, [replacement])
        self.assertEqual(engine.state.cards[original].zone_id, 'discard_pile')
        self.assertEqual(engine.state.cards[replacement].zone_id, 'discard_pile')
        assert_card_zone_invariant(engine.state)

    def test_liuli_updates_route_and_only_damages_actual_target(self):
        engine = make_engine(hero_id="guanyu")
        set_hero(engine, "AI1", "daqiao")
        set_hero(engine, "AI2", "guanyu")
        cost = engine._zone("AI1.hand").card_ids[0]
        engine.ai = RouteAI(lambda _view, request: f"discard:{cost}" if request.kind == "liuli" else "target:AI2" if request.kind == "liuli_target" else None)
        slash = put_hand(engine, "P1", "sha")
        app = self.app_for(engine)
        hp1, hp2 = engine._player("AI1").hp, engine._player("AI2").hp
        app._activate(("battle_card", slash))
        app._activate(("battle_target", "AI1"))
        app._activate(("battle_confirm",))
        self.advance(app)
        self.assertEqual(engine.presentation_event.kind, "retarget")
        self.assertEqual(engine.presentation_event.target_ids, ("AI2",))
        app.battle_ui.event_elapsed = 400
        with patch.object(app.battle_ui, "_route", wraps=app.battle_ui._route) as route:
            app._draw()
            self.assertEqual(route.call_args.args[1], app.battle_ui.port("AI2"))
        self.settle(app)
        self.assertEqual(engine._player("AI1").hp, hp1)
        self.assertEqual(engine._player("AI2").hp, hp2 - 1)

    def test_equipment_animation_commits_latest_weapon_in_real_slot(self):
        engine = make_engine(hero_id="guanyu")
        app = self.app_for(engine)
        for kind in ("crossbow", "kirin_bow"):
            cid = put_hand(engine, "P1", kind)
            app._draw()
            app._activate(("battle_card", cid))
            app._activate(("battle_confirm",))
            self.advance(app)
            self.assertEqual(engine.presentation_event.kind, "equip")
            app.battle_ui.event_elapsed = 500
            with patch.object(app.battle_ui, "_moving_card", wraps=app.battle_ui._moving_card) as move:
                app._draw()
                self.assertEqual(move.call_args.args[2], app.battle_ui.equipment_box("P1", "weapon").center)
            self.settle(app)
            self.assertEqual(engine._weapon_ids("P1"), (cid,))

    def test_pause_freezes_action_and_rule_state_then_resume_completes(self):
        engine = make_engine(hero_id="guanyu")
        cid = put_hand(engine, "P1", "crossbow")
        app = self.app_for(engine)
        app._activate(("battle_card", cid))
        app._activate(("battle_confirm",))
        app._draw()
        before = snapshot_game_state(engine.state)
        elapsed = app.battle_ui.event_elapsed
        app._activate(("pause",))
        app.battle_ui.last_tick = 1000
        with patch("pygame.time.get_ticks", return_value=1100):
            app._draw()
            self.assertFalse(app._advance_ai_display_step(now_ms=1100))
        self.assertEqual(app.battle_ui.event_elapsed, elapsed)
        self.assertEqual(snapshot_game_state(engine.state), before)
        app._activate(("resume",))
        self.settle(app)
        self.assertEqual(engine._weapon_ids("P1"), (cid,))

    def test_large_hands_scrolling_and_overlap_hits_select_the_visible_card(self):
        for count in (12, 18, 30):
            for size in ((1600, 900), (647, 800)):
                with self.subTest(count=count, size=size):
                    self.display = pygame.display.set_mode(size, pygame.HIDDEN)
                    engine = make_engine(hero_id="guanyu")
                    self.clear_hand(engine)
                    for cid in tuple(engine._zone("draw_pile").card_ids[:count]):
                        engine._move(cid, "P1.hand", owner_id="P1", controller_id="P1", visibility=Visibility.OWNER_ONLY)
                    app = self.app_for(engine)
                    ui = app.battle_ui
                    first, second = ui.hand_ids[:2]
                    point = ui.canvas_box(pygame.Rect(ui.hand_rects[second].x + 8, 880, 1, 1)).center
                    app.mouse_canvas_position = point
                    app._draw()
                    hits = [b for b in app.buttons if b.enabled and b.rect.collidepoint(point)]
                    self.assertEqual(hits[-1].action, ("battle_card", second))
                    app._activate(hits[-1].action)
                    self.assertEqual(ui.selected_card, second)
                    for _ in range(8):
                        app._draw()
                        self.assertEqual(ui.hover_hand, second)
                    app._activate(("battle_scroll", 1))
                    app._activate(("battle_scroll", 1))
                    app._draw()
                    self.assertEqual(ui.hand_scroll, ui.max_scroll)
                    # While cards are moving, hits must follow the visible card,
                    # not the entire horizontal gap to its eventual position.
                    for x in range(505, 1630, 48):
                        expected = next((cid for cid in reversed(ui.hand_ids) if ui.hand_rects[cid].collidepoint((x, 740))), None)
                        if expected is None:
                            continue
                        point = ui.canvas_box(pygame.Rect(x, 740, 1, 1)).center
                        hits = [b for b in app.buttons if b.enabled and b.rect.collidepoint(point)]
                        self.assertTrue(hits)
                        self.assertEqual(hits[-1].action, ("battle_card", expected))
                    for _ in range(6):
                        with patch("pygame.time.get_ticks", return_value=ui.last_tick + 100):
                            app._draw()
                    last = ui.hand_ids[-1]
                    point = ui.canvas_box(pygame.Rect(ui.hand_rects[last].centerx, 880, 1, 1)).center
                    hits = [b for b in app.buttons if b.enabled and b.rect.collidepoint(point)]
                    self.assertEqual(hits[-1].action, ("battle_card", last))
                    app._activate(hits[-1].action)
                    self.assertEqual(ui.selected_card, last)
                    self.assertEqual(len(ui.hand_ids), count)
