from __future__ import annotations

from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import asyncio
import inspect

from app.core.event import eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class u115uploadmonitor(_PluginBase):
    plugin_name = "115上传监控-魔改版"
    plugin_desc = "实时监听 115 上传开始/成功/失败事件，支持过滤、去重和统计。"
    plugin_icon = "upload.png"
    plugin_version = "1.3.0"
    plugin_author = "污妖王"
    author_url = ""
    plugin_config_prefix = "u115uploadmonitor_"
    plugin_order = 100
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._config: Dict[str, Any] = {
            "enabled": True,
            "notify_upload_start": True,
            "notify_upload_success": True,
            "notify_upload_failed": True,
            "send_test_notification": False,
            "compat_listen_plugin_triggered": True,
            "compat_patch_u115_emit_events": "auto",
            "debug_log_event_payload": False,
            "include_paths": "",
            "exclude_paths": "",
            "include_exts": "",
            "exclude_exts": "",
            "dedup_seconds": 30,
            "template_upload_start": "{filename} 开始上传 {time}",
            "template_upload_success": "{filename} {upload_type}成功 {time}",
            "template_upload_failed": "{filename} 上传失败: {error} {time}",
            "template_title_upload_start": "115上传开始",
            "template_title_upload_success": "115上传成功",
            "template_title_upload_failed": "115上传失败",
        }
        self._filters: Dict[str, Set[str]] = {
            "include_paths": set(),
            "exclude_paths": set(),
            "include_exts": set(),
            "exclude_exts": set(),
        }
        self._seen: Dict[str, float] = {}
        self._stats: Dict[str, Any] = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "start": 0,
            "success": 0,
            "failed": 0,
            "recent": [],
        }

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)

    @staticmethod
    def _to_set(value: Any, ext: bool = False) -> Set[str]:
        if value is None:
            return set()
        text = str(value).replace("\n", ",").replace(";", ",")
        result = set()
        for part in text.split(","):
            item = part.strip().lower()
            if not item:
                continue
            if ext:
                item = item.lstrip(".")
            result.add(item)
        return result

    @staticmethod
    def _safe_int(value: Any, default: int = 30, minimum: int = 0, maximum: int = 600) -> int:
        try:
            num = int(value)
        except Exception:
            num = default
        if num < minimum:
            return minimum
        if num > maximum:
            return maximum
        return num

    @staticmethod
    def _default_templates() -> Dict[str, str]:
        return {
            "template_upload_start": "{filename} 开始上传 {time}",
            "template_upload_success": "{filename} {upload_type}成功 {time}",
            "template_upload_failed": "{filename} 上传失败: {error} {time}",
            "template_title_upload_start": "115上传开始",
            "template_title_upload_success": "115上传成功",
            "template_title_upload_failed": "115上传失败",
        }

    def _normalize_config(self):
        for key in [
            "enabled", "notify_upload_start", "notify_upload_success", "notify_upload_failed",
            "send_test_notification", "compat_listen_plugin_triggered", "debug_log_event_payload",
        ]:
            self._config[key] = self._to_bool(self._config.get(key))

        patch_mode = self._config.get("compat_patch_u115_emit_events", "auto")
        if isinstance(patch_mode, str):
            patch_mode = patch_mode.strip().lower()
            self._config["compat_patch_u115_emit_events"] = True if patch_mode == "true" else False if patch_mode == "false" else "auto"
        elif isinstance(patch_mode, bool):
            self._config["compat_patch_u115_emit_events"] = patch_mode
        else:
            self._config["compat_patch_u115_emit_events"] = "auto"

        self._config["dedup_seconds"] = self._safe_int(self._config.get("dedup_seconds", 30))

        defaults = self._default_templates()
        for template_key, template_default in defaults.items():
            value = self._config.get(template_key)
            if value is None:
                self._config[template_key] = template_default
            else:
                text = str(value).strip()
                self._config[template_key] = text if text else template_default

        self._filters["include_paths"] = self._to_set(self._config.get("include_paths", ""))
        self._filters["exclude_paths"] = self._to_set(self._config.get("exclude_paths", ""))
        self._filters["include_exts"] = self._to_set(self._config.get("include_exts", ""), ext=True)
        self._filters["exclude_exts"] = self._to_set(self._config.get("exclude_exts", ""), ext=True)

    def _load_stats(self):
        try:
            saved = self.get_data("stats")
            if isinstance(saved, dict):
                self._stats.update(saved)
        except Exception as err:
            logger.debug(f"[115上传监控] 读取统计失败: {err}")
        self._reset_daily()

    def _save_stats(self):
        try:
            self.save_data("stats", self._stats)
        except Exception as err:
            logger.debug(f"[115上传监控] 保存统计失败: {err}")

    def _reset_daily(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._stats.get("date") != today:
            self._stats.update({"date": today, "start": 0, "success": 0, "failed": 0})

    def init_plugin(self, config: dict = None):
        if isinstance(config, dict):
            self._config.update(config)

        self._normalize_config()
        self._load_stats()

        if self._config.get("send_test_notification"):
            self._send_test_notification()
            self._config["send_test_notification"] = False
            self.update_config(self._config)

        self._unregister_events()
        if self.get_state():
            self._register_events()
            self._maybe_patch_u115_emitter()

    def _send_test_notification(self):
        data = {
            "filename": "demo_video.mkv",
            "file_path": "/downloads/demo_video.mkv",
            "target_path": "/115/电影/demo_video.mkv",
            "upload_type": "上传",
            "error": "网络中断",
        }
        if self._config.get("notify_upload_start"):
            self._handle_upload_start(data)
        if self._config.get("notify_upload_success"):
            self._handle_upload_success(data)
        if self._config.get("notify_upload_failed"):
            self._handle_upload_failed(data)

    def _register_events(self):
        try:
            eventmanager.add_event_listener(EventType.PluginAction, self.on_plugin_action)
            if self._to_bool(self._config.get("compat_listen_plugin_triggered", True)):
                plugin_triggered = getattr(EventType, "PluginTriggered", None)
                if plugin_triggered is not None:
                    eventmanager.add_event_listener(plugin_triggered, self.on_plugin_action)
        except Exception as err:
            logger.error(f"[115上传监控] 注册事件失败: {err}")

    def _unregister_events(self):
        try:
            eventmanager.remove_event_listener(EventType.PluginAction, self.on_plugin_action)
        except Exception:
            pass
        try:
            plugin_triggered = getattr(EventType, "PluginTriggered", None)
            if plugin_triggered is not None:
                eventmanager.remove_event_listener(plugin_triggered, self.on_plugin_action)
        except Exception:
            pass

    @staticmethod
    def _event_data(event: Any) -> Dict[str, Any]:
        data = getattr(event, "event_data", None)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _filename(data: Dict[str, Any]) -> str:
        name = data.get("filename")
        if name:
            return str(name)
        for key in ("target_path", "file_path", "path"):
            value = data.get(key)
            if value:
                return Path(str(value)).name or "未知文件"
        return "未知文件"

    @staticmethod
    def _target(data: Dict[str, Any]) -> str:
        return str(data.get("target_path") or data.get("file_path") or data.get("path") or "")

    def _match_filter(self, data: Dict[str, Any]) -> bool:
        target = self._target(data).lower()
        include_paths = self._filters["include_paths"]
        exclude_paths = self._filters["exclude_paths"]
        include_exts = self._filters["include_exts"]
        exclude_exts = self._filters["exclude_exts"]

        if include_paths and not any(rule in target for rule in include_paths):
            return False
        if exclude_paths and any(rule in target for rule in exclude_paths):
            return False

        ext = Path(self._filename(data)).suffix.lower().lstrip(".")
        if include_exts and ext not in include_exts:
            return False
        if exclude_exts and ext in exclude_exts:
            return False
        return True

    def _is_duplicated(self, action: str, data: Dict[str, Any]) -> bool:
        ttl = self._safe_int(self._config.get("dedup_seconds", 30))
        if ttl <= 0:
            return False

        now = datetime.now().timestamp()
        key = f"{action}|{self._filename(data)}|{self._target(data)}"

        for cache_key, ts in list(self._seen.items()):
            if now - ts > ttl * 2:
                self._seen.pop(cache_key, None)

        hit = self._seen.get(key)
        if hit is not None and now - hit < ttl:
            return True

        self._seen[key] = now
        return False

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _inc_stat(self, key: str):
        self._reset_daily()
        if key in {"start", "success", "failed"}:
            self._stats[key] = int(self._stats.get(key, 0)) + 1

    def _add_recent(self, action: str, data: Dict[str, Any], message: str):
        recent = self._stats.get("recent")
        if not isinstance(recent, list):
            recent = []
        recent.insert(0, {
            "time": self._now(),
            "action": action,
            "filename": self._filename(data),
            "target_path": self._target(data),
            "message": message,
        })
        self._stats["recent"] = recent[:30]

    def on_plugin_action(self, event):
        try:
            if not self.get_state():
                return

            data = self._event_data(event)
            action = str(data.get("action") or data.get("event") or data.get("type") or "").strip().lower()
            if self._to_bool(self._config.get("debug_log_event_payload")):
                logger.info(f"[115上传监控] action={action}, payload={data}")

            if action in {"115_upload_start", "115_upload_begin"}:
                if self._config.get("notify_upload_start"):
                    self._handle_upload_start(data)
            elif action in {"115_upload_success", "115_upload_complete", "115_upload_completed"}:
                if self._config.get("notify_upload_success"):
                    self._handle_upload_success(data)
            elif action in {"115_upload_failed", "115_upload_fail", "115_upload_error"}:
                if self._config.get("notify_upload_failed"):
                    self._handle_upload_failed(data)
        except Exception as err:
            logger.error(f"[115上传监控] 处理事件失败: {err}")

    def _maybe_patch_u115_emitter(self):
        mode = self._config.get("compat_patch_u115_emit_events", "auto")
        if mode is False:
            return

        try:
            from app.modules.filemanager.storages.u115 import U115Pan  # type: ignore
        except Exception:
            return

        upload_func = getattr(U115Pan, "upload", None)
        if not upload_func:
            return
        if getattr(upload_func, "__u115uploadmonitor_patched__", False):
            return

        if mode == "auto":
            try:
                source = inspect.getsource(upload_func)
            except Exception:
                source = ""
            if "115_upload_start" in source and "115_upload_success" in source:
                return

        def _extract(args, kwargs):
            target_dir = kwargs.get("target_dir") if isinstance(kwargs, dict) else None
            local_path = kwargs.get("local_path") if isinstance(kwargs, dict) else None
            new_name = kwargs.get("new_name") if isinstance(kwargs, dict) else None
            if len(args) >= 1 and target_dir is None:
                target_dir = args[0]
            if len(args) >= 2 and local_path is None:
                local_path = args[1]
            if len(args) >= 3 and new_name is None:
                new_name = args[2]

            target_dir_path = getattr(target_dir, "path", None)
            filename = new_name or getattr(local_path, "name", None) or (str(local_path) if local_path else "")
            target_path = f"{str(target_dir_path).rstrip('/')}/{filename}" if target_dir_path and filename else ""
            return str(filename), local_path, target_path

        def _emit(action: str, filename: str, local_path: Any, target_path: str, upload_type: str = "", error: str = ""):
            payload = {
                "action": action,
                "filename": filename,
                "file_path": str(local_path) if local_path is not None else "",
                "target_path": target_path,
            }
            if upload_type:
                payload["upload_type"] = upload_type
            if error:
                payload["error"] = error
            try:
                eventmanager.send_event(EventType.PluginAction, payload)
            except Exception:
                pass

        if asyncio.iscoroutinefunction(upload_func):
            @wraps(upload_func)
            async def patched(self_obj, *args, **kwargs):
                filename, local_path, target_path = _extract(args, kwargs)
                if filename:
                    _emit("115_upload_start", filename, local_path, target_path)
                try:
                    result = await upload_func(self_obj, *args, **kwargs)
                except Exception as err:
                    if filename:
                        _emit("115_upload_failed", filename, local_path, target_path, error=str(err))
                    raise
                if filename and result:
                    _emit("115_upload_success", filename, local_path, target_path, upload_type="上传")
                return result
        else:
            @wraps(upload_func)
            def patched(self_obj, *args, **kwargs):
                filename, local_path, target_path = _extract(args, kwargs)
                if filename:
                    _emit("115_upload_start", filename, local_path, target_path)
                try:
                    result = upload_func(self_obj, *args, **kwargs)
                except Exception as err:
                    if filename:
                        _emit("115_upload_failed", filename, local_path, target_path, error=str(err))
                    raise
                if filename and result:
                    _emit("115_upload_success", filename, local_path, target_path, upload_type="上传")
                return result

        setattr(patched, "__u115uploadmonitor_patched__", True)
        setattr(U115Pan, "upload", patched)

    def _notify(self, title: str, text: str):
        try:
            safe_title = (title or "115上传监控").strip() or "115上传监控"
            self.post_message(mtype=NotificationType.Other, title=safe_title, text=text)
        except Exception as err:
            logger.error(f"[115上传监控] 推送失败: {err}")

    def _build_template_context(self, data: Dict[str, Any], action: str) -> Dict[str, str]:
        filename = self._filename(data)
        target_path = self._target(data)
        file_path = str(data.get("file_path") or "")
        upload_type = str(data.get("upload_type") or "上传")
        error = str(data.get("error") or data.get("message") or "未知错误")
        now = self._now()
        return {
            "action": action,
            "filename": filename,
            "target_path": target_path,
            "file_path": file_path,
            "upload_type": upload_type,
            "error": error,
            "time": now,
        }

    def _render_template(self, template_key: str, data: Dict[str, Any], action: str) -> str:
        template = str(self._config.get(template_key) or self._default_templates().get(template_key, ""))
        context = self._build_template_context(data, action)
        safe_context = {k: ("" if v is None else str(v)) for k, v in context.items()}
        try:
            text = template.format_map(safe_context)
        except Exception as err:
            logger.warning(f"[115上传监控] 模板渲染失败({template_key}): {err}，将使用默认模板")
            fallback = self._default_templates().get(template_key, "{filename} {time}")
            text = fallback.format_map(safe_context)
        return text.strip() or self._default_templates().get(template_key, "通知")

    def _handle_upload_start(self, data: Dict[str, Any]):
        if not self._match_filter(data) or self._is_duplicated("start", data):
            return
        title = self._render_template("template_title_upload_start", data, "start")
        message = self._render_template("template_upload_start", data, "start")
        self._notify(title, message)
        self._inc_stat("start")
        self._add_recent("start", data, message)
        self._save_stats()

    def _handle_upload_success(self, data: Dict[str, Any]):
        if not self._match_filter(data) or self._is_duplicated("success", data):
            return
        title = self._render_template("template_title_upload_success", data, "success")
        message = self._render_template("template_upload_success", data, "success")
        self._notify(title, message)
        self._inc_stat("success")
        self._add_recent("success", data, message)
        self._save_stats()

    def _handle_upload_failed(self, data: Dict[str, Any]):
        if not self._match_filter(data) or self._is_duplicated("failed", data):
            return
        title = self._render_template("template_title_upload_failed", data, "failed")
        message = self._render_template("template_upload_failed", data, "failed")
        self._notify(title, message)
        self._inc_stat("failed")
        self._add_recent("failed", data, message)
        self._save_stats()

    def get_state(self) -> bool:
        return self._to_bool(self._config.get("enabled", False))

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    # ── 基础设置 ──
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "class": "mb-0", "title": "📡 基础设置"}},
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 6, "sm": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件", "color": "primary", "hide-details": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 6, "sm": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify_upload_start", "label": "推送上传开始", "color": "info", "hide-details": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 6, "sm": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify_upload_success", "label": "推送上传成功", "color": "success", "hide-details": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 6, "sm": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify_upload_failed", "label": "推送上传失败", "color": "error", "hide-details": True}},
                            ]},
                        ],
                    },
                    {"component": "VDivider", "props": {"class": "my-4"}},
                    # ── 过滤规则 ──
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "class": "mb-0", "title": "🔍 过滤规则"}},
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "include_paths", "label": "仅包含路径", "placeholder": "/115/电影,/115/剧集", "hint": "逗号分隔，留空表示不限制", "persistent-hint": True, "clearable": True, "prepend-inner-icon": "mdi-folder-check"}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "exclude_paths", "label": "排除路径", "placeholder": "/115/临时", "hint": "逗号分隔，匹配的路径将被忽略", "persistent-hint": True, "clearable": True, "prepend-inner-icon": "mdi-folder-remove"}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "include_exts", "label": "仅包含扩展名", "placeholder": "mkv,mp4", "hint": "逗号分隔，留空表示不限制", "persistent-hint": True, "clearable": True, "prepend-inner-icon": "mdi-file-check"}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "exclude_exts", "label": "排除扩展名", "placeholder": "tmp,part", "hint": "逗号分隔，匹配的扩展名将被忽略", "persistent-hint": True, "clearable": True, "prepend-inner-icon": "mdi-file-remove"}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 4}, "content": [
                                {"component": "VTextField", "props": {"model": "dedup_seconds", "label": "去重窗口（秒）", "type": "number", "min": 0, "max": 600, "hint": "0~600，相同事件在此时间内不重复推送", "persistent-hint": True, "clearable": True, "prepend-inner-icon": "mdi-timer-outline"}},
                            ]},
                        ],
                    },
                    {"component": "VDivider", "props": {"class": "my-4"}},
                    # ── 消息模板 ──
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "class": "mb-0", "title": "✉️ 消息模板", "text": "通用变量：{filename} {target_path} {file_path} {time}　｜　成功额外：{upload_type}　｜　失败额外：{error}"}},
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "template_title_upload_start", "label": "📤 开始 - 标题模板", "clearable": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextarea", "props": {"model": "template_upload_start", "label": "📤 开始 - 正文模板", "rows": 2, "auto-grow": True, "clearable": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "template_title_upload_success", "label": "✅ 成功 - 标题模板", "clearable": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextarea", "props": {"model": "template_upload_success", "label": "✅ 成功 - 正文模板", "rows": 2, "auto-grow": True, "clearable": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "template_title_upload_failed", "label": "❌ 失败 - 标题模板", "clearable": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "sm": 6}, "content": [
                                {"component": "VTextarea", "props": {"model": "template_upload_failed", "label": "❌ 失败 - 正文模板", "rows": 2, "auto-grow": True, "clearable": True}},
                            ]},
                        ],
                    },
                    {"component": "VDivider", "props": {"class": "my-4"}},
                    # ── 高级选项 ──
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "warning", "variant": "tonal", "density": "compact", "class": "mb-0", "title": "⚙️ 高级选项"}},
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 6, "sm": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "debug_log_event_payload", "label": "调试日志", "color": "warning", "hide-details": True}},
                            ]},
                            {"component": "VCol", "props": {"cols": 6, "sm": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "send_test_notification", "label": "保存后发送测试通知", "color": "info", "hide-details": True}},
                            ]},
                        ],
                    },
                ],
            }
        ], self._config

    def get_page(self) -> Optional[List[dict]]:
        self._reset_daily()
        today = self._stats.get("date", "")
        recent = self._stats.get("recent") or []
        action_map = {"start": "开始上传", "success": "上传成功", "failed": "上传失败"}
        lines = []
        for item in recent[:15]:
            act = action_map.get(item.get("action", ""), item.get("action", ""))
            lines.append(f"[{item.get('time', '')}] {act}: {item.get('filename', '')}  →  {item.get('target_path', '')}")
        text = "\n".join(lines) or "暂无事件记录"
        return [
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "title": f"📊 今日统计（{today}）"}},
                    ]},
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12, "sm": 4}, "content": [
                        {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "title": f"📤 今日开始", "text": str(self._stats.get('start', 0))}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "sm": 4}, "content": [
                        {"component": "VAlert", "props": {"type": "success", "variant": "tonal", "title": f"✅ 今日成功", "text": str(self._stats.get('success', 0))}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "sm": 4}, "content": [
                        {"component": "VAlert", "props": {"type": "error", "variant": "tonal", "title": f"❌ 今日失败", "text": str(self._stats.get('failed', 0))}},
                    ]},
                ],
            },
            {
                "component": "VRow",
                "props": {"class": "mt-2"},
                "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VTextarea", "props": {"label": "📋 最近事件", "modelValue": text, "readonly": True, "rows": 12, "auto-grow": True}},
                    ]},
                ],
            },
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        self._config["enabled"] = False
        self._unregister_events()


export = u115uploadmonitor
__all__ = ["u115uploadmonitor"]
