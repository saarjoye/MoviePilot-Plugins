"""
DirUpload115 —— 监控本地目录，识别到「下载完成」就把整个目录上传到 115 网盘。

设计要点（与 MoviePilot 原生整理链完全解耦）：
1. 不走 TMDB、不识别、不重命名、不刮削 —— 只要目录「静置稳定」且含视频文件就上传；
2. 上传复用宿主已有的存储实现（p115disk 提供的 u115 存储模块），本插件里没有任何 115 协议代码；
3. 幂等：每个目录写 `.upload115.state`，记录已上传文件；目标已存在同名同大小的文件则跳过；
4. 上传完成后可选钩子：调 CloudMediaSync 增量同步（Emby 刷新由 CMS 负责，插件不重复触发）。
"""

import csv
import json
import os
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


class _RiskPause(RuntimeError):
    """115 风控冷却（MP 会把请求 sleep 住）→ 立刻中止本轮，避免整轮被卡住一小时"""


class _Unmapped(RuntimeError):
    """课程模式：这条视频在映射表里查不到、标题也推不出年级册 → 不上传，等补映射"""

# 状态文件名（放在被监控的媒体目录里，不会被上传）
STATE_FILE = ".upload115.state"
# 正在上传的互斥标记
LOCK_FILE = ".upload115.lock"


