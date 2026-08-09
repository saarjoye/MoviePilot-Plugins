import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
RETRY_COOLDOWN = timedelta(hours=6)
MAX_RETRY_COUNT = 5
RETRY_REOPEN_DELAY = timedelta(hours=24)
MATCHER_VERSION = 4
SEGMENT_GAP_DAYS = 60


class FailureKind(str, Enum):
    NONE = "none"
    AUTH = "auth"
    RESTRICTED = "restricted"
    TRANSIENT = "transient"
    NOT_ALLOWED = "not_allowed"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"


class AuthState(str, Enum):
    VALID = "valid"
    LOGGED_OUT = "logged_out"
    TRANSIENT = "transient"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


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
    release_date: Optional[str] = None


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
class SubjectSearchResult:
    candidates: Tuple[SubjectCandidate, ...] = ()
    kind: FailureKind = FailureKind.NONE
    message: str = ""
    retryable: bool = False

    @property
    def success(self) -> bool:
        return bool(self.candidates)


@dataclass(frozen=True)
class SubjectReleaseResult:
    release_date: Optional[str] = None
    kind: FailureKind = FailureKind.NONE
    message: str = ""
    retryable: bool = False

    @property
    def success(self) -> bool:
        return self.kind == FailureKind.NONE


@dataclass(frozen=True)
class DoubanActionResult:
    success: bool
    kind: FailureKind = FailureKind.NONE
    message: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class AuthCheckResult:
    state: AuthState
    message: str = ""
    retryable: bool = False
    login_attempted: bool = False

    @property
    def success(self) -> bool:
        return self.state == AuthState.VALID

    @property
    def explicitly_logged_out(self) -> bool:
        return self.state == AuthState.LOGGED_OUT


@dataclass(frozen=True)
class EpisodeMetadata:
    episode_number: int
    air_date: Optional[str] = None


@dataclass(frozen=True)
class SubjectSegment:
    start_episode: int
    end_episode: int
    candidate: SubjectCandidate


@dataclass(frozen=True)
class SegmentedResolveResult:
    segments: Tuple[SubjectSegment, ...] = ()
    kind: FailureKind = FailureKind.NONE
    message: str = ""

    @property
    def success(self) -> bool:
        return bool(self.segments)

    def segment_for(self, episode_number: int) -> Optional[SubjectSegment]:
        for segment in self.segments:
            if segment.start_episode <= episode_number <= segment.end_episode:
                return segment
        return None


def classify_auth_check(
        status_code: int,
        final_url: str,
        page_title: str = "",
        page_text: str = "",
) -> AuthCheckResult:
    """Classify the read-only /mine/ response without treating access errors as logout."""
    status_code = int(status_code or 0)
    final_url = str(final_url or "")
    title = str(page_title or "").strip().casefold()
    text = str(page_text or "")[:2000].casefold()
    parsed = urlparse(final_url)
    host = parsed.hostname or ""
    path = parsed.path.rstrip("/") or "/"

    if status_code == 429 or status_code >= 500:
        return AuthCheckResult(
            state=AuthState.TRANSIENT,
            message=f"豆瓣登录状态检查暂时不可用（HTTP {status_code}）",
            retryable=True,
        )

    is_login_page = (
        host == "accounts.douban.com" and path.startswith("/passport/login")
    ) or title == "登录豆瓣"
    if status_code == 401 or is_login_page:
        return AuthCheckResult(
            state=AuthState.LOGGED_OUT,
            message="豆瓣登录状态已失效",
            retryable=True,
        )

    if status_code == 403:
        return AuthCheckResult(
            state=AuthState.RESTRICTED,
            message=f"豆瓣限制了登录状态检查请求（HTTP {status_code}）",
            retryable=True,
        )

    restricted_markers = ("异常请求", "访问被拒绝", "访问受限", "机器人", "captcha")
    if any(marker in text or marker in title for marker in restricted_markers):
        return AuthCheckResult(
            state=AuthState.RESTRICTED,
            message="豆瓣登录状态检查遇到访问限制",
            retryable=True,
        )

    if 200 <= status_code < 400 and host == "www.douban.com" and path == "/mine":
        return AuthCheckResult(state=AuthState.VALID, message="豆瓣登录状态有效")

    return AuthCheckResult(
        state=AuthState.UNKNOWN,
        message="无法确认豆瓣登录状态",
        retryable=True,
    )


