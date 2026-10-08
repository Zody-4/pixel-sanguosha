from __future__ import annotations

import unittest
from unittest.mock import patch

import _support
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.actions import ActionIntent
from xssgkpz.core.observation import make_observation
from xssgkpz.core.stage1_match import (
    STAGE1_CARD_COUNT, STAGE1_HERO_IDS, create_stage1_match, resolve_roster,
)
from xssgkpz.core.state import ControlType, GamePhase, Visibility, assert_card_zone_invariant
from xssgkpz.data.modes import Identity, MODE_BY_ID
from xssgkpz.data.heroes import HERO_BY_ID


def make_engine(
    mode_id: str = "two_heroes",
    *,
    player_hero: str = "caocao",
    player_identity: Identity | None = None,
    all_ai: bool = False,
    seed: int = 20260924,
) -> GameEngine:
    roster = resolve_roster(
        mode_id=mode_id, player_hero_id=player_hero, seed=seed,
        player_identity=player_identity,
    )
    state = create_stage1_match(roster, human_player_ids=frozenset() if all_ai else frozenset({"P1"}))
    for player in state.players:
        player.seat_index = int(player.player_id.removeprefix("AI")) if player.player_id.startswith("AI") else 0
    state.players.sort(key=lambda player: player.seat_index)
    state.current_player_id = "P1"
    state.phase = GamePhase.PLAY
    state.turn_number = 3
    return GameEngine(state)


def _place(engine: GameEngine, kind_id: str, zone_id: str, *, owner_id: str | None = None,
           controller_id: str | None = None, visibility: Visibility = Visibility.OWNER_ONLY) -> str:
    card_id = next(
        card_id for card_id, card in engine.state.cards.items()
        if engine._definition(card_id).kind_id == kind_id and card.zone_id != zone_id
    )
    engine._move(card_id, zone_id, owner_id=owner_id, controller_id=controller_id, visibility=visibility)
    return card_id


def _hand(engine: GameEngine, player_id: str, kind_id: str) -> str:
    return _place(engine, kind_id, engine._player(player_id).hand_zone_id,
                  owner_id=player_id, controller_id=player_id)


def _equipment(engine: GameEngine, player_id: str, kind_id: str) -> str:
    return _place(engine, kind_id, engine._player(player_id).equipment_zone_id,
                  owner_id=player_id, controller_id=player_id, visibility=Visibility.PUBLIC)


def _hero(engine: GameEngine, player_id: str, hero_id: str) -> None:
    player = engine._player(player_id)
    player.hero_id = hero_id
    max_hp = HERO_BY_ID[hero_id].base_hp
    if engine.state.mode_id == "two_heroes" and player_id == "P1":
        max_hp += 1
    if engine.state.mode_id == "five_player_identity" and player.identity == "lord":
        max_hp += 1
    player.max_hp = max_hp
    player.hp = max_hp