class DirUpload115(_PluginBase):
    # 插件元数据（v3 插件页/索引需要）
    plugin_name = "目录监控上传115"
    plugin_desc = "监控本地目录，目录稳定后整目录上传到 115 网盘，不依赖 TMDB 识别"
    plugin_icon = "upload.png"
    plugin_version = "1.7.0"
    plugin_author = "DirUpload115"
    plugin_config_prefix = "dirupload115_"
    plugin_order = 21
    auth_level = 2
    # 1.5.4：115 风控 —— 冷却 1 小时，结束后再等 30 分钟才恢复
    RISK_COOLDOWN_SECONDS = 3600
    RISK_RESUME_DELAY = 1800
    # 单次 115 调用超过这个秒数只记 warning（大文件正常上传），不再据此判定风控
    RISK_SLOW_CALL_SECONDS = 300
    # 只有异常信息里出现这些关键字才判定为 115 风控
    RISK_KEYWORDS = ("风控", "访问上限", "访问过于频繁", "too many", "429", "rate limit")

    def __init__(self) -> None:
        super().__init__()
        self._enabled: bool = False
        self._watch_dirs: List[Path] = []
        self._risk_until: float = 0.0
        self._round_started_at: str = ""
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
        # 1.3.0：每轮最多上传多少集（0=不限）、MP 转移队列繁忙时让路
        # 1.3.1：把队列/进度写成 JSON 供 bili-sync 仪表盘读取
        self._status_path: Path = Path("/downloads/.dirupload115/status.json")
        self._recent_events: list = []
        self._max_per_round: int = 20
        # 1.4.0：每小时最多上传多少集（0=不限，与 MP 共用的 115 限流叠加）
        self._max_per_hour: int = 60
        # 累计统计（删除本地后目录消失，不能靠扫目录统计历史）
        self._totals: Dict[str, int] = {"uploaded": 0, "deleted": 0, "failed": 0}
        self._upload_times: List[float] = []
        # 1.4.1：按小时聚合的上传量（最多保留 12 小时）
        self._hourly: Dict[str, int] = {}
        self._yield_to_mp: bool = True
        self._run_lock = Lock()
        self._storage: Optional[StorageChain] = None
        # 1.5.0：自建 strm —— 上传后直接用 115 的 pickcode 写 .strm，
        # 不再依赖 CMS 的增量同步（115 秒传/批量上传时 CMS 可能收不到生活事件，
        # 导致 strm 迟迟不生成、本地目录一直卡在 waiting_strm）
        self._strm_self_gen: bool = False
        self._strm_302_domain: str = ""          # 115 直链服务前缀，空则回落到 cms_base_url
        self._pickcode_cache: Dict[str, Any] = {}  # remote_dir -> (时间戳, {文件名: pickcode})
        self._pickcode_budget: int = 10             # 每轮最多额外查几次 115（防风控）
        self._pickcode_budget_default: int = 10

    # ------------------------------------------------------------------ 生命周期

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """生效配置"""
        config = config if config is not None else (self.get_config() or {})
        if config:
            self.update_config(config)

        self._enabled = bool(config.get("enabled"))
        # 每行格式：本地路径 => 115 上的相对子路径（后半段可省略，默认用本地目录名）
        # 1.5.3：支持 `父目录 => @auto` —— 自动把父目录下的「科目/UP 目录」两层展开成监控项，
        #        新增科目或新 UP 不用再改配置（之前必须一行一个 UP，属于设计缺陷）
        self._watch_dirs = []
        _auto_roots: List[Path] = []
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
            if remote.lower() in ("@auto", "*"):
                _auto_roots.append(Path(local))
                continue
            path = Path(local)
            self._watch_dirs.append({"local": path, "remote": remote or path.name})
        # 自动展开：<父>/<科目>/<UP目录> → 监控项 <父>/<科目>/<UP目录>，115 子目录 = 科目名
        for root in _auto_roots:
            try:
                if not root.exists():
                    logger.warning(f"【{self.plugin_name}】自动监控根目录不存在：{root}")
                    continue
                for subject in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
                    for up in sorted(p for p in subject.iterdir() if p.is_dir() and not p.name.startswith(".")):
                        self._watch_dirs.append({"local": up, "remote": subject.name})
            except OSError as e:  # noqa: BLE001
                logger.warning(f"【{self.plugin_name}】自动展开 {root} 失败：{e}")
        self._target_storage = (config.get("target_storage") or "u115").strip()
        # 1.5.4：不再默默回落到 "/B站"（历史上曾因此把内容传到网盘根目录）；没填就留空，由 scan_once 拒绝上传
        _raw_target_root = str(config.get("target_root") or "").strip().strip("/")
        self._target_root = ("/" + _raw_target_root) if _raw_target_root else ""
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
        # 1.6.0 课程模式：按「学科路径 / 年级册 / 单元-课题-UP」组织，名字来自映射表
        self._curriculum_mode = bool(config.get("curriculum_mode"))
        self._curriculum_csv = str(config.get("curriculum_csv") or "").strip()
        self._curriculum_fix = str(config.get("curriculum_fix") or "").strip()
        self._dir_template = str(
            config.get("dir_template") or "{stage}{grade}({volume})"
        ).strip() or "{stage}{grade}({volume})"
        self._file_template = str(
            config.get("file_template") or "{unit_no} {unit} - {lesson} - {upper}"
        ).strip() or "{unit_no} {unit} - {lesson} - {upper}"
        self._topic_template = str(
            config.get("topic_template") or "专题·{series}"
        ).strip() or "专题·{series}"
        # 查不到年级册时的去处：topic=归「专题·<合集名>」/ hold=不上传 / delete=不上传并删本地
        self._unmapped_policy = str(config.get("unmapped_policy") or "topic").strip().lower()
        if self._unmapped_policy not in ("topic", "hold", "delete"):
            self._unmapped_policy = "topic"
        # 年级白名单：只上传这些年级（空=不限制），如 ["初中七","初中八"]；前端是多选下拉
        _raw_allow = config.get("grade_allowlist")
        if isinstance(_raw_allow, (list, tuple)):
            _allow = [str(x).strip() for x in _raw_allow if str(x).strip()]
        else:
            _allow = [x.strip() for x in re.split(r"[,，;；\s]+", str(_raw_allow or "")) if x.strip()]
        self._grade_allowlist = {a for a in _allow if a not in ("全部", "不限", "all")}
        # 非目标年级怎么处理：keep=留本地不上传 / delete=不上传并删本地
        self._offgrade_policy = str(config.get("offgrade_policy") or "keep").strip().lower()
        if self._offgrade_policy not in ("keep", "delete"):
            self._offgrade_policy = "keep"
        # 专题目录按什么分组：series=合集/UP名 / tag=标题里的【标签】 / both=合集名/标签
        self._topic_group = str(config.get("topic_group") or "series").strip().lower()
        if self._topic_group not in ("series", "tag", "both"):
            self._topic_group = "series"
        # 1.6.9：标签别名（每行 `旧名=新名`），把「语法」并进「语法线」这类同义专栏
        self._topic_alias: Dict[str, str] = {}
        for line in str(config.get("topic_alias") or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            old, _, new = line.partition("=")
            if old.strip() and new.strip():
                self._topic_alias[old.strip()] = new.strip()
        self._skipped_grade = 0
        self._skipped_noncourse = 0
        self._curriculum = _CurriculumMap(self._curriculum_fix if self._curriculum_mode else "",
                                          self._curriculum_csv if self._curriculum_mode else "")
        # 综合 UP：标题里的【数学】/【地理】覆盖订阅路径里的学科
        self._subject_from_title = bool(config.get("subject_from_title", True))
        self._unmapped: List[Dict[str, str]] = []
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
        _sp = str(config.get("status_path") or "").strip()
        if _sp:
            self._status_path = Path(_sp)
        self._max_per_round = max(0, int(config.get("max_per_round") or 20))
        self._max_per_hour = max(0, int(config.get("max_per_hour") or 60))
        self._yield_to_mp = bool(config.get("yield_to_mp", True))
        # 1.5.0：自建 strm（用 115 pickcode 直链），默认关闭；302 前缀留空则用 CMS 地址
        self._strm_self_gen = bool(config.get("strm_self_gen", False))
        self._strm_302_domain = str(config.get("strm_302_domain") or "").strip().rstrip("/")
        self._pickcode_cache = {}
        self._pickcode_budget = max(0, int(config.get("pickcode_budget") or 10))
        self._pickcode_budget_default = self._pickcode_budget
        # 1.5.4：风控暂停时间要持久化，reload 之后仍然生效
        try:
            self._risk_until = float(self.get_data("risk_until") or 0)
        except Exception:  # noqa: BLE001
            self._risk_until = 0.0
        # 1.5.2：累计统计与小时桶要能从插件数据里恢复，否则每次 reload（改配置/重启）都会清零，
        # 仪表盘上「累计已上传」会莫名回退
        try:
            saved_totals = self.get_data("totals")
            if isinstance(saved_totals, dict):
                self._totals = {
                    k: max(0, int(saved_totals.get(k) or 0))
                    for k in ("uploaded", "deleted", "failed")
                }
            saved_hourly = self.get_data("hourly")
            if isinstance(saved_hourly, dict):
                self._hourly = {
                    str(k): max(0, int(v)) for k, v in saved_hourly.items() if str(k)
                }
                self._hourly = dict(sorted(self._hourly.items())[-12:])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】恢复累计统计失败（不影响上传）：{e}")
        # 注意：StorageChain 不能在应用组合根就绪前实例化（实测报 "Chain 运行上下文尚未由启动组合根配置"），
        # 所以这里不创建，等真正用的时候再懒加载（_storage 为 None 时各处会现场创建）
        self._storage = None

        if self._enabled:
            logger.info(
                f"【{self.plugin_name}】已启用：监控 {len(self._watch_dirs)} 个目录 → "
                f"{self._target_storage}:{self._target_root}，稳定阈值 {self._stable_seconds}s，"
                f"周期 {self._interval_seconds}s"
            )
            # 1.5.7：MP 每次启用/重载都会重挂定时器，这里立刻刷新一次 status.json 的
            # updated_at / next_run_at，仪表盘才不会拿着几小时前的旧时间显示“已逾期”
            self._touch_status("插件已启动/重载，等待下一轮触发")

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
            self._touch_status("上一轮仍在执行")
            return summary
        # 1.5.4：target_root 必须显式配置，否则宁可不上传也不要往网盘根目录乱建目录
        if not self._target_root or self._target_root == "/":
            self._run_lock.release()
            logger.error(
                f"【{self.plugin_name}】未配置「115 目标根路径」(target_root)，为避免把内容传到网盘根目录，本轮跳过"
            )
            self._touch_status("未配置 target_root，已跳过")
            return summary
        # 1.5.4：风控暂停中直接跳过（不发起任何 115 请求，避免被 MP 的冷却 sleep 卡住整整一小时）
        if time.time() < self._risk_until:
            self._run_lock.release()
            left = int(self._risk_until - time.time())
            logger.warning(
                f"【{self.plugin_name}】115 风控冷却中，暂停上传，约 {left // 60} 分钟后再试"
            )
            self._touch_status(f"115 风控暂停中，约 {max(1, left // 60)} 分钟后恢复")
            return summary
        # 1.3.0：MP 自己的转移队列繁忙时让路，避免两份调度互相抢配额
        if self._yield_to_mp and self._mp_busy():
            self._run_lock.release()
            logger.info(f"【{self.plugin_name}】MP 转移队列仍在执行，本轮让路（{self._interval_seconds}s 后再试）")
            self._touch_status("MP 转移队列繁忙，本轮让路")
            return summary

        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        # 1.5.8：本轮开始时立刻标记「执行中」，让仪表盘能和 MP 日志对上
        self._round_started_at = started_at
        self._touch_status("本轮执行中", running=True)
        # 1.5.1：每轮重置「额外查 115 取 pickcode」的预算，避免连续 API 调用触发风控
        self._pickcode_budget = max(0, int(self._pickcode_budget_default))
        queue = {"total": 0, "done": 0, "pending": 0, "waiting": 0, "failed": 0}
        stuck: List[Dict[str, Any]] = []

        # 1.4.0：先做一次「只统计、不上传」的全量扫描，保证仪表盘数字是全局真实队列
        by_dir: Dict[str, Dict[str, int]] = {}
        try:
            for spec in self._watch_dirs:
                watch: Path = spec["local"]
                if not watch.exists():
                    continue
                _dir_key = str(spec.get("remote") or watch.name)
                _bucket = by_dir.setdefault(
                    _dir_key, {"total": 0, "done": 0, "pending": 0, "waiting": 0}
                )
                for item in self._iter_entries(spec):
                    queue["total"] += 1
                    _bucket["total"] += 1
                    st = self._read_state(item)
                    if st.get("status") == "done":
                        queue["done"] += 1
                        _bucket["done"] += 1
                    elif st.get("status") == "waiting_strm":
                        queue["waiting"] += 1
                        _bucket["waiting"] += 1
                        try:
                            age = (time.time() - item.stat().st_mtime) / 60
                            if age >= 30:
                                stuck.append({"name": item.name, "minutes": int(age)})
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        queue["pending"] += 1
                        _bucket["pending"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】全量统计失败：{e}")
        _last_touch = time.time()
        try:
            for spec in self._watch_dirs:
                watch: Path = spec["local"]
                if not watch.exists():
                    logger.warning(f"【{self.plugin_name}】监控目录不存在：{watch}")
                    continue
                if self._max_per_round and len(summary["uploaded"]) >= self._max_per_round:
                    logger.info(
                        f"【{self.plugin_name}】本轮已达上限 {self._max_per_round} 集，剩余留到下一轮"
                    )
                    break
                for item in self._iter_entries(spec):
                    if self._max_per_round and len(summary["uploaded"]) >= self._max_per_round:
                        logger.info(
                            f"【{self.plugin_name}】本轮已达上限 {self._max_per_round} 集，剩余留到下一轮"
                        )
                        break
                    summary["scanned"] += 1
                    # 1.5.8：大文件一轮可能跑几十分钟，每 30 秒刷新一次「执行中」状态
                    if time.time() - _last_touch >= 30:
                        self._touch_status("本轮执行中", running=True)
                        _last_touch = time.time()
                    if self._max_per_hour and len(self._recent_uploads()) >= self._max_per_hour:
                        logger.info(f"【{self.plugin_name}】已达每小时上限 {self._max_per_hour} 集，本轮停止")
                        break
                    try:
                        outcome = self._handle_media_dir(spec, item)
                        if outcome == "failed":
                            queue["failed"] += 1
                        if outcome in ("uploaded", "waiting", "skipped"):
                            self._push_event(item.name, outcome)
                        summary[outcome].append(str(item))
                    except _RiskPause as e:
                        # 1.5.4：撞上 115 风控（MP 的风控冷却会把请求 sleep 住）→ 立刻停止本轮，
                        # 冷却 1 小时后再加 30 分钟缓冲才恢复
                        self._risk_until = time.time() + self.RISK_COOLDOWN_SECONDS + self.RISK_RESUME_DELAY
                        resume = time.strftime("%H:%M:%S", time.localtime(self._risk_until))
                        try:
                            self.save_data("risk_until", self._risk_until)
                        except Exception:  # noqa: BLE001
                            pass
                        logger.warning(
                            f"【{self.plugin_name}】检测到 115 风控（{e}），立即停止本轮上传，"
                            f"暂停到 {resume}（冷却 1 小时 + 缓冲 30 分钟）"
                        )
                        break
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"【{self.plugin_name}】处理 {item} 失败：{e}")
                        summary["failed"].append(f"{item}: {e}")
        finally:
            self._run_lock.release()
            self._write_status(
                started_at=started_at,
                queue=queue,
                summary=summary,
                stuck=stuck,
                by_dir=by_dir,
            )

        if summary["uploaded"] or summary["waiting"] or summary["failed"]:
            logger.info(
                f"【{self.plugin_name}】本轮结果：扫描 {summary['scanned']}，"
                f"完成 {len(summary['uploaded'])}，等 strm {len(summary['waiting'])}，"
                f"跳过 {len(summary['skipped'])}，失败 {len(summary['failed'])}"
            )
        return summary

    def _mp_busy(self) -> bool:
        """查询 MP 自身的转移队列是否还有未完成任务（只读，失败时按空闲处理）"""
        try:
            import asyncio
            import os

            import asyncpg

            async def _q() -> int:
                conn = await asyncpg.connect(
                    host=os.environ.get("DB_POSTGRESQL_HOST", "127.0.0.1"),
                    port=int(os.environ.get("DB_POSTGRESQL_PORT", "5432")),
                    user=os.environ.get("DB_POSTGRESQL_USERNAME", "moviepilot"),
                    password=os.environ.get("DB_POSTGRESQL_PASSWORD", ""),
                    database=os.environ.get("DB_POSTGRESQL_DATABASE", "moviepilot"),
                    timeout=5,
                )
                try:
                    # 1.3.1：只把「真正在执行」的任务算繁忙，
                    # 否则历史上卡在 planned 的脏任务会让插件永远让路
                    return int(
                        await conn.fetchval(
                            "select count(*) from transferpending "
                            "where state = 'running' "
                            "   or (lease_expires_at is not null and lease_expires_at > now())"
                        )
                        or 0
                    )
                finally:
                    await conn.close()

            pending = asyncio.run(_q())
            if pending:
                logger.info(f"【{self.plugin_name}】MP 转移队列还有 {pending} 个任务未完成")
            return pending > 0
        except Exception as e:  # noqa: BLE001
            logger.debug(f"【{self.plugin_name}】查询 MP 队列失败（按空闲处理）：{e}")
            return False

    def _recent_uploads(self) -> List[float]:
        """最近 1 小时内的上传时间戳"""
        cutoff = time.time() - 3600
        self._upload_times = [t for t in self._upload_times if t >= cutoff]
        return self._upload_times

    def _push_event(self, name: str, outcome: str) -> None:
        """记录最近事件（内存里保留最近 30 条）"""
        label = {
            "uploaded": "已上传",
            "waiting": "等 strm",
            "skipped": "已就绪",
            "failed": "失败",
        }.get(outcome, outcome)
        if outcome == "uploaded":
            self._upload_times.append(time.time())
            self._totals["uploaded"] += 1
            hour_key = time.strftime("%m-%d %H:00")
            self._hourly[hour_key] = self._hourly.get(hour_key, 0) + 1
            keep = sorted(self._hourly.keys())[-12:]
            self._hourly = {k: self._hourly[k] for k in keep}
            try:
                self.save_data("hourly", self._hourly)
            except Exception:  # noqa: BLE001
                pass
        elif outcome == "failed":
            self._totals["failed"] += 1
        try:
            self.save_data("totals", self._totals)
        except Exception:  # noqa: BLE001
            pass
        self._recent_events.append(
            {"time": time.strftime("%H:%M:%S"), "name": name, "outcome": outcome, "label": label}
        )
        self._recent_events = self._recent_events[-30:]

    def _touch_status(self, reason: str, running: bool = False) -> None:
        """
        1.5.6：本轮被跳过（风控暂停 / 上一轮没跑完 / 配置缺失）时也刷新 status.json。

        不刷新的后果就是仪表盘一直显示几十分钟前算出来的 next_run_at，
        用户看到「今天 10:07 · 还剩 +00:52」这种过期时间，完全无法判断真实的下一次时间。

        1.5.8：本轮**执行中也刷新**（round_running=true + round_started_at），
        否则遇到大文件分片上传（一轮跑几十分钟）时，仪表盘会以为“还没到时间”，
        而 MP 里其实正在狂传。
        """
        try:
            path = self._status_path
            current: Dict[str, Any] = {}
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    current = {}
            now = time.time()
            current["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            current["next_run_at"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(now + self._interval_seconds)
            )
            current["interval_seconds"] = self._interval_seconds
            # 1.5.7：顺带把当前生效的节奏参数也刷新，避免仪表盘显示上一轮的旧值
            current["max_per_round"] = self._max_per_round
            current["max_per_hour"] = self._max_per_hour
            current["enabled"] = bool(self._enabled)
            current["delete_mode"] = self._delete_mode
            current["ready_mode"] = self._ready_mode
            current["paused_reason"] = reason
            current["round_running"] = bool(running)
            if running and self._round_started_at:
                current["round_started_at"] = self._round_started_at
            current["risk_paused_until"] = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._risk_until))
                if self._risk_until > now
                else ""
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"【{self.plugin_name}】刷新 status.json 失败：{e}")

    def _write_status(
        self,
        started_at: str,
        queue: Dict[str, Any],
        summary: Dict[str, Any],
        stuck: List[Dict[str, Any]],
        by_dir: Dict[str, Dict[str, int]],
    ) -> None:
        """把队列与调度信息写成 JSON，供 bili-sync 仪表盘读取（原子写）"""
        try:
            payload = {
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "round_started_at": started_at,
                "round_running": False,
                "enabled": bool(self._enabled),
                "interval_seconds": self._interval_seconds,
                "max_per_round": self._max_per_round,
                "max_per_hour": self._max_per_hour,
                "uploaded_last_hour": len(self._recent_uploads()),
                "totals": self._totals,
                "hourly": [{"hour": k, "count": v} for k, v in sorted(self._hourly.items())],
                "stuck": sorted(stuck, key=lambda x: -x["minutes"])[:20],
                "next_run_at": time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(time.time() + self._interval_seconds),
                ),
                "yield_to_mp": bool(self._yield_to_mp),
                "delete_mode": self._delete_mode,
                # 1.5.4：风控暂停信息（>现在 时表示暂停中，前端/脚本可据此显示）
                "risk_paused_until": (
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._risk_until))
                    if self._risk_until > time.time()
                    else ""
                ),
                # 1.5.6：正常跑完一轮时清空暂停原因
                "paused_reason": "",
                "ready_mode": self._ready_mode,
                "queue": queue,
                "by_dir": [
                    {"dir": k, **v} for k, v in sorted(by_dir.items())
                ],
                "round": {
                    "scanned": summary.get("scanned", 0),
                    "uploaded": len(summary.get("uploaded") or []),
                    "waiting": len(summary.get("waiting") or []),
                    "skipped": len(summary.get("skipped") or []),
                    "failed": len(summary.get("failed") or []),
                },
                "recent": self._recent_events[-20:],
                # 1.6.0 课程模式：映射表状态 + 待补映射清单
                "curriculum": {
                    "mode": self._curriculum_mode,
                    "csv": self._curriculum_csv or "",
                    "entries": len(self._curriculum.by_bvid),
                    "error": self._curriculum.error,
                    "unmapped_policy": self._unmapped_policy,
                    "grade_allowlist": sorted(self._grade_allowlist),
                    "offgrade_policy": self._offgrade_policy,
                    "skipped_grade": self._skipped_grade,
                    "skipped_noncourse": self._skipped_noncourse,
                    "dir_template": self._dir_template,
                    "file_template": self._file_template,
                    "topic_template": self._topic_template,
                },
                "unmapped": self._unmapped[-50:],
            }
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._status_path)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"【{self.plugin_name}】写状态文件失败：{e}")

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
        if self._curriculum_mode:
            # 课程模式：容器识别（<UP目录>/<合集目录>/<视频目录>），但不生成 Show/Season
            for d in children:
                if self._has_video_direct(d):
                    self._series_hints[str(d)] = watch.name
                    entries.append(d)
                    continue
                subs = [
                    s for s in sorted(d.iterdir())
                    if s.is_dir() and not s.name.startswith(".") and self._dir_has_video(s)
                ]
                if subs:
                    for s in subs:
                        self._series_hints[str(s)] = d.name      # 合集名 → {series}
                        entries.append(s)
                else:
                    self._series_hints[str(d)] = d.name
                    entries.append(d)
            return entries

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

    def _has_video_direct(self, d: Path) -> bool:
        """目录自己这一层是否有视频（用来区分「视频目录」和「合集容器」）"""
        try:
            return any(
                p.is_file() and p.suffix.lower() in self._video_ext for p in d.iterdir()
            )
        except OSError:
            return False

    def _note_unmapped(self, spec: Dict[str, Any], media_dir: Path, reason: str) -> None:
        """记一条「待补映射」，别每轮重复刷日志（状态页能看到就够了）"""
        try:
            key = str(media_dir)
            if any(x.get("dir") == key for x in self._unmapped):
                return
            self._unmapped.append(
                {
                    "dir": key,
                    "name": media_dir.name,
                    "bvid": self._read_nfo_meta(media_dir).get("bvid", ""),
                    "reason": reason,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            self._unmapped = self._unmapped[-100:]
            logger.warning(f"【{self.plugin_name}】待补映射：{reason}")
        except Exception:  # noqa: BLE001
            pass

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
        if self._curriculum_mode:
            # 课程模式：<映射前缀(学科)>/<学段年级(册)>；查不到册就落「专题·<合集名>」
            meta = self._item_meta(spec, media_dir)
            parts: List[str] = []
            remote = str(spec.get("remote") or "").strip("/")
            segs = [seg for seg in remote.split("/") if seg]
            # 综合 UP：标题带【数学】【地理】时，用标题的学科替换监控映射的第一段
            subject = (meta.get("subject") or "").strip()
            if subject and segs and segs[0] != subject:
                segs[0] = subject
            elif subject and not segs:
                segs = [subject]
            parts.extend(segs)
            if meta.get("grade") and meta.get("volume"):
                parts.append(_safe_stem(self._render_tpl(self._dir_template, meta)))
                return parts
            if self._unmapped_policy == "topic" and (meta.get("series") or ""):
                # 合集目录名常带「合集·」「系列·」前缀，做专题目录时去掉，避免 `专题·合集·xxx`
                meta = dict(meta)
                # 注意：先判断「是不是合集来的」，再去掉前缀——顺序反了会把合集误判成单视频
                raw_series = meta.get("series") or ""
                is_collection = bool(re.match(r"^(合集|系列|列表)\s*[·・:：\-_]\s*", raw_series))
                meta["series"] = re.sub(r"^(合集|系列|列表)\s*[·・:：\-_]\s*", "", raw_series).strip()
                # 1.6.5：专题目录的分组来源
                #   series=合集/UP 目录名（旧行为）｜tag=标题里的第一个【标签】｜both=合集名/标签
                #   1.6.8：**来自合集订阅的用合集名**；单视频投稿（目录名是 UP 名/无合集）才看标题标签
                tag = _first_title_tag(meta.get("title") or "") if self._topic_group in ("tag", "both") else ""
                if tag:
                    tag = self._topic_alias.get(tag, tag)   # 1.6.9：标签别名（语法→语法线）
                if tag and self._topic_group in ("tag", "both") and not is_collection:
                    meta["series"] = tag          # 让 {series} 直接渲染成标签名
                parts.append(_safe_stem(self._render_tpl(self._topic_template, meta)))
                if tag and self._topic_group == "both" and is_collection:
                    parts.append(_safe_stem(tag))
                return parts
            raise _Unmapped(
                f"{media_dir.name} 未映射：bvid={meta.get('bvid') or '?'} "
                f"标题={meta.get('title') or '?'}（补一行映射表或用 hold 策略等它）"
            )

        if self._series_mode:
            # 二开修复：剧集模式也要带上「监控目录 => 115 相对路径」里的映射前缀，
            # 否则 数学/英语 这类分类目录会在 115 上被丢掉
            parts: List[str] = []
            remote = str(spec.get("remote") or "").strip("/")
            if remote:
                parts.extend([seg for seg in remote.split("/") if seg])
            parts.append(self._show_name(spec, media_dir))
            parts.append(f"Season {self._season}")
            return parts
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

    @staticmethod
    def _render_tpl(tpl: str, meta: Dict[str, str]) -> str:
        """用 meta 渲染模板；没赋值的占位符直接清空（避免名字里残留 {lesson} 这类字样）"""
        text = tpl or ""
        for key, val in meta.items():
            if isinstance(val, str):
                text = text.replace("{" + key + "}", val)
        text = re.sub(r"\{[a-z_]+(:0\d)?\}", "", text)
        return text

    def _entry_stem(self, spec: Dict[str, Any], media_dir: Path) -> str:
        """课程模式下的最终文件名（不含扩展名），默认 `01 有理数 - 有理数与数轴 - 妖王本妖`"""
        meta = self._item_meta(spec, media_dir)
        return _safe_stem(self._render_tpl(self._file_template, meta))

    def _guess_upper(self, spec: Dict[str, Any], media_dir: Path) -> str:
        """从路径里猜 UP 名：优先取带 `-数字ID` 后缀的那层目录名（bili-sync 的作者目录）"""
        cands = [spec["local"], *list(media_dir.parents)]
        for p in cands:
            if re.search(r"-\d{5,}$", p.name):
                return re.sub(r"-\d{5,}$", "", p.name)
        return ""

    def _show_name(self, spec: Dict[str, Any], media_dir: Path) -> str:
        """剧集（show）目录名，默认 `UP名 - 系列名`"""
        meta = self._item_meta(spec, media_dir)
        series = (meta.get("series") or "").strip()
        upper = (meta.get("upper") or "").strip()
        # 1.2.0：投稿/单视频目录的目录名与 UP 名相同，直接渲染会出现
        # 「一数-初中版 - 一数-初中版」，这里换成更可读的后缀
        if series and upper and series == upper:
            meta["series"] = "投稿"
        elif series in ("单视频", "单集"):
            meta["series"] = series
        text = self._show_template
        for key in ("upper", "series", "title", "bvid", "index"):
            text = text.replace("{" + key + "}", meta.get(key) or "")
        text = text.strip(" -_/")
        # 1.5.5：模板只写 {series} 时，若系列名为空（无合集信息）就回落到 UP 名 / 本地目录名，
        # 避免生成空目录名或 "untitled"
        if not text:
            text = upper or media_dir.name
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
        if self._curriculum_mode:
            # 1) 先定学科（= 订阅路径里的学科目录），词典要按学科启用
            if not meta.get("subject"):
                meta["subject"] = str(spec.get("remote") or "").split("/")[0]
            # 1.5) 综合 UP：标题里明确写了学科（【数学】【地理】）就以标题为准
            if self._subject_from_title:
                tag_subject = _parse_subject_tag(meta.get("title") or "")
                if tag_subject and tag_subject != meta.get("subject"):
                    meta["_subject_override"] = meta.get("subject") or ""
                    meta["subject"] = tag_subject
            # 2) 查映射表（bvid 优先，其次标题），再退到内置词典
            cur = self._curriculum.lookup(
                bvid=meta.get("bvid") or "", title=meta.get("title") or "",
                subject=meta.get("subject") or "",
            )
            for key in ("subject", "stage", "grade", "volume", "unit_no", "unit", "lesson"):
                if cur.get(key):
                    meta[key] = cur[key]
            meta["_match"] = cur.get("_match") or ""
            # 3) 表里没有年级册时，从「合集名」再退到「父目录名 / 标题」读 【七上】/八上/七年级上册
            if not (meta.get("grade") and meta.get("volume")):
                for tag in (
                    _parse_grade_tag(meta.get("series") or ""),
                    _parse_grade_tag(media_dir.parent.name),
                    _parse_grade_tag(meta.get("title") or ""),
                ):
                    for key, val in tag.items():
                        if val and not meta.get(key):
                            meta[key] = val
                    if meta.get("grade") and meta.get("volume"):
                        meta["_match"] = meta.get("_match") or "tag"
                        break
            # 4) UP 名兜底：NFO 没有、也没手填覆盖值时，从带 `-ID` 的目录名里剥出来
            if not meta.get("upper"):
                meta["upper"] = self._guess_upper(spec, media_dir)
            # 5) 课题名兜底：清洗标题（只影响显示，不影响归类）
            if not meta.get("lesson"):
                meta["lesson"] = _clean_lesson(meta.get("title") or media_dir.name)
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

        # 3.5) 课程模式：年级闸门 —— 非目标年级一律不动 115（可选顺手删本地）
        if self._curriculum_mode:
            meta = self._item_meta(spec, media_dir)
            grade_key = f"{meta.get('stage') or '初中'}{meta.get('grade') or ''}"
            if meta.get("grade") and self._grade_allowlist and grade_key not in self._grade_allowlist:
                self._skipped_grade += 1
                logger.info(
                    f"【{self.plugin_name}】{media_dir.name} 是「{grade_key}」，不在允许的年级"
                    f"（{'、'.join(sorted(self._grade_allowlist))}），跳过上传"
                )
                if self._offgrade_policy == "delete":
                    self._drop_local(spec, media_dir)
                return "skipped"
            if not meta.get("grade") and self._unmapped_policy == "delete":
                self._skipped_noncourse += 1
                logger.info(f"【{self.plugin_name}】{media_dir.name} 认不出年级（视为非课程），按策略删除本地")
                self._drop_local(spec, media_dir)
                return "skipped"
            try:
                self._rel_parts(spec, media_dir)
            except _Unmapped as e:
                self._note_unmapped(spec, media_dir, str(e))
                return "skipped"

        # 4) 已上传、正在等 strm：只做就绪检查，不重复上传、也不访问 115
        #    1.6.3：如果命名规则变过（比如从「按合集分季」切到课程模式），旧状态里的文件名
        #    和新模板算出来的对不上——这种情况永远等不到新路径的 strm，必须清空状态按新名字重传
        if status == "waiting_strm":
            upload_files = [f for f in files if f.suffix.lower() in self._upload_ext]
            expected = {self._remote_name_for(spec, media_dir, f) for f in upload_files}
            recorded = set((state.get("files") or {}).keys())
            if recorded and expected and recorded != expected:
                logger.warning(
                    f"【{self.plugin_name}】{media_dir.name} 的命名规则变了"
                    f"（旧：{sorted(recorded)[0]} → 新：{sorted(expected)[0]}），清空旧状态按新规则重传"
                )
                self._write_state(media_dir, {})
                state, status = {}, ""
            else:
                return self._finalize(spec, media_dir, state, files)

        # 5) 首次处理：加锁 → 重命名 → 只传视频 → 随片文件拷到 strm 目录 → 等 strm
        lock = media_dir / LOCK_FILE
        if lock.exists() and (time.time() - lock.stat().st_mtime) < 3600:
            logger.info(f"【{self.plugin_name}】{media_dir.name} 正在被处理，跳过")
            return "skipped"
        lock.write_text(str(time.time()), encoding="utf-8")

        try:
            # 5.1 重命名（必须在上传前：115 文件名 → CMS strm 文件名，事后改名 strm 就断）
            #     课程模式下不改本地文件名——本地目录/文件名是 bili-sync 的记录，动了它会重下
            if self._rename_enabled and not self._curriculum_mode:
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
        if self._curriculum_mode:
            # 课程模式：与 115 同构，但随片文件名要跟着视频的新名字（否则 Emby 认不出配对）
            target_dir = self._strm_dir(spec, media_dir)
            stem = self._entry_stem(spec, media_dir)
            videos = [
                f for f in self._collect_files(media_dir)
                if f.suffix.lower() in self._video_ext and f.parent == media_dir
            ]
            old_stem = videos[0].stem if videos else ""
            for src in sidecar_files:
                if old_stem and src.name.startswith(old_stem):
                    dest = target_dir / (stem + src.name[len(old_stem):])
                    if src.name.endswith("-thumb.jpg"):
                        copied += self._safe_copy(src, dest)
                        continue
                    copied += self._safe_copy(src, dest)
                    if "-poster" in src.name:
                        copied += self._safe_copy(src, target_dir / (stem + "-thumb.jpg"))
                else:
                    copied += self._safe_copy(src, target_dir / src.name)
            if copied:
                logger.info(f"【{self.plugin_name}】{media_dir.name} 课程模式：{copied} 个随片文件已就位")
            return copied

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
                        # 1.2.1：Emby 单集缩略图认的是 <文件名>-thumb.jpg
                        thumb_dest = ep_dir / (ep_stem + "-thumb.jpg")
                        if thumb_dest != dest:
                            copied += self._safe_copy(src, thumb_dest)
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
            # 1.5.0：先自己把 strm 写出来（幂等，已有同内容就跳过），再判断就绪
            if self._strm_self_gen:
                self._write_strm_by_pickcode(spec, media_dir, files, state)
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

    def _slow(self, fn, label: str):
        """
        调用 115 存储接口的统一包装（1.5.9 修正判定方式）。

        教训：1.5.4~1.5.8 里用「单次调用 >45 秒就判定被风控」是错的——
        4GB 的物理课视频分片上传本来就要几十分钟，于是每轮都被误判成风控，
        白白暂停 90 分钟，用户看到的就是「倒计时没跑完又变成 1 个多小时」。
        现在只有**明确的风控错误**才暂停；慢调用只记一条 warning。
        """
        t0 = time.time()
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if self._is_risk_error(e):
                raise _RiskPause(f"{label}: {e}") from e
            raise
        finally:
            elapsed = time.time() - t0
            if elapsed >= self.RISK_SLOW_CALL_SECONDS:
                logger.warning(
                    f"【{self.plugin_name}】{label} 单次耗时 {int(elapsed)}s"
                    f"（大文件分片上传属正常，不判定为风控）"
                )

    def _is_risk_error(self, error: Exception) -> bool:
        """只有 115 明确报「风控 / 访问上限 / 429」才算风控"""
        text = str(error)
        return any(k in text for k in self.RISK_KEYWORDS)

    def _strm_dir(self, spec: Dict[str, Any], media_dir: Path) -> Path:
        """本地媒体目录 → CMS 的 strm 输出目录（与 115 路径严格同构：CMS 会镜像 115 结构）"""
        return Path(self._strm_root).joinpath(*self._rel_parts(spec, media_dir))

    # ------------------------------------------------------------ 1.5.0 自建 strm

    def _strm_302_base(self) -> str:
        """115 直链服务前缀：优先 strm_302_domain，其次 CMS 地址"""
        return (self._strm_302_domain or self._cms_base_url).rstrip("/")

    def _pickcode_map(self, spec: Dict[str, Any], media_dir: Path, state: Dict[str, Any],
                      files: List[Path]) -> Dict[str, str]:
        """
        取「远端文件名 → pickcode」。

        优先用上传时 115 返回并记在 state 里的 pickcode（零额外 API 调用）；
        只有补历史积压时才用 get_item 逐个查，且**每轮有预算上限**（默认 10 次），
        避免像 1.5.0 那样每轮对 115 狂发请求触发风控（实测会触发 QPM/QPH 限流冷却）。
        """
        picks: Dict[str, str] = dict(state.get("pickcodes") or {})
        remote_dir = self._remote_dir(spec, media_dir)
        missing = [
            self._remote_name_for(spec, media_dir, f)
            for f in files
            if f.suffix.lower() in self._video_ext
            and self._remote_name_for(spec, media_dir, f) not in picks
        ]
        if not missing:
            return picks
        if self._storage is None:
            self._storage = StorageChain()
        for name in missing:
            if self._pickcode_budget <= 0:
                break
            try:
                self._pickcode_budget -= 1
                item = self._slow(
                    lambda: self._storage.get_item(
                        storage=self._target_storage, path=Path(remote_dir) / name
                    ),
                    f"get_item {name}",
                )
            except _RiskPause:
                raise
            except Exception as e:  # noqa: BLE001
                logger.debug(f"【{self.plugin_name}】查询 115 文件失败 {name}：{e}")
                continue
            code = getattr(item, "pickcode", None) if item else None
            if code:
                picks[name] = str(code)
        if picks:
            state["pickcodes"] = picks
        return picks

    def _write_strm_by_pickcode(self, spec: Dict[str, Any], media_dir: Path, files: List[Path],
                                state: Dict[str, Any]) -> int:
        """
        用 115 的 pickcode 直接写 .strm（内容与 CMS 生成的格式一致）：
            {302 前缀}/d/{pickcode}{后缀}?/{远端文件名}

        为什么要自己写：CMS 的增量同步依赖 115「生活事件」，而 bili-sync 上传的视频经常是
        秒传/批量完成，事件缺失或滞后，于是 strm 迟迟不出、ready_mode=strm 永远等不到。
        自己写之后 CMS 即使后续补生成也只是覆盖成同样内容（STRM_EXIST_IS_REBUILD）。
        失败只告警，绝不影响上传与清理判断。
        """
        if not self._strm_self_gen or not self._strm_root:
            return 0
        base_url = self._strm_302_base()
        if not base_url:
            logger.warning(
                f"【{self.plugin_name}】已开自建 strm，但没有可用的 302 前缀"
                f"（请填 strm_302_domain 或 CMS 地址）"
            )
            return 0
        try:
            pick = self._pickcode_map(spec, media_dir, state, files)
        except _RiskPause:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】{media_dir.name} 取 pickcode 失败，跳过自建 strm：{e}")
            return 0

        base = self._strm_dir(spec, media_dir)
        written = 0
        for f in files:
            if f.suffix.lower() not in self._video_ext:
                continue
            remote_name = self._remote_name_for(spec, media_dir, f)
            code = pick.get(remote_name)
            if not code:
                continue
            url = f"{base_url}/d/{code}{f.suffix}?/{remote_name}"
            strm_path = base / (remote_name[: -len(f.suffix)] + ".strm")
            try:
                if strm_path.exists() and strm_path.read_text(encoding="utf-8").strip() == url:
                    continue
                strm_path.parent.mkdir(parents=True, exist_ok=True)
                strm_path.write_text(url, encoding="utf-8")
                written += 1
            except OSError as e:  # noqa: BLE001
                logger.warning(f"【{self.plugin_name}】写入 strm 失败 {strm_path.name}：{e}")
        if written:
            logger.info(f"【{self.plugin_name}】{media_dir.name} 已自建 {written} 个 strm（直链 {base_url}）")
        return written


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
            self._totals["deleted"] += 1
            try:
                self.save_data("totals", self._totals)
            except Exception:  # noqa: BLE001
                pass
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

    def _drop_local(self, spec: Dict[str, Any], media_dir: Path) -> bool:
        """被年级/非课程闸门拦下的条目：直接删本地（省磁盘，不进回收站）"""
        import shutil

        try:
            n = sum(1 for p in media_dir.rglob("*") if p.is_file())
            shutil.rmtree(media_dir, ignore_errors=True)
            self._prune_empty_parents(spec["local"], media_dir)
            logger.info(f"【{self.plugin_name}】已删除不符合条件的本地目录 {media_dir}（{n} 个文件）")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"【{self.plugin_name}】删除本地目录失败 {media_dir}：{e}")
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
        folder = self._slow(
            lambda: self._storage.get_folder(storage=self._target_storage, path=Path(remote_dir)),
            f"get_folder {remote_dir}",
        )
        if not folder:
            raise RuntimeError(
                f"无法获取/创建 115 目录 {remote_dir}：请确认已安装并启用 115 存储插件"
                f"（{self._target_storage}），且 115 Cookie 有效"
            )

        # 直接挂在 state 上，保证最终状态里带上完整清单（否则下一轮会整目录重传）
        done: Dict[str, Any] = state.setdefault("files", {})
        # 1.5.1：顺手把 115 返回的 pickcode 存进 state（写 .strm 用，零额外 API 调用）
        picks: Dict[str, str] = state.setdefault("pickcodes", {})
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
            item = self._slow(
                lambda: self._storage.upload_file(fileitem=folder, path=f, new_name=remote_name),
                f"upload_file {remote_name}",
            )
            if not item:
                raise RuntimeError(f"上传失败：{f}")
            code = getattr(item, "pickcode", None) or getattr(item, "pick_code", None)
            if code:
                picks[remote_name] = str(code)
            done[name] = size
            uploaded.append(name)
            # 每传完一个就落盘状态，中途崩溃后只补传剩余文件
            self._write_state(media_dir, {**state, "status": "uploading"})
            logger.info(f"【{self.plugin_name}】已上传 {remote_dir}/{remote_name}")

        return uploaded, skipped

    def _remote_name_for(self, spec: Dict[str, Any], media_dir: Path, f: Path) -> str:
        """该文件在 115 / strm 里的文件名（课程模式用模板，剧集模式带 SxxExx）"""
        if f.suffix.lower() in self._video_ext:
            if self._curriculum_mode:
                return self._entry_stem(spec, media_dir) + f.suffix
            if self._series_mode:
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
            "curriculum_mode": False,
            "curriculum_csv": "",
            "curriculum_fix": "",
            "dir_template": "{stage}{grade}({volume})",
            "file_template": "{unit_no} {unit} - {lesson} - {upper}",
            "topic_template": "专题·{series}",
            "unmapped_policy": "topic",
            "grade_allowlist": [],
            "offgrade_policy": "keep",
            "topic_group": "series",
            "topic_alias": "",
            "subject_from_title": True,
            "interval_seconds": 300,
            "max_per_round": 3,
            "max_per_hour": 6,
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
                                    "① 单目录：/data/bili/合集 => 合集（省略 => 时用本地目录名）\n"
                                    "② 自动展开（推荐）：/downloads/bili => @auto —— 自动把 <父>/<科目>/<UP目录> 两级展开，"
                                    "115 子目录名取「科目」，新增科目或新 UP 无需改配置",
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
                            _col(
                                5,
                                {
                                    "component": "VSelect",
                                    "props": {
                                        "model": "grade_allowlist",
                                        "label": "只上传这些年级（多选，留空=全部）",
                                        "items": [
                                            {"title": "初中七（七上+七下）", "value": "初中七"},
                                            {"title": "初中八（八上+八下）", "value": "初中八"},
                                            {"title": "初中九（九上+九下）", "value": "初中九"},
                                            {"title": "高中一", "value": "高中一"},
                                            {"title": "高中二", "value": "高中二"},
                                            {"title": "高中三", "value": "高中三"},
                                            {"title": "小学一", "value": "小学一"},
                                            {"title": "小学二", "value": "小学二"},
                                            {"title": "小学三", "value": "小学三"},
                                            {"title": "小学四", "value": "小学四"},
                                            {"title": "小学五", "value": "小学五"},
                                            {"title": "小学六", "value": "小学六"},
                                        ],
                                        "multiple": True,
                                        "chips": True,
                                        "clearable": True,
                                        "hint": "选「初中七」就只上传七上/七下，八、九年级一律不上传；"
                                                "专题/专栏（语法线、实验视频等）不受此限制",
                                        "persistent-hint": True,
                                    },
                                },
                            ),
                            _col(
                                4,
                                {
                                    "component": "VSelect",
                                    "props": {
                                        "model": "offgrade_policy",
                                        "label": "非目标年级怎么处理",
                                        "items": [
                                            {"title": "留本地，不上传（推荐先这样）", "value": "keep"},
                                            {"title": "不上传，并删本地（省磁盘）", "value": "delete"},
                                        ],
                                        "hint": "选「删本地」后，非目标年级下载完就会被删掉，只保留目标年级和专题",
                                        "persistent-hint": True,
                                    },
                                },
                            ),
                            _col(
                                3,
                                {
                                    "component": "VSelect",
                                    "props": {
                                        "model": "topic_group",
                                        "label": "专题目录按什么分组",
                                        "items": [
                                            {"title": "合集名 / UP 名（默认）", "value": "series"},
                                            {"title": "标题里的【标签】（如【非连续文本】【诗歌阅读】）", "value": "tag"},
                                            {"title": "合集名/标签（两级）", "value": "both"},
                                        ],
                                        "hint": "语文这种「一个 UP 发很多专栏」的，选「标题标签」就会分成 "
                                                "语文/专题·非连续文本、语文/专题·诗歌阅读 这样；"
                                                "英语按合集订的保持默认即可",
                                        "persistent-hint": True,
                                    },
                                },
                            ),
                            _col(1, _switch("curriculum_mode", "课程模式")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                {
                                    "component": "VTextarea",
                                    "props": {
                                        "model": "topic_alias",
                                        "label": "专题标签别名（每行 旧名=新名，可留空）",
                                        "rows": 4,
                                        "placeholder": "语法=语法线\n单词=单词线\n词汇=单词线\n累计单词=单词线\n听力=听力线\n听写=听力线",
                                        "hint": "用来把同义专栏并进一个目录：例如投稿里的「【语法】…」和合集「语法线」"
                                                "会并到 专题·语法线；留空则各用各的名字",
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
                                5,
                                {
                                    "component": "VSelect",
                                    "props": {
                                        "model": "unmapped_policy",
                                        "label": "认不出年级册时怎么办",
                                        "items": [
                                            {"title": "归到「专题·<合集名>」（推荐）", "value": "topic"},
                                            {"title": "先不上传，等我来补", "value": "hold"},
                                            {"title": "不上传，并删本地（当垃圾清掉）", "value": "delete"},
                                        ],
                                        "hint": "专题/专栏课建议用「专题」；想严格只要教材内容就选「先不上传」；"
                                                "「删本地」用于清理 vlog/表情包这类非课程",
                                        "persistent-hint": True,
                                    },
                                },
                            ),
                            _col(
                                4,
                                _text(
                                    "curriculum_csv",
                                    "（可选）批量导入 CSV 路径",
                                    "留空即可，日常不用它。需要一次导入几百条时才用，如 /config/curriculum.csv",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                _switch(
                                    "subject_from_title",
                                    "综合 UP：以标题里的【学科】为准（【数学】→数学/、【地理】→地理/）",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                {
                                    "component": "VTextarea",
                                    "props": {
                                        "model": "curriculum_fix",
                                        "label": "映射修正（一般留空，认错的才写一行）",
                                        "rows": 6,
                                        "placeholder": "BV1AB3F6qEAQ | 初中 | 七 | 上 | 01 | 有理数 | 有理数与数轴",
                                        "hint": "每行一条，竖线分隔。格式：视频BV号 | 学段 | 年级 | 册 | 章号 | 章名 | 课题。"
                                                "后面几项可以省（只写 BV号|年级|册 也行）。内置人教版 29 章词典会自动归类，"
                                                "绝大多数视频不用写；认错的、或词典没收录的才在这里补一行，保存后下一轮扫描就生效",
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
                                4,
                                _text(
                                    "dir_template",
                                    "目录名模板（学科下那一层）",
                                    "默认 {stage}{grade}({volume}) → 例如 初中七(上)；学科那层来自监控目录映射，不要重复写",
                                ),
                            ),
                            _col(
                                4,
                                _text(
                                    "file_template",
                                    "文件名模板",
                                    "默认 {unit_no} {unit} - {lesson} - {upper} → 例如 01 有理数 - 有理数与数轴 - 一数-初中版",
                                ),
                            ),
                            _col(
                                4,
                                _text(
                                    "topic_template",
                                    "专题目录模板",
                                    "默认 专题·{series} → 例如 专题·语法线（{series}=合集目录名）",
                                ),
                            ),
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
                            _col(3, _text("interval_seconds", "扫描周期（秒）", "最小 60")),
                            _col(
                                3,
                                _text("max_per_round", "每轮最多上传（集）", "一轮里最多传几个；0=不限制。建议 3～5"),
                            ),
                            _col(
                                3,
                                _text(
                                    "max_per_hour",
                                    "每小时最多上传（集）",
                                    "0=不限制。115 有访问上限，建议 6～10，撞风控就调小",
                                ),
                            ),
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
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                4,
                                _switch("strm_self_gen", "自建 strm（不依赖 CMS 增量同步）"),
                            ),
                            _col(
                                8,
                                _text(
                                    "strm_302_domain",
                                    "115 直链前缀（可选，留空用 CMS 地址）",
                                    "如 http://192.168.1.26:9527。开启自建后，插件按 {前缀}/d/{pickcode}.mp4?/{文件名} 直接写 .strm；"
                                    "适合 CMS 收不到 115 秒传事件、strm 迟迟不生成的情况",
                                ),
                            ),
                        ],
                    },
                ],
            }
        ], defaults

    def _status_snapshot(self) -> Dict[str, Any]:
        """读取上次写入的 status.json（纯读文件，不扫目录，保证详情页秒开）"""
        try:
            if self._status_path.exists():
                return json.loads(self._status_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"【{self.plugin_name}】读取 status.json 失败：{e}")
        return {}

    def get_page(self) -> Optional[List[Dict[str, Any]]]:
        """详情页：任务数据统计（只读状态快照，绝不扫描目录）"""
        snap = self._status_snapshot()
        totals = snap.get("totals") or {}
        rnd = snap.get("round") or {}
        cur = snap.get("curriculum") or {}
        queue = snap.get("queue") or {}

        metrics = [
            {"指标": "累计上传", "值": totals.get("uploaded", 0)},
            {"指标": "累计删除本地", "值": totals.get("deleted", 0)},
            {"指标": "累计失败", "值": totals.get("failed", 0)},
            {"指标": "近 1 小时已上传", "值": snap.get("uploaded_last_hour", 0)},
            {
                "指标": "本轮 扫描/上传/跳过/失败",
                "值": "%s / %s / %s / %s"
                % (
                    rnd.get("scanned", 0),
                    rnd.get("uploaded", 0),
                    rnd.get("skipped", 0),
                    rnd.get("failed", 0),
                ),
            },
            {
                "指标": "队列（待上传/等strm/卡住）",
                "值": "%s / %s / %s"
                % (queue.get("pending", 0), queue.get("waiting", 0), queue.get("stuck", 0)),
            },
            {
                "指标": "周期 / 每轮上限 / 每小时上限",
                "值": "%s 秒 / %s 集 / %s 集"
                % (
                    snap.get("interval_seconds", self._interval_seconds),
                    snap.get("max_per_round", self._max_per_round),
                    snap.get("max_per_hour", self._max_per_hour),
                ),
            },
            {
                "指标": "上次完成 / 下次运行",
                "值": "%s → %s" % (snap.get("updated_at", "-"), snap.get("next_run_at", "-")),
            },
            {"指标": "115 风控冷却至", "值": snap.get("risk_paused_until") or "无"},
            {
                "指标": "年级白名单 / 非目标策略",
                "值": "%s / %s"
                % (
                    "、".join(cur.get("grade_allowlist") or []) or "不限",
                    cur.get("offgrade_policy") or self._offgrade_policy,
                ),
            },
            {
                "指标": "被年级拦下 / 非课程拦下",
                "值": "%s / %s" % (cur.get("skipped_grade", 0), cur.get("skipped_noncourse", 0)),
            },
            {"指标": "待补映射（认不出年级册）", "值": len(self._unmapped)},
        ]

        blocks: List[Dict[str, Any]] = [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-1 font-weight-bold mb-2"},
                                "text": "任务数据统计",
                            },
                            {
                                "component": "VTable",
                                "props": {
                                    "density": "compact",
                                    "headers": [
                                        {"title": "指标", "key": "指标"},
                                        {"title": "值", "key": "值"},
                                    ],
                                    "items": metrics,
                                },
                            },
                        ],
                    }
                ],
            }
        ]

        recent = snap.get("recent") or []
        if recent:
            rows = []
            for ev in recent[-15:]:
                rows.append(
                    {
                        "时间": ev.get("time") or ev.get("at") or "",
                        "结果": ev.get("result") or ev.get("status") or "",
                        "目录": (ev.get("dir") or ev.get("name") or "")[:80],
                    }
                )
            blocks.append(
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "text-subtitle-1 font-weight-bold mb-2 mt-4"},
                                    "text": "最近上传记录",
                                },
                                {
                                    "component": "VTable",
                                    "props": {
                                        "density": "compact",
                                        "headers": [
                                            {"title": "时间", "key": "时间"},
                                            {"title": "结果", "key": "结果"},
                                            {"title": "目录", "key": "目录"},
                                        ],
                                        "items": rows,
                                    },
                                },
                            ],
                        }
                    ],
                }
            )

        if self._curriculum_mode:
            self._curriculum.reload()
            buckets: Dict[str, int] = {}
            for rec in list(self._curriculum.by_bvid.values()) + self._curriculum.csv_rows:
                if rec.get("grade") and rec.get("volume"):
                    key = f"{rec.get('stage') or '初中'}{rec['grade']}({rec['volume']})"
                    buckets[key] = buckets.get(key, 0) + 1
            stat_rows = [{"年级册": k, "条数": v} for k, v in sorted(buckets.items())]
            blocks.append(
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "text-subtitle-1 font-weight-bold mb-2 mt-4"},
                                    "text": (
                                        f"课程模式：手工修正 {len(self._curriculum.by_bvid)} 条 · "
                                        f"待补映射 {len(self._unmapped)} 条"
                                    ),
                                },
                                {
                                    "component": "VTable",
                                    "props": {
                                        "density": "compact",
                                        "headers": [
                                            {"title": "年级册", "key": "年级册"},
                                            {"title": "条数", "key": "条数"},
                                        ],
                                        "items": stat_rows,
                                    },
                                },
                            ],
                        }
                    ],
                }
            )

        if self._unmapped:
            rows = [
                {"目录": u.get("目录", ""), "原因": (u.get("原因") or "")[:70]} for u in self._unmapped[:20]
            ]
            blocks.append(
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "text-subtitle-1 font-weight-bold mb-2 mt-4"},
                                    "text": "待补映射（认不出年级册，落专题或卡住）",
                                },
                                {
                                    "component": "VTable",
                                    "props": {
                                        "density": "compact",
                                        "headers": [
                                            {"title": "目录", "key": "目录"},
                                            {"title": "原因", "key": "原因"},
                                        ],
                                        "items": rows,
                                    },
                                },
                            ],
                        }
                    ],
                }
            )
        return blocks

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


