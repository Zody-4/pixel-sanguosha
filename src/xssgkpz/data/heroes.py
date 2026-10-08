"""Canonical hero and skill definitions from the project rules appendix."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Faction(StrEnum):
    WEI = "魏"
    SHU = "蜀"
    WU = "吴"
    QUN = "群"


class Gender(StrEnum):
    MALE = "男性"
    FEMALE = "女性"


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    skill_id: str
    hero_id: str
    name: str
    description: str
    is_lord_skill: bool
    text_key: str


@dataclass(frozen=True, slots=True)
class HeroDefinition:
    hero_id: str
    name: str
    faction: Faction
    gender: Gender
    base_hp: int
    skill_ids: tuple[str, ...]
    asset_key: str


_heroes: list[HeroDefinition] = []
_skills: list[SkillDefinition] = []


def _hero(
    hero_id: str,
    name: str,
    faction: Faction,
    gender: Gender,
    base_hp: int,
    skills: tuple[tuple[str, str, str, bool], ...],
) -> None:
    skill_ids = tuple(f"{hero_id}.{skill_id}" for skill_id, *_ in skills)
    _heroes.append(HeroDefinition(
        hero_id=hero_id, name=name, faction=faction, gender=gender,
        base_hp=base_hp, skill_ids=skill_ids, asset_key=f"heroes.{hero_id}",
    ))
    for skill_id, skill_name, description, is_lord_skill in skills:
        full_id = f"{hero_id}.{skill_id}"
        _skills.append(SkillDefinition(
            skill_id=full_id, hero_id=hero_id, name=skill_name,
            description=description, is_lord_skill=is_lord_skill,
            text_key=f"skills.{full_id}.description",
        ))


_hero("caocao", "曹操", Faction.WEI, Gender.MALE, 4, (
    ("jianxiong", "奸雄", "每次受到由牌造成的伤害并在濒死流程后存活时，可获得仍处于本次结算中的伤害牌；无对应实体牌或牌已离开结算区域时不能获得。", False),
    ("hujia", "护驾", "需要使用或打出闪时，可令其他魏势力角色按行动顺序依次选择是否提供一张合法闪；首个成功提供者结束询问，该闪视为曹操使用或打出。", True),
))
_hero("simayi", "司马懿", Faction.WEI, Gender.MALE, 3, (
    ("fankui", "反馈", "每次受到一次伤害并存活后，可获得伤害来源的一张手牌或装备；隐藏手牌随机取得。一次多点伤害只发动一次。", False),
    ("guicai", "鬼才", "任意角色判定牌翻开后、最终生效前，可打出一张手牌替换；被替换牌进入弃牌堆，替换牌成为最终判定牌。", False),
))
_hero("xiahoudun", "夏侯惇", Faction.WEI, Gender.MALE, 4, (
    ("ganglie", "刚烈", "每次受到一次伤害并存活后，可判定；最终结果不是红桃时，伤害来源选择同时弃两张手牌，否则受到夏侯惇造成的1点伤害。来源不足两张手牌时只能受伤。", False),
))
_hero("zhangliao", "张辽", Faction.WEI, Gender.MALE, 4, (
    ("tuxi", "突袭", "摸牌阶段开始前，可完全放弃正常摸牌，改为选择一至两名有手牌的其他角色，并从每名目标随机获得一张手牌；必须先选完目标再依次取牌。", False),
))
_hero("xuchu", "许褚", Faction.WEI, Gender.MALE, 4, (
    ("luoyi", "裸衣", "摸牌阶段开始前，可令本阶段少摸一张；若如此做，本回合出牌阶段内由许褚使用的杀，或以许褚为伤害来源的决斗，造成伤害时伤害值＋1。", False),
))
_hero("guojia", "郭嘉", Faction.WEI, Gender.MALE, 3, (
    ("tiandu", "天妒", "自己的判定牌最终生效后，可获得该判定牌。", False),
    ("yiji", "遗计", "每受到1点伤害并在濒死流程后存活，可摸两张牌，再分别将这两张牌交给任意角色；可给同一角色，也可保留给自己。多点伤害逐点处理。", False),
))
_hero("zhenji", "甄姬", Faction.WEI, Gender.FEMALE, 3, (
    ("qingguo", "倾国", "可将一张黑色手牌当闪使用或打出；装备区牌不能用于倾国。", False),
    ("luoshen", "洛神", "回合开始阶段可判定；黑色则获得最终判定牌，并可再次判定；红色或主动停止时结束。", False),
))

_hero("liubei", "刘备", Faction.SHU, Gender.MALE, 4, (
    ("rende", "仁德", "出牌阶段可分次将任意张手牌交给其他角色；本阶段累计首次达到两张时立即回复1点体力。即使当时满体力导致没有实际回复，本阶段之后也不再次触发回复。", False),
    ("jijiang", "激将", "需要使用或打出杀时，可令其他蜀势力角色按行动顺序依次选择是否提供一张合法杀；首个成功提供者结束询问，该杀视为刘备使用或打出，伤害来源与奖惩归刘备。", True),
))
_hero("guanyu", "关羽", Faction.SHU, Gender.MALE, 4, (
    ("wusheng", "武圣", "可将一张红色手牌或装备区牌当杀使用或打出；若转换装备会使该杀不再满足发动前条件，则不能用该装备完成此次转换。", False),
))
_hero("zhangfei", "张飞", Faction.SHU, Gender.MALE, 4, (
    ("paoxiao", "咆哮", "出牌阶段使用杀没有次数限制；距离、目标和其他限制不变。", False),
))
_hero("zhugeliang", "诸葛亮", Faction.SHU, Gender.MALE, 3, (
    ("guanxing", "观星", "回合开始阶段可查看牌堆顶X张牌，X为存活角色数与5中的较小值；将任意张按自定顺序置于牌堆顶，其余按自定顺序置于牌堆底。", False),
    ("kongcheng", "空城", "锁定效果；没有手牌时不能成为杀或决斗的目标。已经合法成为目标后才失去最后手牌，不撤销既有目标。", False),
))
_hero("zhaoyun", "赵云", Faction.SHU, Gender.MALE, 4, (
    ("longdan", "龙胆", "可将手牌中的杀当闪、闪当杀使用或打出；不能借此把八卦阵产生的虚拟闪再转成杀。", False),
))
_hero("machao", "马超", Faction.SHU, Gender.MALE, 4, (
    ("mashu", "马术", "锁定效果；计算自己到其他角色的距离时－1。", False),
    ("tieji", "铁骑", "使用杀指定一名目标后，可为该目标判定；最终结果为红色时，该目标不能以闪响应此杀。此效果不会令原本因仁王盾而无效的黑色杀恢复有效。", False),
))
_hero("huangyueying", "黄月英", Faction.SHU, Gender.FEMALE, 3, (
    ("jizhi", "集智", "每使用一张非延时锦囊，在该锦囊开始结算前可摸一张牌。", False),
    ("qicai", "奇才", "锁定效果；使用锦囊不受距离限制，但仍须满足目标、区域和其他条件。", False),
))

_hero("sunquan", "孙权", Faction.WU, Gender.MALE, 4, (
    ("zhiheng", "制衡", "每个出牌阶段限一次，可弃任意张手牌和／或装备，再摸等量牌；至少须弃一张。", False),
    ("jiuyuan", "救援", "锁定效果；其他吴势力角色在孙权濒死时对其使用桃，孙权在该桃原有回复外额外回复1点体力。", True),
))
_hero("ganning", "甘宁", Faction.WU, Gender.MALE, 4, (
    ("qixi", "奇袭", "出牌阶段可将一张黑色手牌或装备区牌当过河拆桥使用；转换后按过河拆桥接受无懈响应。", False),
))
_hero("lvmeng", "吕蒙", Faction.WU, Gender.MALE, 4, (
    ("keji", "克己", "若本回合出牌阶段没有使用或打出过杀，可跳过弃牌阶段；自己发起决斗并在出牌阶段打出杀也会破坏克己条件。", False),
))
_hero("huanggai", "黄盖", Faction.WU, Gender.MALE, 4, (
    ("kurou", "苦肉", "出牌阶段可失去1点体力；若进入濒死，先完整处理濒死，存活后再摸两张牌。每个出牌阶段可多次发动。", False),
))
_hero("zhouyu", "周瑜", Faction.WU, Gender.MALE, 3, (
    ("yingzi", "英姿", "摸牌阶段可额外摸一张牌。", False),
    ("fanjian", "反间", "每个出牌阶段限一次，指定一名其他角色；目标先选一种花色，再随机抽取并展示周瑜一张手牌，将其移入专用结算区。若花色不符，先受到周瑜造成的1点伤害；目标存活后才最终获得该牌，目标死亡则牌退回周瑜手中。结算完成前任何角色均不能使用、弃置或取得该牌。", False),
))
_hero("daqiao", "大乔", Faction.WU, Gender.FEMALE, 3, (
    ("guose", "国色", "出牌阶段可将一张方块手牌或装备区牌当乐不思蜀使用。", False),
    ("liuli", "流离", "成为杀的目标时、进入闪或八卦响应之前，可弃一张手牌或装备，将此杀转移给大乔此时攻击范围内的另一名合法角色；不能转回杀的使用者，支付装备后按支付后的范围检查转移目标。", False),
))
_hero("luxun", "陆逊", Faction.WU, Gender.MALE, 3, (
    ("qianxun", "谦逊", "锁定效果；不能成为顺手牵羊或乐不思蜀的目标。", False),
    ("lianying", "连营", "每当失去最后一张手牌时，可立即摸一张牌。要求同时支付多张牌的代价不能用中途连营补足；依次响应则可在两次响应间正常触发。", False),
))
_hero("sunshangxiang", "孙尚香", Faction.WU, Gender.FEMALE, 3, (
    ("jieyin", "结姻", "每个出牌阶段限一次，弃两张手牌并选择一名受伤男性角色；孙尚香和目标各回复1点体力。只有男性目标必须处于受伤状态；孙尚香满体力不妨碍发动，但她自己的回复不产生实际变化。不能在没有受伤男性目标时只治疗自己。", False),
    ("xiaoji", "枭姬", "每失去装备区里的一张牌后，可摸两张牌；弃置手牌中的装备牌不触发。角色死亡清理装备时不触发普通存活技能。", False),
))

_hero("huatuo", "华佗", Faction.QUN, Gender.MALE, 3, (
    ("jijiu", "急救", "自己的回合外，可将一张红色手牌或装备区牌当桃使用；自己的回合内即使濒死也不能发动。", False),
    ("qingnang", "青囊", "每个出牌阶段限一次，弃一张手牌并令一名受伤角色回复1点体力；可以选择自己。", False),
))
_hero("lvbu", "吕布", Faction.QUN, Gender.MALE, 4, (
    ("wushuang", "无双", "锁定效果；吕布使用杀时，目标须连续提供两张闪才抵消；与吕布进行决斗的另一方每轮须连续打出两张杀。只提供一张时该牌已被使用但整组响应失败。", False),
))
_hero("diaochan", "貂蝉", Faction.QUN, Gender.FEMALE, 3, (
    ("lijian", "离间", "每个出牌阶段限一次，弃一张手牌或装备并选择两名男性角色；指定其中一人为决斗发起方，视为其对另一人使用决斗。此决斗不能被无懈可击响应。", False),
    ("biyue", "闭月", "回合结束阶段可摸一张牌；必须先完成弃牌阶段，不能用预期的闭月摸牌减少弃牌数。", False),
))


HEROES = tuple(_heroes)
SKILLS = tuple(_skills)
HERO_BY_ID = {hero.hero_id: hero for hero in HEROES}
HERO_BY_NAME = {hero.name: hero for hero in HEROES}
SKILL_BY_ID = {skill.skill_id: skill for skill in SKILLS}

