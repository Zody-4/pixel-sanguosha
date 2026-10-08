from __future__ import annotations

import unittest
from dataclasses import replace

import _support
from xssgkpz.core.actions import ActionIntent, ChoiceOption, DecisionRequest, GameAction
from xssgkpz.core.ai import (
    StrategicAI,
    _tactical_adjustment,
    _short_sequence_adjustment,
    infer_public_identities,
    make_ai_policies,
    make_personality_profile,
)
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import create_match, resolve_roster
from xssgkpz.core.observation import PublicActionRecord, make_observation
from xssgkpz.core.state import GamePhase, Visibility
from xssgkpz.data.cards import CARD_BY_ID
from xssgkpz.data.ai_personalities import PERSONALITIES_BY_HERO, Personality
from xssgkpz.data.heroes import HERO_BY_ID
from xssgkpz.data.modes import Difficulty, Identity
from xssgkpz.data.settings import Settings


class AIProfileTests(unittest.TestCase):
    def test_personality_table_covers_all_heroes_with_distinct_secondary_tendencies(self) -> None:
        self.assertEqual(set(PERSONALITIES_BY_HERO), set(HERO_BY_ID))
        self.assertEqual(len(PERSONALITIES_BY_HERO), 25)
        self.assertTrue(all(item.primary != item.secondary
                            for item in PERSONALITIES_BY_HERO.values()))

    def test_profile_is_seeded_once_and_matches_the_seventy_thirty_roll(self) -> None:
        first = make_personality_profile("caocao", 44321)
        self.assertEqual(first, make_personality_profile("caocao", 44321))
        self.assertEqual(first.active, first.primary if first.roll < 7 else first.secondary)
        primary = sum(
            make_personality_profile("caocao", seed).active is Personality.CONTROL
            for seed in range(1000)
        )
        self.assertGreaterEqual(primary, 660)
        self.assertLessEqual(primary, 740)

    def test_match_policies_share_profiles_across_difficulty_tiers(self) -> None:
        roster = resolve_roster(
            mode_id="duel", player_hero_id="caocao", seed=8102,
            difficulty=Difficulty.SIMPLE,
        )
        players = create_match(roster).players
        policies = {
            tier: make_ai_policies(players, seed=roster.seed, difficulty=tier)
            for tier in Difficulty
        }
        self.assertEqual(
            policies[Difficulty.SIMPLE]["P1"].personality,
            policies[Difficulty.MEDIUM]["P1"].personality,
        )
        self.assertEqual(
            policies[Difficulty.MEDIUM]["P1"].personality,
            policies[Difficulty.HARD]["P1"].personality,
        )
        self.assertIsNot(policies[Difficulty.SIMPLE]["P1"], policies[Difficulty.HARD]["P1"])

    def test_setup_selection_reaches_the_match_engine_and_roster_page(self) -> None:
        import pygame
        from xssgkpz.app import CANVAS_SIZE, Stage1App

        pygame.init()
        try:
            screen = pygame.display.set_mode(CANVAS_SIZE, pygame.HIDDEN)
            app = Stage1App(screen, Settings())
            app._activate(("open_setup",))
            app._activate(("difficulty", Difficulty.HARD.value))
            app._draw()
            selected = next(button for button in app.buttons
                            if button.action == ("difficulty", Difficulty.HARD.value))
            self.assertTrue(selected.selected)
            app._lock_roster()
            self.assertEqual(app.roster.difficulty, Difficulty.HARD)
            app._start_match()
            self.assertEqual(app.engine.ai_by_player["AI1"].difficulty, Difficulty.HARD)
            self.assertFalse(app.recorded_match)
        finally:
            pygame.quit()