# ---------------------------------------------------------------------------
# 课程模式（1.6.0）：映射表 + 年级册/单元/课题
# ---------------------------------------------------------------------------

CURRICULUM_COLUMNS = [
    "bvid", "title", "subject", "stage", "grade", "volume",
    "unit_no", "unit", "lesson", "version", "confidence",
]

# 【七上】【初一】（八下）等年级标签 → (学段, 年级, 册)
_TAG_RE = re.compile(r"[【\[（(]\s*(初|高)?\s*([一二三四五六七八九])\s*(上|下|全)?\s*[】\]）)]")
# 没有括号也认：`八上`、`七年级上册`、`九年级上`、`初二下`、`高一`
_PLAIN_RE = re.compile(
    r"(?:初\s*([一二三])|高\s*([一二三])|([七八九一二三四五六])\s*年级?|[七八九])\s*([上下全])"
)
_JUNIOR_MAP = {"一": "七", "二": "八", "三": "九"}


def _parse_grade_tag(text: str) -> Dict[str, str]:
    """从合集名/目录名/标题里读年级册：`【七上】`→初中七(上)，`八年级上册`→初中八(上)，`高一`→高中一"""
    s = text or ""
    m = _TAG_RE.search(s)
    if m:
        prefix, digit, volume = m.group(1), m.group(2), m.group(3) or ""
        if prefix == "初":
            return {"stage": "初中", "grade": _JUNIOR_MAP.get(digit, digit), "volume": volume}
        if prefix == "高":
            return {"stage": "高中", "grade": digit, "volume": volume}
        stage = "初中" if digit in "七八九" else ""
        return {"stage": stage, "grade": digit, "volume": volume}
    m = _PLAIN_RE.search(s)
    if m:
        junior, senior, plain, volume = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        if junior:
            return {"stage": "初中", "grade": _JUNIOR_MAP.get(junior, junior), "volume": volume}
        if senior:
            return {"stage": "高中", "grade": senior, "volume": volume}
        # 纯 `八上` / `七年级上`
        seg = m.group(0)
        digit = next((c for c in seg if c in "七八九一二三四五六"), plain or "")
        if digit:
            stage = "初中" if digit in "七八九" else ""
            return {"stage": stage, "grade": digit, "volume": volume}
    return {}


