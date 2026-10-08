from __future__ import annotations

import unittest
from collections import Counter

from _support import PROJECT_ROOT
from xssgkpz.data.assets import ASSET_BY_KEY
from xssgkpz.data.cards import CARD_DEFINITIONS, CARD_KINDS, CardCategory, Edition, Suit
from xssgkpz.data.heroes import Faction, Gender, HEROES, SKILLS
from xssgkpz.data.modes import DIFFICULTIES, MODE_BY_ID, MODES, Difficulty, HeroSelectionMethod, Identity
from xssgkpz.data.settings import AiDisplaySpeed, Settings, SkillAnimation, WindowMode
from xssgkpz.data.traceability import DECISION_TRACE_BY_ID


EXPECTED_CARD_SHEET = {
    Suit.SPADES: {
        "A": ("闪电", "决斗", None), "2": ("八卦阵", "雌雄双股剑", "寒冰剑"),
        "3": ("过河拆桥", "顺手牵羊", None), "4": ("过河拆桥", "顺手牵羊", None),
        "5": ("青龙偃月刀", "绝影", None), "6": ("乐不思蜀", "青釭剑", None),
        "7": ("南蛮入侵", "杀", None), "8": ("杀", "杀", None), "9": ("杀", "杀", None),
        "10": ("杀", "杀", None), "J": ("无懈可击", "顺手牵羊", None),
        "Q": ("丈八蛇矛", "过河拆桥", None), "K": ("大宛", "南蛮入侵", None),
    },
    Suit.CLUBS: {
        "A": ("诸葛连弩", "决斗", None), "2": ("八卦阵", "杀", "仁王盾"),
        "3": ("过河拆桥", "杀", None), "4": ("过河拆桥", "杀", None),
        "5": ("的卢", "杀", None), "6": ("乐不思蜀", "杀", None),
        "7": ("南蛮入侵", "杀", None), "8": ("杀", "杀", None), "9": ("杀", "杀", None),
        "10": ("杀", "杀", None), "J": ("杀", "杀", None),
        "Q": ("借刀杀人", "无懈可击", None), "K": ("借刀杀人", "无懈可击", None),
    },
    Suit.HEARTS: {
        "A": ("桃园结义", "万箭齐发", None), "2": ("闪", "闪", None),
        "3": ("桃", "五谷丰登", None), "4": ("桃", "五谷丰登", None),
        "5": ("麒麟弓", "赤兔", None), "6": ("桃", "乐不思蜀", None),
        "7": ("桃", "无中生有", None), "8": ("桃", "无中生有", None),
        "9": ("桃", "无中生有", None), "10": ("杀", "杀", None),
        "J": ("杀", "无中生有", None), "Q": ("桃", "过河拆桥", "闪电"),
        "K": ("爪黄飞电", "闪", None),
    },
    Suit.DIAMONDS: {
        "A": ("诸葛连弩", "决斗", None), "2": ("闪", "闪", None),
        "3": ("闪", "顺手牵羊", None), "4": ("闪", "顺手牵羊", None),
        "5": ("闪", "贯石斧", None), "6": ("闪", "杀", None),
        "7": ("闪", "杀", None), "8": ("闪", "杀", None), "9": ("闪", "杀", None),
        "10": ("闪", "杀", None), "J": ("闪", "闪", None),
        "Q": ("桃", "方天画戟", "无懈可击"), "K": ("杀", "紫骍", None),
    },
}

EXPECTED_HEROES = {
    "曹操": (Faction.WEI, Gender.MALE, 4), "司马懿": (Faction.WEI, Gender.MALE, 3),
    "夏侯惇": (Faction.WEI, Gender.MALE, 4), "张辽": (Faction.WEI, Gender.MALE, 4),
    "许褚": (Faction.WEI, Gender.MALE, 4), "郭嘉": (Faction.WEI, Gender.MALE, 3),
    "甄姬": (Faction.WEI, Gender.FEMALE, 3), "刘备": (Faction.SHU, Gender.MALE, 4),
    "关羽": (Faction.SHU, Gender.MALE, 4), "张飞": (Faction.SHU, Gender.MALE, 4),
    "诸葛亮": (Faction.SHU, Gender.MALE, 3), "赵云": (Faction.SHU, Gender.MALE, 4),
    "马超": (Faction.SHU, Gender.MALE, 4), "黄月英": (Faction.SHU, Gender.FEMALE, 3),
    "孙权": (Faction.WU, Gender.MALE, 4), "甘宁": (Faction.WU, Gender.MALE, 4),
    "吕蒙": (Faction.WU, Gender.MALE, 4), "黄盖": (Faction.WU, Gender.MALE, 4),
    "周瑜": (Faction.WU, Gender.MALE, 3), "大乔": (Faction.WU, Gender.FEMALE, 3),
    "陆逊": (Faction.WU, Gender.MALE, 3), "孙尚香": (Faction.WU, Gender.FEMALE, 3),
    "华佗": (Faction.QUN, Gender.MALE, 3), "吕布": (Faction.QUN, Gender.MALE, 4),
    "貂蝉": (Faction.QUN, Gender.FEMALE, 3),
}

