import hashlib
import math
import re
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


RETRY_DATA_VERSION = 4
RETRY_SCAN_INTERVAL_SECONDS = 60
RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW = 3
RETRY_HISTORY_WINDOW_SECONDS = 24 * 60 * 60
RETRY_BACKOFF_SECONDS = (5 * 60, 15 * 60, 60 * 60)

# 115 硬风控共享冷却：连续触发时逐步放大冷却，避免每小时整点探一次
NATIVE_COOLDOWN_JITTER_SECONDS = 90
NATIVE_COOLDOWN_STREAK_MULTIPLIER_CAP = 3.0
NATIVE_COOLDOWN_STREAK_MAX = 5
NATIVE_COOLDOWN_PROBE_GAP_SECONDS = 15

RETRY_RESULT_PENDING = "pending"
RETRY_RESULT_RUNNING = "running"
RETRY_RESULT_SUCCEEDED = "succeeded"
RETRY_RESULT_FAILED = "failed"
RETRY_RESULT_MANUAL = "manual_required"
RETRY_RESULT_HANDLED = "handled"

TRANSIENT_ERROR_PATTERNS = (
    "timeouterror",
    "timed out",
    "timeout",
    "write operation timed out",
    "read operation timed out",
    "connect timeout",
    "connection timeout",
    "connection aborted",
    "connection reset",
    "connection refused",
    "remote disconnected",
    "temporarily unavailable",
    "temporary network",
    "service unavailable",
    "too many requests",
    "request limit",
    "network error",
    "network exception",
    "oss network",
    "oss2.exceptions",
    "u115 network",
    "连接超时",
    "读取超时",
    "写入超时",
    "连接中断",
    "连接被重置",
    "网络异常",
    "网络错误",
    "临时服务错误",
    "服务暂不可用",
    "请求过多",
    "request timeout",
    "gateway timeout",
    "http 408",
    "http 425",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
    "429",
    "502",
    "503",
    "504",
)

AUTH_ERROR_PATTERNS = (
    "unauthorized",
    "forbidden",
    "authentication failed",
    "invalid credential",
    "invalid signature",
    "access denied",
    "permission denied",
    "登录失效",
    "认证失效",
    "凭证失效",
    "签名失效",
    "无权限",
    "权限不足",
    "401",
    "403",
)

DAMAGED_ERROR_PATTERNS = (
    "记录损坏",
    "历史记录损坏",
    "缺少源文件信息",
    "缺少源文件项",
    "缺少必要参数",
    "invalid argument",
    "validation error",
    "src_fileitem",
)

MISSING_SOURCE_PATTERNS = (
    "源目录不存在",
    "源文件不存在",
    "没有找到可整理的媒体文件",
    "no such file",
    "source not found",
    "source does not exist",
)

ERROR_FIELD_NAMES = (
    "errmsg",
    "error",
    "error_msg",
    "error_message",
    "last_message",
    "message",
    "reason",
    "fail_reason",
    "failure_reason",
    "detail",
)

ERROR_CONTAINER_NAMES = (
    "result",
    "data",
    "response",
    "payload",
    "errors",
    "error_detail",
)


def get_value(source: Any, names: Iterable[str], default: Any = "") -> Any:
    for name in names:
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value not in (None, ""):
            return value
    return default


def normalize_text(value: Any, *, lower: bool = False) -> str:
    text = str(value or "").strip()
    return text.casefold() if lower else text


def normalize_path(value: Any) -> str:
    text = normalize_text(value).replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def normalize_season(value: Any) -> str:
    text = normalize_text(value, lower=True).upper()
    return text.lstrip("S").lstrip("0") or ("0" if text else "")


def normalize_episodes(value: Any) -> Tuple[str, ...]:
    text = normalize_text(value, lower=True).upper().replace(" ", "")
    if not text:
        return tuple()
    if "-" in text:
        try:
            start_text, end_text = text.split("-", 1)
            start = int(start_text.replace("E", "") or 0)
            end = int(end_text.replace("E", "") or 0)
            if start and end and start <= end:
                return tuple(str(index) for index in range(start, end + 1))
        except (TypeError, ValueError):
            pass
    episodes: List[str] = []
    for part in re.split(r"[,/;，、]+", text):
        number = part.replace("E", "").lstrip("0")
        if number:
            episodes.append(number)
    return tuple(episodes)


