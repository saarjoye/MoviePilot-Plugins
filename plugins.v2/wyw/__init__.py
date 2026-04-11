import re
import threading
import time
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo
from app.utils.string import StringUtils
from app.db.transferhistory_oper import TransferHistoryOper

lock = threading.Lock()


class TorrentFileListRetriever:
    """种子文件列表获取器"""
    
    def __init__(self, downloader_helper: DownloaderHelper):
        self.downloader_helper = downloader_helper

    def _get_active_downloader_instance(self, downloader_name: str):
        """
        获取已连接的下载器实例（优先使用运行中的服务实例，避免新建实例导致未登录/未连接）
        """
        if not downloader_name:
            return None

        service_info = None
        try:
            services = self.downloader_helper.get_services(name_filters=[downloader_name])
            service_info = services.get(downloader_name) if services else None
        except Exception:
            service_info = None

        if not service_info:
            try:
                service_info = self.downloader_helper.get_service(downloader_name)
            except Exception:
                service_info = None

        downloader_instance = getattr(service_info, "instance", None) if service_info else None
        if not downloader_instance:
            return None

        # 跟插件主体一致：只使用已连接的下载器
        try:
            if hasattr(downloader_instance, "is_inactive") and downloader_instance.is_inactive():
                return None
        except Exception:
            # is_inactive 兜底失败时仍返回实例，让后续 get_files 自己报错
            pass

        return downloader_instance
    
    def get_torrent_files(self, download_hash: str, downloader: str = None) -> Tuple[List[str], str]:
        """
        获取种子文件列表
        Args:
            download_hash: 种子hash
            downloader: 指定下载器名称，如果为None则尝试所有下载器
        Returns:
            (file_list, error_message): 文件路径列表和错误信息
        """
        if not download_hash:
            return [], "种子hash为空"
        
        # 如果指定了下载器，只尝试该下载器
        if downloader:
            downloaders_to_try = [downloader]
        else:
            # 尝试所有配置的下载器
            downloaders_to_try = list(self.downloader_helper.get_configs().keys())
        
        for dl_name in downloaders_to_try:
            try:
                logger.debug(f"尝试从下载器 {dl_name} 获取种子 {download_hash[:8]}... 的文件列表")
                
                # 获取下载器实例（使用运行中的服务实例）
                downloader_instance = self._get_active_downloader_instance(dl_name)
                if not downloader_instance:
                    logger.debug(f"无法获取下载器 {dl_name} 的已连接实例")
                    continue
                
                # 先检查种子是否存在于下载器中
                try:
                    # 尝试获取种子信息来验证种子是否存在
                    if hasattr(downloader_instance, 'get_torrents'):
                        torrents, error = downloader_instance.get_torrents(ids=download_hash)
                        if error or not torrents:
                            logger.debug(f"种子 {download_hash[:8]}... 在下载器 {dl_name} 中不存在或已被删除")
                            continue
                        logger.debug(f"在下载器 {dl_name} 中找到种子 {download_hash[:8]}...")
                except Exception as e:
                    logger.debug(f"检查种子存在性时出错: {e}")
                
                # 获取种子文件列表
                files = downloader_instance.get_files(download_hash)
                if files is None:
                    logger.debug(f"从下载器 {dl_name} 获取种子文件列表失败 - 可能种子不存在或处于特殊状态")
                    continue
                
                # 处理不同下载器的文件列表格式
                file_paths = self._normalize_file_paths(files, dl_name)
                
                if file_paths:
                    logger.debug(f"成功从下载器 {dl_name} 获取到 {len(file_paths)} 个文件")
                    return file_paths, ""
                else:
                    logger.debug(f"从下载器 {dl_name} 获取的文件列表为空")
                    
            except Exception as e:
                logger.debug(f"从下载器 {dl_name} 获取种子文件列表时出错: {e}")
                continue
        
        # 所有下载器都失败了
        if len(downloaders_to_try) == 1:
            error_msg = f"无法从下载器 {downloaders_to_try[0]} 获取种子 {download_hash[:8]}... 的文件列表"
        else:
            error_msg = f"无法从任何下载器获取种子 {download_hash[:8]}... 的文件列表（尝试了 {len(downloaders_to_try)} 个下载器）"
        
        logger.debug(error_msg)  # 改为debug级别，减少日志噪音
        return [], error_msg
    
    def _normalize_file_paths(self, files, downloader_name: str) -> List[str]:
        """
        标准化不同下载器返回的文件路径格式，并过滤掉用户未选择下载的文件
        Args:
            files: 下载器返回的文件列表
            downloader_name: 下载器名称
        Returns:
            标准化的文件路径列表（仅包含实际下载的文件）
        """
        file_paths = []
        total_files = len(files) if files else 0
        skipped_files = 0

        try:
            is_qb = downloader_name.lower().startswith('qb') if downloader_name else False
            is_tr = downloader_name.lower().startswith('tr') if downloader_name else False
            if files and not is_qb and not is_tr:
                sample = files[0]
                if hasattr(sample, 'priority') or (isinstance(sample, dict) and 'priority' in sample):
                    is_qb = True
                elif hasattr(sample, 'wanted') or (isinstance(sample, dict) and 'wanted' in sample):
                    is_tr = True

            if is_qb:
                # qBittorrent返回TorrentFilesList
                # 调试：输出第一个文件对象的结构
                if files and len(files) > 0:
                    first_file = files[0]
                    logger.debug(f"qBittorrent文件对象示例: type={type(first_file)}, "
                               f"has_priority={hasattr(first_file, 'priority')}, "
                               f"has_name={hasattr(first_file, 'name')}")
                    if hasattr(first_file, 'priority'):
                        logger.debug(f"第一个文件priority值: {first_file.priority}")

                for file_info in files:
                    # 检查文件是否被选择下载
                    # qBittorrent优先级: 0=Ignored(不下载), 1=Normal, 6=High, 7=Maximum
                    priority = None
                    if hasattr(file_info, 'priority'):
                        priority = file_info.priority
                    elif isinstance(file_info, dict) and 'priority' in file_info:
                        priority = file_info['priority']

                    # 只处理实际下载的文件(priority > 0)
                    # 如果priority为None或<= 0,则跳过该文件
                    if priority is None:
                        skipped_files += 1
                        continue
                    try:
                        priority_val = int(priority)
                    except (ValueError, TypeError):
                        # 如果priority无法转换为整数,为安全起见跳过该文件
                        logger.warning(f"文件优先级值异常: {priority}, 跳过该文件")
                        skipped_files += 1
                        continue
                    if priority_val not in (1, 6, 7):
                        skipped_files += 1
                        continue

                    # qBittorrent文件对象有name属性
                    if hasattr(file_info, 'name'):
                        file_paths.append(file_info.name)
                    elif isinstance(file_info, dict) and 'name' in file_info:
                        file_paths.append(file_info['name'])

            elif is_tr:
                # Transmission返回List[File]
                for file_info in files:
                    # 检查文件是否被选择下载（wanted = true表示下载）
                    wanted = None
                    if hasattr(file_info, 'wanted'):
                        wanted = file_info.wanted
                    elif isinstance(file_info, dict) and 'wanted' in file_info:
                        wanted = file_info['wanted']

                    # 只处理实际下载的文件（wanted = true）
                    # 如果wanted不为True,则跳过该文件
                    if wanted is not True:
                        skipped_files += 1
                        continue

                    # Transmission文件对象有name属性
                    if hasattr(file_info, 'name'):
                        file_paths.append(file_info.name)
                    elif isinstance(file_info, dict) and 'name' in file_info:
                        file_paths.append(file_info['name'])
            else:
                # 通用处理：尝试提取name属性或直接使用字符串
                for file_info in files:
                    if hasattr(file_info, 'name'):
                        file_paths.append(file_info.name)
                    elif isinstance(file_info, dict) and 'name' in file_info:
                        file_paths.append(file_info['name'])
                    elif isinstance(file_info, str):
                        file_paths.append(file_info)

        except Exception as e:
            logger.error(f"标准化下载器 {downloader_name} 文件路径时出错: {e}")
            return []

        # 过滤空路径并标准化路径分隔符
        normalized_paths = []
        for path in file_paths:
            if path and isinstance(path, str):
                # 统一使用正斜杠作为路径分隔符
                normalized_path = path.replace('\\', '/')
                normalized_paths.append(normalized_path)

        # 输出文件过滤统计信息（强制使用info级别）
        if skipped_files > 0:
            logger.info(f"下载器 {downloader_name} 文件过滤: 总文件数={total_files}, 实际下载={len(normalized_paths)}, 跳过未下载={skipped_files}")
        else:
            logger.info(f"下载器 {downloader_name} 文件统计: 总文件数={total_files}, 实际下载={len(normalized_paths)}, 跳过未下载=0")

        return normalized_paths


