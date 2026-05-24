from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

try:
    from app.plugins import _PluginBase
except Exception:  # pragma: no cover - local import fallback
    class _PluginBase:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._config: dict[str, Any] = {}


PLUGIN_VERSION = "0.1.9"
SCHEMA_VERSION = 1
READY_FILENAME = ".tingbook.ready"
SYNC_FILENAME = ".tingbook.sync.json"
METADATA_FILENAME = "metadata.json"
CN_TZ = timezone(timedelta(hours=8))
LOG_LIMIT = 200
EPISODE_URLS_FILENAME = ".tingbook.episode_urls.json"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".wav", ".ogg", ".opus"}
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class TingBookSyncError(Exception):
    pass


@dataclass(frozen=True)
class ScanResult:
    book_dir: Path
    task_id: str
    status: str
    message: str


@dataclass(frozen=True)
class UploadResult:
    book_dir: Path
    task_id: str
    status: str
    remote_path: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class StrmResult:
    book_dir: Path
    output_dir: Path
    created: int
    skipped: int


@dataclass(frozen=True)
class AdoptResult:
    source_path: Path
    book_dir: Path | None
    status: str
    message: str
    title: str
    source_name: str


@dataclass(frozen=True)
class MetadataCandidate:
    title: str
    author: str
    narrator: str
    category: str
    source_name: str
    source_url: str
    cover: str = ""
    score: float = 0.0


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "watch_dir": "",
    "strm_output_dir": "",
    "target_115_dir": "/Audiobooks",
    "scan_interval": 300,
    "move_completed": True,
    "overwrite_strm": False,
    "min_file_count": 1,
    "auto_adopt_loose_audio": True,
    "scrape_metadata": False,
    "public_base_url": "",
    "dry_run": True,
}


