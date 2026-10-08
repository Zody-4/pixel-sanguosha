from __future__ import annotations

import unittest

import _support
from xssgkpz.core.actions import ActionIntent
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import create_match, resolve_roster
from xssgkpz.core.observation import make_observation
from xssgkpz.core.state import GamePhase, Visibility, assert_card_zone_invariant
from xssgkpz.data.cards import CARD_BY_ID
from xssgkpz.data.heroes import HERO_BY_ID
from xssgkpz.data.modes import Identity, MODE_BY_ID


class PassAI:
    """Make responses deterministic while preserving the observation-only AI API."""

    def choose_action(self, _view, _actions):
        return None

    def choose_option(self, _view, request):
        return next((option.choice_id for option in request.options
                     if option.category == "pass"), request.options[0].choice_id)


class RouteAI(PassAI):
    def __init__(self, route):
        self.route = route

    def choose_option(self, view, request):
        selected = self.route(view, request)
        if selected is not None:
            return selected
        return super().choose_option(view, request)


def make_engine(mode_id: str = "two_heroes", hero_id: str = "caocao", *,
                identity: Identity | None = None, seed: int = 20260925,
                human_player_ids: frozenset[str] = frozenset({"P1"})) -> GameEngine:
    roster = resolve_roster(mode_id=mode_id, player_hero_id=hero_id, seed=seed,
                            player_identity=identity)
    state = create_match(roster, human_player_ids=human_player_ids)
    state.players.sort(key=lambda player: (player.player_id != "P1", player.player_id))
    for index, player in enumerate(state.players):
        player.seat_index = index
    state.current_player_id = "P1"
    state.phase = GamePhase.PLAY
    state.turn_number = 3
    engine = GameEngine(state, ai=PassAI())
    return engine


def place(engine: GameEngine, kind_id: str, zone_id: str, *, owner_id: str | None = None,
          controller_id: str | None = None, visibility: Visibility = Visibility.OWNER_ONLY,
          suit: str | None = None) -> str:
    matching = tuple(card_id for card_id, instance in engine.state.cards.items()
                      if CARD_BY_ID[instance.definition_id].kind_id == kind_id
                      and (suit is None or CARD_BY_ID[instance.definition_id].suit.value == suit)
                      and instance.zone_id != zone_id)
    card_id = next((item for item in matching
                    if engine.state.cards[item].zone_id == "draw_pile"), None)
    if card_id is None:
        card_id = next(item for item in matching)
    engine._move(card_id, zone_id, owner_id=owner_id, controller_id=controller_id,
                 visibility=visibility)
    return card_id


def put_hand(engine: GameEngine, player_id: str, kind_id: str, *, suit: str | None = None) -> str:
    player = engine._player(player_id)
    return place(engine, kind_id, player.hand_zone_id, owner_id=player_id,
                 controller_id=player_id, suit=suit)


def put_equipment(engine: GameEngine, player_id: str, kind_id: str) -> str:
    player = engine._player(player_id)
    return place(engine, kind_id, player.equipment_zone_id, owner_id=player_id,
                 controller_id=player_id, visibility=Visibility.PUBLIC)


def set_hero(engine: GameEngine, player_id: str, hero_id: str) -> None:
    player = engine._player(player_id)
    player.hero_id = hero_id
    player.max_hp = HERO_BY_ID[hero_id].base_hp
    if engine.state.mode_id == "two_heroes" and player_id == "P1":
        player.max_hp += 1
    if engine.state.mode_id == "five_player_identity" and player.identity == Identity.LORD.value:
        player.max_hp += 1
    player.hp = player.max_hp


def run_generator(engine: GameEngine, generator, choose=None) -> None:
    engine._drive(generator)
    while engine.pending_request:
        request = engine.pending_request
        if choose:
            choice = choose(request)
        else:
            choice = next((option.choice_id for option in request.options
                           if option.category == "pass"), request.options[0].choice_id)
        engine.answer_prompt(choice)


def answer_pending(engine: GameEngine, choose=None) -> None:
    while engine.pending_request:
        request = engine.pending_request
        if choose:
            choice = choose(request)
        else:
            choice = next((option.choice_id for option in request.options
                           if option.category == "pass"), request.options[0].choice_id)
        engine.answer_prompt(choice)


def submit(engine: GameEngine, intent: ActionIntent, choose=None) -> None:
    engine.submit_action(intent)
    answer_pending(engine, choose)


def complete_without_prompts(generator):
    try:
        next(generator)
    except StopIteration as result:
        return result.value
    raise AssertionError("expected the fixture to complete without a human prompt")


def choose(request, category: str, index: int = 0) -> str:
    return tuple(option.choice_id for option in request.options
                 if option.category == category)[index]


def action(engine: GameEngine, *, kind_id: str, target_id: str | None = None,
           card_id: str | None = None):
    return next(item.intent for item in engine.available_actions("P1")
                if item.intent.card_id
                and engine._definition(item.intent.card_id).kind_id == kind_id
                and (card_id is None or item.intent.card_id == card_id)
                and (target_id is None or item.intent.target_ids == (target_id,)))


class Stage2MatchTests(unittest.TestCase):
    def test_formal_match_factory_uses_all_heroes_and_unique_full_deck_in_each_mode(self) -> None:
        for mode_id, mode in MODE_BY_ID.items():
            with self.subTest(mode=mode_id):
                identity = Identity.LORD if mode_id == "five_player_identity" else None
                roster = resolve_roster(mode_id=mode_id, player_hero_id="caocao", seed=3819,
                                        player_identity=identity)
                state = create_match(roster)
                self.assertEqual(len(state.players), mode.player_count)
                self.assertEqual(len(state.cards), 108)
                seat_ordered = sorted(state.players, key=lambda player: player.seat_index)
                self.assertEqual(tuple(len(state.zones[player.hand_zone_id].card_ids)
                                       for player in seat_ordered), mode.starting_hand_sizes)
                self.assertEqual(set(state.cards), set(state.zones["draw_pile"].card_ids)
                                 | {card for player in state.players
                                    for zone_id in (player.hand_zone_id, player.equipment_zone_id,
                                                    player.judgment_zone_id)
                                    for card in state.zones[zone_id].card_ids})
                self.assertEqual(len({player.hero_id for player in state.players}), mode.player_count)
                assert_card_zone_invariant(state)
                if mode_id == "two_heroes":
                    self.assertEqual(state.players[0].max_hp, HERO_BY_ID["caocao"].base_hp + 1)
                    self.assertEqual(len(state.zones["P1.hand"].card_ids), 5)
                if mode_id == "five_player_identity":
                    self.assertEqual(sum(player.identity == Identity.LORD.value for player in state.players), 1)
                    self.assertEqual(sum(player.identity == Identity.REBEL.value for player in state.players), 2)
                    lord = next(player for player in state.players if player.identity == Identity.LORD.value)
                    self.assertEqual(lord.max_hp, HERO_BY_ID[lord.hero_id].base_hp + 1)
                    observed = make_observation(state, "P1")
                    self.assertTrue(all(player.identity is None for player in observed.players
                                        if player.player_id != "P1"))

    def test_all_twenty_five_heroes_are_available_to_each_mode(self) -> None:
        for mode_id in MODE_BY_ID:
            for index, hero_id in enumerate(HERO_BY_ID):
                with self.subTest(mode=mode_id, hero=hero_id):
                    identity = Identity.LORD if mode_id == "five_player_identity" else None
                    roster = resolve_roster(mode_id=mode_id, player_hero_id=hero_id,
                                            seed=20260925 + index,
                                            player_identity=identity)
                    self.assertEqual(roster.player_hero_id, hero_id)
                    self.assertEqual(roster.hero_ids[0], hero_id)
                    self.assertEqual(len(set(roster.hero_ids)), MODE_BY_ID[mode_id].player_count)

    def test_two_heroes_opening_bonus_and_clockwise_turn_order(self) -> None:
        roster = resolve_roster(mode_id="two_heroes", player_hero_id="caocao", seed=4401)
        state = create_match(roster)
        self.assertEqual(state.current_player_id, "P1")
        self.assertEqual([player.player_id for player in sorted(state.players,
                                                                 key=lambda item: item.seat_index)],
                         ["P1", "AI1", "AI2"])
        player = next(item for item in state.players if item.player_id == "P1")
        self.assertEqual((player.max_hp, player.hp),
                         (HERO_BY_ID["caocao"].base_hp + 1, HERO_BY_ID["caocao"].base_hp + 1))
        self.assertEqual(len(state.zones[player.hand_zone_id].card_ids), 5)
        self.assertTrue(all(len(state.zones[item.hand_zone_id].card_ids) == 4
                            for item in state.players if item.player_id != "P1"))
        engine = GameEngine(state, ai=PassAI())
        engine.start()
        self.assertTrue(engine.is_human_turn)
        engine.end_play_phase()
        answer_pending(engine, lambda request: tuple(
            option.choice_id for option in request.options
            if option.category == "discard"
        )[:request.max_choices])
        self.assertEqual(state.current_player_id, "P1")
        self.assertEqual(state.turn_number, 4)
        self.assertEqual(state.phase, GamePhase.PLAY)

    def test_five_player_identity_counts_and_lord_opening_are_exact(self) -> None:
        roster = resolve_roster(mode_id="five_player_identity", player_hero_id="caocao",
                                player_identity=Identity.LORD, seed=538)
        state = create_match(roster)
        counts = {identity.value: sum(player.identity == identity.value for player in state.players)
                  for identity in Identity}
        self.assertEqual(counts, {"lord": 1, "loyalist": 1, "rebel": 2, "turncoat": 1})
        lord = next(player for player in state.players if player.identity == Identity.LORD.value)
        self.assertEqual((lord.hp, lord.max_hp),
                         (HERO_BY_ID[lord.hero_id].base_hp + 1,
                          HERO_BY_ID[lord.hero_id].base_hp + 1))
        self.assertEqual(state.current_player_id, lord.player_id)
        self.assertTrue(lord.identity_public)
        view = make_observation(state, "P1")
        for player in view.players:
            if player.player_id == "P1" or player.player_id == lord.player_id:
                continue
            self.assertIsNone(player.identity)

    def test_lord_skills_are_disabled_outside_the_five_player_lord_role(self) -> None:
        for mode_id, identity in (("duel", None), ("two_heroes", None),
                                  ("five_player_identity", Identity.REBEL)):
            engine = make_engine(mode_id, "caocao", identity=identity)
            self.assertFalse(engine._is_lord("P1"), mode_id)
            self.assertFalse(engine._can_hujia("P1"), mode_id)
        lord = make_engine("five_player_identity", "caocao", identity=Identity.LORD)
        self.assertTrue(lord._is_lord("P1"))
        self.assertTrue(lord._can_hujia("P1"))

    def test_duel_first_turn_starts_randomized_mode_with_one_draw(self) -> None:
        roster = resolve_roster(mode_id="duel", player_hero_id="caocao", seed=701,
                                player_identity=None)
        state = create_match(roster)
        first_actor = state.current_player_id
        self.assertIn(first_actor, {"P1", "AI1"})
        replay = create_match(roster)
        self.assertEqual(replay.current_player_id, first_actor)
        sampled_openers = {
            create_match(resolve_roster(mode_id="duel", player_hero_id="caocao", seed=seed)).current_player_id
            for seed in range(701, 711)
        }
        self.assertEqual(sampled_openers, {"P1", "AI1"})
        first_hand = len(state.zones[f"{first_actor}.hand"].card_ids)
        engine = GameEngine(state, ai=PassAI())
        run_generator(engine, engine._start_turn(engine._player(first_actor)))
        self.assertEqual(state.turn_number, 1)
        self.assertEqual(len(state.zones[f"{first_actor}.hand"].card_ids), first_hand + 1)
        self.assertEqual(state.phase, GamePhase.PLAY)
        self.assertEqual(state.current_player_id, first_actor)

    def test_full_deck_ai_matches_reach_a_terminal_result_in_each_mode(self) -> None:
        checked = 0
        for mode_id in MODE_BY_ID:
            for index, hero_id in enumerate(HERO_BY_ID):
                with self.subTest(mode=mode_id, hero=hero_id):
                    identity = Identity.LORD if mode_id == "five_player_identity" else None
                    roster = resolve_roster(mode_id=mode_id, player_hero_id=hero_id,
                                            seed=91000 + index, player_identity=identity)
                    state = create_match(roster, human_player_ids=frozenset())
                    engine = GameEngine(state)
                    engine.start()
                    self.assertTrue(engine.finished)
                    self.assertIn(state.result, {"draw", "player_side_win", "opposing_side_win",
                                                 "ai_side_win", "lord_side_win", "rebel_side_win",
                                                 "turncoat_side_win"})
                    assert_card_zone_invariant(state)
                    checked += 1
        self.assertEqual(checked, len(MODE_BY_ID) * len(HERO_BY_ID))

    def test_identity_mode_lord_rebel_and_turncoat_victories(self) -> None:
        def identity_engine(player_identity: Identity = Identity.LORD) -> GameEngine:
            roster = resolve_roster(mode_id="five_player_identity", player_hero_id="caocao",
                                    player_identity=player_identity, seed=917)
            state = create_match(roster)
            for player in state.players:
                player.identity = {
                    "P1": player_identity.value,
                    "AI1": Identity.LORD.value if player_identity is not Identity.LORD else Identity.LOYALIST.value,
                    "AI2": Identity.LOYALIST.value if player_identity is not Identity.LORD else Identity.REBEL.value,
                    "AI3": Identity.REBEL.value if player_identity is not Identity.LORD else Identity.REBEL.value,
                    "AI4": Identity.TURNCOAT.value,
                }[player.player_id]
                player.identity_public = player.identity == Identity.LORD.value
            return GameEngine(state, ai=PassAI())

        lord = identity_engine()
        lord._kill_player("AI2", None)
        lord._kill_player("AI3", None)
        self.assertIsNone(lord.state.result)
        lord._kill_player("AI4", None)
        self.assertEqual(lord.state.result, "lord_side_win")
        self.assertEqual(lord.player_outcome, "win")

        rebel = identity_engine()
        rebel._player("P1").identity = Identity.REBEL.value
        rebel._player("AI1").identity = Identity.LORD.value
        rebel._player("AI2").identity = Identity.LOYALIST.value
        rebel._player("AI3").identity = Identity.REBEL.value
        rebel._player("AI4").identity = Identity.TURNCOAT.value
        rebel._kill_player("AI1", None)
        self.assertEqual(rebel.state.result, "rebel_side_win")
        self.assertEqual(rebel.player_outcome, "win")

        turncoat = identity_engine(Identity.TURNCOAT)
        turncoat._player("AI1").identity = Identity.LORD.value
        turncoat._player("AI2").identity = Identity.LOYALIST.value
        turncoat._player("AI3").identity = Identity.REBEL.value
        turncoat._player("AI4").identity = Identity.REBEL.value
        turncoat._kill_player("AI2", None)
        turncoat._kill_player("AI3", None)
        turncoat._kill_player("AI4", None)
        self.assertIsNone(turncoat.state.result)
        turncoat._kill_player("AI1", None)
        self.assertEqual(turncoat.state.result, "turncoat_side_win")
        self.assertEqual(turncoat.player_outcome, "win")
        for engine in (lord, rebel, turncoat):
            assert_card_zone_invariant(engine.state)

    def test_dead_loyalist_player_outcome_follows_the_lord_side_victory(self) -> None:
        roster = resolve_roster(mode_id="five_player_identity", player_hero_id="caocao",
                                player_identity=Identity.LOYALIST, seed=119)
        state = create_match(roster)
        identities = {"P1": "loyalist", "AI1": "lord", "AI2": "rebel",
                      "AI3": "rebel", "AI4": "turncoat"}
        for player in state.players:
            player.identity = identities[player.player_id]
            player.identity_public = player.identity == Identity.LORD.value
        engine = GameEngine(state, ai=PassAI())

        engine._kill_player("P1", "AI2")
        self.assertIsNone(engine.state.result)
        self.assertEqual(engine.player_outcome, None)
        engine._kill_player("AI2", "AI1")
        engine._kill_player("AI3", "AI1")
        engine._kill_player("AI4", "AI1")

        self.assertEqual(engine.state.result, "lord_side_win")
        self.assertEqual(engine.player_outcome, "win")
        assert_card_zone_invariant(engine.state)

    def test_duel_and_two_heroes_victory_and_player_outcome(self) -> None:
        duel_win = make_engine("duel")
        duel_win._kill_player("AI1", None)
        self.assertEqual((duel_win.state.result, duel_win.player_outcome),
                         ("player_side_win", "win"))
        duel_loss = make_engine("duel")
        duel_loss._kill_player("P1", None)
        self.assertEqual((duel_loss.state.result, duel_loss.player_outcome),
                         ("opposing_side_win", "loss"))

        two_heroes_win = make_engine("two_heroes")
        two_heroes_win._kill_player("AI1", None)
        self.assertIsNone(two_heroes_win.state.result)
        two_heroes_win._kill_player("AI2", None)
        self.assertEqual((two_heroes_win.state.result, two_heroes_win.player_outcome),
                         ("player_side_win", "win"))
        two_heroes_loss = make_engine("two_heroes")
        two_heroes_loss._kill_player("P1", None)
        self.assertEqual((two_heroes_loss.state.result, two_heroes_loss.player_outcome),
                         ("ai_side_win", "loss"))
        for engine in (duel_win, duel_loss, two_heroes_win, two_heroes_loss):
            assert_card_zone_invariant(engine.state)

    def test_rescue_pass_hands_off_to_next_rescuer_and_stops_when_saved(self) -> None:
        engine = make_engine()
        engine._player("AI2").hp = 0
        p1_peach = put_hand(engine, "P1", "tao")
        ai1_peach = put_hand(engine, "AI1", "tao")
        engine.ai = RouteAI(lambda _view, request:
                            f"peach:{ai1_peach}" if request.kind == "rescue" else None)

        def responder(request):
            if request.kind == "rescue" and request.player_id == "P1":
                return "pass"
            if request.kind == "rescue" and request.player_id == "AI1":
                return f"peach:{ai1_peach}"
            return next((option.choice_id for option in request.options
                         if option.category == "pass"), request.options[0].choice_id)

        run_generator(engine, engine._rescue("AI2"), responder)
        self.assertEqual(engine._player("AI2").hp, 1)
        self.assertTrue(engine._player("AI2").alive)
        self.assertEqual(engine.state.cards[ai1_peach].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[p1_peach].zone_id, "P1.hand")
        self.assertEqual(sum(log.text.count("使用桃救援") for log in engine.logs), 1)
        assert_card_zone_invariant(engine.state)

    def test_guanxing_total_card_shortage_ends_without_partial_reveal(self) -> None:
        engine = make_engine()
        draw = engine._zone("draw_pile")
        chosen_card = draw.card_ids[0]
        for card_id in tuple(draw.card_ids[1:]):
            engine._move(card_id, "resolving", owner_id=None, controller_id=None,
                         visibility=Visibility.HIDDEN)
        remaining = tuple(draw.card_ids)
        run_generator(engine, engine._resolve_guanxing("P1"))
        self.assertEqual(engine.state.result, "draw")
        self.assertEqual(engine.state.end_reason, "C-04_insufficient_cards")
        self.assertEqual(engine._zone("draw_pile").card_ids, list(remaining))
        self.assertFalse(any("观星查看：" in log.text for log in engine.logs))
        self.assertEqual(engine.state.cards[chosen_card].zone_id, "draw_pile")
        assert_card_zone_invariant(engine.state)


