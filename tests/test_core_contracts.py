from __future__ import annotations

import unittest

import _support  # adds the formal src/ package to this test process
from xssgkpz.core.deck import create_standard_deck
from xssgkpz.core.observation import make_observation
from xssgkpz.core.random_stream import FixedSeedRandom
from xssgkpz.core.state import (
    CardInstance, ControlType, GamePhase, GameState, PlayerState, Visibility,
    ZoneKind, ZoneState, assert_card_zone_invariant, snapshot_game_state,
)
from xssgkpz.data.settings import AiDisplaySpeed, Settings, SkillAnimation, WindowMode
from xssgkpz.persistence import (
    append_record_summary, clear_record_summaries, load_record_summaries, load_settings,
    new_record_summary, save_settings,
)


def sample_state(seed: int = 7123) -> GameState:
    players = [
        PlayerState("p1", 0, ControlType.HUMAN, "caocao", "lord", True, 4, 4,
                    hand_zone_id="p1.hand", equipment_zone_id="p1.equipment", judgment_zone_id="p1.judgment"),
        PlayerState("p2", 1, ControlType.AI, "simayi", "rebel", False, 3, 3,
                    hand_zone_id="p2.hand", equipment_zone_id="p2.equipment", judgment_zone_id="p2.judgment"),
    ]
    zones = {
        "draw": ZoneState("draw", ZoneKind.DRAW_PILE, card_ids=["future_card"]),
        "discard": ZoneState("discard", ZoneKind.DISCARD_PILE),
        "p1.hand": ZoneState("p1.hand", ZoneKind.HAND, "p1", ["p1_card"]),
        "p1.equipment": ZoneState("p1.equipment", ZoneKind.EQUIPMENT, "p1"),
        "p1.judgment": ZoneState("p1.judgment", ZoneKind.JUDGMENT, "p1"),
        "p2.hand": ZoneState("p2.hand", ZoneKind.HAND, "p2", ["p2_card"]),
        "p2.equipment": ZoneState("p2.equipment", ZoneKind.EQUIPMENT, "p2"),
        "p2.judgment": ZoneState("p2.judgment", ZoneKind.JUDGMENT, "p2"),
    }
    cards = {
        card_id: CardInstance(card_id, card_id, zone_id, owner_id=owner, visibility=visibility)
        for card_id, zone_id, owner, visibility in (
            ("future_card", "draw", None, Visibility.HIDDEN),
            ("p1_card", "p1.hand", "p1", Visibility.OWNER_ONLY),
            ("p2_card", "p2.hand", "p2", Visibility.OWNER_ONLY),
        )
    }
    state = GameState("five_player_identity", players, cards, zones, FixedSeedRandom(seed),
                      phase=GamePhase.PLAY, current_player_id="p1", turn_number=1)
    assert_card_zone_invariant(state)
    return state


class DeterministicRandomTests(unittest.TestCase):
    def test_same_seed_reproduces_shuffle_and_checkpoint(self) -> None:
        original = list(range(108))
        first = original.copy()
        second = original.copy()
        stream_a = FixedSeedRandom(0x12345678)
        stream_b = FixedSeedRandom(0x12345678)
        stream_a.shuffle(first)
        stream_b.shuffle(second)
        self.assertEqual(first, second)

        checkpoint = stream_a.snapshot()
        expected = [stream_a.randbelow(13) for _ in range(8)]
        resumed = FixedSeedRandom.restore(checkpoint)
        self.assertEqual([resumed.randbelow(13) for _ in range(8)], expected)
        self.assertNotEqual(first, original)

    def test_standard_deck_has_108_unique_instances_and_seeded_order(self) -> None:
        cards_a, pile_a = create_standard_deck(FixedSeedRandom(123))
        cards_b, pile_b = create_standard_deck(FixedSeedRandom(123))
        self.assertEqual(len(cards_a), 108)
        self.assertEqual(len(set(pile_a.card_ids)), 108)
        self.assertEqual(pile_a.card_ids, pile_b.card_ids)
        self.assertEqual(set(cards_a), set(pile_a.card_ids))
        state = GameState("duel", [], cards_a, {pile_a.zone_id: pile_a}, FixedSeedRandom(123))
        assert_card_zone_invariant(state)


