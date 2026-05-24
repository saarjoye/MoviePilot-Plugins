from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

try:
    from app.plugins import _PluginBase
except Exception:  # pragma: no cover - local import fallback
    class _PluginBase:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._config: dict[str, Any] = {}


PLUGIN_VERSION = "0.1.3"
SCHEMA_VERSION = 1
READY_FILENAME = ".tingbook.ready"
SYNC_FILENAME = ".tingbook.sync.json"
METADATA_FILENAME = "metadata.json"
CN_TZ = timezone(timedelta(hours=8))


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


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "watch_dir": "",
    "strm_output_dir": "",
    "target_115_dir": "/Audiobooks",
    "scan_interval": 300,
    "move_completed": True,
    "overwrite_strm": False,
    "min_file_count": 1,
    "dry_run": True,
}


class TingBookSync(_PluginBase):
    plugin_name = "听书同步"
    plugin_desc = "扫描听书系统下载监听目录，dry-run 上传并按分类生成 STRM。"
    plugin_icon = "tingbooksync.png"
    plugin_version = "0.1.3"
    plugin_author = "wYw"
    plugin_config_prefix = "tingbooksync_"
    plugin_order = 100
    auth_level = 1

    def init_plugin(self, config: dict[str, Any] | None = None) -> None:
        self._config = normalize_config(config or {})
        self._last_results: list[dict[str, str]] = []

    def get_state(self) -> bool:
        return bool(self._config.get("enabled"))

    def get_command(self) -> list[dict[str, Any]]:
        return []

    def get_api(self) -> list[dict[str, Any]]:
        return [
            {"path": "/state", "endpoint": self.api_state, "methods": ["GET"], "summary": "读取听书同步配置", "auth": "bear"},
            {"path": "/browse", "endpoint": self.api_browse, "methods": ["GET"], "summary": "浏览 MP 资源目录", "auth": "bear"},
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

    def get_page(self) -> list[dict[str, Any]]:
        return build_page_schema(self)

    def stop_service(self) -> None:
        self._last_results = []

    def api_state(self) -> dict[str, Any]:
        return {
            "success": True,
            "config": normalize_config(getattr(self, "_config", {})),
            "last_results": list(getattr(self, "_last_results", [])),
            "dry_run_only": True,
        }

    def api_browse(self, path: str = "/", storage: str = "local", dirs_only: bool | str = False) -> dict[str, Any]:
        try:
            items = browse_storage_path(path=path or "/", storage=storage or "local", dirs_only=parse_bool(dirs_only))
            return {"success": True, "storage": storage or "local", "path": path or "/", "items": items}
        except Exception as exc:
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
        return {"success": True, "message": "ok"}

    def scan_once(self) -> list[dict[str, str]]:
        config = normalize_config(getattr(self, "_config", {}))
        if not config["enabled"]:
            self._last_results = []
            return []
        if not config["dry_run"]:
            raise TingBookSyncError("当前插件版本只允许 dry_run=true")
        watch_dir = str(config["watch_dir"]).strip()
        if not watch_dir:
            raise TingBookSyncError("watch_dir 不能为空")
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
                upload_result = dry_run_upload_book(result.book_dir, str(config["target_115_dir"]))
                item["status"] = upload_result.status
                item["message"] = upload_result.message
                item["remotePath"] = upload_result.remote_path
            if item["status"] == "uploaded" and strm_output_dir:
                strm_result = generate_strm_files(
                    book_dir=result.book_dir,
                    output_root=Path(strm_output_dir),
                    remote_root=str(config["target_115_dir"]),
                    overwrite=bool(config["overwrite_strm"]),
                    download_root=Path(watch_dir),
                )
                item["status"] = "strm_generated"
                item["message"] = f"strm created={strm_result.created}, skipped={strm_result.skipped}"
                item["strmPath"] = str(strm_result.output_dir)
            payload.append(item)
        self._last_results = payload
        return payload


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(config)
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["move_completed"] = bool(normalized.get("move_completed"))
    normalized["overwrite_strm"] = bool(normalized.get("overwrite_strm"))
    normalized["dry_run"] = bool(normalized.get("dry_run", True))
    normalized["scan_interval"] = max(60, int(normalized.get("scan_interval") or 300))
    normalized["min_file_count"] = max(1, int(normalized.get("min_file_count") or 1))
    return normalized


def parse_bool(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
                        "hint": "可在插件详情页使用 MP 资源目录浏览选择；当前字段保存最终路径。",
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
                        "hint": "STRM 将按下载监听目录下的分类子目录自动新建分类文件夹。",
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
                {"component": "VSwitch", "props": {"model": "dry_run", "label": "Dry-run，模拟上传并生成 STRM"}},
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


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def generate_strm_files(book_dir: Path, output_root: Path, remote_root: str, overwrite: bool = False, provider: str = "115", download_root: Path | None = None) -> StrmResult:
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
        target.write_text(join_remote_path(remote_category_root, book_dir.name, str(episode["filename"])) + "\n", encoding="utf-8")
        created += 1
    message = f"strm dry-run generated: created={created}, skipped={skipped}"
    remote_book_path = join_remote_root(remote_category_root, book_dir.name)
    write_json(
        book_dir / SYNC_FILENAME,
        sync_payload(str(metadata["taskId"]), "strm_generated", "strm_generated", message, provider, remote_book_path, str(output_dir)),
    )
    return StrmResult(book_dir, output_dir, created, skipped)
