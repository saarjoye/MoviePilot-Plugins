"""
DirUpload115 —— 监控本地目录，识别到「下载完成」就把整个目录上传到 115 网盘。

设计要点（与 MoviePilot 原生整理链完全解耦）：
1. 不走 TMDB、不识别、不重命名、不刮削 —— 只要目录「静置稳定」且含视频文件就上传；
2. 上传复用宿主已有的存储实现（p115disk 提供的 u115 存储模块），本插件里没有任何 115 协议代码；
3. 幂等：每个目录写 `.upload115.state`，记录已上传文件；目标已存在同名同大小的文件则跳过；
4. 上传完成后可选钩子：调 CloudMediaSync 增量同步（Emby 刷新由 CMS 负责，插件不重复触发）。
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from app.chain.storage import StorageChain
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase

# 触发上传的视频扩展名（可按需在配置里覆盖）
DEFAULT_VIDEO_EXT = ".mp4,.mkv,.ts,.flv,.m4v"
# 只上传到 115 的扩展名（默认仅视频；NFO/封面等留在本地 strm 目录）
DEFAULT_UPLOAD_EXT = ".mp4,.mkv,.ts,.flv,.m4v"
# 随片文件：不上传 115，而是复制到本地 strm 目录供 Emby 本地刮削
DEFAULT_SIDECAR_EXT = ".nfo,.jpg,.jpeg,.png,.webp,.ass,.srt,.vtt"
# 状态文件名（放在被监控的媒体目录里，不会被上传）
STATE_FILE = ".upload115.state"
# 正在上传的互斥标记
LOCK_FILE = ".upload115.lock"


class DirUpload115(_PluginBase):
    # 插件元数据（v3 插件页/索引需要）
    plugin_name = "目录监控上传115"
    plugin_desc = "监控本地目录，目录稳定后整目录上传到 115 网盘，不依赖 TMDB 识别"
    plugin_icon = "upload.png"
    plugin_version = "1.0.0"
    plugin_author = "DirUpload115"
    plugin_config_prefix = "dirupload115_"
    plugin_order = 21
    auth_level = 2

    def __init__(self) -> None:
        super().__init__()
        self._enabled: bool = False
        self._watch_dirs: List[Path] = []
        self._target_storage: str = "u115"
        self._target_root: str = "/B站"
        self._stable_seconds: int = 120
        self._video_ext: List[str] = []
        self._upload_ext: List[str] = []        # 只把这些扩展名传到 115
        self._sidecar_ext: List[str] = []       # 这些留在本地 strm 目录
        self._rename_enabled: bool = False
        self._rename_template: str = "{title}"
        self._remote_name_template: str = ""    # 115/strm 的条目名模板，如 {upper} - {series} - {title}
        self._series_name: str = ""             # 覆盖「系列名」（默认取父目录名）
        self._series_mode: bool = False         # 课程→剧集模式：一季 N 集 + tvshow.nfo
        self._show_template: str = "{upper} - {series}"      # 剧集（show）目录名
        self._ep_template: str = "{show} - S{season:02}E{ep:02} - {title}"  # 单集文件名
        self._season: int = 1
        self._series_hints: Dict[str, str] = {}   # 扫描时记录的「条目目录 → 系列名」
        self._upper_name: str = ""              # 覆盖「UP 名」（默认取 NFO 里的 actor/role）
        self._delete_mode: str = "none"        # none / recycle / delete
        self._recycle_root: str = ""            # recycle 模式下的回收目录（空=用插件数据目录）
        self._strm_root: str = ""               # CMS 产出的 strm 根目录（对应 target_root）
        self._ready_mode: str = "strm"          # strm / storage / none：如何判定「可以删本地」
        self._strm_timeout: int = 1800          # 等 strm/Emby 就绪的最长容忍（秒）
        self._emby_url: str = ""                # ready_mode=emby 时需要
        self._emby_key: str = ""
        self._cms_base_url: str = ""
        self._cms_token: str = ""
        self._interval_seconds: int = 300
        self._run_lock = Lock()
        self._storage: Optional[StorageChain] = None

    # ------------------------------------------------------------------ 生命周期

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """生效配置"""
        config = config if config is not None else (self.get_config() or {})
        if config:
            self.update_config(config)

        self._enabled = bool(config.get("enabled"))
        # 每行格式：本地路径 => 115 上的相对子路径（后半段可省略，默认用本地目录名）
        self._watch_dirs = []
        for line in str(config.get("watch_dirs") or "").replace(";", "\n").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=>" in line:
                local, _, remote = line.partition("=>")
                local, remote = local.strip(), remote.strip().strip("/")
            else:
                local, remote = line, ""
            if not local:
                continue
            path = Path(local)
            self._watch_dirs.append({"local": path, "remote": remote or path.name})
        self._target_storage = (config.get("target_storage") or "u115").strip()
        self._target_root = "/" + str(config.get("target_root") or "/B站").strip().strip("/")
        self._stable_seconds = int(config.get("stable_seconds") or 120)
        self._video_ext = [
            e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
            for e in str(config.get("video_ext") or DEFAULT_VIDEO_EXT).split(",")
            if e.strip()
        ]
        # 只把视频传上 115；NFO/封面/弹幕留在本地 strm 目录
        self._upload_ext = [
            e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
            for e in str(config.get("upload_ext") or DEFAULT_UPLOAD_EXT).split(",")
            if e.strip()
        ]
        self._sidecar_ext = [
            e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
            for e in str(config.get("sidecar_ext") or DEFAULT_SIDECAR_EXT).split(",")
            if e.strip()
        ]
        # 重命名必须在上传前做：115 上的文件名会被 CMS 原样映射成 strm 文件名，事后改名 strm 就断
        self._rename_enabled = bool(config.get("rename_enabled"))
        self._rename_template = str(config.get("rename_template") or "{title}").strip() or "{title}"
        # 115 / strm 上的条目名（CMS 会镜像 115 目录结构，所以这里定的名字就是 Emby 里看到的）
        self._remote_name_template = str(config.get("remote_name_template") or "").strip()
        self._series_name = str(config.get("series_name") or "").strip()
        self._upper_name = str(config.get("upper_name") or "").strip()
        # 课程→剧集模式
        self._series_mode = bool(config.get("series_mode"))
        self._show_template = str(config.get("show_template") or "{upper} - {series}").strip()
        self._ep_template = str(
            config.get("episode_template") or "{show} - S{season:02}E{ep:02} - {title}"
        ).strip()
        self._season = max(1, int(config.get("season") or 1))
        # 上传成功后如何处理本地文件：none 保留 / recycle 移到回收目录 / delete 直接删除
        self._delete_mode = str(config.get("delete_mode") or "none").strip().lower()
        if self._delete_mode not in ("none", "recycle", "delete"):
            self._delete_mode = "none"
        # 兼容旧配置 delete_local
        if config.get("delete_local"):
            self._delete_mode = "delete"
        self._recycle_root = str(config.get("recycle_root") or "").strip()
        # 默认用「strm 是否已生成」来判定可以删本地：不访问 115，也就不吃 115 的风控
        self._ready_mode = str(config.get("ready_mode") or "strm").strip().lower()
        if self._ready_mode not in ("strm", "emby", "storage", "none"):
            self._ready_mode = "strm"
        self._strm_root = str(config.get("strm_root") or "").strip()
        self._strm_timeout = max(60, int(config.get("strm_timeout_seconds") or 1800))
        self._emby_url = str(config.get("emby_url") or "").strip()
        self._emby_key = str(config.get("emby_api_key") or "").strip()
        self._cms_base_url = str(config.get("cms_base_url") or "").strip().rstrip("/")
        self._cms_token = str(config.get("cms_token") or "").strip()
        self._interval_seconds = max(60, int(config.get("interval_seconds") or 300))
        # 注意：StorageChain 不能在应用组合根就绪前实例化（实测报 "Chain 运行上下文尚未由启动组合根配置"），
        # 所以这里不创建，等真正用的时候再懒加载（_storage 为 None 时各处会现场创建）
        self._storage = None

        if self._enabled:
            logger.info(
                f"【{self.plugin_name}】已启用：监控 {len(self._watch_dirs)} 个目录 → "
                f"{self._target_storage}:{self._target_root}，稳定阈值 {self._stable_seconds}s，"
                f"周期 {self._interval_seconds}s"
            )

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self) -> None:
        """退出清理（本插件无需常驻资源）"""
        logger.info(f"【{self.plugin_name}】已停止")

    # ------------------------------------------------------------------ 定时任务

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时服务：周期扫描"""
        if not self._enabled:
            return []
        return [
            {
                "id": "DirUpload115Scan",
                "name": "目录监控上传115",
                "trigger": "interval",
                "func": self.scan_once,
                "kwargs": {"seconds": self._interval_seconds},
            }
        ]

    # ------------------------------------------------------------------ API

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/scan",
                "endpoint": self.api_scan,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即扫描一轮",
                "description": "手动触发一次目录扫描与上传，返回本轮处理结果",
            },
            {
                "path": "/hook",
                "endpoint": self.api_hook,
                "methods": ["POST", "GET"],
                "auth": "apikey",
                "summary": "外部触发（给 bili-sync webhook 用）",
                "description": "用 API_TOKEN 调用即可立即跑一轮扫描；返回值与本轮处理结果一致",
            },
            {
                "path": "/pending",
                "endpoint": self.api_pending,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "待上传/已上传清单",
                "description": "返回各监控目录下每个子目录的状态（待上传/上传中/已完成/失败）",
            },
        ]

    def api_scan(self) -> Any:
        """手动触发扫描"""
        from app.schemas import Response

        try:
            result = self.scan_once()
            return Response(success=True, message="已执行一轮扫描", data=result)
        except Exception as e:  # noqa: BLE001
            logger.error(f"【{self.plugin_name}】手动扫描失败：{e}")
            return Response(success=False, message=str(e))

    def api_hook(self) -> Any:
        """
        外部触发入口（auth=apikey）：bili-sync 下载完成 → webhook 打这里 → 立即扫一轮。
        与 api_scan 的区别只是鉴权方式：这个端点认 API_TOKEN，方便容器间调用。
        """
        from app.schemas import Response

        try:
            result = self.scan_once()
            return Response(success=True, message="已执行一轮扫描", data=result)
        except Exception as e:  # noqa: BLE001
            logger.error(f"【{self.plugin_name}】webhook 触发扫描失败：{e}")
            return Response(success=False, message=str(e))

    def api_pending(self) -> Any:
        """查看状态清单"""
        from app.schemas import Response

        return Response(success=True, message="ok", data=self.collect_status())

    # ------------------------------------------------------------------ 核心：扫描

    def scan_once(self) -> Dict[str, Any]:
        """
        扫描监控目录并处理每个媒体条目。

        剧集模式（series_mode）下支持**自动识别系列层级**：用户只需要把监控目录指到
        「合集的上一层」（如 /data/bili/合集），插件自己判断某个子目录是「系列容器」
        还是「一集」。这样用户不需要手抄带 `|`、`/` 等非法字符的目录名。
        """
        summary: Dict[str, Any] = {
            "scanned": 0, "uploaded": [], "waiting": [], "skipped": [], "failed": [],
        }
        if not self._enabled:
            return summary
        if not self._run_lock.acquire(blocking=False):
            logger.warning(f"【{self.plugin_name}】上一轮仍在执行，跳过本轮")
            return summary

        try:
            for spec in self._watch_dirs:
                watch: Path = spec["local"]
                if not watch.exists():
                    logger.warning(f"【{self.plugin_name}】监控目录不存在：{watch}")
                    continue
                for item in self._iter_entries(spec):
                    summary["scanned"] += 1
                    try:
                        outcome = self._handle_media_dir(spec, item)
                        summary[outcome].append(str(item))
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"【{self.plugin_name}】处理 {item} 失败：{e}")
                        summary["failed"].append(f"{item}: {e}")
        finally:
            self._run_lock.release()

        if summary["uploaded"] or summary["waiting"] or summary["failed"]:
            logger.info(
                f"【{self.plugin_name}】本轮结果：扫描 {summary['scanned']}，"
                f"完成 {len(summary['uploaded'])}，等 strm {len(summary['waiting'])}，"
                f"跳过 {len(summary['skipped'])}，失败 {len(summary['failed'])}"
            )
        return summary

    def _iter_entries(self, spec: Dict[str, Any]) -> List[Path]:
        """
        产出要处理的「媒体条目」目录列表，剧集模式下顺带记下它属于哪个系列。

        普通模式：监控目录的每个一级子目录 = 一个条目。
        剧集模式：若某个一级子目录下面还有「含视频的子目录」，说明它是系列容器
                 （= bili-sync 的合集目录），于是把它的每个子目录当作一集；
                 否则把这个一级子目录本身当作一集（兼容「直接监控合集目录」的旧配置）。
        """
        watch: Path = spec["local"]
        entries: List[Path] = []
        children = [
            d for d in sorted(watch.iterdir()) if d.is_dir() and not d.name.startswith(".")
        ]
        if self._series_mode:
            # 判断监控目录本身是不是「系列容器」：它的子目录直接含视频、且没有再往下套
            has_nested_container = any(
                any(s.is_dir() and not s.name.startswith(".") and self._dir_has_video(s) for s in c.iterdir())
                for c in children
            )
            if not has_nested_container and any(self._dir_has_video(c) for c in children):
                # 监控目录就是合集目录 → 它的每个子目录都是一集
                for c in children:
                    self._series_hints[str(c)] = watch.name
                return children

        for d in children:
            if not self._series_mode:
                entries.append(d)
                continue
            subdirs = [s for s in sorted(d.iterdir()) if s.is_dir() and not s.name.startswith(".")]
            episode_dirs = [s for s in subdirs if self._dir_has_video(s)]
            if episode_dirs:
                # d 是系列容器（= bili-sync 的合集目录）
                for s in subdirs:
                    self._series_hints[str(s)] = d.name
                    entries.append(s)
            else:
                # 不在系列容器里的条目：它是自己的一集，系列名取自身目录名
                self._series_hints[str(d)] = d.name
                entries.append(d)
        return entries

    def _dir_has_video(self, d: Path, depth: int = 3) -> bool:
        """目录里（有限深度内）是否存在视频文件"""
        if depth <= 0:
            return False
        try:
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in self._video_ext:
                    return True
                if p.is_dir() and self._dir_has_video(p, depth - 1):
                    return True
        except OSError:
            return False
        return False

    def _rel_parts(self, spec: Dict[str, Any], media_dir: Path) -> List[str]:
        """
        决定这个条目在 115 / strm 里的相对路径。

        课程→剧集模式（series_mode）：<剧集名>/Season N —— 一合集一季、一视频一集
        普通模式：配了 remote_name_template 就用它渲染（可含 "/" 做分层），
                 否则退回「监控目录映射名 / 本地相对路径」。

        为什么名字要在这里定：115 上的目录名会被 CMS 原样镜像成 strm 目录名，
        所以上传前定的名字 == Emby 里看到的名字；而本地目录保持 bili-sync 的原样，
        不去动它的数据库记录（改了本地目录 bili-sync 会以为文件丢了重新下载）。
        """
        if self._series_mode:
            return [self._show_name(spec, media_dir), f"Season {self._season}"]
        slug = self._render_remote_name(spec, media_dir)
        if slug:
            return [p for p in slug.split("/") if p]
        parts: List[str] = []
        remote = str(spec.get("remote") or "").strip("/")
        if remote:
            parts.append(remote)
        parts.append(media_dir.relative_to(spec["local"]).as_posix())
        return parts

    # ------------------------------------------------------------------ 课程→剧集

    def _show_name(self, spec: Dict[str, Any], media_dir: Path) -> str:
        """剧集（show）目录名，默认 `UP名 - 系列名`"""
        meta = self._item_meta(spec, media_dir)
        text = self._show_template
        for key in ("upper", "series", "title", "bvid", "index"):
            text = text.replace("{" + key + "}", meta.get(key) or "")
        return _safe_stem(text)

    def _episode_no(self, spec: Dict[str, Any], media_dir: Path) -> int:
        """
        分配集号，并**持久化**下来（bvid → 集号），保证多次扫描、增量追更时集号稳定。

        首次分配规则：按同目录下各条目的 NFO 上映时间排序取序号；
        若该序号已被别的 bvid 占用，则顺延到最大集号 +1。之后一律查表命中。
        """
        meta = self._item_meta(spec, media_dir)
        bvid = meta.get("bvid") or media_dir.name
        mapping: Dict[str, Dict[str, int]] = self.get_data("series_episodes") or {}
        show = self._show_name(spec, media_dir)
        shows = mapping.get(show) or {}
        if bvid in shows:
            return int(shows[bvid])

        siblings = [
            p for p in media_dir.parent.iterdir() if p.is_dir() and not p.name.startswith(".")
        ]
        siblings.sort(key=lambda p: (self._read_nfo_meta(p).get("premiered") or "", p.name))
        names = [p.name for p in siblings]
        rank = names.index(media_dir.name) + 1 if media_dir.name in names else len(shows) + 1
        used = {int(v) for v in shows.values()}
        if rank in used:
            # 说明本地缺了排在前面的集（比如还没下完/并发乱序），只能顺延到末尾，
            # 冒号后的集不会覆盖已有编号，但顺序可能与合集页不一致 —— 记一条警告便于排查
            ep = max(used) + 1 if used else rank
            logger.warning(
                f"【{self.plugin_name}】{show} 第 {rank} 位已被占用（本地缺集？），"
                f"本次 {bvid} 顺延为第 {ep} 集；如需严格按合集顺序，先全量同步再清空 series_episodes"
            )
        else:
            ep = rank
        shows[bvid] = ep
        mapping[show] = shows
        self.save_data("series_episodes", mapping)
        logger.info(f"【{self.plugin_name}】{show} 第 {ep} 集 ← {media_dir.name}（bvid={bvid}）")
        return ep

    def _episode_stem(self, spec: Dict[str, Any], media_dir: Path, suffix: str = "") -> str:
        """单集的最终文件名（不含扩展名），剧集模式下带 SxxExx"""
        meta = self._item_meta(spec, media_dir)
        show = self._show_name(spec, media_dir)
        ep = self._episode_no(spec, media_dir)
        text = self._ep_template
        for key, val in (
            ("{show}", show),
            ("{title}", meta.get("title") or media_dir.name),
            ("{bvid}", meta.get("bvid") or ""),
            ("{season:02}", f"{self._season:02}"),
            ("{ep:02}", f"{ep:02}"),
            ("{season}", str(self._season)),
            ("{ep}", str(ep)),
        ):
            text = text.replace(key, val)
        return _safe_stem(text)

    def _item_meta(self, spec: Dict[str, Any], media_dir: Path) -> Dict[str, str]:
        """收集命名要用的字段：标题/UP名来自 NFO；系列名优先用扫描时识别出的容器名"""
        meta = self._read_nfo_meta(media_dir)
        meta.setdefault("title", media_dir.name)
        if not meta.get("upper") and self._upper_name:
            meta["upper"] = self._upper_name
        hint = self._series_hints.get(str(media_dir))
        if self._series_name:
            meta["series"] = self._series_name
        elif hint:
            # 剧集模式自动识别出的系列容器名：用户不用手抄带 | 、/ 的目录名
            meta["series"] = hint
        else:
            parent = media_dir.parent
            # 兼容「直接监控合集目录」的配置：系列名取监控目录名
            meta["series"] = spec["local"].name if parent == spec["local"] else parent.name
        meta["index"] = self._extract_index(meta.get("title") or "") or self._sibling_index(media_dir)
        return meta

    def _render_remote_name(self, spec: Dict[str, Any], media_dir: Path) -> str:
        tpl = self._remote_name_template
        if not tpl:
            return ""
        meta = self._item_meta(spec, media_dir)
        text = tpl
        for key in ("upper", "series", "title", "bvid", "index"):
            text = text.replace("{" + key + "}", meta.get(key) or "")
        # 分段清洗，允许用 "/" 做层级
        segments = [_safe_stem(p) for p in text.split("/") if p.strip()]
        return "/".join(s for s in segments if s)

    def _remote_dir(self, spec: Dict[str, Any], media_dir: Path) -> str:
        """本地目录 → 115 上的绝对路径：<target_root>/<相对路径>"""
        parts = [self._target_root.strip("/"), *self._rel_parts(spec, media_dir)]
        return "/" + "/".join(p for p in parts if p)

    def _handle_media_dir(self, spec: Dict[str, Any], media_dir: Path) -> str:
        """处理单个媒体目录，返回 summary 的键名：uploaded / skipped / failed"""
        # 1) 已完成的直接跳过
        state = self._read_state(media_dir)
        status = state.get("status")
        if status == "done":
            return "skipped"

        # 2) 稳定性判断（防止上传半成品）
        if not self._is_stable(media_dir):
            return "skipped"

        # 3) 必须有视频文件
        files = self._collect_files(media_dir)
        if not any(f.suffix.lower() in self._video_ext for f in files):
            return "skipped"

        # 4) 已上传、正在等 strm：只做就绪检查，不重复上传、也不访问 115
        if status == "waiting_strm":
            return self._finalize(spec, media_dir, state, files)

        # 5) 首次处理：加锁 → 重命名 → 只传视频 → 随片文件拷到 strm 目录 → 等 strm
        lock = media_dir / LOCK_FILE
        if lock.exists() and (time.time() - lock.stat().st_mtime) < 3600:
            logger.info(f"【{self.plugin_name}】{media_dir.name} 正在被处理，跳过")
            return "skipped"
        lock.write_text(str(time.time()), encoding="utf-8")

        try:
            # 5.1 重命名（必须在上传前：115 文件名 → CMS strm 文件名，事后改名 strm 就断）
            if self._rename_enabled:
                renamed = self._apply_rename(media_dir, files)
                if renamed:
                    files = self._collect_files(media_dir)

            upload_files = [f for f in files if f.suffix.lower() in self._upload_ext]
            sidecar_files = [
                f for f in files if f.suffix.lower() in self._sidecar_ext and f not in upload_files
            ]
            if not upload_files:
                logger.info(f"【{self.plugin_name}】{media_dir.name} 没有需要上传的文件（按 upload_ext 过滤）")
                return "skipped"

            uploaded, skipped = self._upload_dir(spec, media_dir, upload_files, state)

            # 兜底模式：直接回查 115（会多一层 115 访问，默认不启用）
            if self._ready_mode == "storage":
                ok, mismatch = self._verify_remote(spec, media_dir, upload_files)
                if not ok:
                    raise RuntimeError(
                        f"上传后回查 115 未通过（{len(mismatch)} 个文件缺失或大小不一致）：{mismatch[:3]}；"
                        f"本地文件已保留，下轮重试"
                    )

            # 5.2 随片文件（NFO/封面/弹幕/字幕）不上 115，直接放进本地 strm 目录，
            #     这样 CMS 生成 strm 并通知 Emby 时，NFO 已经就位，Emby 能本地刮削
            copied = self._copy_sidecars(spec, media_dir, sidecar_files)

            new_state = {
                **state,
                "status": "waiting_strm",
                "uploaded_at": time.time(),
                "uploaded": uploaded,
                "skipped": skipped,
                "sidecar_copied": copied,
                "file_count": len(files),
            }
            self._write_state(media_dir, new_state)
            logger.info(
                f"【{self.plugin_name}】{media_dir.name} 上传完成（视频 {len(uploaded)} 个，跳过 {len(skipped)}），"
                f"随片文件 {copied} 个已放入 strm 目录，等待 strm 就绪"
            )
            self._post_upload_actions(spec, media_dir)
            # 顺手检查一次，CMS 同步快的话这一轮就能结案
            return self._finalize(spec, media_dir, new_state, files)
        finally:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------ 重命名

    def _apply_rename(self, media_dir: Path, files: List[Path]) -> bool:
        """
        上传前重命名：`<video_name>` 模板 → 实际文件名。

        可用变量：{title} {bvid} {upper} {index} {ext}
          - title/bvid/upper 取自目录里的 NFO（bili-sync 会写 movie.nfo/tvshow.nfo）
          - index 优先取标题里的数字（第1讲→01），否则用该目录在同级中的排序号
        只处理媒体目录**第一层**的视频文件（bili-sync 单页=电影式就是我们主场景）；
        多页结构（Season 1/xxx.mp4）保持原样，避免把剧集编号搞乱。
        """
        videos = [f for f in files if f.suffix.lower() in self._video_ext and f.parent == media_dir]
        if not videos:
            return False
        meta = self._read_nfo_meta(media_dir)
        changed = False
        for video in videos:
            old_stem = video.stem
            new_stem = self._render_name(meta, old_stem, media_dir, video.suffix)
            if not new_stem or new_stem == old_stem:
                continue
            target = media_dir / f"{new_stem}{video.suffix}"
            if target.exists():
                logger.warning(f"【{self.plugin_name}】目标已存在，跳过重命名：{target.name}")
                continue
            # 视频 + 同前缀的随片文件一起改名（xxx.nfo / xxx-poster.jpg / xxx.zh-CN.ass）
            for old in [video, *[p for p in media_dir.iterdir() if p.is_file() and p.name.startswith(old_stem) and p != video]]:
                suffix_part = old.name[len(old_stem):]
                try:
                    old.rename(media_dir / f"{new_stem}{suffix_part}")
                    changed = True
                except OSError as e:  # noqa: BLE001
                    logger.warning(f"【{self.plugin_name}】重命名失败 {old.name}：{e}")
            logger.info(f"【{self.plugin_name}】重命名 {old_stem} → {new_stem}")
        return changed

    def _render_name(self, meta: Dict[str, str], old_stem: str, media_dir: Path, suffix: str) -> str:
        title = meta.get("title") or old_stem
        bvid = meta.get("bvid") or ""
        upper = meta.get("upper") or ""
        index = self._extract_index(title) or self._sibling_index(media_dir)
        text = self._rename_template
        text = text.replace("{title}", title).replace("{bvid}", bvid)
        text = text.replace("{upper}", upper).replace("{index}", index)
        text = text.replace("{ext}", suffix.lstrip("."))
        text = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", " ", text)
        text = re.sub(r"\s+", " ", text).strip().rstrip(".")
        return _safe_stem(text, fallback=old_stem)

    @staticmethod
    def _extract_index(title: str) -> str:
        """从标题里抠序号：第1讲/第 12 课/EP3 都取第一个数字，补到两位"""
        m = re.search(r"(\d{1,3})", title or "")
        if not m:
            return ""
        return f"{int(m.group(1)):02d}"

    @staticmethod
    def _sibling_index(media_dir: Path) -> str:
        try:
            siblings = sorted(p.name for p in media_dir.parent.iterdir() if p.is_dir())
            return f"{siblings.index(media_dir.name) + 1:02d}"
        except Exception:  # noqa: BLE001
            return "01"

    @staticmethod
    def _read_nfo_meta(media_dir: Path) -> Dict[str, str]:
        """从目录里的 NFO 读 title / bvid / upper（movie.nfo 与 tvshow.nfo 都兼容）"""
        meta: Dict[str, str] = {}
        for nfo in sorted(media_dir.glob("*.nfo")):
            try:
                root = ET.parse(nfo).getroot()
            except Exception:  # noqa: BLE001
                continue
            title = (root.findtext("title") or "").strip()
            if title and "title" not in meta:
                meta["title"] = title
            uid = root.find("uniqueid")
            if uid is not None and (uid.get("type") == "bilibili") and (uid.text or "").strip():
                meta.setdefault("bvid", uid.text.strip())
            role = root.findtext("actor/role")
            if role and role.strip():
                meta.setdefault("upper", role.strip())
            premiered = (root.findtext("premiered") or "").strip()
            if premiered and "premiered" not in meta:
                meta["premiered"] = premiered
            if meta.get("title"):
                break
        return meta

    def _write_tvshow_nfo(self, show_dir: Path, title: str, plot: str = "", year: str = "",
                          bvid: str = "", poster: Optional[Path] = None) -> None:
        """在剧集目录生成 tvshow.nfo（115 上不放 nfo，所以这层由插件在 strm 目录生成）"""
        show_dir.mkdir(parents=True, exist_ok=True)
        nfo = show_dir / "tvshow.nfo"
        if nfo.exists():
            return
        root = ET.Element("tvshow")
        ET.SubElement(root, "title").text = title
        if year:
            ET.SubElement(root, "year").text = year
        if plot:
            ET.SubElement(root, "plot").text = plot
        if bvid:
            uid = ET.SubElement(root, "uniqueid", {"type": "bilibili"})
            uid.text = bvid
        nfo.write_text(
            '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
            + ET.tostring(root, encoding="unicode"),
            encoding="utf-8",
        )
        logger.info(f"【{self.plugin_name}】已生成 {nfo}")
        if poster and poster.exists() and not (show_dir / "poster.jpg").exists():
            import shutil

            shutil.copy2(poster, show_dir / "poster.jpg")
            logger.info(f"【{self.plugin_name}】已生成剧集海报 {show_dir / 'poster.jpg'}")

    # ------------------------------------------------------------------ 随片文件

    def _copy_sidecars(self, spec: Dict[str, Any], media_dir: Path, sidecar_files: List[Path]) -> int:
        """
        把 NFO / 封面 / 弹幕 / 字幕复制到本地 strm 目录（不上 115）。

        普通模式：与 115 路径同构，文件名不变。
        剧集模式：单集随片进 `Season N/` 且改成 `SxxExx` 同名；
                  show 级文件（tvshow.nfo/poster.jpg/fanart.jpg）进剧集目录，
                  并在缺失时由插件生成 tvshow.nfo 与剧集海报（115 上没有这些文件）。
        """
        if not self._strm_root:
            if sidecar_files:
                logger.warning(
                    f"【{self.plugin_name}】{media_dir.name} 有 {len(sidecar_files)} 个随片文件，"
                    f"但没配置 strm 根目录，无法放置（不会上传到 115）"
                )
            return 0

        copied = 0
        if self._series_mode:
            parts = self._rel_parts(spec, media_dir)
            ep_dir = Path(self._strm_root).joinpath(*parts)
            show_dir = Path(self._strm_root).joinpath(*parts[:-1])
            ep_stem = self._episode_stem(spec, media_dir)
            videos = [
                f
                for f in self._collect_files(media_dir)
                if f.suffix.lower() in self._video_ext and f.parent == media_dir
            ]
            old_stem = videos[0].stem if videos else ""
            poster_src: Optional[Path] = None
            for src in sidecar_files:
                name = src.name
                if name in ("tvshow.nfo", "poster.jpg", "fanart.jpg"):
                    dest = show_dir / name
                elif old_stem and name.startswith(old_stem):
                    dest = ep_dir / (ep_stem + name[len(old_stem):])
                    if "-poster" in name or name.endswith("-thumb.jpg"):
                        poster_src = src
                else:
                    dest = ep_dir / name
                copied += self._safe_copy(src, dest)
            meta = self._item_meta(spec, media_dir)
            self._write_tvshow_nfo(
                show_dir,
                title=self._show_name(spec, media_dir),
                year=(meta.get("premiered") or "")[:4],
                bvid=meta.get("bvid") or "",
                poster=poster_src,
            )
            if copied:
                logger.info(
                    f"【{self.plugin_name}】{media_dir.name} 剧集模式：{copied} 个随片文件已就位"
                    f"（{parts[0]}/{parts[1]}）"
                )
            return copied

        target_dir = self._strm_dir(spec, media_dir)
        for src in sidecar_files:
            copied += self._safe_copy(src, target_dir / src.relative_to(media_dir))
        if copied:
            logger.info(f"【{self.plugin_name}】{media_dir.name} 随片文件已放入 strm 目录：{copied} 个")
        return copied

    @staticmethod
    def _safe_copy(src: Path, dest: Path) -> int:
        """复制（目标已存在且大小一致则跳过），返回是否真的复制了"""
        try:
            if dest.exists() and dest.stat().st_size == src.stat().st_size:
                return 0
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(src, dest)
            return 1
        except OSError as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】随片文件复制失败 {src.name}：{e}")
            return 0

    def _finalize(
        self, spec: Dict[str, Any], media_dir: Path, state: Dict[str, Any], files: List[Path]
    ) -> str:
        """
        结案判定，按 ready_mode 决定「什么时候算真的成功」：
          none    —— 上传即成功
          storage —— 上传后回查过 115（字节校验在 _handle_media_dir 里做）
          strm    —— CMS 已产出同名 .strm（说明 CMS 已能从 115 读到文件）
          emby    —— strm 已产出，且 Emby 里能查到对应条目（最严，多一次 Emby 查询）
        任一步不满足都继续等；超时只告警，绝不删本地。
        """
        mode = self._ready_mode
        if mode in ("none", "storage"):
            ready, missing = True, []
        else:
            ready, missing = self._strm_ready(spec, media_dir, files)
            if ready and mode == "emby":
                ready, missing = self._emby_ready(spec, media_dir, files)

        if not ready:
            waited = time.time() - float(state.get("uploaded_at") or time.time())
            what = " strm+Emby 条目" if mode == "emby" else " strm"
            if waited > self._strm_timeout and not state.get("timeout_warned"):
                logger.warning(
                    f"【{self.plugin_name}】{media_dir.name} 已上传但 {int(waited)}s 内仍没等到{what}"
                    f"（缺 {missing[:3]}）；本地保留，请检查 CMS 同步 / Emby 入库是否正常"
                )
                self._write_state(media_dir, {**state, "timeout_warned": True})
            else:
                logger.info(f"【{self.plugin_name}】{media_dir.name} 等待{what}就绪（还缺 {len(missing)} 个）")
            return "waiting"

        self._write_state(
            media_dir,
            {**state, "status": "done", "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")},
        )
        logger.info(f"【{self.plugin_name}】{media_dir.name} 判定通过（{mode}），开始清理本地")
        removed = self._cleanup_local(spec, media_dir, len(files))
        self._append_ledger(spec, media_dir, len(files), removed)
        return "uploaded"

    def _emby_ready(
        self, spec: Dict[str, Any], media_dir: Path, files: List[Path]
    ) -> Tuple[bool, List[str]]:
        """在 Emby 里逐个查找 strm 条目，全部查到才算入库完成"""
        if not self._emby_url or not self._emby_key:
            return False, ["未配置 Emby 地址或 API Key"]
        missing: List[str] = []
        for f in files:
            if f.suffix.lower() not in self._video_ext:
                continue
            rel = f.relative_to(media_dir).as_posix()
            strm_rel = rel[: -len(f.suffix)] + ".strm"
            if not self._emby_find_strm(spec, media_dir, strm_rel):
                missing.append(strm_rel)
        return (not missing), missing

    def _emby_find_strm(self, spec: Dict[str, Any], media_dir: Path, strm_rel: str) -> bool:
        """
        在 Emby 里找这条 strm。

        匹配用「相对路径后缀」而不是绝对路径：Emby 容器里看到的挂载点和插件配置的
        strm_root 往往不同（/media/strm/B站 vs D:\\strm），只比后半段才稳。
        """
        base = self._emby_url.rstrip("/")
        # 相对 strm_root 的路径，例如 watch6/入库 [BV6aa]/ep1.strm
        rel_to_root = f"{str(spec.get('remote') or '').strip('/')}/{media_dir.relative_to(spec['local']).as_posix()}/{strm_rel}".strip("/")
        stem = strm_rel.rsplit("/", 1)[-1]
        try:
            import json as _json
            import urllib.parse
            import urllib.request

            q = urllib.parse.urlencode(
                {
                    "Recursive": "true",
                    "SearchTerm": stem.rsplit(".", 1)[0],
                    "Fields": "Path",
                    "IncludeItemTypes": "Movie,Episode,Video",
                    "Limit": "50",
                }
            )
            req = urllib.request.Request(
                f"{base}/Items?{q}",
                headers={"X-Emby-Token": self._emby_key, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode("utf-8") or "null") or {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】查询 Emby 失败（按未就绪处理）：{e}")
            return False

        items = data.get("Items") or []
        norm_rel = rel_to_root.replace("\\", "/")
        for it in items:
            path = str(it.get("Path") or "").replace("\\", "/")
            if not path:
                continue
            if path.endswith("/" + norm_rel) or path.endswith(norm_rel):
                return True
        return False

    def _strm_dir(self, spec: Dict[str, Any], media_dir: Path) -> Path:
        """本地媒体目录 → CMS 的 strm 输出目录（与 115 路径严格同构：CMS 会镜像 115 结构）"""
        return Path(self._strm_root).joinpath(*self._rel_parts(spec, media_dir))

    def _strm_ready(
        self, spec: Dict[str, Any], media_dir: Path, files: List[Path]
    ) -> Tuple[bool, List[str]]:
        """检查 CMS 是否已为该目录产出 strm 文件（视频文件同名 .strm 且非空）"""
        if not self._strm_root:
            return False, ["未配置 strm 根目录"]
        base = self._strm_dir(spec, media_dir)
        missing: List[str] = []
        for f in files:
            if f.suffix.lower() not in self._video_ext:
                continue
            strm_name = self._remote_name_for(spec, media_dir, f)
            strm_path = base / (strm_name[: -len(f.suffix)] + ".strm")
            try:
                if not strm_path.exists() or strm_path.stat().st_size <= 0:
                    missing.append(strm_path.name)
            except OSError:
                missing.append(strm_path.name)
        return (not missing), missing

    def _verify_remote(
        self, spec: Dict[str, Any], media_dir: Path, files: List[Path]
    ) -> Tuple[bool, List[str]]:
        """
        回查 115 目标目录，逐个比对文件名与大小。
        返回 (是否全部一致, 不一致的文件名列表)。

        为什么要这一步：`upload_file` 返回成功只代表请求被接受，115 侧仍可能因为
        秒传未命中/分片失败而缺文件；删除本地是不可逆操作，必须先核对。
        """
        if self._storage is None:
            self._storage = StorageChain()
        remote_dir = self._remote_dir(spec, media_dir)
        folder = self._storage.get_folder(storage=self._target_storage, path=Path(remote_dir))
        if not folder:
            return False, ["无法读取目标目录"]
        remote_items = self._storage.list_files(fileitem=folder, recursion=True) or []
        remote: Dict[str, Optional[int]] = {}
        for it in remote_items:
            name = getattr(it, "name", None)
            if name:
                remote[name] = getattr(it, "size", None)

        mismatch: List[str] = []
        for f in files:
            size = f.stat().st_size
            remote_name = self._remote_name_for(spec, media_dir, f)
            if remote_name not in remote:
                mismatch.append(f"{remote_name}:缺失")
                continue
            remote_size = remote.get(remote_name)
            # 远端未返回大小时只校验存在性，避免误判
            if remote_size is not None and int(remote_size) != size:
                mismatch.append(f"{remote_name}:大小 {remote_size}≠{size}")
        return (not mismatch), mismatch

    def _resolve_recycle_root(self) -> Path:
        """回收目录：配置优先，否则放在插件数据目录下"""
        if self._recycle_root:
            return Path(self._recycle_root)
        try:
            return Path(self.get_data_path()) / "recycle"
        except Exception:  # noqa: BLE001
            return Path("recycle")

    def _cleanup_local(self, spec: Dict[str, Any], media_dir: Path, file_count: int) -> bool:
        """按 delete_mode 处理本地目录，返回是否真的移除了"""
        mode = self._delete_mode
        if mode == "none":
            return False
        if mode == "delete":
            import shutil

            shutil.rmtree(media_dir, ignore_errors=True)
            logger.info(f"【{self.plugin_name}】已删除本地目录 {media_dir}（{file_count} 个文件）")
            self._prune_empty_parents(spec["local"], media_dir)
            return True
        # recycle
        dest = self._resolve_recycle_root() / time.strftime("%Y%m%d") / media_dir.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            import shutil

            shutil.move(str(media_dir), str(dest))
            logger.info(f"【{self.plugin_name}】本地目录已移入回收站：{dest}")
            self._prune_empty_parents(spec["local"], media_dir)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】移入回收站失败（本地保留）：{e}")
            return False

    @staticmethod
    def _prune_empty_parents(watch: Path, media_dir: Path) -> None:
        """清理因移走条目而变空的上级目录（不越过监控根）"""
        parent = media_dir.parent
        while parent != watch and watch in parent.parents:
            try:
                if any(parent.iterdir()):
                    break
                parent.rmdir()
                parent = parent.parent
            except OSError:
                break

    def _append_ledger(
        self, spec: Dict[str, Any], media_dir: Path, file_count: int, removed: bool
    ) -> None:
        """上传台账（本地目录被删后，这是唯一的记录）"""
        try:
            ledger = self.get_data("ledger") or []
            if not isinstance(ledger, list):
                ledger = []
            ledger.append(
                {
                    "本地目录": str(media_dir),
                    "115 路径": self._remote_dir(spec, media_dir),
                    "文件数": file_count,
                    "完成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "本地处理": ("回收" if self._delete_mode == "recycle" else "删除") if removed else "保留",
                }
            )
            self.save_data("ledger", ledger[-200:])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】写台账失败（不影响上传）：{e}")

    def _upload_dir(
        self, spec: Dict[str, Any], media_dir: Path, files: List[Path], state: Dict[str, Any]
    ) -> Tuple[List[str], List[str]]:
        """把目录内文件逐个上传到 115 对应路径，返回 (已上传, 已跳过)"""
        if self._storage is None:
            self._storage = StorageChain()

        remote_dir = self._remote_dir(spec, media_dir)

        # 目录不存在则递归创建（115 存储插件提供的 get_folder 契约）
        folder = self._storage.get_folder(storage=self._target_storage, path=Path(remote_dir))
        if not folder:
            raise RuntimeError(
                f"无法获取/创建 115 目录 {remote_dir}：请确认已安装并启用 115 存储插件"
                f"（{self._target_storage}），且 115 Cookie 有效"
            )

        # 直接挂在 state 上，保证最终状态里带上完整清单（否则下一轮会整目录重传）
        done: Dict[str, Any] = state.setdefault("files", {})
        uploaded: List[str] = []
        skipped: List[str] = []
        for f in files:
            name = f.name
            remote_name = self._remote_name_for(spec, media_dir, f)
            size = f.stat().st_size
            # 已经上传过且大小未变 → 跳过
            if done.get(name) == size:
                skipped.append(name)
                continue
            item = self._storage.upload_file(fileitem=folder, path=f, new_name=remote_name)
            if not item:
                raise RuntimeError(f"上传失败：{f}")
            done[name] = size
            uploaded.append(name)
            # 每传完一个就落盘状态，中途崩溃后只补传剩余文件
            self._write_state(media_dir, {**state, "status": "uploading"})
            logger.info(f"【{self.plugin_name}】已上传 {remote_dir}/{remote_name}")

        return uploaded, skipped

    def _remote_name_for(self, spec: Dict[str, Any], media_dir: Path, f: Path) -> str:
        """该文件在 115 / strm 里的文件名（剧集模式下视频会带 SxxExx）"""
        if self._series_mode and f.suffix.lower() in self._video_ext:
            return self._episode_stem(spec, media_dir) + f.suffix
        return f.name

    def _remote_names(self, spec: Dict[str, Any], media_dir: Path, files: List[Path]) -> List[str]:
        return [self._remote_name_for(spec, media_dir, f) for f in files]

    # ------------------------------------------------------------------ 工具

    def _is_stable(self, media_dir: Path) -> bool:
        """目录内所有文件最近修改时间都早于阈值 → 认为下载已完成

        注意：必须排除本插件自己写的状态/锁文件，否则写完状态就把目录「变新」，
        会导致下一轮永远判定为不稳定（实测踩过）。
        """
        newest = 0.0
        for p in media_dir.rglob("*"):
            if p.is_file() and p.name not in (STATE_FILE, LOCK_FILE):
                newest = max(newest, p.stat().st_mtime)
        if not newest:
            return False
        return (time.time() - newest) >= self._stable_seconds

    @staticmethod
    def _collect_files(media_dir: Path) -> List[Path]:
        """递归收集文件，排除本插件自己的状态/锁文件"""
        return [
            p
            for p in sorted(media_dir.rglob("*"))
            if p.is_file() and p.name not in (STATE_FILE, LOCK_FILE)
        ]

    @staticmethod
    def _read_state(media_dir: Path) -> Dict[str, Any]:
        f = media_dir / STATE_FILE
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _write_state(media_dir: Path, payload: Dict[str, Any]) -> None:
        (media_dir / STATE_FILE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _post_upload_actions(self, spec: Dict[str, Any], media_dir: Path) -> None:
        """上传完成后的钩子：触发 CMS 增量同步（可选）"""
        if not self._cms_base_url or not self._cms_token:
            return
        remote_path = self._remote_dir(spec, media_dir)
        url = f"{self._cms_base_url}/api/sync/lift_by_token"
        try:
            import requests

            resp = requests.get(
                url,
                params={"token": self._cms_token, "type": "lift_sync", "path": remote_path},
                timeout=15,
            )
            logger.info(f"【{self.plugin_name}】已触发 CMS 增量同步 {remote_path}：{resp.status_code}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】触发 CMS 同步失败（不影响上传）：{e}")

    def collect_status(self) -> List[Dict[str, Any]]:
        """状态清单：供 /pending 接口与详情页使用（剧集模式下逐集列出）"""
        rows: List[Dict[str, Any]] = []
        for spec in self._watch_dirs:
            watch: Path = spec["local"]
            if not watch.exists():
                continue
            for item in self._iter_entries(spec):
                state = self._read_state(item)
                rows.append(
                    {
                        "目录": str(item),
                        "系列": self._series_hints.get(str(item), ""),
                        "115 路径": self._remote_dir(spec, item),
                        "状态": state.get("status") or ("待上传" if self._is_stable(item) else "下载中"),
                        "完成时间": state.get("finished_at") or "",
                        "文件数": len(state.get("files") or {}),
                    }
                )
        return rows

    # ------------------------------------------------------------------ 页面

    def get_form(self) -> Tuple[Optional[List[Dict[str, Any]]], Dict[str, Any]]:
        """配置页（Vuetify）"""
        defaults = {
            "enabled": False,
            "watch_dirs": "",
            "target_storage": "u115",
            "target_root": "/B站",
            "stable_seconds": 120,
            "video_ext": DEFAULT_VIDEO_EXT,
            "upload_ext": DEFAULT_UPLOAD_EXT,
            "sidecar_ext": DEFAULT_SIDECAR_EXT,
            "rename_enabled": False,
            "rename_template": "{title}",
            "remote_name_template": "",
            "series_name": "",
            "upper_name": "",
            "series_mode": False,
            "show_template": "{upper} - {series}",
            "episode_template": "{show} - S{season:02}E{ep:02} - {title}",
            "season": 1,
            "interval_seconds": 300,
            "delete_mode": "none",
            "recycle_root": "",
            "ready_mode": "strm",
            "emby_url": "",
            "emby_api_key": "",
            "strm_root": "",
            "strm_timeout_seconds": 1800,
            "cms_base_url": "",
            "cms_token": "",
        }
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            _col(4, _switch("enabled", "启用插件")),
                            _col(
                                8,
                                _text(
                                    "watch_dirs",
                                    "监控目录（每行一个，容器内路径）",
                                    "支持映射：/data/bili/合集 => 合集；省略 => 时默认用本地目录名",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(4, _text("target_storage", "存储标识", "装了 115 存储插件就填 u115")),
                            _col(4, _text("target_root", "115 目标根路径", "如 /B站")),
                            _col(4, _text("stable_seconds", "稳定阈值（秒）", "文件静置这么久才认为下载完成")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(4, _text("video_ext", "视频扩展名", "命中即视为视频，决定该目录要不要处理")),
                            _col(4, _text("upload_ext", "只上传这些扩展名到 115", "默认仅视频；NFO/封面留在本地 strm 目录")),
                            _col(4, _text("sidecar_ext", "随片文件扩展名（不上传）", "复制到 strm 目录供 Emby 本地刮削")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                _text(
                                    "remote_name_template",
                                    "115 / strm 的条目名模板（留空=用「映射名/本地相对路径」）",
                                    "可用变量：{upper} {series} {title} {bvid} {index}；例如 {upper} - {series} - {title}。"
                                    "可用 / 分层，如 {series}/{title}。CMS 会镜像 115 目录，所以这里定的名字就是 Emby 里看到的",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(6, _text("series_name", "覆盖系列名（可选）", "默认取本地父目录名，即 bili-sync 的合集目录")),
                            _col(6, _text("upper_name", "覆盖 UP 名（可选）", "默认取 NFO 里的 actor/role")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(3, _switch("series_mode", "课程→剧集模式（一合集=一季）")),
                            _col(
                                5,
                                _text(
                                    "show_template",
                                    "剧集目录名模板",
                                    "默认 {upper} - {series}，变量 {upper} {series} {title} {bvid}",
                                ),
                            ),
                            _col(
                                3,
                                _text(
                                    "episode_template",
                                    "单集文件名模板",
                                    "默认 {show} - S{season:02}E{ep:02} - {title}",
                                ),
                            ),
                            _col(1, _text("season", "季号", "1")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(3, _switch("rename_enabled", "上传前重命名文件")),
                            _col(
                                9,
                                _text(
                                    "rename_template",
                                    "文件重命名模板",
                                    "可用变量：{title} {bvid} {upper} {index} {ext}；例如「第{index}讲 {title}」",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(4, _text("interval_seconds", "扫描周期（秒）", "最小 60")),
                            _col(
                                8,
                                {
                                    "component": "VSelect",
                                    "props": {
                                        "model": "delete_mode",
                                        "label": "上传后处理本地文件",
                                        "items": [
                                            {"title": "保留（默认）", "value": "none"},
                                            {"title": "移入回收目录", "value": "recycle"},
                                            {"title": "直接删除", "value": "delete"},
                                        ],
                                        "hint": "仅在判定依据满足后才执行",
                                        "persistent-hint": True,
                                    },
                                },
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                6,
                                _text(
                                    "strm_root",
                                    "CMS 的 strm 输出根目录（容器内路径）",
                                    "对应「115 目标根路径」的那一层，例如 /media/strm/B站 的上层 /media/strm 时请配合映射使用",
                                ),
                            ),
                            _col(
                                3,
                                {
                                    "component": "VSelect",
                                    "props": {
                                        "model": "ready_mode",
                                        "label": "删本地的判定依据",
                                        "items": [
                                            {"title": "strm 已生成（推荐，不访问 115）", "value": "strm"},
                                            {"title": "strm 已生成 + Emby 已查到（最严）", "value": "emby"},
                                            {"title": "回查 115 文件大小（多一层 115 请求）", "value": "storage"},
                                            {"title": "上传即删除（不校验）", "value": "none"},
                                        ],
                                        "hint": "strm 出现说明 CMS 已能从 115 读到文件；选 emby 则会再用 Emby 查一次条目，确认真的入库了才删",
                                        "persistent-hint": True,
                                    },
                                },
                            ),
                            _col(3, _text("strm_timeout_seconds", "等待超时（秒）", "超时只告警，不删本地")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(6, _text("emby_url", "Emby 地址（仅 emby 模式需要）", "如 http://emby:8096")),
                            _col(6, _text("emby_api_key", "Emby API Key（仅 emby 模式需要）", "Emby 后台 → 高级 → API 密钥")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                6,
                                _text("recycle_root", "回收目录（可选，仅 recycle 模式）", "留空则用插件数据目录下的 recycle/"),
                            ),
                            _col(6, _text("cms_token", "CMS API Token（可选）", "")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                _text(
                                    "cms_base_url",
                                    "CMS 地址（可选）",
                                    "如 http://cloud-media-sync:9527，填了就在上传校验后触发增量同步",
                                ),
                            ),
                        ],
                    },
                ],
            }
        ], defaults

    def get_page(self) -> Optional[List[Dict[str, Any]]]:
        """详情页：展示状态清单"""
        rows = self.collect_status()
        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTable",
                                "props": {
                                    "density": "compact",
                                    "headers": [
                                        {"title": "目录", "key": "目录"},
                                        {"title": "状态", "key": "状态"},
                                        {"title": "文件数", "key": "文件数"},
                                        {"title": "完成时间", "key": "完成时间"},
                                    ],
                                    "items": rows,
                                },
                            }
                        ],
                    }
                ],
            }
        ]


# ---------------------------------------------------------------------- 页面小工具


def _col(md: int, node: Dict[str, Any]) -> Dict[str, Any]:
    return {"component": "VCol", "props": {"cols": 12, "md": md}, "content": [node]}


def _text(model: str, label: str, hint: str = "") -> Dict[str, Any]:
    props: Dict[str, Any] = {"model": model, "label": label}
    if hint:
        props["hint"] = hint
        props["persistent-hint"] = True
    return {"component": "VTextField", "props": props}


def _switch(model: str, label: str) -> Dict[str, Any]:
    return {"component": "VSwitch", "props": {"model": model, "label": label}}


def _safe_stem(name: str, fallback: str = "untitled", maxlen: int = 120) -> str:
    """把模板渲染结果规整成一个安全的文件名（不含扩展名）"""
    name = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", " ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    # 模板里某个变量为空时会留下 " -  - " 这类残渣（例如没有 UP 名时），收拾干净
    name = re.sub(r"(\s*-\s*){2,}", " - ", name)
    name = re.sub(r"^[\s\-–—·]+|[\s\-–—·]+$", "", name).strip()
    if len(name) > maxlen:
        name = name[:maxlen].rstrip()
    return name or fallback











