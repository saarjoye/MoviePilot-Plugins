from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase

from .client import PinglianClient


_PLUGIN_STATE: Dict[str, Any] = {
    "queued_115": [],
    "last_message": "尚未开始搜索。",
}


class Panlink115(_PluginBase):
    plugin_name = "盘链 115 搜索"
    plugin_desc = "手动搜索盘链影视资源，优先展示 115 网盘链接，并预留加入 115 接口。"
    plugin_icon = "https://115.com/favicon.ico"
    plugin_color = "#2F77FF"
    plugin_version = "0.2.0"
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
                "summary": "加载资源",
                "auth": "bear",
            },
            {
                "path": "/queue_115",
                "endpoint": self.api_queue_115,
                "methods": ["GET"],
                "summary": "加入 115 占位队列",
                "auth": "bear",
            },
            {
                "path": "/clear_queue",
                "endpoint": self.api_clear_queue,
                "methods": ["GET"],
                "summary": "清空待转存队列",
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
                            "text": "当前版本已切换为 Vue 页面搜索，支持盘链搜索、115 资源展示和“加入 115”占位接口，真实 115 转存仍待后续实现。",
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
                    "text": "当前插件详情页使用 Vue 远程组件渲染。如果看到此提示，说明 MoviePilot 前端版本过旧或前端构建文件未完整安装。",
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
            self._last_message = f"搜索完成：关键词“{keyword}”，命中 {len(results)} 条结果。"
            self._persist_state()
            return {"success": True, "message": self._last_message, "results": results}
        except Exception as err:
            logger.error("Panlink115 search failed: %s", err)
            self._last_message = f"搜索失败：{err}"
            self._persist_state()
            return {"success": False, "message": self._last_message, "results": []}

    def api_load_links(self, vod_id: str = "", keyword: str = "") -> Dict[str, Any]:
        keyword = (keyword or "").strip()
        vod_id = str(vod_id or "").strip()
        if not keyword or not vod_id:
            self._last_message = "缺少资源详情参数，无法加载盘链链接。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "links": {}}

        try:
            logger.info("Panlink115 load links requested: keyword=%s vod_id=%s", keyword, vod_id)
            client = self._build_client()
            links = client.search_pan_links(keyword=keyword, vod_id=vod_id)
            if self._only_show_115:
                links = {"115": links.get("115", [])} if links.get("115") else {}
            total = sum(len(items) for items in links.values())
            self._last_message = f"资源加载完成：{keyword} 共展示 {total} 条资源。"
            self._persist_state()
            return {"success": True, "message": self._last_message, "links": links}
        except Exception as err:
            logger.error("Panlink115 load links failed: %s", err)
            self._last_message = f"加载资源失败：{err}"
            self._persist_state()
            return {"success": False, "message": self._last_message, "links": {}}

    def api_queue_115(
        self,
        title: str = "",
        url: str = "",
        password: str = "",
        source: str = "",
    ) -> Dict[str, Any]:
        title = (title or "").strip() or "未命名资源"
        url = (url or "").strip()
        if not url:
            self._last_message = "缺少 115 链接，无法加入待转存队列。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}

        item = {
            "title": title,
            "url": url,
            "password": (password or "").strip(),
            "source": (source or "").strip(),
            "queued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "待实现真实 115 转存",
        }
        if not any(existing.get("url") == url for existing in self._queued_115):
            self._queued_115.insert(0, item)

        self._last_message = f"已加入待转存队列：{title}。当前版本仍为占位接口。"
        self._persist_state()
        logger.info("Panlink115 queued 115 link: %s", title)
        return {
            "success": True,
            "message": self._last_message,
            "item": item,
            "queue": list(self._queued_115),
        }

    def api_clear_queue(self) -> Dict[str, Any]:
        self._queued_115 = []
        self._last_message = "已清空待转存队列。"
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

    def _persist_state(self) -> None:
        _PLUGIN_STATE["queued_115"] = list(self._queued_115)
        _PLUGIN_STATE["last_message"] = self._last_message

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(parsed, minimum)