def retry_group_key(history: Any) -> str:
    source_payload = get_value(history, ("src_fileitem",), {})
    source_storage = get_value(history, ("src_storage", "source_storage", "storage"))
    if not source_storage:
        source_storage = get_value(source_payload, ("storage", "storage_type"))
    source_path = get_value(history, ("src", "source", "source_path"))
    if not source_path:
        source_path = get_value(source_payload, ("path", "file_path"))

    download_hash = normalize_text(get_value(history, ("download_hash",)), lower=True)
    media_source = normalize_text(get_value(history, ("media_source", "source_type")), lower=True)
    media_id = normalize_text(get_value(history, ("media_id",)))
    tmdbid = normalize_text(get_value(history, ("tmdbid",)))
    season = normalize_season(get_value(history, ("seasons", "season")))
    episodes = ",".join(normalize_episodes(get_value(history, ("episodes", "episode"))))
    normalized_source = normalize_path(source_path)
    normalized_storage = normalize_text(source_storage, lower=True)
    media_identity = f"{media_source}:{media_id}" if media_source and media_id else f"tmdb:{tmdbid}" if tmdbid else ""

    if not any((download_hash, normalized_source, media_identity, season, episodes)):
        return ""
    identity = "|".join(
        (download_hash, normalized_storage, normalized_source, media_identity, season, episodes)
    )
    return "group:" + hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()[:32]


def short_group_key(group_key: Any) -> str:
    text = normalize_text(group_key).removeprefix("group:").removeprefix("task:")
    return text[:10] or "unknown"


def to_timestamp(value: Any) -> float:
    if value in (None, "", 0, "0"):
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return max(float(text), 0.0)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def history_failed_at(history: Any) -> float:
    return to_timestamp(
        get_value(history, ("updated_at", "date", "time", "created_at", "transfer_time"))
    )


def sanitize_message(value: Any, limit: int = 200) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"(?i)(authorization|cookie|token|password|secret)\s*[:=]\s*[^\s,;]+", r"\1=<redacted>", text)
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+\-/]+=*", "Bearer <redacted>", text)
    text = re.sub(r"https?://[^\s?#]+\?[^\s]+", "<url-with-query-redacted>", text)
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\s,;]+", "<local-path>", text)
    text = re.sub(r"(?<![:\w])/(?:[^\s,;]+/)+[^\s,;]+", "<local-path>", text)
    text = re.sub(r"(?<!:)//[^\s,;]+", "<path>", text)
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def extract_history_error(history: Any, record: Optional[Dict[str, Any]] = None) -> str:
    history_message = _find_nested_error_value(history)
    if history_message:
        return sanitize_message(history_message)
    record = record if isinstance(record, dict) else {}
    return sanitize_message(_find_nested_error_value(record) or "")


