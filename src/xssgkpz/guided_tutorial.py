"""Isolated practice fixtures and guidance; all effects use the real engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xssgkpz.core.actions import DecisionRequest, GameAction
from xssgkpz.core.ai import SimpleAI
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import MatchRoster, create_match
from xssgkpz.core.state import Visibility, assert_card_zone_invariant
from xssgkpz.data.cards import CARD_BY_ID, Suit
from xssgkpz.data.modes import Difficulty


@dataclass(frozen=True)
class PracticeStep:
    title: str
    instruction: str
    scene: str


BASIC_STEPS = (
    PracticeStep("选择杀", "点击高亮的【杀】。选牌只表示意图，此时不会扣牌。", "attack"),
    PracticeStep("选择目标", "点击对手关羽，将他选为杀的目标。", "attack"),
    PracticeStep("撤回目标", "点击“取消”，先撤回目标；杀仍然保持选中。", "attack"),
    PracticeStep("撤回选牌", "再点击“取消”，撤回选牌。确认前可以重新选择。", "attack"),
    PracticeStep("重新选牌", "重新点击高亮的【杀】。牌没有因为取消而消耗。", "attack"),
    PracticeStep("重新选目标", "再次点击关羽。检查好目标后再提交。", "attack"),
    PracticeStep("确认出杀", "点击“出牌”，观察杀的真实结算和对手体力变化。", "attack"),
    PracticeStep("响应闪", "关羽对你出杀。点击高亮的【闪】，再点“确认响应”。", "flash"),
    PracticeStep("桃恢复体力", "你已受伤。选中高亮的【桃】，点击“出牌”恢复体力。", "heal"),
    PracticeStep("濒死求桃", "观察体力降至0。进入求桃窗口后选【桃】，再确认救援。", "rescue"),
    PracticeStep("结束出牌", "点击“结束阶段”。手牌超过当前体力时，进入弃牌阶段。", "discard"),
    PracticeStep("选择弃牌", "点击一张想弃置的手牌，再点“确认响应”。数量由规则决定。", "discard"),
)


class PracticeOpponent(SimpleAI):
    """One scripted legal attack, otherwise pass; never receives hidden state."""

    def __init__(self, attack: bool) -> None:
        super().__init__()
        self.attack = attack
        self.used = False

    def choose_action(self, view: Any, actions: tuple[GameAction, ...]) -> GameAction | None:
        if self.attack and not self.used:
            action = next((a for a in actions if a.action_id.startswith("play:kill:")
                           and a.intent.target_ids == ("P1",)), None)
            if action:
                self.used = True
                return action
        return None

    def choose_option(self, view: Any, request: DecisionRequest) -> str | tuple[str, ...]:
        if any(o.choice_id == "pass" for o in request.options):
            return "pass"
        return super().choose_option(view, request)


class GuidedTutorial:
    """A small state machine layered over the ordinary battle controls."""

    steps = BASIC_STEPS
    title = "基础操作"

    def __init__(self) -> None:
        self.index = 0
        self.completed = False
        self.message = ""
        self.focus_card: str | None = None
        self.discarded: tuple[str, ...] = ()
        self.initial_hp = 0
        self.target_hp = 0

    @property
    def finished(self) -> bool:
        return self.index >= len(self.steps)

    @property
    def step(self) -> PracticeStep:
        return self.steps[min(self.index, len(self.steps) - 1)]

    def prepare_step(self, engine: GameEngine) -> None:
        """Called when continuing within a fixture; basic steps observe UI directly."""

    def instruction_for(self, app: Any) -> str:
        return self.step.instruction

    def restart_index(self) -> int:
        return next(i for i, step in enumerate(self.steps) if step.scene == self.step.scene)

    def create_scene(self) -> tuple[MatchRoster, GameEngine]:
        scene = self.step.scene
        roster = MatchRoster("duel", Difficulty.SIMPLE, "huanggai", ("huanggai", "guanyu"),
                             (("P1", "opposing_side"), ("AI1", "opposing_side")), 20261003)
        state = create_match(roster)
        # Reset zones only while constructing a new isolated fixture. In-play
        # moves, damage, responses and discards are exclusively engine operations.
        for zone in state.zones.values():
            zone.card_ids.clear()
        for card in state.cards.values():
            card.zone_id = "draw_pile"
            card.owner_id = card.controller_id = None
            card.visibility = Visibility.HIDDEN
        remaining = list(state.cards)

        def deal(player_id: str, names: tuple[str, ...]) -> list[str]:
            dealt = []
            for name in names:
                cid = next(cid for cid in remaining if CARD_BY_ID[state.cards[cid].definition_id].name == name)
                remaining.remove(cid)
                card = state.cards[cid]
                card.zone_id = f"{player_id}.hand"
                card.owner_id = card.controller_id = player_id
                card.visibility = Visibility.OWNER_ONLY
                state.zones[card.zone_id].card_ids.append(cid)
                dealt.append(cid)
            return dealt

        hands = {
            "attack": ("杀", "桃", "闪", "闪"),
            "flash": ("闪", "桃", "杀", "闪"),
            "heal": ("桃", "杀", "闪", "闪"),
            "rescue": ("桃", "桃", "杀", "杀"),
            "discard": ("杀", "桃", "闪", "闪"),
        }
        hand = deal("P1", hands[scene])
        deal("AI1", ("杀", "杀", "桃", "桃"))
        # Subsequent scripted draws are harmless and deterministic, from the
        # actual standard deck, without inventing or duplicating any entity card.
        remaining.sort(key=lambda cid: CARD_BY_ID[state.cards[cid].definition_id].name != "闪")
        state.zones["draw_pile"].card_ids.extend(remaining)
        state.current_player_id = "AI1" if scene in {"flash", "rescue"} else "P1"
        player = next(p for p in state.players if p.player_id == "P1")
        player.hp = player.max_hp - 1 if scene == "heal" else 1 if scene == "rescue" else player.max_hp
        self.focus_card = hand[0]
        self.initial_hp = player.hp
        self.target_hp = next(p.hp for p in state.players if p.player_id == "AI1")
        self.completed = False
        self.message = ""
        self.discarded = ()
        assert_card_zone_invariant(state)
        return roster, GameEngine(state, ai_by_player={"AI1": PracticeOpponent(scene in {"flash", "rescue"})},
                                  display_pacing_enabled=True, presentation_enabled=True)

    def allow(self, app: Any, action: tuple[object, ...]) -> bool:
        name, *args = action
        gameplay = {"battle_card", "battle_target", "battle_skill", "battle_confirm",
                    "battle_option", "battle_pass", "battle_cancel", "end_play", "answer_prompt",
                    "submit_action", "toggle_choice", "clear_choices"}
        if name not in gameplay:
            return True
        if self.finished or self.completed:
            self.message = "本步已完成，请阅读反馈后进入下一练习。"
            return False
        if app.engine.display_waiting:
            self.message = "正在展示真实结算，请稍候。"
            return False
        i = self.index
        allowed = False
        if i in {0, 4}:
            allowed = name == "battle_card" and args == [self.focus_card]
        elif i in {1, 5}:
            allowed = name == "battle_target" and args == ["AI1"]
        elif i in {2, 3}:
            allowed = name == "battle_cancel"
        elif i == 6:
            ready = app.battle_ui.ready_action()
            allowed = (name == "battle_confirm" and ready is not None
                       and ready.intent.card_id == self.focus_card and ready.intent.target_ids == ("AI1",))
        elif i == 8:
            allowed = ((name == "battle_card" and args == [self.focus_card])
                       or name == "battle_cancel"
                       or (name == "battle_confirm" and app.battle_ui.selected_card == self.focus_card))
        elif i in {7, 9, 11}:
            request = app.engine.pending_request
            expected = {7: "flash", 9: "rescue", 11: "discard"}[i]
            if request and request.kind == expected and request.player_id == "P1":
                options = {o.choice_id: o for o in request.options}
                wanted = {o.choice_id for o in request.options
                          if o.category != "pass" and (i == 11 or o.value == self.focus_card)}
                if name == "battle_card" and args:
                    allowed = any(o.value == args[0] for key, o in options.items() if key in wanted)
                elif name in {"battle_option", "toggle_choice"} and args:
                    allowed = args[0] in wanted
                elif name in {"battle_cancel", "clear_choices"}:
                    allowed = True
                elif name == "answer_prompt":
                    allowed = (app.selected_choices <= wanted
                               and request.min_choices <= len(app.selected_choices) <= request.max_choices)
                    if allowed and i == 11:
                        self.discarded = tuple(options[c].value for c in app.selected_choices)
        elif i == 10:
            allowed = name == "end_play" and app.engine.is_human_turn
        if not allowed:
            self.message = "本步练习：" + self.step.instruction
        else:
            self.message = ""
        return allowed

    def observe(self, app: Any, action: str | None = None) -> None:
        if self.finished or self.completed:
            return
        engine, ui = app.engine, app.battle_ui
        if not engine:
            return
        i = self.index
        advance = ((i in {0, 4} and ui.selected_card == self.focus_card)
                   or (i in {1, 5} and ui.targets == ["AI1"])
                   or (i == 2 and action == "battle_cancel" and not ui.targets)
                   or (i == 3 and action == "battle_cancel" and ui.selected_card is None))
        if advance:
            self.index += 1
            self.message = ""
            return
        if i == 10 and engine.pending_request and engine.pending_request.kind == "discard":
            self.index = 11
            self.message = ""
            return
        settled = not engine.display_waiting and not engine.pending_request and engine.is_human_turn
        if not settled:
            return
        player = next(p for p in engine.state.players if p.player_id == "P1")
        spent = self.focus_card and engine.state.cards[self.focus_card].zone_id == "discard_pile"
        success = (i == 6 and spent and next(p.hp for p in engine.state.players if p.player_id == "AI1") == self.target_hp - 1
                   or i == 7 and spent and player.hp == self.initial_hp
                   or i == 8 and spent and player.hp == self.initial_hp + 1
                   or i == 9 and spent and player.alive and player.hp > 0
                   or i == 11 and bool(self.discarded)
                   and all(engine.state.cards[cid].zone_id == "discard_pile" for cid in self.discarded))
        if success:
            self.completed = True
            self.message = {6: "杀已消耗，对手实际失去1点体力。确认后才会结算。",
                            7: "闪已消耗，这次杀被抵消，你没有失去体力。",
                            8: "桃已消耗，你实际恢复了1点体力。",
                            9: "桃救援成功，你从濒死恢复到正体力并存活。",
                            11: "规则要求的弃牌已完成，回合继续推进。基础练习完成。"}[i]

    def next(self) -> bool:
        """Return whether a new fixture is needed; never reset on a plain hint."""
        if not self.completed:
            return False
        self.index += 1
        self.completed = False
        self.message = ""
        return not self.finished


@dataclass(frozen=True)
class RulePracticeStep(PracticeStep):
    goal: str
    card_name: str = ""
    skill_id: str = ""
    request_kind: str = ""
    feedback: str = ""


ADVANCED_STEPS = (
    RulePracticeStep("先看攻击范围", "选中高亮的杀，再点击高亮的远处角色。普通杀的范围为1，距离2的目标不能选中。",
                     "range", "distance", "杀", feedback="目标没有被选中，也没有扣牌：距离2超过当前攻击范围1。"),
    RulePracticeStep("装备武器", "选中青釭剑并出牌。武器进入装备区后，攻击范围才变为2。",
                     "range", "equip", "青釭剑", feedback="青釭剑已进入装备区，攻击范围为2；并非增加杀的伤害。"),
    RulePracticeStep("攻击远处目标", "现在选中杀，点击同一名高亮角色并出牌。观察装备前后的合法目标变化。",
                     "range", "damage", "杀", feedback="距离2的目标现在可以被杀指定，并实际失去1点体力。"),
    RulePracticeStep("拆掉一张装备", "用过河拆桥指定关羽；随后选装备区并确认响应。他只有一张武器，会按规则自动弃置。",
                     "dismantle", "dismantle", "过河拆桥", feedback="目标武器已被弃置。拆桥可操作合法牌区；隐藏手牌只能随机选择。"),
    RulePracticeStep("鬼才改判", "乐不思蜀正在判定。鬼才窗口中选高亮的红桃桃，再确认响应，将最终判定改为红桃。",
                     "judgment", "judgment", "桃", request_kind="guicai",
                     feedback="红桃桃成为最终判定牌；乐不思蜀结算完毕，你正常进入出牌阶段。"),
    RulePracticeStep("救回濒死角色", "等待杀结算到求桃窗口，选高亮的桃并确认救援。体力降至0时先求桃，而非立即死亡。",
                     "rescue", "rescue", "桃", request_kind="rescue",
                     feedback="你从濒死恢复为正体力并存活，原来的杀结算随后继续。"),
    RulePracticeStep("技能时机与代价", "在自己的出牌阶段点击苦肉，再点出牌。观察先失去1点体力、存活后再摸两张牌。",
                     "skill", "skill", skill_id="kurou",
                     feedback="苦肉实际失去1点体力并摸了两张牌。若因此濒死，必须先完成救援再摸牌。"),
)

MODE_STEPS = (
    RulePracticeStep("斗将：击败唯一对手", "这是残局练习。斗将随机先手首回合摸1张，无主公技。用杀击败高亮的关羽，观察胜负。",
                     "duel_goal", "win", "杀", feedback="唯一对手已死亡，正式规则判定你获胜；教学结果不计战绩。"),
    RulePracticeStep("力敌双雄：开局补偿", "你先行动，体力与上限加1，起始手牌5张，每回合摸2张。选诸葛连弩并出牌，准备连续出杀。",
                     "two_goal", "equip", "诸葛连弩", feedback="连弩已装备。同一出牌阶段可以继续使用杀；开局补偿不增加每回合摸牌数。"),
    RulePracticeStep("击败第一名对手", "选高亮的杀，指定关羽并出牌。两名电脑属于同一阵营，击败一人后观察对局是否结束。",
                     "two_goal", "first_enemy", "杀", feedback="第一名对手已死亡，但另一名仍存活，对局继续。"),
    RulePracticeStep("击败第二名对手", "连弩仍生效。再选高亮的杀，指定刘备并出牌，击败第二名对手。",
                     "two_goal", "win", "杀", feedback="两名对手都已死亡，力敌双雄判定你获胜。"),
    RulePracticeStep("身份局：忠臣视角", "你是忠臣，帮助主公清除反贼和内奸。主公公开并先行动；其他存活身份保密。用无中生有补牌。",
                     "identity_view", "draw", "无中生有", feedback="无中生有已摸两张。五人身份为1主公、1忠臣、2反贼、1内奸；提示不泄露隐藏身份。"),
    RulePracticeStep("身份局：击杀后的奖励", "你是主公，体力上限加1。用杀击败高亮角色；他的身份在死亡后公开，再观察手牌变化。",
                     "identity_reward", "reward", "杀", feedback="死者身份公开为反贼。尚未终局，击杀者实际摸了三张奖励牌。"),
    RulePracticeStep("身份局：误杀的代价", "你是主公。这是另一个独立残局，用杀击败高亮的受伤角色，观察身份公开后的真实奖惩。",
                     "identity_penalty", "penalty", "杀", feedback="死者身份公开为忠臣。主公误杀忠臣，实际弃掉了全部手牌和装备。"),
    RulePracticeStep("身份局：反贼目标", "你是反贼。主公身份公开；选杀、指定高亮的主公并出牌。主公死亡时，通常由反贼获胜。",
                     "rebel_goal", "win", "杀", feedback="主公死亡，正式规则判定反贼阵营获胜。"),
    RulePracticeStep("身份局：内奸残局", "你是内奸，残局只剩你和主公。用杀击败主公，成为唯一存活者，观察内奸胜利。",
                     "turncoat_goal", "win", "杀", feedback="主公死亡且内奸是唯一存活者，正式规则判定内奸获胜。三模式练习完成。"),
)


class RuleGuidedTutorial(GuidedTutorial):
    """Rule and mode practice; only the fixture builder writes initial state."""

    def __init__(self, lesson_id: str) -> None:
        super().__init__()
        self.steps = ADVANCED_STEPS if lesson_id == "advanced" else MODE_STEPS
        self.title = "进阶规则" if lesson_id == "advanced" else "三种模式"
        self.target_id = "AI1"
        self.focus_by_name: dict[str, list[str]] = {}
        self.subject_card: str | None = None
        self.delayed_card: str | None = None
        self.submitted = False
        self.attempted_target = False
        self.hand_before = 0

    def create_scene(self) -> tuple[MatchRoster, GameEngine]:
        scene = self.step.scene
        identity = scene == "range" or scene.startswith("identity_") or scene in {"rebel_goal", "turncoat_goal"}
        mode = "five_player_identity" if identity else "two_heroes" if scene == "two_goal" else "duel"
        hero = "simayi" if scene == "judgment" else "huanggai"
        heroes = (hero, "guanyu", "liubei", "lvbu", "ganning")[:5 if identity else 3 if mode == "two_heroes" else 2]
        roles = ("lord", "rebel", "loyalist", "rebel", "turncoat")
        if scene == "identity_view":
            roles = ("loyalist", "lord", "rebel", "rebel", "turncoat")
        elif scene == "identity_penalty":
            roles = ("lord", "loyalist", "rebel", "rebel", "turncoat")
        elif scene == "rebel_goal":
            roles = ("rebel", "lord", "loyalist", "rebel", "turncoat")
        elif scene == "turncoat_goal":
            roles = ("turncoat", "lord", "loyalist", "rebel", "rebel")
        ids = ("P1", *(f"AI{i}" for i in range(1, len(heroes))))
        identities = tuple(zip(ids, roles)) if identity else tuple(
            (pid, "player_side" if pid == "P1" else "ai_side") for pid in ids
        ) if mode == "two_heroes" else tuple((pid, "opposing_side") for pid in ids)
        roster = MatchRoster(mode, Difficulty.SIMPLE, hero, heroes, identities, 20261004)
        state = create_match(roster)
        for zone in state.zones.values():
            zone.card_ids.clear()
        for card in state.cards.values():
            card.zone_id = "draw_pile"
            card.owner_id = card.controller_id = None
            card.visibility = Visibility.HIDDEN
        remaining = list(state.cards)
        self.focus_by_name = {}
        self.subject_card = self.delayed_card = None

        def place(pid: str, name: str, area: str = "hand", suit: Suit | None = None) -> str:
            cid = next(cid for cid in remaining if CARD_BY_ID[state.cards[cid].definition_id].name == name
                       and (suit is None or CARD_BY_ID[state.cards[cid].definition_id].suit is suit))
            remaining.remove(cid)
            card = state.cards[cid]
            card.zone_id = f"{pid}.{area}"
            card.owner_id = card.controller_id = pid
            card.visibility = Visibility.OWNER_ONLY if area == "hand" else Visibility.PUBLIC
            state.zones[card.zone_id].card_ids.append(cid)
            if pid == "P1" and area == "hand":
                self.focus_by_name.setdefault(name, []).append(cid)
            return cid

        names = {"range": ("杀", "青釭剑", "闪", "桃"),
                 "dismantle": ("过河拆桥", "闪", "闪", "桃"),
                 "judgment": ("桃", "闪", "杀", "闪"),
                 "rescue": ("桃", "桃", "杀", "杀"),
                 "skill": ("杀", "闪", "桃", "闪"),
                 "duel_goal": ("杀", "闪", "桃", "闪"),
                 "two_goal": ("诸葛连弩", "杀", "杀", "闪", "桃"),
                 "identity_view": ("无中生有", "桃", "杀", "闪")}
        for name in names.get(scene, ("杀", "桃", "闪", "闪")):
            place("P1", name, suit=Suit.HEARTS if scene == "judgment" and name == "桃" else None)
        for pid in ids[1:]:
            for name in (("杀", "杀", "桃", "桃") if scene == "rescue" else ("闪", "闪", "杀", "桃")):
                place(pid, name)
        player = next(p for p in state.players if p.player_id == "P1")
        self.target_id = "AI1"
        if scene == "range":
            self.target_id = next(p.player_id for p in state.players
                                  if (p.seat_index - player.seat_index) % 5 == 2)
        if scene == "dismantle":
            self.subject_card = place("AI1", "青釭剑", "equipment")
        if scene == "judgment":
            self.delayed_card = place("P1", "乐不思蜀", "judgment")
        if scene in {"identity_reward", "identity_penalty", "rebel_goal"}:
            place("P1", "青釭剑", "equipment")
        if scene == "rescue":
            player.hp = 1
        if scene in {"duel_goal", "two_goal", "identity_reward", "identity_penalty", "rebel_goal", "turncoat_goal"}:
            for p in state.players:
                if p.player_id == "AI1" or scene == "two_goal" and p.player_id == "AI2":
                    p.hp = 1
        if scene == "turncoat_goal":
            for p in state.players:
                if p.player_id not in {"P1", "AI1"}:
                    p.hp = 0
                    p.alive = False
                    p.identity_public = True
                    # Dead players have no residual zones in this public残局.
                    for cid in tuple(state.zones[p.hand_zone_id].card_ids):
                        state.zones[p.hand_zone_id].card_ids.remove(cid)
                        state.zones["discard_pile"].card_ids.append(cid)
                        card = state.cards[cid]
                        card.zone_id = "discard_pile"
                        card.owner_id = card.controller_id = None
                        card.visibility = Visibility.PUBLIC
        remaining.sort(key=lambda cid: CARD_BY_ID[state.cards[cid].definition_id].name != "闪")
        if scene == "judgment":
            original = next(cid for cid in remaining if CARD_BY_ID[state.cards[cid].definition_id].suit is Suit.SPADES)
            remaining.remove(original)
            remaining.insert(0, original)
        state.zones["draw_pile"].card_ids.extend(remaining)
        # Preserve mode opening rules; only the rescue fixture starts mid-round.
        if scene == "rescue":
            state.current_player_id = "AI1"
        if scene in {"duel_goal", "judgment"}:
            # Fixed teaching seed/first actor, with the ordinary first-turn draw.
            state.current_player_id = "P1"
        engine = GameEngine(state, ai_by_player={pid: PracticeOpponent(scene == "rescue") for pid in ids[1:]},
                            display_pacing_enabled=True, presentation_enabled=True)
        assert_card_zone_invariant(state)
        self.prepare_step(engine)
        return roster, engine

    def prepare_step(self, engine: GameEngine) -> None:
        step = self.step
        self.focus_card = next((cid for cid in self.focus_by_name.get(step.card_name, ())
                                if engine.state.cards[cid].zone_id == "P1.hand"), None)
        if self.step.scene == "two_goal":
            self.target_id = "AI2" if step.goal == "win" else "AI1"
        self.submitted = self.attempted_target = self.completed = False
        self.message = ""
        player = next(p for p in engine.state.players if p.player_id == "P1")
        self.initial_hp = player.hp
        self.target_hp = next(p.hp for p in engine.state.players if p.player_id == self.target_id)
        self.hand_before = len(engine.state.zones[player.hand_zone_id].card_ids)

    def _wanted_options(self, request: DecisionRequest) -> set[str]:
        if self.resolution_pass(request):
            return {"pass"}
        if request.kind == self.step.request_kind:
            return {o.choice_id for o in request.options if o.value == self.focus_card}
        if self.step.goal == "dismantle" and request.kind == "dismantle_area":
            return {o.choice_id for o in request.options if o.choice_id == "equipment"}
        if self.step.goal == "dismantle" and request.kind == "dismantle_visible_card":
            return {o.choice_id for o in request.options if o.value == self.subject_card}
        return set()

    def resolution_pass(self, request: DecisionRequest | None) -> bool:
        """An attack is still resolving: the learner must decline saving its target."""
        return bool(self.submitted and request and request.player_id == "P1"
                    and request.kind == "rescue"
                    and dict(request.context).get("target_id") == self.target_id
                    and self.step.goal in {"win", "first_enemy", "reward", "penalty"}
                    and any(o.choice_id == "pass" for o in request.options))

    def instruction_for(self, app: Any) -> str:
        if self.resolution_pass(app.engine.pending_request):
            return "对手已进入濒死，你也会获得求桃响应机会。本练习要观察击败后的结算，请点击“放弃响应”，不使用桃救对手。"
        return self.step.instruction

    def allow(self, app: Any, action: tuple[object, ...]) -> bool:
        name, *args = action
        gameplay = {"battle_card", "battle_target", "battle_skill", "battle_confirm", "battle_option",
                    "battle_pass", "battle_cancel", "end_play", "answer_prompt", "submit_action",
                    "toggle_choice", "clear_choices"}
        if name not in gameplay:
            return True
        if self.completed or self.finished or app.engine.display_waiting:
            self.message = "本步已完成，请进入下一练习。" if self.completed else "正在展示真实结算，请稍候。"
            return False
        request = app.engine.pending_request
        allowed = False
        if request and request.player_id == "P1":
            wanted = self._wanted_options(request)
            if name == "battle_pass":
                allowed = self.resolution_pass(request)
            elif name in {"battle_option", "toggle_choice"} and args:
                allowed = args[0] in wanted
            elif name == "battle_card" and args:
                allowed = any(o.value == args[0] and o.choice_id in wanted for o in request.options)
            elif name in {"battle_cancel", "clear_choices"}:
                allowed = True
            elif name == "answer_prompt":
                allowed = bool(wanted) and app.selected_choices <= wanted and request.min_choices <= len(app.selected_choices) <= request.max_choices
                if allowed:
                    self.submitted = True
        elif app.engine.is_human_turn:
            if name == "battle_card":
                allowed = args == [self.focus_card] and self.focus_card is not None
            elif name == "battle_skill":
                allowed = bool(self.step.skill_id) and args == [self.step.skill_id]
            elif name == "battle_target":
                allowed = args == [self.target_id] and app.battle_ui.selected_card == self.focus_card
                if allowed and self.step.goal == "distance":
                    self.attempted_target = True
            elif name == "battle_cancel":
                allowed = True
            elif name == "battle_confirm" and self.step.goal != "distance":
                ready = app.battle_ui.ready_action()
                allowed = bool(ready and ((self.step.skill_id and ready.intent.skill_id == self.step.skill_id)
                                         or (not self.step.skill_id and ready.intent.card_id == self.focus_card))
                               and (not ready.intent.target_ids or ready.intent.target_ids == (self.target_id,)))
                if allowed:
                    self.submitted = True
                    self.hand_before = len(app.engine.state.zones["P1.hand"].card_ids)
        self.message = "" if allowed else "本步练习：" + self.instruction_for(app)
        return allowed

    def observe(self, app: Any, action: str | None = None) -> None:
        if self.completed or self.finished or not app.engine:
            return
        engine, ui = app.engine, app.battle_ui
        goal = self.step.goal
        if goal == "distance":
            success = self.attempted_target and self.target_id not in ui.targets and not any(
                a.intent.card_id == self.focus_card and a.intent.target_ids == (self.target_id,)
                for a in engine.available_actions("P1"))
        else:
            if not self.submitted or engine.display_waiting or engine.pending_request or not (engine.is_human_turn or engine.finished):
                return
            state = engine.state
            player = next(p for p in state.players if p.player_id == "P1")
            target = next(p for p in state.players if p.player_id == self.target_id)
            hand = len(state.zones["P1.hand"].card_ids)
            spent = bool(self.focus_card and state.cards[self.focus_card].zone_id == "discard_pile")
            success = {
                "equip": bool(self.focus_card and state.cards[self.focus_card].zone_id == "P1.equipment"),
                "damage": spent and target.hp == self.target_hp - 1,
                "dismantle": spent and bool(self.subject_card and state.cards[self.subject_card].zone_id == "discard_pile"),
                "judgment": spent and bool(self.delayed_card and state.cards[self.delayed_card].zone_id == "discard_pile") and engine.is_human_turn,
                "rescue": spent and player.alive and player.hp > 0,
                "skill": player.hp == self.initial_hp - 1 and hand == self.hand_before + 2,
                "draw": spent and hand == self.hand_before + 1,
                "first_enemy": spent and not target.alive and not engine.finished,
                "win": spent and engine.finished and engine.player_outcome == "win",
                "reward": spent and not target.alive and target.identity_public and hand == self.hand_before + 2,
                "penalty": spent and not target.alive and target.identity_public and hand == 0 and not state.zones["P1.equipment"].card_ids,
            }.get(goal, False)
        if success:
            self.completed = True
            self.message = self.step.feedback


def create_tutorial(lesson_id: str) -> GuidedTutorial:
    if lesson_id == "basic":
        return GuidedTutorial()
    if lesson_id not in {"advanced", "modes"}:
        raise ValueError(f"unknown tutorial: {lesson_id}")
    return RuleGuidedTutorial(lesson_id)
