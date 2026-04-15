import copy
import json
import re
import time
from datetime import datetime, timedelta
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends

from app.core.config import settings
from app.chain.subscribe import SubscribeChain
from app.db import ScopedSession
from app.db.models.subscribe import Subscribe
from app.db.models.subscribehistory import SubscribeHistory
from app.db.subscribe_oper import SubscribeOper
from app.db.user_oper import UserOper, get_current_active_user
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import (
    DiscoverMediaSource,
    DiscoverSourceEventData,
    MediaInfo,
    MediaRecognizeConvertEventData,
    RecommendMediaSource,
    RecommendSourceEventData,
)
from app.schemas.types import ChainEventType, MediaType, NotificationType


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PLATFORM_LABELS = {
    "all": "全部平台",
    "iqiyi": "爱奇艺",
    "tencent": "腾讯视频",
    "youku": "优酷",
    "mgtv": "芒果TV",
}

TYPE_LABELS = {
    "all": "全部类型",
    "movie": "电影",
    "tv": "电视剧",
    "anime": "动漫",
    "variety": "综艺",
    "short": "短剧",
    "documentary": "纪录片",
    "kids": "少儿",
    "humanity": "人文",
}

TIME_LABELS = {
    "all": "全部时间",
    "today": "今日上线",
    "tomorrow": "明日上线",
    "3days": "3天内",
    "7days": "7天内",
    "30days": "30天内",
    "pending": "敬请期待",
}

PLATFORM_ALIAS_MAP = {
    "all": "all",
    "全部": "all",
    "全部平台": "all",
    "iqiyi": "iqiyi",
    "爱奇艺": "iqiyi",
    "tencent": "tencent",
    "腾讯": "tencent",
    "腾讯视频": "tencent",
    "youku": "youku",
    "优酷": "youku",
    "mgtv": "mgtv",
    "芒果tv": "mgtv",
    "芒果": "mgtv",
}

TYPE_ALIAS_MAP = {
    "all": "all",
    "全部": "all",
    "全部类型": "all",
    "movie": "movie",
    "电影": "movie",
    "tv": "tv",
    "电视剧": "tv",
    "剧集": "tv",
    "anime": "anime",
    "动漫": "anime",
    "动画": "anime",
    "variety": "variety",
    "综艺": "variety",
    "documentary": "documentary",
    "纪录片": "documentary",
    "short": "short",
    "短剧": "short",
    "kids": "kids",
    "少儿": "kids",
    "humanity": "humanity",
    "人文": "humanity",
}

RECOMMEND_GROUPS = {
    "movie": {"movie"},
    "tv": {"tv", "variety", "short", "documentary", "kids", "humanity"},
    "anime": {"anime"},
    "all": {"movie", "tv", "anime", "variety", "short", "documentary", "kids", "humanity"},
}

AUTO_SUBSCRIBE_TYPE_GROUPS = {
    "all": {"movie", "tv", "anime", "variety", "short", "documentary", "kids", "humanity"},
    "movie": {"movie"},
    "tv": {"tv", "short"},
    "anime": {"anime"},
    "variety": {"variety"},
}

GENRE_ALIAS_MAP = {
    "喜剧": {"喜剧", "comedy"},
    "剧情": {"剧情", "drama"},
    "爱情": {"爱情", "romance", "romantic"},
    "伦理": {"伦理"},
    "家庭": {"家庭", "family"},
    "悬疑": {"悬疑", "mystery"},
    "犯罪": {"犯罪", "crime"},
    "动作": {"动作", "action"},
    "动画": {"动画", "animation"},
    "科幻": {"科幻", "science fiction", "sci-fi", "scifi"},
    "奇幻": {"奇幻", "fantasy"},
    "古装": {"古装", "costume"},
    "历史": {"历史", "history"},
    "战争": {"战争", "war"},
    "惊悚": {"惊悚", "thriller"},
    "恐怖": {"恐怖", "horror"},
    "真人秀": {"真人秀", "reality", "reality-tv"},
    "脱口秀": {"脱口秀", "talk show", "talk"},
    "音乐": {"音乐", "music"},
    "冒险": {"冒险", "adventure"},
    "武侠": {"武侠", "martial arts"},
    "少儿": {"少儿", "儿童", "kids", "children"},
}

IQIYI_TYPE_MAP = {
    "1": "movie",
    "2": "tv",
    "3": "documentary",
    "4": "anime",
    "6": "variety",
    "35": "short",
    "37": "anime",
}

YOUKU_SECTION_MAP = {
    "剧集": "tv",
    "电影": "movie",
    "综艺": "variety",
    "动漫": "anime",
    "纪录片": "documentary",
    "人文": "humanity",
    "少儿": "kids",
}

TENCENT_CHANNELS = {
    "tv": {"channel_id": "100113", "upcoming_value": "1", "type_key": "tv"},
    "movie": {"channel_id": "100173", "upcoming_value": "999", "type_key": "movie"},
}

CACHE_SCHEMA_VERSION = 8

AUTO_SUBSCRIBE_RULES_SAMPLE = json.dumps(
    [
        {
            "name": "7天内国产电视剧",
            "enabled": False,
            "time_range": "7days",
            "days": 7,
            "types": ["tv"],
            "regions": ["国产"],
            "platforms": ["all"],
        },
        {
            "name": "30天内韩国喜剧电影",
            "enabled": False,
            "time_range": "30days",
            "days": 30,
            "types": ["movie"],
            "regions": ["韩国"],
            "genres": ["喜剧"],
            "platforms": ["all"],
        },
    ],
    ensure_ascii=False,
    indent=2,
)
REGION_ALIAS_MAP = {
    "CN": {"CN"},
    "中国": {"CN"},
    "中国大陆": {"CN"},
    "国产": {"CN"},
    "华语": {"CN", "HK", "TW"},
    "HK": {"HK"},
    "香港": {"HK"},
    "TW": {"TW"},
    "台湾": {"TW"},
    "KR": {"KR"},
    "韩国": {"KR"},
    "JP": {"JP"},
    "日本": {"JP"},
    "US": {"US"},
    "美国": {"US"},
    "GB": {"GB"},
    "英国": {"GB"},
}

LANGUAGE_REGION_MAP = {
    "zh": "CN",
    "ko": "KR",
    "ja": "JP",
    "en": "US",
}

REGION_CODE_LABELS = {
    "CN": "国产",
    "HK": "中国香港",
    "TW": "中国台湾",
    "KR": "韩国",
    "JP": "日本",
    "US": "美国",
    "GB": "英国",
}

PAGE_TYPE_LABELS = {
    "all": "全部类型",
    "movie": "电影",
    "tv": "电视剧",
    "anime": "动漫",
    "variety": "综艺",
}

PAGE_REGION_LABELS = {
    "all": "全部地区",
    "国产": "国产",
    "华语": "华语",
    "韩国": "韩国",
    "日本": "日本",
    "美国": "美国",
    "英国": "英国",
    "香港": "中国香港",
    "台湾": "中国台湾",
}

PAGE_GENRE_LABELS = {
    "all": "全部题材",
    "喜剧": "喜剧",
    "剧情": "剧情",
    "爱情": "爱情",
    "伦理": "伦理",
    "家庭": "家庭",
    "悬疑": "悬疑",
    "犯罪": "犯罪",
    "动作": "动作",
    "动画": "动画",
    "科幻": "科幻",
    "奇幻": "奇幻",
    "古装": "古装",
    "真人秀": "真人秀",
    "脱口秀": "脱口秀",
    "音乐": "音乐",
    "冒险": "冒险",
    "武侠": "武侠",
    "少儿": "少儿",
}

PAGE_FILTER_DEFAULTS = {
    "platform": "all",
    "mtype": "all",
    "time_range": "30days",
    "region": "all",
    "genre": "all",
}



def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = unescape(url.strip())
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return f"https://{url[7:]}"
    return url


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_reserve_count(text: str) -> int:
    if not text:
        return 0
    text = str(text).strip().replace(",", "")
    matched = re.search(r"(\d+(?:\.\d+)?)\s*万", text)
    if matched:
        return int(float(matched.group(1)) * 10000)
    matched = re.search(r"(\d+(?:\.\d+)?)", text)
    if matched:
        return int(float(matched.group(1)))
    return 0


def build_title_year(title: str, year: Optional[str]) -> str:
    if title and year:
        return f"{title} ({year})"
    return title or ""


def js_object_to_json(js_text: str) -> str:
    return re.sub(r":undefined(?=[,}])", ":null", js_text)


def extract_balanced_object(text: str, marker: str) -> Optional[str]:
    marker_index = text.find(marker)
    if marker_index == -1:
        return None
    start = text.find("{", marker_index)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


