from __future__ import annotations

import unittest

import _support
from test_stage2_rules import make_engine, place, put_hand, set_hero, action
from xssgkpz.core.actions import ActionIntent
from xssgkpz.core.state import GamePhase, Visibility, assert_card_zone_invariant
from xssgkpz.data.modes import Identity


WEAPONS = {
    "crossbow": 1, "double_swords": 2, "qinggang_sword": 2,
    "frost_sword": 2, "qinglong_blade": 3, "serpent_spear": 3,
    "axe": 3, "halberd": 4, "kirin_bow": 5,
}


class TurnAndWeaponRegressions(unittest.TestCase):
    @staticmethod
    def clear_initial_hand(engine):
        for cid in tuple(engine._zone("P1.hand").card_ids):
            engine._move(cid, "draw_pile", owner_id=None, controller_id=None, visibility=Visibility.HIDDEN)

    def settle(self, engine, *, stop_at_discard=False):
        for _ in range(80):
            if engine.display_waiting:
                engine.resume_display()
            elif engine.pending_request:
                request = engine.pending_request
                if stop_at_discard and request.kind == "discard":
                    return
                if request.kind == "discard":
                    answer = tuple(o.choice_id for o in request.options[:request.min_choices])
                elif request.kind in {"luoyi", "keji"}:
                    answer = "yes"
                else:
                    answer = next((o.choice_id for o in request.options if o.category == "pass"), request.options[0].choice_id)
                engine.answer_prompt(answer)
            else:
                return
        self.fail("rules failed to reach input or completion within 80 transitions")

    def delayed_turn(self, hero="caocao", *, count=8, heart=False, mode="duel", presentation=False):
        engine = make_engine(mode, hero, identity=Identity.LORD if mode == "five_player_identity" else None)
        self.clear_initial_hand(engine)
        for player in engine.state.players:
            if player.player_id != "P1":
                set_hero(engine, player.player_id, "guanyu")
        for _ in range(count):
            put_hand(engine, "P1", "sha")
        delayed = place(engine, "indulgence", "P1.judgment", owner_id="P1", controller_id="P1", visibility=Visibility.PUBLIC)
        top = next(cid for cid in engine._zone("draw_pile").card_ids
                   if (engine._definition(cid).suit.value == "hearts") == heart)
        engine._zone("draw_pile").card_ids.remove(top)
        engine._zone("draw_pile").card_ids.insert(0, top)
        # Bound the fixture after this complete turn; do not simulate unrelated AI turns.
        engine.auto_turn_limit = engine.state.turn_number + 1
        engine.presentation_enabled = presentation
        engine.display_pacing_enabled = presentation
        engine.start()
        self.settle(engine, stop_at_discard=True)
        return engine, delayed

    def test_failed_indulgence_reaches_human_discard_and_finishes_turn(self):
        for mode in ("duel", "two_heroes", "five_player_identity"):
            for hero in ("caocao", "xuchu"):
                for presentation in (False, True):
                    with self.subTest(mode=mode, hero=hero, presentation=presentation):
                        engine, delayed = self.delayed_turn(hero, mode=mode, presentation=presentation)
                        self.assertIsNotNone(engine.pending_request)
                        self.assertEqual(engine.pending_request.kind, "discard")
                        self.assertEqual(engine.state.phase, GamePhase.DISCARD)
                        self.assertFalse(engine.available_actions("P1"))
                        expected_hand = 8 + (1 if hero == "xuchu" else 2)
                        self.assertEqual(len(engine._zone("P1.hand").card_ids), expected_hand)
                        self.assertEqual(engine.pending_request.min_choices, expected_hand - engine._player("P1").hp)
                        self.settle(engine)
                        self.assertTrue(engine.finished)
                        self.assertEqual(len(engine._zone("P1.hand").card_ids), engine._player("P1").hp)
                        self.assertTrue(any("的回合结束" in log.text for log in engine.logs))
                        self.assertEqual(engine.state.cards[delayed].zone_id, "discard_pile")
                        assert_card_zone_invariant(engine.state)

    def test_failed_indulgence_without_excess_advances_without_input(self):
        engine, _ = self.delayed_turn(count=0)
        self.assertTrue(engine.finished)
        self.assertIsNone(engine.pending_request)
        self.assertTrue(any("的回合结束" in log.text for log in engine.logs))

    def test_failed_indulgence_still_allows_keji_to_skip_discard(self):
        engine, _ = self.delayed_turn("lvmeng")
        self.assertTrue(engine.finished)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), 10)
        self.assertTrue(any("发动克己" in log.text for log in engine.logs))

    def test_heart_indulgence_returns_normal_human_play_control(self):
        engine, delayed = self.delayed_turn(heart=True)
        self.assertTrue(engine.is_human_turn)
        self.assertFalse(engine.finished)
        self.assertEqual(engine.state.phase, GamePhase.PLAY)
        self.assertEqual(engine.state.cards[delayed].zone_id, "discard_pile")

    def test_every_ordered_weapon_replacement_uses_only_the_latest_weapon(self):
        for mode in ("duel", "two_heroes", "five_player_identity"):
            for presentation in (False, True):
                for old_kind in WEAPONS:
                    for new_kind, new_range in WEAPONS.items():
                        if new_kind == old_kind:
                            continue
                        with self.subTest(mode=mode, presentation=presentation, old=old_kind, new=new_kind):
                            engine = make_engine(mode, identity=Identity.LORD if mode == "five_player_identity" else None)
                            self.clear_initial_hand(engine)
                            engine.presentation_enabled = presentation
                            old = put_hand(engine, "P1", old_kind)
                            engine.submit_action(ActionIntent("P1", card_id=old))
                            self.settle(engine)
                            new = put_hand(engine, "P1", new_kind)
                            engine.submit_action(ActionIntent("P1", card_id=new))
                            self.settle(engine)
                            self.assertEqual(engine._weapon_ids("P1"), (new,))
                            self.assertEqual(engine.state.cards[old].zone_id, "discard_pile")
                            self.assertFalse(engine._has_equipment("P1", old_kind))
                            self.assertTrue(engine._has_equipment("P1", new_kind))
                            self.assertEqual(engine.attack_range("P1"), new_range)
                            assert_card_zone_invariant(engine.state)

    def test_replaced_crossbow_does_not_allow_an_extra_kill(self):
        engine = make_engine("duel")
        crossbow = put_hand(engine, "P1", "crossbow")
        engine.submit_action(ActionIntent("P1", card_id=crossbow))
        first = put_hand(engine, "P1", "sha")
        second = put_hand(engine, "P1", "sha")
        engine.submit_action(action(engine, kind_id="sha", target_id="AI1", card_id=first))
        self.settle(engine)
        replacement = put_hand(engine, "P1", "qinggang_sword")
        engine.submit_action(ActionIntent("P1", card_id=replacement))
        self.settle(engine)
        self.assertFalse(any(a.intent.card_id == second for a in engine.available_actions("P1")))

    def test_nine_successive_weapons_do_not_accumulate_effects(self):
        engine = make_engine("duel")
        self.clear_initial_hand(engine)
        engine.presentation_enabled = True
        retired = []
        for kind_id, expected_range in WEAPONS.items():
            card = put_hand(engine, "P1", kind_id)
            engine.submit_action(ActionIntent("P1", card_id=card))
            self.settle(engine)
            self.assertEqual(engine._weapon_ids("P1"), (card,))
            self.assertEqual(engine.attack_range("P1"), expected_range)
            for old, old_kind in retired:
                self.assertEqual(engine.state.cards[old].zone_id, "discard_pile")
                self.assertFalse(engine._has_equipment("P1", old_kind))
            retired.append((card, kind_id))
        assert_card_zone_invariant(engine.state)

    def test_replacing_crossbow_with_another_copy_retires_the_old_card(self):
        engine = make_engine("duel")
        self.clear_initial_hand(engine)
        first = put_hand(engine, "P1", "crossbow")
        engine.submit_action(ActionIntent("P1", card_id=first))
        second = put_hand(engine, "P1", "crossbow")
        engine.submit_action(ActionIntent("P1", card_id=second))
        self.assertNotEqual(first, second)
        self.assertEqual(engine._weapon_ids("P1"), (second,))
        self.assertEqual(engine.state.cards[first].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)