class Stage2CardTests(unittest.TestCase):
    def test_sha_and_peach_resolve_with_physical_card_destinations(self) -> None:
        engine = make_engine()
        sha = put_hand(engine, "P1", "sha")
        intent = action(engine, kind_id="sha", target_id="AI1", card_id=sha)
        hp = engine._player("AI1").hp
        engine.submit_action(intent)
        self.assertEqual(engine._player("AI1").hp, hp - 1)
        self.assertEqual(engine.state.cards[sha].zone_id, "discard_pile")
        engine._player("P1").hp -= 1
        tao = put_hand(engine, "P1", "tao")
        engine.submit_action(action(engine, kind_id="tao", card_id=tao))
        self.assertEqual(engine._player("P1").hp, engine._player("P1").max_hp)
        self.assertEqual(engine.state.cards[tao].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_area_tricks_offer_independent_nullification_and_keep_zone_invariant(self) -> None:
        engine = make_engine()
        dismantle = put_hand(engine, "P1", "dismantle")
        target_card = put_equipment(engine, "AI1", "axe")

        def respond(request):
            if request.kind == "dismantle_area":
                return "equipment"
            if request.kind == "dismantle_visible_card":
                return f"card:{target_card}"
            return next((item.choice_id for item in request.options if item.category == "pass"),
                        request.options[0].choice_id)

        engine.submit_action(action(engine, kind_id="dismantle", target_id="AI1", card_id=dismantle))
        while engine.pending_request:
            request = engine.pending_request
            engine.answer_prompt(respond(request))
        self.assertEqual(engine.state.cards[target_card].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[dismantle].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_steal_uses_public_judgment_area_and_qianxun_is_immune(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "guanyu")
        set_hero(engine, "AI2", "luxun")
        steal = put_hand(engine, "P1", "steal")
        delayed = place(engine, "indulgence", engine._player("AI1").judgment_zone_id,
                        owner_id="AI1", controller_id="AI1", visibility=Visibility.PUBLIC)
        engine.submit_action(action(engine, kind_id="steal", target_id="AI1", card_id=steal))
        while engine.pending_request:
            request = engine.pending_request
            choice_id = "judgment" if request.kind == "steal_area" else next(
                (item.choice_id for item in request.options if item.category == "pass"),
                request.options[0].choice_id,
            )
            engine.answer_prompt(choice_id)
        self.assertEqual(engine.state.cards[delayed].zone_id, "P1.hand")
        self.assertEqual(engine.state.cards[steal].zone_id, "discard_pile")
        immune_steal = put_hand(engine, "P1", "steal")
        self.assertNotIn("AI2", engine.legal_targets_for_card("P1", immune_steal))

    def test_dismantle_randomly_discards_hidden_hand_and_steal_selects_public_judgment(self) -> None:
        engine = make_engine()
        dismantle = put_hand(engine, "P1", "dismantle")
        hidden_before = tuple(engine._zone("AI1.hand").card_ids)
        submit(engine, action(engine, kind_id="dismantle", target_id="AI1", card_id=dismantle),
               lambda request: "hand" if request.kind == "dismantle_area" else "pass")
        self.assertEqual(len(engine._zone("AI1.hand").card_ids), len(hidden_before) - 1)
        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile"
                             for item in hidden_before), 1)
        self.assertTrue(any("一张隐藏手牌" in log.text for log in engine.logs))

        second = make_engine()
        set_hero(second, "AI1", "guanyu")
        steal = put_hand(second, "P1", "steal")
        first_judgment = place(second, "indulgence", "AI1.judgment", owner_id="AI1",
                               controller_id="AI1", visibility=Visibility.PUBLIC)
        selected_judgment = place(second, "lightning", "AI1.judgment", owner_id="AI1",
                                  controller_id="AI1", visibility=Visibility.PUBLIC)

        submit(second, action(second, kind_id="steal", target_id="AI1", card_id=steal),
               lambda request: ("judgment" if request.kind == "steal_area" else
                                f"card:{selected_judgment}" if request.kind == "steal_visible_card"
                                else "pass"))
        self.assertEqual(second.state.cards[selected_judgment].zone_id, "P1.hand")
        self.assertEqual(second.state.cards[first_judgment].zone_id, "AI1.judgment")
        assert_card_zone_invariant(engine.state)
        assert_card_zone_invariant(second.state)

    def test_borrow_sword_refusal_transfers_weapon_to_requester_hand(self) -> None:
        engine = make_engine()
        card = put_hand(engine, "P1", "borrow_sword")
        weapon = put_equipment(engine, "AI1", "axe")
        engine.submit_action(action(engine, kind_id="borrow_sword", target_id="AI1", card_id=card))
        self.assertEqual(engine.state.cards[weapon].zone_id, "P1.hand")
        self.assertEqual(engine.state.cards[card].zone_id, "discard_pile")

    def test_borrow_sword_success_uses_the_wielder_as_kill_source(self) -> None:
        engine = make_engine()
        borrow = put_hand(engine, "P1", "borrow_sword")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            if card_id != borrow:
                engine._discard_card(card_id)
        weapon = put_equipment(engine, "AI1", "axe")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        kill = put_hand(engine, "AI1", "sha")
        offered_targets = []

        def route(_view, request):
            if request.kind == "borrow_sword_target":
                offered_targets.extend(option.value for option in request.options)
                return "target:P1"
            if request.kind == "duel_kill":
                return next(option.choice_id for option in request.options
                            if option.category == "kill")
            return None

        engine.ai = RouteAI(route)
        before = engine._player("P1").hp

        submit(engine, action(engine, kind_id="borrow_sword", target_id="AI1", card_id=borrow),
               lambda request: "pass")

        self.assertEqual(engine._player("P1").hp, before - 1)
        self.assertEqual(engine.state.cards[weapon].zone_id, "AI1.equipment")
        self.assertEqual(engine.state.cards[kill].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[borrow].zone_id, "discard_pile")
        self.assertIn("P1", offered_targets)
        self.assertNotIn("AI1", offered_targets)
        self.assertTrue(any(
            log.text.startswith(f"{engine._hero_name(engine._player('P1'))}受到"
                                f"{engine._hero_name(engine._player('AI1'))}造成的")
            and "杀伤害" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_borrow_sword_does_not_offer_weapon_conversion_outside_post_payment_range(self) -> None:
        engine = make_engine("five_player_identity", hero_id="caocao",
                             identity=Identity.LORD)
        set_hero(engine, "AI1", "guanyu")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        axe = place(engine, "axe", "AI1.equipment", owner_id="AI1",
                    controller_id="AI1", visibility=Visibility.PUBLIC,
                    suit="diamonds")
        borrow = put_hand(engine, "P1", "borrow_sword")
        distant_hp = engine._player("AI3").hp
        requests = []

        def route(_view, request):
            requests.append(request.kind)
            if request.kind == "borrow_sword_target":
                return "target:AI3"
            if request.kind == "duel_kill":
                return f"wusheng:{axe}"
            return None

        engine.ai = RouteAI(route)
        submit(engine, action(engine, kind_id="borrow_sword", target_id="AI1",
                              card_id=borrow))

        self.assertNotIn("duel_kill", requests)
        self.assertEqual(engine._player("AI3").hp, distant_hp)
        self.assertEqual(engine.state.cards[axe].zone_id, "P1.hand")
        self.assertEqual(engine.state.cards[borrow].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

        adjacent = make_engine("five_player_identity", hero_id="caocao",
                               identity=Identity.LORD)
        set_hero(adjacent, "AI1", "guanyu")
        for card_id in tuple(adjacent._zone("AI1.hand").card_ids):
            adjacent._discard_card(card_id)
        red_axe = place(adjacent, "axe", "AI1.equipment", owner_id="AI1",
                        controller_id="AI1", visibility=Visibility.PUBLIC,
                        suit="diamonds")
        borrow = put_hand(adjacent, "P1", "borrow_sword")
        close_hp = adjacent._player("AI2").hp
        adjacent.ai = RouteAI(lambda _view, request:
                              "target:AI2" if request.kind == "borrow_sword_target" else
                              f"wusheng:{red_axe}" if request.kind == "duel_kill" else None)

        submit(adjacent, action(adjacent, kind_id="borrow_sword", target_id="AI1",
                                card_id=borrow))

        self.assertEqual(adjacent._player("AI2").hp, close_hp - 1)
        self.assertEqual(adjacent.state.cards[red_axe].zone_id, "discard_pile")
        assert_card_zone_invariant(adjacent.state)

    def test_aoe_and_peach_garden_apply_one_target_at_a_time(self) -> None:
        engine = make_engine()
        put_hand(engine, "P1", "arrows")
        for enemy in ("AI1", "AI2"):
            engine._player(enemy).hp = engine._player(enemy).max_hp
        arrows = next(card_id for card_id in engine._zone("P1.hand").card_ids
                      if engine._definition(card_id).kind_id == "arrows")
        intent = action(engine, kind_id="arrows", card_id=arrows)
        engine.submit_action(intent)
        self.assertEqual([engine._player(item).hp for item in ("AI1", "AI2")],
                         [engine._player(item).max_hp - 1 for item in ("AI1", "AI2")])
        peach_garden = put_hand(engine, "P1", "peach_garden")
        engine.submit_action(action(engine, kind_id="peach_garden", card_id=peach_garden))
        self.assertEqual([engine._player(item).hp for item in ("P1", "AI1", "AI2")],
                         [engine._player(item).max_hp for item in ("P1", "AI1", "AI2")])

    def test_equipment_slots_ranges_and_both_mount_directions(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        weapon_ranges = {
            "crossbow": 1, "double_swords": 2, "qinggang_sword": 2,
            "frost_sword": 2, "qinglong_blade": 3, "serpent_spear": 3,
            "axe": 3, "halberd": 4, "kirin_bow": 5,
        }
        for kind_id, expected_range in weapon_ranges.items():
            weapon = put_equipment(engine, "P1", kind_id)
            self.assertEqual(engine.attack_range("P1"), expected_range)
            engine._discard_card(weapon)
        put_equipment(engine, "P1", "chitu")
        put_equipment(engine, "P1", "jueying")
        self.assertEqual(engine.distance("P1", "AI3"), 1)
        self.assertEqual(engine.distance("AI3", "P1"), 3)
        self.assertEqual(engine.distance("P1", "P1"), 0)
        assert_card_zone_invariant(engine.state)

    def test_barbarians_excludes_source_and_resolves_other_players_clockwise(self) -> None:
        engine = make_engine()
        barbarians = put_hand(engine, "P1", "barbarians")
        before = {player_id: engine._player(player_id).hp for player_id in ("P1", "AI1", "AI2")}
        submit(engine, action(engine, kind_id="barbarians", card_id=barbarians))
        self.assertEqual(engine._player("P1").hp, before["P1"])
        self.assertEqual(engine._player("AI1").hp, before["AI1"] - 1)
        self.assertEqual(engine._player("AI2").hp, before["AI2"] - 1)

    def test_harvest_deals_one_visible_card_to_each_live_player(self) -> None:
        engine = make_engine()
        harvest = put_hand(engine, "P1", "harvest")
        top_cards = tuple(engine._zone("draw_pile").card_ids[:3])
        initial = {player_id: len(engine._zone(f"{player_id}.hand").card_ids)
                   for player_id in ("P1", "AI1", "AI2")}
        submit(engine, action(engine, kind_id="harvest", card_id=harvest),
               lambda request: ("pass" if request.kind == "nullification"
                                else choose(request, "take")))
        self.assertEqual(len(engine._zone("P1.hand").card_ids), initial["P1"])
        self.assertEqual(len(engine._zone("AI1.hand").card_ids), initial["AI1"] + 1)
        self.assertEqual(len(engine._zone("AI2.hand").card_ids), initial["AI2"] + 1)
        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile" for item in top_cards), 0)
        self.assertEqual(engine.state.cards[harvest].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_duel_uses_target_first_response_and_stops_nullification_after_start(self) -> None:
        engine = make_engine()
        engine._player("AI1").hero_id = "guanyu"
        duel = put_hand(engine, "P1", "duel")
        target_hp = engine._player("AI1").hp
        observed = []

        def route(request):
            observed.append(request.kind)
            if request.kind == "nullification":
                return "pass"
            return next((option.choice_id for option in request.options
                         if option.category == "pass"), request.options[0].choice_id)

        submit(engine, action(engine, kind_id="duel", target_id="AI1", card_id=duel), route)
        self.assertEqual(engine._player("AI1").hp, target_hp - 1)
        self.assertNotIn("nullification", observed[1:])
        self.assertEqual(engine.state.cards[duel].zone_id, "discard_pile")

    def test_draw_two_obeys_its_nullification_window_and_full_draw(self) -> None:
        engine = make_engine()
        draw_two = put_hand(engine, "P1", "draw_two")
        before = len(engine._zone("P1.hand").card_ids)
        submit(engine, action(engine, kind_id="draw_two", card_id=draw_two),
               lambda request: "pass" if request.kind == "nullification" else request.options[0].choice_id)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 1)
        self.assertEqual(engine.state.cards[draw_two].zone_id, "discard_pile")

    def test_kirin_bow_is_offered_for_kill_damage_only(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "kirin_bow")
        mount = put_equipment(engine, "AI1", "dilu")
        before = engine._player("AI1").hp
        run_generator(engine, engine._damage("P1", "AI1", 1, None, damage_kind="反间"))
        self.assertEqual(engine._player("AI1").hp, before - 1)
        self.assertEqual(engine.state.cards[mount].zone_id, "AI1.equipment")
        self.assertFalse(any("麒麟弓" in log.text for log in engine.logs))

    def test_kirin_bow_can_choose_a_mount_before_kill_damage(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "kirin_bow")
        mounts = (put_equipment(engine, "AI1", "dilu"),
                  put_equipment(engine, "AI1", "jueying"))
        slash = put_hand(engine, "P1", "sha")
        before = engine._player("AI1").hp
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: next(option.choice_id for option in request.options
                                    if option.category == "mount")
               if request.kind == "kirin_bow" else "pass")
        self.assertEqual(engine._player("AI1").hp, before - 1)
        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile"
                             for item in mounts), 1)

    def test_crossbow_removes_kill_limit_and_losing_it_restores_the_limit(self) -> None:
        engine = make_engine()
        crossbow = put_equipment(engine, "P1", "crossbow")
        first = put_hand(engine, "P1", "sha")
        second = put_hand(engine, "P1", "sha")
        engine.submit_action(action(engine, kind_id="sha", target_id="AI1", card_id=first))
        self.assertTrue(any(item.intent.card_id == second
                            for item in engine.available_actions("P1")))
        engine._discard_card(crossbow)
        self.assertFalse(any(item.intent.card_id == second
                             for item in engine.available_actions("P1")))

    def test_halberd_adds_only_optional_targets_for_last_hand_slash(self) -> None:
        engine = make_engine()
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        put_equipment(engine, "P1", "halberd")
        slash = put_hand(engine, "P1", "sha")
        before = {player_id: engine._player(player_id).hp for player_id in ("AI1", "AI2")}
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: "target:AI2" if request.kind == "halberd_targets" else "pass")
        self.assertEqual(engine._player("AI1").hp, before["AI1"] - 1)
        self.assertEqual(engine._player("AI2").hp, before["AI2"] - 1)

    def test_halberd_liuli_targets_resolve_in_final_action_order_with_duplicates(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        set_hero(engine, "AI1", "daqiao")
        set_hero(engine, "AI2", "guojia")
        set_hero(engine, "AI4", "zhangliao")
        put_equipment(engine, "AI1", "chitu")
        liuli_cost = engine._zone("AI1.hand").card_ids[0]
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        put_equipment(engine, "P1", "halberd")
        slash = put_hand(engine, "P1", "sha")
        engine.ai = RouteAI(lambda _view, request:
                            f"discard:{liuli_cost}" if request.kind == "liuli" else
                            "target:AI4" if request.kind == "liuli_target" else None)

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: ("target:AI2", "target:AI4")
               if request.kind == "halberd_targets" else "pass")

        damage_order = [player.player_id for log in engine.logs for player in engine.state.players
                        if log.text.startswith(f"{engine._hero_name(player)}受到")
                        and "杀伤害" in log.text]
        self.assertEqual(damage_order, ["AI2", "AI4", "AI4"])
        self.assertEqual(engine._player("AI1").hp, engine._player("AI1").max_hp)
        self.assertEqual(engine._player("AI4").hp, engine._player("AI4").max_hp - 2)
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_bagua_red_judgment_supplies_a_flash(self) -> None:
        engine = make_engine()
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        put_equipment(engine, "P1", "bagua_formation")
        red = next(card_id for card_id in engine._zone("draw_pile").card_ids
                   if engine._color(card_id) == "red")
        draw = engine._zone("draw_pile").card_ids
        draw.remove(red)
        draw.insert(0, red)
        result = run_generator(engine, engine._ask_flash("P1", "AI1", None),
                               lambda request: "bagua" if request.kind == "flash" else "pass")
        self.assertEqual(engine._player("P1").hp, engine._player("P1").max_hp)
        self.assertEqual(engine.state.cards[red].zone_id, "discard_pile")
        self.assertIsNone(result)

    def test_bagua_black_judgment_can_be_followed_by_a_hand_flash(self) -> None:
        engine = make_engine()
        put_equipment(engine, "AI1", "bagua_formation")
        flash = put_hand(engine, "AI1", "shan")
        black = next(card_id for card_id in engine._zone("draw_pile").card_ids
                     if engine._color(card_id) == "black")
        draw = engine._zone("draw_pile").card_ids
        draw.remove(black)
        draw.insert(0, black)
        engine.ai = RouteAI(lambda _view, request:
                            "bagua" if request.kind == "flash" and any(
                                option.choice_id == "bagua" for option in request.options) else
                            f"flash:{flash}" if request.kind == "flash" else None)
        result = complete_without_prompts(engine._ask_flash("AI1", "P1", None))
        self.assertTrue(result)
        self.assertEqual(engine.state.cards[black].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[flash].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_two_nullifications_restore_the_original_effect(self) -> None:
        engine = make_engine()
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        negates = (put_hand(engine, "P1", "negate"), put_hand(engine, "P1", "negate"))
        trick = next(card_id for card_id, instance in engine.state.cards.items()
                     if CARD_BY_ID[instance.definition_id].kind_id == "draw_two")
        uses = []

        def route(request):
            uses.append(request.kind)
            if request.kind == "nullification":
                used = sum(engine.state.cards[item].zone_id == "discard_pile" for item in negates)
                return f"negate:{negates[used]}" if used < 2 else "pass"
            return "pass"

        def drive(gen):
            try:
                request = next(gen)
                while True:
                    request = gen.send(route(request))
            except StopIteration as result:
                return result.value

        self.assertFalse(drive(engine._nullification_window("AI1", trick,
                                                            trick_kind_id="draw_two")))
        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile"
                             for item in negates), 2)

    def test_odd_nullification_chain_cancels_only_its_effect(self) -> None:
        engine = make_engine(human_player_ids=frozenset({"P1", "AI1", "AI2"}))
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                if engine._definition(card_id).kind_id == "negate":
                    engine._discard_card(card_id)
        negates = (put_hand(engine, "P1", "negate"),
                   put_hand(engine, "AI1", "negate"),
                   put_hand(engine, "AI2", "negate"))
        trick = next(card_id for card_id, instance in engine.state.cards.items()
                     if CARD_BY_ID[instance.definition_id].kind_id == "draw_two")

        def drive(gen):
            try:
                request = next(gen)
                while True:
                    available = next((card_id for card_id in negates
                                      if engine.state.cards[card_id].zone_id
                                      == f"{request.player_id}.hand"), None)
                    choice = f"negate:{available}" if available else "pass"
                    request = gen.send(choice)
            except StopIteration as result:
                return result.value

        self.assertTrue(drive(engine._nullification_window(
            "AI1", trick, trick_kind_id="draw_two")))
        self.assertTrue(all(engine.state.cards[item].zone_id == "discard_pile"
                            for item in negates))
        assert_card_zone_invariant(engine.state)

    def test_indulgence_judgment_skips_play_on_nonheart_and_discards_both_cards(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "guanyu")
        delayed = put_hand(engine, "P1", "indulgence")
        engine.submit_action(action(engine, kind_id="indulgence", target_id="AI1", card_id=delayed))
        self.assertEqual(engine.state.cards[delayed].zone_id, "AI1.judgment")
        draw = engine._zone("draw_pile").card_ids
        nonheart = next(card_id for card_id in draw
                        if engine._definition(card_id).suit.value != "hearts")
        draw.remove(nonheart)
        draw.insert(0, nonheart)
        run_generator(engine, engine._resolve_judgment_zone(engine._player("AI1")))
        self.assertIn("AI1", engine._skip_play)
        self.assertEqual(engine.state.cards[delayed].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[nonheart].zone_id, "discard_pile")

    def test_lightning_passes_to_next_player_without_returning_to_its_owner(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        lightning = place(engine, "lightning", engine._player("P1").judgment_zone_id,
                          owner_id="P1", controller_id="P1", visibility=Visibility.PUBLIC)
        engine._pass_lightning("P1", lightning)
        self.assertEqual(engine.state.cards[lightning].zone_id, "AI1.judgment")

    def test_delays_resolve_later_placed_first_and_same_kind_cannot_be_repeated(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "guanyu")
        lightning = place(engine, "lightning", "AI1.judgment", owner_id="AI1",
                          controller_id="AI1", visibility=Visibility.PUBLIC)
        indulgence = place(engine, "indulgence", "AI1.judgment", owner_id="AI1",
                           controller_id="AI1", visibility=Visibility.PUBLIC)
        repeated_indulgence = put_hand(engine, "P1", "indulgence")
        self.assertNotIn("AI1", engine.legal_targets_for_card("P1", repeated_indulgence))
        draw = engine._zone("draw_pile").card_ids
        first_judgment = next(card_id for card_id in draw
                              if engine._definition(card_id).suit.value != "hearts")
        second_judgment = next(card_id for card_id in draw
                               if card_id != first_judgment
                               and not (engine._definition(card_id).suit.value == "spades"
                                        and 2 <= engine._definition(card_id).rank <= 9))
        draw.remove(first_judgment)
        draw.remove(second_judgment)
        draw[:0] = [first_judgment, second_judgment]
        run_generator(engine, engine._resolve_judgment_zone(engine._player("AI1")))

        order = [log.text for log in engine.logs if "进行" in log.text and "判定，翻开" in log.text]
        self.assertIn("进行乐不思蜀判定", order[0])
        self.assertIn("进行闪电判定", order[1])
        self.assertEqual(engine.state.cards[indulgence].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[first_judgment].zone_id, "discard_pile")
        self.assertIn("AI1", engine._skip_play)
        self.assertEqual(engine.state.cards[lightning].zone_id, "AI2.judgment")

        assert_card_zone_invariant(engine.state)

    def test_nullified_lightning_passes_but_a_terminal_response_does_not_continue(self) -> None:
        engine = make_engine()
        lightning = place(engine, "lightning", "P1.judgment", owner_id="P1",
                          controller_id="P1", visibility=Visibility.PUBLIC)
        negate = put_hand(engine, "P1", "negate")
        run_generator(engine, engine._resolve_judgment_zone(engine._player("P1")),
                      lambda request: f"negate:{negate}" if request.kind == "nullification" else "pass")
        self.assertEqual(engine.state.cards[lightning].zone_id, "AI1.judgment")

        terminal = make_engine()
        waiting = place(terminal, "lightning", "P1.judgment", owner_id="P1",
                        controller_id="P1", visibility=Visibility.PUBLIC)
        def finish_during_window(_target_id, _card_id, **_kwargs):
            terminal._finish("draw", "C-04_insufficient_cards", "固定终局夹具")
            if False:
                yield
            return True
        terminal._nullification_window = finish_during_window  # type: ignore[method-assign]
        run_generator(terminal, terminal._resolve_judgment_zone(terminal._player("P1")))

        self.assertEqual(terminal.state.result, "draw")
        self.assertEqual(terminal.state.cards[waiting].zone_id, "P1.judgment")
        self.assertFalse(any("闪电传给" in log.text for log in terminal.logs))
        assert_card_zone_invariant(terminal.state)

    def test_cixiong_sword_prompts_only_after_locking_an_opposite_gender_target(self) -> None:
        engine = make_engine(hero_id="daqiao")
        set_hero(engine, "AI1", "guanyu")
        put_equipment(engine, "P1", "double_swords")
        enemy_equipment = put_equipment(engine, "AI1", "axe")
        enemy_judgment = place(engine, "lightning", "AI1.judgment", owner_id="AI1",
                               controller_id="AI1", visibility=Visibility.PUBLIC)
        slash = put_hand(engine, "P1", "sha")
        target_card = engine._zone("AI1.hand").card_ids[0]
        offered_cards = []

        def route(_view, request):
            if request.kind == "double_swords_target":
                offered_cards.extend(option.value for option in request.options
                                     if option.category == "discard")
                return next(option.choice_id for option in request.options
                            if option.category == "discard")
            return None

        engine.ai = RouteAI(route)
        before = engine._player("AI1").hp
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: "yes" if request.kind == "double_swords" else
               f"discard:{target_card}" if request.kind == "double_swords_target" else "pass")
        self.assertEqual(engine.state.cards[target_card].zone_id, "discard_pile")
        self.assertIn(target_card, offered_cards)
        self.assertNotIn(enemy_equipment, offered_cards)
        self.assertNotIn(enemy_judgment, offered_cards)
        self.assertEqual(engine._player("AI1").hp, before - 1)

    def test_cixiong_sword_forces_a_draw_when_the_opposite_gender_target_has_no_hand(self) -> None:
        engine = make_engine(hero_id="daqiao")
        set_hero(engine, "AI1", "guanyu")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        put_equipment(engine, "P1", "double_swords")
        slash = put_hand(engine, "P1", "sha")
        drawn = engine._zone("draw_pile").card_ids[0]
        before = len(engine._zone("P1.hand").card_ids)
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: "yes" if request.kind == "double_swords" else "pass")
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before)
        self.assertEqual(engine.state.cards[drawn].zone_id, "P1.hand")

    def test_random_five_player_identity_assignment_is_reproducible_and_hidden(self) -> None:
        first_roster = resolve_roster(mode_id="five_player_identity", player_hero_id="caocao",
                                      seed=98231)
        repeated_roster = resolve_roster(mode_id="five_player_identity", player_hero_id="caocao",
                                         seed=98231)
        other_roster = resolve_roster(mode_id="five_player_identity", player_hero_id="caocao",
                                      seed=98232)
        identities = dict(first_roster.identities)
        self.assertEqual(first_roster.identities, repeated_roster.identities)
        self.assertEqual(set(identities.values()), {"lord", "loyalist", "rebel", "turncoat"})
        self.assertEqual(tuple(identities.values()).count("rebel"), 2)
        self.assertNotEqual(first_roster.identities, other_roster.identities)

        first = create_match(first_roster)
        repeated = create_match(repeated_roster)
        self.assertEqual([(p.player_id, p.seat_index) for p in first.players],
                         [(p.player_id, p.seat_index) for p in repeated.players])
        self.assertEqual(first.current_player_id,
                         next(player.player_id for player in first.players
                              if player.identity == "lord"))
        self.assertEqual({p.player_id for p in first.players if p.identity_public},
                         {p.player_id for p in first.players if p.identity == "lord"})
        self.assertTrue(all(len(first.zones[p.hand_zone_id].card_ids) == 4
                            for p in first.players))

    def test_all_six_turn_phases_run_in_order_and_skipped_play_keeps_later_phases(self) -> None:
        engine = make_engine()
        phase_trace = []
        original_preparation = engine._preparation_skills
        original_judgment = engine._resolve_judgment_zone
        original_draw = engine._draw_cards
        original_discard = engine._discard_phase
        original_end_skills = engine._resolve_end_skills
        original_end_turn = engine._end_turn

        def trace_preparation(player):
            phase_trace.append(("preparation", engine.state.phase))
            yield from original_preparation(player)

        def trace_judgment(player):
            phase_trace.append(("judgment", engine.state.phase))
            yield from original_judgment(player)

        def trace_draw(count, reason):
            if "摸牌阶段" in reason:
                phase_trace.append(("draw", engine.state.phase))
            return original_draw(count, reason)

        def trace_discard(player):
            yield from original_discard(player)
            phase_trace.append(("discard", engine.state.phase))

        def trace_end_skills(player):
            yield from original_end_skills(player)
            phase_trace.append(("end", engine.state.phase))

        def trace_end_turn(player):
            original_end_turn(player)
            phase_trace.append(("turn_end", engine.state.phase))

        engine._preparation_skills = trace_preparation
        engine._resolve_judgment_zone = trace_judgment
        engine._draw_cards = trace_draw
        engine._discard_phase = trace_discard
        engine._resolve_end_skills = trace_end_skills
        engine._end_turn = trace_end_turn

        run_generator(engine, engine._start_turn(engine._player("P1")))
        self.assertEqual(engine.state.phase, GamePhase.PLAY)
        phase_trace.append(("play", engine.state.phase))
        run_generator(engine, engine._discard_phase(engine._player("P1")),
                      lambda request: tuple(option.choice_id for option in request.options
                                             if option.category == "discard")[:request.min_choices]
                      if request.kind == "discard" else "pass")
        run_generator(engine, engine._resolve_end_skills(engine._player("P1")))
        engine._end_turn(engine._player("P1"))
        self.assertEqual([label for label, _ in phase_trace],
                         ["preparation", "judgment", "draw", "play",
                          "discard", "end", "turn_end"])
        self.assertEqual([phase for _, phase in phase_trace],
                         [GamePhase.PREPARATION, GamePhase.JUDGMENT, GamePhase.DRAW,
                          GamePhase.PLAY, GamePhase.DISCARD, GamePhase.END, GamePhase.END])

        skipped = make_engine()
        target = skipped._player("P1")
        delayed = place(skipped, "indulgence", target.judgment_zone_id,
                         owner_id="P1", controller_id="P1", visibility=Visibility.PUBLIC)
        nonheart = next(card_id for card_id in skipped._zone("draw_pile").card_ids
                        if skipped._definition(card_id).suit.value != "hearts")
        skipped._zone("draw_pile").card_ids.remove(nonheart)
        skipped._zone("draw_pile").card_ids.insert(0, nonheart)
        hand_before = len(skipped._zone("P1.hand").card_ids)
        run_generator(skipped, skipped._start_turn(target))
        self.assertEqual(skipped.state.phase, GamePhase.DISCARD)
        self.assertEqual(len(skipped._zone("P1.hand").card_ids), hand_before + 2)
        self.assertNotIn("P1", skipped._skip_play)
        self.assertEqual(skipped.state.cards[delayed].zone_id, "discard_pile")
        self.assertFalse(skipped.available_actions("P1"))
        run_generator(skipped, skipped._discard_phase(target),
                      lambda request: tuple(option.choice_id for option in request.options
                                             if option.category == "discard")[:request.min_choices]
                      if request.kind == "discard" else "pass")
        run_generator(skipped, skipped._resolve_end_skills(target))
        self.assertEqual(skipped.state.phase, GamePhase.END)
        assert_card_zone_invariant(skipped.state)

    def test_event_stack_tracks_nested_damage_and_human_rescue_resume(self) -> None:
        engine = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        target = engine._player("AI1")
        target.hp = 1
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            if engine._definition(card_id).name == "桃":
                engine._discard_card(card_id)
        peach = put_hand(engine, "AI1", "tao")
        flash = put_hand(engine, "AI1", "shan")
        slash = put_hand(engine, "P1", "sha")

        engine.submit_action(action(engine, kind_id="sha", target_id="AI1", card_id=slash))
        self.assertIsNotNone(engine.pending_request)
        self.assertEqual(engine.pending_request.kind, "flash")
        self.assertEqual(engine.state.cards[slash].zone_id, "resolving")
        response_frames = tuple(engine.state.event_stack)
        self.assertEqual(tuple(frame.event_type for frame in response_frames),
                         ("player_action", "resolve_action"))
        self.assertEqual(response_frames[1].parent_event_id, response_frames[0].event_id)
        self.assertTrue(all(frame.status == "waiting_input" for frame in response_frames))

        engine.answer_prompt("pass")
        self.assertIsNotNone(engine.pending_request)
        self.assertEqual(engine.pending_request.kind, "rescue")
        frames = tuple(engine.state.event_stack)
        self.assertEqual(tuple(frame.event_type for frame in frames),
                         ("player_action", "resolve_action", "damage"))
        self.assertIsNone(frames[0].parent_event_id)
        self.assertEqual(frames[1].parent_event_id, frames[0].event_id)
        self.assertEqual(frames[2].parent_event_id, frames[1].event_id)
        self.assertTrue(all(frame.status == "waiting_input" for frame in frames))

        engine.answer_prompt(f"peach:{peach}")
        self.assertTrue(all(frame.status == "completed" for frame in frames))
        self.assertTrue(all(frame.resume_cursor > 0 for frame in frames))
        self.assertEqual(engine.state.event_stack, [])
        self.assertIsNone(engine.pending_request)
        self.assertEqual(engine._player("AI1").hp, 1)
        self.assertTrue(engine._player("AI1").alive)
        self.assertEqual(engine.state.cards[peach].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[flash].zone_id, "AI1.hand")
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_terminal_abort_during_response_clears_resolving_physical_cards(self) -> None:
        engine = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        target = engine._player("AI1")
        flash = put_hand(engine, "AI1", "shan")
        slash = put_hand(engine, "P1", "sha")

        engine.submit_action(action(engine, kind_id="sha", target_id="AI1", card_id=slash))
        self.assertEqual(engine.pending_request.kind, "flash")
        self.assertEqual(engine.state.cards[slash].zone_id, "resolving")
        engine.resign()

        self.assertEqual(engine.state.result, "player_side_loss")
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[flash].zone_id, "AI1.hand")
        self.assertEqual(engine._zone("resolving").card_ids, [])
        self.assertEqual(engine.state.event_stack, [])
        assert_card_zone_invariant(engine.state)
        self.assertEqual(engine._player("AI1").hp, engine._player("AI1").max_hp)
        assert_card_zone_invariant(engine.state)

    def test_terminal_cleanup_routes_every_resolving_physical_card_once(self) -> None:
        engine = make_engine()
        physical_ids = tuple(engine.state.cards)
        for card_id in physical_ids:
            engine._move(card_id, "resolving", owner_id=None, controller_id=None,
                         visibility=Visibility.PUBLIC)

        engine._finish("draw", "C-04_insufficient_cards", "固定终局夹具")

        self.assertEqual(len(physical_ids), 108)
        self.assertEqual(engine._zone("resolving").card_ids, [])
        self.assertCountEqual(engine._zone("discard_pile").card_ids, physical_ids)
        assert_card_zone_invariant(engine.state)

    def test_frost_sword_prevents_damage_and_discards_two_legal_cards(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "frost_sword")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        target_cards = (put_hand(engine, "AI1", "sha"), put_hand(engine, "AI1", "shan"))
        slash = put_hand(engine, "P1", "sha")
        before = engine._player("AI1").hp

        def route(request):
            if request.kind == "frost_sword":
                return "yes"
            if request.kind == "dismantle_area":
                return "hand"
            return "pass"

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash), route)
        self.assertEqual(engine._player("AI1").hp, before)
        self.assertTrue(all(engine.state.cards[item].zone_id == "discard_pile" for item in target_cards))

    def test_ai_can_pay_both_cards_for_serpent_spear_response(self) -> None:
        engine = make_engine()
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        put_equipment(engine, "AI1", "serpent_spear")
        first = put_hand(engine, "AI1", "sha", suit="hearts")
        second = put_hand(engine, "AI1", "sha", suit="spades")
        engine.ai = RouteAI(lambda _view, request:
                            "serpent_spear" if request.kind == "duel_kill" else
                            tuple(option.choice_id for option in request.options
                                  if option.category == "discard")[:2]
                            if request.kind == "serpent_spear_cost" else None)
        run_generator(engine, engine._ask_kill_response("AI1", "决斗", "P1"))
        # The AI's response helper resolves without yielding to the human controller.
        self.assertTrue(engine.state.cards[first].zone_id == "resolving"
                        and engine.state.cards[second].zone_id == "resolving")
        used = next(card_id for card_id in (first, second)
                    if card_id in engine._response_extra_materials)
        self.assertIsNone(engine._response_virtual_colors[used])
        engine._discard_response_materials(used)

    def test_liuli_redirects_kill_to_another_legal_living_target(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "daqiao")
        cost = engine._zone("AI1.hand").card_ids[0]
        offered_targets = []

        def route(_view, request):
            if request.kind == "liuli":
                return f"discard:{cost}"
            if request.kind == "liuli_target":
                offered_targets.extend(option.value for option in request.options)
                return "target:AI2"
            return None

        engine.ai = RouteAI(route)
        before_daqiao = engine._player("AI1").hp
        before_ai2 = engine._player("AI2").hp
        run_generator(engine, engine._resolve_kill("P1", "AI1", None, active_play=True))
        self.assertEqual(engine._player("AI1").hp, before_daqiao)
        self.assertEqual(engine._player("AI2").hp, before_ai2 - 1)
        self.assertEqual(engine.state.cards[cost].zone_id, "discard_pile")
        self.assertIn("AI2", offered_targets)
        self.assertNotIn("P1", offered_targets)

    def test_qinglong_followup_tracks_liuli_actual_target_beyond_normal_range(self) -> None:
        engine = make_engine("five_player_identity", hero_id="zhangfei",
                             identity=Identity.LORD)
        set_hero(engine, "AI1", "daqiao")
        set_hero(engine, "AI2", "ganning")
        put_equipment(engine, "P1", "qinglong_blade")
        cost = engine._zone("AI1.hand").card_ids[0]
        for card_id in tuple(engine._zone("AI2.hand").card_ids):
            engine._discard_card(card_id)
        first_flash = put_hand(engine, "AI2", "shan")
        second_flash = put_hand(engine, "AI2", "shan")
        initial_kill = place(engine, "sha", "resolving", owner_id="P1",
                             controller_id="P1", visibility=Visibility.PUBLIC)
        followup = put_hand(engine, "P1", "sha")
        original_distance = engine.distance
        engine.distance = lambda source_id, target_id, **kwargs: (
            4 if (source_id, target_id) == ("P1", "AI2")
            else original_distance(source_id, target_id, **kwargs)
        )  # type: ignore[method-assign]
        flash_count = 0
        request_kinds = []

        def route(_view, request):
            nonlocal flash_count
            request_kinds.append(request.kind)
            if request.kind == "liuli":
                return f"discard:{cost}"
            if request.kind == "liuli_target":
                return "target:AI2"
            if request.kind == "flash":
                flash_count += 1
                return f"flash:{first_flash}" if flash_count == 1 else "pass"
            return None

        engine.ai = RouteAI(route)
        before = {player_id: engine._player(player_id).hp for player_id in ("AI1", "AI2")}
        engine._drive(engine._resolve_kill("P1", "AI1", initial_kill, active_play=True))

        self.assertEqual(engine.pending_request.kind, "qinglong_followup")
        self.assertGreater(engine.distance("P1", "AI2"), engine.attack_range("P1"))
        engine.answer_prompt(f"continue:{followup}")

        self.assertEqual(engine._player("AI1").hp, before["AI1"])
        self.assertEqual(engine._player("AI2").hp, before["AI2"] - 1)
        self.assertEqual(engine.state.cards[first_flash].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[second_flash].zone_id, "AI2.hand")
        self.assertIn("liuli_target", request_kinds)
        self.assertEqual(request_kinds.count("flash"), 2)
        self.assertIsNone(engine.pending_request)
        engine._discard_card(initial_kill)
        assert_card_zone_invariant(engine.state)


