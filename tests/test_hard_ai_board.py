from __future__ import annotations

import unittest

import _support
from test_stage2_rules import make_engine, put_hand, put_equipment
from xssgkpz.core.ai import make_ai_policies, _hard_action_utility, infer_public_identities, _card_value
from xssgkpz.core.state import Visibility
from xssgkpz.core.actions import DecisionRequest, ChoiceOption
from xssgkpz.data.modes import Difficulty


class HardBoardTests(unittest.TestCase):
    def scene(self, hero='caocao'):
        engine = make_engine('duel', hero)
        for cid in tuple(engine._zone('P1.hand').card_ids):
            engine._move(cid, 'draw_pile', owner_id=None, controller_id=None, visibility=Visibility.HIDDEN)
        policy = make_ai_policies(engine.state.players, seed=3, difficulty=Difficulty.HARD)['P1']
        return engine, policy

    def utility(self, engine, chosen):
        view = engine.observation_for('P1')
        actions = engine.available_actions('P1')
        return _hard_action_utility(view, chosen, actions, infer_public_identities(view))[0]

    def test_black_kill_is_declined_against_renwang(self):
        engine, policy = self.scene()
        put_equipment(engine, 'AI1', 'renwang_shield')
        black = put_hand(engine, 'P1', 'sha', suit='spades')
        attack = next(a for a in engine.available_actions('P1') if a.intent.card_id == black)
        self.assertIsNone(policy.choose_action(engine.observation_for('P1'), (attack,)))

    def test_qinggang_is_equipped_before_blocked_black_kill(self):
        engine, policy = self.scene()
        put_equipment(engine, 'AI1', 'renwang_shield')
        put_hand(engine, 'P1', 'sha', suit='spades')
        weapon = put_hand(engine, 'P1', 'qinggang_sword')
        chosen = policy.choose_action(engine.observation_for('P1'), engine.available_actions('P1'))
        self.assertEqual(chosen.intent.card_id, weapon)

    def test_removal_is_preferred_before_blocked_attack(self):
        engine, policy = self.scene()
        put_equipment(engine, 'AI1', 'renwang_shield')
        put_hand(engine, 'P1', 'sha', suit='spades')
        trick = put_hand(engine, 'P1', 'dismantle')
        chosen = policy.choose_action(engine.observation_for('P1'), engine.available_actions('P1'))
        self.assertEqual(chosen.intent.card_id, trick)

    def test_duel_counts_real_kill_cards_at_one_hp(self):
        engine, _ = self.scene()
        engine._player('P1').hp = 1
        duel = put_hand(engine, 'P1', 'duel')
        chosen = next(a for a in engine.available_actions('P1') if a.intent.card_id == duel)
        without = self.utility(engine, chosen)
        put_hand(engine, 'P1', 'sha')
        self.assertGreaterEqual(self.utility(engine, chosen) - without, 90)

    def test_longdan_counts_flash_as_duel_response(self):
        engine, _ = self.scene('zhaoyun')
        engine._player('P1').hp = 1
        duel = put_hand(engine, 'P1', 'duel')
        chosen = next(a for a in engine.available_actions('P1') if a.intent.card_id == duel)
        without = self.utility(engine, chosen)
        put_hand(engine, 'P1', 'shan')
        self.assertGreaterEqual(self.utility(engine, chosen) - without, 90)

    def test_low_hp_wusheng_preserves_peach_material(self):
        engine, _ = self.scene('guanyu')
        peach = put_hand(engine, 'P1', 'tao')
        chosen = next(a for a in engine.available_actions('P1') if a.intent.skill_id == 'wusheng' and peach in a.intent.cost_card_ids)
        engine._player('P1').hp = 3
        healthy = self.utility(engine, chosen)
        engine._player('P1').hp = 2
        self.assertLessEqual(self.utility(engine, chosen), healthy - 65)

    def test_last_flash_conversion_retains_defence_at_low_hp(self):
        engine, _ = self.scene('zhaoyun')
        flash = put_hand(engine, 'P1', 'shan')
        chosen = next(a for a in engine.available_actions('P1') if a.intent.skill_id == 'longdan' and flash in a.intent.cost_card_ids)
        engine._player('P1').hp = 3
        healthy = self.utility(engine, chosen)
        engine._player('P1').hp = 2
        self.assertLessEqual(self.utility(engine, chosen), healthy - 26)

    def test_real_card_costs_preserve_recovery_and_defence(self):
        engine, _ = self.scene()
        values = {kind: _card_value(put_hand(engine, 'P1', kind), '') for kind in ('tao', 'shan', 'sha', 'negate')}
        self.assertGreater(values['tao'], values['shan'])
        self.assertGreater(values['shan'], values['sha'])
        self.assertGreater(values['sha'], values['negate'])

    def test_nullification_accounts_for_target_and_chain_parity(self):
        engine, policy = self.scene()
        counter = put_hand(engine, 'P1', 'negate')
        view = engine.observation_for('P1')
        for kind in ('steal', 'dismantle', 'arrows', 'lightning', 'draw_two', 'harvest', 'peach_garden'):
            harmful = kind in ('steal', 'dismantle', 'arrows', 'lightning')
            for target in ('P1', 'AI1'):
                for cancelled in (False, True):
                    with self.subTest(kind=kind, target=target, cancelled=cancelled):
                        request = DecisionRequest('nullification', 'P1', '', '', (
                            ChoiceOption('pass', '放弃', 'pass'),
                            ChoiceOption('counter', '无懈', 'negate', counter),
                        ), context=(('target_id', target), ('trick_kind_id', kind), ('cancelled', cancelled)))
                        desired = (target == 'P1') if harmful else (target != 'P1')
                        self.assertEqual(policy.choose_option(view, request), 'counter' if desired != cancelled else 'pass')

    def test_hard_rescues_public_teammate_not_opponent(self):
        engine = make_engine('two_heroes')
        engine.state.current_player_id = 'AI1'
        policy = make_ai_policies(engine.state.players, seed=3, difficulty=Difficulty.HARD)['AI1']
        peach = put_hand(engine, 'AI1', 'tao')
        for target, expected in (('AI2', 'heal'), ('P1', 'pass')):
            engine._player(target).hp = 0
            view = engine.observation_for('AI1')
            request = DecisionRequest('rescue', 'AI1', '', '', (
                ChoiceOption('pass', '放弃', 'pass'), ChoiceOption('heal', '桃', 'peach', peach),
            ), context=(('target_id', target),))
            self.assertEqual(policy.choose_option(view, request), expected)


if __name__ == '__main__':
    unittest.main()
