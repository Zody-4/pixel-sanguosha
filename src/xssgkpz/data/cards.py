"""Canonical early-standard 108-card catalog transcribed from the rules appendix."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Suit(StrEnum):
    SPADES = "spades"
    HEARTS = "hearts"
    CLUBS = "clubs"
    DIAMONDS = "diamonds"


class CardCategory(StrEnum):
    BASIC = "basic"
    TRICK = "trick"
    EQUIPMENT = "equipment"


class Edition(StrEnum):
    STANDARD = "standard"
    EX = "EX"


@dataclass(frozen=True, slots=True)
class CardKindDefinition:
    kind_id: str
    name: str
    category: CardCategory
    description: str
    display_summary: str
    asset_key: str
    effect_key: str
    subtype: str | None = None


@dataclass(frozen=True, slots=True)
class CardDefinition:
    definition_id: str
    kind_id: str
    name: str
    category: CardCategory
    suit: Suit
    rank: str
    point: int
    edition: Edition
    copy_number: int
    effect_key: str
    asset_key: str



_CARD_FACE_SUMMARIES: dict[str, str] = {
    "sha": "出牌阶段，选攻击范围内的一名其他角色。对方可打出【闪】抵消，否则受到1点伤害。",
    "shan": "规则要求使用或打出【闪】时响应；通常用于抵消【杀】。",
    "tao": "受伤时可对自己使用并回复1点体力；有人濒死时也可用来救援。",
    "lightning": "置入自己的判定区；判定为黑桃2—9时受到3点伤害，否则传给下一名角色。",
    "indulgence": "置入一名其他角色的判定区；判定非红桃时，其跳过出牌阶段。",
    "duel": "目标先打出【杀】，之后双方轮流打；先不能或不愿继续的一方受到对方1点伤害。",
    "dismantle": "弃置一名其他角色区域内的一张牌。",
    "steal": "获得距离1且有牌的一名其他角色的一张牌。",
    "draw_two": "对自己使用，摸两张牌。",
    "borrow_sword": "令一名持武器角色对其攻击范围内的目标使用【杀】；若拒绝，你获得其武器。",
    "barbarians": "其他角色依次打出【杀】；未打出者受到此牌使用者造成的1点伤害。",
    "arrows": "其他角色依次打出【闪】；未打出者受到此牌使用者造成的1点伤害。",
    "peach_garden": "所有受伤角色依次回复1点体力。",
    "harvest": "亮出与存活人数相同的牌，所有角色依次选择一张。",
    "negate": "锦囊效果生效前使用，抵消它对一名目标的效果。",
    "crossbow": "范围1；装备后，出牌阶段使用【杀】没有次数限制。",
    "double_swords": "范围2；杀指定异性角色后，目标可弃1张手牌，或让你摸1张牌。",
    "qinggang_sword": "范围2；你使用【杀】时，忽略目标的防具。",
    "frost_sword": "范围2；杀将造成伤害时，可防止伤害，改为弃置目标手牌或装备。",
    "qinglong_blade": "范围3；杀被【闪】抵消后，可继续对该杀的实际目标使用【杀】。",
    "serpent_spear": "范围3；需要使用或打出【杀】时，可用两张手牌当一张【杀】。",
    "axe": "范围3；杀被【闪】抵消后，同时弃两张牌，使该杀仍生效。",
    "halberd": "范围4；最后一张手牌当【杀】使用时，可额外指定至多两名合法目标。",
    "kirin_bow": "范围5；【杀】造成伤害时，可弃置目标装备区的一匹坐骑。",
    "bagua_formation": "防具；需要使用或打出【闪】时可判定，红色视为打出无色【闪】。",
    "renwang_shield": "防具；黑色【杀】对装备者无效。",
    "jueying": "+1马；其他角色到你的距离+1。",
    "dilu": "+1马；其他角色到你的距离+1。",
    "zhuahuangfeidian": "+1马；其他角色到你的距离+1。",
    "chitu": "-1马；你到其他角色的距离−1。",
    "dayuan": "-1马；你到其他角色的距离−1。",
    "zixing": "-1马；你到其他角色的距离−1。",
}

def _kind(
    kind_id: str,
    name: str,
    category: CardCategory,
    description: str,
    subtype: str | None = None,
) -> CardKindDefinition:
    return CardKindDefinition(
        kind_id=kind_id,
        name=name,
        category=category,
        description=description,
        display_summary=_CARD_FACE_SUMMARIES[kind_id],
        asset_key=f"cards.{kind_id}",
        effect_key=f"card_effects.{kind_id}",
        subtype=subtype,
    )


CARD_KINDS: tuple[CardKindDefinition, ...] = (
    _kind("sha", "杀", CardCategory.BASIC, "出牌阶段对攻击范围内一名其他角色使用；通常每阶段限一次。目标以一张闪抵消，否则受到来源为杀使用者的1点伤害。"),
    _kind("shan", "闪", CardCategory.BASIC, "只能在规则或效果要求时使用或打出，通常用于抵消一张杀；不能在普通出牌阶段主动使用。"),
    _kind("tao", "桃", CardCategory.BASIC, "出牌阶段可对受伤的自己使用并回复1点体力；角色濒死时，合法响应者可对濒死角色使用。体力不能超过上限，满体力时不能主动使用桃。"),
    _kind("lightning", "闪电", CardCategory.TRICK, "出牌阶段置入自己的判定区。判定阶段若最终结果为黑桃2至9，闪电对该角色造成3点无来源伤害后进入弃牌堆；否则移动到行动顺序下一名合法角色的判定区。闪电效果被无懈抵消时仍向后传递。", "delayed"),
    _kind("indulgence", "乐不思蜀", CardCategory.TRICK, "出牌阶段置入一名其他角色的判定区；其判定阶段判定，若最终结果不是红桃，该角色跳过本回合出牌阶段。结算后乐不思蜀进入弃牌堆。", "delayed"),
    _kind("duel", "决斗", CardCategory.TRICK, "对一名其他角色使用。目标先打出一张杀，然后双方轮流打出杀；首先不能或不愿打出者受到对方造成的1点伤害。决斗开始交替出杀后，不能再以无懈可击取消。", "immediate"),
    _kind("dismantle", "过河拆桥", CardCategory.TRICK, "对一名区域内有牌的其他角色使用；选择其装备区或判定区的一张明牌，或从其隐藏手牌中随机选择一张并弃置。", "immediate"),
    _kind("steal", "顺手牵羊", CardCategory.TRICK, "对距离为1且区域内有牌的其他角色使用；选择其装备区或判定区的一张明牌，或从其隐藏手牌中随机选择一张并获得。", "immediate"),
    _kind("draw_two", "无中生有", CardCategory.TRICK, "对自己使用，摸两张牌。", "immediate"),
    _kind("borrow_sword", "借刀杀人", CardCategory.TRICK, "先选一名装备武器的其他角色为被要求者，再选其攻击范围内另一名合法角色为杀的目标；第二目标可以是锦囊使用者，但不能是被要求者自己。被要求者选择对第二目标使用一张杀；若不如此做，锦囊使用者获得其武器并收入手牌，不立即装备。此杀由被要求者使用并承担伤害来源及击杀奖惩；刘备激将等技能另按自身来源规则处理。", "immediate"),
    _kind("barbarians", "南蛮入侵", CardCategory.TRICK, "按行动顺序逐一结算所有其他角色；每名角色打出一张杀，否则受到锦囊使用者造成的1点伤害。", "immediate"),
    _kind("arrows", "万箭齐发", CardCategory.TRICK, "按行动顺序逐一结算所有其他角色；每名角色打出一张闪，否则受到锦囊使用者造成的1点伤害。", "immediate"),
    _kind("peach_garden", "桃园结义", CardCategory.TRICK, "按行动顺序逐一结算所有角色；每名受伤角色回复1点体力，未受伤者不变化。", "immediate"),
    _kind("harvest", "五谷丰登", CardCategory.TRICK, "亮出等于存活角色数的牌，从使用者开始按行动顺序逐人结算。每名角色取得牌前单独开放此目标的无懈窗口；被无懈者跳过取牌，后续角色从剩余明牌中选择；效果未被抵消的角色不能主动放弃取牌；已取得的无懈可在后续目标的独立窗口中使用；最后弃置未取得的牌。", "immediate"),
    _kind("negate", "无懈可击", CardCategory.TRICK, "在一项锦囊效果生效前使用，抵消该锦囊对当前一名目标的效果；也可响应另一张无懈可击。群体锦囊逐目标询问与结算，一张无懈不取消整组目标。", "immediate"),
    _kind("crossbow", "诸葛连弩", CardCategory.EQUIPMENT, "武器，攻击范围1：出牌阶段使用杀没有次数限制。", "weapon"),
    _kind("double_swords", "雌雄双股剑", CardCategory.EQUIPMENT, "武器，攻击范围2：以杀指定异性角色后，使用者可发动；目标选择弃一张手牌，或令使用者摸一张牌。目标没有手牌时只能令使用者摸牌。", "weapon"),
    _kind("qinggang_sword", "青釭剑", CardCategory.EQUIPMENT, "武器，攻击范围2：杀对目标结算期间忽略其防具效果。", "weapon"),
    _kind("frost_sword", "寒冰剑", CardCategory.EQUIPMENT, "武器，攻击范围2：杀即将对目标造成伤害且目标有手牌或装备时，使用者可防止此伤害，改为依次弃置目标至多两张手牌或装备；隐藏手牌随机选择，不能弃判定区。目标没有合法牌时不能发动；只有一张时弃这一张；能弃两张时不得主动只弃一张。两次弃置间先结算失去牌触发的技能，再判断第二次可弃的牌。", "weapon"),
    _kind("qinglong_blade", "青龙偃月刀", CardCategory.EQUIPMENT, "武器，攻击范围3：杀被目标以闪抵消后，可立即对刚刚抵消这张杀的实际目标再使用一张杀；若新杀再次被闪抵消，可继续重复，直至杀生效或使用者不愿再出杀。连续追杀期间不能插入普通出牌操作。若首杀经流离转移，追杀对象是流离后的实际目标；依C-06，即使该角色超出青龙刀通常范围，仍可进行这次连续追杀。此例外只适用于青龙刀追杀，不推广到普通杀或其他新杀。", "weapon"),
    _kind("serpent_spear", "丈八蛇矛", CardCategory.EQUIPMENT, "武器，攻击范围3：需要使用或打出杀时，可将两张手牌作为一张杀；两张同色时杀继承该颜色，一红一黑时视为无色。", "weapon"),
    _kind("axe", "贯石斧", CardCategory.EQUIPMENT, "武器，攻击范围3：杀被目标以闪抵消时，可同时弃置两张牌，使该杀仍对目标生效；可以弃手牌或其他装备，不能以正在发动的贯石斧本身支付。合法锁定目标后不因弃-1马重新检查距离。", "weapon"),
    _kind("halberd", "方天画戟", CardCategory.EQUIPMENT, "武器，攻击范围4：从手牌使用的杀是使用者最后一张手牌时，可额外指定至多两名合法目标；全部目标按行动顺序结算。若杀是由激将等技能提供且使用者手中/装备区仍有牌，不符合“最后一张手牌”条件；不能把手牌以外的牌或仅视为杀的供牌误算成最后一张手牌。", "weapon"),
    _kind("kirin_bow", "麒麟弓", CardCategory.EQUIPMENT, "武器，攻击范围5：杀对目标造成伤害时，使用者可弃置目标装备区的一匹坐骑；目标有两匹时由使用者选择。", "weapon"),
    _kind("bagua_formation", "八卦阵", CardCategory.EQUIPMENT, "防具：需要使用或打出闪时，可先判定；最终结果为红色则视为使用或打出一张无色闪，黑色则仍可从其他合法来源提供闪。", "armor"),
    _kind("renwang_shield", "仁王盾", CardCategory.EQUIPMENT, "防具：锁定效果；黑色杀对装备者无效。青釭剑忽略此防具。", "armor"),
    _kind("jueying", "绝影", CardCategory.EQUIPMENT, "坐骑，+1马：使其他角色到自己的距离+1。", "horse_plus_one"),
    _kind("dilu", "的卢", CardCategory.EQUIPMENT, "坐骑，+1马：使其他角色到自己的距离+1。", "horse_plus_one"),
    _kind("zhuahuangfeidian", "爪黄飞电", CardCategory.EQUIPMENT, "坐骑，+1马：使其他角色到自己的距离+1。", "horse_plus_one"),
    _kind("chitu", "赤兔", CardCategory.EQUIPMENT, "坐骑，-1马：使自己到其他角色的距离-1。", "horse_minus_one"),
    _kind("dayuan", "大宛", CardCategory.EQUIPMENT, "坐骑，-1马：使自己到其他角色的距离-1。", "horse_minus_one"),
    _kind("zixing", "紫骍", CardCategory.EQUIPMENT, "坐骑，-1马：使自己到其他角色的距离-1。", "horse_minus_one"),
)

CARD_KIND_BY_NAME = {kind.name: kind for kind in CARD_KINDS}

# Each row is the rules appendix's two standard prints and optional EX print.
_CARD_TABLE: dict[Suit, dict[str, tuple[str, str, str | None]]] = {
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

RANK_POINTS = {rank: point for point, rank in enumerate(("A", *map(str, range(2, 11)), "J", "Q", "K"), start=1)}


def _build_card_definitions() -> tuple[CardDefinition, ...]:
    definitions: list[CardDefinition] = []
    for suit in Suit:
        for rank, (first, second, ex_name) in _CARD_TABLE[suit].items():
            for copy_number, name in enumerate((first, second), start=1):
                kind = CARD_KIND_BY_NAME[name]
                definitions.append(CardDefinition(
                    definition_id=f"{suit.value}_{rank}_{Edition.STANDARD.value}_{copy_number}",
                    kind_id=kind.kind_id, name=name, category=kind.category,
                    suit=suit, rank=rank, point=RANK_POINTS[rank],
                    edition=Edition.STANDARD, copy_number=copy_number,
                    effect_key=kind.effect_key, asset_key=kind.asset_key,
                ))
            if ex_name is not None:
                kind = CARD_KIND_BY_NAME[ex_name]
                definitions.append(CardDefinition(
                    definition_id=f"{suit.value}_{rank}_{Edition.EX.value}_1",
                    kind_id=kind.kind_id, name=ex_name, category=kind.category,
                    suit=suit, rank=rank, point=RANK_POINTS[rank],
                    edition=Edition.EX, copy_number=1,
                    effect_key=kind.effect_key, asset_key=kind.asset_key,
                ))
    return tuple(definitions)


CARD_DEFINITIONS = _build_card_definitions()
CARD_BY_ID = {card.definition_id: card for card in CARD_DEFINITIONS}
