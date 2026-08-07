import threading
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from app.chain.media import MediaChain
from app.core.event import eventmanager, Event
from app.core.metainfo import MetaInfo
from app.plugins import _PluginBase
from .doubanapi import DoubanApi
from app.schemas import WebhookEventInfo, MediaInfo
from app.schemas.types import EventType, MediaType
import re
from app.log import logger
from app.schemas import Notification, NotificationType, MessageChannel
from .sync_models import (
    DATETIME_FORMAT,
    MATCHER_VERSION,
    DoubanActionResult,
    EpisodeMetadata,
    FailureKind,
    SubjectCandidate,
    SubjectResolveResult,
    TERMINAL_FAILURES,
    build_segmented_subject_mapping,
    failure_is_suppressed,
    find_processed_record_key,
    normalize_wait_entry,
    prepare_retry_attempt,
    record_retry_failure,
    resolve_subject_target,
    retry_is_due,
    schedule_initial_retry,
    segment_from_mapping_cache,
    should_use_segmented_fallback,
    status_for_segment,
)

lock = threading.Lock()


class DoubanMediaFolio(_PluginBase):
    # 插件名称
    plugin_name = "豆瓣影音档案"
    # 插件描述
    plugin_desc = "追剧观影自动同步进度到豆瓣，打造专属观影档案"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/xijin285/MoviePilot-Plugins/refs/heads/main/icons/douban.png"
    # 插件版本
    plugin_version = "1.0.7"
    # 插件作者
    plugin_author = "wYw"
    # 作者主页
    author_url = "https://github.com/saarjoye/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "doubanmediafolio_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    _enable = False
    _private = True
    _first = True
    _user = ""
    _exclude = ""
    _cookie = ""
    _douban_username = ""
    _douban_password = ""
    _auto_login = True

    _pc_month = None
    _pc_num = None
    _mobile_month = None
    _mobile_num = None

    _wait_process: Dict = None
    _failed_process: Dict = None
    _tv_mappings: Dict = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sync_lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enable = config.get("enable", False)
        self._private = config.get("private", True)
        self._first = config.get("first", True)
        self._user = config.get("user", "")
        self._exclude = config.get("exclude", "")
        self._cookie = config.get("cookie", "")
        self._douban_username = config.get("douban_username", "")
        self._douban_password = config.get("douban_password", "")
        self._auto_login = config.get("auto_login", True)

        self._pc_month = int(config.get("pc_month")) if config.get("pc_month", None) else 3
        self._pc_num = int(config.get("pc_num", 50)) if config.get("pc_num", None) else 50
        self._mobile_month = int(config.get("mobile_month")) if config.get("mobile_month", None) else 2
        self._mobile_num = int(config.get("mobile_num", None)) if config.get("mobile_num", None) else 15
        self._notify = config.get("notify", False)

        if self.get_data("processed"):
            from app.db.plugindata_oper import PluginDataOper
            PluginDataOper().del_data(plugin_id="DoubanMediaFolio")
            logger.warn("检测到本插件旧版本数据，删除旧版本数据，避免报错...")

        if self._enable:
            logger.info("豆瓣观影档案插件已启用")

    @eventmanager.register(EventType.WebhookMessage)
    def sync_log(self, event: Event, played: bool = False):
        if not hasattr(self, '_sync_lock'):
            self._sync_lock = threading.Lock()
        if not self._sync_lock.acquire(blocking=False):
            import time
            now = time.time()
            if not hasattr(self, '_last_skip_log_time'):
                self._last_skip_log_time = 0
            if now - self._last_skip_log_time > 600:  # 10分钟
               # logger.info("同步流程已在进行中，跳过本次事件处理，防止重复通知。")
                self._last_skip_log_time = now
            return
        try:
            import time
            if not hasattr(self, '_last_cookie_check_time'):
                self._last_cookie_check_time = 0
            now = time.time()
            if now - self._last_cookie_check_time > 3600:  # 1小时
                try:
                    douban_helper = self._get_douban_helper()
                    auth_result = douban_helper.check_auth_status(allow_login=True)
                except Exception as err:
                    auth_result = None
                    logger.warning(f"检查豆瓣登录状态异常: {DoubanApi._safe_message(err)}")

                if auth_result and auth_result.success:
                    self._cookie = douban_helper.get_cookie_string()
                    self._cookie_invalid_notified = False
                    if not hasattr(self, '_last_cookie_valid_time'):
                        self._last_cookie_valid_time = 0
                    if now - self._last_cookie_valid_time > 600:
                        logger.info("豆瓣登录状态检测通过")
                        self._last_cookie_valid_time = now
                elif auth_result and auth_result.explicitly_logged_out:
                    if not getattr(self, '_cookie_invalid_notified', False):
                        message = (
                            "豆瓣登录状态已明确失效，自动登录未成功，请人工登录或更新Cookie。"
                            if auth_result.login_attempted
                            else "豆瓣登录状态已明确失效，请人工登录或更新Cookie。"
                        )
                        self._send_notification(False, message)
                        self._cookie_invalid_notified = True
                elif auth_result:
                    if not hasattr(self, '_last_cookie_check_warning_time'):
                        self._last_cookie_check_warning_time = 0
                    if now - self._last_cookie_check_warning_time > 21600:
                        logger.warning(auth_result.message or "暂时无法确认豆瓣登录状态")
                        self._last_cookie_check_warning_time = now
                self._last_cookie_check_time = now

            event_info: WebhookEventInfo = event.event_data
            play_start = {"playback.start", "media.play", "PlaybackStart"}
            path = event_info.item_path
            processed_items: Dict = self.get_data('data') or {}
            self._wait_process: Dict = self.get_data('wait') or {}
            self._failed_process: Dict = self.get_data('failed') or {}
            self._tv_mappings: Dict = self.get_data('tv_mappings') or {}

            if (event_info.event in play_start and event_info.user_name in self._user.split(',')) or played:
                if played:
                    logger.info(f"标记播放完成 {event_info.item_name}")

                if not self.exclude_keyword(path=path, keywords=self._exclude).get("ret", False):
                    logger.info(self.exclude_keyword(path=path, keywords=self._exclude).get("message", ""))
                    return

                if event_info.item_type == "TV":
                    self._process_tv_show(event_info, processed_items, played=played)
                elif event_info.item_type == "MOV":
                    self._process_movie(event_info, processed_items, played=played)
                else:
                    return
        finally:
            self._sync_lock.release()
            self._skip_log_printed = False

    @eventmanager.register(EventType.WebhookMessage)
    def sync_played(self, event: Event):
        event_info: WebhookEventInfo = event.event_data
        played = {'item.markplayed', 'media.scrobble'}
        is_played = event_info.event in played
        if event_info.channel == "jellyfin":
            is_played = event_info.event == 'UserDataSaved' and event_info.save_reason == 'TogglePlayed'

        if is_played and event_info.user_name in self._user.split(','):
            with lock:
                self.sync_log(event=event, played=True)

    def _process_tv_show(self, event_info: WebhookEventInfo, processed_items: Dict, played: bool = False):
        index = event_info.item_name.index(" S")
        title = event_info.item_name[:index]
        season_id, episode_id = map(int, [event_info.season_id, event_info.episode_id])
        tmdb_id = event_info.tmdb_id

        if not played:
            logger.info(f"开始播放 {title} 第{season_id}季 第{episode_id}集")

        if episode_id < 2 and self._first:
            logger.info(f"剧集第1集的活动不同步到豆瓣档案，跳过")
            return

        meta = MetaInfo(title)
        meta.begin_season = season_id
        meta.type = MediaType("电视剧")
        mediainfo = self._recognize_media(meta, tmdb_id)

        if not mediainfo:
            logger.warn(f'标题：{title}，tmdbid：{tmdb_id}，指定tmdbid未识别到媒体信息，尝试仅使用标题识别')
            meta.tmdbid = None
            mediainfo = self._recognize_media(meta, None)
            if not mediainfo:
                logger.error(f'仍然未识别到媒体信息，请检查TMDB网络连接...')
                return

        episodes = mediainfo.seasons.get(season_id, [])

        title = self.format_title(title, season_id)
        status = "collect" if len(episodes) == episode_id else "do"

        if processed_items.get(title) and len(episodes) != episode_id:
            logger.info(f"{title} 已同步到豆瓣在看，不处理")
            # 已处理过的条目直接跳过，无需发送通知
            if self._notify:
                logger.info(f"{title} 跳过同步，不发送通知")
            return

        sync_ret = self._sync_to_douban(
            title,
            status,
            event_info.item_type,
            processed_items,
            mediainfo.poster_path,
            direct_douban_id=getattr(mediainfo, "douban_id", None),
            year=getattr(mediainfo, "year", None),
            season_id=season_id,
            episode_id=episode_id,
            episode_count=len(episodes),
            tmdb_id=getattr(mediainfo, "tmdb_id", None) or tmdb_id,
            season_name=self._get_season_name(mediainfo, season_id),
        )
        # 尝试同步之前同步失败的
        if sync_ret:
            logger.info(f"尝试同步之前同步失败的条目")
            self._run_due_waiting_items(processed_items)

    def _process_movie(self, event_info: WebhookEventInfo, processed_items: Dict, played: bool = False):
        title = event_info.item_name

        if not played:
            logger.info(f"开始播放 {title}")

        meta = MetaInfo(title)
        meta.type = MediaType("电影")
        mediainfo = self._recognize_media(meta, event_info.tmdb_id)

        if not mediainfo:
            logger.warn(f'标题：{title}，tmdbid：{event_info.tmdb_id}，指定tmdbid未识别到媒体信息，尝试仅使用标题识别')
            meta.tmdbid = None
            mediainfo = self._recognize_media(meta, None)
            if not mediainfo:
                logger.error(f'仍然未识别到媒体信息，请检查TMDB网络连接...')
                return

        if processed_items.get(title):
            logger.info(f"{title} 已同步到豆瓣在看，不处理")
            return

        self._sync_to_douban(
            title,
            "collect",
            event_info.item_type,
            processed_items,
            mediainfo.poster_path,
            direct_douban_id=getattr(mediainfo, "douban_id", None),
            year=getattr(mediainfo, "year", None),
        )

    def _recognize_media(self, meta: MetaInfo, tmdb_id: Optional[int]) -> Optional[MediaInfo]:
        return MediaChain().recognize_media(meta=meta, mtype=meta.type, tmdbid=tmdb_id, cache=True)

    def _get_douban_helper(self) -> DoubanApi:
        return DoubanApi(
            user_cookie=self._cookie,
            username=self._douban_username,
            password=self._douban_password,
            auto_login=self._auto_login
        )

    @staticmethod
    def _item_value(item, key: str, default=None):
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _get_season_name(self, mediainfo: Optional[MediaInfo], season_id: Optional[int]) -> str:
        for season in getattr(mediainfo, "season_info", None) or []:
            if self._item_value(season, "season_number") == season_id:
                return str(self._item_value(season, "name", "") or "").strip()
        return ""

    @staticmethod
    def _mapping_key(tmdb_id: Optional[int], season_id: Optional[int]) -> str:
        return f"tmdb:{tmdb_id}:s{season_id}"

    def _cached_tv_segment(
            self,
            tmdb_id: Optional[int],
            season_id: Optional[int],
            episode_id: Optional[int],
            season_name: str,
            episode_count: int,
    ):
        if not tmdb_id or season_id is None or episode_id is None:
            return None
        self._tv_mappings = self._tv_mappings or self.get_data('tv_mappings') or {}
        entry = self._tv_mappings.get(self._mapping_key(tmdb_id, season_id))
        expected_name = season_name or str((entry or {}).get("season_name") or "")
        expected_count = episode_count or int((entry or {}).get("episode_count") or 0)
        segment = segment_from_mapping_cache(entry, expected_name, expected_count, episode_id)
        return (segment.candidate, segment.end_episode) if segment else None

    def _resolve_segmented_tv(
            self,
            douban_helper: DoubanApi,
            title: str,
            tmdb_id: Optional[int],
            season_id: Optional[int],
            episode_id: Optional[int],
            episode_count: int,
            season_name: str,
    ):
        if not tmdb_id or season_id is None or episode_id is None:
            return SubjectResolveResult(
                candidate=None,
                kind=FailureKind.NO_MATCH,
                message="缺少 TMDB 季集信息，无法执行兼容匹配",
            ), None
        try:
            from app.chain.tmdb import TmdbChain

            tmdb_chain = TmdbChain()
            if not season_name:
                for season in tmdb_chain.tmdb_seasons(tmdbid=int(tmdb_id)) or []:
                    if self._item_value(season, "season_number") == season_id:
                        season_name = str(self._item_value(season, "name", "") or "").strip()
                        break
            tmdb_episodes = tmdb_chain.tmdb_episodes(tmdbid=int(tmdb_id), season=int(season_id)) or []
        except Exception as err:
            logger.error(f"获取 TMDB 季集元数据失败: {err}")
            return SubjectResolveResult(
                candidate=None,
                kind=FailureKind.TRANSIENT,
                message="获取 TMDB 季集元数据失败",
                retryable=True,
            ), None

        episodes = [
            EpisodeMetadata(
                episode_number=int(self._item_value(item, "episode_number", 0) or 0),
                air_date=self._item_value(item, "air_date"),
            )
            for item in tmdb_episodes
            if self._item_value(item, "episode_number")
        ]
        if not season_name or not episodes:
            return SubjectResolveResult(
                candidate=None,
                kind=FailureKind.NO_MATCH,
                message="TMDB 未提供可用于兼容匹配的季名或单集日期",
            ), None
        if episode_count and len(episodes) != episode_count:
            return SubjectResolveResult(
                candidate=None,
                kind=FailureKind.NO_MATCH,
                message="TMDB 单集元数据尚未完整，暂不执行分段匹配",
            ), None

        base_title = re.sub(r"\s*第\s*[0-9一二三四五六七八九十]+\s*季\s*$", "", title).strip()
        search_result = douban_helper.search_subject_candidates(f"{base_title} {season_name}".strip())
        if not search_result.success and search_result.kind != FailureKind.NONE:
            return SubjectResolveResult(
                candidate=None,
                kind=search_result.kind,
                message=search_result.message,
                retryable=search_result.retryable,
            ), None
        mapping = build_segmented_subject_mapping(
            base_title=base_title,
            season_name=season_name,
            episodes=episodes,
            candidates=search_result.candidates,
        )
        if not mapping.success:
            return SubjectResolveResult(
                candidate=None,
                kind=mapping.kind,
                message=mapping.message,
            ), None
        segment = mapping.segment_for(episode_id)
        if not segment:
            return SubjectResolveResult(
                candidate=None,
                kind=FailureKind.NO_MATCH,
                message=f"当前第 {episode_id} 集不在已确认的豆瓣分段范围内",
            ), None

        self._tv_mappings = self._tv_mappings or self.get_data('tv_mappings') or {}
        self._tv_mappings[self._mapping_key(tmdb_id, season_id)] = {
            "matcher_version": MATCHER_VERSION,
            "season_name": season_name,
            "episode_count": episode_count or len(episodes),
            "segments": [
                {
                    "start_episode": item.start_episode,
                    "end_episode": item.end_episode,
                    "subject_id": item.candidate.subject_id,
                    "subject_name": item.candidate.title,
                    "year": item.candidate.year,
                }
                for item in mapping.segments
            ],
        }
        self.save_data('tv_mappings', self._tv_mappings)
        candidate = SubjectCandidate(
            subject_id=segment.candidate.subject_id,
            title=segment.candidate.title,
            year=segment.candidate.year,
            media_type=segment.candidate.media_type,
            source="tmdb_segment",
        )
        return SubjectResolveResult(candidate=candidate), segment.end_episode

    def _send_notification(self, success: bool, message: str):
        if not self._notify:
            return
        title = f"豆瓣观影档案 {'成功' if success else '失败'}"
        text_content = message.strip()
        text_content += f"\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        try:
            self.post_message(mtype=NotificationType.MediaServer, title=title, text=text_content)
            logger.info(f"{self.plugin_name} 发送通知: {title}")
        except Exception as e:
            error_msg = f'{self.plugin_name} 发送通知失败: {e}'
            if 'The resource you requested could not be found.' in error_msg:
                logger.error('请求的资源未找到（可能是条目不存在或ID错误）')
            else:
                logger.error(error_msg)

    def retry_waiting_items(self):
        """MoviePilot 公共服务入口：扫描并重试已到期的待同步条目。"""
        if not self._enable:
            return
        if not hasattr(self, '_sync_lock'):
            self._sync_lock = threading.Lock()
        if not self._sync_lock.acquire(blocking=False):
            logger.info("豆瓣待同步重试跳过：同步流程正在运行")
            return
        try:
            self._run_due_waiting_items()
        except Exception as err:
            logger.error(f"豆瓣待同步重试服务异常: {DoubanApi._safe_message(err)}")
        finally:
            self._sync_lock.release()

    def _run_due_waiting_items(self, processed_items: Optional[Dict] = None):
        waiting_items = self.get_data('wait') or {}
        if not isinstance(waiting_items, dict):
            logger.error("豆瓣待同步数据格式无效，本次扫描已跳过")
            return

        self._wait_process = waiting_items
        self._failed_process = self.get_data('failed') or {}
        self._tv_mappings = self.get_data('tv_mappings') or {}
        processed_items = processed_items if isinstance(processed_items, dict) else self.get_data('data') or {}

        for title, value in list(waiting_items.items()):
            if not retry_is_due(value):
                continue
            normalized = normalize_wait_entry(value)
            prepared = prepare_retry_attempt(normalized)
            if prepared != normalized:
                self._wait_process[title] = prepared
                self.save_data('wait', self._wait_process)
            value = prepared
            try:
                logger.info(f"尝试自动重试待同步条目: {title}")
                self._retry_waiting_item(title, value, processed_items)
            except Exception as err:
                logger.error(f"待同步条目自动重试异常: {DoubanApi._safe_message(err)}")
                current = self._wait_process.get(title)
                if current and retry_is_due(current):
                    self._handle_retry_exception(title, current)

    def _handle_retry_exception(self, title: str, value: Dict):
        value = normalize_wait_entry(value)
        subject_id = str(value.get("subject_id") or "")
        candidate = SubjectCandidate(
            subject_id=subject_id,
            title=str(value.get("subject_name") or title),
        ) if subject_id else None
        self._handle_sync_failure(
            title=title,
            status=value.get("status", "do"),
            media_type=value.get("type", "TV"),
            poster_path=value.get("poster_path", ""),
            year=value.get("year"),
            season_id=value.get("season_id"),
            episode_id=value.get("episode_id"),
            episode_count=value.get("episode_count", 0),
            tmdb_id=value.get("tmdb_id"),
            season_name=value.get("season_name", ""),
            candidate=candidate,
            action_result=DoubanActionResult(
                success=False,
                kind=FailureKind.TRANSIENT,
                message="待同步自动重试发生内部异常",
                retryable=True,
            ),
            is_retry=True,
            direct_douban_id=value.get("douban_id", ""),
        )

    def _retry_waiting_item(self, title: str, value: Dict, processed_items: Dict) -> bool:
        value = normalize_wait_entry(value)
        media_type = value.get("type", "TV")
        season_id = value.get("season_id")
        meta = MetaInfo(title)
        meta.type = MediaType("电视剧" if media_type == "TV" else "电影")
        if media_type == "TV" and season_id:
            meta.begin_season = season_id
        mediainfo = self._recognize_media(meta, None)
        season_name = self._get_season_name(mediainfo, season_id) if mediainfo else value.get("season_name", "")
        return self._sync_to_douban(
            title=title,
            status=value.get("status", "do"),
            mediaType=media_type,
            processed_items=processed_items,
            poster_path=value.get("poster_path", ""),
            direct_douban_id=getattr(mediainfo, "douban_id", None) if mediainfo else None,
            year=getattr(mediainfo, "year", None) if mediainfo else value.get("year"),
            season_id=season_id,
            episode_id=value.get("episode_id"),
            episode_count=value.get("episode_count", 0),
            tmdb_id=getattr(mediainfo, "tmdb_id", None) if mediainfo else value.get("tmdb_id"),
            season_name=season_name,
            is_retry=True,
        )

    def _sync_to_douban(
            self,
            title: str,
            status: str,
            mediaType: str,
            processed_items: Dict,
            poster_path: str,
            direct_douban_id: Optional[str] = None,
            year: Optional[int] = None,
            season_id: Optional[int] = None,
            episode_id: Optional[int] = None,
            episode_count: int = 0,
            tmdb_id: Optional[int] = None,
            season_name: str = "",
            is_retry: bool = False,
    ) -> bool:
        self._wait_process = self._wait_process or self.get_data('wait') or {}
        self._failed_process = self._failed_process or self.get_data('failed') or {}
        self._tv_mappings = self._tv_mappings or self.get_data('tv_mappings') or {}
        direct_id = str(direct_douban_id or "").strip()
        waiting = normalize_wait_entry(self._wait_process.get(title)) if title in self._wait_process else None
        if waiting:
            waiting_direct_id = str(waiting.get("douban_id") or "").strip()
            waiting_target_id = waiting_direct_id or str(waiting.get("subject_id") or "").strip()
            if direct_id and waiting_target_id and direct_id != waiting_target_id:
                del self._wait_process[title]
                self.save_data('wait', self._wait_process)
                waiting = None
            elif not retry_is_due(waiting):
                return False
            else:
                prepared = prepare_retry_attempt(waiting)
                if prepared != waiting:
                    waiting = prepared
                    self._wait_process[title] = waiting
                    self.save_data('wait', self._wait_process)
                is_retry = True

        if self._is_failure_suppressed(title, direct_id):
            return False

        logger.info(f"开始尝试解析 {title} 豆瓣条目")
        douban_helper = self._get_douban_helper()
        segment_end = None
        segmented = False
        if direct_id:
            resolve_result = resolve_subject_target(
                direct_douban_id=direct_id,
                title=title,
                candidates=[],
                year=year,
                media_type=mediaType,
                season=season_id,
            )
        else:
            cached = None
            if mediaType == "TV":
                cached = self._cached_tv_segment(
                    tmdb_id=tmdb_id,
                    season_id=season_id,
                    episode_id=episode_id,
                    season_name=season_name,
                    episode_count=episode_count,
                )
            if cached:
                resolve_result = SubjectResolveResult(candidate=cached[0])
                segment_end = cached[1]
                segmented = True
            else:
                resolve_result = douban_helper.resolve_subject(
                    title=title,
                    year=year,
                    media_type=mediaType,
                    season=season_id,
                )
                if should_use_segmented_fallback(mediaType, direct_id, resolve_result.kind):
                    resolve_result, segment_end = self._resolve_segmented_tv(
                        douban_helper=douban_helper,
                        title=title,
                        tmdb_id=tmdb_id,
                        season_id=season_id,
                        episode_id=episode_id,
                        episode_count=episode_count,
                        season_name=season_name,
                    )
                    segmented = resolve_result.candidate is not None

        if not resolve_result.candidate:
            self._handle_sync_failure(
                title=title,
                status=status,
                media_type=mediaType,
                poster_path=poster_path,
                year=year,
                season_id=season_id,
                episode_id=episode_id,
                episode_count=episode_count,
                tmdb_id=tmdb_id,
                season_name=season_name,
                resolve_result=resolve_result,
                is_retry=is_retry,
            )
            return False

        candidate = resolve_result.candidate
        if self._is_failure_suppressed(title, candidate.subject_id):
            return False
        effective_status = status_for_segment(status, episode_id, segment_end) if segmented else status
        processed_key = title
        if segmented:
            existing_key = find_processed_record_key(processed_items, title, candidate.subject_id)
            if existing_key:
                existing_status = str(processed_items[existing_key].get("status") or "")
                if effective_status == "do" or existing_status == "collect":
                    logger.info(f"{candidate.title} 已同步到豆瓣，不重复处理")
                    return False
                processed_key = existing_key
            else:
                processed_key = f"{title}::{candidate.subject_id}"
        logger.info(
            f"查询：{title} => 匹配豆瓣：{candidate.title} "
            f"https://movie.douban.com/subject/{candidate.subject_id}/ 来源：{candidate.source}"
        )
        action_result = douban_helper.set_watching_status_result(
            subject_id=candidate.subject_id,
            status=effective_status,
            private=self._private,
        )
        if not action_result.success:
            self._handle_sync_failure(
                title=title,
                status=effective_status,
                media_type=mediaType,
                poster_path=poster_path,
                year=year,
                season_id=season_id,
                episode_id=episode_id,
                episode_count=episode_count,
                tmdb_id=tmdb_id,
                season_name=season_name,
                candidate=candidate,
                action_result=action_result,
                is_retry=is_retry,
                direct_douban_id=direct_id,
            )
            return False

        self._cookie = douban_helper.get_cookie_string()
        processed_items[processed_key] = {
            "subject_id": candidate.subject_id,
            "subject_name": candidate.title,
            "timestamp": datetime.now().strftime(DATETIME_FORMAT),
            "poster_path": poster_path,
            "type": "电视剧" if mediaType == "TV" else "电影",
            "status": effective_status,
        }
        self._wait_process.pop(title, None)
        self._failed_process.pop(title, None)
        self.save_data('data', processed_items)
        self.save_data('wait', self._wait_process)
        self.save_data('failed', self._failed_process)
        logger.info(f"{title} 同步到档案成功")
        self._send_notification(True, f"《{candidate.title}》已成功同步到豆瓣档案。")
        return True

    def _is_failure_suppressed(self, title: str, current_subject_id: str = "") -> bool:
        failed = self._failed_process.get(title)
        suppressed, should_remove = failure_is_suppressed(failed, current_subject_id)
        if should_remove:
            self._failed_process.pop(title, None)
            self.save_data('failed', self._failed_process)
        return suppressed

    def _handle_sync_failure(
            self,
            title: str,
            status: str,
            media_type: str,
            poster_path: str,
            year: Optional[int],
            season_id: Optional[int],
            episode_id: Optional[int] = None,
            episode_count: int = 0,
            tmdb_id: Optional[int] = None,
            season_name: str = "",
            resolve_result: Optional[SubjectResolveResult] = None,
            candidate: Optional[SubjectCandidate] = None,
            action_result=None,
            is_retry: bool = False,
            direct_douban_id: str = "",
    ):
        failure = action_result or resolve_result
        kind = failure.kind
        message = failure.message or "未知原因"
        subject_id = candidate.subject_id if candidate else ""
        subject_name = candidate.title if candidate else title
        permanent = kind in TERMINAL_FAILURES

        if permanent:
            self._wait_process.pop(title, None)
            self._failed_process[title] = {
                "subject_id": subject_id,
                "kind": kind.value,
                "reason": message,
                "timestamp": datetime.now().strftime(DATETIME_FORMAT),
                "blocked_until": "",
                "matcher_version": MATCHER_VERSION,
            }
            self.save_data('wait', self._wait_process)
            self.save_data('failed', self._failed_process)
            logger.error(f"{title} 同步停止：{message}")
            if kind == FailureKind.NOT_ALLOWED:
                notice = (
                    f"《{title}》匹配到豆瓣条目「{subject_name}」(ID {subject_id})，"
                    "但豆瓣未开播或不允许标记；已停止自动重试，请确认条目、开播状态或豆瓣页面权限。"
                )
            else:
                notice = f"《{title}》{message}；为避免误标，已停止自动重试。"
            self._send_notification(False, notice)
            return

        queue_entry = {
            "subject_id": subject_id,
            "subject_name": subject_name,
            "douban_id": direct_douban_id,
            "status": status,
            "poster_path": poster_path,
            "type": media_type,
            "year": year,
            "season_id": season_id,
            "episode_id": episode_id,
            "episode_count": episode_count,
            "tmdb_id": tmdb_id,
            "season_name": season_name,
            "kind": kind.value,
            "last_error": message,
        }
        existing = normalize_wait_entry(self._wait_process.get(title)) if title in self._wait_process else None
        if existing and is_retry:
            existing.update(queue_entry)
            updated, exhausted = record_retry_failure(existing)
            if exhausted:
                self._wait_process[title] = updated
                self._failed_process[title] = {
                    "subject_id": subject_id,
                    "kind": kind.value,
                    "reason": message,
                    "timestamp": datetime.now().strftime(DATETIME_FORMAT),
                    "blocked_until": updated["next_retry_at"],
                    "matcher_version": MATCHER_VERSION,
                }
                self.save_data('wait', self._wait_process)
                self.save_data('failed', self._failed_process)
                logger.error(f"{title} 自动重试已达到上限")
                self._send_notification(
                    False,
                    f"《{title}》连续 5 次自动重试仍失败：{message}；已暂停重试 24 小时。",
                )
                return
            self._wait_process[title] = updated
            self.save_data('wait', self._wait_process)
            logger.warning(f"{title} 自动重试失败，将在冷却后再次尝试：{message}")
            return

        if not existing:
            self._wait_process[title] = schedule_initial_retry(queue_entry)
            self.save_data('wait', self._wait_process)
            logger.error(f"{title} 因可重试错误加入待同步列表：{message}")
            if kind == FailureKind.AUTH:
                notice = f"《{title}》因豆瓣登录状态无效同步失败，已加入待同步列表；请检查 Cookie/CK 或账号验证状态。"
            elif kind == FailureKind.RESTRICTED:
                notice = (
                    f"《{title}》因豆瓣访问限制同步失败：{message}；"
                    "已加入待同步列表，将在冷却后自动重试。"
                )
            else:
                notice = f"《{title}》因网络或豆瓣服务临时异常同步失败，已加入待同步列表。"
            self._send_notification(False, notice)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'private',
                                            'label': '仅自己可见',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'first',
                                            'label': '不标记第一集',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'user',
                                            'label': '媒体库用户名',
                                            'placeholder': '多个关键词以,分隔',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude',
                                            'label': '媒体路径排除关键词',
                                            'placeholder': '多个关键词以,分隔',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'auto_login',
                                            'label': 'CK失效自动登录',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 9
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cookie',
                                            'label': '豆瓣cookie',
                                            'placeholder': '留空则每次从cookiecloud获取',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'douban_username',
                                            'label': '豆瓣账号',
                                            'placeholder': '仅用于CK失效后自动登录',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'douban_password',
                                            'label': '豆瓣密码',
                                            'type': 'password',
                                            'placeholder': '仅本地保存使用，请勿写入日志或发给他人',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pc_month',
                                            'label': '大屏幕显示月份数',
                                            'placeholder': '默认3个月，最少两个月',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pc_num',
                                            'label': '大屏幕每月最多显示数',
                                            'placeholder': '50',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'mobile_month',
                                            'label': '小屏幕屏幕显示月份数',
                                            'placeholder': '默认2个月，最少两个月',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'mobile_num',
                                            'label': '小屏幕每月最多显示数',
                                            'placeholder': '15',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '需要开启媒体服务器的webhook。可继续使用cookiecloud或手动Cookie；当CK失效时，插件会尝试使用配置的豆瓣账号密码重新登录并刷新CK。若豆瓣触发验证码、短信验证或风控，需要人工登录处理。'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '致谢\n本插件基于 honue 大佬的豆瓣书影音档案项目进行二次开发，特此感谢！'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": False,
            "private": True,
            "first": True,
            "user": '',
            "exclude": '',
            "cookie": "",
            "douban_username": "",
            "douban_password": "",
            "auto_login": True,
            "pc_month": 3,
            "pc_num": 50,
            "mobile_month": 2,
            "mobile_num": 15,
            "notify": False,
        }

    def get_dashboard(self, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        cols = {
            "cols": 12, "md": 12
        }
        mobile = self.is_mobile(kwargs.get('user_agent'))
        attrs = {"refresh": 600, "border": False}
        elements = [
            {
                'component': 'VRow',
                'props': {
                },
                'content': [
                    {
                        'component': 'VTimeline',
                        'props': {
                            'dot-color': '#AF85FD',
                            'direction': "vertical",
                            'style': 'padding: 1rem 1rem 1rem 1rem',
                            'hide-opposite': True,
                            'side': 'end',
                            'align': 'start'
                        },
                        "content": self.get_line_item(mobile=mobile)
                    }
                ]
            }
        ]

        return cols, attrs, elements

    def get_line_item(self, mobile: bool = False):
        """
        processed_items[f"{title}"] = {
                        "subject_id": subject_id,
                        "subject_name": subject_name,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
        """
        data: Dict = self.get_data('data') or {}
        content = []

        # 按月分组
        last_month = None
        current_month_item = None
        # 限制显示月数
        limit_month = self._mobile_month if mobile else self._pc_month
        limit_month -= 1
        # 限制每月最多显示数
        limit_num = self._mobile_num if mobile else self._pc_num

        # 将字典按照 timestamp 排序
        sorted_data = sorted(data.items(),
                             key=lambda item: datetime.strptime(item[1]['timestamp'], "%Y-%m-%d %H:%M:%S"))

        for key, val in sorted_data[::-1]:
            if not isinstance(val, dict):
                continue
            if not val.get('poster_path', ''):
                meta = MetaInfo(val.get("subject_name"))
                meta.type = MediaType("电视剧" if not val.get("type", '') else val.get("type"))
                # 识别媒体信息
                mediainfo: MediaInfo = MediaChain().recognize_media(meta=meta, mtype=meta.type,
                                                                    cache=True)
                if mediainfo:
                    poster_path = mediainfo.poster_path
                else:
                    continue
            else:
                poster_path = val.get('poster_path')

            time_object = datetime.strptime(val.get('timestamp'), "%Y-%m-%d %H:%M:%S")

            if time_object.month != last_month or last_month is None:
                if limit_month < 1:
                    break
                if last_month:
                    num_movies = len(current_month_item["content"][0]["content"][1]["content"])
                    current_month_item["content"][0]["content"][0][
                        "html"] += f"<span class='text-sm font-normal'>看过{num_movies}部</span>"
                    # 截取limit_num
                    current_month_item["content"][0]["content"][1]["content"] = \
                        current_month_item["content"][0]["content"][1]["content"][:limit_num]
                    content.append(current_month_item)
                    limit_month -= 1

                # 新的一月
                # 初始化 current_month_item 模板
                current_month_item = {
                    "component": "VTimelineItem",
                    "props": {
                        "size": "x-small",
                    },
                    "content": [
                        {
                            "component": "VCol",
                            'props': {
                                'style': 'padding: 0rem 0rem 0rem 0rem'
                            },
                            'content': [
                                {
                                    'component': 'h1',
                                    'props': {
                                        'style': 'padding:0rem 0rem 1rem 0rem;font-weight: bold;',
                                        'class': 'text-base'
                                    },
                                    'html': f"{time_object.month}月 ",
                                },
                                {
                                    'component': 'VRow',
                                    'props': {
                                        'style': 'padding: 0rem 0rem 0rem 0rem'
                                    },
                                    'content': []
                                }
                            ]
                        }
                    ]
                }
                last_month = time_object.month
            if not poster_path or (poster_path.count('original') < 1):
                continue
            current_month_item["content"][0]["content"][1]["content"].append({
                "component": "a",
                'props': {
                    'href': 'https://www.douban.com/doubanapp/dispatch?uri=/movie/' + val.get(
                        'subject_id') + '?from=mdouban&open=app',
                    'target': '_blank',
                    # 图片卡片间的间距 上 右 下 左
                    # 'style': 'padding: 1rem 0.5rem 1rem 0.5rem'
                    'style': 'padding: 0.2rem'
                },
                "content": [
                    {
                        "component": "VCard",
                        "props": {
                            "class": "elevation-4"
                        },
                        "content": [
                            {
                                "component": "VImg",
                                "props": {
                                    "src": poster_path.replace("/original/", "/w200/"),
                                    "style": "width:44px; height: 66px;" if mobile else "width:66px; height: 99px;",
                                    "aspect-ratio": "2/3"
                                }
                            }
                        ]
                    }
                ]
            })

        if current_month_item:
            num_movies = len(current_month_item["content"][0]["content"][1]["content"])
            current_month_item["content"][0]["content"][0][
                "html"] += f"<span class='text-sm font-normal'>看过{num_movies}部</span>"
            current_month_item["content"][0]["content"][1]["content"] = \
                current_month_item["content"][0]["content"][1]["content"][:limit_num]
            content.append(current_month_item)
        return content

    @staticmethod
    def is_mobile(user_agent):
        mobile_keywords = [
            'Mobile', 'Android', 'Silk/', 'Kindle', 'BlackBerry', 'Opera Mini', 'Opera Mobi', 'iPhone', 'iPad'
        ]
        for keyword in mobile_keywords:
            if re.search(keyword, user_agent, re.IGNORECASE):
                return True
        return False

    def get_page(self) -> List[dict]:
        pass

    def get_state(self) -> bool:
        return self._enable

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enable:
            return []
        return [{
            "id": "DoubanMediaFolioRetry",
            "name": "豆瓣影音档案待同步重试",
            "trigger": "interval",
            "func": self.retry_waiting_items,
            "kwargs": {},
            "seconds": 600,
        }]

    def stop_service(self):
        pass

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    @staticmethod
    def exclude_keyword(path: str, keywords: str) -> Dict[str, Any]:
        if not keywords:
            return {"ret": True, "message": "空关键词"}

        if not path:
            logger.warn('媒体路径为空,不执行过滤操作')
            return {"ret": True, "message": "媒体路径为空,不执行过滤操作"}

        keywords_list = re.split(r'[，,]', keywords)
        if any(k in path for k in keywords_list):
            return {"ret": False, "message": f"路径 {path} 包含 {keywords}"}

        return {"ret": True, "message": f"路径 {path} 不包含任何关键词 {keywords}"}

    @staticmethod
    def format_title(title: str, season_id: int) -> str:
        if season_id > 1:
            return f"{title} 第{season_id}季"
        else:
            return title