class TingBookSync(_PluginBase):
    plugin_name = "听书同步"
    plugin_desc = "扫描听书系统下载监听目录，接管散音频，上传 115 并生成 302 STRM。"
    plugin_icon = "tingbooksync.png"
    plugin_version = "0.1.9"
    plugin_author = "wYw"
    plugin_config_prefix = "tingbooksync_"
    plugin_order = 100
    auth_level = 1

    def init_plugin(self, config: dict[str, Any] | None = None) -> None:
        self._config = normalize_config(config or {})
        self._last_results: list[dict[str, str]] = []
        self._logs: list[dict[str, str]] = []
        self._add_log("info", "插件已初始化", "init")

    def get_state(self) -> bool:
        return bool(self._config.get("enabled"))

    def get_command(self) -> list[dict[str, Any]]:
        return []

    def get_api(self) -> list[dict[str, Any]]:
        return [
            {"path": "/state", "endpoint": self.api_state, "methods": ["GET"], "summary": "读取听书同步配置", "auth": "bear"},
            {"path": "/storages", "endpoint": self.api_storages, "methods": ["GET"], "summary": "读取可用资源存储", "auth": "bear"},
            {"path": "/browse", "endpoint": self.api_browse, "methods": ["GET"], "summary": "浏览 MP 资源目录", "auth": "bear"},
            {"path": "/logs", "endpoint": self.api_logs, "methods": ["GET"], "summary": "读取运行日志", "auth": "bear"},
            {"path": "/logs/clear", "endpoint": self.api_clear_logs, "methods": ["POST"], "summary": "清空运行日志", "auth": "bear"},
            {"path": "/play/{token}", "endpoint": self.api_play, "methods": ["GET"], "summary": "302 跳转到 115 临时下载地址", "allow_anonymous": True},
            {"path": "/page_browse", "endpoint": self.page_browse, "methods": ["GET"], "summary": "切换资源目录浏览位置", "auth": "bear"},
            {"path": "/page_select", "endpoint": self.page_select, "methods": ["GET"], "summary": "选择资源目录到插件配置", "auth": "bear"},
        ]

    def get_service(self) -> list[dict[str, Any]]:
        if not self.get_state():
            return []
        return [
            {
                "id": "TingBookSyncScan",
                "name": "听书目录扫描",
                "trigger": "interval",
                "func": self.scan_once,
                "kwargs": {},
                "seconds": int(self._config.get("scan_interval", 300)),
            }
        ]

    def get_form(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return build_form_schema(), dict(self._config)

    @classmethod
    def _frontend_dist_path(cls) -> str:
        return f"dist/v{cls.plugin_version.replace('.', '_')}"

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        return "vue", TingBookSync._frontend_dist_path()

    def get_page(self) -> list[dict[str, Any]] | None:
        return None

    def stop_service(self) -> None:
        self._last_results = []

    def api_state(self) -> dict[str, Any]:
        return {
            "success": True,
            "config": normalize_config(getattr(self, "_config", {})),
            "last_results": list(getattr(self, "_last_results", [])),
            "logs": list(getattr(self, "_logs", []))[-50:],
            "dry_run_only": True,
        }

    def api_storages(self) -> dict[str, Any]:
        return {"success": True, "items": get_storage_options()}

    def api_logs(self, limit: int | str = 100) -> dict[str, Any]:
        try:
            size = max(1, min(200, int(limit)))
        except Exception:
            size = 100
        items = list(getattr(self, "_logs", []))[-size:]
        return {"success": True, "items": items}

    def api_clear_logs(self) -> dict[str, Any]:
        self._logs = []
        self._add_log("info", "运行日志已清空", "logs")
        return {"success": True, "message": "运行日志已清空"}

    def api_play(self, token: str):
        try:
            payload = verify_play_token(token, str(self._config.get("play_token_secret") or ""))
            location = resolve_u115_download_url(str(payload["pickcode"]))
            try:
                from starlette.responses import RedirectResponse

                return RedirectResponse(url=location, status_code=302)
            except Exception:
                return {"success": True, "location": location}
        except Exception as exc:
            self._add_log("error", f"302 播放地址生成失败：{exc}", "play")
            try:
                from starlette.responses import PlainTextResponse

                return PlainTextResponse(str(exc), status_code=404)
            except Exception:
                return {"success": False, "message": str(exc)}

    def api_browse(self, path: str = "/", storage: str = "local", dirs_only: bool | str = False) -> dict[str, Any]:
        try:
            items = browse_storage_path(path=path or "/", storage=storage or "local", dirs_only=parse_bool(dirs_only))
            return {"success": True, "storage": storage or "local", "path": path or "/", "items": items}
        except Exception as exc:
            self._add_log("error", f"目录读取失败：{storage or 'local'}:{path or '/'}，{exc}", "browse")
            return {"success": False, "storage": storage or "local", "path": path or "/", "items": [], "message": str(exc)}

    def page_browse(self, path: str = "/", storage: str = "local") -> dict[str, Any]:
        self._browse_path = path or "/"
        self._browse_storage = storage or "local"
        return {"success": True, "message": "ok"}

    def page_select(self, field: str, path: str, storage: str = "local") -> dict[str, Any]:
        if field not in {"watch_dir", "strm_output_dir", "target_115_dir"}:
            return {"success": False, "message": "invalid field"}
        config = normalize_config(getattr(self, "_config", {}))
        config[field] = path or ""
        self._config = config
        if hasattr(self, "update_config"):
            self.update_config(config)
        self._add_log("info", f"已选择 {field}: {path or ''}", "config")
        return {"success": True, "message": "ok"}

    def scan_once(self) -> list[dict[str, str]]:
        config = normalize_config(getattr(self, "_config", {}))
        if not config["enabled"]:
            self._last_results = []
            self._add_log("info", "插件未启用，跳过扫描", "scan")
            return []
        watch_dir = str(config["watch_dir"]).strip()
        if not watch_dir:
            self._add_log("error", "下载监听目录为空，无法扫描", "scan")
            raise TingBookSyncError("watch_dir 不能为空")
        self._add_log("info", f"开始扫描下载监听目录：{watch_dir}", "scan")
        if config["auto_adopt_loose_audio"]:
            adopted = adopt_loose_audio_in_library(Path(watch_dir), scrape_metadata=bool(config["scrape_metadata"]))
            for item in adopted:
                self._add_log("info", f"{item.message}，来源={item.source_name}", "adopt")
        results = scan_ready_books(Path(watch_dir), write_sync=True)
        payload = []
        strm_output_dir = str(config["strm_output_dir"]).strip()
        for result in results:
            item = {
                "bookDir": str(result.book_dir),
                "taskId": result.task_id,
                "status": result.status,
                "message": result.message,
            }
            if result.status == "scanning":
                upload_result = dry_run_upload_book(result.book_dir, str(config["target_115_dir"])) if config["dry_run"] else upload_book_to_u115(result.book_dir, str(config["target_115_dir"]), str(config.get("public_base_url") or ""), str(config["play_token_secret"]))
                item["status"] = upload_result.status
                item["message"] = upload_result.message
                item["remotePath"] = upload_result.remote_path
                self._add_log("info", f"上传完成：{result.book_dir.name} -> {upload_result.remote_path}", "upload")
            if item["status"] == "uploaded" and strm_output_dir:
                episode_url_map = read_episode_url_map(result.book_dir)
                strm_result = generate_strm_files(
                    book_dir=result.book_dir,
                    output_root=Path(strm_output_dir),
                    remote_root=str(config["target_115_dir"]),
                    overwrite=bool(config["overwrite_strm"]),
                    download_root=Path(watch_dir),
                    episode_url_map=episode_url_map,
                )
                item["status"] = "strm_generated"
                item["message"] = f"strm created={strm_result.created}, skipped={strm_result.skipped}"
                item["strmPath"] = str(strm_result.output_dir)
                self._add_log("info", f"STRM 生成完成：{result.book_dir.name} created={strm_result.created}, skipped={strm_result.skipped}", "strm")
            if item["status"] == "failed":
                self._add_log("error", f"扫描失败：{result.book_dir.name}，{result.message}", "scan")
            payload.append(item)
        self._last_results = payload
        self._add_log("info", f"扫描完成：共 {len(payload)} 个结果", "scan")
        return payload

    def _add_log(self, level: str, message: str, stage: str = "runtime") -> None:
        entry = {
            "time": datetime.now(CN_TZ).isoformat(timespec="seconds"),
            "level": str(level or "info"),
            "stage": str(stage or "runtime"),
            "message": str(message or "")[:500],
        }
        logs = list(getattr(self, "_logs", []))
        logs.append(entry)
        self._logs = logs[-LOG_LIMIT:]


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(config)
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["move_completed"] = bool(normalized.get("move_completed"))
    normalized["overwrite_strm"] = bool(normalized.get("overwrite_strm"))
    normalized["auto_adopt_loose_audio"] = bool(normalized.get("auto_adopt_loose_audio", True))
    normalized["scrape_metadata"] = bool(normalized.get("scrape_metadata", False))
    normalized["dry_run"] = bool(normalized.get("dry_run", True))
    normalized["public_base_url"] = str(normalized.get("public_base_url") or "").strip().rstrip("/")
    normalized["play_token_secret"] = str(normalized.get("play_token_secret") or "").strip() or make_secret()
    normalized["scan_interval"] = max(60, int(normalized.get("scan_interval") or 300))
    normalized["min_file_count"] = max(1, int(normalized.get("min_file_count") or 1))
    return normalized


def parse_bool(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def make_secret() -> str:
    return hashlib.sha256(f"{datetime.now(CN_TZ).isoformat()}:{id(object())}".encode("utf-8")).hexdigest()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def make_play_token(pickcode: str, secret: str) -> str:
    body = b64url_encode(json.dumps({"pickcode": pickcode}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{b64url_encode(signature)}"


def verify_play_token(token: str, secret: str) -> dict[str, Any]:
    if not secret:
        raise TingBookSyncError("播放密钥未初始化")
    try:
        body, signature = str(token or "").split(".", 1)
    except ValueError as exc:
        raise TingBookSyncError("播放 token 无效") from exc
    expected = b64url_encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise TingBookSyncError("播放 token 校验失败")
    payload = json.loads(b64url_decode(body).decode("utf-8"))
    if not payload.get("pickcode"):
        raise TingBookSyncError("播放 token 缺少 pickcode")
    return payload


def public_play_url(base_url: str, token: str) -> str:
    path = f"/api/v1/plugin/TingBookSync/play/{quote(token, safe='')}"
    return f"{base_url}{path}" if base_url else path


def read_episode_url_map(book_dir: Path) -> dict[str, str]:
    path = book_dir / EPISODE_URLS_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_form_schema() -> list[dict[str, Any]]:
    return [
        {
            "component": "VForm",
            "content": [
                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}},
                {
                    "component": "VTextField",
                    "props": {
                        "model": "watch_dir",
                        "label": "下载监听目录",
                        "clearable": True,
                        "prepend-inner-icon": "mdi-folder-search-outline",
                        "hint": "请在插件详情页使用“资源存储 + 资源目录”方式选择，避免手动填写路径。",
                        "persistent-hint": True,
                    },
                },
                {
                    "component": "VTextField",
                    "props": {
                        "model": "strm_output_dir",
                        "label": "STRM 生成目录",
                        "clearable": True,
                        "prepend-inner-icon": "mdi-folder-open-outline",
                        "hint": "请在插件详情页选择；STRM 会按下载监听目录下的分类子目录自动新建分类文件夹。",
                        "persistent-hint": True,
                    },
                },
                {
                    "component": "VTextField",
                    "props": {
                        "model": "target_115_dir",
                        "label": "115 目标目录",
                        "clearable": True,
                        "prepend-inner-icon": "mdi-folder-upload-outline",
                    },
                },
                {"component": "VTextField", "props": {"model": "scan_interval", "label": "扫描间隔（秒）", "type": "number"}},
                {"component": "VTextField", "props": {"model": "min_file_count", "label": "最少音频数", "type": "number"}},
                {"component": "VSwitch", "props": {"model": "move_completed", "label": "完成后移动目录"}},
                {"component": "VSwitch", "props": {"model": "overwrite_strm", "label": "覆盖已有 STRM"}},
                {"component": "VSwitch", "props": {"model": "auto_adopt_loose_audio", "label": "自动接管散音频"}},
                {"component": "VSwitch", "props": {"model": "scrape_metadata", "label": "联网刮削补全书籍信息"}},
                {"component": "VTextField", "props": {"model": "public_base_url", "label": "MP 外部访问地址", "clearable": True, "hint": "用于写入 302 STRM，例如 http://192.168.1.10:3000；留空则写相对地址。", "persistent-hint": True}},
                {"component": "VSwitch", "props": {"model": "dry_run", "label": "Dry-run，模拟上传；关闭后真实上传 115"}},
            ],
        }
    ]


def build_page_schema(plugin: TingBookSync) -> list[dict[str, Any]]:
    page_api_base = f"plugin/{plugin.__class__.__name__}"
    config = normalize_config(getattr(plugin, "_config", {}))
    storage = str(getattr(plugin, "_browse_storage", "") or "local")
    path = str(getattr(plugin, "_browse_path", "") or "/")
    browse_result = plugin.api_browse(path=path, storage=storage, dirs_only=False)
    items = browse_result.get("items", [])
    dirs = [item for item in items if item.get("type") == "dir"]
    files = [item for item in items if item.get("type") != "dir"]
    return [
        {
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "text": "当前版本仅 dry-run：扫描、模拟上传、生成 STRM，不访问 115。下方目录浏览器使用 MP 资源目录能力，可从 / 展开选择真实目录。",
            },
        },
        {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-3"},
            "content": [
                {"component": "VCardTitle", "text": "资源目录浏览"},
                {
                    "component": "VCardText",
                    "content": [
                        {
                            "component": "VAlert",
                            "props": {
                                "type": "success" if browse_result.get("success") else "error",
                                "variant": "tonal",
                                "density": "compact",
                                "text": f"当前位置：{storage}:{path}" if browse_result.get("success") else str(browse_result.get("message") or "目录读取失败"),
                            },
                        },
                        {
                            "component": "VRow",
                            "props": {"class": "mt-2"},
                            "content": [
                                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "watch_dir", "label": "下载监听目录", "readonly": True}, "text": config["watch_dir"]}]},
                                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "strm_output_dir", "label": "STRM 生成目录", "readonly": True}, "text": config["strm_output_dir"]}]},
                                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "target_115_dir", "label": "115 目标目录", "readonly": True}, "text": config["target_115_dir"]}]},
                            ],
                        },
                        {"component": "VBtn", "props": {"class": "mr-2 mt-2", "variant": "outlined", "prependIcon": "mdi-folder-home-outline"}, "text": "回到 /", "events": {"click": {"api": f"{page_api_base}/page_browse", "method": "GET", "params": {"storage": storage, "path": "/"}}}},
                        {"component": "VBtn", "props": {"class": "mr-2 mt-2", "color": "primary", "variant": "tonal", "prependIcon": "mdi-download"}, "text": "选为下载监听目录", "events": {"click": {"api": f"{page_api_base}/page_select", "method": "GET", "params": {"field": "watch_dir", "storage": storage, "path": path}}}},
                        {"component": "VBtn", "props": {"class": "mr-2 mt-2", "color": "success", "variant": "tonal", "prependIcon": "mdi-file-link-outline"}, "text": "选为 STRM 生成目录", "events": {"click": {"api": f"{page_api_base}/page_select", "method": "GET", "params": {"field": "strm_output_dir", "storage": storage, "path": path}}}},
                        {"component": "VBtn", "props": {"class": "mt-2", "color": "warning", "variant": "tonal", "prependIcon": "mdi-folder-upload-outline"}, "text": "选为 115 目标目录", "events": {"click": {"api": f"{page_api_base}/page_select", "method": "GET", "params": {"field": "target_115_dir", "storage": storage, "path": path}}}},
                    ],
                },
                {"component": "VDivider"},
                {
                    "component": "VList",
                    "props": {"density": "compact", "lines": "one"},
                    "content": [build_directory_item(item, page_api_base, storage) for item in dirs[:100]]
                    + [{"component": "VListItem", "props": {"prependIcon": "mdi-file-outline", "subtitle": str(item.get("path") or "")}, "text": str(item.get("name") or item.get("path") or "")} for item in files[:50]],
                },
            ],
        },
    ]