class StateAndObservationTests(unittest.TestCase):
    def test_snapshot_is_immutable_and_contains_true_state(self) -> None:
        state = sample_state()
        snapshot = snapshot_game_state(state)
        self.assertEqual(snapshot.players[0].identity, "lord")
        self.assertEqual(snapshot.random_state.seed, 7123)
        self.assertEqual(snapshot.players[0].hp, 4)
        state.players[0].hp = 2
        self.assertEqual(snapshot.players[0].hp, 4)
        with self.assertRaises((AttributeError, TypeError)):
            snapshot.turn_number = 8

    def test_observation_hides_other_hands_identity_seed_and_future_order(self) -> None:
        state = sample_state()
        view = make_observation(state, "p1")
        p1, p2 = view.players
        self.assertEqual(p1.identity, "lord")
        self.assertEqual(p1.own_hand_card_ids, ("p1_card",))
        self.assertIsNone(p2.identity)
        self.assertEqual(p2.hand_count, 1)
        self.assertIsNone(p2.own_hand_card_ids)
        self.assertEqual(view.draw_pile_count, 1)
        self.assertNotIn("future_card", repr(view))
        self.assertNotIn("7123", repr(view))
        self.assertNotIn("random_stream", view.__dataclass_fields__)

    def test_public_identity_setting_and_death_visibility_are_projected(self) -> None:
        state = sample_state()
        state.players[1].identity_public = True
        self.assertEqual(make_observation(state, "p1").players[1].identity, "rebel")
        state.players[1].identity_public = False
        state.players[1].alive = False
        self.assertEqual(make_observation(state, "p1").players[1].identity, "rebel")

    def test_duplicate_or_missing_zone_reference_fails(self) -> None:
        state = sample_state()
        state.zones["discard"].card_ids.append("p1_card")
        with self.assertRaises(ValueError):
            assert_card_zone_invariant(state)


class PersistenceTests(unittest.TestCase):
    def test_settings_round_trip_and_unknown_fields_are_ignored(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            chosen = Settings(
                window_mode=WindowMode.BORDERLESS_FULLSCREEN,
                resolution_width=1600, resolution_height=900, ui_scale=1.25,
                ai_display_speed=AiDisplaySpeed.FAST,
                skill_animation=SkillAnimation.OFF,
            )
            save_settings(chosen, target)
            self.assertEqual(load_settings(target), chosen)
            payload = target.read_text(encoding="utf-8").replace('"schema_version": 1', '"schema_version": 1,\n  "future_field": "ignored"')
            target.write_text(payload, encoding="utf-8")
            self.assertEqual(load_settings(target), chosen)

    def test_corrupt_settings_are_isolated_before_defaults_are_used(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            target.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_settings(target), Settings())
            self.assertFalse(target.exists())
            self.assertEqual(len(list(Path(folder).glob("settings.json.corrupt-*"))), 1)

    def test_battle_records_are_append_only_summaries(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as folder:
            target = Path(folder) / "records.jsonl"
            first = new_record_summary(
                record_id="one", mode_id="duel", difficulty="medium",
                player_hero_id="caocao", player_identity=None,
                result="win", end_reason="normal", turn_count=4,
            )
            second = new_record_summary(
                record_id="two", mode_id="duel", difficulty="simple",
                player_hero_id="guanyu", player_identity=None,
                result="loss", end_reason="resigned", turn_count=2,
            )
            append_record_summary(first, target)
            append_record_summary(second, target)
            loaded = load_record_summaries(target)
            self.assertEqual(loaded, (first, second))
            content = target.read_text(encoding="utf-8")
            self.assertNotIn("hand", content)
            self.assertNotIn("identity_of_other_players", content)

    def test_clearing_records_preserves_settings_and_uses_explicit_paths(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as folder:
            root = Path(folder)
            settings_target = root / "settings.json"
            records_target = root / "records.jsonl"
            chosen = Settings(ui_scale=1.15)
            save_settings(chosen, settings_target)
            append_record_summary(new_record_summary(
                record_id="clear-test", mode_id="duel", difficulty="simple",
                player_hero_id="caocao", player_identity=None,
                result="win", end_reason="victory", turn_count=3,
            ), records_target)
            clear_record_summaries(records_target)
            self.assertEqual(load_record_summaries(records_target), ())
            self.assertEqual(load_settings(settings_target), chosen)


if __name__ == "__main__":
    unittest.main()