def _norm_title(s: str) -> str:
    """标题归一化：只留中日文/字母/数字，用来做「115 文件名 ↔ 映射表 title」的模糊匹配"""
    s = re.sub(r"[\s\-_·|｜:，,。!！?？~～【】\[\]（）()<>《》\"'“”‘’/\\]+", "", str(s or ""))
    return s.lower()


# 标题里【】中出现的学科名（综合 UP 会用它标学科，如「【数学】八上 11.1 …」）
_KNOWN_SUBJECTS = {
    "数学": "数学", "语文": "语文", "英语": "英语", "物理": "物理", "化学": "化学",
    "生物": "生物", "历史": "历史", "地理": "地理", "科学": "科学",
    "政治": "道德与法治", "道法": "道德与法治", "道德与法治": "道德与法治",
}
_SUBJECT_TAG_RE = re.compile(r"【\s*([^】]{1,8}?)\s*】")


_TAG_SKIP_RE = re.compile(r"^(梓墨说|梓墨品书|新课速递|开学第一课|.*新课.*|.*抽奖.*|.*广告.*)$")
# 标签里常见的编号：写作W19 / W15 / #F01 / 第3讲 / 03
_TAG_CODE_TAIL = re.compile(r"[\s\-_·]*(?:[A-Za-z]{1,3}|#)?\s*\d{1,4}\s*$")
_TAG_CODE_HEAD = re.compile(r"^[\s\-_·#]*(?:[A-Za-z]{1,3})?\s*\d{1,4}[\s\-_·:：]*")