def _named_value(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _find_nested_error_value(source: Any, *, max_depth: int = 4) -> Any:
    """Read known error fields without walking arbitrary model attributes."""
    visited = set()

    def visit(value: Any, depth: int) -> Any:
        if value in (None, "", False):
            return ""
        if isinstance(value, (str, int, float)):
            return value
        if depth > max_depth:
            return ""
        marker = id(value)
        if marker in visited:
            return ""
        visited.add(marker)

        for name in ERROR_FIELD_NAMES:
            candidate = _named_value(value, name)
            if candidate in (None, "", False):
                continue
            if isinstance(candidate, (dict, list, tuple)):
                nested = visit(candidate, depth + 1)
                if nested not in (None, "", False):
                    return nested
            else:
                return candidate

        for name in ERROR_CONTAINER_NAMES:
            candidate = _named_value(value, name)
            if candidate not in (None, "", False):
                nested = visit(candidate, depth + 1)
                if nested not in (None, "", False):
                    return nested
        if isinstance(value, (list, tuple)):
            for item in value[:20]:
                nested = visit(item, depth + 1)
                if nested not in (None, "", False):
                    return nested
        return ""

    return visit(source, 0)


def classify_retry_error(message: Any) -> Dict[str, Any]:
    sanitized = sanitize_message(message)
    lowered = sanitized.casefold()
    if any(pattern.casefold() in lowered for pattern in MISSING_SOURCE_PATTERNS):
        return {"code": "source_missing", "auto_retryable": False, "manual_retryable": False, "message": sanitized}
    if any(pattern.casefold() in lowered for pattern in DAMAGED_ERROR_PATTERNS):
        return {"code": "record_damaged", "auto_retryable": False, "manual_retryable": False, "message": sanitized}
    if any(pattern.casefold() in lowered for pattern in AUTH_ERROR_PATTERNS):
        return {"code": "auth_or_permission", "auto_retryable": False, "manual_retryable": True, "message": sanitized}
    if any(pattern.casefold() in lowered for pattern in TRANSIENT_ERROR_PATTERNS):
        return {"code": "transient", "auto_retryable": True, "manual_retryable": True, "message": sanitized}
    return {"code": "unknown", "auto_retryable": False, "manual_retryable": True, "message": sanitized or "未识别到可自动重试的错误信息"}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def recent_attempts(record: Dict[str, Any], now_ts: float) -> List[float]:
    raw = record.get("attempt_timestamps") if isinstance(record, dict) else []
    values: List[float] = []
    if isinstance(raw, list):
        for item in raw:
            timestamp = to_timestamp(item)
            if timestamp and now_ts - timestamp < RETRY_HISTORY_WINDOW_SECONDS:
                values.append(timestamp)
    legacy_last = to_timestamp(record.get("last_attempt_at") or record.get("last_attempt_ts")) if isinstance(record, dict) else 0.0
    if legacy_last and now_ts - legacy_last < RETRY_HISTORY_WINDOW_SECONDS:
        values.append(legacy_last)
    return sorted(set(values))


def normalize_record(record: Optional[Dict[str, Any]], now_ts: float, *, group_key: str = "") -> Dict[str, Any]:
    source = dict(record or {})
    attempts = recent_attempts(source, now_ts)
    history_ids = source.get("history_ids")
    normalized_ids = sorted({str(item) for item in history_ids or [] if str(item)}) if isinstance(history_ids, list) else []
    latest_history_id = str(source.get("latest_history_id") or source.get("history_id") or "")
    if latest_history_id:
        normalized_ids = sorted(set(normalized_ids + [latest_history_id]))
    first_seen_at = to_timestamp(source.get("first_seen_at"))
    total_attempts = _to_int(source.get("total_attempts", source.get("attempts", 0)))
    last_attempt_at = max(attempts) if attempts else to_timestamp(source.get("last_attempt_at") or source.get("last_attempt_ts"))
    return {
        "group_key": group_key or str(source.get("group_key") or source.get("task_key") or ""),
        "latest_history_id": latest_history_id,
        "history_ids": normalized_ids,
        "attempt_timestamps": attempts,
        "total_attempts": max(total_attempts, len(attempts)),
        "consecutive_failures": _to_int(source.get("consecutive_failures")),
        "first_seen_at": first_seen_at,
        "last_attempt_at": last_attempt_at,
        "next_retry_at": to_timestamp(source.get("next_retry_at") or source.get("next_retry_after")),
        "last_result": str(source.get("last_result") or (RETRY_RESULT_SUCCEEDED if source.get("success") else RETRY_RESULT_PENDING)),
        "last_message": sanitize_message(source.get("last_message") or source.get("message") or ""),
        "manual_required": bool(source.get("manual_required")),
        "error_code": str(source.get("error_code") or ""),
        "updated_at": str(source.get("updated_at") or ""),
    }


def merge_records(
    group_key: str,
    stable_records: Iterable[Dict[str, Any]],
    legacy_history_records: Iterable[Dict[str, Any]],
    history_ids: Iterable[str],
    now_ts: float,
) -> Dict[str, Any]:
    stable = [normalize_record(record, now_ts, group_key=group_key) for record in stable_records if isinstance(record, dict)]
    legacy = [normalize_record(record, now_ts, group_key=group_key) for record in legacy_history_records if isinstance(record, dict)]
    all_records = stable + legacy
    if not all_records:
        merged = normalize_record({}, now_ts, group_key=group_key)
    else:
        merged = max(all_records, key=lambda item: (item["last_attempt_at"], item["total_attempts"])).copy()
    attempts = sorted({timestamp for record in all_records for timestamp in record["attempt_timestamps"]})
    stable_total = max((record["total_attempts"] for record in stable), default=0)
    legacy_total = sum(record["total_attempts"] for record in legacy)
    merged["group_key"] = group_key
    merged["history_ids"] = sorted({str(item) for item in history_ids if str(item)} | {item for record in all_records for item in record["history_ids"]})
    merged["attempt_timestamps"] = attempts
    merged["total_attempts"] = max(stable_total, legacy_total, len(attempts), merged.get("total_attempts", 0))
    merged["consecutive_failures"] = max((record["consecutive_failures"] for record in all_records), default=0)
    merged["first_seen_at"] = min((record["first_seen_at"] for record in all_records if record["first_seen_at"]), default=0.0)
    merged["last_attempt_at"] = max(attempts) if attempts else max((record["last_attempt_at"] for record in all_records), default=0.0)
    merged["manual_required"] = any(record["manual_required"] for record in all_records)
    return merged


def round_up_to_scan(timestamp: float, scan_anchor: float, interval_seconds: int = RETRY_SCAN_INTERVAL_SECONDS) -> float:
    if timestamp <= scan_anchor:
        return scan_anchor
    steps = math.ceil((timestamp - scan_anchor) / max(interval_seconds, 1))
    return scan_anchor + steps * max(interval_seconds, 1)


def calculate_next_retry_at(
    history: Any,
    group_record: Dict[str, Any],
    safety_state: Optional[Dict[str, Any]],
    cooldown_state: Optional[Dict[str, Any]],
    *,
    now_ts: float,
    next_scan_at: float,
    retry_delay_seconds: int = 0,
) -> Tuple[float, str]:
    record = normalize_record(group_record, now_ts, group_key=str(group_record.get("group_key") or ""))
    attempts = recent_attempts(record, now_ts)
    first_seen = record["first_seen_at"] or history_failed_at(history) or now_ts
    reasons: List[Tuple[float, str]] = []

    if len(attempts) >= RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW:
        reasons.append((min(attempts) + RETRY_HISTORY_WINDOW_SECONDS, "24 小时滚动次数窗口"))
    elif not attempts:
        reasons.append((first_seen + RETRY_BACKOFF_SECONDS[0], "首次失败等待 5 分钟"))
    elif len(attempts) == 1:
        reasons.append((max(attempts) + RETRY_BACKOFF_SECONDS[1], "首次重试失败后退避 15 分钟"))
    else:
        reasons.append((max(attempts) + RETRY_BACKOFF_SECONDS[2], "第二次重试失败后退避 60 分钟"))

    cooldown_until = to_timestamp((cooldown_state or {}).get("until"))
    if cooldown_until > now_ts:
        reasons.append((cooldown_until + max(int(retry_delay_seconds), 0), "等待 115 风控冷却结束"))
    safety_retry_at = to_timestamp((safety_state or {}).get("retry_after"))
    if not (safety_state or {}).get("allowed", True) and safety_retry_at > now_ts:
        reasons.append((safety_retry_at + max(int(retry_delay_seconds), 0), "等待 API 安全余量恢复"))

    policy_at, reason = max(reasons, key=lambda item: item[0])
    effective_at = max(policy_at, next_scan_at or now_ts)
    if effective_at > policy_at:
        reason = f"{reason}；等待下一次周期扫描"
    return effective_at, reason


def calculate_manual_retry_at(
    group_record: Dict[str, Any],
    safety_state: Optional[Dict[str, Any]],
    cooldown_state: Optional[Dict[str, Any]],
    *,
    now_ts: float,
    retry_delay_seconds: int = 0,
) -> Tuple[float, str]:
    """Apply safety, cooldown and rolling quota limits without auto backoff."""
    record = normalize_record(group_record, now_ts, group_key=str(group_record.get("group_key") or ""))
    attempts = recent_attempts(record, now_ts)
    reasons: List[Tuple[float, str]] = []

    if len(attempts) >= RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW:
        reasons.append((min(attempts) + RETRY_HISTORY_WINDOW_SECONDS, "24 小时滚动次数窗口"))

    cooldown_until = to_timestamp((cooldown_state or {}).get("until"))
    if cooldown_until > now_ts:
        reasons.append((cooldown_until + max(int(retry_delay_seconds), 0), "等待 115 风控冷却结束"))
    safety_retry_at = to_timestamp((safety_state or {}).get("retry_after"))
    if not (safety_state or {}).get("allowed", True) and safety_retry_at > now_ts:
        reasons.append((safety_retry_at + max(int(retry_delay_seconds), 0), "等待 API 安全余量恢复"))

    if not reasons:
        return now_ts, "人工确认后可立即重试"
    return max(reasons, key=lambda item: item[0])


def reserve_attempt(record: Dict[str, Any], history: Any, now_ts: float) -> Dict[str, Any]:
    group_key = str(record.get("group_key") or retry_group_key(history))
    reserved = normalize_record(record, now_ts, group_key=group_key)
    reserved["latest_history_id"] = str(get_value(history, ("id",)))
    reserved["history_ids"] = sorted(set(reserved["history_ids"] + [reserved["latest_history_id"]]))
    reserved["attempt_timestamps"] = sorted(set(recent_attempts(reserved, now_ts) + [now_ts]))
    reserved["total_attempts"] += 1
    reserved["last_attempt_at"] = now_ts
    reserved["last_result"] = RETRY_RESULT_RUNNING
    reserved["last_message"] = "已记录尝试，等待 MoviePilot 整理结果"
    reserved["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return reserved


def cooldown_streak_multiplier(fail_streak: Any) -> float:
    """连续第 N 轮硬风控的冷却放大系数：1.0、1.5、2.0……最多放大到 3.0 倍。"""
    streak = max(int(fail_streak or 0), 1)
    return min(1.0 + 0.5 * (streak - 1), NATIVE_COOLDOWN_STREAK_MULTIPLIER_CAP)


def escalated_cooldown_seconds(base_seconds: Any, fail_streak: Any) -> float:
    """按连续失败轮次放大基础冷却秒数，基础值非法时返回 0。"""
    base = max(float(base_seconds or 0.0), 0.0)
    return base * cooldown_streak_multiplier(fail_streak)


def jittered_wait_seconds(remaining_seconds: Any, random_value: Any) -> float:
    """在冷却剩余时间上叠加 0 到抖动上限之间的随机偏移，打散同时醒来的请求。"""
    remaining = max(float(remaining_seconds or 0.0), 0.0)
    ratio = min(max(float(random_value or 0.0), 0.0), 1.0)
    return remaining + ratio * max(float(NATIVE_COOLDOWN_JITTER_SECONDS), 0.0)


def should_start_cooldown_probe(
    *,
    now_ts: float,
    cooldown_until: Any,
    probe_in_flight: bool,
    last_probe_at: Any = 0.0,
    probe_gap_seconds: Any = NATIVE_COOLDOWN_PROBE_GAP_SECONDS,
) -> bool:
    """判断当前请求能否成为冷却结束后的探针请求：冷却已结束、无其他探针在飞、且满足最小间隔。"""
    if probe_in_flight:
        return False
    try:
        until = float(cooldown_until or 0.0)
    except (TypeError, ValueError):
        until = 0.0
    if until > now_ts:
        return False
    gap = max(float(probe_gap_seconds or 0.0), 0.0)
    try:
        last_probe = float(last_probe_at or 0.0)
    except (TypeError, ValueError):
        last_probe = 0.0
    if gap and last_probe and now_ts - last_probe < gap:
        return False
    return True

