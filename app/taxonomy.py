from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import ROOT_DIR


TAXONOMY_PATH = ROOT_DIR / "config" / "industry_taxonomy.yaml"


@dataclass(frozen=True)
class IndustryNode:
    id: str
    name: str
    parent_id: str | None
    level: int
    aliases: tuple[str, ...] = ()

    @property
    def scope_id(self) -> str:
        return f"industry:{self.id}"


@dataclass(frozen=True)
class TagNode:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    legacy_groups: tuple[str, ...] = ()

    @property
    def scope_id(self) -> str:
        return f"tag:{self.id}"


class Taxonomy:
    def __init__(self, path: Path = TAXONOMY_PATH) -> None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.version = int(raw.get("version", 1))
        self.nodes: dict[str, IndustryNode] = {}
        self.children: dict[str | None, list[str]] = defaultdict(list)
        self.alias_to_leaf: dict[str, str] = {}
        self.tags: dict[str, TagNode] = {}
        self.group_tags: dict[str, tuple[str, ...]] = {}

        for item in raw.get("industries", []):
            self._load_industry(item, parent_id=None, level=1)
        self._validate_industries()

        tag_aliases: set[str] = set()
        group_tags: dict[str, list[str]] = defaultdict(list)
        for item in raw.get("tags", []):
            tag = TagNode(
                id=str(item["id"]),
                name=str(item["name"]),
                aliases=tuple(str(value) for value in item.get("aliases", [])),
                legacy_groups=tuple(str(value) for value in item.get("legacy_groups", [])),
            )
            if tag.id in self.tags:
                raise ValueError(f"重复标签ID: {tag.id}")
            for alias in (tag.name, *tag.aliases):
                if alias in tag_aliases:
                    raise ValueError(f"重复标签别名: {alias}")
                tag_aliases.add(alias)
            self.tags[tag.id] = tag
            for group in tag.legacy_groups:
                group_tags[group].append(tag.id)
        self.group_tags = {
            group: tuple(dict.fromkeys(tag_ids))
            for group, tag_ids in group_tags.items()
        }

    def _load_industry(
        self,
        item: dict[str, Any],
        parent_id: str | None,
        level: int,
    ) -> None:
        node = IndustryNode(
            id=str(item["id"]),
            name=str(item["name"]),
            parent_id=parent_id,
            level=level,
            aliases=tuple(str(value) for value in item.get("aliases", [])),
        )
        if node.id in self.nodes:
            raise ValueError(f"重复行业ID: {node.id}")
        self.nodes[node.id] = node
        self.children[parent_id].append(node.id)

        child_items = item.get("children", [])
        if child_items:
            for child in child_items:
                self._load_industry(child, parent_id=node.id, level=level + 1)
        else:
            for alias in node.aliases:
                if alias in self.alias_to_leaf:
                    raise ValueError(f"重复行业别名: {alias}")
                self.alias_to_leaf[alias] = node.id

    def _validate_industries(self) -> None:
        for node in self.nodes.values():
            if node.level not in (1, 2, 3):
                raise ValueError(f"行业层级必须为1至3级: {node.id}")
            if node.level < 3 and not self.children.get(node.id):
                raise ValueError(f"非三级行业必须包含子节点: {node.id}")
            if node.level == 3 and self.children.get(node.id):
                raise ValueError(f"三级行业不能包含子节点: {node.id}")

    def resolve_group(self, group: str) -> str | None:
        return self.alias_to_leaf.get(group)

    def legacy_groups_for_scope(self, scope_id: str) -> tuple[str, ...]:
        if scope_id.startswith("industry:"):
            node_id = scope_id.removeprefix("industry:")
            return tuple(
                group for group, leaf_id in self.alias_to_leaf.items() if leaf_id == node_id
            )
        if scope_id.startswith("tag:"):
            tag_id = scope_id.removeprefix("tag:")
            tag = self.tags.get(tag_id)
            return tag.legacy_groups if tag else ()
        return ()

    def ancestors(self, node_id: str, include_self: bool = True) -> tuple[str, ...]:
        values: list[str] = []
        current_id: str | None = node_id if include_self else self.nodes[node_id].parent_id
        while current_id is not None:
            values.append(current_id)
            current_id = self.nodes[current_id].parent_id
        return tuple(reversed(values))

    def path_names(self, node_id: str) -> tuple[str, ...]:
        return tuple(self.nodes[current].name for current in self.ancestors(node_id))

    def stock_projection(self, primary_group: str, groups: Iterable[str]) -> dict[str, Any]:
        group_list = list(dict.fromkeys(groups))
        leaf_ids = [
            leaf_id
            for group in group_list
            if (leaf_id := self.resolve_group(group)) is not None
        ]
        leaf_ids = list(dict.fromkeys(leaf_ids))
        primary_id = self.resolve_group(primary_group)
        if primary_id not in leaf_ids:
            primary_id = leaf_ids[0] if leaf_ids else None

        scope_ids: list[str] = []
        for leaf_id in leaf_ids:
            scope_ids.extend(
                self.nodes[node_id].scope_id for node_id in self.ancestors(leaf_id)
            )
        tag_ids = list(
            dict.fromkeys(
                tag_id
                for group in group_list
                for tag_id in self.group_tags.get(group, ())
            )
        )
        return {
            "primary_industry_id": primary_id,
            "industry_memberships": [
                {
                    "industry_id": leaf_id,
                    "primary": leaf_id == primary_id,
                }
                for leaf_id in leaf_ids
            ],
            "industry_scope_ids": list(dict.fromkeys(scope_ids)),
            "tags": tag_ids,
            "tag_scope_ids": [self.tags[tag_id].scope_id for tag_id in tag_ids],
        }

    def tree_payload(self) -> list[dict[str, Any]]:
        return [self._node_payload(node_id) for node_id in self.children.get(None, [])]

    def _node_payload(self, node_id: str) -> dict[str, Any]:
        node = self.nodes[node_id]
        return {
            "id": node.id,
            "scope_id": node.scope_id,
            "name": node.name,
            "level": node.level,
            "parent_id": node.parent_id,
            "children": [
                self._node_payload(child_id)
                for child_id in self.children.get(node_id, [])
            ],
        }

    def payload(self, is_scope_starred: Any | None = None) -> dict[str, Any]:
        industries = self.tree_payload()
        tags = [
            {
                "id": tag.id,
                "scope_id": tag.scope_id,
                "name": tag.name,
                "star": bool(is_scope_starred and is_scope_starred(tag.scope_id)),
            }
            for tag in self.tags.values()
        ]
        scope_names = {
            node.scope_id: node.name for node in self.nodes.values()
        }
        scope_names.update({tag.scope_id: tag.name for tag in self.tags.values()})

        def add_stars(items: list[dict[str, Any]]) -> None:
            for item in items:
                item["star"] = bool(
                    is_scope_starred and is_scope_starred(item["scope_id"])
                )
                add_stars(item["children"])

        add_stars(industries)
        return {
            "version": self.version,
            "industries": industries,
            "tags": tags,
            "legacy_group_scopes": {
                group: [
                    self.nodes[node_id].scope_id
                    for node_id in self.ancestors(leaf_id)
                ]
                for group, leaf_id in self.alias_to_leaf.items()
            },
            "legacy_group_tags": {
                group: [self.tags[tag_id].scope_id for tag_id in tag_ids]
                for group, tag_ids in self.group_tags.items()
            },
            "scope_names": scope_names,
        }