class FileTransferMatcher:
    """文件整理状态匹配器"""
    
    def __init__(self):
        pass
    
    def match_files_with_records(self, torrent_files: List[str], 
                                transfer_records: List) -> Dict[str, bool]:
        """
        匹配种子文件与整理记录
        Args:
            torrent_files: 种子文件路径列表
            transfer_records: 整理记录列表
        Returns:
            {file_path: is_transferred}: 文件路径到是否已整理的映射
        """
        if not torrent_files:
            return {}
        
        # 从成功整理记录中提取“可用于匹配的源文件路径”
        # 说明：MP 的 TransferHistory 可能一条记录里包含多个文件（record.files）
        success_src_paths = self._extract_success_src_paths(transfer_records)
        logger.debug(f"从成功整理记录中提取到 {len(success_src_paths)} 个可匹配源路径")

        # 为了避免“1条成功记录匹配多个文件”的误判，这里做一对一匹配：
        # 每个种子文件必须匹配到一条未被占用的成功整理记录。
        return self._unique_match(torrent_files, success_src_paths)

    def _extract_success_src_paths(self, transfer_records: List) -> List[str]:
        """
        提取成功整理记录中的源文件路径集合（用于与种子文件列表匹配）
        """
        if not transfer_records:
            return []

        extracted: List[str] = []
        seen = set()

        def _add(path_value: Any):
            if not path_value or not isinstance(path_value, str):
                return
            key = path_value.strip()
            if not key or key in seen:
                return
            seen.add(key)
            extracted.append(key)

        for record in transfer_records:
            try:
                if not record or not getattr(record, "status", False):
                    continue

                # 1) 主源路径（最常见）
                _add(getattr(record, "src", None))

                # 2) src_fileitem 里也可能带 path（冗余但稳妥）
                src_fileitem = getattr(record, "src_fileitem", None)
                if isinstance(src_fileitem, dict):
                    _add(src_fileitem.get("path"))

                # 3) files 字段：可能包含多个源文件（list[str] 或 list[dict]）
                files_field = getattr(record, "files", None)
                if isinstance(files_field, list):
                    for item in files_field:
                        if isinstance(item, str):
                            _add(item)
                        elif isinstance(item, dict):
                            _add(item.get("path"))
            except Exception:
                continue

        return extracted

    def _unique_match(self, torrent_files: List[str], success_src_paths: List[str]) -> Dict[str, bool]:
        """
        一对一匹配：每个 torrent_file 必须匹配到一条唯一的成功整理记录 src
        """
        if not torrent_files:
            return {}

        # 先按路径长短（更具体）排序，优先用“后缀路径匹配”解决同名不同目录的情况
        normalized_files = [(f, self._normalize_path(f)) for f in torrent_files]
        normalized_files.sort(key=lambda x: len(x[1] or ""), reverse=True)

        # 预处理成功记录
        normalized_srcs = []
        for src in success_src_paths:
            norm_src = self._normalize_path(src)
            if norm_src:
                normalized_srcs.append((src, norm_src))

        used_src_indices = set()
        match_result: Dict[str, bool] = {f: False for f in torrent_files}

        import posixpath

        for original_file, norm_file in normalized_files:
            if not norm_file:
                continue

            file_basename = posixpath.basename(norm_file)
            if not file_basename:
                continue

            # 1) 优先“后缀路径匹配”：成功记录 src 以 torrent 内相对路径结尾
            matched_index = None
            for idx, (_, norm_src) in enumerate(normalized_srcs):
                if idx in used_src_indices:
                    continue
                if norm_src.endswith(norm_file):
                    matched_index = idx
                    break

            # 2) 回退到“文件名匹配”：要求 basename 完全一致（确保每个文件都有对应记录）
            if matched_index is None:
                for idx, (_, norm_src) in enumerate(normalized_srcs):
                    if idx in used_src_indices:
                        continue
                    if posixpath.basename(norm_src) == file_basename:
                        matched_index = idx
                        break

            # 3) 再回退到“集数匹配”：当同一剧集存在不同版本/不同发布组时，文件名不同但 SxxEyy 一致
            if matched_index is None:
                file_se = self._extract_se_from_name(file_basename)
                if file_se:
                    for idx, (_, norm_src) in enumerate(normalized_srcs):
                        if idx in used_src_indices:
                            continue
                        src_se = self._extract_se_from_name(posixpath.basename(norm_src))
                        if src_se and src_se == file_se:
                            matched_index = idx
                            break

            if matched_index is not None:
                used_src_indices.add(matched_index)
                match_result[original_file] = True

        return match_result

    def _extract_se_from_name(self, filename: str) -> Optional[Tuple[int, int]]:
        """
        从文件名中提取 (season, episode)，用于同剧集不同版本的回退匹配
        """
        if not filename:
            return None
        m_season = re.search(r"(?i)s(\d{1,2})", filename)
        if not m_season:
            return None
        m_episode = re.search(r"(?i)e(\d{1,3})", filename)
        if not m_episode:
            return None
        try:
            season = int(m_season.group(1))
            episode = int(m_episode.group(1))
            return season, episode
        except Exception:
            return None
    
    def _match_single_file(self, torrent_file: str, success_src_paths: List[str]) -> bool:
        """
        匹配单个种子文件是否已成功整理
        Args:
            torrent_file: 种子文件路径
            success_src_paths: 成功整理记录的源路径列表
        Returns:
            是否匹配到成功整理记录
        """
        if not torrent_file or not success_src_paths:
            return False
        
        # 标准化种子文件路径
        normalized_torrent_file = self._normalize_path(torrent_file)
        
        for src_path in success_src_paths:
            if not src_path:
                continue
                
            # 标准化整理记录源路径
            normalized_src_path = self._normalize_path(src_path)
            
            # 尝试多种匹配策略
            if self._exact_match(normalized_torrent_file, normalized_src_path):
                logger.debug(f"精确匹配: {torrent_file} <-> {src_path}")
                return True
            
            if self._filename_match(normalized_torrent_file, normalized_src_path):
                logger.debug(f"文件名匹配: {torrent_file} <-> {src_path}")
                return True
            
            if self._path_contains_match(normalized_torrent_file, normalized_src_path):
                logger.debug(f"路径包含匹配: {torrent_file} <-> {src_path}")
                return True
        
        return False
    
    def _normalize_path(self, path: str) -> str:
        """
        标准化路径格式
        Args:
            path: 原始路径
        Returns:
            标准化后的路径
        """
        if not path:
            return ""
        
        # 统一路径分隔符为正斜杠
        normalized = path.replace('\\', '/')
        
        # 移除开头的路径分隔符
        normalized = normalized.lstrip('/')
        
        # 转换为小写以便比较（处理大小写不敏感的文件系统）
        normalized = normalized.lower()
        
        return normalized
    
    def _exact_match(self, torrent_file: str, src_path: str) -> bool:
        """
        精确路径匹配
        """
        return torrent_file == src_path
    
    def _filename_match(self, torrent_file: str, src_path: str) -> bool:
        """
        文件名匹配（忽略路径）
        """
        import os
        torrent_filename = os.path.basename(torrent_file)
        src_filename = os.path.basename(src_path)
        return torrent_filename == src_filename and torrent_filename != ""
    
    def _path_contains_match(self, torrent_file: str, src_path: str) -> bool:
        """
        路径包含匹配（检查源路径是否包含种子文件路径）
        """
        # 检查源路径是否以种子文件路径结尾
        if src_path.endswith(torrent_file):
            return True
        
        # 检查种子文件路径是否包含在源路径中
        if torrent_file in src_path:
            return True
        
        return False


