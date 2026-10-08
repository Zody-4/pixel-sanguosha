"""Runtime registry for approved hero portraits and layered card artwork."""

from __future__ import annotations

from dataclasses import dataclass

from xssgkpz.data.cards import CARD_KINDS
from xssgkpz.data.heroes import HEROES


@dataclass(frozen=True, slots=True)
class AssetKeyDefinition:
    asset_key: str
    relative_path: str | None
    status: str


_CARD_ASSETS = (
    AssetKeyDefinition(kind.asset_key, relative_path=f"assets/runtime/cards/v06/layers/底图/{kind.kind_id}.png", status="integrated")
    for kind in CARD_KINDS
)
_HERO_ASSETS = (
    AssetKeyDefinition(
        hero.asset_key,
        relative_path=(
            f"assets/references/武将牌/{hero.faction.value}-半身/{hero.name}半身.png"
        ),
        status="integrated",
    )
    for hero in HEROES
)
_BATTLE_ASSETS = tuple(AssetKeyDefinition(f"battle.v12.{name}", ("assets/references/卡背-设计参考.png" if name == "back" else f"assets/runtime/battle/v12/{name}.png"), "integrated")
                      for name in ("skin", "skin-seat-clean-20261002", "skin-header-clean-20261002",
                                   "back", "health-green", "health-red", "health-gray"))
_SHELL_ASSETS = (AssetKeyDefinition("shell.command_tent", "assets/runtime/shell/battle-tent-menu-v02.png", "integrated"),)
_APPROVED_SHELL_ASSETS = (
    AssetKeyDefinition("shell.secondary_pavilion", "assets/runtime/shell/command-pavilion-secondary-v01.png", "integrated_pending_review"),
    AssetKeyDefinition("shell.approved_menu", "assets/runtime/shell/menu-approved.png", "integrated"),
    AssetKeyDefinition("card.back", "assets/references/卡背-设计参考.png", "integrated"),
    *(AssetKeyDefinition(f"identity.{role}", f"assets/references/身份卡/{name}.png", "integrated")
      for role, name in (("lord", "主公"), ("loyalist", "忠诚"), ("rebel", "反贼"), ("turncoat", "内奸"))),
)
ASSET_KEYS = tuple(sorted((*_CARD_ASSETS, *_HERO_ASSETS, *_BATTLE_ASSETS, *_SHELL_ASSETS, *_APPROVED_SHELL_ASSETS), key=lambda asset: asset.asset_key))
ASSET_BY_KEY = {asset.asset_key: asset for asset in ASSET_KEYS}
