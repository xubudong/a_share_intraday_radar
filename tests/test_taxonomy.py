from __future__ import annotations

from app.config import StarStore
from app.taxonomy import Taxonomy, build_scope_stats


def test_taxonomy_maps_all_legacy_leaf_groups():
    taxonomy = Taxonomy()

    assert len(taxonomy.alias_to_leaf) == 123
    assert len(taxonomy.children[None]) == 21
    assert taxonomy.resolve_group("半导体材料-电子特气") == (
        "semiconductor.materials.electronic_gases"
    )
    assert taxonomy.path_names("semiconductor.materials.electronic_gases") == (
        "半导体",
        "半导体材料",
        "电子特气",
    )
    assert taxonomy.resolve_group("先进封装-封测厂") == (
        "semiconductor.packaging.osat"
    )


def test_stock_projection_includes_ancestors_and_theme_tags():
    taxonomy = Taxonomy()
    projection = taxonomy.stock_projection(
        "先进封装-封测厂",
        ["先进封装-封测厂"],
    )

    assert projection["primary_industry_id"] == "semiconductor.packaging.osat"
    assert projection["industry_scope_ids"] == [
        "industry:semiconductor",
        "industry:semiconductor.packaging",
        "industry:semiconductor.packaging.osat",
    ]
    assert projection["tags"] == ["advanced_packaging"]
    assert projection["tag_scope_ids"] == ["tag:advanced_packaging"]


def test_scope_stats_deduplicate_stock_inside_parent_nodes():
    taxonomy = Taxonomy()
    stocks = [
        {
            "code": "300655",
            "group": "半导体材料-光刻胶",
            "groups": ["半导体材料-光刻胶", "半导体材料-湿电子"],
            "quote": {"pct_chg": 4.0},
            "signal": {"signal": "观察"},
        },
        {
            "code": "688268",
            "group": "半导体材料-电子特气",
            "groups": ["半导体材料-电子特气"],
            "quote": {"pct_chg": -2.0},
            "signal": {"signal": "观察"},
        },
    ]

    stats = build_scope_stats(stocks, taxonomy)

    assert stats["industry:semiconductor"]["total"] == 2
    assert stats["industry:semiconductor.materials"]["total"] == 2
    assert stats["industry:semiconductor.materials"]["avg_pct"] == 1.0
    assert stats["industry:semiconductor.materials"]["up"] == 1
    assert stats["industry:semiconductor.materials"]["down"] == 1
    assert stats["industry:semiconductor.materials.photoresist"]["total"] == 1
    assert stats["industry:semiconductor.materials.wet_chemicals"]["total"] == 1


def test_taxonomy_payload_supports_legacy_snapshot_projection():
    taxonomy = Taxonomy()
    payload = taxonomy.payload()

    assert payload["legacy_group_scopes"]["半导体材料-电子特气"] == [
        "industry:semiconductor",
        "industry:semiconductor.materials",
        "industry:semiconductor.materials.electronic_gases",
    ]
    assert payload["legacy_group_tags"]["先进封装-封测厂"] == [
        "tag:advanced_packaging"
    ]


def test_star_store_persists_scope_stars_without_dropping_legacy_groups(tmp_path):
    path = tmp_path / "star_state.json"
    path.write_text(
        '{"stars": [], "groups": ["半导体材料-电子特气"], "holdings": []}',
        encoding="utf-8",
    )
    store = StarStore(path)

    assert store.is_group_starred("半导体材料-电子特气")
    assert store.toggle_scope("industry:semiconductor.materials") is True

    reloaded = StarStore(path)
    assert reloaded.is_group_starred("半导体材料-电子特气")
    assert reloaded.is_scope_starred("industry:semiconductor.materials")
    assert reloaded.scope_count == 1


def test_frontend_contains_three_level_scope_filters():
    app_js = (
        __import__("pathlib").Path(__file__).parents[1] / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "taxonomy.industries" in app_js
    assert "taxonomyRoot: root.id" in app_js
    assert "function computeScopeStatsFromStocks" in app_js
    assert "taxonomy-branch-btn" in app_js
    assert "taxonomy-leaf-btn" in app_js
    assert 'state.group.startsWith("industry:")' in app_js
    assert 'state.group.startsWith("tag:")' in app_js
    assert 'fetch("/api/toggle-scope-star"' in app_js