def build_directory_item(item: dict[str, Any], page_api_base: str, storage: str) -> dict[str, Any]:
    path = str(item.get("path") or "")
    return {
        "component": "VListItem",
        "props": {"prependIcon": "mdi-folder-outline", "subtitle": path},
        "text": str(item.get("name") or path or "/"),
        "events": {"click": {"api": f"{page_api_base}/page_browse", "method": "GET", "params": {"storage": item.get("storage") or storage, "path": path}}},
    }


def browse_storage_path(path: str = "/", storage: str = "local", dirs_only: bool = False) -> list[dict[str, Any]]:
    try:
        from app import schemas
        from app.chain.storage import StorageChain

        fileitem = schemas.FileItem(storage=storage or "local", path=path or "/", type="dir")
        raw_items = StorageChain().list_files(fileitem, recursion=False) or []
        items = [storage_item_to_dict(item) for item in raw_items]
    except Exception:
        items = browse_local_path(path=path or "/", storage=storage or "local")
    if dirs_only:
        items = [item for item in items if item.get("type") == "dir"]
    return sorted(items, key=lambda item: (item.get("type") != "dir", str(item.get("name") or "").lower()))


def get_storage_options() -> list[dict[str, str]]:
    options: dict[str, str] = {"local": "本地", "u115": "115 网盘"}
    try:
        from app.helper.directory import DirectoryHelper

        for directory in DirectoryHelper().get_dirs():
            for attr in ("storage", "library_storage"):
                value = str(getattr(directory, attr, "") or "").strip()
                if value:
                    options.setdefault(value, storage_title(value))
    except Exception:
        pass
    return [{"title": title, "value": value} for value, title in options.items()]


