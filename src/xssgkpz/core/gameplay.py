"""Turn engine for the formal 25-hero, 108-card ruleset and Stage 1 fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from itertools import combinations
from collections.abc import Mapping
from typing import Any, Generator

from xssgkpz.core.actions import ActionIntent, ChoiceOption, DecisionRequest, GameAction
from xssgkpz.core.ai import SimpleAI
from xssgkpz.core.observation import ObservationView, PublicActionRecord, make_observation
from xssgkpz.data.cards import CARD_DEFINITIONS, CARD_BY_ID
from xssgkpz.core.state import (
    ControlType, EventFrame, GamePhase, GameState, PlayerState, Visibility,
    ZoneKind, assert_card_zone_invariant,
)
from xssgkpz.data.cards import CARD_KIND_BY_NAME, CardCategory, Suit
from xssgkpz.data.heroes import Faction, HERO_BY_ID
from xssgkpz.data.modes import Identity, MODE_BY_ID


@dataclass(frozen=True, slots=True)
class EventLog:
    turn_number: int
    text: str
    private_to: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AIExecutionIssue:
    player_id: str
    turn_number: int
    stage: str
    selected: tuple[str, ...]
    reason: str


_NO_ANSWER = object()
_DISPLAY_PAUSE = object()


@dataclass(frozen=True, slots=True)
class PresentationEvent:
    """Public, already committed action evidence for the optional display layer."""

    serial: int
    kind: str
    actor_id: str | None
    card_ids: tuple[str, ...] = ()
    target_ids: tuple[str, ...] = ()
    label: str = ""
    effective_name: str | None = None
    reference_card_id: str | None = None
    origin_actor_id: str | None = None



class GameEngine:
    """Authoritative mutable game state; the UI and AI only submit intents."""

    def __init__(
        self,
        state: GameState,
        ai: SimpleAI | None = None,
        *,
        ai_by_player: Mapping[str, Any] | None = None,
        auto_turn_limit: int | None = None,
        display_pacing_enabled: bool = False,
        presentation_enabled: bool = False,
    ) -> None:
        self.state = state
        self.ai = ai or SimpleAI()
        self.ai_by_player = dict(ai_by_player or {})
        self.auto_turn_limit = auto_turn_limit
        self.display_pacing_enabled = display_pacing_enabled
        self.presentation_enabled = presentation_enabled
        self.presentation_event: PresentationEvent | None = None
        self._presentation_serial = 0
        self.audio_events: deque[tuple[int, str]] = deque(maxlen=128)
        self._audio_serial = 0
        self.public_action_history: list[PublicActionRecord] = []
        self.ai_issues: list[AIExecutionIssue] = []
        self.logs: list[EventLog] = []
        self.pending_request: DecisionRequest | None = None
        self._generator: Generator[Any, Any, Any] | None = None
        self.display_waiting = False
        self._started = False
        self._fast_forward = False
        self.spectator_waiting = False
        self.spectator_reveal_identities = False
        self.spectator_reveal_hands = False
        self._event_serial = 0
        self._turn_counts: dict[str, int] = {}
        self._kill_uses: dict[str, int] = {}
        self._skip_play: set[str] = set()
        self._used_skill_this_play: set[tuple[str, str]] = set()
        self._rende_given: dict[str, int] = {}
        self._rende_heal_used: set[str] = set()
        self._played_kill_this_turn: set[str] = set()
        self._luoyi_bonus: set[str] = set()
        self._response_extra_materials: dict[str, tuple[str, ...]] = {}
        self._response_virtual_colors: dict[str, str | None] = {}
        self._append_log(
            "正式对局已建立，使用108张标准牌组。" if len(state.cards) == 108
            else "阶段1固定场景已建立，使用其专用测试牌组。"
        )

    @property
    def finished(self) -> bool:
        return self.state.result is not None

    @property
    def current_player(self) -> PlayerState | None:
        return self._player(self.state.current_player_id) if self.state.current_player_id else None

    @property
    def is_human_turn(self) -> bool:
        player = self.current_player
        return bool(player and player.alive and player.control is ControlType.HUMAN
                    and self.state.phase is GamePhase.PLAY and not self.pending_request
                    and self._generator is None and not self.finished)

    @property
    def player_outcome(self) -> str | None:
        if not self.finished:
            return None
        if self.state.result in {"draw", "unfinished"}:
            return self.state.result
        if self.state.mode_id in {"duel", "two_heroes"}:
            return "win" if self.state.result == "player_side_win" else "loss"
        player = self._player("P1")
        winning_identities = {
            "lord_side_win": {Identity.LORD.value, Identity.LOYALIST.value},
            "rebel_side_win": {Identity.REBEL.value},
            "turncoat_side_win": {Identity.TURNCOAT.value},
        }.get(self.state.result, set())
        return "win" if player and player.identity in winning_identities else "loss"

    def observation_for(self, player_id: str) -> ObservationView:
        distances = ()
        if self._player(player_id).alive:
            distances = tuple(
                (player.player_id, self.distance(player_id, player.player_id))
                for player in self.state.players
                if player.alive
            )
        return make_observation(
            self.state,
            player_id,
            public_actions=tuple(self.public_action_history),
            distances_from_viewer=distances,
        )

    def _ai_for(self, player_id: str) -> Any:
        return self.ai_by_player.get(player_id, self.ai)

    def public_logs(self) -> tuple[EventLog, ...]:
        return tuple(log for log in self.logs if not log.private_to)

    def private_logs_for(self, player_id: str) -> tuple[EventLog, ...]:
        return tuple(log for log in self.logs if not log.private_to or player_id in log.private_to)

    def start(self) -> None:
        if self._started or self.finished:
            return
        self._started = True
        self._drive(self._continue_until_human())

    def answer_prompt(self, choice: str | tuple[str, ...]) -> None:
        request = self.pending_request
        if request is None or self._generator is None:
            raise ValueError("there is no pending choice")
        chosen = (choice,) if isinstance(choice, str) else tuple(choice)
        allowed = {option.choice_id for option in request.options}
        if any(item not in allowed for item in chosen):
            raise ValueError("choice is not available in the current prompt")
        if not request.min_choices <= len(chosen) <= request.max_choices:
            raise ValueError("incorrect number of choices")
        if request.kind in {"axe_payment", "ganglie"}:
            allowed_shape = chosen == ("pass",) or chosen == ("damage",) or (
                len(chosen) == 2 and all(item.startswith("discard:") for item in chosen)
                and chosen[0] != chosen[1]
            )
            if not allowed_shape:
                raise ValueError("choose pass/damage or exactly two different discard cards")
        self.pending_request = None
        self._drive(self._generator, chosen[0] if len(chosen) == 1 else chosen)

    def submit_action(self, intent: ActionIntent) -> None:
        if not self.is_human_turn or intent.actor_id != self.state.current_player_id:
            raise ValueError("the actor cannot act now")
        if not self.is_legal_intent(intent):
            raise ValueError("this action is not legal in the current state")
        self._drive(self._event("player_action", intent.actor_id, self._resolve_intent(intent)))

    def end_play_phase(self) -> None:
        if not self.is_human_turn:
            raise ValueError("the player cannot end the play phase now")
        self._drive(self._finish_human_turn())

    def resign(self, *, end_reason: str = "resigned") -> None:
        if not self.finished:
            self._finish("player_side_loss", end_reason, "玩家认输。")

    def exit_unfinished(self) -> None:
        if not self.finished:
            self._finish("unfinished", "exit_to_menu", "玩家退出对局，未计胜负。")

    def continue_spectator(self, *, fast_forward: bool = False) -> None:
        if not self.spectator_waiting or self.finished:
            return
        self.spectator_waiting = False
        self._fast_forward = fast_forward
        self._drive(self._continue_until_human())
        self._fast_forward = False

    def resume_display(self) -> None:
        """Resume a UI-only AI presentation pause without changing the rules state."""
        if not self.display_waiting or self._generator is None or self.finished:
            return
        generator = self._generator
        self.display_waiting = False
        self._drive(generator)

    def reveal_identities_for_spectator(self) -> None:
        self.spectator_reveal_identities = True

    def reveal_hands_for_spectator(self) -> None:
        self.spectator_reveal_hands = True

    def live_players(self) -> tuple[PlayerState, ...]:
        return tuple(sorted((player for player in self.state.players if player.alive), key=lambda item: item.seat_index))

    def distance(self, source_id: str, target_id: str, *, ignore_range_modifiers: bool = False) -> int:
        source = self._player(source_id)
        target = self._player(target_id)
        if source is target:
            return 0
        alive = self.live_players()
        count = len(alive)
        if count < 2:
            return 0
        source_index = next(i for i, player in enumerate(alive) if player.player_id == source_id)
        target_index = next(i for i, player in enumerate(alive) if player.player_id == target_id)
        distance = min((source_index - target_index) % count, (target_index - source_index) % count)
        if not ignore_range_modifiers:
            if self._has_skill(source_id, "mashu"):
                distance -= 1
            if self._has_horse(source_id, "horse_minus_one"):
                distance -= 1
            if self._has_horse(target_id, "horse_plus_one"):
                distance += 1
        return max(1, distance)

    def attack_range(self, player_id: str) -> int:
        for card_id in self._zone(self._player(player_id).equipment_zone_id).card_ids:
            definition = self._definition(card_id)
            ranges = {
                "crossbow": 1, "double_swords": 2, "qinggang_sword": 2,
                "frost_sword": 2, "qinglong_blade": 3, "serpent_spear": 3,
                "axe": 3, "halberd": 4, "kirin_bow": 5,
            }
            if definition.kind_id in ranges:
                return ranges[definition.kind_id]
        return 1

    def kill_targets(self, player_id: str, *, cost_card_ids: tuple[str, ...] = (), locked_followup: bool = False) -> tuple[str, ...]:
        excluded_equipment = set(cost_card_ids)
        targets = []
        for target in self.live_players():
            if target.player_id == player_id:
                continue
            if self._has_skill(target.player_id, "kongcheng") and not self._zone(target.hand_zone_id).card_ids:
                continue
            if locked_followup:
                targets.append(target.player_id)
                continue
            distance = self.distance(player_id, target.player_id, ignore_range_modifiers=True)
            source_horse_removed = any(
                card_id in excluded_equipment
                and CARD_KIND_BY_NAME[self._definition(card_id).name].subtype == "horse_minus_one"
                for card_id in self._zone(self._player(player_id).equipment_zone_id).card_ids
            )
            if self._has_horse(player_id, "horse_minus_one") and not source_horse_removed:
                distance -= 1
            if self._has_skill(player_id, "mashu"):
                distance -= 1
            if self._has_horse(target.player_id, "horse_plus_one"):
                distance += 1
            distance = max(1, distance)
            attack_range = self.attack_range(player_id)
            for card_id in excluded_equipment:
                if self._equipment_slot_by_id(card_id) == "weapon":
                    attack_range = 1
            if distance <= attack_range:
                targets.append(target.player_id)
        return tuple(targets)

    def available_actions(self, actor_id: str) -> tuple[GameAction, ...]:
        if self.finished or actor_id != self.state.current_player_id or self.state.phase is not GamePhase.PLAY:
            return ()
        player = self._player(actor_id)
        if not player.alive:
            return ()
        actions: list[GameAction] = []
        hand = tuple(self._zone(player.hand_zone_id).card_ids)
        for card_id in hand:
            definition = self._definition(card_id)
            name = definition.name
            if name == "杀" and self._can_use_kill(actor_id):
                for target_id in self.kill_targets(actor_id):
                    actions.append(self._action(f"play:kill:{card_id}:{target_id}", "使用【杀】", ActionIntent(actor_id, card_id, target_ids=(target_id,))))
            elif name == "桃" and player.hp < player.max_hp:
                actions.append(self._action(f"play:tao:{card_id}", "使用【桃】", ActionIntent(actor_id, card_id)))
            elif name in {"决斗", "过河拆桥", "顺手牵羊"}:
                for target_id in self.legal_targets_for_card(actor_id, card_id):
                    actions.append(self._action(f"play:{definition.kind_id}:{card_id}:{target_id}", f"使用【{name}】", ActionIntent(actor_id, card_id, target_ids=(target_id,))))
            elif name == "无中生有":
                actions.append(self._action(f"play:draw_two:{card_id}", "使用【无中生有】", ActionIntent(actor_id, card_id)))
            elif name == "南蛮入侵":
                actions.append(self._action(f"play:barbarians:{card_id}", "使用【南蛮入侵】", ActionIntent(actor_id, card_id)))
            elif name == "万箭齐发":
                actions.append(self._action(f"play:arrows:{card_id}", "使用【万箭齐发】", ActionIntent(actor_id, card_id)))
            elif name == "桃园结义":
                actions.append(self._action(f"play:peach_garden:{card_id}", "使用【桃园结义】", ActionIntent(actor_id, card_id)))
            elif name == "五谷丰登":
                actions.append(self._action(f"play:harvest:{card_id}", "使用【五谷丰登】", ActionIntent(actor_id, card_id)))
            elif name == "借刀杀人":
                for target in self.live_players():
                    if (target.player_id != actor_id and self._weapon_ids(target.player_id)
                            and self._borrow_sword_targets(target.player_id, actor_id)):
                        actions.append(self._action(f"play:borrow_sword:{card_id}:{target.player_id}", "使用【借刀杀人】", ActionIntent(actor_id, card_id, target_ids=(target.player_id,))))
            elif name == "乐不思蜀":
                for target in self.live_players():
                    if (target.player_id != actor_id and not self._has_skill(target.player_id, "qianxun")
                            and not self._has_same_delayed(target.player_id, "indulgence")):
                        actions.append(self._action(f"play:indulgence:{card_id}:{target.player_id}", "使用【乐不思蜀】", ActionIntent(actor_id, card_id, target_ids=(target.player_id,))))
            elif name == "闪电" and not self._has_same_delayed(actor_id, "lightning"):
                actions.append(self._action(f"play:lightning:{card_id}", "使用【闪电】", ActionIntent(actor_id, card_id)))
            elif definition.category is CardCategory.EQUIPMENT:
                actions.append(self._action(f"equip:{definition.kind_id}:{card_id}", f"装备【{name}】", ActionIntent(actor_id, card_id)))

        if self._has_skill(actor_id, "wusheng") and self._can_use_kill(actor_id):
            for card_id in self._red_sources(actor_id):
                for target_id in self.kill_targets(actor_id, cost_card_ids=(card_id,)):
                    actions.append(self._action(f"skill:wusheng:{card_id}:{target_id}", "武圣：当杀使用", ActionIntent(actor_id, skill_id="wusheng", cost_card_ids=(card_id,), target_ids=(target_id,))))
        if self._has_skill(actor_id, "longdan") and self._can_use_kill(actor_id):
            for card_id in hand:
                if self._definition(card_id).name != "闪":
                    continue
                for target_id in self.kill_targets(actor_id):
                    actions.append(self._action(f"skill:longdan:{card_id}:{target_id}", "龙胆：当杀使用", ActionIntent(actor_id, skill_id="longdan", cost_card_ids=(card_id,), target_ids=(target_id,))))
        if (self._has_equipment(actor_id, "serpent_spear") and self._can_use_kill(actor_id)
                and len(hand) >= 2):
            for cost_ids in combinations(hand, 2):
                for target_id in self.kill_targets(actor_id):
                    actions.append(self._action(
                        f"skill:serpent_spear:{cost_ids[0]}:{cost_ids[1]}:{target_id}",
                        "丈八蛇矛：两张手牌当杀",
                        ActionIntent(actor_id, skill_id="serpent_spear", cost_card_ids=cost_ids,
                                     target_ids=(target_id,))))
        if self._has_skill(actor_id, "qixi"):
            for card_id in self._black_sources(actor_id):
                for target in self.live_players():
                    if target.player_id != actor_id and self._has_interactable_card(target.player_id):
                        actions.append(self._action(f"skill:qixi:{card_id}:{target.player_id}", "奇袭：当过河拆桥使用", ActionIntent(actor_id, skill_id="qixi", cost_card_ids=(card_id,), target_ids=(target.player_id,))))
        if self._has_skill(actor_id, "guose"):
            for card_id in self._red_sources(actor_id):
                if self._definition(card_id).suit is not Suit.DIAMONDS:
                    continue
                for target_id in self.legal_targets_for_card(actor_id, card_id, "guose", (card_id,)):
                    actions.append(self._action(f"skill:guose:{card_id}:{target_id}", "国色：当乐不思蜀使用", ActionIntent(actor_id, skill_id="guose", cost_card_ids=(card_id,), target_ids=(target_id,))))
        if self._has_skill(actor_id, "rende"):
            for target in self.live_players():
                if target.player_id != actor_id and hand:
                    actions.append(self._action(f"skill:rende:{target.player_id}", "仁德：选择手牌交给角色", ActionIntent(actor_id, skill_id="rende", choice="choose", target_ids=(target.player_id,))))
        if self._has_skill(actor_id, "zhiheng") and (actor_id, "zhiheng") not in self._used_skill_this_play:
            candidates = (*hand, *self._zone(player.equipment_zone_id).card_ids)
            if candidates:
                actions.append(self._action("skill:zhiheng:choose", "制衡：选择要弃置的牌", ActionIntent(actor_id, skill_id="zhiheng", choice="choose")))
        if self._has_skill(actor_id, "fanjian") and (actor_id, "fanjian") not in self._used_skill_this_play and hand:
            for target in self.live_players():
                if target.player_id != actor_id:
                    actions.append(self._action(f"skill:fanjian:{target.player_id}", "反间", ActionIntent(actor_id, skill_id="fanjian", target_ids=(target.player_id,))))
        if self._has_skill(actor_id, "qingnang") and (actor_id, "qingnang") not in self._used_skill_this_play and hand:
            for target in self.live_players():
                if target.hp < target.max_hp:
                    actions.append(self._action(f"skill:qingnang:{target.player_id}", "青囊：弃手牌治疗", ActionIntent(actor_id, skill_id="qingnang", choice="choose", target_ids=(target.player_id,))))
        if self._has_skill(actor_id, "kurou"):
            actions.append(self._action("skill:kurou", "苦肉：失去1点体力摸两张", ActionIntent(actor_id, skill_id="kurou")))
        if self._has_skill(actor_id, "jieyin") and (actor_id, "jieyin") not in self._used_skill_this_play and len(hand) >= 2:
            for target in self.live_players():
                if (target.player_id != actor_id and target.hp < target.max_hp
                        and HERO_BY_ID[target.hero_id].gender.value == "男性"):
                    actions.append(self._action(f"skill:jieyin:{target.player_id}", "结姻：弃两张手牌治疗", ActionIntent(actor_id, skill_id="jieyin", choice="choose", target_ids=(target.player_id,))))
        if self._has_skill(actor_id, "lijian") and (actor_id, "lijian") not in self._used_skill_this_play:
            costs = (*hand, *self._zone(player.equipment_zone_id).card_ids)
            male_ids = tuple(item.player_id for item in self.live_players()
                             if item.player_id != actor_id and HERO_BY_ID[item.hero_id].gender.value == "男性")
            for card_id in costs:
                for first, second in combinations(male_ids, 2):
                    actions.append(self._action(f"skill:lijian:{card_id}:{first}:{second}", "离间：弃牌并令两名男性决斗", ActionIntent(actor_id, skill_id="lijian", cost_card_ids=(card_id,), target_ids=(first, second))))
        if self._is_lord(actor_id) and self._has_skill(actor_id, "jijiang") and self._can_use_kill(actor_id):
            for target_id in self.kill_targets(actor_id):
                if self._jijiang_providers(actor_id):
                    actions.append(self._action(f"skill:jijiang:{target_id}", "激将：请蜀将提供杀", ActionIntent(actor_id, skill_id="jijiang", target_ids=(target_id,))))
        return tuple(actions)

    def legal_targets_for_card(self, actor_id: str, card_id: str, skill_id: str | None = None, cost_card_ids: tuple[str, ...] = ()) -> tuple[str, ...]:
        definition = self._definition(card_id)
        if skill_id == "guose":
            return tuple(player.player_id for player in self.live_players()
                         if player.player_id != actor_id
                         and not self._has_skill(player.player_id, "qianxun")
                         and not self._has_same_delayed(player.player_id, "indulgence"))
        if skill_id == "qixi":
            return tuple(player.player_id for player in self.live_players()
                         if player.player_id != actor_id and self._has_interactable_card(player.player_id))
        if definition.name == "杀" or skill_id == "wusheng":
            return self.kill_targets(actor_id, cost_card_ids=cost_card_ids)
        if definition.name == "决斗":
            return tuple(player.player_id for player in self.live_players()
                         if player.player_id != actor_id
                         and not (self._has_skill(player.player_id, "kongcheng")
                                  and not self._zone(player.hand_zone_id).card_ids))
        if definition.name in {"过河拆桥", "顺手牵羊"} or skill_id == "qixi":
            if definition.name == "顺手牵羊" and skill_id is None:
                return tuple(player.player_id for player in self.live_players()
                             if player.player_id != actor_id
                             and (self._has_skill(actor_id, "qicai") or self.distance(actor_id, player.player_id) == 1)
                             and not self._has_skill(player.player_id, "qianxun")
                             and self._has_interactable_card(player.player_id))
            return tuple(player.player_id for player in self.live_players() if player.player_id != actor_id and self._has_interactable_card(player.player_id))
        if definition.name == "乐不思蜀":
            return tuple(player.player_id for player in self.live_players() if player.player_id != actor_id
                         and not self._has_skill(player.player_id, "qianxun")
                         and not self._has_same_delayed(player.player_id, "indulgence"))
        return ()

    def is_legal_intent(self, intent: ActionIntent) -> bool:
        actor = self._player(intent.actor_id)
        if not actor.alive or self.state.current_player_id != intent.actor_id or self.state.phase is not GamePhase.PLAY:
            return False
        if intent.skill_id:
            skill = intent.skill_id
            if skill == "wusheng":
                return (self._has_skill(intent.actor_id, skill) and len(intent.cost_card_ids) == 1
                        and intent.cost_card_ids[0] in self._red_sources(intent.actor_id)
                        and len(intent.target_ids) == 1 and intent.target_ids[0] in self.kill_targets(intent.actor_id, cost_card_ids=intent.cost_card_ids)
                        and self._can_use_kill(intent.actor_id))
            if skill == "longdan":
                return (self._has_skill(intent.actor_id, skill) and self._can_use_kill(intent.actor_id)
                        and len(intent.cost_card_ids) == 1
                        and intent.cost_card_ids[0] in self._zone(actor.hand_zone_id).card_ids
                        and self._definition(intent.cost_card_ids[0]).name == "闪"
                        and len(intent.target_ids) == 1
                        and intent.target_ids[0] in self.kill_targets(intent.actor_id))
            if skill == "serpent_spear":
                return (self._has_equipment(intent.actor_id, "serpent_spear")
                        and self._can_use_kill(intent.actor_id)
                        and len(intent.cost_card_ids) == 2
                        and len(set(intent.cost_card_ids)) == 2
                        and set(intent.cost_card_ids) <= set(self._zone(actor.hand_zone_id).card_ids)
                        and len(intent.target_ids) == 1
                        and intent.target_ids[0] in self.kill_targets(intent.actor_id))
            if skill == "qixi":
                if not self._has_skill(intent.actor_id, skill) or len(intent.cost_card_ids) != 1 or len(intent.target_ids) != 1:
                    return False
                return (intent.cost_card_ids[0] in self._black_sources(intent.actor_id)
                        and intent.target_ids[0] in self.legal_targets_for_card(intent.actor_id, intent.cost_card_ids[0], skill, intent.cost_card_ids))
            if skill == "guose":
                allowed = set(self._zone(actor.hand_zone_id).card_ids) | set(self._zone(actor.equipment_zone_id).card_ids)
                return (self._has_skill(intent.actor_id, skill)
                        and len(intent.cost_card_ids) == 1 and intent.cost_card_ids[0] in allowed
                        and self._definition(intent.cost_card_ids[0]).suit is Suit.DIAMONDS
                        and len(intent.target_ids) == 1
                        and intent.target_ids[0] in self.legal_targets_for_card(intent.actor_id, intent.cost_card_ids[0], skill, intent.cost_card_ids))
            if skill == "rende":
                allowed_hand = set(self._zone(actor.hand_zone_id).card_ids)
                costs_valid = (
                    intent.choice == "choose" and not intent.cost_card_ids and bool(allowed_hand)
                ) or (
                    bool(intent.cost_card_ids) and len(set(intent.cost_card_ids)) == len(intent.cost_card_ids)
                    and set(intent.cost_card_ids) <= allowed_hand
                )
                return (self._has_skill(intent.actor_id, skill) and costs_valid
                        and len(intent.target_ids) == 1 and intent.target_ids[0] != intent.actor_id
                        and self._player(intent.target_ids[0]).alive)
            if skill == "zhiheng":
                allowed = set(self._zone(actor.hand_zone_id).card_ids) | set(self._zone(actor.equipment_zone_id).card_ids)
                costs_valid = (
                    intent.choice == "choose" and not intent.cost_card_ids and bool(allowed)
                ) or (
                    bool(intent.cost_card_ids) and len(set(intent.cost_card_ids)) == len(intent.cost_card_ids)
                    and set(intent.cost_card_ids) <= allowed
                )
                return (self._has_skill(intent.actor_id, skill) and (intent.actor_id, skill) not in self._used_skill_this_play
                        and costs_valid)
            if skill == "fanjian":
                return (self._has_skill(intent.actor_id, skill) and (intent.actor_id, skill) not in self._used_skill_this_play
                        and bool(self._zone(actor.hand_zone_id).card_ids) and len(intent.target_ids) == 1
                        and intent.target_ids[0] != intent.actor_id and self._player(intent.target_ids[0]).alive)
            if skill == "qingnang":
                return (self._has_skill(intent.actor_id, skill)
                        and (intent.actor_id, skill) not in self._used_skill_this_play
                        and intent.choice == "choose" and not intent.cost_card_ids
                        and len(intent.target_ids) == 1 and self._player(intent.target_ids[0]).alive
                        and self._player(intent.target_ids[0]).hp < self._player(intent.target_ids[0]).max_hp
                        and bool(self._zone(actor.hand_zone_id).card_ids))
            if skill == "kurou":
                return self._has_skill(intent.actor_id, skill) and not intent.cost_card_ids and not intent.target_ids
            if skill == "jieyin":
                allowed_hand = set(self._zone(actor.hand_zone_id).card_ids)
                target = self._player(intent.target_ids[0]) if len(intent.target_ids) == 1 else None
                costs_valid = (intent.choice == "choose" and not intent.cost_card_ids
                               or len(intent.cost_card_ids) == 2
                               and len(set(intent.cost_card_ids)) == 2
                               and set(intent.cost_card_ids) <= allowed_hand)
                return (self._has_skill(intent.actor_id, skill)
                        and (intent.actor_id, skill) not in self._used_skill_this_play
                        and costs_valid and target is not None and target.player_id != intent.actor_id
                        and target.alive and target.hp < target.max_hp
                        and HERO_BY_ID[target.hero_id].gender.value == "男性")
            if skill == "lijian":
                allowed = set(self._zone(actor.hand_zone_id).card_ids) | set(self._zone(actor.equipment_zone_id).card_ids)
                if (not self._has_skill(intent.actor_id, skill)
                        or (intent.actor_id, skill) in self._used_skill_this_play
                        or len(intent.cost_card_ids) != 1 or intent.cost_card_ids[0] not in allowed
                        or len(intent.target_ids) != 2 or intent.target_ids[0] == intent.target_ids[1]):
                    return False
                if not all(self._player(target_id).alive
                           and HERO_BY_ID[self._player(target_id).hero_id].gender.value == "男性"
                           for target_id in intent.target_ids):
                    return False
                return any(
                    not (self._has_skill(other_id, "kongcheng")
                         and not self._zone(self._player(other_id).hand_zone_id).card_ids)
                    for initiator_id in intent.target_ids
                    for other_id in intent.target_ids
                    if initiator_id != other_id
                )
            if skill == "jijiang":
                return (self._is_lord(intent.actor_id) and self._has_skill(intent.actor_id, skill)
                        and self._can_use_kill(intent.actor_id) and len(intent.target_ids) == 1
                        and intent.target_ids[0] in self.kill_targets(intent.actor_id)
                        and bool(self._jijiang_providers(intent.actor_id)))
            return False

        if intent.card_id is None or intent.card_id not in self._zone(actor.hand_zone_id).card_ids:
            return False
        definition = self._definition(intent.card_id)
        if definition.name == "杀":
            return self._can_use_kill(intent.actor_id) and len(intent.target_ids) == 1 and intent.target_ids[0] in self.kill_targets(intent.actor_id)
        if definition.name == "桃":
            return not intent.target_ids and actor.hp < actor.max_hp
        if definition.name == "决斗":
            return len(intent.target_ids) == 1 and intent.target_ids[0] in self.legal_targets_for_card(intent.actor_id, intent.card_id)
        if definition.name in {"过河拆桥", "顺手牵羊"}:
            return len(intent.target_ids) == 1 and intent.target_ids[0] in self.legal_targets_for_card(intent.actor_id, intent.card_id)
        if definition.name == "借刀杀人":
            return len(intent.target_ids) == 1 and intent.target_ids[0] in self._borrow_sword_wielders(intent.actor_id)
        if definition.name == "无中生有":
            return not intent.target_ids
        if definition.name in {"南蛮入侵", "万箭齐发", "桃园结义", "五谷丰登"}:
            return not intent.target_ids
        if definition.name == "乐不思蜀":
            return len(intent.target_ids) == 1 and intent.target_ids[0] in self.legal_targets_for_card(intent.actor_id, intent.card_id)
        if definition.name == "闪电":
            return not intent.target_ids and not self._has_same_delayed(intent.actor_id, "lightning")
        if definition.category is CardCategory.EQUIPMENT:
            return not intent.target_ids
        return False

    def _action(self, action_id: str, label: str, intent: ActionIntent) -> GameAction:
        return GameAction(action_id, label, intent)

    def _drive(self, generator: Generator[Any, Any, Any], answer: Any = _NO_ANSWER) -> None:
        self._generator = generator
        self.pending_request = None
        self.display_waiting = False
        self.presentation_event = None
        while True:
            try:
                yielded = next(generator) if answer is _NO_ANSWER else generator.send(answer)
                answer = _NO_ANSWER
            except StopIteration:
                self._generator = None
                self.pending_request = None
                self.display_waiting = False
                self._assert_invariants()
                return
            if yielded is _DISPLAY_PAUSE:
                self.display_waiting = True
                return
            if not isinstance(yielded, DecisionRequest):
                raise RuntimeError(f"engine yielded unexpected value: {yielded!r}")
            self.pending_request = yielded
            return

    def _present_action(self, kind: str, actor_id: str | None, *,
                        card_ids: tuple[str, ...] = (), target_ids: tuple[str, ...] = (),
                        label: str = "", effective_name: str | None = None,
                        reference_card_id: str | None = None,
                        origin_actor_id: str | None = None) -> Generator[Any, Any, None]:
        # No rule result or random draw occurs here. Disabled for headless consumers.
        if not self.presentation_enabled or self._fast_forward or self.finished:
            return
        public_cards = tuple(card_id for card_id in card_ids
                             if self.state.cards[card_id].visibility is Visibility.PUBLIC)
        self._presentation_serial += 1
        self.presentation_event = PresentationEvent(
            self._presentation_serial, kind, actor_id, public_cards, target_ids,
            label, effective_name, reference_card_id, origin_actor_id,
        )
        yield _DISPLAY_PAUSE

    def _continue_until_human(self) -> Generator[Any, Any, None]:
        while not self.finished:
            if (self.auto_turn_limit is not None
                    and self.state.turn_number >= self.auto_turn_limit):
                self._finish("unfinished", "ai_simulation_turn_limit", "自动模拟达到回合上限。")
                return
            if self.spectator_waiting:
                return
            player = self.current_player
            if player is None or not player.alive:
                self._advance_current_player()
                continue
            yield from self._start_turn(player)
            if self.finished:
                return
            # Only an actual play phase hands control back to the action UI.
            # A skipped human play phase must continue to discard/end here.
            if self.is_human_current_player() and self.state.phase is GamePhase.PLAY:
                return
            if self.state.phase is GamePhase.PLAY:
                yield from self._run_ai_play(player)
            if self.finished:
                return
            yield from self._discard_phase(player)
            if self.finished:
                return
            yield from self._resolve_end_skills(player)
            if self.finished:
                return
            self._end_turn(player)
            if self._is_spectating() and not self._fast_forward:
                self.spectator_waiting = True
                return
            self._advance_current_player()

    def _start_turn(self, player: PlayerState) -> Generator[Any, Any, None]:
        if self.finished or not player.alive:
            return
        self.state.current_player_id = player.player_id
        self.state.turn_number += 1
        self._turn_counts[player.player_id] = self._turn_counts.get(player.player_id, 0) + 1
        self._kill_uses[player.player_id] = 0
        self._played_kill_this_turn.discard(player.player_id)
        self._luoyi_bonus.discard(player.player_id)
        self._used_skill_this_play = {item for item in self._used_skill_this_play if item[0] != player.player_id}
        self._rende_given[player.player_id] = 0
        self._rende_heal_used.discard(player.player_id)
        self.state.phase = GamePhase.PREPARATION
        self._append_log(f"{self._hero_name(player)}的回合开始。")
        yield from self._preparation_skills(player)
        if self.finished or not player.alive:
            return
        self.state.phase = GamePhase.JUDGMENT
        yield from self._resolve_judgment_zone(player)
        if self.finished or not player.alive:
            return
        self.state.phase = GamePhase.DRAW
        draw_count = 1 if self.state.mode_id == "duel" and self.state.turn_number == 1 else 2
        replaced_draw = False
        if self._has_skill(player.player_id, "tuxi"):
            targets = tuple(item for item in self.live_players()
                            if item.player_id != player.player_id and self._zone(item.hand_zone_id).card_ids)
            if targets:
                answer = yield from self._ask(player.player_id, "tuxi", "突袭",
                                              "可放弃本阶段正常摸牌，改为从一至两名有手牌的角色处各随机获得一张。",
                                              (ChoiceOption("yes", "发动突袭", "yes"),
                                               ChoiceOption("pass", "不发动", "pass")))
                if answer == "yes":
                    target_options = tuple(ChoiceOption(f"target:{item.player_id}", self._hero_name(item), "target", item.player_id)
                                           for item in targets)
                    chosen = yield from self._ask(player.player_id, "tuxi_targets", "突袭",
                                                  "先选择一至两名目标，再依次随机取得其手牌。",
                                                  target_options, min_choices=1, max_choices=min(2, len(target_options)))
                    selected_ids = (chosen,) if isinstance(chosen, str) else chosen
                    selected_targets = tuple(option.value for option in target_options if option.choice_id in selected_ids)
                    for target_id in selected_targets:
                        hand_cards = tuple(self._zone(self._player(target_id).hand_zone_id).card_ids)
                        if not hand_cards:
                            continue
                        card_id = self.state.random_stream.choice(hand_cards)
                        yield from self._move_with_loss_triggers(card_id, player.hand_zone_id,
                                                                owner_id=player.player_id,
                                                                controller_id=player.player_id,
                                                                visibility=Visibility.OWNER_ONLY)
                        self._append_log(f"张辽发动突袭，从{self._hero_name(self._player(target_id))}处随机获得一张手牌。",
                                         private_to=(player.player_id,))
                        if self.finished:
                            return
                    replaced_draw = True
        if not replaced_draw and self._has_skill(player.player_id, "luoyi"):
            answer = yield from self._ask(player.player_id, "luoyi", "裸衣",
                                          "可令本摸牌阶段少摸一张；本回合出牌阶段杀和自己造成的决斗伤害+1。",
                                          (ChoiceOption("yes", "发动裸衣", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            if answer == "yes":
                draw_count = max(0, draw_count - 1)
                self._luoyi_bonus.add(player.player_id)
                self._append_log("许褚发动裸衣，本摸牌阶段少摸一张。")
        if not replaced_draw and self._has_skill(player.player_id, "yingzi"):
            choices = (
                ChoiceOption("yes", "发动英姿，额外摸一张", "yes"),
                ChoiceOption("no", "不发动", "pass"),
            )
            answer = yield from self._ask(player.player_id, "yingzi", "英姿", "摸牌阶段可额外摸一张牌。", choices)
            if answer == "yes":
                draw_count += 1
                self._append_log(f"{self._hero_name(player)}发动英姿。")
        if not replaced_draw:
            drawn = self._draw_cards(draw_count, f"{self._hero_name(player)}摸牌阶段")
            if drawn is None:
                return
            for card_id in drawn:
                self._move(card_id, player.hand_zone_id, owner_id=player.player_id,
                           controller_id=player.player_id, visibility=Visibility.OWNER_ONLY)
            self._append_log(f"{self._hero_name(player)}摸了{draw_count}张牌。", private_to=(player.player_id,))
        if player.player_id in self._skip_play:
            self._skip_play.discard(player.player_id)
            self._append_log(f"{self._hero_name(player)}因【乐不思蜀】跳过出牌阶段。")
            self.state.phase = GamePhase.DISCARD
        else:
            self.state.phase = GamePhase.PLAY

    def _preparation_skills(self, player: PlayerState) -> Generator[Any, Any, None]:
        player_id = player.player_id
        if self._has_skill(player_id, "guanxing"):
            answer = yield from self._ask(player_id, "guanxing", "观星",
                                          "可查看牌堆顶至多五张牌，并选择牌堆顶顺序。",
                                          (ChoiceOption("yes", "发动观星", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            if answer == "yes":
                yield from self._resolve_guanxing(player_id)
                if self.finished:
                    return
        if self._has_skill(player_id, "luoshen"):
            answer = yield from self._ask(player_id, "luoshen", "洛神",
                                          "可进行判定；黑色获得判定牌并可继续，红色或主动停止时结束。",
                                          (ChoiceOption("yes", "发动洛神", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            while answer == "yes" and not self.finished and player.alive:
                result = yield from self._judge(player_id, "洛神")
                if result is None or self.finished:
                    return
                if self._color(result) == "black":
                    if result in self._zone("resolving").card_ids:
                        self._move(result, player.hand_zone_id, owner_id=player_id,
                                   controller_id=player_id, visibility=Visibility.OWNER_ONLY)
                    self._append_log("甄姬发动洛神，获得黑色最终判定牌。", private_to=(player_id,))
                    answer = yield from self._ask(player_id, "luoshen", "洛神",
                                                  "本次最终判定为黑色；可继续判定或停止。",
                                                  (ChoiceOption("yes", "继续洛神判定", "yes"),
                                                   ChoiceOption("pass", "停止", "pass")))
                else:
                    self._append_log("洛神最终判定为红色，判定牌不被获得。")
                    yield from self._settle_judgment(player_id, result)
                    break

    def _resolve_guanxing(self, player_id: str) -> Generator[Any, Any, None]:
        count = min(len(self.live_players()), 5)
        revealed = self._draw_cards(count, "诸葛亮观星查看牌")
        if revealed is None:
            return
        for card_id in revealed:
            self.state.cards[card_id].visibility = Visibility.OWNER_ONLY
        self._append_log("诸葛亮观星查看：" + "、".join(self._card_label(item) for item in revealed) + "。",
                         private_to=(player_id,))
        remaining = list(revealed)
        top_order: list[str] = []
        while remaining and not self.finished:
            options = (ChoiceOption("done", "将剩余牌按原顺序置于牌堆底", "done"),) + tuple(
                ChoiceOption(f"top:{card_id}", f"下一张牌堆顶：{self._card_label(card_id)}", "top", card_id)
                for card_id in remaining
            )
            answer = yield from self._ask(player_id, "guanxing_order", "观星排序",
                                          "逐张选择要置于牌堆顶的顺序；完成后剩余牌按原顺序置底。", options)
            if answer == "done":
                break
            card_id = answer.removeprefix("top:")
            if card_id in remaining:
                top_order.append(card_id)
                remaining.remove(card_id)
        bottom_order: list[str] = []
        while remaining and not self.finished:
            options = tuple(
                ChoiceOption(f"bottom:{card_id}", f"下一张牌堆底：{self._card_label(card_id)}", "bottom", card_id)
                for card_id in remaining
            )
            answer = yield from self._ask(player_id, "guanxing_bottom_order", "观星排序",
                                          "选择剩余牌依次置于牌堆底的顺序。", options)
            card_id = answer.removeprefix("bottom:")
            if card_id in remaining:
                bottom_order.append(card_id)
                remaining.remove(card_id)
        if self.finished:
            for card_id in revealed:
                if card_id in self._zone("resolving").card_ids:
                    self._discard_card(card_id)
            return
        draw = self._zone("draw_pile")
        for card_id in reversed(top_order):
            self._move(card_id, draw.zone_id, owner_id=None, controller_id=None,
                       visibility=Visibility.HIDDEN)
            draw.card_ids.remove(card_id)
            draw.card_ids.insert(0, card_id)
        for card_id in bottom_order:
            self._move(card_id, draw.zone_id, owner_id=None, controller_id=None,
                       visibility=Visibility.HIDDEN)
        self._append_log(f"观星将{len(top_order)}张按指定顺序置于牌堆顶，其余{len(bottom_order)}张置于牌堆底。",
                         private_to=(player_id,))

    def _resolve_end_skills(self, player: PlayerState) -> Generator[Any, Any, None]:
        self.state.phase = GamePhase.END
        if player.alive and self._has_skill(player.player_id, "biyue"):
            answer = yield from self._ask(player.player_id, "biyue", "闭月",
                                          "结束阶段可摸一张牌。",
                                          (ChoiceOption("yes", "发动闭月", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            if answer == "yes" and not self.finished:
                drawn = self._draw_cards(1, "貂蝉闭月")
                if drawn is None:
                    return
                self._move(drawn[0], player.hand_zone_id, owner_id=player.player_id,
                           controller_id=player.player_id, visibility=Visibility.OWNER_ONLY)
                self._append_log("貂蝉发动闭月，摸一张牌。", private_to=(player.player_id,))

    def _run_ai_play(self, player: PlayerState) -> Generator[Any, Any, None]:
        iterations = 0
        while not self.finished and player.alive and self.state.phase is GamePhase.PLAY:
            actions = self.available_actions(player.player_id)
            policy = self._ai_for(player.player_id)
            action = policy.choose_action(self.observation_for(player.player_id), actions)
            offered_ids = {candidate.action_id for candidate in actions}
            valid = bool(action and action.action_id in offered_ids
                         and action.intent.actor_id == player.player_id
                         and self.is_legal_intent(action.intent))
            if action is not None and not valid:
                self.ai_issues.append(AIExecutionIssue(
                    player.player_id, self.state.turn_number, "play",
                    (action.action_id,), "selected_action_not_in_legal_action_set",
                ))
                action = next((candidate for candidate in actions
                               if candidate.intent.actor_id == player.player_id
                               and self.is_legal_intent(candidate.intent)), None)
            if action is None:
                break
            yield from self._event("ai_action", player.player_id, self._resolve_intent(action.intent))
            iterations += 1
            if self.display_pacing_enabled and not self._fast_forward and not self.finished:
                yield _DISPLAY_PAUSE
            if iterations >= 12:
                self._append_log("AI本回合操作达到安全上限，进入弃牌阶段。")
                break

    def _finish_human_turn(self) -> Generator[Any, Any, None]:
        player = self.current_player
        if player is None:
            return
        self.state.phase = GamePhase.DISCARD
        yield from self._discard_phase(player)
        if self.finished:
            return
        yield from self._resolve_end_skills(player)
        if self.finished:
            return
        self._end_turn(player)
        self._advance_current_player()
        yield from self._continue_until_human()

    def _discard_phase(self, player: PlayerState) -> Generator[Any, Any, None]:
        if self.finished or not player.alive:
            return
        self.state.phase = GamePhase.DISCARD
        hand = tuple(self._zone(player.hand_zone_id).card_ids)
        excess = max(0, len(hand) - player.hp)
        if excess == 0:
            return
        if (self._has_skill(player.player_id, "keji")
                and player.player_id not in self._played_kill_this_turn):
            answer = yield from self._ask(player.player_id, "keji", "克己",
                                          "本回合出牌阶段没有使用或打出过杀；可跳过弃牌阶段。",
                                          (ChoiceOption("yes", "发动克己，跳过弃牌阶段", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            if answer == "yes":
                self._append_log("吕蒙发动克己，跳过弃牌阶段。")
                return
        options = tuple(ChoiceOption(f"discard:{card_id}", self._card_label(card_id), "discard", card_id) for card_id in hand)
        if player.control is ControlType.HUMAN and player.player_id == "P1" and player.alive:
            choices = yield from self._ask(player.player_id, "discard", "弃牌阶段", f"手牌上限{player.hp}张；当前{len(hand)}张，还需弃置{excess}张。", options, min_choices=excess, max_choices=excess)
        else:
            view = self.observation_for(player.player_id)
            request = DecisionRequest("discard", player.player_id, "弃牌", "", options, excess, excess)
            choices = self._choose_ai_option(view, request)
            if isinstance(choices, str):
                choices = (choices,)
        if isinstance(choices, str):
            choices = (choices,)
        for choice in choices:
            card_id = next(option.value for option in options if option.choice_id == choice)
            yield from self._discard_with_loss_triggers(card_id)
        self._append_log(f"{self._hero_name(player)}弃置{excess}张牌。")

    def _end_turn(self, player: PlayerState) -> None:
        if self.finished:
            return
        self.state.phase = GamePhase.END
        self._append_log(f"{self._hero_name(player)}的回合结束。")

    def _advance_current_player(self) -> None:
        living = self.live_players()
        if not living:
            self._finish("draw", "no_survivors", "没有存活角色，对局平局。")
            return
        if self.state.current_player_id not in {player.player_id for player in living}:
            self.state.current_player_id = living[0].player_id
            return
        index = next(i for i, player in enumerate(living) if player.player_id == self.state.current_player_id)
        self.state.current_player_id = living[(index + 1) % len(living)].player_id
        self.state.phase = GamePhase.PREPARATION

    def _resolve_intent(self, intent: ActionIntent) -> Generator[Any, Any, None]:
        yield from self._event("resolve_action", intent.actor_id, self._resolve_intent_inner(intent))

    def _resolve_intent_inner(self, intent: ActionIntent) -> Generator[Any, Any, None]:
        if not self.is_legal_intent(intent):
            self._append_log("所选操作在确认时已不合法，未支付代价。")
            return
        self._record_public_action(intent)
        actor = self._player(intent.actor_id)
        skill = intent.skill_id
        if skill == "rende":
            selected_cards = intent.cost_card_ids
            if intent.choice == "choose":
                options = tuple(ChoiceOption(f"rende:{card_id}", self._card_label(card_id), "give", card_id)
                                for card_id in self._zone(actor.hand_zone_id).card_ids)
                answer = yield from self._ask(actor.player_id, "rende_cards", "仁德", "选择任意张手牌交给目标角色。", options,
                                               min_choices=1, max_choices=len(options), context={"target_id": intent.target_ids[0]})
                selected_ids = (answer,) if isinstance(answer, str) else answer
                selected_cards = tuple(option.value for option in options if option.choice_id in selected_ids)
            count = len(selected_cards)
            for card_id in selected_cards:
                yield from self._move_with_loss_triggers(
                    card_id, self._player(intent.target_ids[0]).hand_zone_id,
                    owner_id=intent.target_ids[0], controller_id=intent.target_ids[0],
                    visibility=Visibility.OWNER_ONLY)
            self._rende_given[actor.player_id] = self._rende_given.get(actor.player_id, 0) + count
            self._append_log(f"{self._hero_name(actor)}发动仁德，交给{self._hero_name(self._player(intent.target_ids[0]))}{count}张手牌。")
            if self._rende_given[actor.player_id] >= 2 and actor.player_id not in self._rende_heal_used:
                self._rende_heal_used.add(actor.player_id)
                self._recover(actor.player_id, 1)
            return
        if skill == "zhiheng":
            self._used_skill_this_play.add((actor.player_id, skill))
            selected_cards = intent.cost_card_ids
            if intent.choice == "choose":
                candidates = (*self._zone(actor.hand_zone_id).card_ids, *self._zone(actor.equipment_zone_id).card_ids)
                options = tuple(ChoiceOption(f"discard:{card_id}", self._card_label(card_id), "discard", card_id)
                                for card_id in candidates)
                answer = yield from self._ask(actor.player_id, "zhiheng_cards", "制衡", "选择一张或多张手牌与／或装备弃置。", options,
                                               min_choices=1, max_choices=len(options))
                selected_ids = (answer,) if isinstance(answer, str) else answer
                selected_cards = tuple(option.value for option in options if option.choice_id in selected_ids)
            count = len(selected_cards)
            yield from self._discard_many_with_loss_triggers(tuple(selected_cards))
            if self.finished:
                return
            self._append_log(f"{self._hero_name(actor)}发动制衡，弃置{count}张牌并摸牌。")
            drawn = self._draw_cards(count, "孙权制衡")
            if drawn is None:
                return
            for card_id in drawn:
                self._move(card_id, actor.hand_zone_id, owner_id=actor.player_id,
                           controller_id=actor.player_id, visibility=Visibility.OWNER_ONLY)
            return
        if skill == "fanjian":
            self._used_skill_this_play.add((actor.player_id, skill))
            yield from self._resolve_fanjian(actor.player_id, intent.target_ids[0])
            return
        if skill == "qingnang":
            self._used_skill_this_play.add((actor.player_id, skill))
            options = tuple(ChoiceOption(f"discard:{card_id}", self._card_label(card_id), "discard", card_id)
                            for card_id in self._zone(actor.hand_zone_id).card_ids)
            choice = yield from self._ask(actor.player_id, "qingnang_cost", "青囊",
                                          "弃置一张手牌并令一名受伤角色回复1点体力。", options)
            cost_id = choice.removeprefix("discard:")
            yield from self._discard_with_loss_triggers(cost_id)
            if not self.finished and self._player(intent.target_ids[0]).alive:
                self._recover(intent.target_ids[0], 1)
                self._append_log(f"华佗发动青囊，{self._hero_name(self._player(intent.target_ids[0]))}回复1点体力。")
            return
        if skill == "kurou":
            actor.hp -= 1
            self._append_log(f"黄盖发动苦肉，失去1点体力（当前{actor.hp}）。")
            if actor.hp <= 0:
                rescued = yield from self._rescue(actor.player_id)
                if not rescued:
                    self._kill_player(actor.player_id, None)
            if self.finished or not actor.alive:
                return
            drawn = self._draw_cards(2, "黄盖苦肉")
            if drawn is None:
                return
            for card_id in drawn:
                self._move(card_id, actor.hand_zone_id, owner_id=actor.player_id,
                           controller_id=actor.player_id, visibility=Visibility.OWNER_ONLY)
            self._append_log("黄盖苦肉存活，摸两张牌。", private_to=(actor.player_id,))
            return
        if skill == "jieyin":
            self._used_skill_this_play.add((actor.player_id, skill))
            selected_cards = intent.cost_card_ids
            if intent.choice == "choose":
                options = tuple(ChoiceOption(f"discard:{card_id}", self._card_label(card_id), "discard", card_id)
                                for card_id in self._zone(actor.hand_zone_id).card_ids)
                answer = yield from self._ask(actor.player_id, "jieyin_cost", "结姻",
                                              "选择两张手牌弃置。", options, min_choices=2, max_choices=2)
                selected = (answer,) if isinstance(answer, str) else answer
                selected_cards = tuple(option.value for option in options if option.choice_id in selected)
            yield from self._discard_many_with_loss_triggers(tuple(selected_cards))
            if self.finished:
                return
            target = self._player(intent.target_ids[0])
            self._recover(actor.player_id, 1)
            if target.alive:
                self._recover(target.player_id, 1)
            self._append_log(f"孙尚香发动结姻，自己与{self._hero_name(target)}各回复1点体力。")
            return
        if skill == "lijian":
            self._used_skill_this_play.add((actor.player_id, skill))
            yield from self._discard_with_loss_triggers(intent.cost_card_ids[0])
            if self.finished:
                return
            other_by_initiator = {
                target_id: next(item for item in intent.target_ids if item != target_id)
                for target_id in intent.target_ids
            }
            initiator_options = tuple(
                ChoiceOption(f"initiator:{target_id}", f"由{self._hero_name(self._player(target_id))}发起决斗", "target", target_id)
                for target_id in intent.target_ids
                if not (self._has_skill(other_by_initiator[target_id], "kongcheng")
                        and not self._zone(self._player(
                            other_by_initiator[target_id]).hand_zone_id).card_ids)
            )
            initiator_choice = yield from self._ask(actor.player_id, "lijian_initiator", "离间",
                                                    "选择其中一名男性角色作为决斗发起方。", initiator_options)
            initiator = initiator_choice.removeprefix("initiator:")
            other = next(target_id for target_id in intent.target_ids if target_id != initiator)
            self._append_log(f"貂蝉发动离间，由{self._hero_name(self._player(initiator))}对{self._hero_name(self._player(other))}进行决斗。")
            yield from self._resolve_duel(initiator, other, None)
            return
        if skill == "jijiang":
            provided = yield from self._resolve_jijiang_kill(
                actor.player_id, intent.target_ids[0], response=False)
            if provided:
                self._kill_uses[actor.player_id] = self._kill_uses.get(actor.player_id, 0) + 1
            return

        is_wusheng = skill == "wusheng"
        is_longdan = skill == "longdan"
        is_spear = skill == "serpent_spear"
        is_qixi = skill == "qixi"
        is_guose = skill == "guose"
        card_id = intent.cost_card_ids[0] if (is_wusheng or is_longdan or is_spear or is_qixi or is_guose) else intent.card_id
        material_ids = intent.cost_card_ids if is_spear else (card_id,)
        definition = self._definition(card_id)
        kill_target_ids = intent.target_ids
        if (skill is None and definition.name == "杀"
                and len(self._zone(actor.hand_zone_id).card_ids) == 1
                and self._has_equipment(actor.player_id, "halberd")):
            extra_candidates = tuple(target_id for target_id in self.kill_targets(actor.player_id)
                                     if target_id != intent.target_ids[0])
            if extra_candidates:
                options = tuple(ChoiceOption(f"target:{target_id}", self._hero_name(self._player(target_id)), "target", target_id)
                                for target_id in extra_candidates)
                chosen = yield from self._ask(actor.player_id, "halberd_targets", "方天画戟",
                                              "此杀是最后一张手牌，可再选择至多两名合法目标；不选则只结算原目标。",
                                              options, min_choices=0, max_choices=min(2, len(options)))
                selected = (chosen,) if isinstance(chosen, str) else chosen
                extras = tuple(option.value for option in options if option.choice_id in selected)
                locked = set((*kill_target_ids, *extras))
                kill_target_ids = tuple(item.player_id for item in self._clockwise_order(actor.player_id)
                                         if item.player_id in locked)
                self._append_log(f"方天画戟锁定{len(kill_target_ids)}名目标，按行动顺序结算。")
        if is_spear:
            for material_id in material_ids:
                if material_id in self._zone(actor.hand_zone_id).card_ids:
                    yield from self._move_with_loss_triggers(material_id, "resolving", owner_id=actor.player_id,
                                                            controller_id=actor.player_id, visibility=Visibility.PUBLIC)
        elif card_id in self._zone(actor.equipment_zone_id).card_ids or card_id in self._zone(actor.hand_zone_id).card_ids:
            yield from self._move_with_loss_triggers(card_id, "resolving", owner_id=actor.player_id,
                                                    controller_id=actor.player_id, visibility=Visibility.PUBLIC)
        if self.finished:
            for material_id in material_ids:
                if self._zone("resolving").card_ids.count(material_id):
                    self._discard_card(material_id)
            return
        display_name = "杀" if (is_wusheng or is_longdan or is_spear) else "过河拆桥" if is_qixi else "乐不思蜀" if is_guose else definition.name
        skill_label = "武圣" if is_wusheng else "龙胆" if is_longdan else "丈八蛇矛" if is_spear else "奇袭" if is_qixi else "国色" if is_guose else None
        self._append_log(f"{self._hero_name(actor)}{'发动' + skill_label + '，' if skill_label else '使用'}【{display_name}】。")
        display_targets = kill_target_ids
        if display_name in {"南蛮入侵", "万箭齐发", "五谷丰登", "桃园结义"}:
            display_targets = tuple(player.player_id for player in self._clockwise_order(
                actor.player_id, include_start=display_name in {"五谷丰登", "桃园结义"}) if player.alive)
        elif display_name in {"桃", "无中生有", "闪电"}:
            display_targets = (actor.player_id,)
        yield from self._present_action("play", actor.player_id, card_ids=tuple(material_ids),
                                        target_ids=display_targets,
                                        label=f"{self._hero_name(actor)}使用【{display_name}】",
                                        effective_name=display_name)
        effective_trick_kind = ("dismantle" if is_qixi else "indulgence" if is_guose
                                else None if (is_spear or is_wusheng or is_longdan)
                                else definition.kind_id)
        effective_kind = next((item for item in CARD_KIND_BY_NAME.values()
                               if effective_trick_kind and item.kind_id == effective_trick_kind), None)
        if self._has_skill(actor.player_id, "jizhi") and effective_kind and effective_kind.subtype == "immediate":
            answer = yield from self._ask(actor.player_id, "jizhi", "集智",
                                          "使用非延时锦囊开始结算前，可摸一张牌。",
                                          (ChoiceOption("yes", "发动集智", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            if answer == "yes":
                drawn = self._draw_cards(1, "黄月英集智")
                if drawn is None:
                    if self._zone("resolving").card_ids.count(card_id):
                        self._discard_card(card_id)
                    return
                self._move(drawn[0], actor.hand_zone_id, owner_id=actor.player_id,
                           controller_id=actor.player_id, visibility=Visibility.OWNER_ONLY)
                self._append_log("黄月英发动集智，摸一张牌。", private_to=(actor.player_id,))
        if is_wusheng or is_longdan:
            self._kill_uses[actor.player_id] = self._kill_uses.get(actor.player_id, 0) + 1
            self._played_kill_this_turn.add(actor.player_id)
            yield from self._resolve_kill(actor.player_id, intent.target_ids[0], card_id, active_play=True)
        elif is_qixi:
            if not (yield from self._nullification_window(intent.target_ids[0], card_id, trick_kind_id="dismantle")):
                yield from self._resolve_dismantle(actor.player_id, intent.target_ids[0], intent.choice, card_id)
        elif is_guose:
            target_id = intent.target_ids[0]
            if not (yield from self._nullification_window(target_id, card_id, trick_kind_id="indulgence")):
                self._move(card_id, self._player(target_id).judgment_zone_id,
                           owner_id=target_id, controller_id=target_id, visibility=Visibility.PUBLIC)
        elif definition.name == "杀" or is_spear:
            self._kill_uses[actor.player_id] = self._kill_uses.get(actor.player_id, 0) + 1
            self._played_kill_this_turn.add(actor.player_id)
            virtual_color = self._combined_card_color(intent.cost_card_ids) if is_spear else None
            virtual = is_spear
            liuli_resolved = len(kill_target_ids) > 1
            if liuli_resolved:
                redirected_targets = []
                for target_id in kill_target_ids:
                    if self.finished:
                        break
                    redirected_targets.append(
                        (yield from self._try_liuli_redirect(actor.player_id, target_id)))
                order = {player.player_id: index for index, player in enumerate(
                    self._clockwise_order(actor.player_id, include_start=False))}
                kill_target_ids = tuple(sorted(redirected_targets, key=order.__getitem__))
            for target_id in kill_target_ids:
                if self.finished:
                    break
                yield from self._resolve_kill(actor.player_id, target_id,
                                              None if virtual else card_id,
                                              active_play=True,
                                              liuli_resolved=liuli_resolved,
                                              card_color_override=virtual_color,
                                              virtual_card=virtual)
        elif definition.name == "桃":
            self._recover(actor.player_id, 1)
        elif definition.name == "决斗":
            target_id = intent.target_ids[0]
            if not (yield from self._nullification_window(target_id, card_id)):
                yield from self._resolve_duel(actor.player_id, target_id, card_id)
        elif definition.name == "过河拆桥":
            target_id = intent.target_ids[0]
            if not (yield from self._nullification_window(target_id, card_id)):
                yield from self._resolve_dismantle(actor.player_id, target_id, intent.choice, card_id)
        elif definition.name == "顺手牵羊":
            target_id = intent.target_ids[0]
            if not (yield from self._nullification_window(target_id, card_id)):
                yield from self._resolve_steal(actor.player_id, target_id, intent.choice, card_id)
        elif definition.name == "借刀杀人":
            wielder_id = intent.target_ids[0]
            if not (yield from self._nullification_window(wielder_id, card_id)):
                yield from self._resolve_borrow_sword(actor.player_id, wielder_id, card_id)
        elif definition.name == "无中生有":
            if not (yield from self._nullification_window(actor.player_id, card_id)):
                drawn = self._draw_cards(2, "无中生有")
                if drawn is not None:
                    for item in drawn:
                        self._move(item, actor.hand_zone_id, owner_id=actor.player_id,
                                   controller_id=actor.player_id, visibility=Visibility.OWNER_ONLY)
        elif definition.name == "南蛮入侵":
            yield from self._resolve_barbarians(actor.player_id, card_id)
        elif definition.name == "万箭齐发":
            yield from self._resolve_arrows(actor.player_id, card_id)
        elif definition.name == "桃园结义":
            yield from self._resolve_peach_garden(actor.player_id, card_id)
        elif definition.name == "五谷丰登":
            yield from self._resolve_harvest(actor.player_id, card_id)
        elif definition.name == "乐不思蜀":
            target_id = intent.target_ids[0]
            if not (yield from self._nullification_window(target_id, card_id)):
                self._move(card_id, self._player(target_id).judgment_zone_id,
                           owner_id=target_id, controller_id=target_id, visibility=Visibility.PUBLIC)
        elif definition.name == "闪电":
            self._move(card_id, actor.judgment_zone_id, owner_id=actor.player_id,
                       controller_id=actor.player_id, visibility=Visibility.PUBLIC)
        elif definition.category is CardCategory.EQUIPMENT:
            yield from self._equip_card(actor.player_id, card_id)

        final_log = next((log.text for log in reversed(self.logs) if not log.private_to), "")
        yield from self._present_action("result", actor.player_id, label=final_log)
        if self.state.event_stack:
            self._assert_invariants()
        for material_id in material_ids:
            if self._zone("resolving").card_ids.count(material_id):
                self._discard_card(material_id)

    def _resolve_kill(self, source_id: str, target_id: str, card_id: str | None, *, active_play: bool,
                      locked_followup: bool = False, card_color_override: str | None = None,
                      virtual_card: bool = False, liuli_resolved: bool = False) -> Generator[Any, Any, None]:
        if self.finished or not self._player(target_id).alive:
            return
        if active_play and source_id == self.state.current_player_id and self.state.phase is GamePhase.PLAY:
            self._played_kill_this_turn.add(source_id)
        actual_target_id = (target_id if liuli_resolved
                            else (yield from self._try_liuli_redirect(source_id, target_id)))
        target = self._player(actual_target_id)
        if self.finished or not target.alive:
            return
        card_color = card_color_override if virtual_card else (self._color(card_id) if card_id else None)
        ignore_armor = self._has_equipment(source_id, "qinggang_sword")
        if self._has_equipment(actual_target_id, "renwang_shield") and card_color == "black" and not ignore_armor:
            self._append_log(f"仁王盾使黑色【杀】对{self._hero_name(target)}无效。")
            return
        self._append_log(f"【杀】已锁定{self._hero_name(target)}为实际目标。")
        if (self._has_equipment(source_id, "double_swords")
                and HERO_BY_ID[self._player(source_id).hero_id].gender
                is not HERO_BY_ID[target.hero_id].gender):
            yield from self._resolve_double_swords(source_id, actual_target_id)
            if self.finished:
                return
        forbidden_flash = False
        if self._has_skill(source_id, "tieji"):
            answer = yield from self._ask(source_id, "tieji", "铁骑",
                                          f"可令{self._hero_name(target)}判定；若为红色，此杀不能以闪响应。",
                                          (ChoiceOption("yes", "发动铁骑", "yes"),
                                           ChoiceOption("pass", "不发动", "pass")))
            if answer == "yes":
                result = yield from self._judge(actual_target_id, "铁骑")
                if result is None or self.finished:
                    return
                forbidden_flash = self._color(result) == "red"
                # 铁骑的判定由马超发起并归马超所有；目标只承受该判定结果。
                yield from self._settle_judgment(source_id, result)
                if forbidden_flash:
                    self._append_log("铁骑最终判定为红色，该目标不能以闪响应此杀。")
        dodged = False if forbidden_flash else (yield from self._ask_flash(
            actual_target_id, source_id, card_id,
            allow_bagua=not ignore_armor,
            required_count=2 if self._has_skill(source_id, "wushuang") else 1))
        if not dodged:
            if (self._has_equipment(source_id, "frost_sword")
                    and (self._zone(target.hand_zone_id).card_ids or self._zone(target.equipment_zone_id).card_ids)):
                options = (ChoiceOption("yes", "发动寒冰剑，防止伤害并弃牌", "yes"),
                           ChoiceOption("pass", "不发动寒冰剑", "pass"))
                answer = yield from self._ask(source_id, "frost_sword", "寒冰剑",
                                              "杀即将造成伤害；可防止伤害并弃置目标至多两张手牌或装备。",
                                              options)
                if answer == "yes":
                    count = 0
                    while count < 2:
                        candidates = (*self._zone(target.hand_zone_id).card_ids,
                                      *self._zone(target.equipment_zone_id).card_ids)
                        if not candidates:
                            break
                        selected, _area = yield from self._choose_target_card(source_id, actual_target_id,
                                                                             "hand" if not self._zone(target.equipment_zone_id).card_ids else None,
                                                                             "寒冰剑")
                        if not selected:
                            break
                        yield from self._discard_with_loss_triggers(selected)
                        count += 1
                        if self.finished:
                            return
                    self._append_log("寒冰剑防止本次伤害，已按顺序弃置合法手牌或装备。")
                    return
            yield from self._damage(source_id, actual_target_id, 1,
                                    None if virtual_card else card_id, damage_kind="杀")
            return

        axe_id = self._equipment_id(source_id, "axe")
        if axe_id:
            costs = self._axe_cost_options(source_id, axe_id)
            if len(costs) >= 2:
                choice_options = tuple(ChoiceOption(f"discard:{item}", self._card_label(item), "discard", item) for item in costs)
                options = (ChoiceOption("pass", "不发动贯石斧", "pass"), *choice_options)
                answer = yield from self._ask(source_id, "axe_payment", "贯石斧", "【杀】已被闪抵消。可同时弃置两张其他牌使原杀继续生效。", options, min_choices=1, max_choices=2)
                if answer and answer != "pass":
                    selected = answer if isinstance(answer, tuple) else (answer,)
                    if len(selected) == 2:
                        yield from self._discard_many_with_loss_triggers(
                            tuple(item.removeprefix("discard:") for item in selected))
                        if self.finished:
                            return
                        self._append_log("贯石斧同时弃置两张牌；原杀不重新检查距离。")
                        yield from self._damage(source_id, actual_target_id, 1,
                                                None if virtual_card else card_id,
                                                damage_kind="贯石斧")
                        return

        if (self._has_equipment(source_id, "qinglong_blade")
                and actual_target_id in self.kill_targets(source_id, locked_followup=True)):
            available = self._kill_response_sources(source_id)
            has_spear_payment = (self._has_equipment(source_id, "serpent_spear")
                                 and len(self._zone(self._player(source_id).hand_zone_id).card_ids) >= 2)
            if available or has_spear_payment:
                options = (ChoiceOption("stop", "停止追杀", "pass"),) + tuple(
                    ChoiceOption(f"continue:{item}", f"再使用【杀】（{self._card_label(item)}）", "continue", item)
                    for item in available
                )
                if has_spear_payment:
                    options += (ChoiceOption("continue:serpent_spear", "丈八蛇矛：两张手牌当【杀】", "continue"),)
                answer = yield from self._ask(source_id, "qinglong_followup", "青龙偃月刀", "刚才的杀被闪抵消，可对同一实际目标继续追杀。", options)
                if answer == "continue:serpent_spear":
                    hand = tuple(self._zone(self._player(source_id).hand_zone_id).card_ids)
                    costs = tuple(ChoiceOption(f"cost:{item}", self._card_label(item), "discard", item) for item in hand)
                    selected = yield from self._ask(source_id, "serpent_spear_cost", "丈八蛇矛",
                                                    "同时选择两张手牌作为一张【杀】。",
                                                    costs, min_choices=2, max_choices=2)
                    selected_ids = (selected,) if isinstance(selected, str) else selected
                    materials = tuple(option.value for option in costs if option.choice_id in selected_ids)
                    if len(materials) != 2:
                        return
                    for material in materials:
                        yield from self._move_with_loss_triggers(material, "resolving", owner_id=source_id,
                                                                controller_id=source_id, visibility=Visibility.PUBLIC)
                        if self.finished:
                            for item in materials:
                                if item in self._zone("resolving").card_ids:
                                    self._discard_card(item)
                            return
                    first, *extras = materials
                    self._response_extra_materials[first] = tuple(extras)
                    self._response_virtual_colors[first] = self._combined_card_color(materials)
                    self._append_log(f"青龙刀对{self._hero_name(target)}以丈八蛇矛继续使用【杀】。")
                    self._kill_uses[source_id] = self._kill_uses.get(source_id, 0) + (1 if active_play else 0)
                    yield from self._resolve_kill(source_id, actual_target_id, first,
                                                  active_play=active_play, locked_followup=True,
                                                  card_color_override=self._response_virtual_colors[first],
                                                  virtual_card=True)
                    self._discard_response_materials(first)
                elif answer and answer.startswith("continue:"):
                    follow_card = answer.split(":", 1)[1]
                    yield from self._move_with_loss_triggers(follow_card, "resolving", owner_id=source_id,
                                                            controller_id=source_id, visibility=Visibility.PUBLIC)
                    if self.finished:
                        if follow_card in self._zone("resolving").card_ids:
                            self._discard_card(follow_card)
                        return
                    self._append_log(f"青龙刀对{self._hero_name(target)}继续使用【杀】；此为同一追杀链。")
                    self._kill_uses[source_id] = self._kill_uses.get(source_id, 0) + (1 if active_play else 0)
                    yield from self._resolve_kill(source_id, actual_target_id, follow_card, active_play=active_play, locked_followup=True)
                    if self._zone("resolving").card_ids.count(follow_card):
                        self._discard_card(follow_card)

    def _try_liuli_redirect(self, source_id: str, target_id: str) -> Generator[Any, Any, str]:
        target = self._player(target_id)
        if not target.alive or not self._has_skill(target_id, "liuli"):
            return target_id
        candidates = (*self._zone(target.hand_zone_id).card_ids,
                      *self._zone(target.equipment_zone_id).card_ids)
        eligible: dict[str, tuple[str, ...]] = {}
        for card_id in candidates:
            legal = tuple(item for item in self.kill_targets(target_id, cost_card_ids=(card_id,))
                          if item not in {source_id, target_id})
            if legal:
                eligible[card_id] = legal
        if not eligible:
            return target_id
        options = (ChoiceOption("pass", "不发动流离", "pass"),) + tuple(
            ChoiceOption(f"discard:{card_id}", f"弃置一张牌（{self._card_label(card_id)}）并转移杀", "discard", card_id)
            for card_id in eligible
        )
        answer = yield from self._ask(target_id, "liuli", "流离",
                                      "可弃置一张手牌或装备，将此杀转移给另一名攻击范围内的合法角色。",
                                      options, context={"source_id": source_id, "original_target_id": target_id})
        if not answer or answer == "pass":
            return target_id
        cost_id = answer.removeprefix("discard:")
        legal = eligible.get(cost_id, ())
        if not legal:
            return target_id
        yield from self._discard_with_loss_triggers(cost_id)
        if self.finished:
            return target_id
        choices = tuple(ChoiceOption(f"target:{candidate}", self._hero_name(self._player(candidate)), "target", candidate)
                        for candidate in legal if self._player(candidate).alive)
        if not choices:
            return target_id
        chosen = yield from self._ask(target_id, "liuli_target", "流离",
                                      "选择流离后的杀目标；此选择按弃牌后的攻击范围检查。", choices,
                                      context={"source_id": source_id})
        actual = chosen.removeprefix("target:")
        self._append_log(f"大乔发动流离，杀转移至{self._hero_name(self._player(actual))}。")
        yield from self._present_action("retarget", source_id, target_ids=(actual,),
                                        label=f"流离：杀转移至{self._hero_name(self._player(actual))}")
        return actual

    def _resolve_double_swords(self, source_id: str, target_id: str) -> Generator[Any, Any, None]:
        source = self._player(source_id)
        target = self._player(target_id)
        options = (ChoiceOption("yes", "发动雌雄双股剑", "yes"),
                   ChoiceOption("pass", "不发动", "pass"))
        answer = yield from self._ask(source_id, "double_swords", "雌雄双股剑",
                                      "以杀指定异性后，可令目标弃一张手牌或令自己摸一张牌。", options)
        if answer != "yes":
            return
        hand = tuple(self._zone(target.hand_zone_id).card_ids)
        if not hand:
            selected = "draw"
        else:
            choices = (ChoiceOption("draw", f"令{self._hero_name(source)}摸一张牌", "draw"),) + tuple(
                ChoiceOption(f"discard:{card_id}", f"弃置手牌（{self._card_label(card_id)}）", "discard", card_id)
                for card_id in hand
            )
            selected = yield from self._ask(target_id, "double_swords_target", "雌雄双股剑",
                                            "选择弃置一张手牌，或令攻击者摸一张牌。", choices)
        if selected.startswith("discard:"):
            card_id = selected.removeprefix("discard:")
            if card_id in self._zone(target.hand_zone_id).card_ids:
                yield from self._discard_with_loss_triggers(card_id)
        else:
            drawn = self._draw_cards(1, "雌雄双股剑")
            if drawn is None:
                return
            self._move(drawn[0], source.hand_zone_id, owner_id=source_id,
                       controller_id=source_id, visibility=Visibility.OWNER_ONLY)

    def _settle_judgment(self, owner_id: str, card_id: str) -> Generator[Any, Any, None]:
        player = self._player(owner_id)
        if card_id not in self._zone("resolving").card_ids:
            return
        if player.alive and self._has_skill(owner_id, "tiandu"):
            choices = (ChoiceOption("yes", "发动天妒，获得最终判定牌", "yes"),
                       ChoiceOption("pass", "不发动", "pass"))
            answer = yield from self._ask(owner_id, "tiandu", "天妒",
                                          "自己的判定牌最终生效后，可获得该牌。", choices)
            if answer == "yes" and card_id in self._zone("resolving").card_ids:
                self._move(card_id, player.hand_zone_id, owner_id=owner_id,
                           controller_id=owner_id, visibility=Visibility.OWNER_ONLY)
                self._append_log("郭嘉发动天妒，获得最终判定牌。", private_to=(owner_id,))
                return
        if card_id in self._zone("resolving").card_ids:
            self._discard_card(card_id)

    def _ask_flash(self, target_id: str, source_id: str, source_card_id: str | None, *,
                   allow_bagua: bool = True, allow_hujia: bool = True,
                   required_count: int = 1) -> Generator[Any, Any, bool]:
        target = self._player(target_id)
        for _ in range(required_count):
            bagua_used = False
            hujia_used = False
            while True:
                choices: list[ChoiceOption] = [ChoiceOption("pass", "放弃响应", "pass")]
                hand = tuple(self._zone(target.hand_zone_id).card_ids)
                for card_id in hand:
                    name = self._definition(card_id).name
                    if name == "闪":
                        choices.append(ChoiceOption(f"flash:{card_id}", f"打出【闪】（{self._card_point_label(card_id)}）", "flash", card_id))
                    if self._has_skill(target_id, "qingguo") and self._color(card_id) == "black":
                        choices.append(ChoiceOption(f"qingguo:{card_id}", f"倾国：黑色手牌当【闪】（{self._card_point_label(card_id)}）", "flash", card_id))
                    if self._has_skill(target_id, "longdan") and name == "杀":
                        choices.append(ChoiceOption(f"longdan:{card_id}", f"龙胆：手牌【杀】当【闪】（{self._card_point_label(card_id)}）", "flash", card_id))
                if allow_bagua and not bagua_used and self._has_equipment(target_id, "bagua_formation"):
                    choices.append(ChoiceOption("bagua", "发动八卦阵判定", "bagua"))
                if allow_hujia and not hujia_used and self._can_hujia(target_id) and self._hujia_providers(target_id):
                    choices.append(ChoiceOption("hujia", "发动护驾", "hujia"))
                if len(choices) == 1:
                    return False
                answer = yield from self._ask(target_id, "flash", "闪响应",
                                              f"{self._hero_name(target)}需要为【杀】打出第{_ + 1}张【闪】。",
                                              tuple(choices), context={"target_id": target_id, "source_id": source_id})
                if answer == "pass":
                    return False
                if answer.startswith(("flash:", "qingguo:", "longdan:")):
                    card_id = answer.split(":", 1)[1]
                    yield from self._discard_with_loss_triggers(card_id)
                    self._append_log(f"{self._hero_name(target)}打出或视为打出【闪】。")
                    yield from self._present_action("response", target_id, card_ids=(card_id,),
                                                    label=f"{self._hero_name(target)}打出【闪】",
                                                    effective_name="闪")
                    if self.finished:
                        return False
                    break
                if answer == "hujia":
                    hujia_used = True
                    if (yield from self._resolve_hujia(target_id)):
                        break
                    continue
                if answer == "bagua":
                    bagua_used = True
                    result = yield from self._judge(target_id, "八卦阵")
                    if self.finished:
                        return False
                    if result and self._color(result) == "red":
                        self._append_log("八卦阵判定为红色，视为打出一张无色闪。")
                        yield from self._settle_judgment(target_id, result)
                        break
                    self._append_log("八卦阵判定未能提供闪。")
                    if result:
                        yield from self._settle_judgment(target_id, result)
                    continue
                return False
        return True

    def _resolve_hujia(self, lord_id: str) -> Generator[Any, Any, bool]:
        for provider in self._hujia_providers(lord_id):
            flashes = [card_id for card_id in self._zone(provider.hand_zone_id).card_ids if self._definition(card_id).name == "闪"]
            if not flashes:
                continue
            options = (ChoiceOption("pass", "不提供【闪】", "pass"),) + tuple(
                ChoiceOption(f"flash:{card_id}", f"提供【闪】（{self._card_point_label(card_id)}）", "flash", card_id)
                for card_id in flashes
            )
            answer = yield from self._ask(provider.player_id, "hujia", "护驾", f"曹操请求提供【闪】；{self._hero_name(provider)}可以响应。", options, context={"target_id": lord_id})
            if answer and answer.startswith("flash:"):
                card_id = answer.split(":", 1)[1]
                self._discard_card(card_id)
                self._append_log(f"{self._hero_name(provider)}提供【闪】；该闪视为曹操使用或打出。")
                yield from self._present_action("response", provider.player_id, card_ids=(card_id,),
                                                label=f"{self._hero_name(provider)}提供【闪】", effective_name="闪")
                return True
        self._append_log("护驾无人提供【闪】。")
        return False

    def _resolve_duel(self, source_id: str, target_id: str, card_id: str) -> Generator[Any, Any, None]:
        responder_id = target_id
        prior_id = source_id
        while not self.finished and self._player(responder_id).alive and self._player(prior_id).alive:
            required = 2 if self._has_skill(prior_id, "wushuang") else 1
            failed = False
            for response_index in range(required):
                response = yield from self._ask_kill_response(responder_id, "决斗", prior_id)
                if response is None:
                    failed = True
                    break
                used_card, _used_by = response
                self._discard_response_materials(used_card)
                self._append_log(f"{self._hero_name(self._player(responder_id))}为决斗打出第{response_index + 1}张【杀】。")
            if failed:
                self._append_log(f"{self._hero_name(self._player(responder_id))}未能打出【杀】，受到{self._hero_name(self._player(prior_id))}造成的1点伤害。")
                yield from self._damage(prior_id, responder_id, 1, card_id, damage_kind="决斗")
                return
            prior_id, responder_id = responder_id, prior_id

    def _ask_kill_response(self, player_id: str, reason: str, opponent_id: str) -> Generator[Any, Any, tuple[str | None, str] | None]:
        player = self._player(player_id)
        choices: list[ChoiceOption] = [ChoiceOption("pass", "放弃响应", "pass")]
        for card_id in self._zone(player.hand_zone_id).card_ids:
            name = self._definition(card_id).name
            if name == "杀":
                choices.append(ChoiceOption(f"kill:{card_id}", f"打出【杀】（{self._card_point_label(card_id)}）", "kill", card_id))
            if self._has_skill(player_id, "longdan") and name == "闪":
                choices.append(ChoiceOption(f"longdan:{card_id}", f"龙胆：手牌【闪】当【杀】（{self._card_point_label(card_id)}）", "kill", card_id))
        if self._has_skill(player_id, "wusheng"):
            for card_id in self._red_sources(player_id):
                if (reason == "借刀杀人"
                        and card_id in self._zone(player.equipment_zone_id).card_ids
                        and opponent_id not in self.kill_targets(
                            player_id, cost_card_ids=(card_id,))):
                    continue
                choices.append(ChoiceOption(f"wusheng:{card_id}", f"武圣当【杀】（{self._card_point_label(card_id)}）", "kill", card_id))
        if self._is_lord(player_id) and self._has_skill(player_id, "jijiang") and self._jijiang_providers(player_id):
            choices.append(ChoiceOption("jijiang", "发动激将", "jijiang"))
        if self._has_equipment(player_id, "serpent_spear") and len(self._zone(player.hand_zone_id).card_ids) >= 2:
            choices.append(ChoiceOption("serpent_spear", "丈八蛇矛：两张手牌当【杀】", "kill"))
        if len(choices) == 1:
            return None
        answer = yield from self._ask(player_id, "duel_kill", reason, f"请为【{reason}】打出【杀】。", tuple(choices), context={"target_id": opponent_id})
        if not answer or answer == "pass":
            return None
        if answer == "jijiang":
            provided = yield from self._resolve_jijiang_kill(player_id, opponent_id, response=True)
            if provided and player_id == self.state.current_player_id and self.state.phase is GamePhase.PLAY:
                self._played_kill_this_turn.add(player_id)
            return provided
        if answer == "serpent_spear":
            cards = tuple(self._zone(player.hand_zone_id).card_ids)
            options = tuple(ChoiceOption(f"cost:{card_id}", self._card_label(card_id), "discard", card_id)
                            for card_id in cards)
            selected = yield from self._ask(player_id, "serpent_spear_cost", "丈八蛇矛",
                                            "同时选择两张手牌作为一张【杀】。",
                                            options, min_choices=2, max_choices=2)
            selected_ids = (selected,) if isinstance(selected, str) else selected
            materials = tuple(option.value for option in options if option.choice_id in selected_ids)
            if len(materials) != 2:
                return None
            for card_id in materials:
                yield from self._move_with_loss_triggers(card_id, "resolving", owner_id=player_id,
                                                        controller_id=player_id, visibility=Visibility.PUBLIC)
                if self.finished:
                    for item in materials:
                        if item in self._zone("resolving").card_ids:
                            self._discard_card(item)
                    return None
            first, *extras = materials
            self._response_extra_materials[first] = tuple(extras)
            self._response_virtual_colors[first] = self._combined_card_color(materials)
            yield from self._present_action("response", player_id, card_ids=tuple(materials),
                                            label=f"{self._hero_name(player)}打出【杀】", effective_name="杀")
            if player_id == self.state.current_player_id and self.state.phase is GamePhase.PLAY:
                self._played_kill_this_turn.add(player_id)
            return first, player_id
        prefix, card_id = answer.split(":", 1)
        yield from self._move_with_loss_triggers(card_id, "resolving", owner_id=player_id,
                                                controller_id=player_id, visibility=Visibility.PUBLIC)
        yield from self._present_action("response", player_id, card_ids=(card_id,),
                                        label=f"{self._hero_name(player)}打出【杀】", effective_name="杀")
        if player_id == self.state.current_player_id and self.state.phase is GamePhase.PLAY:
            self._played_kill_this_turn.add(player_id)
        return card_id, player_id

    def _discard_response_materials(self, card_id: str | None) -> None:
        if not card_id:
            return
        extra = self._response_extra_materials.pop(card_id, ())
        for item in (card_id, *extra):
            if item in self._zone("resolving").card_ids:
                self._discard_card(item)
        self._response_virtual_colors.pop(card_id, None)

    def _resolve_jijiang_kill(self, lord_id: str, target_id: str, *, response: bool) -> Generator[Any, Any, tuple[str | None, str] | None]:
        for provider in self._jijiang_providers(lord_id):
            options = self._jijiang_options(provider.player_id)
            if not options:
                continue
            choices = (ChoiceOption("pass", "不提供【杀】", "pass"),) + tuple(
                ChoiceOption(f"provide:{kind}:{card_id}", label, "kill", (kind, card_id))
                for kind, card_id, label in options
            )
            answer = yield from self._ask(provider.player_id, "jijiang", "激将", f"刘备请求提供【杀】；{self._hero_name(provider)}可以响应。", choices, context={"target_id": target_id})
            if answer and answer.startswith("provide:"):
                _, kind, card_id = answer.split(":", 2)
                materials = tuple(card_id.split("|")) if kind == "serpent_spear" else (card_id,)
                for material in materials:
                    yield from self._move_with_loss_triggers(material, "resolving", owner_id=provider.player_id,
                                                            controller_id=provider.player_id, visibility=Visibility.PUBLIC)
                    if self.finished:
                        for item in materials:
                            if item in self._zone("resolving").card_ids:
                                self._discard_card(item)
                        return None
                used_card = materials[0]
                virtual = kind == "serpent_spear"
                if virtual:
                    self._response_extra_materials[used_card] = materials[1:]
                    self._response_virtual_colors[used_card] = self._combined_card_color(materials)
                self._append_log(f"{self._hero_name(provider)}提供【杀】；由刘备使用，伤害来源和奖惩归刘备。")
                yield from self._present_action("response" if response else "play", provider.player_id if response else lord_id,
                                                card_ids=materials, target_ids=() if response else (target_id,),
                                                label=f"{self._hero_name(provider)}为刘备提供【杀】", effective_name="杀",
                                                origin_actor_id=provider.player_id)
                if not response:
                    yield from self._resolve_kill(lord_id, target_id, used_card, active_play=True,
                                                  card_color_override=self._response_virtual_colors.get(used_card),
                                                  virtual_card=virtual)
                    self._discard_response_materials(used_card)
                    return used_card, provider.player_id
                return used_card, provider.player_id
        self._append_log("激将无人提供【杀】。")
        return None

    def _jijiang_options(self, provider_id: str) -> tuple[tuple[str, str, str], ...]:
        provider = self._player(provider_id)
        if HERO_BY_ID[provider.hero_id].faction is not Faction.SHU:
            return ()
        result = []
        for card_id in self._zone(provider.hand_zone_id).card_ids:
            if self._definition(card_id).name == "杀":
                result.append(("card", card_id, f"提供手牌【杀】（{self._card_point_label(card_id)}）"))
            elif self._has_skill(provider_id, "longdan") and self._definition(card_id).name == "闪":
                result.append(("longdan", card_id, f"龙胆：提供手牌【闪】当杀（{self._card_point_label(card_id)}）"))
        if self._has_skill(provider_id, "wusheng"):
            for card_id in self._red_sources(provider_id):
                if self._definition(card_id).name == "杀":
                    continue
                result.append(("wusheng", card_id, f"武圣提供【杀】（{self._card_point_label(card_id)}）"))
        hand = tuple(self._zone(provider.hand_zone_id).card_ids)
        if self._has_equipment(provider_id, "serpent_spear"):
            for pair in combinations(hand, 2):
                result.append(("serpent_spear", "|".join(pair),
                               f"丈八蛇矛：两张手牌当杀（{self._card_label(pair[0])}、{self._card_label(pair[1])}）"))
        return tuple(result)

    def _jijiang_providers(self, lord_id: str) -> tuple[PlayerState, ...]:
        return tuple(player for player in self._clockwise_order(lord_id, include_start=False)
                     if HERO_BY_ID[player.hero_id].faction is Faction.SHU and self._jijiang_options(player.player_id))

    def _nullification_window(self, target_id: str, trick_card_id: str, *,
                              trick_kind_id: str | None = None) -> Generator[Any, Any, bool]:
        cancelled = False
        responders = self._clockwise_order(self.state.current_player_id or target_id)
        if not responders:
            return False
        cursor = 0
        consecutive_passes = 0
        while consecutive_passes < len(responders) and not self.finished:
            player = responders[cursor % len(responders)]
            cursor += 1
            negates = [card_id for card_id in self._zone(player.hand_zone_id).card_ids if self._definition(card_id).name == "无懈可击"]
            if not negates:
                consecutive_passes += 1
                continue
            options = (ChoiceOption("pass", "不使用无懈", "pass"),) + tuple(
                ChoiceOption(f"negate:{card_id}", f"使用【无懈可击】（{self._card_point_label(card_id)}）", "negate", card_id)
                for card_id in negates
            )
            definition = self._definition(trick_card_id)
            effective_kind = trick_kind_id or definition.kind_id
            trick_name = "乐不思蜀" if effective_kind == "indulgence" else "过河拆桥" if effective_kind == "dismantle" else definition.name
            answer = yield from self._ask(player.player_id, "nullification", "无懈窗口", f"【{trick_name}】对{self._hero_name(self._player(target_id))}的效果。", options, context={"target_id": target_id, "trick_card_id": trick_card_id, "trick_kind_id": effective_kind, "cancelled": cancelled})
            if answer and answer.startswith("negate:"):
                counter_id = answer.split(":", 1)[1]
                yield from self._discard_with_loss_triggers(counter_id)
                if self.finished:
                    break
                cancelled = not cancelled
                consecutive_passes = 0
                self._append_log(f"{self._hero_name(player)}使用【无懈可击】；响应链当前{'抵消' if cancelled else '恢复'}原效果。")
                yield from self._present_action("negate", player.player_id, card_ids=(counter_id,),
                                                label=f"无懈可击：{'抵消' if cancelled else '恢复'}原效果",
                                                effective_name="无懈可击", reference_card_id=trick_card_id)
            else:
                consecutive_passes += 1
        if self.finished:
            return True
        self._append_log(f"无懈响应链结束，当前目标的锦囊效果{'被抵消' if cancelled else '生效'}。")
        return cancelled

    def _resolve_barbarians(self, source_id: str, card_id: str) -> Generator[Any, Any, None]:
        for target in self._clockwise_order(source_id, include_start=False):
            if self.finished or not target.alive:
                continue
            if (yield from self._nullification_window(target.player_id, card_id)):
                continue
            response = yield from self._ask_kill_response(target.player_id, "南蛮入侵", source_id)
            if response:
                used_card, used_by = response
                self._discard_response_materials(used_card)
                self._append_log(f"{self._hero_name(target)}为南蛮入侵打出【杀】。")
            else:
                yield from self._damage(source_id, target.player_id, 1, card_id, damage_kind="南蛮入侵")

    def _resolve_arrows(self, source_id: str, card_id: str) -> Generator[Any, Any, None]:
        for target in self._clockwise_order(source_id, include_start=False):
            if self.finished or not target.alive:
                continue
            if (yield from self._nullification_window(target.player_id, card_id)):
                continue
            dodged = yield from self._ask_flash(target.player_id, source_id, card_id)
            if dodged:
                self._append_log(f"{self._hero_name(target)}为万箭齐发打出【闪】。")
            else:
                yield from self._damage(source_id, target.player_id, 1, card_id, damage_kind="万箭齐发")

    def _resolve_peach_garden(self, source_id: str, card_id: str) -> Generator[Any, Any, None]:
        for target in self._clockwise_order(source_id):
            if self.finished:
                return
            if not target.alive or target.hp >= target.max_hp:
                continue
            if (yield from self._nullification_window(target.player_id, card_id)):
                continue
            self._recover(target.player_id, 1)
            self._append_log(f"桃园结义令{self._hero_name(target)}回复1点体力。")

    def _resolve_borrow_sword(self, source_id: str, wielder_id: str, card_id: str) -> Generator[Any, Any, None]:
        weapons = self._weapon_ids(wielder_id)
        if not weapons or not self._player(wielder_id).alive:
            return
        targets = self._borrow_sword_targets(wielder_id, source_id)
        if not targets:
            return
        options = tuple(ChoiceOption(f"target:{target_id}", self._hero_name(self._player(target_id)), "target", target_id)
                        for target_id in targets)
        target_choice = yield from self._ask(wielder_id, "borrow_sword_target", "借刀杀人",
                                             "选择攻击范围内另一名角色作为【杀】的目标。",
                                             options, context={"source_id": source_id})
        target_id = target_choice.removeprefix("target:")
        response = yield from self._ask_kill_response(wielder_id, "借刀杀人", target_id)
        if response:
            used_card, _provider_id = response
            self._append_log(f"{self._hero_name(self._player(wielder_id))}以借刀杀人的效果对{self._hero_name(self._player(target_id))}使用【杀】。")
            yield from self._present_action("play", wielder_id, card_ids=(used_card,), target_ids=(target_id,),
                                            label=f"借刀杀人：{self._hero_name(self._player(wielder_id))}使用【杀】",
                                            effective_name="杀")
            virtual = used_card in self._response_virtual_colors
            yield from self._resolve_kill(wielder_id, target_id, used_card, active_play=False,
                                          card_color_override=self._response_virtual_colors.get(used_card),
                                          virtual_card=virtual)
            self._discard_response_materials(used_card)
            return
        weapon_id = weapons[0]
        if self._player(source_id).alive and self._zone(self._player(wielder_id).equipment_zone_id).card_ids.count(weapon_id):
            yield from self._move_with_loss_triggers(
                weapon_id, self._player(source_id).hand_zone_id, owner_id=source_id,
                controller_id=source_id, visibility=Visibility.OWNER_ONLY)
            self._append_log(f"{self._hero_name(self._player(source_id))}因借刀杀人取得{self._hero_name(self._player(wielder_id))}的武器；武器收入手牌。")
        elif self._zone(self._player(wielder_id).equipment_zone_id).card_ids.count(weapon_id):
            self._discard_card(weapon_id)

    def _resolve_harvest(self, source_id: str, card_id: str) -> Generator[Any, Any, None]:
        count = len(self.live_players())
        revealed = self._draw_cards(count, "五谷丰登展示牌")
        if revealed is None:
            return
        for item in revealed:
            self.state.cards[item].visibility = Visibility.PUBLIC
        self._append_log("五谷丰登展示：" + "、".join(self._card_label(item) for item in revealed) + "。")
        remaining = list(revealed)
        for target in self._clockwise_order(source_id):
            if self.finished or not target.alive or not remaining:
                continue
            cancelled = yield from self._nullification_window(target.player_id, card_id)
            if self.finished:
                break
            if cancelled:
                self._append_log(f"{self._hero_name(target)}的五谷目标被无懈，跳过取牌。")
                continue
            options = tuple(ChoiceOption(f"take:{item}", self._card_label(item), "take", item) for item in remaining)
            choice = yield from self._ask(target.player_id, "harvest_pick", "五谷丰登", "请选择一张展示牌；此效果不能主动放弃。", options)
            selected = next(option.value for option in options if option.choice_id == choice)
            remaining.remove(selected)
            self._move(selected, target.hand_zone_id, owner_id=target.player_id,
                       controller_id=target.player_id, visibility=Visibility.OWNER_ONLY)
            self._append_log(f"{self._hero_name(target)}从五谷丰登中取得一张牌。", private_to=(target.player_id,))
        for item in tuple(remaining):
            if self._zone("resolving").card_ids.count(item):
                self._discard_card(item)

    def _resolve_dismantle(self, source_id: str, target_id: str, area_choice: str | None, card_id: str) -> Generator[Any, Any, None]:
        selected, area = yield from self._choose_target_card(source_id, target_id, area_choice, "过河拆桥")
        if selected:
            yield from self._discard_with_loss_triggers(selected)
            label = "隐藏手牌" if area == "hand" else "明置牌"
            self._append_log(f"过河拆桥弃置{self._hero_name(self._player(target_id))}的一张{label}。")

    def _resolve_steal(self, source_id: str, target_id: str, area_choice: str | None, card_id: str) -> Generator[Any, Any, None]:
        if (self._has_skill(target_id, "qianxun")
                or (not self._has_skill(source_id, "qicai") and self.distance(source_id, target_id) != 1)):
            return
        selected, area = yield from self._choose_target_card(source_id, target_id, area_choice, "顺手牵羊")
        if selected:
            actor = self._player(source_id)
            yield from self._move_with_loss_triggers(selected, actor.hand_zone_id, owner_id=source_id,
                                                    controller_id=source_id, visibility=Visibility.OWNER_ONLY)
            label = "隐藏手牌" if area == "hand" else "明置牌"
            self._append_log(f"顺手牵羊取得{self._hero_name(self._player(target_id))}的一张{label}。",
                             private_to=(source_id,))

    def _choose_target_card(self, source_id: str, target_id: str, area_choice: str | None,
                            title: str) -> Generator[Any, Any, tuple[str | None, str | None]]:
        if not self._player(target_id).alive or not self._has_interactable_card(target_id):
            return None, None
        prompt_key = {"过河拆桥": "dismantle", "顺手牵羊": "steal"}.get(title, "card_choice")
        areas = dict(self._interactable_areas(target_id))
        if area_choice is None or area_choice not in areas:
            options = tuple(ChoiceOption(area, label.replace("弃置", "取得") if prompt_key == "steal" else label, area)
                            for area, label in areas.items())
            area_choice = yield from self._ask(source_id, f"{prompt_key}_area", title,
                                               f"选择{self._hero_name(self._player(target_id))}的一个有牌区域。", options)
        zone = self._zone(self._area_zone(target_id, area_choice))
        if not zone.card_ids:
            return None, area_choice
        if area_choice == "hand":
            return self.state.random_stream.choice(tuple(zone.card_ids)), area_choice
        if len(zone.card_ids) == 1:
            return zone.card_ids[0], area_choice
        options = tuple(ChoiceOption(f"card:{item}", self._card_label(item), "card", item)
                        for item in zone.card_ids)
        selected = yield from self._ask(source_id, f"{prompt_key}_visible_card", title,
                                        "选择一张明置牌。", options)
        return selected.removeprefix("card:"), area_choice

    def _resolve_fanjian(self, source_id: str, target_id: str) -> Generator[Any, Any, None]:
        source = self._player(source_id)
        target = self._player(target_id)
        hand = self._zone(source.hand_zone_id).card_ids
        if not hand or not target.alive:
            return
        choices = tuple(ChoiceOption(suit.value, label, suit.value) for suit, label in (
            (Suit.SPADES, "黑桃"), (Suit.HEARTS, "红桃"),
            (Suit.CLUBS, "梅花"), (Suit.DIAMONDS, "方块"),
        ))
        guess = yield from self._ask(target_id, "fan_jian_suit", "反间猜花色", "选择一种花色，再展示周瑜随机一张手牌。", choices)
        card_id = self.state.random_stream.choice(tuple(hand))
        self.state.cards[card_id].temporary_marks.add("fanjian_pending")
        yield from self._move_with_loss_triggers(card_id, "resolving", owner_id=source_id,
                                                controller_id=source_id, visibility=Visibility.PUBLIC)
        actual_suit = self._definition(card_id).suit.value
        self._append_log(f"周瑜反间展示【{self._definition(card_id).name}】（{actual_suit}）。")
        if guess != actual_suit:
            self._append_log(f"猜错花色，{self._hero_name(target)}受到周瑜造成的1点伤害；展示牌处于隔离区，不能用于自救。")
            yield from self._damage(source_id, target_id, 1, None, damage_kind="反间")
            if self.finished:
                if card_id in self._zone("resolving").card_ids:
                    if target.alive:
                        self._move(card_id, target.hand_zone_id, owner_id=target_id,
                                   controller_id=target_id, visibility=Visibility.OWNER_ONLY)
                    else:
                        self._move(card_id, source.hand_zone_id, owner_id=source_id,
                                   controller_id=source_id, visibility=Visibility.OWNER_ONLY)
                    self.state.cards[card_id].temporary_marks.discard("fanjian_pending")
                return
        if self._zone("resolving").card_ids.count(card_id):
            if target.alive:
                self._move(card_id, target.hand_zone_id, owner_id=target_id,
                           controller_id=target_id, visibility=Visibility.OWNER_ONLY)
                self.state.cards[card_id].temporary_marks.discard("fanjian_pending")
                self._append_log(f"{self._hero_name(target)}存活，获得反间展示牌。")
            else:
                self._move(card_id, source.hand_zone_id, owner_id=source_id,
                           controller_id=source_id, visibility=Visibility.OWNER_ONLY)
                self.state.cards[card_id].temporary_marks.discard("fanjian_pending")
                self._append_log("反间目标死亡，展示牌退回周瑜手中。")

    def _damage(self, source_id: str | None, target_id: str, amount: int, card_id: str | None, *, damage_kind: str) -> Generator[Any, Any, None]:
        if self.finished:
            return
        target = self._player(target_id)
        if not target.alive:
            return
        if (source_id and source_id == self.state.current_player_id
                and self.state.phase is GamePhase.PLAY
                and source_id in self._luoyi_bonus
                and damage_kind in {"杀", "贯石斧", "决斗"}):
            amount += 1
            self._append_log(f"许褚发动裸衣，本次{damage_kind}伤害+1。")
        yield from self._event("damage", source_id, self._damage_inner(source_id, target_id, amount, card_id, damage_kind))

    def _damage_inner(self, source_id: str | None, target_id: str, amount: int, card_id: str | None, damage_kind: str) -> Generator[Any, Any, None]:
        target = self._player(target_id)
        source = self._player(source_id) if source_id else None
        if (source and damage_kind in {"杀", "贯石斧"}
                and self._has_equipment(source_id, "kirin_bow")):
            mounts = tuple(card_id for card_id in self._zone(target.equipment_zone_id).card_ids
                           if CARD_KIND_BY_NAME[self._definition(card_id).name].subtype
                           in {"horse_plus_one", "horse_minus_one"})
            if mounts:
                choices = (ChoiceOption("pass", "不发动麒麟弓", "pass"),) + tuple(
                    ChoiceOption(f"mount:{card_id}", f"弃置坐骑【{self._definition(card_id).name}】", "mount", card_id)
                    for card_id in mounts
                )
                answer = yield from self._ask(source_id, "kirin_bow", "麒麟弓",
                                              "杀将造成伤害；可先弃置目标装备区的一匹坐骑。", choices)
                if answer and answer.startswith("mount:"):
                    mount_id = answer.removeprefix("mount:")
                    if mount_id in self._zone(target.equipment_zone_id).card_ids:
                        yield from self._discard_with_loss_triggers(mount_id)
                    if self.finished:
                        return
        target.hp -= amount
        self._append_log(f"{self._hero_name(target)}受到{self._hero_name(source) if source else '无来源'}造成的{amount}点{damage_kind}伤害，体力降至{target.hp}。")
        yield from self._present_action("damage", source_id, target_ids=(target_id,), label=f"−{amount}")
        if target.hp <= 0:
            rescued = yield from self._rescue(target_id)
            if not rescued:
                self._kill_player(target_id, source_id)
                if self.finished:
                    return
            elif target.hp > 0:
                self._append_log(f"{self._hero_name(target)}脱离濒死。")
        if not target.alive or self.finished:
            return
        if self._has_skill(target_id, "jianxiong") and card_id and self._zone("resolving").card_ids.count(card_id):
            choices = (ChoiceOption("take", f"取得伤害牌【{self._definition(card_id).name}】", "take", card_id),
                       ChoiceOption("pass", "不发动奸雄", "pass"))
            answer = yield from self._ask(target_id, "jianxiong", "奸雄", "牌造成伤害且曹操存活，可取得仍在结算中的伤害牌。", choices)
            if answer == "take" and self._zone("resolving").card_ids.count(card_id):
                self._move(card_id, target.hand_zone_id, owner_id=target_id,
                           controller_id=target_id, visibility=Visibility.OWNER_ONLY)
                self._append_log("曹操发动奸雄，取得造成伤害的牌。")
        if self._has_skill(target_id, "fankui") and source and source.alive:
            source_cards = (*self._zone(source.equipment_zone_id).card_ids, *self._zone(source.hand_zone_id).card_ids)
            if source_cards:
                options = [ChoiceOption("pass", "不发动反馈", "pass")]
                for item in self._zone(source.equipment_zone_id).card_ids:
                    options.append(ChoiceOption(f"take:{item}", f"取得装备【{self._definition(item).name}】", "take_public", item))
                if self._zone(source.hand_zone_id).card_ids:
                    options.append(ChoiceOption("take_random_hand", "随机取得一张隐藏手牌", "take_hidden"))
                answer = yield from self._ask(target_id, "fankui", "反馈", "受到一次伤害并存活后，可获得伤害来源的一张手牌或装备。", tuple(options))
                if answer == "take_random_hand" and self._zone(source.hand_zone_id).card_ids:
                    item = self.state.random_stream.choice(tuple(self._zone(source.hand_zone_id).card_ids))
                    yield from self._move_with_loss_triggers(
                        item, target.hand_zone_id, owner_id=target_id,
                        controller_id=target_id, visibility=Visibility.OWNER_ONLY)
                    if self.finished:
                        return
                    self._append_log(f"司马懿发动反馈，随机取得{self._hero_name(source)}一张隐藏手牌。")
                elif answer and answer.startswith("take:"):
                    item = answer.split(":", 1)[1]
                    yield from self._move_with_loss_triggers(
                        item, target.hand_zone_id, owner_id=target_id,
                        controller_id=target_id, visibility=Visibility.OWNER_ONLY)
                    if self.finished:
                        return
                    self._append_log(f"司马懿发动反馈，取得{self._hero_name(source)}一件装备。")
        if self._has_skill(target_id, "ganglie"):
            trigger = yield from self._ask(
                target_id, "ganglie_trigger", "刚烈",
                "受到伤害后，可发动刚烈进行判定。",
                (ChoiceOption("yes", "发动刚烈", "trigger"),
                 ChoiceOption("pass", "不发动刚烈", "pass")),
            )
            if trigger == "yes":
                result = yield from self._judge(target_id, "刚烈")
                if self.finished:
                    return
                if result:
                    yield from self._settle_judgment(target_id, result)
                    if self.finished:
                        return
                if result and self._definition(result).suit is not Suit.HEARTS:
                    if source and source.alive:
                        hand = self._zone(source.hand_zone_id).card_ids
                        if len(hand) >= 2:
                            options = (ChoiceOption("damage", "受到夏侯惇造成的1点伤害", "damage"),) + tuple(
                                ChoiceOption(f"discard:{item}", self._card_label(item), "discard", item)
                                for item in hand
                            )
                            answer = yield from self._ask(source_id, "ganglie", "刚烈", "选择同时弃置两张手牌，或受到夏侯惇造成的1点伤害。", options, min_choices=1, max_choices=2, context={"target_id": target_id})
                            if isinstance(answer, tuple) and len(answer) == 2:
                                yield from self._discard_many_with_loss_triggers(
                                    tuple(choice.removeprefix("discard:") for choice in answer))
                                self._append_log(f"{self._hero_name(source)}为刚烈同时弃置两张手牌。")
                            elif answer == "damage":
                                yield from self._damage(target_id, source_id, 1, None, damage_kind="刚烈")
                        else:
                            self._append_log(f"{self._hero_name(source)}手牌不足两张，受到刚烈伤害。")
                            yield from self._damage(target_id, source_id, 1, None, damage_kind="刚烈")
                    else:
                        self._append_log("刚烈伤害没有来源，无法执行来源的弃牌或受伤选择。")
            else:
                self._append_log("夏侯惇不发动刚烈。")
        if self._has_skill(target_id, "yiji"):
            for damage_index in range(amount):
                if self.finished or not target.alive:
                    return
                drawn = self._draw_cards(2, "郭嘉遗计")
                if drawn is None:
                    return
                for card_id in drawn:
                    self._move(card_id, target.hand_zone_id, owner_id=target_id,
                               controller_id=target_id, visibility=Visibility.OWNER_ONLY)
                self._append_log(f"郭嘉因第{damage_index + 1}点伤害发动遗计，摸两张牌。",
                                 private_to=(target_id,))
                for card_id in drawn:
                    choices = (ChoiceOption("keep", "自己保留", "keep"),) + tuple(
                        ChoiceOption(f"give:{player.player_id}", f"交给{self._hero_name(player)}", "target", player.player_id)
                        for player in self.live_players()
                    )
                    choice = yield from self._ask(target_id, "yiji_give", "遗计",
                                                  "选择自己保留这张牌，或交给一名角色。", choices)
                    if choice.startswith("give:"):
                        recipient_id = choice.removeprefix("give:")
                        if self._player(recipient_id).alive and card_id in self._zone(target.hand_zone_id).card_ids:
                            yield from self._move_with_loss_triggers(
                                card_id, self._player(recipient_id).hand_zone_id,
                                owner_id=recipient_id, controller_id=recipient_id,
                                visibility=Visibility.OWNER_ONLY)

    def _rescue(self, dying_id: str) -> Generator[Any, Any, bool]:
        order = self._clockwise_order(self.state.current_player_id or dying_id)
        full_round_passed = 0
        cursor = 0
        while not self.finished and self._player(dying_id).hp <= 0 and full_round_passed < len(order):
            rescuer = order[cursor % len(order)]
            cursor += 1
            peaches = [card_id for card_id in self._zone(rescuer.hand_zone_id).card_ids if self._definition(card_id).name == "桃"]
            jijiu_cards: tuple[str, ...] = ()
            if rescuer.player_id != self.state.current_player_id and self._has_skill(rescuer.player_id, "jijiu"):
                sources = (*self._zone(rescuer.hand_zone_id).card_ids,
                           *self._zone(rescuer.equipment_zone_id).card_ids)
                jijiu_cards = tuple(card_id for card_id in sources
                                    if self._color(card_id) == "red"
                                    and self._definition(card_id).name != "桃")
            if not peaches and not jijiu_cards:
                full_round_passed += 1
                continue
            dying = self._player(dying_id)
            extra = (
                self.state.mode_id == "five_player_identity"
                and self._has_skill(dying_id, "jiuyuan")
                and dying.identity == Identity.LORD.value
                and rescuer.player_id != dying_id
                and HERO_BY_ID[rescuer.hero_id].faction is Faction.WU
            )
            options = (ChoiceOption("pass", "放弃本次救援机会", "pass", {"target_id": dying_id}),) + tuple(
                ChoiceOption(f"peach:{card_id}", f"使用【桃】（{self._card_point_label(card_id)}）", "peach", card_id)
                for card_id in peaches
            ) + tuple(ChoiceOption(f"jijiu:{card_id}", f"急救：以红色牌当【桃】（{self._card_label(card_id)}）", "peach", card_id)
                     for card_id in jijiu_cards)
            answer = yield from self._ask(rescuer.player_id, "rescue", "濒死救援", f"{self._hero_name(self._player(dying_id))}体力为{self._player(dying_id).hp}，需回复至正数。", options, context={"target_id": dying_id})
            if answer and answer.startswith("peach:"):
                card_id = answer.split(":", 1)[1]
                yield from self._discard_with_loss_triggers(card_id)
                yield from self._present_action("rescue", rescuer.player_id, card_ids=(card_id,),
                                                target_ids=(dying_id,), label=f"{self._hero_name(rescuer)}使用桃救援",
                                                effective_name="桃")
                amount = 1 + (1 if extra else 0)
                self._recover(dying_id, amount)
                self._append_log(f"{self._hero_name(rescuer)}使用桃救援{self._hero_name(self._player(dying_id))}。")
                full_round_passed = 0
                cursor = max(0, cursor - 1)
                if self._player(dying_id).hp > 0:
                    return True
            elif answer and answer.startswith("jijiu:"):
                card_id = answer.split(":", 1)[1]
                yield from self._discard_with_loss_triggers(card_id)
                yield from self._present_action("rescue", rescuer.player_id, card_ids=(card_id,),
                                                target_ids=(dying_id,), label=f"{self._hero_name(rescuer)}发动急救",
                                                effective_name="桃")
                amount = 1 + (1 if extra else 0)
                self._recover(dying_id, amount)
                self._append_log(f"{self._hero_name(rescuer)}发动急救，红色牌当桃救援{self._hero_name(self._player(dying_id))}。")
                full_round_passed = 0
                # C-03: ask this same rescuer again if the dying player is still at 0 or less.
                cursor = max(0, cursor - 1)
                if self._player(dying_id).hp > 0:
                    return True
            else:
                full_round_passed += 1
        return self._player(dying_id).hp > 0

    def _kill_player(self, player_id: str, killer_id: str | None) -> None:
        player = self._player(player_id)
        if not player.alive:
            return
        player.alive = False
        player.identity_public = True
        self._append_log(f"{self._hero_name(player)}阵亡，身份公开。")
        for zone_id in (player.hand_zone_id, player.equipment_zone_id, player.judgment_zone_id):
            for card_id in tuple(self._zone(zone_id).card_ids):
                self._discard_card(card_id)
        terminal = self._check_victory()
        if terminal:
            self._finish(terminal, "normal", f"对局结束：{self._winner_label(terminal)}。")
            return
        if killer_id:
            killer = self._player(killer_id)
            if self.state.mode_id == "five_player_identity" and player.identity == Identity.REBEL.value:
                drawn = self._draw_cards(3, "击杀反贼奖励")
                if drawn is None:
                    return
                for item in drawn:
                    self._move(item, killer.hand_zone_id, owner_id=killer_id,
                               controller_id=killer_id, visibility=Visibility.OWNER_ONLY)
                self._append_log(f"{self._hero_name(killer)}击杀反贼，摸三张牌。")
            if self.state.mode_id == "five_player_identity" and killer.identity == Identity.LORD.value and player.identity == Identity.LOYALIST.value:
                for zone_id in (killer.hand_zone_id, killer.equipment_zone_id):
                    for card_id in tuple(self._zone(zone_id).card_ids):
                        self._discard_card(card_id)
                self._append_log("主公误杀忠臣，弃置其全部手牌和装备；判定区保留。")
            terminal = self._check_victory()
            if terminal:
                self._finish(terminal, "normal", f"对局结束：{self._winner_label(terminal)}。")

    def _check_victory(self) -> str | None:
        alive = self.live_players()
        if self.state.mode_id == "duel":
            if len(alive) <= 1:
                return "player_side_win" if alive and alive[0].player_id == "P1" else "opposing_side_win"
        elif self.state.mode_id == "two_heroes":
            if not any(player.player_id == "P1" for player in alive):
                return "ai_side_win"
            if not any(player.player_id != "P1" for player in alive):
                return "player_side_win"
        else:
            lord_alive = any(player.identity == Identity.LORD.value for player in alive)
            turncoat = [player for player in alive if player.identity == Identity.TURNCOAT.value]
            rebels = [player for player in alive if player.identity == Identity.REBEL.value]
            if lord_alive and not turncoat and not rebels:
                return "lord_side_win"
            if not lord_alive:
                if len(alive) == 1 and turncoat:
                    return "turncoat_side_win"
                return "rebel_side_win"
        return None

    def _resolve_judgment_zone(self, player: PlayerState) -> Generator[Any, Any, None]:
        zone = self._zone(player.judgment_zone_id)
        for delayed_id in tuple(reversed(zone.card_ids)):
            if self.finished or not player.alive or delayed_id not in zone.card_ids:
                continue
            definition = self._definition(delayed_id)
            cancelled = yield from self._nullification_window(player.player_id, delayed_id)
            if self.finished:
                return
            if cancelled:
                if definition.kind_id == "indulgence":
                    self._discard_card(delayed_id)
                else:
                    self._pass_lightning(player.player_id, delayed_id)
                continue
            result = yield from self._judge(player.player_id, definition.name)
            if result is None or self.finished:
                return
            if definition.kind_id == "indulgence":
                if self._definition(result).suit is not Suit.HEARTS:
                    self._skip_play.add(player.player_id)
                    self._append_log(f"乐不思蜀判定非红桃，{self._hero_name(player)}跳过本回合出牌阶段。")
                else:
                    self._append_log("乐不思蜀判定为红桃，不跳过出牌阶段。")
                self._discard_card(delayed_id)
                yield from self._settle_judgment(player.player_id, result)
            elif definition.kind_id == "lightning":
                judgment = self._definition(result)
                if judgment.suit is Suit.SPADES and 2 <= judgment.point <= 9:
                    self._append_log("闪电判定为黑桃2至9，造成3点无来源伤害。")
                    self._move(delayed_id, "resolving", owner_id=player.player_id,
                               controller_id=player.player_id, visibility=Visibility.PUBLIC)
                    yield from self._damage(None, player.player_id, 3, delayed_id, damage_kind="闪电")
                    if delayed_id in self._zone("resolving").card_ids:
                        self._discard_card(delayed_id)
                else:
                    self._pass_lightning(player.player_id, delayed_id)
                if result in self._zone("resolving").card_ids:
                    if not self.finished:
                        yield from self._settle_judgment(player.player_id, result)
                    else:
                        self._discard_card(result)

    def _pass_lightning(self, source_id: str, card_id: str) -> None:
        alive = self.live_players()
        if len(alive) <= 1:
            self._discard_card(card_id)
            self._append_log("没有下一名合法角色，闪电进入弃牌堆。")
            return
        order = self._clockwise_order(source_id, include_start=False)
        target = next((player for player in order if not self._has_same_delayed(player.player_id, "lightning")), None)
        if target is None:
            self._discard_card(card_id)
            self._append_log("没有可接收闪电的角色，闪电进入弃牌堆。")
        else:
            self._move(card_id, target.judgment_zone_id, owner_id=target.player_id,
                       controller_id=target.player_id, visibility=Visibility.PUBLIC)
            self._append_log(f"闪电传给{self._hero_name(target)}。")

    def _judge(self, target_id: str, reason: str) -> Generator[Any, Any, str | None]:
        drawn = self._draw_cards(1, f"{reason}判定")
        if drawn is None:
            return None
        original = drawn[0]
        self._sound_event("judgement")
        self.state.cards[original].visibility = Visibility.PUBLIC
        yield from self._present_action("judgement", target_id, card_ids=(original,),
                                        label=f"{self._hero_name(self._player(target_id))} · {reason}判定")
        self._append_log(f"{self._hero_name(self._player(target_id))}进行{reason}判定，翻开【{self._definition(original).name}】（{self._card_point_label(original)}）。")
        current = original
        simayi = next((player for player in self._clockwise_order(self.state.current_player_id or target_id)
                       if player.alive and self._has_skill(player.player_id, "guicai")
                       and self._zone(player.hand_zone_id).card_ids), None)
        if simayi:
            choices = (ChoiceOption("pass", "不发动鬼才", "pass"),) + tuple(
                ChoiceOption(f"replace:{item}", f"替换为手牌（{self._card_point_label(item)}）", "replace", item)
                for item in self._zone(simayi.hand_zone_id).card_ids
            )
            answer = yield from self._ask(simayi.player_id, "guicai", "鬼才改判", "判定牌最终生效前，司马懿可用一张手牌替换。", choices)
            if answer and answer.startswith("replace:"):
                replacement = answer.split(":", 1)[1]
                self._discard_card(original)
                yield from self._move_with_loss_triggers(replacement, "resolving", owner_id=simayi.player_id,
                                                        controller_id=simayi.player_id, visibility=Visibility.PUBLIC)
                current = replacement
                self._append_log(f"司马懿发动鬼才，最终判定牌为【{self._definition(current).name}】（{self._card_point_label(current)}）。")
                yield from self._present_action("judgement_replace", target_id, card_ids=(current,),
                                                label="鬼才改判 · 最终判定牌")
        self._move(current, "resolving", owner_id=None, controller_id=None, visibility=Visibility.PUBLIC)
        return current

    def _equip_card(self, player_id: str, card_id: str) -> Generator[Any, Any, None]:
        definition = self._definition(card_id)
        target_slot = self._equipment_slot(definition.kind_id)
        if target_slot is None:
            return
        player = self._player(player_id)
        zone = self._zone(player.equipment_zone_id)
        replaced = [item for item in zone.card_ids if self._equipment_slot(self._definition(item).kind_id) == target_slot]
        for item in replaced:
            yield from self._discard_with_loss_triggers(item)
            if self.finished or not player.alive:
                return
        yield from self._present_action("equip", player_id, card_ids=(card_id,),
                                        label=f"{self._hero_name(player)}装备【{definition.name}】")
        self._move(card_id, zone.zone_id, owner_id=player_id,
                   controller_id=player_id, visibility=Visibility.PUBLIC)
        self._append_log(f"{self._hero_name(player)}装备【{definition.name}】。")
        if False:
            yield

    def _draw_cards(self, count: int, reason: str) -> list[str] | None:
        if count <= 0 or self.finished:
            return []
        draw = self._zone("draw_pile")
        discard = self._zone("discard_pile")
        if len(draw.card_ids) < count and discard.card_ids:
            recycled = tuple(discard.card_ids)
            discard.card_ids.clear()
            draw.card_ids.extend(recycled)
            for card_id in recycled:
                card = self.state.cards[card_id]
                card.zone_id = draw.zone_id
                card.owner_id = None
                card.controller_id = None
                card.visibility = Visibility.HIDDEN
            self.state.random_stream.shuffle(draw.card_ids)
            self._append_log("牌堆不足，弃牌堆洗回牌堆后重新检查。")
        if len(draw.card_ids) < count:
            self._finish("draw", "C-04_insufficient_cards", f"{reason}需要完整执行{count}张牌，但牌堆与弃牌堆合计不足；按C-04平局结束。")
            return None
        picked = [draw.card_ids.pop(0) for _ in range(count)]
        if picked and not reason.endswith("判定"):
            self._sound_event("card_draw")
        resolving = self._zone("resolving")
        for card_id in picked:
            card = self.state.cards[card_id]
            card.zone_id = resolving.zone_id
            card.owner_id = None
            card.controller_id = None
            card.visibility = Visibility.HIDDEN
            resolving.card_ids.append(card_id)
        return picked

    def _recover(self, player_id: str, amount: int) -> None:
        player = self._player(player_id)
        before = player.hp
        player.hp = min(player.max_hp, player.hp + amount)
        if player.hp > before:
            self._sound_event("heal")
        self._append_log(f"{self._hero_name(player)}回复{player.hp - before}点体力，当前{player.hp}/{player.max_hp}。")

    def _sound_event(self, name: str) -> None:
        """Optional presentation evidence; no card identities or rule side effects."""
        if self.presentation_enabled and not self._fast_forward:
            self._audio_serial += 1
            self.audio_events.append((self._audio_serial, name))

    def _event(self, kind: str, actor_id: str | None, generator: Generator[Any, Any, Any]) -> Generator[Any, Any, None]:
        self._event_serial += 1
        parent_event_id = self.state.event_stack[-1].event_id if self.state.event_stack else None
        frame = EventFrame(f"E{self._event_serial}", kind, actor_id=actor_id,
                           status="processing", parent_event_id=parent_event_id)
        self.state.event_stack.append(frame)
        answer = _NO_ANSWER
        try:
            while True:
                try:
                    yielded = next(generator) if answer is _NO_ANSWER else generator.send(answer)
                    answer = _NO_ANSWER
                except StopIteration as result:
                    frame.status = "completed"
                    return result.value
                frame.status = "waiting_input"
                answer = yield yielded
                frame.resume_cursor += 1
                frame.status = "processing"
        finally:
            if frame in self.state.event_stack:
                self.state.event_stack.remove(frame)

    def _ask(
        self,
        player_id: str,
        kind: str,
        title: str,
        message: str,
        options: tuple[ChoiceOption, ...],
        *,
        min_choices: int = 1,
        max_choices: int = 1,
        minimum_override: tuple[int, int] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Generator[Any, Any, str | tuple[str, ...]]:
        player = self._player(player_id)
        if not player.alive:
            return "pass"
        if minimum_override:
            min_choices, max_choices = minimum_override
        request = DecisionRequest(kind, player_id, title, message, options,
                                  min_choices=min_choices, max_choices=max_choices,
                                  context=tuple((context or {}).items()))
        if player.control is ControlType.HUMAN:
            if self._is_spectating():
                return "pass"
            answer = yield request
            return answer
        view = self.observation_for(player_id)
        return self._choose_ai_option(view, request)

    def _choose_ai_option(
        self,
        view: ObservationView,
        request: DecisionRequest,
    ) -> str | tuple[str, ...]:
        raw = self._ai_for(request.player_id).choose_option(view, request)
        selected = (raw,) if isinstance(raw, str) else tuple(raw)
        if not self._valid_ai_choice(request, selected):
            self.ai_issues.append(AIExecutionIssue(
                request.player_id, self.state.turn_number, request.kind,
                selected, "selected_choice_not_in_legal_option_set",
            ))
            selected = self._fallback_ai_choice(request)
        if len(selected) == 1:
            return selected[0]
        return selected

    @staticmethod
    def _valid_ai_choice(request: DecisionRequest, selected: tuple[str, ...]) -> bool:
        allowed = {option.choice_id for option in request.options}
        if (len(set(selected)) != len(selected)
                or any(item not in allowed for item in selected)
                or not request.min_choices <= len(selected) <= request.max_choices):
            return False
        if request.kind in {"axe_payment", "ganglie"}:
            return selected in {("pass",), ("damage",)} or (
                len(selected) == 2 and all(item.startswith("discard:") for item in selected)
            )
        return True

    @staticmethod
    def _fallback_ai_choice(request: DecisionRequest) -> tuple[str, ...]:
        options = request.options
        if request.min_choices == 0:
            return ()
        if request.kind in {"axe_payment", "ganglie"}:
            passes = tuple(option.choice_id for option in options if option.category == "pass")
            if passes and request.min_choices <= 1 <= request.max_choices:
                return passes[:1]
            discards = tuple(option.choice_id for option in options if option.category == "discard")
            if len(discards) >= 2 and request.min_choices <= 2 <= request.max_choices:
                return discards[:2]
        selected: list[str] = []
        for option in options:
            if option.choice_id not in selected:
                selected.append(option.choice_id)
            if len(selected) == request.min_choices:
                break
        return tuple(selected)

    def _record_public_action(self, intent: ActionIntent) -> None:
        if intent.card_id:
            physical = self.state.cards.get(intent.card_id)
            definition = CARD_BY_ID.get(physical.definition_id) if physical else None
            action_kind = definition.kind_id if definition else None
        else:
            action_kind = None
        if not action_kind:
            action_kind = intent.skill_id.rsplit(".", 1)[-1] if intent.skill_id else "action"
        self.public_action_history.append(PublicActionRecord(
            turn_number=self.state.turn_number,
            actor_id=intent.actor_id,
            kind_id=str(action_kind),
            target_ids=tuple(intent.target_ids),
        ))

    def _finish(self, result: str, end_reason: str, text: str) -> None:
        if self.finished:
            return
        self.state.result = result
        self.state.end_reason = end_reason
        self.state.phase = GamePhase.END
        self._append_log(text)
        self.pending_request = None
        self._generator = None
        self.display_waiting = False
        resolving = self._zone("resolving")
        for card_id in tuple(resolving.card_ids):
            card = self.state.cards[card_id]
            if "fanjian_pending" in card.temporary_marks:
                if end_reason not in {"resigned", "restart", "exit_to_menu"}:
                    # The active Fanjian generator resumes after a rules-driven terminal
                    # result and sends the isolated card to its confirmed destination.
                    continue
                owner_id = card.owner_id
                if owner_id and self._player(owner_id).alive:
                    self._move(card_id, self._player(owner_id).hand_zone_id,
                               owner_id=owner_id, controller_id=owner_id,
                               visibility=Visibility.OWNER_ONLY)
                else:
                    self._discard_card(card_id)
                card.temporary_marks.discard("fanjian_pending")
                continue
            self._discard_card(card_id)
        self._response_extra_materials.clear()
        self._response_virtual_colors.clear()
        self.state.event_stack.clear()
        self.spectator_waiting = False

    def _append_log(self, text: str, private_to: tuple[str, ...] = ()) -> None:
        self.logs.append(EventLog(self.state.turn_number, text, private_to))
        if len(self.logs) > 400:
            del self.logs[:len(self.logs) - 400]

    def _assert_invariants(self) -> None:
        assert_card_zone_invariant(self.state)
        for player in self.state.players:
            if player.hp > player.max_hp:
                raise ValueError(f"player {player.player_id} exceeds maximum HP")

    def _player(self, player_id: str | None) -> PlayerState:
        if player_id is None:
            raise ValueError("player id is required")
        return next(player for player in self.state.players if player.player_id == player_id)

    def _zone(self, zone_id: str):
        return self.state.zones[zone_id]

    def _move(self, card_id: str, destination_id: str, *, owner_id: str | None, controller_id: str | None, visibility: Visibility) -> None:
        card = self.state.cards[card_id]
        source = self._zone(card.zone_id)
        if card_id in source.card_ids:
            source.card_ids.remove(card_id)
        destination = self._zone(destination_id)
        destination.card_ids.append(card_id)
        card.zone_id = destination_id
        card.owner_id = owner_id
        card.controller_id = controller_id
        card.visibility = visibility

    def _move_with_loss_triggers(self, card_id: str, destination_id: str, *, owner_id: str | None,
                                 controller_id: str | None, visibility: Visibility) -> Generator[Any, Any, None]:
        source_zone = self._zone(self.state.cards[card_id].zone_id)
        player_id = source_zone.owner_id if source_zone.kind in {ZoneKind.HAND, ZoneKind.EQUIPMENT} else None
        lost_hand = source_zone.kind is ZoneKind.HAND
        lost_equipment = source_zone.kind is ZoneKind.EQUIPMENT
        self._move(card_id, destination_id, owner_id=owner_id,
                   controller_id=controller_id, visibility=visibility)
        if player_id:
            yield from self._resolve_loss_triggers(player_id, lost_hand=lost_hand,
                                                   lost_equipment=lost_equipment)

    def _discard_with_loss_triggers(self, card_id: str) -> Generator[Any, Any, None]:
        if card_id in self.state.cards and self.state.cards[card_id].zone_id != "discard_pile":
            yield from self._move_with_loss_triggers(card_id, "discard_pile", owner_id=None,
                                                     controller_id=None, visibility=Visibility.PUBLIC)

    def _discard_many_with_loss_triggers(self, card_ids: tuple[str, ...]) -> Generator[Any, Any, None]:
        losses: dict[str, tuple[bool, int]] = {}
        for card_id in card_ids:
            if card_id not in self.state.cards or self.state.cards[card_id].zone_id == "discard_pile":
                continue
            source_zone = self._zone(self.state.cards[card_id].zone_id)
            if source_zone.kind not in {ZoneKind.HAND, ZoneKind.EQUIPMENT} or source_zone.owner_id is None:
                self._discard_card(card_id)
                continue
            player_id = source_zone.owner_id
            hand_loss, equipment_count = losses.get(player_id, (False, 0))
            losses[player_id] = (hand_loss or source_zone.kind is ZoneKind.HAND,
                                 equipment_count + (1 if source_zone.kind is ZoneKind.EQUIPMENT else 0))
            self._discard_card(card_id)
        order = self._clockwise_order(self.state.current_player_id or next(iter(losses), "")) if losses else ()
        ids = [player.player_id for player in order if player.player_id in losses]
        ids.extend(player_id for player_id in losses if player_id not in ids)
        for player_id in ids:
            lost_hand, equipment_count = losses[player_id]
            yield from self._resolve_loss_triggers(player_id, lost_hand=lost_hand,
                                                   lost_equipment=bool(equipment_count),
                                                   equipment_trigger_count=equipment_count)

    def _resolve_loss_triggers(self, player_id: str, *, lost_hand: bool,
                               lost_equipment: bool, equipment_trigger_count: int = 1) -> Generator[Any, Any, None]:
        player = self._player(player_id)
        if not player.alive or self.finished:
            return
        if lost_hand and self._has_skill(player_id, "lianying") and not self._zone(player.hand_zone_id).card_ids:
            choices = (ChoiceOption("yes", "发动连营，摸一张牌", "yes"),
                       ChoiceOption("pass", "不发动", "pass"))
            answer = yield from self._ask(player_id, "lianying", "连营",
                                          "失去最后一张手牌后，可摸一张牌。", choices)
            if answer == "yes":
                drawn = self._draw_cards(1, "陆逊连营")
                if drawn is None:
                    return
                self._move(drawn[0], player.hand_zone_id, owner_id=player_id,
                           controller_id=player_id, visibility=Visibility.OWNER_ONLY)
                self._append_log("陆逊发动连营，摸一张牌。", private_to=(player_id,))
        for _ in range(equipment_trigger_count if lost_equipment else 0):
            if not player.alive or self.finished or not self._has_skill(player_id, "xiaoji"):
                return
            choices = (ChoiceOption("yes", "发动枭姬，摸两张牌", "yes"),
                       ChoiceOption("pass", "不发动", "pass"))
            answer = yield from self._ask(player_id, "xiaoji", "枭姬",
                                          "失去装备区的一张牌后，可摸两张牌。", choices)
            if answer == "yes":
                drawn = self._draw_cards(2, "孙尚香枭姬")
                if drawn is None:
                    return
                for item in drawn:
                    self._move(item, player.hand_zone_id, owner_id=player_id,
                               controller_id=player_id, visibility=Visibility.OWNER_ONLY)
                self._append_log("孙尚香发动枭姬，摸两张牌。", private_to=(player_id,))

    def _discard_card(self, card_id: str) -> None:
        if card_id not in self.state.cards:
            return
        if self.state.cards[card_id].zone_id == "discard_pile":
            return
        self._move(card_id, "discard_pile", owner_id=None, controller_id=None, visibility=Visibility.PUBLIC)

    def _definition(self, card_id: str):
        try:
            return CARD_BY_ID[card_id.removeprefix("card:")]
        except KeyError as exc:
            raise KeyError(f"unknown card definition: {card_id}") from exc

    def _hero_name(self, player: PlayerState) -> str:
        return HERO_BY_ID[player.hero_id].name

    def _card_label(self, card_id: str) -> str:
        definition = self._definition(card_id)
        return f"{definition.name} {self._card_point_label(card_id)}"

    def _card_point_label(self, card_id: str) -> str:
        definition = self._definition(card_id)
        return f"{definition.suit.value}:{definition.rank}"

    def _color(self, card_id: str | None) -> str | None:
        if not card_id:
            return None
        return "red" if self._definition(card_id).suit in {Suit.HEARTS, Suit.DIAMONDS} else "black"

    def _has_skill(self, player_id: str, skill_name: str) -> bool:
        return any(skill_id.endswith(f".{skill_name}") for skill_id in HERO_BY_ID[self._player(player_id).hero_id].skill_ids)

    def _is_lord(self, player_id: str) -> bool:
        return self.state.mode_id == "five_player_identity" and self._player(player_id).identity == Identity.LORD.value

    def _can_use_kill(self, player_id: str) -> bool:
        player = self._player(player_id)
        unlimited = self._has_skill(player_id, "paoxiao") or self._has_equipment(player_id, "crossbow")
        return unlimited or self._kill_uses.get(player_id, 0) == 0

    def _red_sources(self, player_id: str) -> tuple[str, ...]:
        player = self._player(player_id)
        cards = (*self._zone(player.hand_zone_id).card_ids, *self._zone(player.equipment_zone_id).card_ids)
        return tuple(card_id for card_id in cards if self._color(card_id) == "red")

    def _black_sources(self, player_id: str) -> tuple[str, ...]:
        player = self._player(player_id)
        cards = (*self._zone(player.hand_zone_id).card_ids, *self._zone(player.equipment_zone_id).card_ids)
        return tuple(card_id for card_id in cards if self._color(card_id) == "black")

    def _kill_response_sources(self, player_id: str) -> tuple[str, ...]:
        player = self._player(player_id)
        hand = tuple(self._zone(player.hand_zone_id).card_ids)
        result = [card_id for card_id in hand if self._definition(card_id).name == "杀"]
        if self._has_skill(player_id, "wusheng"):
            result.extend(card_id for card_id in self._red_sources(player_id)
                          if self._definition(card_id).name != "杀")
        if self._has_skill(player_id, "longdan"):
            result.extend(card_id for card_id in hand if self._definition(card_id).name == "闪")
        return tuple(dict.fromkeys(result))

    def _has_equipment(self, player_id: str, kind_id: str) -> bool:
        return self._equipment_id(player_id, kind_id) is not None

    def _combined_card_color(self, card_ids: tuple[str, ...]) -> str | None:
        colors = {self._color(card_id) for card_id in card_ids}
        return next(iter(colors)) if len(colors) == 1 else None

    def _weapon_ids(self, player_id: str) -> tuple[str, ...]:
        return tuple(card_id for card_id in self._zone(self._player(player_id).equipment_zone_id).card_ids
                     if CARD_KIND_BY_NAME[self._definition(card_id).name].subtype == "weapon")

    def _borrow_sword_targets(self, wielder_id: str, requester_id: str) -> tuple[str, ...]:
        return tuple(target_id for target_id in self.kill_targets(wielder_id)
                     if target_id != wielder_id and self._player(target_id).alive)

    def _borrow_sword_wielders(self, requester_id: str) -> tuple[str, ...]:
        return tuple(player.player_id for player in self.live_players()
                     if player.player_id != requester_id and self._weapon_ids(player.player_id)
                     and self._borrow_sword_targets(player.player_id, requester_id))

    def _axe_cost_options(self, player_id: str, axe_id: str) -> tuple[str, ...]:
        player = self._player(player_id)
        hand = tuple(self._zone(player.hand_zone_id).card_ids)
        equipment = tuple(card_id for card_id in self._zone(player.equipment_zone_id).card_ids if card_id != axe_id)
        return hand + equipment

    def _equipment_id(self, player_id: str, kind_id: str) -> str | None:
        return next((card_id for card_id in self._zone(self._player(player_id).equipment_zone_id).card_ids
                     if self._definition(card_id).kind_id == kind_id), None)

    def _equipment_slot(self, kind_id: str) -> str | None:
        kind = next((item for item in CARD_KIND_BY_NAME.values() if item.kind_id == kind_id), None)
        if kind is None:
            return None
        if kind.subtype == "weapon":
            return "weapon"
        if kind.subtype == "armor":
            return "armor"
        if kind.subtype in {"horse_plus_one", "horse_minus_one"}:
            return kind.subtype
        return None

    def _has_interactable_card(self, player_id: str) -> bool:
        player = self._player(player_id)
        return any(self._zone(zone_id).card_ids for zone_id in (
            player.hand_zone_id, player.equipment_zone_id, player.judgment_zone_id,
        ))

    def _interactable_areas(self, player_id: str) -> tuple[tuple[str, str], ...]:
        player = self._player(player_id)
        result = []
        if self._zone(player.hand_zone_id).card_ids:
            result.append(("hand", "随机弃置一张隐藏手牌"))
        if self._zone(player.equipment_zone_id).card_ids:
            result.append(("equipment", "弃置一张明置装备"))
        if self._zone(player.judgment_zone_id).card_ids:
            result.append(("judgment", "弃置一张明置判定牌"))
        return tuple(result)

    def _area_zone(self, player_id: str, area: str) -> str:
        player = self._player(player_id)
        return {"hand": player.hand_zone_id, "equipment": player.equipment_zone_id,
                "judgment": player.judgment_zone_id}[area]

    def _has_same_delayed(self, player_id: str, kind_id: str) -> bool:
        return any(self._definition(card_id).kind_id == kind_id
                   for card_id in self._zone(self._player(player_id).judgment_zone_id).card_ids)

    def _clockwise_order(self, start_id: str, *, include_start: bool = True) -> tuple[PlayerState, ...]:
        alive = list(self.live_players())
        if not alive:
            return ()
        index = next((i for i, player in enumerate(alive) if player.player_id == start_id), 0)
        ordered = alive[index:] + alive[:index]
        return tuple(ordered if include_start else ordered[1:])

    def _has_visible_allies(self, viewer_id: str, target_id: str) -> bool:
        viewer = self._player(viewer_id)
        target = self._player(target_id)
        if self.state.mode_id == "two_heroes":
            return viewer.player_id != "P1" and target.player_id != "P1"
        if self.state.mode_id == "duel":
            return False
        if viewer.identity in {Identity.LORD.value, Identity.LOYALIST.value}:
            return target.identity_public and target.identity in {Identity.LORD.value, Identity.LOYALIST.value}
        if viewer.identity == Identity.REBEL.value:
            return target.identity_public and target.identity == Identity.REBEL.value
        return False

    def _can_hujia(self, player_id: str) -> bool:
        return self.state.mode_id == "five_player_identity" and self._is_lord(player_id) and self._has_skill(player_id, "hujia")

    def _hujia_providers(self, lord_id: str) -> tuple[PlayerState, ...]:
        return tuple(player for player in self._clockwise_order(lord_id, include_start=False)
                     if HERO_BY_ID[player.hero_id].faction is Faction.WEI
                     and any(self._definition(card_id).name == "闪" for card_id in self._zone(player.hand_zone_id).card_ids))

    def _is_spectating(self) -> bool:
        player = next((item for item in self.state.players if item.player_id == "P1"), None)
        return bool(player and not player.alive and self.state.mode_id == "five_player_identity" and not self.finished)

    def is_human_current_player(self) -> bool:
        player = self.current_player
        return bool(player and player.alive and player.control is ControlType.HUMAN
                    and player.player_id == "P1" and not self._is_spectating())

    def _equipment_slot_by_id(self, card_id: str) -> str | None:
        return self._equipment_slot(self._definition(card_id).kind_id)

    def _has_horse(self, player_id: str, subtype: str) -> bool:
        return any(CARD_KIND_BY_NAME[self._definition(card_id).name].subtype == subtype
                   for card_id in self._zone(self._player(player_id).equipment_zone_id).card_ids)

    def _winner_label(self, result: str) -> str:
        return {
            "player_side_win": "玩家阵营胜利", "opposing_side_win": "对方胜利",
            "ai_side_win": "电脑阵营胜利", "lord_side_win": "主公与忠臣胜利",
            "rebel_side_win": "反贼阵营胜利", "turncoat_side_win": "内奸胜利",
            "draw": "平局", "unfinished": "未完成",
        }.get(result, result)
