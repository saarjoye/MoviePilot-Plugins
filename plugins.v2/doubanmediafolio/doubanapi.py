import re
from dataclasses import replace
from http.cookies import CookieError, SimpleCookie
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.meta import MetaBase
from app.helper.cookiecloud import CookieCloudHelper
from app.log import logger
from .sync_models import (
    AuthCheckResult,
    AuthState,
    DoubanActionResult,
    FailureKind,
    SubjectCandidate,
    SubjectResolveResult,
    SubjectReleaseResult,
    SubjectSearchResult,
    choose_refreshed_ck,
    classify_auth_check,
    classify_action_response,
    extract_season,
    extract_initial_release_dates,
    normalize_media_type,
    normalize_release_date,
    normalize_title,
    preferred_initial_release_date,
    select_subject_candidate,
    strip_title_year_suffix,
)


class DoubanApi:
    HOME_URL = "https://www.douban.com/"
    MINE_URL = "https://www.douban.com/mine/"
    LOGIN_PAGE = "https://accounts.douban.com/passport/login"
    LOGIN_API = "https://accounts.douban.com/j/mobile/login/basic"
    SEARCH_URL = "https://www.douban.com/search"
    INTEREST_URL = "https://movie.douban.com/j/subject/{subject_id}/interest"
    SUBJECT_URL = "https://movie.douban.com/subject/{subject_id}/"

    def __init__(
            self,
            user_cookie: str = None,
            username: str = None,
            password: str = None,
            auto_login: bool = True,
            allow_restricted_login: bool = False,
    ):
        self.username = (username or "").strip()
        self.password = password or ""
        self.auto_login = bool(auto_login)
        self.allow_restricted_login = bool(allow_restricted_login)
        self.restricted_login_attempted = False
        self.restricted_login_succeeded = False
        self.restricted_login_verified = False
        self.session = requests.Session()
        self.cookies: Dict[str, str] = self._load_cookies(user_cookie)
        self.ck: str = self.cookies.get("ck", "")

        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, sdch",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.6,en;q=0.4,en-GB;q=0.2,zh-TW;q=0.2",
            "Connection": "keep-alive",
            "DNT": "1",
        }
        self.session.headers.update(self.headers)
        self._apply_cookies(self.cookies)

        if not self.cookies:
            logger.error("cookie获取为空，请检查插件配置或cookie cloud")
        elif not self.ck:
            logger.warning("豆瓣Cookie中未发现CK，将在提交观影状态前按需刷新")

    def _load_cookies(self, user_cookie: str = None) -> Dict[str, str]:
        if user_cookie:
            return self._parse_cookie_string(user_cookie)

        cookie_dict, msg = CookieCloudHelper().download()
        if cookie_dict is None:
            logger.error(f"获取cookiecloud数据错误 {self._safe_message(msg)}")
            return {}

        cookie_string = cookie_dict.get("douban.com") or cookie_dict.get(".douban.com") or ""
        return self._parse_cookie_string(cookie_string)

    @staticmethod
    def _parse_cookie_string(cookie_string: str) -> Dict[str, str]:
        if not cookie_string:
            return {}
        try:
            return {k: v.value for k, v in SimpleCookie(cookie_string).items()}
        except CookieError as err:
            logger.error(f"解析豆瓣cookie失败: {err}")
            return {}

    def _apply_cookies(self, cookies: Dict[str, str]):
        self.cookies = dict(cookies or {})
        self.cookies.pop("__utmz", None)
        self.session.cookies.clear()
        self.session.cookies.update(self.cookies)

    def _update_cookies_from_session(self):
        session_cookies = self.session.cookies.get_dict()
        if session_cookies:
            self.cookies.update(session_cookies)
            self.cookies.pop("__utmz", None)
            self.ck = self.cookies.get("ck", self.ck)

    def _remove_cookie(self, name: str):
        self.cookies.pop(name, None)
        for cookie in list(self.session.cookies):
            if cookie.name == name:
                try:
                    self.session.cookies.clear(domain=cookie.domain, path=cookie.path, name=cookie.name)
                except KeyError:
                    pass

    def _cookie_header(self) -> str:
        self._update_cookies_from_session()
        return "; ".join([f"{key}={value}" for key, value in self.cookies.items()])

    def get_cookie_string(self) -> str:
        return self._cookie_header()

    @staticmethod
    def _extract_ck(set_cookie_header: str) -> Optional[str]:
        if not set_cookie_header:
            return None
        try:
            cookie = SimpleCookie(set_cookie_header)
            if "ck" in cookie:
                return cookie["ck"].value
        except CookieError:
            pass
        match = re.search(r"(?:^|,\s*)ck=([^;,\s]+)", set_cookie_header)
        return match.group(1) if match else None

    @staticmethod
    def _safe_message(message: str) -> str:
        message = str(message or "未知原因")
        message = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "***", message)
        message = re.sub(r"\b\d{6,}\b", "***", message)
        return message[:200]

    @staticmethod
    def _looks_like_auth_failed(response: requests.Response, payload: Optional[dict] = None) -> bool:
        if response.status_code == 401:
            return True
        text = response.text[:1000] if response.text else ""
        if "passport/login" in response.url or "登录豆瓣" in text:
            return True
        if response.status_code == 403:
            return False
        if payload:
            message = str(payload.get("message") or payload.get("msg") or payload.get("description") or "")
            if any(keyword in message for keyword in ("登录", "ck", "cookie", "captcha", "验证码")):
                return True
        return False

    def _restore_ck(self, ck: str):
        if not ck:
            self.ck = ""
            return
        self.cookies["ck"] = ck
        self.session.cookies.set("ck", ck)
        self.ck = ck

    def set_ck(self, force_refresh: bool = False) -> bool:
        previous_ck = self.ck or self.cookies.get("ck", "")
        if previous_ck and not force_refresh:
            self._restore_ck(previous_ck)
            return True

        self._remove_cookie("ck")
        self.ck = ""
        try:
            response = self.session.get(
                self.HOME_URL,
                headers={**self.headers, "Host": "www.douban.com"},
                timeout=15,
                allow_redirects=True
            )
        except Exception as err:
            logger.error(f"请求豆瓣首页刷新ck失败: {self._safe_message(err)}")
            self._restore_ck(previous_ck)
            return False

        self._update_cookies_from_session()
        session_ck = self.session.cookies.get_dict().get("ck")
        header_ck = self._extract_ck(response.headers.get("Set-Cookie", ""))
        ck = choose_refreshed_ck("", session_ck, header_ck)
        if ck:
            self.cookies["ck"] = ck
            self.session.cookies.set("ck", ck)
            self.ck = ck
            return True

        self._restore_ck(previous_ck)
        return False

    @staticmethod
    def _response_title(response: requests.Response) -> str:
        text = response.text[:4000] if response.text else ""
        match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def _check_auth_once(self) -> AuthCheckResult:
        try:
            response = self.session.get(
                self.MINE_URL,
                headers={**self.headers, "Host": "www.douban.com"},
                timeout=15,
                allow_redirects=True,
            )
        except Exception as err:
            logger.warning(f"检查豆瓣登录状态失败: {self._safe_message(err)}")
            return AuthCheckResult(
                state=AuthState.TRANSIENT,
                message="连接豆瓣登录状态检查服务失败",
                retryable=True,
            )

        return classify_auth_check(
            status_code=response.status_code,
            final_url=response.url,
            page_title=self._response_title(response),
            page_text=response.text[:2000] if response.text else "",
        )

    def check_auth_status(self, allow_login: bool = True) -> AuthCheckResult:
        result = self._check_auth_once()
        if not allow_login:
            return result

        can_login = self.auto_login and bool(self.username and self.password)
        if not can_login:
            return result

        if result.state == AuthState.RESTRICTED:
            if not self.allow_restricted_login or self.ck:
                return result
            self.restricted_login_attempted = True
            if not self.login():
                return AuthCheckResult(
                    state=AuthState.RESTRICTED,
                    message=(result.message or "豆瓣登录状态检查遇到访问限制") + "；受限状态下自动登录未成功",
                    retryable=True,
                    login_attempted=True,
                )
            self.restricted_login_succeeded = True
            verified = self._check_auth_once()
            self.restricted_login_verified = verified.success
            return AuthCheckResult(
                state=verified.state,
                message=verified.message,
                retryable=verified.retryable,
                login_attempted=True,
            )

        if not result.explicitly_logged_out:
            return result

        if not self.login():
            return AuthCheckResult(
                state=AuthState.LOGGED_OUT,
                message="豆瓣登录状态已失效，自动登录未成功",
                retryable=True,
                login_attempted=True,
            )

        verified = self._check_auth_once()
        return AuthCheckResult(
            state=verified.state,
            message=verified.message,
            retryable=verified.retryable,
            login_attempted=True,
        )

    def login(self) -> bool:
        if not self.username or not self.password:
            return False

        previous_ck = self.ck or self.cookies.get("ck", "")
        try:
            self.session.get(
                self.LOGIN_PAGE,
                headers={**self.headers, "Host": "accounts.douban.com"},
                timeout=15
            )
            response = self.session.post(
                self.LOGIN_API,
                headers={
                    **self.headers,
                    "Host": "accounts.douban.com",
                    "Origin": "https://accounts.douban.com",
                    "Referer": self.LOGIN_PAGE,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
                data={
                    "name": self.username,
                    "username": self.username,
                    "password": self.password,
                    "remember": "true",
                    "ck": "",
                    "ticket": "",
                },
                timeout=15
            )
        except Exception as err:
            logger.error(f"豆瓣账号密码登录请求失败: {self._safe_message(err)}")
            return False

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code == 200 and result.get("status") == "success":
            self._update_cookies_from_session()
            login_ck = self.cookies.get("ck", "")
            if login_ck and login_ck != previous_ck:
                self._restore_ck(login_ck)
                logger.info("豆瓣账号密码登录成功，已获得新ck")
                return True
            if self.set_ck(force_refresh=True):
                logger.info("豆瓣账号密码登录成功，已刷新ck")
                return True
            logger.error("豆瓣账号密码登录成功，但刷新ck失败")
            return False

        message = (
                result.get("message")
                or result.get("msg")
                or result.get("description")
                or f"HTTP {response.status_code}"
        )
        safe_message = self._safe_message(message)
        if any(keyword in safe_message for keyword in ("captcha", "验证码", "安全", "风控")):
            logger.error(f"豆瓣账号密码登录需要人工验证: {safe_message}")
        else:
            logger.error(f"豆瓣账号密码登录失败: {safe_message}")
        return False

    def _ensure_ck_result(self) -> DoubanActionResult:
        if self.ck:
            return DoubanActionResult(success=True)
        if self.set_ck():
            return DoubanActionResult(success=True)

        auth_result = self.check_auth_status(allow_login=True)
        if auth_result.success:
            if self.ck or self.set_ck():
                return DoubanActionResult(success=True)
            return DoubanActionResult(
                success=False,
                kind=FailureKind.TRANSIENT,
                message="豆瓣登录状态有效，但暂时无法刷新CK",
                retryable=True,
            )
        if auth_result.explicitly_logged_out:
            return DoubanActionResult(
                success=False,
                kind=FailureKind.AUTH,
                message=auth_result.message or "豆瓣登录状态无效，无法提交观影状态",
                retryable=True,
            )
        if auth_result.state == AuthState.RESTRICTED:
            return DoubanActionResult(
                success=False,
                kind=FailureKind.RESTRICTED,
                message=auth_result.message or "豆瓣登录状态检查遇到访问限制",
                retryable=True,
            )
        return DoubanActionResult(
            success=False,
            kind=FailureKind.TRANSIENT,
            message=auth_result.message or "暂时无法确认豆瓣登录状态",
            retryable=True,
        )

    def _ensure_ck(self) -> bool:
        return self._ensure_ck_result().success

    def search_subject_candidates(self, title: str) -> SubjectSearchResult:
        """搜索豆瓣条目并返回候选列表，不执行目标选择。"""
        try:
            response = self.session.get(
                self.SEARCH_URL,
                params={"cat": "1002", "q": title},
                headers={**self.headers, "Host": "www.douban.com", "Cookie": self._cookie_header()},
                timeout=15
            )
        except Exception as err:
            logger.error(f"搜索 {title} 失败: {self._safe_message(err)}")
            return SubjectSearchResult(
                kind=FailureKind.TRANSIENT,
                message="连接豆瓣搜索服务失败",
                retryable=True,
            )

        is_login_page = "passport/login" in response.url or self._response_title(response) == "登录豆瓣"
        if response.status_code != 200 or is_login_page:
            status_code = response.status_code
            logger.error(f"搜索 {title} 失败 状态码：{status_code}")
            if status_code == 401 or is_login_page:
                kind = FailureKind.AUTH
                message = "豆瓣登录状态无效，搜索条目失败"
            elif status_code == 403:
                kind = FailureKind.RESTRICTED
                message = "豆瓣搜索请求被 HTTP 403 拒绝，可能触发访问限制"
            else:
                kind = FailureKind.TRANSIENT
                message = f"豆瓣搜索服务返回 HTTP {status_code}"
            return SubjectSearchResult(
                kind=kind,
                message=message,
                retryable=True,
            )

        soup = BeautifulSoup(response.text, "lxml")
        candidates: List[SubjectCandidate] = []
        for div in soup.find_all("div", class_="title"):
            a_tags = div.find_all("a")
            if not a_tags:
                continue
            subject_title = a_tags[0].get_text(strip=True)
            link = unquote(a_tags[0].get("href", ""))
            match = re.search(r"subject/(\d+)/", link)
            if not subject_title or not match:
                continue

            result_node = div.find_parent("div", class_="result") or div.parent
            result_text = result_node.get_text(" ", strip=True) if result_node else div.get_text(" ", strip=True)
            year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", result_text)
            type_match = re.search(r"[\[【]([^\]】]+)[\]】]", div.get_text(" ", strip=True))
            candidates.append(SubjectCandidate(
                subject_id=match.group(1),
                title=subject_title,
                year=int(year_match.group(1)) if year_match else None,
                media_type=type_match.group(1).strip() if type_match else None,
                season=extract_season(subject_title),
            ))

        if not candidates:
            logger.warning(f"找不到 {title} 相关条目，本条目不存在于豆瓣")
        return SubjectSearchResult(candidates=tuple(candidates))

    def resolve_subject(
            self,
            title: str,
            year: Optional[int] = None,
            media_type: Optional[str] = None,
            season: Optional[int] = None,
            release_date=None,
    ) -> SubjectResolveResult:
        """搜索并选择唯一高置信豆瓣条目。"""
        search_title = strip_title_year_suffix(title, year)
        if search_title != title:
            logger.info(f"豆瓣搜索使用去除年份后的标题: {search_title}")
        search_result = self.search_subject_candidates(search_title)
        if not search_result.success and search_result.kind != FailureKind.NONE:
            return SubjectResolveResult(
                candidate=None,
                kind=search_result.kind,
                message=search_result.message,
                retryable=search_result.retryable,
            )
        strict_result = select_subject_candidate(
            title, search_result.candidates, year, media_type, season, release_date
        )
        expected_release_date = normalize_release_date(release_date)
        if (
                strict_result.kind != FailureKind.NO_MATCH
                or normalize_media_type(media_type) != "movie"
                or not expected_release_date
                or not year
        ):
            return strict_result

        expected_title = normalize_title(title)
        mismatched = [
            candidate for candidate in search_result.candidates
            if normalize_title(candidate.title) == expected_title
            and normalize_media_type(candidate.media_type) == "movie"
            and candidate.year
            and int(candidate.year) != int(year)
        ]
        if not mismatched:
            return strict_result

        enriched = []
        detail_failure = None
        for candidate in mismatched:
            detail_result = self.get_subject_release_date(candidate.subject_id)
            if not detail_result.success:
                detail_failure = detail_result
                continue
            enriched.append(replace(
                candidate,
                release_date=detail_result.release_date,
                source="search_release_date" if detail_result.release_date else candidate.source,
            ))

        resolved = select_subject_candidate(
            title, enriched, year, media_type, season, expected_release_date
        )
        if resolved.success or resolved.kind == FailureKind.AMBIGUOUS:
            return resolved
        if detail_failure:
            return SubjectResolveResult(
                candidate=None,
                kind=detail_failure.kind,
                message=detail_failure.message,
                retryable=detail_failure.retryable,
            )
        return strict_result

    def get_subject_release_date(self, subject_id: str) -> SubjectReleaseResult:
        try:
            response = self.session.get(
                self.SUBJECT_URL.format(subject_id=subject_id),
                headers={**self.headers, "Host": "movie.douban.com", "Cookie": self._cookie_header()},
                timeout=15,
            )
        except Exception as err:
            logger.warning(f"读取豆瓣条目上映日期失败: {self._safe_message(err)}")
            return SubjectReleaseResult(
                kind=FailureKind.TRANSIENT,
                message="连接豆瓣条目详情服务失败",
                retryable=True,
            )

        if response.status_code == 403:
            return SubjectReleaseResult(
                kind=FailureKind.RESTRICTED,
                message="豆瓣限制了条目上映日期查询（HTTP 403）",
                retryable=True,
            )
        if response.status_code == 429 or response.status_code >= 500:
            return SubjectReleaseResult(
                kind=FailureKind.TRANSIENT,
                message=f"豆瓣条目详情暂时不可用（HTTP {response.status_code}）",
                retryable=True,
            )
        if response.status_code != 200:
            return SubjectReleaseResult()

        values = extract_initial_release_dates(response.text)
        return SubjectReleaseResult(release_date=preferred_initial_release_date(values))

    def get_subject_id(self, title: str = None, meta: MetaBase = None) -> Tuple | None:
        if not title:
            title = meta.title
        result = self.resolve_subject(
            title=title,
            year=getattr(meta, "year", None) if meta else None,
            media_type=str(getattr(meta, "type", "")) if meta else None,
            season=getattr(meta, "begin_season", None) if meta else None,
            release_date=getattr(meta, "release_date", None) if meta else None,
        )
        if result.candidate:
            return result.candidate.title, result.candidate.subject_id
        return None, None

    def set_watching_status_result(
            self,
            subject_id: str,
            status: str = "do",
            private: bool = True,
    ) -> DoubanActionResult:
        for retry in range(2):
            ck_result = self._ensure_ck_result()
            if not ck_result.success:
                return ck_result

            try:
                response = self.session.post(
                    url=self.INTEREST_URL.format(subject_id=subject_id),
                    headers={
                        **self.headers,
                        "Referer": f"https://movie.douban.com/subject/{subject_id}/",
                        "Origin": "https://movie.douban.com",
                        "Host": "movie.douban.com",
                        "Cookie": self._cookie_header(),
                    },
                    data={
                        "ck": self.ck,
                        "interest": status,
                        "rating": "",
                        "foldcollect": "U",
                        "tags": "",
                        "comment": "",
                        **({"private": "on"} if private else {}),
                    },
                    timeout=15
                )
            except Exception as err:
                logger.error(f"提交豆瓣观影状态失败: {self._safe_message(err)}")
                return DoubanActionResult(
                    success=False,
                    kind=FailureKind.TRANSIENT,
                    message="连接豆瓣标记服务失败",
                    retryable=True,
                )

            try:
                result = response.json()
            except Exception:
                result = {}

            raw_message = str(
                result.get("message")
                or result.get("msg")
                or result.get("description")
                or ""
            )
            safe_message = self._safe_message(raw_message) if raw_message else ""
            auth_failed = self._looks_like_auth_failed(response, result)
            action_result = classify_action_response(
                status_code=response.status_code,
                payload=result,
                auth_failed=auth_failed,
                message=safe_message,
            )
            if action_result.success:
                self._update_cookies_from_session()
                return action_result
            if retry == 0 and self.auto_login and action_result.kind == FailureKind.AUTH and self.login():
                continue

            if action_result.kind == FailureKind.NOT_ALLOWED:
                logger.error(f"douban_id: {subject_id} 未开播或不允许标记")
            else:
                logger.error(action_result.message or f"提交豆瓣观影状态失败 HTTP {response.status_code}")
            return action_result

        return DoubanActionResult(
            success=False,
            kind=FailureKind.AUTH,
            message="豆瓣自动登录重试后仍无法提交观影状态",
            retryable=True,
        )

    def set_watching_status(self, subject_id: str, status: str = "do", private: bool = True) -> bool:
        return self.set_watching_status_result(subject_id, status, private).success


if __name__ == "__main__":
    doubanApi = DoubanApi()
    subject_title, subject_id = doubanApi.get_subject_id("太阳的后裔")