class PublicInformationTests(unittest.TestCase):
    def test_hidden_truth_hands_and_future_order_do_not_change_observation_or_choice(self) -> None:
        roster = resolve_roster(
            mode_id="five_player_identity", player_hero_id="caocao", seed=733,
            player_identity=Identity.LORD,
        )
        state = create_match(roster)
        engine = GameEngine(state)
        before = engine.observation_for("P1")
        policies_before = {
            difficulty: make_ai_policies(
                state.players, seed=roster.seed, difficulty=difficulty,
            )["P1"]
            for difficulty in Difficulty
        }
        hidden_player = next(player for player in state.players
                             if player.player_id != "P1" and not player.identity_public)
        hidden_player.identity = (
            Identity.LOYALIST.value
            if hidden_player.identity == Identity.REBEL.value
            else Identity.REBEL.value
        )
        hidden_hand = state.zones[hidden_player.hand_zone_id].card_ids
        draw_pile = state.zones["draw_pile"].card_ids
        hand_card, draw_card = hidden_hand[0], draw_pile[0]
        hidden_hand[0], draw_pile[0] = draw_card, hand_card
        state.cards[draw_card].zone_id = hidden_player.hand_zone_id
        state.cards[draw_card].owner_id = hidden_player.player_id
        state.cards[hand_card].zone_id = "draw_pile"
        state.cards[hand_card].owner_id = None
        draw_pile.reverse()
        after = engine.observation_for("P1")
        self.assertEqual(before, after)
        self.assertNotIn(hidden_player.identity, (player.identity for player in before.players))

        actions = (
            GameAction("play:kill:public-sample:AI1", "使用杀",
                       ActionIntent("P1", card_id="card:sample", target_ids=("AI1",))),
            GameAction("play:draw_two:public-sample", "摸两张牌",
                       ActionIntent("P1", card_id="card:sample")),
        )
        for difficulty in Difficulty:
            policy_after = make_ai_policies(
                state.players, seed=roster.seed, difficulty=difficulty,
            )["P1"]
            policy_before = policies_before[difficulty]
            choice_before = policy_before.choose_action(before, actions)
            choice_after = policy_after.choose_action(after, actions)
            self.assertEqual(choice_before, choice_after, difficulty.value)
            self.assertEqual(
                policy_before.decisions[-1], policy_after.decisions[-1],
                difficulty.value,
            )
            self.assertEqual(
                len(policy_before.decisions[-1].ranked_actions), len(actions),
                difficulty.value,
            )

    def test_simple_ai_declines_attacks_on_publicly_known_allies(self) -> None:
        roster = resolve_roster(
            mode_id="two_heroes", player_hero_id="caocao", seed=734,
        )
        state = create_match(roster)
        state.current_player_id = "AI1"
        state.phase = GamePhase.PLAY
        engine = GameEngine(state)
        for kind_id in ("sha", "duel"):
            card_id = next(
                card_id for card_id in engine._zone("draw_pile").card_ids
                if engine._definition(card_id).kind_id == kind_id
            )
            engine._move(
                card_id, "AI1.hand", owner_id="AI1", controller_id="AI1",
                visibility=Visibility.OWNER_ONLY,
            )
        view = engine.observation_for("AI1")
        ally = next(player for player in view.players if player.player_id == "AI2")
        self.assertEqual(
            next(player for player in view.players if player.player_id == "AI1").identity,
            "ai_side",
        )
        self.assertEqual(ally.identity, "ai_side")
        candidates: dict[str, GameAction] = {}
        for action in engine.available_actions("AI1"):
            if action.intent.target_ids != (ally.player_id,) or action.intent.card_id is None:
                continue
            kind_id = engine._definition(action.intent.card_id).kind_id
            if kind_id in {"sha", "duel"}:
                candidates.setdefault(kind_id, action)
        self.assertEqual(set(candidates), {"sha", "duel"})
        actions = tuple(candidates[kind_id] for kind_id in ("sha", "duel"))
        self.assertTrue(all(engine.is_legal_intent(action.intent) for action in actions))
        policy = make_ai_policies(
            state.players, seed=roster.seed, difficulty=Difficulty.SIMPLE,
        )["AI1"]

        self.assertIsNone(policy.choose_action(view, actions))
        trace = policy.decisions[-1]
        self.assertIsNone(trace.chosen_action_id)
        self.assertEqual({action_id for action_id, _ in trace.ranked_actions},
                         {action.action_id for action in actions})
        self.assertTrue(all(score < 0 for _, score in trace.ranked_actions))

    def test_public_behavior_changes_probability_but_response_requests_do_not_label_identity(self) -> None:
        roster = resolve_roster(
            mode_id="five_player_identity", player_hero_id="caocao", seed=991,
            player_identity=Identity.LORD,
        )
        view = make_observation(create_match(roster), "P1")
        base = infer_public_identities(view)["AI1"]
        attack = replace(view, public_actions=(PublicActionRecord(
            1, "AI1", "sha", ("P1",),
        ),))
        after_attack = infer_public_identities(attack)["AI1"]
        self.assertGreater(after_attack[Identity.REBEL.value], base[Identity.REBEL.value])
        self.assertLess(after_attack[Identity.LOYALIST.value], base[Identity.LOYALIST.value])
        public_skill_attack = replace(view, public_actions=(PublicActionRecord(
            1, "AI1", "wusheng", ("P1",),
        ),))
        self.assertGreater(
            infer_public_identities(public_skill_attack)["AI1"][Identity.REBEL.value],
            base[Identity.REBEL.value],
        )

        response = replace(view, public_actions=(PublicActionRecord(
            1, "AI1", "hujia_response", ("P1",),
        ),))
        self.assertEqual(infer_public_identities(response)["AI1"], base)
        jijiang = replace(view, public_actions=(PublicActionRecord(
            1, "AI1", "jijiang_response", ("P1",),
        ),))
        self.assertEqual(infer_public_identities(jijiang)["AI1"], base)

    def test_tiers_use_public_team_and_threat_state_and_hard_has_short_sequence_signal(self) -> None:
        roster = resolve_roster(
            mode_id="five_player_identity", player_hero_id="caocao", seed=1082,
            player_identity=Identity.LORD,
        )
        state = create_match(roster)
        for player in state.players:
            player.identity_public = True
        base_view = make_observation(state, "P1")
        adjusted_players = tuple(
            replace(
                player,
                identity={"P1": Identity.LORD.value, "AI1": Identity.LOYALIST.value,
                          "AI2": Identity.REBEL.value}.get(player.player_id, player.identity),
                hero_id={"AI1": "simayi", "AI2": "zhangliao"}.get(player.player_id, player.hero_id),
                hp={"AI1": 2}.get(player.player_id, player.hp),
                max_hp={"AI1": 4}.get(player.player_id, player.max_hp),
                hand_count={"AI1": 1, "AI2": 5}.get(player.player_id, player.hand_count),
            )
            for player in base_view.players
        )
        view = replace(base_view, players=adjusted_players)
        actions = (
            GameAction("play:kill:red:AI1", "攻击忠臣",
                       ActionIntent("P1", card_id="card:red", target_ids=("AI1",))),
            GameAction("play:kill:red:AI2", "攻击反贼",
                       ActionIntent("P1", card_id="card:red", target_ids=("AI2",))),
        )
        simple = StrategicAI(
            difficulty=Difficulty.SIMPLE,
            personality=make_personality_profile("caocao", 1),
        )
        medium = StrategicAI(
            difficulty=Difficulty.MEDIUM,
            personality=make_personality_profile("caocao", 1),
        )
        self.assertEqual(simple.choose_action(view, actions).intent.target_ids, ("AI2",))
        self.assertEqual(medium.choose_action(view, actions).intent.target_ids, ("AI2",))

        setup = GameAction("play:dismantle:one:AI2", "拆除防具",
                           ActionIntent("P1", card_id="card:one", target_ids=("AI2",)))
        followup = actions[1]
        hard = StrategicAI(
            difficulty=Difficulty.HARD,
            personality=make_personality_profile("caocao", 1),
        )
        self.assertEqual(_short_sequence_adjustment(setup, (setup, followup)), 7)

    def test_middle_tier_scores_public_equipment_and_distance(self) -> None:
        roster = resolve_roster(
            mode_id="five_player_identity", player_hero_id="caocao", seed=515,
            player_identity=Identity.LORD,
        )
        state = create_match(roster)
        view = make_observation(state, "P1")
        players = tuple(
            replace(player, identity=Identity.REBEL.value)
            if player.player_id == "AI1" else player
            for player in view.players
        )
        enemy = next(player for player in players if player.player_id == "AI1")
        armor = next(definition for definition in CARD_BY_ID.values()
                     if definition.kind_id == "bagua_formation")
        action = GameAction(
            "play:dismantle:sample:AI1", "拆除装备",
            ActionIntent("P1", card_id="card:sample", target_ids=("AI1",)),
        )
        near = replace(
            view,
            players=tuple(replace(player, equipment_card_ids=(f"card:{armor.definition_id}",))
                          if player.player_id == "AI1" else player for player in players),
            distances_from_viewer=(("P1", 0), ("AI1", 1)),
        )
        far = replace(near, distances_from_viewer=(("P1", 0), ("AI1", 4)))
        without_armor = replace(
            near,
            players=tuple(replace(player, equipment_card_ids=())
                          if player.player_id == "AI1" else player for player in near.players),
        )
        near_score, _ = _tactical_adjustment(near, action, infer_public_identities(near))
        far_score, _ = _tactical_adjustment(far, action, infer_public_identities(far))
        no_equipment_score, _ = _tactical_adjustment(
            without_armor, action, infer_public_identities(without_armor),
        )
        self.assertGreater(near_score, far_score)
        self.assertGreater(near_score, no_equipment_score)

    def test_personality_changes_only_close_choices(self) -> None:
        roster = resolve_roster(
            mode_id="two_heroes", player_hero_id="xiahoudun", seed=711,
            difficulty=Difficulty.SIMPLE,
        )
        view = make_observation(create_match(roster), "P1")
        target = next(player for player in view.players if player.player_id == "AI1")
        view = replace(
            view,
            players=tuple(replace(player, hp=2, max_hp=4)
                          if player.player_id == target.player_id else player
                          for player in view.players),
        )
        attack = GameAction(
            "play:kill:red:AI1", "杀",
            ActionIntent("P1", card_id="card:red", target_ids=("AI1",)),
        )
        draw = GameAction(
            "play:draw_two:blue", "摸牌",
            ActionIntent("P1", card_id="card:blue"),
        )
        aggressive = StrategicAI(
            difficulty=Difficulty.SIMPLE,
            personality=make_personality_profile("xiahoudun", 0),
        )
        controlled = StrategicAI(
            difficulty=Difficulty.SIMPLE,
            personality=make_personality_profile("xiahoudun", 0),
        )
        aggressive.personality = replace(aggressive.personality, active=Personality.AGGRESSION)
        controlled.personality = replace(controlled.personality, active=Personality.CONTROL)
        self.assertEqual(aggressive.choose_action(view, (attack, draw)), attack)
        self.assertIn("personality_aggression", aggressive.decisions[-1].reason)
        self.assertEqual(controlled.choose_action(view, (attack, draw)), draw)

        high_value = GameAction(
            "skill:zhouyu.yingzi", "摸牌技能",
            ActionIntent("P1", skill_id="zhouyu.yingzi"),
        )
        chosen = aggressive.choose_action(view, (attack, draw, high_value))
        self.assertEqual(chosen, high_value)
        self.assertEqual(aggressive.decisions[-1].reason, "baseline")

        critical_view = replace(
            view,
            players=tuple(replace(player, hp=1)
                          if player.player_id == "P1" else player
                          for player in view.players),
        )
        peach = GameAction(
            "play:tao:self", "桃",
            ActionIntent("P1", card_id="card:peach"),
        )
        self.assertEqual(aggressive.choose_action(critical_view, (attack, peach)), peach)