def storage_title(value: str) -> str:
    return {
        "local": "本地",
        "u115": "115 网盘",
        "alist": "Alist",
        "rclone": "Rclone",
        "smb": "SMB",
        "alipan": "阿里云盘",
    }.get(value, value)


def storage_item_to_dict(item: Any) -> dict[str, Any]:
    item_type = str(getattr(item, "type", "") or "")
    path = str(getattr(item, "path", "") or "")
    name = str(getattr(item, "name", "") or path or "/")
    return {
        "storage": str(getattr(item, "storage", "") or "local"),
        "type": item_type,
        "name": name,
        "path": path,
        "isDir": item_type == "dir",
        "size": getattr(item, "size", None),
        "modifyTime": getattr(item, "modify_time", None),
    }


def browse_local_path(path: str = "/", storage: str = "local") -> list[dict[str, Any]]:
    if path in {"", "/"}:
        roots = [Path(anchor) for anchor in sorted({Path.cwd().anchor or "/"})]
    else:
        roots = [Path(path)]
    items: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            items.append({"storage": storage, "type": "file", "name": root.name, "path": str(root), "isDir": False, "size": root.stat().st_size})
            continue
        for child in root.iterdir():
            try:
                is_dir = child.is_dir()
                items.append({"storage": storage, "type": "dir" if is_dir else "file", "name": child.name, "path": str(child), "isDir": is_dir, "size": None if is_dir else child.stat().st_size})
            except OSError:
                continue
    return items


