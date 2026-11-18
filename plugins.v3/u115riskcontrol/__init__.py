import gc
import hashlib
import inspect
import math
import random
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from apscheduler.triggers.interval import IntervalTrigger

from app.log import logger
from app.plugins import _PluginBase

from .retry_scheduler import (
    NATIVE_COOLDOWN_PROBE_GAP_SECONDS,
    NATIVE_COOLDOWN_STREAK_MAX,
    RETRY_DATA_VERSION,
    RETRY_HISTORY_MAX_ATTEMPTS_PER_WINDOW,
    RETRY_HISTORY_WINDOW_SECONDS,
    RETRY_RESULT_FAILED,
    RETRY_RESULT_HANDLED,
    RETRY_RESULT_MANUAL,
    RETRY_RESULT_PENDING,
    RETRY_RESULT_RUNNING,
    RETRY_RESULT_SUCCEEDED,
    RETRY_SCAN_INTERVAL_SECONDS,
    calculate_next_retry_at,
    calculate_manual_retry_at,
    classify_retry_error,
    escalated_cooldown_seconds,
    extract_history_error,
    history_failed_at,
    jittered_wait_seconds,
    merge_records,
    normalize_episodes,
    normalize_record,
    normalize_season,
    normalize_text,
    recent_attempts,
    reserve_attempt,
    retry_group_key,
    sanitize_message,
    should_start_cooldown_probe,
    short_group_key,
    to_timestamp,
)


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
RETRY_MANUAL_REQUIRED_FAILURES = 9
RETRY_CONFIRM_TIMEOUT_SECONDS = 30
RETRY_CONFIRM_POLL_SECONDS = 5
RETRY_SERVICE_ID = "U115RiskControlRetryScan"
NATIVE_COOLDOWN_DATA_KEY = "native_cooldown"
NATIVE_COOLDOWN_MAX_WAIT_SECONDS = 600.0
NATIVE_COOLDOWN_PROBE_POLL_SECONDS = 2.0
NATIVE_COOLDOWN_PERSIST_INTERVAL_SECONDS = 5.0

MP_DEFAULTS = {
    "api_qps": 3,
    "download_qps": 1,
    "limit_sleep_seconds": 3600,
}

EVENT_TYPE_PATCH_ACTIVE = "patch_active"
EVENT_TYPE_SOFT_LIMIT = "soft_limit_triggered"
EVENT_TYPE_HARD_LIMIT = "115_limit_triggered"
EVENT_TYPE_COOLDOWN_RECOVERED = "cooldown_recovered"
EVENT_TYPE_RETRY_SCHEDULED = "failed_transfer_retry_scheduled"
EVENT_TYPE_RETRY_STARTED = "failed_transfer_retry_started"
EVENT_TYPE_RETRY_PROGRESS = "failed_transfer_retry_progress"
EVENT_TYPE_RETRY_FINISHED = "failed_transfer_retry_finished"
EVENT_TYPE_RETRY_SKIPPED = "failed_transfer_retry_skipped"


