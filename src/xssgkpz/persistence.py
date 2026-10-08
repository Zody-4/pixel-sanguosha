"""Small, versioned settings and append-only result-summary storage."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xssgkpz import APP_VERSION, RULES_VERSION
from xssgkpz.data.settings import AiDisplaySpeed, Settings, SkillAnimation, WindowMode


def data_directory() -> Path:
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        base = Path(local_app_data)
    elif os.name == "nt":
        base = Path.home() / "AppData" / "Local"
    elif xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        base = Path(xdg_data_home)
    else:
        base = Path.home() / ".local" / "share"
    return base / "xssgkpz"


def settings_path() -> Path:
    return data_directory() / "settings.json"


def records_path() -> Path:
    return data_directory() / "records.jsonl"


def _isolate_corrupt_file(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = path.with_name(f"{path.name}.corrupt-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}-{suffix}")
        suffix += 1
    path.replace(candidate)
    return candidate


def _atomic_write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _settings_payload(settings: Settings) -> dict[str, Any]:
    return {
        "schema_version": settings.schema_version,
        "window_mode": settings.window_mode.value,
        "resolution_width": settings.resolution_width,
        "resolution_height": settings.resolution_height,
        "ui_scale": settings.ui_scale,
        "ai_display_speed": settings.ai_display_speed.value,
        "skill_animation": settings.skill_animation.value,
        "music_volume": settings.music_volume,
        "audio_scale_version": settings.audio_scale_version,
        "voice_volume": settings.voice_volume,
        "effects_volume": settings.effects_volume,
        "card_details_enabled": settings.card_details_enabled,
        "card_details_size": settings.card_details_size,
        "card_details_x": settings.card_details_x,
        "card_details_y": settings.card_details_y,
        "card_details_layouts": settings.card_details_layouts,
    }


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    target = path or settings_path()
    _atomic_write_text(target, json.dumps(_settings_payload(settings), ensure_ascii=False, indent=2) + "\n")
    return target


def load_settings(path: Path | None = None) -> Settings:
    target = path or settings_path()
    if not target.exists():
        return Settings()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("settings root must be an object")
        version = payload.get("schema_version", 1)
        if not isinstance(version, int) or version < 1 or version > 1:
            raise ValueError(f"unsupported settings schema version: {version}")
        defaults = Settings()
        return Settings(
            schema_version=version,
            window_mode=WindowMode(payload.get("window_mode", defaults.window_mode.value)),
            resolution_width=int(payload.get("resolution_width", defaults.resolution_width)),
            resolution_height=int(payload.get("resolution_height", defaults.resolution_height)),
            ui_scale=float(payload.get("ui_scale", defaults.ui_scale)),
            ai_display_speed=AiDisplaySpeed(payload.get("ai_display_speed", defaults.ai_display_speed.value)),
            skill_animation=SkillAnimation(payload.get("skill_animation", defaults.skill_animation.value)),
            music_volume=float(payload.get("music_volume", defaults.music_volume)) if payload.get("audio_scale_version") == 2 else defaults.music_volume,
            voice_volume=float(payload.get("voice_volume", defaults.voice_volume)) if payload.get("audio_scale_version") == 2 else defaults.voice_volume,
            effects_volume=float(payload.get("effects_volume", defaults.effects_volume)) if payload.get("audio_scale_version") == 2 else defaults.effects_volume,
            card_details_enabled=payload.get("card_details_enabled", defaults.card_details_enabled),
            card_details_size=float(payload.get("card_details_size", defaults.card_details_size)),
            card_details_x=float(payload.get("card_details_x", defaults.card_details_x)),
            card_details_y=float(payload.get("card_details_y", defaults.card_details_y)),
            card_details_layouts=tuple((str(mode), float(size), float(x), float(y)) for mode, size, x, y in payload.get("card_details_layouts", ())),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        _isolate_corrupt_file(target)
        return Settings()


@dataclass(frozen=True, slots=True)
class BattleRecordSummary:
    record_id: str
    recorded_at: str
    program_version: str
    rules_version: str
    mode_id: str
    difficulty: str
    player_hero_id: str | None
    player_identity: str | None
    result: str
    end_reason: str
    turn_count: int

    def __post_init__(self) -> None:
        if self.turn_count < 0:
            raise ValueError("turn_count cannot be negative")


def new_record_summary(
    *, record_id: str, mode_id: str, difficulty: str,
    player_hero_id: str | None, player_identity: str | None,
    result: str, end_reason: str, turn_count: int,
) -> BattleRecordSummary:
    return BattleRecordSummary(
        record_id=record_id,
        recorded_at=datetime.now(UTC).isoformat(),
        program_version=APP_VERSION,
        rules_version=RULES_VERSION,
        mode_id=mode_id,
        difficulty=difficulty,
        player_hero_id=player_hero_id,
        player_identity=player_identity,
        result=result,
        end_reason=end_reason,
        turn_count=turn_count,
    )


def _record_payload(record: BattleRecordSummary) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_id": record.record_id,
        "recorded_at": record.recorded_at,
        "program_version": record.program_version,
        "rules_version": record.rules_version,
        "mode_id": record.mode_id,
        "difficulty": record.difficulty,
        "player_hero_id": record.player_hero_id,
        "player_identity": record.player_identity,
        "result": record.result,
        "end_reason": record.end_reason,
        "turn_count": record.turn_count,
    }


def _record_from_payload(payload: dict[str, Any]) -> BattleRecordSummary:
    if payload.get("schema_version", 1) != 1:
        raise ValueError("unsupported record schema version")
    return BattleRecordSummary(
        record_id=str(payload["record_id"]),
        recorded_at=str(payload["recorded_at"]),
        program_version=str(payload["program_version"]),
        rules_version=str(payload["rules_version"]),
        mode_id=str(payload["mode_id"]),
        difficulty=str(payload["difficulty"]),
        player_hero_id=payload.get("player_hero_id"),
        player_identity=payload.get("player_identity"),
        result=str(payload["result"]),
        end_reason=str(payload["end_reason"]),
        turn_count=int(payload["turn_count"]),
    )


def load_record_summaries(path: Path | None = None) -> tuple[BattleRecordSummary, ...]:
    target = path or records_path()
    if not target.exists():
        return ()
    try:
        records = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("record line must be an object")
                records.append(_record_from_payload(payload))
        return tuple(records)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, ValueError):
        _isolate_corrupt_file(target)
        return ()


def append_record_summary(record: BattleRecordSummary, path: Path | None = None) -> Path:
    target = path or records_path()
    records = load_record_summaries(target)
    records = (*records, record)
    contents = "".join(
        json.dumps(_record_payload(item), ensure_ascii=False, separators=(",", ":")) + "\n"
        for item in records
    )
    _atomic_write_text(target, contents)
    return target


def clear_record_summaries(path: Path | None = None) -> Path:
    """Atomically clear battle summaries without affecting settings."""
    target = path or records_path()
    _atomic_write_text(target, "")
    return target