def build_scope_stats(
    stocks: Iterable[dict[str, Any]],
    taxonomy: Taxonomy,
    is_scope_starred: Any | None = None,
) -> dict[str, dict[str, Any]]:
    scope_stocks: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for stock in stocks:
        projection = taxonomy.stock_projection(
            str(stock.get("group", "")),
            stock.get("groups") or [stock.get("group", "")],
        )
        scope_ids = [
            *projection["industry_scope_ids"],
            *projection["tag_scope_ids"],
        ]
        for scope_id in scope_ids:
            scope_stocks[scope_id][str(stock.get("code", ""))] = stock

    result: dict[str, dict[str, Any]] = {}
    for scope_id, members_by_code in scope_stocks.items():
        members = list(members_by_code.values())
        signals = Counter(
            (stock.get("signal") or {}).get("signal", "") for stock in members
        )
        pcts = [
            pct
            for stock in members
            if (pct := (stock.get("quote") or {}).get("pct_chg")) is not None
        ]
        up = sum(1 for pct in pcts if pct > 0)
        down = sum(1 for pct in pcts if pct < 0)
        flat = len(members) - up - down
        result[scope_id] = {
            "total": len(members),
            "up": up,
            "down": down,
            "flat": flat,
            "signals": dict(signals),
            "avg_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "star": bool(is_scope_starred and is_scope_starred(scope_id)),
        }
    return result


taxonomy = Taxonomy()