def make_task_id() -> str:
    stamp = datetime.now(CN_TZ).strftime("%Y%m%d")
    return f"tb_{stamp}_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def sanitize_filename(value: str, default: str = "未命名") -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", value).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or default


def clean_book_query(value: str) -> str:
    text = Path(value).stem if Path(value).suffix else value
    text = re.sub(r"(?i)\b(mp3|m4a|m4b|aac|flac|wav|ogg|opus|有声书|全集|完结|完整版)\b", " ", text)
    text = re.sub(r"(?i)\b\d{2,4}\s*(kbps|k|hz|m)\b", " ", text)
    text = re.sub(r"第?\s*\d+\s*[集章节回部期]?", " ", text)
    text = re.sub(r"^\s*\d+[\s._-]*", " ", text)
    text = re.sub(r"[\[\]【】()（）《》<>_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -.")
    return text or sanitize_filename(value, "未命名")


def best_effort_book_title(source: Path) -> str:
    return clean_book_query(source.name if source.is_dir() else source.stem)


def book_dir_name(title: str, author: str) -> str:
    title_part = sanitize_filename(title, "未命名")
    author_part = sanitize_filename(author, "")
    return f"{title_part} - {author_part}" if author_part else title_part


def ensure_library_dirs(library: Path) -> None:
    for name in ("staging", "syncing", "completed", "failed"):
        (library / name).mkdir(parents=True, exist_ok=True)


def find_audio_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() in AUDIO_EXTENSIONS else []
    return sorted([path for path in source.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS], key=lambda item: item.name.lower())


def episode_title_from_file(path: Path, index: int) -> str:
    title = path.stem.strip()
    title = re.sub(r"^\s*\d+[\s._-]*", "", title).strip()
    return title or f"第{index}章"


def numbered_episode_filename(index: int, source_file: Path) -> str:
    title = sanitize_filename(episode_title_from_file(source_file, index), f"第{index}章")
    return f"{index:03d} - {title}{source_file.suffix.lower()}"


def unique_destination(base: Path) -> Path:
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = base.with_name(f"{base.name} ({index})")
        if not candidate.exists():
            return candidate
    raise TingBookSyncError(f"无法创建唯一目录: {base}")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_local_book(
    source: Path,
    library: Path,
    title: str,
    author: str = "",
    narrator: str = "",
    category: str = "有声书",
    source_name: str = "manual-import",
    source_url: str = "",
    copy_files: bool = True,
) -> Path:
    if not source.exists() or not source.is_dir():
        raise TingBookSyncError(f"导入源目录不存在: {source}")
    audio_files = find_audio_files(source)
    if not audio_files:
        raise TingBookSyncError(f"导入源目录未找到音频文件: {source}")
    ensure_library_dirs(library)
    final_dir = unique_destination(library / "staging" / book_dir_name(title, author))
    tmp_dir = final_dir.with_name(f"{final_dir.name}.tmp")
    tmp_dir.mkdir(parents=True)
    episodes = []
    try:
        for index, audio_file in enumerate(audio_files, start=1):
            filename = numbered_episode_filename(index, audio_file)
            destination = tmp_dir / filename
            if copy_files:
                shutil.copy2(audio_file, destination)
            else:
                shutil.move(str(audio_file), destination)
            episodes.append({"index": index, "title": episode_title_from_file(audio_file, index), "filename": filename, "duration": 0, "size": destination.stat().st_size})
        metadata = {
            "schemaVersion": SCHEMA_VERSION,
            "taskId": make_task_id(),
            "title": title.strip(),
            "author": author.strip(),
            "narrator": narrator.strip(),
            "category": category.strip() or "有声书",
            "source": {"name": source_name.strip() or "manual-import", "url": source_url.strip()},
            "episodes": episodes,
            "cover": "",
            "createdAt": now_iso(),
        }
        validate_metadata(metadata, tmp_dir)
        write_json(tmp_dir / METADATA_FILENAME, metadata)
        tmp_dir.rename(final_dir)
        (final_dir / READY_FILENAME).write_text(now_iso() + "\n", encoding="utf-8")
        return final_dir
    except Exception:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise


def fetch_json_url(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "TingBookSync/0.1 metadata lookup"})
    with urlopen(request, timeout=8) as response:
        payload = response.read(1024 * 1024)
    return json.loads(payload.decode("utf-8"))


def metadata_from_query(query: str, enable_network: bool = True) -> MetadataCandidate | None:
    cleaned = clean_book_query(query)
    if not cleaned or not enable_network:
        return None
    for provider in (search_google_books, search_open_library):
        try:
            candidate = provider(cleaned)
        except Exception:
            candidate = None
        if candidate:
            return candidate
    return None


def search_google_books(query: str) -> MetadataCandidate | None:
    payload = fetch_json_url("https://www.googleapis.com/books/v1/volumes?" + urlencode({"q": query, "maxResults": 5, "printType": "books"}))
    for item in payload.get("items") or []:
        info = item.get("volumeInfo") or {}
        title = str(info.get("title") or "").strip()
        if not title:
            continue
        authors = info.get("authors") or []
        author = "、".join(str(author).strip() for author in authors if str(author).strip())
        categories = info.get("categories") or []
        links = info.get("imageLinks") or {}
        return MetadataCandidate(title, author, "", str(categories[0]).strip() if categories else "有声书", "google-books", str(info.get("infoLink") or item.get("selfLink") or ""), str(links.get("thumbnail") or links.get("smallThumbnail") or ""), 0.85)
    return None


def search_open_library(query: str) -> MetadataCandidate | None:
    payload = fetch_json_url("https://openlibrary.org/search.json?" + urlencode({"q": query, "limit": 5}))
    for item in payload.get("docs") or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        authors = item.get("author_name") or []
        author = "、".join(str(author).strip() for author in authors[:3] if str(author).strip())
        key = str(item.get("key") or "").strip()
        cover = f"https://covers.openlibrary.org/b/id/{item['cover_i']}-L.jpg" if item.get("cover_i") else ""
        return MetadataCandidate(title, author, "", "有声书", "open-library", f"https://openlibrary.org{key}" if key else "", cover, 0.75)
    return None


def adopt_loose_audio(source: Path, library: Path, scrape_metadata: bool = False, copy_files: bool = False) -> AdoptResult:
    if not source.exists():
        raise TingBookSyncError(f"接管源不存在: {source}")
    if source.name in {"staging", "syncing", "completed", "failed"}:
        return AdoptResult(source, None, "ignored", "系统目录跳过", "", "")
    if source.is_dir() and ((source / READY_FILENAME).exists() or source.name.endswith(".tmp")):
        return AdoptResult(source, None, "ignored", "ready 或临时目录跳过", "", "")
    if not find_audio_files(source):
        return AdoptResult(source, None, "ignored", "未找到散音频", "", "")
    fallback_title = best_effort_book_title(source)
    candidate = metadata_from_query(fallback_title, enable_network=scrape_metadata) if scrape_metadata else None
    title = candidate.title if candidate and candidate.title else fallback_title
    author = candidate.author if candidate else ""
    narrator = candidate.narrator if candidate else ""
    category = candidate.category if candidate and candidate.category else "有声书"
    source_name = candidate.source_name if candidate else "loose-audio"
    source_url = candidate.source_url if candidate else ""
    import_source = source
    temp_source: Path | None = None
    if source.is_file():
        temp_source = unique_destination(source.with_name(f"{source.stem}.adopt.tmp"))
        temp_source.mkdir()
        if copy_files:
            shutil.copy2(source, temp_source / source.name)
        else:
            shutil.move(str(source), temp_source / source.name)
        import_source = temp_source
    try:
        book_dir = import_local_book(import_source, library, title, author, narrator, category, source_name, source_url, copy_files=copy_files)
    finally:
        if temp_source and temp_source.exists():
            shutil.rmtree(temp_source)
    if candidate and candidate.cover:
        metadata_path = book_dir / METADATA_FILENAME
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["cover"] = candidate.cover
        write_json(metadata_path, metadata)
    return AdoptResult(source, book_dir, "adopted", f"散音频已接管：{title}", title, source_name)


def adopt_loose_audio_in_library(library: Path, scrape_metadata: bool = False) -> list[AdoptResult]:
    if not library.exists():
        raise TingBookSyncError(f"监听目录不存在: {library}")
    ensure_library_dirs(library)
    results = []
    for child in sorted(library.iterdir(), key=lambda item: item.name.lower()):
        if child.name in {"staging", "syncing", "completed", "failed"} or child.name.endswith(".tmp"):
            continue
        if child.is_dir() and (child / READY_FILENAME).exists():
            continue
        if child.is_file() and child.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        result = adopt_loose_audio(child, library, scrape_metadata=scrape_metadata, copy_files=False)
        if result.status == "adopted":
            results.append(result)
    return results


