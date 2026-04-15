from __future__ import annotations

import html
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote, urljoin

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


class CloudDrive2Client:
    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        timeout: int = 20,
        detect_delay: float = 1.2,
    ):
        self.base_url = self._normalize_base_url(base_url)
        self.token = (token or "").strip()
        self.timeout = timeout or 20
        self.detect_delay = max(float(detect_delay or 1.2), 0.2)
        self._session = requests.Session()

    def update_config(
        self,
        base_url: str = "",
        token: str = "",
        timeout: int = 20,
        detect_delay: float = 1.2,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.token = (token or "").strip()
        self.timeout = timeout or 20
        self.detect_delay = max(float(detect_delay or 1.2), 0.2)

    def add_offline_file(self, url: str, target_path: str) -> Dict[str, str]:
        link = (url or "").strip()
        target = self.normalize_path(target_path)
        if not link:
            raise RuntimeError("缺少 CD2 需要提交的 115 链接")
        if not target:
            raise RuntimeError("缺少 CD2 目标目录")

        before_paths = {item.get("full_path"): item for item in self.list_subfiles(target)}
        payload = self._wrap_request(
            [
                self._encode_string_field(1, link),
                self._encode_string_field(2, target),
            ]
        )
        self._post_grpc("AddOfflineFiles", payload)

        created_item: Dict[str, str] = {}
        for _ in range(4):
            time.sleep(self.detect_delay)
            after_items = self.list_subfiles(target)
            new_items = [
                item
                for item in after_items
                if item.get("full_path") and item.get("full_path") not in before_paths
            ]
            if new_items:
                created_item = new_items[0]
                break

        return {
            "target_path": target,
            "created_name": str(created_item.get("name") or "").strip(),
            "created_path": str(created_item.get("full_path") or "").strip(),
        }

    def list_subfiles(self, path: str) -> List[Dict[str, str]]:
        target = self.normalize_path(path)
        payload = self._wrap_request([self._encode_string_field(1, target)])
        body = self._post_grpc("GetSubFiles", payload)
        items: List[Dict[str, str]] = []
        for frame in self._iter_grpc_frames(body):
            for field_number, wire_type, value in self._iter_message_fields(frame):
                if field_number != 1 or wire_type != 2:
                    continue
                item = self._parse_subfile(value)
                if item:
                    items.append(item)
        return items

    def _post_grpc(self, method: str, body: bytes) -> bytes:
        if not self.base_url:
            raise RuntimeError("请先在插件配置中填写 CD2 地址")
        if not self.token:
            raise RuntimeError("请先在插件配置中填写 CD2 API Token")

        response = self._session.post(
            f"{self.base_url}/clouddrive.CloudDriveFileSrv/{method}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "accept": "application/grpc-web+proto",
                "content-type": "application/grpc-web+proto",
                "x-grpc-web": "1",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        grpc_status = str(response.headers.get("Grpc-Status") or "").strip()
        grpc_message = unquote(str(response.headers.get("Grpc-Message") or "").strip())
        if grpc_status and grpc_status != "0":
            raise RuntimeError(grpc_message or f"CD2 调用失败（grpc-status={grpc_status}）")
        return bytes(response.content or b"")

    @staticmethod
    def _wrap_request(parts: Iterable[bytes]) -> bytes:
        payload = b"".join(parts)
        return b"\x00" + len(payload).to_bytes(4, "big") + payload

    @staticmethod
    def _encode_string_field(field_number: int, value: str) -> bytes:
        text = (value or "").strip()
        encoded = text.encode("utf-8")
        return CloudDrive2Client._encode_tag(field_number, 2) + CloudDrive2Client._encode_varint(len(encoded)) + encoded

    @staticmethod
    def _encode_tag(field_number: int, wire_type: int) -> bytes:
        return CloudDrive2Client._encode_varint((field_number << 3) | wire_type)

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        number = int(value or 0)
        chunks = bytearray()
        while True:
            current = number & 0x7F
            number >>= 7
            if number:
                chunks.append(current | 0x80)
            else:
                chunks.append(current)
                break
        return bytes(chunks)

    @staticmethod
    def _iter_grpc_frames(body: bytes) -> Iterable[bytes]:
        data = body or b""
        cursor = 0
        length = len(data)
        while cursor + 5 <= length:
            flag = data[cursor]
            frame_len = int.from_bytes(data[cursor + 1 : cursor + 5], "big")
            cursor += 5
            frame = data[cursor : cursor + frame_len]
            cursor += frame_len
            # grpc-web trailers use 0x80; only message frames matter here.
            if flag == 0x80:
                break
            yield frame

    @staticmethod
    def _iter_message_fields(payload: bytes) -> Iterable[Tuple[int, int, Any]]:
        cursor = 0
        length = len(payload or b"")
        while cursor < length:
            tag, cursor = CloudDrive2Client._read_varint(payload, cursor)
            field_number = tag >> 3
            wire_type = tag & 0x07
            if wire_type == 0:
                value, cursor = CloudDrive2Client._read_varint(payload, cursor)
                yield field_number, wire_type, value
                continue
            if wire_type == 2:
                item_length, cursor = CloudDrive2Client._read_varint(payload, cursor)
                value = payload[cursor : cursor + item_length]
                cursor += item_length
                yield field_number, wire_type, value
                continue
            if wire_type == 5:
                value = payload[cursor : cursor + 4]
                cursor += 4
                yield field_number, wire_type, value
                continue
            if wire_type == 1:
                value = payload[cursor : cursor + 8]
                cursor += 8
                yield field_number, wire_type, value
                continue
            raise RuntimeError(f"CD2 protobuf 解析失败，暂不支持 wire_type={wire_type}")

    @staticmethod
    def _read_varint(payload: bytes, cursor: int) -> Tuple[int, int]:
        shift = 0
        result = 0
        while cursor < len(payload):
            current = payload[cursor]
            cursor += 1
            result |= (current & 0x7F) << shift
            if not current & 0x80:
                return result, cursor
            shift += 7
        raise RuntimeError("CD2 protobuf 数据不完整，无法继续解析")

    @staticmethod
    def _parse_subfile(payload: bytes) -> Optional[Dict[str, str]]:
        name = ""
        full_path = ""
        for field_number, wire_type, value in CloudDrive2Client._iter_message_fields(payload):
            if wire_type != 2:
                continue
            if field_number == 2:
                name = value.decode("utf-8", errors="ignore").strip()
            elif field_number == 3:
                full_path = value.decode("utf-8", errors="ignore").strip()
        if not name and not full_path:
            return None
        return {
            "name": name,
            "full_path": full_path,
        }

    @staticmethod
    def normalize_path(path: str) -> str:
        text = str(path or "").strip().replace("\\", "/")
        if not text:
            return ""
        parts = [segment for segment in text.split("/") if segment]
        normalized = "/" + "/".join(parts)
        return normalized or "/"

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        return str(url or "").strip().rstrip("/")

    @staticmethod
    def append_share_password(url: str, password: str) -> str:
        link = (url or "").strip()
        secret = (password or "").strip()
        if not link or not secret or "password=" in link:
            return link
        joiner = "&" if "?" in link else "?"
        return f"{link}{joiner}password={quote(secret)}"