class Stage1SetupTests(unittest.TestCase):
    def test_p01_committed_rosters_cover_all_modes_and_hide_unpublished_roles(self) -> None:
        for mode_id in MODE_BY_ID:
            with self.subTest(mode=mode_id):
                identity = Identity.LORD if mode_id == "five_player_identity" else None
                first = resolve_roster(mode_id=mode_id, player_hero_id="caocao", seed=481516,
                                       player_identity=identity)
                second = resolve_roster(mode_id=mode_id, player_hero_id="caocao", seed=481516,
                                        player_identity=identity)
                self.assertEqual(first, second)
                self.assertEqual(first.player_hero_id, "caocao")
                self.assertEqual(len(first.hero_ids), MODE_BY_ID[mode_id].player_count)
                self.assertTrue(set(first.hero_ids) <= set(STAGE1_HERO_IDS))
                engine = GameEngine(create_stage1_match(first))
                p1 = engine._player("P1")
                self.assertEqual(p1.hero_id, "caocao")
                if mode_id == "five_player_identity":
                    self.assertEqual(p1.identity, Identity.LORD.value)
                    self.assertTrue(p1.identity_public)
                    observed = make_observation(engine.state, "P1")
                    self.assertTrue(all(player.identity is None for player in observed.players if player.player_id != "P1"))
                assert_card_zone_invariant(engine.state)
        self.assertGreater(STAGE1_CARD_COUNT, 0)

    def test_three_hero_selection_methods_stay_inside_the_nine_hero_slice(self) -> None:
        from xssgkpz.core.random_stream import FixedSeedRandom
        from xssgkpz.core.stage1_match import random_hero_candidates

        candidates = random_hero_candidates(FixedSeedRandom(99))
        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(set(candidates)), 3)
        self.assertTrue(set(candidates) <= set(STAGE1_HERO_IDS))

    def test_p01_committed_ui_roster_is_read_only_and_restart_records_failure_before_new_setup(self) -> None:
        from unittest.mock import patch

        import pygame
        from xssgkpz.app import Stage1App
        from xssgkpz.data.settings import Settings

        pygame.font.init()
        app = Stage1App(pygame.Surface((1280, 720)), Settings())
        app.page = "setup"
        app.selected_mode = "five_player_identity"
        app.selected_hero = "caocao"
        app.identity_choice = Identity.LORD.value
        app._lock_roster()
        committed = app.roster
        self.assertEqual(app.page, "roster")
        self.assertIsNone(app.engine)

        app._activate(("confirm", "abandon_setup"))
        app._activate(("confirm_no",))
        self.assertEqual(app.page, "roster")
        self.assertEqual(app.roster, committed)
        self.assertIsNotNone(app.pending_match_state)

        app._activate(("mode", "duel"))
        app._activate(("hero", "liubei"))
        app._activate(("identity", Identity.REBEL.value))
        self.assertEqual(app.roster, committed)
        app._activate(("reveal_identity",))
        self.assertEqual(app.page, "identity")
        app._activate(("show_own_identity",))
        with patch("pygame.time.get_ticks", return_value=app.shell_layout.identity_flip_started + 650):
            app.shell_layout.identity_progress()
        app._activate(("confirm_identity",))
        self.assertEqual(app.page, "objective")
        app._start_match()
        self.assertEqual(app.page, "game")

        # The approved deal buffer locks controls until the engine starts.
        app._advance_ai_display_step(app.deal_started_ms + 3000)

        with patch("xssgkpz.app.append_record_summary") as save_record:
            app._activate(("confirm", "restart"))
            self.assertFalse(app.engine.finished)
            app._activate(("confirm_yes",))
            self.assertEqual(save_record.call_count, 1)
            record = save_record.call_args.args[0]
            self.assertEqual(record.result, "loss")
            self.assertEqual(record.end_reason, "restart")

        self.assertEqual(app.page, "setup")
        self.assertIsNone(app.roster)
        self.assertIsNone(app.engine)

        app._activate(("confirm", "abandon_setup"))
        app._activate(("confirm_yes",))
        self.assertEqual(app.page, "menu")

        app.page = "setup"
        app.selected_mode = "duel"
        app.selected_hero = "zhangfei"
        app._lock_roster()
        app._start_match()
        app._advance_ai_display_step(app.deal_started_ms + 3000)
        with patch("xssgkpz.app.append_record_summary") as save_record:
            app._activate(("confirm", "resign"))
            self.assertFalse(app.engine.finished)
            app._activate(("confirm_no",))
            self.assertFalse(app.engine.finished)
            self.assertEqual(app.page, "game")
            app._activate(("confirm", "resign"))
            app._activate(("confirm_yes",))
            self.assertEqual(save_record.call_count, 1)
            record = save_record.call_args.args[0]
            self.assertEqual(record.result, "loss")
            self.assertEqual(record.end_reason, "resigned")
            self.assertEqual(app.page, "game")
            app._advance_ai_display_step(app.outcome_started_ms + 3200)
            self.assertEqual(app.page, "result")
        pygame.font.quit()


