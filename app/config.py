from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "stock_pool.yaml"
STAR_STATE_PATH = ROOT_DIR / "config" / "star_state.json"


@dataclass(frozen=True)
class StockConfig:
    code: str
    name: str
    group: str
    groups: tuple[str, ...] = field(default_factory=tuple)
    watch: bool = False
    note: str = ""
    tier: int = 0


class StarStore:
    """User-managed star state, persisted to star_state.json."""

    def __init__(self, path: Path = STAR_STATE_PATH) -> None:
        self._path = path
        self._stars: set[str] = set()
        self._groups: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._stars = set(data.get("stars", []))
                self._groups = set(data.get("groups", []))
                return
            except Exception:
                pass
        # First run: migrate stars from YAML
        self._migrate_from_yaml()
        self._save()

    def _migrate_from_yaml(self) -> None:
        try:
            raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
            for group in raw.get("groups", []):
                for item in group.get("stocks", []):
                    if item.get("star"):
                        self._stars.add(str(item["code"]).zfill(6))
        except Exception:
            pass

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "stars": sorted(self._stars),
                    "groups": sorted(self._groups),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def is_starred(self, code: str) -> bool:
        return code in self._stars

    def toggle(self, code: str) -> bool:
        """Toggle star for a code. Returns new state (True = starred)."""
        if code in self._stars:
            self._stars.discard(code)
        else:
            self._stars.add(code)
        self._save()
        return code in self._stars

    def is_group_starred(self, group: str) -> bool:
        return group in self._groups

    def toggle_group(self, group: str) -> bool:
        """Toggle star for a group. Returns new state (True = starred)."""
        if group in self._groups:
            self._groups.discard(group)
        else:
            self._groups.add(group)
        self._save()
        return group in self._groups

    @property
    def count(self) -> int:
        return len(self._stars)

    @property
    def group_count(self) -> int:
        return len(self._groups)


star_store = StarStore()


def load_stock_pool(path: Path = CONFIG_PATH) -> list[StockConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    stocks_by_code: dict[str, dict[str, Any]] = {}

    for group in raw.get("groups", []):
        group_name = group["name"]
        for item in group.get("stocks", []):
            code = str(item["code"]).zfill(6)
            existing = stocks_by_code.get(code)
            if existing is None:
                stocks_by_code[code] = {
                    "code": code,
                    "name": item["name"],
                    "group": group_name,
                    "groups": [group_name],
                    "watch": bool(item.get("watch")),
                    "note": item.get("note", ""),
                    "tier": int(item.get("tier", 0)),
                }
            else:
                existing["groups"].append(group_name)
                existing["watch"] = existing["watch"] or bool(item.get("watch"))
                if item.get("note"):
                    notes = [n for n in [existing.get("note"), item.get("note")] if n]
                    existing["note"] = " / ".join(dict.fromkeys(notes))
                existing_tier = int(existing.get("tier", 0))
                new_tier = int(item.get("tier", 0))
                if existing_tier and new_tier:
                    existing["tier"] = min(existing_tier, new_tier)
                else:
                    existing["tier"] = max(existing_tier, new_tier)

    return [
        StockConfig(
            code=item["code"],
            name=item["name"],
            group=item["group"],
            groups=tuple(item["groups"]),
            watch=item["watch"],
            note=item["note"],
            tier=item["tier"],
        )
        for item in stocks_by_code.values()
    ]


def eastmoney_market(code: str) -> str:
    return "1" if code.startswith(("5", "6", "9")) else "0"


def eastmoney_secid(code: str) -> str:
    return f"{eastmoney_market(code)}.{code}"
