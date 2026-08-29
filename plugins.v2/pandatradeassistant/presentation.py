"""把站点首页响应整理为稳定、只读的前端展示模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple


Path = Tuple[str, ...]


def _pick(source: Mapping[str, Any], paths: Sequence[Path], default: Any = None) -> Any:
    for path in paths:
        current: Any = source
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                current = None
                break
            current = current[key]
        if current is not None and current != "":
            return current
    return default


def _mapping(source: Mapping[str, Any], paths: Sequence[Path]) -> Mapping[str, Any]:
    value = _pick(source, paths, {})
    return value if isinstance(value, Mapping) else {}


def _pick_sources(
    sources: Sequence[Mapping[str, Any]],
    paths: Sequence[Path],
    default: Any = None,
) -> Any:
    for source in sources:
        value = _pick(source, paths)
        if value is not None and value != "":
            return value
    return default


def _rows(source: Mapping[str, Any], paths: Sequence[Path]) -> List[Mapping[str, Any]]:
    value = _pick(source, paths, [])
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _find_mapping(source: Mapping[str, Any], marker_keys: Sequence[str], depth: int = 4) -> Mapping[str, Any]:
    if any(key in source for key in marker_keys):
        return source
    if depth <= 0:
        return {}
    for value in source.values():
        if isinstance(value, Mapping):
            found = _find_mapping(value, marker_keys, depth - 1)
            if found:
                return found
    return {}


def _find_rows(source: Mapping[str, Any], marker_keys: Sequence[str], depth: int = 4) -> List[Mapping[str, Any]]:
    if depth <= 0:
        return []
    for value in source.values():
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, Mapping)]
            if rows and any(key in rows[0] for key in marker_keys):
                return rows
        elif isinstance(value, Mapping):
            found = _find_rows(value, marker_keys, depth - 1)
            if found:
                return found
    return []


def _income_view(home: Mapping[str, Any]) -> Dict[str, Any]:
    income = _mapping(home, [("income_summary",)])
    sources = _mapping(income, [("earning_sources",)])
    source = lambda key: _mapping(sources, [(key,)])
    return {
        "total": income.get("total_earned"),
        "today": income.get("today_earned"),
        "servant": source("daily_income").get("total"),
        "work": source("work_income").get("total"),
        "work_tip": source("work_tip").get("total"),
        "trade": source("trade_income").get("total"),
        "task": source("task_reward").get("total"),
        "business": source("business_reward").get("total"),
        "available": bool(income),
    }


TRANSACTION_LABELS = {
    "buy": "买下", "bought": "买下", "purchase": "买下", "market_buy": "买下",
    "sell": "卖出", "sold": "卖出", "snatch": "挖角", "redeem": "赎身",
    "initial": "初始归属", "initial_owner": "初始归属", "assign": "初始归属",
}


def _transaction_view(home: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = _rows(home, [("activity_feed",)])
    result = []
    for row in rows[:50]:
        action = str(row.get("trade_type") or "")
        result.append({
            "type": TRANSACTION_LABELS.get(action.lower(), row.get("relation_text") or "交易"),
            "time": row.get("created_at"),
            "amount": row.get("trade_price"),
            "username": row.get("slave_username"),
            "counterparty": row.get("to_owner_username") or row.get("from_owner_username"),
            "detail": row.get("relation_text"),
        })
    return result


def _profile_view(home: Mapping[str, Any], inventory: Mapping[str, Any]) -> Dict[str, Any]:
    me = _mapping(home, [("me",)])
    owner = _mapping(home, [("my_owner",)])
    task = _mapping(owner, [("owner_today_work",)])
    return {
        "username": me.get("username"),
        "magic": inventory.get("magic_balance"),
        "asset_total": home.get("asset_total_value"),
        "worth": home.get("my_profile_price"),
        "owner_name": owner.get("username"),
        "redeem_price": owner.get("redeem_price"),
        "owner_task": task.get("work_label"),
        "owner_task_tip": task.get("tip_amount"),
        "claimable_income": home.get("claimable_income"),
        "available": bool(me),
    }


def _progress_view(home: Mapping[str, Any]) -> Dict[str, Any]:
    business = _mapping(home, [("business_summary",)])
    progression = _mapping(business, [("progression",)])
    commissions = _mapping(business, [("commissions",)])
    screening = _mapping(business, [("screening",)])
    collection = _mapping(business, [("collection",)])
    achievements = business.get("achievements") if isinstance(business.get("achievements"), list) else []
    badge = next((item for item in reversed(achievements) if isinstance(item, Mapping)), {})
    return {
        "level": progression.get("level"),
        "title": progression.get("title"),
        "exp": progression.get("current_level_exp"),
        "next_exp": progression.get("next_level_exp"),
        "total_exp": progression.get("total_exp"),
        "office_unlock_level": commissions.get("unlock_level"),
        "screening_unlock_level": screening.get("unlock_level"),
        "poster_count": collection.get("owned_count"),
        "poster_target": collection.get("catalog_size"),
        "badge_name": badge.get("label"),
        "badge_status": badge.get("status_label"),
        "available": bool(progression),
    }


def _asset_view(asset: Mapping[str, Any]) -> Dict[str, Any]:
    trait = _mapping(asset, [("trait_summary",), ("trait",)])
    cultivation = _mapping(asset, [("cultivation_summary",), ("cultivation",), ("relationship_summary",)])
    protection = _mapping(asset, [("protection_summary",), ("sponsorship_summary",)])
    attributes = _mapping(trait, [("attributes",), ("stats",)])
    return {
        "username": _pick(asset, [("username",), ("name",), ("slave_username",)]),
        "rarity": _pick(trait, [("rarity",), ("rarity_key",)]) or _pick(asset, [("rarity",)]),
        "talent": trait.get("talent_label"),
        "current_price": _pick(asset, [("current_price",), ("price",), ("worth",)]),
        "buy_price": asset.get("acquire_price"),
        "daily_income": _pick(asset, [("daily_income",), ("servant_income",), ("daily_output",)]),
        "intimacy": _pick(cultivation, [("intimacy",), ("affection",), ("closeness",)]),
        "intimacy_max": cultivation.get("intimacy_cap"),
        "mood": _pick(cultivation, [("mood",), ("mood_value",)]),
        "mood_name": _pick(cultivation, [("mood_name",), ("mood_label",), ("mood_status",)]),
        "sponsorship": _pick(protection, [("status_name",), ("name",), ("status",)]) or _pick(cultivation, [("sponsorship",), ("patronage",)], "无包养"),
        "relationship_stage": cultivation.get("relationship_stage_label") or cultivation.get("relationship_stage"),
        "stage_exp": cultivation.get("relationship_exp"),
        "stage_required_exp": cultivation.get("next_stage_exp"),
        "stage_remaining_exp": cultivation.get("stage_remaining_exp"),
        "can_work_today": _pick(cultivation, [("can_work_today",), ("can_work",)]),
        "can_interact_today": _pick(cultivation, [("can_interact_today",), ("can_interact",)]),
        "attributes": {key: _pick(attributes, [(key,)]) for key in ("virtue", "wisdom", "physique", "charm", "diligence")},
    }


def build_home_view(home: Mapping[str, Any], inventory: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """从已脱敏的首页数据构建稳定展示字段，不发起额外请求。"""
    capacity = _mapping(home, [("capacity_summary",), ("asset_capacity",), ("capacity",)])
    assets = _rows(home, [("my_assets",), ("assets",), ("servants",), ("slaves",)])
    profile = _profile_view(home, inventory or {})
    profile["servant_count"] = len(assets)
    return {
        "income": _income_view(home),
        "transactions": _transaction_view(home),
        "profile": profile,
        "progress": _progress_view(home),
        "capacity": {
            "used": len(assets),
            "total": _pick(capacity, [("formal_capacity",), ("total",), ("capacity",)], len(assets)),
        },
        "assets": [_asset_view(asset) for asset in assets],
    }
