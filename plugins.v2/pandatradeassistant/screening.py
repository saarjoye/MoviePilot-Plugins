"""每日放映挑战的确定性求解与提交载荷构建。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ENUMS = {
    "tone": ("coral", "amber", "teal", "blue", "plum", "mint"),
    "motif": ("orbit", "beam", "tower", "waves", "prism", "steps"),
    "layout": ("center", "split", "diagonal"),
    "rotation": (0, 90, 180, 270),
}
CARD_FIELDS = ("tone", "motif", "layout", "rotation", "title", "code")


def _site_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def submission_wait_seconds(
    challenge: Mapping[str, Any],
    submission: Mapping[str, str],
    safety_ms: int = 150,
) -> float:
    """按服务端时钟计算提交事件尚需等待的时间。"""
    started_at = _site_datetime(challenge.get("started_at"))
    server_now = _site_datetime(challenge.get("server_now"))
    if started_at is None or server_now is None:
        raise ValueError("放映挑战缺少服务端计时字段")
    if (started_at.tzinfo is None) != (server_now.tzinfo is None):
        raise ValueError("放映挑战时间时区不一致")
    try:
        events = json.loads(str(submission.get("events_json") or "[]"))
    except (TypeError, ValueError) as error:
        raise ValueError("放映提交事件结构无效") from error
    if not isinstance(events, list):
        raise ValueError("放映提交事件结构无效")
    event_times = []
    for event in events:
        if not isinstance(event, Mapping):
            raise ValueError("放映提交事件结构无效")
        elapsed = event.get("elapsed_ms")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
            raise ValueError("放映提交事件缺少有效时间")
        event_times.append(float(elapsed))
    required_ms = max(event_times, default=0.0)
    elapsed_ms = max(0.0, (server_now - started_at).total_seconds() * 1000.0)
    remaining_ms = max(0.0, required_ms - elapsed_ms)
    wait_ms = remaining_ms + max(0, int(safety_ms)) if remaining_ms > 0 else 0.0
    expires_at = _site_datetime(challenge.get("expires_at"))
    if expires_at is not None:
        if (expires_at.tzinfo is None) != (server_now.tzinfo is None):
            raise ValueError("放映挑战时间时区不一致")
        if server_now.timestamp() + wait_ms / 1000.0 >= expires_at.timestamp():
            raise ValueError("放映挑战将在可提交前过期")
    return wait_ms / 1000.0


def calibration_position(prompt: Mapping[str, Any], elapsed_ms: int) -> int:
    """复现页面中胶片指针在指定时间的位置。"""
    cycle = int(prompt.get("cycle_ms") or 0)
    if cycle < 2 or cycle % 2:
        raise ValueError("cycle_ms 必须是大于等于 2 的偶数")
    phase = (max(0, int(elapsed_ms)) % cycle) / cycle
    progress = phase * 2 if phase <= 0.5 else (1 - phase) * 2
    center = int(prompt.get("target_center_bp") or 0)
    half_width = round(int(prompt.get("target_width_bp") or 0) / 2)
    start = max(0, min(10000, center - half_width))
    end = max(0, min(10000, center + half_width))
    multiplier = 1.11
    weighted_target = (end - start) / multiplier
    weighted_length = start + weighted_target + (10000 - end)
    distance = progress * weighted_length
    if distance <= start:
        position = distance
    elif distance <= start + weighted_target:
        position = start + (distance - start) * multiplier
    else:
        position = end + (distance - start - weighted_target)
    return round(max(0.0, min(10000.0, position)))


def solve_calibration(prompt: Mapping[str, Any]) -> int:
    """搜索最接近目标中心的胶片停止时间。"""
    cycle = int(prompt.get("cycle_ms") or 0)
    center = int(prompt.get("target_center_bp") or 0)
    if cycle <= 0:
        raise ValueError("无效的 cycle_ms")
    step = max(1, cycle // 5000)
    candidates = range(0, cycle + 1, step)
    best = min(candidates, key=lambda elapsed: abs(calibration_position(prompt, elapsed) - center))
    return int(best)


def card_identity(card: Mapping[str, Any]) -> Tuple[Any, ...]:
    """构造视觉卡片的稳定身份。"""
    return tuple(card.get(field) for field in CARD_FIELDS)


def solve_memory(prompt: Mapping[str, Any]) -> List[str]:
    """把预览卡片与候选卡片精确匹配。"""
    preview = list(prompt.get("preview") or [])
    options = list(prompt.get("options") or [])
    index = {card_identity(option.get("card") or {}): str(option.get("option_key") or "") for option in options}
    keys = [index.get(card_identity(card), "") for card in preview]
    if not keys or any(not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("海报闪记候选无法唯一匹配")
    required = int(prompt.get("required_selection_count") or len(preview))
    if len(keys) != required:
        raise ValueError("海报闪记选择数量不匹配")
    return keys


def _constant_modular_step(values: Sequence[Any], enum_values: Sequence[Any]) -> bool:
    indexes = [enum_values.index(value) for value in values]
    modulo = len(enum_values)
    steps = [(indexes[index + 1] - indexes[index]) % modulo for index in range(len(indexes) - 1)]
    return bool(steps) and len(set(steps)) == 1


def solve_missing_frame(prompt: Mapping[str, Any]) -> Optional[str]:
    """按色调、图形、布局和旋转的循环步长推断缺失画格。"""
    sequence = list(prompt.get("sequence") or [])
    missing_index = int(prompt.get("missing_index") or -1)
    options = list(prompt.get("options") or [])
    if len(sequence) != 5 or missing_index not in (1, 2, 3) or len(options) != 3:
        raise ValueError("缺帧挑战结构无效")
    scored: List[Tuple[int, str]] = []
    for option in options:
        candidate = option.get("card") or {}
        cards = [dict(frame.get("card") or {}) for frame in sequence]
        cards[missing_index] = dict(candidate)
        score = 0
        for field, enum_values in ENUMS.items():
            values = [card.get(field) for card in cards]
            if all(value in enum_values for value in values) and _constant_modular_step(values, enum_values):
                score += 1
        scored.append((score, str(option.get("option_key") or "")))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 2 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1] or None


def build_submission(challenge: Mapping[str, Any]) -> Dict[str, str]:
    """为三种放映挑战构建站点要求的提交参数。"""
    game_key = str(challenge.get("game_key") or "")
    prompt = challenge.get("prompt") or {}
    token = str(challenge.get("challenge_token") or "")
    if not token:
        raise ValueError("挑战缺少 challenge_token")
    if game_key == "film_calibration":
        elapsed = solve_calibration(prompt)
        events = [{"type": "freeze", "elapsed_ms": elapsed}]
        answer: Any = {}
    elif game_key == "poster_memory":
        keys = solve_memory(prompt)
        elapsed = max(int(prompt.get("preview_ms") or 0), 1)
        events = [{"type": "toggle", "option_key": key, "selected": True, "elapsed_ms": elapsed} for key in keys]
        events.append({"type": "submit", "elapsed_ms": elapsed})
        answer = {"selected_option_keys": keys}
    elif game_key == "missing_frame":
        option_key = solve_missing_frame(prompt)
        if not option_key:
            raise ValueError("缺帧候选无法唯一推断")
        elapsed = 1000
        events = [{"type": "select", "option_key": option_key, "elapsed_ms": elapsed}]
        answer = {"option_key": option_key}
    else:
        raise ValueError(f"不支持的放映游戏: {game_key}")
    return {
        "challenge_token": token,
        "events_json": json.dumps(events, ensure_ascii=False, separators=(",", ":")),
        "answer_json": json.dumps(answer, ensure_ascii=False, separators=(",", ":")),
    }
