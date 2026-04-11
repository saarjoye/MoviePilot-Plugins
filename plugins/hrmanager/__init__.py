import time
from typing import Any, List, Dict, Tuple, Optional
from datetime import datetime, timedelta

from app import schemas
from app.core.config import settings
from app.plugins import _PluginBase
from app.log import logger
from app.schemas import NotificationType
from app.core.event import eventmanager, Event
from app.schemas.types import EventType, TorrentStatus
from app.helper.downloader import DownloaderHelper


class HRManager(_PluginBase):
    # 插件名称
    plugin_name = "HR管理-魔改版"
    # 插件描述
    plugin_desc = "自动管理下载种子的HR标签，监控种子的做种时间和分享率，满足条件后自动更改标签并通知用户"
    # 插件图标
    plugin_icon = "seed.png"
    # 插件版本
    plugin_version = "2.0"
    # 插件作者
    plugin_author = "污妖王"
    # 插件配置项ID前缀
    plugin_config_prefix = "hrmanager_"
    # 加载顺序
    plugin_order = 20
    # 可使用的用户级别
    auth_level = 1

    # 告警级别常量
    ALERT_NORMAL = "normal"      # 正常
    ALERT_WARNING = "warning"    # 警告
    ALERT_URGENT = "urgent"      # 紧急
    ALERT_TIMEOUT = "timeout"    # 超期

    # 私有属性
    _enabled = False
    # HR标签
    _hr_tag = "HR"
    # 出种标签
    _finished_tag = "已完成"
    # 检查间隔（秒）
    _check_interval = 3600
    # 站点HR标准配置
    _sites_config = []
    # 监控的下载器列表
    _monitor_downloaders = []
    # 下载器帮助类
    _downloaderhelper = None
    # 定时器
    _scheduler = None
    # 用于去重的种子哈希缓存 (哈希: 处理时间戳)
    _processed_torrents = {}

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        # 移除SitesHelper的初始化，使用SiteOper代替

        if config:
            self._enabled = bool(config.get("enabled"))
            self._hr_tag = str(config.get("hr_tag", "HR") or "HR").strip() or "HR"
            self._finished_tag = str(config.get("finished_tag", "已完成") or "已完成").strip() or "已完成"
            raw_check_interval = config.get("check_interval", 3600)
            try:
                if isinstance(raw_check_interval, str):
                    raw_check_interval = raw_check_interval.strip()
                check_interval = int(float(raw_check_interval))
                if check_interval <= 0:
                    raise ValueError("check_interval must be > 0")
                self._check_interval = check_interval
            except (TypeError, ValueError):
                self._check_interval = 3600
                logger.warning(
                    f"check_interval 配置无效：{raw_check_interval}，已回退默认值 {self._check_interval} 秒"
                )
            monitor_downloaders = config.get("monitor_downloaders", [])
            if isinstance(monitor_downloaders, list):
                self._monitor_downloaders = [str(item).strip() for item in monitor_downloaders if str(item).strip()]
            else:
                self._monitor_downloaders = []
            
            # 处理站点HR配置
            self._sites_config = []
            
            # 优先处理YAML配置
            site_config_str = config.get("site_config_str", "")
            if site_config_str:
                try:
                    import yaml
                    yaml_config = yaml.safe_load(site_config_str)
                    if yaml_config and isinstance(yaml_config, list):
                        for site_config in yaml_config:
                            if isinstance(site_config, dict) and site_config.get("site_name"):
                                # 将hr_duration转换为time（保持向后兼容性）
                                site_config["time"] = site_config.get("hr_duration", site_config.get("time", 0.0))
                                self._sites_config.append(site_config)
                    logger.info(f"解析YAML配置成功，共 {len(self._sites_config)} 个站点")
                except Exception as e:
                    logger.error(f"解析YAML配置失败: {e}")
                    # YAML解析失败时，尝试使用旧格式
                    self._sites_config = []
            
            # 如果YAML配置解析失败或为空，尝试使用旧格式
            if not self._sites_config:
                # 处理旧格式的sites_config（兼容性支持）
                old_sites_config = config.get("sites_config", [])
                if old_sites_config:
                    self._sites_config = old_sites_config
                else:
                    # 处理最旧格式的站点配置（site_1_name, site_1_time等）
                    for i in range(1, 4):  # 支持3个站点配置
                        site_name = config.get(f"site_{i}_name", "")
                        if not site_name:
                            continue
                        
                        site_config = {
                            "site_name": site_name,
                            "time": config.get(f"site_{i}_time", 0.0),
                            "hr_ratio": config.get(f"site_{i}_ratio", 0.0),
                            "hr_active": config.get(f"site_{i}_active", False),
                            "hr_deadline_days": config.get(f"site_{i}_deadline", 0)
                        }
                        self._sites_config.append(site_config)

            self._sites_config = self._validate_and_normalize_sites_config(self._sites_config)

        # 初始化下载器帮助类
        self._downloaderhelper = DownloaderHelper()

        # 启动定时任务
        if self._enabled:
            self._start_scheduler()

    def _start_scheduler(self):
        """
        启动定时任务
        """
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        logger.info(f"HR管理服务启动，检查间隔：{self._check_interval}秒")
        logger.info(f"监控的下载器：{self._monitor_downloaders if self._monitor_downloaders else '所有下载器'}")
        logger.info(f"HR标签：{self._hr_tag}，出种标签：{self._finished_tag}")
        logger.info(f"站点HR配置：{self._sites_config}")
        self._scheduler.add_job(func=self.check_hr_seeds,
                               trigger=IntervalTrigger(seconds=self._check_interval),
                               name="检查HR种子")
        self._scheduler.start()

    def _get_site_from_tracker(self, torrent_info):
        """
        从种子的tracker信息中解析站点
        """
        try:
            from urllib.parse import parse_qs, urlparse, unquote
            from app.utils.string import StringUtils
            
            trackers = []
            
            # 尝试从种子信息中获取tracker
            if isinstance(torrent_info, dict):
                # 如果是字典类型（从下载器获取的种子信息）
                tracker_url = torrent_info.get('tracker')
                if tracker_url:
                    trackers.append(tracker_url)
                
                magnet_link = torrent_info.get('magnet_uri')
                if magnet_link:
                    query_params = parse_qs(urlparse(magnet_link).query)
                    encoded_tracker_urls = query_params.get('tr', [])
                    decoded_tracker_urls = [unquote(url) for url in encoded_tracker_urls]
                    trackers.extend(decoded_tracker_urls)
            
            if not trackers:
                logger.debug("未从种子中提取到任何tracker信息")
                return None
            
            logger.debug(f"从种子中提取到的trackers：{trackers}")
            
            # 特定tracker到域名的映射（仅作为后备）
            tracker_mappings = {
                "chdbits.xyz": "ptchdbits.co",
                "agsvpt.trackers.work": "agsvpt.com",
                "tracker.cinefiles.info": "audiences.me",
            }
            
            # 尝试从tracker解析站点
            for tracker in trackers:
                if not tracker:
                    continue
                
                domain = None
                
                # 检查tracker是否包含特定的关键字，并进行相应的映射
                for key, mapped_domain in tracker_mappings.items():
                    if key in tracker:
                        domain = mapped_domain
                        break
                else:
                    # 使用StringUtils工具类获取tracker的域名
                    domain = StringUtils.get_url_domain(tracker)
                
                if not domain:
                    continue
                
                logger.debug(f"从tracker {tracker} 提取到域名：{domain}")
                
                # 尝试匹配配置的站点
                
                for site_config in self._sites_config:
                    site_name = site_config.get('site_name')
                    if site_name and domain.lower() in site_name.lower():
                        logger.debug(f"从tracker域名 {domain} 匹配到配置的站点：{site_name}")
                        return site_name
                        
            # 如果所有tracker都没有匹配到站点，返回第一个tracker的域名
            domain = StringUtils.get_url_domain(trackers[0])
            if domain:
                logger.debug(f"所有tracker都未匹配到已知站点，返回第一个tracker的域名：{domain}")
                return domain
        except Exception as e:
            logger.error(f"从tracker解析站点失败: {e}")
        return None
    
    @eventmanager.register(EventType.DownloadAdded)
    def on_download_added(self, event: Event):
        """
        处理下载添加事件
        """
        logger.info("收到下载添加事件")
        
        if not self._enabled:
            logger.info("插件未启用，忽略下载添加事件")
            return

        try:
            # 从事件数据中获取信息（参考hitandrun插件实现）
            torrent_hash = event.event_data.get("hash")
            context = event.event_data.get("context")
            downloader_name = event.event_data.get("downloader")
            
            # 检查种子是否在短时间内已经处理过（去重逻辑）
            if torrent_hash:
                current_time = time.time()
                last_process_time = self._processed_torrents.get(torrent_hash, 0)
                
                # 如果种子在30秒内已经处理过，跳过本次处理
                if current_time - last_process_time < 30:
                    logger.debug(f"种子 {torrent_hash} 在30秒内已经处理过，跳过本次处理")
                    return
                
                # 更新种子的处理时间戳
                self._processed_torrents[torrent_hash] = current_time
                
                # 清理过期的处理记录（超过5分钟的记录）
                expired_torrents = [hash for hash, timestamp in self._processed_torrents.items() 
                                  if current_time - timestamp > 300]
                for expired_hash in expired_torrents:
                    del self._processed_torrents[expired_hash]
            
            logger.debug(f"从事件中获取的原始数据：hash={torrent_hash}, downloader={downloader_name}, context={context}")
            
            # 首先尝试使用参考插件的方式处理
            if downloader_name and torrent_hash and context and hasattr(context, "torrent_info"):
                logger.info("使用参考插件的方式处理下载事件")
                
                # 检查下载器是否在监控列表中
                if self._monitor_downloaders and downloader_name not in self._monitor_downloaders:
                    logger.info(f"下载器 {downloader_name} 不在监控列表中，忽略种子处理")
                    return
                
                # 获取下载器实例
                logger.debug(f"尝试获取下载器实例：{downloader_name}")
                downloader_service = self._downloaderhelper.get_service(name=downloader_name)
                if not downloader_service:
                    logger.error(f"无法获取下载器服务：{downloader_name}")
                    return
                if not downloader_service.instance:
                    logger.error(f"无法获取下载器实例：{downloader_name}")
                    return
                
                downloader = downloader_service.instance
                logger.debug(f"成功获取下载器实例：{downloader_name}")
                
                # 获取种子信息
                torrent_info = context.torrent_info
                
                # 从torrent_info中获取种子名称
                torrent_name = None
                if hasattr(torrent_info, "title"):
                    torrent_name = torrent_info.title
                elif hasattr(torrent_info, "name"):
                    torrent_name = torrent_info.name
                
                # 如果没有获取到种子名称，使用哈希值作为临时名称
                if not torrent_name:
                    torrent_name = torrent_hash
                    logger.warning(f"使用种子哈希值作为临时名称：{torrent_name}")
                
                logger.info(f"处理新种子：{torrent_name} (哈希: {torrent_hash})，来自下载器：{downloader_name}")
                
                # 从torrent_info中获取站点名称
                site_name = None
                if hasattr(torrent_info, "site_name"):
                    site_name = torrent_info.site_name
                    logger.debug(f"从torrent_info中获取站点名称：{site_name}")
                
                # 如果没有从torrent_info中获取到站点名称，尝试其他方法
                if not site_name:
                    # 从种子名称中解析站点
                    site_name = self._extract_site_name(torrent_name)
                    
                    # 如果仍然没有站点名称，尝试从tracker中解析
                    if not site_name:
                        logger.debug(f"尝试从tracker解析种子 {torrent_name} 的站点信息")
                        torrents, error = downloader.get_torrents()
                        if not error and torrents:
                            for torrent in torrents:
                                if torrent.get("hash") == torrent_hash:
                                    site_name = self._get_site_from_tracker(torrent)
                                    break
                
                if not site_name:
                    logger.warning(f"无法解析种子所属站点：{torrent_name}")
                    logger.debug(f"当前配置的站点：{[site.get('site_name') for site in self._sites_config]}")
                    return
                
                logger.info(f"种子 {torrent_name} 所属站点：{site_name}")
                
                # 获取站点HR配置
                logger.debug(f"尝试获取站点 {site_name} 的HR配置")
                site_config = self._get_site_config(site_name)
                if not site_config:
                    logger.warning(f"未找到站点HR配置：{site_name}")
                    logger.debug(f"当前站点HR配置：{self._sites_config}")
                    return
                logger.info(f"站点 {site_name} 的HR配置：{site_config}")
                
                # 从torrent_info中获取HR状态
                is_hr_seed = False
                if hasattr(torrent_info, "hit_and_run"):
                    is_hr_seed = torrent_info.hit_and_run
                    logger.info(f"✓ 从torrent_info中获取到HR状态：{is_hr_seed}")
                
                # 如果没有从torrent_info中获取到HR状态，尝试其他方法
                if not is_hr_seed:
                    # 尝试从数据库查询
                    logger.debug(f"尝试从数据库查询种子 {torrent_name} 的HR信息")
                    db_hr_info = self._get_hr_info_from_db(torrent_hash, torrent_name)
                    is_hr_seed = db_hr_info.get("is_hr", False)
                
                # 如果仍然没有HR信息，使用常规检测方法
                if not is_hr_seed:
                    is_hr_seed = self._is_hr_seed(torrent_name, site_config)
                
                if is_hr_seed:
                    # 设置HR标签
                    logger.info(f"✓ 识别到HR种子：{torrent_name}")
                    logger.info(f"正在为种子 {torrent_hash} - {torrent_name} 设置HR标签：{self._hr_tag}")
                    
                    try:
                        # 先获取种子的所有当前标签
                        logger.debug(f"获取种子 {torrent_hash} 的所有当前标签")
                        torrents, error = downloader.get_torrents(ids=torrent_hash)
                        if not error and torrents and len(torrents) > 0:
                            current_tags_str = torrents[0].get("tags", "")
                            # 处理不同的标签分隔符情况
                            if isinstance(current_tags_str, str):
                                # 尝试不同的分隔符
                                if "," in current_tags_str:
                                    current_tags = [str(tag).strip() for tag in current_tags_str.split(',') if tag.strip()]
                                elif "|" in current_tags_str:
                                    current_tags = [str(tag).strip() for tag in current_tags_str.split('|') if tag.strip()]
                                else:
                                    current_tags = [current_tags_str.strip()] if current_tags_str.strip() else []
                            elif isinstance(current_tags_str, list):
                                current_tags = [str(tag).strip() for tag in current_tags_str if tag.strip()]
                            else:
                                current_tags = []
                                
                            logger.debug(f"种子 {torrent_hash} 当前的标签：{current_tags}")
                            
                            # 移除所有现有标签
                            if current_tags:
                                logger.debug(f"移除种子 {torrent_hash} 的所有标签：{current_tags}")
                                
                                # 逐个移除标签，确保每个标签都被正确移除
                                for tag in current_tags:
                                    if tag:
                                        downloader.remove_torrents_tag(ids=torrent_hash, tag=[tag])
                                        logger.debug(f"成功移除标签：{tag}")
                                
                                # 等待一下，确保标签移除操作完成
                                time.sleep(0.5)
                    
                        # 然后设置HR标签
                        logger.debug(f"为种子 {torrent_hash} 设置HR标签：{self._hr_tag}")
                        downloader.set_torrents_tag(ids=torrent_hash, tags=[self._hr_tag])
                        
                        # 验证标签是否设置成功
                        time.sleep(0.5)
                        torrents, error = downloader.get_torrents(ids=torrent_hash)
                        if not error and torrents and len(torrents) > 0:
                            new_tags_str = torrents[0].get("tags", "")
                            new_tags = [str(tag).strip() for tag in new_tags_str.split(',') if tag.strip()]
                            logger.debug(f"种子 {torrent_hash} 设置标签后的标签：{new_tags}")
                            
                        logger.info(f"成功为种子 {torrent_hash} 设置HR标签：{self._hr_tag}")
                    except Exception as e:
                        logger.error(f"设置HR标签失败：{str(e)}")
                        raise
                
                else:
                    logger.info(f"✗ 种子 {torrent_name} 不是HR种子")
                    
                # 发送通知
                if is_hr_seed:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="【HR管理】新HR种子添加",
                        text=f"种子 {torrent_name} 已添加到下载器并标记为HR种子\n"\
                             f"站点：{site_name}\n"\
                             f"需要满足：做种时间 ≥ {site_config.get('time', 0)}小时，分享率 ≥ {site_config.get('hr_ratio', 0)}"
                    )
                    logger.info(f"发送HR种子添加通知：{torrent_name}")
                
                return
            
            # 兼容旧的处理方式，保持向后兼容性
            logger.info("使用兼容模式处理下载事件")
            
            # 获取下载信息
            download_info = event.event_data
            if not download_info:
                logger.error("下载事件数据为空")
                return
            
            # 打印完整的下载事件数据，用于调试
            logger.debug(f"下载事件数据：{download_info}")

            # 处理不同格式的事件数据
            if isinstance(download_info, dict):
                # 处理嵌套的message对象（根据用户提供的通知格式）
                if 'message' in download_info:
                    message_obj = download_info['message']
                    
                    # 尝试从message对象中获取文本内容
                    notification_text = None
                    
                    # 如果message_obj是对象类型，尝试获取其属性
                    if hasattr(message_obj, 'text'):
                        notification_text = message_obj.text
                    # 否则，尝试将message_obj转换为字符串
                    elif isinstance(message_obj, str):
                        notification_text = message_obj
                    # 否则，尝试从__str__或__repr__方法获取字符串表示
                    else:
                        try:
                            notification_text = str(message_obj)
                        except Exception as e:
                            logger.error(f"无法获取message对象的文本内容: {e}")
                    
                    if notification_text:
                        logger.debug(f"通知文本：{notification_text}")
                        
                        # 从通知文本中提取信息
                        download_info['notification_text'] = notification_text
                        
                        # 提取种子名称
                        import re
                        torrent_match = re.search(r'种子：(.*?)\n', notification_text)
                        if torrent_match:
                            download_info['name'] = torrent_match.group(1)
                            logger.debug(f"从通知文本中提取种子名称：{download_info['name']}")
                        
                        # 提取站点信息
                        site_match = re.search(r'站点：(.*?)\n', notification_text)
                        if site_match:
                            download_info['site_name'] = site_match.group(1)
                            logger.debug(f"从通知文本中提取站点：{download_info['site_name']}")
                        
                        # 提取HR信息 - 使用更灵活的正则表达式
                        hr_match = re.search(r'Hit&Run\s*[:：]\s*(是|Yes)', notification_text, re.IGNORECASE)
                        if hr_match:
                            download_info['is_hr'] = True
                            logger.debug("从通知文本中检测到Hit&Run：是")
                            logger.info(f"✓ 从通知文本中确认种子 {download_info.get('name', '未知')} 是HR种子")
                
                # 尝试从下载器名称或其他字段获取站点信息
                if 'downloader' in download_info:
                    downloader_name = download_info['downloader']
                    logger.debug(f"下载器名称：{downloader_name}")

            # 检查是否已经在参考插件方式中处理过
            if torrent_hash and context and hasattr(context, "torrent_info"):
                logger.debug(f"种子 {torrent_hash} 已经在参考插件方式中处理过，跳过兼容模式处理")
                return
            
            # 获取种子信息
            downloader_name = download_info.get("downloader")
            torrent_hash = download_info.get("hash")
            
            # 尝试从不同字段获取种子名称
            torrent_name = download_info.get("name") or download_info.get("title") or download_info.get("filename")

            if not downloader_name:
                logger.error("无法获取下载器名称")
                return
            if not torrent_hash:
                logger.error("无法获取种子哈希值")
                return
            
            # 如果没有种子名称，尝试从下载器中获取
            if not torrent_name:
                logger.warning(f"无法从事件数据中获取种子名称，尝试从下载器中查询 (哈希: {torrent_hash})")
                
                # 获取下载器实例
                downloader_service = self._downloaderhelper.get_service(name=downloader_name)
                if downloader_service and downloader_service.instance:
                    try:
                        # 从下载器中获取种子信息
                        torrents, error = downloader_service.instance.get_torrents()
                        if not error and torrents:
                            for torrent in torrents:
                                if torrent.get("hash") == torrent_hash:
                                    torrent_name = torrent.get("name") or torrent.get("title")
                                    break
                    except Exception as e:
                        logger.error(f"从下载器查询种子名称失败：{str(e)}")
            
            # 如果仍然没有种子名称，使用哈希值作为临时名称
            if not torrent_name:
                torrent_name = torrent_hash
                logger.warning(f"使用种子哈希值作为临时名称：{torrent_name}")
            
            logger.info(f"处理新种子：{torrent_name} (哈希: {torrent_hash})，来自下载器：{downloader_name}")

            # 检查下载器是否在监控列表中
            if self._monitor_downloaders and downloader_name not in self._monitor_downloaders:
                logger.info(f"下载器 {downloader_name} 不在监控列表中，忽略种子：{torrent_name}")
                return

            # 获取下载器实例
            logger.debug(f"尝试获取下载器实例：{downloader_name}")
            downloader_service = self._downloaderhelper.get_service(name=downloader_name)
            if not downloader_service:
                logger.error(f"无法获取下载器服务：{downloader_name}")
                return
            if not downloader_service.instance:
                logger.error(f"无法获取下载器实例：{downloader_name}")
                return

            downloader = downloader_service.instance
            logger.debug(f"成功获取下载器实例：{downloader_name}")

            # 解析站点信息
            logger.debug(f"尝试解析种子 {torrent_name} 的站点信息")
            
            # 优先使用从通知文本中提取的站点名称
            site_name = download_info.get("site_name")
            
            # 如果没有从通知中提取到站点名称，尝试从种子名称中解析
            if not site_name:
                site_name = self._extract_site_name(torrent_name)
                
            # 如果仍然没有站点名称，尝试从tracker中解析
            if not site_name:
                logger.debug(f"尝试从tracker解析种子 {torrent_name} 的站点信息")
                # 从下载器获取种子信息，尝试解析tracker
                torrents, error = downloader.get_torrents()
                if not error and torrents:
                    for torrent in torrents:
                        if torrent.get("hash") == torrent_hash:
                            site_name = self._get_site_from_tracker(torrent)
                            break
            
            if not site_name:
                logger.warning(f"无法解析种子所属站点：{torrent_name}")
                logger.debug(f"当前配置的站点：{[site.get('site_name') for site in self._sites_config]}")
                return
            
            logger.info(f"种子 {torrent_name} 所属站点：{site_name}")

            # 获取站点HR配置
            logger.debug(f"尝试获取站点 {site_name} 的HR配置")
            site_config = self._get_site_config(site_name)
            if not site_config:
                logger.warning(f"未找到站点HR配置：{site_name}")
                logger.debug(f"当前站点HR配置：{self._sites_config}")
                return
            logger.info(f"站点 {site_name} 的HR配置：{site_config}")

            # 检查是否为HR种子
            logger.debug(f"检查种子 {torrent_name} 是否为HR种子")
            
            # 优先使用从通知文本中提取的HR信息
            is_hr_seed = download_info.get("is_hr", False)
            
            # 如果没有从通知中提取到HR信息，尝试从数据库查询
            if not is_hr_seed:
                logger.debug(f"尝试从数据库查询种子 {torrent_name} 的HR信息")
                db_hr_info = self._get_hr_info_from_db(torrent_hash, torrent_name)
                is_hr_seed = db_hr_info.get("is_hr", False)
            
            # 如果仍然没有HR信息，使用常规检测方法
            if not is_hr_seed:
                is_hr_seed = self._is_hr_seed(torrent_name, site_config)
            
            if is_hr_seed:
                # 设置HR标签
                logger.info(f"✓ 识别到HR种子：{torrent_name}")
                logger.info(f"正在为种子 {torrent_hash} - {torrent_name} 设置HR标签：{self._hr_tag}")
                
                try:
                    # 先获取种子的所有当前标签
                    logger.debug(f"获取种子 {torrent_hash} 的所有当前标签")
                    torrents, error = downloader.get_torrents(ids=torrent_hash)
                    if not error and torrents and len(torrents) > 0:
                        current_tags_str = torrents[0].get("tags", "")
                        # 处理不同的标签分隔符情况
                        if isinstance(current_tags_str, str):
                            # 尝试不同的分隔符
                            if "," in current_tags_str:
                                current_tags = [str(tag).strip() for tag in current_tags_str.split(',') if tag.strip()]
                            elif "|" in current_tags_str:
                                current_tags = [str(tag).strip() for tag in current_tags_str.split('|') if tag.strip()]
                            else:
                                current_tags = [current_tags_str.strip()] if current_tags_str.strip() else []
                        elif isinstance(current_tags_str, list):
                            current_tags = [str(tag).strip() for tag in current_tags_str if tag.strip()]
                        else:
                            current_tags = []
                            
                        logger.debug(f"种子 {torrent_hash} 当前的标签：{current_tags}")
                        
                        # 移除所有现有标签
                        if current_tags:
                            logger.debug(f"移除种子 {torrent_hash} 的所有标签：{current_tags}")
                            
                            # 逐个移除标签，确保每个标签都被正确移除
                            for tag in current_tags:
                                if tag:
                                    downloader.remove_torrents_tag(ids=torrent_hash, tag=[tag])
                                    logger.debug(f"成功移除标签：{tag}")
                            
                            # 等待一下，确保标签移除操作完成
                            time.sleep(0.5)
                    
                    # 然后设置HR标签
                    logger.debug(f"为种子 {torrent_hash} 设置HR标签：{self._hr_tag}")
                    downloader.set_torrents_tag(ids=torrent_hash, tags=[self._hr_tag])
                    
                    # 验证标签是否设置成功
                    time.sleep(0.5)
                    torrents, error = downloader.get_torrents(ids=torrent_hash)
                    if not error and torrents and len(torrents) > 0:
                        new_tags_str = torrents[0].get("tags", "")
                        new_tags = [str(tag).strip() for tag in new_tags_str.split(',') if tag.strip()]
                        logger.debug(f"种子 {torrent_hash} 设置标签后的标签：{new_tags}")
                        
                    logger.info(f"成功为种子 {torrent_hash} 设置HR标签：{self._hr_tag}")
                except Exception as e:
                    logger.error(f"设置HR标签失败：{str(e)}")
                    raise

                # 发送通知
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="【HR管理】新HR种子添加",
                    text=f"种子 {torrent_name} 已添加到下载器并标记为HR种子\n"
                         f"站点：{site_name}\n"
                         f"需要满足：做种时间 ≥ {site_config.get('time', 0)}小时，分享率 ≥ {site_config.get('hr_ratio', 0)}"
                )
                logger.info(f"发送HR种子添加通知：{torrent_name}")
            else:
                logger.info(f"✗ 种子 {torrent_name} 不是HR种子")

        except Exception as e:
            logger.error(f"处理下载添加事件出错：{str(e)}", exc_info=True)

    def check_hr_seeds(self):
        """
        定期检查HR种子
        """
        logger.info("=== 开始定期检查HR种子 ===")
        
        if not self._enabled:
            logger.warning("插件未启用，跳过HR种子检查")
            logger.info("=== HR种子检查结束 ===")
            return

        try:
            # 获取所有下载器
            logger.info("尝试获取所有下载器配置...")
            downloaders = self._downloaderhelper.get_configs()
            logger.info(f"✓ 成功获取 {len(downloaders)} 个下载器配置：{list(downloaders.keys())}")
            
            # 根据监控下载器列表过滤下载器
            filtered_downloaders = {}
            if self._monitor_downloaders:
                logger.info("根据监控下载器列表过滤下载器...")
                for downloader_name in self._monitor_downloaders:
                    if downloader_name in downloaders:
                        filtered_downloaders[downloader_name] = downloaders[downloader_name]
                        logger.info(f"✓ 下载器 {downloader_name} 在配置中，添加到监控列表")
                    else:
                        logger.warning(f"✗ 下载器 {downloader_name} 不在配置中，跳过")
                logger.info(f"✓ 共监控 {len(filtered_downloaders)} 个下载器：{list(filtered_downloaders.keys())}")
            else:
                # 监控所有下载器
                filtered_downloaders = downloaders
                logger.info(f"✓ 未设置监控下载器列表，将监控所有 {len(filtered_downloaders)} 个下载器")
            
            # 遍历过滤后的下载器
            for downloader_name, config in filtered_downloaders.items():
                logger.info(f"\n=== 处理下载器：{downloader_name} ===")
                
                # 获取下载器实例
                logger.info(f"尝试获取下载器实例：{downloader_name}...")
                downloader_service = self._downloaderhelper.get_service(name=downloader_name)
                if not downloader_service:
                    logger.error(f"✗ 无法获取下载器服务：{downloader_name}")
                    continue
                if not downloader_service.instance:
                    logger.error(f"✗ 无法获取下载器实例：{downloader_name}")
                    continue

                downloader = downloader_service.instance
                logger.info(f"✓ 成功获取下载器实例：{downloader_name}")

                # 获取所有种子
                logger.info(f"尝试获取下载器 {downloader_name} 的所有种子...")
                torrents, error = downloader.get_torrents()
                if error:
                    logger.error(f"✗ 获取下载器 {downloader_name} 种子列表失败：{error}")
                    continue

                if not torrents:
                    logger.info(f"✓ 下载器 {downloader_name} 中没有种子")
                    continue
                logger.info(f"✓ 成功获取下载器 {downloader_name} 中的 {len(torrents)} 个种子")
                logger.debug(f"获取到的种子列表：{[t.get('name') for t in torrents]}")
                # 打印第一个种子的完整信息，用于调试
                if torrents:
                    logger.debug(f"第一个种子的完整信息：{torrents[0]}")
                    # 特别打印时间相关的字段
                    logger.debug(f"种子时间相关字段：")
                    for field in ['added_time', 'created_at', 'start_time', 'time_added', 'date_added', 'addedOn', 'add_time', 'added', 'added_on']:
                        logger.debug(f"  {field}: {torrents[0].get(field)}")

                # 过滤出HR种子：自动识别 + 标签匹配
                logger.info(f"开始识别HR种子，当前HR标签：{self._hr_tag}...")
                hr_torrents = []
                for torrent in torrents:
                    torrent_name = torrent.get("name", "")
                    tags = []
                    tags_str = torrent.get("tags", "")
                    
                    if isinstance(tags_str, str):
                        # 处理各种可能的标签分隔符
                        separators = [',', '|', ';']
                        found_separator = None
                        for sep in separators:
                            if sep in tags_str:
                                found_separator = sep
                                break
                        
                        if found_separator:
                            tags = [str(tag).strip() for tag in tags_str.split(found_separator) if tag.strip()]
                        else:
                            tags = [tags_str.strip()] if tags_str.strip() else []
                    elif isinstance(tags_str, list):
                        tags = [str(tag).strip() for tag in tags_str if tag.strip()]
                    
                    logger.debug(f"种子 {torrent_name} 的标签：{tags}")
                    
                    # 检查是否为HR种子
                    is_hr = False
                    
                    # 检查标签
                    if self._hr_tag in tags:
                        is_hr = True
                        logger.info(f"✓ 种子 {torrent_name} 带有HR标签 '{self._hr_tag}'，标记为HR种子")
                    else:
                        # 尝试自动识别
                        logger.debug(f"尝试自动识别种子 {torrent_name} 是否为HR种子")
                        # 解析站点信息
                        site_name = self._extract_site_name(torrent_name)
                        if site_name:
                            logger.debug(f"✓ 从种子名称提取到站点：{site_name}")
                            # 获取站点HR配置
                            site_config = self._get_site_config(site_name)
                            if site_config:
                                logger.debug(f"✓ 获取到站点 {site_name} 的HR配置：{site_config}")
                                # 使用_is_hr_seed方法判断是否为HR种子
                                is_hr = self._is_hr_seed(torrent_name, site_config)
                                if is_hr:
                                    logger.info(f"✓ 种子 {torrent_name} 通过自动识别标记为HR种子")
                            else:
                                logger.debug(f"✗ 未找到站点 {site_name} 的HR配置，跳过自动识别")
                        else:
                            logger.debug(f"✗ 无法从种子名称提取站点信息，跳过自动识别")
                    
                    if is_hr:
                        hr_torrents.append(torrent)
                        logger.info(f"✓ 种子 {torrent_name} 添加到HR种子列表")
                    else:
                        logger.debug(f"✗ 种子 {torrent_name} 不是HR种子")

                logger.info(f"下载器 {downloader_name} 中找到 {len(hr_torrents)} 个HR种子")

                # 检查每个HR种子
                for torrent in hr_torrents:
                    try:
                        torrent_hash = torrent.get("hash")
                        torrent_name = torrent.get("name")
                        seeding_time = torrent.get("seeding_time", 0) / 3600  # 转换为小时
                        ratio = torrent.get("ratio", 0)
                        state = torrent.get("state", "")
                        
                        logger.info(f"检查HR种子：{torrent_name} (状态: {state})")
                        logger.debug(f"种子详情：哈希={torrent_hash}, 做种时间={seeding_time:.2f}小时, 分享率={ratio:.2f}, 状态={state}")

                        # 解析站点信息
                        logger.debug(f"尝试解析种子 {torrent_name} 的站点信息")
                        site_name = self._extract_site_name(torrent_name)
                        if not site_name:
                            logger.warning(f"无法解析种子所属站点：{torrent_name}")
                            logger.debug(f"当前配置的站点：{[site.get('site_name') for site in self._sites_config]}")
                            continue
                        logger.info(f"种子 {torrent_name} 所属站点：{site_name}")

                        # 获取站点HR配置
                        logger.debug(f"尝试获取站点 {site_name} 的HR配置")
                        site_config = self._get_site_config(site_name)
                        if not site_config:
                            logger.warning(f"未找到站点HR配置：{site_name}")
                            logger.debug(f"当前站点HR配置：{self._sites_config}")
                            continue
                        logger.info(f"站点 {site_name} 的HR配置：{site_config}")

                        # 检查是否满足HR条件
                        time_requirement = site_config.get("time", 0)
                        ratio_requirement = site_config.get("hr_ratio", 0)
                        hr_deadline_days = site_config.get("hr_deadline_days", 0)

                        logger.info(f"HR要求 - 做种时间：{time_requirement}小时，分享率：{ratio_requirement}")
                        logger.info(f"当前状态 - 做种时间：{seeding_time:.2f}小时，分享率：{ratio:.2f}")

                        # 检查是否超过HR满足期限
                        added_time = torrent.get("added_time")
                        if added_time and hr_deadline_days > 0:
                            # 计算已过去的天数
                            days_passed = (datetime.now() - datetime.fromtimestamp(added_time)).days
                            logger.info(f"HR期限检查 - 已过去：{days_passed}天，要求期限：{hr_deadline_days}天")
                            
                            if days_passed > hr_deadline_days:
                                # 超过期限，发送警告通知
                                logger.warning(f"⚠ 种子 {torrent_name} 已超过HR满足期限 {hr_deadline_days}天")
                                self.post_message(
                                    mtype=NotificationType.Plugin,
                                    title="【HR管理】HR种子超过期限警告",
                                    text=f"种子 {torrent_name} 已超过HR满足期限 {hr_deadline_days}天\n"
                                         f"站点：{site_name}\n"
                                         f"当前做种时间：{seeding_time:.2f}小时，分享率：{ratio:.2f}\n"
                                         f"要求：做种时间 ≥ {time_requirement}小时，分享率 ≥ {ratio_requirement}"
                                )
                                logger.info(f"发送HR期限警告通知：{torrent_name}")
                                continue

                        # 检查是否满足HR条件
                        time_ok = seeding_time >= time_requirement
                        ratio_ok = ratio >= ratio_requirement
                        
                        logger.info(f"HR条件检查 - 做种时间: {'✓' if time_ok else '✗'}, 分享率: {'✓' if ratio_ok else '✗'}")
                        
                        if time_ok and ratio_ok:
                            # 移除HR标签，添加出种标签
                            logger.info(f"🎉 种子 {torrent_name} 已满足所有HR条件！")
                            logger.info(f"正在更新种子标签：移除 '{self._hr_tag}'，添加 '{self._finished_tag}'")
                            
                            try:
                                # 先获取种子的所有当前标签
                                logger.debug(f"获取种子 {torrent_hash} 的所有当前标签")
                                torrents, error = downloader.get_torrents(ids=torrent_hash)
                                if not error and torrents and len(torrents) > 0:
                                    current_tags_str = torrents[0].get("tags", "")
                                    # 处理不同的标签分隔符情况
                                    if isinstance(current_tags_str, str):
                                        # 尝试不同的分隔符
                                        if "," in current_tags_str:
                                            current_tags = [str(tag).strip() for tag in current_tags_str.split(',') if tag.strip()]
                                        elif "|" in current_tags_str:
                                            current_tags = [str(tag).strip() for tag in current_tags_str.split('|') if tag.strip()]
                                        else:
                                            current_tags = [current_tags_str.strip()] if current_tags_str.strip() else []
                                    elif isinstance(current_tags_str, list):
                                        current_tags = [str(tag).strip() for tag in current_tags_str if tag.strip()]
                                    else:
                                        current_tags = []
                                        
                                    logger.debug(f"种子 {torrent_hash} 当前的标签：{current_tags}")
                                    
                                    # 移除所有现有标签
                                    if current_tags:
                                        logger.debug(f"移除种子 {torrent_hash} 的所有标签：{current_tags}")
                                        
                                        # 逐个移除标签，确保每个标签都被正确移除
                                        for tag in current_tags:
                                            if tag:
                                                downloader.remove_torrents_tag(ids=torrent_hash, tag=[tag])
                                                logger.debug(f"成功移除标签：{tag}")
                                        
                                        # 等待一下，确保标签移除操作完成
                                        time.sleep(0.5)
                                
                                # 然后设置出种标签
                                logger.debug(f"为种子 {torrent_hash} 设置出种标签：{self._finished_tag}")
                                downloader.set_torrents_tag(ids=torrent_hash, tags=[self._finished_tag])
                                
                                # 验证标签是否设置成功
                                time.sleep(0.5)
                                torrents, error = downloader.get_torrents(ids=torrent_hash)
                                if not error and torrents and len(torrents) > 0:
                                    new_tags_str = torrents[0].get("tags", "")
                                    new_tags = [str(tag).strip() for tag in new_tags_str.split(',') if tag.strip()]
                                    logger.debug(f"种子 {torrent_hash} 设置标签后的标签：{new_tags}")
                                
                                logger.info(f"成功更新种子 {torrent_hash} 的标签")
                            except Exception as e:
                                logger.error(f"更新种子标签失败：{str(e)}")
                                raise

                            # 发送通知
                            self.post_message(
                                mtype=NotificationType.Plugin,
                                title="【HR管理】HR种子出种",
                                text=f"种子 {torrent_name} 已满足HR条件\n"
                                     f"站点：{site_name}\n"
                                     f"实际做种时间：{seeding_time:.2f}小时\n"
                                     f"实际分享率：{ratio:.2f}\n"
                                     f"标签已更改为：{self._finished_tag}"
                            )
                            logger.info(f"发送HR种子出种通知：{torrent_name}")
                        else:
                            logger.info(f"种子 {torrent_name} 尚未满足HR条件，继续监控")

                    except Exception as e:
                        logger.error(f"检查种子 {torrent.get('name')} 出错：{str(e)}", exc_info=True)

            logger.info("✅ HR种子检查完成")

        except Exception as e:
            logger.error(f"检查HR种子出错：{str(e)}", exc_info=True)

    def _extract_site_name(self, torrent_name: str) -> Optional[str]:
        """
        从种子名称中提取站点信息
        """
        logger.debug(f"提取站点信息 - 种子名称：{torrent_name}")
        
        if not torrent_name:
            logger.debug("种子名称为空，无法提取站点信息")
            return None
            
        # 检查是否有站点配置
        if not self._sites_config:
            logger.debug("没有配置任何站点，无法提取站点信息")
            return None
            
        # 站点名称映射表
        site_name_mappings = {
            "CHDBits": "彩虹岛",
            "chdbits": "彩虹岛",
            "RHDao": "彩虹岛",
            "rhd": "彩虹岛",
            "rhdbits": "彩虹岛",
        }
        
        # 1. 尝试从种子名称中提取站点标识
        import re
        site_patterns = [r'@(\w+)', r'_(\w+)_', r'\[(\w+)\]', r'\((\w+)\)']
        extracted_site = None
        
        for pattern in site_patterns:
            match = re.search(pattern, torrent_name)
            if match:
                extracted_site = match.group(1)
                logger.debug(f"从种子名称中提取到站点标识：{extracted_site}")
                break
        
        # 如果提取到站点标识，尝试映射
        if extracted_site:
            if extracted_site in site_name_mappings:
                mapped_site = site_name_mappings[extracted_site]
                logger.debug(f"将站点标识 {extracted_site} 映射为站点名称 {mapped_site}")
                # 检查映射后的站点是否在配置中
                for site_config in self._sites_config:
                    site_name = site_config.get("site_name")
                    if site_name and site_name == mapped_site:
                        logger.debug(f"成功匹配映射后的站点：{site_name}")
                        return site_name
            else:
                # 检查提取的站点标识是否直接匹配配置的站点
                for site_config in self._sites_config:
                    site_name = site_config.get("site_name")
                    if site_name and extracted_site.lower() in site_name.lower():
                        logger.debug(f"成功匹配站点：{site_name}")
                        return site_name
        
        # 2. 直接匹配站点名称
        # 将站点按名称长度降序排序，优先匹配较长的站点名称
        sorted_sites = sorted(self._sites_config, 
                             key=lambda x: len(x.get("site_name", "")), 
                             reverse=True)
        
        logger.debug(f"站点列表（按长度降序）：{[site.get('site_name') for site in sorted_sites]}")
        
        # 匹配站点名称
        for site_config in sorted_sites:
            site_name = site_config.get("site_name")
            if not site_name:
                logger.debug("跳过空站点名称的配置")
                continue
            
            logger.debug(f"尝试匹配站点：{site_name}")
            
            # 不区分大小写的匹配
            if site_name.lower() in torrent_name.lower():
                logger.debug(f"成功匹配站点：{site_name}")
                return site_name
        
        logger.debug(f"无法匹配种子 {torrent_name} 的站点信息")
        return None

    def _get_site_config(self, site_name: str) -> Optional[dict]:
        """
        获取站点HR配置
        """
        logger.debug(f"查找站点配置 - 站点名称：{site_name}")
        
        for site_config in self._sites_config:
            if site_config.get("site_name") == site_name:
                logger.debug(f"成功找到站点 {site_name} 的配置：{site_config}")
                return site_config
        
        logger.debug(f"未找到站点 {site_name} 的配置")
        return None

    def _is_hr_seed(self, torrent_name: str, site_config: dict) -> bool:
        """
        判断是否为HR种子
        """
        logger.debug(f"检测HR种子 - 种子名称：{torrent_name}, 站点配置：{site_config}")
        
        # 检查站点是否启用全站HR
        if site_config.get("hr_active", False):
            logger.debug(f"站点 {site_config.get('site_name')} 已启用全站HR，种子自动标记为HR种子")
            return True

        # 检查种子名称中是否包含HR标签
        has_hr = "HR" in torrent_name.upper()
        has_hr_with_slash = "H&R" in torrent_name.upper()
        
        logger.debug(f"种子名称包含HR: {has_hr}, 包含H&R: {has_hr_with_slash}")
        
        return has_hr or has_hr_with_slash

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            value_str = value.strip().lower()
            if value_str in ["1", "true", "yes", "y", "on", "是"]:
                return True
            if value_str in ["0", "false", "no", "n", "off", "否"]:
                return False
        if isinstance(value, (int, float)):
            return value != 0
        return default

    def _validate_and_normalize_sites_config(self, sites_config: Any) -> List[dict]:
        """
        校验并标准化站点配置
        """
        if not isinstance(sites_config, list):
            logger.warning("站点配置格式无效，已回退为空列表")
            return []

        normalized_sites: List[dict] = []
        seen_site_names = set()

        for index, site in enumerate(sites_config, start=1):
            if not isinstance(site, dict):
                logger.warning(f"第 {index} 个站点配置不是字典，已跳过")
                continue

            site_name = str(site.get("site_name", "") or "").strip()
            if not site_name:
                logger.warning(f"第 {index} 个站点缺少 site_name，已跳过")
                continue

            site_key = site_name.lower()
            if site_key in seen_site_names:
                logger.warning(f"检测到重复站点配置：{site_name}，仅保留首次配置")
                continue
            seen_site_names.add(site_key)

            base_time = self._safe_float(site.get("time", site.get("hr_duration", 0.0)), 0.0)
            base_time = max(0.0, base_time)

            additional_seed_time_raw = site.get("additional_seed_time")
            additional_seed_time = None
            if additional_seed_time_raw not in [None, ""]:
                additional_seed_time = max(0.0, self._safe_float(additional_seed_time_raw, 0.0))

            final_time = base_time + (additional_seed_time or 0.0)
            hr_ratio = max(0.0, self._safe_float(site.get("hr_ratio", 0.0), 0.0))
            hr_deadline_days = max(0, self._safe_int(site.get("hr_deadline_days", 0), 0))
            hr_active = self._safe_bool(site.get("hr_active", False), False)

            normalized_site = {
                "site_name": site_name,
                "time": final_time,
                "hr_duration": final_time,
                "additional_seed_time": additional_seed_time,
                "hr_ratio": hr_ratio,
                "hr_active": hr_active,
                "hr_deadline_days": hr_deadline_days,
            }
            normalized_sites.append(normalized_site)

        logger.info(f"站点配置标准化完成，有效站点数：{len(normalized_sites)}")
        return normalized_sites

    def _get_torrent_added_time(self, torrent: dict) -> int:
        """
        获取种子添加时间戳（秒）
        """
        possible_time_fields = [
            "added_time", "created_at", "start_time", "time_added", "date_added",
            "addedOn", "add_time", "added", "added_on"
        ]
        for field in possible_time_fields:
            raw_value = torrent.get(field)
            if raw_value in [None, "", 0, "0"]:
                continue
            ts = self._safe_int(raw_value, 0)
            if ts > 0:
                return ts
        return 0

    def _calculate_priority_score(
            self,
            seeding_time: float,
            ratio: float,
            time_requirement: float,
            ratio_requirement: float,
            hr_deadline_days: int,
            added_time: int,
            is_timeout: bool = False) -> float:
        """
        计算优先级分数（0-100，越高越紧急）
        优先级 = 期限权重 * 0.5 + 时间权重 * 0.3 + 分享率权重 * 0.2
        """
        if is_timeout:
            return 100.0

        time_gap = max(0.0, time_requirement - seeding_time)
        ratio_gap = max(0.0, ratio_requirement - ratio)

        time_pressure = min(1.0, time_gap / max(time_requirement, 1.0))
        ratio_pressure = min(1.0, ratio_gap / max(ratio_requirement, 1.0)) if ratio_requirement > 0 else 0.0

        deadline_pressure = 0.0
        if hr_deadline_days > 0 and added_time > 0:
            elapsed_hours = max(0.0, (time.time() - added_time) / 3600)
            total_deadline_hours = hr_deadline_days * 24
            deadline_pressure = min(1.0, elapsed_hours / max(total_deadline_hours, 1.0))

        score = (deadline_pressure * 0.5 + time_pressure * 0.3 + ratio_pressure * 0.2) * 100
        return round(min(100.0, max(0.0, score)), 2)

    def _calculate_alert_info(
            self,
            seeding_time: float,
            ratio: float,
            time_requirement: float,
            ratio_requirement: float,
            hr_deadline_days: int,
            added_time: int) -> Dict[str, Any]:
        """
        计算告警信息与展示字段
        """
        time_progress = 1.0 if time_requirement <= 0 else min(1.0, seeding_time / max(time_requirement, 1.0))
        ratio_progress = 1.0 if ratio_requirement <= 0 else min(1.0, ratio / max(ratio_requirement, 1.0))
        progress = min(time_progress, ratio_progress)
        progress_percent = round(progress * 100, 1)

        time_ok = seeding_time >= time_requirement
        ratio_ok = ratio >= ratio_requirement
        finished = time_ok and ratio_ok

        remaining_deadline_days = None
        is_timeout = False
        if hr_deadline_days > 0 and added_time > 0:
            deadline_ts = added_time + hr_deadline_days * 24 * 3600
            remaining_seconds = deadline_ts - int(time.time())
            remaining_deadline_days = round(remaining_seconds / 86400, 2)
            if remaining_seconds <= 0 and not finished:
                is_timeout = True

        alert_level = self.ALERT_NORMAL
        if is_timeout:
            alert_level = self.ALERT_TIMEOUT
        elif remaining_deadline_days is not None and remaining_deadline_days <= 3 and not finished:
            alert_level = self.ALERT_URGENT
        elif progress < 0.5 and not finished:
            alert_level = self.ALERT_WARNING

        alert_text_map = {
            self.ALERT_NORMAL: "正常",
            self.ALERT_WARNING: "警告",
            self.ALERT_URGENT: "紧急",
            self.ALERT_TIMEOUT: "超期",
        }
        alert_text = alert_text_map.get(alert_level, "正常")

        priority_score = self._calculate_priority_score(
            seeding_time=seeding_time,
            ratio=ratio,
            time_requirement=time_requirement,
            ratio_requirement=ratio_requirement,
            hr_deadline_days=hr_deadline_days,
            added_time=added_time,
            is_timeout=is_timeout,
        )

        star_level = 1
        if priority_score >= 80:
            star_level = 5
        elif priority_score >= 60:
            star_level = 4
        elif priority_score >= 40:
            star_level = 3
        elif priority_score >= 20:
            star_level = 2

        priority_stars = "★" * star_level + "☆" * (5 - star_level)

        return {
            "alert_level": alert_level,
            "alert_text": alert_text,
            "progress_percent": progress_percent,
            "priority_score": priority_score,
            "priority_stars": priority_stars,
            "remaining_deadline_days": remaining_deadline_days,
            "is_timeout": is_timeout,
        }

    def get_state(self) -> bool:
        return self._enabled

    def get_command(self) -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/hr_seeds",
                "endpoint": self.get_hr_seeds_data,
                "methods": ["GET"],
                "summary": "获取HR种子数据",
                "description": "返回HR种子看板数据（总数、详情、站点分布）",
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        if self._enabled:
            return [{
                "id": "HRManagerCheck",
                "name": "HR种子检查服务",
                "trigger": "interval",
                "func": self.check_hr_seeds,
                "kwargs": {"seconds": self._check_interval}
            }]
        return []

    def __get_demo_config(self):
        """
        获取默认配置
        """
        return """####### 配置说明 BEGIN #######
# 1. 此配置文件专门用于设定各站点的特定配置，包括做种时间、H&R激活状态等。
# 2. 配置项通过数组形式组织，每个站点的配置作为数组的一个元素，以'-'标记开头。
# 3. 如果某站点的具体配置项与全局配置相同，则无需单独设置该项，默认采用全局配置。
####### 配置说明 END #######

- # 站点名称，用于标识适用于哪个站点
  site_name: '彩虹岛'
  # H&R时间（小时），站点默认的H&R时间，做种时间达到H&R时间后移除标签
  hr_duration: 120.0
  # 分享率，做种时期望达到的分享比例，达到目标分享率后移除标签
  hr_ratio: 99.0
  # H&R激活，站点是否已启用全站H&R，开启后所有种子均视为H&R种子
  hr_active: false
  # H&R满足要求的期限（天数），需在此天数内满足H&R要求
  hr_deadline_days: 20

- # 站点名称，用于标识适用于哪个站点
  site_name: '站点2'
  # H&R时间（小时），站点默认的H&R时间，做种时间达到H&R时间后移除标签
  hr_duration: 0.0
  # 分享率，做种时期望达到的分享比例，达到目标分享率后移除标签
  hr_ratio: 0.0
  # H&R激活，站点是否已启用全站H&R，开启后所有种子均视为H&R种子
  hr_active: false
  # H&R满足要求的期限（天数），需在此天数内满足H&R要求
  hr_deadline_days: 0

- # 站点名称，用于标识适用于哪个站点
  site_name: '站点3'
  # H&R时间（小时），站点默认的H&R时间，做种时间达到H&R时间后移除标签
  hr_duration: 0.0
  # 分享率，做种时期望达到的分享比例，达到目标分享率后移除标签
  hr_ratio: 0.0
  # H&R激活，站点是否已启用全站H&R，开启后所有种子均视为H&R种子
  hr_active: false
  # H&R满足要求的期限（天数），需在此天数内满足H&R要求
  hr_deadline_days: 0
"""

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        # 获取所有配置的下载器列表
        downloader_list = []
        try:
            if hasattr(self, '_downloaderhelper') and self._downloaderhelper:
                downloader_configs = self._downloaderhelper.get_configs()
                downloader_list = [name for name in downloader_configs.keys()]
        except Exception as e:
            logger.debug(f"获取下载器列表失败：{e}")
        
        return [
            {
                'component': 'VForm',
                'content': [
                    # 基本设置
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'flat',
                            'class': 'mb-6',
                            'color': 'surface'
                        },
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {
                                    'class': 'pa-6'
                                },
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'd-flex align-center text-h6'
                                        },
                                        'content': [
                                            {
                                                'component': 'VIcon',
                                                'props': {
                                                    'style': 'color: #16b1ff;',
                                                    'class': 'mr-3',
                                                    'size': 'default'
                                                },
                                                'text': 'mdi-cog'
                                            },
                                            {
                                                'component': 'span',
                                                'text': '基本设置'
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'px-6 pb-6'
                                },
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
                                                            'model': 'enabled',
                                                            'label': '启用插件',
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
                                            },
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
                                                            'model': 'hr_tag',
                                                            'label': 'HR标签',
                                                            'placeholder': 'HR',
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
                                            },
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
                                                            'model': 'finished_tag',
                                                            'label': '出种标签',
                                                            'placeholder': '已完成',
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
                                            },
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
                                                            'model': 'check_interval',
                                                            'label': '检查间隔（秒）',
                                                            'placeholder': '3600',
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 高级设置
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'flat',
                            'class': 'mb-6',
                            'color': 'surface'
                        },
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {
                                    'class': 'pa-6'
                                },
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'd-flex align-center text-h6'
                                        },
                                        'content': [
                                            {
                                                'component': 'VIcon',
                                                'props': {
                                                    'style': 'color: #16b1ff;',
                                                    'class': 'mr-3',
                                                    'size': 'default'
                                                },
                                                'text': 'mdi-puzzle'
                                            },
                                            {
                                                'component': 'span',
                                                'text': '高级设置'
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'px-6 pb-6'
                                },
                                'content': [
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
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'monitor_downloaders',
                                                            'label': '监控的下载器',
                                                            'items': downloader_list,
                                                            'multiple': True,
                                                            'return-object': False,
                                                            'placeholder': '选择要监控的下载器（空表示监控所有）',
                                                            'color': 'primary',
                                                            'hide-details': True
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
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'dialog_closed',
                                                            'label': '打开站点配置窗口',
                                                            'hint': '点击弹出窗口以修改站点配置',
                                                            'persistent-hint': True,
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 站点配置
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'flat',
                            'class': 'mb-6',
                            'color': 'surface'
                        },
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {
                                    'class': 'pa-6'
                                },
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'd-flex align-center text-h6'
                                        },
                                        'content': [
                                            {
                                                'component': 'VIcon',
                                                'props': {
                                                    'style': 'color: #16b1ff;',
                                                    'class': 'mr-3',
                                                    'size': 'default'
                                                },
                                                'text': 'mdi-database'
                                            },
                                            {
                                                'component': 'span',
                                                'text': '站点配置'
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'px-6 pb-6'
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'class': 'mb-4'
                                        },
                                        'content': [
                                            {
                                                'component': 'span',
                                                'text': '点击上方的"打开站点配置窗口"按钮，可以设置各站点的HR标准，包括做种时间、分享率和期限等。'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'span',
                                                'text': '注意：配置完成后请保存设置并重启插件以应用更改'
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 使用说明
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'flat',
                            'class': 'mb-6',
                            'color': 'surface'
                        },
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {
                                    'class': 'pa-6'
                                },
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'd-flex align-center text-h6'
                                        },
                                        'content': [
                                            {
                                                'component': 'VIcon',
                                                'props': {
                                                    'style': 'color: #16b1ff;',
                                                    'class': 'mr-3',
                                                    'size': 'default'
                                                },
                                                'text': 'mdi-help-circle'
                                            },
                                            {
                                                'component': 'span',
                                                'text': '使用说明'
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'px-6 pb-6'
                                },
                                'content': [
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'text-body-1'
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'mb-4'
                                                },
                                                'text': '📦 插件功能：自动管理下载种子的HR标签，监控种子的做种时间和分享率，满足条件后自动更改标签并通知用户。'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'mb-4'
                                                },
                                                'text': '⚙️ 基本设置：配置插件的核心功能，包括启用/禁用插件、设置HR标签和出种标签、调整检查间隔。'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'mb-4'
                                                },
                                                'text': '🔧 高级设置：选择要监控的下载器，或点击按钮打开站点配置窗口。'
                                            },
                                            {
                                                'component': 'div',
                                                'text': '📝 站点配置：在弹出的配置窗口中，可以为每个站点单独设置HR标准，包括做种时间、分享率和满足期限等。'
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 站点配置对话框
                    {
                        "component": "VDialog",
                        "props": {
                            "model": "dialog_closed",
                            "max-width": "65rem",
                            "overlay-class": "v-dialog--scrollable v-overlay--scroll-blocked",
                            "content-class": "v-card v-card--density-default v-card--variant-elevated rounded-t"
                        },
                        "content": [
                            {
                                "component": "VCard",
                                "content": [
                                    {
                                        "component": "VCardItem",
                                        "props": {
                                            "class": "pa-4"
                                        },
                                        "content": [
                                            {
                                                "component": "VCardTitle",
                                                "props": {
                                                    "class": "text-h6"
                                                },
                                                "text": "站点HR配置"
                                            },
                                            {
                                                "component": "VDialogCloseBtn",
                                                "props": {
                                                    "model": "dialog_closed"
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {
                                            "class": "px-4"
                                        },
                                        "content": [
                                            {
                                                'component': 'VAceEditor',
                                                'props': {
                                                    'modelvalue': 'site_config_str',
                                                    'lang': 'yaml',
                                                    'theme': 'monokai',
                                                    'style': 'height: 30rem',
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCardActions",
                                        "props": {
                                            "class": "justify-end px-4 pb-4"
                                        },
                                        "content": [
                                            {
                                                "component": "VDialogCloseBtn",
                                                "props": {
                                                    "model": "dialog_closed",
                                                    "text": "关闭",
                                                    "variant": "text"
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "hr_tag": "HR",
            "finished_tag": "已完成",
            "check_interval": 3600,
            "monitor_downloaders": [],
            "dialog_closed": False,
            "site_config_str": HRManager.__get_demo_config()
        }

    @staticmethod
    def __get_demo_config():
        """获取默认YAML配置模板"""
        return """####### 配置说明 BEGIN #######
# 1. 此配置文件用于设定各站点的HR标准，包括做种时间、分享率、期限等
# 2. 配置项通过数组形式组织，每个站点的配置作为数组的一个元素，以'-'标记开头
# 3. 如果某站点的具体配置项未设置，则使用默认值
####### 配置说明 END #######

- # 站点名称，用于标识适用于哪个站点
  site_name: '彩虹岛'
  # H&R时间（小时），做种时间达到此值后视为完成HR要求
  hr_duration: 120.0
  # 分享率，做种时期望达到的分享比例
  hr_ratio: 99.0
  # H&R激活，站点是否已启用全站H&R，开启后所有种子均视为HR种子
  hr_active: false
  # H&R满足要求的期限（天数），需在此天数内满足H&R要求
  hr_deadline_days: 20

- # 站点名称，用于标识适用于哪个站点
  site_name: '站点2'
  # H&R时间（小时），做种时间达到此值后视为完成HR要求
  hr_duration: 48.0
  # 分享率，做种时期望达到的分享比例
  hr_ratio: 1.0
  # H&R激活，站点是否已启用全站H&R，开启后所有种子均视为HR种子
  hr_active: true
  # H&R满足要求的期限（天数），需在此天数内满足H&R要求
  hr_deadline_days: 14

- # 站点名称，用于标识适用于哪个站点
  site_name: '站点3'
  # H&R时间（小时），做种时间达到此值后视为完成HR要求
  hr_duration: 72.0
  # 分享率，做种时期望达到的分享比例
  hr_ratio: 2.0
  # H&R激活，站点是否已启用全站H&R，开启后所有种子均视为HR种子
  hr_active: false
  # H&R满足要求的期限（天数），需在此天数内满足H&R要求
  hr_deadline_days: 30
"""

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，展示HR种子数据看板
        """
        # 辅助函数：构建统计卡片
        def _stat_card(icon: str, color: str, value: str, label: str) -> dict:
            return {
                'component': 'VCol',
                'props': {'cols': 6, 'md': 3},
                'content': [{
                    'component': 'VCard',
                    'props': {'variant': 'tonal', 'color': color, 'class': 'pa-4'},
                    'content': [{
                        'component': 'div',
                        'props': {'class': 'd-flex align-center'},
                        'content': [
                            {
                                'component': 'VIcon',
                                'props': {'size': 'x-large', 'color': color, 'class': 'mr-4'},
                                'text': icon
                            },
                            {
                                'component': 'div',
                                'content': [
                                    {
                                        'component': 'div',
                                        'props': {'class': 'text-h4 font-weight-bold'},
                                        'text': value
                                    },
                                    {
                                        'component': 'div',
                                        'props': {'class': 'text-caption text-medium-emphasis'},
                                        'text': label
                                    }
                                ]
                            }
                        ]
                    }]
                }]
            }

        # 辅助函数：告警级别对应的 VChip 颜色
        def _alert_chip(alert_level: str, alert_text: str) -> dict:
            color_map = {
                'normal': 'success', 'warning': 'warning',
                'urgent': 'error', 'timeout': 'error'
            }
            variant = 'flat' if alert_level == 'timeout' else 'tonal'
            return {
                'component': 'VChip',
                'props': {
                    'color': color_map.get(alert_level, 'success'),
                    'variant': variant, 'size': 'small', 'label': True
                },
                'text': alert_text
            }

        # 辅助函数：进度条颜色
        def _progress_color(pct: float) -> str:
            if pct >= 80: return 'success'
            if pct >= 50: return 'info'
            if pct >= 30: return 'warning'
            return 'error'

        # 辅助函数：剩余时间单元格内容
        def _remaining_cell(remaining_time: str) -> dict:
            if remaining_time == '已满足':
                return {
                    'component': 'td',
                    'props': {'class': 'text-center'},
                    'content': [{
                        'component': 'VChip',
                        'props': {'color': 'success', 'variant': 'tonal', 'size': 'small', 'prepend-icon': 'mdi-check-circle'},
                        'text': '已满足'
                    }]
                }
            return {
                'component': 'td',
                'props': {'class': 'text-center text-high-emphasis'},
                'text': remaining_time
            }

        # 辅助函数：进度单元格（进度条 + 百分比）
        def _progress_cell(pct: float) -> dict:
            return {
                'component': 'td',
                'props': {'class': 'text-center', 'style': 'min-width: 120px;'},
                'content': [
                    {
                        'component': 'VProgressLinear',
                        'props': {
                            'model-value': pct,
                            'color': _progress_color(pct),
                            'height': 8,
                            'rounded': True
                        }
                    },
                    {
                        'component': 'div',
                        'props': {'class': 'text-caption text-medium-emphasis mt-1'},
                        'text': f'{pct}%'
                    }
                ]
            }

        try:
            hr_seeds_data = self.get_hr_seeds_data()
            seeds = hr_seeds_data.get('seeds', [])
            site_stats = hr_seeds_data.get('site_stats', {})
            total = hr_seeds_data.get('total_count', 0)

            # 计算统计数据
            alert_count = sum(1 for s in seeds if s.get('alert_level') in ('warning', 'urgent', 'timeout'))
            timeout_count = sum(1 for s in seeds if s.get('alert_level') == 'timeout')
            avg_progress = round(sum(s.get('progress_percent', 0) for s in seeds) / max(len(seeds), 1), 1)

            # 站点分布芯片颜色轮换
            chip_colors = ['primary', 'success', 'info', 'warning', 'secondary']

            # 如果没有种子数据，显示空状态
            if not seeds:
                return [{
                    'component': 'VContainer',
                    'props': {'fluid': True, 'class': 'pa-0'},
                    'content': [
                        # 统计概览（全零）
                        {
                            'component': 'VRow',
                            'props': {'class': 'mb-4'},
                            'content': [
                                _stat_card('mdi-seed', 'primary', '0', 'HR种子总数'),
                                _stat_card('mdi-alert', 'warning', '0', '告警种子'),
                                _stat_card('mdi-clock-alert', 'error', '0', '超期种子'),
                                _stat_card('mdi-percent', 'success', '0%', '平均进度'),
                            ]
                        },
                        # 空状态提示
                        {
                            'component': 'VCard',
                            'props': {'variant': 'flat'},
                            'content': [{
                                'component': 'VCardText',
                                'props': {'class': 'text-center py-16'},
                                'content': [
                                    {
                                        'component': 'VIcon',
                                        'props': {'size': '80', 'color': 'grey-lighten-1', 'class': 'mb-4'},
                                        'text': 'mdi-seed-off'
                                    },
                                    {
                                        'component': 'div',
                                        'props': {'class': 'text-h6 text-medium-emphasis mb-2'},
                                        'text': '暂无HR种子'
                                    },
                                    {
                                        'component': 'div',
                                        'props': {'class': 'text-body-2 text-disabled'},
                                        'text': '当前没有正在监控的HR种子，请确认插件已启用并正确配置站点'
                                    }
                                ]
                            }]
                        }
                    ]
                }]

            # 有数据时的完整看板
            return [{
                'component': 'VContainer',
                'props': {'fluid': True, 'class': 'pa-0'},
                'content': [
                    # ===== 统计概览 =====
                    {
                        'component': 'VRow',
                        'props': {'class': 'mb-4'},
                        'content': [
                            _stat_card('mdi-seed', 'primary', str(total), 'HR种子总数'),
                            _stat_card('mdi-alert', 'warning', str(alert_count), '告警种子'),
                            _stat_card('mdi-clock-alert', 'error', str(timeout_count), '超期种子'),
                            _stat_card('mdi-percent', 'success', f'{avg_progress}%', '平均进度'),
                        ]
                    },
                    # ===== 站点分布 =====
                    {
                        'component': 'VCard',
                        'props': {'variant': 'flat', 'class': 'mb-4'},
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {'class': 'pa-4 pb-0'},
                                'content': [{
                                    'component': 'VCardTitle',
                                    'props': {'class': 'd-flex align-center text-subtitle-1'},
                                    'content': [
                                        {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mr-2', 'size': 'small'}, 'text': 'mdi-map-marker'},
                                        {'component': 'span', 'text': '站点分布'}
                                    ]
                                }]
                            },
                            {
                                'component': 'VCardText',
                                'props': {'class': 'pa-4 d-flex flex-wrap ga-2'},
                                'content': [
                                    {
                                        'component': 'VChip',
                                        'props': {
                                            'color': chip_colors[i % len(chip_colors)],
                                            'variant': 'tonal',
                                            'label': True
                                        },
                                        'text': f'{site} ({count})'
                                    }
                                    for i, (site, count) in enumerate(site_stats.items())
                                ] if site_stats else [{
                                    'component': 'span',
                                    'props': {'class': 'text-disabled'},
                                    'text': '暂无站点数据'
                                }]
                            }
                        ]
                    },
                    # ===== HR种子列表 =====
                    {
                        'component': 'VCard',
                        'props': {'variant': 'flat'},
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {'class': 'pa-4 pb-0'},
                                'content': [{
                                    'component': 'VCardTitle',
                                    'props': {'class': 'd-flex align-center justify-space-between'},
                                    'content': [
                                        {
                                            'component': 'div',
                                            'props': {'class': 'd-flex align-center text-subtitle-1'},
                                            'content': [
                                                {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mr-2', 'size': 'small'}, 'text': 'mdi-format-list-bulleted'},
                                                {'component': 'span', 'text': 'HR种子列表'}
                                            ]
                                        },
                                        {
                                            'component': 'VChip',
                                            'props': {'size': 'small', 'variant': 'text', 'color': 'default'},
                                            'text': f'共 {len(seeds)} 条'
                                        }
                                    ]
                                }]
                            },
                            {
                                'component': 'VCardText',
                                'props': {'class': 'pa-4'},
                                'content': [{
                                    'component': 'VTable',
                                    'props': {'hover': True, 'density': 'comfortable'},
                                    'content': [
                                        {
                                            'component': 'thead',
                                            'content': [{
                                                'component': 'tr',
                                                'content': [
                                                    {'component': 'th', 'props': {'class': 'text-left font-weight-bold', 'style': 'min-width: 200px;'}, 'text': '种子名称'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '站点'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '下载器'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '添加时间'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '做种时间'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '剩余时间'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '要求时间'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '告警'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold', 'style': 'min-width: 120px;'}, 'text': '进度'},
                                                    {'component': 'th', 'props': {'class': 'text-center font-weight-bold'}, 'text': '优先级'},
                                                ]
                                            }]
                                        },
                                        {
                                            'component': 'tbody',
                                            'content': [
                                                {
                                                    'component': 'tr',
                                                    'content': [
                                                        # 种子名称（溢出省略）
                                                        {
                                                            'component': 'td',
                                                            'props': {
                                                                'class': 'text-left',
                                                                'style': 'max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'
                                                            },
                                                            'text': seed.get('name')
                                                        },
                                                        # 站点
                                                        {'component': 'td', 'props': {'class': 'text-center'}, 'text': seed.get('site')},
                                                        # 下载器
                                                        {'component': 'td', 'props': {'class': 'text-center'}, 'text': seed.get('downloader')},
                                                        # 添加时间
                                                        {'component': 'td', 'props': {'class': 'text-center text-caption'}, 'text': seed.get('added_time')},
                                                        # 做种时间
                                                        {'component': 'td', 'props': {'class': 'text-center'}, 'text': seed.get('seeding_time')},
                                                        # 剩余时间（带图标）
                                                        _remaining_cell(seed.get('remaining_time', '')),
                                                        # 要求时间
                                                        {'component': 'td', 'props': {'class': 'text-center'}, 'text': seed.get('required_time')},
                                                        # 告警（VChip 徽章）
                                                        {
                                                            'component': 'td',
                                                            'props': {'class': 'text-center'},
                                                            'content': [_alert_chip(seed.get('alert_level', 'normal'), seed.get('alert_text', '正常'))]
                                                        },
                                                        # 进度（进度条）
                                                        _progress_cell(seed.get('progress_percent', 0)),
                                                        # 优先级
                                                        {'component': 'td', 'props': {'class': 'text-center'}, 'text': seed.get('priority_stars')},
                                                    ]
                                                }
                                                for seed in seeds
                                            ]
                                        }
                                    ]
                                }]
                            }
                        ]
                    }
                ]
            }]

        except Exception as e:
            logger.error(f"获取HR种子详情页数据失败：{str(e)}")
            return [{
                'component': 'VContainer',
                'props': {'fluid': True, 'class': 'pa-4'},
                'content': [
                    {
                        'component': 'VAlert',
                        'props': {'type': 'error', 'variant': 'tonal', 'class': 'mb-4'},
                        'text': f'数据加载失败：{str(e)}'
                    },
                    {
                        'component': 'VCard',
                        'props': {'variant': 'flat'},
                        'content': [{
                            'component': 'VCardText',
                            'content': [
                                {
                                    'component': 'div',
                                    'props': {'class': 'text-subtitle-2 mb-2'},
                                    'text': '可能的原因：'
                                },
                                {
                                    'component': 'VList',
                                    'props': {'density': 'compact'},
                                    'content': [
                                        {
                                            'component': 'VListItem',
                                            'props': {'prepend-icon': 'mdi-circle-small'},
                                            'text': reason
                                        }
                                        for reason in ['插件未启用', '下载器连接失败', '站点配置错误', '系统内部错误']
                                    ]
                                }
                            ]
                        }]
                    }
                ]
            }]

    def _get_hr_info_from_db(self, torrent_hash: str, torrent_name: str) -> dict:
        """
        从数据库查询种子的HR信息
        """
        hr_info = {"is_hr": False}
        try:
            from app.db.downloadhistory_oper import DownloadHistoryOper
            
            # 创建DownloadHistoryOper实例
            download_history_oper = DownloadHistoryOper()
            
            # 按哈希查询下载记录
            if torrent_hash:
                download_history = download_history_oper.get_by_hash(download_hash=torrent_hash)
                if download_history:
                    logger.debug(f"从数据库中查询到下载历史记录：{download_history}")
                    
                    # 检查种子描述中是否包含HR信息（主要来源）
                    if hasattr(download_history, 'torrent_description') and download_history.torrent_description:
                        logger.debug(f"种子描述：{download_history.torrent_description}")
                        import re
                        # 匹配多种HR格式，包括"Hit&Run：是"、"Hit & Run: Yes"等
                        hr_match = re.search(r'Hit\s*&\s*Run\s*[:：]\s*(是|Yes|1)', download_history.torrent_description, re.IGNORECASE)
                        if hr_match:
                            hr_info["is_hr"] = True
                            logger.debug("从数据库种子描述中检测到Hit&Run：是")
                            logger.info(f"✓ 从数据库中确认种子 {torrent_name} 是HR种子")
        except Exception as e:
            logger.error(f"从数据库查询HR信息失败: {e}", exc_info=True)
        
        return hr_info

    def stop_service(self):
        """
        停止插件服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"停止HR管理服务失败：{str(e)}")
    
    def get_hr_seeds_data(self) -> Dict[str, Any]:
        """
        获取HR种子数据，用于详情页展示
        """
        # 确保返回完整的数据结构
        hr_seeds_data = {
            "total_count": 0,
            "seeds": [],
            "site_stats": {}
        }
        
        if not self._enabled:
            logger.warning("插件未启用，返回空的HR种子数据")
            logger.info(f"返回的HR种子数据：{hr_seeds_data}")
            return hr_seeds_data
        
        try:
            logger.info("=== 开始获取HR种子数据 ===")
            logger.info(f"当前监控的下载器列表：{self._monitor_downloaders}")
            logger.info(f"当前配置的站点：{[site.get('site_name') for site in self._sites_config]}")
            
            # 确保_downloaderhelper已初始化
            if not hasattr(self, '_downloaderhelper') or not self._downloaderhelper:
                logger.error("下载器辅助类未初始化")
                return hr_seeds_data
            
            # 获取所有下载器
            downloaders = self._downloaderhelper.get_configs()
            logger.info(f"✓ 成功获取所有下载器配置：{list(downloaders.keys())}")
            
            # 根据监控下载器列表过滤下载器
            filtered_downloaders = {}
            if self._monitor_downloaders:
                logger.info("根据监控下载器列表过滤下载器")
                for downloader_name in self._monitor_downloaders:
                    if downloader_name in downloaders:
                        filtered_downloaders[downloader_name] = downloaders[downloader_name]
                        logger.info(f"✓ 下载器 {downloader_name} 在配置中，添加到监控列表")
                    else:
                        logger.warning(f"✗ 下载器 {downloader_name} 不在配置中，跳过")
            else:
                filtered_downloaders = downloaders
                logger.info(f"✓ 未设置监控下载器列表，将监控所有 {len(downloaders)} 个下载器")
            
            total_hr_seeds = 0
            all_hr_seeds = []
            
            # 遍历过滤后的下载器
            logger.info(f"✓ 过滤后共监控 {len(filtered_downloaders)} 个下载器")
            for downloader_name, config in filtered_downloaders.items():
                logger.info(f"\n=== 处理下载器：{downloader_name} ===")
                
                # 获取下载器实例
                downloader_service = self._downloaderhelper.get_service(name=downloader_name)
                if not downloader_service:
                    logger.error(f"✗ 无法获取下载器服务：{downloader_name}")
                    continue
                if not downloader_service.instance:
                    logger.error(f"✗ 无法获取下载器实例：{downloader_name}")
                    continue
                
                downloader = downloader_service.instance
                logger.info(f"✓ 成功获取下载器实例：{downloader_name}")
                
                # 获取所有种子
                logger.info(f"尝试从下载器 {downloader_name} 获取所有种子...")
                torrents, error = downloader.get_torrents()
                if error:
                    logger.error(f"✗ 获取下载器 {downloader_name} 种子列表失败：{error}")
                    continue
                
                if not torrents:
                    logger.info(f"✓ 下载器 {downloader_name} 中没有种子")
                    continue
                
                logger.info(f"✓ 成功获取下载器 {downloader_name} 中的 {len(torrents)} 个种子")
                logger.debug(f"获取到的种子列表：{[t.get('name') for t in torrents]}")
                
                # 过滤出HR种子：自动识别 + 标签匹配
                hr_torrents = []
                logger.info(f"当前HR标签：{self._hr_tag}")
                logger.info("开始识别HR种子...")
                
                for torrent in torrents:
                    torrent_hash = torrent.get("hash", "")
                    torrent_name = torrent.get("name", "")
                    tags = []
                    tags_str = torrent.get("tags", "")
                    
                    if isinstance(tags_str, str):
                        # 处理各种可能的标签分隔符
                        separators = [',', '|', ';']
                        found_separator = None
                        for sep in separators:
                            if sep in tags_str:
                                found_separator = sep
                                break
                        
                        if found_separator:
                            tags = [str(tag).strip() for tag in tags_str.split(found_separator) if tag.strip()]
                        else:
                            tags = [tags_str.strip()] if tags_str.strip() else []
                    elif isinstance(tags_str, list):
                        tags = [str(tag).strip() for tag in tags_str if tag.strip()]
                    
                    logger.debug(f"种子 {torrent_name} (hash: {torrent_hash}) 的标签：{tags}")
                    
                    # 检查是否为HR种子：
                    # 1. 已标记HR标签的种子
                    # 2. 自动识别的HR种子（根据站点配置和种子名称）
                    is_hr = False
                    
                    # 检查标签
                    if self._hr_tag in tags:
                        is_hr = True
                        logger.info(f"✓ 种子 {torrent_name} 带有HR标签 '{self._hr_tag}'，标记为HR种子")
                    else:
                        # 尝试自动识别
                        logger.debug(f"尝试自动识别种子 {torrent_name} 是否为HR种子")
                        # 解析站点信息
                        site_name = self._extract_site_name(torrent_name)
                        if site_name:
                            logger.debug(f"✓ 从种子名称提取到站点：{site_name}")
                            # 获取站点HR配置
                            site_config = self._get_site_config(site_name)
                            if site_config:
                                logger.debug(f"✓ 获取到站点 {site_name} 的HR配置：{site_config}")
                                # 使用_is_hr_seed方法判断是否为HR种子
                                is_hr = self._is_hr_seed(torrent_name, site_config)
                                if is_hr:
                                    logger.info(f"✓ 种子 {torrent_name} 通过自动识别标记为HR种子")
                            else:
                                logger.debug(f"✗ 未找到站点 {site_name} 的HR配置，跳过自动识别")
                        else:
                            logger.debug(f"✗ 无法从种子名称提取站点信息，跳过自动识别")
                    
                    if is_hr:
                        hr_torrents.append(torrent)
                        logger.info(f"✓ 种子 {torrent_name} 添加到HR种子列表")
                    else:
                        logger.debug(f"✗ 种子 {torrent_name} 不是HR种子")
                
                total_hr_seeds += len(hr_torrents)
                logger.info(f"✓ 累计HR种子数量：{total_hr_seeds}")
                
                # 处理每个HR种子
                for torrent in hr_torrents:
                    torrent_hash = torrent.get("hash")
                    torrent_name = torrent.get("name")
                    seeding_time = torrent.get("seeding_time", 0) / 3600  # 转换为小时
                    ratio = torrent.get("ratio", 0)
                    state = torrent.get("state", "")
                    added_time = self._get_torrent_added_time(torrent)
                    if not added_time:
                        logger.debug(f"✗ 种子 {torrent_name} 未找到有效添加时间字段")
                        logger.debug(f"  种子所有可用字段：{list(torrent.keys())}")
                    logger.info(f"  添加时间：{added_time} (timestamp)")
                    
                    logger.info(f"\n处理HR种子：{torrent_name} (hash: {torrent_hash})")
                    logger.info(f"  状态：{state}")
                    logger.info(f"  当前做种时间：{seeding_time:.2f}小时")
                    logger.info(f"  当前分享率：{ratio:.2f}")
                    logger.info(f"  添加时间：{added_time} (timestamp)")
                    
                    # 解析站点信息
                    site_name = self._extract_site_name(torrent_name)
                    logger.info(f"  从种子名称解析出的站点：{site_name}")
                    if not site_name:
                        site_name = "未知站点"
                        logger.warning(f"  ✗ 无法解析种子 {torrent_name} 的站点信息，设置为未知站点")
                    
                    # 获取站点HR配置
                    site_config = self._get_site_config(site_name)
                    logger.info(f"  站点 {site_name} 的HR配置：{site_config}")
                    
                    # 如果没有找到站点配置，使用默认配置
                    if not site_config:
                        logger.warning(f"  ✗ 没有找到站点 {site_name} 的HR配置，使用默认配置")
                        site_config = {
                            "site_name": site_name,
                            "time": 72.0,  # 默认要求72小时做种
                            "hr_ratio": 1.0  # 默认要求分享率1.0
                        }
                    
                    # 计算剩余时间
                    time_requirement = self._safe_float(site_config.get("time", 0), 0.0)
                    remaining_time = time_requirement - seeding_time
                    logger.info(f"  要求做种时间：{time_requirement}小时，剩余做种时间：{remaining_time:.2f}小时")
                    
                    # 格式化剩余时间
                    if remaining_time <= 0:
                        remaining_time_str = "已满足"
                        logger.info(f"  ✅ 做种时间已满足要求")
                    else:
                        days = int(remaining_time // 24)
                        hours = int(remaining_time % 24)
                        if days > 0:
                            remaining_time_str = f"{days}天{hours}小时"
                        else:
                            remaining_time_str = f"{hours}小时"
                        logger.info(f"  ⏳ 还需做种 {remaining_time_str}")
                    
                    # 计算分享率状态
                    ratio_requirement = self._safe_float(site_config.get("hr_ratio", 0), 0.0)
                    ratio_status = "已满足" if ratio >= ratio_requirement else "未满足"
                    logger.info(f"  要求分享率：{ratio_requirement}，当前状态：{ratio_status}")

                    hr_deadline_days = self._safe_int(site_config.get("hr_deadline_days", 0), 0)
                    alert_info = self._calculate_alert_info(
                        seeding_time=seeding_time,
                        ratio=ratio,
                        time_requirement=time_requirement,
                        ratio_requirement=ratio_requirement,
                        hr_deadline_days=hr_deadline_days,
                        added_time=added_time,
                    )
                    
                    # 格式化添加时间
                    from datetime import datetime
                    added_time_str = "未知" if not added_time else datetime.fromtimestamp(added_time).strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"  格式化添加时间：{added_time_str}")
                    
                    # 添加种子信息
                    seed_info = {
                        "name": torrent_name,
                        "site": site_name,
                        "downloader": downloader_name,
                        "hash": torrent_hash,
                        "added_time": added_time_str,
                        "seeding_time": f"{seeding_time:.2f}小时",
                        "required_time": f"{time_requirement}小时",
                        "remaining_time": remaining_time_str,
                        "remaining_time_hours": remaining_time,
                        "current_ratio": f"{ratio:.2f}",
                        "required_ratio": f"{ratio_requirement}",
                        "ratio_status": ratio_status,
                        "state": state,
                        "alert_level": alert_info.get("alert_level"),
                        "alert_text": alert_info.get("alert_text"),
                        "progress_percent": alert_info.get("progress_percent"),
                        "priority_score": alert_info.get("priority_score"),
                        "priority_stars": alert_info.get("priority_stars"),
                        "remaining_deadline_days": alert_info.get("remaining_deadline_days"),
                    }
                    
                    all_hr_seeds.append(seed_info)
                    logger.info(f"  ✅ 种子 {torrent_name} 信息处理完成")
            
            # 按告警等级+优先级+剩余时间排序
            logger.info(f"✓ 所有HR种子处理完成，开始排序（共 {len(all_hr_seeds)} 个）")
            level_weight = {
                self.ALERT_TIMEOUT: 0,
                self.ALERT_URGENT: 1,
                self.ALERT_WARNING: 2,
                self.ALERT_NORMAL: 3,
            }
            all_hr_seeds.sort(
                key=lambda x: (
                    level_weight.get(x.get("alert_level"), 4),
                    -self._safe_float(x.get("priority_score"), 0.0),
                    self._safe_float(x.get("remaining_time_hours"), 999999.0),
                )
            )
            
            # 统计按站点分类的HR种子数量
            logger.info(f"✓ 开始统计HR种子站点分布")
            site_stats = {}
            for seed in all_hr_seeds:
                site = seed["site"]
                if site not in site_stats:
                    site_stats[site] = 0
                site_stats[site] += 1
            
            logger.info(f"✓ 站点分布统计完成：{site_stats}")
            
            # 填充返回数据
            hr_seeds_data["total_count"] = total_hr_seeds
            hr_seeds_data["seeds"] = all_hr_seeds
            hr_seeds_data["site_stats"] = site_stats
            
            # 日志总结
            logger.info("\n=== HR种子数据获取完成 ===")
            logger.info(f"✓ 总HR种子数量：{total_hr_seeds}")
            logger.info(f"✓ HR种子站点分布：{site_stats}")
            logger.info(f"✓ HR种子详情列表：{all_hr_seeds}")
            logger.info(f"✓ 返回给详情页的数据结构：{hr_seeds_data}")
        
        except Exception as e:
            logger.error(f"获取HR种子数据失败：{str(e)}", exc_info=True)
            logger.error("=== HR种子数据获取失败 ===")
        
        logger.info(f"✓ 最终返回的HR种子数据：{hr_seeds_data}")
        logger.info("=== HR种子数据获取流程结束 ===")
        return hr_seeds_data
