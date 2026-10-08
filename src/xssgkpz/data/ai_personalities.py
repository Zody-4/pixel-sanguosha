"""Private, deterministic AI personality tendencies for the 25 standard heroes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Personality(StrEnum):
    AGGRESSION = "aggression"
    CAUTION = "caution"
    CONTROL = "control"
    SUPPORT = "support"
    STOCKPILING = "stockpiling"


@dataclass(frozen=True, slots=True)
class PersonalityDefinition:
    primary: Personality
    secondary: Personality


# The 70/30 choice is made once for each hero and match seed by the AI policy.
PERSONALITIES_BY_HERO: dict[str, PersonalityDefinition] = {
    "caocao": PersonalityDefinition(Personality.CONTROL, Personality.CAUTION),
    "simayi": PersonalityDefinition(Personality.CAUTION, Personality.CONTROL),
    "xiahoudun": PersonalityDefinition(Personality.AGGRESSION, Personality.CONTROL),
    "zhangliao": PersonalityDefinition(Personality.CONTROL, Personality.AGGRESSION),
    "xuchu": PersonalityDefinition(Personality.AGGRESSION, Personality.CAUTION),
    "guojia": PersonalityDefinition(Personality.SUPPORT, Personality.STOCKPILING),
    "zhenji": PersonalityDefinition(Personality.CAUTION, Personality.STOCKPILING),
    "liubei": PersonalityDefinition(Personality.SUPPORT, Personality.CAUTION),
    "guanyu": PersonalityDefinition(Personality.AGGRESSION, Personality.SUPPORT),
    "zhangfei": PersonalityDefinition(Personality.AGGRESSION, Personality.CONTROL),
    "zhugeliang": PersonalityDefinition(Personality.STOCKPILING, Personality.CONTROL),
    "zhaoyun": PersonalityDefinition(Personality.SUPPORT, Personality.CAUTION),
    "machao": PersonalityDefinition(Personality.AGGRESSION, Personality.CONTROL),
    "huangyueying": PersonalityDefinition(Personality.STOCKPILING, Personality.CONTROL),
    "sunquan": PersonalityDefinition(Personality.CONTROL, Personality.CAUTION),
    "ganning": PersonalityDefinition(Personality.CONTROL, Personality.AGGRESSION),
    "lvmeng": PersonalityDefinition(Personality.STOCKPILING, Personality.CAUTION),
    "huanggai": PersonalityDefinition(Personality.AGGRESSION, Personality.SUPPORT),
    "zhouyu": PersonalityDefinition(Personality.CONTROL, Personality.AGGRESSION),
    "daqiao": PersonalityDefinition(Personality.CONTROL, Personality.SUPPORT),
    "luxun": PersonalityDefinition(Personality.CAUTION, Personality.STOCKPILING),
    "sunshangxiang": PersonalityDefinition(Personality.SUPPORT, Personality.AGGRESSION),
    "huatuo": PersonalityDefinition(Personality.SUPPORT, Personality.CAUTION),
    "lvbu": PersonalityDefinition(Personality.AGGRESSION, Personality.CONTROL),
    "diaochan": PersonalityDefinition(Personality.CONTROL, Personality.CAUTION),
}