class TransferRecordChecker:
    """媒体整理记录检查器"""
    
    def __init__(self, enabled: bool = True, timeout: int = 5, fail_open: bool = False):
        self.enabled = enabled
        self.timeout = timeout
        self.fail_open = fail_open
        self.transfer_oper = None
        self.file_retriever = None
        self.file_matcher = None
        
        if enabled:
            try:
                self.transfer_oper = TransferHistoryOper()
                # 初始化新的组件
                self.file_retriever = TorrentFileListRetriever(DownloaderHelper())
                self.file_matcher = FileTransferMatcher()
                logger.info("媒体整理记录检查器初始化成功")
            except Exception as e:
                logger.error(f"媒体整理记录检查器初始化失败: {e}")
                self.enabled = False
    
    def _run_with_timeout(self, func, *args, default: bool = False) -> bool:
        """以可配置超时执行检查，超时/异常时返回默认值"""
        try:
            timeout = float(self.timeout)
        except (TypeError, ValueError):
            timeout = 0

        if timeout <= 0:
            return func(*args)

        result_holder = {"ok": False, "value": default, "error": None}

        def _runner():
            try:
                result_holder["value"] = func(*args)
            except Exception as exc:
                result_holder["error"] = exc
            finally:
                result_holder["ok"] = True

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join(timeout=timeout)

        if worker.is_alive():
            logger.warning(f"媒体整理记录检查超时（{timeout}s），按{'放行' if default else '阻断'}策略处理")
            return default

        if result_holder["error"] is not None:
            logger.error(f"媒体整理记录检查执行异常: {result_holder['error']}")
            return default

        return result_holder["value"]

    def check_transfer_record(self, download_hash: str, torrent_name: str = "",
                              downloader: str = None) -> bool:
        """检查种子是否有成功的媒体整理记录"""
        if not self.enabled or not self.transfer_oper:
            logger.info("媒体整理记录检查功能未启用，跳过检查")
            return True

        if not download_hash:
            logger.info(f"种子 [{torrent_name}] hash为空，跳过媒体整理记录检查")
            return False

        return self._run_with_timeout(
            self._check_transfer_record_internal,
            download_hash,
            torrent_name,
            downloader,
            default=self.fail_open
        )

    def _check_transfer_record_internal(self, download_hash: str, torrent_name: str,
                                        downloader: str = None) -> bool:
        try:
            logger.info(f"正在检查种子 [{torrent_name}] (hash: {download_hash[:8]}...) 的媒体整理记录")

            # 查询该hash对应的所有转移记录（兼容大小写差异）
            transfer_records = self._list_records_by_hash(download_hash)
            if not transfer_records:
                logger.info(f"✗ 种子 [{torrent_name}] 不存在任何媒体整理记录，跳过删种")
                return False

            # 尝试使用增强检查逻辑
            try:
                passed = self._check_all_files_transferred(download_hash, torrent_name,
                                                           downloader, transfer_records)
                if passed:
                    return True

                # 回退扩展：有些整理记录未写入/写错 download_hash，导致按hash查询不全
                expanded_records = self._expand_records_by_title(torrent_name, transfer_records)
                if expanded_records is not transfer_records:
                    logger.info(
                        f"种子 [{torrent_name}] 按hash记录不足，已扩展到 {len(expanded_records)} 条记录后重新校验"
                    )
                    return self._check_all_files_transferred(download_hash, torrent_name,
                                                             downloader, expanded_records)
                return False
            except Exception as e:
                logger.warning(f"增强检查逻辑失败，回退到原始逻辑: {e}")
                return self._fallback_check(transfer_records, torrent_name)

        except Exception as e:
            logger.error(f"检查种子 [{torrent_name}] 的媒体整理记录时发生错误: {e}")
            logger.warning(
                f"因数据库查询异常，种子 [{torrent_name}] 将按{'放行' if self.fail_open else '阻断'}策略处理"
            )
            return self.fail_open

    def _list_records_by_hash(self, download_hash: str) -> List:
        """
        按 hash 查询整理记录（兼容大小写差异并去重）
        """
        transfer_records = []
        for h in {download_hash, download_hash.lower(), download_hash.upper()}:
            try:
                records = self.transfer_oper.list_by_hash(h)
                if records:
                    transfer_records.extend(records)
            except Exception:
                continue
        return self._dedupe_records(transfer_records)

    def _dedupe_records(self, records: List) -> List:
        """
        对整理记录去重（优先按 id）
        """
        if not records:
            return []
        uniq = {}
        for r in records:
            rid = getattr(r, "id", None)
            if rid is not None:
                uniq[rid] = r
            else:
                key = (getattr(r, "src", None), getattr(r, "dest", None), getattr(r, "date", None))
                uniq[key] = r
        return list(uniq.values())

    def _expand_records_by_title(self, torrent_name: str, existing_records: List) -> List:
        """
        当按 hash 查询不到足够记录时，按标题关键字扩展查询（仍然会走逐文件匹配，保证安全）
        """
        if not torrent_name or not self.transfer_oper:
            return existing_records

        keywords = self._derive_title_keywords(torrent_name)
        if not keywords:
            return existing_records

        extra_records: List = []
        for kw in keywords:
            try:
                records = self.transfer_oper.get_by_title(kw)
                if records:
                    extra_records.extend(records)
            except Exception:
                continue

        if not extra_records:
            return existing_records

        merged = list(existing_records) + extra_records
        merged = self._dedupe_records(merged)
        return merged if len(merged) > len(existing_records) else existing_records

    def _derive_title_keywords(self, torrent_name: str) -> List[str]:
        """
        从种子名称提取用于模糊查询的标题关键字（优先中文，其次英文/数字）
        """
        name = (torrent_name or "").strip()
        if not name:
            return []

        # 去掉常见的方括号包裹信息
        name = re.sub(r"\[.*?]", "", name).strip()

        keywords: List[str] = []

        # 1) 取开头连续中文（>=2）
        m = re.match(r"^([\u4e00-\u9fff]{2,})", name)
        if m:
            keywords.append(m.group(1))

        # 2) 取 Sxx 之前的英文/数字片段（避免把分辨率等带进去）
        # 例如：小城大事.The.Dream.Maker.S01.2026... -> The Dream Maker
        parts = re.split(r"[.\s]+", name)
        cleaned = []
        for p in parts:
            if not p:
                continue
            if re.match(r"^S\d{1,2}$", p, re.IGNORECASE):
                break
            if re.match(r"^(19|20)\d{2}$", p):
                break
            cleaned.append(p)
        # 跳过第一个（通常是中文名），保留后面的英文名
        if len(cleaned) >= 2:
            eng = " ".join([c for c in cleaned[1:] if re.search(r"[a-zA-Z0-9]", c)])
            eng = eng.strip()
            if len(eng) >= 4:
                keywords.append(eng)

        # 去重并限制数量，避免LIKE过宽
        uniq = []
        seen = set()
        for k in keywords:
            kk = k.strip()
            if kk and kk not in seen:
                seen.add(kk)
                uniq.append(kk)
        return uniq[:2]
    
    def _check_all_files_transferred(self, download_hash: str, torrent_name: str, 
                                   downloader: str, transfer_records: List) -> bool:
        """
        检查种子中所有文件是否都已成功整理
        """
        # 获取种子文件列表
        torrent_files, error_msg = self.file_retriever.get_torrent_files(download_hash, downloader)
        
        if error_msg:
            logger.warning(f"获取种子 [{torrent_name}] 文件列表失败: {error_msg}")
            # 无法获取文件列表时，无法确认“每个文件都有成功整理记录”，为避免误删直接跳过
            logger.info(f"✗ 种子 [{torrent_name}] 无法获取文件列表，跳过删种")
            return False
        
        if not torrent_files:
            logger.warning(f"种子 [{torrent_name}] 文件列表为空")
            logger.info(f"✗ 种子 [{torrent_name}] 文件列表为空，跳过删种")
            return False
        
        logger.info(f"种子 [{torrent_name}] 包含 {len(torrent_files)} 个文件")

        # 仅对 MP 可能会整理的文件类型做校验（媒体/字幕/音轨），避免把 NFO/JPG/样例等文件计入导致误判
        relevant_files = self._filter_relevant_torrent_files(torrent_files)
        if not relevant_files:
            logger.info(f"✗ 种子 [{torrent_name}] 未发现可整理的媒体/字幕/音轨文件，跳过删种")
            return False
        if len(relevant_files) != len(torrent_files):
            logger.info(f"种子 [{torrent_name}] 过滤后需校验 {len(relevant_files)} 个媒体/字幕/音轨文件")

        # 先做数量层面的硬性校验：成功整理记录中可提取的“源文件路径数量”必须 >= 待校验文件数
        success_src_paths = self.file_matcher._extract_success_src_paths(transfer_records)
        normalized_success_srcs = {
            self.file_matcher._normalize_path(p) for p in success_src_paths if isinstance(p, str) and p
        }
        if len(normalized_success_srcs) < len(relevant_files):
            logger.info(
                f"✗ 种子 [{torrent_name}] 需要至少 {len(relevant_files)} 个成功整理文件匹配，但仅找到 {len(normalized_success_srcs)} 个，跳过删种"
            )
            return False
        
        # 匹配种子文件与整理记录
        match_result = self.file_matcher.match_files_with_records(relevant_files, transfer_records)
        
        # 统计匹配结果
        total_files = len(relevant_files)
        transferred_files = sum(1 for is_transferred in match_result.values() if is_transferred)
        untransferred_files = [file_path for file_path, is_transferred in match_result.items() 
                              if not is_transferred]
        
        logger.info(f"种子 [{torrent_name}] 文件整理状态: {transferred_files}/{total_files} 已整理")
        
        if untransferred_files:
            logger.info(f"✗ 种子 [{torrent_name}] 存在 {len(untransferred_files)} 个未整理文件，跳过删种")
            # 显示未整理的文件（最多显示5个）
            for i, file_path in enumerate(untransferred_files[:5]):
                logger.info(f"  未整理文件{i+1}: {file_path}")
            if len(untransferred_files) > 5:
                logger.info(f"  ... 还有 {len(untransferred_files) - 5} 个未整理文件")
            return False
        else:
            logger.info(f"✓ 种子 [{torrent_name}] 所有文件都已成功整理，允许删种")
            # 显示已整理的文件信息（最多显示3个）
            transferred_file_list = [file_path for file_path, is_transferred in match_result.items() 
                                   if is_transferred]
            for i, file_path in enumerate(transferred_file_list[:3]):
                logger.info(f"  已整理文件{i+1}: {file_path}")
            if len(transferred_file_list) > 3:
                logger.info(f"  ... 还有 {len(transferred_file_list) - 3} 个已整理文件")
            return True

    def _filter_relevant_torrent_files(self, torrent_files: List[str]) -> List[str]:
        """
        过滤出 MP 可能会整理的文件（媒体/字幕/音轨），避免把非整理文件计入导致误判
        """
        if not torrent_files:
            return []

        import posixpath

        allowed_exts = set()
        try:
            allowed_exts.update([ext.lower() for ext in (getattr(settings, "RMT_MEDIAEXT", []) or [])])
            allowed_exts.update([ext.lower() for ext in (getattr(settings, "RMT_SUBEXT", []) or [])])
            allowed_exts.update([ext.lower() for ext in (getattr(settings, "RMT_AUDIO_TRACK_EXT", []) or [])])
        except Exception:
            allowed_exts = set([ext.lower() for ext in (settings.RMT_MEDIAEXT or [])]) if getattr(settings, "RMT_MEDIAEXT", None) else set()

        relevant = []
        for f in torrent_files:
            if not f or not isinstance(f, str):
                continue
            _, ext = posixpath.splitext(f)
            if ext and ext.lower() in allowed_exts:
                relevant.append(f)
        return relevant
    
    def _fallback_check(self, transfer_records: List, torrent_name: str) -> bool:
        """
        回退到原始检查逻辑
        """
        logger.info(f"对种子 [{torrent_name}] 使用原始检查逻辑")
        success_records = [record for record in transfer_records if record.status == 1]
        
        if success_records:
            logger.info(f"✓ 种子 [{torrent_name}] 存在 {len(success_records)} 条成功的媒体整理记录，允许删种")
            # 显示成功记录的详细信息
            for i, record in enumerate(success_records[:3]):  # 最多显示3条记录
                logger.info(f"  记录{i+1}: {record.src} => {record.dest}")
            if len(success_records) > 3:
                logger.info(f"  ... 还有 {len(success_records) - 3} 条记录")
            return True
        else:
            total_records = len(transfer_records)
            if total_records > 0:
                logger.info(f"✗ 种子 [{torrent_name}] 存在 {total_records} 条整理记录但均为失败状态，跳过删种")
                # 显示失败记录的错误信息
                for i, record in enumerate(transfer_records[:2]):  # 最多显示2条失败记录
                    if record.errmsg:
                        logger.info(f"  失败记录{i+1}: {record.errmsg}")
            else:
                logger.info(f"✗ 种子 [{torrent_name}] 不存在任何媒体整理记录，跳过删种")
            return False
    
    def is_enabled(self) -> bool:
        """检查功能是否启用"""
        return self.enabled