def _first_title_tag(title: str) -> str:
    """取标题里第一个【标签】做专题分组名，并去掉编号（【写作W19】→写作、【W15】→空）"""
    for m in re.finditer(r"【\s*([^】]{1,14}?)\s*】", str(title or "")):
        tag = m.group(1).strip()
        tag = tag.replace("沖", "冲").replace("衝", "冲")
        tag = re.sub(r"^(精读|精讲|专题|连载|系列|解读)\s*[·・:：\-_]\s*", "", tag).strip()
        # 去掉结尾/开头的编号，避免「写作W19」「W15」各自成目录
        tag = _TAG_CODE_TAIL.sub("", tag).strip()
        tag = _TAG_CODE_HEAD.sub("", tag).strip()
        tag = tag.strip("#＃·・-_ 　")
        if len(tag) < 2 or _TAG_SKIP_RE.match(tag):
            continue
        return tag
    return ""


def _parse_subject_tag(title: str) -> str:
    """标题里的【数学】/【地理】→ 学科名（不认识的一律忽略，避免把【初一】当学科）"""
    for m in _SUBJECT_TAG_RE.finditer(str(title or "")):
        name = _KNOWN_SUBJECTS.get(m.group(1).strip())
        if name:
            return name
    return ""


_NOISE_WORDS = sorted([
    "持续更新", "一个视频全覆盖", "一个视频全通关", "一次性吃透全部题型", "学完拿满分",
    "学霸必会都在这", "全面知识和思维提升", "史上最全", "快速上手", "搞定", "速通",
    "满分大合集", "满分", "通关", "大全", "大合集", "合集", "必会", "必考", "超高频",
    "重难点", "核心解法", "核心", "精讲", "详解", "初中数学",
], key=len, reverse=True)
_SEG_SPLIT = re.compile(r"[，,｜|！!？?。～~：:\s]+")
_GENERIC_PREFIX = re.compile(r"^(考试必考难点|考试难点|高频考点|重难点|难点|重点|方法|技巧|总结|注意)[：:]\s*")


