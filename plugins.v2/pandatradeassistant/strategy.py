"""好友买卖的纯策略函数。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


ATTRIBUTE_KEYS = ("virtue", "wisdom", "physique", "charm", "diligence")
RARITY_SCORES = {
    "normal": 25.0,
    "excellent": 50.0,
    "rare": 72.0,
    "precious": 88.0,
    "legendary": 100.0,
}
TALENT_FOCUS = {
    "comforting": ("charm", "diligence"),
    "hardworking": ("diligence", "physique"),
    "loyal": ("virtue", "physique"),
    "energetic": ("physique", "charm"),
    "thrifty": ("wisdom", "diligence"),
    "nostalgic": ("virtue", "wisdom"),
}


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """把数值限制到指定范围。"""
    return max(minimum, min(maximum, float(value)))


def nested(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """安全读取嵌套字典。"""
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return default if current is None else current


@dataclass(frozen=True)
class ScoredCandidate:
    """市场候选人的评分结果。"""

    uid: int
    username: str
    score: float
    price: float
    owned: bool
    breakdown: Dict[str, float]
    candidate: Dict[str, Any]


def score_market_candidate(
    candidate: Mapping[str, Any],
    median_price: float,
    weights: Optional[Mapping[str, float]] = None,
) -> ScoredCandidate:
    """按照稀有度、五维、天赋、价格和交易风险计算市场评分。"""
    weights = dict(weights or {
        "rarity": 0.20,
        "attributes": 0.35,
        "talent": 0.15,
        "price": 0.20,
        "stability": 0.10,
    })
    trait = candidate.get("trait_summary") or {}
    attributes = trait.get("attributes") or {}
    values = [clamp(float(attributes.get(key) or 0)) for key in ATTRIBUTE_KEYS]
    values.sort(reverse=True)
    attribute_score = sum(values[:3]) / max(1, min(3, len(values)))
    rarity_score = RARITY_SCORES.get(str(trait.get("rarity") or "normal"), 20.0)

    talent_key = str(trait.get("talent_key") or "")
    focus = TALENT_FOCUS.get(talent_key, ())
    talent_score = (
        sum(clamp(float(attributes.get(key) or 0)) for key in focus) / len(focus)
        if focus else attribute_score * 0.8
    )

    price = float(candidate.get("current_price") or candidate.get("price") or 0)
    reference = max(float(median_price or price or 1), 1.0)
    price_score = clamp(100.0 - max(0.0, price / reference - 0.5) * 70.0)
    today_trades = int(candidate.get("today_trade_count") or candidate.get("today_trades") or 0)
    protected = bool(nested(candidate, "protection_summary", "is_protected", default=False))
    stability_score = clamp(100.0 - today_trades * 18.0 - (35.0 if protected else 0.0))

    breakdown = {
        "rarity": round(rarity_score, 2),
        "attributes": round(attribute_score, 2),
        "talent": round(talent_score, 2),
        "price": round(price_score, 2),
        "stability": round(stability_score, 2),
    }
    total_weight = sum(max(float(value), 0.0) for value in weights.values()) or 1.0
    score = sum(breakdown[key] * max(float(weights.get(key, 0.0)), 0.0) for key in breakdown)
    score = round(clamp(score / total_weight), 2)
    return ScoredCandidate(
        uid=int(candidate.get("uid") or 0),
        username=str(candidate.get("username") or ""),
        score=score,
        price=price,
        owned=bool(candidate.get("owner_uid")),
        breakdown=breakdown,
        candidate=dict(candidate),
    )


def rank_market_candidates(
    candidates: Iterable[Mapping[str, Any]],
    weights: Optional[Mapping[str, float]] = None,
) -> List[ScoredCandidate]:
    """按综合评分、价格和 UID 稳定排序市场候选人。"""
    rows = [dict(candidate) for candidate in candidates]
    prices = sorted(float(row.get("current_price") or row.get("price") or 0) for row in rows)
    positive = [price for price in prices if price > 0]
    median = positive[len(positive) // 2] if positive else 1.0
    scored = [score_market_candidate(row, median, weights) for row in rows]
    return sorted(scored, key=lambda item: (-item.score, item.price, item.uid))


def market_candidate_decision(
    candidate: ScoredCandidate,
    config: Mapping[str, Any],
    available_bonus: float = 0.0,
) -> Dict[str, str]:
    """生成市场列表中的中文策略判断，顺序与真实执行门禁一致。"""
    minimum_score = float(config.get("min_market_score") or 70)
    if candidate.score < minimum_score:
        return {"status": "blocked", "label": f"评分不足（需 >= {minimum_score:g}）"}

    price = candidate.price * (1.2 if candidate.owned else 1.0)
    single_cap = float(config.get("single_trade_cap") or 0)
    daily_budget = float(config.get("daily_trade_budget") or 0)
    if single_cap <= 0 or daily_budget <= 0:
        return {"status": "blocked", "label": "交易预算未启用"}
    if price > single_cap:
        return {"status": "blocked", "label": f"超过每次上限（{price:g} > {single_cap:g}）"}
    if price > daily_budget:
        return {"status": "blocked", "label": f"超过每天预算（{price:g} > {daily_budget:g}）"}

    reserve = float(config.get("reserve_bonus") or 0)
    if available_bonus > 0 and available_bonus - price < reserve:
        return {"status": "blocked", "label": f"交易后低于保留魔力 {reserve:g}"}
    if candidate.owned and not config.get("allow_snatch", False):
        return {"status": "blocked", "label": "挖角未启用"}
    return {"status": "ready", "label": "可挖角" if candidate.owned else "可购买"}


def choose_work(asset: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """为佣人选择兼顾成长、收益和心情的工作。"""
    cultivation = asset.get("cultivation_summary") or {}
    if not cultivation.get("can_work_today", False):
        return None
    options = cultivation.get("available_works") or cultivation.get("work_options") or {}
    if not isinstance(options, Mapping) or not options:
        return None
    mood = float(cultivation.get("mood") or 0)
    if mood < 35 and "rest" in options:
        option = options.get("rest") or {}
        return {"key": "rest", "name": option.get("name") or option.get("title") or "休息", "score": 100.0, "reason": "心情低于安全线"}

    attributes = nested(asset, "trait_summary", "attributes", default={}) or {}
    best: Optional[Dict[str, Any]] = None
    for key, option in options.items():
        if not isinstance(option, Mapping) or option.get("is_unlocked") is False:
            continue
        focus = option.get("attributes") or []
        fit = sum(float(attributes.get(name) or 0) for name in focus) / len(focus) if focus else 55.0
        description = str(option.get("description") or "")
        magic = 75.0 if "最高魔力" in description else 65.0 if "较高魔力" in description else 52.0 if "魔力" in description else 25.0
        growth = 75.0 if "较多关系经验" in description or "大幅" in description else 60.0 if "关系经验" in description else 40.0
        mood_score = 85.0 if "恢复心情" in description else clamp(mood)
        if "消耗较多心情" in description:
            mood_score = max(0.0, mood - 45.0)
        score = fit * 0.35 + magic * 0.25 + growth * 0.25 + mood_score * 0.15
        row = {"key": str(key), "name": option.get("name") or option.get("title") or option.get("label"), "score": round(score, 2), "reason": f"能力适配 {fit:.0f}，均衡收益 {score:.1f}"}
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def choose_interaction(asset: Mapping[str, Any], paid_budget: float = 0.0) -> Optional[Dict[str, Any]]:
    """根据心情和成长目标选择互动，默认只使用免费互动。"""
    cultivation = asset.get("cultivation_summary") or {}
    if not cultivation.get("can_interact_today", False):
        return None
    mood = float(cultivation.get("mood") or 0)
    remaining = float(cultivation.get("stage_remaining_exp") or 0)
    if mood < 45:
        return {"key": "praise", "cost": 0.0, "reason": "优先恢复心情"}
    if paid_budget >= 300 and remaining <= 30:
        return {"key": "small_reward", "cost": 300.0, "reason": "接近关系阶段升级"}
    if remaining > 0:
        return {"key": "whisper", "cost": 0.0, "reason": "优先关系经验"}
    return {"key": "pat", "cost": 0.0, "reason": "免费维持亲密度"}


def team_fit_score(asset: Mapping[str, Any], focus_targets: Mapping[str, Any]) -> float:
    """计算单个佣人与委托能力目标的匹配度。"""
    attributes = nested(asset, "trait_summary", "attributes", default={}) or {}
    if not focus_targets:
        return sum(float(attributes.get(key) or 0) for key in ATTRIBUTE_KEYS) / len(ATTRIBUTE_KEYS)
    ratios = []
    for key, target in focus_targets.items():
        target_value = max(float(target or 1), 1.0)
        ratios.append(clamp(float(attributes.get(key) or 0) / target_value * 100.0))
    mood = float(nested(asset, "cultivation_summary", "mood", default=50) or 50)
    return sum(ratios) / len(ratios) * 0.85 + clamp(mood) * 0.15


def select_commission_team(
    offer: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
    team_size_limit: int,
) -> List[int]:
    """选择未派遣且最匹配委托目标的正式佣人关系 ID。"""
    recommended = int(offer.get("recommended_team_size") or 1)
    size = max(1, min(recommended, int(team_size_limit or recommended)))
    available = [
        asset for asset in assets
        if not asset.get("is_temporary")
        and not nested(asset, "cultivation_summary", "is_on_commission", default=False)
        and not asset.get("commission_assignment")
    ]
    ranked = sorted(
        available,
        key=lambda asset: team_fit_score(asset, offer.get("focus_targets") or {}),
        reverse=True,
    )
    result = []
    for asset in ranked[:size]:
        relation_id = nested(asset, "cultivation_summary", "relationship_id")
        if relation_id is not None:
            result.append(int(relation_id))
    return result if len(result) == size else []


def is_target_on_cooldown(last_action_at: Optional[str], cooldown_days: int, today: Optional[date] = None) -> bool:
    """判断目标是否仍处于交易冷却期。"""
    if not last_action_at:
        return False
    try:
        action_date = datetime.fromisoformat(last_action_at).date()
    except (TypeError, ValueError):
        return True
    return ((today or date.today()) - action_date).days < max(int(cooldown_days), 0)
