import gc
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase


DEFAULT_CONFIG = {
    "enabled": True,
    "api_qps": 1,
    "download_qps": 1,
    "limit_sleep_seconds": 3600,
    "hourly_soft_limit": 60,
    "hourly_soft_cooldown": 1200,
    "enable_event_log": True,
    "max_event_log_count": 50,
    "startup_log": True,
    "strict_mode": True,
}

MP_DEFAULTS = {
    "api_qps": 3,
    "download_qps": 1,
    "limit_sleep_seconds": 3600,
}

EVENT_TYPE_PATCH_ACTIVE = "patch_active"
EVENT_TYPE_SOFT_LIMIT = "soft_limit_triggered"
EVENT_TYPE_HARD_LIMIT = "115_limit_triggered"


class U115RiskControl(_PluginBase):
    plugin_name = "u115风控参数"
    plugin_desc = "为 MoviePilot 的 u115 存储提供低风控默认参数、运行态状态页和风控触发事件日志。"
    plugin_icon = "U115RiskControl.jpg"
    plugin_version = "0.1.2"
    plugin_author = "wYw"
    author_url = ""
    plugin_config_prefix = "u115riskcontrol_"
    plugin_order = 98
    auth_level = 1

    _patch_lock = threading.Lock()
    _event_lock = threading.Lock()
    _patched = False

    def __init__(self):
        super().__init__()
        self._enabled = DEFAULT_CONFIG["enabled"]
        self._api_qps = DEFAULT_CONFIG["api_qps"]
        self._download_qps = DEFAULT_CONFIG["download_qps"]
        self._limit_sleep_seconds = DEFAULT_CONFIG["limit_sleep_seconds"]
        self._hourly_soft_limit = DEFAULT_CONFIG["hourly_soft_limit"]
        self._hourly_soft_cooldown = DEFAULT_CONFIG["hourly_soft_cooldown"]
        self._enable_event_log = DEFAULT_CONFIG["enable_event_log"]
        self._max_event_log_count = DEFAULT_CONFIG["max_event_log_count"]
        self._startup_log = DEFAULT_CONFIG["startup_log"]
        self._strict_mode = DEFAULT_CONFIG["strict_mode"]

        self._last_status = "未初始化"
        self._last_error = ""
        self._patched_instances = 0
        self._soft_limit_hits = 0
        self._hard_limit_hits = 0
        self._current_cooldown_reason = "未冷却"
        self._current_cooldown_remaining = 0
        self._last_event_source = "无"
        self._last_event_type = "无"
        self._event_logs: List[Dict[str, Any]] = []

    def init_plugin(self, config: dict = None):
        cfg = self._normalize_config(config)
        self._enabled = cfg["enabled"]
        self._api_qps = cfg["api_qps"]
        self._download_qps = cfg["download_qps"]
        self._limit_sleep_seconds = cfg["limit_sleep_seconds"]
        self._hourly_soft_limit = cfg["hourly_soft_limit"]
        self._hourly_soft_cooldown = cfg["hourly_soft_cooldown"]
        self._enable_event_log = cfg["enable_event_log"]
        self._max_event_log_count = cfg["max_event_log_count"]
        self._startup_log = cfg["startup_log"]
        self._strict_mode = cfg["strict_mode"]

        if not self._enabled:
            self._last_status = "插件已禁用，未应用补丁"
            self._last_error = ""
            self._restore_patch()
            return

        self._apply_patch()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        low_risk_note = (
            "当前默认值已经按低风控思路设置：普通接口 QPS=1、下载接口 QPS=1、"
            "115 返回访问上限后的冷却=3600 秒、小时软阈值=60、主动冷却=1200 秒。"
        )
        mp_default_note = (
            "按当前 MoviePilot 的 u115 默认实现，普通接口 QPS=3，下载接口 QPS=1，"
            "115 返回访问上限后的本地冷却=3600 秒。"
            "小时软阈值和主动冷却是本插件新增保护项，MP 原始默认并没有这两个参数。"
        )

        form = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": (
                                "此插件不会直接修改 MoviePilot 核心源码，而是在运行时为 u115 存储注入低风控参数。"
                            ),
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "text": low_risk_note,
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": mp_default_note,
                        },
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._build_switch_col("enabled", "启用插件"),
                            self._build_switch_col("startup_log", "启动时输出补丁日志"),
                            self._build_switch_col("strict_mode", "严格兼容模式"),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._build_text_col(
                                "api_qps",
                                "普通接口 QPS",
                                "目录解析、上传初始化、状态查询等普通请求的每秒上限。插件默认 1；MP 原始默认 3。",
                                1,
                                10,
                            ),
                            self._build_text_col(
                                "download_qps",
                                "下载接口 QPS",
                                "下载相关接口保持更保守的速率。插件默认 1；MP 原始默认也是 1。",
                                1,
                                10,
                            ),
                            self._build_text_col(
                                "limit_sleep_seconds",
                                "115 硬风控冷却秒数",
                                "当 115 返回“已达到当前访问上限”后，本地继续保持冷却的秒数。插件默认 3600；MP 原始默认也是 3600。",
                                60,
                                86400,
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._build_text_col(
                                "hourly_soft_limit",
                                "小时软阈值",
                                "1 小时内请求数达到此数量后，插件主动介入。插件默认 60；MP 原始没有这个参数。设为 0 表示关闭软阈值。",
                                0,
                                500,
                            ),
                            self._build_text_col(
                                "hourly_soft_cooldown",
                                "主动冷却秒数",
                                "达到小时软阈值后的主动冷却时长。插件默认 1200；MP 原始没有这个参数。设为 0 表示只记日志不暂停。",
                                0,
                                86400,
                            ),
                            self._build_text_col(
                                "max_event_log_count",
                                "事件日志保留条数",
                                "配置页和状态页里最多显示多少条最近事件。默认 50。",
                                10,
                                300,
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._build_switch_col("enable_event_log", "记录风控事件日志"),
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "success",
                                            "variant": "tonal",
                                            "text": (
                                                "推荐用法：先保持默认低风控值运行一段时间，再根据“风控事件日志”里的触发来源和阈值决定是否继续放宽。"
                                            ),
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
        return form, dict(DEFAULT_CONFIG)

    def get_page(self) -> List[dict]:
        status_text = self._last_status
        if self._last_error:
            status_text = f"{status_text} | {self._last_error}"

        logs = self._event_logs[-self._max_event_log_count :]
        log_rows = [self._build_event_row(event) for event in reversed(logs)]
        if not log_rows:
            log_rows = [
                {
                    "component": "div",
                    "props": {"class": "text-body-2"},
                    "text": "暂无风控事件。当前还没有命中 115 硬风控，也没有触发插件侧主动冷却。",
                }
            ]

        return [
            {
                "component": "VRow",
                "content": [
                    self._build_info_card(
                        title="运行状态",
                        lines=[
                            f"启用状态：{'已启用' if self._enabled else '已禁用'}",
                            f"补丁状态：{status_text}",
                            f"当前实例数：{self._patched_instances}",
                            f"最近事件来源：{self._last_event_source}",
                            f"最近事件类型：{self._last_event_type}",
                        ],
                    ),
                    self._build_info_card(
                        title="低风控默认值",
                        lines=[
                            f"普通接口 QPS：{self._api_qps}",
                            f"下载接口 QPS：{self._download_qps}",
                            f"115 硬风控冷却：{self._limit_sleep_seconds} 秒",
                            f"小时软阈值：{self._hourly_soft_limit}",
                            f"主动冷却：{self._hourly_soft_cooldown} 秒",
                        ],
                    ),
                ],
            },
            {
                "component": "VRow",
                "content": [
                    self._build_info_card(
                        title="风控统计",
                        lines=[
                            f"插件软阈值命中次数：{self._soft_limit_hits}",
                            f"115 硬风控命中次数：{self._hard_limit_hits}",
                            f"当前冷却状态：{self._current_cooldown_reason}",
                            f"当前剩余冷却：{self._current_cooldown_remaining} 秒",
                        ],
                    ),
                    self._build_info_card(
                        title="MP 原始默认值",
                        lines=[
                            f"普通接口 QPS：{MP_DEFAULTS['api_qps']}",
                            f"下载接口 QPS：{MP_DEFAULTS['download_qps']}",
                            f"115 硬风控冷却：{MP_DEFAULTS['limit_sleep_seconds']} 秒",
                            "小时软阈值：无",
                            "主动冷却：无",
                        ],
                    ),
                    self._build_info_card(
                        title="触发源判断",
                        lines=[
                            "一级来源：MoviePilot / 内置 u115",
                            "二级来源：插件侧主动冷却",
                            "事件会区分：补丁生效 / 插件软阈值 / 115 硬风控",
                            "建议根据事件来源决定是降 QPS 还是降每小时整理量",
                        ],
                    ),
                ],
            },
            {
                "component": "VCard",
                "props": {"variant": "tonal"},
                "content": [
                    {"component": "VCardTitle", "text": "最近风控事件日志"},
                    {
                        "component": "VCardText",
                        "content": log_rows,
                    },
                ],
            },
        ]

    def stop_service(self):
        self._restore_patch()

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "default", None

    def _apply_patch(self):
        try:
            from app.modules.filemanager.storages.u115 import U115Pan
            from app.utils.limit import QpsRateLimiter
        except Exception as exc:
            self._last_status = "补丁失败"
            self._last_error = f"无法导入 u115 相关模块: {exc}"
            logger.error(f"[U115RiskControl] {self._last_error}")
            return

        with self._patch_lock:
            original_init = getattr(U115Pan, "_u115riskcontrol_original_init", None)
            if original_init is None:
                original_init = U115Pan.__init__
                setattr(U115Pan, "_u115riskcontrol_original_init", original_init)

            original_request_api = getattr(U115Pan, "_u115riskcontrol_original_request_api", None)
            if original_request_api is None:
                original_request_api = U115Pan._request_api
                setattr(U115Pan, "_u115riskcontrol_original_request_api", original_request_api)

            api_qps = self._api_qps
            download_qps = self._download_qps
            limit_sleep_seconds = self._limit_sleep_seconds
            hourly_soft_limit = self._hourly_soft_limit
            hourly_soft_cooldown = self._hourly_soft_cooldown
            strict_mode = self._strict_mode
            startup_log = self._startup_log

            def patched_init(instance, *args, **kwargs):
                original_init(instance, *args, **kwargs)
                applied = self._patch_instance(
                    instance=instance,
                    QpsRateLimiter=QpsRateLimiter,
                    api_qps=api_qps,
                    download_qps=download_qps,
                    limit_sleep_seconds=limit_sleep_seconds,
                    hourly_soft_limit=hourly_soft_limit,
                    hourly_soft_cooldown=hourly_soft_cooldown,
                    strict_mode=strict_mode,
                )
                self._record_event(
                    event_type=EVENT_TYPE_PATCH_ACTIVE,
                    source="U115RiskControl / runtime patch",
                    endpoint="U115Pan.__init__",
                    threshold=f"api_qps={api_qps}, download_qps={download_qps}",
                    detail=f"已补丁实例，生效项：{applied}",
                    suggestion="继续观察后续 u115 请求是否按更保守的节奏执行。",
                )
                if startup_log:
                    logger.info(
                        "[U115RiskControl] u115 instance patched: "
                        f"api_qps={api_qps}, download_qps={download_qps}, "
                        f"limit_sleep_seconds={limit_sleep_seconds}, "
                        f"hourly_soft_limit={hourly_soft_limit}, "
                        f"hourly_soft_cooldown={hourly_soft_cooldown}, applied={applied}"
                    )

            def patched_request_api(instance, *args, **kwargs):
                endpoint = None
                if len(args) >= 2:
                    endpoint = args[1]
                elif "endpoint" in kwargs:
                    endpoint = kwargs.get("endpoint")

                self._maybe_soft_cooldown(
                    instance=instance,
                    endpoint=str(endpoint or ""),
                    hourly_soft_limit=hourly_soft_limit,
                    hourly_soft_cooldown=hourly_soft_cooldown,
                )

                result = original_request_api(instance, *args, **kwargs)
                self._inspect_hard_limit_response(
                    endpoint=str(endpoint or ""),
                    result=result,
                )
                return result

            U115Pan.__init__ = patched_init
            U115Pan._request_api = patched_request_api

            self._patched_instances = self._patch_live_instances(
                U115Pan=U115Pan,
                QpsRateLimiter=QpsRateLimiter,
                api_qps=api_qps,
                download_qps=download_qps,
                limit_sleep_seconds=limit_sleep_seconds,
                hourly_soft_limit=hourly_soft_limit,
                hourly_soft_cooldown=hourly_soft_cooldown,
                strict_mode=strict_mode,
            )

            self._patched = True
            self._last_status = "已应用运行时补丁"
            self._last_error = ""
            if self._startup_log:
                logger.info(
                    "[U115RiskControl] patch active: "
                    f"api_qps={api_qps}, download_qps={download_qps}, "
                    f"limit_sleep_seconds={limit_sleep_seconds}, "
                    f"hourly_soft_limit={hourly_soft_limit}, "
                    f"hourly_soft_cooldown={hourly_soft_cooldown}, "
                    f"live_instances={self._patched_instances}"
                )

    def _restore_patch(self):
        try:
            from app.modules.filemanager.storages.u115 import U115Pan
        except Exception:
            return

        with self._patch_lock:
            original_init = getattr(U115Pan, "_u115riskcontrol_original_init", None)
            if original_init is not None:
                U115Pan.__init__ = original_init

            original_request_api = getattr(U115Pan, "_u115riskcontrol_original_request_api", None)
            if original_request_api is not None:
                U115Pan._request_api = original_request_api

            self._patched = False

    def _patch_live_instances(
        self,
        *,
        U115Pan,
        QpsRateLimiter,
        api_qps: int,
        download_qps: int,
        limit_sleep_seconds: int,
        hourly_soft_limit: int,
        hourly_soft_cooldown: int,
        strict_mode: bool,
    ) -> int:
        count = 0
        for obj in gc.get_objects():
            try:
                if isinstance(obj, U115Pan):
                    self._patch_instance(
                        instance=obj,
                        QpsRateLimiter=QpsRateLimiter,
                        api_qps=api_qps,
                        download_qps=download_qps,
                        limit_sleep_seconds=limit_sleep_seconds,
                        hourly_soft_limit=hourly_soft_limit,
                        hourly_soft_cooldown=hourly_soft_cooldown,
                        strict_mode=strict_mode,
                    )
                    count += 1
            except Exception:
                continue
        return count

    def _patch_instance(
        self,
        *,
        instance,
        QpsRateLimiter,
        api_qps: int,
        download_qps: int,
        limit_sleep_seconds: int,
        hourly_soft_limit: int,
        hourly_soft_cooldown: int,
        strict_mode: bool,
    ) -> str:
        applied: List[str] = []

        if hasattr(instance, "_api_limiter"):
            instance._api_limiter = QpsRateLimiter(api_qps)
            applied.append("_api_limiter")
        elif strict_mode:
            logger.warning("[U115RiskControl] current U115Pan instance has no _api_limiter")

        if hasattr(instance, "_download_limiter"):
            instance._download_limiter = QpsRateLimiter(download_qps)
            applied.append("_download_limiter")
        elif strict_mode:
            logger.warning("[U115RiskControl] current U115Pan instance has no _download_limiter")

        if hasattr(instance, "limit_sleep_seconds"):
            instance.limit_sleep_seconds = limit_sleep_seconds
            applied.append("limit_sleep_seconds")
        elif strict_mode:
            logger.warning("[U115RiskControl] current U115Pan instance has no limit_sleep_seconds")

        if hasattr(instance.__class__, "limit_sleep_seconds"):
            instance.__class__.limit_sleep_seconds = limit_sleep_seconds

        instance._u115riskcontrol_runtime = {
            "api_qps": api_qps,
            "download_qps": download_qps,
            "limit_sleep_seconds": limit_sleep_seconds,
            "hourly_soft_limit": hourly_soft_limit,
            "hourly_soft_cooldown": hourly_soft_cooldown,
        }
        if not hasattr(instance, "_u115riskcontrol_hour_timestamps"):
            instance._u115riskcontrol_hour_timestamps = deque()
        if not hasattr(instance, "_u115riskcontrol_soft_limit_until"):
            instance._u115riskcontrol_soft_limit_until = 0.0
        return ",".join(applied) if applied else "none"

    def _maybe_soft_cooldown(
        self,
        *,
        instance,
        endpoint: str,
        hourly_soft_limit: int,
        hourly_soft_cooldown: int,
    ) -> None:
        if not hourly_soft_limit:
            return

        now = time.time()
        timestamps: Optional[Deque[float]] = getattr(instance, "_u115riskcontrol_hour_timestamps", None)
        if timestamps is None:
            timestamps = deque()
            instance._u115riskcontrol_hour_timestamps = timestamps

        limit_until = float(getattr(instance, "_u115riskcontrol_soft_limit_until", 0.0) or 0.0)
        if limit_until > now:
            remaining = int(limit_until - now)
            self._current_cooldown_reason = "插件主动冷却"
            self._current_cooldown_remaining = max(remaining, 0)
            if remaining > 0:
                logger.warning(
                    "[U115RiskControl] hourly soft cooldown active: "
                    f"endpoint={endpoint}, remaining={remaining}s"
                )
                time.sleep(remaining)
                now = time.time()

        while timestamps and now - timestamps[0] >= 3600:
            timestamps.popleft()

        if len(timestamps) >= hourly_soft_limit:
            self._soft_limit_hits += 1
            self._last_event_source = "U115RiskControl / 插件软阈值"
            self._last_event_type = EVENT_TYPE_SOFT_LIMIT
            self._current_cooldown_reason = "插件主动冷却"
            self._current_cooldown_remaining = hourly_soft_cooldown
            instance._u115riskcontrol_soft_limit_until = now + max(hourly_soft_cooldown, 0)
            self._record_event(
                event_type=EVENT_TYPE_SOFT_LIMIT,
                source="U115RiskControl / 插件软阈值",
                endpoint=endpoint,
                threshold=f"hourly_soft_limit={hourly_soft_limit}",
                detail=f"最近 1 小时累计请求数达到 {len(timestamps)}，主动冷却 {hourly_soft_cooldown} 秒。",
                suggestion="说明插件已经在 115 硬风控前主动介入；如仍频繁触发，可继续降低每小时整理量。",
            )
            if hourly_soft_cooldown > 0:
                logger.warning(
                    "[U115RiskControl] hourly soft limit reached: "
                    f"endpoint={endpoint}, limit={hourly_soft_limit}, cooldown={hourly_soft_cooldown}s"
                )
                time.sleep(hourly_soft_cooldown)
                now = time.time()
                while timestamps and now - timestamps[0] >= 3600:
                    timestamps.popleft()

        timestamps.append(now)
        self._current_cooldown_remaining = 0
        if self._current_cooldown_reason == "插件主动冷却":
            self._current_cooldown_reason = "未冷却"

    def _inspect_hard_limit_response(self, *, endpoint: str, result: Any) -> None:
        message = self._extract_message(result)
        if "已达到当前访问上限" not in message:
            return

        self._hard_limit_hits += 1
        self._last_event_source = "MoviePilot / 内置 u115"
        self._last_event_type = EVENT_TYPE_HARD_LIMIT
        self._current_cooldown_reason = "115 硬风控"
        self._current_cooldown_remaining = self._limit_sleep_seconds
        self._record_event(
            event_type=EVENT_TYPE_HARD_LIMIT,
            source="MoviePilot / 内置 u115",
            endpoint=endpoint,
            threshold=f"limit_sleep_seconds={self._limit_sleep_seconds}",
            detail="115 返回“已达到当前访问上限”，说明当前命中的是账号侧硬风控。",
            suggestion="优先降低每小时整理量，而不是只调整瞬时 QPS。",
        )

    def _extract_message(self, result: Any) -> str:
        if isinstance(result, dict):
            for key in ("message", "msg", "error"):
                value = result.get(key)
                if isinstance(value, str):
                    return value
        return str(result or "")

    def _record_event(
        self,
        *,
        event_type: str,
        source: str,
        endpoint: str,
        threshold: str,
        detail: str,
        suggestion: str,
    ) -> None:
        self._last_event_source = source
        self._last_event_type = event_type
        if not self._enable_event_log:
            return

        event = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "endpoint": endpoint,
            "event_type": event_type,
            "threshold": threshold,
            "detail": detail,
            "suggestion": suggestion,
        }
        with self._event_lock:
            self._event_logs.append(event)
            if len(self._event_logs) > self._max_event_log_count:
                self._event_logs = self._event_logs[-self._max_event_log_count :]

    def _build_switch_col(self, model: str, label: str) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 4},
            "content": [
                {
                    "component": "VSwitch",
                    "props": {
                        "model": model,
                        "label": label,
                    },
                }
            ],
        }

    def _build_text_col(
        self,
        model: str,
        label: str,
        hint: str,
        minimum: int,
        maximum: int,
    ) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 4},
            "content": [
                {
                    "component": "VTextField",
                    "props": {
                        "model": model,
                        "label": label,
                        "type": "number",
                        "min": minimum,
                        "max": maximum,
                        "hint": hint,
                        "persistent-hint": True,
                    },
                }
            ],
        }

    def _build_info_card(self, *, title: str, lines: List[str]) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 6},
            "content": [
                {
                    "component": "VCard",
                    "props": {"variant": "tonal"},
                    "content": [
                        {"component": "VCardTitle", "text": title},
                        {
                            "component": "VCardText",
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "text-body-2 mb-2"},
                                    "text": line,
                                }
                                for line in lines
                            ],
                        },
                    ],
                }
            ],
        }

    def _build_event_row(self, event: Dict[str, Any]) -> Dict[str, Any]:
        title = f"{event.get('time')} | {event.get('source')}"
        body = (
            f"事件类型：{event.get('event_type')} | "
            f"接口：{event.get('endpoint')} | "
            f"命中阈值：{event.get('threshold')}"
        )
        detail = str(event.get("detail") or "")
        suggestion = str(event.get("suggestion") or "")
        return {
            "component": "VCard",
            "props": {"class": "mb-3", "variant": "outlined"},
            "content": [
                {"component": "VCardTitle", "text": title},
                {
                    "component": "VCardText",
                    "content": [
                        {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": body},
                        {"component": "div", "props": {"class": "text-body-2 mb-2"}, "text": detail},
                        {"component": "div", "props": {"class": "text-caption"}, "text": f"建议：{suggestion}"},
                    ],
                },
            ],
        }

    def _normalize_config(self, config: Optional[dict]) -> Dict[str, Any]:
        merged = dict(DEFAULT_CONFIG)
        if isinstance(config, dict):
            merged.update(config)

        return {
            "enabled": self._to_bool(merged.get("enabled"), DEFAULT_CONFIG["enabled"]),
            "api_qps": self._to_int(merged.get("api_qps"), DEFAULT_CONFIG["api_qps"], minimum=1, maximum=10),
            "download_qps": self._to_int(
                merged.get("download_qps"),
                DEFAULT_CONFIG["download_qps"],
                minimum=1,
                maximum=10,
            ),
            "limit_sleep_seconds": self._to_int(
                merged.get("limit_sleep_seconds"),
                DEFAULT_CONFIG["limit_sleep_seconds"],
                minimum=60,
                maximum=86400,
            ),
            "hourly_soft_limit": self._to_int(
                merged.get("hourly_soft_limit"),
                DEFAULT_CONFIG["hourly_soft_limit"],
                minimum=0,
                maximum=500,
            ),
            "hourly_soft_cooldown": self._to_int(
                merged.get("hourly_soft_cooldown"),
                DEFAULT_CONFIG["hourly_soft_cooldown"],
                minimum=0,
                maximum=86400,
            ),
            "enable_event_log": self._to_bool(
                merged.get("enable_event_log"),
                DEFAULT_CONFIG["enable_event_log"],
            ),
            "max_event_log_count": self._to_int(
                merged.get("max_event_log_count"),
                DEFAULT_CONFIG["max_event_log_count"],
                minimum=10,
                maximum=300,
            ),
            "startup_log": self._to_bool(merged.get("startup_log"), DEFAULT_CONFIG["startup_log"]),
            "strict_mode": self._to_bool(merged.get("strict_mode"), DEFAULT_CONFIG["strict_mode"]),
        }

    @staticmethod
    def _to_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "on"}:
                return True
            if lowered in {"0", "false", "no", "n", "off"}:
                return False
        return bool(value)

    @staticmethod
    def _to_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))