class UpcomingReleases(_PluginBase):
    plugin_name = "待播影视日历"
    plugin_desc = "聚合爱奇艺、腾讯视频、优酷、芒果TV的即将上映内容，支持探索页筛选、推荐页扩展和定时推送。"
    plugin_icon = "TrendingShow.jpg"
    plugin_version = "0.6.15"
    plugin_release_date = "2026-04-15"
    plugin_author = "wYw"
    author_url = "https://github.com/saarjoye/MoviePilot-Plugins"
    plugin_config_prefix = "upcomingreleases_"
    plugin_order = 26
    auth_level = 1

    _cache: Dict[str, Any] = {"timestamp": 0, "items": []}
    _security_domains_ready = False

    _default_config = {
        "enabled": True,
        "enable_iqiyi": True,
        "enable_tencent": True,
        "enable_youku": True,
        "enable_mgtv": True,
        "cache_ttl_minutes": 180,
        "push_enabled": True,
        "push_cron": "0 9,18 * * *",
        "push_days": 7,
        "push_limit": 8,
        "auto_subscribe_enabled": False,
        "auto_subscribe_notify": True,
        "auto_subscribe_rules": AUTO_SUBSCRIBE_RULES_SAMPLE,
    }

    def init_plugin(self, config: dict = None):
        self._config = copy.deepcopy(self._default_config)
        if config:
            self._config.update(config)
        self._config["enabled"] = bool(self._config.get("enabled", True))
        self._config["push_enabled"] = bool(self._config.get("push_enabled", True))
        self._config["auto_subscribe_enabled"] = bool(self._config.get("auto_subscribe_enabled", False))
        self._config["auto_subscribe_notify"] = bool(self._config.get("auto_subscribe_notify", True))
        self._config["cache_ttl_minutes"] = max(5, safe_int(self._config.get("cache_ttl_minutes"), 180))
        self._config["push_days"] = max(1, safe_int(self._config.get("push_days"), 7))
        self._config["push_limit"] = max(1, safe_int(self._config.get("push_limit"), 8))
        if not str(self._config.get("push_cron") or "").strip():
            self._config["push_cron"] = self._default_config["push_cron"]
        rules = self._config.get("auto_subscribe_rules")
        if isinstance(rules, list):
            self._config["auto_subscribe_rules"] = json.dumps(rules, ensure_ascii=False, indent=2)
        elif not isinstance(rules, str) or not rules.strip():
            self._config["auto_subscribe_rules"] = AUTO_SUBSCRIBE_RULES_SAMPLE
        self._ensure_security_domains()
        self._restore_cache()

    def get_state(self) -> bool:
        return bool(self._config.get("enabled"))

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vue", "ui"

    def get_api(self) -> List[Dict[str, Any]]:
        self._ensure_security_domains()
        return [
            {
                "path": "/upcoming_discover",
                "endpoint": self.upcoming_discover,
                "methods": ["GET"],
                "summary": "待播影视探索源",
                "description": "获取平台聚合的即将上映影视列表。",
            },
            {
                "path": "/upcoming_recommend",
                "endpoint": self.upcoming_recommend,
                "methods": ["GET"],
                "summary": "待播影视推荐源",
                "description": "获取推荐页使用的即将上映影视列表。",
            },
            {
                "path": "/config_state",
                "endpoint": self.config_state,
                "methods": ["GET"],
                "summary": "配置页待播状态",
                "description": "获取配置弹窗所需的筛选选项、统计信息与待播影视卡片。",
                "auth": "bear",
            },
            {
                "path": "/page_filter",
                "endpoint": self.page_set_filter,
                "methods": ["GET"],
                "summary": "更新插件页筛选",
                "description": "更新插件详情页的筛选条件。",
                "auth": "bear",
            },
            {
                "path": "/page_reset_filters",
                "endpoint": self.page_reset_filters,
                "methods": ["GET"],
                "summary": "重置插件页筛选",
                "description": "恢复插件详情页默认筛选。",
                "auth": "bear",
            },
            {
                "path": "/page_refresh",
                "endpoint": self.page_refresh,
                "methods": ["GET"],
                "summary": "刷新待播缓存",
                "description": "立即同步各平台待播数据。",
                "auth": "bear",
            },
            {
                "path": "/page_subscribe",
                "endpoint": self.page_subscribe,
                "methods": ["GET"],
                "summary": "插件页直接订阅",
                "description": "在插件详情页直接订阅待播影视。",
                "auth": "bear",
            },
            {
                "path": "/run_auto_subscribe_once",
                "endpoint": self.run_auto_subscribe_once,
                "methods": ["GET"],
                "summary": "立即执行自动订阅规则",
                "description": "手动执行一次当前自动订阅规则，便于测试规则是否生效。",
                "auth": "bear",
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        return None, copy.deepcopy(self._default_config)

    def get_service(self) -> List[Dict[str, Any]]:
        if not self.get_state():
            return []
        if not self._config.get("push_enabled") and not self._config.get("auto_subscribe_enabled"):
            return []
        cron_expr = str(self._config.get("push_cron") or self._default_config["push_cron"]).strip()
        try:
            trigger = CronTrigger.from_crontab(cron_expr)
        except Exception as err:
            logger.error(f"[UpcomingReleases] 定时 Cron 无效，已回退到默认值: {err}")
            trigger = CronTrigger.from_crontab(self._default_config["push_cron"])
        return [{"id": "upcoming_sync", "name": "待播影视同步", "trigger": trigger, "func": self.sync_and_push}]

    def get_page(self) -> List[dict]:
        # Vue 渲染模式下详情页由远程 Page 组件负责，这里只需安全返回占位数据。
        return []

        items = self._get_items(force_refresh=False)
        filters = self._get_page_filters()
        filtered_items = self._filter_page_items(items, filters)
        display_items = filtered_items[:12]
        feedback = self._get_page_feedback()
        page_api_base = f"plugin/{self.__class__.__name__}"

        platform_counts = []
        type_counts = []
        for key, label in PLATFORM_LABELS.items():
            if key == "all":
                continue
            count = len([item for item in items if item.get("platform") == key])
            platform_counts.append(
                {
                    "component": "VChip",
                    "props": {"class": "mr-2 mb-2", "color": "primary", "variant": "outlined"},
                    "text": f"{label} {count}",
                }
            )
        for key, label in TYPE_LABELS.items():
            if key == "all":
                continue
            count = len([item for item in items if item.get("type_key") == key])
            if count:
                type_counts.append(
                    {
                        "component": "VChip",
                        "props": {"class": "mr-2 mb-2", "color": "success", "variant": "outlined"},
                        "text": f"{label} {count}",
                    }
                )

        page_content = []
        if feedback:
            page_content.append(
                {
                    "component": "VAlert",
                    "props": {"type": feedback.get("type", "info"), "variant": "tonal", "class": "mb-3"},
                    "text": feedback.get("text") or "操作已完成",
                }
            )
        page_content.extend(
            [
                self._build_page_filter_row("平台", "platform", PLATFORM_LABELS, filters.get("platform"), page_api_base, "primary"),
                self._build_page_filter_row("类型", "mtype", PAGE_TYPE_LABELS, filters.get("mtype"), page_api_base, "success"),
                self._build_page_filter_row("时间", "time_range", TIME_LABELS, filters.get("time_range"), page_api_base, "warning"),
                self._build_page_filter_row("地区", "region", PAGE_REGION_LABELS, filters.get("region"), page_api_base, "info"),
                self._build_page_filter_row("题材", "genre", PAGE_GENRE_LABELS, filters.get("genre"), page_api_base, "secondary"),
                {
                    "component": "VRow",
                    "props": {"class": "mb-2"},
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 8},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "text-body-2 mb-2"},
                                    "text": f"当前筛选命中 {len(filtered_items)} 条，展示前 {min(len(display_items), 12)} 条，统一按开播时间升序排列。",
                                }
                            ],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 4},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "d-flex justify-end flex-wrap"},
                                    "content": [
                                        {
                                            "component": "VBtn",
                                            "props": {"class": "mr-2 mb-2", "color": "primary", "variant": "tonal", "size": "small"},
                                            "text": "立即同步",
                                            "events": {"click": {"api": f"{page_api_base}/page_refresh", "method": "GET", "params": {}}},
                                        },
                                        {
                                            "component": "VBtn",
                                            "props": {"class": "mb-2", "color": "default", "variant": "outlined", "size": "small"},
                                            "text": "重置筛选",
                                            "events": {"click": {"api": f"{page_api_base}/page_reset_filters", "method": "GET", "params": {}}},
                                        },
                                    ],
                                }
                            ],
                        },
                    ],
                },
            ]
        )

        if display_items:
            page_content.append(
                {
                    "component": "VRow",
                    "content": [self._build_page_media_card(item, page_api_base) for item in display_items],
                }
            )
        else:
            page_content.append(
                {
                    "component": "VAlert",
                    "props": {"type": "info", "variant": "tonal"},
                    "text": "当前筛选条件下暂无可展示的待播影视，请切换平台、类型、地区或题材后再试。",
                }
            )

        last_refresh = "未同步"
        if self._cache.get("timestamp"):
            last_refresh = datetime.fromtimestamp(self._cache.get("timestamp")).strftime("%Y-%m-%d %H:%M:%S")

        page = [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"class": "mb-4"},
                                "content": [
                                    {"component": "VCardTitle", "text": "插件概览"},
                                    {"component": "VDivider"},
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": f"缓存条目：{len(items)}"},
                                            {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": f"最近刷新：{last_refresh}"},
                                            {"component": "div", "props": {"class": "text-body-2"}, "text": f"定时推送：{'已启用' if self._config.get('push_enabled') else '未启用'} / Cron={self._config.get('push_cron')}"},
                                        ],
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"class": "mb-4"},
                                "content": [
                                    {"component": "VCardTitle", "text": "已知限制"},
                                    {"component": "VDivider"},
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": "探索页可新增“即将上映”筛选源。"},
                                            {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": "推荐页可新增“即将上映”推荐源卡片。"},
                                            {"component": "div", "props": {"class": "text-body-2"}, "text": "推荐页顶部分类标签写死在前端核心代码中，纯插件无法额外插入新的顶部分类。"},
                                        ],
                                    },
                                ],
                            }
                        ],
                    },
                ],
            },
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "text": "平台统计"},
                    {"component": "VDivider"},
                    {"component": "VCardText", "content": platform_counts or [{"component": "div", "text": "暂无平台统计"}]},
                ],
            },
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "text": "类型统计"},
                    {"component": "VDivider"},
                    {"component": "VCardText", "content": type_counts or [{"component": "div", "text": "暂无类型统计"}]},
                ],
            },
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "text": "近期预览"},
                    {"component": "VDivider"},
                    {"component": "VCardText", "content": page_content},
                ],
            },
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "text": "????"},
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "content": [
                            {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": f"当前版本：{self.plugin_version}"},
                            {"component": "div", "props": {"class": "text-body-2"}, "text": f"发布时间：{self.plugin_release_date}"},
                        ],
                    },
                ],
            },
        ]
        if getattr(self, "_recognize_dirty", False):
            self._persist_recognize_cache()
        return page

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        if not self.get_state():
            return
        event_data: DiscoverSourceEventData = event.event_data
        api_path = f"plugin/{self.__class__.__name__}/upcoming_discover?apikey={settings.API_TOKEN}"
        if any(getattr(source, "mediaid_prefix", None) == "upcomingreleases" for source in event_data.extra_sources):
            return
        event_data.extra_sources.append(
            DiscoverMediaSource(
                name="即将上映",
                mediaid_prefix="upcomingreleases",
                api_path=api_path,
                filter_params={"platform": "all", "mtype": "all", "time_range": "all", "region": "all", "genre": "all"},
                filter_ui=self._build_filter_ui(),
            )
        )

    @eventmanager.register(ChainEventType.RecommendSource)
    def recommend_source(self, event: Event):
        if not self.get_state():
            return
        event_data: RecommendSourceEventData = event.event_data
        base = f"plugin/{self.__class__.__name__}/upcoming_recommend?apikey={settings.API_TOKEN}"
        sources = [
            RecommendMediaSource(name="即将上映·电影", api_path=f"{base}&group=movie", type="电影"),
            RecommendMediaSource(name="即将上映·剧集", api_path=f"{base}&group=tv", type="电视剧"),
            RecommendMediaSource(name="即将上映·动漫", api_path=f"{base}&group=anime", type="动漫"),
            RecommendMediaSource(name="即将上映·全平台", api_path=f"{base}&group=all", type="榜单"),
        ]
        existing_paths = {getattr(source, "api_path", None) for source in event_data.extra_sources}
        for source in sources:
            if source.api_path not in existing_paths:
                event_data.extra_sources.append(source)

    @eventmanager.register(ChainEventType.MediaRecognizeConvert)
    def media_recognize_convert(self, event: Event):
        if not self.get_state():
            return
        event_data: MediaRecognizeConvertEventData = event.event_data
        mediaid = str(event_data.mediaid or "")
        if not mediaid.startswith("upcomingreleases:"):
            return
        item = self._find_item_by_mediaid(mediaid.split(":", 1)[1])
        if not item:
            return
        media_dict = self._resolve_media_dict(item, event_data.convert_type)
        if media_dict:
            event_data.media_dict = media_dict

    def upcoming_discover(
        self,
        platform: str = "all",
        mtype: str = "all",
        time_range: str = "all",
        region: str = "all",
        genre: str = "all",
        page: int = 1,
        count: int = 30,
    ) -> List[Dict[str, Any]]:
        items = self._filter_items(
            self._get_items(force_refresh=False),
            platform=platform,
            mtype=mtype,
            time_range=time_range,
            region=region,
            genre=genre,
        )
        page = max(1, safe_int(page, 1))
        count = max(1, min(100, safe_int(count, 30)))
        start = (page - 1) * count
        end = start + count
        payload = [self._to_media_info(item).model_dump() for item in items[start:end]]
        if getattr(self, "_recognize_dirty", False):
            self._persist_recognize_cache()
        return payload

    def upcoming_recommend(
        self,
        group: str = "all",
        platform: str = "all",
        count: int = 20,
    ) -> List[Dict[str, Any]]:
        count = max(1, min(60, safe_int(count, 20)))
        items = self._filter_items(self._get_items(force_refresh=False), platform=platform, time_range="all")
        if group not in RECOMMEND_GROUPS:
            group = "all"
        allowed_types = RECOMMEND_GROUPS[group]
        picked = [item for item in items if item.get("type_key") in allowed_types]
        payload = [self._to_media_info(item).model_dump() for item in picked[:count]]
        if getattr(self, "_recognize_dirty", False):
            self._persist_recognize_cache()
        return payload

    def config_state(
        self,
        platform: str = "all",
        mtype: str = "all",
        time_range: str = "all",
        region: str = "all",
        genre: str = "all",
        limit: int = 24,
        force_refresh: bool = False,
        current_user=Depends(get_current_active_user),
    ) -> Dict[str, Any]:
        username = self._resolve_subscribe_username(getattr(current_user, "name", None))
        filters = self._normalize_browser_filters(
            {
                "platform": platform,
                "mtype": mtype,
                "time_range": time_range,
                "region": region,
                "genre": genre,
            }
        )
        try:
            items = self._get_items(force_refresh=bool(force_refresh))
            state = self._build_browser_state(items, filters, limit=limit, username=username)
            if getattr(self, "_recognize_dirty", False):
                self._persist_recognize_cache()
            return {"success": True, **state}
        except Exception as err:
            logger.error(f"[UpcomingReleases] 配置页状态生成失败: {err}")
            cached_items = []
            if isinstance(getattr(self, "_cache", None), dict):
                cached_items = self._sanitize_items(self._cache.get("items") or [])
            state = self._build_browser_state(cached_items, filters, limit=limit, username=username)
            state["message"] = f"待播数据加载失败：{err}"
            return {"success": False, **state}

    def _normalize_browser_filters(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        current = filters or {}
        return {
            field: self._normalize_page_filter_value(field, current.get(field, default))
            for field, default in PAGE_FILTER_DEFAULTS.items()
        }

    def _build_browser_state(
        self,
        items: List[Dict[str, Any]],
        filters: Dict[str, str],
        limit: int = 24,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        items = self._sanitize_items(items)
        limit = max(1, min(60, safe_int(limit, 24)))
        merged_items = self._merge_browser_items(items)
        filtered_items = self._filter_page_items(items, filters)
        merged_filtered_items = self._merge_browser_items(filtered_items)
        display_items = merged_filtered_items[:limit]
        last_refresh = "未同步"
        if self._cache.get("timestamp"):
            last_refresh = datetime.fromtimestamp(self._cache.get("timestamp")).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "filters": filters,
            "options": {
                "platforms": self._build_browser_option_items(PLATFORM_LABELS),
                "types": self._build_browser_option_items(PAGE_TYPE_LABELS),
                "times": self._build_browser_option_items(TIME_LABELS),
                "regions": self._build_browser_option_items(PAGE_REGION_LABELS),
                "genres": self._build_browser_option_items(PAGE_GENRE_LABELS),
                "rule_types": self._build_browser_option_items(PAGE_TYPE_LABELS, include_all=False),
                "rule_platforms": self._build_browser_option_items(PLATFORM_LABELS, include_all=False),
                "rule_regions": self._build_browser_option_items(PAGE_REGION_LABELS, include_all=False),
                "rule_genres": self._build_browser_option_items(PAGE_GENRE_LABELS, include_all=False),
            },
            "stats": {
                "total": len(merged_items),
                "matched": len(merged_filtered_items),
                "showing": len(display_items),
                "last_refresh": last_refresh,
                "platform_counts": [
                    {
                        "value": key,
                        "label": label,
                        "count": len([item for item in items if item.get("platform") == key]),
                    }
                    for key, label in PLATFORM_LABELS.items()
                    if key != "all"
                ],
                "type_counts": [
                    {
                        "value": key,
                        "label": label,
                        "count": len([item for item in items if item.get("type_key") == key]),
                    }
                    for key, label in TYPE_LABELS.items()
                    if key != "all"
                ],
            },
            "items": [self._serialize_browser_item(item, username=username) for item in display_items],
        }

    def _build_browser_option_items(self, mapping: Dict[str, str], include_all: bool = True) -> List[Dict[str, str]]:
        return [
            {"value": key, "label": value}
            for key, value in mapping.items()
            if include_all or key != "all"
        ]

    def _sanitize_items(self, items: List[Any]) -> List[Dict[str, Any]]:
        return [item for item in (items or []) if isinstance(item, dict)]


    def page_subscribe(self, media_id: str, current_user=Depends(get_current_active_user)) -> Dict[str, Any]:
        item = self._find_item_by_mediaid(media_id)
        if not item:
            self._set_page_feedback("error", "未找到要订阅的待播内容。")
            return {"success": False, "message": "not found"}

        username = self._resolve_subscribe_username(getattr(current_user, "name", None))
        recognition = self._get_cached_recognition(item, populate=True, require_ids=False) or {}
        subscription_status = self._get_item_subscription_status(
            item,
            username=username,
            populate_recognition=True,
            recognition=recognition,
        )
        if subscription_status == "active":
            self._set_page_feedback("info", f"{item.get('title')} 已在订阅列表中。")
            return {"success": True, "message": "exists"}
        if subscription_status == "history":
            self._set_page_feedback("info", f"{item.get('title')} 已在订阅历史中，资源已处理完成。")
            return {"success": True, "message": "completed"}

        subscribe_chain = SubscribeChain()
        resolved_mtype = self._type_key_to_media_type(recognition.get("type_key")) or self._type_key_to_media_type(item.get("type_key")) or MediaType.TV
        resolved_season = self._resolve_item_subscribe_season(item, recognition)
        sid, message = subscribe_chain.add(
            title=item.get("title"),
            year=item.get("year") or "",
            mtype=resolved_mtype,
            tmdbid=safe_int(recognition.get("tmdb_id"), 0) or None,
            doubanid=self._clean_text(recognition.get("douban_id")) or None,
            bangumiid=safe_int(recognition.get("bangumi_id"), 0) or None,
            mediaid=self._make_subscribe_mediaid(item),
            season=resolved_season,
            message=False,
            exist_ok=True,
            source="upcoming page subscribe",
            username=username,
        )
        logger.info(f"[UpcomingReleases] page subscribe result: title={item.get('title')} sid={sid} message={message or ''}")
        release_text = self._format_release_display(item)
        if sid and not self._is_exists_message(message):
            self._set_page_feedback("success", f"已添加订阅：{item.get('title')}（{release_text}）")
            return {"success": True, "message": message or "added"}

        if self._is_exists_message(message):
            claimed = self._claim_subscribe_owner(item=item, username=username)
            if claimed:
                self._set_page_feedback("success", f"已同步订阅状态：{item.get('title')}（{release_text}）")
                return {"success": True, "message": "claimed"}
            warning_message = "发现可能存在识别冲突，未找到可直接对应的订阅记录，请先在搜索页核对后再订阅。"
            self._set_page_feedback("warning", warning_message)
            return {"success": False, "message": warning_message}

        self._set_page_feedback("error", f"{item.get('title')} 订阅失败：{message or '未知原因'}")
        return {"success": False, "message": message or "failed"}

    def _make_subscribe_mediaid(self, item: Dict[str, Any]) -> str:
        return f"upcomingreleases:{item.get('media_id')}"

    def _resolve_subscribe_username(self, username: Optional[str] = None) -> Optional[str]:
        normalized = self._clean_text(username)
        if normalized:
            return normalized
        configured = self._clean_text(self._config.get("subscribe_username"))
        if configured:
            return configured
        return None

    def _get_default_subscribe_username(self) -> Optional[str]:
        configured = self._resolve_subscribe_username(None)
        if configured:
            return configured
        try:
            users = UserOper().list() or []
        except Exception as err:
            logger.warning(f"[UpcomingReleases] ??????????: {err}")
            return None
        for user in users:
            name = self._clean_text(getattr(user, "name", None))
            if name and getattr(user, "is_active", False) and getattr(user, "is_superuser", False):
                return name
        for user in users:
            name = self._clean_text(getattr(user, "name", None))
            if name and getattr(user, "is_active", False):
                return name
        return None

    def _get_subscribe_by_mediaid(self, mediaid: str):
        if not mediaid:
            return None
        subscribe_oper = SubscribeOper()
        mediaid_lookup = getattr(subscribe_oper, "get_by_mediaid", None)
        if callable(mediaid_lookup):
            try:
                result = mediaid_lookup(mediaid)
                if result:
                    return result
            except Exception as err:
                logger.warning(f"[UpcomingReleases] mediaid ??????: {err}")
        try:
            return Subscribe.get_by_mediaid(subscribe_oper._db, mediaid)
        except Exception as err:
            logger.warning(f"[UpcomingReleases] ???? mediaid ????: {err}")
            return None

    def _subscribe_record_matches_username(self, subscribe, username: Optional[str] = None) -> bool:
        normalized_username = self._resolve_subscribe_username(username)
        if not normalized_username:
            return True
        current_username = self._resolve_subscribe_username(getattr(subscribe, "username", None))
        return not current_username or current_username == normalized_username

    def _normalize_compare_text(self, text: Optional[str]) -> str:
        return re.sub(r"\s+", "", self._clean_text(text)).lower()

    def _find_existing_subscribe(
        self,
        item: Dict[str, Any],
        username: Optional[str] = None,
        populate_recognition: bool = False,
        recognition: Optional[Dict[str, Any]] = None,
    ):
        mediaid = self._make_subscribe_mediaid(item)
        record = self._get_subscribe_by_mediaid(mediaid)
        if record and self._subscribe_record_matches_username(record, username=username):
            return record

        expected_title = self._normalize_compare_text(item.get("title"))
        if not expected_title:
            return None
        expected_year = self._clean_text(item.get("year"))
        recognition = recognition or self._get_cached_recognition(
            item,
            populate=populate_recognition,
            require_ids=False,
        ) or {}
        type_candidates = self._get_item_type_candidates(item, recognition)
        resolved_season = self._resolve_item_subscribe_season(item, recognition)
        subscribe_oper = SubscribeOper()

        lookup_args = []
        tmdb_id = safe_int(recognition.get("tmdb_id"), 0)
        douban_id = self._clean_text(recognition.get("douban_id"))
        bangumi_id = safe_int(recognition.get("bangumi_id"), 0)
        if tmdb_id:
            lookup_args.append({"tmdbid": tmdb_id})
        if douban_id:
            lookup_args.append({"doubanid": douban_id})
        if bangumi_id:
            lookup_args.append({"bangumiid": bangumi_id})

        for type_key in type_candidates:
            expected_type, expected_season = self._type_key_to_subscribe_lookup(type_key, resolved_season)
            for lookup in lookup_args:
                try:
                    record = subscribe_oper.get_by(type=expected_type, season=expected_season, **lookup)
                except Exception as err:
                    logger.warning(f"[UpcomingReleases] subscribe ID lookup failed: {lookup} - {err}")
                    record = None
                if record and self._subscribe_record_matches_username(record, username=username):
                    return record

        try:
            subscribes = subscribe_oper.list() or []
        except Exception as err:
            logger.warning(f"[UpcomingReleases] direct subscribe lookup failed: {err}")
            return None

        for type_key in type_candidates:
            expected_type, expected_season = self._type_key_to_subscribe_lookup(type_key, resolved_season)
            for subscribe in subscribes:
                if not self._subscribe_record_matches_username(subscribe, username=username):
                    continue
                if self._clean_text(getattr(subscribe, "type", None)) != expected_type:
                    continue
                if self._normalize_compare_text(getattr(subscribe, "name", None)) != expected_title:
                    continue
                subscribe_year = self._clean_text(getattr(subscribe, "year", None))
                if expected_year and subscribe_year and subscribe_year != expected_year:
                    continue
                subscribe_season = getattr(subscribe, "season", None)
                if expected_season is not None and subscribe_season not in {None, expected_season}:
                    continue
                return subscribe
        return None

    def _get_page_filters(self) -> Dict[str, str]:
        filters = copy.deepcopy(PAGE_FILTER_DEFAULTS)
        stored = self.get_data("page_filters")
        if isinstance(stored, dict):
            for field in filters:
                filters[field] = self._normalize_page_filter_value(field, stored.get(field, filters[field]))
        return filters

    def _normalize_page_filter_value(self, field: str, value: Any) -> str:
        option_map = {
            "platform": PLATFORM_LABELS,
            "mtype": PAGE_TYPE_LABELS,
            "time_range": TIME_LABELS,
            "region": PAGE_REGION_LABELS,
            "genre": PAGE_GENRE_LABELS,
        }
        raw_value = self._clean_text(value or "all")
        if field in {"platform", "mtype", "time_range"}:
            raw_value = raw_value.lower()
        elif field == "genre" and raw_value != "all":
            normalized = sorted(self._normalize_genre_values([raw_value]))
            raw_value = normalized[0] if normalized else "all"
        if raw_value in option_map.get(field, {}):
            return raw_value
        return PAGE_FILTER_DEFAULTS.get(field, "all")

    def _get_page_feedback(self) -> Dict[str, str]:
        feedback = self.get_data("page_feedback")
        if isinstance(feedback, dict) and feedback.get("text"):
            return feedback
        return {}

    def _set_page_feedback(self, level: str, text: str):
        self.save_data(
            "page_feedback",
            {"type": level if level in {"success", "info", "warning", "error"} else "info", "text": text},
        )

    def _filter_page_items(self, items: List[Dict[str, Any]], filters: Dict[str, str]) -> List[Dict[str, Any]]:
        filtered = []
        for item in items:
            if filters.get("platform") != "all" and item.get("platform") != filters.get("platform"):
                continue
            if filters.get("mtype") != "all" and not self._match_rule_types(item, [filters.get("mtype")]):
                continue
            if not self._match_time_filter(item, filters.get("time_range") or "all"):
                continue
            if filters.get("region") not in {None, "", "all"} and not self._match_rule_regions(item, [filters.get("region")]):
                continue
            if filters.get("genre") not in {None, "", "all"} and not self._match_rule_genres(item, [filters.get("genre")]):
                continue
            filtered.append(item)
        return filtered

    def _build_page_filter_row(
        self,
        label: str,
        field: str,
        options: Dict[str, str],
        current_value: str,
        page_api_base: str,
        color: str,
    ) -> Dict[str, Any]:
        chips = []
        for value, text_value in options.items():
            is_active = current_value == value
            chips.append(
                {
                    "component": "VChip",
                    "props": {
                        "class": "mr-2 mb-2",
                        "color": color if is_active else "default",
                        "variant": "flat" if is_active else "outlined",
                        "size": "small",
                    },
                    "text": text_value,
                    "events": {
                        "click": {
                            "api": f"{page_api_base}/page_filter",
                            "method": "GET",
                            "params": {"field": field, "value": value},
                        }
                    },
                }
            )
        return {
            "component": "div",
            "props": {"class": "mb-2"},
            "content": [
                {"component": "div", "props": {"class": "text-subtitle-2 mb-2"}, "text": label},
                {"component": "div", "props": {"class": "d-flex flex-wrap"}, "content": chips},
            ],
        }

    def _build_page_media_card(self, item: Dict[str, Any], page_api_base: str) -> Dict[str, Any]:
        subscription_status = self._get_item_subscription_status(item, populate_recognition=True)
        subscribed = subscription_status != "none"
        region_text = self._get_item_region_text(item)
        genre_text = self._get_item_genre_text(item)
        story_text = self._clean_text(item.get("story"))
        if len(story_text) > 72:
            story_text = f"{story_text[:72].rstrip()}..."

        status_chip_map = {
            "active": {"color": "success", "text": "\u5df2\u8ba2\u9605"},
            "history": {"color": "info", "text": "\u5df2\u5b8c\u6210"},
        }
        status_button_map = {
            "active": {"color": "success", "variant": "tonal", "prependIcon": "mdi-check-circle", "text": "\u5df2\u8ba2\u9605"},
            "history": {"color": "info", "variant": "tonal", "prependIcon": "mdi-archive-check", "text": "\u5df2\u5b8c\u6210"},
            "none": {"color": "primary", "variant": "flat", "prependIcon": "mdi-bell-plus", "text": "\u7acb\u5373\u8ba2\u9605"},
        }
        button_meta = status_button_map.get(subscription_status, status_button_map["none"])

        chips = [
            {
                "component": "VChip",
                "props": {"class": "mr-2 mb-2", "color": "primary", "size": "small", "variant": "tonal"},
                "text": item.get("platform_label"),
            },
            {
                "component": "VChip",
                "props": {"class": "mr-2 mb-2", "color": "success", "size": "small", "variant": "tonal"},
                "text": item.get("type_label"),
            },
        ]
        if subscription_status in status_chip_map:
            chips.append(
                {
                    "component": "VChip",
                    "props": {
                        "class": "mr-2 mb-2",
                        "color": status_chip_map[subscription_status]["color"],
                        "size": "small",
                        "variant": "flat",
                    },
                    "text": status_chip_map[subscription_status]["text"],
                }
            )
        if item.get("time_key") in TIME_LABELS and item.get("time_key") != "all":
            chips.append(
                {
                    "component": "VChip",
                    "props": {"class": "mr-2 mb-2", "color": "warning", "size": "small", "variant": "tonal"},
                    "text": TIME_LABELS.get(item.get("time_key"), item.get("time_key")),
                }
            )
        reserve_count = safe_int(item.get("reserve_count"), 0)
        if reserve_count > 0:
            chips.append(
                {
                    "component": "VChip",
                    "props": {"class": "mb-2", "color": "info", "size": "small", "variant": "outlined"},
                    "text": f"\u9884\u7ea6 {reserve_count:,}",
                }
            )

        card_content = [
            {"component": "VImg", "props": {"src": item.get("poster"), "height": 260, "cover": True}}
            if item.get("poster")
            else {
                "component": "div",
                "props": {
                    "class": "d-flex align-center justify-center text-subtitle-1 bg-grey-lighten-3 text-medium-emphasis",
                    "style": "height: 260px; padding: 12px; text-align: center;",
                },
                "text": item.get("title"),
            },
            {
                "component": "VCardItem",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": item.get("title"),
                    },
                    {
                        "component": "VCardSubtitle",
                        "text": f"{self._format_release_display(item)} | {region_text}",
                    },
                ],
            },
            {
                "component": "VCardText",
                "content": [
                    {"component": "div", "props": {"class": "d-flex flex-wrap mb-2"}, "content": chips},
                    {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": f"\u9898\u6750\uff1a{genre_text}"},
                    {"component": "div", "props": {"class": "text-body-2"}, "text": story_text or "\u6682\u65e0\u7b80\u4ecb"},
                ],
            },
            {
                "component": "VCardActions",
                "content": [
                    {
                        "component": "VBtn",
                        "props": {
                            "color": button_meta["color"],
                            "variant": button_meta["variant"],
                            "prependIcon": button_meta["prependIcon"],
                            "size": "small",
                            "disabled": subscribed,
                        },
                        "text": button_meta["text"],
                        "events": (
                            {
                                "click": {
                                    "api": f"{page_api_base}/subscribe",
                                    "method": "GET",
                                    "params": {"media_id": item.get("media_id")},
                                }
                            }
                            if not subscribed
                            else None
                        ),
                    },
                    {
                        "component": "VBtn",
                        "props": {"variant": "text", "href": item.get("detail_link") or None, "target": "_blank", "size": "small"},
                        "text": "\u67e5\u770b\u8be6\u60c5",
                    },
                ],
            },
        ]
        return {"component": "VCol", "props": {"cols": 12, "md": 6, "lg": 4}, "content": [{"component": "VCard", "content": card_content}]}

    def _is_exists_message(self, message: Any) -> bool:
        text_value = self._clean_text(message).lower()
        return "已存在" in text_value or "exists" in text_value

    def _claim_subscribe_owner(self, item: Dict[str, Any], username: Optional[str]) -> bool:
        target_username = self._resolve_subscribe_username(username)
        subscribe = self._find_existing_subscribe(item, username=username, populate_recognition=True)
        if not subscribe:
            return False
        current_username = self._resolve_subscribe_username(getattr(subscribe, "username", None))
        if current_username and target_username and current_username != target_username:
            return False

        payload = {}
        expected_mediaid = self._make_subscribe_mediaid(item)
        current_mediaid = self._clean_text(getattr(subscribe, "mediaid", None))
        if target_username and not current_username:
            payload["username"] = target_username
        if not current_mediaid:
            payload["mediaid"] = expected_mediaid

        if payload:
            try:
                SubscribeOper().update(subscribe.id, payload)
            except Exception as err:
                logger.warning(f"[UpcomingReleases] subscribe claim failed: {err}")
                return False
        return True

    def _get_item_type_candidates(
        self,
        item: Dict[str, Any],
        recognition: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        values = []
        for value in [
            (recognition or {}).get("type_key"),
            item.get("type_key"),
        ]:
            normalized = self._clean_text(value).lower()
            if normalized and normalized in TYPE_LABELS and normalized not in values and normalized != "all":
                values.append(normalized)
        return values or ["tv"]

    def _resolve_item_subscribe_season(
        self,
        item: Dict[str, Any],
        recognition: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        type_key = self._clean_text((recognition or {}).get("type_key") or item.get("type_key")).lower()
        if self._type_key_to_media_type(type_key) != MediaType.TV:
            return None
        title = self._clean_text(item.get("title"))
        if not title:
            return 1
        try:
            season = MetaInfo(title).begin_season
        except Exception as err:
            logger.warning(f"[UpcomingReleases] parse subscribe season failed: {title} - {err}")
            season = None
        return season or 1

    def _type_key_to_media_type(self, type_key: Optional[str]) -> Optional[MediaType]:
        normalized = self._clean_text(type_key).lower()
        if normalized == "movie":
            return MediaType.MOVIE
        if normalized in {"tv", "anime", "variety", "short", "documentary", "kids", "humanity"}:
            return MediaType.TV
        return None

    def _type_key_to_subscribe_lookup(self, type_key: Optional[str], season: Optional[int] = None) -> Tuple[str, Optional[int]]:
        media_type = self._type_key_to_media_type(type_key)
        if media_type == MediaType.MOVIE:
            return MediaType.MOVIE.value, None
        return MediaType.TV.value, season or 1

    def _list_subscribe_history(self) -> List[Any]:
        db = ScopedSession()
        try:
            return db.query(SubscribeHistory).all() or []
        except Exception as err:
            logger.warning(f"[UpcomingReleases] subscribe history lookup failed: {err}")
            return []
        finally:
            try:
                db.close()
            finally:
                ScopedSession.remove()

    def _get_subscribe_history_by_mediaid(self, mediaid: str):
        if not mediaid:
            return None
        db = ScopedSession()
        try:
            return (
                db.query(SubscribeHistory)
                .filter(SubscribeHistory.mediaid == mediaid)
                .first()
            )
        except Exception as err:
            logger.warning(f"[UpcomingReleases] subscribe history mediaid lookup failed: {err}")
            return None
        finally:
            try:
                db.close()
            finally:
                ScopedSession.remove()

    def _find_existing_subscribe_history(
        self,
        item: Dict[str, Any],
        username: Optional[str] = None,
        populate_recognition: bool = False,
        recognition: Optional[Dict[str, Any]] = None,
    ):
        mediaid = self._make_subscribe_mediaid(item)
        record = self._get_subscribe_history_by_mediaid(mediaid)
        if record and self._subscribe_record_matches_username(record, username=username):
            return record

        expected_title = self._normalize_compare_text(item.get("title"))
        if not expected_title:
            return None
        expected_year = self._clean_text(item.get("year"))
        recognition = recognition or self._get_cached_recognition(
            item,
            populate=populate_recognition,
            require_ids=False,
        ) or {}
        type_candidates = self._get_item_type_candidates(item, recognition)
        resolved_season = self._resolve_item_subscribe_season(item, recognition)
        tmdb_id = safe_int(recognition.get("tmdb_id"), 0)
        douban_id = self._clean_text(recognition.get("douban_id"))
        bangumi_id = safe_int(recognition.get("bangumi_id"), 0)
        histories = self._list_subscribe_history()
        if not histories:
            return None

        for type_key in type_candidates:
            expected_type, expected_season = self._type_key_to_subscribe_lookup(type_key, resolved_season)
            for history in histories:
                if not self._subscribe_record_matches_username(history, username=username):
                    continue
                if self._clean_text(getattr(history, "type", None)) != expected_type:
                    continue
                history_season = getattr(history, "season", None)
                if tmdb_id and getattr(history, "tmdbid", None) == tmdb_id:
                    if expected_season is None or history_season in {None, expected_season}:
                        return history
                if douban_id and self._clean_text(getattr(history, "doubanid", None)) == douban_id:
                    if expected_season is None or history_season in {None, expected_season}:
                        return history
                if bangumi_id and safe_int(getattr(history, "bangumiid", None), 0) == bangumi_id:
                    if expected_season is None or history_season in {None, expected_season}:
                        return history

        for type_key in type_candidates:
            expected_type, expected_season = self._type_key_to_subscribe_lookup(type_key, resolved_season)
            for history in histories:
                if not self._subscribe_record_matches_username(history, username=username):
                    continue
                if self._clean_text(getattr(history, "type", None)) != expected_type:
                    continue
                if self._normalize_compare_text(getattr(history, "name", None)) != expected_title:
                    continue
                history_year = self._clean_text(getattr(history, "year", None))
                if expected_year and history_year and history_year != expected_year:
                    continue
                history_season = getattr(history, "season", None)
                if expected_season is not None and history_season not in {None, expected_season}:
                    continue
                return history
        return None

    def _get_item_subscription_status(
        self,
        item: Dict[str, Any],
        username: Optional[str] = None,
        populate_recognition: bool = False,
        recognition: Optional[Dict[str, Any]] = None,
    ) -> str:
        recognition = recognition or self._get_cached_recognition(
            item,
            populate=populate_recognition,
            require_ids=False,
        ) or {}
        if self._find_existing_subscribe(
            item,
            username=username,
            populate_recognition=populate_recognition,
            recognition=recognition,
        ):
            return "active"
        if self._find_existing_subscribe_history(
            item,
            username=username,
            populate_recognition=populate_recognition,
            recognition=recognition,
        ):
            return "history"
        return "none"

    def _is_item_subscribed(
        self,
        item: Dict[str, Any],
        username: Optional[str] = None,
        populate_recognition: bool = False,
    ) -> bool:
        try:
            return self._get_item_subscription_status(
                item,
                username=username,
                populate_recognition=populate_recognition,
            ) != "none"
        except Exception as err:
            logger.warning(f"[UpcomingReleases] subscribe status check failed: {err}")
            return False

    def _format_release_display(self, item: Dict[str, Any]) -> str:
        release_date = self._clean_text(item.get("release_date"))
        release_text = self._clean_text(item.get("release_text"))
        time_match = re.search(r"(\d{1,2}:\d{2})", release_text)
        if release_date:
            if time_match:
                return f"{release_date} {time_match.group(1)}"
            return release_date
        if release_text:
            return release_text
        return "??"

    def _get_item_region_text(self, item: Dict[str, Any]) -> str:
        record = self._get_cached_recognition(item, populate=True, require_ids=False)
        labels = []
        for code in record.get("country_codes") or []:
            label = REGION_CODE_LABELS.get(str(code).upper(), str(code).upper())
            if label not in labels:
                labels.append(label)
        return " / ".join(labels[:3]) if labels else "待识别"

    def _get_item_genre_text(self, item: Dict[str, Any]) -> str:
        record = self._get_cached_recognition(item, populate=True, require_ids=False)
        labels = []
        for genre_name in record.get("genre_names") or []:
            text_value = self._clean_text(genre_name)
            if text_value and text_value not in labels:
                labels.append(text_value)
        if labels:
            return " / ".join(labels[:4])
        type_fallback = {
            "movie": "电影",
            "tv": "剧集",
            "anime": "动画",
            "variety": "综艺",
            "documentary": "纪录片",
            "kids": "少儿",
            "humanity": "人文",
            "short": "短剧",
        }
        resolved_type = self._get_item_type_candidates(item, record)[0]
        return type_fallback.get(resolved_type, "待识别")


    def _make_browser_group_key(self, item: Dict[str, Any]) -> Tuple[str, str]:
        title_key = self._normalize_compare_text(item.get("title"))
        type_key = self._clean_text(item.get("type_key") or "").lower() or "unknown"
        return title_key, type_key

    def _merge_browser_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for item in self._sanitize_items(items):
            key = self._make_browser_group_key(item)
            if not key[0]:
                continue
            merged_groups.setdefault(key, []).append(item)
        return [self._merge_browser_group(group_items) for group_items in merged_groups.values()]

    def _merge_browser_group(self, group_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        ranked_items = sorted(
            group_items,
            key=lambda item: (
                1 if item.get("poster") else 0,
                safe_int(item.get("reserve_count"), 0),
                len(self._clean_text(item.get("story"))),
            ),
            reverse=True,
        )
        primary = copy.deepcopy(ranked_items[0])
        platform_values = []
        platform_labels = []
        detail_links = []
        stories = []
        reserve_count = 0
        for item in group_items:
            platform = self._clean_text(item.get("platform"))
            platform_label = self._clean_text(item.get("platform_label"))
            detail_link = self._clean_text(item.get("detail_link"))
            story_text = self._clean_text(item.get("story"))
            reserve_count = max(reserve_count, safe_int(item.get("reserve_count"), 0))
            if platform and platform not in platform_values:
                platform_values.append(platform)
            if platform_label and platform_label not in platform_labels:
                platform_labels.append(platform_label)
            if detail_link and detail_link not in detail_links:
                detail_links.append(detail_link)
            if story_text:
                stories.append(story_text)
        primary["platform"] = platform_values[0] if platform_values else primary.get("platform")
        primary["platform_label"] = " / ".join(platform_labels) if platform_labels else primary.get("platform_label")
        primary["platforms"] = platform_values
        primary["platform_labels"] = platform_labels
        primary["detail_link"] = detail_links[0] if detail_links else primary.get("detail_link")
        primary["detail_links"] = detail_links
        primary["reserve_count"] = reserve_count
        if stories:
            primary["story"] = max(stories, key=len)
        return primary

    def _serialize_browser_item(self, item: Dict[str, Any], username: Optional[str] = None) -> Dict[str, Any]:
        story_text = self._clean_text(item.get("story"))
        if len(story_text) > 140:
            story_text = f"{story_text[:140].rstrip()}..."
        time_key = item.get("time_key")
        recognition = self._get_cached_recognition(item, populate=True, require_ids=False) or {}
        subscription_status = self._get_item_subscription_status(
            item,
            username=username,
            recognition=recognition,
        )
        return {
            "media_id": item.get("media_id"),
            "title": item.get("title"),
            "year": item.get("year"),
            "poster": item.get("poster"),
            "detail_link": item.get("detail_link"),
            "platform": item.get("platform"),
            "platform_label": item.get("platform_label"),
            "platforms": item.get("platforms") or ([item.get("platform")] if item.get("platform") else []),
            "platform_labels": item.get("platform_labels") or ([item.get("platform_label")] if item.get("platform_label") else []),
            "type_key": item.get("type_key"),
            "type_label": item.get("type_label"),
            "time_key": time_key,
            "time_label": TIME_LABELS.get(time_key) if time_key and time_key != "all" else "",
            "release_display": self._format_release_display(item),
            "release_date": item.get("release_date"),
            "release_text": item.get("release_text"),
            "region_text": self._get_item_region_text(item),
            "genre_text": self._get_item_genre_text(item),
            "story": story_text,
            "reserve_count": safe_int(item.get("reserve_count"), 0),
            "subscribed": subscription_status != "none",
            "subscription_status": subscription_status,
            "subscription_label": "已完成" if subscription_status == "history" else ("已订阅" if subscription_status == "active" else ""),
        }

    def page_set_filter(self, field: str, value: str = "all") -> Dict[str, Any]:
        if field not in PAGE_FILTER_DEFAULTS:
            self._set_page_feedback("error", "无效的筛选字段。")
            return {"success": False, "message": "invalid field"}
        filters = self._get_page_filters()
        filters[field] = self._normalize_page_filter_value(field, value)
        self.save_data("page_filters", filters)
        self.save_data("page_feedback", None)
        return {"success": True, "message": "ok"}

    def page_reset_filters(self) -> Dict[str, Any]:
        self.save_data("page_filters", copy.deepcopy(PAGE_FILTER_DEFAULTS))
        self.save_data("page_feedback", None)
        return {"success": True, "message": "ok"}

    def page_refresh(self) -> Dict[str, Any]:
        items = self._get_items(force_refresh=True)
        self._set_page_feedback("success", f"已同步最新待播数据，共 {len(items)} 条。")
        if getattr(self, "_recognize_dirty", False):
            self._persist_recognize_cache()
        return {"success": True, "count": len(items)}

    def run_auto_subscribe_once(self) -> Dict[str, Any]:
        if not self.get_state():
            return {"success": False, "message": "插件未启用，无法执行自动订阅规则。"}
        try:
            items = self._get_items(force_refresh=True)
            summary = self._run_auto_subscribe(items)
            added = summary.get("added") or []
            existing = summary.get("existing") or []
            failed = summary.get("failed") or []
            if self._config.get("auto_subscribe_notify") and (added or existing or failed):
                self._post_auto_subscribe_summary(summary, manual=True)
            if getattr(self, "_recognize_dirty", False):
                self._persist_recognize_cache()
            return {
                "success": True,
                "message": f"执行完成：新增 {len(added)} 条，已存在 {len(existing)} 条，失败 {len(failed)} 条。",
                "count": len(items),
                "added_count": len(added),
                "existing_count": len(existing),
                "failed_count": len(failed),
                "summary": summary,
            }
        except Exception as err:
            logger.error(f"[UpcomingReleases] 手动执行自动订阅失败: {err}")
            return {"success": False, "message": f"执行失败：{err}"}

    def _post_auto_subscribe_summary(self, summary: Dict[str, List[str]], manual: bool = False):
        added = summary.get("added") or []
        existing = summary.get("existing") or []
        failed = summary.get("failed") or []
        lines = ["待播自动订阅执行结果："]
        if added:
            lines.append(f"新增订阅 {len(added)} 条：")
            for item in added[:10]:
                lines.append(f"- {item}")
        if existing:
            lines.append(f"已存在 {len(existing)} 条：")
            for item in existing[:10]:
                lines.append(f"- {item}")
        if failed:
            lines.append(f"失败 {len(failed)} 条：")
            for item in failed[:10]:
                lines.append(f"- {item}")
        self.post_message(
            mtype=NotificationType.Plugin,
            title="待播自动订阅结果（手动执行）" if manual else "待播自动订阅结果",
            text="\n".join(lines),
        )

    def sync_and_push(self):
        if not self.get_state():
            return
        items = self._get_items(force_refresh=True)
        auto_summary = None
        if self._config.get("auto_subscribe_enabled"):
            auto_summary = self._run_auto_subscribe(items)

        if self._config.get("push_enabled"):
            days = max(1, safe_int(self._config.get("push_days"), 7))
            limit = max(1, safe_int(self._config.get("push_limit"), 8))
            push_items = [item for item in items if self._is_within_days(item, days)]
            for item in self._filter_items(items, time_range="pending"):
                if len(push_items) >= limit:
                    break
                if item not in push_items:
                    push_items.append(item)
            push_items = push_items[:limit]
            if push_items:
                signature = "|".join(f"{item.get('media_id')}:{item.get('release_date') or item.get('release_text')}" for item in push_items)
                if signature and signature != self.get_data("last_push_signature"):
                    lines = [f"未来 {days} 天待播提醒："]
                    for item in push_items:
                        lines.append(f"- {item.get('release_text') or '敬请期待'} | {item.get('platform_label')} | {item.get('type_label')} | {item.get('title')}")
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="待播影视提醒",
                        text="\n".join(lines),
                        image=push_items[0].get("poster"),
                        link=push_items[0].get("detail_link") or None,
                    )
                    self.save_data("last_push_signature", signature)
            else:
                logger.info("[UpcomingReleases] 当前没有符合推送条件的待播内容")

        if auto_summary and self._config.get("auto_subscribe_notify") and (auto_summary.get("added") or auto_summary.get("failed") or auto_summary.get("existing")):
            self._post_auto_subscribe_summary(auto_summary)

        if getattr(self, "_recognize_dirty", False):
            self._persist_recognize_cache()
    def stop_service(self):
        if getattr(self, "_recognize_dirty", False):
            self._persist_recognize_cache()

    def _ensure_runtime_state(self):
        if not isinstance(getattr(self, "_cache", None), dict):
            self._cache = {"timestamp": 0, "items": []}
        if not isinstance(getattr(self, "_recognize_cache", None), dict):
            self._recognize_cache = {}
        if not hasattr(self, "_recognize_dirty"):
            self._recognize_dirty = False

    def _get_items(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        self._ensure_runtime_state()
        if not self.get_state():
            return []
        ttl_seconds = max(300, safe_int(self._config.get("cache_ttl_minutes"), 180) * 60)
        now_ts = time.time()
        if (
            not force_refresh
            and self._cache.get("items")
            and now_ts - safe_int(self._cache.get("timestamp"), 0) < ttl_seconds
        ):
            return self._sanitize_items(self._cache.get("items") or [])
        try:
            items: List[Dict[str, Any]] = []
            if self._config.get("enable_iqiyi"):
                items.extend(self._safe_fetch("爱奇艺", self._fetch_iqiyi))
            if self._config.get("enable_tencent"):
                items.extend(self._safe_fetch("腾讯视频", self._fetch_tencent))
            if self._config.get("enable_youku"):
                items.extend(self._safe_fetch("优酷", self._fetch_youku))
            if self._config.get("enable_mgtv"):
                items.extend(self._safe_fetch("芒果TV", self._fetch_mgtv))
            items = self._finalize_items(items)
            self._cache = {"timestamp": now_ts, "items": items}
            try:
                self._persist_cache()
            except Exception as err:
                logger.error(f"[UpcomingReleases] 缓存写入失败: {err}")
            if self._recognize_dirty:
                try:
                    self._persist_recognize_cache()
                except Exception as err:
                    logger.error(f"[UpcomingReleases] 识别缓存写入失败: {err}")
            return self._sanitize_items(items)
        except Exception as err:
            logger.error(f"[UpcomingReleases] 待播数据汇总失败: {err}")
            return self._sanitize_items(self._cache.get("items") or [])

    def _safe_fetch(self, label: str, fetcher) -> List[Dict[str, Any]]:
        try:
            return fetcher() or []
        except Exception as err:
            logger.error(f"[UpcomingReleases] 抓取 {label} 失败: {err}")
            return []

    def _finalize_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        seen = set()
        today = datetime.now().date()
        for item in items:
            if not item or not item.get("title"):
                continue
            release_date = item.get("release_date")
            if release_date:
                try:
                    release_dt = datetime.strptime(release_date, "%Y-%m-%d").date()
                    if release_dt < today:
                        continue
                except ValueError:
                    pass
            dedup_key = (item.get("platform"), item.get("title"), item.get("release_date") or item.get("release_text"))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            item["platform_label"] = PLATFORM_LABELS.get(item.get("platform"), item.get("platform") or "")
            item["type_label"] = TYPE_LABELS.get(item.get("type_key"), "电视剧")
            item["time_key"] = self._compute_time_key(item.get("release_date"))
            result.append(item)
        result.sort(key=lambda item: (0 if item.get("release_date") else 1, item.get("release_date") or item.get("release_text") or "9999-12-31", item.get("title") or ""))
        return result

    def _filter_items(
        self,
        items: List[Dict[str, Any]],
        platform: str = "all",
        mtype: str = "all",
        time_range: str = "all",
        region: str = "all",
        genre: str = "all",
    ) -> List[Dict[str, Any]]:
        filtered = []
        for item in items:
            if platform != "all" and item.get("platform") != platform:
                continue
            if mtype != "all" and item.get("type_key") != mtype:
                continue
            if not self._match_time_filter(item, time_range):
                continue
            if region not in {None, "", "all"} and not self._match_rule_regions(item, [region]):
                continue
            if genre not in {None, "", "all"} and not self._match_rule_genres(item, [genre]):
                continue
            filtered.append(item)
        return filtered

    def _match_time_filter(self, item: Dict[str, Any], time_range: str) -> bool:
        if time_range == "all":
            return True
        if time_range == "pending":
            return not item.get("release_date")
        release_date = item.get("release_date")
        if not release_date:
            return False
        try:
            release_dt = datetime.strptime(release_date, "%Y-%m-%d").date()
        except ValueError:
            return False
        delta = (release_dt - datetime.now().date()).days
        if time_range == "today":
            return delta == 0
        if time_range == "tomorrow":
            return delta == 1
        if time_range == "3days":
            return 0 <= delta <= 3
        if time_range == "7days":
            return 0 <= delta <= 7
        if time_range == "30days":
            return 0 <= delta <= 30
        return True

    def _is_within_days(self, item: Dict[str, Any], days: int) -> bool:
        release_date = item.get("release_date")
        if not release_date:
            return False
        try:
            release_dt = datetime.strptime(release_date, "%Y-%m-%d").date()
        except ValueError:
            return False
        delta = (release_dt - datetime.now().date()).days
        return 0 <= delta <= days

    def _to_media_info(self, item: Dict[str, Any]) -> MediaInfo:
        media_type = MediaType.MOVIE.value if item.get("type_key") == "movie" else MediaType.TV.value
        summary = f"{item.get('platform_label')} / {item.get('type_label')}"
        if item.get("release_text"):
            summary = f"{summary} / {item.get('release_text')}"
        overview = item.get("story") or ""
        overview = f"{summary}\n{overview}" if overview else summary
        # Warm recognition cache for later detail/subscribe conversion, but keep
        # discover/recommend cards on the custom upcomingreleases: mediaid path.
        self._get_cached_recognition(item, populate=True)
        return MediaInfo(
            source="upcomingreleases",
            type=media_type,
            title=item.get("title"),
            year=item.get("year"),
            title_year=build_title_year(item.get("title"), item.get("year")),
            mediaid_prefix="upcomingreleases",
            media_id=item.get("media_id"),
            tmdb_id=None,
            douban_id=None,
            bangumi_id=None,
            release_date=item.get("release_date"),
            first_air_date=item.get("release_date") if media_type == MediaType.TV.value else None,
            poster_path=item.get("poster"),
            backdrop_path=item.get("poster"),
            overview=overview,
            category=f"{item.get('platform_label')} / {item.get('type_label')}",
            detail_link=item.get("detail_link"),
            tagline=item.get("release_text"),
            vote_count=safe_int(item.get("reserve_count"), 0),
        )

    def _get_cached_recognition(
        self,
        item: Dict[str, Any],
        populate: bool = False,
        require_ids: bool = True,
    ) -> Dict[str, Any]:
        lookup_key = self._make_lookup_key(item.get("title"), item.get("year"), item.get("type_key"))
        for key in [item.get("media_id"), lookup_key]:
            record = self._recognize_cache.get(key) if key else None
            if record and (
                record.get("recognition_failed")
                or not require_ids
                or record.get("tmdb_id")
                or record.get("douban_id")
                or record.get("bangumi_id")
            ):
                return record
        if not populate:
            return {}
        media = self._recognize_item(item)
        if not media:
            fallback = self._build_text_fallback_recognition(item)
            self._store_recognition_record(item, fallback)
            return fallback
        type_key = self._media_to_type_key(media)
        self._cache_recognition(item, media, type_key)
        for key in [item.get("media_id"), lookup_key]:
            record = self._recognize_cache.get(key) if key else None
            if record:
                return record
        return {}

    def _is_failed_recognition_record(self, record: Optional[Dict[str, Any]]) -> bool:
        return bool(record and record.get("recognition_failed"))

    def _get_cached_recognition_record(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        lookup_key = self._make_lookup_key(item.get("title"), item.get("year"), item.get("type_key"))
        for key in [item.get("media_id"), lookup_key]:
            if key and key in self._recognize_cache:
                return self._recognize_cache.get(key)
        return None

    def _fetch_iqiyi(self) -> List[Dict[str, Any]]:
        html = self._request_text("https://www.iqiyi.com/newOnlinePCW", headers={"Referer": "https://www.iqiyi.com/"})
        if not html:
            return []
        start_index = html.find("allVideos:[")
        if start_index < 0:
            logger.warning("[UpcomingReleases] iqiyi page missing allVideos payload")
            return []
        array_start = html.find("[", start_index)
        payload = self._extract_bracket_array(html, array_start) if array_start >= 0 else None
        if not payload:
            logger.warning("[UpcomingReleases] iqiyi allVideos array is incomplete")
            return []
        items = []
        cursor = payload.find("{")
        while cursor >= 0:
            obj_text = self._extract_brace_object(payload, cursor)
            if not obj_text:
                break
            title = self._clean_text(self._extract_js_string_field(obj_text, "name"))
            publish_text = self._clean_text(self._extract_js_string_field(obj_text, "publishText"))
            page_url = normalize_url(self._extract_js_string_field(obj_text, "pageUrl"))
            thumbnail = normalize_url(
                self._extract_js_string_field(obj_text, "thumbnail")
                or self._extract_js_string_field(obj_text, "imageUrl")
            )
            desc = self._clean_text(self._extract_js_string_field(obj_text, "desc"))
            if title and publish_text:
                release_date, parsed_text = self._parse_release_info(publish_text)
                raw_id = self._search_text(page_url, r"/([^/]+)\.html") or title
                year = self._guess_year(title, release_date, publish_text)
                type_key = self._extract_iqiyi_type_key(obj_text) or self._infer_type_key(
                    title=title,
                    year=year,
                    story=desc,
                    release_text=publish_text,
                    cache_key=raw_id,
                    prefer_cached=False,
                )
                items.append(
                    self._build_item(
                        platform="iqiyi",
                        raw_id=raw_id,
                        title=title,
                        type_key=type_key,
                        release_date=release_date,
                        release_text=parsed_text,
                        poster=thumbnail,
                        detail_link=page_url,
                        story=desc,
                        year=year,
                    )
                )
            cursor = payload.find("{", cursor + len(obj_text))
        logger.info(f"[UpcomingReleases] iqiyi fetched {len(items)} items")
        return items

    def _extract_iqiyi_type_key(self, obj_text: str) -> str:
        for pattern in [
            r"\bchannelId\s*:\s*(\d+)",
            r"\bchannelID\s*:\s*(\d+)",
            r"\bchannelType\s*:\s*(\d+)",
            r"\balbumType\s*:\s*(\d+)",
            r"\bvideoType\s*:\s*(\d+)",
        ]:
            channel_value = self._search_text(obj_text, pattern)
            if channel_value in IQIYI_TYPE_MAP:
                return IQIYI_TYPE_MAP[channel_value]
        return ""

    def _fetch_tencent(self) -> List[Dict[str, Any]]:
        url = (
            "https://pbaccess.video.qq.com/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData"
            "?video_appid=1000005&vplatform=2&vversion_name=8.9.10&new_mark_label_enabled=1"
        )
        items = []
        seen_ids = set()
        for channel in TENCENT_CHANNELS.values():
            payload = {
                "page_params": {
                    "channel_id": channel["channel_id"],
                    "page_type": "channel_operation",
                    "page_id": "channel_list_second_page",
                    "filter_params": f"iyear={channel['upcoming_value']}",
                }
            }
            response = self._request_json(
                url,
                method="POST",
                json_body=payload,
                headers={"Referer": "https://v.qq.com/", "Content-Type": "application/json"},
            )
            module_list = response.get("data", {}).get("module_list_datas") or []
            for module in module_list:
                for module_data in module.get("module_datas") or []:
                    entries = module_data.get("item_data_lists", {}).get("item_datas", [])
                    for entry in entries:
                        if str(entry.get("item_type")) != "2":
                            continue
                        params = entry.get("item_params") or {}
                        title = self._clean_text(params.get("title"))
                        cid = str(params.get("cid") or "").strip()
                        dedup_key = (channel["type_key"], cid)
                        if not title or not cid or dedup_key in seen_ids:
                            continue
                        seen_ids.add(dedup_key)
                        release_hint = params.get("publish_date") or params.get("second_title") or params.get("sub_title") or ""
                        release_date, parsed_text = self._parse_release_info(release_hint)
                        reserve_text = self._clean_text(" / ".join(filter(None, [params.get("third_title"), params.get("chnlist_search_label")])))
                        items.append(
                            self._build_item(
                                platform="tencent",
                                raw_id=cid,
                                title=title,
                                type_key=channel["type_key"],
                                release_date=release_date,
                                release_text=parsed_text,
                                poster=normalize_url(params.get("new_pic_vt") or params.get("new_pic_hz") or params.get("pic_url") or params.get("image_url")),
                                detail_link=normalize_url(params.get("href") or f"https://v.qq.com/x/cover/{cid}.html"),
                                story=self._clean_text(params.get("second_title") or params.get("sub_title") or reserve_text),
                                reserve_count=parse_reserve_count(reserve_text),
                            )
                        )
        logger.info(f"[UpcomingReleases] 腾讯视频待播抓取完成，共 {len(items)} 条")
        return items

    def _fetch_youku(self) -> List[Dict[str, Any]]:
        html = self._request_text("https://www.youku.com/ku/new")
        if not html:
            return []
        payload_text = extract_balanced_object(html, "__INITIAL_DATA__")
        if not payload_text:
            return []
        try:
            data = json.loads(js_object_to_json(payload_text))
        except json.JSONDecodeError as err:
            logger.error(f"[UpcomingReleases] 优酷 JSON 解析失败: {err}")
            return []
        module_list = self._deep_find_first(data, "moduleList") or []
        items = []
        for module in module_list:
            components = module.get("components") or []
            for component in components:
                section_title = self._clean_text(
                    component.get("title")
                    or component.get("moduleTitle")
                    or component.get("header", {}).get("title")
                )
                if "即将上线" not in section_title:
                    continue
                type_name = re.split(r"[-|｜]", section_title)[0].strip()
                type_key = YOUKU_SECTION_MAP.get(type_name, "tv")
                candidates: List[Dict[str, Any]] = []
                self._collect_matching_dicts(
                    component,
                    lambda node: bool(node.get("title")) and bool(node.get("reserve") or node.get("subtitle") or node.get("img") or node.get("desc")),
                    candidates,
                )
                seen = set()
                for entry in candidates:
                    title = self._clean_text(entry.get("title"))
                    reserve = entry.get("reserve") or {}
                    raw_id = str(reserve.get("id") or entry.get("id") or "").strip()
                    subtitle = self._clean_text(entry.get("subtitle"))
                    desc = self._clean_text(entry.get("desc") or reserve.get("desc"))
                    dedup_key = (title, raw_id or subtitle)
                    if not title or dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    release_date, parsed_text = self._parse_release_info(subtitle or desc)
                    detail_link = f"https://v.youku.com/video?s={raw_id}" if raw_id else ""
                    poster = normalize_url(entry.get("img") or entry.get("poster") or entry.get("cover"))
                    items.append(
                        self._build_item(
                            platform="youku",
                            raw_id=raw_id or title,
                            title=title,
                            type_key=type_key,
                            release_date=release_date,
                            release_text=parsed_text,
                            poster=poster,
                            detail_link=detail_link,
                            story=desc,
                            year=self._guess_year(title, release_date, subtitle or desc),
                            reserve_count=parse_reserve_count(str(reserve.get("count") or reserve.get("desc") or "")),
                        )
                    )
        logger.info(f"[UpcomingReleases] 优酷抓取到 {len(items)} 条")
        return items

    def _fetch_mgtv(self) -> List[Dict[str, Any]]:
        response = self._request_json(
            "https://playbill.api.mgtv.com/yy/module?pbId=9",
            headers={"Referer": "https://www.mgtv.com/"},
        )
        candidates: List[Dict[str, Any]] = []
        self._collect_matching_dicts(
            response,
            lambda node: bool(node.get("title")) and bool(node.get("aid") or node.get("url") or node.get("onlineTime") or node.get("beginTime")),
            candidates,
        )
        items = []
        seen = set()
        for entry in candidates:
            title = self._clean_text(entry.get("title"))
            raw_id = str(entry.get("aid") or entry.get("id") or "").strip()
            dedup_key = raw_id or title
            if not title or dedup_key in seen:
                continue
            seen.add(dedup_key)
            begin_time = self._clean_text(entry.get("beginTime"))
            online_time = self._clean_text(entry.get("onlineTime"))
            release_hint = begin_time or online_time
            release_date, parsed_text = self._parse_release_info(release_hint or f"{begin_time} {online_time}".strip())
            poster = normalize_url(entry.get("imgVer") or entry.get("img"))
            detail_link = normalize_url(entry.get("url"))
            if detail_link.startswith("/"):
                detail_link = f"https://www.mgtv.com{detail_link}"
            story = self._clean_text(entry.get("stroy") or entry.get("story"))
            year = self._guess_year(title, release_date, release_hint)
            type_key = self._infer_type_key(
                title=title,
                year=year,
                story=story,
                release_text=release_hint,
                cache_key=raw_id or self._make_lookup_key(title, year),
            )
            items.append(
                self._build_item(
                    platform="mgtv",
                    raw_id=raw_id or title,
                    title=title,
                    type_key=type_key,
                    release_date=release_date,
                    release_text=parsed_text,
                    poster=poster,
                    detail_link=detail_link,
                    story=story,
                    year=year,
                )
            )
        logger.info(f"[UpcomingReleases] 芒果TV抓取到 {len(items)} 条")
        return items

    def _build_item(
        self,
        platform: str,
        raw_id: str,
        title: str,
        type_key: str,
        release_date: Optional[str],
        release_text: Optional[str],
        poster: str,
        detail_link: str = "",
        story: str = "",
        year: Optional[str] = None,
        reserve_count: int = 0,
    ) -> Dict[str, Any]:
        if type_key not in TYPE_LABELS:
            type_key = "tv"
        if not year:
            year = self._guess_year(title, release_date, release_text)
        return {
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "type_key": type_key,
            "type_label": TYPE_LABELS.get(type_key, "电视剧"),
            "title": self._clean_text(title),
            "year": year,
            "release_date": release_date,
            "release_text": self._clean_text(release_text) or "敬请期待",
            "poster": poster,
            "detail_link": detail_link,
            "story": self._clean_text(story),
            "reserve_count": safe_int(reserve_count, 0),
            "media_id": self._make_media_id(platform, raw_id, title, release_date or release_text or ""),
        }

    def _resolve_media_dict(self, item: Dict[str, Any], convert_type: str) -> Dict[str, Any]:
        record = self._get_cached_recognition_record(item)
        if record:
            if convert_type == "themoviedb" and record.get("tmdb_id"):
                return {"id": record.get("tmdb_id")}
            if convert_type == "douban" and record.get("douban_id"):
                return {"id": record.get("douban_id")}
            if self._is_failed_recognition_record(record):
                return {}
        media = self._recognize_item(item)
        if not media:
            return {}
        resolved_type = self._media_to_type_key(media)
        self._cache_recognition(item, media, resolved_type)
        if convert_type == "themoviedb" and media.tmdb_id:
            return {"id": media.tmdb_id}
        if convert_type == "douban" and media.douban_id:
            return {"id": media.douban_id}
        return {}

    def _recognize_item(self, item: Dict[str, Any]) -> Optional[MediaInfo]:
        title = self._clean_text(item.get("title"))
        if not title:
            return None
        year = item.get("year")
        text_blob = " ".join(filter(None, [title, item.get("story"), item.get("release_text"), item.get("type_label")]))
        candidate_types = []
        for value in [
            item.get("type_key"),
            self._keyword_type_key(text_blob),
            None,
        ]:
            normalized = self._clean_text(value).lower() if value is not None else ""
            key = normalized or "<none>"
            if key in candidate_types:
                continue
            candidate_types.append(key)

        last_error = None
        for candidate in candidate_types:
            type_key = None if candidate == "<none>" else candidate
            meta = MetaInfo(title)
            if year:
                meta.year = year
            resolved_mtype = self._type_key_to_media_type(type_key)
            if resolved_mtype == MediaType.MOVIE:
                meta.type = MediaType.MOVIE
            elif resolved_mtype == MediaType.TV:
                meta.type = MediaType.TV
            try:
                media = self.chain.recognize_media(meta=meta, mtype=resolved_mtype, cache=True)
                if media:
                    return media
            except Exception as err:
                last_error = err
        if last_error:
            logger.warning(f"[UpcomingReleases] recognize media failed: {item.get('title')} - {last_error}")
        return None

    def _cache_recognition(self, item: Dict[str, Any], media: MediaInfo, type_key: Optional[str] = None):
        if not media:
            return
        resolved_type_key = type_key or item.get("type_key") or "tv"
        record = {
            "recognition_failed": False,
            "type_key": resolved_type_key,
            "tmdb_id": media.tmdb_id,
            "douban_id": media.douban_id,
            "bangumi_id": media.bangumi_id,
            "title": item.get("title"),
            "year": item.get("year"),
            "country_codes": sorted(self._extract_region_codes(media)),
            "genre_names": sorted(self._extract_genre_names(media, item)),
            "updated": int(time.time()),
        }
        keys = [item.get("media_id"), self._make_lookup_key(item.get("title"), item.get("year"), resolved_type_key)]
        changed = False
        for key in keys:
            if not key:
                continue
            if self._recognize_cache.get(key) != record:
                self._recognize_cache[key] = record
                changed = True
        if changed:
            self._recognize_dirty = True

    def _run_auto_subscribe(self, items: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        rules = self._load_auto_subscribe_rules()
        summary = {"added": [], "existing": [], "failed": []}
        if not rules:
            return summary
        subscribe_chain = SubscribeChain()
        default_username = self._get_default_subscribe_username()
        processed = set()
        for rule in rules:
            matched_items = [item for item in items if self._rule_matches_item(item, rule)]
            logger.info(f"[UpcomingReleases] auto-subscribe rule {rule.get('name')} matched {len(matched_items)} items")
            for item in matched_items:
                process_key = self._make_browser_group_key(item)
                if process_key in processed:
                    continue
                processed.add(process_key)
                try:
                    recognition = self._get_cached_recognition(item, populate=True, require_ids=False) or {}
                    detail = f"[{rule.get('name')}] {item.get('title')} ({item.get('release_text')})"
                    subscription_status = self._get_item_subscription_status(
                        item,
                        username=default_username,
                        recognition=recognition,
                    )
                    if subscription_status == "active":
                        summary["existing"].append(detail)
                        continue
                    if subscription_status == "history":
                        summary["existing"].append(f"{detail} [已在订阅历史]")
                        continue

                    resolved_mtype = self._type_key_to_media_type(recognition.get("type_key")) or self._type_key_to_media_type(item.get("type_key")) or MediaType.TV
                    resolved_season = self._resolve_item_subscribe_season(item, recognition)
                    sid, message = subscribe_chain.add(
                        title=item.get("title"),
                        year=item.get("year") or "",
                        mtype=resolved_mtype,
                        tmdbid=safe_int(recognition.get("tmdb_id"), 0) or None,
                        doubanid=self._clean_text(recognition.get("douban_id")) or None,
                        bangumiid=safe_int(recognition.get("bangumi_id"), 0) or None,
                        mediaid=self._make_subscribe_mediaid(item),
                        season=resolved_season,
                        message=False,
                        exist_ok=True,
                        source=f"upcoming auto subscribe:{rule.get('name')}",
                        username=default_username,
                    )
                    logger.info(f"[UpcomingReleases] auto subscribe result: rule={rule.get('name')} title={item.get('title')} sid={sid} message={message or ''}")
                    if sid and not self._is_exists_message(message):
                        summary["added"].append(detail)
                    elif self._is_exists_message(message):
                        if self._claim_subscribe_owner(item=item, username=default_username):
                            summary["added"].append(f"{detail} [已补全归属]")
                        else:
                            summary["existing"].append(detail)
                    else:
                        summary["failed"].append(f"{detail} - {message or '未知原因'}")
                except Exception as err:
                    logger.error(f"[UpcomingReleases] auto subscribe error: {item.get('title')} - {err}")
                    summary["failed"].append(f"[{rule.get('name')}] {item.get('title')} - {err}")
        logger.info(f"[UpcomingReleases] auto subscribe finished: added {len(summary['added'])}, existing {len(summary['existing'])}, failed {len(summary['failed'])}")
        return summary

    def _ensure_rule_list(self, value: Any, default: Optional[List[str]] = None) -> List[str]:
        if value is None:
            return list(default or [])
        if isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            text_value = str(value).strip()
            if not text_value:
                return list(default or [])
            values = [part for part in re.split(r"[,，、|\n]+", text_value) if str(part).strip()]
        normalized = [self._clean_text(item) for item in values if self._clean_text(item)]
        return normalized or list(default or [])

    def _normalize_rule_time_range(self, value: Any) -> str:
        raw_value = self._clean_text(value or "")
        if not raw_value:
            return ""
        lookup_value = raw_value.lower()
        if lookup_value in TIME_LABELS:
            return lookup_value
        for key, label in TIME_LABELS.items():
            if raw_value == label:
                return key
        return ""

    def _infer_rule_time_range(self, item: Dict[str, Any]) -> str:
        time_range = self._normalize_rule_time_range(item.get("time_range") or item.get("window"))
        if time_range:
            return time_range
        days = safe_int(item.get("days") or item.get("window_days"), 0)
        if days <= 0:
            return "pending" if bool(item.get("include_pending", False)) else ""
        if days == 1:
            return "today"
        if days <= 3:
            return "3days"
        if days <= 7:
            return "7days"
        if days <= 30:
            return "30days"
        return "all"

    def _load_auto_subscribe_rules(self) -> List[Dict[str, Any]]:
        raw_rules = self._config.get("auto_subscribe_rules")
        if isinstance(raw_rules, list):
            data = raw_rules
        else:
            text_value = str(raw_rules or "").strip()
            if not text_value:
                return []
            try:
                data = json.loads(text_value)
            except json.JSONDecodeError as err:
                logger.warning(f"[UpcomingReleases] 自动订阅规则 JSON 解析失败: {err}")
                return []
        if not isinstance(data, list):
            return []
        rules = []
        for index, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            rule = {
                "name": self._clean_text(item.get("name") or f"规则{index}"),
                "enabled": bool(item.get("enabled", True)),
                "time_range": self._infer_rule_time_range(item),
                "days": max(1, safe_int(item.get("days") or item.get("window_days"), 7)),
                "types": self._ensure_rule_list(item.get("types") or item.get("type") or item.get("mtype"), ["all"]),
                "platforms": self._ensure_rule_list(item.get("platforms") or item.get("platform"), ["all"]),
                "regions": self._ensure_rule_list(item.get("regions") or item.get("region") or item.get("countries")),
                "genres": self._ensure_rule_list(item.get("genres") or item.get("genre") or item.get("tags")),
                "exclude_genres": self._ensure_rule_list(item.get("exclude_genres") or item.get("exclude_genre")),
                "include_pending": bool(item.get("include_pending", False)),
                "keyword": self._clean_text(item.get("keyword") or ""),
                "exclude_keyword": self._clean_text(item.get("exclude_keyword") or item.get("exclude") or ""),
            }
            if rule["enabled"]:
                rules.append(rule)
        return rules

    def _rule_matches_item(self, item: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        platforms = self._normalize_platform_values(rule.get("platforms") or ["all"])
        if platforms and "all" not in platforms and item.get("platform") not in platforms:
            return False

        if not self._match_rule_types(item, rule.get("types") or ["all"]):
            return False

        if rule.get("keyword") and rule.get("keyword") not in item.get("title", "") and rule.get("keyword") not in item.get("story", ""):
            return False
        if rule.get("exclude_keyword") and (rule.get("exclude_keyword") in item.get("title", "") or rule.get("exclude_keyword") in item.get("story", "")):
            return False

        time_range = self._normalize_rule_time_range(rule.get("time_range"))
        if time_range:
            if item.get("release_date"):
                if not self._match_time_filter(item, time_range):
                    return False
            elif time_range != "pending" and not rule.get("include_pending"):
                return False
        else:
            if item.get("release_date"):
                try:
                    delta = (datetime.strptime(item.get("release_date"), "%Y-%m-%d").date() - datetime.now().date()).days
                except ValueError:
                    return False
                if delta < 0 or delta > max(1, safe_int(rule.get("days"), 7)):
                    return False
            elif not rule.get("include_pending"):
                return False

        regions = rule.get("regions") or []
        if regions and not self._match_rule_regions(item, regions):
            return False

        genres = rule.get("genres") or []
        if genres and not self._match_rule_genres(item, genres):
            return False

        exclude_genres = rule.get("exclude_genres") or []
        if exclude_genres and self._match_rule_genres(item, exclude_genres):
            return False
        return True

    def _match_rule_types(self, item: Dict[str, Any], types: List[Any]) -> bool:
        normalized_types = self._normalize_rule_types(types)
        if not normalized_types or "all" in normalized_types:
            return True
        item_type = item.get("type_key")
        return any(item_type in AUTO_SUBSCRIBE_TYPE_GROUPS.get(type_name, {type_name}) for type_name in normalized_types)

    def _match_rule_regions(self, item: Dict[str, Any], regions: List[Any]) -> bool:
        expected = self._normalize_region_values(regions)
        if not expected:
            return True
        failed_cached = False
        cache_keys = [item.get("media_id"), self._make_lookup_key(item.get("title"), item.get("year"), item.get("type_key"))]
        for key in cache_keys:
            record = self._recognize_cache.get(key) if key else None
            if record and record.get("country_codes"):
                return bool(set(record.get("country_codes") or []) & expected)
            if self._is_failed_recognition_record(record):
                failed_cached = True
        if failed_cached:
            return False
        media = self._recognize_item(item)
        if not media:
            return False
        type_key = self._media_to_type_key(media)
        self._cache_recognition(item, media, type_key)
        actual = self._extract_region_codes(media)
        return bool(actual & expected)

    def _match_rule_genres(self, item: Dict[str, Any], genres: List[Any]) -> bool:
        expected = self._normalize_genre_values(genres)
        if not expected:
            return True
        actual = set()
        failed_cached = False
        cache_keys = [item.get("media_id"), self._make_lookup_key(item.get("title"), item.get("year"), item.get("type_key"))]
        for key in cache_keys:
            record = self._recognize_cache.get(key) if key else None
            if record:
                actual.update(record.get("genre_names") or [])
            if self._is_failed_recognition_record(record):
                failed_cached = True
        actual.update(self._extract_text_genre_names(" ".join(filter(None, [item.get("title"), item.get("story"), item.get("release_text")]))))
        if actual & expected:
            return True
        if failed_cached:
            return False
        media = self._recognize_item(item)
        if not media:
            return False
        type_key = self._media_to_type_key(media)
        self._cache_recognition(item, media, type_key)
        actual.update(self._extract_genre_names(media, item))
        return bool(actual & expected)

    def _extract_region_codes(self, media: MediaInfo) -> set:
        codes = set()
        for code in media.origin_country or []:
            if isinstance(code, str) and code.strip():
                codes.update(self._normalize_region_values([code]))
        for country in media.production_countries or []:
            if isinstance(country, dict):
                code = country.get("iso_3166_1") or country.get("iso")
                if code:
                    codes.update(self._normalize_region_values([code]))
                    continue
                name = country.get("name") or country.get("id")
                if name:
                    codes.update(self._normalize_region_values([name]))
        for country in media.production_countries or []:
            if isinstance(country, str) and country.strip():
                codes.update(self._normalize_region_values([country]))
        language = str(getattr(media, "original_language", "") or "").strip().lower()
        if language in LANGUAGE_REGION_MAP:
            codes.add(LANGUAGE_REGION_MAP[language])
        return codes

    def _extract_genre_names(self, media: MediaInfo, item: Optional[Dict[str, Any]] = None) -> set:
        values = set()
        for genre in media.genres or []:
            if isinstance(genre, dict):
                name = self._clean_text(genre.get("name"))
            else:
                name = self._clean_text(genre)
            if name:
                values.update(self._normalize_genre_values([name]))
        if item:
            values.update(self._extract_text_genre_names(" ".join(filter(None, [item.get("title"), item.get("story"), item.get("release_text")]))))
        return values

    def _extract_text_region_codes(self, text: str) -> set:
        text_value = self._clean_text(text)
        if not text_value:
            return set()
        text_lower = text_value.lower()
        values = set()
        for alias, codes in REGION_ALIAS_MAP.items():
            alias_text = self._clean_text(alias)
            if not alias_text:
                continue
            if re.fullmatch(r"[A-Za-z]{2,3}", alias_text):
                if re.search(rf"\b{re.escape(alias_text.lower())}\b", text_lower):
                    values.update(codes)
            elif alias_text in text_value:
                values.update(codes)
        return values

    def _extract_text_genre_names(self, text: str) -> set:
        text_value = self._clean_text(text).lower()
        if not text_value:
            return set()
        values = set()
        for genre_name, aliases in GENRE_ALIAS_MAP.items():
            alias_values = {genre_name.lower()} | {self._clean_text(alias).lower() for alias in aliases if self._clean_text(alias)}
            if any(alias and alias in text_value for alias in alias_values):
                values.add(genre_name)
        fallback_map = {
            "综艺": "综艺",
            "动漫": "动画",
            "动画": "动画",
            "纪录片": "纪录片",
            "少儿": "少儿",
            "人文": "人文",
            "短剧": "短剧",
        }
        for keyword, label in fallback_map.items():
            if keyword in text and label not in values:
                values.add(label)
        return values

    def _build_text_fallback_recognition(self, item: Dict[str, Any]) -> Dict[str, Any]:
        text_blob = " ".join(
            filter(
                None,
                [
                    item.get("title"),
                    item.get("story"),
                    item.get("release_text"),
                    item.get("type_label"),
                    item.get("detail_link"),
                ],
            )
        )
        country_codes = sorted(self._extract_text_region_codes(text_blob))
        genre_names = sorted(self._extract_text_genre_names(text_blob))
        type_key = self._clean_text(item.get("type_key")).lower()
        type_genre_fallback = {
            "anime": "动画",
            "variety": "综艺",
            "documentary": "纪录片",
            "kids": "少儿",
            "humanity": "人文",
            "short": "短剧",
        }
        if not genre_names and type_key in type_genre_fallback:
            genre_names = [type_genre_fallback[type_key]]
        return {
            "recognition_failed": True,
            "type_key": type_key or "tv",
            "tmdb_id": None,
            "douban_id": None,
            "bangumi_id": None,
            "title": item.get("title"),
            "year": item.get("year"),
            "country_codes": country_codes,
            "genre_names": genre_names,
            "updated": int(time.time()),
        }

    def _store_recognition_record(self, item: Dict[str, Any], record: Dict[str, Any]):
        keys = [
            item.get("media_id"),
            self._make_lookup_key(item.get("title"), item.get("year"), record.get("type_key") or item.get("type_key")),
        ]
        changed = False
        for key in keys:
            if not key:
                continue
            if self._recognize_cache.get(key) != record:
                self._recognize_cache[key] = record
                changed = True
        if changed:
            self._recognize_dirty = True

    def _normalize_region_values(self, regions: List[Any]) -> set:
        values = set()
        for region in regions:
            text_value = self._clean_text(region).upper()
            if not text_value:
                continue
            if text_value in REGION_ALIAS_MAP:
                values.update(REGION_ALIAS_MAP[text_value])
            else:
                values.add(text_value)
        return values

    def _normalize_genre_values(self, genres: List[Any]) -> set:
        values = set()
        for genre in genres:
            text_value = self._clean_text(genre).lower()
            if not text_value:
                continue
            matched = False
            for genre_name, aliases in GENRE_ALIAS_MAP.items():
                alias_values = {genre_name.lower()} | {self._clean_text(alias).lower() for alias in aliases if self._clean_text(alias)}
                if text_value in alias_values:
                    values.add(genre_name)
                    matched = True
                    break
            if not matched:
                values.add(self._clean_text(genre))
        return values

    def _normalize_platform_values(self, platforms: List[Any]) -> set:
        values = set()
        for platform in platforms:
            text_value = self._clean_text(platform).lower()
            if not text_value:
                continue
            values.add(PLATFORM_ALIAS_MAP.get(text_value, text_value))
        return values

    def _normalize_rule_types(self, types: List[Any]) -> set:
        values = set()
        for type_value in types:
            text_value = self._clean_text(type_value).lower()
            if not text_value:
                continue
            values.add(TYPE_ALIAS_MAP.get(text_value, text_value))
        return values or {"all"}
    def _infer_type_key(
        self,
        title: str,
        year: Optional[str] = None,
        story: str = "",
        release_text: str = "",
        cache_key: str = "",
        prefer_cached: bool = True,
    ) -> str:
        for key in [cache_key, self._make_lookup_key(title, year)]:
            record = self._recognize_cache.get(key) if key else None
            if record and self._is_failed_recognition_record(record) and record.get("type_key"):
                return record.get("type_key")
            if prefer_cached and record and record.get("type_key"):
                return record.get("type_key")
        keyword_type = self._keyword_type_key(" ".join(filter(None, [title, story, release_text])))
        media = self._recognize_item({"title": title, "year": year})
        if media:
            type_key = self._media_to_type_key(media)
            if not prefer_cached and keyword_type == "movie" and type_key == "tv":
                type_key = "movie"
            temp_item = {
                "media_id": cache_key or self._make_media_id("mgtv", title, title, release_text),
                "title": title,
                "year": year,
                "type_key": type_key,
            }
            self._cache_recognition(temp_item, media, type_key)
            return type_key
        return keyword_type

    def _media_to_type_key(self, media: MediaInfo) -> str:
        if media.type == MediaType.MOVIE.value:
            return "movie"
        genre_names = [str(genre.get("name") or "").lower() for genre in media.genres or [] if isinstance(genre, dict)]
        if any("动画" in name or "animation" in name for name in genre_names):
            return "anime"
        if any("纪录" in name or "documentary" in name for name in genre_names):
            return "documentary"
        return "tv"

    def _keyword_type_key(self, text: str) -> str:
        text = self._clean_text(text).lower()
        if any(keyword in text for keyword in ["动漫", "动画", "番剧", "animation"]):
            return "anime"
        if any(keyword in text for keyword in ["纪录", "纪实", "documentary"]):
            return "documentary"
        if any(keyword in text for keyword in ["综艺", "晚会", "脱口秀", "真人秀"]):
            return "variety"
        if any(keyword in text for keyword in ["电影", "院线", "大片", "film", "movie"]):
            return "movie"
        return "tv"

    def _build_filter_ui(self) -> List[Dict[str, Any]]:
        return [
            self._build_chip_group("平台", "platform", PLATFORM_LABELS),
            self._build_chip_group("类型", "mtype", TYPE_LABELS),
            self._build_chip_group("时间", "time_range", TIME_LABELS),
            self._build_chip_group("地区", "region", PAGE_REGION_LABELS),
            self._build_chip_group("题材", "genre", PAGE_GENRE_LABELS),
        ]

    def _build_chip_group(self, label: str, model: str, options: Dict[str, str]) -> Dict[str, Any]:
        return {
            "component": "div",
            "props": {"class": "flex justify-start items-center flex-wrap mb-3"},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "mr-5 mb-2"},
                    "content": [{"component": "VLabel", "text": label}],
                },
                {
                    "component": "VChipGroup",
                    "props": {"model": model},
                    "content": [
                        {"component": "VChip", "props": {"filter": True, "tile": True, "value": key}, "text": value}
                        for key, value in options.items()
                    ],
                },
            ],
        }

    def _ensure_security_domains(self):
        if self._security_domains_ready:
            return
        domains = ["iqiyipic.com", "qpic.cn", "ykimg.com", "hitv.com", "mgtv.com"]
        for domain in domains:
            if domain not in settings.SECURITY_IMAGE_DOMAINS:
                settings.SECURITY_IMAGE_DOMAINS.append(domain)
        self._security_domains_ready = True

    def _restore_cache(self):
        self._ensure_runtime_state()
        cache = self.get_data("cache")
        if isinstance(cache, dict) and safe_int(cache.get("schema_version"), 0) == CACHE_SCHEMA_VERSION:
            items = cache.get("items") or []
            if isinstance(items, list):
                self._cache = {
                    "timestamp": safe_int(cache.get("timestamp"), 0),
                    "items": items,
                    "schema_version": CACHE_SCHEMA_VERSION,
                }
        recognize_cache = self.get_data("recognize_cache")
        if isinstance(recognize_cache, dict) and safe_int(recognize_cache.get("schema_version"), 0) == CACHE_SCHEMA_VERSION:
            records = recognize_cache.get("records") or {}
            if isinstance(records, dict):
                self._recognize_cache = records

    def _persist_cache(self):
        cache_payload = {
            "timestamp": self._cache.get("timestamp"),
            "items": self._cache.get("items") or [],
            "schema_version": CACHE_SCHEMA_VERSION,
        }
        self.save_data("cache", cache_payload)

    def _persist_recognize_cache(self):
        self.save_data(
            "recognize_cache",
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "records": self._recognize_cache,
            },
        )
        self._recognize_dirty = False

    def _request_text(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> str:
        req_headers = dict(DEFAULT_HEADERS)
        if headers:
            req_headers.update(headers)
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
            method = "POST"
        request = Request(url, headers=req_headers, data=data, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                content = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return content.decode(charset, errors="ignore")
        except HTTPError as err:
            logger.warning(f"[UpcomingReleases] 请求失败 {url}: HTTP {err.code}")
        except URLError as err:
            logger.warning(f"[UpcomingReleases] 请求失败 {url}: {err}")
        except Exception as err:
            logger.warning(f"[UpcomingReleases] 请求异常 {url}: {err}")
        return ""

    def _request_json(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = self._request_text(url, method=method, headers=headers, json_body=json_body)
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            logger.warning(f"[UpcomingReleases] JSON 解析失败 {url}: {err}")
            return {}

    def _find_item_by_mediaid(self, media_id: str) -> Optional[Dict[str, Any]]:
        for item in self._get_items(force_refresh=False):
            if item.get("media_id") == media_id:
                return item
        return None

    def _parse_release_info(self, text: str) -> Tuple[Optional[str], str]:
        raw = self._clean_text(text)
        if not raw:
            return None, "敬请期待"
        today = datetime.now().date()
        if any(keyword in raw for keyword in ["敬请期待", "待定", "暂未定档", "即将上线", "即将播出"]) and not re.search(r"\d", raw):
            return None, raw
        if "今日" in raw or "今天" in raw:
            return today.strftime("%Y-%m-%d"), raw
        if "明日" in raw or "明天" in raw:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d"), raw
        matched = re.search(r"((?:19|20)\d{2})[./-](\d{1,2})[./-](\d{1,2})", raw)
        if matched:
            year, month, day = map(int, matched.groups())
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d"), raw
            except ValueError:
                return None, raw
        matched = re.search(r"(\d{1,2})月(\d{1,2})日", raw)
        if not matched:
            matched = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)", raw)
        if matched:
            month, day = map(int, matched.groups())
            year = today.year
            try:
                candidate = datetime(year, month, day).date()
            except ValueError:
                return None, raw
            if candidate < today - timedelta(days=30):
                candidate = datetime(year + 1, month, day).date()
            return candidate.strftime("%Y-%m-%d"), raw
        return None, raw

    def _compute_time_key(self, release_date: Optional[str]) -> str:
        if not release_date:
            return "pending"
        try:
            release_dt = datetime.strptime(release_date, "%Y-%m-%d").date()
        except ValueError:
            return "pending"
        delta = (release_dt - datetime.now().date()).days
        if delta < 0:
            return "past"
        if delta == 0:
            return "today"
        if delta == 1:
            return "tomorrow"
        if delta <= 3:
            return "3days"
        if delta <= 7:
            return "7days"
        if delta <= 30:
            return "30days"
        return "all"

    def _guess_year(self, title: str, release_date: Optional[str], text: Optional[str]) -> Optional[str]:
        if release_date:
            return release_date[:4]
        matched = re.search(r"((?:19|20)\d{2})", f"{title or ''} {text or ''}")
        return matched.group(1) if matched else None

    def _make_lookup_key(self, title: str, year: Optional[str], type_key: Optional[str] = None) -> str:
        title_part = self._normalize_compare_text(title)
        title_part = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", title_part)
        year_part = re.sub(r"[^0-9]", "", self._clean_text(year))[:4]
        type_part = re.sub(r"[^0-9a-z]+", "", self._clean_text(type_key).lower())
        base = "|".join(part for part in [title_part, year_part, type_part] if part)
        if not base:
            return "upcoming_default"
        return base[:96]

    def _make_media_id(self, platform: str, raw_id: str, title: str, suffix: str) -> str:
        raw_id = str(raw_id or "").strip()
        if raw_id and re.fullmatch(r"[0-9A-Za-z_-]{1,48}", raw_id):
            key = raw_id
        else:
            base = self._clean_text(f"{title or ''}-{suffix or ''}").lower()
            key = re.sub(r"[^0-9a-z]+", "", base)[:32]
            if not key:
                checksum = sum((index + 1) * ord(char) for index, char in enumerate(f"{platform}|{title}|{suffix}"))
                key = str(checksum)
        return f"{platform}_{key}"

    def _decode_js_string(self, raw: str) -> str:
        if raw is None:
            return ""
        value = str(raw)
        if not value or "\\" not in value:
            return value
        try:
            return json.loads(f'"{value}"')
        except Exception:
            value = re.sub(
                r"\\u([0-9a-fA-F]{4})",
                lambda match: chr(int(match.group(1), 16)),
                value,
            )
            return (
                value.replace("\\/", "/")
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
            )

    def _extract_js_string_field(self, text: str, field: str) -> str:
        matched = re.search(rf'{re.escape(field)}:"', text or "", re.IGNORECASE)
        if not matched:
            return ""
        start = matched.end()
        value = []
        escape = False
        for char in text[start:]:
            if escape:
                value.append("\\" + char)
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                return self._decode_js_string("".join(value))
            value.append(char)
        return self._decode_js_string("".join(value))

    def _extract_bracket_array(self, text: str, start_index: int) -> Optional[str]:
        if start_index < 0 or start_index >= len(text):
            return None
        depth = 0
        in_string = False
        escape = False
        for index in range(start_index, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[start_index:index + 1]
        return None

    def _extract_brace_object(self, text: str, start_index: int) -> Optional[str]:
        depth = 0
        in_string = False
        escape = False
        for index in range(start_index, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index:index + 1]
        return None

    def _search_text(self, text: str, pattern: str) -> str:
        matched = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
        if not matched:
            return ""
        return matched.group(1) if matched.groups() else matched.group(0)

    def _clean_text(self, text: Any) -> str:
        if text is None:
            return ""
        cleaned = unescape(str(text))
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _deep_find_first(self, node: Any, key: str):
        if isinstance(node, dict):
            if key in node:
                return node.get(key)
            for value in node.values():
                found = self._deep_find_first(value, key)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._deep_find_first(value, key)
                if found is not None:
                    return found
        return None

    def _collect_matching_dicts(self, node: Any, predicate, output: List[Dict[str, Any]]):
        if isinstance(node, dict):
            try:
                if predicate(node):
                    output.append(node)
            except Exception:
                pass
            for value in node.values():
                self._collect_matching_dicts(value, predicate, output)
        elif isinstance(node, list):
            for value in node:
                self._collect_matching_dicts(value, predicate, output)