EXPECTED_SKILLS_BY_HERO = {
    "曹操": {"奸雄", "护驾"}, "司马懿": {"反馈", "鬼才"}, "夏侯惇": {"刚烈"},
    "张辽": {"突袭"}, "许褚": {"裸衣"}, "郭嘉": {"天妒", "遗计"},
    "甄姬": {"倾国", "洛神"}, "刘备": {"仁德", "激将"}, "关羽": {"武圣"},
    "张飞": {"咆哮"}, "诸葛亮": {"观星", "空城"}, "赵云": {"龙胆"},
    "马超": {"马术", "铁骑"}, "黄月英": {"集智", "奇才"},
    "孙权": {"制衡", "救援"}, "甘宁": {"奇袭"}, "吕蒙": {"克己"},
    "黄盖": {"苦肉"}, "周瑜": {"英姿", "反间"}, "大乔": {"国色", "流离"},
    "陆逊": {"谦逊", "连营"}, "孙尚香": {"结姻", "枭姬"},
    "华佗": {"急救", "青囊"}, "吕布": {"无双"}, "貂蝉": {"离间", "闭月"},
}


class CardCatalogTests(unittest.TestCase):
    def test_deck_counts_and_every_suit_rank_print_match_rules_appendix(self) -> None:
        self.assertEqual(len(CARD_DEFINITIONS), 108)
        self.assertEqual(len({card.definition_id for card in CARD_DEFINITIONS}), 108)
        self.assertEqual(Counter(card.edition for card in CARD_DEFINITIONS), {Edition.STANDARD: 104, Edition.EX: 4})
        self.assertEqual(Counter(card.category for card in CARD_DEFINITIONS), {
            CardCategory.BASIC: 53, CardCategory.TRICK: 36, CardCategory.EQUIPMENT: 19,
        })
        self.assertEqual(Counter(card.suit for card in CARD_DEFINITIONS), {suit: 27 for suit in Suit})

        for suit, rows in EXPECTED_CARD_SHEET.items():
            for rank, expected in rows.items():
                cards = [card for card in CARD_DEFINITIONS if card.suit is suit and card.rank == rank]
                standard = sorted(
                    (card for card in cards if card.edition is Edition.STANDARD),
                    key=lambda card: card.copy_number,
                )
                ex = [card.name for card in cards if card.edition is Edition.EX]
                self.assertEqual(tuple(card.name for card in standard), expected[:2], f"{suit.value} {rank}")
                self.assertEqual(ex, [expected[2]] if expected[2] else [], f"{suit.value} {rank} EX")
                self.assertEqual({card.point for card in cards}, {standard[0].point})

        self.assertEqual(len(CARD_KINDS), 32)
        for card in CARD_DEFINITIONS:
            self.assertTrue(card.effect_key.startswith("card_effects."))
            self.assertIn(card.asset_key, ASSET_BY_KEY)
            self.assertEqual(card.asset_key, next(kind.asset_key for kind in CARD_KINDS if kind.kind_id == card.kind_id))


class HeroCatalogTests(unittest.TestCase):
    def test_all_25_heroes_and_skill_references_match_rules_appendix(self) -> None:
        self.assertEqual(len(HEROES), 25)
        self.assertEqual(len({hero.hero_id for hero in HEROES}), 25)
        self.assertEqual({hero.name for hero in HEROES}, set(EXPECTED_HEROES))
        for hero in HEROES:
            self.assertEqual((hero.faction, hero.gender, hero.base_hp), EXPECTED_HEROES[hero.name])
            self.assertGreaterEqual(hero.base_hp, 1)
            self.assertIn(hero.asset_key, ASSET_BY_KEY)
            self.assertTrue(hero.skill_ids)
            self.assertEqual(
                {next(skill.name for skill in SKILLS if skill.skill_id == skill_id) for skill_id in hero.skill_ids},
                EXPECTED_SKILLS_BY_HERO[hero.name],
            )
            for skill_id in hero.skill_ids:
                self.assertEqual(next(skill for skill in SKILLS if skill.skill_id == skill_id).hero_id, hero.hero_id)

        self.assertEqual(len(SKILLS), 40)
        self.assertEqual(len({skill.skill_id for skill in SKILLS}), len(SKILLS))
        self.assertEqual({skill.name for skill in SKILLS if skill.is_lord_skill}, {"护驾", "激将", "救援"})
        self.assertTrue(all(skill.description and skill.text_key for skill in SKILLS))

    def test_approved_runtime_art_is_integrated_and_files_exist(self) -> None:
        self.assertTrue(ASSET_BY_KEY)
        hero_assets = {hero.asset_key: ASSET_BY_KEY[hero.asset_key] for hero in HEROES}
        self.assertEqual(len(hero_assets), 25)
        for hero in HEROES:
            asset = hero_assets[hero.asset_key]
            self.assertEqual(asset.status, "integrated")
            self.assertIsNotNone(asset.relative_path)
            self.assertTrue((PROJECT_ROOT / asset.relative_path).is_file())

        card_assets = set(ASSET_BY_KEY) - set(hero_assets)
        self.assertTrue(card_assets)
        for asset_key in card_assets:
            asset = ASSET_BY_KEY[asset_key]
            self.assertIsNotNone(asset.relative_path)
            self.assertIn(asset.status, {"integrated", "integrated_pending_review"})
            self.assertTrue((PROJECT_ROOT / asset.relative_path).is_file())