class U115RiskControl(_PluginBase):
    plugin_name = "u115风控参数"
    plugin_desc = "为 MoviePilot 的 u115 存储提供低风控参数、风控日志和失败整理冷却后重试。"
    plugin_icon = "U115RiskControl.jpg"
    plugin_version = "0.3.6"
    plugin_author = "wYw"
    author_url = ""
    plugin_config_prefix = "u115riskcontrol_"
    plugin_order = 98
    auth_level = 1

    _patch_lock = threading.Lock()
    _event_lock = threading.Lock()
    _scheduler_lock = threading.RLock()
    _global_retry_in_progress = False
    _global_retry_current_history_id = ""
    _global_retry_current_group_key = ""
    _patched = False
    # 以下状态挂在类上，跨 U115Pan 实例、跨插件重载共享，避免新实例绕过 115 冷却
    _native_gate = threading.Condition(threading.RLock())
    _native_cooldown_until = 0.0
    _native_guard_active = False
    _native_probe_in_flight = False
    _native_fail_streak = 0
    _native_last_probe_at = 0.0

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
        self._retry_current_history_id = ""
        self._retry_current_group_key = ""
        self._scheduler_started = False
        self._last_retry_scan_time = "无"
        self._next_retry_scan_time = "无"
        self._last_retry_scan_result = "未扫描"
        self._duplicate_schedule_skipped = 0
        self._pending_scan_not_before = 0.0
        self._pending_scan_reason = ""
        self._pending_scan_requested = False
        self._pending_target_history_id = ""
        self._pending_manual = False
        self._dispatch_pending = False
        self._state_lock = threading.RLock()
        self._stopped = True
        self._instance_generation = ""
        self._last_native_limit_until = 0.0
        self._native_cooldown_persist_at = 0.0
        self._event_logs: List[Dict[str, Any]] = []

    def init_plugin(self, config: dict = None):
        self._stopped = False
        self._instance_generation = uuid.uuid4().hex
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
            self._scheduler_started = False
            self._restore_patch()
            return

        self._restore_retry_state()
        self._restore_native_cooldown()
        self._apply_patch()
        self._schedule_startup_failed_transfer_retry()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if self._stopped or not self._enabled or not self._retry_failed_after_cooldown:
            self._scheduler_started = False
            return []
        self._scheduler_started = True
        if to_timestamp(self._next_retry_scan_time) <= time.time():
            self._next_retry_scan_time = self._format_history_time(time.time() + RETRY_SCAN_INTERVAL_SECONDS)
        return [
            {
                "id": RETRY_SERVICE_ID,
                "name": "U115RiskControl 失败整理补偿扫描",
                "trigger": IntervalTrigger(seconds=RETRY_SCAN_INTERVAL_SECONDS),
                "func": self._run_retry_scan,
                "kwargs": {"trigger_reason": "周期补偿扫描"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/U115RiskControl/status",
                "endpoint": self.get_live_status,
                "methods": ["GET"],
                "summary": "获取 U115RiskControl 实时状态",
                "description": "返回当前冷却、失败整理重试和事件日志快照，供前端轮询刷新使用。",
            },
            {
                "path": "/U115RiskControl/retry",
                "endpoint": self.retry_failed_task,
                "methods": ["GET", "POST"],
                "summary": "重试单条失败整理任务",
                "description": "校验当前风控状态后，将指定失败整理历史加入单条后台重试。",
            },
            {
                "path": "/U115RiskControl/page_refresh",
                "endpoint": self.page_refresh,
                "methods": ["GET"],
                "summary": "刷新 U115RiskControl 状态页",
                "description": "供状态页按钮调用，触发 MoviePilot 重新读取页面数据。",
            },
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

    def _get_legacy_page_impl(self) -> List[dict]:
        snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs = self._event_logs[-self._max_event_log_count :]
        event_text = self._format_event_preview(logs)
        pending_tasks, pending_error = self._get_pending_retry_tasks()
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
                            f"{self._format_cooldown_remaining(current_cooldown_remaining)}"
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
                    self._build_pending_retry_section(pending_tasks, pending_error),
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

    def _get_page_impl(self) -> List[dict]:
        return self._get_tabbed_page_impl()

    def _get_scheduler_snapshot(self) -> Dict[str, Any]:
        with self._scheduler_lock:
            current_history_id = self.__class__._global_retry_current_history_id
            current_group_key = self.__class__._global_retry_current_group_key
            running = self.__class__._global_retry_in_progress
            scheduled_until = self._pending_scan_not_before
        return {
            "enabled": bool(self._enabled and self._retry_failed_after_cooldown),
            "interval_seconds": RETRY_SCAN_INTERVAL_SECONDS,
            "running": bool(self._scheduler_started and not self._stopped),
            "executing": running,
            "last_scan_at": self._last_retry_scan_time,
            "next_scan_at": self._next_retry_scan_time,
            "scheduled_until": scheduled_until,
            "current_history_id": current_history_id or self._retry_current_history_id,
            "current_group_key": current_group_key or self._retry_current_group_key,
            "last_scan_result": self._last_retry_scan_result,
            "duplicate_schedule_skipped": self._duplicate_schedule_skipped,
        }

    def _get_tabbed_page_impl(self) -> List[dict]:
        snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        page_api_base = f"plugin/{self.__class__.__name__}"
        logs = self._event_logs[-self._max_event_log_count :]
        pending_tasks, pending_error = self._get_pending_retry_tasks()
        scheduler = self._get_scheduler_snapshot()
        scheduled_text = "无"
        if scheduler["executing"]:
            scheduled_text = "正在执行"
        elif scheduler["scheduled_until"] > time.time():
            remaining = max(math.ceil(scheduler["scheduled_until"] - time.time()), 0)
            scheduled_time = datetime.fromtimestamp(scheduler["scheduled_until"]).strftime("%Y-%m-%d %H:%M:%S")
            scheduled_text = f"{scheduled_time}（{self._format_remaining_seconds(remaining)}）"

        task_summary = self._summarize_pending_tasks(pending_tasks)
        overall_status = self._build_overall_status(scheduled_text=scheduled_text)
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
                                    "title": "u115风控参数",
                                    "text": f"{overall_status['title']} · 版本 {self.plugin_version}\n{overall_status['text']}",
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
                        "props": {"cols": 12, "class": "d-flex justify-end"},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "variant": "outlined",
                                    "color": "primary",
                                    "size": "small",
                                    "prependIcon": "mdi-refresh",
                                },
                                "text": "刷新状态",
                                "events": {
                                    "click": {
                                        "api": f"{page_api_base}/page_refresh",
                                        "method": "GET",
                                        "params": {},
                                    }
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "component": "VExpansionPanels",
                "props": {
                    "modelValue": 0,
                    "variant": "accordion",
                    "class": "mt-2",
                },
                "content": [
                    {
                        "component": "VExpansionPanel",
                        "props": {"title": "状态总览"},
                        "content": self._build_overview_tab(
                            scheduler, scheduled_text, snapshot_time, task_summary
                        ),
                    },
                    {
                        "component": "VExpansionPanel",
                        "props": {"title": "待重试任务"},
                        "content": [self._build_pending_retry_section(pending_tasks, pending_error)],
                    },
                    {
                        "component": "VExpansionPanel",
                        "props": {"title": "风控事件"},
                        "content": self._build_events_tab(logs),
                    },
                ],
            },
        ]

    def _build_overview_tab(
        self,
        scheduler: Dict[str, Any],
        scheduled_text: str,
        snapshot_time: str,
        task_summary: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        now = time.time()
        next_scan_timestamp = to_timestamp(scheduler["next_scan_at"])
        next_scan_remaining = max(math.ceil(next_scan_timestamp - now), 0) if next_scan_timestamp else 0
        scheduler_text = (
            f"调度器：{'运行中' if scheduler['running'] else '未运行'}\n"
            f"执行状态：{'正在处理' if scheduler['executing'] else '空闲'}\n"
            f"扫描间隔：{scheduler['interval_seconds']} 秒\n"
            f"上次扫描：{scheduler['last_scan_at']}\n"
            f"下次扫描：{scheduler['next_scan_at']}"
            f"（{self._format_remaining_seconds(next_scan_remaining)}）\n"
            f"当前任务：{scheduler['current_history_id'] or '无'} / 组 {short_group_key(scheduler['current_group_key']) if scheduler['current_group_key'] else '无'}\n"
            f"最近结果：{scheduler['last_scan_result']}\n"
            f"重复调度跳过：{scheduler['duplicate_schedule_skipped']} 次"
        )
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
                                    "type": "info",
                                    "variant": "tonal",
                                    "density": "compact",
                                    "title": "自动补偿调度",
                                    "text": scheduler_text,
                                },
                            }
                        ],
                    }
                ],
            },
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
                            f"{self._format_cooldown_remaining(self._get_current_cooldown_remaining())}"
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
                            f"成功 {self._last_retry_success} / 失败 {self._last_retry_failed} / 跳过 {self._last_retry_skipped}\n"
                            f"失败历史 {self._last_retry_failed_history_count} / 冷却中 {self._last_retry_cooldown_count}\n"
                            f"可重试 {self._last_retry_retryable_count} / 需人工 {self._last_retry_manual_required_count}\n"
                            f"当前任务总数 {task_summary['total']} / 自动重试任务 {task_summary['cooling'] + task_summary['retryable']}\n"
                            f"待人工确认 {task_summary['manual_required']} / 需人工处理 {task_summary['needs_attention']}\n"
                            f"计划状态 {scheduled_text}"
                        ),
                    ),
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
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "density": "compact",
                                    "title": "整理进度",
                                    "text": (
                                        f"当前进度：{self._last_retry_progress}\n"
                                        f"当前任务：{self._last_retry_current_task}\n"
                                        f"详情：{self._last_retry_progress_detail}\n"
                                        f"页面快照：{snapshot_time}"
                                    ),
                                },
                            }
                        ],
                    }
                ],
            },
        ]

    def _build_events_tab(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        content: List[Dict[str, Any]] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "title": "风控事件",
                    "text": f"最近 {len(logs)} 条事件，按时间倒序显示。",
                },
            }
        ]
        if logs:
            content.append(
                {
                    "component": "VList",
                    "props": {"density": "compact", "lines": "three", "class": "border rounded"},
                    "content": [self._build_event_item(event) for event in reversed(logs[-10:])],
                }
            )
            content.append(
                {
                    "component": "VExpansionPanels",
                    "props": {"variant": "accordion", "class": "mt-2"},
                    "content": [
                        {
                            "component": "VExpansionPanel",
                            "props": {"title": "查看原始事件日志"},
                            "content": [
                                {
                                    "component": "VTextarea",
                                    "props": {
                                        "label": "原始事件日志",
                                        "modelValue": self._format_event_preview(logs),
                                        "readonly": True,
                                        "rows": 8,
                                        "auto-grow": True,
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
        else:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "density": "compact",
                        "text": "暂无风控事件。",
                    },
                }
            )
        return content

    def _build_event_item(self, event: Dict[str, Any]) -> Dict[str, Any]:
        title = f"{event.get('time') or '-'} · {event.get('event_type') or '-'}"
        subtitle = (
            f"来源：{self._short_text(event.get('source') or '-', 80)}\n"
            f"接口：{self._short_text(event.get('endpoint') or '-', 80)} · "
            f"阈值：{self._short_text(event.get('threshold') or '-', 120)}\n"
            f"摘要：{self._short_text(event.get('detail') or '-', 180)}"
        )
        return {
            "component": "VListItem",
            "props": {"title": title, "subtitle": subtitle, "lines": "three", "class": "py-2"},
        }

    def get_live_status(self) -> Dict[str, Any]:
        return self._build_live_status()

    def page_refresh(self) -> Dict[str, Any]:
        """Return success so MoviePilot reloads the current page schema."""
        return {
            "success": True,
            "snapshot_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def retry_failed_task(self, history_id: Any = None) -> Dict[str, Any]:
        task_id = str(history_id or "").strip()
        if not task_id:
            return {"success": False, "status": "invalid", "message": "缺少 history_id"}
        if self._stopped or not self._enabled or not self._retry_failed_after_cooldown:
            return {"success": False, "status": "disabled", "message": "插件未启用或自动重试已关闭"}
        with self._scheduler_lock:
            if self._retry_in_progress or self._dispatch_pending:
                return {"success": False, "status": "busy", "message": "已有重试任务正在执行"}

        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            from app.db.models.transferhistory import TransferHistory
        except Exception as exc:
            logger.warning(
                "[U115RiskControl] manual retry import failed: "
                f"error_type={type(exc).__name__}"
            )
            return {"success": False, "status": "unavailable", "message": "MoviePilot 整理接口不可用"}

        try:
            histories = self._list_failed_transfer_histories(TransferHistoryOper, TransferHistory)
        except Exception as exc:
            logger.warning(
                "[U115RiskControl] manual retry history lookup failed: "
                f"error_type={type(exc).__name__}"
            )
            return {"success": False, "status": "unavailable", "message": "无法读取失败整理历史"}

        now = time.time()
        retry_state = self._load_retry_state(histories=histories, now_ts=now)
        records = retry_state.setdefault("groups", {})
        task_groups = self._collapse_failed_histories(histories, records, now)
        task_group = next((item for item in task_groups if task_id in item["history_ids"]), None)
        if not task_group:
            return {"success": False, "status": "not_found", "message": "未找到仍处于失败状态的整理任务"}

        history = task_group["history"]
        group_key = task_group["group_key"]
        record = normalize_record(task_group["record"], now, group_key=group_key)
        existing_success, existing_message = self._verify_existing_success_history(
            history=history,
            TransferHistoryOper=TransferHistoryOper,
        )
        if existing_success or self._target_file_exists(history):
            return {"success": False, "status": "handled", "message": existing_message or "目标文件已存在"}
        source_missing = self._source_file_missing(history)
        damaged = self._is_damaged_history(history)
        if source_missing or damaged:
            return {"success": False, "status": "manual_required", "message": "源文件不存在或历史记录缺少必要源文件信息"}

        classification = classify_retry_error(extract_history_error(history, record))
        if not classification["manual_retryable"]:
            return {"success": False, "status": "manual_required", "message": "该错误当前不可安全重试"}
        next_retry_at, wait_reason = calculate_manual_retry_at(
            record,
            self._get_retry_safety_state(),
            {"until": self._current_cooldown_until},
            now_ts=now,
            retry_delay_seconds=self._retry_failed_delay_seconds,
        )
        if next_retry_at > now:
            return {
                "success": False,
                "status": "cooldown",
                "message": f"尚未到预计重试时间：{self._format_history_time(next_retry_at)}；{wait_reason}",
                "next_retry_at": self._format_history_time(next_retry_at),
            }

        with self._scheduler_lock:
            if self._retry_in_progress or self._dispatch_pending:
                return {"success": False, "status": "busy", "message": "已有重试任务正在执行"}
            self._dispatch_pending = True
        latest_history_id = str(getattr(history, "id", "") or task_id)
        self._dispatch_retry_scan(
            "人工触发单条重试",
            target_history_id=latest_history_id,
            manual=True,
        )
        return {
            "success": True,
            "status": "queued",
            "message": "单条失败整理任务已加入重试",
            "history_id": latest_history_id,
            "group_key": group_key,
        }

    def stop_service(self):
        self._stopped = True
        self._instance_generation = ""
        with self.__class__._native_gate:
            self.__class__._native_gate.notify_all()
        with self._scheduler_lock:
            self._scheduler_started = False
            self._pending_scan_requested = False
            self._pending_scan_not_before = 0.0
            self._pending_scan_reason = ""
            self._dispatch_pending = False
            self._pending_target_history_id = ""
            self._pending_manual = False
        self._restore_patch()
        self._retry_scheduled_until = 0.0
        if not self._retry_in_progress:
            self._retry_current_history_id = ""
            self._retry_current_group_key = ""

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
                shared_limit_until = self._shared_native_limit_until()
                if shared_limit_until > 0:
                    before_limit_until = max(self._get_native_limit_until(instance), shared_limit_until)
                    try:
                        instance._limit_until = before_limit_until
                    except Exception:
                        pass
                else:
                    before_limit_until = self._get_native_limit_until(instance)

                self._inspect_native_limit_window(
                    instance=instance,
                    endpoint=endpoint_text,
                    before_limit_until=0.0,
                    after_limit_until=before_limit_until,
                    request_started_at=request_started_at,
                    phase="before_request",
                )

                claimed_probe = self._await_native_cooldown_gate(
                    instance=instance,
                    endpoint=endpoint_text,
                )

                self._maybe_soft_cooldown(
                    instance=instance,
                    endpoint=endpoint_text,
                    hourly_soft_limit=hourly_soft_limit,
                    hourly_soft_cooldown=hourly_soft_cooldown,
                )

                call_ok = False
                try:
                    result = original_request_api(instance, *args, **kwargs)
                    call_ok = True
                    elapsed = max(time.time() - request_started_at, 0.0)
                    if elapsed >= self._native_sleep_probe_threshold():
                        # MP 内部撞限后会直接 sleep(limit_sleep_seconds) 再重试，
                        # 调用耗时异常长说明已经发生过一次访问上限。
                        self._arm_native_cooldown(
                            until=time.time() + max(float(self._limit_sleep_seconds or 0), 0.0),
                            endpoint=endpoint_text,
                        )
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
                finally:
                    self._finish_native_cooldown_gate(
                        claimed_probe=claimed_probe,
                        call_ok=call_ok,
                    )

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
        self._arm_native_cooldown(until=time.time() + max(self._limit_sleep_seconds, 0), endpoint=endpoint)
        self._record_event(
            event_type=EVENT_TYPE_HARD_LIMIT,
            source="MoviePilot / 内置 u115",
            endpoint=endpoint,
            threshold=f"limit_sleep_seconds={self._limit_sleep_seconds}",
            detail="115 返回“已达到当前访问上限”，说明当前命中的是账号侧硬风控。",
            suggestion="优先降低每小时整理量，而不是只调整瞬时 QPS。",
        )

    @classmethod
    def _shared_native_limit_until(cls) -> float:
        try:
            return float(cls._native_cooldown_until or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _native_sleep_probe_threshold(self) -> float:
        """单次调用耗时超过该秒数时，判定 MP 内部已经因为访问上限休眠过。"""
        limit_sleep = float(self._limit_sleep_seconds or 0)
        if limit_sleep <= 0:
            return 300.0
        return max(min(limit_sleep * 0.5, 600.0), 30.0)

    def _sync_instance_native_limit(self, instance) -> float:
        shared_until = self._shared_native_limit_until()
        if shared_until <= 0:
            return 0.0
        current = self._get_native_limit_until(instance)
        if shared_until > current:
            try:
                instance._limit_until = shared_until
            except Exception:
                pass
        return shared_until

    def _await_native_cooldown_gate(self, *, instance, endpoint: str) -> bool:
        """冷却期阻塞，冷却结束后只放行一个探针请求；返回 True 表示本请求是探针。"""
        cls = self.__class__
        probe_gap = float(NATIVE_COOLDOWN_PROBE_GAP_SECONDS or 0)
        while True:
            if self._stopped:
                return False
            with cls._native_gate:
                shared_until = self._sync_instance_native_limit(instance)
                now = time.time()
                if not cls._native_guard_active:
                    return False
                if shared_until > now:
                    wait_seconds = jittered_wait_seconds(shared_until - now, random.random())
                    cls._native_gate.wait(
                        timeout=min(max(wait_seconds, 1.0), NATIVE_COOLDOWN_MAX_WAIT_SECONDS)
                    )
                    continue
                if not should_start_cooldown_probe(
                    now_ts=now,
                    cooldown_until=shared_until,
                    probe_in_flight=cls._native_probe_in_flight,
                    last_probe_at=cls._native_last_probe_at,
                    probe_gap_seconds=probe_gap if cls._native_fail_streak else 0.0,
                ):
                    cls._native_gate.wait(timeout=NATIVE_COOLDOWN_PROBE_POLL_SECONDS)
                    continue
                cls._native_probe_in_flight = True
                cls._native_last_probe_at = now
                if self._startup_log:
                    logger.info(
                        "[U115RiskControl] cooldown probe released: "
                        f"endpoint={endpoint or 'unknown'}, "
                        f"fail_streak={cls._native_fail_streak}"
                    )
                return True

    def _finish_native_cooldown_gate(self, *, claimed_probe: bool, call_ok: bool = True) -> None:
        """探针请求结束后释放闸门：成功则退出守护，失败则由 _arm_native_cooldown 重新计时。"""
        if not claimed_probe:
            return
        cls = self.__class__
        recovered = False
        with cls._native_gate:
            cls._native_probe_in_flight = False
            if call_ok and cls._native_guard_active and cls._native_cooldown_until <= time.time():
                cls._native_guard_active = False
                cls._native_fail_streak = 0
                cls._native_cooldown_until = 0.0
                recovered = True
            cls._native_gate.notify_all()
        self._persist_native_cooldown()
        if recovered:
            self._current_cooldown_reason = "未冷却"
            self._current_cooldown_remaining = 0
            self._current_cooldown_until = 0.0
            self._record_event(
                event_type=EVENT_TYPE_COOLDOWN_RECOVERED,
                source="U115RiskControl / 共享冷却",
                endpoint="U115Pan._request_api",
                threshold="probe_success",
                detail="探针请求未再被 115 判定为访问上限，共享冷却结束并恢复正常请求节奏。",
                suggestion="若短时间内再次触发，请继续降低每小时整理量，并确认同一 115 账号是否还有其他客户端在使用。",
            )

    def _arm_native_cooldown(self, *, until: float, endpoint: str = "") -> None:
        """把单次硬风控升级为跨实例共享、持久化并按连续轮次放大的冷却。"""
        now = time.time()
        detected_until = max(float(until or 0.0), now)
        cls = self.__class__
        with cls._native_gate:
            fresh_window = cls._native_cooldown_until <= now
            if fresh_window:
                cls._native_fail_streak = min(cls._native_fail_streak + 1, NATIVE_COOLDOWN_STREAK_MAX)
                base = max(detected_until - now, float(self._limit_sleep_seconds or 0))
                escalated = max(escalated_cooldown_seconds(base, cls._native_fail_streak), base)
                cls._native_cooldown_until = now + escalated
            else:
                # 同一冷却窗口内的重复检测只延长到实际窗口结束时间，不能无限续期
                cls._native_cooldown_until = max(cls._native_cooldown_until, detected_until)
            cls._native_guard_active = True
            cls._native_probe_in_flight = False
            cls._native_last_probe_at = now
            effective_until = cls._native_cooldown_until
            cls._native_gate.notify_all()

        remaining = max(int(math.ceil(effective_until - now)), 0)
        self._current_cooldown_reason = "115 硬风控"
        self._current_cooldown_remaining = remaining
        self._current_cooldown_until = effective_until
        self._last_native_limit_until = max(self._last_native_limit_until, float(until or 0.0))
        self._schedule_failed_transfer_retry("115 硬风控冷却结束", delay_seconds=remaining)
        self._persist_native_cooldown()
        if self._startup_log:
            logger.warning(
                "[U115RiskControl] shared cooldown armed: "
                f"endpoint={endpoint or 'unknown'}, "
                f"fail_streak={cls._native_fail_streak}, remaining={remaining}s"
            )

    def _persist_native_cooldown(self) -> None:
        now = time.time()
        if now - self._native_cooldown_persist_at < NATIVE_COOLDOWN_PERSIST_INTERVAL_SECONDS:
            return
        self._native_cooldown_persist_at = now
        cls = self.__class__
        try:
            self.save_data(
                NATIVE_COOLDOWN_DATA_KEY,
                {
                    "until": self._shared_native_limit_until(),
                    "guard_active": bool(cls._native_guard_active),
                    "fail_streak": int(cls._native_fail_streak or 0),
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
            )
        except Exception as exc:
            logger.warning(
                "[U115RiskControl] save native cooldown failed: "
                f"error_type={type(exc).__name__}"
            )

    def _restore_native_cooldown(self) -> None:
        try:
            data = self.get_data(NATIVE_COOLDOWN_DATA_KEY) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        now = time.time()
        until = to_timestamp(data.get("until"))
        streak = self._to_int(
            data.get("fail_streak"),
            0,
            minimum=0,
            maximum=NATIVE_COOLDOWN_STREAK_MAX,
        )
        guard_active = bool(data.get("guard_active")) or until > now or streak > 0
        if not guard_active:
            return

        cls = self.__class__
        with cls._native_gate:
            cls._native_cooldown_until = max(cls._native_cooldown_until, until)
            cls._native_fail_streak = max(cls._native_fail_streak, streak)
            cls._native_guard_active = True
            cls._native_probe_in_flight = False
            effective_until = cls._native_cooldown_until

        remaining = max(int(math.ceil(effective_until - now)), 0)
        if remaining > 0:
            self._last_native_limit_until = effective_until
            self._current_cooldown_reason = "115 硬风控"
            self._current_cooldown_remaining = remaining
            self._current_cooldown_until = effective_until
        self._record_event(
            event_type=EVENT_TYPE_HARD_LIMIT,
            source="U115RiskControl / 共享冷却恢复",
            endpoint="plugin_init",
            threshold=f"guard_active=True, fail_streak={streak}",
            detail=(
                "已从本地数据恢复 115 硬风控共享冷却，避免插件重载后立刻向 115 发请求。"
                f"剩余约 {remaining} 秒。"
            ),
            suggestion="冷却结束后由单个探针请求确认恢复，再恢复正常整理节奏。",
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
        self._arm_native_cooldown(until=after_limit_until, endpoint=endpoint)

        self._record_event(
            event_type=EVENT_TYPE_HARD_LIMIT,
            source="MoviePilot / 内置 u115",
            endpoint=endpoint,
            threshold=f"_limit_until={datetime.fromtimestamp(after_limit_until).strftime('%Y-%m-%d %H:%M:%S')}",
            detail=(
                "检测到 MoviePilot 内置 u115 已进入风控冷却窗口。"
                f"阶段：{phase}，剩余约 {remaining} 秒。"
            ),
            suggestion="插件已按共享冷却结束时间安排失败整理重试；冷却结束后只放行一个探针请求试探 115。",
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

        shared_remaining = int(self._shared_native_limit_until() - time.time())
        if shared_remaining > delay_seconds:
            delay_seconds = shared_remaining
            cooldown_count = max(cooldown_count, 1)

        if delay_seconds > 0:
            reason = "插件启动补偿扫描：等待现有 115 冷却结束"
        else:
            reason = "插件启动补偿扫描：当前未检测到 115 冷却"
        self._schedule_failed_transfer_retry(
            reason,
            delay_seconds=max(delay_seconds, 0),
            include_retry_delay=True,
        )
        self._record_event(
            event_type=EVENT_TYPE_RETRY_SCHEDULED,
            source="U115RiskControl / startup retry scan",
            endpoint="TransferHistory",
            threshold=f"native_cooldown_instances={cooldown_count}, delay={max(delay_seconds, 0)}s",
            detail="插件启动后已安排一次失败整理补偿扫描，用于处理安装新版本前已结束的冷却期。",
            suggestion="若失败整理历史仍未被处理，请查看状态页最近重试状态，确认是否为无候选任务、已重试过或 MP 接口不可用。",
        )

    def _schedule_failed_transfer_retry(
        self,
        reason: str,
        delay_seconds: Optional[int] = None,
        include_retry_delay: bool = True,
    ) -> None:
        if not self._retry_failed_after_cooldown:
            self._last_retry_status = "已关闭"
            return

        if self._stopped or not self._enabled:
            return
        delay = max(int(delay_seconds if delay_seconds is not None else 0), 0)
        if include_retry_delay:
            delay += max(int(self._retry_failed_delay_seconds), 0)
        scheduled_until = time.time() + delay

        with self._scheduler_lock:
            if self._pending_scan_requested and self._pending_scan_not_before >= scheduled_until:
                self._duplicate_schedule_skipped += 1
                return
            self._pending_scan_requested = True
            self._pending_scan_not_before = max(self._pending_scan_not_before, scheduled_until)
            self._pending_scan_reason = reason
            self._retry_scheduled_until = self._pending_scan_not_before
            self._retry_scheduled_reason = reason

        self._record_event(
            event_type=EVENT_TYPE_RETRY_SCHEDULED,
            source="U115RiskControl / failed transfer retry",
            endpoint="TransferHistory",
            threshold=f"delay={delay}s, max_count={self._retry_failed_max_count}",
            detail=f"已计划在风控期后重试 MP 失败整理任务，原因：{reason}。",
            suggestion="如果失败任务很多，建议保持较小的单次重试条数，避免恢复后立即再次触发风控。",
        )
        if scheduled_until <= time.time():
            self._dispatch_retry_scan(reason)

    def _dispatch_retry_scan(
        self,
        reason: str,
        *,
        target_history_id: str = "",
        manual: bool = False,
    ) -> None:
        generation = self._instance_generation
        if self._stopped or not generation:
            return
        thread = threading.Thread(
            target=self._run_retry_scan_if_current,
            kwargs={
                "generation": generation,
                "trigger_reason": reason,
                "target_history_id": target_history_id,
                "manual": manual,
            },
            name="U115RiskControlRetryDispatch",
            daemon=True,
        )
        self._retry_threads.append(thread)
        thread.start()

    def _run_retry_scan_if_current(
        self,
        *,
        generation: str,
        trigger_reason: str,
        target_history_id: str = "",
        manual: bool = False,
    ) -> None:
        if self._stopped or not generation or generation != self._instance_generation:
            return
        self._run_retry_scan(
            trigger_reason=trigger_reason,
            target_history_id=target_history_id,
            manual=manual,
        )

    def _run_retry_scan(
        self,
        trigger_reason: str = "周期补偿扫描",
        target_history_id: str = "",
        manual: bool = False,
    ) -> None:
        if self._stopped or not self._enabled or not self._retry_failed_after_cooldown:
            return
        now = time.time()
        with self._scheduler_lock:
            if self.__class__._global_retry_in_progress or not self._retry_lock.acquire(blocking=False):
                self._dispatch_pending = False
                self._pending_scan_requested = True
                self._pending_scan_not_before = min(
                    value for value in (self._pending_scan_not_before, now) if value > 0
                ) if self._pending_scan_not_before else now
                self._pending_scan_reason = trigger_reason
                if target_history_id:
                    self._pending_target_history_id = target_history_id
                    self._pending_manual = manual
                self._duplicate_schedule_skipped += 1
                return
            self._dispatch_pending = False
            self.__class__._global_retry_in_progress = True
            self._retry_in_progress = True
            self._last_retry_scan_time = self._format_history_time(now)
            self._next_retry_scan_time = self._format_history_time(now + RETRY_SCAN_INTERVAL_SECONDS)
            if self._pending_scan_not_before <= now:
                self._pending_scan_requested = False
                self._pending_scan_not_before = 0.0
                self._pending_scan_reason = ""
                self._retry_scheduled_until = 0.0
        try:
            self._retry_failed_transfer_histories(
                trigger_reason,
                target_history_id=target_history_id,
                manual=manual,
            )
            self._last_retry_scan_result = self._last_retry_status
        except Exception as exc:
            error_type = type(exc).__name__
            self._last_retry_status = f"执行异常：{error_type}"
            self._last_retry_scan_result = self._last_retry_status
            self._last_retry_time = self._format_history_time(now)
            logger.exception("[U115RiskControl] failed transfer retry scan crashed")
        finally:
            with self._scheduler_lock:
                self.__class__._global_retry_in_progress = False
                self.__class__._global_retry_current_history_id = ""
                self.__class__._global_retry_current_group_key = ""
                self._retry_in_progress = False
                self._dispatch_pending = False
                self._retry_current_history_id = ""
                self._retry_current_group_key = ""
                follow_up = (
                    self._pending_scan_requested
                    and self._pending_scan_not_before <= time.time()
                    and not self._stopped
                )
                follow_up_reason = self._pending_scan_reason or "合并补偿扫描"
                follow_up_target = self._pending_target_history_id
                follow_up_manual = self._pending_manual
                if follow_up:
                    self._pending_target_history_id = ""
                    self._pending_manual = False
                self._retry_threads = [item for item in self._retry_threads if item.is_alive()]
            self._retry_lock.release()
        if follow_up:
            self._dispatch_retry_scan(
                follow_up_reason,
                target_history_id=follow_up_target,
                manual=follow_up_manual,
            )

    def _retry_failed_transfer_histories(
        self,
        reason: str,
        *,
        target_history_id: str = "",
        manual: bool = False,
    ) -> None:
        self._last_retry_status = "执行中"
        self._last_retry_time = self._format_history_time(time.time())
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
            logger.warning(
                "[U115RiskControl] retry scan import failed: "
                f"error_type={type(exc).__name__}"
            )
            return

        now_ts = time.time()
        raw_histories = self._list_failed_transfer_histories(TransferHistoryOper, TransferHistory)
        retry_state = self._load_retry_state(histories=raw_histories, now_ts=now_ts)
        retry_records = retry_state.setdefault("groups", {})
        task_groups = self._collapse_failed_histories(raw_histories, retry_records, now_ts)
        safety_state = self._get_retry_safety_state()
        cooldown_state = {"until": self._current_cooldown_until}
        candidates: List[Dict[str, Any]] = []
        skipped_count = 0
        cooldown_count = 0
        retryable_count = 0
        manual_required_count = 0
        handled_count = 0

        for task_group in task_groups:
            history = task_group["history"]
            group_key = task_group["group_key"]
            history_id = str(getattr(history, "id", "") or "")
            record = normalize_record(task_group["record"], now_ts, group_key=group_key)
            record["latest_history_id"] = history_id
            record["history_ids"] = sorted(set(record["history_ids"] + task_group["history_ids"]))
            record["first_seen_at"] = record["first_seen_at"] or history_failed_at(history) or now_ts

            existing_success, existing_message = self._verify_existing_success_history(
                history=history,
                TransferHistoryOper=TransferHistoryOper,
            )
            target_exists = bool(self._target_file_exists(history))
            source_missing = self._source_file_missing(history)
            damaged = self._is_damaged_history(history)
            error_message = extract_history_error(history, record)
            classification = classify_retry_error(error_message)
            if source_missing:
                classification = classify_retry_error("源文件不存在")
            elif damaged:
                classification = classify_retry_error("历史记录损坏，缺少源文件信息")

            if existing_success or target_exists:
                record["last_result"] = RETRY_RESULT_HANDLED
                record["last_message"] = sanitize_message(existing_message or "目标文件已存在")
                record["manual_required"] = False
                record["error_code"] = "handled"
                record["next_retry_at"] = 0.0
                record["wait_reason"] = "已确认成功或目标存在"
                handled_count += 1
                retry_records[group_key] = record
                continue

            if classification["auto_retryable"]:
                next_retry_at, wait_reason = calculate_next_retry_at(
                    history,
                    record,
                    safety_state,
                    cooldown_state,
                    now_ts=now_ts,
                    next_scan_at=now_ts,
                    retry_delay_seconds=self._retry_failed_delay_seconds,
                )
            elif manual and classification["manual_retryable"]:
                next_retry_at, wait_reason = calculate_manual_retry_at(
                    record,
                    safety_state,
                    cooldown_state,
                    now_ts=now_ts,
                    retry_delay_seconds=self._retry_failed_delay_seconds,
                )
            else:
                next_retry_at = 0.0
                wait_reason = self._manual_wait_reason(
                    classification,
                    source_missing=source_missing,
                    damaged=damaged,
                )
            record["next_retry_at"] = next_retry_at
            record["wait_reason"] = wait_reason
            record["error_code"] = classification["code"]
            if classification["message"]:
                record["last_message"] = classification["message"]
            record["manual_required"] = not classification["auto_retryable"]
            if record["last_result"] not in {RETRY_RESULT_RUNNING, RETRY_RESULT_FAILED}:
                record["last_result"] = (
                    RETRY_RESULT_PENDING if classification["auto_retryable"] else RETRY_RESULT_MANUAL
                )
            record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            retry_records[group_key] = record

            requested_group = not target_history_id or target_history_id in task_group["history_ids"]
            if not requested_group:
                continue
            if source_missing or damaged:
                manual_required_count += 1
                skipped_count += 1
                continue
            can_retry_kind = classification["manual_retryable"] if manual else classification["auto_retryable"]
            if not can_retry_kind:
                manual_required_count += 1
                skipped_count += 1
                continue
            if next_retry_at > now_ts:
                cooldown_count += 1
                skipped_count += 1
                continue
            retryable_count += 1
            if self._retry_failed_max_count and len(candidates) >= self._retry_failed_max_count:
                skipped_count += 1
                continue
            candidates.append(task_group)

        retry_state["version"] = RETRY_DATA_VERSION
        retry_state["scheduler"] = {
            "last_scan_at": now_ts,
            "next_scan_at": now_ts + RETRY_SCAN_INTERVAL_SECONDS,
            "last_scan_result": "扫描完成，等待执行",
        }
        self._save_retry_state(retry_state)

        success_count = 0
        failed_count = 0
        for index, task_group in enumerate(candidates, 1):
            if self._stopped:
                skipped_count += len(candidates) - index + 1
                break
            history = task_group["history"]
            history_id = str(getattr(history, "id", "") or "")
            group_key = task_group["group_key"]
            record = normalize_record(retry_records.get(group_key), time.time(), group_key=group_key)

            existing_success, existing_message = self._verify_existing_success_history(
                history=history,
                TransferHistoryOper=TransferHistoryOper,
            )
            if existing_success or self._target_file_exists(history):
                record["last_result"] = RETRY_RESULT_HANDLED
                record["last_message"] = sanitize_message(existing_message or "目标文件已存在")
                record["next_retry_at"] = 0.0
                retry_records[group_key] = record
                handled_count += 1
                skipped_count += 1
                self._save_retry_state(retry_state)
                continue
            if self._source_file_missing(history) or self._is_damaged_history(history):
                record["last_result"] = RETRY_RESULT_MANUAL
                record["manual_required"] = True
                record["error_code"] = "source_missing"
                record["last_message"] = "源文件不存在或历史记录缺少源文件信息"
                retry_records[group_key] = record
                manual_required_count += 1
                skipped_count += 1
                self._save_retry_state(retry_state)
                continue

            current_safety = self._get_retry_safety_state()
            current_cooldown = {"until": self._current_cooldown_until}
            due_at, wait_reason = calculate_next_retry_at(
                history,
                record,
                current_safety,
                current_cooldown,
                now_ts=time.time(),
                next_scan_at=time.time(),
                retry_delay_seconds=self._retry_failed_delay_seconds,
            )
            if due_at > time.time():
                record["next_retry_at"] = due_at
                record["wait_reason"] = wait_reason
                retry_records[group_key] = record
                cooldown_count += 1
                skipped_count += 1
                self._save_retry_state(retry_state)
                continue

            attempt_ts = time.time()
            record = reserve_attempt(record, history, attempt_ts)
            record["wait_reason"] = "正在执行 MoviePilot 原生历史重试"
            retry_records[group_key] = record
            self._save_retry_state(retry_state)

            self._retry_current_history_id = history_id
            self._retry_current_group_key = group_key
            self.__class__._global_retry_current_history_id = history_id
            self.__class__._global_retry_current_group_key = group_key
            summary = f"#{history_id} group:{short_group_key(group_key)}"
            self._update_retry_progress(
                f"同步 MP 整理 {index}/{len(candidates)}",
                summary,
                f"累计第 {record['total_attempts']} 次尝试",
            )
            logger.info(
                "[U115RiskControl] retry started: "
                f"history_id={history_id}, group={short_group_key(group_key)}, "
                f"attempt={record['total_attempts']}"
            )
            try:
                state, message = self._retry_one_transfer_history(
                    history=history,
                    TransferChain=TransferChain,
                    FileItem=FileItem,
                    MediaType=MediaType,
                    EpisodeFormat=EpisodeFormat,
                )
                if state:
                    state, message = self._confirm_transfer_history_result(
                        history=history,
                        history_id=history_id,
                        TransferHistoryOper=TransferHistoryOper,
                    )
            except Exception as exc:
                state = False
                message = type(exc).__name__
                logger.exception(
                    "[U115RiskControl] retry failed: "
                    f"history_id={history_id}, group={short_group_key(group_key)}, "
                    f"error_type={type(exc).__name__}"
                )

            finished_at = time.time()
            record = normalize_record(retry_records.get(group_key), finished_at, group_key=group_key)
            sanitized_message = sanitize_message(message)
            result_classification = classify_retry_error(sanitized_message)
            if state:
                success_count += 1
                record["consecutive_failures"] = 0
                record["last_result"] = RETRY_RESULT_SUCCEEDED
                record["last_message"] = sanitized_message or "已复查确认整理成功"
                record["manual_required"] = False
                record["error_code"] = ""
                record["next_retry_at"] = 0.0
                record["wait_reason"] = "整理完成"
            else:
                failed_count += 1
                record["consecutive_failures"] += 1
                record["last_result"] = RETRY_RESULT_FAILED
                record["last_message"] = sanitized_message or "MoviePilot 整理失败，未返回详情"
                record["manual_required"] = not result_classification["auto_retryable"]
                record["error_code"] = result_classification["code"]
                if result_classification["auto_retryable"]:
                    record["next_retry_at"], record["wait_reason"] = calculate_next_retry_at(
                        history,
                        record,
                        self._get_retry_safety_state(),
                        {"until": self._current_cooldown_until},
                        now_ts=finished_at,
                        next_scan_at=finished_at + RETRY_SCAN_INTERVAL_SECONDS,
                        retry_delay_seconds=self._retry_failed_delay_seconds,
                    )
                else:
                    record["next_retry_at"] = 0.0
                    record["wait_reason"] = self._manual_wait_reason(result_classification)
            record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            retry_records[group_key] = record
            self._save_retry_state(retry_state)
            logger.info(
                "[U115RiskControl] retry finished: "
                f"history_id={history_id}, group={short_group_key(group_key)}, "
                f"result={'success' if state else 'failed'}, error_type={record['error_code'] or 'none'}"
            )

        try:
            refreshed = self._list_failed_transfer_histories(TransferHistoryOper, TransferHistory)
            self._collapse_failed_histories(refreshed, retry_records, time.time())
        except Exception as exc:
            logger.warning(
                "[U115RiskControl] retry history refresh failed: "
                f"error_type={type(exc).__name__}"
            )

        total = len(candidates)
        self._last_retry_total = total
        self._last_retry_success = success_count
        self._last_retry_failed = failed_count
        self._last_retry_skipped = skipped_count
        self._last_retry_failed_history_count = len(task_groups)
        self._last_retry_cooldown_count = cooldown_count
        self._last_retry_retryable_count = retryable_count
        self._last_retry_manual_required_count = manual_required_count
        if failed_count:
            self._last_retry_status = "部分整理失败"
        elif total:
            self._last_retry_status = "整理完成"
        elif cooldown_count:
            self._last_retry_status = "等待冷却后重试"
        elif manual_required_count:
            self._last_retry_status = "待人工确认"
        else:
            self._last_retry_status = "无可重试任务"
        self._update_retry_progress(
            self._last_retry_status,
            "无",
            (
                f"任务组 {len(task_groups)}，执行 {total}，成功 {success_count}，失败 {failed_count}，"
                f"跳过 {skipped_count}，合并历史 {max(len(raw_histories) - len(task_groups), 0)}。"
            ),
        )
        retry_state["last_run"] = {
            "time": self._last_retry_time,
            "reason": reason,
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "failed_history_count": len(task_groups),
            "raw_failed_history_count": len(raw_histories),
            "duplicate_history_count": max(len(raw_histories) - len(task_groups), 0),
            "cooldown_count": cooldown_count,
            "retryable_count": retryable_count,
            "manual_required_count": manual_required_count,
            "progress": self._last_retry_progress,
            "current_task": self._last_retry_current_task,
            "progress_detail": self._last_retry_progress_detail,
        }
        retry_state["scheduler"]["last_scan_result"] = self._last_retry_status
        self._save_retry_state(retry_state)

    def _list_failed_transfer_histories(self, TransferHistoryOper, TransferHistory) -> List[Any]:
        db = self._resolve_history_db(TransferHistoryOper)
        if db is None:
            logger.warning(
                "[U115RiskControl] history database is not available, skip retry scan"
            )
            return []
        session = db if hasattr(db, "close") else None
        try:
            for kwargs in (
                {"page": 1, "count": -1, "status": False},
                {"page": 1, "count": 200, "status": False},
            ):
                try:
                    histories = TransferHistory.list_by_page(db, **kwargs)
                    return list(histories or [])
                except TypeError:
                    continue
            histories = TransferHistory.list_by_page(db, 1, 200, False)
            return list(histories or [])
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    @staticmethod
    def _resolve_history_db(TransferHistoryOper) -> Any:
        """优先使用 MoviePilot v3 的 SessionFactory，回退到旧版 Oper 的 _db。"""
        try:
            from app.db.session import SessionFactory

            session = SessionFactory()
            if session is not None:
                return session
        except Exception:
            pass
        try:
            return getattr(TransferHistoryOper(), "_db", None)
        except Exception:
            return None

    def _format_transfer_history_summary(self, history: Any) -> str:
        history_id = self._short_text(getattr(history, "id", "") or "无ID", 24)
        return f"#{history_id} group:{short_group_key(self._retry_task_key(history))}"

    def _retry_one_transfer_history(self, *, history, TransferChain, FileItem, MediaType, EpisodeFormat) -> Tuple[bool, str]:
        history_id = getattr(history, "id", None)
        chain = TransferChain()
        if history_id and hasattr(chain, "redo_transfer_history"):
            try:
                signature = inspect.signature(chain.redo_transfer_history)
                accepts_kwargs = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
                redo_kwargs = (
                    {"no_error_log": False}
                    if "no_error_log" in signature.parameters or accepts_kwargs
                    else {}
                )
                result = chain.redo_transfer_history(history_id, **redo_kwargs)
                if isinstance(result, tuple) and len(result) >= 2:
                    state, message = result[0], result[1]
                else:
                    state, message = bool(result), result
                message_text = self._extract_message(message)
                if not message_text:
                    message_text = "已调用 MoviePilot 原生历史重试" if state else "MoviePilot 整理接口返回失败，未提供错误详情"
                return bool(state), self._short_text(message_text)
            except Exception as exc:
                logger.warning(
                    "[U115RiskControl] native redo_transfer_history failed, fallback manual_transfer: "
                    f"id={history_id}, error_type={type(exc).__name__}"
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
            "no_error_log": False,
        }
        signature = inspect.signature(chain.manual_transfer)
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if not accepts_kwargs:
            kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        result = chain.manual_transfer(**kwargs)
        if isinstance(result, tuple) and len(result) >= 2:
            state, message = result[0], result[1]
        else:
            state, message = bool(result), result
        message_text = self._extract_message(message)
        if not message_text:
            message_text = "MoviePilot 整理接口返回失败，未提供错误详情" if not state else "MoviePilot 整理接口已提交"
        return bool(state), self._short_text(message_text)

    def _confirm_transfer_history_result(
        self,
        *,
        history: Any,
        history_id: str,
        TransferHistoryOper: Any,
    ) -> Tuple[bool, str]:
        deadline = time.time() + RETRY_CONFIRM_TIMEOUT_SECONDS
        last_message = "提交后暂未确认完成"
        while True:
            verified, message = self._verify_transfer_history_result(
                history=history,
                history_id=history_id,
                TransferHistoryOper=TransferHistoryOper,
            )
            if verified:
                return True, message
            last_message = message or last_message
            if self._is_missing_source_message(last_message) or self._is_damaged_record_message(last_message):
                return False, last_message
            remaining = deadline - time.time()
            if remaining <= 0:
                return False, f"提交后 {RETRY_CONFIRM_TIMEOUT_SECONDS} 秒内未确认完成：{self._short_text(last_message, 140)}"
            time.sleep(min(RETRY_CONFIRM_POLL_SECONDS, remaining))

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

    def _retry_task_key(self, history: Any) -> str:
        return retry_group_key(history)

    def _collapse_failed_histories(
        self,
        histories: List[Any],
        retry_records: Dict[str, Any],
        now_ts: float,
    ) -> List[Dict[str, Any]]:
        """Collapse MP retry-generated history IDs into one stable logical group."""
        groups: Dict[str, List[Any]] = {}
        for history in histories:
            group_key = self._retry_task_key(history)
            if not group_key:
                invalid_identity = "|".join(
                    (
                        str(history_failed_at(history)),
                        extract_history_error(history),
                        str(type(history).__name__),
                    )
                )
                group_key = "invalid:" + hashlib.sha256(
                    invalid_identity.encode("utf-8", errors="ignore")
                ).hexdigest()[:32]
            groups.setdefault(group_key, []).append(history)

        collapsed: List[Dict[str, Any]] = []
        for group_key, group in groups.items():
            executable = [
                history
                for history in group
                if not self._is_damaged_history(history) and not self._source_file_missing(history)
            ]
            selection_pool = executable or group
            canonical_history = max(
                selection_pool,
                key=lambda history: (
                    history_failed_at(history),
                    self._to_int(getattr(history, "id", 0), 0, minimum=0, maximum=999999999),
                ),
            )
            history_ids = sorted(
                {str(getattr(history, "id", "") or "") for history in group if getattr(history, "id", None)}
            )
            stable_record = retry_records.get(group_key) if isinstance(retry_records, dict) else None
            merged = merge_records(
                group_key,
                [stable_record] if isinstance(stable_record, dict) else [],
                [],
                history_ids,
                now_ts,
            )
            merged["latest_history_id"] = str(getattr(canonical_history, "id", "") or "")
            merged["history_ids"] = history_ids
            retry_records[group_key] = merged
            collapsed.append(
                {
                    "history": canonical_history,
                    "group_key": group_key,
                    "task_key": group_key,
                    "record": merged,
                    "history_ids": history_ids,
                    "merged_history_ids": [
                        history_id for history_id in history_ids if history_id != merged["latest_history_id"]
                    ],
                }
            )
        return collapsed

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
        wait_seconds = max(math.ceil(retry_after - time.time()), 0)
        return f"安全余量不足：最近 1 小时 {used}/{limit}，剩余 {remaining}，{self._format_remaining_seconds(wait_seconds)}后再试"

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
        scheduler = retry_state.get("scheduler") if isinstance(retry_state, dict) else None
        if isinstance(scheduler, dict):
            last_scan_at = to_timestamp(scheduler.get("last_scan_at"))
            next_scan_at = to_timestamp(scheduler.get("next_scan_at"))
            if last_scan_at:
                self._last_retry_scan_time = self._format_history_time(last_scan_at)
            if next_scan_at:
                self._next_retry_scan_time = self._format_history_time(next_scan_at)
            self._last_retry_scan_result = str(scheduler.get("last_scan_result") or "未扫描")
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

    def _load_retry_state(
        self,
        *,
        histories: Optional[List[Any]] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            data = self.get_data(RETRY_DATA_KEY) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        now_ts = float(now_ts if now_ts is not None else time.time())
        original_version = self._to_int(data.get("version"), 0, minimum=0, maximum=1000)
        existing_groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
        legacy_records = data.get("legacy_records") if isinstance(data.get("legacy_records"), dict) else {}
        old_records = data.get("records") if isinstance(data.get("records"), dict) else {}

        if histories is None:
            if original_version >= RETRY_DATA_VERSION:
                data["groups"] = existing_groups
                data["legacy_records"] = legacy_records
            data.setdefault("scheduler", {})
            return data

        histories = list(histories or [])
        history_to_group: Dict[str, str] = {}
        group_history_ids: Dict[str, List[str]] = {}
        for history in histories:
            history_id = str(getattr(history, "id", "") or "")
            group_key = retry_group_key(history)
            if history_id and group_key:
                history_to_group[history_id] = group_key
                group_history_ids.setdefault(group_key, []).append(history_id)

        stable_by_group: Dict[str, List[Dict[str, Any]]] = {}
        legacy_by_group: Dict[str, List[Dict[str, Any]]] = {}
        for key, record in old_records.items():
            if not isinstance(record, dict):
                legacy_records[str(key)] = record
                continue
            candidate_ids = [str(key), str(record.get("history_id") or "")]
            if isinstance(record.get("history_ids"), list):
                candidate_ids.extend(str(item) for item in record["history_ids"])
            group_key = next(
                (history_to_group[item] for item in candidate_ids if item in history_to_group),
                "",
            )
            if not group_key:
                legacy_records[str(key)] = record
                continue
            if str(key).startswith(("task:", "group:")):
                stable_by_group.setdefault(group_key, []).append(record)
            else:
                legacy_by_group.setdefault(group_key, []).append(record)

        migrated_groups: Dict[str, Dict[str, Any]] = {}
        all_group_keys = set(existing_groups) | set(stable_by_group) | set(legacy_by_group) | set(group_history_ids)
        for group_key in all_group_keys:
            stable_records: List[Dict[str, Any]] = []
            existing = existing_groups.get(group_key)
            if isinstance(existing, dict):
                stable_records.append(existing)
            stable_records.extend(stable_by_group.get(group_key, []))
            migrated_groups[group_key] = merge_records(
                group_key,
                stable_records,
                legacy_by_group.get(group_key, []),
                group_history_ids.get(group_key, []),
                now_ts,
            )

        migrated = dict(data)
        migrated["version"] = RETRY_DATA_VERSION
        migrated["groups"] = migrated_groups
        migrated["legacy_records"] = legacy_records
        migrated["retried_ids"] = []
        migrated.pop("records", None)
        migrated.setdefault("scheduler", {})
        if original_version < RETRY_DATA_VERSION or old_records:
            migrated["migration"] = {
                "from_version": original_version,
                "to_version": RETRY_DATA_VERSION,
                "migrated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "group_count": len(migrated_groups),
                "legacy_count": len(legacy_records),
            }
            self._save_retry_state(migrated)
            if legacy_records:
                digest = hashlib.sha256(
                    "|".join(sorted(str(key) for key in legacy_records)).encode("utf-8", errors="ignore")
                ).hexdigest()[:10]
                logger.warning(
                    "[U115RiskControl] retry state migration retained unmapped records: "
                    f"count={len(legacy_records)}, digest={digest}"
                )
        return migrated

    def _save_retry_state(self, data: Dict[str, Any]) -> None:
        try:
            self.save_data(RETRY_DATA_KEY, data)
        except Exception as exc:
            logger.warning(
                "[U115RiskControl] save retry state failed: "
                f"error_type={type(exc).__name__}"
            )

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
            for key in ("message", "msg", "error", "detail", "reason"):
                value = result.get(key)
                if isinstance(value, str):
                    return value
            nested = result.get("data")
            if nested is not result:
                nested_message = self._extract_message(nested)
                if nested_message:
                    return nested_message
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

    def _get_pending_retry_tasks(self) -> Tuple[List[Dict[str, Any]], str]:
        try:
            from app.db.models.transferhistory import TransferHistory
            from app.db.transferhistory_oper import TransferHistoryOper
        except Exception:
            return [], "MoviePilot 整理历史接口暂不可用"
        try:
            histories = self._list_failed_transfer_histories(TransferHistoryOper, TransferHistory)
        except Exception:
            return [], "无法读取失败整理历史"

        now = time.time()
        retry_state = self._load_retry_state(histories=histories, now_ts=now)
        records = retry_state.setdefault("groups", {})
        task_groups = self._collapse_failed_histories(histories, records, now)
        safety_state = self._get_retry_safety_state()
        cooldown_state = {"until": self._current_cooldown_until}
        next_scan_at = to_timestamp(self._next_retry_scan_time) or now + RETRY_SCAN_INTERVAL_SECONDS
        tasks: List[Dict[str, Any]] = []
        state_changed = False

        for task_group in task_groups:
            history = task_group["history"]
            history_id = str(getattr(history, "id", "") or "")
            if not history_id:
                continue
            try:
                existing_success, _ = self._verify_existing_success_history(
                    history=history,
                    TransferHistoryOper=TransferHistoryOper,
                )
                if existing_success or self._target_file_exists(history):
                    continue
            except Exception:
                pass

            group_key = task_group["group_key"]
            record = normalize_record(task_group["record"], now, group_key=group_key)
            original_record = dict(record)
            original_updated_at = record.get("updated_at", "")
            record["latest_history_id"] = history_id
            record["history_ids"] = sorted(set(record["history_ids"] + task_group["history_ids"]))
            record["first_seen_at"] = record["first_seen_at"] or history_failed_at(history) or now
            source_missing = self._source_file_missing(history)
            damaged = self._is_damaged_history(history)
            classification = classify_retry_error(extract_history_error(history, record))
            if source_missing:
                classification = classify_retry_error("源文件不存在")
            elif damaged:
                classification = classify_retry_error("历史记录损坏，缺少源文件信息")
            if classification["auto_retryable"]:
                next_retry_at, wait_reason = calculate_next_retry_at(
                    history,
                    record,
                    safety_state,
                    cooldown_state,
                    now_ts=now,
                    next_scan_at=next_scan_at,
                    retry_delay_seconds=self._retry_failed_delay_seconds,
                )
            else:
                next_retry_at = 0.0
                wait_reason = self._manual_wait_reason(
                    classification,
                    source_missing=source_missing,
                    damaged=damaged,
                )
            record["next_retry_at"] = next_retry_at
            record["wait_reason"] = wait_reason
            record["error_code"] = classification["code"]
            record["manual_required"] = not classification["auto_retryable"]
            if classification["message"]:
                record["last_message"] = classification["message"]
            record["updated_at"] = original_updated_at
            changed = record != original_record
            if changed:
                record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            records[group_key] = record
            state_changed = state_changed or changed

            executing = group_key in {
                self._retry_current_group_key,
                self.__class__._global_retry_current_group_key,
            }
            if executing:
                status = "正在重试"
                status_type = "info"
                can_retry = False
                wait_reason = "当前任务正在执行"
            elif source_missing or damaged:
                status = "需人工处理"
                status_type = "warning"
                can_retry = False
                wait_reason = self._manual_wait_reason(
                    classification,
                    source_missing=source_missing,
                    damaged=damaged,
                )
            elif not classification["auto_retryable"]:
                status = "待人工确认"
                status_type = "warning"
                can_retry = bool(
                    classification["manual_retryable"]
                    and next_retry_at <= now
                    and not self._retry_in_progress
                    and not self._dispatch_pending
                )
            elif next_retry_at > now:
                status = "冷却中"
                status_type = "info"
                can_retry = False
            else:
                status = "可重试"
                status_type = "success"
                can_retry = bool(
                    self._enabled
                    and self._retry_failed_after_cooldown
                    and not self._retry_in_progress
                    and not self._dispatch_pending
                )

            if status in {"待人工确认", "需人工处理"}:
                remaining_seconds = 0
                remaining_text = "不会自动重试"
            elif status == "正在重试":
                remaining_seconds = 0
                remaining_text = "执行中"
            elif status == "可重试":
                remaining_seconds = 0
                remaining_text = "现在可以重试"
            else:
                remaining_seconds = max(math.ceil(next_retry_at - now), 0) if next_retry_at > now else 0
                remaining_text = self._format_remaining_seconds(remaining_seconds)
            auto_retry = bool(classification["auto_retryable"] and not source_missing and not damaged)
            source_payload = getattr(history, "src_fileitem", None)
            source_path = self._history_value(history, ("src", "source", "source_path"))
            if not source_path:
                source_path = self._payload_value(source_payload, ("path", "file_path", "name"))
            target_path = self._history_value(history, ("dest", "target", "target_path"))
            title = self._history_value(history, ("title", "name", "media_name"))
            if not title:
                title = self._payload_value(source_payload, ("name", "file_name", "filename"))
            if not title:
                title = self._basename(source_path) or f"失败整理任务 #{history_id}"
            size = self._history_value(history, ("size", "file_size", "total_size"))
            if not size:
                size = self._payload_value(source_payload, ("size", "file_size", "filesize"))
            source_storage = self._history_value(history, ("src_storage", "source_storage", "storage"))
            if not source_storage:
                source_storage = self._payload_value(source_payload, ("storage", "storage_type"))

            tasks.append(
                {
                    "history_id": history_id,
                    "latest_history_id": history_id,
                    "group_key": group_key,
                    "group_key_short": short_group_key(group_key),
                    "history_ids": task_group["history_ids"],
                    "merged_history_ids": task_group["merged_history_ids"],
                    "merged_count": len(task_group["merged_history_ids"]),
                    "title": self._short_text(title, 120),
                    "source_storage": self._short_text(source_storage or "本地", 32),
                    "source_path": self._short_text(source_path or "源路径未知", 240),
                    "target_path": self._short_text(target_path or "目标路径未知", 240),
                    "size": self._to_int(size, 0, minimum=0, maximum=999999999999999),
                    "size_text": self._format_bytes(size),
                    "failed_time": self._format_history_time(history_failed_at(history)),
                    "failure_reason": sanitize_message(record["last_message"] or classification["message"]),
                    "error_code": classification["code"],
                    "retry_count": record["total_attempts"],
                    "total_attempts": record["total_attempts"],
                    "consecutive_failures": record["consecutive_failures"],
                    "next_retry_at": self._format_history_time(next_retry_at),
                    "next_retry_timestamp": next_retry_at,
                    "remaining_seconds": remaining_seconds,
                    "remaining_text": remaining_text,
                    "auto_retry": auto_retry,
                    "wait_reason": wait_reason,
                    "last_result": record["last_result"],
                    "manual_required": record["manual_required"],
                    "status": status,
                    "status_type": status_type,
                    "can_retry": can_retry,
                }
            )

        if state_changed:
            self._save_retry_state(retry_state)
        status_order = {"正在重试": 0, "可重试": 1, "冷却中": 2, "待人工确认": 3, "需人工处理": 4}
        tasks.sort(
            key=lambda item: (
                status_order.get(item["status"], 9),
                item["next_retry_timestamp"],
                item["history_id"],
            )
        )
        return tasks, ""

    @staticmethod
    def _history_value(history: Any, names: Tuple[str, ...]) -> Any:
        for name in names:
            value = getattr(history, name, None)
            if value not in (None, ""):
                return value
        return ""

    @staticmethod
    def _payload_value(payload: Any, names: Tuple[str, ...]) -> Any:
        if isinstance(payload, dict):
            for name in names:
                value = payload.get(name)
                if value not in (None, ""):
                    return value
        else:
            for name in names:
                value = getattr(payload, name, None)
                if value not in (None, ""):
                    return value
        return ""

    @staticmethod
    def _manual_wait_reason(
        classification: Dict[str, Any],
        *,
        source_missing: bool = False,
        damaged: bool = False,
    ) -> str:
        if source_missing:
            return "源文件不存在，需要人工处理"
        if damaged:
            return "源文件或历史记录存在问题，需要人工处理"
        reasons = {
            "auth_or_permission": "认证或权限错误，需要人工处理",
            "unknown": "错误类型无法识别，需要人工确认",
        }
        return reasons.get(
            str(classification.get("code") or "unknown"),
            "错误类型不允许自动重试，需要人工确认",
        )

    @staticmethod
    def _summarize_pending_tasks(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
        return {
            "total": len(tasks),
            "cooling": sum(task.get("status") == "冷却中" for task in tasks),
            "retryable": sum(task.get("status") == "可重试" for task in tasks),
            "manual_required": sum(task.get("status") == "待人工确认" for task in tasks),
            "needs_attention": sum(task.get("status") == "需人工处理" for task in tasks),
        }

    @staticmethod
    def _format_cooldown_remaining(seconds: Any) -> str:
        try:
            remaining = max(math.ceil(float(seconds or 0)), 0)
        except (TypeError, ValueError, OverflowError):
            remaining = 0
        if remaining:
            return f"剩余时间：{U115RiskControl._format_remaining_seconds(remaining)}"
        return "当前无风控冷却"

    @staticmethod
    def _format_bytes(value: Any) -> str:
        try:
            size = max(float(value or 0), 0)
        except (TypeError, ValueError):
            size = 0
        if not size:
            return "大小未知"
        units = ("B", "KB", "MB", "GB", "TB")
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        return f"{size:.2f} {units[index]}" if index else f"{int(size)} {units[index]}"

    @staticmethod
    def _format_history_time(value: Any) -> str:
        if value in (None, "", 0, "0"):
            return "时间未知"
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
            except (OverflowError, OSError, ValueError):
                return "时间未知"
        return str(value)[:32]

    @staticmethod
    def _format_remaining_seconds(value: Any) -> str:
        try:
            seconds = max(math.ceil(float(value or 0)), 0)
        except (TypeError, ValueError, OverflowError):
            seconds = 0
        if seconds <= 0:
            return "现在"

        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days} 天")
        if hours:
            parts.append(f"{hours} 小时")
        if minutes:
            parts.append(f"{minutes} 分")
        if seconds or not parts:
            parts.append(f"{seconds:02d} 秒" if parts else f"{seconds} 秒")
        return "约 " + " ".join(parts)

    def _build_pending_retry_section(
        self,
        tasks: List[Dict[str, Any]],
        error: str,
    ) -> Dict[str, Any]:
        summary = self._summarize_pending_tasks(tasks)
        content: List[Dict[str, Any]] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "title": f"待处理失败整理（{summary['total']}）",
                    "text": (
                        f"自动重试：{summary['cooling'] + summary['retryable']} 条（冷却中 {summary['cooling']}，可重试 {summary['retryable']}）\n"
                        f"待人工确认：{summary['manual_required']} 条；需人工处理：{summary['needs_attention']} 条。"
                    ),
                },
            }
        ]
        if error:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "tonal",
                        "density": "compact",
                        "text": error,
                    },
                }
            )
        elif not tasks:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "density": "compact",
                        "text": "当前没有待重试的失败整理任务。",
                    },
                }
            )
        else:
            content.append(
                {
                    "component": "VList",
                    "props": {
                        "density": "compact",
                        "lines": "two",
                        "class": "border rounded",
                    },
                    "content": [self._build_pending_retry_item(task) for task in tasks],
                }
            )
        return {
            "component": "VCol",
            "props": {"cols": 12},
            "content": content,
        }

    def _build_pending_retry_item(self, task: Dict[str, Any]) -> Dict[str, Any]:
        merged_text = f" · 已合并旧历史 {task.get('merged_count', 0)} 条" if task.get("merged_count") else ""
        metadata = (
            f"{task['source_storage']} · {task['size_text']} · 失败时间 {task['failed_time']} · "
            f"已重试 {task['retry_count']} 次{merged_text}"
        )
        path_text = f"源：{task['source_path']}\n目标：{task['target_path']}"
        status = task["status"]
        if status == "冷却中":
            status_text = (
                f"状态：冷却中\n自动重试：会执行\n距自动重试：{task.get('remaining_text') or '时间未知'}"
                f"（{task['next_retry_at']}）"
            )
        elif status == "可重试":
            status_text = "状态：可重试\n自动重试：会执行\n现在可以重试"
        elif status == "待人工确认":
            status_text = "状态：待人工确认\n自动重试：不会自动重试，需要人工确认\n可单条人工重试"
        else:
            status_text = "状态：需人工处理\n自动重试：不会执行\n需要先修复源文件或历史记录"
        status_text = f"{status_text} · 等待原因：{task.get('wait_reason') or '无'}"
        action_props = {
            "size": "small",
            "variant": "text",
            "color": "primary",
            "disabled": not task["can_retry"],
            "title": "立即重试",
        }
        return {
            "component": "VListItem",
            "props": {
                "class": "py-2",
                "lines": "three",
                "title": task["title"],
                "subtitle": f"{path_text}\n{metadata}\n{status_text}\n最近失败：{task['failure_reason']}",
            },
            "content": [
                {
                    "component": "VRow",
                    "props": {"align": "center", "dense": True},
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "class": "d-flex justify-end"},
                            "content": [
                                {
                                    "component": "VBtn",
                                    "props": action_props,
                                    "text": "立即重试",
                                    "events": {
                                        "click": {
                                            "api": f"plugin/{self.__class__.__name__}/retry",
                                            "method": "GET",
                                            "params": {"history_id": task["history_id"]},
                                        }
                                    },
                                }
                            ],
                        },
                    ],
                },
            ],
        }

    def _build_live_status(self) -> Dict[str, Any]:
        now = time.time()
        snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cooldown_remaining = self._get_current_cooldown_remaining()
        retry_remaining = 0
        scheduled_time = "无"
        if self._retry_scheduled_until > now:
            retry_remaining = max(math.ceil(self._retry_scheduled_until - now), 0)
            scheduled_time = datetime.fromtimestamp(self._retry_scheduled_until).strftime("%Y-%m-%d %H:%M:%S")

        if self._retry_in_progress:
            scheduled_text = "正在执行"
        elif retry_remaining > 0:
            scheduled_text = f"{scheduled_time}（{self._format_remaining_seconds(retry_remaining)}）"
        else:
            scheduled_text = "无"

        overall_status = self._build_overall_status(scheduled_text=scheduled_text)
        pending_tasks, pending_error = self._get_pending_retry_tasks()
        task_summary = self._summarize_pending_tasks(pending_tasks)
        scheduler = self._get_scheduler_snapshot()
        logs = self._event_logs[-self._max_event_log_count :]
        return {
            "snapshot_time": snapshot_time,
            "enabled": self._enabled,
            "overall": overall_status,
            "cooldown": {
                "reason": self._current_cooldown_reason,
                "remaining_seconds": cooldown_remaining,
                "remaining_text": self._format_cooldown_remaining(cooldown_remaining),
                "until": self._current_cooldown_until,
                "soft_limit_hits": self._soft_limit_hits,
                "hard_limit_hits": self._hard_limit_hits,
                "shared_until": self._shared_native_limit_until(),
                "guard_active": bool(self.__class__._native_guard_active),
                "fail_streak": int(self.__class__._native_fail_streak or 0),
                "probe_in_flight": bool(self.__class__._native_probe_in_flight),
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
                "scheduled_remaining_text": self._format_remaining_seconds(retry_remaining),
                "in_progress": self._retry_in_progress,
                "current_history_id": scheduler["current_history_id"],
                "current_group_key": scheduler["current_group_key"],
            },
            "pending_tasks": pending_tasks,
            "pending_task_count": len(pending_tasks),
            "task_summary": task_summary,
            "pending_tasks_error": pending_error,
            "scheduler": {
                "scheduler_enabled": scheduler["enabled"],
                "service_id": RETRY_SERVICE_ID,
                "scan_interval_seconds": scheduler["interval_seconds"],
                "scheduler_running": scheduler["running"],
                "executing": scheduler["executing"],
                "last_scan_at": scheduler["last_scan_at"],
                "next_scan_at": scheduler["next_scan_at"],
                "current_history_id": scheduler["current_history_id"],
                "current_group_key": scheduler["current_group_key"],
                "last_scan_result": scheduler["last_scan_result"],
                "duplicate_schedule_skipped": scheduler["duplicate_schedule_skipped"],
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
                    f"剩余时间：{self._format_remaining_seconds(cooldown_remaining)}\n"
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
            remaining = max(math.ceil(self._retry_scheduled_until - now), 0)
            return {
                "type": "info",
                "title": "当前状态：等待失败任务扫描",
                "text": (
                    f"已计划重试时间：{scheduled_text}\n"
                    f"剩余等待：{self._format_remaining_seconds(remaining)}\n"
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
            return max(math.ceil(self._current_cooldown_until - now), 0)
        if self._current_cooldown_reason != "未冷却" and self._current_cooldown_remaining > 0:
            return max(math.ceil(self._current_cooldown_remaining), 0)
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