class wYw(_PluginBase):
    # 插件名称
    plugin_name = "自动删种115版"
    # 插件描述
    plugin_desc = "自动删除下载器中的下载任务。"
    # 插件图标
    plugin_icon = "delete.jpg"
    # 插件版本
    plugin_version = "2.5"
    # 插件作者
    plugin_author = "wYw"
    # 作者主页
    author_url = "https://github.com/saarjoye/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "wyw_"
    # 加载顺序
    plugin_order = 8
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _event = threading.Event()
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _notify = False
    # pause/delete
    _downloaders = []
    _action = "pause"
    _cron = None
    _samedata = False
    _mponly = False
    _size = None
    _ratio = None
    _time = None
    _upspeed = None
    _labels = None
    _pathkeywords = None
    _trackerkeywords = None
    _errorkeywords = None
    _torrentstates = None
    _torrentcategorys = None
    # 新增配置项
    _check_transfer_record = True
    _transfer_check_timeout = 5
    _transfer_fail_open = False
    
    # 媒体整理记录检查器
    _transfer_checker = None

    def init_plugin(self, config: dict = None):

        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._downloaders = config.get("downloaders") or []
            self._action = config.get("action")
            self._cron = config.get("cron")
            self._samedata = config.get("samedata")
            self._mponly = config.get("mponly")
            self._size = config.get("size") or ""
            self._ratio = config.get("ratio")
            self._time = config.get("time")
            self._upspeed = config.get("upspeed")
            self._labels = config.get("labels") or ""
            self._pathkeywords = config.get("pathkeywords") or ""
            self._trackerkeywords = config.get("trackerkeywords") or ""
            self._errorkeywords = config.get("errorkeywords") or ""
            self._torrentstates = config.get("torrentstates") or ""
            self._torrentcategorys = config.get("torrentcategorys") or ""
            # 新增配置项处理
            self._check_transfer_record = config.get("check_transfer_record", True)
            self._transfer_fail_open = config.get("transfer_fail_open", False)
            timeout_config = config.get("transfer_check_timeout", 5)
            try:
                self._transfer_check_timeout = max(1, int(float(timeout_config)))
            except (TypeError, ValueError):
                self._transfer_check_timeout = 5

        # 初始化媒体整理记录检查器
        self._transfer_checker = TransferRecordChecker(
            enabled=self._check_transfer_record,
            timeout=self._transfer_check_timeout,
            fail_open=self._transfer_fail_open
        )
        
        # 记录配置状态
        if self._check_transfer_record:
            logger.info("自动删种插件：媒体整理记录检查功能已启用")
        else:
            logger.info("自动删种插件：媒体整理记录检查功能已禁用")

        self.stop_service()

        if self.get_state() or self._onlyonce:
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"自动删种服务启动，立即运行一次")
                self._scheduler.add_job(func=self.delete_torrents, trigger='date',
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False
                # 保存设置
                self.update_config({
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                    "action": self._action,
                    "cron": self._cron,
                    "downloaders": self._downloaders,
                    "samedata": self._samedata,
                    "mponly": self._mponly,
                    "size": self._size,
                    "ratio": self._ratio,
                    "time": self._time,
                    "upspeed": self._upspeed,
                    "labels": self._labels,
                    "pathkeywords": self._pathkeywords,
                    "trackerkeywords": self._trackerkeywords,
                    "errorkeywords": self._errorkeywords,
                    "torrentstates": self._torrentstates,
                    "torrentcategorys": self._torrentcategorys,
                    "check_transfer_record": self._check_transfer_record,
                    "transfer_check_timeout": self._transfer_check_timeout,
                    "transfer_fail_open": self._transfer_fail_open

                })
                if self._scheduler.get_jobs():
                    # 启动服务
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return True if self._enabled and self._cron and self._downloaders else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self.get_state():
            return [{
                "id": "wyw",
                "name": "自动删种服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.delete_torrents,
                "kwargs": {}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
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
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 */12 * * *'
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'action',
                                            'label': '动作',
                                            'items': [
                                                {'title': '暂停', 'value': 'pause'},
                                                {'title': '删除种子', 'value': 'delete'},
                                                {'title': '删除种子和文件', 'value': 'deletefile'}
                                            ]
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in DownloaderHelper().get_configs().values()]
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
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size',
                                            'label': '种子大小（GB）',
                                            'placeholder': '例如1-10'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'ratio',
                                            'label': '分享率',
                                            'placeholder': ''
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'time',
                                            'label': '做种时间（小时）',
                                            'placeholder': ''
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'upspeed',
                                            'label': '平均上传速度',
                                            'placeholder': ''
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'labels',
                                            'label': '标签',
                                            'placeholder': '用,分隔多个标签'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pathkeywords',
                                            'label': '保存路径关键词',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'trackerkeywords',
                                            'label': 'Tracker关键词',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'errorkeywords',
                                            'label': '错误信息关键词（TR）',
                                            'placeholder': '支持正式表达式，仅适用于TR'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'torrentstates',
                                            'label': '任务状态（QB）',
                                            'placeholder': '用,分隔多个状态，仅适用于QB'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'torrentcategorys',
                                            'label': '任务分类',
                                            'placeholder': '用,分隔多个分类'
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'samedata',
                                            'label': '处理辅种',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'mponly',
                                            'label': '仅MoviePilot任务',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'check_transfer_record',
                                            'label': '检查媒体整理记录',
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
                                            'model': 'transfer_check_timeout',
                                            'label': '数据库查询超时（秒）',
                                            'placeholder': '5',
                                            'type': 'number'
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
                                            'model': 'transfer_fail_open',
                                            'label': '检查异常时放行删种',
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
                                            'text': '媒体整理记录检查：启用后，只有在MoviePilot中存在成功整理记录的种子才会被删除。可通过“检查异常时放行删种”控制异常策略。'
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
                                            'text': '自动删种存在风险，如设置不当可能导致数据丢失！建议动作先选择暂停，确定条件正确后再改成删除。'
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
                                            'text': '任务状态（QB）字典：'
                                                    'downloading：正在下载-传输数据，'
                                                    'stalledDL：正在下载_未建立连接，'
                                                    'uploading：正在上传-传输数据，'
                                                    'stalledUP：正在上传-未建立连接，'
                                                    'error：暂停-发生错误，'
                                                    'pausedDL：暂停-下载未完成，'
                                                    'pausedUP：暂停-下载完成，'
                                                    'missingFiles：暂停-文件丢失，'
                                                    'checkingDL：检查中-下载未完成，'
                                                    'checkingUP：检查中-下载完成，'
                                                    'checkingResumeData：检查中-启动时恢复数据，'
                                                    'forcedDL：强制下载-忽略队列，'
                                                    'queuedDL：等待下载-排队，'
                                                    'forcedUP：强制上传-忽略队列，'
                                                    'queuedUP：等待上传-排队，'
                                                    'allocating：分配磁盘空间，'
                                                    'metaDL：获取元数据，'
                                                    'moving：移动文件，'
                                                    'unknown：未知状态'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "action": 'pause',
            'downloaders': [],
            "cron": '0 */12 * * *',
            "samedata": False,
            "mponly": False,
            "size": "",
            "ratio": "",
            "time": "",
            "upspeed": "",
            "labels": "",
            "pathkeywords": "",
            "trackerkeywords": "",
            "errorkeywords": "",
            "torrentstates": "",
            "torrentcategorys": "",
            "check_transfer_record": True,
            "transfer_check_timeout": 5,
            "transfer_fail_open": False
        }

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._downloaders:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = DownloaderHelper().get_services(name_filters=self._downloaders)
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    def __get_downloader(self, name: str):
        """
        根据类型返回下载器实例
        """
        return self.service_infos.get(name).instance

    def __get_downloader_config(self, name: str):
        """
        根据类型返回下载器实例配置
        """
        return self.service_infos.get(name).config

    def delete_torrents(self):
        """
        定时删除下载器中的下载任务
        """
        logger.info("=== 自动删种任务开始执行 ===")
        for downloader in self._downloaders:
            try:
                with lock:
                    logger.info(f"开始处理下载器: {downloader}")
                    # 获取需删除种子列表
                    torrents = self.get_remove_torrents(downloader)
                    logger.info(f"下载器 {downloader} 最终符合删种条件的种子数: {len(torrents)}")
                    
                    if not torrents:
                        logger.info(f"下载器 {downloader} 没有符合删种条件的种子")
                        continue
                    
                    # 下载器
                    downlader_obj = self.__get_downloader(downloader)
                    if self._action == "pause":
                        message_text = f"{downloader.title()} 共暂停{len(torrents)}个种子"
                        for torrent in torrents:
                            if self._event.is_set():
                                logger.info(f"自动删种服务停止")
                                return
                            text_item = f"{torrent.get('name')} " \
                                        f"来自站点：{torrent.get('site')} " \
                                        f"大小：{StringUtils.str_filesize(torrent.get('size'))}"
                            # 暂停种子
                            downlader_obj.stop_torrents(ids=[torrent.get("id")])
                            logger.info(f"自动删种任务 暂停种子：{text_item}")
                            message_text = f"{message_text}\n{text_item}"
                    elif self._action == "delete":
                        message_text = f"{downloader.title()} 共删除{len(torrents)}个种子"
                        for torrent in torrents:
                            if self._event.is_set():
                                logger.info(f"自动删种服务停止")
                                return
                            text_item = f"{torrent.get('name')} " \
                                        f"来自站点：{torrent.get('site')} " \
                                        f"大小：{StringUtils.str_filesize(torrent.get('size'))}"
                            # 删除种子
                            downlader_obj.delete_torrents(delete_file=False,
                                                          ids=[torrent.get("id")])
                            logger.info(f"自动删种任务 删除种子：{text_item}")
                            message_text = f"{message_text}\n{text_item}"
                    elif self._action == "deletefile":
                        message_text = f"{downloader.title()} 共删除{len(torrents)}个种子及文件"
                        for torrent in torrents:
                            if self._event.is_set():
                                logger.info(f"自动删种服务停止")
                                return
                            text_item = f"{torrent.get('name')} " \
                                        f"来自站点：{torrent.get('site')} " \
                                        f"大小：{StringUtils.str_filesize(torrent.get('size'))}"
                            # 删除种子
                            downlader_obj.delete_torrents(delete_file=True,
                                                          ids=[torrent.get("id")])
                            logger.info(f"自动删种任务 删除种子及文件：{text_item}")
                            message_text = f"{message_text}\n{text_item}"
                    else:
                        continue
                    if torrents and message_text and self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title=f"【自动删种任务完成】",
                            text=message_text
                        )
            except Exception as e:
                logger.error(f"自动删种任务异常：{str(e)}")
        logger.info("=== 自动删种任务执行完成 ===")

    def get_remove_torrents(self, downloader: str):
        """
        获取自动删种任务种子
        """
        remove_torrents = []
        # 下载器对象
        downloader_obj = self.__get_downloader(downloader)
        downloader_config = self.__get_downloader_config(downloader)
        # 标题
        if self._labels:
            tags = [t.strip() for t in self._labels.split(',') if str(t).strip()]
        else:
            tags = []
        if self._mponly:
            tags.append(settings.TORRENT_TAG)
        # 去重（保持顺序），并做规范化（去空/去重）
        if tags:
            uniq_tags = []
            seen = set()
            for t in tags:
                tt = str(t).strip()
                if not tt:
                    continue
                key = tt.lower()
                if key in seen:
                    continue
                seen.add(key)
                uniq_tags.append(tt)
            tags = uniq_tags
        if tags:
            logger.info(f"下载器 {downloader} 获取种子使用标签过滤: {tags}")
        else:
            logger.info(f"下载器 {downloader} 获取种子不使用标签过滤")
        # 查询种子
        torrents, error_flag = downloader_obj.get_torrents(tags=tags or None)
        if error_flag:
            return []

        # 某些下载器实现对 tags 过滤不可靠：若返回0，尝试改为“拉全量后本地过滤”并输出少量诊断信息
        if tags and not torrents:
            logger.warning(f"下载器 {downloader} 按标签过滤后返回 0 个种子，尝试不带标签获取后本地过滤")
            all_torrents, err2 = downloader_obj.get_torrents(tags=None)
            if not err2 and all_torrents:
                def _extract_tags(t) -> List[str]:
                    try:
                        if downloader_config.type == "qbittorrent":
                            raw = ""
                            try:
                                raw = t.get("tags") if hasattr(t, "get") else ""
                            except Exception:
                                raw = ""
                            raw = raw or getattr(t, "tags", "") or ""
                            return [x.strip() for x in str(raw).split(",") if x and str(x).strip()]
                        labels = getattr(t, "labels", None) or []
                        return [str(x).strip() for x in labels if x and str(x).strip()]
                    except Exception:
                        return []

                want = {str(x).strip().lower() for x in tags if x and str(x).strip()}
                filtered = []
                for tor in all_torrents:
                    tor_tags = {x.lower() for x in _extract_tags(tor)}
                    if want.issubset(tor_tags):
                        filtered.append(tor)
                torrents = filtered

                sample = []
                for tor in all_torrents[:5]:
                    try:
                        name = getattr(tor, "name", None) or (tor.get("name") if hasattr(tor, "get") else "")
                        sample.append(f"{name} tags={_extract_tags(tor)}")
                    except Exception:
                        continue
                if sample:
                    logger.info(f"下载器 {downloader} 标签诊断示例(前5): " + " | ".join(sample))
            elif err2:
                logger.warning(f"下载器 {downloader} 不带标签获取种子失败，无法进行本地过滤")

        # 统计信息
        total_torrents = len(torrents)
        transfer_check_passed = 0
        transfer_check_failed = 0
        condition_check_passed = 0
        
        logger.info(f"下载器 {downloader} 共获取到 {total_torrents} 个种子")
        logger.info(f"媒体整理记录检查功能: {'已启用' if self._transfer_checker.is_enabled() else '已禁用'}")
        
        # 处理种子
        for torrent in torrents:
            # 获取种子hash和名称
            if downloader_config.type == "qbittorrent":
                torrent_hash = torrent.hash
                torrent_name = torrent.name
            else:
                torrent_hash = torrent.hashString
                torrent_name = torrent.name
            
            # 媒体整理记录检查
            if self._transfer_checker.is_enabled():
                if not self._transfer_checker.check_transfer_record(torrent_hash, torrent_name, downloader):
                    transfer_check_failed += 1
                    continue
                else:
                    transfer_check_passed += 1
            
            # 原有的删种条件检查
            if downloader_config.type == "qbittorrent":
                item = self.__get_qb_torrent(torrent)
            else:
                item = self.__get_tr_torrent(torrent)
            if not item:
                logger.debug(f"种子 [{torrent_name}] 不符合删种条件，跳过")
                continue
            
            condition_check_passed += 1
            logger.info(f"种子 [{torrent_name}] 通过所有检查，加入删种列表")
            remove_torrents.append(item)
        
        # 处理辅种
        if self._samedata and remove_torrents:
            logger.info("开始处理辅种...")
            remove_ids = [t.get("id") for t in remove_torrents]
            remove_id_set = set(remove_ids)
            remove_torrents_plus = []

            # 预构建候选索引，避免全量嵌套扫描
            candidates_by_key: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
            for torrent in torrents:
                if downloader_config.type == "qbittorrent":
                    plus_id = torrent.hash
                    plus_name = torrent.name
                    plus_size = torrent.size
                    plus_site = StringUtils.get_url_sld(torrent.tracker)
                else:
                    plus_id = torrent.hashString
                    plus_name = torrent.name
                    plus_size = torrent.total_size
                    plus_site = torrent.trackers[0].get("sitename") if torrent.trackers else ""

                key = (plus_name, plus_size)
                candidates_by_key.setdefault(key, []).append({
                    "id": plus_id,
                    "name": plus_name,
                    "size": plus_size,
                    "site": plus_site
                })

            # 文件列表缓存，避免重复请求下载器
            file_list_cache: Dict[str, List[str]] = {}

            def _get_cached_files(hash_id: str) -> List[str]:
                if not hash_id:
                    return []
                if hash_id in file_list_cache:
                    return file_list_cache[hash_id]
                files, _ = self._transfer_checker.file_retriever.get_torrent_files(hash_id, downloader) \
                    if self._transfer_checker.file_retriever else ([], "")
                file_list_cache[hash_id] = files or []
                return file_list_cache[hash_id]

            for remove_torrent in remove_torrents:
                name = remove_torrent.get("name")
                size = remove_torrent.get("size")
                # 获取原种子的文件列表用于更精确的辅种判断
                original_torrent_hash = remove_torrent.get("id")
                original_files = _get_cached_files(original_torrent_hash)

                for candidate in candidates_by_key.get((name, size), []):
                    plus_id = candidate.get("id")
                    plus_name = candidate.get("name")
                    plus_size = candidate.get("size")
                    plus_site = candidate.get("site")

                    if plus_id in remove_id_set:
                        continue

                    # 对于多文件种子，需要进一步比较文件列表的相似性
                    is_potential_duplicate = True
                    if original_files:
                        plus_files = _get_cached_files(plus_id)
                        if plus_files:
                            # 检查两个种子的文件列表是否高度相似
                            is_potential_duplicate = self._compare_file_lists(original_files, plus_files)
                            if not is_potential_duplicate:
                                logger.debug(f"辅种 [{plus_name}] 文件列表与原种子差异较大，跳过")
                                continue

                    if is_potential_duplicate:
                        # 辅种也需要检查媒体整理记录
                        if self._transfer_checker.is_enabled():
                            # 对辅种进行更严格的检查，确保其文件也被正确处理
                            if not self._transfer_checker.check_transfer_record(plus_id, plus_name, downloader):
                                logger.info(f"辅种 [{plus_name}] 未通过媒体整理记录检查，跳过")
                                continue

                        logger.info(f"辅种 [{plus_name}] 通过检查，加入删种列表")
                        remove_torrents_plus.append(
                            {
                                "id": plus_id,
                                "name": plus_name,
                                "site": plus_site,
                                "size": plus_size
                            }
                        )
                        remove_id_set.add(plus_id)
            if remove_torrents_plus:
                remove_torrents.extend(remove_torrents_plus)
                logger.info(f"新增 {len(remove_torrents_plus)} 个辅种到删种列表")
        
        # 记录统计信息
        logger.info("=== 种子筛选统计 ===")
        logger.info(f"总种子数: {total_torrents}")
        if self._transfer_checker.is_enabled():
            logger.info(f"媒体整理记录检查 - 通过: {transfer_check_passed}, 未通过: {transfer_check_failed}")
        logger.info(f"删种条件检查 - 通过: {condition_check_passed}")
        logger.info(f"最终删种数量: {len(remove_torrents)}")
        logger.info("==================")
        
        return remove_torrents

    def __get_qb_torrent(self, torrent: Any) -> Optional[dict]:
        """
        检查QB下载任务是否符合条件
        """
        # 完成时间
        date_done = torrent.completion_on if torrent.completion_on > 0 else torrent.added_on
        # 现在时间
        date_now = int(time.mktime(datetime.now().timetuple()))
        # 做种时间
        torrent_seeding_time = date_now - date_done if date_done else 0
        # 平均上传速度
        torrent_upload_avs = torrent.uploaded / torrent_seeding_time if torrent_seeding_time else 0
        # 大小 单位：GB
        sizes = self._size.split('-') if self._size else []
        minsize = float(sizes[0]) * 1024 * 1024 * 1024 if sizes else 0
        maxsize = float(sizes[-1]) * 1024 * 1024 * 1024 if sizes else 0
        # 分享率
        if self._ratio and torrent.ratio <= float(self._ratio):
            return None
        # 做种时间 单位：小时
        if self._time and torrent_seeding_time <= float(self._time) * 3600:
            return None
        # 文件大小
        if self._size and (torrent.size >= int(maxsize) or torrent.size <= int(minsize)):
            return None
        # 平均上传速度
        if self._upspeed and torrent_upload_avs <= float(self._upspeed):
            return None
        # 保存路径关键词
        if self._pathkeywords and not re.search(r"%s" % self._pathkeywords, torrent.save_path, re.IGNORECASE):
            return None
        # Tracker关键词
        if self._trackerkeywords and not re.search(r"%s" % self._trackerkeywords, torrent.tracker, re.IGNORECASE):
            return None
        # 任务状态
        if self._torrentstates and torrent.state not in self._torrentstates.split(','):
            return None
        # 任务分类
        if self._torrentcategorys and torrent.category not in self._torrentcategorys.split(','):
            return None
        return {
            "id": torrent.hash,
            "name": torrent.name,
            "site": StringUtils.get_url_sld(torrent.tracker),
            "size": torrent.size
        }

    def __get_tr_torrent(self, torrent: Any) -> Optional[dict]:
        """
        检查TR下载任务是否符合条件
        """
        # 完成时间
        date_done = torrent.date_done if torrent.date_done else torrent.date_added
        # 现在时间
        date_now = int(time.mktime(datetime.now().timetuple()))
        # 做种时间
        torrent_seeding_time = date_now - int(date_done.timestamp()) if date_done else 0
        # 平均上传速度
        torrent_upload_avs = torrent.ratio * torrent.total_size / torrent_seeding_time if torrent_seeding_time else 0
        # 大小 单位：GB
        sizes = self._size.split('-') if self._size else []
        minsize = float(sizes[0]) * 1024 * 1024 * 1024 if sizes else 0
        maxsize = float(sizes[-1]) * 1024 * 1024 * 1024 if sizes else 0
        # 分享率
        if self._ratio and torrent.ratio <= float(self._ratio):
            return None
        # 做种时间 单位：小时
        if self._time and torrent_seeding_time <= float(self._time) * 3600:
            return None
        # 文件大小
        if self._size and (torrent.total_size >= int(maxsize) or torrent.total_size <= int(minsize)):
            return None
        # 平均上传速度
        if self._upspeed and torrent_upload_avs <= float(self._upspeed):
            return None
        # 保存路径关键词
        if self._pathkeywords and not re.search(r"%s" % self._pathkeywords, torrent.download_dir, re.IGNORECASE):
            return None
        # Tracker关键词
        if self._trackerkeywords:
            tracker_match = False
            for tracker in torrent.trackers:
                if re.search(r"%s" % self._trackerkeywords, tracker.get("announce", ""), re.IGNORECASE):
                    tracker_match = True
                    break
            if not tracker_match:
                return None
        # 错误信息关键词
        if self._errorkeywords and not re.search(r"%s" % self._errorkeywords, torrent.error_string, re.IGNORECASE):
            return None
        return {
            "id": torrent.hashString,
            "name": torrent.name,
            "site": torrent.trackers[0].get("sitename") if torrent.trackers else "",
            "size": torrent.total_size
        }

    def _compare_file_lists(self, files1: List[str], files2: List[str]) -> bool:
        """
        比较两个文件列表的相似性，判断是否为相同的种子（辅种）
        """
        if not files1 or not files2:
            return len(files1) == len(files2)  # 如果其中一个为空，则两个都应为空

        # 标准化文件路径（统一使用正斜杠，转换为小写）
        normalized_files1 = [self._transfer_checker.file_matcher._normalize_path(f) for f in files1]
        normalized_files2 = [self._transfer_checker.file_matcher._normalize_path(f) for f in files2]

        # 计算两个文件列表的交集
        set1 = set(normalized_files1)
        set2 = set(normalized_files2)
        
        # 如果两个列表完全相同，直接返回True
        if set1 == set2:
            return True

        # 计算交集比例
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        
        if len(union) == 0:
            return True  # 两个集合都为空
            
        # 计算Jaccard相似度
        similarity = len(intersection) / len(union)
        
        # 如果相似度超过阈值（如90%），认为是相同的种子
        return similarity > 0.9
