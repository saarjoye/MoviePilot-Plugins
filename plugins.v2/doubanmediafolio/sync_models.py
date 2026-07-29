import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Iterable, Optional


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
RETRY_COOLDOWN = timedelta(hours=6)
MAX_RETRY_COUNT = 5
RETRY_REOPEN_DELAY = timedelta(hours=24)


class FailureKind(str, Enum):
    NONE = "none"
    AUTH = "auth"
    TRANSIENT = "transient"
    NOT_ALLOWED = "not_allowed"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"


TERMINAL_FAILURES = {
    FailureKind.NOT_ALLOWED,
    FailureKind.NO_MATCH,
    FailureKind.AMBIGUOUS,
}


@dataclass(frozen=True)
class SubjectCandidate:
    subject_id: str
    title: str
    year: Optional[int] = None
    media_type: Optional[str] = None
    season: Optional[int] = None
    source: str = "search"


@dataclass(frozen=True)
class SubjectResolveResult:
    candidate: Optional[SubjectCandidate]
    kind: FailureKind = FailureKind.NONE
    message: str = ""
    retryable: bool = False

    @property
    def success(self) -> bool:
        return self.candidate is not None


@dataclass(frozen=True)
class DoubanActionResult:
    success: bool
    kind: FailureKind = FailureKind.NONE
    message: str = ""
    retryable: bool = False


