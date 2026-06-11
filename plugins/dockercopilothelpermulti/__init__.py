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
    plugin_version = "1.0.0"
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
        self._intervallimit = config.get("intervallimit") or 6
        self._interval = config.get("interval") or 10
        self._sources_text = config.get("sources_text") or config.get("sources") or ""
        self._sources = self._load_sources(config)

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

    def __update_config(self):
        self.update_config({
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
            "sources_text": self._sources_text,
            "sources": self._sources,
            "intervallimit": self._intervallimit,
            "interval": self._interval
        })

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

    def _load_sources(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        sources = self._parse_sources(config.get("sources_text") or config.get("sources"))
        if not sources and config.get("host") and config.get("secretKey"):
            sources = [{
                "id": "default",
                "name": "默认源",
                "host": config.get("host"),
                "secretKey": config.get("secretKey"),
                "enabled": True,
            }]
            self._sources_text = json.dumps(sources, ensure_ascii=False, indent=2)
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
        if normalized and not self._sources_text:
            self._sources_text = json.dumps(normalized, ensure_ascii=False, indent=2)
        return normalized

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
        for source in self._enabled_sources():
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

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        pass

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        container_items = self._build_container_items()
        source_summary = self._build_source_summary()
        default_sources = self._sources_text or json.dumps([
            {
                "id": "pve_lxc_01",
                "name": "PVE-LXC-01",
                "host": "http://dc-lxc-01:12712",
                "secretKey": "请替换为真实 secretKey",
                "enabled": True
            }
        ], ensure_ascii=False, indent=2)

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "text": "多源配置包含 DC 地址与 secretKey，请勿在日志、截图或公开渠道泄露。secretKey 在通知中不会明文输出。"
                        }
                    },
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
                            self._text_col("sources_text", "DockerCopilot 源 JSON", 12,
                                           hint="数组格式：id/name/host/secretKey/enabled。host 示例：http://dc-lxc-01:12712",
                                           textarea=True)
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._text_col("updatecron", "更新通知周期", 4, placeholder="15 8-23/2 * * *"),
                            self._text_col("autoupdatecron", "自动更新周期", 4, placeholder="15 2 * * *"),
                            self._text_col("backupcron", "自动备份周期", 4, placeholder="0 7 * * *")
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._text_col("interval", "进度检查间隔（秒）", 3, placeholder="10"),
                            self._text_col("intervallimit", "进度检查次数", 3, placeholder="6"),
                            self._switch_col("updatablenotify", "更新通知开关", 3),
                            self._switch_col("autoupdatenotify", "自动更新通知", 3)
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._switch_col("backupsnotify", "备份结果通知", 3),
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 9},
                                "content": [
                                    {
                                        "component": "VChip",
                                        "props": {
                                            "color": "primary",
                                            "variant": "tonal",
                                            "text": source_summary
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._select_col("updatablelist", "更新通知容器", container_items,
                                             "选择容器后，有更新时发送通知。选项格式：源名称 / 容器名"),
                            self._select_col("autoupdatelist", "自动更新容器", container_items,
                                             "选择容器后，有更新时自动调用对应源的 DC 更新接口")
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "updatablenotify": False,
            "autoupdatenotify": False,
            "schedulereport": False,
            "deleteimages": False,
            "backupsnotify": False,
            "interval": 10,
            "intervallimit": 6,
            "sources_text": default_sources
        }

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
                  hint: str = None, textarea: bool = False) -> Dict[str, Any]:
        props = {"model": model, "label": label}
        if placeholder:
            props["placeholder"] = placeholder
        if hint:
            props["hint"] = hint
            props["persistent-hint"] = True
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
    def _select_col(model: str, label: str, items: List[Dict[str, str]], hint: str) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 6},
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

    def get_page(self) -> List[dict]:
        sources = []
        for source in self._sources:
            secret = source.get("secretKey") or ""
            sources.append({
                "source": source,
                "masked_secret": f"{secret[:2]}******{secret[-2:]}" if len(secret) > 4 else "******",
                "enabled_text": "启用" if source.get("enabled", True) else "停用"
            })
        rows = []
        for source_info in sources:
            source = source_info["source"]
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": source.get("name")},
                    {"component": "td", "text": source.get("host")},
                    {"component": "td", "text": source_info["enabled_text"]},
                    {"component": "td", "text": source_info["masked_secret"]},
                ]
            })
        return [
            {
                "component": "VCard",
                "props": {"variant": "outlined"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "DC助手多源版"
                    },
                    {
                        "component": "VCardText",
                        "text": self._build_source_summary()
                    }
                ]
            }
        ]

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
