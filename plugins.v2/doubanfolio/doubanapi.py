import re
from http.cookies import CookieError, SimpleCookie
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.meta import MetaBase
from app.helper.cookiecloud import CookieCloudHelper
from app.log import logger


class DoubanApi:
    HOME_URL = "https://www.douban.com/"
    LOGIN_PAGE = "https://accounts.douban.com/passport/login"
    LOGIN_API = "https://accounts.douban.com/j/mobile/login/basic"
    SEARCH_URL = "https://www.douban.com/search"
    INTEREST_URL = "https://movie.douban.com/j/subject/{subject_id}/interest"

    def __init__(
            self,
            user_cookie: str = None,
            username: str = None,
            password: str = None,
            auto_login: bool = True
    ):
        self.username = (username or "").strip()
        self.password = password or ""
        self.auto_login = bool(auto_login)
        self.session = requests.Session()
        self.cookies: Dict[str, str] = self._load_cookies(user_cookie)
        self.ck: str = ""

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

        self.set_ck()
        if not self.ck and self.auto_login:
            self.login()

        if not self.ck:
            logger.error("请求ck失败，请检查cookie登录状态或豆瓣账号密码配置")

    def _load_cookies(self, user_cookie: str = None) -> Dict[str, str]:
        if user_cookie:
            return self._parse_cookie_string(user_cookie)

        cookie_dict, msg = CookieCloudHelper().download()
        if cookie_dict is None:
            logger.error(f"获取cookiecloud数据错误 {msg}")
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
        if response.status_code in (401, 403):
            return True
        text = response.text[:1000] if response.text else ""
        if "passport/login" in response.url or "登录豆瓣" in text:
            return True
        if payload:
            message = str(payload.get("message") or payload.get("msg") or payload.get("description") or "")
            if any(keyword in message for keyword in ("登录", "ck", "cookie", "captcha", "验证码")):
                return True
        return False

    def set_ck(self) -> bool:
        self._remove_cookie("ck")
        try:
            response = self.session.get(
                self.HOME_URL,
                headers={**self.headers, "Host": "www.douban.com"},
                timeout=15,
                allow_redirects=True
            )
        except Exception as err:
            logger.error(f"请求豆瓣首页刷新ck失败: {err}")
            self.ck = ""
            return False

        self._update_cookies_from_session()
        ck = self.cookies.get("ck") or self._extract_ck(response.headers.get("Set-Cookie", ""))
        if ck and ck != '"deleted"':
            self.cookies["ck"] = ck
            self.session.cookies.set("ck", ck)
            self.ck = ck
            return True

        self.ck = ""
        return False

    def login(self) -> bool:
        if not self.username or not self.password:
            return False

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
            logger.error(f"豆瓣账号密码登录请求失败: {err}")
            return False

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code == 200 and result.get("status") == "success":
            self._update_cookies_from_session()
            if self.set_ck():
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

    def _ensure_ck(self) -> bool:
        if self.ck:
            return True
        if self.set_ck():
            return True
        return self.auto_login and self.login()

    def get_subject_id(self, title: str = None, meta: MetaBase = None) -> Tuple | None:
        if not title:
            title = meta.title

        response = None
        for retry in range(2):
            try:
                response = self.session.get(
                    self.SEARCH_URL,
                    params={"cat": "1002", "q": title},
                    headers={**self.headers, "Host": "www.douban.com", "Cookie": self._cookie_header()},
                    timeout=15
                )
            except Exception as err:
                if title == "肖申克的救赎":
                    return None, None
                logger.error(f"搜索 {title} 失败: {err}")
                return None, None

            if response.status_code == 200 or retry > 0 or not self.auto_login:
                break
            if self._looks_like_auth_failed(response) and self.login():
                continue
            break

        if not response or response.status_code != 200:
            if title == "肖申克的救赎":
                return None, None
            status_code = response.status_code if response else "无响应"
            logger.error(f"搜索 {title} 失败 状态码：{status_code}")
            return None, None

        soup = BeautifulSoup(response.text, "lxml")
        title_divs = soup.find_all("div", class_="title")
        subject_items: List = []
        for div in title_divs:
            a_tags = div.find_all("a")
            if not a_tags:
                continue
            item = {}
            item["title"] = (a_tags[0].string or "").strip()
            link = unquote(a_tags[0]["href"])
            if link.count("subject/"):
                match = re.search(r"subject/(\d+)/", link)
                if match:
                    item["subject_id"] = match.group(1)
            if item.get("title") and item.get("subject_id"):
                subject_items.append(item)

        if not subject_items:
            if title == "肖申克的救赎":
                return None, None
            logger.warn(f"找不到 {title} 相关条目，本条目不存在于豆瓣")
            return None, None

        for subject_item in subject_items:
            return subject_item["title"], subject_item["subject_id"]
        return None, None

    def set_watching_status(self, subject_id: str, status: str = "do", private: bool = True) -> bool:
        for retry in range(2):
            if not self._ensure_ck():
                return False

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
                logger.error(f"提交豆瓣观影状态失败: {err}")
                return False

            try:
                result = response.json()
            except Exception:
                result = {}

            if response.status_code == 200:
                ret = result.get("r")
                if not (isinstance(ret, bool) and ret is False):
                    self._update_cookies_from_session()
                    return True
                if not self._looks_like_auth_failed(response, result):
                    logger.error(f"douban_id: {subject_id} 未开播或不允许标记")
                    return False

            if retry == 0 and self.auto_login and self._looks_like_auth_failed(response, result) and self.login():
                continue

            logger.error(self._safe_message(response.text))
            return False

        return False


if __name__ == "__main__":
    doubanApi = DoubanApi()
    subject_title, subject_id = doubanApi.get_subject_id("太阳的后裔")
