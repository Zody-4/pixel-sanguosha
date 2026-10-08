"""Observation-only AI policies with explicit difficulty and private personality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xssgkpz.core.actions import ChoiceOption, DecisionRequest, GameAction
from xssgkpz.core.observation import ObservationView, ObservedPlayer
from xssgkpz.core.random_stream import FixedSeedRandom
from xssgkpz.data.ai_personalities import (
    PERSONALITIES_BY_HERO,
    Personality,
)
from xssgkpz.data.cards import CARD_BY_ID
from xssgkpz.data.heroes import HERO_BY_ID
from xssgkpz.data.modes import Difficulty


_NO_BENEFIT_FRIENDLY_TARGET_FEATURES = frozenset({
    "kill", "duel", "dismantle", "steal", "indulgence",
    "wusheng", "qixi", "tieji", "jijiang",
})


@dataclass(frozen=True, slots=True)
class PersonalityProfile:
    hero_id: str
    primary: Personality
    secondary: Personality
    active: Personality
    roll: int


@dataclass(frozen=True, slots=True)
class AIDecisionTrace:
    player_id: str
    turn_number: int
    difficulty: Difficulty
    chosen_action_id: str | None
    reason: str
    ranked_actions: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class AIOptionTrace:
    player_id: str
    turn_number: int
    request_kind: str
    choice_ids: tuple[str, ...]
    reason: str


class SimpleAI:
    """Baseline policy retained for rule fixtures and simple-tactic comparisons."""

    def __init__(self) -> None:
        self.decisions: list[AIDecisionTrace] = []
        self.option_decisions: list[AIOptionTrace] = []

    def choose_action(self, view: ObservationView, actions: tuple[GameAction, ...]) -> GameAction | None:
        if not actions:
            return None
        scored = tuple((_simple_action_score(view, action), action) for action in actions)
        ranked = sorted(scored, key=lambda item: (item[0], item[1].action_id), reverse=True)
        best_score, best = ranked[0]
        chosen = best if best_score > 0 else None
        self.decisions.append(AIDecisionTrace(
            view.viewer_id, view.turn_number, Difficulty.SIMPLE,
            chosen.action_id if chosen else None,
            "baseline_positive_score" if chosen else "no_positive_baseline_score",
            tuple((action.action_id, score) for score, action in ranked[:5]),
        ))
        return chosen

    def choose_option(
        self,
        view: ObservationView,
        request: DecisionRequest,
    ) -> str | tuple[str, ...]:
        choice, reason = _simple_option(view, request)
        choices = (choice,) if isinstance(choice, str) else tuple(choice)
        self.option_decisions.append(AIOptionTrace(
            view.viewer_id, view.turn_number, request.kind, choices, reason,
        ))
        return choice


class StrategicAI(SimpleAI):
    """A three-tier policy that only scores information present in its observation."""

    PERSONALITY_WINDOW = 8

    def __init__(
        self,
        *,
        difficulty: Difficulty,
        personality: PersonalityProfile,
    ) -> None:
        super().__init__()
        self.difficulty = difficulty
        self.personality = personality
        self._chosen_action: GameAction | None = None

    def choose_action(self, view: ObservationView, actions: tuple[GameAction, ...]) -> GameAction | None:
        if not actions:
            self._chosen_action = None
            self.decisions.append(AIDecisionTrace(
                view.viewer_id, view.turn_number, self.difficulty, None,
                "no_legal_actions", (),
            ))
            return None

        base_scores = {action.action_id: _simple_action_score(view, action) for action in actions}
        best_base = max(base_scores.values())
        beliefs = infer_public_identities(view)
        ranked_scores: list[tuple[int, GameAction, str]] = []
        for action in actions:
            score = base_scores[action.action_id]
            reasons = ["baseline"]
            if self.difficulty in {Difficulty.MEDIUM, Difficulty.HARD}:
                tactical, explanation = _tactical_adjustment(view, action, beliefs)
                score += tactical
                if explanation:
                    reasons.append(explanation)
            if self.difficulty is Difficulty.HARD:
                sequence = _short_sequence_adjustment(action, actions)
                score += sequence
                if sequence:
                    reasons.append("two_action_setup")
                utility, explanation = _hard_action_utility(view, action, actions, beliefs)
                score += utility
                if explanation:
                    reasons.append(explanation)
            if best_base - base_scores[action.action_id] <= self.PERSONALITY_WINDOW:
                preference = _personality_adjustment(view, action, beliefs, self.personality.active)
                score += preference
                if preference:
                    reasons.append(f"personality_{self.personality.active.value}")
            ranked_scores.append((score, action, "+".join(reasons)))

        ranked_scores.sort(key=lambda item: (item[0], item[1].action_id), reverse=True)
        best_score, best_action, reason = ranked_scores[0]
        chosen = best_action if best_score > 0 else None
        self._chosen_action = chosen
        self.decisions.append(AIDecisionTrace(
            view.viewer_id, view.turn_number, self.difficulty,
            chosen.action_id if chosen else None,
            reason if chosen else "no_positive_policy_score",
            tuple((action.action_id, score) for score, action, _ in ranked_scores[:5]),
        ))
        return chosen

    def choose_option(
        self,
        view: ObservationView,
        request: DecisionRequest,
    ) -> str | tuple[str, ...]:
        selected, reason = _simple_option(view, request)
        beliefs = infer_public_identities(view)
        own = next(player for player in view.players if player.player_id == view.viewer_id)
        context = dict(request.context)

        if request.kind == "rescue" and self.difficulty is not Difficulty.SIMPLE:
            target = next((player for player in view.players
                           if player.player_id == context.get("target_id")), None)
            if target and target.hp <= 0 and (
                target.player_id == own.player_id
                or _team_probability(view, own, target, beliefs) >= 0.5
            ):
                peach = next((option.choice_id for option in request.options
                              if option.category == "peach"), None)
                if peach:
                    selected, reason = peach, "save_self_or_likely_ally"

        if request.kind == "nullification" and self.difficulty is not Difficulty.SIMPLE:
            target = next((player for player in view.players
                           if player.player_id == context.get("target_id")), None)
            if target:
                ally_probability = _team_probability(view, own, target, beliefs)
                cancelled = bool(context.get("cancelled"))
                trick_kind = str(context.get("trick_kind_id", ""))
                harmful = trick_kind in {"duel", "dismantle", "indulgence", "barbarians"}
                beneficial = trick_kind in {"draw_two", "harvest"}
                should_cancel = (ally_probability >= 0.5) if harmful else (
                    ally_probability < 0.5 if beneficial else cancelled
                )
                if should_cancel != cancelled:
                    negate = next((option.choice_id for option in request.options
                                   if option.category == "negate"), None)
                    if negate:
                        selected, reason = negate, "public_team_probability"

        cost_requests = {"discard", "cost_two", "zhiheng_cards", "jieyin_cost"}
        if self.difficulty is Difficulty.HARD:
            cost_requests.update({"rende_cards", "serpent_spear_cost"})
        if request.kind in cost_requests:
            candidates = [option for option in request.options
                          if option.category in {"discard", "give"}]
            count = request.min_choices
            if candidates and count > 0 and self.difficulty is not Difficulty.SIMPLE:
                ranked = sorted(candidates, key=lambda option: (
                    _card_value(option.value, option.label), option.choice_id,
                ))
                selected = tuple(option.choice_id for option in ranked[:count])
                reason = "preserve_high_value_cards"
                if count == 1:
                    selected = selected[0]

        if request.kind == "nullification" and self.difficulty is Difficulty.HARD:
            target = next((p for p in view.players if p.player_id == context.get("target_id")), None)
            if target:
                ally = _team_probability(view, own, target, beliefs)
                kind = str(context.get("trick_kind_id", ""))
                harmful = kind in {"duel", "dismantle", "steal", "indulgence", "barbarians", "arrows", "lightning"}
                beneficial = kind in {"draw_two", "harvest", "peach_garden"}
                # Decide both to counter and to pass: do not inherit a baseline
                # counter when the current effect already favours our side.
                should_cancel = ally >= .5 if harmful else ally < .5 if beneficial else None
                if should_cancel is not None:
                    category = "negate" if should_cancel != bool(context.get("cancelled")) else "pass"
                    option = next((o for o in request.options if o.category == category), None)
                    if option:
                        selected, reason = option.choice_id, "hard_effect_and_team_nullification"

        if self.difficulty is Difficulty.HARD and request.kind in {"dismantle_area", "steal_area"}:
            target_ids = self._chosen_action.intent.target_ids if self._chosen_action else ()
            target = next((p for p in view.players if p.player_id in target_ids), None)
            if target:
                ally = _team_probability(view, own, target, beliefs)
                # Hidden hand choices remain random in the engine; only public
                # equipment/judgement can be evaluated by name.
                preferred = "judgment" if ally >= .5 and target.judgment_card_ids else "equipment" if ally < .5 and target.equipment_card_ids else "hand"
                option = next((o for o in request.options if o.category == preferred), None)
                if option:
                    selected, reason = option.choice_id, "choose_public_control_area"
        if self.difficulty is Difficulty.HARD and request.kind in {"dismantle_visible_card", "steal_visible_card", "harvest_pick"}:
            def value(option):
                definition = _visible_definition(option.value)
                if definition and definition.kind_id in {"renwang_shield", "bagua_formation"}:
                    return 30 if request.kind != "harvest_pick" else 8
                return _card_value(option.value, option.label)
            if request.options:
                selected = max(request.options, key=lambda o: (value(o), o.choice_id)).choice_id
                reason = "choose_visible_card_value"

        choices = (selected,) if isinstance(selected, str) else tuple(selected)
        self.option_decisions.append(AIOptionTrace(
            view.viewer_id, view.turn_number, request.kind, choices, reason,
        ))
        return selected


def make_personality_profile(hero_id: str, seed: int) -> PersonalityProfile:
    definition = PERSONALITIES_BY_HERO[hero_id]
    roll = FixedSeedRandom(_stable_profile_seed(hero_id, seed)).randbelow(10)
    active = definition.primary if roll < 7 else definition.secondary
    return PersonalityProfile(
        hero_id, definition.primary, definition.secondary, active, roll,
    )


def make_ai_policies(
    players: tuple[Any, ...] | list[Any],
    *,
    seed: int,
    difficulty: Difficulty,
) -> dict[str, StrategicAI]:
    """Build per-player policies; each gets a separate, private profile."""
    return {
        player.player_id: StrategicAI(
            difficulty=difficulty,
            personality=make_personality_profile(player.hero_id, seed),
        )
        for player in players
    }


def infer_public_identities(view: ObservationView) -> dict[str, dict[str, float]]:
    """Estimate hidden roles from role counts and public direct-action history only."""
    identity_names = ("lord", "loyalist", "rebel", "turncoat")
    if view.mode_id != "five_player_identity":
        result: dict[str, dict[str, float]] = {}
        for player in view.players:
            if player.identity is not None:
                result[player.player_id] = {player.identity: 1.0}
            else:
                result[player.player_id] = {}
        return result

    role_counts = {"lord": 1, "loyalist": 1, "rebel": 2, "turncoat": 1}
    known = {player.player_id: player.identity for player in view.players if player.identity is not None}
    for identity in known.values():
        if identity in role_counts:
            role_counts[identity] = max(0, role_counts[identity] - 1)
    hidden = [player for player in view.players if player.identity is None]
    priors: dict[str, dict[str, float]] = {}
    for player in view.players:
        if player.identity is not None:
            priors[player.player_id] = {player.identity: 1.0}
        elif hidden:
            denominator = sum(role_counts.values()) or len(hidden)
            priors[player.player_id] = {
                role: count / denominator for role, count in role_counts.items() if count
            }
        else:
            priors[player.player_id] = {}

    offensive = {
        "kill", "sha", "duel", "dismantle", "steal", "indulgence", "lightning",
        "wusheng", "longdan", "tieji", "serpent_spear", "fanjian",
    }
    for action in view.public_actions:
        if not any(
            target.player_id in action.target_ids and target.identity == "lord"
            for target in view.players
        ):
            continue
        # Requests that ask other characters to provide a response are not role evidence.
        if action.kind_id in {"hujia", "jijiang", "hujia_response", "jijiang_response"}:
            continue
        if action.kind_id not in offensive:
            continue
        distribution = priors.get(action.actor_id, {})
        likelihood = {"lord": 0.25, "loyalist": 0.45, "rebel": 2.8, "turncoat": 1.7}
        weighted = {role: probability * likelihood.get(role, 1.0)
                    for role, probability in distribution.items()}
        total = sum(weighted.values())
        if total:
            priors[action.actor_id] = {role: probability / total
                                       for role, probability in weighted.items()}
    return priors


def _simple_action_score(view: ObservationView, action: GameAction) -> int:
    self_player = next(player for player in view.players if player.player_id == view.viewer_id)
    target = next((player for player in view.players if player.player_id in action.intent.target_ids), None)
    kind = action.action_id
    intent = action.intent
    feature = _action_feature(action)
    targets = tuple(
        player for player in view.players
        if player.player_id in action.intent.target_ids
    )
    if (
        feature in _NO_BENEFIT_FRIENDLY_TARGET_FEATURES
        and targets
        and all(_known_allies(self_player.identity, player.identity) for player in targets)
    ):
        return -10
    if intent.skill_id == "zhouyu.yingzi":
        return 95
    if intent.skill_id == "sunquan.zhiheng":
        return 90
    if intent.skill_id == "zhouyu.fanjian":
        return 82
    if intent.skill_id == "rende":
        return 35 if target and _known_allies(self_player.identity, target.identity) else -5
    if intent.skill_id == "wusheng" and target is not None:
        return 79 + (self_player.max_hp - target.hp)
    if intent.skill_id == "qixi" and target is not None:
        return 52 + target.hand_count
    if intent.skill_id == "jijiang" and target is not None:
        return 74 + (self_player.max_hp - target.hp)
    if intent.card_id:
        if kind.startswith("play:tao") and self_player.hp < self_player.max_hp:
            return 110
        if kind.startswith("play:draw_two"):
            return 85
        if kind.startswith("play:kill") and target is not None:
            return 80 + (self_player.max_hp - target.hp)
        if kind.startswith("play:duel") and target is not None:
            return 63 + (self_player.max_hp - target.hp)
        if kind.startswith("play:barbarians"):
            return 61
        if kind.startswith("play:harvest"):
            return 60
        if kind.startswith("play:dismantle"):
            return 50 + (target.hand_count if target else 0)
        if kind.startswith("equip:"):
            return 45
    return 0


def _simple_option(view: ObservationView, request: DecisionRequest) -> tuple[str | tuple[str, ...], str]:
    by_category = {option.category: option for option in request.options}
    own = next(player for player in view.players if player.player_id == view.viewer_id)
    context = dict(request.context)
    pass_id = next((option.choice_id for option in request.options if option.category == "pass"), None)

    if request.kind == "rescue":
        target = next((player for player in view.players if player.player_id == context.get("target_id")), None)
        if target and target.hp <= 0 and (
            target.player_id == own.player_id or _known_allies(own.identity, target.identity)
        ):
            peach = next((option for option in request.options if option.category == "peach"), None)
            if peach:
                return peach.choice_id, "rescue_self_or_known_ally"
    elif request.kind in {"flash", "duel_kill", "hujia", "hujia_provider", "nullification", "axe_payment", "ganglie", "qinglong_followup"}:
        if request.kind == "nullification":
            target = next((player for player in view.players if player.player_id == context.get("target_id")), None)
            cancelled = bool(context.get("cancelled"))
            trick_kind = context.get("trick_kind_id")
            ally = bool(target and target.identity is not None and _known_allies(own.identity, target.identity))
            if trick_kind in {"duel", "dismantle", "indulgence", "barbarians"}:
                should_cancel = bool(target and target.identity is not None and ally)
            elif trick_kind in {"draw_two", "harvest"}:
                should_cancel = bool(target and target.identity is not None and not ally)
            else:
                should_cancel = False
            if target and should_cancel != cancelled:
                negate = next((option for option in request.options if option.category == "negate"), None)
                if negate:
                    return negate.choice_id, "known_identity_nullification"
        if request.kind in {"hujia", "hujia_provider"}:
            flash = next((option for option in request.options if option.category == "flash"), None)
            if flash:
                return flash.choice_id, "provide_flash"
        preferred = {
            "flash": ("flash", "bagua"),
            "duel_kill": ("kill",),
            "qinglong_followup": ("continue",),
        }.get(request.kind, ())
        for category in preferred:
            if category in by_category:
                return by_category[category].choice_id, f"prefer_{category}"
        if request.kind == "axe_payment":
            payments = tuple(option.choice_id for option in request.options if option.category == "discard")
            if len(payments) >= 2:
                return payments[:2], "axe_payment_for_extra_hit"
        if request.kind == "ganglie":
            payments = tuple(option.choice_id for option in request.options if option.category == "discard")
            if len(payments) >= 2 and own.hp <= 1:
                return payments[:2], "avoid_self_damage_at_low_hp"
            damage = next((option for option in request.options if option.category == "damage"), None)
            if damage:
                return damage.choice_id, "ganglie_damage_over_card_cost"
    elif request.kind == "harvest_pick":
        option = next((option for option in request.options if option.category == "take"), None)
        if option:
            return option.choice_id, "take_harvest_card"
    elif request.kind in {"rende_cards", "zhiheng_cards"}:
        option = next((option for option in request.options if option.category in {"give", "discard"}), None)
        if option:
            return option.choice_id, "first_available_card"
    elif request.kind == "jieyin_cost":
        return tuple(option.choice_id for option in request.options if option.category == "discard")[:request.min_choices], "pay_jieyin_cost"
    elif request.kind == "serpent_spear_cost":
        costs = tuple(option.choice_id for option in request.options if option.category == "discard")
        if len(costs) >= request.min_choices:
            return costs[:request.min_choices], "pay_serpent_spear_cost"
    elif request.kind == "jianxiong":
        option = next((option for option in request.options if option.category == "take"), None)
        if option:
            return option.choice_id, "take_damage_card"
    elif request.kind == "jijiang":
        option = next((option for option in request.options if option.category == "kill"), None)
        if option:
            return option.choice_id, "accept_public_response_request"
    elif request.kind == "fankui":
        option = next((option for option in request.options if option.category in {"take_public", "take_hidden"}), None)
        if option:
            return option.choice_id, "take_available_card"
    elif request.kind == "guicai":
        option = next((option for option in request.options if option.category == "replace"), None)
        if option:
            return option.choice_id, "replace_judgment"
    elif request.kind in {
        "yingzi", "lianying", "xiaoji", "luoyi", "tuxi", "guanxing", "luoshen",
        "tieji", "double_swords", "frost_sword", "biyue", "qingnang",
    }:
        option = next((option for option in request.options if option.category == "yes"), None)
        if option:
            return option.choice_id, "use_optional_skill"
    elif request.kind == "tuxi_targets":
        targets = tuple(option.choice_id for option in request.options if option.category == "target")
        if targets:
            return targets[:request.min_choices], "take_available_target_cards"
    elif request.kind == "liuli":
        option = next((option for option in request.options if option.category == "pass"), None)
        if option:
            return option.choice_id, "keep_attack_target"
    elif request.kind == "kirin_bow":
        option = next((option for option in request.options if option.category == "mount"), None)
        if option:
            return option.choice_id, "remove_mount"
    elif request.kind == "yiji_give":
        option = next((option for option in request.options if option.category == "keep"), None)
        if option:
            return option.choice_id, "keep_card"
    elif request.kind == "lijian_initiator":
        option = next((option for option in request.options if option.category == "target"), None)
        if option:
            return option.choice_id, "choose_legal_target"
    elif request.kind == "fan_jian_suit" and own.hand_count <= 2:
        option = next((option for option in request.options if option.category == "spades"), None)
        if option:
            return option.choice_id, "choose_low_hand_suit"
    elif request.kind == "rende_target":
        option = next((option for option in request.options if option.category == "target"), None)
        if option:
            return option.choice_id, "choose_legal_target"
    elif request.kind in {"discard", "cost_two"}:
        discard = tuple(option.choice_id for option in request.options if option.category == "discard")
        if len(discard) >= request.min_choices:
            return discard[:request.min_choices], "discard_first_legal_cards"

    if pass_id is not None:
        return pass_id, "pass_optional_choice"
    if request.min_choices == 0:
        return (), "empty_optional_choice"
    if request.options:
        return request.options[0].choice_id, "first_legal_option"
    return (), "no_available_options"


def _tactical_adjustment(
    view: ObservationView,
    action: GameAction,
    beliefs: dict[str, dict[str, float]],
) -> tuple[int, str | None]:
    own = next(player for player in view.players if player.player_id == view.viewer_id)
    targets = [player for player in view.players if player.player_id in action.intent.target_ids]
    feature = _action_feature(action)
    if not targets and feature in {"barbarians", "arrows", "peach_garden"}:
        targets = [player for player in view.players if player.player_id != own.player_id and player.alive]

    score = 0
    notes: list[str] = []
    for target in targets:
        ally = _team_probability(view, own, target, beliefs)
        if feature in {"kill", "duel", "dismantle", "steal", "indulgence", "lightning", "barbarians", "arrows"}:
            if ally >= 0.5:
                score -= round(28 * ally)
                notes.append("avoid_likely_ally")
            else:
                distance = _distance_to(view, target.player_id)
                closeness = max(-2, min(3, 4 - distance)) if distance is not None else 0
                score += round((1 - ally) * (
                    _threat_value(target) + max(0, target.max_hp - target.hp) * 2 + closeness
                ))
                notes.append("prefer_public_enemy_threat")
            if feature in {"dismantle", "steal", "qixi"}:
                equipment_pressure = _equipment_pressure(target)
                if equipment_pressure:
                    score += round((1 - ally) * min(8, equipment_pressure))
                    notes.append("public_equipment_value")
        elif feature in {"peach", "peach_garden", "healing"}:
            score += round(14 * ally * max(0, target.max_hp - target.hp))
            if target.hp <= 1:
                score += round(8 * ally)
            if not ally and target.player_id != own.player_id:
                score -= 10
                notes.append("preserve_heal_for_team")
        elif feature in {"rende", "recovery", "draw"} and target.player_id != own.player_id:
            score += round(5 * ally * max(1, target.max_hp - target.hp))

    if feature == "kill" and own.hp <= 1 and own.hand_count <= 1:
        score -= 3
        notes.append("retain_survival_resource")
    if feature in {"draw_two", "harvest", "yingzi", "zhiheng"}:
        score += min(5, max(0, 4 - own.hand_count))
        if own.hand_count <= 2:
            notes.append("rebuild_hand")
    if feature.startswith("equip_"):
        own_equipment = next(player for player in view.players if player.player_id == own.player_id)
        current_pressure = _equipment_pressure(own_equipment)
        if feature == "equip_armor":
            score += 5 if own.hp <= 2 else 2
            if current_pressure >= 5:
                score -= 3
        elif feature == "equip_weapon":
            score += 2 if current_pressure < 4 else 0
        elif feature == "equip_mount":
            score += 1
        notes.append("compare_public_equipment")
    if own.hp <= 1 and feature in {"equip_armor", "equip_mount"}:
        score += 3
        notes.append("low_hp_defense")
    return score, "+".join(dict.fromkeys(notes)) if notes else None


def _short_sequence_adjustment(action: GameAction, actions: tuple[GameAction, ...]) -> int:
    feature = _action_feature(action)
    if feature not in {"dismantle", "steal", "qixi"} or not action.intent.target_ids:
        return 0
    target_id = action.intent.target_ids[0]
    if not any(
        other is not action and other.intent.target_ids == (target_id,)
        and _action_feature(other) in {"kill", "duel"}
        and not (_action_material_ids(action) & _action_material_ids(other))
        for other in actions
    ):
        return 0
    return 7


def _action_material_ids(action: GameAction) -> set[str]:
    intent = action.intent
    return set(intent.cost_card_ids) | ({intent.card_id} if intent.card_id else set())


def _visible_definition(card_id):
    return CARD_BY_ID.get(card_id.removeprefix("card:")) if isinstance(card_id, str) else None


def _public_equipment(player: ObservedPlayer) -> set[str]:
    return {d.kind_id for cid in player.equipment_card_ids if (d := _visible_definition(cid))}


def _hero_has(player: ObservedPlayer, skill: str) -> bool:
    hero = HERO_BY_ID.get(player.hero_id)
    return bool(hero and any(s.rsplit(".", 1)[-1] == skill for s in hero.skill_ids))


def _attack_color(action: GameAction) -> str | None:
    materials = [_visible_definition(cid) for cid in _action_material_ids(action)]
    colors = {"black" if d.suit.value in {"spades", "clubs"} else "red" for d in materials if d}
    # Mixed-colour spear material produces a colourless virtual kill. Jijiang
    # providers are unknown at decision time: never assume their card colour.
    if action.intent.skill_id == "jijiang":
        return None
    return next(iter(colors)) if len(colors) == 1 else None


def _hard_action_utility(view, action, actions, beliefs) -> tuple[int, str | None]:
    """Bounded public-board evaluation; never accesses engine/private opponents."""
    own = next(p for p in view.players if p.player_id == view.viewer_id)
    targets = [p for p in view.players if p.player_id in action.intent.target_ids]
    feature = _action_feature(action)
    attack = feature in {"kill", "wusheng", "longdan", "serpent_spear", "jijiang", "tieji"}
    own_equipment = _public_equipment(own)
    hand = own.own_hand_card_ids or ()
    spent = _action_material_ids(action)
    remaining = [d for cid in hand if cid not in spent and (d := _visible_definition(cid))]
    score, notes = 0, []
    for target in targets:
        equipment = _public_equipment(target)
        ally = _team_probability(view, own, target, beliefs)
        if attack:
            if ("renwang_shield" in equipment and "qinggang_sword" not in own_equipment
                    and _attack_color(action) == "black"):
                return -1000, "known_ineffective_attack"
            if ally >= .65:
                score -= 110
                notes.append("avoid_team_damage")
            else:
                # Empty/few-card targets are more vulnerable, not guaranteed to
                # lack a flash. Public armour and retaliation temper the estimate.
                score += max(0, 3 - target.hand_count) * 8
                if "bagua_formation" in equipment and "qinggang_sword" not in own_equipment:
                    score -= 24
                    notes.append("armour_response_risk")
                if target.hp == 1:
                    score += 24
                    notes.append("finish_vulnerable_enemy")
                if _hero_has(target, "ganglie"):
                    score -= 45 if own.hp == 1 else 14
                    notes.append("retaliation_risk")
                if _hero_has(target, "fankui") or _hero_has(target, "yiji") or _hero_has(target, "jianxiong"):
                    score -= 12 if target.hp > 1 else 0
                    notes.append("damage_trigger_value")
        if feature == "duel":
            kills = sum(d.kind_id == "sha" or (_hero_has(own, "wusheng") and d.suit.value in {"hearts", "diamonds"})
                        or (_hero_has(own, "longdan") and d.kind_id == "shan") for d in remaining)
            score += 10 * min(2, kills) - 12 * min(3, target.hand_count)
            if own.hp <= 1 and kills == 0:
                score -= 80
            if _hero_has(target, "wushuang") and not _hero_has(own, "wushuang"):
                score -= 30
            notes.append("duel_response_budget")
        if feature in {"dismantle", "steal", "qixi"} and ally < .5:
            followups = [a for a in actions if a.intent.target_ids == (target.player_id,)
                         and _action_feature(a) in {"kill", "wusheng", "longdan", "serpent_spear"}
                         and not (spent & _action_material_ids(a))]
            if followups and equipment & {"renwang_shield", "bagua_formation"}:
                score += 48
                notes.append("remove_defence_before_attack")
        if feature == "rende":
            score += round(30 * ally) if ally >= .5 else -30
            notes.append("team_transfer_value")

    if feature in {"barbarians", "arrows", "peach_garden", "harvest"}:
        utility = 28.0 * min(1, own.max_hp - own.hp) if feature == "peach_garden" else 12.0 if feature == "harvest" else 0.0
        for target in view.players:
            if target.player_id == own.player_id or not target.alive:
                continue
            ally = _team_probability(view, own, target, beliefs)
            if feature == "peach_garden":
                utility += (2 * ally - 1) * min(1, target.max_hp - target.hp) * 28
            elif feature == "harvest":
                utility += (2 * ally - 1) * 12
            else:
                vulnerability = 30 + max(0, 3 - target.hand_count) * 8 + (25 if target.hp == 1 else 0)
                utility += (1 - 2 * ally) * vulnerability
        score += round(utility) - (65 if utility < 0 else 0)
        notes.append("whole_table_effect_value")

    if feature == "equip_weapon" and action.intent.card_id:
        definition = _visible_definition(action.intent.card_id)
        if definition and definition.kind_id == "qinggang_sword" and any(
                "renwang_shield" in _public_equipment(t) and _team_probability(view, own, t, beliefs) < .5
                for t in view.players if t.alive and t.player_id != own.player_id):
            if any(_action_feature(a) in {"kill", "longdan", "serpent_spear"} and _attack_color(a) == "black" for a in actions):
                score += 60
                notes.append("equip_armour_bypass_first")
    if feature == "draw_two":
        score += 20
        notes.append("draw_before_commit")
    if feature != "peach" and own.hp <= 2:
        used = [d for cid in spent if (d := _visible_definition(cid))]
        if any(d.kind_id == "tao" for d in used):
            score -= 65
            notes.append("preserve_recovery")
        if any(d.kind_id == "shan" for d in used) and not any(d.kind_id == "shan" for d in remaining):
            score -= 26
            notes.append("preserve_last_defence")
    if len(spent) > 1:
        score -= sum(_card_value(cid, "") for cid in spent)
        notes.append("multi_card_opportunity_cost")
    return score, "+".join(dict.fromkeys(notes)) if notes else None


def _personality_adjustment(
    view: ObservationView,
    action: GameAction,
    beliefs: dict[str, dict[str, float]],
    personality: Personality,
) -> int:
    own = next(player for player in view.players if player.player_id == view.viewer_id)
    targets = [player for player in view.players if player.player_id in action.intent.target_ids]
    feature = _action_feature(action)
    allies = max((_team_probability(view, own, target, beliefs) for target in targets), default=0.0)
    enemies = max((1 - _team_probability(view, own, target, beliefs) for target in targets), default=0.0)
    if personality is Personality.AGGRESSION and feature in {
        "kill", "duel", "barbarians", "arrows", "wusheng", "tieji", "fanjian",
    }:
        return 3 if enemies >= 0.5 else 1
    if personality is Personality.CAUTION and feature in {"equip_armor", "equip_mount", "draw_two", "harvest"}:
        return 3 if own.hp <= 2 or own.hand_count <= 2 else 1
    if personality is Personality.CONTROL and feature in {"dismantle", "steal", "indulgence", "qixi", "guicai"}:
        return 3 if enemies >= 0.5 else 1
    if personality is Personality.SUPPORT and (
        feature in {"peach", "peach_garden", "rende", "qingnang", "biyue"} and allies > 0
    ):
        return 4 if any(target.hp < target.max_hp for target in targets) else 2
    if personality is Personality.STOCKPILING and feature in {
        "draw_two", "harvest", "yingzi", "zhiheng", "luoshen", "biyue",
    }:
        return 3 if own.hand_count <= 3 else 1
    return 0


def _team_probability(
    view: ObservationView,
    own: ObservedPlayer,
    target: ObservedPlayer,
    beliefs: dict[str, dict[str, float]],
) -> float:
    if target.player_id == own.player_id:
        return 1.0
    if own.identity in {"player_side", "ai_side", "opposing_side"}:
        return 1.0 if own.identity == target.identity else 0.0
    if own.identity in {"lord", "loyalist"}:
        friendly_roles = {"lord", "loyalist"}
    elif own.identity == "rebel":
        friendly_roles = {"rebel"}
    else:
        return 0.0
    distribution = beliefs.get(target.player_id, {})
    return sum(probability for role, probability in distribution.items() if role in friendly_roles)


def _threat_value(player: ObservedPlayer) -> int:
    hero = HERO_BY_ID.get(player.hero_id)
    skill_count = len(hero.skill_ids) if hero else 0
    return min(12, 2 + skill_count + (2 if player.hp <= 2 else 0)
               + (1 if player.hand_count >= 4 else 0)
               + min(4, _equipment_pressure(player)))


def _distance_to(view: ObservationView, player_id: str) -> int | None:
    return dict(view.distances_from_viewer).get(player_id)


def _equipment_pressure(player: ObservedPlayer) -> int:
    value = 0
    for card_id in player.equipment_card_ids:
        definition = CARD_BY_ID.get(card_id.removeprefix("card:"))
        if not definition:
            continue
        if definition.kind_id in {"bagua_formation", "renwang_shield"}:
            value += 5
        elif definition.kind_id in {"jueying", "dilu", "zhuahuangfeidian", "chitu", "dayuan", "zixing"}:
            value += 1
        else:
            value += 3
    return value


def _action_feature(action: GameAction) -> str:
    intent = action.intent
    action_id = action.action_id
    if intent.skill_id:
        key = intent.skill_id.rsplit(".", 1)[-1]
        return {
            "yingzi": "yingzi", "zhiheng": "zhiheng", "fanjian": "fanjian",
            "wusheng": "wusheng", "qixi": "qixi", "rende": "rende",
            "qingnang": "qingnang", "biyue": "biyue", "tieji": "tieji",
            "jijiang": "jijiang", "guicai": "guicai",
        }.get(key, key)
    if action_id.startswith("equip:"):
        kind_id = action_id.split(":", 2)[1]
        if kind_id in {"bagua_formation", "renwang_shield"}:
            return "equip_armor"
        if kind_id in {"jueying", "dilu", "zhuahuangfeidian", "chitu", "dayuan", "zixing"}:
            return "equip_mount"
        return "equip_weapon"
    for prefix, feature in (
        ("play:tao", "peach"), ("play:draw_two", "draw_two"),
        ("play:kill", "kill"), ("play:duel", "duel"),
        ("play:barbarians", "barbarians"), ("play:arrows", "arrows"),
        ("play:harvest", "harvest"), ("play:dismantle", "dismantle"),
        ("play:steal", "steal"), ("play:indulgence", "indulgence"),
        ("play:peach_garden", "peach_garden"),
    ):
        if action_id.startswith(prefix):
            return feature
    return "other"


def _card_value(card_id: Any, label: str) -> int:
    if isinstance(card_id, str):
        normalized = card_id.removeprefix("card:")
        definition = CARD_BY_ID.get(normalized)
        if definition:
            return {
                "tao": 10, "shan": 9, "sha": 8, "negate": 7,
                "draw_two": 7, "duel": 6, "indulgence": 6,
            }.get(definition.kind_id, 3)
    if "桃" in label:
        return 10
    if "闪" in label:
        return 9
    if "杀" in label:
        return 8
    return 3


def _stable_profile_seed(hero_id: str, seed: int) -> int:
    value = seed & ((1 << 64) - 1)
    for byte in hero_id.encode("utf-8"):
        value = ((value ^ byte) * 0x100000001B3) & ((1 << 64) - 1)
    return value


def _known_allies(identity: str | None, other_identity: str | None) -> bool:
    if identity is None or other_identity is None:
        return False
    if identity in {"lord", "loyalist"}:
        return other_identity in {"lord", "loyalist"}
    if identity == "rebel":
        return other_identity == "rebel"
    if identity in {"player_side", "ai_side", "opposing_side"}:
        return identity == other_identity
    return identity == other_identity
