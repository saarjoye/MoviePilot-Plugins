from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


class Direct115Client:
    RECEIVE_API = "https://webapi.115.com/share/receive"

    def __init__(self, cookie: str = "", timeout: int = 20):
        self.cookie = ""
        self.timeout = timeout or 20
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (MoviePilot Panlink115 Direct115)",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://115.com",
            }
        )
        self.update_config(cookie=cookie, timeout=timeout)

    def update_config(self, cookie: str = "", timeout: int = 20) -> None:
        self.cookie = str(cookie or "").strip()
        self.timeout = timeout or 20

    def describe_auth(self) -> Dict[str, Any]:
        return {
            "mode": "direct_115",
            "label": "115 网页 Cookie",
            "configured": bool(self.cookie),
            "has_cookie": bool(self.cookie),
        }

    def receive_share(self, url: str, target_cid: str, password: str = "") -> Dict[str, Any]:
        share_url, receive_code = self.normalize_share_link(url=url, password=password)
        share_code = self.extract_share_code(share_url)
        cid = str(target_cid or "").strip()
        if not share_code:
            raise RuntimeError("无法从 115 分享链接中解析出 share_code")
        if not cid:
            raise RuntimeError("缺少 115 目标目录 cid")
        if not self.cookie:
            raise RuntimeError("请先在插件配置中填写 115 网页 Cookie")

        response = self._session.post(
            self.RECEIVE_API,
            data={
                "share_code": share_code,
                "receive_code": receive_code,
                "cid": cid,
                "is_check": "0",
            },
            headers={
                "Cookie": self.cookie,
                "Referer": self.append_share_password(share_url, receive_code) or share_url,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = self._decode_json(response)

        if payload.get("state") is True:
            return {
                "target_cid": cid,
                "share_code": share_code,
                "already_exists": False,
                "raw": payload,
            }

        message = self._extract_error_message(payload)
        lowered = message.lower()
        if "already" in lowered or "存在" in message:
            return {
                "target_cid": cid,
                "share_code": share_code,
                "already_exists": True,
                "raw": payload,
            }
        raise RuntimeError(message or "115 分享转存失败")

    @staticmethod
    def _decode_json(response: requests.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as err:
            raise RuntimeError("115 接口返回的不是有效 JSON") from err
        if not isinstance(payload, dict):
            raise RuntimeError("115 接口返回结构异常")
        return payload

    @staticmethod
    def _extract_error_message(payload: Dict[str, Any]) -> str:
        for key in ("error", "message", "msg"):
            text = str(payload.get(key) or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def extract_share_code(url: str) -> str:
        path = urlsplit(str(url or "").strip()).path
        matched = re.search(r"/s/([A-Za-z0-9]+)", path)
        if matched:
            return matched.group(1)
        return ""

    @staticmethod
    def normalize_share_link(url: str, password: str = "") -> Tuple[str, str]:
        link = (url or "").strip()
        secret = (password or "").strip()
        if not link:
            return "", secret

        parts = urlsplit(link)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        filtered_items = []
        for key, value in query_items:
            if key == "password":
                if not secret and value:
                    secret = value.strip()
                continue
            filtered_items.append((key, value))

        normalized_url = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(filtered_items, doseq=True),
                parts.fragment,
            )
        )
        return normalized_url or link, secret

    @staticmethod
    def append_share_password(url: str, password: str) -> str:
        link = str(url or "").strip()
        secret = str(password or "").strip()
        if not link or not secret:
            return link
        parts = urlsplit(link)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        filtered_items = [(key, value) for key, value in query_items if key != "password"]
        filtered_items.append(("password", secret))
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(filtered_items, doseq=True),
                parts.fragment,
            )
        )