class SetupDataTests(unittest.TestCase):
    def test_three_modes_and_shared_setup_options_are_declared(self) -> None:
        self.assertEqual(len(MODES), 3)
        duel = MODE_BY_ID["duel"]
        self.assertEqual((duel.player_count, duel.ai_count, duel.starting_hand_sizes), (2, 1, (4, 4)))
        self.assertEqual(duel.opening_actor, "random")
        self.assertEqual(duel.duel_first_turn_draw_count, 1)
        self.assertEqual(duel.initial_seat_distance, 1)
        self.assertFalse(duel.lord_skills_enabled)

        two_heroes = MODE_BY_ID["two_heroes"]
        self.assertEqual((two_heroes.player_count, two_heroes.ai_count), (3, 2))
        self.assertEqual(two_heroes.starting_hand_sizes, (5, 4, 4))
        self.assertEqual((two_heroes.player_current_hp_delta, two_heroes.player_max_hp_delta), (1, 1))
        self.assertEqual(two_heroes.opening_actor, "player")
        self.assertEqual(two_heroes.initial_seat_distance, 1)
        self.assertTrue(two_heroes.public_identity)

        identity_mode = MODE_BY_ID["five_player_identity"]
        self.assertEqual((identity_mode.player_count, identity_mode.ai_count), (5, 4))
        self.assertEqual(sum(count for _, count in identity_mode.identity_counts), 5)
        self.assertTrue(identity_mode.random_seating)
        self.assertEqual(identity_mode.opening_actor, "lord")
        self.assertEqual(identity_mode.starting_hand_sizes, (4, 4, 4, 4, 4))
        self.assertEqual(dict(identity_mode.identity_counts), {
            Identity.LORD: 1, Identity.LOYALIST: 1, Identity.REBEL: 2, Identity.TURNCOAT: 1,
        })
        self.assertEqual((identity_mode.lord_current_hp_delta, identity_mode.lord_max_hp_delta), (1, 1))

        self.assertEqual({item.difficulty for item in DIFFICULTIES}, set(Difficulty))
        self.assertEqual(len(HeroSelectionMethod), 3)

    def test_settings_shape_uses_confirmed_options(self) -> None:
        defaults = Settings()
        self.assertEqual((defaults.resolution_width, defaults.resolution_height), (1280, 720))
        self.assertEqual(defaults.window_mode, WindowMode.WINDOWED)
        self.assertEqual(set(AiDisplaySpeed), {AiDisplaySpeed.NORMAL, AiDisplaySpeed.FAST, AiDisplaySpeed.INSTANT})
        self.assertEqual(set(SkillAnimation), {SkillAnimation.NORMAL, SkillAnimation.FAST, SkillAnimation.OFF})
        self.assertEqual(len(WindowMode), 2)

    def test_decision_trace_landings_include_stage1_automated_evidence(self) -> None:
        self.assertEqual(set(DECISION_TRACE_BY_ID), {"P-01", "R-01", "R-02"})
        matrix = (PROJECT_ROOT / "docs/product/需求规则追踪矩阵.md").read_text(encoding="utf-8")
        for decision_id, trace in DECISION_TRACE_BY_ID.items():
            with self.subTest(decision_id=decision_id):
                self.assertIn(trace.matrix_id, matrix)
                self.assertIn(trace.verification_landing.rsplit(" ", 1)[-1], matrix)
                self.assertIn("自动场景通过", trace.status)
                self.assertIn("真人整局待用户验收", trace.status)


if __name__ == "__main__":
    unittest.main()
