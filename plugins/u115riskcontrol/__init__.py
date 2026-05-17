import gc
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase


DEFAULT_CONFIG = {
    "enabled": True,
    "api_qps": 1,
    "download_qps": 1,
    "limit_sleep_seconds": 3600,
    "hourly_soft_limit": 70,
    "hourly_soft_cooldown": 900,
    "startup_log": True,
    "strict_mode": True,
}


class U115RiskControl(_PluginBase):
    plugin_name = "u115风控参数"
    plugin_desc = "为 MoviePilot 的 u115 存储注入可持久的限流参数，降低 115 Open API 风控概率。"
    plugin_icon = "U115RiskControl.jpg"
    plugin_version = "0.1.0"
    plugin_author = "wYw"
    author_url = ""
    plugin_config_prefix = "u115riskcontrol_"
    plugin_order = 98
    auth_level = 1

    _patch_lock = threading.Lock()
    _patched = False
    _original_u115_init = None

    def __init__(self):
        super().__init__()
        self._enabled = DEFAULT_CONFIG["enabled"]
        self._api_qps = DEFAULT_CONFIG["api_qps"]
        self._download_qps = DEFAULT_CONFIG["download_qps"]
        self._limit_sleep_seconds = DEFAULT_CONFIG["limit_sleep_seconds"]
        self._hourly_soft_limit = DEFAULT_CONFIG["hourly_soft_limit"]
        self._hourly_soft_cooldown = DEFAULT_CONFIG["hourly_soft_cooldown"]
        self._startup_log = DEFAULT_CONFIG["startup_log"]
        self._strict_mode = DEFAULT_CONFIG["strict_mode"]
        self._last_status = "未初始化"
        self._last_error = ""
        self._patched_instances = 0
        self._soft_limit_hits = 0

    def init_plugin(self, config: dict = None):
        cfg = self._normalize_config(config)
        self._enabled = cfg["enabled"]
        self._api_qps = cfg["api_qps"]
        self._download_qps = cfg["download_qps"]
        self._limit_sleep_seconds = cfg["limit_sleep_seconds"]
        self._hourly_soft_limit = cfg["hourly_soft_limit"]
        self._hourly_soft_cooldown = cfg["hourly_soft_cooldown"]
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
        config_suggest = (
            "建议先将普通接口 QPS 设为 1。若仍频繁触发“已达到当前访问上限”，"
            "再配合拉长整理节奏，避免在 1 小时内集中提交大量文件。"
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
                            "text": "此插件不会直接改 MoviePilot 核心文件，而是在启动时为 u115 存储注入限流参数。",
                        },
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "startup_log",
                                            "label": "启动时输出日志",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "strict_mode",
                                            "label": "严格兼容模式",
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "api_qps",
                                            "label": "普通接口 QPS",
                                            "type": "number",
                                            "min": 1,
                                            "max": 10,
                                            "hint": "u115 普通接口每秒请求上限，建议 1。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "download_qps",
                                            "label": "下载接口 QPS",
                                            "type": "number",
                                            "min": 1,
                                            "max": 10,
                                            "hint": "默认保持 1，一般不建议再调高。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "hourly_soft_limit",
                                            "label": "小时软阈值",
                                            "type": "number",
                                            "min": 0,
                                            "max": 500,
                                            "hint": "1 小时内请求达到此数量后，插件会主动进入冷却。设为 0 表示关闭。",
                                            "persistent-hint": True,
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "hourly_soft_cooldown",
                                            "label": "主动冷却秒数",
                                            "type": "number",
                                            "min": 0,
                                            "max": 86400,
                                            "hint": "达到小时软阈值后，主动暂停请求的秒数。设为 0 表示只记录不冷却。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "limit_sleep_seconds",
                                            "label": "115 访问上限冷却秒数",
                                            "type": "number",
                                            "min": 60,
                                            "max": 86400,
                                            "hint": "115 明确返回访问上限后，沿用本地冷却的秒数。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "text": (
                                f"{config_suggest} 当前默认软阈值为每小时 {DEFAULT_CONFIG['hourly_soft_limit']} 次，"
                                f"主动冷却 {DEFAULT_CONFIG['hourly_soft_cooldown']} 秒。"
                            ),
                        },
                    },
                ],
            }
        ]
        return form, dict(DEFAULT_CONFIG)

    def get_page(self) -> List[dict]:
        status_text = self._last_status
        if self._last_error:
            status_text = f"{status_text}；{self._last_error}"

        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "content": [
                                    {"component": "VCardTitle", "text": "当前状态"},
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {"component": "div", "text": f"启用状态：{'已启用' if self._enabled else '已禁用'}"},
                                            {"component": "div", "text": f"补丁状态：{status_text}"},
                                            {"component": "div", "text": f"已处理实例数：{self._patched_instances}"},
                                            {"component": "div", "text": f"小时软阈值命中次数：{self._soft_limit_hits}"},
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
                                "content": [
                                    {"component": "VCardTitle", "text": "当前参数"},
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {"component": "div", "text": f"普通接口 QPS：{self._api_qps}"},
                                            {"component": "div", "text": f"下载接口 QPS：{self._download_qps}"},
                                            {"component": "div", "text": f"风控冷却秒数：{self._limit_sleep_seconds}"},
                                            {"component": "div", "text": f"小时软阈值：{self._hourly_soft_limit}"},
                                            {"component": "div", "text": f"主动冷却秒数：{self._hourly_soft_cooldown}"},
                                        ],
                                    },
                                ],
                            }
                        ],
                    },
                ],
            }
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

            api_qps = self._api_qps
            download_qps = self._download_qps
            limit_sleep_seconds = self._limit_sleep_seconds
            hourly_soft_limit = self._hourly_soft_limit
            hourly_soft_cooldown = self._hourly_soft_cooldown
            strict_mode = self._strict_mode
            startup_log = self._startup_log
            original_request_api = getattr(U115Pan, "_u115riskcontrol_original_request_api", None)
            if original_request_api is None:
                original_request_api = U115Pan._request_api
                setattr(U115Pan, "_u115riskcontrol_original_request_api", original_request_api)

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
                    endpoint=endpoint,
                    hourly_soft_limit=hourly_soft_limit,
                    hourly_soft_cooldown=hourly_soft_cooldown,
                )
                return original_request_api(instance, *args, **kwargs)

            patched_init._u115riskcontrol_patched = True  # type: ignore[attr-defined]
            patched_request_api._u115riskcontrol_patched = True  # type: ignore[attr-defined]
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
        endpoint: Any,
        hourly_soft_limit: int,
        hourly_soft_cooldown: int,
    ) -> None:
        if not hourly_soft_limit:
            return

        now = time.time()
        timestamps = getattr(instance, "_u115riskcontrol_hour_timestamps", None)
        if timestamps is None:
            timestamps = deque()
            instance._u115riskcontrol_hour_timestamps = timestamps

        limit_until = float(getattr(instance, "_u115riskcontrol_soft_limit_until", 0.0) or 0.0)
        if limit_until > now:
            remaining = limit_until - now
            if remaining > 0:
                logger.warning(
                    "[U115RiskControl] hourly soft cooldown active: "
                    f"endpoint={endpoint}, remaining={int(remaining)}s"
                )
                time.sleep(remaining)
                now = time.time()

        while timestamps and now - timestamps[0] >= 3600:
            timestamps.popleft()

        if len(timestamps) >= hourly_soft_limit:
            self._soft_limit_hits += 1
            next_until = now + max(hourly_soft_cooldown, 0)
            instance._u115riskcontrol_soft_limit_until = next_until
            logger.warning(
                "[U115RiskControl] hourly soft limit reached before request: "
                f"endpoint={endpoint}, limit={hourly_soft_limit}, "
                f"cooldown={hourly_soft_cooldown}s, recent_calls={len(timestamps)}"
            )
            if hourly_soft_cooldown > 0:
                time.sleep(hourly_soft_cooldown)
                now = time.time()
                while timestamps and now - timestamps[0] >= 3600:
                    timestamps.popleft()

        timestamps.append(now)

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