def _clean_lesson(title: str, limit: int = 40) -> str:
    """把营销体标题洗成能看的课题名（只影响显示，不影响归类）"""
    raw = re.sub(r"【[^】]*】", "", str(title or "")).replace("　", " ")
    segs = [s for s in _SEG_SPLIT.split(raw) if s and not re.fullmatch(r"[\d\-–—.%]+", s)]
    t = max(segs, key=len) if segs else raw
    t = _GENERIC_PREFIX.sub("", t)
    t = re.sub(r"\d+\s*[-–—]\s*\d+\s*[节讲]", "", t)
    for w in _NOISE_WORDS:
        t = t.replace(w, "")
    t = re.sub(r"[【】\[\]（）()<>《》]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -_·，,。.!！?？~～")
    return (t[:limit].strip(" -_·") or str(title or "")[:limit]).strip()


# 人教版初中数学 29 章 + 专题（内置词典，零配置也能归类）
_UNIT_TABLE: Dict[str, Tuple[str, str, str]] = {
    "01": ("七", "上", "有理数"), "02": ("七", "上", "整式的加减"),
    "03": ("七", "上", "一元一次方程"), "04": ("七", "上", "几何图形初步"),
    "05": ("七", "下", "相交线与平行线"), "06": ("七", "下", "实数"),
    "07": ("七", "下", "平面直角坐标系"), "08": ("七", "下", "二元一次方程组"),
    "09": ("七", "下", "不等式与不等式组"), "10": ("七", "下", "数据的收集整理与描述"),
    "11": ("八", "上", "三角形"), "12": ("八", "上", "全等三角形"),
    "13": ("八", "上", "轴对称"), "14": ("八", "上", "整式的乘法与因式分解"),
    "15": ("八", "上", "分式"), "16": ("八", "下", "二次根式"),
    "17": ("八", "下", "勾股定理"), "18": ("八", "下", "平行四边形"),
    "19": ("八", "下", "一次函数"), "20": ("八", "下", "数据的分析"),
    "21": ("九", "上", "一元二次方程"), "22": ("九", "上", "二次函数"),
    "23": ("九", "上", "旋转"), "24": ("九", "上", "圆"),
    "25": ("九", "上", "概率初步"), "26": ("九", "下", "反比例函数"),
    "27": ("九", "下", "相似"), "28": ("九", "下", "锐角三角函数"),
    "29": ("九", "下", "投影与视图"), "98": ("九", "下", "专题·模型"),
    "99": ("九", "下", "中考压轴专题"),
}