def load_metadata(book_dir: Path) -> dict:
    metadata_path = book_dir / METADATA_FILENAME
    if not metadata_path.exists():
        raise TingBookSyncError("缺少 metadata.json")
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TingBookSyncError(f"metadata.json 解析失败: {exc.msg}") from exc


def validate_metadata(metadata: dict, book_dir: Path) -> None:
    required = ["schemaVersion", "taskId", "title", "author", "narrator", "category", "source", "episodes", "cover", "createdAt"]
    for field in required:
        if field not in metadata:
            raise TingBookSyncError(f"metadata 缺少字段: {field}")
    if metadata["schemaVersion"] != SCHEMA_VERSION:
        raise TingBookSyncError(f"不支持的 schemaVersion: {metadata['schemaVersion']}")
    if not isinstance(metadata["episodes"], list) or not metadata["episodes"]:
        raise TingBookSyncError("episodes 至少需要 1 条")
    for episode in metadata["episodes"]:
        for field in ("index", "title", "filename", "duration", "size"):
            if field not in episode:
                raise TingBookSyncError(f"episode 缺少字段: {field}")
        filename = str(episode["filename"])
        if Path(filename).is_absolute() or ".." in Path(filename).parts:
            raise TingBookSyncError(f"episode 文件名必须是安全相对路径: {filename}")
        if not (book_dir / filename).exists():
            raise TingBookSyncError(f"episode 文件不存在: {filename}")


def sync_payload(task_id: str, status: str, stage: str, message: str = "", provider: str = "", remote_path: str = "", strm_path: str = "") -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": task_id,
        "status": status,
        "stage": stage,
        "provider": provider,
        "remotePath": remote_path,
        "strmPath": strm_path,
        "message": message[:500],
        "updatedAt": now_iso(),
    }


def scan_ready_books(library: Path, write_sync: bool = False) -> list[ScanResult]:
    staging = library / "staging"
    scan_root = staging if staging.exists() else library
    if not scan_root.exists():
        raise TingBookSyncError(f"监听目录不存在: {scan_root}")
    results: list[ScanResult] = []
    for ready_file in sorted(scan_root.rglob(READY_FILENAME), key=lambda item: str(item.parent).lower()):
        book_dir = ready_file.parent
        if book_dir.name.endswith(".tmp"):
            continue
        if any(part.endswith(".tmp") for part in book_dir.relative_to(scan_root).parts):
            continue
        task_id = ""
        try:
            metadata = load_metadata(book_dir)
            task_id = str(metadata.get("taskId", ""))
            validate_metadata(metadata, book_dir)
            status = "scanning"
            message = "ready directory is valid"
            if write_sync:
                write_json(book_dir / SYNC_FILENAME, sync_payload(task_id, status, "dry_run", message))
        except TingBookSyncError as exc:
            status = "failed"
            message = str(exc)
            if write_sync:
                write_json(book_dir / SYNC_FILENAME, sync_payload(task_id, status, "scan_failed", message))
        results.append(ScanResult(book_dir, task_id, status, message))
    return results