_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def extract_season(value: Optional[str]) -> Optional[int]:
    value = str(value or "")
    match = re.search(r"第\s*([0-9一二三四五六七八九十]+)\s*季", value, re.IGNORECASE)
    if not match:
        match = re.search(r"(?:^|\s)S(?:eason)?\s*0*([0-9]{1,3})(?:\s|$)", value, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    if token in _CHINESE_NUMBERS:
        return _CHINESE_NUMBERS[token]
    if token.startswith("十") and len(token) == 2:
        return 10 + _CHINESE_NUMBERS.get(token[1], 0)
    if token.endswith("十") and len(token) == 2:
        return _CHINESE_NUMBERS.get(token[0], 0) * 10
    return None


def normalize_title(value: Optional[str]) -> str:
    value = str(value or "")
    value = re.sub(r"第\s*[0-9一二三四五六七八九十]+\s*季", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:^|\s)S(?:eason)?\s*0*[0-9]{1,3}(?:\s|$)", "", value, flags=re.IGNORECASE)
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def normalize_media_type(value: Optional[str]) -> Optional[str]:
    value = str(value or "").strip().casefold()
    if not value or value in {"影视", "movie"}:
        return None
    if value in {"mov", "电影", "film"}:
        return "movie"
    if value in {"tv", "电视剧", "电视", "剧集", "动画", "动漫", "综艺", "纪录片"}:
        return "tv"
    return None


def select_subject_candidate(
        title: str,
        candidates: Iterable[SubjectCandidate],
        year: Optional[int] = None,
        media_type: Optional[str] = None,
        season: Optional[int] = None,
) -> SubjectResolveResult:
    expected_title = normalize_title(title)
    expected_type = normalize_media_type(media_type)
    expected_season = season or extract_season(title)
    scored = []
    seen_ids = set()

    for candidate in candidates:
        if not candidate.subject_id or candidate.subject_id in seen_ids:
            continue
        seen_ids.add(candidate.subject_id)
        if normalize_title(candidate.title) != expected_title:
            continue
        if year and candidate.year and int(candidate.year) != int(year):
            continue
        candidate_type = normalize_media_type(candidate.media_type)
        if expected_type and candidate_type and candidate_type != expected_type:
            continue
        candidate_season = candidate.season or extract_season(candidate.title)
        if expected_season and expected_season > 1 and candidate_season != expected_season:
            continue
        if candidate_season and expected_season and candidate_season != expected_season:
            continue

        score = 100
        if year and candidate.year and int(candidate.year) == int(year):
            score += 20
        if expected_type and candidate_type == expected_type:
            score += 15
        if expected_season and candidate_season == expected_season:
            score += 10
        scored.append((score, candidate))

    if not scored:
        return SubjectResolveResult(
            candidate=None,
            kind=FailureKind.NO_MATCH,
            message="未找到与标题、年份、类型和季号一致的豆瓣条目",
        )

    best_score = max(item[0] for item in scored)
    best = [item[1] for item in scored if item[0] == best_score]
    if len(best) != 1:
        return SubjectResolveResult(
            candidate=None,
            kind=FailureKind.AMBIGUOUS,
            message="豆瓣搜索存在多个同等匹配条目，无法安全确认目标",
        )
    return SubjectResolveResult(candidate=best[0])


def resolve_subject_target(
        direct_douban_id: Optional[str],
        title: str,
        candidates: Iterable[SubjectCandidate],
        year: Optional[int] = None,
        media_type: Optional[str] = None,
        season: Optional[int] = None,
) -> SubjectResolveResult:
    direct_id = str(direct_douban_id or "").strip()
    if direct_id:
        return SubjectResolveResult(candidate=SubjectCandidate(
            subject_id=direct_id,
            title=title,
            year=year,
            media_type=media_type,
            season=season,
            source="media_info",
        ))
    return select_subject_candidate(title, candidates, year, media_type, season)


def classify_action_response(
        status_code: int,
        payload: Optional[Dict[str, Any]] = None,
        auth_failed: bool = False,
        message: str = "",
) -> DoubanActionResult:
    payload = payload or {}
    if status_code == 200 and payload.get("r") is not False:
        return DoubanActionResult(success=True)
    if auth_failed:
        return DoubanActionResult(
            success=False,
            kind=FailureKind.AUTH,
            message=message or "豆瓣登录状态无效",
            retryable=True,
        )
    if status_code == 200 and payload.get("r") is False:
        return DoubanActionResult(
            success=False,
            kind=FailureKind.NOT_ALLOWED,
            message=message or "豆瓣未开播或不允许标记该条目",
        )
    if 400 <= status_code < 500 and status_code != 429:
        return DoubanActionResult(
            success=False,
            kind=FailureKind.NOT_ALLOWED,
            message=message or f"豆瓣拒绝标记该条目（HTTP {status_code}）",
        )
    return DoubanActionResult(
        success=False,
        kind=FailureKind.TRANSIENT,
        message=message or f"豆瓣服务返回 HTTP {status_code}",
        retryable=True,
    )


def normalize_wait_entry(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = dict(entry or {})
    try:
        normalized["retry_count"] = max(0, int(normalized.get("retry_count", 0)))
    except (TypeError, ValueError):
        normalized["retry_count"] = 0
    normalized.setdefault("next_retry_at", "")
    normalized.setdefault("last_error", "")
    normalized.setdefault("douban_id", "")
    return normalized


def retry_is_due(entry: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    value = normalize_wait_entry(entry).get("next_retry_at")
    if not value:
        return True
    try:
        return now >= datetime.strptime(value, DATETIME_FORMAT)
    except (TypeError, ValueError):
        return True


def schedule_initial_retry(entry: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now()
    result = normalize_wait_entry(entry)
    result["retry_count"] = 0
    result["next_retry_at"] = (now + RETRY_COOLDOWN).strftime(DATETIME_FORMAT)
    return result


def record_retry_failure(
        entry: Dict[str, Any],
        now: Optional[datetime] = None,
) -> tuple[Dict[str, Any], bool]:
    now = now or datetime.now()
    result = normalize_wait_entry(entry)
    result["retry_count"] += 1
    result["next_retry_at"] = (now + RETRY_COOLDOWN).strftime(DATETIME_FORMAT)
    return result, result["retry_count"] >= MAX_RETRY_COUNT


def failure_is_suppressed(
        entry: Optional[Dict[str, Any]],
        current_subject_id: str = "",
        now: Optional[datetime] = None,
) -> tuple[bool, bool]:
    """返回是否抑制，以及调用方是否应删除已失效的抑制记录。"""
    if not isinstance(entry, dict):
        return False, False
    stored_id = str(entry.get("subject_id") or "").strip()
    current_id = str(current_subject_id or "").strip()
    if stored_id and not current_id:
        return False, False
    if stored_id != current_id:
        return False, True
    blocked_until = entry.get("blocked_until")
    if not blocked_until:
        return True, False
    try:
        blocked = (now or datetime.now()) < datetime.strptime(blocked_until, DATETIME_FORMAT)
    except (TypeError, ValueError):
        return True, False
    return blocked, not blocked
