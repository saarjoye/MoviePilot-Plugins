from __future__ import annotations

from typing import Any, Dict, List

import requests


class PinglianClient:
    BASE_URL = "https://pinglian.lol"
    SEARCH_API = f"{BASE_URL}/api/search.php"
    LOGIN_API = f"{BASE_URL}/api/login.php"
    DETAIL_API = f"{BASE_URL}/api/search_pan_links.php"
    DETAIL_PAGE = f"{BASE_URL}/pages/video.php"

    _GROUP_ORDER = {
        "115": 0,
        "quark": 1,
        "aliyun": 2,
        "tianyi": 3,
        "pikpak": 4,
        "123": 5,
        "others": 99,
    }

    def __init__(self, username: str = "", password: str = "", timeout: int = 20):
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout or 20
        self._logged_in = False
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (MoviePilot Panlink115 Plugin)",
                "Accept": "application/json, text/plain, */*",
            }
        )

    def update_credentials(self, username: str = "", password: str = "", timeout: int = 20) -> None:
        creds_changed = username != self.username or password != self.password
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout or 20
        if creds_changed:
            self._logged_in = False
            self._session.cookies.clear()

    def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        payload = self._get_json(self.SEARCH_API, params={"q": keyword})
        if not payload.get("success"):
            raise RuntimeError(payload.get("message") or "盘链搜索失败")

        results = []
        for item in payload.get("results") or []:
            vod_id = str(item.get("vod_id") or "").strip()
            vod_name = str(item.get("vod_name") or "").strip()
            if not vod_id or not vod_name:
                continue

            results.append(
                {
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "type_name": str(item.get("type_name") or "").strip(),
                    "vod_year": str(item.get("vod_year") or "").strip(),
                    "vod_area": str(item.get("vod_area") or "").strip(),
                    "vod_lang": str(item.get("vod_lang") or "").strip(),
                    "vod_remarks": str(item.get("vod_remarks") or "").strip(),
                    "vod_pic": str(item.get("vod_pic") or "").strip(),
                }
            )

        return results[: max(limit, 1)]

    def search_pan_links(self, keyword: str, vod_id: str) -> Dict[str, List[Dict[str, Any]]]:
        keyword = (keyword or "").strip()
        vod_id = str(vod_id or "").strip()
        if not keyword or not vod_id:
            return {}

        self._login_if_needed()
        payload = self._fetch_pan_links(keyword=keyword, vod_id=vod_id)
        if not payload.get("success"):
            self._logged_in = False
            self._login_if_needed()
            payload = self._fetch_pan_links(keyword=keyword, vod_id=vod_id)
        if not payload.get("success"):
            message = payload.get("message") or "盘链资源查询失败"
            self._logged_in = False
            raise RuntimeError(message)

        return self._normalize_pan_links(payload.get("data") or {})

    def _fetch_pan_links(self, keyword: str, vod_id: str) -> Dict[str, Any]:
        return self._get_json(
            self.DETAIL_API,
            params={"keyword": keyword, "vod_id": vod_id},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.DETAIL_PAGE}?id={vod_id}",
            },
        )

    def _login_if_needed(self) -> None:
        if self._logged_in:
            return
        if not self.username or not self.password:
            raise RuntimeError("请先在插件配置中填写盘链账号和密码。")

        payload = self._post_json(
            self.LOGIN_API,
            data={
                "username": self.username,
                "password": self.password,
                "remember": "on",
            },
        )
        if not payload.get("success"):
            raise RuntimeError(payload.get("message") or "盘链登录失败")

        self._logged_in = True

    def _get_json(
        self,
        url: str,
        params: Dict[str, Any] | None = None,
        headers: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        response = self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._decode_json(response)

    def _post_json(
        self,
        url: str,
        data: Dict[str, Any] | None = None,
        headers: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        response = self._session.post(
            url,
            data=data,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._decode_json(response)

    @staticmethod
    def _decode_json(response: requests.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as err:
            raise RuntimeError("盘链返回的不是合法 JSON。") from err

        if not isinstance(payload, dict):
            raise RuntimeError("盘链接口返回结构异常。")
        return payload

    def _normalize_pan_links(self, raw_groups: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for group_name, entries in raw_groups.items():
            if not isinstance(entries, list):
                continue

            normalized_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                url = str(entry.get("url") or "").strip()
                if not url:
                    continue

                normalized_entries.append(
                    {
                        "title": str(entry.get("title") or "未命名资源").strip(),
                        "url": url,
                        "password": str(entry.get("password") or "").strip(),
                        "type": str(entry.get("type") or group_name).strip(),
                        "time": str(entry.get("time") or "").strip(),
                        "source": str(entry.get("source") or "").strip(),
                    }
                )

            if normalized_entries:
                groups[group_name] = normalized_entries

        sorted_items = sorted(
            groups.items(),
            key=lambda item: (self._GROUP_ORDER.get(item[0], 50), item[0].lower()),
        )
        return dict(sorted_items)