class Stage2HeroTests(unittest.TestCase):
    def test_zhangliao_tuxi_skips_normal_draw_and_takes_after_target_selection(self) -> None:
        engine = make_engine(hero_id="zhangliao")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        target_card = put_hand(engine, "AI1", "tao")
        before = len(engine._zone(engine._player("P1").hand_zone_id).card_ids)

        def choose_skill(request):
            if request.kind == "tuxi":
                return "yes"
            if request.kind == "tuxi_targets":
                return choose(request, "target", 0)
            return next((item.choice_id for item in request.options if item.category == "pass"),
                        request.options[0].choice_id)

        run_generator(engine, engine._start_turn(engine._player("P1")), choose_skill)
        self.assertEqual(engine.state.cards[target_card].zone_id, "P1.hand")
        self.assertEqual(len(engine._zone(engine._player("P1").hand_zone_id).card_ids), before + 1)

    def test_zhangliao_tuxi_can_take_from_two_targets_without_public_hand_identity(self) -> None:
        engine = make_engine(hero_id="zhangliao")
        for player_id in ("AI1", "AI2"):
            for card_id in tuple(engine._zone(f"{player_id}.hand").card_ids):
                engine._discard_card(card_id)
        target_cards = {player_id: put_hand(engine, player_id, "tao")
                        for player_id in ("AI1", "AI2")}
        before = len(engine._zone("P1.hand").card_ids)

        def choose_skill(request):
            if request.kind == "tuxi":
                return "yes"
            if request.kind == "tuxi_targets":
                return tuple(option.choice_id for option in request.options
                             if option.value in target_cards)
            return next((option.choice_id for option in request.options
                         if option.category == "pass"), request.options[0].choice_id)

        run_generator(engine, engine._start_turn(engine._player("P1")), choose_skill)
        self.assertTrue(all(engine.state.cards[card_id].zone_id == "P1.hand"
                            for card_id in target_cards.values()))
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 2)
        self.assertFalse(any("桃" in log.text for log in engine.public_logs()))
        assert_card_zone_invariant(engine.state)

    def test_zhangliao_tuxi_decline_draws_normally_and_empty_opponents_offer_no_skill(self) -> None:
        engine = make_engine(hero_id="zhangliao")
        before = len(engine._zone("P1.hand").card_ids)
        requests = []
        run_generator(engine, engine._start_turn(engine._player("P1")),
                      lambda request: (requests.append(request.kind) or "pass"))
        self.assertIn("tuxi", requests)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 2)

        empty = make_engine(hero_id="zhangliao")
        for player in empty.state.players:
            if player.player_id != "P1":
                for card_id in tuple(empty._zone(player.hand_zone_id).card_ids):
                    empty._discard_card(card_id)
        requests = []
        run_generator(empty, empty._start_turn(empty._player("P1")),
                      lambda request: (requests.append(request.kind) or "pass"))
        self.assertNotIn("tuxi", requests)
        self.assertEqual(empty.state.phase, GamePhase.PLAY)

    def test_xuchu_luoyi_bonus_is_limited_to_his_play_phase(self) -> None:
        engine = make_engine(hero_id="xuchu")

        def choose_luoyi(request):
            if request.kind == "luoyi":
                return "yes"
            return next((item.choice_id for item in request.options if item.category == "pass"),
                        request.options[0].choice_id)

        run_generator(engine, engine._start_turn(engine._player("P1")), choose_luoyi)
        before = engine._player("AI1").hp
        run_generator(engine, engine._damage("P1", "AI1", 1, None, damage_kind="决斗"))
        self.assertEqual(engine._player("AI1").hp, before - 2)
        engine.state.current_player_id = "AI1"
        before = engine._player("AI2").hp
        run_generator(engine, engine._damage("P1", "AI2", 1, None, damage_kind="决斗"))
        self.assertEqual(engine._player("AI2").hp, before - 1)

    def test_guojia_yiji_processes_each_damage_point_and_guo_jia_tiandu(self) -> None:
        engine = make_engine(hero_id="guojia")
        deck = engine._zone("draw_pile").card_ids
        yiji_cards = tuple(deck[:4])
        run_generator(engine, engine._damage("AI1", "P1", 2, None, damage_kind="测试"),
                      lambda request: "keep")
        self.assertEqual(sum(engine.state.cards[item].zone_id == "P1.hand" for item in yiji_cards), 4)
        judge_card = place(engine, "shan", "resolving", visibility=Visibility.PUBLIC)
        run_generator(engine, engine._settle_judgment("P1", judge_card),
                      lambda request: "yes" if request.kind == "tiandu" else "pass")
        self.assertEqual(engine.state.cards[judge_card].zone_id, "P1.hand")

    def test_guojia_resolves_rescue_before_yiji_and_skips_yiji_after_death(self) -> None:
        saved = make_engine(hero_id="guojia")
        saved._player("P1").hp = 1
        peach = put_hand(saved, "P1", "tao")
        order = []
        def saved_route(request):
            order.append(request.kind)
            return f"peach:{peach}" if request.kind == "rescue" else "keep"

        run_generator(saved, saved._damage("AI1", "P1", 1, None, damage_kind="测试"),
                      saved_route)
        self.assertTrue(saved._player("P1").alive)
        self.assertEqual(saved._player("P1").hp, 1)
        self.assertLess(order.index("rescue"), order.index("yiji_give"))
        self.assertEqual(saved.state.cards[peach].zone_id, "discard_pile")
        assert_card_zone_invariant(saved.state)

        dead = make_engine(hero_id="guojia")
        dead._player("P1").hp = 1
        for player in dead.state.players:
            for card_id in tuple(dead._zone(player.hand_zone_id).card_ids):
                if dead._definition(card_id).kind_id == "tao":
                    dead._discard_card(card_id)
        order = []
        run_generator(dead, dead._damage("AI1", "P1", 1, None, damage_kind="测试"),
                      lambda request: (order.append(request.kind) or "pass"))
        self.assertFalse(dead._player("P1").alive)
        self.assertNotIn("yiji_give", order)
        assert_card_zone_invariant(dead.state)

    def test_zhenji_luosheng_repeats_black_then_stops_on_red(self) -> None:
        engine = make_engine(hero_id="zhenji")
        draw = engine._zone("draw_pile").card_ids
        black = next(card_id for card_id in draw if engine._color(card_id) == "black")
        red = next(card_id for card_id in draw if engine._color(card_id) == "red")
        draw.remove(black)
        draw.remove(red)
        draw[:0] = [black, red]
        run_generator(engine, engine._preparation_skills(engine._player("P1")),
                      lambda request: "yes" if request.kind == "luoshen" else "pass")
        self.assertEqual(engine.state.cards[black].zone_id, "P1.hand")
        self.assertEqual(engine.state.cards[red].zone_id, "discard_pile")

    def test_zhenji_can_decline_luosheng_without_revealing_or_moving_a_judgment(self) -> None:
        engine = make_engine(hero_id="zhenji")
        before = tuple(engine._zone("draw_pile").card_ids)
        requests = []
        run_generator(engine, engine._preparation_skills(engine._player("P1")),
                      lambda request: (requests.append(request.kind) or "pass"))
        self.assertEqual(requests, ["luoshen"])
        self.assertEqual(tuple(engine._zone("draw_pile").card_ids), before)
        self.assertFalse(any("洛神最终判定" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_luoshen_uses_c04_when_no_judgment_card_can_be_drawn(self) -> None:
        engine = make_engine(hero_id="zhenji")
        for card_id in tuple(engine._zone("draw_pile").card_ids):
            engine._move(card_id, "P1.hand", owner_id="P1", controller_id="P1",
                         visibility=Visibility.OWNER_ONLY)
        for card_id in tuple(engine._zone("discard_pile").card_ids):
            engine._move(card_id, "P1.hand", owner_id="P1", controller_id="P1",
                         visibility=Visibility.OWNER_ONLY)
        self.assertEqual(engine._zone("draw_pile").card_ids, [])
        self.assertEqual(engine._zone("discard_pile").card_ids, [])

        run_generator(engine, engine._preparation_skills(engine._player("P1")),
                      lambda request: "yes" if request.kind == "luoshen" else "pass")

        self.assertEqual(engine.state.result, "draw")
        self.assertEqual(engine.state.end_reason, "C-04_insufficient_cards")
        self.assertEqual(engine._zone("resolving").card_ids, [])
        self.assertFalse(any("洛神最终判定" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_guanxing_allows_user_order_for_both_top_and_bottom(self) -> None:
        engine = make_engine(hero_id="zhugeliang")
        original = tuple(engine._zone("draw_pile").card_ids[:3])
        chosen_top = original[1]
        chosen_bottom = (original[0], original[2])
        reveal_counts = []

        def order(request):
            if request.kind == "guanxing":
                return "yes"
            if request.kind == "guanxing_order":
                reveal_counts.append(len(request.options) - 1)
                return f"top:{chosen_top}" if chosen_top in [option.value for option in request.options] else "done"
            if request.kind == "guanxing_bottom_order":
                desired = next(item for item in chosen_bottom
                               if any(option.value == item for option in request.options))
                return f"bottom:{desired}"
            return "pass"

        run_generator(engine, engine._preparation_skills(engine._player("P1")), order)
        self.assertEqual(engine._zone("draw_pile").card_ids[0], chosen_top)
        self.assertEqual(tuple(engine._zone("draw_pile").card_ids[-2:]), chosen_bottom)
        self.assertEqual(reveal_counts, [3, 2])
        assert_card_zone_invariant(engine.state)

    def test_guanxing_caps_the_reveal_at_five_in_the_five_player_mode(self) -> None:
        engine = make_engine("five_player_identity", hero_id="zhugeliang",
                             identity=Identity.LORD)
        order_option_counts = []

        def order(request):
            if request.kind == "guanxing":
                return "yes"
            if request.kind == "guanxing_order":
                order_option_counts.append(len(request.options))
                return "done"
            if request.kind == "guanxing_bottom_order":
                return request.options[0].choice_id
            return "pass"

        run_generator(engine, engine._preparation_skills(engine._player("P1")), order)
        self.assertEqual(order_option_counts, [6])  # five cards and the “done” option
        assert_card_zone_invariant(engine.state)

    def test_longdan_and_qingguo_are_only_hand_based_flash_responses(self) -> None:
        engine = make_engine(hero_id="zhaoyun")
        slash = put_hand(engine, "P1", "sha")
        run_generator(engine, engine._ask_flash("P1", "AI1", None),
                      lambda request: next(option.choice_id for option in request.options
                                           if option.choice_id == f"longdan:{slash}"))
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        set_hero(engine, "P1", "zhenji")
        black = put_hand(engine, "P1", "sha", suit="spades")
        run_generator(engine, engine._ask_flash("P1", "AI1", None),
                      lambda request: next(option.choice_id for option in request.options
                                           if option.choice_id == f"qingguo:{black}"))
        self.assertEqual(engine.state.cards[black].zone_id, "discard_pile")
        black_equipment = place(engine, "frost_sword", "P1.equipment", owner_id="P1",
                                controller_id="P1", visibility=Visibility.PUBLIC,
                                suit="spades")
        black_hand = put_hand(engine, "P1", "sha", suit="spades")
        qingguo_options = []
        run_generator(engine, engine._ask_flash("P1", "AI1", None),
                      lambda request: (qingguo_options.extend(
                          option.choice_id for option in request.options),
                          f"qingguo:{black_hand}")[1])
        self.assertNotIn(f"qingguo:{black_equipment}", qingguo_options)

        set_hero(engine, "P1", "zhaoyun")
        longdan_options = []
        run_generator(engine, engine._ask_flash("P1", "AI1", None),
                      lambda request: (longdan_options.extend(
                          option.choice_id for option in request.options), "pass")[1])
        self.assertNotIn(f"longdan:{black_equipment}", longdan_options)
        flash_as_kill = put_hand(engine, "P1", "shan")
        run_generator(engine, engine._ask_kill_response("P1", "决斗", "AI1"),
                      lambda request: f"longdan:{flash_as_kill}")
        self.assertEqual(engine.state.cards[flash_as_kill].zone_id, "resolving")
        engine._discard_response_materials(flash_as_kill)
        assert_card_zone_invariant(engine.state)

    def test_tieji_red_judgment_prevents_flash_and_qinggang_ignores_renwang(self) -> None:
        engine = make_engine(hero_id="machao")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        flash = put_hand(engine, "AI1", "shan")
        red = next(card_id for card_id in engine._zone("draw_pile").card_ids
                   if engine._color(card_id) == "red")
        draw = engine._zone("draw_pile").card_ids
        draw.remove(red)
        draw.insert(0, red)
        slash = put_hand(engine, "P1", "sha", suit="spades")
        before = engine._player("AI1").hp
        response_kinds = []
        engine.ai = RouteAI(lambda _view, request:
                            (response_kinds.append(request.kind) or None))
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: "yes" if request.kind == "tieji" else "pass")
        self.assertEqual(engine._player("AI1").hp, before - 1)
        self.assertEqual(engine.state.cards[flash].zone_id, "AI1.hand")
        self.assertNotIn("flash", response_kinds)

        shielded = make_engine(hero_id="machao")
        put_equipment(shielded, "AI1", "renwang_shield")
        black_slash = put_hand(shielded, "P1", "sha", suit="spades")
        hp = shielded._player("AI1").hp
        submit(shielded, action(shielded, kind_id="sha", target_id="AI1", card_id=black_slash),
               lambda request: "yes" if request.kind == "tieji" else "pass")
        self.assertEqual(shielded._player("AI1").hp, hp)
        self.assertEqual(shielded.state.cards[black_slash].zone_id, "discard_pile")

    def test_tieji_judgment_belongs_to_machao_not_its_target(self) -> None:
        engine = make_engine(hero_id="machao")
        set_hero(engine, "AI1", "guojia")
        red = next(card_id for card_id in engine._zone("draw_pile").card_ids
                   if engine._color(card_id) == "red")
        draw = engine._zone("draw_pile").card_ids
        draw.remove(red)
        draw.insert(0, red)
        slash = put_hand(engine, "P1", "sha")
        requests = []
        engine.ai = RouteAI(lambda _view, request:
                            (requests.append(request.kind) or
                             "yes" if request.kind == "tiandu" else None))

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: "yes" if request.kind == "tieji" else "pass")

        self.assertNotIn("tiandu", requests)
        self.assertEqual(engine.state.cards[red].zone_id, "discard_pile")
        self.assertEqual(engine._player("AI1").hp, engine._player("AI1").max_hp - 1)

    def test_zhangba_mixed_suit_kill_is_colorless_and_costs_both_hand_cards(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "serpent_spear")
        red = put_hand(engine, "P1", "sha", suit="hearts")
        black = put_hand(engine, "P1", "sha", suit="spades")
        intent = next(item.intent for item in engine.available_actions("P1")
                      if item.intent.skill_id == "serpent_spear"
                      and set(item.intent.cost_card_ids) == {red, black}
                      and item.intent.target_ids == ("AI1",))
        before = engine._player("AI1").hp
        engine.submit_action(intent)
        self.assertEqual(engine._player("AI1").hp, before - 1)
        self.assertEqual(engine.state.cards[red].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[black].zone_id, "discard_pile")

    def test_xiaoji_triggers_for_lost_equipment_but_not_hand_equipment_discard(self) -> None:
        engine = make_engine(hero_id="sunshangxiang")
        equipment = put_equipment(engine, "P1", "axe")
        deck = engine._zone("draw_pile").card_ids
        expected = set(deck[:2])
        run_generator(engine, engine._discard_with_loss_triggers(equipment),
                      lambda request: "yes" if request.kind == "xiaoji" else "pass")
        self.assertEqual(set(engine._zone("P1.hand").card_ids) & expected, expected)
        hand_equipment = put_hand(engine, "P1", "bagua_formation")
        run_generator(engine, engine._discard_with_loss_triggers(hand_equipment),
                      lambda request: "yes" if request.kind == "xiaoji" else "pass")
        self.assertEqual(set(engine._zone("P1.hand").card_ids) & expected, expected)

        declined = make_engine(hero_id="sunshangxiang")
        lost_equipment = put_equipment(declined, "P1", "axe")
        top_two = tuple(declined._zone("draw_pile").card_ids[:2])
        hand_before = tuple(declined._zone("P1.hand").card_ids)
        run_generator(declined, declined._discard_with_loss_triggers(lost_equipment),
                      lambda request: "pass" if request.kind == "xiaoji" else "pass")
        self.assertEqual(tuple(declined._zone("P1.hand").card_ids), hand_before)
        self.assertEqual(tuple(declined._zone("draw_pile").card_ids[:2]), top_two)
        self.assertEqual(declined.state.cards[lost_equipment].zone_id, "discard_pile")
        assert_card_zone_invariant(declined.state)

    def test_xiaoji_triggers_when_equipment_is_replaced(self) -> None:
        engine = make_engine(hero_id="sunshangxiang")
        old_equipment = put_equipment(engine, "P1", "axe")
        new_equipment = put_hand(engine, "P1", "halberd")
        expected = set(engine._zone("draw_pile").card_ids[:2])
        intent = ActionIntent("P1", card_id=new_equipment)
        self.assertTrue(engine.is_legal_intent(intent))
        run_generator(engine, engine._resolve_intent(intent),
                      lambda request: "yes" if request.kind == "xiaoji" else "pass")
        self.assertEqual(engine.state.cards[old_equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[new_equipment].zone_id, "P1.equipment")
        self.assertEqual(set(engine._zone("P1.hand").card_ids) & expected, expected)

    def test_zhangliao_empty_hand_cannot_be_targeted_before_kill_lock(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "zhugeliang")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        sha = put_hand(engine, "P1", "sha")
        self.assertNotIn("AI1", engine.kill_targets("P1"))
        self.assertNotIn("AI1", engine.legal_targets_for_card("P1", sha))

    def test_kongcheng_does_not_cancel_a_target_after_it_was_locked(self) -> None:
        engine = make_engine(hero_id="daqiao")
        set_hero(engine, "AI1", "zhugeliang")
        only_card = next(card_id for card_id in tuple(engine._zone("AI1.hand").card_ids))
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            if card_id != only_card:
                engine._discard_card(card_id)
        put_equipment(engine, "P1", "double_swords")
        slash = put_hand(engine, "P1", "sha")
        engine.ai = RouteAI(lambda _view, request:
                            "yes" if request.kind == "double_swords" else
                            f"discard:{only_card}" if request.kind == "double_swords_target" else None)
        before = engine._player("AI1").hp
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: "yes" if request.kind == "double_swords" else
               f"discard:{only_card}" if request.kind == "double_swords_target" else
               next((item.choice_id for item in request.options if item.category == "pass"),
                    request.options[0].choice_id))
        self.assertEqual(engine.state.cards[only_card].zone_id, "discard_pile")
        self.assertEqual(engine._player("AI1").hp, before - 1)

    def test_lianying_triggers_when_the_last_nullification_is_spent(self) -> None:
        engine = make_engine(hero_id="luxun")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        negate = put_hand(engine, "P1", "negate")
        before_deck = tuple(engine._zone("draw_pile").card_ids)
        choices_seen = []

        def route(request):
            choices_seen.append(request.kind)
            if request.kind == "nullification":
                return f"negate:{negate}"
            if request.kind == "lianying":
                return "yes"
            return "pass"

        run_generator(engine, engine._nullification_window("AI1", negate), route)
        self.assertIn("lianying", choices_seen)
        self.assertEqual(engine.state.cards[negate].zone_id, "discard_pile")
        self.assertEqual(len(engine._zone("P1.hand").card_ids), 1)
        self.assertEqual(engine._zone("P1.hand").card_ids[0], before_deck[0])

    def test_keji_skips_only_when_no_kill_was_used_or_played(self) -> None:
        engine = make_engine(hero_id="lvmeng")
        before = tuple(engine._zone("P1.hand").card_ids)
        run_generator(engine, engine._discard_phase(engine._player("P1")),
                      lambda request: "yes" if request.kind == "keji" else "pass")
        self.assertEqual(tuple(engine._zone("P1.hand").card_ids), before)
        engine._played_kill_this_turn.add("P1")
        seen = []
        run_generator(engine, engine._discard_phase(engine._player("P1")),
                      lambda request: (seen.append(request.kind) or
                                       next(option.choice_id for option in request.options
                                            if option.category == "discard")))
        self.assertNotIn("keji", seen)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), engine._player("P1").hp)

    def test_jizhi_draws_before_the_immediate_trick_window(self) -> None:
        engine = make_engine(hero_id="huangyueying")
        draw_two = put_hand(engine, "P1", "draw_two")
        put_hand(engine, "P1", "negate")
        before = len(engine._zone("P1.hand").card_ids)
        order = []

        def route(request):
            order.append(request.kind)
            if request.kind == "jizhi":
                return "yes"
            return "pass" if request.kind == "nullification" else request.options[0].choice_id

        submit(engine, action(engine, kind_id="draw_two", card_id=draw_two), route)
        self.assertLess(order.index("jizhi"), order.index("nullification"))
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 2)

    def test_jizhi_does_not_trigger_for_a_delayed_trick(self) -> None:
        engine = make_engine(hero_id="huangyueying")
        lightning = put_hand(engine, "P1", "lightning")
        seen = []
        run_generator(engine, engine._resolve_intent(ActionIntent("P1", card_id=lightning)),
                      lambda request: (seen.append(request.kind) or "pass"))
        self.assertNotIn("jizhi", seen)
        self.assertEqual(engine.state.cards[lightning].zone_id, "P1.judgment")
        assert_card_zone_invariant(engine.state)

    def test_qicai_waives_steal_distance_without_changing_other_target_rules(self) -> None:
        engine = make_engine("five_player_identity", hero_id="huangyueying",
                             identity=Identity.LORD)
        set_hero(engine, "P1", "caocao")
        steal = put_hand(engine, "P1", "steal")
        put_hand(engine, "AI3", "tao")
        self.assertEqual(engine.distance("P1", "AI3"), 2)
        self.assertNotIn("AI3", engine.legal_targets_for_card("P1", steal))
        set_hero(engine, "P1", "huangyueying")
        self.assertIn("AI3", engine.legal_targets_for_card("P1", steal))
        set_hero(engine, "AI3", "luxun")
        self.assertNotIn("AI3", engine.legal_targets_for_card("P1", steal))

    def test_guose_places_a_diamond_card_as_indulgence(self) -> None:
        engine = make_engine(hero_id="daqiao")
        set_hero(engine, "AI1", "guanyu")
        diamond = put_hand(engine, "P1", "sha", suit="diamonds")
        intent = ActionIntent("P1", skill_id="guose", cost_card_ids=(diamond,),
                              target_ids=("AI1",))
        self.assertTrue(engine.is_legal_intent(intent))
        submit(engine, intent, lambda request: "pass")
        self.assertEqual(engine.state.cards[diamond].zone_id, "AI1.judgment")

    def test_kurou_resolves_rescue_before_drawing_and_does_not_draw_after_death(self) -> None:
        engine = make_engine(hero_id="huanggai")
        engine._player("P1").hp = 1
        peach = put_hand(engine, "P1", "tao")
        before = len(engine._zone("P1.hand").card_ids)
        submit(engine, ActionIntent("P1", skill_id="kurou"),
               lambda request: f"peach:{peach}"
               if request.kind == "rescue" else "pass")
        self.assertTrue(engine._player("P1").alive)
        self.assertEqual(engine._player("P1").hp, 1)
        self.assertEqual(engine.state.cards[peach].zone_id, "discard_pile")
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 1)

        repeated = make_engine(hero_id="huanggai")
        hand_before = len(repeated._zone("P1.hand").card_ids)
        submit(repeated, ActionIntent("P1", skill_id="kurou"))
        submit(repeated, ActionIntent("P1", skill_id="kurou"))
        self.assertEqual(repeated._player("P1").hp, repeated._player("P1").max_hp - 2)
        self.assertEqual(len(repeated._zone("P1.hand").card_ids), hand_before + 4)
        assert_card_zone_invariant(repeated.state)

        doomed = make_engine(hero_id="huanggai")
        doomed._player("P1").hp = 1
        for player in doomed.state.players:
            for card_id in tuple(doomed._zone(player.hand_zone_id).card_ids):
                if doomed._definition(card_id).kind_id == "tao":
                    doomed._discard_card(card_id)
        submit(doomed, ActionIntent("P1", skill_id="kurou"))
        self.assertFalse(doomed._player("P1").alive)
        self.assertEqual(len(doomed._zone("P1.hand").card_ids), 0)
        self.assertEqual(doomed.state.result, "ai_side_win")

    def test_huatuo_jijiu_uses_red_equipment_out_of_turn_but_not_on_own_turn(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        set_hero(engine, "AI1", "huatuo")
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                if engine._definition(card_id).kind_id == "tao":
                    engine._discard_card(card_id)
        red_equipment = place(engine, "crossbow", "AI1.equipment", owner_id="AI1",
                              controller_id="AI1", visibility=Visibility.PUBLIC,
                              suit="diamonds")
        engine._player("AI2").hp = 0
        engine.ai = RouteAI(lambda _view, request:
                            next(option.choice_id for option in request.options
                                 if option.choice_id.startswith("jijiu:"))
                            if request.kind == "rescue" and request.player_id == "AI1" else None)
        result = complete_without_prompts(engine._rescue("AI2"))
        self.assertTrue(result)
        self.assertEqual(engine._player("AI2").hp, 1)
        self.assertEqual(engine.state.cards[red_equipment].zone_id, "discard_pile")

        own_turn = make_engine(hero_id="huatuo")
        for player in own_turn.state.players:
            for card_id in tuple(own_turn._zone(player.hand_zone_id).card_ids):
                if own_turn._definition(card_id).kind_id == "tao":
                    own_turn._discard_card(card_id)
        red = put_hand(own_turn, "P1", "sha", suit="hearts")
        own_turn._player("P1").hp = 0
        result = complete_without_prompts(own_turn._rescue("P1"))
        self.assertFalse(result)
        self.assertEqual(own_turn._player("P1").hp, 0)
        self.assertEqual(own_turn.state.cards[red].zone_id, "P1.hand")

    def test_qingnang_is_once_per_play_phase_and_only_spends_hand_card(self) -> None:
        engine = make_engine(hero_id="huatuo")
        engine._player("AI1").hp -= 1
        cost = engine._zone("P1.hand").card_ids[0]
        intent = ActionIntent("P1", skill_id="qingnang", choice="choose",
                              target_ids=("AI1",))
        before = engine._player("AI1").hp
        submit(engine, intent,
               lambda request: f"discard:{cost}" if request.kind == "qingnang_cost" else "pass")
        self.assertEqual(engine._player("AI1").hp, before + 1)
        self.assertEqual(engine.state.cards[cost].zone_id, "discard_pile")
        self.assertFalse(any(item.intent.skill_id == "qingnang"
                             for item in engine.available_actions("P1")))

        full_health = make_engine(hero_id="huatuo")
        self.assertFalse(any(item.intent.skill_id == "qingnang"
                             for item in full_health.available_actions("P1")))
        full_health._player("AI1").hp -= 1
        armor = put_equipment(full_health, "P1", "bagua_formation")
        equipment_only = ActionIntent("P1", skill_id="qingnang", choice="choose",
                                      cost_card_ids=(armor,), target_ids=("AI1",))
        self.assertFalse(full_health.is_legal_intent(equipment_only))
        self.assertEqual(full_health.state.cards[armor].zone_id, "P1.equipment")

    def test_wushuang_requires_two_flashes_and_consumes_the_single_flash(self) -> None:
        engine = make_engine(hero_id="lvbu")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        flash = put_hand(engine, "AI1", "shan")
        slash = put_hand(engine, "P1", "sha")
        engine.ai = RouteAI(lambda _view, request:
                            next(option.choice_id for option in request.options
                                 if option.category == "flash")
                            if request.kind == "flash" else None)
        before = engine._player("AI1").hp
        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash))
        self.assertEqual(engine._player("AI1").hp, before - 1)
        self.assertEqual(engine.state.cards[flash].zone_id, "discard_pile")

    def test_wushuang_in_duel_requires_two_kills_and_stops_after_the_first_missing_response(self) -> None:
        engine = make_engine(hero_id="lvbu")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        first_kill = put_hand(engine, "AI1", "sha")
        engine.ai = RouteAI(lambda _view, request:
                            next((option.choice_id for option in request.options
                                  if option.category == "kill"), None)
                            if request.kind == "duel_kill" else None)
        hp = engine._player("AI1").hp
        result = complete_without_prompts(engine._resolve_duel("P1", "AI1", None))
        self.assertIsNone(result)
        self.assertEqual(engine._player("AI1").hp, hp - 1)
        self.assertEqual(engine.state.cards[first_kill].zone_id, "discard_pile")
        self.assertEqual(sum("为决斗打出" in log.text for log in engine.logs), 1)
        assert_card_zone_invariant(engine.state)

    def test_lord_kill_rewards_and_terminal_check_order_are_exact(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        roles = {"P1": "lord", "AI1": "loyalist", "AI2": "rebel",
                 "AI3": "rebel", "AI4": "turncoat"}
        for player_id, identity in roles.items():
            engine._player(player_id).identity = identity
        engine.state.random_stream
        before = len(engine._zone("P1.hand").card_ids)
        engine._kill_player("AI4", "P1")
        engine._kill_player("AI2", "P1")
        after_reward = len(engine._zone("P1.hand").card_ids)
        self.assertEqual(after_reward, before + 3)
        engine._kill_player("AI3", "P1")
        self.assertEqual(engine.state.result, "lord_side_win")
        self.assertEqual(len(engine._zone("P1.hand").card_ids), after_reward)

    def test_lord_penalty_keeps_dead_loyalists_judgment_cards_out_of_cleanup(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        for player_id, identity in {"P1": "lord", "AI1": "loyalist", "AI2": "rebel",
                                    "AI3": "rebel", "AI4": "turncoat"}.items():
            engine._player(player_id).identity = identity
        hand_card = put_hand(engine, "P1", "sha")
        equipment = put_equipment(engine, "P1", "axe")
        judgment = place(engine, "lightning", engine._player("P1").judgment_zone_id,
                         owner_id="P1", controller_id="P1", visibility=Visibility.PUBLIC)
        engine._kill_player("AI1", "P1")
        self.assertEqual(engine.state.cards[hand_card].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[judgment].zone_id, "P1.judgment")

    def test_terminal_aoe_stops_before_the_next_target_and_discards_its_source_card(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        roles = {"P1": "lord", "AI1": "rebel", "AI2": "rebel",
                 "AI3": "loyalist", "AI4": "turncoat"}
        for player_id, identity in roles.items():
            engine._player(player_id).identity = identity
        for player_id in ("AI1", "AI2", "AI3", "AI4"):
            for card_id in tuple(engine._zone(f"{player_id}.hand").card_ids):
                engine._discard_card(card_id)
        dead_equipment = put_equipment(engine, "AI1", "axe")
        dead_judgment = place(engine, "lightning", engine._player("AI1").judgment_zone_id,
                              owner_id="AI1", controller_id="AI1",
                              visibility=Visibility.PUBLIC)
        engine._player("AI1").hp = 1
        engine._player("AI2").hp = 1
        engine._kill_player("AI4", None)
        source = put_hand(engine, "P1", "barbarians")
        ai3_hp = engine._player("AI3").hp
        submit(engine, action(engine, kind_id="barbarians", card_id=source))
        self.assertEqual(engine.state.result, "lord_side_win")
        self.assertEqual(engine._player("AI3").hp, ai3_hp)
        self.assertEqual(engine.state.cards[source].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[dead_equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[dead_judgment].zone_id, "discard_pile")
        self.assertEqual(engine._zone("AI1.hand").card_ids, [])
        self.assertEqual(engine._zone("AI1.equipment").card_ids, [])
        self.assertEqual(engine._zone("AI1.judgment").card_ids, [])
        self.assertEqual(engine._zone("resolving").card_ids, [])
        self.assertEqual(engine.state.event_stack, [])
        assert_card_zone_invariant(engine.state)

    def test_terminal_fanjian_death_returns_isolated_card_and_cleans_dead_zones(self) -> None:
        engine = make_engine("five_player_identity", hero_id="zhouyu",
                             identity=Identity.LORD)
        for player_id, identity in {"P1": "lord", "AI1": "rebel", "AI2": "rebel",
                                    "AI3": "loyalist", "AI4": "turncoat"}.items():
            engine._player(player_id).identity = identity
        engine._kill_player("AI4", None)
        engine._kill_player("AI2", None)
        target = engine._player("AI1")
        target.hp = 1
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                if engine._definition(card_id).name == "桃":
                    engine._discard_card(card_id)
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        exposed = put_hand(engine, "P1", "sha", suit="hearts")
        dead_equipment = put_equipment(engine, "AI1", "axe")
        dead_judgment = place(engine, "lightning", target.judgment_zone_id,
                              owner_id="AI1", controller_id="AI1",
                              visibility=Visibility.PUBLIC)
        dead_hand = put_hand(engine, "AI1", "shan")

        run_generator(engine, engine._resolve_fanjian("P1", "AI1"),
                      lambda request: "spades" if request.kind == "fan_jian_suit" else "pass")

        self.assertEqual(engine.state.result, "lord_side_win")
        self.assertEqual(engine.state.cards[exposed].zone_id, "P1.hand")
        self.assertNotIn("fanjian_pending", engine.state.cards[exposed].temporary_marks)
        self.assertEqual(engine.state.cards[dead_hand].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[dead_equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[dead_judgment].zone_id, "discard_pile")
        self.assertEqual(engine._zone("resolving").card_ids, [])
        assert_card_zone_invariant(engine.state)

    def test_lightning_no_source_death_cleans_all_zones_without_reward(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        for player_id, identity in {"P1": "lord", "AI1": "rebel", "AI2": "rebel",
                                    "AI3": "loyalist", "AI4": "turncoat"}.items():
            engine._player(player_id).identity = identity
        target = engine._player("AI1")
        target.hp = 3
        engine.state.current_player_id = "AI1"
        engine.state.phase = GamePhase.JUDGMENT
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                if (engine._definition(card_id).name in {"无懈可击", "桃"}
                        or player.player_id == "AI1"):
                    engine._discard_card(card_id)
        dead_hand = put_hand(engine, "AI1", "shan")
        dead_equipment = put_equipment(engine, "AI1", "axe")
        lightning = place(engine, "lightning", target.judgment_zone_id,
                          owner_id="AI1", controller_id="AI1",
                          visibility=Visibility.PUBLIC)
        judgment = next(card_id for card_id in engine._zone("draw_pile").card_ids
                        if engine._definition(card_id).suit.value == "spades"
                        and 2 <= int(engine._definition(card_id).rank) <= 9)
        engine._zone("draw_pile").card_ids.remove(judgment)
        engine._zone("draw_pile").card_ids.insert(0, judgment)
        lord_hand_before = tuple(engine._zone("P1.hand").card_ids)

        run_generator(engine, engine._resolve_judgment_zone(target))

        self.assertFalse(target.alive)
        self.assertIsNone(engine.state.result)
        self.assertEqual(tuple(engine._zone("P1.hand").card_ids), lord_hand_before)
        self.assertEqual(engine.state.cards[dead_hand].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[dead_equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[lightning].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[judgment].zone_id, "discard_pile")
        self.assertEqual(target.hand_zone_id, "AI1.hand")
        self.assertEqual(engine._zone("AI1.hand").card_ids, [])
        self.assertEqual(engine._zone("AI1.equipment").card_ids, [])
        self.assertEqual(engine._zone("AI1.judgment").card_ids, [])
        self.assertFalse(any("击杀反贼" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_lijian_duel_has_no_nullification_and_biyue_follows_discard_phase(self) -> None:
        engine = make_engine(hero_id="diaochan")
        cost = put_hand(engine, "P1", "tao")
        set_hero(engine, "AI1", "guanyu")
        set_hero(engine, "AI2", "zhangfei")
        intent = ActionIntent("P1", skill_id="lijian", cost_card_ids=(cost,),
                              target_ids=("AI1", "AI2"))
        self.assertTrue(engine.is_legal_intent(intent))
        run_generator(engine, engine._resolve_intent(intent),
                      lambda request: request.options[-1].choice_id
                      if request.kind == "lijian_initiator" else "pass")
        self.assertNotIn("nullification", [log.text for log in engine.logs])
        engine.state.phase = GamePhase.END
        hand_before = len(engine._zone("P1.hand").card_ids)
        run_generator(engine, engine._resolve_end_skills(engine._player("P1")),
                      lambda request: "yes" if request.kind == "biyue" else "pass")
        self.assertEqual(len(engine._zone("P1.hand").card_ids), hand_before + 1)

        declined = make_engine(hero_id="diaochan")
        before_declined = tuple(declined._zone("P1.hand").card_ids)
        run_generator(declined, declined._resolve_end_skills(declined._player("P1")),
                      lambda request: "pass")
        self.assertEqual(tuple(declined._zone("P1.hand").card_ids), before_declined)
        self.assertFalse(any("发动闭月" in log.text for log in declined.logs))

    def test_jiuyuan_extra_healing_requires_a_wu_rescuer(self) -> None:
        engine = make_engine("five_player_identity", hero_id="sunquan",
                             identity=Identity.LORD)
        engine._player("P1").identity = Identity.LORD.value
        engine._player("AI1").identity = Identity.LOYALIST.value
        set_hero(engine, "AI1", "caocao")
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                if engine._definition(card_id).kind_id == "tao":
                    engine._discard_card(card_id)
        peach = put_hand(engine, "AI1", "tao")
        engine._player("P1").hp = 0
        engine.ai = RouteAI(lambda _view, request:
                            f"peach:{peach}" if request.kind == "rescue" else None)

        result = complete_without_prompts(engine._rescue("P1"))

        self.assertTrue(result)
        self.assertEqual(engine._player("P1").hp, 1)
        self.assertEqual(engine.state.cards[peach].zone_id, "discard_pile")
        self.assertFalse(any("回复2点体力" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_lijian_accepts_equipment_cost_and_rejects_same_gender_targets(self) -> None:
        engine = make_engine(hero_id="diaochan")
        set_hero(engine, "AI1", "guanyu")
        set_hero(engine, "AI2", "zhangfei")
        equipment = put_equipment(engine, "P1", "axe")
        intent = ActionIntent("P1", skill_id="lijian", cost_card_ids=(equipment,),
                              target_ids=("AI1", "AI2"))
        self.assertTrue(engine.is_legal_intent(intent))
        submit(engine, intent,
               lambda request: ("initiator:AI1" if request.kind == "lijian_initiator"
                                else "pass"))
        self.assertEqual(engine.state.cards[equipment].zone_id, "discard_pile")
        self.assertEqual(engine._player("AI2").hp, engine._player("AI2").max_hp - 1)

        invalid = make_engine(hero_id="diaochan")
        set_hero(invalid, "AI1", "zhenji")
        set_hero(invalid, "AI2", "daqiao")
        cost = put_hand(invalid, "P1", "shan")
        same_gender = ActionIntent("P1", skill_id="lijian", cost_card_ids=(cost,),
                                   target_ids=("AI1", "AI2"))
        self.assertFalse(invalid.is_legal_intent(same_gender))
        assert_card_zone_invariant(engine.state)
        assert_card_zone_invariant(invalid.state)

    def test_jieyin_can_be_used_at_full_health_but_needs_an_injured_male_target(self) -> None:
        engine = make_engine(hero_id="sunshangxiang")
        set_hero(engine, "AI1", "guanyu")
        engine._player("AI1").hp -= 1
        cost = tuple(engine._zone("P1.hand").card_ids[:2])
        before_player = engine._player("P1").hp
        before_target = engine._player("AI1").hp
        intent = ActionIntent("P1", skill_id="jieyin", choice="choose",
                              target_ids=("AI1",))
        self.assertTrue(engine.is_legal_intent(intent))
        submit(engine, intent,
               lambda request: tuple(f"discard:{item}" for item in cost)
               if request.kind == "jieyin_cost" else "pass")
        self.assertEqual(engine._player("P1").hp, before_player)
        self.assertEqual(engine._player("AI1").hp, before_target + 1)
        self.assertFalse(any(item.intent.skill_id == "jieyin"
                             for item in engine.available_actions("P1")))

    def test_liuli_rechecks_range_after_paying_distance_reducing_mount(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        set_hero(engine, "AI1", "daqiao")
        minus_one = put_equipment(engine, "AI1", "chitu")
        target_options = []

        def route(_view, request):
            if request.kind == "liuli":
                return f"discard:{minus_one}"
            if request.kind == "liuli_target":
                target_options.extend(option.choice_id for option in request.options)
                return "target:AI2"
            return None

        engine.ai = RouteAI(route)
        before = {player_id: engine._player(player_id).hp
                  for player_id in ("AI1", "AI2", "AI3", "AI4")}
        run_generator(engine, engine._resolve_kill("P1", "AI1", None, active_play=True))
        self.assertTrue(target_options)
        self.assertNotIn("target:AI3", target_options)
        self.assertNotIn("target:AI4", target_options)
        self.assertEqual(engine._player("AI2").hp, before["AI2"] - 1)
        self.assertEqual(engine._player("AI1").hp, before["AI1"])

    def test_failed_jijiang_does_not_consume_a_kill_use(self) -> None:
        engine = make_engine("five_player_identity", hero_id="liubei",
                             identity=Identity.LORD)
        set_hero(engine, "AI1", "guanyu")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        provider_kill = put_hand(engine, "AI1", "sha", suit="spades")
        target_id = "AI1"
        intent = ActionIntent("P1", skill_id="jijiang", target_ids=(target_id,))
        self.assertTrue(engine.is_legal_intent(intent))
        submit(engine, intent)
        self.assertEqual(engine._kill_uses.get("P1", 0), 0)
        self.assertEqual(engine.state.cards[provider_kill].zone_id, "AI1.hand")


class Stage2RemainingMatrixTests(unittest.TestCase):
    def test_hujia_all_eligible_providers_can_decline_without_consuming_flashes(self) -> None:
        engine = make_engine("five_player_identity", hero_id="caocao",
                             identity=Identity.LORD)
        engine._player("P1").identity = Identity.LORD.value
        set_hero(engine, "P1", "caocao")
        for player in engine.state.players:
            if player.player_id != "P1":
                set_hero(engine, player.player_id, "caocao")
        providers = engine._hujia_providers("P1")
        self.assertTrue(providers)
        flash_ids = []
        for provider in providers:
            for card_id in tuple(engine._zone(provider.hand_zone_id).card_ids):
                engine._discard_card(card_id)
            flash_ids.append(put_hand(engine, provider.player_id, "shan"))
        engine.ai = RouteAI(lambda _view, request:
                            "pass" if request.kind == "hujia" else None)

        result = complete_without_prompts(engine._resolve_hujia("P1"))

        self.assertFalse(result)
        self.assertTrue(all(engine.state.cards[card_id].zone_id.endswith(".hand")
                            for card_id in flash_ids))
        assert_card_zone_invariant(engine.state)

    def test_jianxiong_without_a_physical_damage_card_does_not_offer_trigger(self) -> None:
        engine = make_engine(hero_id="caocao")
        requests = []

        run_generator(engine, engine._damage("AI1", "P1", 1, None, damage_kind="技能"),
                      lambda request: (requests.append(request.kind) or "pass"))

        self.assertEqual(engine._player("P1").hp, engine._player("P1").max_hp - 1)
        self.assertNotIn("jianxiong", requests)
        assert_card_zone_invariant(engine.state)

    def test_jianxiong_can_decline_a_physical_damage_card(self) -> None:
        engine = make_engine(hero_id="caocao")
        damage_card = put_hand(engine, "AI1", "sha")
        engine._move(damage_card, "resolving", owner_id="AI1", controller_id="AI1",
                     visibility=Visibility.PUBLIC)
        before = engine._player("P1").hp
        requests = []

        run_generator(engine, engine._damage("AI1", "P1", 1, damage_card, damage_kind="杀"),
                      lambda request: (requests.append(request.kind) or "pass"))

        self.assertIn("jianxiong", requests)
        self.assertEqual(engine._player("P1").hp, before - 1)
        self.assertEqual(engine.state.cards[damage_card].zone_id, "resolving")
        engine._discard_card(damage_card)
        assert_card_zone_invariant(engine.state)

    def test_jianxiong_follows_rescue_and_does_not_trigger_after_death(self) -> None:
        rescued = make_engine(hero_id="caocao", human_player_ids=frozenset({"P1", "AI1"}))
        rescued._player("P1").hp = 1
        peach = put_hand(rescued, "P1", "tao")
        damage_card = put_hand(rescued, "AI1", "sha")
        rescued._move(damage_card, "resolving", owner_id="AI1", controller_id="AI1",
                      visibility=Visibility.PUBLIC)
        request_order = []

        def choose_rescue_or_jianxiong(request):
            request_order.append(request.kind)
            if request.kind == "rescue":
                return f"peach:{peach}"
            if request.kind == "jianxiong":
                return "take"
            return "pass"

        run_generator(rescued,
                      rescued._damage("AI1", "P1", 1, damage_card, damage_kind="杀"),
                      choose_rescue_or_jianxiong)

        self.assertLess(request_order.index("rescue"), request_order.index("jianxiong"))
        self.assertTrue(rescued._player("P1").alive)
        self.assertEqual(rescued._player("P1").hp, 1)
        self.assertEqual(rescued.state.cards[peach].zone_id, "discard_pile")
        self.assertEqual(rescued.state.cards[damage_card].zone_id, "P1.hand")

        dead = make_engine(hero_id="caocao")
        dead._player("P1").hp = 1
        for player in dead.state.players:
            for card_id in tuple(dead._zone(player.hand_zone_id).card_ids):
                if dead._definition(card_id).kind_id == "tao":
                    dead._discard_card(card_id)
        lethal_card = put_hand(dead, "AI1", "sha")
        dead._move(lethal_card, "resolving", owner_id="AI1", controller_id="AI1",
                   visibility=Visibility.PUBLIC)
        requests = []

        run_generator(dead,
                      dead._damage("AI1", "P1", 1, lethal_card, damage_kind="杀"),
                      lambda request: (requests.append(request.kind) or "pass"))

        self.assertFalse(dead._player("P1").alive)
        self.assertNotIn("jianxiong", requests)
        self.assertNotIn(lethal_card, dead._zone("P1.hand").card_ids)
        dead._discard_card(lethal_card)
        assert_card_zone_invariant(rescued.state)
        assert_card_zone_invariant(dead.state)

    def test_fankui_can_decline_and_has_no_choice_when_source_has_no_cards(self) -> None:
        declined = make_engine(hero_id="simayi")
        original_hand = tuple(declined._zone("AI1.hand").card_ids)
        original_equipment = tuple(declined._zone("AI1.equipment").card_ids)
        requests = []
        run_generator(declined, declined._damage("AI1", "P1", 1, None, damage_kind="测试"),
                      lambda request: (requests.append(request.kind) or "pass"))
        self.assertIn("fankui", requests)
        self.assertEqual(tuple(declined._zone("AI1.hand").card_ids), original_hand)
        self.assertEqual(tuple(declined._zone("AI1.equipment").card_ids), original_equipment)

        empty_source = make_engine(hero_id="simayi")
        for card_id in tuple(empty_source._zone("AI1.hand").card_ids):
            empty_source._discard_card(card_id)
        for card_id in tuple(empty_source._zone("AI1.equipment").card_ids):
            empty_source._discard_card(card_id)
        requests = []
        run_generator(empty_source,
                      empty_source._damage("AI1", "P1", 1, None, damage_kind="测试"),
                      lambda request: (requests.append(request.kind) or "pass"))
        self.assertNotIn("fankui", requests)
        assert_card_zone_invariant(declined.state)
        assert_card_zone_invariant(empty_source.state)

    def test_guicai_decline_keeps_final_judgment_card_and_does_not_replace(self) -> None:
        engine = make_engine(hero_id="simayi", human_player_ids=frozenset())
        original = engine._zone("draw_pile").card_ids[0]
        hand_before = tuple(engine._zone("P1.hand").card_ids)
        requests = []
        engine.ai = RouteAI(lambda _view, request:
                            (requests.append(request.kind) or "pass"))
        judged = complete_without_prompts(engine._judge("AI1", "测试"))

        self.assertEqual(requests, ["guicai"])
        self.assertEqual(judged, original)
        self.assertEqual(engine.state.cards[original].zone_id, "resolving")
        self.assertEqual(tuple(engine._zone("P1.hand").card_ids),
                         hand_before)
        engine._discard_card(original)
        assert_card_zone_invariant(engine.state)

    def test_luoyi_decline_keeps_normal_draw_and_duel_damage_is_attributed_to_actual_responder(self) -> None:
        engine = make_engine(hero_id="xuchu")
        before = len(engine._zone("P1.hand").card_ids)
        run_generator(engine, engine._start_turn(engine._player("P1")),
                      lambda request: "pass" if request.kind == "luoyi" else "pass")
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 2)
        self.assertNotIn("P1", engine._luoyi_bonus)

        active = make_engine(hero_id="xuchu")
        run_generator(active, active._start_turn(active._player("P1")),
                      lambda request: "yes" if request.kind == "luoyi" else "pass")
        for card_id in tuple(active._zone("P1.hand").card_ids):
            active._discard_card(card_id)
        for card_id in tuple(active._zone("AI1.hand").card_ids):
            if active._definition(card_id).name == "杀":
                active._discard_card(card_id)
        duel = put_hand(active, "P1", "duel")
        reply = put_hand(active, "AI1", "sha")
        active.ai = RouteAI(lambda _view, request:
                            f"kill:{reply}" if request.kind == "duel_kill"
                            and request.player_id == "AI1" else None)
        hp = active._player("P1").hp

        submit(active, action(active, kind_id="duel", target_id="AI1", card_id=duel),
               lambda request: "pass")

        self.assertEqual(active._player("P1").hp, hp - 1)
        self.assertEqual(active._player("AI1").hp, active._player("AI1").max_hp)
        self.assertEqual(active.state.cards[reply].zone_id, "discard_pile")
        self.assertEqual(active.state.cards[duel].zone_id, "discard_pile")
        assert_card_zone_invariant(active.state)

    def test_mashu_changes_only_the_users_outgoing_attack_distance(self) -> None:
        engine = make_engine("five_player_identity", hero_id="machao",
                             identity=Identity.LORD)
        self.assertEqual(engine.distance("P1", "AI2"), 1)
        self.assertEqual(engine.distance("AI2", "P1"), 2)
        set_hero(engine, "P1", "caocao")
        self.assertEqual(engine.distance("P1", "AI2"), 2)
        self.assertEqual(engine.distance("AI2", "P1"), 2)

    def test_yingzi_can_be_declined_without_changing_the_normal_draw(self) -> None:
        engine = make_engine(hero_id="zhouyu")
        before = len(engine._zone("P1.hand").card_ids)
        requests = []

        run_generator(engine, engine._start_turn(engine._player("P1")),
                      lambda request: (requests.append(request.kind) or
                                       "no" if request.kind == "yingzi" else "pass"))

        self.assertIn("yingzi", requests)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), before + 2)
        self.assertEqual(engine.state.phase, GamePhase.PLAY)
        assert_card_zone_invariant(engine.state)

    def test_yingzi_draw_shortage_is_checked_before_moving_any_card(self) -> None:
        engine = make_engine(hero_id="zhouyu")
        deck = engine._zone("draw_pile").card_ids
        retained = tuple(deck[:2])
        for card_id in tuple(engine.state.cards):
            if card_id not in retained:
                engine._move(card_id, "P1.hand", owner_id="P1", controller_id="P1",
                             visibility=Visibility.OWNER_ONLY)
        hand_before = tuple(engine._zone("P1.hand").card_ids)

        run_generator(engine, engine._start_turn(engine._player("P1")),
                      lambda request: "yes" if request.kind == "yingzi" else "pass")

        self.assertEqual(engine.state.result, "draw")
        self.assertEqual(engine.state.end_reason, "C-04_insufficient_cards")
        self.assertEqual(tuple(engine._zone("draw_pile").card_ids), retained)
        self.assertEqual(tuple(engine._zone("P1.hand").card_ids), hand_before)
        assert_card_zone_invariant(engine.state)

    def test_xiaoji_does_not_trigger_when_death_cleans_equipment(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        set_hero(engine, "AI1", "sunshangxiang")
        equipment = put_equipment(engine, "AI1", "axe")
        before_hand = tuple(engine._zone("AI1.hand").card_ids)
        before_draw = tuple(engine._zone("draw_pile").card_ids)

        engine._kill_player("AI1", None)

        self.assertEqual(engine.state.cards[equipment].zone_id, "discard_pile")
        self.assertEqual(tuple(engine._zone("AI1.hand").card_ids), ())
        self.assertEqual(tuple(engine._zone("draw_pile").card_ids), before_draw)
        self.assertFalse(any("枭姬" in log.text for log in engine.logs))
        self.assertNotEqual(before_hand, ())
        assert_card_zone_invariant(engine.state)

    def test_liuli_is_not_offered_when_only_attacker_and_daqiao_remain_legal(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "daqiao")
        engine._kill_player("AI2", None)
        prompts = []

        run_generator(engine, engine._resolve_kill("P1", "AI1", None, active_play=True),
                      lambda request: (prompts.append(request.kind) or "pass"))

        self.assertNotIn("liuli", prompts)
        self.assertEqual(engine._player("AI1").hp, engine._player("AI1").max_hp - 1)
        assert_card_zone_invariant(engine.state)

    def test_qixi_is_unavailable_without_target_cards_and_can_be_nullified(self) -> None:
        empty = make_engine(hero_id="ganning")
        black = put_hand(empty, "P1", "sha", suit="spades")
        for player in empty.state.players:
            if player.player_id != "P1":
                for zone_id in (player.hand_zone_id, player.equipment_zone_id,
                                player.judgment_zone_id):
                    for card_id in tuple(empty._zone(zone_id).card_ids):
                        empty._discard_card(card_id)
        intent = ActionIntent("P1", skill_id="qixi", cost_card_ids=(black,),
                              target_ids=("AI1",))
        self.assertFalse(empty.is_legal_intent(intent))

        negated = make_engine(hero_id="ganning")
        black = put_hand(negated, "P1", "sha", suit="clubs")
        target_card = put_equipment(negated, "AI1", "axe")
        negate = put_hand(negated, "AI1", "negate")
        intent = ActionIntent("P1", skill_id="qixi", cost_card_ids=(black,),
                              target_ids=("AI1",))
        self.assertTrue(negated.is_legal_intent(intent))
        negated.ai = RouteAI(lambda _view, request:
                             f"negate:{negate}" if request.kind == "nullification" else None)

        submit(negated, intent)

        self.assertEqual(negated.state.cards[black].zone_id, "discard_pile")
        self.assertEqual(negated.state.cards[negate].zone_id, "discard_pile")
        self.assertEqual(negated.state.cards[target_card].zone_id, "AI1.equipment")
        assert_card_zone_invariant(empty.state)
        assert_card_zone_invariant(negated.state)

    def test_harvest_uses_a_prior_pick_negate_and_discards_unclaimed_display_cards(self) -> None:
        human_ids = frozenset({"P1", "AI1", "AI2", "AI3", "AI4"})
        engine = make_engine("five_player_identity", hero_id="caocao",
                             identity=Identity.LORD, human_player_ids=human_ids)
        engine._player("P1").identity = Identity.LORD.value
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                engine._discard_card(card_id)
        draw = engine._zone("draw_pile").card_ids
        negate = next(card_id for card_id in draw
                      if engine._definition(card_id).kind_id == "negate")
        others = [card_id for card_id in draw
                  if card_id != negate
                  and engine._definition(card_id).kind_id != "harvest"][:4]
        revealed = (negate, *others)
        for card_id in reversed(revealed):
            draw.remove(card_id)
            draw.insert(0, card_id)
        harvest = put_hand(engine, "P1", "harvest")
        engine._move(harvest, "resolving", owner_id="P1", controller_id="P1",
                     visibility=Visibility.PUBLIC)
        pick_targets = []
        negated_targets = []

        engine._drive(engine._resolve_harvest("P1", harvest))
        while engine.pending_request:
            request = engine.pending_request
            if request.kind == "nullification":
                target_id = dict(request.context)["target_id"]
                if request.player_id == "P1" and target_id == "AI1":
                    choice = f"negate:{negate}"
                    negated_targets.append(target_id)
                else:
                    choice = "pass"
            elif request.kind == "harvest_pick":
                pick_targets.append(request.player_id)
                self.assertEqual(request.min_choices, 1)
                self.assertFalse(any(option.category == "pass" for option in request.options))
                choice = (f"take:{negate}" if request.player_id == "P1" else
                          next(option.choice_id for option in request.options))
            else:
                self.fail(f"unexpected request kind: {request.kind}")
            engine.answer_prompt(choice)

        engine._discard_card(harvest)
        self.assertEqual(negated_targets, ["AI1"])
        self.assertEqual(pick_targets, ["P1", "AI2", "AI3", "AI4"])
        self.assertEqual(engine.state.cards[negate].zone_id, "discard_pile")
        self.assertEqual(sum(engine.state.cards[item].zone_id.endswith(".hand")
                             for item in others), 3)
        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile"
                             for item in others), 1)
        self.assertEqual(engine._zone("resolving").card_ids, [])
        assert_card_zone_invariant(engine.state)

    def test_renwang_shield_blocks_black_slash_but_not_duel(self) -> None:
        engine = make_engine()
        shield = put_equipment(engine, "AI1", "renwang_shield")
        black_slash = put_hand(engine, "P1", "sha", suit="spades")
        initial_hp = engine._player("AI1").hp

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=black_slash))

        self.assertEqual(engine._player("AI1").hp, initial_hp)
        self.assertEqual(engine._kill_uses["P1"], 1)
        self.assertEqual(engine.state.cards[black_slash].zone_id, "discard_pile")
        duel = put_hand(engine, "P1", "duel")
        submit(engine, action(engine, kind_id="duel", target_id="AI1", card_id=duel))
        self.assertEqual(engine._player("AI1").hp, initial_hp - 1)
        self.assertEqual(engine.state.cards[shield].zone_id, "AI1.equipment")
        assert_card_zone_invariant(engine.state)

    def test_frost_sword_has_no_prompt_without_cards_and_takes_a_single_card(self) -> None:
        empty = make_engine()
        put_equipment(empty, "P1", "frost_sword")
        for zone_id in ("AI1.hand", "AI1.equipment"):
            for card_id in tuple(empty._zone(zone_id).card_ids):
                empty._discard_card(card_id)
        slash = put_hand(empty, "P1", "sha")
        prompts = []
        before = empty._player("AI1").hp
        submit(empty, action(empty, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: (prompts.append(request.kind) or "pass"))
        self.assertNotIn("frost_sword", prompts)
        self.assertEqual(empty._player("AI1").hp, before - 1)

        one = make_engine()
        put_equipment(one, "P1", "frost_sword")
        for zone_id in ("AI1.hand", "AI1.equipment"):
            for card_id in tuple(one._zone(zone_id).card_ids):
                one._discard_card(card_id)
        only_card = put_hand(one, "AI1", "shan")
        slash = put_hand(one, "P1", "sha")
        before = one._player("AI1").hp
        prompts = []

        def choose_frost(request):
            prompts.append(request.kind)
            return "yes" if request.kind == "frost_sword" else "hand"

        submit(one, action(one, kind_id="sha", target_id="AI1", card_id=slash),
               choose_frost)
        self.assertIn("frost_sword", prompts)
        self.assertEqual(one._player("AI1").hp, before)
        self.assertEqual(one.state.cards[only_card].zone_id, "discard_pile")
        assert_card_zone_invariant(empty.state)
        assert_card_zone_invariant(one.state)

    def test_axe_payment_is_atomic_before_loss_triggers_and_excludes_axe(self) -> None:
        engine = make_engine(hero_id="luxun")
        axe = put_equipment(engine, "P1", "axe")
        armor = put_equipment(engine, "P1", "bagua_formation")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            if engine._definition(card_id).name == "闪":
                engine._discard_card(card_id)
        slash = put_hand(engine, "P1", "sha")
        remaining_hand = put_hand(engine, "P1", "shan")
        target_flash = put_hand(engine, "AI1", "shan")
        seen = []
        engine.ai = RouteAI(lambda _view, request:
                            f"flash:{target_flash}" if request.kind == "flash" else None)
        before_hp = engine._player("AI1").hp

        def choose_axe(request):
            seen.append((request.kind,
                         tuple(engine._zone("discard_pile").card_ids)))
            if request.kind == "flash":
                return f"flash:{target_flash}"
            if request.kind == "axe_payment":
                return (f"discard:{remaining_hand}", f"discard:{armor}")
            if request.kind == "lianying":
                return "yes"
            return "pass"

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               choose_axe)

        self.assertEqual(engine.state.cards[axe].zone_id, "P1.equipment")
        self.assertEqual(engine.state.cards[armor].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[remaining_hand].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        self.assertEqual(engine._player("AI1").hp, before_hp - 1)
        self.assertIn("lianying", [kind for kind, _discarded in seen])
        lianying_snapshot = next(cards for kind, cards in seen if kind == "lianying")
        self.assertIn(armor, lianying_snapshot)
        self.assertIn(remaining_hand, lianying_snapshot)
        assert_card_zone_invariant(engine.state)

    def test_kirin_bow_decline_preserves_both_mounts_and_resolves_damage(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "kirin_bow")
        mounts = (put_equipment(engine, "AI1", "dilu"),
                  put_equipment(engine, "AI1", "jueying"))
        slash = put_hand(engine, "P1", "sha")
        before = engine._player("AI1").hp
        prompt_hp = []

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: (prompt_hp.append(engine._player("AI1").hp) or "pass")
               if request.kind == "kirin_bow" else "pass")

        self.assertEqual(prompt_hp, [before])
        self.assertTrue(all(engine.state.cards[item].zone_id == "AI1.equipment"
                            for item in mounts))
        self.assertEqual(engine._player("AI1").hp, before - 1)
        assert_card_zone_invariant(engine.state)

    def test_serpent_spear_response_preserves_color_for_same_color_materials(self) -> None:
        engine = make_engine()
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        put_equipment(engine, "AI1", "serpent_spear")
        first = put_hand(engine, "AI1", "sha", suit="hearts")
        second = put_hand(engine, "AI1", "shan", suit="diamonds")
        engine.ai = RouteAI(lambda _view, request:
                            "serpent_spear" if request.kind == "duel_kill" else
                            tuple(option.choice_id for option in request.options
                                  if option.category == "discard")[:2]
                            if request.kind == "serpent_spear_cost" else None)

        result = complete_without_prompts(
            engine._ask_kill_response("AI1", "决斗", "P1"))

        self.assertEqual(engine._response_virtual_colors[result[0]], "red")
        self.assertEqual(engine.state.cards[first].zone_id, "resolving")
        self.assertEqual(engine.state.cards[second].zone_id, "resolving")
        engine._discard_response_materials(result[0])
        assert_card_zone_invariant(engine.state)

    def test_qinglong_followup_does_not_open_ordinary_skill_actions_between_kills(self) -> None:
        engine = make_engine(hero_id="zhangfei", human_player_ids=frozenset({"P1", "AI1"}))
        put_equipment(engine, "P1", "qinglong_blade")
        first_flash = put_hand(engine, "AI1", "shan")
        first = put_hand(engine, "P1", "sha")
        second = put_hand(engine, "P1", "sha")
        prompt_order = []

        def choose_followup(request):
            prompt_order.append(request.kind)
            if request.kind == "flash":
                return f"flash:{first_flash}"
            if request.kind == "qinglong_followup":
                return f"continue:{second}"
            return "pass"

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=first),
               choose_followup)

        self.assertEqual(prompt_order, ["flash", "qinglong_followup"])
        self.assertEqual(engine._player("AI1").hp, engine._player("AI1").max_hp - 1)
        self.assertEqual(engine.state.cards[second].zone_id, "discard_pile")
        self.assertEqual(engine.state.event_stack, [])
        assert_card_zone_invariant(engine.state)

    def test_rescue_from_zero_and_minus_two_requires_positive_health(self) -> None:
        for starting_hp in (0, -2):
            with self.subTest(starting_hp=starting_hp):
                engine = make_engine(human_player_ids=frozenset({"P1"}))
                engine._player("P1").hp = starting_hp
                peaches = tuple(put_hand(engine, "P1", "tao")
                                for _ in range(1 - starting_hp))
                engine._drive(engine._rescue("P1"))
                for index, peach in enumerate(peaches):
                    self.assertEqual(engine.pending_request.kind, "rescue")
                    self.assertTrue(any(option.choice_id == f"peach:{peach}"
                                        for option in engine.pending_request.options))
                    engine.answer_prompt(f"peach:{peach}")
                    expected_hp = starting_hp + index + 1
                    self.assertEqual(engine._player("P1").hp, expected_hp)
                    if expected_hp <= 0:
                        self.assertEqual(engine.pending_request.kind, "rescue")
                    else:
                        self.assertIsNone(engine.pending_request)
                self.assertTrue(all(engine.state.cards[item].zone_id == "discard_pile"
                                    for item in peaches))
                assert_card_zone_invariant(engine.state)

    def test_rende_healing_at_full_health_is_consumed_for_the_phase(self) -> None:
        engine = make_engine(hero_id="liubei")
        first_cost = tuple(engine._zone("P1.hand").card_ids[:2])
        first_intent = ActionIntent("P1", skill_id="rende", choice="choose",
                                    target_ids=("AI1",))
        self.assertTrue(engine.is_legal_intent(first_intent))
        submit(engine, first_intent,
               lambda request: tuple(f"rende:{item}" for item in first_cost)
               if request.kind == "rende_cards" else "pass")
        self.assertEqual(engine._player("P1").hp, engine._player("P1").max_hp)
        self.assertIn("P1", engine._rende_heal_used)
        self.assertEqual(engine._rende_given["P1"], 2)

        engine._player("P1").hp -= 1
        second_cost = engine._zone("P1.hand").card_ids[0]
        second_intent = ActionIntent("P1", skill_id="rende", choice="choose",
                                     target_ids=("AI1",))
        submit(engine, second_intent,
               lambda request: (f"rende:{second_cost}",)
               if request.kind == "rende_cards" else "pass")
        self.assertEqual(engine._player("P1").hp, engine._player("P1").max_hp - 1)
        self.assertEqual(engine._rende_given["P1"], 3)
        assert_card_zone_invariant(engine.state)

    def test_zhiheng_requires_a_card_and_is_once_per_play_phase(self) -> None:
        engine = make_engine(hero_id="sunquan")
        no_cost = ActionIntent("P1", skill_id="zhiheng")
        self.assertFalse(engine.is_legal_intent(no_cost))
        choose_cost = ActionIntent("P1", skill_id="zhiheng", choice="choose")
        self.assertTrue(engine.is_legal_intent(choose_cost))
        card = engine._zone("P1.hand").card_ids[0]

        submit(engine, choose_cost,
               lambda request: f"discard:{card}" if request.kind == "zhiheng_cards"
               else "pass")

        self.assertEqual(engine.state.cards[card].zone_id, "discard_pile")
        self.assertFalse(any(item.intent.skill_id == "zhiheng"
                             for item in engine.available_actions("P1")))
        assert_card_zone_invariant(engine.state)

    def test_guose_rejects_self_qianxun_and_duplicate_delayed_targets(self) -> None:
        engine = make_engine(hero_id="daqiao")
        diamond = put_hand(engine, "P1", "sha", suit="diamonds")
        self.assertFalse(engine.is_legal_intent(ActionIntent(
            "P1", skill_id="guose", cost_card_ids=(diamond,), target_ids=("P1",))))
        set_hero(engine, "AI1", "luxun")
        self.assertFalse(engine.is_legal_intent(ActionIntent(
            "P1", skill_id="guose", cost_card_ids=(diamond,), target_ids=("AI1",))))
        indulgence = place(engine, "indulgence", "AI2.judgment", owner_id="AI2",
                           controller_id="AI2", visibility=Visibility.PUBLIC)
        duplicate = ActionIntent("P1", skill_id="guose", cost_card_ids=(diamond,),
                                 target_ids=("AI2",))
        self.assertFalse(engine.is_legal_intent(duplicate))
        self.assertEqual(engine.state.cards[indulgence].zone_id, "AI2.judgment")
        assert_card_zone_invariant(engine.state)

    def test_guose_can_use_diamond_equipment_and_has_no_nullification_window(self) -> None:
        engine = make_engine(hero_id="daqiao")
        equipment = next(card_id for card_id, card in engine.state.cards.items()
                         if CARD_BY_ID[card.definition_id].category.value == "equipment"
                         and CARD_BY_ID[card.definition_id].suit.value == "diamonds"
                         and card.zone_id == "draw_pile")
        engine._move(equipment, "P1.equipment", owner_id="P1", controller_id="P1",
                     visibility=Visibility.PUBLIC)
        intent = ActionIntent("P1", skill_id="guose", cost_card_ids=(equipment,),
                              target_ids=("AI1",))
        self.assertTrue(engine.is_legal_intent(intent))
        requests = []

        submit(engine, intent, lambda request: (requests.append(request.kind) or "pass"))

        self.assertNotIn("nullification", requests)
        self.assertEqual(engine.state.cards[equipment].zone_id, "AI1.judgment")
        assert_card_zone_invariant(engine.state)

    def test_draw_two_shortage_after_jizhi_keeps_the_effect_atomic(self) -> None:
        engine = make_engine(hero_id="huangyueying")
        draw_two = put_hand(engine, "P1", "draw_two")
        one_card = next(card_id for card_id in engine._zone("draw_pile").card_ids
                        if card_id != draw_two)
        for card_id in tuple(engine.state.cards):
            if card_id == draw_two:
                continue
            destination = "draw_pile" if card_id == one_card else "P1.hand"
            if engine.state.cards[card_id].zone_id != destination:
                engine._move(card_id, destination,
                             owner_id="P1" if destination == "P1.hand" else None,
                             controller_id="P1" if destination == "P1.hand" else None,
                             visibility=(Visibility.OWNER_ONLY if destination == "P1.hand"
                                         else Visibility.HIDDEN))
        before_draw = tuple(engine._zone("draw_pile").card_ids)
        self.assertEqual(before_draw, (one_card,))
        intent = action(engine, kind_id="draw_two", card_id=draw_two)

        submit(engine, intent, lambda request: "yes" if request.kind == "jizhi" else "pass")

        self.assertEqual(engine.state.result, "draw")
        self.assertEqual(engine.player_outcome, "draw")
        self.assertEqual(tuple(engine._zone("draw_pile").card_ids), ())
        self.assertEqual(engine.state.cards[one_card].zone_id, "P1.hand")
        self.assertEqual(engine.state.cards[draw_two].zone_id, "discard_pile")
        self.assertFalse(any("无中生有摸" in log.text for log in engine.logs))
        self.assertEqual(engine._zone("resolving").card_ids, [])
        assert_card_zone_invariant(engine.state)

    def test_empty_city_blocks_duel_before_target_lock(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "zhugeliang")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        duel = put_hand(engine, "P1", "duel")
        self.assertNotIn("AI1", engine.legal_targets_for_card("P1", duel))
        self.assertFalse(engine.is_legal_intent(
            ActionIntent("P1", card_id=duel, target_ids=("AI1",))))

    def test_empty_city_can_initiate_lijian_but_cannot_receive_its_duel(self) -> None:
        engine = make_engine(hero_id="diaochan")
        set_hero(engine, "AI1", "zhugeliang")
        set_hero(engine, "AI2", "guanyu")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("AI2.hand").card_ids):
            engine._discard_card(card_id)
        cost = put_hand(engine, "P1", "tao")
        intent = ActionIntent("P1", skill_id="lijian", cost_card_ids=(cost,),
                              target_ids=("AI1", "AI2"))
        self.assertTrue(engine.is_legal_intent(intent))

        engine.submit_action(intent)
        self.assertEqual(engine.pending_request.kind, "lijian_initiator")
        offered = {option.value for option in engine.pending_request.options}
        self.assertEqual(offered, {"AI1"})
        ai2_hp = engine._player("AI2").hp
        engine.answer_prompt("initiator:AI1")

        self.assertEqual(engine._player("AI2").hp, ai2_hp - 1)
        self.assertEqual(engine.state.cards[cost].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

        both_empty_engine = make_engine(hero_id="diaochan")
        for player_id in ("AI1", "AI2"):
            set_hero(both_empty_engine, player_id, "zhugeliang")
            for card_id in tuple(both_empty_engine._zone(f"{player_id}.hand").card_ids):
                both_empty_engine._discard_card(card_id)
        both_empty_cost = put_hand(both_empty_engine, "P1", "tao")
        both_empty = ActionIntent("P1", skill_id="lijian",
                                  cost_card_ids=(both_empty_cost,),
                                  target_ids=("AI1", "AI2"))
        self.assertFalse(both_empty_engine.is_legal_intent(both_empty))

    def test_bagua_generated_flash_is_not_reoffered_as_longdan_material(self) -> None:
        engine = make_engine()
        set_hero(engine, "AI1", "zhaoyun")
        put_equipment(engine, "AI1", "bagua_formation")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        red = next(card_id for card_id in engine._zone("draw_pile").card_ids
                   if engine._color(card_id) == "red")
        engine._zone("draw_pile").card_ids.remove(red)
        engine._zone("draw_pile").card_ids.insert(0, red)
        slash = put_hand(engine, "P1", "sha")
        requests = []
        engine.ai = RouteAI(lambda _view, request:
                            (requests.append(request.kind) or "bagua")
                            if request.kind == "flash" else None)
        target_hp = engine._player("AI1").hp

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash))

        self.assertEqual(requests, ["flash"])
        self.assertEqual(engine._player("AI1").hp, target_hp)
        self.assertEqual(engine.state.cards[red].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_tiandu_only_offers_guojia_his_own_final_judgment(self) -> None:
        engine = make_engine(hero_id="guojia")
        card = place(engine, "dismantle", "resolving", visibility=Visibility.PUBLIC)
        requests = []

        run_generator(engine, engine._settle_judgment("AI1", card),
                      lambda request: (requests.append(request.kind) or "yes"))

        self.assertNotIn("tiandu", requests)
        self.assertEqual(engine.state.cards[card].zone_id, "discard_pile")
        self.assertNotIn(card, engine._zone("P1.hand").card_ids)
        assert_card_zone_invariant(engine.state)

    def test_luoshen_can_stop_after_a_black_card_without_revealing_next_card(self) -> None:
        engine = make_engine(hero_id="zhenji")
        draw = engine._zone("draw_pile").card_ids
        black_cards = [card_id for card_id in draw if engine._color(card_id) == "black"][:2]
        for card_id in reversed(black_cards):
            draw.remove(card_id)
            draw.insert(0, card_id)
        requests = []

        run_generator(engine, engine._preparation_skills(engine._player("P1")),
                      lambda request: (requests.append(request.kind) or
                                       ("yes" if request.kind == "luoshen"
                                        and requests.count("luoshen") == 1 else "pass")))

        self.assertEqual(requests.count("luoshen"), 2)
        self.assertEqual(engine.state.cards[black_cards[0]].zone_id, "P1.hand")
        self.assertEqual(engine._zone("draw_pile").card_ids[0], black_cards[1])
        assert_card_zone_invariant(engine.state)

    def test_guojia_can_give_all_yiji_cards_to_the_same_player_per_damage_point(self) -> None:
        engine = make_engine(hero_id="guojia", human_player_ids=frozenset())
        deck_before = tuple(engine._zone("draw_pile").card_ids[:4])
        engine.ai = RouteAI(lambda _view, request:
                            "give:AI2" if request.kind == "yiji_give" else None)

        complete_without_prompts(engine._damage("AI1", "P1", 2, None,
                                                damage_kind="测试"))

        self.assertTrue(all(engine.state.cards[item].zone_id == "AI2.hand"
                            for item in deck_before))
        self.assertEqual(sum(log.text.startswith("郭嘉因第") for log in engine.logs), 2)
        assert_card_zone_invariant(engine.state)

    def test_lianying_can_trigger_between_wushuang_flash_responses(self) -> None:
        engine = make_engine(hero_id="lvbu")
        set_hero(engine, "AI1", "luxun")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        first_flash = put_hand(engine, "AI1", "shan")
        next_flash = next(card_id for card_id in engine._zone("draw_pile").card_ids
                          if engine._definition(card_id).name == "闪")
        engine._zone("draw_pile").card_ids.remove(next_flash)
        engine._zone("draw_pile").card_ids.insert(0, next_flash)
        slash = put_hand(engine, "P1", "sha")
        prompt_order = []

        def route(_view, request):
            if request.kind == "flash":
                prompt_order.append(request.kind)
                return next((option.choice_id for option in request.options
                             if option.category == "flash"), None)
            if request.kind == "lianying":
                prompt_order.append(request.kind)
                return "yes"
            return None

        engine.ai = RouteAI(route)
        before = engine._player("AI1").hp

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash))

        self.assertEqual(prompt_order[:3], ["flash", "lianying", "flash"])
        self.assertEqual(engine._player("AI1").hp, before)
        self.assertEqual(engine.state.cards[first_flash].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[next_flash].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_keji_is_disabled_by_a_kill_played_as_a_duel_response(self) -> None:
        engine = make_engine(hero_id="lvmeng")
        for player_id in ("P1", "AI1"):
            for card_id in tuple(engine._zone(f"{player_id}.hand").card_ids):
                engine._discard_card(card_id)
        duel = put_hand(engine, "P1", "duel")
        response_kill = put_hand(engine, "P1", "sha")
        ai_kill = put_hand(engine, "AI1", "sha")
        fillers = tuple(put_hand(engine, "P1", "shan") for _ in range(6))
        engine.ai = RouteAI(lambda _view, request:
                            f"kill:{ai_kill}" if request.kind == "duel_kill"
                            and request.player_id == "AI1" else None)
        submit(engine, action(engine, kind_id="duel", target_id="AI1", card_id=duel),
               lambda request: f"kill:{response_kill}"
               if request.kind == "duel_kill" else "pass")
        self.assertIn("P1", engine._played_kill_this_turn)
        self.assertTrue(all(engine.state.cards[item].zone_id == "P1.hand" for item in fillers))

        seen = []
        run_generator(engine, engine._discard_phase(engine._player("P1")),
                      lambda request: (seen.append(request.kind) or
                                       tuple(option.choice_id for option in request.options
                                             if option.category == "discard")[:request.min_choices]
                                       if request.kind == "discard" else "yes"))

        self.assertNotIn("keji", seen)
        self.assertEqual(len(engine._zone("P1.hand").card_ids), engine._player("P1").hp)
        assert_card_zone_invariant(engine.state)

    def test_ganglie_red_heart_judgment_stops_without_source_choice(self) -> None:
        engine = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        set_hero(engine, "AI1", "xiahoudun")
        heart = next(card_id for card_id in engine._zone("draw_pile").card_ids
                     if engine._definition(card_id).suit.value == "hearts")
        engine._zone("draw_pile").card_ids.remove(heart)
        engine._zone("draw_pile").card_ids.insert(0, heart)
        target_hp = engine._player("AI1").hp
        source_hp = engine._player("P1").hp

        engine._drive(engine._damage("P1", "AI1", 1, None, damage_kind="测试"))
        self.assertEqual(engine.pending_request.kind, "ganglie_trigger")
        request_kinds = [engine.pending_request.kind]
        engine.answer_prompt("yes")
        while engine.pending_request:
            request = engine.pending_request
            request_kinds.append(request.kind)
            engine.answer_prompt("pass")

        self.assertIsNone(engine.pending_request)
        self.assertEqual(engine._player("AI1").hp, target_hp - 1)
        self.assertEqual(engine._player("P1").hp, source_hp)
        self.assertEqual(engine.state.cards[heart].zone_id, "discard_pile")
        self.assertNotIn("ganglie", request_kinds)
        assert_card_zone_invariant(engine.state)

    def test_ganglie_triggers_once_for_multi_point_damage_and_after_rescue(self) -> None:
        multi = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        set_hero(multi, "AI1", "xiahoudun")
        before = multi._player("AI1").hp
        multi._drive(multi._damage("P1", "AI1", 2, None, damage_kind="测试"))
        self.assertEqual(multi.pending_request.kind, "ganglie_trigger")
        multi.answer_prompt("pass")
        self.assertIsNone(multi.pending_request)
        self.assertEqual(multi._player("AI1").hp, before - 2)
        self.assertFalse(any("判定" in log.text for log in multi.logs))

        rescued = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        set_hero(rescued, "AI1", "xiahoudun")
        rescued._player("AI1").hp = 1
        for player in rescued.state.players:
            if player.player_id != "AI1":
                for card_id in tuple(rescued._zone(player.hand_zone_id).card_ids):
                    if rescued._definition(card_id).name == "桃":
                        rescued._discard_card(card_id)
        peach = put_hand(rescued, "AI1", "tao")
        rescued._drive(rescued._damage("P1", "AI1", 1, None, damage_kind="测试"))
        self.assertEqual(rescued.pending_request.kind, "rescue")
        rescued.answer_prompt(f"peach:{peach}")
        self.assertEqual(rescued._player("AI1").hp, 1)
        self.assertEqual(rescued.pending_request.kind, "ganglie_trigger")
        rescued.answer_prompt("pass")
        self.assertEqual(rescued._player("P1").hp, rescued._player("P1").max_hp)
        self.assertEqual(rescued.state.cards[peach].zone_id, "discard_pile")
        assert_card_zone_invariant(multi.state)
        assert_card_zone_invariant(rescued.state)

    def test_wushuang_duel_uses_two_kills_each_round_for_both_lvbu_roles(self) -> None:
        engine = make_engine(hero_id="lvbu")
        set_hero(engine, "AI1", "lvbu")
        for player_id in ("P1", "AI1"):
            for card_id in tuple(engine._zone(f"{player_id}.hand").card_ids):
                engine._discard_card(card_id)
        duel = put_hand(engine, "P1", "duel")
        player_kills = [put_hand(engine, "P1", "sha") for _ in range(4)]
        ai_kills = [put_hand(engine, "AI1", "sha") for _ in range(4)]
        engine.ai = RouteAI(lambda _view, request:
                            next(option.choice_id for option in request.options
                                 if option.category == "kill")
                            if request.kind == "duel_kill" else None)
        before = {player_id: engine._player(player_id).hp for player_id in ("P1", "AI1")}

        submit(engine, action(engine, kind_id="duel", target_id="AI1", card_id=duel),
               lambda request: next(option.choice_id for option in request.options
                                    if option.category == "kill")
               if request.kind == "duel_kill" else "pass")

        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile"
                             for item in player_kills), 4)
        self.assertEqual(sum(engine.state.cards[item].zone_id == "discard_pile"
                             for item in ai_kills), 4)
        self.assertEqual(sum("为决斗打出" in log.text for log in engine.logs), 8)
        self.assertEqual(engine._player("P1").hp, before["P1"])
        self.assertEqual(engine._player("AI1").hp, before["AI1"] - 1)
        self.assertEqual(engine.state.cards[duel].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_qinggang_ignores_renwang_only_for_its_users_black_slash(self) -> None:
        engine = make_engine()
        sword = put_equipment(engine, "P1", "qinggang_sword")
        shield = put_equipment(engine, "AI1", "renwang_shield")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        slash = put_hand(engine, "P1", "sha", suit="spades")
        before = engine._player("AI1").hp

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash))

        self.assertEqual(engine._player("AI1").hp, before - 1)
        self.assertEqual(engine.state.cards[sword].zone_id, "P1.equipment")
        self.assertEqual(engine.state.cards[shield].zone_id, "AI1.equipment")
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

        non_kill = make_engine()
        put_equipment(non_kill, "P1", "qinggang_sword")
        non_kill_shield = put_equipment(non_kill, "AI1", "renwang_shield")
        for card_id in tuple(non_kill._zone("AI1.hand").card_ids):
            if non_kill._definition(card_id).name == "闪":
                non_kill._discard_card(card_id)
        arrows = put_hand(non_kill, "P1", "arrows")
        before = non_kill._player("AI1").hp
        submit(non_kill, action(non_kill, kind_id="arrows", card_id=arrows))
        self.assertEqual(non_kill._player("AI1").hp, before - 1)
        self.assertEqual(non_kill._zone("AI1.equipment").card_ids, [non_kill_shield])
        assert_card_zone_invariant(non_kill.state)

    def test_basic_cards_keep_usage_target_and_response_boundaries(self) -> None:
        engine = make_engine()
        slashes = (put_hand(engine, "P1", "sha"), put_hand(engine, "P1", "sha"))
        flash = put_hand(engine, "P1", "shan")
        peach = put_hand(engine, "P1", "tao")
        first_intent = action(engine, kind_id="sha", target_id="AI1", card_id=slashes[0])
        self.assertFalse(engine.is_legal_intent(
            ActionIntent("P1", card_id=slashes[0], target_ids=("P1",))))
        self.assertFalse(engine.is_legal_intent(ActionIntent("P1", card_id=peach)))
        self.assertFalse(any(item.intent.card_id == flash
                             for item in engine.available_actions("P1")))

        submit(engine, first_intent)

        self.assertFalse(any(item.intent.card_id == slashes[1]
                             for item in engine.available_actions("P1")))
        self.assertEqual(engine.state.cards[slashes[0]].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[flash].zone_id, "P1.hand")
        assert_card_zone_invariant(engine.state)

    def test_duel_can_be_nullified_before_the_first_kill_response(self) -> None:
        engine = make_engine()
        negate = put_hand(engine, "AI1", "negate")
        duel = put_hand(engine, "P1", "duel")
        target_hp = engine._player("AI1").hp
        engine.ai = RouteAI(lambda _view, request:
                            f"negate:{negate}" if request.kind == "nullification" else None)
        requests = []

        submit(engine, action(engine, kind_id="duel", target_id="AI1", card_id=duel),
               lambda request: (requests.append(request.kind) or "pass"))

        self.assertEqual(requests, [])
        self.assertEqual(engine._player("AI1").hp, target_hp)
        self.assertEqual(engine.state.cards[duel].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[negate].zone_id, "discard_pile")
        self.assertFalse(any("为决斗打出" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_serpent_spear_keeps_matching_color_and_rejects_equipment_cost(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "serpent_spear")
        shield = put_equipment(engine, "AI1", "renwang_shield")
        first = put_hand(engine, "P1", "sha", suit="spades")
        second = put_hand(engine, "P1", "sha", suit="clubs")
        intent = ActionIntent("P1", skill_id="serpent_spear",
                              cost_card_ids=(first, second), target_ids=("AI1",))
        self.assertTrue(engine.is_legal_intent(intent))
        target_hp = engine._player("AI1").hp

        submit(engine, intent)

        self.assertEqual(engine._player("AI1").hp, target_hp)
        self.assertEqual(engine.state.cards[first].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[second].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[shield].zone_id, "AI1.equipment")

        invalid = make_engine()
        spear = put_equipment(invalid, "P1", "serpent_spear")
        equipment_cost = put_equipment(invalid, "P1", "bagua_formation")
        hand_cost = put_hand(invalid, "P1", "shan")
        illegal = ActionIntent("P1", skill_id="serpent_spear",
                               cost_card_ids=(equipment_cost, hand_cost),
                               target_ids=("AI1",))
        self.assertNotEqual(spear, equipment_cost)
        self.assertFalse(invalid.is_legal_intent(illegal))
        assert_card_zone_invariant(engine.state)
        assert_card_zone_invariant(invalid.state)

    def test_crossbow_limit_returns_after_same_slot_weapon_replacement(self) -> None:
        engine = make_engine()
        crossbow = put_equipment(engine, "P1", "crossbow")
        first = put_hand(engine, "P1", "sha")
        second = put_hand(engine, "P1", "sha")
        engine.submit_action(action(engine, kind_id="sha", target_id="AI1", card_id=first))
        replacement = put_hand(engine, "P1", "qinggang_sword")
        submit(engine, ActionIntent("P1", card_id=replacement))

        self.assertEqual(engine.state.cards[crossbow].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[replacement].zone_id, "P1.equipment")
        self.assertFalse(any(item.intent.card_id == second
                             for item in engine.available_actions("P1")))
        assert_card_zone_invariant(engine.state)

    def test_double_swords_can_be_declined_and_has_no_same_gender_trigger(self) -> None:
        declined = make_engine(hero_id="daqiao")
        set_hero(declined, "AI1", "guanyu")
        put_equipment(declined, "P1", "double_swords")
        slash = put_hand(declined, "P1", "sha")
        before_hand = tuple(declined._zone("P1.hand").card_ids)
        requests = []
        submit(declined, action(declined, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: (requests.append(request.kind) or "pass"))
        self.assertIn("double_swords", requests)
        self.assertNotIn("double_swords_target", requests)
        self.assertEqual(tuple(declined._zone("P1.hand").card_ids),
                         tuple(card for card in before_hand if card != slash))

        same_gender = make_engine()
        set_hero(same_gender, "AI1", "guanyu")
        put_equipment(same_gender, "P1", "double_swords")
        same_slash = put_hand(same_gender, "P1", "sha")
        same_requests = []
        submit(same_gender, action(same_gender, kind_id="sha", target_id="AI1",
                                   card_id=same_slash),
               lambda request: (same_requests.append(request.kind) or "pass"))
        self.assertNotIn("double_swords", same_requests)
        self.assertNotIn("double_swords_target", same_requests)

    def test_frost_sword_loss_trigger_resolves_between_its_two_discards(self) -> None:
        engine = make_engine()
        put_equipment(engine, "P1", "frost_sword")
        set_hero(engine, "AI1", "luxun")
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        hand_card = put_hand(engine, "AI1", "shan")
        equipment = put_equipment(engine, "AI1", "axe")
        slash = put_hand(engine, "P1", "sha")
        lianying_draw = engine._zone("draw_pile").card_ids[0]
        before_hp = engine._player("AI1").hp
        area_choices = []
        engine.ai = RouteAI(lambda _view, request:
                            "yes" if request.kind == "lianying" else None)

        def route(request):
            if request.kind == "frost_sword":
                return "yes"
            if request.kind == "card_choice_area":
                area_choices.append(tuple(option.choice_id for option in request.options))
                return "hand" if len(area_choices) == 1 else "equipment"
            if request.kind == "lianying":
                return "yes"
            return "pass"

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash), route)

        self.assertEqual(engine._player("AI1").hp, before_hp)
        self.assertEqual(engine.state.cards[hand_card].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[lianying_draw].zone_id, "AI1.hand")
        self.assertEqual(engine.state.cards[equipment].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        self.assertEqual(len(area_choices), 2)
        self.assertTrue(any("发动连营" in log.text for log in engine.logs))
        assert_card_zone_invariant(engine.state)

    def test_axe_needs_two_other_cards_and_cannot_pay_with_its_own_weapon(self) -> None:
        engine = make_engine()
        axe = put_equipment(engine, "P1", "axe")
        put_equipment(engine, "P1", "bagua_formation")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        for card_id in tuple(engine._zone("AI1.hand").card_ids):
            engine._discard_card(card_id)
        flash = put_hand(engine, "AI1", "shan")
        slash = put_hand(engine, "P1", "sha")
        prompts = []
        engine.ai = RouteAI(lambda _view, request:
                            f"flash:{flash}" if request.kind == "flash" else None)
        hp = engine._player("AI1").hp

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: (prompts.append(request.kind) or
                                f"flash:{flash}" if request.kind == "flash" else "pass"))

        self.assertEqual(engine._player("AI1").hp, hp)
        self.assertNotIn("axe_payment", prompts)
        self.assertEqual(engine.state.cards[axe].zone_id, "P1.equipment")
        self.assertEqual(engine.state.cards[flash].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        assert_card_zone_invariant(engine.state)

    def test_serpent_spear_simultaneous_payment_finishes_before_lianying(self) -> None:
        engine = make_engine(hero_id="luxun")
        put_equipment(engine, "P1", "serpent_spear")
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        first = put_hand(engine, "P1", "sha", suit="hearts")
        second = put_hand(engine, "P1", "shan")
        top = engine._zone("draw_pile").card_ids[0]
        intent = next(item.intent for item in engine.available_actions("P1")
                      if item.intent.skill_id == "serpent_spear"
                      and set(item.intent.cost_card_ids) == {first, second}
                      and item.intent.target_ids == ("AI1",))

        engine.submit_action(intent)
        self.assertEqual(engine.pending_request.kind, "lianying")
        self.assertEqual(engine.state.cards[first].zone_id, "resolving")
        self.assertEqual(engine.state.cards[second].zone_id, "resolving")
        engine.answer_prompt("yes")

        self.assertEqual(engine.state.cards[first].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[second].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[top].zone_id, "P1.hand")
        self.assertEqual(engine._player("AI1").hp, engine._player("AI1").max_hp - 1)
        assert_card_zone_invariant(engine.state)

    def test_qinglong_new_kill_rechecks_renwang_and_kongcheng(self) -> None:
        shielded = make_engine()
        put_equipment(shielded, "P1", "qinglong_blade")
        put_equipment(shielded, "AI1", "renwang_shield")
        for card_id in tuple(shielded._zone("AI1.hand").card_ids):
            shielded._discard_card(card_id)
        first_slash = put_hand(shielded, "P1", "sha", suit="hearts")
        second_slash = put_hand(shielded, "P1", "sha", suit="spades")
        flash = put_hand(shielded, "AI1", "shan")
        shielded.ai = RouteAI(lambda _view, request:
                              f"flash:{flash}" if request.kind == "flash" else None)
        before = shielded._player("AI1").hp
        submit(shielded, action(shielded, kind_id="sha", target_id="AI1",
                                card_id=first_slash),
               lambda request: (f"continue:{second_slash}"
                                if request.kind == "qinglong_followup" else "pass"))
        self.assertEqual(shielded._player("AI1").hp, before)
        self.assertEqual(shielded.state.cards[second_slash].zone_id, "discard_pile")

        empty_city = make_engine()
        set_hero(empty_city, "AI1", "zhugeliang")
        put_equipment(empty_city, "P1", "qinglong_blade")
        for card_id in tuple(empty_city._zone("AI1.hand").card_ids):
            empty_city._discard_card(card_id)
        first_slash = put_hand(empty_city, "P1", "sha")
        second_slash = put_hand(empty_city, "P1", "sha")
        flash = put_hand(empty_city, "AI1", "shan")
        empty_city.ai = RouteAI(lambda _view, request:
                                f"flash:{flash}" if request.kind == "flash" else None)
        prompts = []
        submit(empty_city, action(empty_city, kind_id="sha", target_id="AI1",
                                  card_id=first_slash),
               lambda request: (prompts.append(request.kind) or
                                f"continue:{second_slash}"
                                if request.kind == "qinglong_followup" else "pass"))
        self.assertNotIn("qinglong_followup", prompts)
        self.assertEqual(empty_city.state.cards[second_slash].zone_id, "P1.hand")

    def test_bagua_can_cover_two_wushuang_flashes_or_mix_with_one_hand_flash(self) -> None:
        two_bagua = make_engine(hero_id="lvbu")
        put_equipment(two_bagua, "AI1", "bagua_formation")
        for card_id in tuple(two_bagua._zone("AI1.hand").card_ids):
            two_bagua._discard_card(card_id)
        slash = put_hand(two_bagua, "P1", "sha")
        red_cards = [card_id for card_id in two_bagua._zone("draw_pile").card_ids
                     if two_bagua._color(card_id) == "red"][:2]
        for card_id in reversed(red_cards):
            two_bagua._zone("draw_pile").card_ids.remove(card_id)
            two_bagua._zone("draw_pile").card_ids.insert(0, card_id)
        requests = []
        two_bagua.ai = RouteAI(lambda _view, request:
                               (requests.append(request.kind) or "bagua"
                                if request.kind == "flash" and any(
                                    option.choice_id == "bagua" for option in request.options)
                                else None))
        hp = two_bagua._player("AI1").hp
        submit(two_bagua, action(two_bagua, kind_id="sha", target_id="AI1", card_id=slash))
        self.assertEqual(two_bagua._player("AI1").hp, hp)
        self.assertEqual([two_bagua.state.cards[item].zone_id for item in red_cards],
                         ["discard_pile", "discard_pile"])

        mixed = make_engine(hero_id="lvbu")
        put_equipment(mixed, "AI1", "bagua_formation")
        for card_id in tuple(mixed._zone("AI1.hand").card_ids):
            mixed._discard_card(card_id)
        flash = put_hand(mixed, "AI1", "shan")
        slash = put_hand(mixed, "P1", "sha")
        red = next(card_id for card_id in mixed._zone("draw_pile").card_ids
                   if mixed._color(card_id) == "red")
        mixed._zone("draw_pile").card_ids.remove(red)
        mixed._zone("draw_pile").card_ids.insert(0, red)
        flash_calls = 0

        def mix_route(_view, request):
            nonlocal flash_calls
            if request.kind == "flash":
                flash_calls += 1
                return "bagua" if flash_calls == 1 else f"flash:{flash}"
            return None

        mixed.ai = RouteAI(mix_route)
        hp = mixed._player("AI1").hp
        submit(mixed, action(mixed, kind_id="sha", target_id="AI1", card_id=slash))
        self.assertEqual(mixed._player("AI1").hp, hp)
        self.assertEqual(mixed.state.cards[red].zone_id, "discard_pile")
        self.assertEqual(mixed.state.cards[flash].zone_id, "discard_pile")
        assert_card_zone_invariant(mixed.state)

    def test_mounts_are_directional_and_same_slot_replacement_preserves_current_distance(self) -> None:
        engine = make_engine("five_player_identity", identity=Identity.LORD)
        for player_id, identity in {"P1": "lord", "AI1": "loyalist", "AI2": "rebel",
                                    "AI3": "rebel", "AI4": "turncoat"}.items():
            engine._player(player_id).identity = identity
        self.assertEqual(engine.distance("P1", "AI2"), 2)
        self.assertEqual(engine.distance("AI2", "P1"), 2)
        minus_old = put_equipment(engine, "P1", "chitu")
        self.assertEqual(engine.distance("P1", "AI2"), 1)
        self.assertEqual(engine.distance("AI2", "P1"), 2)
        plus_old = put_equipment(engine, "AI2", "jueying")
        self.assertEqual(engine.distance("P1", "AI2"), 2)
        self.assertEqual(engine.distance("AI2", "P1"), 2)
        other_to_player = engine.distance("AI1", "P1")
        new_plus = put_hand(engine, "AI2", "dilu")
        # The player turn is P1 in this fixture; resolve direct replacement for the AI owner.
        run_generator(engine, engine._equip_card("AI2", new_plus))
        self.assertEqual(engine.state.cards[plus_old].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[new_plus].zone_id, "AI2.equipment")
        self.assertEqual(engine.distance("P1", "AI2"), 2)
        self.assertEqual(engine.distance("AI2", "P1"), 2)
        self.assertEqual(engine.distance("AI1", "P1"), other_to_player)
        new_minus = put_hand(engine, "P1", "dayuan")
        submit(engine, ActionIntent("P1", card_id=new_minus))
        self.assertEqual(engine.state.cards[minus_old].zone_id, "discard_pile")
        self.assertEqual(engine.state.cards[new_minus].zone_id, "P1.equipment")
        self.assertEqual(engine.distance("P1", "AI2"), 2)
        assert_card_zone_invariant(engine.state)

    def test_halberd_does_not_expand_nonlast_hand_or_jijiang_provided_kill(self) -> None:
        nonlast = make_engine()
        put_equipment(nonlast, "P1", "halberd")
        first = put_hand(nonlast, "P1", "sha")
        second = put_hand(nonlast, "P1", "shan")
        requests = []
        submit(nonlast, action(nonlast, kind_id="sha", target_id="AI1", card_id=first),
               lambda request: (requests.append(request.kind) or "pass"))
        self.assertNotIn("halberd_targets", requests)
        self.assertEqual(nonlast.state.cards[second].zone_id, "P1.hand")

        jijiang = make_engine("five_player_identity", hero_id="liubei",
                              identity=Identity.LORD)
        put_equipment(jijiang, "P1", "halberd")
        set_hero(jijiang, "AI1", "guanyu")
        for card_id in tuple(jijiang._zone("P1.hand").card_ids):
            jijiang._discard_card(card_id)
        for card_id in tuple(jijiang._zone("AI1.hand").card_ids):
            jijiang._discard_card(card_id)
        provided = put_hand(jijiang, "AI1", "sha")
        intent = ActionIntent("P1", skill_id="jijiang", target_ids=("AI2",))
        self.assertTrue(jijiang.is_legal_intent(intent))
        jijiang.ai = RouteAI(lambda _view, request:
                             "provide:card:" + provided if request.kind == "jijiang" else None)
        prompts = []
        submit(jijiang, intent,
               lambda request: (prompts.append(request.kind) or "pass"))
        self.assertNotIn("halberd_targets", prompts)
        self.assertEqual(jijiang.state.cards[provided].zone_id, "discard_pile")

    def test_ganglie_can_be_declined_without_judgment_or_source_effect(self) -> None:
        engine = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        set_hero(engine, "AI1", "xiahoudun")
        p1_hp = engine._player("P1").hp
        xiahou_hp = engine._player("AI1").hp
        draw = engine._zone("draw_pile").card_ids
        top_before = draw[0]

        engine._drive(engine._damage("P1", "AI1", 1, None, damage_kind="测试"))
        self.assertEqual(engine.pending_request.kind, "ganglie_trigger")
        self.assertEqual(engine.pending_request.player_id, "AI1")
        engine.answer_prompt("pass")

        self.assertEqual(engine._player("AI1").hp, xiahou_hp - 1)
        self.assertEqual(engine._player("P1").hp, p1_hp)
        self.assertEqual(engine._zone("draw_pile").card_ids[0], top_before)
        self.assertFalse(any("进行刚烈判定" in log.text for log in engine.logs))
        self.assertIsNone(engine.pending_request)
        assert_card_zone_invariant(engine.state)

    def test_ganglie_with_black_judgment_forces_source_with_fewer_than_two_cards(self) -> None:
        engine = make_engine(human_player_ids=frozenset({"P1", "AI1"}))
        set_hero(engine, "AI1", "xiahoudun")
        engine._player("P1").hp = 4
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        draw = engine._zone("draw_pile").card_ids
        black = next(card_id for card_id in draw if engine._color(card_id) == "black")
        draw.remove(black)
        draw.insert(0, black)
        xiahou_hp = engine._player("AI1").hp

        engine._drive(engine._damage("P1", "AI1", 1, None, damage_kind="测试"))
        self.assertEqual(engine.pending_request.kind, "ganglie_trigger")
        engine.answer_prompt("yes")

        self.assertIsNone(engine.pending_request)
        self.assertEqual(engine._player("AI1").hp, xiahou_hp - 1)
        self.assertEqual(engine._player("P1").hp, 3)
        self.assertTrue(any("手牌不足两张，受到刚烈伤害" in log.text for log in engine.logs))
        self.assertEqual(engine._zone("resolving").card_ids, [])
        assert_card_zone_invariant(engine.state)

    def test_fangtian_locked_targets_continue_after_user_death_when_game_is_live(self) -> None:
        engine = make_engine("five_player_identity", hero_id="caocao",
                             identity=Identity.TURNCOAT)
        roles = {"P1": "turncoat", "AI1": "lord", "AI2": "loyalist",
                 "AI3": "rebel", "AI4": "rebel"}
        for player_id, identity in roles.items():
            engine._player(player_id).identity = identity
        set_hero(engine, "AI1", "xiahoudun")
        engine._player("AI1").hp = 3
        engine._player("P1").hp = 1
        for player in engine.state.players:
            for card_id in tuple(engine._zone(player.hand_zone_id).card_ids):
                if engine._definition(card_id).name == "桃":
                    engine._discard_card(card_id)
        for card_id in tuple(engine._zone("P1.hand").card_ids):
            engine._discard_card(card_id)
        slash = put_hand(engine, "P1", "sha")
        draw = engine._zone("draw_pile").card_ids
        black = next(card_id for card_id in draw
                     if engine._color(card_id) == "black")
        draw.remove(black)
        draw.insert(0, black)
        put_equipment(engine, "P1", "halberd")
        p1_damage = []
        engine.ai = RouteAI(lambda _view, request:
                            (p1_damage.append(request.kind) or "yes"
                             if request.kind == "ganglie_trigger" else
                             (p1_damage.append(request.kind) or "damage"
                              if request.kind == "ganglie" else None)))

        submit(engine, action(engine, kind_id="sha", target_id="AI1", card_id=slash),
               lambda request: tuple(option.choice_id for option in request.options
                                     if option.category == "target"
                                     and option.value in {"AI3", "AI4"})
               if request.kind == "halberd_targets" else "pass")

        self.assertFalse(engine._player("P1").alive)
        self.assertIsNone(engine.state.result)
        kill_damage_order = [player.player_id for log in engine.logs
                             for player in engine.state.players
                             if log.text.startswith(f"{engine._hero_name(player)}受到")
                             and "杀伤害" in log.text]
        self.assertEqual(kill_damage_order, ["AI1", "AI3", "AI4"])
        self.assertEqual(engine.state.cards[slash].zone_id, "discard_pile")
        self.assertEqual(engine._zone("resolving").card_ids, [])
        assert_card_zone_invariant(engine.state)


if __name__ == "__main__":
    unittest.main()