# 顺序 = 优先级：专题最先，具体知识点随后，泛词兜底，最后才是"压轴"
_UNIT_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("99", ["阿氏圆", "隐圆", "费马点", "瓜豆", "胡不归", "阿基米德折弦"]),
    ("21", ["一元二次方程", "韦达定理", "根与系数", "判别式", "配方法"]),
    ("03", ["一元一次方程", "移项", "去分母", "列方程解应用题"]),
    ("08", ["二元一次方程"]),
    ("09", ["不等式"]),
    ("22", ["二次函数", "抛物线", "顶点式", "区间最值", "多结论"]),
    ("26", ["反比例", "双曲线", "面积模型"]),
    ("19", ["一次函数", "正比例函数"]),
    ("28", ["三角函数", "正弦", "余弦", "正切", "解直角三角形", "仰角", "俯角", "坡度"]),
    ("27", ["相似", "位似", "黄金分割"]),
    ("12", ["全等", "倍长中线", "角平分线", "半角模型", "截长补短", "一线三等角"]),
    ("13", ["轴对称", "等腰三角形", "等边三角形", "垂直平分线", "将军饮马"]),
    ("17", ["勾股"]),
    ("18", ["平行四边形", "矩形", "菱形", "正方形", "中位线"]),
    ("05", ["平行线", "相交线", "同位角", "内错角", "同旁内角", "拐点"]),
    ("01", ["有理数", "数轴", "相反数", "绝对值", "正负数"]),
    ("02", ["整式加减", "整式的加减", "合并同类项", "去括号"]),
    ("14", ["整式乘法", "幂的运算", "平方差", "完全平方", "因式分解", "提公因式", "十字相乘"]),
    ("15", ["分式"]),
    ("16", ["二次根式", "分母有理化"]),
    ("06", ["平方根", "立方根", "无理数", "实数"]),
    ("07", ["平面直角坐标系", "坐标系", "象限"]),
    ("04", ["几何图形初步", "射线线段", "余角", "补角", "展开图", "角的度量"]),
    ("20", ["平均数", "中位数", "众数", "方差"]),
    ("23", ["旋转", "中心对称"]),
    ("25", ["概率", "树状图"]),
    ("29", ["三视图", "投影"]),
    ("10", ["统计调查", "直方图", "频数"]),
    ("24", ["圆周角", "圆心角", "切线", "垂径定理", "弧长", "扇形", "圆"]),
    ("11", ["三角形", "三边关系", "多边形内角和"]),
    ("99", ["中考压轴", "压轴"]),
]


