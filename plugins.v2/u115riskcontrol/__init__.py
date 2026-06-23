import gc
import hashlib
import inspect
import re
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
    "retry_failed_after_cooldown": True,
    "retry_failed_on_startup": True,
    "retry_failed_delay_seconds": 60,
    "retry_failed_max_count": 1,
}

RETRY_DATA_KEY = "failed_transfer_retry"
RETRY_DATA_VERSION = 2
RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW = 3
RETRY_HISTORY_WINDOW_SECONDS = 86400
RETRY_MANUAL_REQUIRED_FAILURES = 9

MP_DEFAULTS = {
    "api_qps": 3,
    "download_qps": 1,
    "limit_sleep_seconds": 3600,
}

EVENT_TYPE_PATCH_ACTIVE = "patch_active"
EVENT_TYPE_SOFT_LIMIT = "soft_limit_triggered"
EVENT_TYPE_HARD_LIMIT = "115_limit_triggered"
EVENT_TYPE_RETRY_SCHEDULED = "failed_transfer_retry_scheduled"
EVENT_TYPE_RETRY_STARTED = "failed_transfer_retry_started"
EVENT_TYPE_RETRY_PROGRESS = "failed_transfer_retry_progress"
EVENT_TYPE_RETRY_FINISHED = "failed_transfer_retry_finished"
EVENT_TYPE_RETRY_SKIPPED = "failed_transfer_retry_skipped"


