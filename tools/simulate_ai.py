"""Run the deterministic Stage 3 AI matrix without writing formal game records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xssgkpz.core.ai import make_ai_policies
from xssgkpz.core.gameplay import GameEngine
from xssgkpz.core.match import HERO_IDS, create_match, resolve_roster
from xssgkpz.core.state import snapshot_game_state
from xssgkpz.data.modes import Difficulty, Identity


DIFFICULTIES = (Difficulty.SIMPLE, Difficulty.MEDIUM, Difficulty.HARD)
IDENTITIES_BY_MODE: dict[str, tuple[Identity | None, ...]] = {
    "duel": (None,),
    "two_heroes": (None,),
    "five_player_identity": (
        Identity.LORD, Identity.LOYALIST, Identity.REBEL, Identity.TURNCOAT,
    ),
}
DEFAULT_SUMMARY = PROJECT_ROOT / "docs/project/EXEC-04自动模拟汇总.csv"
DEFAULT_BLIND_LOGS = PROJECT_ROOT / "docs/project/EXEC-04盲看日志样本.md"


def _seed_for(base_seed: int, group_index: int, sample_index: int) -> int:
    return base_seed + group_index * 4099 + sample_index * 131


def run_matrix(
    *,
    samples: int,
    base_seed: int,
    turn_limit: int,
    summary_path: Path,
    blind_logs_path: Path,
    group_limit: int | None = None,
) -> int:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    initial_signatures: dict[tuple[str, str, str, int], str] = {}
    blind_samples: dict[Difficulty, tuple[tuple[int, str], ...]] = {}
    processed_groups = 0
    group_index = 0
    for mode_id, identities in IDENTITIES_BY_MODE.items():
        for hero_id in HERO_IDS:
            for identity in identities:
                if group_limit is not None and processed_groups >= group_limit:
                    break
                identity_key = identity.value if identity else ""
                key = (mode_id, hero_id, "", identity_key)
                for sample_index in range(samples):
                    seed = _seed_for(base_seed, group_index, sample_index)
                    for difficulty in DIFFICULTIES:
                        roster = resolve_roster(
                            mode_id=mode_id,
                            player_hero_id=hero_id,
                            seed=seed,
                            player_identity=identity,
                            difficulty=difficulty,
                        )
                        state = create_match(roster, human_player_ids=frozenset())
                        snapshot = snapshot_game_state(state)
                        signature_key = (mode_id, hero_id, identity_key, seed)
                        signature = hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()
                        prior_signature = initial_signatures.setdefault(signature_key, signature)
                        if prior_signature != signature:
                            raise AssertionError(
                                f"initial state differs across difficulty for {signature_key}"
                            )
                        policies = make_ai_policies(
                            state.players, seed=seed, difficulty=difficulty,
                        )
                        engine = GameEngine(
                            state,
                            ai_by_player=policies,
                            auto_turn_limit=turn_limit,
                        )
                        engine.start()
                        while not engine.finished and engine.spectator_waiting:
                            engine.continue_spectator(fast_forward=True)
                        player_ai = policies["P1"]
                        reasons = Counter(
                            _public_reason(decision.reason)
                            for decision in player_ai.decisions
                        )
                        grouped[key + (difficulty.value,)].append({
                            "seed": seed,
                            "outcome": engine.player_outcome or "unfinished",
                            "turns": state.turn_number,
                            "illegal_actions": sum(issue.stage == "play" for issue in engine.ai_issues),
                            "illegal_choices": sum(issue.stage != "play" for issue in engine.ai_issues),
                            "reasons": reasons,
                            "end_reason": state.end_reason or "unknown",
                        })
                        if (mode_id == "five_player_identity" and hero_id == "zhaoyun"
                                and identity is Identity.LOYALIST and sample_index == 0):
                            blind_samples[difficulty] = tuple(
                                (event.turn_number, event.text) for event in engine.public_logs()
                            )
                processed_groups += 1
                group_index += 1
            if group_limit is not None and processed_groups >= group_limit:
                break
        if group_limit is not None and processed_groups >= group_limit:
            break

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    rows = _summary_rows(grouped)
    with summary_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "mode_id", "hero_id", "difficulty", "identity", "sample_count", "seeds",
            "wins", "losses", "draws", "unfinished", "mean_turns",
            "illegal_actions", "illegal_choices", "reason_counts", "end_reasons",
        ))
        writer.writeheader()
        writer.writerows(rows)
    if blind_samples:
        _write_blind_logs(blind_logs_path, blind_samples)

    failed = sum(
        int(row["unfinished"] or 0) + int(row["illegal_actions"] or 0)
        + int(row["illegal_choices"] or 0)
        for row in rows
    )
    expected_groups = processed_groups * len(DIFFICULTIES)
    print(f"groups={processed_groups} scenarios, {expected_groups} difficulty groups")
    print(f"rows={len(rows)} samples={samples} failures={failed}")
    print(f"summary={summary_path}")
    if blind_samples:
        print(f"blind_logs={blind_logs_path}")
    return 1 if failed else 0


def _public_reason(reason: str) -> str:
    for personality in ("aggression", "caution", "control", "support", "stockpiling"):
        reason = reason.replace(f"personality_{personality}", "personality_adjustment")
    return reason


def _summary_rows(grouped: dict[tuple[str, ...], list[dict[str, object]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (mode_id, hero_id, _unused, identity, difficulty), matches in sorted(grouped.items()):
        outcomes = Counter(str(match["outcome"]) for match in matches)
        reasons: Counter[str] = Counter()
        end_reasons: Counter[str] = Counter()
        for match in matches:
            reasons.update(match["reasons"])
            end_reasons[str(match["end_reason"])] += 1
        rows.append({
            "mode_id": mode_id,
            "hero_id": hero_id,
            "difficulty": difficulty,
            "identity": identity,
            "sample_count": len(matches),
            "seeds": ";".join(str(match["seed"]) for match in matches),
            "wins": outcomes["win"],
            "losses": outcomes["loss"],
            "draws": outcomes["draw"],
            "unfinished": outcomes["unfinished"],
            "mean_turns": round(sum(int(match["turns"]) for match in matches) / max(1, len(matches)), 2),
            "illegal_actions": sum(int(match["illegal_actions"]) for match in matches),
            "illegal_choices": sum(int(match["illegal_choices"]) for match in matches),
            "reason_counts": json.dumps(reasons, ensure_ascii=False, sort_keys=True),
            "end_reasons": json.dumps(end_reasons, ensure_ascii=False, sort_keys=True),
        })
    return rows


def _write_blind_logs(path: Path, samples: dict[Difficulty, tuple[str, ...]]) -> None:
    # Stable ordering hides the tier labels while keeping the sample reproducible.
    ordered = sorted(samples.items(), key=lambda pair: hashlib.sha256(pair[0].value.encode()).hexdigest())
    lines = [
        "# EXEC-04 盲看日志样本",
        "",
        "以下三个样本来自同一模式、同一武将、同一身份与同一随机种子；难度和性格档案标签已省略。日志只采用对局公开日志，没有导出隐藏手牌、隐藏身份或未来牌序。样本排序未对应简单／中等／困难顺序。",
        "",
        "样本场景：五人身份局，赵云，玩家座位为忠臣。",
    ]
    labels = (chr(0x7532), chr(0x4e59), chr(0x4e19))
    for index, (_difficulty, events) in enumerate(ordered):
        lines.extend(("", f"## 样本 {labels[index]}", ""))
        lines.extend(f"- 第{turn}回合：{event}" for turn, event in events)
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--base-seed", type=int, default=20260926)
    parser.add_argument("--turn-limit", type=int, default=300)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--blind-logs", type=Path, default=DEFAULT_BLIND_LOGS)
    parser.add_argument("--group-limit", type=int, default=None,
                        help="development-only prefix of scenario groups")
    args = parser.parse_args()
    if args.samples < 1 or args.turn_limit < 1:
        parser.error("samples and turn-limit must be positive")
    return run_matrix(
        samples=args.samples,
        base_seed=args.base_seed,
        turn_limit=args.turn_limit,
        summary_path=args.summary,
        blind_logs_path=args.blind_logs,
        group_limit=args.group_limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
