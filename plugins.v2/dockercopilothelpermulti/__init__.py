import json
import re
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
    plugin_version = "1.0.3"
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
    _intervallimit = 6
    _interval = 10
    _sources: List[Dict[str, Any]] = []
    _sources_text = ""
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
        self._intervallimit = config.get("intervallimit") or 6
        self._interval = config.get("interval") or 10
        self._sources = self._load_sources(config)
        self._sources_text = json.dumps(self._sources, ensure_ascii=False, indent=2) if self._sources else ""
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
            "interval": self._interval
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
        self._intervallimit = config.get("intervallimit") or 6
        self._interval = config.get("interval") or 10
        self._sources = self._load_sources(config) if config else []
        self._sources_text = json.dumps(self._sources, ensure_ascii=False, indent=2) if self._sources else ""

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

    def get_docker_list(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            data = self._get_json(source, "/api/containers")
            if self._is_success(data):
                return data.get("data") or []
            logger.error(f"DC助手多源版[{source['name']}] 获取容器列表异常：{data}")
        except Exception as err:
            logger.error(f"DC助手多源版[{source['name']}] 请求容器列表网络异常：{err}")
        return []

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
            logger.error(f"DC助手多源版[{source['name']}] 获取镜像列表异常：{data}")
        except Exception as err:
            logger.error(f"DC助手多源版[{source['name']}] 请求镜像列表网络异常：{err}")
        return []

    def remove_image(self, source: Dict[str, Any], sha: str) -> bool:
        try:
            data = self._delete_json(source, f"/api/image/{sha}?force=false")
            if self._is_success(data, accepted_codes=(200,)):
                logger.info(f"DC助手多源版[{source['name']}] 清理镜像成功：{sha}")
                return True
            logger.error(f"DC助手多源版[{source['name']}] 清理镜像异常：{data}")
        except Exception as err:
            logger.error(f"DC助手多源版[{source['name']}] 清理镜像网络异常：{err}")
        return False

    def auto_update(self):
        logger.info("DC助手多源版-自动更新-准备执行")
        if not self._auto_update_cron:
            return
        selected = set(self._auto_update_list)
        if not selected:
            logger.info("DC助手多源版-自动更新-未选择容器")
            return

        for source in self._enabled_sources():
            if self._delete_images:
                for image in self.get_images_list(source):
                    if not image.get("inUsed") and image.get("tag"):
                        self.remove_image(source, image.get("id"))
            containers = self.get_docker_list(source)
            for container in containers:
                name = container.get("name")
                key = self._container_key(source, name)
                legacy_selected = name in selected and not self._has_key_for_source(selected, source["id"])
                if key not in selected and not legacy_selected:
                    continue
                if not container.get("haveUpdate"):
                    continue
                if not container.get("usingImage") or str(container.get("usingImage")).startswith("sha256:"):
                    self._notify_tag_error(source, container, "自动更新")
                    continue
                self._update_container(source, container)

    @staticmethod
    def _has_key_for_source(selected: set, source_id: str) -> bool:
        prefix = f"{source_id}::"
        return any(str(item).startswith(prefix) for item in selected)

    def _update_container(self, source: Dict[str, Any], container: Dict[str, Any]):
        name = container.get("name")
        path = f"/api/container/{container.get('id')}/update"
        payload = {
            "containerName": name,
            "imageNameAndTag": container.get("usingImage")
        }
        try:
            data = self._post_json(source, path, payload)
            if self._is_success(data, accepted_codes=(200,)):
                task_id = (data.get("data") or {}).get("taskID")
                if self._auto_update_notify:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="【DC助手多源版-自动更新】",
                        text=f"[{source['name']}] {name}\n容器更新任务创建成功"
                    )
                if self._schedule_report and task_id:
                    self._report_progress(source, name, task_id)
            else:
                logger.error(f"DC助手多源版[{source['name']}] 创建更新任务失败：{data}")
        except Exception as err:
            logger.error(f"DC助手多源版[{source['name']}] 自动更新网络异常：{err}")

    def _report_progress(self, source: Dict[str, Any], name: str, task_id: str):
        for iteration in range(int(self._intervallimit)):
            try:
                data = self._get_json(source, f"/api/progress/{task_id}")
                if self._is_success(data, accepted_codes=(200,)):
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="【DC助手多源版-更新进度】",
                        text=f"[{source['name']}] {name}\n进度：{data.get('msg')}"
                    )
                    if data.get("msg") == "更新成功":
                        break
                time.sleep(int(self._interval))
            except Exception as err:
                logger.error(f"DC助手多源版[{source['name']}] 进度追踪异常：{err}")
                break
            if iteration + 1 >= int(self._intervallimit):
                logger.info(f"DC助手多源版[{source['name']}] 更新进度追踪超时：{name}")

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
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="【DC助手多源版-更新通知】",
                    text=f"[{source['name']}] {name} 可以更新\n"
                         f"当前镜像：{container.get('usingImage')}\n"
                         f"状态：{container.get('status')} {container.get('runningTime')}\n"
                         f"构建时间：{container.get('createTime')}"
                )
            else:
                self._notify_tag_error(source, container, "更新通知")

    def _notify_tag_error(self, source: Dict[str, Any], container: Dict[str, Any], scene: str):
        self.post_message(
            mtype=NotificationType.Plugin,
            title=f"【DC助手多源版-{scene}】",
            text=f"[{source['name']}] 检测到容器 TAG 不正确\n"
                 f"容器：{container.get('name')}\n"
                 f"当前镜像：{container.get('usingImage')}\n"
                 f"状态：{container.get('status')} {container.get('runningTime')}\n"
                 f"该镜像无法通过 DC 自动更新，请修正 TAG"
        )

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
                    msg = data.get("msg") if isinstance(data, dict) else "无响应"
                    results.append(f"[{source['name']}] 失败：{msg}")
                    logger.error(f"DC助手多源版[{source['name']}] 备份失败：{data}")
            except Exception as err:
                results.append(f"[{source['name']}] 失败：网络异常")
                logger.error(f"DC助手多源版[{source['name']}] 备份网络异常：{err}")
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
        pass

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
                            self._text_col("intervallimit", "检查次数", 3, placeholder="6"),
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
            "intervallimit": self._intervallimit or 6,
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
                        msg = data.get("msg") if isinstance(data, dict) else "无响应"
                        message = f"接口异常：{msg}"
                except Exception as err:
                    state = "异常"
                    message = f"连接异常：{err}"
                    source_containers = []
            for container in source_containers:
                item = dict(container)
                item["_source"] = source
                item["_source_id"] = source["id"]
                item["_source_name"] = source["name"]
                item["_key"] = self._container_key(source, item.get("name", ""))
                containers.append(item)
            source_states.append({
                "id": source.get("id"),
                "name": source.get("name"),
                "host": source.get("host"),
                "enabled": source.get("enabled", True),
                "state": state,
                "version": version,
                "message": message,
                "container_count": len(source_containers)
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