class Stage1ScenarioTests(unittest.TestCase):
    def test_r01_axe_payment_keeps_the_already_locked_kill_target(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_identity=Identity.LORD)
        _hero(engine, "AI2", "ganning")
        axe = _equipment(engine, "P1", "axe")
        horse = _equipment(engine, "P1", "chitu")
        kill = _hand(engine, "P1", "sha")
        target = engine._player("AI2")
        for card_id in tuple(engine._zone(target.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        _hand(engine, "AI2", "shan")
        cost = _hand(engine, "P1", "tao")
        self.assertEqual(engine._equipment_id("P1", "axe"), axe)
        before_distance = engine.distance("P1", "AI2")
        original_kill_targets = engine.kill_targets
        check_count = 0

        def count_target_checks(*args, **kwargs):
            nonlocal check_count
            check_count += 1
            return original_kill_targets(*args, **kwargs)

        engine.kill_targets = count_target_checks  # type: ignore[method-assign]

        engine.submit_action(ActionIntent("P1", card_id=kill, target_ids=("AI2",)))
        self.assertEqual(engine.pending_request.kind, "axe_payment")
        checks_at_lock = check_count
        engine.answer_prompt((f"discard:{horse}", f"discard:{cost}"))

        self.assertEqual(engine.distance("P1", "AI2"), before_distance + 1)
        self.assertEqual(engine._player("AI2").hp, 3)
        self.assertEqual(check_count, checks_at_lock)
        self.assertEqual(engine.state.cards[horse].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[axe].zone_id, "P1.equipment")
        self.assertEqual(engine.state.cards[kill].zone_id, "discard_pile")
        self.assertIsNone(engine.pending_request)

    def test_r02_fanjian_peach_stays_isolated_through_lethal_rescue_and_returns(self) -> None:
        engine = make_engine(player_hero="zhouyu")
        _hero(engine, "AI1", "ganning")
        source = engine._player("P1")
        for card_id in tuple(engine._zone(source.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        target = engine._player("AI1")
        target.hp = 1
        for card_id in tuple(engine._zone(target.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        peach = _hand(engine, "P1", "tao")

        engine._drive(engine._resolve_fanjian("P1", "AI1"))

        if engine.pending_request:
            self.assertEqual(engine.pending_request.kind, "rescue")
            self.assertFalse(any(option.category == "peach" for option in engine.pending_request.options))
            engine.answer_prompt("pass")

        self.assertFalse(target.alive)
        self.assertEqual(engine.state.cards[peach].zone_id, "P1.hand")
        self.assertTrue(any("展示牌处于隔离区" in item.text for item in engine.logs))
        self.assertTrue(any("展示牌退回周瑜手中" in item.text for item in engine.logs))
        self.assertNotIn("peach:" + peach, {item.choice_id for item in (engine.pending_request.options if engine.pending_request else ())})
        assert_card_zone_invariant(engine.state)

    def test_cao_cao_jianxiong_can_take_a_resolving_damage_card(self) -> None:
        engine = make_engine(player_hero="caocao")
        engine._player("P1").hp = 3
        damage_card = _place(engine, "sha", "resolving", visibility=Visibility.PUBLIC)
        engine._drive(engine._damage("AI1", "P1", 1, damage_card, damage_kind="测试"))

        self.assertEqual(engine.pending_request.kind, "jianxiong")
        engine.answer_prompt("take")

        self.assertEqual(engine._player("P1").hp, 2)
        self.assertEqual(engine.state.cards[damage_card].zone_id, "P1.hand")
        assert_card_zone_invariant(engine.state)

    def test_hujia_asks_wei_providers_and_uses_the_first_flash(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_identity=Identity.LORD)
        _hero(engine, "P1", "caocao")
        _hero(engine, "AI1", "simayi")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        flash = _hand(engine, "AI1", "shan")

        engine._drive(engine._ask_flash("P1", "AI4", None))
        self.assertEqual(engine.pending_request.kind, "flash")
        self.assertIn("hujia", {option.choice_id for option in engine.pending_request.options})
        engine.answer_prompt("hujia")

        self.assertEqual(engine.state.cards[flash].zone_id, "discard_pile")
        self.assertIsNone(engine.pending_request)

    def test_liubei_jijiang_uses_a_shu_provider_but_keeps_liubei_as_source(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_hero="liubei", player_identity=Identity.LORD)
        _hero(engine, "AI1", "guanyu")
        _hero(engine, "AI2", "ganning")
        _equipment(engine, "P1", "axe")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("AI2.hand").card_ids):
            engine._discard_card(card_id)
        supplied_kill = _hand(engine, "AI1", "sha")
        action = next(action for action in engine.available_actions("P1")
                      if action.intent.skill_id == "jijiang" and action.intent.target_ids == ("AI2",))

        engine.submit_action(action.intent)

        self.assertEqual(engine._player("AI2").hp, 3)
        self.assertEqual(engine.state.cards[supplied_kill].zone_id, "discard_pile")
        self.assertTrue(any("伤害来源和奖惩归刘备" in item.text for item in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_liubei_rende_can_give_multiple_cards_and_heals_only_once(self) -> None:
        engine = make_engine(player_hero="liubei")
        player = engine._player("P1")
        player.hp = 2
        target = engine._player("AI1")
        before_target = len(engine._zone(target.hand_zone_id).card_ids)

        action = next(action for action in engine.available_actions("P1")
                      if action.intent.skill_id == "rende" and action.intent.target_ids == ("AI1",))
        engine.submit_action(action.intent)
        self.assertEqual(engine.pending_request.kind, "rende_cards")
        selected = tuple(option.choice_id for option in engine.pending_request.options[:2])
        engine.answer_prompt(selected)
        self.assertEqual(player.hp, 3)
        self.assertEqual(len(engine._zone(target.hand_zone_id).card_ids), before_target + 2)

        second_gift = next(action for action in engine.available_actions("P1")
                           if action.intent.skill_id == "rende" and action.intent.target_ids == ("AI1",))
        engine.submit_action(second_gift.intent)
        engine.answer_prompt(engine.pending_request.options[0].choice_id)
        self.assertEqual(player.hp, 3)
        self.assertEqual(len(engine._zone(target.hand_zone_id).card_ids), before_target + 3)

    def test_sun_quan_zhiheng_can_discard_hand_and_equipment_together(self) -> None:
        engine = make_engine(player_hero="sunquan")
        equipment = _equipment(engine, "P1", "qinglong_blade")
        hand_card = engine._zone("P1.hand").card_ids[0]
        draw_before = len(engine._zone("draw_pile").card_ids)
        action = next(action for action in engine.available_actions("P1") if action.intent.skill_id == "zhiheng")

        engine.submit_action(action.intent)
        self.assertEqual(engine.pending_request.kind, "zhiheng_cards")
        options_by_card = {option.value: option.choice_id for option in engine.pending_request.options}
        engine.answer_prompt((options_by_card[equipment], options_by_card[hand_card]))

        self.assertEqual(engine.state.cards[equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[hand_card].zone_id, "discard_pile")
        self.assertEqual(len(engine._zone("draw_pile").card_ids), draw_before - 2)
        self.assertFalse(any(item.intent.skill_id == "zhiheng" for item in engine.available_actions("P1")))
        assert_card_zone_invariant(engine.state)

    def test_sun_quan_jiuyuan_adds_one_for_a_wu_rescuer_saving_the_lord(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_hero="sunquan",
                             player_identity=Identity.LORD)
        _hero(engine, "AI1", "ganning")
        engine._player("AI1").identity = Identity.LOYALIST.value
        engine._player("AI1").identity_public = True
        engine._player("P1").hp = -1
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        peach = _hand(engine, "AI1", "tao")

        engine._drive(engine._rescue("P1"))

        self.assertEqual(engine._player("P1").hp, 1)
        self.assertEqual(engine.state.cards[peach].zone_id, "discard_pile")
        self.assertTrue(any("回复2点体力" in item.text for item in engine.logs))

    def test_simayi_fankui_can_take_a_random_hidden_card(self) -> None:
        engine = make_engine(player_hero="simayi")
        engine._player("P1").hp = 3
        source = engine._player("AI1")
        for card_id in tuple(engine._zone(source.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        hidden_card = _hand(engine, "AI1", "tao")
        engine._drive(engine._damage("AI1", "P1", 1, None, damage_kind="测试"))

        self.assertEqual(engine.pending_request.kind, "fankui")
        engine.answer_prompt("take_random_hand")

        self.assertEqual(engine.state.cards[hidden_card].zone_id, "P1.hand")
        self.assertEqual(engine._player("P1").hp, 2)
        assert_card_zone_invariant(engine.state)

    def test_simayi_guicai_replaces_a_judgment_with_a_hand_card(self) -> None:
        engine = make_engine(player_hero="simayi")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        replacement = _hand(engine, "P1", "tao")
        engine._drive(engine._judge("AI1", "测试"))

        self.assertEqual(engine.pending_request.kind, "guicai")
        original = next(card_id for card_id in engine._zone("resolving").card_ids if card_id != replacement)
        engine.answer_prompt(f"replace:{replacement}")

        self.assertEqual(engine.state.cards[original].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[replacement].zone_id, "resolving")
        self.assertTrue(any("最终判定牌" in item.text for item in engine.logs))

    def test_xiahoudun_ganglie_can_damage_the_damage_source(self) -> None:
        engine = make_engine(player_hero="liubei")
        _hero(engine, "AI1", "xiahoudun")
        engine._player("AI1").control = ControlType.HUMAN
        engine._player("P1").hp = 4
        for player in engine.state.players:
            if player.player_id not in {"P1", "AI1"}:
                for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                    engine._discard_card(card_id)
        draw = engine._zone("draw_pile")
        spade = next(card_id for card_id in draw.card_ids if engine._definition(card_id).suit.value == "spades")
        draw.card_ids.remove(spade)
        draw.card_ids.insert(0, spade)

        engine._drive(engine._damage("P1", "AI1", 1, None, damage_kind="测试"))
        self.assertEqual(engine.pending_request.kind, "ganglie_trigger")
        engine.answer_prompt("yes")
        self.assertEqual(engine.pending_request.kind, "ganglie")
        engine.answer_prompt("damage")

        self.assertEqual(engine._player("AI1").hp, 3)
        self.assertEqual(engine._player("P1").hp, 3)
        assert_card_zone_invariant(engine.state)

    def test_zhangfei_paoxiao_removes_the_per_turn_kill_limit(self) -> None:
        engine = make_engine(player_hero="zhangfei")
        engine._kill_uses["P1"] = 4
        self.assertTrue(engine._can_use_kill("P1"))
        _hero(engine, "P1", "guanyu")
        self.assertFalse(engine._can_use_kill("P1"))

    def test_zhouyu_yingzi_adds_one_card_to_the_normal_draw(self) -> None:
        engine = make_engine(player_hero="zhouyu")
        before = len(engine._zone("P1.hand").card_ids)
        engine.start()
        self.assertEqual(engine.pending_request.kind, "yingzi")
        engine.answer_prompt("yes")

        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 3)
        self.assertEqual(engine.state.phase, GamePhase.PLAY)

    def test_guanyu_wusheng_uses_a_red_card_as_sha(self) -> None:
        engine = make_engine(player_hero="guanyu")
        target = engine._player("AI1")
        _hero(engine, "AI1", "ganning")
        for card_id in tuple(engine._zone(target.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        red_card = _hand(engine, "P1", "tao")
        action = next(action for action in engine.available_actions("P1")
                      if action.intent.skill_id == "wusheng" and action.intent.cost_card_ids == (red_card,))

        engine.submit_action(action.intent)

        self.assertEqual(target.hp, 3)
        self.assertEqual(engine.state.cards[red_card].zone_id, "discard_pile")

    def test_wusheng_does_not_use_a_paid_minus_one_horse_for_range(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_hero="guanyu",
                             player_identity=Identity.LORD)
        _equipment(engine, "P1", "chitu")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("AI2.hand").card_ids):
            engine._discard_card(card_id)
        chitu = engine._equipment_id("P1", "chitu")

        self.assertEqual(engine.distance("P1", "AI2"), 1)
        self.assertNotIn("AI2", engine.kill_targets("P1", cost_card_ids=(chitu,)))

    def test_ganning_qixi_uses_black_card_to_remove_equipment(self) -> None:
        engine = make_engine(player_hero="ganning")
        target = engine._player("AI1")
        _hero(engine, "AI1", "caocao")
        for card_id in tuple(engine._zone(target.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        horse = _equipment(engine, "AI1", "chitu")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        black_card = _hand(engine, "P1", "sha")
        self.assertEqual(engine._color(black_card), "black")
        action = next(action for action in engine.available_actions("P1")
                      if action.intent.skill_id == "qixi" and action.intent.target_ids == ("AI1",))

        engine.submit_action(action.intent)
        self.assertEqual(engine.pending_request.kind, "dismantle_area")
        engine.answer_prompt("equipment")

        self.assertEqual(engine.state.cards[black_card].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[horse].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_c03_same_rescuer_can_play_repeated_peaches_until_above_zero(self) -> None:
        engine = make_engine()
        p1 = engine._player("P1")
        p1.hp = -1
        peaches = (_hand(engine, "P1", "tao"), _hand(engine, "P1", "tao"))
        engine._drive(engine._rescue("P1"))

        self.assertEqual(engine.pending_request.kind, "rescue")
        first = next(option.choice_id for option in engine.pending_request.options if option.value == peaches[0])
        engine.answer_prompt(first)
        self.assertEqual(p1.hp, 0)
        self.assertEqual(engine.pending_request.kind, "rescue")
        second = next(option.choice_id for option in engine.pending_request.options if option.value == peaches[1])
        engine.answer_prompt(second)

        self.assertEqual(p1.hp, 1)
        self.assertTrue(all(engine.state.cards[card_id].zone_id == "discard_pile" for card_id in peaches))
        self.assertIsNone(engine.pending_request)

    def test_c04_short_draw_fails_before_moving_any_requested_card(self) -> None:
        engine = make_engine()
        draw = engine._zone("draw_pile")
        self.assertGreater(len(draw.card_ids), 2)
        keep = draw.card_ids[0]
        for card_id in tuple(draw.card_ids[1:]):
            engine._move(card_id, "P1.hand", owner_id="P1", controller_id="P1", visibility=Visibility.OWNER_ONLY)
        before = tuple(draw.card_ids)

        result = engine._draw_cards(2, "C-04测试")

        self.assertIsNone(result)
        self.assertEqual(tuple(draw.card_ids), before)
        self.assertEqual(draw.card_ids, [keep])
        self.assertEqual(engine.state.result, "draw")
        assert_card_zone_invariant(engine.state)

    def test_c04_recycles_discard_before_a_full_exact_size_draw(self) -> None:
        engine = make_engine()
        draw = engine._zone("draw_pile")
        discard = engine._zone("discard_pile")
        all_cards = tuple(draw.card_ids)
        draw.card_ids.clear()
        for index, card_id in enumerate(all_cards):
            if index < 2:
                engine._move(card_id, discard.zone_id, owner_id=None,
                             controller_id=None, visibility=Visibility.PUBLIC)
            else:
                engine._move(card_id, "P1.hand", owner_id="P1", controller_id="P1",
                             visibility=Visibility.OWNER_ONLY)

        drawn = engine._draw_cards(2, "C-04精确数量测试")

        self.assertIsNotNone(drawn)
        self.assertEqual(len(drawn), 2)
        self.assertEqual(draw.card_ids, [])
        self.assertEqual(discard.card_ids, [])
        self.assertEqual(set(drawn), set(engine._zone("resolving").card_ids))
        assert_card_zone_invariant(engine.state)

    def test_c05_harvest_has_a_separate_nullification_window_for_each_target(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_hero="caocao",
                             player_identity=Identity.LORD, all_ai=True)
        _hero(engine, "AI1", "liubei")
        _hero(engine, "AI2", "simayi")
        _hero(engine, "AI3", "ganning")
        _hero(engine, "AI4", "xiahoudun")
        for player_id, identity in (("P1", "lord"), ("AI1", "loyalist"), ("AI2", "rebel"),
                                    ("AI3", "rebel"), ("AI4", "turncoat")):
            engine._player(player_id).identity = identity
        for player in engine.state.players:
            player.identity_public = player.player_id in {"P1", "AI1", "AI2"}
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                engine._discard_card(card_id)
        negate = next(card_id for card_id in engine._zone("draw_pile").card_ids
                      if engine._definition(card_id).kind_id == "negate")
        engine._zone("draw_pile").card_ids.remove(negate)
        engine._zone("draw_pile").card_ids.insert(0, negate)
        harvest = _place(engine, "harvest", "resolving", visibility=Visibility.PUBLIC)
        engine.state.current_player_id = "P1"

        engine._drive(engine._resolve_harvest("P1", harvest))
        engine._discard_card(harvest)

        self.assertEqual(engine.state.cards[negate].zone_id, "discard_pile")
        target_name = engine._hero_name(engine._player("AI2"))
        source_name = engine._hero_name(engine._player("P1"))
        self.assertTrue(any(source_name + "从五谷丰登中取得一张牌" in item.text for item in engine.logs))
        self.assertTrue(any(target_name + "的五谷目标被无懈" in item.text for item in engine.logs))
        pick_events = [item for item in engine.logs if "从五谷丰登中取得一张牌" in item.text]
        self.assertEqual(len(pick_events), 4)
        assert_card_zone_invariant(engine.state)

    def test_c06_locked_qinglong_followup_can_continue_against_out_of_range_actual_target(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_hero="zhangfei",
                             player_identity=Identity.LORD)
        _hero(engine, "AI2", "ganning")
        _equipment(engine, "P1", "qinglong_blade")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        target = engine._player("AI2")
        for card_id in tuple(engine._zone(target.hand_zone_id).card_ids):
            engine._discard_card(card_id)
        _hand(engine, "AI2", "shan")
        _hand(engine, "AI2", "shan")
        initial_kill = _place(engine, "sha", "resolving", visibility=Visibility.PUBLIC)
        followup_kill = _hand(engine, "P1", "sha")
        engine.distance = lambda _source, _target, **_kwargs: 4  # type: ignore[method-assign]

        engine._drive(engine._resolve_kill("P1", "AI2", initial_kill, active_play=True))
        self.assertEqual(engine.pending_request.kind, "qinglong_followup")
        self.assertGreater(engine.distance("P1", "AI2"), engine.attack_range("P1"))
        engine.answer_prompt(f"continue:{followup_kill}")
        engine._discard_card(initial_kill)

        self.assertEqual(target.hp, target.max_hp)
        self.assertTrue(any("继续使用【杀】；此为同一追杀链" in item.text for item in engine.logs))
        self.assertTrue(all(engine.state.cards[item].zone_id == "discard_pile" for item in (initial_kill, followup_kill)))
        self.assertIsNone(engine.pending_request)
        assert_card_zone_invariant(engine.state)


class Stage1ModeLoopTests(unittest.TestCase):
    def test_ui_can_start_a_locked_match_in_each_mode(self) -> None:
        from unittest.mock import patch

        import pygame
        from xssgkpz.app import Stage1App
        from xssgkpz.data.settings import Settings

        pygame.font.init()
        with patch("xssgkpz.app.append_record_summary"):
            for index, mode_id in enumerate(MODE_BY_ID):
                with self.subTest(mode=mode_id):
                    app = Stage1App(pygame.Surface((1280, 720)), Settings())
                    app.page = "setup"
                    app.selected_mode = mode_id
                    app.selected_hero = "caocao"
                    app.identity_choice = Identity.LORD.value if mode_id == "five_player_identity" else None
                    app.setup_seed = 20260924 + index
                    app._lock_roster()
                    self.assertEqual(app.page, "roster")
                    if mode_id == "five_player_identity":
                        app._activate(("reveal_identity",))
                        app._activate(("show_own_identity",))
                        with patch("pygame.time.get_ticks", return_value=app.shell_layout.identity_flip_started + 650):
                            app.shell_layout.identity_progress()
                        app._activate(("confirm_identity",))
                        self.assertEqual(app.page, "objective")
                    app._activate(("start_match",))
                    self.assertEqual(app.page, "game")
                    self.assertIsNotNone(app.engine)
                    self.assertEqual(app.engine.state.mode_id, mode_id)
                    self.assertFalse(app.engine.finished)
        pygame.font.quit()

    def test_simple_ai_can_complete_a_match_in_each_mode(self) -> None:
        for mode_id in MODE_BY_ID:
            with self.subTest(mode=mode_id):
                identity = Identity.LORD if mode_id == "five_player_identity" else None
                roster = resolve_roster(mode_id=mode_id, player_hero_id="caocao", seed=20260924,
                                        player_identity=identity)
                state = create_stage1_match(roster, human_player_ids=frozenset())
                engine = GameEngine(state)

                engine.start()

                self.assertTrue(engine.finished)
                self.assertIsNotNone(engine.state.result)
                self.assertEqual(engine.state.phase, GamePhase.END)
                assert_card_zone_invariant(engine.state)

    def test_spectator_reveals_do_not_change_ai_observation(self) -> None:
        engine = make_engine(mode_id="five_player_identity", player_identity=Identity.REBEL)
        before = engine.observation_for("AI1")

        engine.reveal_identities_for_spectator()
        engine.reveal_hands_for_spectator()

        self.assertEqual(engine.observation_for("AI1"), before)


class Stage1SpectatorTests(unittest.TestCase):
    def test_first_spectator_reveals_require_confirmation_and_do_not_change_ai_view(self) -> None:
        import pygame
        from xssgkpz.app import Stage1App
        from xssgkpz.data.settings import Settings

        pygame.font.init()
        app = Stage1App(pygame.Surface((1280, 720)), Settings())
        app.page = "game"
        app.engine = make_engine(mode_id="five_player_identity", player_identity=Identity.REBEL)
        app.engine.spectator_waiting = True
        before = app.engine.observation_for("AI1")

        app._activate(("spectator_reveal_identity",))
        self.assertEqual(app.confirm_kind, "reveal_identity")
        self.assertFalse(app.engine.spectator_reveal_identities)
        app._activate(("confirm_no",))
        self.assertFalse(app.engine.spectator_reveal_identities)
        app._activate(("spectator_reveal_identity",))
        app._activate(("confirm_yes",))
        self.assertTrue(app.engine.spectator_reveal_identities)
        self.assertEqual(app.engine.observation_for("AI1"), before)
        app._activate(("spectator_reveal_identity",))
        self.assertFalse(app.spectator_identity_reveal)
        app._activate(("spectator_reveal_identity",))
        self.assertTrue(app.spectator_identity_reveal)
        self.assertIsNone(app.confirm_kind)

        app._activate(("spectator_reveal_hands",))
        self.assertEqual(app.confirm_kind, "reveal_hands")
        app._activate(("confirm_yes",))
        self.assertTrue(app.engine.spectator_reveal_hands)
        self.assertEqual(app.engine.observation_for("AI1"), before)
        pygame.font.quit()

    def test_spectator_exit_fast_forwards_to_real_result_and_records_it(self) -> None:
        from unittest.mock import patch

        import pygame
        from xssgkpz.app import Stage1App
        from xssgkpz.data.settings import Settings

        pygame.font.init()
        app = Stage1App(pygame.Surface((1280, 720)), Settings())
        app.page = "game"
        app.setup_seed = 482901
        app.engine = make_engine(mode_id="five_player_identity", player_identity=Identity.LOYALIST, seed=482901)
        app.engine._kill_player("P1", None)
        app.engine.state.current_player_id = "AI1"
        app.engine.spectator_waiting = True

        with patch("xssgkpz.app.append_record_summary") as save_record:
            app._activate(("spectator_exit",))
            self.assertEqual(app.confirm_kind, "spectator_exit")
            app._activate(("confirm_yes",))
            self.assertTrue(app.engine.finished)
            self.assertEqual(app.page, "game")
            self.assertIsNotNone(app.outcome_started_ms)
            app._advance_ai_display_step(app.outcome_started_ms + 3200)
            self.assertEqual(app.page, "result")
            self.assertEqual(save_record.call_count, 1)
            self.assertEqual(save_record.call_args.args[0].result, "loss")
            self.assertEqual(save_record.call_args.args[0].end_reason, "normal")
        pygame.font.quit()


class Stage1LayoutTests(unittest.TestCase):
    def test_primary_page_controls_fit_canvas_and_1600x900_clicks_scale_back(self) -> None:
        import pygame
        from xssgkpz.app import CANVAS_SIZE, Stage1App
        from xssgkpz.data.settings import Settings

        pygame.font.init()
        pygame.display.init()
        self.addCleanup(pygame.display.quit)
        app = Stage1App(pygame.display.set_mode((1600, 900), pygame.HIDDEN), Settings())

        def assert_buttons_fit() -> None:
            app._draw()
            for button in app.buttons:
                with self.subTest(page=app.page, label=button.label):
                    self.assertGreaterEqual(button.rect.left, 0)
                    self.assertGreaterEqual(button.rect.top, 0)
                    self.assertLessEqual(button.rect.right, app.screen.get_width())
                    self.assertLessEqual(button.rect.bottom, app.screen.get_height())

        self.assertEqual(app._to_canvas((800, 450)), (640, 360))
        for page in ("menu", "setup"):
            app.page = page
            assert_buttons_fit()
        app.page = "setup"
        app.selected_mode = "five_player_identity"
        app.identity_choice = Identity.LORD.value
        app._lock_roster()
        assert_buttons_fit()
        app._activate(("reveal_identity",))
        assert_buttons_fit()
        app._activate(("show_own_identity",))
        with patch("pygame.time.get_ticks", return_value=app.shell_layout.identity_flip_started + 650):
            app.shell_layout.identity_progress()
        app._activate(("confirm_identity",))
        assert_buttons_fit()
        app._start_match()
        for state in ("game", "pause", "confirm"):
            app.pause_open = state == "pause"
            app.confirm_kind = "resign" if state == "confirm" else None
            app.page = "game"
            assert_buttons_fit()
        app.confirm_kind = "reveal_identity"
        assert_buttons_fit()
        app.confirm_kind = None
        app.engine.spectator_waiting = True
        assert_buttons_fit()
        pygame.font.quit()


if __name__ == "__main__":
    unittest.main()
