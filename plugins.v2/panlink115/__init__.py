from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase

from .client import PinglianClient


_PLUGIN_STATE: Dict[str, Any] = {
    "queued_115": [],
    "last_message": "尚未开始搜索。",
    "last_keyword": "",
    "search_results": [],
    "selected_media": None,
    "link_groups": {},
}


class Panlink115(_PluginBase):
    plugin_name = "盘链 115 搜索"
    plugin_desc = "手动搜索盘链影视资源，按详情页展示 115 网盘资源，并预留下载到 115 的接口。"
    plugin_icon = "https://115.com/favicon.ico"
    plugin_color = "#2F77FF"
    plugin_version = "0.3.0"
    plugin_author = "wYw"
    author_url = "https://github.com/saarjoye/MoviePilot-Plugins"
    plugin_config_prefix = "panlink115_"
    plugin_order = 66
    auth_level = 2

    _enabled: bool = False
    _username: str = ""
    _password: str = ""
    _timeout: int = 20
    _max_results: int = 10
    _only_show_115: bool = True
    _client: Optional[PinglianClient] = None
    _queued_115: List[Dict[str, Any]] = []
    _last_message: str = "尚未开始搜索。"
    _last_keyword: str = ""
    _search_results: List[Dict[str, Any]] = []
    _selected_media: Optional[Dict[str, Any]] = None
    _link_groups: Dict[str, List[Dict[str, Any]]] = {}

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._username = str(config.get("username") or "").strip()
        self._password = str(config.get("password") or "").strip()
        self._timeout = self._to_int(config.get("timeout"), default=20, minimum=5)
        self._max_results = self._to_int(config.get("max_results"), default=10, minimum=1)
        self._only_show_115 = bool(config.get("only_show_115", True))
        self._restore_state()
        self._client = self._build_client()
        logger.info("Panlink115 plugin initialized")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/state",
                "endpoint": self.api_state,
                "methods": ["GET"],
                "summary": "读取插件状态",
                "auth": "bear",
            },
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["GET"],
                "summary": "盘链搜索",
                "auth": "bear",
            },
            {
                "path": "/load_links",
                "endpoint": self.api_load_links,
                "methods": ["GET"],
                "summary": "加载资源详情与链接",
                "auth": "bear",
            },
            {
                "path": "/queue_115",
                "endpoint": self.api_queue_115,
                "methods": ["GET"],
                "summary": "加入 115 下载任务队列",
                "auth": "bear",
            },
            {
                "path": "/clear_queue",
                "endpoint": self.api_clear_queue,
                "methods": ["GET"],
                "summary": "清空下载任务队列",
                "auth": "bear",
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "only_show_115", "label": "仅展示 115 资源"},
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "username",
                                            "label": "盘链账号",
                                            "placeholder": "填写盘链用户名",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "password",
                                            "label": "盘链密码",
                                            "type": "password",
                                            "placeholder": "填写盘链密码",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "timeout",
                                            "label": "请求超时秒数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_results",
                                            "label": "搜索结果数量",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "当前版本已切换为详情页式搜索界面，支持展示盘链详情、115 资源弹层与 MP 分类下载任务占位接口；真实 115 自动转存和 MP 整理链路仍待下一阶段接入。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "username": "",
            "password": "",
            "timeout": 20,
            "max_results": 10,
            "only_show_115": True,
        }

    def get_page(self) -> List[dict]:
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "当前插件详情页使用 Vue 远程组件渲染。如果看到此提示，说明 MoviePilot 前端版本较旧或前端构建文件未完整安装。",
                },
            }
        ]

    def api_state(self) -> Dict[str, Any]:
        return {
            "success": True,
            "message": self._last_message,
            "queue": list(self._queued_115),
            "enabled": self._enabled,
            "only_show_115": self._only_show_115,
            "max_results": self._max_results,
            "keyword": self._last_keyword,
            "results": list(self._search_results),
            "selected_media": dict(self._selected_media or {}),
            "link_groups": dict(self._link_groups),
        }

    def api_search(self, keyword: str = "") -> Dict[str, Any]:
        keyword = (keyword or "").strip()
        if not keyword:
            self._last_message = "请输入影视名称后再搜索。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "results": []}

        try:
            logger.info("Panlink115 search requested: %s", keyword)
            client = self._build_client()
            results = client.search(keyword=keyword, limit=self._max_results)
            self._last_keyword = keyword
            self._search_results = results
            self._selected_media = results[0] if results else None
            self._link_groups = {}
            self._last_message = f"搜索完成：关键词“{keyword}”，命中 {len(results)} 条结果。"
            self._persist_state()
            return {
                "success": True,
                "message": self._last_message,
                "keyword": self._last_keyword,
                "results": results,
                "selected_media": dict(self._selected_media or {}),
                "link_groups": {},
            }
        except Exception as err:
            logger.error("Panlink115 search failed: %s", err)
            self._last_message = f"搜索失败：{err}"
            self._persist_state()
            return {"success": False, "message": self._last_message, "results": []}

    def api_load_links(self, vod_id: str = "", keyword: str = "") -> Dict[str, Any]:
        keyword = (keyword or "").strip()
        vod_id = str(vod_id or "").strip()
        if not keyword or not vod_id:
            self._last_message = "缺少资源详情参数，无法加载盘链接。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "detail": {}, "links": {}}

        try:
            logger.info("Panlink115 load links requested: keyword=%s vod_id=%s", keyword, vod_id)
            client = self._build_client()
            basic_item = next(
                (item for item in self._search_results if str(item.get("vod_id")) == vod_id),
                {"vod_id": vod_id, "vod_name": keyword},
            )
            detail = client.get_video_detail(vod_id=vod_id, fallback=basic_item)
            links = client.search_pan_links(keyword=keyword, vod_id=vod_id)
            if self._only_show_115:
                links = {"115": links.get("115", [])} if links.get("115") else {}

            total = sum(len(items) for items in links.values())
            self._selected_media = detail
            self._link_groups = links
            self._last_message = f"资源加载完成：{detail.get('vod_name') or keyword} 共展示 {total} 条资源。"
            self._persist_state()
            return {
                "success": True,
                "message": self._last_message,
                "detail": detail,
                "links": links,
            }
        except Exception as err:
            logger.error("Panlink115 load links failed: %s", err)
            self._last_message = f"加载资源失败：{err}"
            self._persist_state()
            return {"success": False, "message": self._last_message, "detail": {}, "links": {}}

    def api_queue_115(
        self,
        title: str = "",
        url: str = "",
        password: str = "",
        source: str = "",
        vod_id: str = "",
        vod_name: str = "",
        type_name: str = "",
        category_group: str = "",
        category_name: str = "",
    ) -> Dict[str, Any]:
        title = (title or "").strip() or "未命名资源"
        vod_name = (vod_name or "").strip() or title
        url = (url or "").strip()
        category_group = (category_group or "").strip()
        category_name = (category_name or "").strip()
        if not url:
            self._last_message = "缺少 115 链接，无法加入下载任务。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}
        if not category_group or not category_name:
            self._last_message = "请选择当前 MoviePilot 已配置的分类后再创建下载任务。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}

        item = {
            "title": title,
            "vod_id": str(vod_id or "").strip(),
            "vod_name": vod_name,
            "type_name": (type_name or "").strip(),
            "url": url,
            "password": (password or "").strip(),
            "source": (source or "").strip(),
            "category_group": category_group,
            "category_name": category_name,
            "queued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "待接入 115 自动转存与 MP 整理链路",
        }
        if not any(existing.get("url") == url and existing.get("category_name") == category_name for existing in self._queued_115):
            self._queued_115.insert(0, item)

        self._last_message = f"已创建下载任务：{vod_name} -> {category_group} / {category_name}。"
        self._persist_state()
        logger.info("Panlink115 queued 115 task: %s -> %s/%s", vod_name, category_group, category_name)
        return {
            "success": True,
            "message": self._last_message,
            "item": item,
            "queue": list(self._queued_115),
        }

    def api_clear_queue(self) -> Dict[str, Any]:
        self._queued_115 = []
        self._last_message = "已清空下载任务队列。"
        self._persist_state()
        return {"success": True, "message": self._last_message, "queue": []}

    def stop_service(self):
        self._client = None

    def _build_client(self) -> PinglianClient:
        if not self._client:
            self._client = PinglianClient(self._username, self._password, self._timeout)
        else:
            self._client.update_credentials(self._username, self._password, self._timeout)
        return self._client

    def _restore_state(self) -> None:
        self._queued_115 = list(_PLUGIN_STATE.get("queued_115") or [])
        self._last_message = str(_PLUGIN_STATE.get("last_message") or "尚未开始搜索。")
        self._last_keyword = str(_PLUGIN_STATE.get("last_keyword") or "")
        self._search_results = list(_PLUGIN_STATE.get("search_results") or [])
        selected = _PLUGIN_STATE.get("selected_media") or {}
        self._selected_media = dict(selected) if isinstance(selected, dict) else None
        self._link_groups = dict(_PLUGIN_STATE.get("link_groups") or {})

    def _persist_state(self) -> None:
        _PLUGIN_STATE["queued_115"] = list(self._queued_115)
        _PLUGIN_STATE["last_message"] = self._last_message
        _PLUGIN_STATE["last_keyword"] = self._last_keyword
        _PLUGIN_STATE["search_results"] = list(self._search_results)
        _PLUGIN_STATE["selected_media"] = dict(self._selected_media or {})
        _PLUGIN_STATE["link_groups"] = dict(self._link_groups)

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(parsed, minimum)
