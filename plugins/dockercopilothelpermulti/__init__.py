import json
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import jwt
import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class DockerCopilotHelperMulti(_PluginBase):
    plugin_name = "DC助手多源版"
    plugin_desc = "配合 DockerCopilot 管理多个 DC 源，支持跨源更新通知、自动更新、镜像清理和自动备份"
    plugin_icon = "Docker_Copilot.png"
    plugin_version = "1.0.12"
    plugin_author = "wYw"
    author_url = ""
    plugin_config_prefix = "dockercopilothelpermulti_"
    plugin_order = 15
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _update_cron = None
    _updatable_list: List[str] = []
    _updatable_notify = False
    _schedule_report = False
    _auto_update_cron = None
    _auto_update_list: List[str] = []
    _auto_update_notify = False
    _delete_images = False
    _backup_cron = None
    _backups_notify = False
    _backup_sources: List[str] = []
    _intervallimit = 60
    _interval = 10
    _sources: List[Dict[str, Any]] = []
    _sources_text = ""
    _task_logs: List[Dict[str, Any]] = []
    _progress_tasks: List[Dict[str, Any]] = []
    _pending_update_keys = set()
    _progress_lock = threading.RLock()
    _update_submission_lock = threading.RLock()
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        self.stop_service()
        if not config:
            return

        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._update_cron = config.get("updatecron")
        self._updatable_list = self._as_list(config.get("updatablelist"))
        self._updatable_notify = bool(config.get("updatablenotify"))
        self._auto_update_cron = config.get("autoupdatecron")
        self._auto_update_list = self._as_list(config.get("autoupdatelist"))
        self._auto_update_notify = bool(config.get("autoupdatenotify"))
        self._schedule_report = bool(config.get("schedulereport"))
        self._delete_images = bool(config.get("deleteimages"))
        self._backup_cron = config.get("backupcron")
        self._backups_notify = bool(config.get("backupsnotify"))
        self._backup_sources = self._as_list(config.get("backup_sources"))
        self._intervallimit = max(60, int(config.get("intervallimit") or 60))
        self._interval = config.get("interval") or 10
        self._sources = self._load_sources(config)
        self._sources_text = json.dumps(self._sources, ensure_ascii=False, indent=2) if self._sources else ""
        saved_tasks = config.get("progress_tasks")
        if isinstance(saved_tasks, list):
            self._progress_tasks = [item for item in saved_tasks if isinstance(item, dict)][:50]
        self.__update_config()

        if not self._sources:
            logger.error("DC助手多源版服务结束：未配置可用 DockerCopilot 源")
            return False

        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._onlyonce:
                logger.info("DC助手多源版服务启动：立即运行一次")
                self._add_once_jobs()
                self._onlyonce = False
                self.__update_config()

            self._add_cron_jobs()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vue", "dist/assets"

    def __update_config(self):
        config = {
            "onlyonce": self._onlyonce,
            "enabled": self._enabled,
            "updatecron": self._update_cron,
            "updatablelist": self._updatable_list,
            "updatablenotify": self._updatable_notify,
            "autoupdatecron": self._auto_update_cron,
            "autoupdatelist": self._auto_update_list,
            "autoupdatenotify": self._auto_update_notify,
            "schedulereport": self._schedule_report,
            "deleteimages": self._delete_images,
            "backupcron": self._backup_cron,
            "backupsnotify": self._backups_notify,
            "backup_sources": self._backup_sources,
            "sources_text": self._sources_text,
            "sources": self._sources,
            "intervallimit": self._intervallimit,
            "interval": self._interval,
            "progress_tasks": self._progress_task_snapshot()
        }
        self.update_config(config)

    def _add_once_jobs(self):
        timezone = pytz.timezone(settings.TZ)
        if self._backup_cron:
            self._scheduler.add_job(self.backup, "date",
                                    run_date=datetime.now(tz=timezone) + timedelta(seconds=3),
                                    name="DC助手多源版-备份")
        if self._update_cron:
            self._scheduler.add_job(self.updatable, "date",
                                    run_date=datetime.now(tz=timezone) + timedelta(seconds=6),
                                    name="DC助手多源版-更新通知")
        if self._auto_update_cron:
            self._scheduler.add_job(self.auto_update, "date",
                                    run_date=datetime.now(tz=timezone) + timedelta(seconds=10),
                                    name="DC助手多源版-自动更新")

    def _add_cron_jobs(self):
        jobs = [
            (self._backup_cron, self.backup, "DC助手多源版-备份"),
            (self._update_cron, self.updatable, "DC助手多源版-更新通知"),
            (self._auto_update_cron, self.auto_update, "DC助手多源版-自动更新"),
        ]
        for cron, func, name in jobs:
            if not cron:
                continue
            try:
                self._scheduler.add_job(func=func, trigger=CronTrigger.from_crontab(cron), name=name)
            except Exception as err:
                logger.error(f"{name} 定时任务配置错误：{err}")
                self.systemmessage.put(f"{name} 定时任务配置错误：{err}")

    @staticmethod
    def _as_list(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return [str(value)]

    def _apply_config_snapshot(self, config: Dict[str, Any]):
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._update_cron = config.get("updatecron")
        self._updatable_list = self._as_list(config.get("updatablelist"))
        self._updatable_notify = bool(config.get("updatablenotify"))
        self._auto_update_cron = config.get("autoupdatecron")
        self._auto_update_list = self._as_list(config.get("autoupdatelist"))
        self._auto_update_notify = bool(config.get("autoupdatenotify"))
        self._schedule_report = bool(config.get("schedulereport"))
        self._delete_images = bool(config.get("deleteimages"))
        self._backup_cron = config.get("backupcron")
        self._backups_notify = bool(config.get("backupsnotify"))
        self._backup_sources = self._as_list(config.get("backup_sources"))
        self._intervallimit = max(60, int(config.get("intervallimit") or 60))
        self._interval = config.get("interval") or 10
        self._sources = self._load_sources(config) if config else []
        self._sources_text = json.dumps(self._sources, ensure_ascii=False, indent=2) if self._sources else ""
        saved_tasks = config.get("progress_tasks") if config else None
        if isinstance(saved_tasks, list):
            self._progress_tasks = [item for item in saved_tasks if isinstance(item, dict)][:50]

    def _load_sources(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        sources = self._parse_source_slots(config)
        if not sources:
            sources = self._parse_sources(config.get("sources_text") or config.get("sources"))
        if not sources and config.get("host") and config.get("secretKey"):
            sources = [{
                "id": "default",
                "name": "默认源",
                "host": config.get("host"),
                "secretKey": config.get("secretKey"),
                "enabled": True,
            }]
        normalized = []
        seen = set()
        for index, source in enumerate(sources):
            source_id = self._safe_source_id(source.get("id") or source.get("name") or f"dc_{index + 1}")
            if source_id in seen:
                logger.warning(f"DC助手多源版忽略重复源ID：{source_id}")
                continue
            host = str(source.get("host") or "").rstrip("/")
            secret_key = str(source.get("secretKey") or source.get("secret_key") or "")
            if not host or not secret_key:
                logger.warning(f"DC助手多源版忽略配置不完整的源：{source.get('name') or source_id}")
                continue
            seen.add(source_id)
            normalized.append({
                "id": source_id,
                "name": source.get("name") or source_id,
                "host": host,
                "secretKey": secret_key,
                "enabled": source.get("enabled", True) is not False,
            })
        return normalized

    def _parse_source_slots(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        sources = []
        for index in range(1, 101):
            prefix = f"source{index}"
            host = str(config.get(f"{prefix}_host") or "").strip().rstrip("/")
            secret_key = str(config.get(f"{prefix}_secretKey") or "").strip()
            name = str(config.get(f"{prefix}_name") or "").strip()
            source_id = str(config.get(f"{prefix}_id") or "").strip()
            if not host and not secret_key:
                continue
            sources.append({
                "id": source_id or name or f"dc_{index}",
                "name": name or source_id or f"DC源{index}",
                "host": host,
                "secretKey": secret_key,
                "enabled": config.get(f"{prefix}_enabled", True) is not False
            })
        return sources

    @staticmethod
    def _parse_sources(value: Any) -> List[Dict[str, Any]]:
        if not value:
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception as err:
                logger.error(f"DC助手多源版 sources_text JSON 解析失败：{err}")
                return []
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, dict):
                return [parsed]
        return []

    @staticmethod
    def _safe_source_id(value: str) -> str:
        source_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value).strip()).strip("_").lower()
        return source_id or "dc"

    def _enabled_sources(self) -> List[Dict[str, Any]]:
        return [source for source in self._sources if source.get("enabled", True)]

    @staticmethod
    def _container_key(source: Dict[str, Any], container_name: str) -> str:
        return f"{source['id']}::{container_name}"

    @staticmethod
    def _split_container_key(value: str) -> Tuple[str, str]:
        if "::" not in value:
            return "", value
        source_id, container_name = value.split("::", 1)
        return source_id, container_name

    def _source_by_id(self, source_id: str) -> Optional[Dict[str, Any]]:
        for source in self._enabled_sources():
            if source["id"] == source_id:
                return source
        return None

    def get_jwt(self, source: Dict[str, Any]) -> str:
        payload = {
            "exp": int(time.time()) + 28 * 24 * 60 * 60,
            "iat": int(time.time())
        }
        encoded_jwt = jwt.encode(payload, source["secretKey"], algorithm="HS256")
        return "Bearer " + encoded_jwt

    def _get_json(self, source: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
        url = f"{source['host']}{path}"
        result = RequestUtils(headers={"Authorization": self.get_jwt(source)}).get_res(url)
        return result.json() if result else None

    def _post_json(self, source: Dict[str, Any], path: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = f"{source['host']}{path}"
        result = RequestUtils(headers={"Authorization": self.get_jwt(source)}).post_res(url, data)
        return result.json() if result else None

    def _delete_json(self, source: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
        url = f"{source['host']}{path}"
        result = self.delete_res(url, {"Authorization": self.get_jwt(source)})
        return result.json() if result else None

    @staticmethod
    def _is_success(data: Optional[Dict[str, Any]], accepted_codes=(0, 200)) -> bool:
        return isinstance(data, dict) and data.get("code") in accepted_codes

    def _get_docker_list_status(self, source: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], str]:
        try:
            data = self._get_json(source, "/api/containers")
            if self._is_success(data):
                containers = data.get("data") or []
                if not isinstance(containers, list):
                    return False, [], "容器列表格式异常"
                return True, containers, ""
            reason = self._format_dc_error(data)
            logger.error(f"DC助手多源版[{source['name']}] 获取容器列表异常：{reason}")
            return False, [], reason
        except Exception as err:
            reason = self._safe_reason(err)
            logger.error(f"DC助手多源版[{source['name']}] 请求容器列表网络异常：{reason}")
            return False, [], reason

    def get_docker_list(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        _available, containers, _reason = self._get_docker_list_status(source)
        return containers

    def get_all_docker_list(self) -> List[Dict[str, Any]]:
        containers = []
        for source in self._enabled_sources():
            for container in self.get_docker_list(source):
                item = dict(container)
                item["_source"] = source
                item["_source_id"] = source["id"]
                item["_source_name"] = source["name"]
                item["_key"] = self._container_key(source, item.get("name", ""))
                containers.append(item)
        return containers

    def get_images_list(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            data = self._get_json(source, "/api/images")
            if self._is_success(data, accepted_codes=(200,)):
                return data.get("data") or []
            logger.error(f"DC助手多源版[{source['name']}] 获取镜像列表异常：{self._safe_reason(data)}")
        except Exception as err:
            logger.error(f"DC助手多源版[{source['name']}] 请求镜像列表网络异常：{self._safe_reason(err)}")
        return []

    def remove_image(self, source: Dict[str, Any], sha: str, image: str = None,
                     container_name: str = "unknown", reason: str = "unused") -> bool:
        image_name = image or sha or "unknown"
        try:
            data = self._delete_json(source, f"/api/image/{sha}?force=false")
            if self._is_success(data, accepted_codes=(200,)):
                message = "镜像清理成功"
                logger.info(
                    f"DC助手多源版 镜像清理成功 "
                    f"source={source['name']} container={container_name} image={image_name} reason={reason}"
                )
                self._record_task_log("镜像清理", source, container_name, image_name, True, message)
                return True
            message = self._format_dc_error(data)
            logger.error(
                f"DC助手多源版 镜像清理失败 "
                f"source={source['name']} container={container_name} image={image_name} reason={message}"
            )
            self._record_task_log("镜像清理", source, container_name, image_name, False, message)
        except Exception as err:
            safe_reason = self._safe_reason(err)
            message = f"网络异常：{safe_reason}"
            logger.error(
                f"DC助手多源版 镜像清理网络异常 "
                f"source={source['name']} container={container_name} image={image_name} reason={safe_reason}"
            )
            self._record_task_log("镜像清理", source, container_name, image_name, False, message)
        return False

    def auto_update(self):
        logger.info("DC助手多源版-自动更新-准备执行")
        if not self._auto_update_cron:
            return
        selected = set(self._auto_update_list)
        if not selected:
            logger.info("DC助手多源版-自动更新-未选择容器")
            for source in self._enabled_sources():
                self._record_task_log(
                    "自动更新", source, "-", "-", False,
                    "跳过：未选中容器", result="已跳过"
                )
            return

        for source in self._enabled_sources():
            if self._delete_images:
                for image in self.get_images_list(source):
                    if not image.get("inUsed") and image.get("tag"):
                        self.remove_image(
                            source,
                            image.get("id"),
                            image=image.get("tag") or image.get("id"),
                            container_name="unknown",
                            reason="unused"
                        )
            available, containers, source_reason = self._get_docker_list_status(source)
            if not available:
                self._record_task_log(
                    "自动更新", source, "-", "-", False,
                    f"跳过：源不可用，无法确认容器状态：{source_reason}",
                    result="远程源无法确认"
                )
                continue
            selected_in_source = False
            for container in containers:
                name = container.get("name")
                key = self._container_key(source, name)
                legacy_selected = name in selected and not self._has_key_for_source(selected, source["id"])
                if key not in selected and not legacy_selected:
                    continue
                selected_in_source = True
                if not container.get("haveUpdate"):
                    if self._reconcile_confirmed_task(
                        source, container, notify=self._auto_update_notify
                    ):
                        continue
                    self._record_task_log(
                        "自动更新", source, name, container.get("usingImage") or "unknown", True,
                        "跳过：未检测到新版本", result="无需更新"
                    )
                    continue
                if not container.get("usingImage") or str(container.get("usingImage")).startswith("sha256:"):
                    if self._auto_update_notify:
                        self._notify_tag_error(source, container, "自动更新")
                    self._record_task_log(
                        "自动更新",
                        source,
                        name,
                        container.get("usingImage") or "unknown",
                        False,
                        "跳过：镜像 TAG 无效，无法自动更新",
                        result="失败"
                    )
                    continue
                self._update_container(source, container, scene="自动更新", notify=self._auto_update_notify)
            if not selected_in_source:
                self._record_task_log(
                    "自动更新", source, "-", "-", False,
                    "跳过：未找到该源中选中的容器", result="已跳过"
                )

    @staticmethod
    def _has_key_for_source(selected: set, source_id: str) -> bool:
        prefix = f"{source_id}::"
        return any(str(item).startswith(prefix) for item in selected)

    @staticmethod
    def _update_task_key(source: Dict[str, Any], container_name: str) -> str:
        return f"{source.get('id') or '-'}::{container_name or '-'}"

    def _find_update_task(self, source: Dict[str, Any], container_name: str) -> Optional[Dict[str, Any]]:
        task_key = self._update_task_key(source, container_name)
        with self._progress_lock:
            tasks = list(getattr(self, "_progress_tasks", []) or [])
            return next((dict(item) for item in tasks if item.get("container_key") == task_key), None)

    def _submission_guard(self, source: Dict[str, Any], container_name: str) -> Tuple[bool, str]:
        task_key = self._update_task_key(source, container_name)
        if task_key in getattr(self, "_pending_update_keys", set()):
            return False, "跳过：已有更新任务正在提交，禁止重复提交"
        task = self._find_update_task(source, container_name)
        if not task:
            return True, ""
        status = str(task.get("status") or "")
        if status in {"已提交", "执行中", "超时待确认", "远程源无法确认"}:
            return False, f"跳过：已有更新任务处于{status}状态，禁止重复提交"
        submitted_ts = task.get("submitted_ts")
        try:
            elapsed = time.time() - float(submitted_ts)
        except (TypeError, ValueError):
            elapsed = self._intervallimit
        cooldown = max(60, int(self._intervallimit or 60))
        if elapsed < cooldown:
            return False, f"跳过：更新任务仍在冷却期（{cooldown}秒）"
        self._pending_update_keys.add(task_key)
        return True, ""

    def _release_submission(self, source: Dict[str, Any], container_name: str):
        with self._update_submission_lock:
            self._pending_update_keys.discard(self._update_task_key(source, container_name))

    def _reconcile_confirmed_task(self, source: Dict[str, Any], container: Dict[str, Any],
                                  notify: bool = False) -> bool:
        task = self._find_update_task(source, container.get("name"))
        if not task or task.get("status") in {"更新成功", "更新失败"}:
            return False
        name = container.get("name") or "unknown"
        image = container.get("usingImage") or task.get("image") or "unknown"
        message = "后续容器状态确认成功，haveUpdate 已清除"
        self._record_progress_task(
            task_id=task.get("task_id"),
            source=source,
            container_name=name,
            image=image,
            scene=task.get("scene") or "自动更新",
            status="更新成功",
            percent=100,
            message=message,
            reason=""
        )
        self._record_task_log(
            task.get("scene") or "自动更新", source, name, image, True, message
        )
        if notify:
            self._notify_update_success(
                source, name, image, task.get("scene") or "自动更新", message
            )
        return True

    def _update_container(self, source: Dict[str, Any], container: Dict[str, Any],
                          scene: str = "自动更新", notify: bool = False) -> Dict[str, Any]:
        name = container.get("name")
        image = container.get("usingImage") or "unknown"
        with self._update_submission_lock:
            allowed, guard_reason = self._submission_guard(source, name)
            if not allowed:
                self._record_task_log(scene, source, name, image, False, guard_reason, result="已跳过")
                logger.info(
                    f"DC助手多源版 更新任务跳过 source={source['name']} "
                    f"container={name} image={image} reason={guard_reason}"
                )
                return {"success": False, "message": guard_reason, "skipped": True}

        path = f"/api/container/{container.get('id')}/update"
        payload = {
            "containerName": name,
            "imageNameAndTag": image
        }
        try:
            data = self._post_json(source, path, payload)
            if self._is_success(data, accepted_codes=(200,)):
                task_id = (data.get("data") or {}).get("taskID")
                message = "容器更新任务已提交"
                logger.info(
                    f"DC助手多源版 更新任务已提交 "
                    f"source={source['name']} container={name} image={image} reason={scene}"
                )
                progress_id = task_id or f"{source.get('id')}::{name}::{int(time.time())}"
                self._record_progress_task(
                    task_id=progress_id,
                    source=source,
                    container_name=name,
                    image=image,
                    scene=scene,
                    status="已提交",
                    percent=5,
                    message=message,
                    reason="" if task_id else "DockerCopilot 未返回 taskID，无法继续追踪进度",
                    submitted_at=self._now_text(),
                    submitted_ts=time.time(),
                    remote_task_id=task_id or ""
                )
                self._record_task_log(scene, source, name, image, True, message)
                if notify:
                    self._notify_update_started(source, name, image, scene)
                if task_id:
                    self._start_progress_tracker(source, name, image, scene, task_id, notify=notify)
                else:
                    self._record_progress_task(
                        task_id=progress_id,
                        source=source,
                        container_name=name,
                        image=image,
                        scene=scene,
                        status="远程源无法确认",
                        percent=5,
                        message="更新任务已提交，但 DockerCopilot 未返回 taskID",
                        reason="无法轮询远程任务",
                        submitted_at=self._now_text(),
                        submitted_ts=time.time(),
                        remote_task_id=""
                    )
                self._release_submission(source, name)
                return {"success": True, "message": message, "task_id": task_id}
            else:
                message = self._format_dc_error(data)
                logger.error(
                    f"DC助手多源版 更新任务创建失败 "
                    f"source={source['name']} container={name} image={image} reason={message}"
                )
                self._record_task_log(scene, source, name, image, False, message, result="失败")
                if notify:
                    self._notify_update_failed(
                        source, name, image, scene, f"创建更新任务失败：{message}"
                    )
        except Exception as err:
            safe_reason = self._safe_reason(err)
            message = f"请求 DockerCopilot 更新接口异常：{safe_reason}"
            logger.error(
                f"DC助手多源版 更新任务网络异常 "
                f"source={source['name']} container={name} image={image} reason={safe_reason}"
            )
            self._record_task_log(scene, source, name, image, False, message, result="失败")
            if notify:
                self._notify_update_failed(source, name, image, scene, message)
        self._release_submission(source, name)
        return {"success": False, "message": message}

    @staticmethod
    def _format_dc_error(data: Optional[Dict[str, Any]]) -> str:
        if isinstance(data, dict):
            return DockerCopilotHelperMulti._safe_reason(data.get("msg") or data.get("message") or data.get("detail") or data)
        return "无响应"

    @staticmethod
    def _safe_reason(value: Any) -> str:
        text = str(value or "-")
        text = re.sub(r"https?://[^\s，。；,;]+", "[redacted-url]", text, flags=re.IGNORECASE)
        text = re.sub(r"(?i)(secretKey|token|cookie|authorization)=([^\s，。；,;]+)", r"\1=[redacted]", text)
        return text

    def _notify_auto_update_failed(self, source: Dict[str, Any], container: Dict[str, Any], reason: str):
        if not self._auto_update_notify:
            return
        self._notify_update_failed(
            source,
            container.get("name") or "unknown",
            container.get("usingImage") or "unknown",
            "自动更新",
            reason
        )

    def _notify_update_started(self, source: Dict[str, Any], container_name: str, image: str, scene: str):
        self.post_message(
            mtype=NotificationType.Plugin,
            title="【DC助手多源版-正在更新】",
            text=f"[{source['name']}] {container_name}\n"
                 f"任务：{scene}\n"
                 f"当前镜像：{image or '-'}\n"
                 f"状态：更新任务已提交，正在等待 DockerCopilot 执行"
        )

    def _notify_update_success(self, source: Dict[str, Any], container_name: str, image: str, scene: str, message: str):
        self.post_message(
            mtype=NotificationType.Plugin,
            title="【DC助手多源版-更新成功】",
            text=f"[{source['name']}] {container_name}\n"
                 f"任务：{scene}\n"
                 f"镜像：{image or '-'}\n"
                 f"结果：{self._safe_reason(message) or '容器更新完成'}"
        )

    def _notify_update_failed(self, source: Dict[str, Any], container_name: str, image: str, scene: str, reason: str):
        safe_reason = self._safe_reason(reason)
        self.post_message(
            mtype=NotificationType.Plugin,
            title="【DC助手多源版-更新失败】",
            text=f"[{source['name']}] {container_name}\n"
                 f"任务：{scene}\n"
                 f"镜像：{image or '-'}\n"
                 f"原因：{safe_reason}"
        )

    def _start_progress_tracker(self, source: Dict[str, Any], name: str, image: str,
                                scene: str, task_id: str, notify: bool = False):
        worker = threading.Thread(
            target=self._track_update_progress,
            args=(dict(source), name, image, scene, task_id, notify),
            daemon=True
        )
        worker.start()

    def _track_update_progress(self, source: Dict[str, Any], name: str, image: str,
                               scene: str, task_id: str, notify: bool = False):
        interval = max(1, int(self._interval or 10))
        limit = max(60, int(self._intervallimit or 60))
        for iteration in range(limit):
            try:
                data = self._get_json(source, f"/api/progress/{task_id}")
                if not self._is_success(data, accepted_codes=(200,)):
                    message = self._format_dc_error(data)
                    raw_message = str((data or {}).get("msg") or (data or {}).get("message") or "") if isinstance(data, dict) else ""
                    explicit_failure = bool(re.search(r"失败|异常|错误|超时", raw_message))
                    status = "更新失败" if explicit_failure else "远程源无法确认"
                    self._record_progress_task(
                        task_id=task_id,
                        source=source,
                        container_name=name,
                        image=image,
                        scene=scene,
                        status=status,
                        percent=self._estimate_progress_percent(iteration, limit),
                        message="更新进度查询失败" if explicit_failure else "无法确认远程更新进度",
                        reason=message
                    )
                    self._record_task_log(
                        scene, source, name, image, False,
                        f"更新进度查询失败：{message}", result=status
                    )
                    if notify and explicit_failure:
                        self._notify_update_failed(source, name, image, scene, message)
                    return

                raw_message = data.get("msg") or data.get("message") or data.get("detail") or "更新任务执行中"
                safe_message = self._safe_reason(raw_message)
                status = self._progress_status_from_message(safe_message)
                if status == "更新失败":
                    self._record_progress_task(
                        task_id=task_id,
                        source=source,
                        container_name=name,
                        image=image,
                        scene=scene,
                        status=status,
                        percent=self._estimate_progress_percent(iteration, limit),
                        message=safe_message,
                        reason=safe_message
                    )
                    self._record_task_log(scene, source, name, image, False, safe_message, result=status)
                    if notify:
                        self._notify_update_failed(source, name, image, scene, safe_message)
                    return

                if status == "更新成功":
                    confirmed, confirmation_reason = self._query_update_confirmation(source, name)
                    if confirmed is True:
                        self._record_progress_task(
                            task_id=task_id,
                            source=source,
                            container_name=name,
                            image=image,
                            scene=scene,
                            status="更新成功",
                            percent=100,
                            message="进度完成且容器已无可更新标记",
                            reason=""
                        )
                        self._record_task_log(scene, source, name, image, True, "容器更新完成")
                        if notify:
                            self._notify_update_success(source, name, image, scene, "容器更新完成")
                    else:
                        result_status = "超时待确认" if confirmed is False else "远程源无法确认"
                        reason = (
                            "进度接口已完成，但容器仍报告 haveUpdate=true"
                            if confirmed is False else confirmation_reason
                        )
                        self._record_progress_task(
                            task_id=task_id,
                            source=source,
                            container_name=name,
                            image=image,
                            scene=scene,
                            status=result_status,
                            percent=95,
                            message="更新完成但最终容器状态无法确认",
                            reason=reason
                        )
                        self._record_task_log(
                            scene, source, name, image, False,
                            f"更新完成但结果无法确认：{reason}", result=result_status
                        )
                    return

                self._record_progress_task(
                    task_id=task_id,
                    source=source,
                    container_name=name,
                    image=image,
                    scene=scene,
                    status=status,
                    percent=self._estimate_progress_percent(iteration, limit),
                    message=safe_message,
                    reason=""
                )
                time.sleep(interval)
            except Exception as err:
                safe_reason = self._safe_reason(err)
                self._record_progress_task(
                    task_id=task_id,
                    source=source,
                    container_name=name,
                    image=image,
                    scene=scene,
                    status="远程源无法确认",
                    percent=self._estimate_progress_percent(iteration, limit),
                    message="无法确认远程更新进度",
                    reason=safe_reason
                )
                logger.error(f"DC助手多源版[{source['name']}] 进度追踪异常：{safe_reason}")
                self._record_task_log(
                    scene, source, name, image, False,
                    f"更新结果无法确认：{safe_reason}", result="远程源无法确认"
                )
                return

        confirmed, confirmation_reason = self._query_update_confirmation(source, name)
        if confirmed is True:
            message = "追踪结束后容器状态校验通过，容器已无可更新标记"
            self._record_progress_task(
                task_id=task_id,
                source=source,
                container_name=name,
                image=image,
                scene=scene,
                status="更新成功",
                percent=100,
                message=message,
                reason=""
            )
            self._record_task_log(scene, source, name, image, True, "容器更新完成（追踪结束后校验）")
            if notify:
                self._notify_update_success(source, name, image, scene, message)
            return

        status = "超时待确认" if confirmed is False else "远程源无法确认"
        message = "等待最终结果，DockerCopilot 可能仍在后台执行，请稍后刷新"
        reason = (
            "追踪结束时容器仍报告 haveUpdate=true"
            if confirmed is False else confirmation_reason
        )
        self._record_progress_task(
            task_id=task_id,
            source=source,
            container_name=name,
            image=image,
            scene=scene,
            status=status,
            percent=95,
            message=message,
            reason=reason
        )
        self._record_task_log(
            scene, source, name, image, False,
            f"更新完成但结果无法确认：{reason}", result=status
        )
        logger.info(f"DC助手多源版[{source['name']}] 等待更新最终结果：{name}")

    def _query_update_confirmation(self, source: Dict[str, Any], container_name: str) -> Tuple[Optional[bool], str]:
        available, containers, reason = self._get_docker_list_status(source)
        if not available:
            return None, reason or "远程源不可用"
        target = next((item for item in containers if item.get("name") == container_name), None)
        if not target:
            return None, "更新后未找到目标容器，无法确认结果"
        have_update = target.get("haveUpdate")
        if isinstance(have_update, str):
            normalized = have_update.strip().lower()
            if normalized in {"false", "0", "no", "否"}:
                return True, ""
            if normalized in {"true", "1", "yes", "是"}:
                return False, ""
            return None, "容器返回的 haveUpdate 状态未知"
        if have_update is False or have_update == 0:
            return True, ""
        if have_update is True or have_update == 1:
            return False, ""
        return None, "容器未返回 haveUpdate，无法确认结果"

    def _is_update_confirmed_after_tracking(self, source: Dict[str, Any], container_name: str) -> bool:
        confirmed, _reason = self._query_update_confirmation(source, container_name)
        return confirmed is True

    @staticmethod
    def _estimate_progress_percent(iteration: int, limit: int) -> int:
        if limit <= 1:
            return 60
        return min(95, max(10, int(((iteration + 1) / limit) * 90)))

    @staticmethod
    def _progress_status_from_message(message: str) -> str:
        text = str(message or "")
        if any(keyword in text for keyword in ["更新成功", "更新完成", "任务完成"]):
            return "更新成功"
        if any(keyword in text for keyword in ["失败", "异常", "错误", "超时"]):
            return "更新失败"
        return "执行中"

    def _record_progress_task(self, task_id: str, source: Dict[str, Any], container_name: str,
                              image: str, scene: str, status: str, percent: int,
                              message: str, reason: str = "", submitted_at: str = None,
                              submitted_ts: float = None, remote_task_id: str = None):
        safe_message = self._safe_reason(message)
        safe_reason = self._safe_reason(reason)
        now_text = self._now_text()
        task_key = str(task_id or f"{source.get('id')}::{container_name}")
        with self._progress_lock:
            tasks = list(getattr(self, "_progress_tasks", []) or [])
            existing = next((item for item in tasks if item.get("task_id") == task_key), None)
            log_item = {
                "time": now_text,
                "status": status,
                "message": safe_message,
                "reason": safe_reason
            }
            if existing:
                existing.update({
                    "status": status,
                    "percent": max(0, min(100, int(percent or 0))),
                    "message": safe_message,
                    "reason": safe_reason,
                    "updated_at": now_text
                })
                if submitted_at:
                    existing["submitted_at"] = submitted_at
                if submitted_ts is not None:
                    existing["submitted_ts"] = submitted_ts
                if remote_task_id is not None:
                    existing["remote_task_id"] = remote_task_id
                logs = list(existing.get("logs") or [])
                logs.insert(0, log_item)
                existing["logs"] = logs[:20]
                tasks.remove(existing)
                tasks.insert(0, existing)
            else:
                tasks.insert(0, {
                    "task_id": task_key,
                    "source_id": source.get("id"),
                    "source": source.get("name") or source.get("id") or "-",
                    "container": container_name or "unknown",
                    "container_key": self._update_task_key(source, container_name),
                    "image": image or "unknown",
                    "scene": scene or "-",
                    "submitted_at": submitted_at or now_text,
                    "submitted_ts": submitted_ts if submitted_ts is not None else time.time(),
                    "remote_task_id": remote_task_id if remote_task_id is not None else task_key,
                    "status": status,
                    "percent": max(0, min(100, int(percent or 0))),
                    "message": safe_message,
                    "reason": safe_reason,
                    "updated_at": now_text,
                    "logs": [log_item]
                })
            self._progress_tasks = tasks[:50]
        self._persist_progress_tasks()

    def _persist_progress_tasks(self):
        updater = getattr(self, "update_config", None)
        if not callable(updater):
            return
        try:
            self.__update_config()
        except Exception as err:
            logger.warning(f"DC助手多源版保存更新任务状态失败：{self._safe_reason(err)}")

    def _progress_task_snapshot(self) -> List[Dict[str, Any]]:
        with self._progress_lock:
            return [dict(item) for item in list(getattr(self, "_progress_tasks", []) or [])]

    def updatable(self):
        logger.info("DC助手多源版-更新通知-准备执行")
        if not self._update_cron:
            return
        selected = set(self._updatable_list)
        if not selected:
            logger.info("DC助手多源版-更新通知-未选择容器")
            return

        for container in self.get_all_docker_list():
            source = container["_source"]
            name = container.get("name")
            legacy_selected = name in selected and not self._has_key_for_source(selected, source["id"])
            if container["_key"] not in selected and not legacy_selected:
                continue
            if not container.get("haveUpdate"):
                continue
            if container.get("usingImage") and not str(container.get("usingImage")).startswith("sha256:"):
                self._record_task_log(
                    "更新通知",
                    source,
                    name,
                    container.get("usingImage") or "unknown",
                    True,
                    "检测到可更新，未推送提醒"
                )
            else:
                self._record_task_log(
                    "更新通知",
                    source,
                    name,
                    container.get("usingImage") or "unknown",
                    False,
                    "镜像 TAG 不正确，无法发送有效更新通知"
                )

    def _notify_tag_error(self, source: Dict[str, Any], container: Dict[str, Any], scene: str):
        self._notify_update_failed(
            source,
            container.get("name") or "unknown",
            container.get("usingImage") or "unknown",
            scene,
            "镜像 TAG 不正确，无法通过 DockerCopilot 自动更新"
        )

    @staticmethod
    def _now_text() -> str:
        return datetime.now(pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")

    def _record_task_log(self, action: str, source: Dict[str, Any], container_name: str,
                         image: str, success: bool, message: str, result: str = None):
        message = self._safe_reason(message)
        if result:
            log_result = result
        elif success:
            if "更新完成" in str(message or "") or "更新成功" in str(message or ""):
                log_result = "成功"
            elif action in {"手动升级", "自动更新"}:
                log_result = "已提交"
            elif action == "更新通知":
                log_result = "已记录"
            elif action.endswith("通知"):
                log_result = "已发送"
            elif action in {"镜像清理", "备份"}:
                log_result = "已完成"
            else:
                log_result = "成功"
        else:
            log_result = "失败"
        log_item = {
            "time": self._now_text(),
            "type": action,
            "source": source.get("name") or source.get("id") or "-",
            "source_id": source.get("id"),
            "container": container_name or "unknown",
            "image": image or "unknown",
            "success": bool(success),
            "result": log_result,
            "message": message or "-"
        }
        logs = list(getattr(self, "_task_logs", []) or [])
        logs.insert(0, log_item)
        self._task_logs = logs[:100]

    def _last_log_for_container(self, container_key: str) -> Optional[Dict[str, Any]]:
        source_id, name = self._split_container_key(container_key or "")
        for item in getattr(self, "_task_logs", []) or []:
            if item.get("source_id") == source_id and item.get("container") == name:
                return item
        return None

    def backup(self):
        logger.info("DC助手多源版-备份-准备执行")
        results = []
        backup_sources = self._selected_backup_sources()
        for source in backup_sources:
            try:
                data = self._get_json(source, "/api/container/backup")
                if self._is_success(data, accepted_codes=(200,)):
                    results.append(f"[{source['name']}] 成功")
                    logger.info(f"DC助手多源版[{source['name']}] 备份完成")
                else:
                    msg = self._format_dc_error(data)
                    results.append(f"[{source['name']}] 失败：{msg}")
                    logger.error(f"DC助手多源版[{source['name']}] 备份失败：{msg}")
            except Exception as err:
                safe_reason = self._safe_reason(err)
                results.append(f"[{source['name']}] 失败：网络异常")
                logger.error(f"DC助手多源版[{source['name']}] 备份网络异常：{safe_reason}")
        if self._backups_notify and results:
            self.post_message(
                mtype=NotificationType.Plugin,
                title="【DC助手多源版-备份结果】",
                text="\n".join(results)
            )

    def _selected_backup_sources(self) -> List[Dict[str, Any]]:
        if not self._backup_sources:
            return self._enabled_sources()
        selected = set(self._backup_sources)
        return [source for source in self._enabled_sources() if source.get("id") in selected]

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        pass

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/state",
                "endpoint": self.api_state,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 DC 助手多源状态",
                "description": "返回已脱敏的源状态、容器选项和任务选择摘要"
            },
            {
                "path": "/manual_update",
                "endpoint": self.api_manual_update,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动升级指定容器",
                "description": "按 source_id::container_name 调用对应 DockerCopilot 源的容器更新接口"
            }
        ]

    def api_state(self) -> Dict[str, Any]:
        config = self.get_config() or {}
        self._apply_config_snapshot(config)
        source_states, containers = self._collect_page_state()
        container_items = self._container_items_from_containers(containers)
        enabled_sources = [source for source in self._sources if source.get("enabled", True)]
        task_logs = list(getattr(self, "_task_logs", []) or [])
        progress_tasks = self._progress_task_snapshot()
        logs_success = len([item for item in task_logs if item.get("result") == "成功"])
        logs_failed = len([item for item in task_logs if item.get("result") in {"失败", "更新失败"}])
        auto_updatable_count = len([item for item in containers if item.get("_selected_auto") and item.get("haveUpdate")])
        progress_running = len([item for item in progress_tasks if item.get("status") in {"已提交", "执行中"}])
        progress_failed = len([item for item in progress_tasks if item.get("status") == "更新失败"])
        return {
            "enabled": self._enabled,
            "sources": [self._public_source(source) for source in self._sources],
            "source_states": source_states,
            "containers": [self._public_container(container) for container in containers],
            "container_items": container_items,
            "source_items": self._build_source_items(),
            "updatablelist": self._updatable_list or [],
            "autoupdatelist": self._auto_update_list or [],
            "backup_sources": self._backup_sources or [],
            "logs": task_logs,
            "progress_tasks": progress_tasks,
            "metrics": {
                "sources": len(self._sources),
                "enabled_sources": len(enabled_sources),
                "containers": len(containers),
                "updatable": len([item for item in containers if item.get("haveUpdate")]),
                "notify_selected": len(self._updatable_list or []),
                "auto_selected": len(self._auto_update_list or []),
                "auto_updatable": auto_updatable_count,
                "failed_sources": len([item for item in source_states if item.get("state") == "异常"]),
                "logs_total": len(task_logs),
                "logs_success": logs_success,
                "logs_failed": logs_failed,
                "progress_running": progress_running,
                "progress_failed": progress_failed
            }
        }

    def api_manual_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        config = self.get_config() or {}
        self._apply_config_snapshot(config)
        container_key = str((data or {}).get("container_key") or "").strip()
        if not container_key:
            return {"success": False, "message": "缺少容器标识"}

        source_id, container_name = self._split_container_key(container_key)
        source = self._source_by_id(source_id)
        if not source:
            return {"success": False, "message": "未找到对应的启用源"}

        containers = self.get_docker_list(source)
        target = None
        for container in containers:
            if self._container_key(source, container.get("name", "")) == container_key:
                target = container
                break
        if not target:
            return {"success": False, "message": "未找到对应容器"}
        if not target.get("haveUpdate"):
            return {"success": False, "message": "容器当前无需升级"}

        image = target.get("usingImage")
        if not image or str(image).startswith("sha256:"):
            message = "镜像 TAG 不正确，无法手动升级"
            logger.error(
                f"DC助手多源版 手动升级失败 "
                f"source={source['name']} container={target.get('name')} image={image or 'unknown'} reason={message}"
            )
            self._record_task_log("手动升级", source, target.get("name"), image or "unknown", False, message)
            return {"success": False, "message": message}

        return self._update_container(source, target, scene="手动升级", notify=True)

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        config = self.get_config() or {}
        self._apply_config_snapshot(config)
        if self.get_render_mode()[0] == "vue":
            return None, self._build_form_defaults()
        container_items = self._build_container_items()
        source_items = self._build_source_items()
        source_summary = self._build_source_summary()
        form_defaults = self._build_form_defaults()

        return [
            {
                "component": "VForm",
                "content": [
                    self._form_header(source_summary),
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "text": "多源配置包含 DC 地址与 secretKey：secretKey 仅保存在 MP 插件配置中，日志与通知不输出明文。"
                        }
                    },
                    self._section_title("DockerCopilot 源", "当前启用 Vue 配置页：点击“新增源”会在页面中新增 1 个 DC 源设置卡片。"),
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "如你看到此后备页面，说明当前 MP 未加载插件远程组件。请确认 dist/assets/remoteEntry.js 已随插件安装。"
                        }
                    },
                    self._section_title("基础开关", "对应设计稿左侧基础开关区；保存后定时任务立即按新配置生效。"),
                    {
                        "component": "VRow",
                        "content": [
                            self._switch_col("enabled", "启用插件", 3),
                            self._switch_col("onlyonce", "立即运行一次", 3),
                            self._switch_col("schedulereport", "进度汇报", 3),
                            self._switch_col("deleteimages", "镜像清理", 3)
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._text_col("interval", "检查间隔（秒）", 3, placeholder="10"),
                            self._text_col("intervallimit", "检查次数", 3, placeholder="60"),
                            self._text_col("updatecron", "更新通知 Cron", 3, placeholder="15 8-23/2 * * *"),
                            self._text_col("autoupdatecron", "自动更新 Cron", 3, placeholder="15 2 * * *")
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._text_col("backupcron", "自动备份 Cron", 4, placeholder="0 7 * * *"),
                            self._switch_col("updatablenotify", "更新通知开关", 4),
                            self._switch_col("autoupdatenotify", "自动更新通知", 4)
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._switch_col("backupsnotify", "备份结果通知", 4),
                            self._select_col("backup_sources", "自动备份源范围", source_items,
                                             "留空表示备份全部启用源；选择后只备份指定 DC 源。", 8)
                        ]
                    },
                    self._section_title("容器选择", "跨源选择更新通知、自动更新与备份范围；保存复合值 source_id::container_name，避免同名容器误更新。"),
                    self._selection_tabs(container_items)
                ]
            }
        ], form_defaults

    def _form_header(self, source_summary: str) -> Dict[str, Any]:
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "color": "primary", "class": "mb-4"},
            "content": [
                {
                    "component": "VCardTitle",
                    "text": "DC助手 · 多 DockerCopilot 源"
                },
                {
                    "component": "VCardText",
                    "text": f"统一管理多个 LXC 中的 DockerCopilot 实例。{source_summary}，容器值使用 source_id::container_name 防同名冲突。"
                }
            ]
        }

    @staticmethod
    def _section_title(title: str, subtitle: str = None) -> Dict[str, Any]:
        content = [{
            "component": "VCardTitle",
            "props": {"class": "px-0 pb-1"},
            "text": title
        }]
        if subtitle:
            content.append({
                "component": "VCardSubtitle",
                "props": {"class": "px-0 pb-3"},
                "text": subtitle
            })
        return {
            "component": "VCard",
            "props": {"variant": "text", "class": "mt-4"},
            "content": content
        }

    def _selection_tabs(self, container_items: List[Dict[str, str]]) -> Dict[str, Any]:
        return {
            "component": "VRow",
            "content": [{
                "component": "VCol",
                "props": {"cols": 12},
                "content": [
                    {
                        "component": "VTabs",
                        "props": {"model": "_tabs", "height": 40},
                        "content": [
                            {"component": "VTab", "props": {"value": "notify"}, "text": "更新通知"},
                            {"component": "VTab", "props": {"value": "auto"}, "text": "自动更新"},
                            {"component": "VTab", "props": {"value": "backup"}, "text": "自动备份"}
                        ]
                    },
                    {
                        "component": "VWindow",
                        "props": {"model": "_tabs"},
                        "content": [
                            {
                                "component": "VWindowItem",
                                "props": {"value": "notify", "style": {"margin-top": "20px"}},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            self._select_col("updatablelist", "更新通知容器", container_items,
                                                             "按源名称 / 容器名展示，保存 source_id::container_name。", 12)
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "auto", "style": {"margin-top": "20px"}},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            self._select_col("autoupdatelist", "自动更新容器", container_items,
                                                             "只有选中的容器有更新时才自动调用对应源更新接口。", 12)
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "backup", "style": {"margin-top": "20px"}},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "DockerCopilot 备份接口为源级操作；留空备份全部启用源，选择源后只备份指定源。"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }]
        }

    def _build_form_defaults(self) -> Dict[str, Any]:
        defaults = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "updatablenotify": self._updatable_notify,
            "autoupdatenotify": self._auto_update_notify,
            "schedulereport": self._schedule_report,
            "deleteimages": self._delete_images,
            "backupsnotify": self._backups_notify,
            "updatecron": self._update_cron,
            "autoupdatecron": self._auto_update_cron,
            "backupcron": self._backup_cron,
            "interval": self._interval or 10,
            "intervallimit": self._intervallimit or 60,
            "updatablelist": self._updatable_list or [],
            "autoupdatelist": self._auto_update_list or [],
            "_tabs": "notify",
            "backup_sources": self._backup_sources or []
        }
        defaults["sources"] = self._sources or []
        defaults["sources_text"] = self._sources_text
        defaults["container_items"] = self._build_container_items()
        return defaults

    def _build_source_summary(self) -> str:
        if not self._sources:
            return "当前未加载可用 DC 源"
        enabled_count = len(self._enabled_sources())
        return f"已配置 {len(self._sources)} 个源，启用 {enabled_count} 个"

    def _build_container_items(self) -> List[Dict[str, str]]:
        items = []
        try:
            containers = self.get_all_docker_list() if self._sources else []
            valid_keys = {item["_key"] for item in containers}
            if self._updatable_list:
                self._updatable_list = [item for item in self._updatable_list if item in valid_keys or "::" not in item]
            if self._auto_update_list:
                self._auto_update_list = [item for item in self._auto_update_list if item in valid_keys or "::" not in item]
            for container in containers:
                source_name = container.get("_source_name")
                name = container.get("name")
                title = f"{source_name} / {name}"
                if container.get("haveUpdate"):
                    title = f"{title}（可更新）"
                items.append({"title": title, "value": container["_key"]})
        except Exception as err:
            logger.error(f"DC助手多源版生成容器选项失败：{err}")
        return items

    @staticmethod
    def _container_items_from_containers(containers: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        items = []
        for container in containers:
            source_name = container.get("_source_name")
            name = container.get("name")
            title = f"{source_name} / {name}"
            if container.get("haveUpdate"):
                title = f"{title}（可更新）"
            items.append({"title": title, "value": container.get("_key")})
        return items

    @staticmethod
    def _public_source(source: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": source.get("id"),
            "name": source.get("name"),
            "host": "已脱敏" if source.get("host") else "",
            "enabled": source.get("enabled", True)
        }

    @staticmethod
    def _public_container(container: Dict[str, Any]) -> Dict[str, Any]:
        last_log = container.get("_last_log") or {}
        return {
            "key": container.get("_key"),
            "source_id": container.get("_source_id"),
            "source_name": container.get("_source_name"),
            "name": container.get("name"),
            "id": container.get("id"),
            "usingImage": container.get("usingImage"),
            "status": container.get("status"),
            "runningTime": container.get("runningTime"),
            "createTime": container.get("createTime"),
            "haveUpdate": container.get("haveUpdate"),
            "selected_notify": container.get("_selected_notify", False),
            "selected_auto": container.get("_selected_auto", False),
            "last_result": last_log.get("result") or ("等待更新" if container.get("haveUpdate") else "无需更新"),
            "last_message": last_log.get("message") or "-"
        }

    def _build_source_items(self) -> List[Dict[str, str]]:
        return [
            {"title": f"{source.get('name')} · {source.get('id')}", "value": source.get("id")}
            for source in self._enabled_sources()
        ]

    @staticmethod
    def _switch_col(model: str, label: str, md: int) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{
                "component": "VSwitch",
                "props": {"model": model, "label": label}
            }]
        }

    @staticmethod
    def _text_col(model: str, label: str, md: int, placeholder: str = None,
                  hint: str = None, textarea: bool = False, password: bool = False) -> Dict[str, Any]:
        props = {"model": model, "label": label}
        if placeholder:
            props["placeholder"] = placeholder
        if hint:
            props["hint"] = hint
            props["persistent-hint"] = True
        if password:
            props["type"] = "password"
        if textarea:
            props["rows"] = 8
            props["auto-grow"] = True
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{
                "component": "VTextarea" if textarea else "VTextField",
                "props": props
            }]
        }

    @staticmethod
    def _select_col(model: str, label: str, items: List[Dict[str, str]], hint: str, md: int = 6) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{
                "component": "VSelect",
                "props": {
                    "chips": True,
                    "multiple": True,
                    "model": model,
                    "label": label,
                    "items": items,
                    "hint": hint,
                    "persistent-hint": True
                }
            }]
        }

    def get_page(self) -> Optional[List[dict]]:
        config = self.get_config() or {}
        self._apply_config_snapshot(config)
        if self.get_render_mode()[0] == "vue":
            return None
        source_states, containers = self._collect_page_state()
        updatable_count = len([item for item in containers if item.get("haveUpdate")])
        auto_count = len(self._auto_update_list or [])
        backup_count = len(self._selected_backup_sources())
        failed_count = len([item for item in source_states if item.get("state") == "异常"])
        selected_titles = self._selected_container_titles(containers)
        notify_preview = self._notify_preview(containers)
        return [
            self._page_header(),
            {
                "component": "VRow",
                "content": [
                    self._metric_card("可更新容器", str(updatable_count), "primary"),
                    self._metric_card("今日自动更新", str(auto_count), "success"),
                    self._metric_card("备份源", str(backup_count), "success"),
                    self._metric_card("异常源", str(failed_count), "error")
                ]
            },
            {
                "component": "VRow",
                "content": [
                    self._page_col(7, self._source_status_card(source_states)),
                    self._page_col(5, self._notify_card(notify_preview))
                ]
            },
            {
                "component": "VRow",
                "content": [
                    self._page_col(7, self._container_card(containers)),
                    self._page_col(5, self._selection_summary_card(selected_titles))
                ]
            },
            {
                "component": "VRow",
                "content": [
                    self._page_col(7, self._audit_card(source_states, containers)),
                    self._page_col(5, self._failed_policy_card())
                ]
            }
        ]

    def _collect_page_state(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        source_states = []
        containers = []
        notify_selected = set(self._updatable_list or [])
        auto_selected = set(self._auto_update_list or [])
        for source in self._sources:
            source_containers = []
            state = "停用"
            version = "未知"
            message = "源已停用"
            if source.get("enabled", True):
                try:
                    data = self._get_json(source, "/api/containers")
                    if self._is_success(data):
                        source_containers = data.get("data") or []
                        state = "已连接"
                        message = f"获取到 {len(source_containers)} 个容器"
                        version = "1.1.x"
                    else:
                        state = "异常"
                        msg = self._format_dc_error(data)
                        message = f"接口异常：{msg}"
                except Exception as err:
                    state = "异常"
                    message = f"连接异常：{self._safe_reason(err)}"
                    source_containers = []
            for container in source_containers:
                item = dict(container)
                item["_source"] = source
                item["_source_id"] = source["id"]
                item["_source_name"] = source["name"]
                item["_key"] = self._container_key(source, item.get("name", ""))
                name = item.get("name")
                legacy_notify = name in notify_selected and not self._has_key_for_source(notify_selected, source["id"])
                legacy_auto = name in auto_selected and not self._has_key_for_source(auto_selected, source["id"])
                item["_selected_notify"] = item["_key"] in notify_selected or legacy_notify
                item["_selected_auto"] = item["_key"] in auto_selected or legacy_auto
                item["_last_log"] = self._last_log_for_container(item["_key"])
                containers.append(item)
            selected_auto_count = len([item for item in containers if item.get("_source_id") == source.get("id")
                                       and item.get("_selected_auto")])
            auto_updatable_count = len([item for item in containers if item.get("_source_id") == source.get("id")
                                        and item.get("_selected_auto") and item.get("haveUpdate")])
            source_states.append({
                "id": source.get("id"),
                "name": source.get("name"),
                "host": "已脱敏" if source.get("host") else "",
                "enabled": source.get("enabled", True),
                "state": state,
                "version": version,
                "message": message,
                "container_count": len(source_containers),
                "selected_auto_count": selected_auto_count,
                "auto_updatable_count": auto_updatable_count
            })
        return source_states, containers

    def _page_header(self) -> Dict[str, Any]:
        status = "已启用" if self._enabled else "未启用"
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "color": "primary", "class": "mb-4"},
            "content": [
                {"component": "VCardTitle", "text": "DC助手 · 执行与通知"},
                {
                    "component": "VCardText",
                    "text": f"多源任务进度、通知预览与审计记录。状态：{status}，{self._build_source_summary()}。"
                }
            ]
        }

    @staticmethod
    def _metric_card(label: str, value: str, color: str) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 6, "md": 3},
            "content": [{
                "component": "VCard",
                "props": {"variant": "outlined"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": f"text-{color}"},
                        "text": value
                    },
                    {"component": "VCardText", "text": label}
                ]
            }]
        }

    @staticmethod
    def _page_col(md: int, child: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [child]
        }

    def _source_status_card(self, source_states: List[Dict[str, Any]]) -> Dict[str, Any]:
        rows = []
        for item in source_states:
            rows.append(f"{item['name']} | {item['host']} | {item['state']} | {item['version']} | {item['message']}")
        return self._text_card(
            "DockerCopilot 源",
            rows or ["暂无已配置源"],
            "源名称 | 地址 | 认证状态 | 版本 | 说明"
        )

    def _container_card(self, containers: List[Dict[str, Any]]) -> Dict[str, Any]:
        rows = []
        for container in containers[:20]:
            rows.append(
                f"{container.get('_source_name')} / {container.get('name')} | "
                f"{container.get('usingImage') or '-'} | "
                f"{container.get('status') or '-'} | "
                f"{'是' if container.get('haveUpdate') else '否'}"
            )
        if len(containers) > 20:
            rows.append(f"... 另有 {len(containers) - 20} 个容器未展示")
        return self._text_card(
            "容器列表",
            rows or ["保存并启用 DC 源后，刷新详情页加载容器列表。"],
            "源 / 容器 | 镜像 | 状态 | 可更新"
        )

    def _notify_card(self, preview: str) -> Dict[str, Any]:
        return {
            "component": "VCard",
            "props": {"variant": "outlined"},
            "content": [
                {"component": "VCardTitle", "text": "通知预览"},
                {
                    "component": "VCardText",
                    "content": [{
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": preview
                        }
                    }]
                }
            ]
        }

    def _selection_summary_card(self, selected_titles: List[str]) -> Dict[str, Any]:
        rows = selected_titles[:12]
        if len(selected_titles) > 12:
            rows.append(f"... 另有 {len(selected_titles) - 12} 项")
        rows.append("保存复合值 source_id::container_name，避免同名容器误更新。")
        return self._text_card("选择摘要", rows or ["当前未选择容器"], "已选容器")

    def _audit_card(self, source_states: List[Dict[str, Any]], containers: List[Dict[str, Any]]) -> Dict[str, Any]:
        now = datetime.now(pytz.timezone(settings.TZ)).strftime("%H:%M")
        rows = [
            f"{now} | 源检查 | 全部源 | 已连接 {len([item for item in source_states if item.get('state') == '已连接'])} / {len(source_states)}",
            f"{now} | 容器刷新 | 全部源 | 共 {len(containers)} 个容器",
            f"{now} | 配置读取 | MP 插件配置 | secretKey 已脱敏"
        ]
        return self._text_card("审计记录", rows, "时间 | 动作 | 目标 | 结果")

    @staticmethod
    def _failed_policy_card() -> Dict[str, Any]:
        return {
            "component": "VCard",
            "props": {"variant": "outlined"},
            "content": [
                {"component": "VCardTitle", "text": "失败源处理"},
                {
                    "component": "VList",
                    "props": {"density": "compact"},
                    "content": [
                        {"component": "VListItem", "props": {"title": "重试策略", "subtitle": "本轮跳过，下一次调度继续重试"}},
                        {"component": "VListItem", "props": {"title": "日志级别", "subtitle": "ERROR，不输出 secretKey 明文"}},
                        {"component": "VListItem", "props": {"title": "通知策略", "subtitle": "备份和更新结果按源名汇总推送"}}
                    ]
                }
            ]
        }

    @staticmethod
    def _text_card(title: str, rows: List[str], subtitle: str = None) -> Dict[str, Any]:
        content = [{"component": "VCardTitle", "text": title}]
        if subtitle:
            content.append({"component": "VCardSubtitle", "text": subtitle})
        content.append({
            "component": "VCardText",
            "text": "\n".join(rows)
        })
        return {
            "component": "VCard",
            "props": {"variant": "outlined"},
            "content": content
        }

    def _selected_container_titles(self, containers: List[Dict[str, Any]]) -> List[str]:
        selected = set((self._updatable_list or []) + (self._auto_update_list or []))
        titles = []
        for container in containers:
            key = container.get("_key")
            name = container.get("name")
            source_name = container.get("_source_name")
            source_id = container.get("_source_id")
            if key in selected or (name in selected and not self._has_key_for_source(selected, source_id)):
                titles.append(f"{source_name} / {name}")
        return titles

    def _notify_preview(self, containers: List[Dict[str, Any]]) -> str:
        for container in containers:
            if not container.get("haveUpdate"):
                continue
            return (
                f"【DC助手-更新通知】\n"
                f"[{container.get('_source_name')}] {container.get('name')} 可更新\n"
                f"当前镜像：{container.get('usingImage') or '-'}\n"
                f"状态：{container.get('status') or '-'} · {container.get('runningTime') or '-'}\n"
                f"说明：通知始终展示源名称，避免排障混乱。"
            )
        return "暂无可更新容器；有更新时通知会展示源名称、容器名、当前镜像与运行状态。"

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as err:
            logger.error(f"退出 DC助手多源版失败：{err}")

    @staticmethod
    def delete_res(url: str, headers: dict = None, params: dict = None, data: Any = None,
                   json: dict = None, allow_redirects: bool = True,
                   raise_exception: bool = False) -> Optional[requests.Response]:
        try:
            return requests.delete(
                url,
                params=params,
                data=data,
                json=json,
                verify=False,
                headers=headers,
                timeout=20,
                allow_redirects=allow_redirects,
                stream=False
            )
        except requests.exceptions.RequestException:
            if raise_exception:
                raise
            return None


