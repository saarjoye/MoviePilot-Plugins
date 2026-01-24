# 插件加载日志
import logging
logger = logging.getLogger(__name__)
logger.info("[115上传监控] 插件模块开始加载")

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import asyncio
from functools import wraps
import inspect
import re

from app.core.event import eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType

logger.info("[115上传监控] 插件模块加载完成，所有导入成功")


class u115uploadmonitor(_PluginBase):
    """
    监听 115 网盘上传开始/完成事件并推送通知。
    """

    plugin_name = "115上传监控"
    plugin_desc = "实时监听 115 网盘上传开始/完成事件，仅推送整条任务的开始与完成信息。"
    plugin_icon = "https://raw.githubusercontent.com/KoWming/MoviePilot-Plugins/main/icons/u115.png"
    plugin_version = "1.0.4"
    plugin_author = "wYw"
    author_url = ""
    plugin_config_prefix = "u115uploadmonitor_"
    plugin_order = 100
    auth_level = 1

    def __init__(self):
        """初始化插件实例。"""
        logger.info("[115上传监控] 插件实例创建")
        super().__init__()
        self._config: Dict[str, Any] = {
            "enabled": True,
            "notify_upload_start": True,
            "notify_upload_success": True,
            "send_test_notification": False,
            # 兼容：部分 MP 版本可能改用 PluginTriggered 或根本未发送 115 上传事件
            "compat_listen_plugin_triggered": True,
            # auto: 仅当检测到 MP 未内置发送时才打补丁；True/False 强制开关
            "compat_patch_u115_emit_events": "auto",
            # 调试：打印收到的事件数据
            "debug_log_event_payload": False,
        }
        logger.info(f"[115上传监控] 初始配置: {self._config}")

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "y", "on"}:
                return True
            if v in {"0", "false", "no", "n", "off", ""}:
                return False
        return bool(value)

    def init_plugin(self, config: dict = None):
        """初始化插件配置并注册事件。"""
        logger.info("[115上传监控] 开始初始化插件")
        
        # 首先更新配置，确保事件监听基于最新配置
        if config:
            logger.info(f"[115上传监控] 收到配置: {config}")
            # 确保config是字典类型
            if isinstance(config, dict):
                self._config.update(config)
                logger.info(f"[115上传监控] 更新后配置: {self._config}")
                
                # 检查是否需要发送测试通知
                if self._config.get("send_test_notification"):
                    # 发送测试通知
                    logger.info("[115上传监控] 准备发送测试通知")
                    self._send_test_notification()
                    # 重置测试通知开关
                    self._config["send_test_notification"] = False
                    # 更新配置
                    logger.info("[115上传监控] 重置测试通知开关并更新配置")
                    self.update_config(self._config)
            else:
                logger.warning(f"[115上传监控] 收到的配置不是字典类型: {type(config)}")
        
        # 确保配置中有必要的键
        required_keys = ["enabled", "notify_upload_start", "notify_upload_success"]
        for key in required_keys:
            if key not in self._config:
                logger.warning(f"[115上传监控] 配置中缺少必要键: {key}，使用默认值")
                if key == "enabled":
                    self._config[key] = True
                else:
                    self._config[key] = True
        
        logger.info(f"[115上传监控] 初始化完成，最终配置: {self._config}")
        
        # 检查enabled配置的值
        enabled_value = self._config.get("enabled")
        logger.info(f"[115上传监控] enabled配置值: {enabled_value}, 类型: {type(enabled_value)}")
        
        # 调用get_state方法并记录返回值
        state = self.get_state()
        logger.info(f"[115上传监控] get_state返回值: {state}, 类型: {type(state)}")
        logger.info(f"[115上传监控] 插件状态: {'启用' if state else '禁用'}")
        
        # 调用父类的初始化方法（如果有）
        if hasattr(super(), 'init_plugin'):
            logger.info("[115上传监控] 调用父类init_plugin方法")
            super().init_plugin(config)
        
        # 无论插件是否启用，都先移除旧的监听器，然后根据当前状态重新注册
        logger.info("[115上传监控] 开始移除旧的事件监听器")
        self._unregister_events()
        
        if state:
            logger.info("[115上传监控] 插件已启用，开始注册事件监听")
            self._register_events()
            logger.info("[115上传监控] 已启用并监听上传事件")
            self._maybe_patch_u115_emitter()
        else:
            logger.info("[115上传监控] 插件未启用，不注册事件监听")
            # 注意：MP 会在插件禁用时通过 EventManager 禁用该插件的事件处理器；
            # 即便这里注册监听，也不会触发 on_plugin_action。
            # 如需测试，请在配置中开启 enabled 或使用 send_test_notification。
            logger.info("[115上传监控] 插件禁用状态下不会接收事件（MP 会禁用处理器）")
    
    def _send_test_notification(self):
        """发送测试通知。"""
        try:
            # 发送开始上传测试通知
            if self._config.get("notify_upload_start"):
                test_data = {
                    "filename": "test_movie.mp4",
                    "file_path": "/local/path/test_movie.mp4",
                    "target_path": "/115/电影/test_movie.mp4"
                }
                self._handle_upload_start(test_data)
            # 发送上传完成测试通知
            if self._config.get("notify_upload_success"):
                test_data = {
                    "filename": "test_movie.mp4",
                    "file_path": "/local/path/test_movie.mp4",
                    "target_path": "/115/电影/test_movie.mp4",
                    "upload_type": "秒传"
                }
                self._handle_upload_success(test_data)
            logger.info("[115上传监控] 测试通知发送成功")
        except Exception as err:
            logger.error(f"[115上传监控] 测试通知发送失败：{err}")

    def _register_events(self):
        """注册事件监听。"""
        logger.info("[115上传监控] _register_events方法被调用")
        
        # 先移除旧的监听器
        self._unregister_events()
        
        try:
            # 检查eventmanager是否可用
            if eventmanager is None:
                logger.error("[115上传监控] eventmanager为None")
                return
            
            logger.info("[115上传监控] 开始注册事件监听")
            
            # 打印eventmanager实例和类型
            logger.info(f"[115上传监控] eventmanager实例: {eventmanager}")
            logger.info(f"[115上传监控] eventmanager类型: {type(eventmanager)}")
            
            # 列出eventmanager的所有方法
            eventmanager_methods = [method for method in dir(eventmanager) if not method.startswith('_')]
            logger.info(f"[115上传监控] eventmanager的方法: {eventmanager_methods}")
            
            # 检查是否有add_event_listener方法
            if hasattr(eventmanager, 'add_event_listener'):
                logger.info("[115上传监控] eventmanager有add_event_listener方法")
                
                # 尝试注册监听器
                try:
                    eventmanager.add_event_listener(EventType.PluginAction, self.on_plugin_action)
                    logger.info(f"[115上传监控] 已成功注册 EventType.PluginAction 监听")
                    logger.info(f"[115上传监控] 监听器方法: {self.on_plugin_action}")
                    # 兼容：部分版本把插件动作事件改成 PluginTriggered
                    if self._to_bool(self._config.get("compat_listen_plugin_triggered", True)):
                        plugin_triggered = getattr(EventType, "PluginTriggered", None)
                        if plugin_triggered is not None:
                            eventmanager.add_event_listener(plugin_triggered, self.on_plugin_action)
                            logger.info("[115上传监控] 已成功注册 EventType.PluginTriggered 监听（兼容模式）")
                except Exception as e:
                    logger.error(f"[115上传监控] 注册监听器失败: {e}")
                    import traceback
                    traceback.print_exc()
                    return
            else:
                logger.error("[115上传监控] eventmanager没有add_event_listener方法")
                return
            
            # 不在注册时自动发送测试事件：避免每次重启/保存配置都产生“假通知”。
            # 如需验证链路，请在配置中开启 send_test_notification。
                
        except Exception as e:
            logger.error(f"[115上传监控] 注册事件监听失败: {e}")
            import traceback
            traceback.print_exc()

    def _unregister_events(self):
        """移除事件监听。"""
        try:
            eventmanager.remove_event_listener(EventType.PluginAction, self.on_plugin_action)
            plugin_triggered = getattr(EventType, "PluginTriggered", None)
            if plugin_triggered is not None:
                eventmanager.remove_event_listener(plugin_triggered, self.on_plugin_action)
            logger.debug("[115上传监控] 已移除事件监听")
        except Exception as err:
            logger.debug(f"[115上传监控] 移除事件监听失败: {err}")

    def on_plugin_action(self, event):
        """处理 115 上传事件。"""
        try:
            # 记录收到的事件信息
            logger.info(f"[115上传监控] 收到事件: {event}")
            logger.info(f"[115上传监控] 事件类型: {event.event_type}")
            logger.info(f"[115上传监控] 事件数据: {event.event_data}")
            if self._to_bool(self._config.get("debug_log_event_payload")):
                logger.info(f"[115上传监控] debug_log_event_payload: {event.event_data}")
            
            # 检查插件是否启用
            if not self.get_state():
                logger.info("[115上传监控] 插件未启用，忽略事件")
                return

            # 处理事件
            event_data = event.event_data or {}
            action = event_data.get("action") or event_data.get("event") or event_data.get("type")
            logger.info(f"[115上传监控] 事件action: {action}")
            logger.info(f"[115上传监控] 插件配置: {self._config}")

            if action in {"115_upload_start", "115_upload_begin"}:
                if self._config.get("notify_upload_start"):
                    logger.info(f"[115上传监控] 捕获开始上传事件，发送通知: {event_data}")
                    self._handle_upload_start(event_data)
                else:
                    logger.info(f"[115上传监控] 捕获开始上传事件，但未启用通知")
            elif action in {"115_upload_success", "115_upload_complete", "115_upload_completed"}:
                if self._config.get("notify_upload_success"):
                    logger.info(f"[115上传监控] 捕获上传完成事件，发送通知: {event_data}")
                    self._handle_upload_success(event_data)
                else:
                    logger.info(f"[115上传监控] 捕获上传完成事件，但未启用通知")
            else:
                logger.info(f"[115上传监控] 忽略非115上传事件: action={action}")
        except Exception as e:
            logger.error(f"[115上传监控] 处理事件时出错: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"[115上传监控] 错误堆栈: {traceback.format_exc()}")

    def _maybe_patch_u115_emitter(self):
        """
        仅修改插件、不改 MP 源码的兼容方案：
        - 若运行中的 MP 版本在 115 上传流程里没有发送 plugin.action 事件，尝试对 U115Pan.upload 做运行时补丁，补齐事件发送。
        - 默认 auto：检测到源码里已包含 115_upload_start/115_upload_success 字样则不打补丁，避免重复通知。
        """
        mode = self._config.get("compat_patch_u115_emit_events", "auto")
        if mode is False:
            return

        try:
            from app.modules.filemanager.storages.u115 import U115Pan  # type: ignore
        except Exception as err:
            logger.debug(f"[115上传监控] 无法导入 U115Pan，跳过兼容补丁：{err}")
            return

        upload_func = getattr(U115Pan, "upload", None)
        if not upload_func:
            logger.debug("[115上传监控] U115Pan.upload 不存在，跳过兼容补丁")
            return

        if getattr(upload_func, "__u115uploadmonitor_patched__", False):
            return

        if mode == "auto":
            try:
                src = inspect.getsource(upload_func)
            except Exception:
                src = ""
            if "115_upload_start" in src or "115_upload_success" in src:
                logger.info("[115上传监控] 检测到 MP 已内置 115 上传事件发送，跳过兼容补丁")
                return

        def _extract_paths(args, kwargs):
            target_dir = kwargs.get("target_dir") if isinstance(kwargs, dict) else None
            local_path = kwargs.get("local_path") if isinstance(kwargs, dict) else None
            new_name = kwargs.get("new_name") if isinstance(kwargs, dict) else None
            if len(args) >= 1 and target_dir is None:
                target_dir = args[0]
            if len(args) >= 2 and local_path is None:
                local_path = args[1]
            if len(args) >= 3 and new_name is None:
                new_name = args[2]

            target_dir_path = getattr(target_dir, "path", None)
            filename = new_name or getattr(local_path, "name", None) or None
            if filename is None and local_path is not None:
                filename = str(local_path)

            target_path = None
            if target_dir_path and filename:
                target_path = f"{str(target_dir_path).rstrip('/')}/{filename}"
            return filename, local_path, target_path

        async def _async_send(action: str, filename: str, local_path: Any, target_path: str, upload_type: str = ""):
            try:
                payload = {
                    "action": action,
                    "filename": filename,
                    "file_path": str(local_path) if local_path is not None else "",
                    "target_path": target_path or "",
                }
                if upload_type:
                    payload["upload_type"] = upload_type
                eventmanager.send_event(EventType.PluginAction, payload)
            except Exception as err:
                logger.debug(f"[115上传监控] 兼容补丁发送事件失败：{err}")

        if asyncio.iscoroutinefunction(upload_func):
            @wraps(upload_func)
            async def patched(self_obj, *args, **kwargs):
                filename, local_path, target_path = _extract_paths(args, kwargs)
                if filename:
                    await _async_send("115_upload_start", filename, local_path, target_path or "")
                result = await upload_func(self_obj, *args, **kwargs)
                if filename and result:
                    await _async_send("115_upload_success", filename, local_path, target_path or "", upload_type="上传")
                return result
        else:
            @wraps(upload_func)
            def patched(self_obj, *args, **kwargs):
                filename, local_path, target_path = _extract_paths(args, kwargs)
                if filename:
                    try:
                        eventmanager.send_event(
                            EventType.PluginAction,
                            {
                                "action": "115_upload_start",
                                "filename": filename,
                                "file_path": str(local_path) if local_path is not None else "",
                                "target_path": target_path or "",
                            },
                        )
                    except Exception as err:
                        logger.debug(f"[115上传监控] 兼容补丁发送开始事件失败：{err}")
                result = upload_func(self_obj, *args, **kwargs)
                if filename and result:
                    try:
                        eventmanager.send_event(
                            EventType.PluginAction,
                            {
                                "action": "115_upload_success",
                                "filename": filename,
                                "file_path": str(local_path) if local_path is not None else "",
                                "target_path": target_path or "",
                                "upload_type": "上传",
                            },
                        )
                    except Exception as err:
                        logger.debug(f"[115上传监控] 兼容补丁发送完成事件失败：{err}")
                return result

        setattr(patched, "__u115uploadmonitor_patched__", True)
        try:
            setattr(U115Pan, "upload", patched)
            logger.info("[115上传监控] 已对 U115Pan.upload 打入兼容补丁（补齐 115 上传事件发送）")
        except Exception as err:
            logger.debug(f"[115上传监控] 打补丁失败：{err}")

    def _get_media_title(self, filename: str) -> str:
        """从文件名中提取媒体标题（兼容电视剧和电影）。"""
        # 移除文件扩展名
        title = filename.rsplit('.', 1)[0] if '.' in filename else filename
        
        # 处理电视剧格式（如：骄阳似火第25集、骄阳似火S01E25、骄阳似火 S01 E25等）
        # 匹配SxxExx格式
        season_episode_match = re.search(r'(S\d+E\d+)', title, re.IGNORECASE)
        if season_episode_match:
            return title
        
        # 匹配中文格式的集数（如：第25集）
        chinese_episode_match = re.search(r'(第\d+集)', title)
        if chinese_episode_match:
            return title
        
        # 电影格式，直接返回标题
        return title

    def _get_formatted_time(self) -> str:
        """获取格式化的当前时间（如：2026-01-12 14:31:03,556）。"""
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]  # 保留毫秒

    def _handle_upload_start(self, data: dict):
        """推送开始上传通知。"""
        filename = data.get("filename") or "未知文件"
        
        # 获取当前时间
        formatted_time = self._get_formatted_time()
        
        # 构建通知内容
        notification_text = f"{filename} 开始上传 {formatted_time}"
        
        self._push_notification(notification_text)

    def _handle_upload_success(self, data: dict):
        """推送上传完成通知。"""
        filename = data.get("filename") or "未知文件"
        upload_type = data.get("upload_type") or "上传"
        
        # 获取当前时间
        formatted_time = self._get_formatted_time()
        
        # 构建通知内容
        notification_text = f"{filename} {upload_type}成功 {formatted_time}"
        
        self._push_notification(notification_text)

    def _push_notification(self, text: str):
        """通过系统通知通道推送消息。"""
        try:
            self.post_message(
                mtype=NotificationType.Other,
                title="115上传监控",
                text=text,
            )
            logger.info(f"[115上传监控] 已推送通知：{text}")
        except Exception as err:
            logger.error(f"[115上传监控] 推送失败：{err}")

    def get_state(self) -> bool:
        """获取插件运行状态。"""
        return self._to_bool(self._config.get("enabled", False))

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置表单。"""
        return [
            {
                'component': 'VForm',
                'content': [
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
                                                'text': '115上传监控设置'
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
                                                    'sm': 4
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
                                                    'sm': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'notify_upload_start',
                                                            'label': '推送开始上传',
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
                                                    'sm': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'notify_upload_success',
                                                            'label': '推送上传完成',
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'class': 'mt-4'
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'sm': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'send_test_notification',
                                                            'label': '保存后发送测试通知',
                                                            'color': 'primary',
                                                            'hide-details': True
                                                        }
                                                    }
                                                ]
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
                                            'text': '开启开关后会在日志输出并推送对应事件；关闭则停止监听。点击测试按钮可发送测试通知。',
                                            'class': 'mt-2'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], self._config

    def get_api(self) -> List[Dict[str, Any]]:
        """注册API接口。"""
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> Optional[List[dict]]:
        return []

    def stop_service(self):
        """停止插件并移除监听。"""
        self._config["enabled"] = False
        self._unregister_events()
        logger.info("[115上传监控] 已停止并取消事件监听")


export = u115uploadmonitor
__all__ = ["u115uploadmonitor"]