def choose_refreshed_ck(previous_ck: str, *candidates: Optional[str]) -> str:
    """Choose a usable refreshed CK, falling back to the previous value."""
    for candidate in candidates:
        value = str(candidate or "").strip().strip('"')
        if value and value.casefold() != "deleted":
            return value
    return str(previous_ck or "")


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


def strip_title_year_suffix(value: Optional[str], year: Optional[int] = None) -> str:
    value = str(value or "").strip()
    match = re.search(r"\s*[\(（\[【]\s*((?:19|20)\d{2})\s*[\)）\]】]\s*$", value)
    if not match:
        return value
    if year and int(match.group(1)) != int(year):
        return value
    return value[:match.start()].strip()


def normalize_title(value: Optional[str]) -> str:
    value = strip_title_year_suffix(value)
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


def normalize_release_date(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    match = re.search(r"(?<!\d)((?:19|20)\d{2}-\d{2}-\d{2})(?!\d)", str(value or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


class _InitialReleaseDateParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values: List[str] = []
        self._capture_depth = 0
        self._buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        if self._capture_depth:
            self._capture_depth += 1
            return
        attributes = dict(attrs)
        if attributes.get("property") != "v:initialReleaseDate":
            return
        content = str(attributes.get("content") or "").strip()
        if content:
            self.values.append(content)
        self._capture_depth = 1
        self._buffer = []

    def handle_data(self, data: str):
        if self._capture_depth:
            self._buffer.append(data)

    def handle_endtag(self, tag: str):
        if not self._capture_depth:
            return
        self._capture_depth -= 1
        if self._capture_depth == 0:
            text = "".join(self._buffer).strip()
            if text:
                self.values.append(text)
            self._buffer = []


def extract_initial_release_dates(html: str) -> Tuple[str, ...]:
    parser = _InitialReleaseDateParser()
    try:
        parser.feed(str(html or ""))
        parser.close()
    except Exception:
        return ()
    return tuple(dict.fromkeys(parser.values))


def preferred_initial_release_date(values: Iterable[str]) -> Optional[str]:
    parsed = [(str(value or ""), normalize_release_date(value)) for value in values]
    valid = [(raw, value) for raw, value in parsed if value]
    if not valid:
        return None
    for raw, value in valid:
        if "中国大陆" in raw:
            return value
    return valid[0][1]


def _season_label_key(season_name: Optional[str], base_title: str) -> str:
    label = normalize_title(season_name)
    base = normalize_title(base_title)
    if base and label.startswith(base):
        label = label[len(base):]
    label = re.sub(r"(?:season|part)\d+$", "", label, flags=re.IGNORECASE)
    return label[:-1] if label.endswith("篇") else label


def _candidate_part_number(title: str) -> Optional[int]:
    match = re.search(r"\bpart[.\s_-]*(\d+)\b", title, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _parse_air_date(value: Optional[str]):
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _split_episode_groups(episodes: Sequence[EpisodeMetadata]) -> List[List[EpisodeMetadata]]:
    dated = []
    for episode in episodes:
        air_date = _parse_air_date(episode.air_date)
        if episode.episode_number and air_date:
            dated.append((episode, air_date))
    dated.sort(key=lambda item: item[0].episode_number)
    if not dated or len(dated) != len(episodes):
        return []
    episode_numbers = [item[0].episode_number for item in dated]
    if episode_numbers != list(range(episode_numbers[0], episode_numbers[-1] + 1)):
        return []

    groups: List[List[EpisodeMetadata]] = [[dated[0][0]]]
    previous_date = dated[0][1]
    for episode, air_date in dated[1:]:
        if (air_date - previous_date).days >= SEGMENT_GAP_DAYS:
            groups.append([])
        groups[-1].append(episode)
        previous_date = air_date
    return groups


def _filter_segment_candidates(
        base_title: str,
        season_name: str,
        candidates: Iterable[SubjectCandidate],
) -> List[SubjectCandidate]:
    base = normalize_title(base_title)
    season_label = _season_label_key(season_name, base_title)
    if not base or not season_label:
        return []

    matched = []
    seen = set()
    for candidate in candidates:
        if not candidate.subject_id or candidate.subject_id in seen:
            continue
        candidate_title = normalize_title(candidate.title)
        candidate_type = normalize_media_type(candidate.media_type)
        if candidate_type not in {None, "tv"}:
            continue
        if not candidate_title.startswith(base):
            continue
        if season_label not in candidate_title[len(base):]:
            continue
        seen.add(candidate.subject_id)
        matched.append(candidate)
    return matched


def build_segmented_subject_mapping(
        base_title: str,
        season_name: str,
        episodes: Sequence[EpisodeMetadata],
        candidates: Iterable[SubjectCandidate],
) -> SegmentedResolveResult:
    groups = _split_episode_groups(episodes)
    matched = _filter_segment_candidates(base_title, season_name, candidates)
    if not groups or not matched:
        return SegmentedResolveResult(
            kind=FailureKind.NO_MATCH,
            message="未找到可由 TMDB 季名确认的豆瓣条目",
        )

    if len(matched) == 1:
        first_episode = min(ep.episode_number for group in groups for ep in group)
        last_episode = max(ep.episode_number for group in groups for ep in group)
        first_year = _parse_air_date(groups[0][0].air_date).year
        candidate = matched[0]
        if candidate.year and int(candidate.year) != first_year:
            return SegmentedResolveResult(
                kind=FailureKind.NO_MATCH,
                message="豆瓣候选年份与 TMDB 季首播年份不一致",
            )
        return SegmentedResolveResult(segments=(SubjectSegment(first_episode, last_episode, candidate),))

    if len(matched) != len(groups):
        return SegmentedResolveResult(
            kind=FailureKind.AMBIGUOUS,
            message="豆瓣候选数与 TMDB 播出批次数不一致",
        )

    groups_by_year: Dict[int, List[List[EpisodeMetadata]]] = {}
    candidates_by_year: Dict[int, List[SubjectCandidate]] = {}
    for group in groups:
        year = _parse_air_date(group[0].air_date).year
        groups_by_year.setdefault(year, []).append(group)
    for candidate in matched:
        if not candidate.year:
            return SegmentedResolveResult(
                kind=FailureKind.AMBIGUOUS,
                message="分段豆瓣候选缺少年份，无法安全排序",
            )
        candidates_by_year.setdefault(int(candidate.year), []).append(candidate)
    if {year: len(items) for year, items in groups_by_year.items()} != {
        year: len(items) for year, items in candidates_by_year.items()
    }:
        return SegmentedResolveResult(
            kind=FailureKind.AMBIGUOUS,
            message="豆瓣候选年份与 TMDB 播出批次无法一一对应",
        )

    segments = []
    for year in sorted(groups_by_year):
        year_groups = groups_by_year[year]
        year_candidates = candidates_by_year[year]
        if len(year_candidates) > 1:
            numbered = [(_candidate_part_number(item.title), item) for item in year_candidates]
            if any(number is None for number, _ in numbered) or len({number for number, _ in numbered}) != len(numbered):
                return SegmentedResolveResult(
                    kind=FailureKind.AMBIGUOUS,
                    message="同年豆瓣候选缺少唯一 Part 顺序",
                )
            year_candidates = [item for _, item in sorted(numbered, key=lambda pair: pair[0])]
        for group, candidate in zip(year_groups, year_candidates):
            segments.append(SubjectSegment(
                start_episode=group[0].episode_number,
                end_episode=group[-1].episode_number,
                candidate=candidate,
            ))
    segments.sort(key=lambda item: item.start_episode)
    return SegmentedResolveResult(segments=tuple(segments))


def mapping_cache_is_valid(
        entry: Optional[Dict[str, Any]],
        season_name: str,
        episode_count: int,
) -> bool:
    if not isinstance(entry, dict):
        return False
    return (
        entry.get("matcher_version") == MATCHER_VERSION
        and str(entry.get("season_name") or "") == str(season_name or "")
        and int(entry.get("episode_count") or 0) == int(episode_count or 0)
        and bool(entry.get("segments"))
    )


def segment_from_mapping_cache(
        entry: Optional[Dict[str, Any]],
        season_name: str,
        episode_count: int,
        episode_number: int,
) -> Optional[SubjectSegment]:
    if not mapping_cache_is_valid(entry, season_name, episode_count):
        return None
    for segment in entry.get("segments", []):
        start_episode = int(segment.get("start_episode", 0))
        end_episode = int(segment.get("end_episode", 0))
        if start_episode <= episode_number <= end_episode:
            return SubjectSegment(
                start_episode=start_episode,
                end_episode=end_episode,
                candidate=SubjectCandidate(
                    subject_id=str(segment.get("subject_id") or ""),
                    title=str(segment.get("subject_name") or ""),
                    year=segment.get("year"),
                    media_type="电视剧",
                    source="tmdb_segment_cache",
                ),
            )
    return None


def should_use_segmented_fallback(
        media_type: str,
        direct_douban_id: Optional[str],
        failure_kind: FailureKind,
) -> bool:
    return (
        normalize_media_type(media_type) == "tv"
        and not str(direct_douban_id or "").strip()
        and failure_kind in {FailureKind.NO_MATCH, FailureKind.AMBIGUOUS}
    )


def status_for_segment(default_status: str, episode_number: Optional[int], segment_end: Optional[int]) -> str:
    if episode_number is None or segment_end is None:
        return default_status
    return "collect" if int(episode_number) >= int(segment_end) else "do"


def find_processed_record_key(
        processed_items: Dict[str, Any],
        title: str,
        subject_id: str,
) -> Optional[str]:
    for key, value in processed_items.items():
        if key != title and not key.startswith(f"{title}::"):
            continue
        if isinstance(value, dict) and str(value.get("subject_id") or "") == str(subject_id or ""):
            return key
    return None


def select_subject_candidate(
        title: str,
        candidates: Iterable[SubjectCandidate],
        year: Optional[int] = None,
        media_type: Optional[str] = None,
        season: Optional[int] = None,
        release_date: Any = None,
) -> SubjectResolveResult:
    expected_title = normalize_title(title)
    expected_type = normalize_media_type(media_type)
    expected_season = season or extract_season(title)
    expected_release_date = normalize_release_date(release_date)
    scored = []
    seen_ids = set()

    for candidate in candidates:
        if not candidate.subject_id or candidate.subject_id in seen_ids:
            continue
        seen_ids.add(candidate.subject_id)
        if normalize_title(candidate.title) != expected_title:
            continue
        candidate_type = normalize_media_type(candidate.media_type)
        if expected_type and candidate_type and candidate_type != expected_type:
            continue
        candidate_season = candidate.season or extract_season(candidate.title)
        if expected_season and expected_season > 1 and candidate_season != expected_season:
            continue
        if candidate_season and expected_season and candidate_season != expected_season:
            continue

        candidate_release_date = normalize_release_date(candidate.release_date)
        if expected_release_date and candidate_release_date:
            if candidate_release_date != expected_release_date:
                continue
        elif year and candidate.year and int(candidate.year) != int(year):
            continue

        score = 100
        if expected_release_date and candidate_release_date == expected_release_date:
            score += 30
        if year and candidate.year and int(candidate.year) == int(year):
            score += 20
        if expected_type and candidate_type == expected_type:
            score += 15
        if expected_season and candidate_season == expected_season:
            score += 10
        scored.append((score, candidate))

    if not scored:
        criteria = "标题、年份或上映日期、类型和季号" if expected_release_date else "标题、年份、类型和季号"
        return SubjectResolveResult(
            candidate=None,
            kind=FailureKind.NO_MATCH,
            message=f"未找到与{criteria}一致的豆瓣条目",
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
        release_date: Any = None,
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
            release_date=normalize_release_date(release_date),
        ))
    return select_subject_candidate(title, candidates, year, media_type, season, release_date)


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
    if status_code == 403:
        return DoubanActionResult(
            success=False,
            kind=FailureKind.RESTRICTED,
            message=message or "豆瓣访问限制拒绝了标记请求（HTTP 403）",
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
    normalized.setdefault("release_date", "")
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
    exhausted = result["retry_count"] >= MAX_RETRY_COUNT
    delay = RETRY_REOPEN_DELAY if exhausted else RETRY_COOLDOWN
    result["next_retry_at"] = (now + delay).strftime(DATETIME_FORMAT)
    return result, exhausted


def prepare_retry_attempt(
        entry: Dict[str, Any],
        now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Reset an exhausted retry counter when its 24-hour pause has elapsed."""
    result = normalize_wait_entry(entry)
    if result["retry_count"] >= MAX_RETRY_COUNT and retry_is_due(result, now):
        result["retry_count"] = 0
    return result


def failure_is_suppressed(
        entry: Optional[Dict[str, Any]],
        current_subject_id: str = "",
        now: Optional[datetime] = None,
) -> tuple[bool, bool]:
    """返回是否抑制，以及调用方是否应删除已失效的抑制记录。"""
    if not isinstance(entry, dict):
        return False, False
    if (
            entry.get("kind") in {FailureKind.NO_MATCH.value, FailureKind.AMBIGUOUS.value}
            and int(entry.get("matcher_version") or 0) < MATCHER_VERSION
    ):
        return False, True
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