def _guess_unit(title: str) -> Tuple[str, str]:
    """内置词典：标题里的知识点 → (章号, 命中词)；匹配不到返回 ("", "")"""
    t = str(title or "")
    cands: List[Tuple[int, int, int, int, str, str]] = []
    for order, (unit, keys) in enumerate(_UNIT_KEYWORDS):
        tier = 0 if (unit == "99" and keys and keys[0] not in ("中考压轴", "压轴")) else 1
        for idx, k in enumerate(keys):
            pos = t.find(k)
            if pos >= 0:
                cands.append((tier, pos, order, idx, unit, k))
                break
    if not cands:
        return "", ""
    best = min(cands)
    return best[4], best[5]


class _CurriculumMap:
    """
    映射表：bvid / 标题 → 学段/年级/册/章号/章名/课题。

    三个来源，后者覆盖前者：
      ① 内置词典（人教版 29 章 + 专题，按标题关键词命中，零配置）
      ② 插件配置页「映射修正」多行文本（网页里改，立即生效）
      ③ 可选 CSV（老用户/批量导入，路径留空就不用）
    """

    def __init__(self, fix_text: str = "", path: str = ""):
        self.fix_text = str(fix_text or "")
        self.path = str(path or "").strip()
        self._mtime = -1.0
        self.by_bvid: Dict[str, Dict[str, str]] = {}
        self.by_title: Dict[str, Dict[str, str]] = {}
        self.csv_rows: List[Dict[str, str]] = []
        self.error = ""

    # ---------------- 解析 ----------------

    @staticmethod
    def _parse_fix(text: str) -> List[Dict[str, str]]:
        """把配置页里的多行文本解析成行：bvid | 学段 | 年级 | 册 | 章号 | 章名 | 课题"""
        out: List[Dict[str, str]] = []
        for line in str(text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in re.split(r"[|\t]", line)]
            if len(parts) < 3:
                continue
            rec = {k: "" for k in CURRICULUM_COLUMNS}
            rec["bvid"] = parts[0]
            rest = parts[1:]
            if rest and rest[0] in ("小学", "初中", "高中"):
                rec["stage"] = rest.pop(0)
            if rest:
                rec["grade"] = rest.pop(0)
            if rest:
                rec["volume"] = rest.pop(0)
            if rest:
                rec["unit_no"] = rest.pop(0)
            if rest:
                rec["unit"] = rest.pop(0)
            if rest:
                rec["lesson"] = rest.pop(0)
            if not rec["stage"]:
                rec["stage"] = "初中"
            out.append(rec)
        return out

    def _reload_csv(self) -> None:
        if not self.path:
            return
        try:
            st = os.stat(self.path)
        except OSError as e:
            self.error = f"读不到 CSV {self.path}：{e}（可留空不用）"
            return
        if st.st_mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                raw = list(csv.DictReader(f))
        except Exception as e:  # noqa: BLE001
            self.error = f"解析 CSV 失败：{e}"
            return
        rows = []
        for r in raw:
            rec = {k: str(r.get(k) or "").strip() for k in CURRICULUM_COLUMNS}
            if not rec["stage"]:
                rec["stage"] = "初中"
            rows.append(rec)
        self.csv_rows = rows
        self._mtime, self.error = st.st_mtime, ""

    def _rebuild_index(self) -> None:
        by_bvid: Dict[str, Dict[str, str]] = {}
        by_title: Dict[str, Dict[str, str]] = {}
        for rec in self._parse_fix(self.fix_text) + self.csv_rows:
            if rec.get("bvid"):
                by_bvid[rec["bvid"]] = rec
            if rec.get("title"):
                by_title[_norm_title(rec["title"])] = rec
        self.by_bvid, self.by_title = by_bvid, by_title

    def reload(self) -> None:
        self._reload_csv()
        self._rebuild_index()

    # ---------------- 查询 ----------------

    def lookup(self, bvid: str = "", title: str = "", subject: str = "") -> Dict[str, str]:
        self.reload()
        if bvid and bvid in self.by_bvid:
            return dict(self.by_bvid[bvid], _match="bvid")
        if title:
            key = _norm_title(title)
            if key in self.by_title:
                return dict(self.by_title[key], _match="title")
            # 退化匹配：标题前缀对得上（115 上的名字可能被截断）
            for k, rec in self.by_title.items():
                if not k:
                    continue
                if (key.startswith(k) or k.startswith(key)) and min(len(k), len(key)) >= 8:
                    return dict(rec, _match="title~")
        # ③ 内置词典兜底：**只对数学启用**（这张表是人教版初中数学的 29 章，
        #    套到英语/生物上会误判——实测「英语·概率问题」会被算成数学九上第 25 章）
        unit_no, _key = _guess_unit(title or "") if subject in ("", "数学") else ("", "")
        if unit_no and unit_no in _UNIT_TABLE:
            _g, _v, _u = _UNIT_TABLE[unit_no]
            return {
                "bvid": bvid, "title": title, "subject": "", "stage": "初中",
                "grade": _g, "volume": _v, "unit_no": unit_no, "unit": _u,
                "lesson": _clean_lesson(title or ""),
                "version": "人教", "confidence": "dict", "_match": "dict",
            }
        return {}