class EngineGuardTests(unittest.TestCase):
    def test_ai_invalid_prompt_choice_is_recorded_and_replaced_by_legal_option(self) -> None:
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=17)
        engine = GameEngine(create_match(roster))

        class InvalidAI:
            def choose_option(self, _view, _request):
                return "not-an-option"

        engine.ai_by_player["AI1"] = InvalidAI()
        request = DecisionRequest(
            "test", "AI1", "test", "", (
                ChoiceOption("pass", "pass", "pass"),
                ChoiceOption("yes", "yes", "yes"),
            ),
        )
        result = engine._choose_ai_option(engine.observation_for("AI1"), request)
        self.assertEqual(result, "pass")
        self.assertEqual(len(engine.ai_issues), 1)
        self.assertEqual(engine.ai_issues[0].reason, "selected_choice_not_in_legal_option_set")

    def test_ai_invalid_action_is_revalidated_and_logged_before_legal_fallback(self) -> None:
        from xssgkpz.data.cards import CARD_DEFINITIONS

        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=101)
        state = create_match(roster, human_player_ids=frozenset())
        state.current_player_id = "P1"
        state.phase = GamePhase.PLAY
        definition = next(item for item in CARD_DEFINITIONS if item.kind_id == "draw_two")
        physical_id = f"card:{definition.definition_id}"
        card = state.cards[physical_id]
        state.zones[card.zone_id].card_ids.remove(physical_id)
        state.zones["P1.hand"].card_ids.append(physical_id)
        card.zone_id = "P1.hand"
        card.owner_id = "P1"
        card.controller_id = "P1"

        class InvalidActionAI:
            def choose_action(self, view, _actions):
                return GameAction("forged", "invalid", ActionIntent(view.viewer_id, card_id="card:missing"))

            def choose_option(self, _view, request):
                return next((option.choice_id for option in request.options
                             if option.category == "pass"), request.options[0].choice_id)

        engine = GameEngine(state, ai=InvalidActionAI())
        engine._drive(engine._run_ai_play(engine._player("P1")))
        self.assertTrue(any(issue.reason == "selected_action_not_in_legal_action_set"
                            for issue in engine.ai_issues))
        self.assertTrue(any(record.actor_id == "P1" and record.kind_id == "draw_two"
                            for record in engine.public_action_history))

    def test_indulgence_catalogue_respects_qianxun_legality(self) -> None:
        roster = resolve_roster(
            mode_id="five_player_identity", player_hero_id="caocao", seed=88,
            player_identity=Identity.LORD,
        )
        state = create_match(roster)
        state.current_player_id = "P1"
        state.phase = GamePhase.PLAY
        qianxun_player = next(player for player in state.players if player.player_id == "AI1")
        qianxun_player.hero_id = "luxun"
        card_id = next(
            card_id for card_id, card in state.cards.items()
            if CARD_BY_ID[card.definition_id].kind_id == "indulgence"
        )
        card = state.cards[card_id]
        state.zones[card.zone_id].card_ids.remove(card_id)
        state.zones["P1.hand"].card_ids.append(card_id)
        card.zone_id = "P1.hand"
        card.owner_id = "P1"
        card.controller_id = "P1"
        engine = GameEngine(state)
        actions = engine.available_actions("P1")
        self.assertTrue(all(engine.is_legal_intent(action.intent) for action in actions))
        self.assertFalse(any(
            action.intent.target_ids == ("AI1",)
            and action.intent.card_id == card_id
            for action in actions
        ))


if __name__ == "__main__":
    unittest.main()