def read_sync_status(book_dir: Path) -> dict:
    sync_path = book_dir / SYNC_FILENAME
    if not sync_path.exists():
        return {}
    try:
        return json.loads(sync_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TingBookSyncError(f".tingbook.sync.json 解析失败: {exc.msg}") from exc


def dry_run_upload_book(book_dir: Path, remote_root: str, provider: str = "115", force: bool = False) -> UploadResult:
    metadata = load_metadata(book_dir)
    validate_metadata(metadata, book_dir)
    task_id = str(metadata["taskId"])
    sync_status = str(read_sync_status(book_dir).get("status", ""))
    remote_path = f"{remote_root.rstrip('/')}/{book_dir.name}"
    if not force and sync_status in {"uploaded", "strm_generated"}:
        return UploadResult(book_dir, task_id, sync_status, remote_path, f"upload dry-run skipped: existing status={sync_status}", False)
    write_json(book_dir / SYNC_FILENAME, sync_payload(task_id, "uploading", "uploading", "upload dry-run started", provider, remote_path))
    write_json(book_dir / SYNC_FILENAME, sync_payload(task_id, "uploaded", "uploaded", "upload dry-run completed", provider, remote_path))
    return UploadResult(book_dir, task_id, "uploaded", remote_path, "upload dry-run completed", True)


def upload_book_to_u115(book_dir: Path, remote_root: str, public_base_url: str, secret: str) -> UploadResult:
    try:
        from app.chain.storage import StorageChain
    except Exception as exc:
        raise TingBookSyncError(f"无法导入 MoviePilot 存储链：{exc}") from exc
    metadata = load_metadata(book_dir)
    task_id = str(metadata["taskId"])
    target_dir = StorageChain().get_folder("u115", Path(remote_root) / book_dir.name)
    if not target_dir:
        raise TingBookSyncError(f"无法创建或获取 115 目标目录: {remote_root}/{book_dir.name}")
    remote_path = f"{remote_root.rstrip('/')}/{book_dir.name}"
    write_json(book_dir / SYNC_FILENAME, sync_payload(task_id, "uploading", "uploading", "115 上传开始", "115", remote_path))
    episode_urls: dict[str, str] = {}
    for episode in sorted(metadata["episodes"], key=lambda item: int(item["index"])):
        filename = str(episode["filename"])
        uploaded = StorageChain().upload_file(target_dir, book_dir / filename, new_name=Path(filename).name)
        if not uploaded:
            raise TingBookSyncError(f"115 上传失败: {filename}")
        pickcode = str(getattr(uploaded, "pickcode", "") or "")
        if not pickcode:
            detail = StorageChain().get_file_item("u115", Path(str(getattr(uploaded, "path", "") or Path(target_dir.path) / Path(filename).name)))
            pickcode = str(getattr(detail, "pickcode", "") or "")
        if not pickcode:
            raise TingBookSyncError(f"115 上传成功但未返回 pickcode: {filename}")
        episode_urls[filename] = public_play_url(public_base_url, make_play_token(pickcode, secret))
    write_json(book_dir / EPISODE_URLS_FILENAME, episode_urls)
    write_json(book_dir / SYNC_FILENAME, sync_payload(task_id, "uploaded", "uploaded", "115 上传完成", "115", remote_path))
    return UploadResult(book_dir, task_id, "uploaded", remote_path, "115 upload completed", True)


def resolve_u115_download_url(pickcode: str) -> str:
    try:
        from app.modules.filemanager.storages.u115 import U115Pan
    except Exception as exc:
        raise TingBookSyncError(f"无法导入 u115 存储模块：{exc}") from exc
    client = U115Pan()
    download_info = client._request_api("POST", "/open/ufile/downurl", "data", data={"pick_code": pickcode})
    if not download_info:
        raise TingBookSyncError("115 下载链接获取失败")
    location = list(download_info.values())[0].get("url", {}).get("url")
    if not location:
        raise TingBookSyncError("115 下载链接为空")
    return str(location)


def strm_filename(filename: str) -> str:
    source = Path(filename)
    if source.is_absolute() or ".." in source.parts:
        raise TingBookSyncError(f"episode 文件名必须是安全相对路径: {filename}")
    return source.stem + ".strm"


def join_remote_path(remote_root: str, book_name: str, filename: str) -> str:
    root = remote_root.strip().replace("\\", "/").rstrip("/")
    if not root:
        root = "/"
    if not root.startswith("/"):
        root = "/" + root
    path = Path(filename)
    if path.is_absolute() or ".." in path.parts:
        raise TingBookSyncError(f"路径必须是安全相对路径: {filename}")
    return f"{root}/{book_name}/{'/'.join(path.parts)}"


def join_remote_root(remote_root: str, *parts: str) -> str:
    root = remote_root.strip().replace("\\", "/").rstrip("/")
    if not root:
        root = "/"
    if not root.startswith("/"):
        root = "/" + root
    safe_parts = []
    for part in parts:
        path = Path(str(part))
        if path.is_absolute() or ".." in path.parts:
            raise TingBookSyncError(f"路径必须是安全相对路径: {part}")
        value = "/".join(path.parts).strip("/")
        if value:
            safe_parts.append(value)
    return "/".join([root.rstrip("/"), *safe_parts]) or "/"


def relative_category_dir(book_dir: Path, download_root: Path) -> Path:
    scan_root = download_root / "staging" if (download_root / "staging").exists() else download_root
    try:
        relative_parent = book_dir.parent.relative_to(scan_root)
    except ValueError:
        return Path()
    if str(relative_parent) in {"", "."}:
        return Path()
    return relative_parent


def generate_strm_files(book_dir: Path, output_root: Path, remote_root: str, overwrite: bool = False, provider: str = "115", download_root: Path | None = None, episode_url_map: dict[str, str] | None = None) -> StrmResult:
    metadata = load_metadata(book_dir)
    validate_metadata(metadata, book_dir)
    category_dir = relative_category_dir(book_dir, download_root) if download_root else Path()
    output_dir = output_root / category_dir / book_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    remote_category_root = join_remote_root(remote_root, *category_dir.parts)
    created = 0
    skipped = 0
    for episode in sorted(metadata["episodes"], key=lambda item: int(item["index"])):
        target = output_dir / strm_filename(str(episode["filename"]))
        if target.exists() and not overwrite:
            skipped += 1
            continue
        filename = str(episode["filename"])
        target.write_text(((episode_url_map or {}).get(filename) or join_remote_path(remote_category_root, book_dir.name, filename)) + "\n", encoding="utf-8")
        created += 1
    message = f"strm dry-run generated: created={created}, skipped={skipped}"
    remote_book_path = join_remote_root(remote_category_root, book_dir.name)
    write_json(
        book_dir / SYNC_FILENAME,
        sync_payload(str(metadata["taskId"]), "strm_generated", "strm_generated", message, provider, remote_book_path, str(output_dir)),
    )
    return StrmResult(book_dir, output_dir, created, skipped)
