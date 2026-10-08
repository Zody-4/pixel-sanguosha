"""Legacy knowledge inventory; live tutorial entries now use guided practice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TutorialStep:
    title: str
    prompt: str
    choices: tuple[str, ...]
    answer_index: int
    feedback: str
    coverage_tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class TutorialLesson:
    lesson_id: str
    title: str
    steps: tuple[TutorialStep, ...]


TUTORIALS: tuple[TutorialLesson, ...] = (
    TutorialLesson("basic", "基础操作", (
        TutorialStep("选牌、选目标与确认", "使用手牌指定目标时，确认前要做什么？",
                     ("选择手牌和合法目标，检查后确认", "点击目标就立即结算", "不检查目标直接确认"), 0,
                     "先选择手牌和合法目标，检查当前条件，再明确确认；点目标本身不会立即结算。",
                     frozenset({"card_selection", "target_selection", "confirm"})),
        TutorialStep("取消当前选择", "尚未确认结算时，想撤回当前选择应怎么做？",
                     ("取消当前选择，再重新选择", "立刻结束整局", "已选的牌自动弃置"), 0,
                     "确认前可取消当前步骤并调整选择；没有牌或体力等代价会提前支付。",
                     frozenset({"cancel"})),
        TutorialStep("杀与闪", "你成为【杀】的合法目标时，通常如何避免伤害？",
                     ("使用或打出【闪】", "再使用一张【杀】", "结束自己的回合"), 0,
                     "【闪】用于响应【杀】；没有合法闪时继续结算杀的效果。",
                     frozenset({"sha", "shan"})),
        TutorialStep("桃", "【桃】有哪些常见使用时机？",
                     ("出牌阶段救治受伤的自己；濒死时响应救人", "只对满体力角色使用", "用来取消【杀】"), 0,
                     "出牌阶段可对受伤的自己使用【桃】；濒死时，合法响应者也可对濒死角色使用【桃】。",
                     frozenset({"tao"})),
        TutorialStep("结束出牌阶段", "完成出牌后，怎样进入后续阶段？",
                     ("明确结束出牌阶段，再按规则弃牌", "点击任意角色结束", "系统随机弃牌"), 0,
                     "点击结束出牌阶段后进入后续阶段；弃牌数量按手牌上限计算，有合法选择时由玩家选择。",
                     frozenset({"end_phase"})),
    )),
    TutorialLesson("advanced", "进阶规则", (
        TutorialStep("距离", "普通【杀】指定目标时，先检查什么？",
                     ("目标是否在攻击范围内", "目标手牌是否比自己多", "本局是否已经过三回合"), 0,
                     "目标资格包括距离和攻击范围；装备和技能可能改变距离，例如马术影响自己的对外距离。",
                     frozenset({"distance"})),
        TutorialStep("装备", "装备武器后，武器效果何时适用？",
                     ("按该武器说明检查对应时机", "所有武器都让杀造成2点伤害", "只在回合结束时"), 0,
                     "不同装备的效果和生效时机不同；先看装备说明，也可在卡牌录查同一份正式定义。",
                     frozenset({"equipment"})),
        TutorialStep("锦囊", "使用【过河拆桥】前，目标需要满足什么条件？",
                     ("有可操作区域的合法其他角色", "任意角色都可选，即使没有牌", "只能指定自己"), 0,
                     "锦囊也要检查时机与目标资格；【过河拆桥】须指定有合法牌区可操作的其他角色，具体区域见卡牌录。",
                     frozenset({"trick"})),
        TutorialStep("判定", "判定牌翻开后、最终生效前，什么情况可能改变结果？",
                     ("鬼才等改判技能可替换判定牌", "任何角色都能随时换牌", "判定牌不会影响后续效果"), 0,
                     "判定牌翻开后、最终生效前，拥有鬼才的角色可按技能说明打出手牌改判；后续看最终判定牌。",
                     frozenset({"judgment"})),
        TutorialStep("濒死", "角色体力降到0或更低时，下一步是什么？",
                     ("进入濒死求桃流程", "立刻判负，不再响应", "直接摸一张牌"), 0,
                     "先处理濒死响应；合法角色可以使用【桃】。恢复到正体力便存活，否则死亡并检查终局。",
                     frozenset({"near_death"})),
        TutorialStep("技能时机", "发动武将技能前，先查看什么？",
                     ("触发时机、条件、代价和合法目标", "技能随时都能发动", "只看角色是否满体力"), 0,
                     "技能有各自的触发时机和条件；还要检查代价与合法目标。武将录会显示当前模式不可用的原因。",
                     frozenset({"skill_timing"})),
    )),
    TutorialLesson("modes", "三种模式", (
        TutorialStep("斗将：1v1目标", "斗将模式怎样获胜？",
                     ("击败唯一对手", "保护主公并清除反贼", "击败两名对手"), 0,
                     "斗将是双方各一名武将的1v1；击败唯一对手获胜，不使用身份牌。",
                     frozenset({"duel_goal"})),
        TutorialStep("斗将：特殊规则", "斗将的随机先手第一回合摸几张牌？",
                     ("一张", "两张", "四张"), 0,
                     "先手随机；先手第一回合只摸一张，之后正常摸牌。没有主公身份，所以主公技不可用。",
                     frozenset({"duel_special"})),
        TutorialStep("力敌双雄：1v2目标", "玩家如何赢得力敌双雄？",
                     ("击败两个同阵营对手", "击败其中一名即可", "等主公阵亡"), 0,
                     "玩家独自对抗两名彼此同阵营的电脑角色；击败两人获胜，玩家先行动。",
                     frozenset({"two_heroes_goal"})),
        TutorialStep("力敌双雄：特殊规则", "此模式给玩家的开局补偿是什么？",
                     ("当前与上限体力各加1，起始手牌多1张", "每回合多摸1张", "电脑角色互相敌对"), 0,
                     "玩家当前与上限体力各加1，起始手牌多1张；每回合摸牌数不增加，两个电脑角色属于同一对手阵营。",
                     frozenset({"two_heroes_special"})),
        TutorialStep("五人身份局：身份与目标", "身份局包含哪些身份；主公和忠臣如何获胜？",
                     ("1主公、1忠臣、2反贼、1内奸；消灭全部反贼与内奸", "三主公、两反贼；只要存活", "势力等于身份"), 0,
                     "身份数量为一主公、一忠臣、两反贼、一内奸。主公与忠臣须消灭全部反贼和内奸；反贼以主公死亡为胜。主公死亡时若内奸是唯一存活者，则内奸获胜。",
                     frozenset({"identity_roles", "identity_goals"})),
        TutorialStep("五人身份局：保密与特殊规则", "五人局中哪些信息公开？",
                     ("武将公开；自己身份和主公身份可见；其他存活身份保密", "所有身份开局公开", "武将也全部保密"), 0,
                     "座次随机、主公先行动且增加1点体力；自己的身份可见，主公身份公开，其他存活者身份保密，死亡角色按规则公开。击杀反贼摸三张；主公误杀忠臣须弃全部手牌和装备。",
                     frozenset({"identity_privacy", "identity_special"})),
    )),
)

TUTORIAL_BY_ID = {lesson.lesson_id: lesson for lesson in TUTORIALS}
