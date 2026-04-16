from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase

from .client import CloudDrive2Client, PinglianClient


_PLUGIN_STATE: Dict[str, Any] = {
    "queued_115": [],
    "last_message": "尚未开始搜索。",
    "last_keyword": "",
    "search_results": [],
    "selected_media": None,
    "link_groups": {},
    "diagnosis": {},
}


class Panlink115(_PluginBase):
    plugin_name = "盘链 115 搜索"
    plugin_desc = "手动搜索盘链影视资源，展示 115 链接并提交到 CD2。"
    plugin_icon = "https://115.com/favicon.ico"
    plugin_color = "#2F77FF"
    plugin_version = "0.4.10"
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
    _cd2_url: str = ""
    _cd2_auth_mode: str = "api_token"
    _cd2_token: str = ""
    _cd2_web_token: str = ""
    _cd2_default_root: str = ""
    _cd2_directory_roots: Dict[str, str] = {}
    _cd2_category_roots: Dict[str, str] = {}
    _cd2_detect_delay: float = 1.2
    _client: Optional[PinglianClient] = None
    _cd2_client: Optional[CloudDrive2Client] = None
    _queued_115: List[Dict[str, Any]] = []
    _last_message: str = "尚未开始搜索。"
    _last_keyword: str = ""
    _search_results: List[Dict[str, Any]] = []
    _selected_media: Optional[Dict[str, Any]] = None
    _link_groups: Dict[str, List[Dict[str, Any]]] = {}
    _last_diagnosis: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._username = str(config.get("username") or "").strip()
        self._password = str(config.get("password") or "").strip()
        self._timeout = self._to_int(config.get("timeout"), default=20, minimum=5)
        self._max_results = self._to_int(config.get("max_results"), default=10, minimum=1)
        self._only_show_115 = bool(config.get("only_show_115", True))
        self._cd2_url = str(config.get("cd2_url") or "").strip()
        self._cd2_auth_mode = self._normalize_cd2_auth_mode(config.get("cd2_auth_mode"))
        self._cd2_token = str(config.get("cd2_token") or "").strip()
        self._cd2_web_token = str(config.get("cd2_web_token") or "").strip()
        self._cd2_default_root = self._normalize_path(config.get("cd2_default_root"))
        self._cd2_directory_roots = self._parse_directory_roots(config.get("cd2_directory_roots"))
        self._cd2_category_roots = self._parse_category_roots(config.get("cd2_category_roots"))
        self._merge_legacy_category_roots(config)
        self._cd2_detect_delay = self._to_float(config.get("cd2_detect_delay"), default=1.2, minimum=0.2)
        self._restore_state()
        self._client = self._build_client()
        self._cd2_client = self._build_cd2_client()
        logger.info(
            "Panlink115 plugin initialized: auth_mode=%s has_api_token=%s has_web_token=%s",
            self._cd2_auth_mode,
            bool(self._cd2_token),
            bool(self._cd2_web_token),
        )

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
                "summary": "提交到 115/CD2",
                "auth": "bear",
            },
            {
                "path": "/clear_queue",
                "endpoint": self.api_clear_queue,
                "methods": ["GET"],
                "summary": "清空任务队列",
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
                                        "props": {"model": "only_show_115", "label": "仅显示 115 资源"},
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
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "cd2_auth_mode",
                                            "label": "CD2 鉴权模式",
                                            "items": [
                                                {"title": "API Token", "value": "api_token"},
                                                {"title": "网页登录 Token", "value": "web_token"},
                                            ],
                                            "itemTitle": "title",
                                            "itemValue": "value",
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
                                            "model": "cd2_web_token",
                                            "label": "CD2 网页登录 Token",
                                            "type": "password",
                                            "placeholder": "填写浏览器 localStorage.token",
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cd2_url",
                                            "label": "CD2 地址",
                                            "placeholder": "例如：https://cd2.example.com:5555",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cd2_directory_roots",
                                            "label": "CD2 MP目录映射",
                                            "rows": 5,
                                            "autoGrow": True,
                                            "placeholder": "每行一个映射，例如：\nlocal:D:/115挂载/媒体库=/115open/媒体库\nlocal:D:/115挂载/媒体库/电影=/115open/媒体库/电影",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cd2_token",
                                            "label": "CD2 API Token",
                                            "type": "password",
                                            "placeholder": "填写 CD2 的 API Token",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cd2_default_root",
                                            "label": "CD2 默认根目录",
                                            "placeholder": "例如：/115open/媒体库",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cd2_category_roots",
                                            "label": "CD2 分类目录映射",
                                            "rows": 5,
                                            "autoGrow": True,
                                            "placeholder": "每行一个映射，例如：\n综艺节目=/115open/媒体库/综艺节目\n电视剧/国产剧=/115open/媒体库/剧集/国产剧\n*=/115open/媒体库",
                                        },
                                    }
                                ],
                            }
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
                                            "model": "cd2_detect_delay",
                                            "label": "CD2 检测等待秒数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "插件不会再内置任何电影、剧集或综艺目录假设。目录解析顺序为：1）精确分类映射（顶层/子分类）；2）顶层分类映射；3）通配映射 *；4）默认根目录/顶层分类/子分类。",
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
            "cd2_url": "",
            "cd2_auth_mode": "api_token",
            "cd2_token": "",
            "cd2_web_token": "",
            "cd2_default_root": "",
            "cd2_directory_roots": "",
            "cd2_category_roots": "",
            "cd2_detect_delay": 1.2,
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
            "cd2_configured": bool(self._cd2_url and self._cd2_token),
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
            self._last_message = "缺少资源详情参数，无法加载盘链链接。"
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
        raw_url = (url or "").strip()
        category_group = (category_group or "").strip()
        category_name = (category_name or "").strip()
        if not raw_url:
            self._last_message = "缺少 115 链接，无法加入下载任务。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}
        if not category_group or not category_name:
            self._last_message = "请选择当前 MoviePilot 已配置的分类后再创建下载任务。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}

        try:
            share_url = CloudDrive2Client.append_share_password(raw_url, password)
            target_path = self._resolve_cd2_target_path(category_group, category_name)
            result = self._build_cd2_client().add_offline_file(url=share_url, target_path=target_path)
        except Exception as err:
            logger.error(
                "Panlink115 submit to CD2 failed: auth_mode=%s has_api_token=%s has_web_token=%s error=%s",
                self._cd2_auth_mode,
                bool(self._cd2_token),
                bool(self._cd2_web_token),
                err,
            )
            self._last_message = f"提交到 115 失败：{err}"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}

        item = {
            "title": title,
            "vod_id": str(vod_id or "").strip(),
            "vod_name": vod_name,
            "type_name": (type_name or "").strip(),
            "url": share_url,
            "password": (password or "").strip(),
            "source": (source or "").strip(),
            "category_group": category_group,
            "category_name": category_name,
            "target_path": result.get("target_path") or target_path,
            "created_name": result.get("created_name") or "",
            "created_path": result.get("created_path") or "",
            "queued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已提交到 115",
        }
        if item["created_path"]:
            item["status"] = "已提交到 115，并检测到新目录"

        if not any(
            existing.get("url") == item["url"] and existing.get("target_path") == item["target_path"]
            for existing in self._queued_115
        ):
            self._queued_115.insert(0, item)

        if item["created_path"]:
            self._last_message = (
                f"已提交到 115：{vod_name} -> {item['target_path']}，检测到新目录 "
                f"{item['created_name'] or item['created_path']}。"
            )
        else:
            self._last_message = f"已提交到 115：{vod_name} -> {item['target_path']}。"
        self._persist_state()
        logger.info("Panlink115 submitted 115 task via CD2: %s -> %s", vod_name, item["target_path"])
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
        self._cd2_client = None

    def _build_client(self) -> PinglianClient:
        if not self._client:
            self._client = PinglianClient(self._username, self._password, self._timeout)
        else:
            self._client.update_credentials(self._username, self._password, self._timeout)
        return self._client

    def _build_cd2_client(self) -> CloudDrive2Client:
        if not self._cd2_client:
            self._cd2_client = CloudDrive2Client(
                base_url=self._cd2_url,
                token=self._cd2_token,
                timeout=self._timeout,
                detect_delay=self._cd2_detect_delay,
            )
        else:
            self._cd2_client.update_config(
                base_url=self._cd2_url,
                token=self._cd2_token,
                timeout=self._timeout,
                detect_delay=self._cd2_detect_delay,
            )
        return self._cd2_client

    def _resolve_cd2_target_path(self, category_group: str, category_name: str) -> str:
        group = (category_group or "").strip()
        name = (category_name or "").strip()
        if not group or not name:
            raise RuntimeError("缺少 MoviePilot 分类信息，无法计算 CD2 目录")

        mp_target = self._resolve_mp_target_directory(group, name)
        if mp_target:
            mp_direct_path = self._resolve_direct_cd2_path(mp_target)
            if mp_direct_path:
                return mp_direct_path
            mp_mapped_path = self._resolve_cd2_path_from_mp_target(mp_target)
            if mp_mapped_path:
                return mp_mapped_path

        exact_mapping = self._cd2_category_roots.get(self._category_key(group, name))
        if exact_mapping:
            return self._render_mapping_path(exact_mapping, group, name, mode="exact")

        group_mapping = self._cd2_category_roots.get(group)
        if group_mapping:
            return self._render_mapping_path(group_mapping, group, name, mode="group")

        wildcard_mapping = self._cd2_category_roots.get("*")
        if wildcard_mapping:
            return self._render_mapping_path(wildcard_mapping, group, name, mode="wildcard")

        if self._cd2_default_root:
            return self._join_cd2_path(self._join_cd2_path(self._cd2_default_root, group), name)

        if mp_target:
            matched_storage = mp_target.get("library_storage") or "local"
            matched_path = mp_target.get("target_path") or mp_target.get("library_path") or ""
            raise RuntimeError(
                f"已匹配到 MoviePilot 目录“{matched_storage}:{matched_path}”，但未找到对应的 CD2 目录。"
                f"请优先配置“CD2 MP目录映射”，或改用“CD2 分类目录映射/默认根目录”回退。"
            )

        raise RuntimeError(
            f"未找到分类“{group} / {name}”对应的 CD2 目录，请配置“CD2 分类目录映射”或填写“CD2 默认根目录”。"
        )

    def _render_mapping_path(self, mapping_value: str, group: str, name: str, mode: str) -> str:
        template = self._normalize_path(mapping_value)
        if not template:
            raise RuntimeError("CD2 分类目录映射中存在空路径，请检查插件配置。")

        if "{group}" in template or "{name}" in template:
            rendered = template.replace("{group}", group).replace("{name}", name)
            return self._normalize_path(rendered)

        if mode == "exact":
            return template
        if mode == "group":
            return self._join_cd2_path(template, name)
        return self._join_cd2_path(self._join_cd2_path(template, group), name)

    def _merge_legacy_category_roots(self, config: Dict[str, Any]) -> None:
        legacy_pairs = {
            "电影": self._normalize_path(config.get("cd2_movie_root")),
            "电视剧": self._normalize_path(config.get("cd2_tv_root")),
        }
        for key, value in legacy_pairs.items():
            if value and key not in self._cd2_category_roots:
                self._cd2_category_roots[key] = value

    def _resolve_mp_target_directory(self, category_group: str, category_name: str) -> Optional[Dict[str, Any]]:
        try:
            from app.helper.directory import DirectoryHelper
        except Exception as err:
            logger.warning("Panlink115 failed to import DirectoryHelper, fallback to plugin mappings only: %s", err)
            return None

        candidates: List[Tuple[int, int, Dict[str, Any]]] = []
        for directory in sorted(DirectoryHelper().get_dirs(), key=lambda item: item.priority or 0):
            library_path = self._normalize_fs_path(getattr(directory, "library_path", None))
            if not library_path:
                continue

            score = self._score_mp_directory(directory, category_group, category_name)
            if score <= 0:
                continue

            candidates.append(
                (
                    score,
                    int(getattr(directory, "priority", 0) or 0),
                    {
                        "name": str(getattr(directory, "name", "") or "").strip(),
                        "library_storage": str(getattr(directory, "library_storage", "") or "local").strip() or "local",
                        "library_path": library_path,
                        "target_path": self._build_mp_library_target_path(directory, category_group, category_name),
                        "media_type": str(getattr(directory, "media_type", "") or "").strip(),
                        "media_category": str(getattr(directory, "media_category", "") or "").strip(),
                    },
                )
            )

        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]

    def _score_mp_directory(self, directory: Any, category_group: str, category_name: str) -> int:
        media_type = str(getattr(directory, "media_type", "") or "").strip()
        media_category = str(getattr(directory, "media_category", "") or "").strip()
        group = (category_group or "").strip()
        name = (category_name or "").strip()

        if media_type and media_type != group:
            return 0
        if media_category and media_category != name:
            return 0
        if media_type == group and media_category == name:
            return 400
        if media_type == group and not media_category:
            return 300
        if not media_type and media_category == name:
            return 200
        if not media_type and not media_category:
            return 100
        return 0

    def _build_mp_library_target_path(self, directory: Any, category_group: str, category_name: str) -> str:
        library_dir = self._normalize_fs_path(getattr(directory, "library_path", None))
        if not library_dir:
            return ""

        media_type = str(getattr(directory, "media_type", "") or "").strip()
        media_category = str(getattr(directory, "media_category", "") or "").strip()

        if bool(getattr(directory, "library_type_folder", False)):
            library_dir = self._join_fs_path(library_dir, media_type or category_group)
        if bool(getattr(directory, "library_category_folder", False)):
            library_dir = self._join_fs_path(library_dir, media_category or category_name)
        return library_dir

    def _resolve_cd2_path_from_mp_target(self, mp_target: Dict[str, Any]) -> str:
        target_path = self._normalize_fs_path(mp_target.get("target_path"))
        library_storage = str(mp_target.get("library_storage") or "local").strip() or "local"
        best_match: Optional[Tuple[int, int, str, str]] = None

        for raw_key, cd2_root in self._cd2_directory_roots.items():
            mapping_storage, mapping_path = self._split_storage_path(raw_key)
            if not mapping_path:
                continue
            if mapping_storage and mapping_storage != library_storage:
                continue

            relative_path = self._relative_fs_path(target_path, mapping_path)
            if relative_path is None:
                continue

            score = len(mapping_path)
            storage_score = 1 if mapping_storage else 0
            if not best_match or (score, storage_score) > (best_match[0], best_match[1]):
                best_match = (score, storage_score, cd2_root, relative_path)

        if not best_match:
            return ""

        _, _, cd2_root, relative_path = best_match
        if not relative_path:
            return self._normalize_path(cd2_root)
        return self._join_cd2_path(cd2_root, relative_path)

    def _resolve_direct_cd2_path(self, mp_target: Dict[str, Any]) -> str:
        target_path = self._normalize_fs_path(mp_target.get("target_path"))
        library_storage = str(mp_target.get("library_storage") or "").strip()
        if not target_path.startswith("/"):
            return ""

        storage_name = library_storage.lower()
        if "clouddrive" in storage_name or "cd2" in storage_name:
            return self._normalize_path(target_path)

        if target_path.startswith("/115open/"):
            return self._normalize_path(target_path)
        return ""

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
                "summary": "加载详情与链接",
                "auth": "bear",
            },
            {
                "path": "/queue_115",
                "endpoint": self.api_queue_115,
                "methods": ["GET"],
                "summary": "提交到 115 / CD2",
                "auth": "bear",
            },
            {
                "path": "/diagnose_cd2",
                "endpoint": self.api_diagnose_cd2,
                "methods": ["GET"],
                "summary": "诊断 CD2 认证与目录连通性",
                "auth": "bear",
            },
            {
                "path": "/clear_queue",
                "endpoint": self.api_clear_queue,
                "methods": ["GET"],
                "summary": "清空任务队列",
                "auth": "bear",
            },
        ]

    def api_state(self) -> Dict[str, Any]:
        auth_info = self._get_cd2_auth_info()
        return {
            "success": True,
            "message": self._last_message,
            "queue": list(self._queued_115),
            "enabled": self._enabled,
            "only_show_115": self._only_show_115,
            "max_results": self._max_results,
            "cd2_configured": bool(auth_info.get("configured")),
            "cd2_auth_mode": auth_info.get("mode"),
            "cd2_auth_label": auth_info.get("label"),
            "cd2_has_api_token": bool(auth_info.get("has_api_token")),
            "cd2_has_web_token": bool(auth_info.get("has_web_token")),
            "keyword": self._last_keyword,
            "results": list(self._search_results),
            "selected_media": dict(self._selected_media or {}),
            "link_groups": dict(self._link_groups),
            "diagnosis": dict(self._last_diagnosis or {}),
        }

    def api_diagnose_cd2(self, category_group: str = "", category_name: str = "") -> Dict[str, Any]:
        group = (category_group or "").strip()
        name = (category_name or "").strip()
        if not group or not name:
            self._last_message = "请先选择 MoviePilot 分类，再执行 CD2 诊断。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "diagnosis": {}}

        try:
            target_path = self._resolve_cd2_target_path(group, name)
            diagnosis = self._build_cd2_client().diagnose_target(
                target_path=target_path,
                has_alternate_auth=self._has_alternate_cd2_auth(),
            )
            diagnosis["category_group"] = group
            diagnosis["category_name"] = name
            self._last_diagnosis = diagnosis
            self._last_message = str(diagnosis.get("message") or "CD2 诊断完成。")
            self._persist_state()
            logger.info("Panlink115 CD2 diagnose requested: %s / %s -> %s", group, name, target_path)
            return {
                "success": diagnosis.get("status") != "error",
                "message": self._last_message,
                "diagnosis": diagnosis,
            }
        except Exception as err:
            logger.error("Panlink115 CD2 diagnose failed: %s", err)
            self._last_diagnosis = {
                "status": "error",
                "auth_mode": self._cd2_auth_mode,
                "auth_label": self._get_cd2_auth_info().get("label"),
                "category_group": group,
                "category_name": name,
                "message": str(err),
            }
            self._last_message = f"CD2 诊断失败：{err}"
            self._persist_state()
            return {
                "success": False,
                "message": self._last_message,
                "diagnosis": dict(self._last_diagnosis),
            }

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
        raw_url = (url or "").strip()
        group = (category_group or "").strip()
        name = (category_name or "").strip()
        if not raw_url:
            self._last_message = "缺少 115 链接，无法加入下载任务。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}
        if not group or not name:
            self._last_message = "请先选择当前 MoviePilot 已配置的分类后再创建下载任务。"
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}

        try:
            share_url = CloudDrive2Client.append_share_password(raw_url, password)
            target_path = self._resolve_cd2_target_path(group, name)
            client = self._build_cd2_client()
            logger.info(
                "Panlink115 submit via CD2: auth_mode=%s auth_label=%s target=%s",
                self._cd2_auth_mode,
                client.get_auth_label(),
                target_path,
            )
            result = client.add_offline_file(url=share_url, target_path=target_path)
        except Exception as err:
            logger.error("Panlink115 submit to CD2 failed: %s", err)
            self._last_message = self._append_cd2_auth_hint(f"提交到 115 失败：{err}")
            self._persist_state()
            return {"success": False, "message": self._last_message, "queue": list(self._queued_115)}

        item = {
            "title": title,
            "vod_id": str(vod_id or "").strip(),
            "vod_name": vod_name,
            "type_name": (type_name or "").strip(),
            "url": share_url,
            "password": (password or "").strip(),
            "source": (source or "").strip(),
            "category_group": group,
            "category_name": name,
            "target_path": result.get("target_path") or target_path,
            "created_name": result.get("created_name") or "",
            "created_path": result.get("created_path") or "",
            "auth_label": client.get_auth_label(),
            "queued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已提交到 115",
        }
        if item["created_path"]:
            item["status"] = "已提交到 115，并检测到新目录"

        if not any(
            existing.get("url") == item["url"] and existing.get("target_path") == item["target_path"]
            for existing in self._queued_115
        ):
            self._queued_115.insert(0, item)

        if item["created_path"]:
            self._last_message = (
                f"已提交到 115：{vod_name} -> {item['target_path']}，检测到新目录"
                f"{item['created_name'] or item['created_path']}。"
            )
        else:
            self._last_message = f"已提交到 115：{vod_name} -> {item['target_path']}。"
        self._persist_state()
        logger.info("Panlink115 submitted 115 task via CD2: %s -> %s", vod_name, item["target_path"])
        return {
            "success": True,
            "message": self._last_message,
            "item": item,
            "queue": list(self._queued_115),
        }

    def _build_cd2_client(self) -> CloudDrive2Client:
        if not self._cd2_client:
            self._cd2_client = CloudDrive2Client(
                base_url=self._cd2_url,
                token=self._cd2_token,
                web_token=self._cd2_web_token,
                auth_mode=self._cd2_auth_mode,
                timeout=self._timeout,
                detect_delay=self._cd2_detect_delay,
            )
        else:
            self._cd2_client.update_config(
                base_url=self._cd2_url,
                token=self._cd2_token,
                web_token=self._cd2_web_token,
                auth_mode=self._cd2_auth_mode,
                timeout=self._timeout,
                detect_delay=self._cd2_detect_delay,
            )
        return self._cd2_client

    def _restore_state(self) -> None:
        self._queued_115 = list(_PLUGIN_STATE.get("queued_115") or [])
        self._last_message = str(_PLUGIN_STATE.get("last_message") or "尚未开始搜索。")
        self._last_keyword = str(_PLUGIN_STATE.get("last_keyword") or "")
        self._search_results = list(_PLUGIN_STATE.get("search_results") or [])
        selected = _PLUGIN_STATE.get("selected_media") or {}
        self._selected_media = dict(selected) if isinstance(selected, dict) else None
        self._link_groups = dict(_PLUGIN_STATE.get("link_groups") or {})
        self._last_diagnosis = dict(_PLUGIN_STATE.get("diagnosis") or {})

    def _persist_state(self) -> None:
        _PLUGIN_STATE["queued_115"] = list(self._queued_115)
        _PLUGIN_STATE["last_message"] = self._last_message
        _PLUGIN_STATE["last_keyword"] = self._last_keyword
        _PLUGIN_STATE["search_results"] = list(self._search_results)
        _PLUGIN_STATE["selected_media"] = dict(self._selected_media or {})
        _PLUGIN_STATE["link_groups"] = dict(self._link_groups)
        _PLUGIN_STATE["diagnosis"] = dict(self._last_diagnosis or {})

    def _get_cd2_auth_info(self) -> Dict[str, Any]:
        return self._build_cd2_client().describe_auth()

    def _has_alternate_cd2_auth(self) -> bool:
        if self._cd2_auth_mode == "web_token":
            return bool(self._cd2_token)
        return bool(self._cd2_web_token)

    def _append_cd2_auth_hint(self, message: str) -> str:
        text = str(message or "").strip()
        lowered = text.lower()
        if (
            self._cd2_auth_mode == "api_token"
            and self._cd2_web_token
            and ("离线下载" in text or "add offline" in lowered or "permission required" in lowered)
        ):
            return f"{text} 当前已配置网页登录 Token，可将 CD2 鉴权模式切换为“网页登录 Token”后重试。"
        return text

    @staticmethod
    def _normalize_cd2_auth_mode(value: Any) -> str:
        mode = str(value or "").strip().lower()
        if mode == "web_token":
            return "web_token"
        return "api_token"

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(parsed, minimum)

    @staticmethod
    def _to_float(value: Any, default: float, minimum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(parsed, minimum)

    @classmethod
    def _parse_category_roots(cls, value: Any) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for raw_line in str(value or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = None
            for separator in ("=", ":", "："):
                if separator in line:
                    parts = line.split(separator, 1)
                    break

            if not parts:
                continue

            key = str(parts[0] or "").strip()
            root = cls._normalize_path(parts[1])
            if key and root:
                mapping[key] = root
        return mapping

    @classmethod
    def _parse_directory_roots(cls, value: Any) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for raw_line in str(value or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = None
            for separator in ("=", "＝"):
                if separator in line:
                    parts = line.split(separator, 1)
                    break

            if not parts:
                continue

            key = str(parts[0] or "").strip()
            root = cls._normalize_path(parts[1])
            if key and root:
                mapping[key] = root
        return mapping

    @staticmethod
    def _category_key(group: str, name: str) -> str:
        return f"{str(group or '').strip()}/{str(name or '').strip()}"

    @staticmethod
    def _normalize_path(value: Any) -> str:
        return CloudDrive2Client.normalize_path(str(value or ""))

    @staticmethod
    def _join_cd2_path(base_root: str, child_name: str) -> str:
        base = CloudDrive2Client.normalize_path(base_root)
        child = str(child_name or "").strip().replace("\\", "/").strip("/")
        if not base:
            return ""
        if not child:
            return base
        return f"{base}/{child}"

    @staticmethod
    def _normalize_fs_path(value: Any) -> str:
        path = str(value or "").strip().replace("\\", "/")
        if not path:
            return ""
        if path == "/":
            return path
        if len(path) == 3 and path[1] == ":" and path.endswith("/"):
            return path
        return path.rstrip("/")

    @classmethod
    def _join_fs_path(cls, base_root: str, child_name: str) -> str:
        base = cls._normalize_fs_path(base_root)
        child = str(child_name or "").strip().replace("\\", "/").strip("/")
        if not base:
            return child
        if not child:
            return base
        if base == "/":
            return f"/{child}"
        return f"{base}/{child}"

    @classmethod
    def _split_storage_path(cls, value: str) -> Tuple[str, str]:
        raw = str(value or "").strip()
        if not raw:
            return "", ""
        if len(raw) >= 3 and raw[1] == ":" and raw[2] in ("/", "\\"):
            return "", cls._normalize_fs_path(raw)
        if ":" in raw and not raw.startswith("/"):
            storage, path = raw.split(":", 1)
            return storage.strip(), cls._normalize_fs_path(path)
        return "", cls._normalize_fs_path(raw)

    @classmethod
    def _relative_fs_path(cls, full_path: str, root_path: str) -> Optional[str]:
        full_norm = cls._normalize_fs_path(full_path)
        root_norm = cls._normalize_fs_path(root_path)
        if not full_norm or not root_norm:
            return None

        full_cmp = full_norm.lower()
        root_cmp = root_norm.lower()
        if full_cmp == root_cmp:
            return ""

        prefix = f"{root_cmp}/" if root_norm != "/" else "/"
        if not full_cmp.startswith(prefix):
            return None

        if root_norm == "/":
            return full_norm[1:]
        return full_norm[len(root_norm) + 1:]
