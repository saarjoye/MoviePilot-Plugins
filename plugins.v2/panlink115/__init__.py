from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase

from .client import PinglianClient


_PAGE_STATE: Dict[str, Any] = {
    "last_keyword": "",
    "search_results": [],
    "current_links": {},
    "queued_115": [],
    "last_message": "尚未开始搜索。",
}


class Panlink115(_PluginBase):
    plugin_name = "盘链 115 搜索"
    plugin_desc = "手动搜索盘链影视资源，优先展示 115 链接，并预留加入 115 接口。"
    plugin_icon = "https://115.com/favicon.ico"
    plugin_color = "#2F77FF"
    plugin_version = "0.1.1"
    plugin_author = "wYw"
    author_url = "https://github.com/openai"
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
    _last_keyword: str = ""
    _search_results: List[Dict[str, Any]] = []
    _current_links: Dict[str, List[Dict[str, Any]]] = {}
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
        self._restore_page_state()
        self._client = self._build_client()
        logger.info("Panlink115 plugin initialized")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["GET"],
                "summary": "盘链搜索",
            },
            {
                "path": "/load_links",
                "endpoint": self.api_load_links,
                "methods": ["GET"],
                "summary": "加载资源",
            },
            {
                "path": "/queue_115",
                "endpoint": self.api_queue_115,
                "methods": ["GET"],
                "summary": "加入 115 占位",
            },
            {
                "path": "/clear_queue",
                "endpoint": self.api_clear_queue,
                "methods": ["GET"],
                "summary": "清空待转存队列",
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
                            "text": "当前版本只完成盘链搜索、115资源展示和加入 115 占位接口，尚未实现真实转存。",
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
        page: List[dict] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "info" if self._enabled else "warning",
                    "variant": "tonal",
                    "text": self._build_status_text(),
                },
            },
            self._build_search_card(),
        ]
        page.extend(self._build_results_cards())
        page.extend(self._build_links_cards())
        page.extend(self._build_queue_cards())
        return page

    def api_search(self, keyword: str = "") -> Dict[str, Any]:
        keyword = (keyword or "").strip()
        if not keyword:
            self._last_message = "请输入影视名称后再搜索。"
            self._persist_page_state()
            return {"success": False, "message": self._last_message}

        try:
            logger.info("Panlink115 search requested: %s", keyword)
            client = self._build_client()
            self._search_results = client.search(keyword=keyword, limit=self._max_results)
            self._last_keyword = keyword
            self._current_links = {}
            self._last_message = f"搜索完成：关键词“{keyword}”，命中 {len(self._search_results)} 条结果。"
            self._persist_page_state()
            return {"success": True, "message": self._last_message, "results": self._search_results}
        except Exception as err:
            logger.error("Panlink115 search failed: %s", err)
            self._search_results = []
            self._current_links = {}
            self._last_message = f"搜索失败：{err}"
            self._persist_page_state()
            return {"success": False, "message": self._last_message}

    def api_load_links(self, vod_id: str = "", keyword: str = "") -> Dict[str, Any]:
        keyword = (keyword or self._last_keyword or "").strip()
        vod_id = str(vod_id or "").strip()
        if not keyword or not vod_id:
            self._last_message = "缺少资源详情参数，无法加载盘链链接。"
            self._persist_page_state()
            return {"success": False, "message": self._last_message}

        try:
            logger.info("Panlink115 load links requested: keyword=%s vod_id=%s", keyword, vod_id)
            client = self._build_client()
            links = client.search_pan_links(keyword=keyword, vod_id=vod_id)
            if self._only_show_115:
                links = {"115": links.get("115", [])} if links.get("115") else {}
            self._current_links = links
            total = sum(len(items) for items in links.values())
            self._last_message = f"资源加载完成：{keyword} 共展示 {total} 条资源。"
            self._persist_page_state()
            return {"success": True, "message": self._last_message, "links": links}
        except Exception as err:
            logger.error("Panlink115 load links failed: %s", err)
            self._current_links = {}
            self._last_message = f"加载资源失败：{err}"
            self._persist_page_state()
            return {"success": False, "message": self._last_message}

    def api_queue_115(self, title: str = "", url: str = "", password: str = "", source: str = "") -> Dict[str, Any]:
        title = (title or "").strip() or "未命名资源"
        url = (url or "").strip()
        if not url:
            self._last_message = "缺少 115 链接，无法加入待转存队列。"
            self._persist_page_state()
            return {"success": False, "message": self._last_message}

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
        self._persist_page_state()
        logger.info("Panlink115 queued 115 link: %s", title)
        return {"success": True, "message": self._last_message, "item": item}

    def api_clear_queue(self) -> Dict[str, Any]:
        self._queued_115 = []
        self._last_message = "已清空待转存队列。"
        self._persist_page_state()
        return {"success": True, "message": self._last_message}

    def stop_service(self):
        self._client = None

    def _build_client(self) -> PinglianClient:
        if not self._client:
            self._client = PinglianClient(self._username, self._password, self._timeout)
        else:
            self._client.update_credentials(self._username, self._password, self._timeout)
        return self._client

    def _build_status_text(self) -> str:
        status = "已启用" if self._enabled else "未启用"
        mode = "仅 115" if self._only_show_115 else "全部网盘"
        return f"{status}。当前显示模式：{mode}。{self._last_message}"

    def _restore_page_state(self) -> None:
        self._last_keyword = str(_PAGE_STATE.get("last_keyword") or "")
        self._search_results = list(_PAGE_STATE.get("search_results") or [])
        self._current_links = dict(_PAGE_STATE.get("current_links") or {})
        self._queued_115 = list(_PAGE_STATE.get("queued_115") or [])
        self._last_message = str(_PAGE_STATE.get("last_message") or "尚未开始搜索。")

    def _persist_page_state(self) -> None:
        _PAGE_STATE["last_keyword"] = self._last_keyword
        _PAGE_STATE["search_results"] = self._search_results
        _PAGE_STATE["current_links"] = self._current_links
        _PAGE_STATE["queued_115"] = self._queued_115
        _PAGE_STATE["last_message"] = self._last_message

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(parsed, minimum)

    def _build_search_card(self) -> Dict[str, Any]:
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "class": "mb-4"},
            "content": [
                {"component": "VCardTitle", "text": "盘链搜索"},
                {"component": "VCardText", "text": "输入电影或电视剧名称后点击搜索，优先展示 115 资源。"},
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "按钮说明：搜索盘链 = 按关键词查影视；加载资源 = 读取该影视的网盘资源；加入 115 = 先放入待转存队列。",
                    },
                },
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 8},
                            "content": [
                                {
                                    "component": "VTextField",
                                    "props": {
                                        "model": "keyword_input",
                                        "label": "影视名称",
                                        "placeholder": "例如：流浪地球、庆余年、狂飙",
                                    },
                                }
                            ],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 4},
                            "content": [
                                {
                                    "component": "VBtn",
                                    "text": "搜索盘链",
                                    "props": {"color": "primary", "block": True},
                                    "events": {
                                        "click": {
                                            "api": "plugin/Panlink115/search",
                                            "method": "get",
                                            "params": {"keyword": "{{keyword_input}}"},
                                        }
                                    },
                                }
                            ],
                        },
                    ],
                },
            ],
        }

    def _build_results_cards(self) -> List[Dict[str, Any]]:
        if not self._search_results:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无搜索结果。先执行一次盘链搜索即可在这里查看候选影视条目。",
                    },
                }
            ]

        cards: List[Dict[str, Any]] = [
            {"component": "VCard", "props": {"class": "mb-4"}, "content": [{"component": "VCardTitle", "text": f"搜索结果：{self._last_keyword}"}]}
        ]
        for item in self._search_results:
            subtitle = " / ".join(
                part for part in [item.get("type_name"), item.get("vod_year"), item.get("vod_area"), item.get("vod_remarks")] if part
            )
            cards.append(
                {
                    "component": "VCard",
                    "props": {"variant": "outlined", "class": "mb-3"},
                    "content": [
                        {"component": "VCardTitle", "text": item.get("vod_name") or "未命名条目"},
                        {"component": "VCardSubtitle", "text": subtitle or f"vod_id={item.get('vod_id')}"},
                        {"component": "VCardText", "text": f"vod_id：{item.get('vod_id')}  语言：{item.get('vod_lang') or '未知'}"},
                        {
                            "component": "VCardActions",
                            "content": [
                                {
                                    "component": "VBtn",
                                    "text": "加载资源",
                                    "props": {"color": "primary", "variant": "flat"},
                                    "events": {
                                        "click": {
                                            "api": "plugin/Panlink115/load_links",
                                            "method": "get",
                                            "params": {"vod_id": item.get("vod_id"), "keyword": item.get("vod_name")},
                                        }
                                    },
                                }
                            ],
                        },
                    ],
                }
            )
        return cards

    def _build_links_cards(self) -> List[Dict[str, Any]]:
        if not self._current_links:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "当前还没有加载任何资源链接。点击某个搜索结果的“加载资源”后会在这里显示。",
                    },
                }
            ]

        cards: List[Dict[str, Any]] = [
            {"component": "VCard", "props": {"class": "mb-4"}, "content": [{"component": "VCardTitle", "text": "资源列表"}]}
        ]
        for group_name, entries in self._current_links.items():
            cards.append(
                {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [{"component": "VCardTitle", "text": f"{group_name} 资源"}]}
            )
            for entry in entries:
                actions: List[Dict[str, Any]] = [
                    {
                        "component": "VBtn",
                        "text": "打开链接",
                        "props": {"href": entry.get("url"), "target": "_blank", "variant": "text"},
                    }
                ]
                if group_name == "115":
                    actions.append(
                        {
                            "component": "VBtn",
                            "text": "加入 115",
                            "props": {"color": "primary", "variant": "flat"},
                            "events": {
                                "click": {
                                    "api": "plugin/Panlink115/queue_115",
                                    "method": "get",
                                    "params": {
                                        "title": entry.get("title"),
                                        "url": entry.get("url"),
                                        "password": entry.get("password"),
                                        "source": entry.get("source"),
                                    },
                                }
                            },
                        }
                    )
                cards.append(
                    {
                        "component": "VCard",
                        "props": {"variant": "outlined", "class": "mb-3"},
                        "content": [
                            {"component": "VCardTitle", "text": entry.get("title") or "未命名资源"},
                            {
                                "component": "VCardSubtitle",
                                "text": f"来源：{entry.get('source') or '未知'}  更新时间：{entry.get('time') or '未知'}",
                            },
                            {"component": "VCardText", "text": self._format_link_text(entry)},
                            {"component": "VCardActions", "content": actions},
                        ],
                    }
                )
        return cards

    def _build_queue_cards(self) -> List[Dict[str, Any]]:
        if not self._queued_115:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "tonal",
                        "text": "待转存队列为空。当前“加入 115”只是占位动作，用来预留后续自动转存接口。",
                    },
                }
            ]

        cards: List[Dict[str, Any]] = [
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "text": "待转存到 115"},
                    {
                        "component": "VCardActions",
                        "content": [
                            {
                                "component": "VBtn",
                                "text": "清空队列",
                                "props": {"color": "warning", "variant": "text"},
                                "events": {
                                    "click": {
                                        "api": "plugin/Panlink115/clear_queue",
                                        "method": "get",
                                        "params": {},
                                    }
                                },
                            }
                        ],
                    },
                ],
            }
        ]
        for item in self._queued_115:
            cards.append(
                {
                    "component": "VCard",
                    "props": {"variant": "outlined", "class": "mb-3"},
                    "content": [
                        {"component": "VCardTitle", "text": item.get("title") or "未命名资源"},
                        {
                            "component": "VCardSubtitle",
                            "text": f"加入时间：{item.get('queued_at')}  状态：{item.get('status')}",
                        },
                        {"component": "VCardText", "text": self._format_queue_text(item)},
                    ],
                }
            )
        return cards

    @staticmethod
    def _format_link_text(entry: Dict[str, Any]) -> str:
        return f"链接：{entry.get('url')}\n提取码：{entry.get('password') or '无'}"

    @staticmethod
    def _format_queue_text(item: Dict[str, Any]) -> str:
        return f"来源：{item.get('source') or '未知'}\n链接：{item.get('url')}\n提取码：{item.get('password') or '无'}"