class U115RiskControl(_PluginBase):
    plugin_name = "u115风控参数"
    plugin_desc = "为 MoviePilot 的 u115 存储提供低风控参数、风控日志和失败整理冷却后重试。"
    plugin_icon = "U115RiskControl.jpg"
    plugin_version = "0.1.15"
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
        self._retry_failed_after_cooldown = DEFAULT_CONFIG["retry_failed_after_cooldown"]
        self._retry_failed_on_startup = DEFAULT_CONFIG["retry_failed_on_startup"]
        self._retry_failed_delay_seconds = DEFAULT_CONFIG["retry_failed_delay_seconds"]
        self._retry_failed_max_count = DEFAULT_CONFIG["retry_failed_max_count"]

        self._last_status = "未初始化"
        self._last_error = ""
        self._patched_instances = 0
        self._soft_limit_hits = 0
        self._hard_limit_hits = 0
        self._current_cooldown_reason = "未冷却"
        self._current_cooldown_remaining = 0
        self._current_cooldown_until = 0.0
        self._last_event_source = "无"
        self._last_event_type = "无"
        self._retry_lock = threading.Lock()
        self._retry_threads: List[threading.Thread] = []
        self._retry_in_progress = False
        self._retry_scheduled_until = 0.0
        self._retry_scheduled_reason = "无"
        self._last_retry_status = "未执行"
        self._last_retry_time = "无"
        self._last_retry_total = 0
        self._last_retry_success = 0
        self._last_retry_failed = 0
        self._last_retry_skipped = 0
        self._last_retry_failed_history_count = 0
        self._last_retry_cooldown_count = 0
        self._last_retry_retryable_count = 0
        self._last_retry_manual_required_count = 0
        self._last_retry_progress = "未开始"
        self._last_retry_current_task = "无"
        self._last_retry_progress_detail = "无"
        self._retry_reschedule_reason = ""
        self._retry_reschedule_delay_seconds = 0
        self._last_native_limit_until = 0.0
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
        self._retry_failed_after_cooldown = cfg["retry_failed_after_cooldown"]
        self._retry_failed_on_startup = cfg["retry_failed_on_startup"]
        self._retry_failed_delay_seconds = cfg["retry_failed_delay_seconds"]
        self._retry_failed_max_count = cfg["retry_failed_max_count"]

        if not self._enabled:
            self._last_status = "插件已禁用，未应用补丁"
            self._last_error = ""
            self._restore_patch()
            return

        self._restore_retry_state()
        self._apply_patch()
        self._schedule_startup_failed_transfer_retry()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/u115riskcontrol/status",
                "endpoint": self.get_live_status,
                "methods": ["GET"],
                "summary": "获取 U115RiskControl 实时状态",
                "description": "返回当前冷却、失败整理重试和事件日志快照，供前端轮询刷新使用。",
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        try:
            return self._get_form_impl()
        except Exception as exc:
            logger.exception("[U115RiskControl] get_form render failed")
            fallback_form = [
                {
                    "component": "VForm",
                    "content": [
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [
                                        {
                                            "component": "VAlert",
                                            "props": {
                                                "type": "error",
                                                "variant": "tonal",
                                                "title": "配置页渲染失败",
                                                "text": f"插件配置页渲染异常：{exc}",
                                            },
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "component": "VRow",
                            "content": [
                                self._build_switch_col("enabled", "启用插件", sm=12),
                            ],
                        },
                    ],
                }
            ]
            return fallback_form, dict(DEFAULT_CONFIG)

    def get_page(self) -> List[dict]:
        try:
            return self._get_page_impl()
        except Exception as exc:
            logger.exception("[U115RiskControl] get_page render failed")
            return [
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "VAlert",
                                    "props": {
                                        "type": "error",
                                        "variant": "tonal",
                                        "title": "状态页渲染失败",
                                        "text": f"插件状态页渲染异常：{exc}",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]

    def _get_form_impl(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        form = [
            {
                "component": "VForm",
                "content": [
                    self._build_section_title("基础"),
                    {
                        "component": "VRow",
                        "content": [
                            self._build_switch_col("enabled", "启用插件", sm=4),
                            self._build_switch_col("startup_log", "启动日志", sm=4),
                            self._build_switch_col("strict_mode", "严格兼容", sm=4),
                        ],
                    },
                    {"component": "VDivider", "props": {"class": "my-4"}},
                    self._build_section_title("风控参数"),
                    {
                        "component": "VRow",
                        "content": [
                            self._build_text_col("api_qps", "普通接口 QPS", "范围 1-10", 1, 10),
                            self._build_text_col("download_qps", "下载接口 QPS", "范围 1-10", 1, 10),
                            self._build_text_col(
                                "limit_sleep_seconds",
                                "硬风控冷却",
                                "范围 60-86400",
                                60,
                                86400,
                                suffix="秒",
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._build_text_col("hourly_soft_limit", "小时软阈值", "0 表示关闭", 0, 500),
                            self._build_text_col(
                                "hourly_soft_cooldown",
                                "主动冷却",
                                "0 只记录日志",
                                0,
                                86400,
                                suffix="秒",
                            ),
                            self._build_note_col(
                                f"MP 默认：普通 QPS {MP_DEFAULTS['api_qps']}，"
                                f"下载 QPS {MP_DEFAULTS['download_qps']}，"
                                f"硬风控冷却 {MP_DEFAULTS['limit_sleep_seconds']} 秒"
                            ),
                        ],
                    },
                    {"component": "VDivider", "props": {"class": "my-4"}},
                    self._build_section_title("失败整理重试"),
                    {
                        "component": "VRow",
                        "content": [
                            self._build_switch_col("retry_failed_after_cooldown", "冷却后重试", sm=3),
                            self._build_switch_col("retry_failed_on_startup", "启动后补扫", sm=3),
                            self._build_text_col(
                                "retry_failed_delay_seconds",
                                "重试等待",
                                "冷却结束后等待",
                                0,
                                86400,
                                sm=3,
                                suffix="秒",
                            ),
                            self._build_text_col(
                                "retry_failed_max_count",
                                "单次最大条数",
                                "0 表示不限",
                                0,
                                100,
                                sm=3,
                            ),
                        ],
                    },
                    self._build_inline_alert("warning", "仅重试 MP 当前仍失败的整理历史。"),
                    {"component": "VDivider", "props": {"class": "my-4"}},
                    self._build_section_title("日志与高级"),
                    {
                        "component": "VRow",
                        "content": [
                            self._build_switch_col("enable_event_log", "记录事件日志", sm=4),
                            self._build_text_col(
                                "max_event_log_count",
                                "日志保留条数",
                                "范围 10-300",
                                10,
                                300,
                                sm=4,
                            ),
                        ],
                    },
                ],
            }
        ]
        return form, dict(DEFAULT_CONFIG)

    def _get_page_impl(self) -> List[dict]:
        snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs = self._event_logs[-self._max_event_log_count :]
        event_text = self._format_event_preview(logs)
        scheduled_text = "无"
        if self._retry_in_progress:
            scheduled_text = "正在执行"
        elif self._retry_scheduled_until > time.time():
            remaining = int(self._retry_scheduled_until - time.time())
            scheduled_time = datetime.fromtimestamp(self._retry_scheduled_until).strftime("%Y-%m-%d %H:%M:%S")
            scheduled_text = f"{scheduled_time}，约 {remaining} 秒后"

        overall_status = self._build_overall_status(scheduled_text=scheduled_text)
        current_cooldown_remaining = self._get_current_cooldown_remaining()

        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": overall_status["type"],
                                    "variant": "tonal",
                                    "density": "compact",
                                    "title": overall_status["title"],
                                    "text": f"{overall_status['text']}\n页面快照：{snapshot_time}",
                                },
                            }
                        ],
                    }
                ],
            },
            self._build_inline_alert(
                "info",
                "MoviePilot 当前状态弹窗不会自动重新请求插件页面；倒计时为打开页面时的快照。"
                "如需秒级跳动，需要接入插件实时状态 API 做前端轮询。",
            ),
            {
                "component": "VRow",
                "content": [
                    self._build_status_col(
                        "风控",
                        "warning",
                        (
                            f"软阈值命中 {self._soft_limit_hits}\n"
                            f"硬风控命中 {self._hard_limit_hits}\n"
                            f"当前冷却 {self._current_cooldown_reason}\n"
                            f"剩余 {current_cooldown_remaining} 秒"
                        ),
                    ),
                    self._build_status_col(
                        "生效参数",
                        "success",
                        (
                            f"普通 QPS {self._api_qps}\n"
                            f"下载 QPS {self._download_qps}\n"
                            f"硬风控冷却 {self._limit_sleep_seconds} 秒\n"
                            f"软阈值 {self._hourly_soft_limit} / 主动冷却 {self._hourly_soft_cooldown} 秒"
                        ),
                    ),
                    self._build_status_col(
                        "失败整理重试",
                        self._retry_status_alert_type(),
                        (
                            f"最近状态 {self._last_retry_status}\n"
                            f"最近时间 {self._last_retry_time}\n"
                            f"成功 {self._last_retry_success} / 失败 {self._last_retry_failed} / 跳过 {self._last_retry_skipped}\n"
                            f"失败历史 {self._last_retry_failed_history_count} / 冷却中 {self._last_retry_cooldown_count} / 可重试 {self._last_retry_retryable_count}\n"
                            f"需人工 {self._last_retry_manual_required_count}\n"
                            f"计划时间 {scheduled_text}\n"
                            f"快照时间 {snapshot_time}"
                        ),
                    ),
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
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "density": "compact",
                                    "title": "整理进度",
                                    "text": (
                                        f"当前进度：{self._last_retry_progress}\n"
                                        f"当前任务：{self._last_retry_current_task}\n"
                                        f"详情：{self._last_retry_progress_detail}"
                                    ),
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "component": "VRow",
                "props": {"class": "mt-2"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "label": "最近事件",
                                    "modelValue": event_text,
                                    "readonly": True,
                                    "rows": 8,
                                    "auto-grow": True,
                                },
                            }
                        ],
                    }
                ],
            },
        ]

    def get_live_status(self) -> Dict[str, Any]:
        return self._build_live_status()

    def stop_service(self):
        self._restore_patch()
        self._retry_scheduled_until = 0.0
        self._retry_in_progress = False

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vuetify", None

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
                endpoint_text = str(endpoint or "")
                request_started_at = time.time()
                before_limit_until = self._get_native_limit_until(instance)

                self._inspect_native_limit_window(
                    instance=instance,
                    endpoint=endpoint_text,
                    before_limit_until=0.0,
                    after_limit_until=before_limit_until,
                    request_started_at=request_started_at,
                    phase="before_request",
                )

                self._maybe_soft_cooldown(
                    instance=instance,
                    endpoint=endpoint_text,
                    hourly_soft_limit=hourly_soft_limit,
                    hourly_soft_cooldown=hourly_soft_cooldown,
                )

                result = original_request_api(instance, *args, **kwargs)
                after_limit_until = self._get_native_limit_until(instance)
                self._inspect_native_limit_window(
                    instance=instance,
                    endpoint=endpoint_text,
                    before_limit_until=before_limit_until,
                    after_limit_until=after_limit_until,
                    request_started_at=request_started_at,
                    phase="after_request",
                )
                self._inspect_hard_limit_response(
                    endpoint=endpoint_text,
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
            self._current_cooldown_until = now + max(remaining, 0)
            if remaining > 0:
                logger.warning(
                    "[U115RiskControl] hourly soft cooldown active: "
                    f"endpoint={endpoint}, remaining={remaining}s"
                )
                time.sleep(remaining)
                self._schedule_failed_transfer_retry("插件主动冷却结束")
                now = time.time()

        while timestamps and now - timestamps[0] >= 3600:
            timestamps.popleft()

        if len(timestamps) >= hourly_soft_limit:
            self._soft_limit_hits += 1
            self._last_event_source = "U115RiskControl / 插件软阈值"
            self._last_event_type = EVENT_TYPE_SOFT_LIMIT
            self._current_cooldown_reason = "插件主动冷却"
            self._current_cooldown_remaining = hourly_soft_cooldown
            self._current_cooldown_until = now + max(hourly_soft_cooldown, 0)
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
                self._schedule_failed_transfer_retry("插件软阈值冷却结束")
                now = time.time()
                while timestamps and now - timestamps[0] >= 3600:
                    timestamps.popleft()

        timestamps.append(now)
        self._current_cooldown_remaining = 0
        if self._current_cooldown_reason == "插件主动冷却":
            self._current_cooldown_reason = "未冷却"
            self._current_cooldown_until = 0.0

    def _inspect_hard_limit_response(self, *, endpoint: str, result: Any) -> None:
        message = self._extract_message(result)
        if "已达到当前访问上限" not in message:
            return

        self._hard_limit_hits += 1
        self._last_event_source = "MoviePilot / 内置 u115"
        self._last_event_type = EVENT_TYPE_HARD_LIMIT
        self._current_cooldown_reason = "115 硬风控"
        self._current_cooldown_remaining = self._limit_sleep_seconds
        self._current_cooldown_until = time.time() + max(self._limit_sleep_seconds, 0)
        self._schedule_failed_transfer_retry("115 硬风控冷却结束", delay_seconds=self._limit_sleep_seconds)
        self._record_event(
            event_type=EVENT_TYPE_HARD_LIMIT,
            source="MoviePilot / 内置 u115",
            endpoint=endpoint,
            threshold=f"limit_sleep_seconds={self._limit_sleep_seconds}",
            detail="115 返回“已达到当前访问上限”，说明当前命中的是账号侧硬风控。",
            suggestion="优先降低每小时整理量，而不是只调整瞬时 QPS。",
        )

    @staticmethod
    def _get_native_limit_until(instance) -> float:
        try:
            return float(getattr(instance, "_limit_until", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _inspect_native_limit_window(
        self,
        *,
        instance,
        endpoint: str,
        before_limit_until: float,
        after_limit_until: float,
        request_started_at: float,
        phase: str,
    ) -> None:
        if after_limit_until <= 0:
            return

        now = time.time()
        detected_existing_cooldown = phase == "before_request" and after_limit_until > now
        detected_new_cooldown = (
            phase == "after_request"
            and after_limit_until > request_started_at
            and after_limit_until > before_limit_until + 1
        )
        if not detected_existing_cooldown and not detected_new_cooldown:
            return
        if abs(after_limit_until - self._last_native_limit_until) < 1:
            return
        self._last_native_limit_until = after_limit_until

        remaining = max(int(after_limit_until - now), 0)
        self._hard_limit_hits += 1
        self._last_event_source = "MoviePilot / 内置 u115"
        self._last_event_type = EVENT_TYPE_HARD_LIMIT
        self._current_cooldown_reason = "115 硬风控"
        self._current_cooldown_remaining = remaining
        self._current_cooldown_until = now + max(remaining, 0)

        reason = "115 硬风控冷却结束"
        self._schedule_failed_transfer_retry(reason, delay_seconds=remaining)
        self._record_event(
            event_type=EVENT_TYPE_HARD_LIMIT,
            source="MoviePilot / 内置 u115",
            endpoint=endpoint,
            threshold=f"_limit_until={datetime.fromtimestamp(after_limit_until).strftime('%Y-%m-%d %H:%M:%S')}",
            detail=(
                "检测到 MoviePilot 内置 u115 已进入风控冷却窗口。"
                f"阶段：{phase}，剩余约 {remaining} 秒。"
            ),
            suggestion="插件已按 MP 内置冷却结束时间安排失败整理重试；如仍无候选任务，请检查整理历史是否缺少可复用的源文件项。",
        )

    def _schedule_startup_failed_transfer_retry(self) -> None:
        if not self._enabled or not self._retry_failed_after_cooldown or not self._retry_failed_on_startup:
            return

        delay_seconds = 0
        cooldown_count = 0
        try:
            from app.modules.filemanager.storages.u115 import U115Pan
            for obj in gc.get_objects():
                try:
                    if isinstance(obj, U115Pan):
                        limit_until = self._get_native_limit_until(obj)
                        remaining = int(limit_until - time.time())
                        if remaining > delay_seconds:
                            delay_seconds = remaining
                        if remaining > 0:
                            cooldown_count += 1
                except Exception:
                    continue
        except Exception:
            delay_seconds = 0

        if delay_seconds > 0:
            reason = "插件启动补偿扫描：等待现有 115 冷却结束"
        else:
            reason = "插件启动补偿扫描：当前未检测到 115 冷却"
        self._schedule_failed_transfer_retry(reason, delay_seconds=max(delay_seconds, 0))
        self._record_event(
            event_type=EVENT_TYPE_RETRY_SCHEDULED,
            source="U115RiskControl / startup retry scan",
            endpoint="TransferHistory",
            threshold=f"native_cooldown_instances={cooldown_count}, delay={max(delay_seconds, 0)}s",
            detail="插件启动后已安排一次失败整理补偿扫描，用于处理安装新版本前已结束的冷却期。",
            suggestion="若失败整理历史仍未被处理，请查看状态页最近重试状态，确认是否为无候选任务、已重试过或 MP 接口不可用。",
        )

    def _schedule_failed_transfer_retry(self, reason: str, delay_seconds: Optional[int] = None) -> None:
        if not self._retry_failed_after_cooldown:
            self._last_retry_status = "已关闭"
            return

        delay = max(int(delay_seconds if delay_seconds is not None else 0), 0)
        delay += max(int(self._retry_failed_delay_seconds), 0)
        scheduled_until = time.time() + delay

        with self._retry_lock:
            if self._retry_in_progress:
                self._record_event(
                    event_type=EVENT_TYPE_RETRY_SKIPPED,
                    source="U115RiskControl / failed transfer retry",
                    endpoint="TransferHistory",
                    threshold="retry_in_progress=True",
                    detail="已有失败整理重试任务正在执行，本次不重复启动。",
                    suggestion="等待当前后台重试完成后再观察状态页。",
                )
                return
            if self._retry_scheduled_until and self._retry_scheduled_until >= scheduled_until:
                return
            self._retry_scheduled_until = scheduled_until
            self._retry_scheduled_reason = reason
            thread = threading.Thread(
                target=self._run_failed_transfer_retry_after_delay,
                args=(scheduled_until, reason),
                name="U115RiskControlFailedTransferRetry",
                daemon=True,
            )
            self._retry_threads.append(thread)
            thread.start()

        self._record_event(
            event_type=EVENT_TYPE_RETRY_SCHEDULED,
            source="U115RiskControl / failed transfer retry",
            endpoint="TransferHistory",
            threshold=f"delay={delay}s, max_count={self._retry_failed_max_count}",
            detail=f"已计划在风控期后重试 MP 失败整理任务，原因：{reason}。",
            suggestion="如果失败任务很多，建议保持较小的单次重试条数，避免恢复后立即再次触发风控。",
        )

    def _run_failed_transfer_retry_after_delay(self, scheduled_until: float, reason: str) -> None:
        wait_seconds = max(int(scheduled_until - time.time()), 0)
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        with self._retry_lock:
            if not self._enabled or not self._retry_failed_after_cooldown:
                self._last_retry_status = "已取消"
                return
            if scheduled_until < self._retry_scheduled_until:
                return
            self._retry_scheduled_until = 0.0
            self._retry_in_progress = True

        try:
            self._retry_failed_transfer_histories(reason)
        except Exception as exc:
            self._last_retry_status = f"执行异常：{exc}"
            self._last_retry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.exception("[U115RiskControl] failed transfer retry crashed")
            self._record_event(
                event_type=EVENT_TYPE_RETRY_FINISHED,
                source="U115RiskControl / failed transfer retry",
                endpoint="TransferHistory",
                threshold="exception",
                detail=f"失败整理重试异常：{exc}",
                suggestion="请检查 MoviePilot 日志中的具体整理失败原因。",
            )
        finally:
            with self._retry_lock:
                self._retry_in_progress = False
                self._retry_threads = [thread for thread in self._retry_threads if thread.is_alive()]

        if self._retry_reschedule_reason:
            next_reason = self._retry_reschedule_reason
            next_delay = max(int(self._retry_reschedule_delay_seconds), 0)
            self._retry_reschedule_reason = ""
            self._retry_reschedule_delay_seconds = 0
            self._schedule_failed_transfer_retry(next_reason, delay_seconds=next_delay)

    def _retry_failed_transfer_histories(self, reason: str) -> None:
        self._last_retry_status = "执行中"
        self._last_retry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._record_event(
            event_type=EVENT_TYPE_RETRY_STARTED,
            source="U115RiskControl / failed transfer retry",
            endpoint="TransferHistory",
            threshold=(
                f"max_count={self._retry_failed_max_count}, "
                f"rolling_window={RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW}/{RETRY_HISTORY_WINDOW_SECONDS}s"
            ),
            detail=f"开始重试 MP 失败整理任务，触发原因：{reason}。",
            suggestion="重试期间请关注是否再次出现 115 风控事件。",
        )
        self._update_retry_progress("扫描失败历史", "无", f"触发原因：{reason}")

        try:
            from app.chain.transfer import TransferChain
            from app.db.transferhistory_oper import TransferHistoryOper
            from app.db.models.transferhistory import TransferHistory
            from app.schemas import FileItem, MediaType
            from app.schemas.transfer import EpisodeFormat
        except Exception as exc:
            self._last_retry_status = "MP 接口不可用"
            self._last_retry_failed = 1
            self._record_event(
                event_type=EVENT_TYPE_RETRY_FINISHED,
                source="U115RiskControl / failed transfer retry",
                endpoint="import",
                threshold="mp_import_failed",
                detail=f"无法导入 MoviePilot 整理相关模块：{exc}",
                suggestion="确认当前运行环境为 MoviePilot V2，且整理模块路径未变更。",
            )
            return

        retry_state = self._load_retry_state()
        retry_records = retry_state.setdefault("records", {})
        now_ts = time.time()
        histories = self._list_failed_transfer_histories(TransferHistoryOper, TransferHistory)
        candidates = []
        candidate_details: List[str] = []
        skipped_details: List[str] = []
        cooldown_details: List[str] = []
        handled_details: List[str] = []
        source_missing_details: List[str] = []
        manual_required_details: List[str] = []
        earliest_next_retry_after = 0.0
        already_handled_count = 0
        cooldown_count = 0
        retryable_count = 0
        manual_required_count = 0

        for history in histories:
            history_id = str(getattr(history, "id", ""))
            history_summary = self._format_transfer_history_summary(history)
            if not history_id:
                skipped_details.append(f"{history_summary}: 缺少历史ID")
                continue

            retry_record = retry_records.get(history_id) if isinstance(retry_records, dict) else None
            if not isinstance(retry_record, dict):
                retry_record = {}
            retry_record = self._normalize_retry_record(retry_record, now_ts)

            existing_success, existing_message = self._verify_existing_success_history(
                history=history,
                TransferHistoryOper=TransferHistoryOper,
            )
            target_exists = self._target_file_exists(history)
            if existing_success or target_exists:
                already_handled_count += 1
                retry_records[history_id] = self._build_retry_record(
                    history=history,
                    previous=retry_record,
                    attempt_ts=None,
                    state=True,
                    message=existing_message or "目标媒体库文件已存在，不再重复补整理",
                    manual_required=False,
                )
                handled_details.append(f"{history_summary}: 已确认成功或目标已存在")
                continue
            if retry_record.get("success") is True:
                retry_record["success"] = False
                retry_record["message"] = "此前成功标记未复查到成功历史或目标文件，重新进入滚动重试"

            if retry_record.get("manual_required") is True:
                manual_required_count += 1
                manual_required_details.append(f"{history_summary}: 需要人工处理")
                continue

            attempt_timestamps = self._get_recent_attempt_timestamps(retry_record, now_ts)
            if len(attempt_timestamps) >= RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW:
                next_retry_after = min(attempt_timestamps) + RETRY_HISTORY_WINDOW_SECONDS
                retry_record["attempt_timestamps"] = attempt_timestamps
                retry_record["next_retry_after"] = next_retry_after
                retry_record["success"] = False
                retry_record["message"] = "24 小时重试冷却中"
                retry_record["manual_required"] = False
                retry_records[history_id] = retry_record
                cooldown_count += 1
                if not earliest_next_retry_after or next_retry_after < earliest_next_retry_after:
                    earliest_next_retry_after = next_retry_after
                remaining = int(next_retry_after - now_ts)
                cooldown_details.append(f"{history_summary}: 24 小时重试冷却中，剩余 {max(remaining, 0)} 秒")
                continue

            retryable_count += 1
            if self._retry_failed_max_count and len(candidates) >= self._retry_failed_max_count:
                skipped_details.append(f"{history_summary}: 超过单次上限")
                continue
            candidates.append(history)
            candidate_details.append(
                f"{history_summary}: 24 小时内第 {len(attempt_timestamps) + 1}/"
                f"{RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW} 次补整理"
            )

        total = len(candidates)
        success_count = 0
        failed_count = 0
        skipped_count = len(skipped_details)
        failure_details: List[str] = []

        self._last_retry_failed_history_count = len(histories)
        self._last_retry_cooldown_count = cooldown_count
        self._last_retry_retryable_count = retryable_count
        self._last_retry_manual_required_count = manual_required_count

        safety_state = self._get_retry_safety_state()
        safety_detail = self._format_retry_safety_state(safety_state)
        logger.info(f"[U115RiskControl] retry safety summary: {safety_detail}")
        self._record_event(
            event_type=EVENT_TYPE_RETRY_PROGRESS,
            source="U115RiskControl / failed transfer retry",
            endpoint="U115Pan.request_window",
            threshold=safety_detail,
            detail=f"补整理前安全余量检查：{safety_detail}",
            suggestion="如接近每小时软阈值，插件会延后补整理，避免冷却刚结束时再次集中请求。",
        )

        if total > 0 and not safety_state.get("allowed", True):
            retry_after = self._to_float(safety_state.get("retry_after"), 0.0, minimum=0.0, maximum=9999999999.0)
            delay_seconds = max(int(retry_after - time.time() - self._retry_failed_delay_seconds), 0)
            self._retry_reschedule_reason = "等待当前安全余量恢复后重试"
            self._retry_reschedule_delay_seconds = delay_seconds
            skipped_count += total
            skipped_details.extend(f"{self._format_transfer_history_summary(history)}: 安全余量不足，延后重试" for history in candidates)
            candidates = []
            total = 0
            self._last_retry_status = "等待安全余量"
            self._update_retry_progress(
                self._last_retry_status,
                "无",
                f"扫描 {len(histories)} 条，可重试 {retryable_count} 条；{safety_detail}。",
            )

        self._update_retry_progress(
            "已入队",
            "无",
            (
                f"扫描到失败历史 {len(histories)} 条，入队 {total} 条，跳过 {skipped_count} 条；"
                f"冷却中 {cooldown_count} 条，可重试 {retryable_count} 条。"
            ),
        )

        for index, history in enumerate(candidates, 1):
            history_id = str(getattr(history, "id", ""))
            history_summary = self._format_transfer_history_summary(history)
            retry_record = retry_records.get(history_id) if isinstance(retry_records, dict) else None
            if not isinstance(retry_record, dict):
                retry_record = {}
            retry_record = self._normalize_retry_record(retry_record, time.time())
            attempt_timestamps = self._get_recent_attempt_timestamps(retry_record, time.time())
            attempt_number = len(attempt_timestamps) + 1
            total_attempts = self._to_int(retry_record.get("total_attempts"), 0, minimum=0, maximum=100000) + 1
            progress = f"同步 MP 整理 {index}/{total}"
            self._update_retry_progress(
                progress,
                history_summary,
                (
                    f"24 小时内第 {attempt_number}/{RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW} 次补整理，"
                    "优先调用 TransferChain.redo_transfer_history，必要时兼容回退 manual_transfer。"
                ),
            )
            self._record_event(
                event_type=EVENT_TYPE_RETRY_PROGRESS,
                source="U115RiskControl / failed transfer retry",
                endpoint="TransferChain.redo_transfer_history",
                threshold=(
                    f"progress={index}/{total}, "
                    f"window_attempt={attempt_number}/{RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW}"
                ),
                detail=f"准备同步执行 MP 重新整理：{history_summary}。",
                suggestion="插件会优先复用 MP 原生历史重试；若源文件不存在，需要恢复源文件或重新下载。",
            )
            logger.info(
                "[U115RiskControl] retry transfer history sync started: "
                f"{history_summary}, progress={index}/{total}, "
                f"window_attempt={attempt_number}, safety={safety_detail}"
            )
            attempt_ts = time.time()
            try:
                state, message = self._retry_one_transfer_history(
                    history=history,
                    TransferChain=TransferChain,
                    FileItem=FileItem,
                    MediaType=MediaType,
                    EpisodeFormat=EpisodeFormat,
                )
            except Exception as exc:
                state = False
                message = str(exc)
                logger.exception(f"[U115RiskControl] retry transfer history failed: id={history_id}")
            if state:
                verified_state, verify_message = self._verify_transfer_history_result(
                    history=history,
                    history_id=history_id,
                    TransferHistoryOper=TransferHistoryOper,
                )
                if not verified_state:
                    state = False
                    message = verify_message or "同步整理返回成功，但原失败历史仍未确认变为成功"

            manual_required = self._should_mark_manual_required(
                message=message,
                previous_record=retry_record,
                total_attempts=total_attempts,
            )
            retry_records[history_id] = self._build_retry_record(
                history=history,
                previous=retry_record,
                attempt_ts=attempt_ts,
                state=bool(state),
                message=message,
                manual_required=manual_required,
            )
            if state:
                success_count += 1
                progress_detail = f"MP 同步整理成功：{self._short_text(message) or '无返回消息'}"
                self._update_retry_progress(f"整理成功 {index}/{total}", history_summary, progress_detail)
                self._record_event(
                    event_type=EVENT_TYPE_RETRY_PROGRESS,
                    source="U115RiskControl / failed transfer retry",
                    endpoint="TransferChain.redo_transfer_history",
                    threshold=f"progress={index}/{total}, synced=True",
                    detail=f"MP 同步整理成功：{history_summary}。返回：{self._short_text(message) or '无返回消息'}",
                    suggestion="插件已按同步返回和历史状态复查记录成功。",
                )
                logger.info(
                    "[U115RiskControl] retry transfer history sync succeeded: "
                    f"{history_summary}, message={self._short_text(message)}"
                )
            else:
                failed_count += 1
                failure_text = self._short_text(message)
                failure_details.append(f"{history_summary}: {failure_text}")
                if manual_required:
                    manual_required_count += 1
                    manual_required_details.append(f"{history_summary}: {failure_text}")
                if self._is_missing_source_message(message):
                    source_missing_details.append(f"{history_summary}: {failure_text}")
                self._update_retry_progress(f"整理失败 {index}/{total}", history_summary, failure_text)
                logger.warning(
                    "[U115RiskControl] retry transfer history sync failed: "
                    f"{history_summary}, message={failure_text}"
                )

        retry_state["version"] = RETRY_DATA_VERSION
        retry_state["retried_ids"] = []
        self._last_retry_total = total
        self._last_retry_success = success_count
        self._last_retry_failed = failed_count
        self._last_retry_skipped = skipped_count
        self._last_retry_failed_history_count = len(histories)
        self._last_retry_cooldown_count = cooldown_count
        self._last_retry_retryable_count = retryable_count
        self._last_retry_manual_required_count = manual_required_count

        if earliest_next_retry_after > time.time():
            delay_seconds = max(int(earliest_next_retry_after - time.time() - self._retry_failed_delay_seconds), 0)
            self._retry_reschedule_reason = "24 小时重试冷却结束"
            self._retry_reschedule_delay_seconds = delay_seconds

        if self._last_retry_status == "等待安全余量":
            pass
        elif cooldown_count and not total and retryable_count == 0:
            self._last_retry_status = "等待冷却后重试"
        elif total == 0:
            self._last_retry_status = "无可重试任务"
        elif failed_count:
            self._last_retry_status = "部分整理失败"
        else:
            self._last_retry_status = "整理完成"
        self._update_retry_progress(
            self._last_retry_status,
            "无",
            (
                f"扫描 {len(histories)} 条，整理成功 {success_count} 条，整理失败 {failed_count} 条，"
                f"跳过 {skipped_count} 条；冷却中 {cooldown_count} 条，可重试 {retryable_count} 条，"
                f"已处理 {already_handled_count} 条，需人工 {manual_required_count} 条。"
            ),
        )
        retry_state["last_run"] = {
            "time": self._last_retry_time,
            "reason": reason,
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "failed_history_count": len(histories),
            "cooldown_count": cooldown_count,
            "retryable_count": retryable_count,
            "manual_required_count": manual_required_count,
            "safety": safety_detail,
            "next_retry_after": earliest_next_retry_after,
            "candidates": candidate_details[:20],
            "skipped_details": skipped_details[:20],
            "cooldown_details": cooldown_details[:20],
            "handled_details": handled_details[:20],
            "progress": self._last_retry_progress,
            "current_task": self._last_retry_current_task,
            "progress_detail": self._last_retry_progress_detail,
        }
        self._save_retry_state(retry_state)

        scan_detail = (
            f"本次扫描到状态失败历史 {len(histories)} 条；本次候选 {total} 条，"
            f"整理成功 {success_count} 条，整理失败 {failed_count} 条，跳过 {skipped_count} 条；"
            f"24 小时冷却中 {cooldown_count} 条，可重试 {retryable_count} 条，"
            f"已处理 {already_handled_count} 条，需人工 {manual_required_count} 条。"
        )
        candidate_text = self._join_limited_details(candidate_details, "候选任务")
        skipped_text = self._join_limited_details(skipped_details, "跳过任务")
        cooldown_text = self._join_limited_details(cooldown_details, "冷却任务")
        handled_text = self._join_limited_details(handled_details, "已处理任务")
        detail_parts = [scan_detail, safety_detail, candidate_text, skipped_text, cooldown_text, handled_text]
        if source_missing_details:
            detail_parts.append(f"源文件问题：{'；'.join(source_missing_details[:3])}")
        if manual_required_details:
            detail_parts.append(f"需人工处理：{'；'.join(manual_required_details[:3])}")
        if failure_details:
            detail_parts.append(f"失败摘要：{'；'.join(failure_details[:3])}")
        detail = " ".join(part for part in detail_parts if part)
        self._record_event(
            event_type=EVENT_TYPE_RETRY_FINISHED,
            source="U115RiskControl / failed transfer retry",
            endpoint="TransferHistory",
            threshold=(
                f"max_count={self._retry_failed_max_count}, "
                f"rolling_window={RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW}/{RETRY_HISTORY_WINDOW_SECONDS}s"
            ),
            detail=detail,
            suggestion="24 小时冷却跳过不会记为异常；源文件不存在或记录损坏时请恢复源文件、重新下载或重新定位后再整理。",
        )

    def _list_failed_transfer_histories(self, TransferHistoryOper, TransferHistory) -> List[Any]:
        transfer_history = TransferHistoryOper()
        for kwargs in (
            {"page": 1, "count": -1, "status": False},
            {"page": 1, "count": 200, "status": False},
        ):
            try:
                histories = TransferHistory.list_by_page(transfer_history._db, **kwargs)
                return list(histories or [])
            except TypeError:
                continue
        histories = TransferHistory.list_by_page(transfer_history._db, 1, 200, False)
        return list(histories or [])

    def _format_transfer_history_summary(self, history: Any) -> str:
        history_id = self._short_text(getattr(history, "id", "") or "无ID", 24)
        fingerprint = self._history_fingerprint(history)
        return f"#{history_id} fp:{fingerprint}"

    def _retry_one_transfer_history(self, *, history, TransferChain, FileItem, MediaType, EpisodeFormat) -> Tuple[bool, str]:
        history_id = getattr(history, "id", None)
        chain = TransferChain()
        if history_id and hasattr(chain, "redo_transfer_history"):
            try:
                state, message = chain.redo_transfer_history(history_id)
                return bool(state), self._short_text(message or "已调用 MoviePilot 原生历史重试")
            except Exception as exc:
                logger.warning(
                    "[U115RiskControl] native redo_transfer_history failed, fallback manual_transfer: "
                    f"id={history_id}, error={self._short_text(exc)}"
                )

        src_payload = getattr(history, "src_fileitem", None)
        if not src_payload:
            return False, "历史记录缺少源文件项"

        fileitem = FileItem(**src_payload)
        type_name = str(getattr(history, "type", "") or "").strip()
        media_type = None
        if type_name:
            try:
                media_type = MediaType(type_name)
            except Exception:
                media_type = None

        season = self._parse_season(getattr(history, "seasons", None))
        episode_format = self._build_episode_format(history=history, EpisodeFormat=EpisodeFormat)
        target_path = getattr(history, "dest", None)
        target_path_obj = None
        if target_path:
            try:
                from pathlib import Path
                target_path_obj = Path(target_path).parent
            except Exception:
                target_path_obj = None

        kwargs = {
            "fileitem": fileitem,
            "target_storage": getattr(history, "dest_storage", None),
            "target_path": target_path_obj,
            "tmdbid": getattr(history, "tmdbid", None),
            "doubanid": getattr(history, "doubanid", None),
            "mtype": media_type,
            "season": season,
            "episode_group": getattr(history, "episode_group", None),
            "transfer_type": getattr(history, "mode", None),
            "epformat": episode_format,
            "force": True,
            "background": False,
            "downloader": getattr(history, "downloader", None),
            "download_hash": getattr(history, "download_hash", None),
        }
        signature = inspect.signature(chain.manual_transfer)
        kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        state, message = chain.manual_transfer(**kwargs)
        return bool(state), self._short_text(message)

    def _verify_transfer_history_result(self, *, history: Any, history_id: str, TransferHistoryOper) -> Tuple[bool, str]:
        transfer_oper = TransferHistoryOper()
        try:
            current = transfer_oper.get(int(history_id) if str(history_id).isdigit() else history_id)
        except Exception as exc:
            return False, f"整理后复查历史失败：{exc}"
        if not current:
            return True, "原失败历史已不存在，视为已被 MP 处理"
        if bool(getattr(current, "status", False)):
            return True, "原失败历史状态已变为成功"
        existing_success, existing_message = self._verify_existing_success_history(
            history=history,
            TransferHistoryOper=TransferHistoryOper,
        )
        if existing_success:
            return True, existing_message
        if self._target_file_exists(history):
            return True, "目标媒体库文件已存在，视为已处理"
        if self._source_file_missing(history):
            return False, "源文件不存在，需要人工恢复源文件或重新下载"
        if self._is_damaged_history(history):
            return False, "整理历史记录损坏或缺少源文件信息，需要人工处理"
        return False, "同步整理返回成功，但原失败历史仍为失败状态"

    def _verify_existing_success_history(self, *, history: Any, TransferHistoryOper) -> Tuple[bool, str]:
        transfer_oper = TransferHistoryOper()
        try:
            src = getattr(history, "src", None)
            src_storage = getattr(history, "src_storage", None)
            if src and hasattr(transfer_oper, "get_by_src"):
                by_src = transfer_oper.get_by_src(src, src_storage)
                if by_src and bool(getattr(by_src, "status", False)):
                    return True, f"已发现同源路径成功历史：#{getattr(by_src, 'id', '')}"
            dest = getattr(history, "dest", None)
            if dest and hasattr(transfer_oper, "get_by_dest"):
                by_dest = transfer_oper.get_by_dest(dest)
                if by_dest and bool(getattr(by_dest, "status", False)):
                    return True, f"已发现同目标路径成功历史：#{getattr(by_dest, 'id', '')}"

            tmdbid = getattr(history, "tmdbid", None)
            season = getattr(history, "seasons", None)
            episode = getattr(history, "episodes", None)
            if tmdbid and hasattr(transfer_oper, "get_by"):
                matches = transfer_oper.get_by(
                    mtype=getattr(history, "type", None),
                    tmdbid=tmdbid,
                    season=season,
                    episode=episode,
                )
                for matched in list(matches or []):
                    if bool(getattr(matched, "status", False)):
                        return True, f"已发现同 tmdbid/季/集成功历史：#{getattr(matched, 'id', '')}"

            download_hash = getattr(history, "download_hash", None)
            if download_hash and hasattr(transfer_oper, "list_by_hash"):
                for by_hash in list(transfer_oper.list_by_hash(download_hash) or []):
                    if not bool(getattr(by_hash, "status", False)):
                        continue
                    if self._is_same_media_episode(history, by_hash):
                        return True, f"已发现同 download_hash 且同季集成功历史：#{getattr(by_hash, 'id', '')}"
        except Exception as exc:
            return False, f"复查成功历史失败：{self._short_text(exc)}"
        return False, ""

    def _is_same_media_episode(self, left: Any, right: Any) -> bool:
        left_tmdbid = self._normalize_match_value(getattr(left, "tmdbid", None))
        right_tmdbid = self._normalize_match_value(getattr(right, "tmdbid", None))
        if not left_tmdbid or left_tmdbid != right_tmdbid:
            return False
        return (
            self._normalize_season_episode_value(getattr(left, "seasons", None))
            == self._normalize_season_episode_value(getattr(right, "seasons", None))
            and self._normalize_episode_set(getattr(left, "episodes", None))
            == self._normalize_episode_set(getattr(right, "episodes", None))
        )

    @staticmethod
    def _normalize_match_value(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize_season_episode_value(value: Any) -> str:
        text = str(value or "").strip().upper()
        return text.lstrip("S").lstrip("0") or ("0" if text else "")

    def _normalize_episode_set(self, value: Any) -> Tuple[str, ...]:
        text = str(value or "").strip().upper()
        if not text:
            return tuple()
        normalized = text.replace(" ", "")
        if "-" in normalized:
            try:
                start_text, end_text = normalized.split("-", 1)
                start = int(start_text.replace("E", "") or 0)
                end = int(end_text.replace("E", "") or 0)
                if start and end and start <= end:
                    return tuple(str(index) for index in range(start, end + 1))
            except Exception:
                pass
        parts = re.split(r"[,/;，、]+", normalized)
        episodes: List[str] = []
        for part in parts:
            number = part.replace("E", "").lstrip("0")
            if number:
                episodes.append(number)
        return tuple(episodes)

    @staticmethod
    def _is_missing_source_message(message: Any) -> bool:
        text = str(message or "")
        keywords = (
            "源目录不存在",
            "源文件不存在",
            "没有找到可整理的媒体文件",
            "缺少源文件项",
            "No such file",
            "not found",
            "does not exist",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _is_damaged_record_message(message: Any) -> bool:
        text = str(message or "")
        keywords = ("记录损坏", "历史记录损坏", "缺少源文件信息", "src_fileitem", "dest_fileitem", "缺少参数")
        return any(keyword in text for keyword in keywords)

    def _normalize_retry_record(self, record: Dict[str, Any], now_ts: float) -> Dict[str, Any]:
        normalized = dict(record or {})
        timestamps = self._get_recent_attempt_timestamps(normalized, now_ts)
        last_attempt_ts = self._to_float(
            normalized.get("last_attempt_ts"),
            0.0,
            minimum=0.0,
            maximum=9999999999.0,
        )
        if last_attempt_ts and last_attempt_ts not in timestamps and now_ts - last_attempt_ts < RETRY_HISTORY_WINDOW_SECONDS:
            timestamps.append(last_attempt_ts)
        timestamps = sorted(set(float(ts) for ts in timestamps if ts > 0))
        normalized["attempt_timestamps"] = timestamps
        normalized["last_attempt_ts"] = max(timestamps) if timestamps else last_attempt_ts
        if len(timestamps) >= RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW:
            normalized["next_retry_after"] = min(timestamps) + RETRY_HISTORY_WINDOW_SECONDS
        else:
            normalized["next_retry_after"] = 0.0
        normalized.setdefault("success", False)
        normalized.setdefault("message", "")
        normalized.setdefault("manual_required", False)
        normalized["total_attempts"] = self._to_int(
            normalized.get("total_attempts", normalized.get("attempts")),
            0,
            minimum=0,
            maximum=100000,
        )
        normalized.pop("attempts", None)
        return normalized

    def _get_recent_attempt_timestamps(self, record: Dict[str, Any], now_ts: float) -> List[float]:
        raw_timestamps = record.get("attempt_timestamps") if isinstance(record, dict) else []
        timestamps: List[float] = []
        if isinstance(raw_timestamps, list):
            for item in raw_timestamps:
                ts = self._to_float(item, 0.0, minimum=0.0, maximum=9999999999.0)
                if ts and now_ts - ts < RETRY_HISTORY_WINDOW_SECONDS:
                    timestamps.append(ts)
        return sorted(set(timestamps))

    def _build_retry_record(
        self,
        *,
        history: Any,
        previous: Dict[str, Any],
        attempt_ts: Optional[float],
        state: bool,
        message: Any,
        manual_required: bool,
    ) -> Dict[str, Any]:
        now_ts = time.time()
        previous = self._normalize_retry_record(previous or {}, now_ts)
        attempt_timestamps = self._get_recent_attempt_timestamps(previous, now_ts)
        if attempt_ts:
            attempt_timestamps.append(float(attempt_ts))
        attempt_timestamps = sorted(set(ts for ts in attempt_timestamps if now_ts - ts < RETRY_HISTORY_WINDOW_SECONDS))
        last_attempt_ts = max(attempt_timestamps) if attempt_timestamps else self._to_float(
            previous.get("last_attempt_ts"),
            0.0,
            minimum=0.0,
            maximum=9999999999.0,
        )
        total_attempts = self._to_int(previous.get("total_attempts"), 0, minimum=0, maximum=100000)
        if attempt_ts:
            total_attempts += 1
        next_retry_after = 0.0
        if not state and len(attempt_timestamps) >= RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW:
            next_retry_after = min(attempt_timestamps) + RETRY_HISTORY_WINDOW_SECONDS
        return {
            "attempt_timestamps": attempt_timestamps,
            "last_attempt_ts": last_attempt_ts,
            "next_retry_after": next_retry_after,
            "success": bool(state),
            "message": self._short_text(message, 200),
            "manual_required": bool(manual_required),
            "consecutive_failures": 0 if state else self._to_int(
                previous.get("consecutive_failures"),
                1,
                minimum=0,
                maximum=100000,
            ),
            "total_attempts": total_attempts,
            "history_id": str(getattr(history, "id", "") or ""),
            "fingerprint": self._history_fingerprint(history),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _should_mark_manual_required(
        self,
        *,
        message: Any,
        previous_record: Dict[str, Any],
        total_attempts: int,
    ) -> bool:
        if self._is_missing_source_message(message) or self._is_damaged_record_message(message):
            return True
        previous = previous_record if isinstance(previous_record, dict) else {}
        previous_message = str(previous.get("message") or "")
        consecutive_failures = self._to_int(previous.get("consecutive_failures"), 0, minimum=0, maximum=100000)
        if previous_message and self._short_text(previous_message) == self._short_text(message):
            consecutive_failures += 1
        else:
            consecutive_failures = 1
        previous_record["consecutive_failures"] = consecutive_failures
        return total_attempts >= RETRY_MANUAL_REQUIRED_FAILURES and consecutive_failures >= RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW

    def _history_fingerprint(self, history: Any) -> str:
        parts = [
            str(getattr(history, "id", "") or ""),
            str(getattr(history, "src", "") or ""),
            str(getattr(history, "dest", "") or ""),
            str(getattr(history, "download_hash", "") or ""),
            str(getattr(history, "tmdbid", "") or ""),
            str(getattr(history, "seasons", "") or ""),
            str(getattr(history, "episodes", "") or ""),
        ]
        digest = hashlib.sha256("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()
        return digest[:10]

    def _target_file_exists(self, history: Any) -> bool:
        return self._fileitem_or_path_exists(
            payload=getattr(history, "dest_fileitem", None),
            path=getattr(history, "dest", None),
            storage_name=getattr(history, "dest_storage", None),
        )

    def _source_file_missing(self, history: Any) -> bool:
        if self._is_damaged_history(history):
            return True
        exists = self._fileitem_or_path_exists(
            payload=getattr(history, "src_fileitem", None),
            path=getattr(history, "src", None),
            storage_name=getattr(history, "src_storage", None),
        )
        return exists is False

    @staticmethod
    def _is_damaged_history(history: Any) -> bool:
        return not bool(getattr(history, "src_fileitem", None) or getattr(history, "src", None))

    def _fileitem_or_path_exists(self, *, payload: Any, path: Any, storage_name: Any = "") -> Optional[bool]:
        candidates: List[Any] = []
        if payload:
            candidates.append(payload)
        if path:
            candidates.append(path)
        if not candidates:
            return None
        for candidate in candidates:
            try:
                if self._storage_item_exists(candidate):
                    return True
            except Exception:
                continue
            try:
                from pathlib import Path
                text_path = None
                candidate_storage_name = str(storage_name or "")
                if isinstance(candidate, dict):
                    text_path = candidate.get("path") or candidate.get("file_path")
                    candidate_storage_name = str(
                        candidate.get("storage") or candidate.get("storage_type") or candidate_storage_name
                    )
                else:
                    text_path = str(candidate)
                if text_path and self._looks_local_path(text_path, candidate_storage_name):
                    return bool(Path(text_path).exists())
            except Exception:
                continue
        return None

    @staticmethod
    def _storage_item_exists(candidate: Any) -> bool:
        for method_name in ("exists", "is_file", "is_dir"):
            method = getattr(candidate, method_name, None)
            if callable(method):
                try:
                    if bool(method()):
                        return True
                except TypeError:
                    continue
        return False

    @staticmethod
    def _looks_local_path(path: Any, storage_name: str = "") -> bool:
        text = str(path or "").strip()
        storage = str(storage_name or "").lower()
        if not text or "115" in storage or "u115" in storage:
            return False
        if re.match(r"^[A-Za-z]:[\\/]", text):
            return True
        if text.startswith("\\\\"):
            return True
        if text.startswith("/") and storage in {"local", "localhost", "system"}:
            return True
        return False

    def _get_retry_safety_state(self) -> Dict[str, Any]:
        now = time.time()
        limit = int(self._hourly_soft_limit or 0)
        if not limit:
            return {"allowed": True, "limit": 0, "used": 0, "remaining": 999999, "retry_after": now}

        timestamps = self._collect_recent_u115_timestamps(now)
        used = len(timestamps)
        remaining = max(limit - used, 0)
        min_required_margin = max(int(self._retry_failed_max_count or 1), 1)
        near_limit = remaining <= min_required_margin
        retry_after = now
        if timestamps and near_limit:
            retry_after = min(timestamps) + 3600
        return {
            "allowed": not near_limit,
            "limit": limit,
            "used": used,
            "remaining": remaining,
            "retry_after": retry_after,
        }

    def _collect_recent_u115_timestamps(self, now: float) -> List[float]:
        timestamps: List[float] = []
        try:
            from app.modules.filemanager.storages.u115 import U115Pan
            for obj in gc.get_objects():
                try:
                    if isinstance(obj, U115Pan):
                        obj_timestamps = getattr(obj, "_u115riskcontrol_hour_timestamps", None)
                        if obj_timestamps:
                            timestamps.extend(
                                float(ts)
                                for ts in list(obj_timestamps)
                                if ts and now - float(ts) < 3600
                            )
                except Exception:
                    continue
        except Exception:
            return []
        return sorted(set(timestamps))

    def _format_retry_safety_state(self, state: Dict[str, Any]) -> str:
        limit = int(state.get("limit") or 0)
        if not limit:
            return "安全余量：未启用小时软阈值"
        used = int(state.get("used") or 0)
        remaining = int(state.get("remaining") or 0)
        if state.get("allowed", True):
            return f"安全余量：最近 1 小时 {used}/{limit}，剩余 {remaining}"
        retry_after = self._to_float(state.get("retry_after"), 0.0, minimum=0.0, maximum=9999999999.0)
        wait_seconds = max(int(retry_after - time.time()), 0)
        return f"安全余量不足：最近 1 小时 {used}/{limit}，剩余 {remaining}，约 {wait_seconds} 秒后再试"

    def _build_episode_format(self, *, history, EpisodeFormat):
        episodes = getattr(history, "episodes", None)
        if not episodes:
            return None
        episode_detail = str(episodes).replace("E", "")
        if "-" in str(episodes):
            try:
                episode_start, episode_end = str(episodes).split("-", 1)
                episode_detail = ",".join(
                    str(index)
                    for index in range(int(episode_start.replace("E", "")), int(episode_end.replace("E", "")) + 1)
                )
            except Exception:
                episode_detail = str(episodes)
        try:
            return EpisodeFormat(detail=episode_detail)
        except Exception:
            return None

    @staticmethod
    def _parse_season(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(str(value).replace("S", ""))
        except ValueError:
            return None

    def _restore_retry_state(self) -> None:
        retry_state = self._load_retry_state()
        last_run = retry_state.get("last_run") if isinstance(retry_state, dict) else None
        if not isinstance(last_run, dict):
            return
        self._last_retry_time = str(last_run.get("time") or "无")
        self._last_retry_total = self._to_int(last_run.get("total"), 0, minimum=0, maximum=100000)
        self._last_retry_success = self._to_int(last_run.get("success"), 0, minimum=0, maximum=100000)
        self._last_retry_failed = self._to_int(last_run.get("failed"), 0, minimum=0, maximum=100000)
        self._last_retry_skipped = self._to_int(last_run.get("skipped"), 0, minimum=0, maximum=100000)
        self._last_retry_failed_history_count = self._to_int(
            last_run.get("failed_history_count"),
            0,
            minimum=0,
            maximum=100000,
        )
        self._last_retry_cooldown_count = self._to_int(
            last_run.get("cooldown_count"),
            0,
            minimum=0,
            maximum=100000,
        )
        self._last_retry_retryable_count = self._to_int(
            last_run.get("retryable_count"),
            0,
            minimum=0,
            maximum=100000,
        )
        self._last_retry_manual_required_count = self._to_int(
            last_run.get("manual_required_count"),
            0,
            minimum=0,
            maximum=100000,
        )
        self._last_retry_progress = str(last_run.get("progress") or "已恢复上次记录")
        self._last_retry_current_task = str(last_run.get("current_task") or "无")
        self._last_retry_progress_detail = str(last_run.get("progress_detail") or "无")
        self._last_retry_status = "已恢复上次记录"

    def _load_retry_state(self) -> Dict[str, Any]:
        try:
            data = self.get_data(RETRY_DATA_KEY) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", RETRY_DATA_VERSION)
        data.setdefault("retried_ids", [])
        data.setdefault("records", {})
        return data

    def _save_retry_state(self, data: Dict[str, Any]) -> None:
        try:
            self.save_data(RETRY_DATA_KEY, data)
        except Exception as exc:
            logger.warning(f"[U115RiskControl] save retry state failed: {exc}")

    def _update_retry_progress(self, progress: str, current_task: str, detail: str) -> None:
        self._last_retry_progress = self._short_text(progress, 80) or "无"
        self._last_retry_current_task = self._short_text(current_task, 120) or "无"
        self._last_retry_progress_detail = self._short_text(detail, 200) or "无"

    @staticmethod
    def _short_text(value: Any, limit: int = 160) -> str:
        text = str(value or "")
        text = " ".join(text.split())
        if len(text) > limit:
            return f"{text[:limit]}..."
        return text

    @staticmethod
    def _basename(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.replace("\\", "/").rstrip("/").split("/")[-1]

    def _join_limited_details(self, items: List[str], label: str, limit: int = 5) -> str:
        if not items:
            return ""
        shown = "；".join(self._short_text(item, 100) for item in items[:limit])
        remaining = len(items) - limit
        if remaining > 0:
            shown = f"{shown}；另 {remaining} 条"
        return f"{label}：{shown}。"

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

    def _build_switch_col(self, model: str, label: str, sm: int = 4) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": sm},
            "content": [
                {
                    "component": "VSwitch",
                    "props": {
                        "model": model,
                        "label": label,
                        "hide-details": True,
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
        sm: int = 4,
        suffix: Optional[str] = None,
    ) -> Dict[str, Any]:
        props = {
            "model": model,
            "label": label,
            "type": "number",
            "min": minimum,
            "max": maximum,
            "hint": hint,
            "persistent-hint": True,
        }
        if suffix:
            props["suffix"] = suffix
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": sm},
            "content": [
                {
                    "component": "VTextField",
                    "props": props,
                }
            ],
        }

    def _build_section_title(self, title: str) -> Dict[str, Any]:
        return {
            "component": "VRow",
            "content": [
                {
                    "component": "VCol",
                    "props": {"cols": 12},
                    "content": [
                        {
                            "component": "VAlert",
                            "props": {
                                "type": "info",
                                "variant": "tonal",
                                "density": "compact",
                                "title": title,
                            },
                        }
                    ],
                }
            ],
        }

    def _build_note_col(self, text: str, sm: int = 4) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": sm, "class": "d-flex align-center"},
            "content": [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "text": text,
                    },
                }
            ],
        }

    def _build_inline_alert(self, alert_type: str, text: str) -> Dict[str, Any]:
        return {
            "component": "VRow",
            "content": [
                {
                    "component": "VCol",
                    "props": {"cols": 12},
                    "content": [
                        {
                            "component": "VAlert",
                            "props": {
                                "type": alert_type,
                                "variant": "tonal",
                                "density": "compact",
                                "text": text,
                            },
                        }
                    ],
                }
            ],
        }

    def _build_status_col(self, title: str, alert_type: str, text: str) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": 4},
            "content": [
                {
                    "component": "VAlert",
                    "props": {
                        "type": alert_type,
                        "variant": "tonal",
                        "density": "compact",
                        "title": title,
                        "text": text,
                    },
                }
            ],
        }

    def _retry_status_alert_type(self) -> str:
        if self._last_retry_status in {"部分整理失败"}:
            return "warning"
        if self._last_retry_status in {"等待冷却后重试", "等待安全余量"}:
            return "info"
        if "异常" in str(self._last_retry_status) or self._last_retry_status == "MP 接口不可用":
            return "error"
        return "info"

    def _format_event_preview(self, logs: List[Dict[str, Any]]) -> str:
        if not logs:
            return "暂无事件。"
        rows = []
        for event in reversed(logs[-10:]):
            rows.append(
                " | ".join(
                    [
                        str(event.get("time") or "-"),
                        str(event.get("source") or "-"),
                        str(event.get("event_type") or "-"),
                        str(event.get("endpoint") or "-"),
                        str(event.get("threshold") or "-"),
                        str(event.get("detail") or "-"),
                    ]
                )
            )
        return "\n".join(rows)

    def _build_live_status(self) -> Dict[str, Any]:
        now = time.time()
        snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cooldown_remaining = self._get_current_cooldown_remaining()
        retry_remaining = 0
        scheduled_time = "无"
        if self._retry_scheduled_until > now:
            retry_remaining = max(int(self._retry_scheduled_until - now), 0)
            scheduled_time = datetime.fromtimestamp(self._retry_scheduled_until).strftime("%Y-%m-%d %H:%M:%S")

        if self._retry_in_progress:
            scheduled_text = "正在执行"
        elif retry_remaining > 0:
            scheduled_text = f"{scheduled_time}，约 {retry_remaining} 秒后"
        else:
            scheduled_text = "无"

        overall_status = self._build_overall_status(scheduled_text=scheduled_text)
        logs = self._event_logs[-self._max_event_log_count :]
        return {
            "snapshot_time": snapshot_time,
            "enabled": self._enabled,
            "overall": overall_status,
            "cooldown": {
                "reason": self._current_cooldown_reason,
                "remaining_seconds": cooldown_remaining,
                "until": self._current_cooldown_until,
                "soft_limit_hits": self._soft_limit_hits,
                "hard_limit_hits": self._hard_limit_hits,
            },
            "params": {
                "api_qps": self._api_qps,
                "download_qps": self._download_qps,
                "limit_sleep_seconds": self._limit_sleep_seconds,
                "hourly_soft_limit": self._hourly_soft_limit,
                "hourly_soft_cooldown": self._hourly_soft_cooldown,
            },
            "retry": {
                "status": self._last_retry_status,
                "time": self._last_retry_time,
                "total": self._last_retry_total,
                "success": self._last_retry_success,
                "failed": self._last_retry_failed,
                "skipped": self._last_retry_skipped,
                "failed_history_count": self._last_retry_failed_history_count,
                "cooldown_count": self._last_retry_cooldown_count,
                "retryable_count": self._last_retry_retryable_count,
                "manual_required_count": self._last_retry_manual_required_count,
                "progress": self._last_retry_progress,
                "current_task": self._last_retry_current_task,
                "progress_detail": self._last_retry_progress_detail,
                "scheduled_time": scheduled_time,
                "scheduled_text": scheduled_text,
                "scheduled_reason": self._retry_scheduled_reason,
                "scheduled_remaining_seconds": retry_remaining,
                "in_progress": self._retry_in_progress,
            },
            "events": list(reversed(logs[-10:])),
            "event_preview": self._format_event_preview(logs),
        }

    def _format_event_line(self, event: Dict[str, Any]) -> str:
        return (
            f"[{event.get('time')}] {event.get('source')}\n"
            f"事件类型：{event.get('event_type')}\n"
            f"接口：{event.get('endpoint')}\n"
            f"命中阈值：{event.get('threshold')}\n"
            f"详情：{event.get('detail')}\n"
            f"建议：{event.get('suggestion')}"
        )

    def _build_overall_status(self, *, scheduled_text: str) -> Dict[str, str]:
        now = time.time()
        cooldown_remaining = self._get_current_cooldown_remaining()

        if not self._enabled:
            return {
                "type": "warning",
                "title": "当前状态：已禁用",
                "text": "插件未启用，不会修改 u115 限流参数，也不会调度失败整理重试。",
            }
        if self._last_error or self._last_status == "补丁失败":
            reason = self._last_error or self._last_status
            return {
                "type": "error",
                "title": "当前状态：异常",
                "text": f"异常原因：{reason}\n失败整理重试状态：{self._last_retry_status}\n进度详情：{self._last_retry_progress_detail}",
            }
        if cooldown_remaining > 0 and self._current_cooldown_reason != "未冷却":
            return {
                "type": "warning",
                "title": "当前状态：风控中",
                "text": (
                    f"风控类型：{self._current_cooldown_reason}\n"
                    f"剩余时间：{cooldown_remaining} 秒\n"
                    f"失败整理重试：{scheduled_text}"
                ),
            }
        if self._retry_in_progress:
            return {
                "type": "info",
                "title": "当前状态：整理执行中",
                "text": (
                    f"当前进度：{self._last_retry_progress}\n"
                    f"当前任务：{self._last_retry_current_task}\n"
                    f"进度详情：{self._last_retry_progress_detail}"
                ),
            }
        if self._retry_scheduled_until > now:
            remaining = int(self._retry_scheduled_until - now)
            return {
                "type": "info",
                "title": "当前状态：等待失败任务扫描",
                "text": (
                    f"已计划重试时间：{scheduled_text}\n"
                    f"剩余等待：{max(remaining, 0)} 秒\n"
                    f"计划原因：{self._retry_scheduled_reason}"
                ),
            }
        if self._last_retry_status == "等待冷却后重试":
            return {
                "type": "info",
                "title": "当前状态：等待冷却后重试",
                "text": (
                    f"24 小时重试冷却中：{self._last_retry_cooldown_count} 条\n"
                    f"可重试：{self._last_retry_retryable_count} 条\n"
                    f"进度详情：{self._last_retry_progress_detail}"
                ),
            }
        if self._last_retry_status == "等待安全余量":
            return {
                "type": "info",
                "title": "当前状态：等待安全余量",
                "text": (
                    f"当前请求安全余量不足，已延后补整理。\n"
                    f"失败历史：{self._last_retry_failed_history_count} 条；可重试：{self._last_retry_retryable_count} 条\n"
                    f"进度详情：{self._last_retry_progress_detail}"
                ),
            }
        if self._last_retry_status == "部分整理失败":
            return {
                "type": "warning",
                "title": "当前状态：有失败整理待处理",
                "text": (
                    f"最近补整理仍有失败项，但插件补丁状态正常。\n"
                    f"失败历史：{self._last_retry_failed_history_count} 条；冷却中：{self._last_retry_cooldown_count} 条；"
                    f"可重试：{self._last_retry_retryable_count} 条；需人工：{self._last_retry_manual_required_count} 条\n"
                    f"进度详情：{self._last_retry_progress_detail}"
                ),
            }
        return {
            "type": "success",
            "title": "当前状态：正常",
            "text": (
                f"补丁状态：{self._last_status}\n"
                f"当前实例数：{self._patched_instances}\n"
                f"失败整理重试：{self._last_retry_status}；最近处理总数 {self._last_retry_total}"
            ),
        }

    def _get_current_cooldown_remaining(self) -> int:
        now = time.time()
        if self._current_cooldown_until > now:
            return max(int(self._current_cooldown_until - now), 0)
        if self._current_cooldown_reason != "未冷却" and self._current_cooldown_remaining > 0:
            return max(int(self._current_cooldown_remaining), 0)
        return 0

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
            "retry_failed_after_cooldown": self._to_bool(
                merged.get("retry_failed_after_cooldown"),
                DEFAULT_CONFIG["retry_failed_after_cooldown"],
            ),
            "retry_failed_on_startup": self._to_bool(
                merged.get("retry_failed_on_startup"),
                DEFAULT_CONFIG["retry_failed_on_startup"],
            ),
            "retry_failed_delay_seconds": self._to_int(
                merged.get("retry_failed_delay_seconds"),
                DEFAULT_CONFIG["retry_failed_delay_seconds"],
                minimum=0,
                maximum=86400,
            ),
            "retry_failed_max_count": self._to_int(
                merged.get("retry_failed_max_count"),
                DEFAULT_CONFIG["retry_failed_max_count"],
                minimum=0,
                maximum=100,
            ),
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

    @staticmethod
    def _to_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))
