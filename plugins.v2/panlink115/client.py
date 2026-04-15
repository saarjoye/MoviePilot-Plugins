from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

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
            normalized = self._normalize_search_item(item)
            if normalized:
                results.append(normalized)

        return results[: max(limit, 1)]

    def get_video_detail(
        self,
        vod_id: str,
        fallback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        vod_id = str(vod_id or "").strip()
        if not vod_id:
            return {}

        self._login_if_needed()
        page_html = self._get_text(f"{self.DETAIL_PAGE}?id={vod_id}")

        detail = dict(fallback or {})
        detail["vod_id"] = vod_id
        detail["detail_url"] = f"{self.DETAIL_PAGE}?id={vod_id}"
        detail["vod_name"] = self._extract_first(
            page_html,
            r'<h1 class="premium-title">(.*?)</h1>',
        ) or str(detail.get("vod_name") or "").strip()
        detail["vod_pic"] = self._extract_image(page_html) or str(detail.get("vod_pic") or "").strip()
        detail["type_name"] = self._extract_tag_text(page_html, "type") or str(detail.get("type_name") or "").strip()
        detail["vod_year"] = self._extract_tag_text(page_html, "year") or str(detail.get("vod_year") or "").strip()
        detail["vod_area"] = self._extract_tag_text(page_html, "area") or str(detail.get("vod_area") or "").strip()
        detail["vod_remarks"] = self._extract_tag_text(page_html, "quality") or str(detail.get("vod_remarks") or "").strip()
        detail["vod_alias"] = self._extract_meta_value(page_html, "别名")
        detail["vod_director"] = self._extract_meta_value(page_html, "导演")
        detail["vod_actor"] = self._extract_meta_value(page_html, "主演")
        detail["vod_lang"] = self._extract_meta_value(page_html, "语言") or str(detail.get("vod_lang") or "").strip()
        detail["vod_update_time"] = self._extract_meta_value(page_html, "更新时间")
        detail["vod_content"] = self._extract_plot(page_html)
        return detail

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
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        response = self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._decode_json(response)

    def _get_text(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        response = self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def _post_json(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
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

    def _normalize_search_item(self, item: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None

        vod_id = str(item.get("vod_id") or "").strip()
        vod_name = str(item.get("vod_name") or "").strip()
        if not vod_id or not vod_name:
            return None

        return {
            "vod_id": vod_id,
            "vod_name": vod_name,
            "type_name": str(item.get("type_name") or "").strip(),
            "vod_year": str(item.get("vod_year") or "").strip(),
            "vod_area": str(item.get("vod_area") or "").strip(),
            "vod_lang": str(item.get("vod_lang") or "").strip(),
            "vod_remarks": str(item.get("vod_remarks") or "").strip(),
            "vod_pic": str(item.get("vod_pic") or "").strip(),
            "detail_url": f"{self.DETAIL_PAGE}?id={vod_id}",
        }

    def _normalize_pan_links(self, raw_groups: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for group_name, group_payload in raw_groups.items():
            group_label = str(group_name or "").strip() or "others"
            group_icon = ""
            entries = group_payload
            if isinstance(group_payload, dict):
                group_label = str(group_payload.get("name") or group_name).strip() or group_label
                group_icon = str(group_payload.get("icon") or "").strip()
                entries = group_payload.get("links")

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
                        "group_label": group_label,
                        "group_icon": group_icon,
                    }
                )

            if normalized_entries:
                groups[group_name] = normalized_entries

        sorted_items = sorted(
            groups.items(),
            key=lambda item: (self._GROUP_ORDER.get(item[0], 50), item[0].lower()),
        )
        return dict(sorted_items)

    def _extract_image(self, page_html: str) -> str:
        image = self._extract_first(
            page_html,
            r'<div class="detail-poster premium-poster">\s*<img src="([^"]+)"',
        )
        if not image:
            return ""
        return urljoin(self.BASE_URL, image)

    def _extract_tag_text(self, page_html: str, tag_name: str) -> str:
        return self._extract_first(
            page_html,
            rf'<span class="p-tag {re.escape(tag_name)}">(.*?)</span>',
        )

    def _extract_meta_value(self, page_html: str, label: str) -> str:
        return self._extract_first(
            page_html,
            rf'<span class="m-label">{re.escape(label)}</span>\s*<span class="m-val">(.*?)</span>',
        )

    def _extract_plot(self, page_html: str) -> str:
        return self._extract_first(
            page_html,
            r'<div class="premium-plot">.*?<p>(.*?)</p>',
            flags=re.S,
        )

    def _extract_first(self, text: str, pattern: str, flags: int = 0) -> str:
        matched = re.search(pattern, text, flags)
        if not matched:
            return ""
        return self._clean_html_text(matched.group(1))

    @staticmethod
    def _clean_html_text(value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = html.unescape(text)
        text = text.replace("\xa0", " ").replace("\u3000", " ")
        return re.sub(r"\s+", " ", text).strip()
