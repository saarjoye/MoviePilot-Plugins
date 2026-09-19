# -*- coding: utf-8 -*-
from calendar import monthrange
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pytz
import requests
from requests.exceptions import ProxyError, ConnectTimeout, SSLError, RequestException
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas import NotificationType


class HDHavenSignin(_PluginBase):
    # 插件元数据
    plugin_name = "栖影签到"
    plugin_desc = "栖影 (HDHaven) 站点自动签到插件。支持普通稳健签到与赌狗高收益签到、积分风控保护、深度兼容MoviePilot系统梯子网络、签到走势看板及通知推送。"
    plugin_icon = "HDHavenSignin.svg"
    plugin_version = "1.0.0"
    plugin_author = "wYw"
    author_url = "https://github.com/saarjoye/MoviePilot-Plugins"
    plugin_config_prefix = "hdhavensignin_"
    plugin_order = 27
    auth_level = 1

    # 插件元数据
    _enabled: bool = False
    _notify: bool = True
    _onlyonce: bool = False
    _cron: Optional[str] = "0 8 * * *"
    _random_time_range: str = "0-300"
    _retry_count: int = 3
    _retry_interval: int = 60
    _connect_timeout: int = 15
    _read_timeout: int = 30
    _history_count: int = 30

    # 基础运行配置
    _use_proxy: bool = True
    _custom_proxy: str = ""

    # 基础运行配置
    _auth_mode: str = "cookie"
    _cookie: str = ""
    _username: str = ""
    _password: str = ""
    _signin_mode: str = "normal"
    _gamble_min_points: int = 20
    _user_agent: str = ""

    # 站点网络常量
    _base_url: str = "https://hdhaven.com"
    _default_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    )

    _signin_mode_options: Dict[str, str] = {
        "normal": "普通签到 (稳健+5积分)",
        "gamble": "赌狗签到 (高风险博弈)",
    }

    _auth_mode_options: Dict[str, str] = {
        "cookie": "Cookie 会话 (推荐/包含hdh_session)",
        "password": "账号密码登录",
    }

    _scheduler: Optional[BackgroundScheduler] = None

    def __init__(self):
        super().__init__()

    @staticmethod
    def _to_bool(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    @staticmethod
    def _to_int(val: Any, default: int = 0) -> int:
        try:
            return int(val)
        except Exception:
            return default

    @staticmethod
    def _to_number(raw_value: Any, default: float = 0.0) -> float:
        try:
            if raw_value in (None, ""):
                return default
            return float(raw_value)
        except Exception:
            return default

    @staticmethod
    def _get_timezone():
        tz_val = getattr(settings, "TZ", None)
        if isinstance(tz_val, str) and tz_val.strip():
            try:
                return pytz.timezone(tz_val.strip())
            except Exception:
                pass
        return pytz.timezone("Asia/Shanghai")

    def _clean_cookie(self, raw_cookie: Optional[str]) -> str:
        """清洗并规范化 Cookie，提取或补充 hdh_session 会话"""
        if not raw_cookie:
            return ""
        cookie_str = raw_cookie.strip().strip("'\"")
        match = re.search(r'(hdh_session=[^;\s]+)', cookie_str)
        if match:
            session_part = match.group(1)
            other_parts = [p.strip() for p in cookie_str.split(";") if p.strip() and not p.strip().startswith("hdh_session=")]
            if other_parts:
                return f"{session_part}; " + "; ".join(other_parts)
            return session_part
        if "=" not in cookie_str and ";" not in cookie_str and len(cookie_str) >= 16:
            return f"hdh_session={cookie_str}"
        return cookie_str

    def _normalize_auth_mode(self, mode: Optional[str], has_cookie: bool = False) -> str:
        val = str(mode or "").strip().lower()
        if val in self._auth_mode_options:
            return val
        return "cookie" if has_cookie else "cookie"

    def _normalize_signin_mode(self, mode: Optional[str]) -> str:
        val = str(mode or "").strip().lower()
        if val in self._signin_mode_options:
            return val
        return "normal"

    def _is_configured(self) -> bool:
        if self._auth_mode == "cookie":
            return bool(self._cookie and self._cookie.strip())
        return bool(self._username and self._username.strip() and self._password and self._password.strip())

    def _get_proxies(self) -> Optional[Dict[str, str]]:
        """
        获取有效网络代理配置字典。
        优先级：自定义代理 > MoviePilot 全局代理设置 (settings.PROXY)
        """
        if not self._use_proxy:
            return None

        if self._custom_proxy and self._custom_proxy.strip():
            proxy_url = self._custom_proxy.strip()
            return {"http": proxy_url, "https": proxy_url}

        mp_proxy = getattr(settings, "PROXY", None)
        if mp_proxy:
            if isinstance(mp_proxy, dict):
                return mp_proxy
            elif isinstance(mp_proxy, str) and mp_proxy.strip():
                return {"http": mp_proxy.strip(), "https": mp_proxy.strip()}

        return None

    def _get_proxy_status_display(self) -> Tuple[bool, str]:
        """获取当前网络代理状态文本用于 WebUI 与通知展示"""
        if not self._use_proxy:
            return False, "未启用 (直连)"
        if self._custom_proxy and self._custom_proxy.strip():
            return True, f"自定义梯子 ({self._custom_proxy.strip()})"
        mp_proxy = getattr(settings, "PROXY", None)
        if mp_proxy:
            if isinstance(mp_proxy, str) and mp_proxy.strip():
                return True, f"MP系统梯子 ({mp_proxy.strip()})"
            elif isinstance(mp_proxy, dict):
                val = mp_proxy.get("https") or mp_proxy.get("http") or str(mp_proxy)
                return True, f"MP系统梯子 ({val})"
        return False, "已开启 (但未在MP设置梯子地址)"

    def _build_request_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        ua = self._user_agent.strip() if self._user_agent and self._user_agent.strip() else self._default_user_agent
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer or f"{self._base_url}/me",
            "Origin": self._base_url,
        }
        if self._cookie and self._cookie.strip():
            headers["Cookie"] = self._cookie.strip()
        return headers

    def init_plugin(self, config: dict = None):
        try:
            logger.info(f"{self.plugin_name}: 插件加载 - version={self.plugin_version}")
            self._enabled = False
            self._notify = True
            self._onlyonce = False
            self._cron = "0 8 * * *"
            self._use_proxy = True
            self._custom_proxy = ""
            self._auth_mode = "cookie"
            self._cookie = ""
            self._username = ""
            self._password = ""
            self._signin_mode = "normal"
            self._gamble_min_points = 20
            self._random_time_range = "0-300"
            self._retry_count = 3
            self._retry_interval = 60
            self._connect_timeout = 15
            self._read_timeout = 30
            self._history_count = 30
            self._user_agent = ""

            if config:
                self._enabled = self._to_bool(config.get("enabled", False))
                self._notify = self._to_bool(config.get("notify", True))
                self._onlyonce = self._to_bool(config.get("onlyonce", False))
                self._cron = config.get("cron") or "0 8 * * *"
                self._use_proxy = self._to_bool(config.get("use_proxy", True))
                self._custom_proxy = (config.get("custom_proxy") or "").strip()
                self._cookie = self._clean_cookie(config.get("cookie"))
                self._auth_mode = self._normalize_auth_mode(config.get("auth_mode"), bool(self._cookie))
                self._username = (config.get("username") or "").strip()
                self._password = str(config.get("password") or "")
                self._signin_mode = self._normalize_signin_mode(config.get("signin_mode"))
                self._gamble_min_points = self._to_int(config.get("gamble_min_points", 20), 20)
                self._random_time_range = (config.get("random_time_range") or "0-300").strip()
                self._retry_count = self._to_int(config.get("retry_count", 3), 3)
                self._retry_interval = self._to_int(config.get("retry_interval", 60), 60)
                self._connect_timeout = self._to_int(config.get("connect_timeout", 15), 15)
                self._read_timeout = self._to_int(config.get("read_timeout", 30), 30)
                self._history_count = self._to_int(config.get("history_count", 30), 30)
                self._user_agent = (config.get("user_agent") or "").strip()

            if self._onlyonce:
                tz = getattr(settings, "TZ", "Asia/Shanghai")
                self._scheduler = BackgroundScheduler(timezone=tz)
                logger.info(f"{self.plugin_name}: 立即执行一次签到任务")
                self._scheduler.add_job(
                    func=self._signin,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(tz)) + timedelta(seconds=2),
                    name="栖影签到-即时执行"
                )
                self._onlyonce = False
                self.update_config(self._get_config())
                if self._scheduler.get_jobs():
                    self._scheduler.start()

            if not self._enabled:
                logger.info(f"{self.plugin_name}: 插件未启用")
                return

            if self._enabled and self._cron:
                logger.info(f"{self.plugin_name}: 已配置 CRON '{self._cron}'，调度将通过公共服务注册")
        except Exception as err:
            logger.error(f"{self.plugin_name}: 初始化失败 - {err}")
            self._enabled = False

    def get_state(self) -> bool:
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        services = []
        if self._enabled and self._cron:
            services.append({
                "id": "hdhavensignin",
                "name": "栖影签到 - 定时任务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self._schedule_signin_with_random_delay,
                "kwargs": {},
            })

        pending = self.get_data("pending_task")
        if pending and isinstance(pending, dict):
            run_time_ts = pending.get("run_time_ts")
            if run_time_ts:
                run_date = datetime.fromtimestamp(run_time_ts)
                task_type = pending.get("type", "unknown")
                if run_date > datetime.now():
                    services.append({
                        "id": f"hdhavensignin_pending_{task_type}",
                        "name": f"栖影签到 - {'随机延迟' if task_type == 'random_delay' else '重试任务'}",
                        "trigger": "date",
                        "func": self._execute_delayed_signin,
                        "kwargs": {"run_date": run_date},
                    })
                    logger.info(f"{self.plugin_name}: 恢复待执行任务 ({task_type}) - {run_date.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self._clear_pending_task()

        return services

    def stop_service(self):
        try:
            Scheduler().remove_plugin_job(self.__class__.__name__.lower())
        except Exception as err:
            logger.debug(f"{self.plugin_name}: 移除公共调度器任务异常 - {err}")

        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as err:
            logger.debug(f"{self.plugin_name}: 停止内部调度器异常 - {err}")

    def _format_http_error(self, response: requests.Response, res_data: Optional[dict] = None) -> str:
        code = response.status_code
        if res_data and isinstance(res_data, dict):
            msg = res_data.get("message") or res_data.get("error") or res_data.get("msg")
            if msg:
                return f"HTTP {code}: {msg}"
        text_snippet = response.text.strip()[:160]
        if "cf-turnstile" in text_snippet or "Cloudflare" in text_snippet:
            return f"HTTP {code}: Cloudflare 拦截保护，请切换为 Cookie 模式"
        return f"HTTP {code} ({text_snippet or response.reason})"

    def _login_with_password(self, session: requests.Session, proxies: Optional[dict]):
        login_url = f"{self._base_url}/api/auth/login"
        payload = {
            "username": self._username,
            "password": self._password,
        }
        try:
            res = session.post(
                login_url,
                json=payload,
                headers=self._build_request_headers(referer=f"{self._base_url}/login"),
                proxies=proxies,
                timeout=(self._connect_timeout, self._read_timeout)
            )
            res_data = {}
            try:
                res_data = res.json()
            except Exception:
                pass

            if res.status_code in (200, 201):
                cookie_dict = session.cookies.get_dict()
                if "hdh_session" in cookie_dict:
                    self._cookie = f"hdh_session={cookie_dict['hdh_session']}"
                    cfg = self._get_config()
                    cfg["cookie"] = self._cookie
                    self.update_config(cfg)
                    logger.info(f"{self.plugin_name}: 账号密码登录成功，已自动更新 hdh_session")
                    return
                logger.info(f"{self.plugin_name}: 账号密码登录成功")
                return

            err_text = self._format_http_error(res, res_data)
            if "turnstile" in err_text.lower() or "cloudflare" in err_text.lower() or res.status_code == 403:
                raise ValueError("检测到站点启用了 Cloudflare 人机验证 (Turnstile)，密码登录受阻。请在插件配置中切换为【Cookie 模式】并填入 hdh_session 会话。")
            raise ValueError(f"账号密码登录失败 - {err_text}")
        except RequestException as e:
            if isinstance(e, (ProxyError, ConnectTimeout)):
                raise ValueError(f"代理网络异常，无法连接到栖影站点: {e}")
            raise

    def _fetch_user_profile(self, session: requests.Session, proxies: Optional[dict]) -> dict:
        url = f"{self._base_url}/api/auth/me"
        res = session.get(
            url,
            headers=self._build_request_headers(referer=f"{self._base_url}/me"),
            proxies=proxies,
            timeout=(self._connect_timeout, self._read_timeout)
        )
        if res.status_code in (401, 403):
            raise ValueError(f"登录态失效 (HTTP {res.status_code})，请更新 hdh_session 会话 Cookie")
        if res.status_code != 200:
            raise ValueError(f"获取用户信息失败 - HTTP {res.status_code}")

        try:
            data = res.json()
        except Exception as e:
            raise ValueError(f"解析用户信息响应异常: {e}")

        if isinstance(data, dict):
            data_dict = data["data"] if "data" in data and isinstance(data["data"], dict) else (
                data["user"] if "user" in data and isinstance(data["user"], dict) else data
            )
            if isinstance(data_dict, dict):
                cls_val = data_dict.get("class")
                if isinstance(cls_val, dict):
                    data_dict["class_name"] = cls_val.get("name") or ""
                elif "class_name" not in data_dict:
                    data_dict["class_name"] = str(cls_val or "")

                if "level" not in data_dict or not data_dict["level"]:
                    data_dict["level"] = data_dict["class_name"] or data_dict.get("role") or "会员"

                checked = data_dict.get("checkin_today") if "checkin_today" in data_dict else data_dict.get("checkedInToday", False)
                data_dict["checkin_today"] = bool(checked)
                data_dict["checkedInToday"] = bool(checked)

                streak = data_dict.get("checkin_streak") or data_dict.get("consecutive_signin") or data_dict.get("streak", 0)
                data_dict["streak"] = streak
                data_dict["checkin_streak"] = streak

                data_dict["points"] = self._to_number(data_dict.get("points"), 0.0)
                return data_dict
        return {}

    def _execute_checkin(self, session: requests.Session, proxies: Optional[dict], target_mode: str) -> Tuple[int, dict]:
        if target_mode == "gamble":
            url = f"{self._base_url}/api/account/checkin/gamble"
        else:
            url = f"{self._base_url}/api/account/checkin"

        res = session.post(
            url,
            headers=self._build_request_headers(referer=f"{self._base_url}/me#account-points"),
            proxies=proxies,
            timeout=(self._connect_timeout, self._read_timeout)
        )
        try:
            res_data = res.json()
        except Exception:
            res_data = {}

        return res.status_code, res_data

    def _signin(self, retry_index: int = 0) -> Dict[str, Any]:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self._is_configured():
            msg = "未配置栖影 Cookie (hdh_session)" if self._auth_mode == "cookie" else "未配置用户名或密码"
            result = {
                "success": False,
                "timestamp": timestamp,
                "message": msg,
                "action": "config_required",
                "status": "config_required",
                "points_change": 0,
                "risk_downgraded": False,
                "detail": msg,
            }
            self._record_history(result)
            return result

        proxy_enabled, proxy_desc = self._get_proxy_status_display()
        try:
            proxies = self._get_proxies()
            session = requests.Session()

            if self._auth_mode == "password":
                self._login_with_password(session, proxies)

            # 1. 账号身份认证校验
            try:
                user_info = self._fetch_user_profile(session, proxies)
                if user_info:
                    self.save_data("user_info", user_info)
            except Exception as e:
                logger.warning(f"{self.plugin_name}: 获取用户信息异常 - {e}")
                user_info = self.get_data("user_info") or {}

            nickname = user_info.get("nickname") or user_info.get("username") or "栖影用户"
            user_id = user_info.get("id", "--")
            level = user_info.get("level") or "普通用户"
            is_vip = bool(user_info.get("vip", False))
            current_points = self._to_number(user_info.get("points", 0))

    # 基础运行配置
            if user_info.get("checkin_today") is True:
                streak = user_info.get("checkin_streak", user_info.get("consecutive_signin", "--"))
                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": "今日已在其他端完成签到，无需重复操作",
                    "action": "already_signed",
                    "status": "already_signed_in",
                    "points_change": 0,
                    "risk_downgraded": False,
                    "detail": "今日已签到，无需重复签到",
                    "mode": self._signin_mode,
                    "mode_name": self._signin_mode_options.get(self._signin_mode, "普通签到"),
                    "points": current_points,
                    "checkin_days": streak,
                    "proxy_status": proxy_desc,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【栖影签到】今日已签到 \U0001f7e1",
                    text=(
                        f"━━━━━━━━━━━━━━━\n"
                        f"✨ 状态：今日已完成签到\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"\U0001f464 用户：{nickname} (UID: {user_id})\n"
                        f"\U0001f396️ 等级：{level} {'(VIP)' if is_vip else ''}\n"
                        f"\U0001f4b0 当前积分：{current_points}\n"
                        f"\U0001f4c5 连续签到：{streak} 天\n"
                        f"\U0001f310 网络环境：{proxy_desc}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"\U0001f552 记录时间：{timestamp}"
                    ),
                )
                return result

            # 2. 赌狗模式风控检查：最低积分保护
            target_mode = self._signin_mode
            downgraded = False
            downgrade_reason = ""
            if target_mode == "gamble":
                if current_points < self._gamble_min_points:
                    target_mode = "normal"
                    downgraded = True
                    downgrade_reason = f"当前积分 ({current_points}) 低于设定的风控阈值 ({self._gamble_min_points})，已自动降级为普通签到以保护积分安全！"
                    logger.warning(f"{self.plugin_name}: {downgrade_reason}")

            mode_name = self._signin_mode_options.get(target_mode, "普通签到")
            if downgraded:
                mode_name += " (风控保护降级)"

            # 3. 发起签到请求
            status_code, res_data = self._execute_checkin(session, proxies, target_mode)

            # 签到成功 (HTTP 200 或 201)
            if status_code in (200, 201):
                data_obj = res_data.get("data") if isinstance(res_data.get("data"), dict) else res_data
                earned = self._to_number(data_obj.get("earned") or data_obj.get("points_awarded") or (5 if target_mode == "normal" else 0))
                new_points = data_obj.get("points") or data_obj.get("new_balance")

                try:
                    updated_profile = self._fetch_user_profile(session, proxies)
                    if updated_profile:
                        self.save_data("user_info", updated_profile)
                        new_points = updated_profile.get("points", new_points)
                        streak = updated_profile.get("checkin_streak", updated_profile.get("consecutive_signin", 1))
                    else:
                        streak = data_obj.get("checkin_streak", 1)
                except Exception:
                    streak = data_obj.get("checkin_streak", 1)

                new_points_num = self._to_number(new_points, current_points + earned)
                signed_msg = f"{mode_name}成功，获得 {earned:g} 积分！"
                if downgrade_reason:
                    signed_msg += f" [{downgrade_reason}]"

                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": signed_msg,
                    "action": "signed",
                    "status": "success",
                    "mode": target_mode,
                    "mode_name": mode_name,
                    "points_awarded": earned,
                    "points_change": earned,
                    "points": new_points_num,
                    "checkin_days": streak,
                    "proxy_status": proxy_desc,
                    "downgraded": downgraded,
                    "risk_downgraded": downgraded,
                    "detail": signed_msg,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【栖影签到】成功 \U0001f7e2",
                    text=(
                        f"━━━━━━━━━━━━━━━\n"
                        f"✨ 状态：签到成功\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"\U0001f464 用户：{nickname} (UID: {user_id})\n"
                        f"\U0001f396️ 等级：{level} {'(VIP)' if is_vip else ''}\n"
                        f"\U0001f3b2 签到模式：{mode_name}\n"
                        f"\U0001f381 获得积分：{earned:+g}\n"
                        f"\U0001f4b0 当前总积分：{new_points_num:g}\n"
                        f"\U0001f4c5 连续签到：{streak} 天\n"
                        f"\U0001f310 网络环境：{proxy_desc}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"\U0001f552 签到时间：{timestamp}"
                    ),
                )
                return result

            # HTTP 409 Conflict: 今日已签到
            elif status_code == 409:
                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": f"今日已完成签到，请勿重复操作 ({mode_name})",
                    "action": "already_signed",
                    "status": "already_signed_in",
                    "points_change": 0,
                    "risk_downgraded": False,
                    "detail": "今日已签到，无需重复签到",
                    "mode": target_mode,
                    "mode_name": mode_name,
                    "points": current_points,
                    "checkin_days": user_info.get("checkin_streak", "--"),
                    "proxy_status": proxy_desc,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【栖影签到】今日已签到 \U0001f7e1",
                    text=(
                        f"━━━━━━━━━━━━━━━\n"
                        f"✨ 状态：今日已完成签到\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"\U0001f464 用户：{nickname} (UID: {user_id})\n"
                        f"\U0001f3b2 默认模式：{mode_name}\n"
                        f"\U0001f4b0 当前积分：{current_points}\n"
                        f"\U0001f310 网络环境：{proxy_desc}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"\U0001f552 检查时间：{timestamp}"
                    ),
                )
                return result

            # 其它 HTTP 异常状态码处理
            else:
                err_text = f"HTTP {status_code}: {res_data.get('message') or res_data.get('error') or '接口响应异常'}"
                raise ValueError(err_text)

        except Exception as err:
            err_msg = str(err)
            if isinstance(err, (ProxyError, ConnectTimeout)) or "ProxyError" in type(err).__name__:
                err_msg = f"代理梯子连接失败，请检查MoviePilot全局代理或自定义代理设置是否可用 ({err})"
            logger.error(f"{self.plugin_name}: 执行签到失败 - {err_msg}")

            next_retry_time = None
            if retry_index < self._retry_count:
                next_retry_time = self._schedule_retry_signin(retry_index + 1)
            else:
                self._clear_pending_task()

            user_info = self.get_data("user_info") or {}
            nickname = user_info.get("nickname") or "栖影用户"
            result = {
                "success": False,
                "timestamp": timestamp,
                "message": err_msg,
                "action": "failed",
                "status": "failed",
                "detail": err_msg,
                "points_change": 0,
                "risk_downgraded": False,
                "retry_index": retry_index,
                "next_retry_time": next_retry_time,
                "is_retry_task": retry_index > 0,
                "proxy_status": proxy_desc,
            }
            self._record_history(result)
            self._notify_result(
                title="【栖影签到】异常 \U0001f534",
                text=(
                    f"━━━━━━━━━━━━━━━\n"
                    f"⚠️ 状态：签到执行失败\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"\U0001f464 用户：{nickname}\n"
                    f"❌ 失败原因：{err_msg}\n"
                    f"\U0001f504 重试进度：{retry_index}/{self._retry_count}\n"
                    f"⏰ 下次重试：{next_retry_time or '无'}\n"
                    f"\U0001f310 网络环境：{proxy_desc}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"\U0001f552 执行时间：{timestamp}"
                ),
            )
            return result

    def _parse_random_delay(self) -> int:
        if not self._random_time_range:
            return 0
        try:
            p = [int(x.strip()) for x in self._random_time_range.split("-") if x.strip()]
            if len(p) == 2:
                return random.randint(min(p), max(p))
            if len(p) == 1:
                return random.randint(0, p[0])
        except Exception:
            pass
        return 0

    def _schedule_signin_with_random_delay(self):
        delay = self._parse_random_delay()
        if delay <= 0:
            logger.info(f"{self.plugin_name}: 无随机延迟，立即开始签到")
            self._signin(0)
            return

        tz_obj = self._get_timezone()
        run_date = datetime.now(tz=tz_obj) + timedelta(seconds=delay)
        self.save_data("pending_task", {
            "type": "random_delay",
            "run_time_ts": run_date.timestamp(),
            "retry_index": 0,
        })
        logger.info(f"{self.plugin_name}: 随机延迟 {delay} 秒，预计于 {run_date.strftime('%H:%M:%S')} 执行签到")
        try:
            if not self._scheduler:
                self._scheduler = BackgroundScheduler(timezone=tz)
            self._scheduler.add_job(
                func=self._execute_delayed_signin,
                trigger="date",
                run_date=run_date,
                kwargs={"run_date": run_date},
                name="栖影签到-延迟任务"
            )
            if not self._scheduler.running:
                self._scheduler.start()
        except Exception as e:
            logger.error(f"{self.plugin_name}: 启动延迟任务失败 - {e}")
            self._signin(0)

    def _schedule_retry_signin(self, next_retry_index: int) -> Optional[str]:
        interval = max(self._retry_interval, 5)
        tz_obj = self._get_timezone()
        run_date = datetime.now(tz=tz_obj) + timedelta(seconds=interval)
        self.save_data("pending_task", {
            "type": "retry",
            "run_time_ts": run_date.timestamp(),
            "retry_index": next_retry_index,
        })
        logger.info(f"{self.plugin_name}: 将在 {interval} 秒后进行第 {next_retry_index} 次签到重试")
        try:
            if not self._scheduler:
                self._scheduler = BackgroundScheduler(timezone=tz)
            self._scheduler.add_job(
                func=self._execute_delayed_signin,
                trigger="date",
                run_date=run_date,
                kwargs={"run_date": run_date},
                name=f"栖影签到-重试任务{next_retry_index}"
            )
            if not self._scheduler.running:
                self._scheduler.start()
            return run_date.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"{self.plugin_name}: 注册重试调度器异常 - {e}")
            return None

    def _execute_delayed_signin(self, run_date: Optional[datetime] = None):
        pending = self.get_data("pending_task") or {}
        retry_idx = pending.get("retry_index", 0)
        self._clear_pending_task()
        self._signin(retry_index=retry_idx)

    def _clear_pending_task(self):
        self.save_data("pending_task", None)

    def _record_history(self, record: Dict[str, Any]) -> None:
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = []
        history.append(record)
        history = sorted(history, key=lambda x: x.get("timestamp") or "", reverse=True)
        if len(history) > self._history_count:
            history = history[:self._history_count]
        self.save_data("history", history)
        self.save_data("latest_result", record)

    def _notify_result(self, title: str, text: str) -> None:
        if not self._notify:
            return
        try:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=title,
                text=text,
            )
        except Exception as err:
            logger.error(f"{self.plugin_name}: 发送通知异常 - {err}")

    @staticmethod
    def _parse_history_datetime(raw_value: Any) -> Optional[datetime]:
        if not raw_value:
            return None
        raw_text = str(raw_value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw_text[:len(fmt)], fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(raw_text.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    def _month_label(self) -> str:
        now = datetime.now()
        return f"{now.year}年{now.month}月"

    def _build_month_points_series(self, history: List[dict]) -> Tuple[List[Dict[str, Any]], float, float]:
        now = datetime.now()
        days_in_month = monthrange(now.year, now.month)[1]
        points_by_day = {day: 0.0 for day in range(1, days_in_month + 1)}

        for item in history:
            dt_val = self._parse_history_datetime(item.get("timestamp"))
            if not dt_val or dt_val.year != now.year or dt_val.month != now.month:
                continue
            if item.get("action") not in ("signed", "already_signed"):
                continue
            points_by_day[dt_val.day] += self._to_number(item.get("points_awarded"), 0.0)

        series = [{"day": day, "points": points_by_day[day]} for day in range(1, days_in_month + 1)]
        total_points = sum(item["points"] for item in series)
        peak_points = max([item["points"] for item in series] + [0.0])
        return series, total_points, peak_points

    def _build_points_chart(self, series: List[Dict[str, Any]]) -> Dict[str, Any]:
        width, height = 920, 300
        left, right, top, bottom = 64, 28, 28, 48
        chart_w = width - left - right
        chart_h = height - top - bottom

        values = [self._to_number(item.get("points"), 0.0) for item in series]
        min_v = min(values + [0.0])
        max_v = max(values + [5.0])
        if min_v == max_v:
            min_v -= 1.0
            max_v += 1.0
        padding = max((max_v - min_v) * 0.15, 1.0)
        y_min = min_v - padding
        y_max = max_v + padding

        def x_at(idx: int) -> float:
            if len(series) <= 1:
                return left + chart_w / 2
            return left + chart_w * idx / (len(series) - 1)

        def y_at(val: float) -> float:
            return top + (y_max - val) * chart_h / (y_max - y_min)

        pts = [(x_at(i), y_at(self._to_number(it.get("points"), 0.0))) for i, it in enumerate(series)]
        path_d = ""
        for i, (x, y) in enumerate(pts):
            path_d += f"{'M' if i == 0 else ' L'} {x:.1f} {y:.1f}"

        grid_nodes = []
        for i in range(5):
            val = y_min + (y_max - y_min) * i / 4
            y = y_at(val)
            grid_nodes.append({
                "component": "line",
                "props": {"x1": left, "y1": y, "x2": width - right, "y2": y, "stroke": "#e2e8f0", "stroke-width": 1, "stroke-dasharray": "4 4"}
            })
            grid_nodes.append({
                "component": "text",
                "props": {"x": left - 10, "y": y + 4, "text-anchor": "end", "fill": "#94a3b8", "font-size": 11},
                "text": f"{val:.0f}"
            })

        x_indexes = sorted(set([0, len(series) - 1, max(0, len(series) // 4), max(0, len(series) // 2), max(0, len(series) * 3 // 4)]))
        x_labels = [
            {"component": "text", "props": {"x": x_at(idx), "y": height - 16, "text-anchor": "middle", "fill": "#94a3b8", "font-size": 11}, "text": f"{series[idx]['day']}日"}
            for idx in x_indexes if 0 <= idx < len(series)
        ]

        circles = [
            {"component": "circle", "props": {"cx": x, "cy": y, "r": 3.8, "fill": "#3b82f6", "stroke": "#ffffff", "stroke-width": 2}}
            for x, y in pts
        ]

        return {
            "component": "div",
            "props": {"style": "width: 100%; overflow-x: auto;"},
            "content": [
                {
                    "component": "svg",
                    "props": {"viewBox": f"0 0 {width} {height}", "style": "width: 100%; min-width: 600px; height: auto; display: block;"},
                    "content": [
                        *grid_nodes,
                        {"component": "line", "props": {"x1": left, "y1": y_at(0), "x2": width - right, "y2": y_at(0), "stroke": "#cbd5e1", "stroke-width": 1.2}},
                        {"component": "path", "props": {"d": path_d, "fill": "none", "stroke": "#2563eb", "stroke-width": 3.5, "stroke-linecap": "round", "stroke-linejoin": "round"}},
                        *circles,
                        *x_labels,
                    ]
                }
            ]
        }

    @staticmethod
    def _section_card(header_bg: str, icon: str, title: str, content: List[dict], badge: Optional[dict] = None) -> Dict[str, Any]:
        header_items = [
            {
                "component": "div",
                "props": {"class": "d-flex align-center ga-2"},
                "content": [
                    {"component": "VIcon", "props": {"size": 22, "color": "primary"}, "text": icon},
                    {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold text-high-emphasis"}, "text": title},
                ]
            }
        ]
        if badge:
            header_items.append(badge)

        return {
            "component": "div",
            "props": {"style": "border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; background: #ffffff; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);"},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "d-flex align-center justify-space-between flex-wrap ga-2", "style": f"background: {header_bg}; padding: 14px 20px;"},
                    "content": header_items
                },
                {
                    "component": "div",
                    "props": {"style": "padding: 18px 20px;"},
                    "content": content
                }
            ]
        }

    def _get_config(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "use_proxy": self._use_proxy,
            "custom_proxy": self._custom_proxy,
            "auth_mode": self._auth_mode,
            "cookie": self._cookie,
            "username": self._username,
            "password": self._password,
            "signin_mode": self._signin_mode,
            "gamble_min_points": self._gamble_min_points,
            "random_time_range": self._random_time_range,
            "retry_count": self._retry_count,
            "retry_interval": self._retry_interval,
            "user_agent": self._user_agent,
            "history_count": self._history_count,
        }

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        version = getattr(settings, "VERSION_FLAG", "v1")
        cron_component = "VCronField" if version == "v2" else "VTextField"
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VCard",
                        "props": {"variant": "flat", "class": "mb-4", "color": "surface"},
                        "content": [
                            {
                                "component": "VCardItem",
                                "props": {"class": "px-4 pb-0"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "props": {"class": "d-flex align-center text-subtitle-1 font-weight-bold"},
                                        "content": [
                                            {"component": "VIcon", "props": {"class": "mr-2", "color": "primary", "size": "small"}, "text": "mdi-clock-outline"},
                                            {"component": "span", "text": "基础运行与调度设置"}
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VCardText",
                                "props": {"class": "pt-2"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件", "color": "success"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知", "color": "info"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "保存后立即执行一次", "color": "warning"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": cron_component, "props": {"model": "cron", "label": "Cron 定时规则 (默认每天 08:00)"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "random_time_range", "label": "随机延迟区间 (秒，如 0-300)"}}]},
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCard",
                        "props": {"variant": "flat", "class": "mb-4", "color": "surface"},
                        "content": [
                            {
                                "component": "VCardItem",
                                "props": {"class": "px-4 pb-0"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "props": {"class": "d-flex align-center text-subtitle-1 font-weight-bold"},
                                        "content": [
                                            {"component": "VIcon", "props": {"class": "mr-2", "color": "info", "size": "small"}, "text": "mdi-web"},
                                            {"component": "span", "text": "梯子网络与代理环境 (国内必须经由代理访问)"}
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VCardText",
                                "props": {"class": "pt-2"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "use_proxy", "label": "启用代理 / 梯子访问", "color": "success", "hint": "开启后将通过代理访问栖影站点，留空自定义代理时自动读取 MP 全局梯子配置", "persistent-hint": True}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [{"component": "VTextField", "props": {"model": "custom_proxy", "label": "自定义代理地址 (选填，留空则默认对接 MP 全局梯子)", "placeholder": "例如: http://127.0.0.1:7890 或 socks5://127.0.0.1:10808"}}]},
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCard",
                        "props": {"variant": "flat", "class": "mb-4", "color": "surface"},
                        "content": [
                            {
                                "component": "VCardItem",
                                "props": {"class": "px-4 pb-0"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "props": {"class": "d-flex align-center text-subtitle-1 font-weight-bold"},
                                        "content": [
                                            {"component": "VIcon", "props": {"class": "mr-2", "color": "primary", "size": "small"}, "text": "mdi-shield-key-outline"},
                                            {"component": "span", "text": "账号身份认证设置"}
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VCardText",
                                "props": {"class": "pt-2"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "auth_mode",
                                                            "label": "认证方式",
                                                            "items": [
                                                                {"title": "Cookie 会话模式 (推荐/稳定绕过人机验证)", "value": "cookie"},
                                                                {"title": "账号密码模式 (若遇Cloudflare人机验证需换Cookie)", "value": "password"}
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12},
                                                "content": [
                                                    {
                                                        "component": "VTextarea",
                                                        "props": {
                                                            "model": "cookie",
                                                            "label": "Cookie / hdh_session 会话",
                                                            "rows": 3,
                                                            "hint": "推荐填入。可直接输入 hdh_session=xxxx 或浏览器复制的完整 Cookie 字符串，插件将自动提纯清洗",
                                                            "persistent-hint": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "username", "label": "用户名 / 邮箱 (密码模式下使用)"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "password", "label": "登录密码 (密码模式下使用)", "type": "password"}}]},
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCard",
                        "props": {"variant": "flat", "class": "mb-4", "color": "surface"},
                        "content": [
                            {
                                "component": "VCardItem",
                                "props": {"class": "px-4 pb-0"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "props": {"class": "d-flex align-center text-subtitle-1 font-weight-bold"},
                                        "content": [
                                            {"component": "VIcon", "props": {"class": "mr-2", "color": "warning", "size": "small"}, "text": "mdi-dice-multiple-outline"},
                                            {"component": "span", "text": "签到策略与风控保护"}
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VCardText",
                                "props": {"class": "pt-2"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "signin_mode",
                                                            "label": "签到模式",
                                                            "items": [
                                                                {"title": "普通签到 (稳健保底 +5 积分)", "value": "normal"},
                                                                {"title": "赌狗签到 (高风险博弈，可能扣减或翻倍)", "value": "gamble"}
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "gamble_min_points",
                                                            "label": "赌狗最低积分风控阈值 (默认 20)",
                                                            "type": "number",
                                                            "hint": "开启赌狗签到时，若当前积分低于该值将自动降级为普通签到保护积分",
                                                            "persistent-hint": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "retry_count", "label": "失败重试次数 (默认 3)", "type": "number"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "retry_interval", "label": "重试间隔时间 (秒，默认 60)", "type": "number"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "user_agent", "label": "自定义 User-Agent (留空使用默认最新Chrome UA)"}}]},
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], self._get_config()

    def get_page(self) -> List[dict]:
        latest = self.get_data("latest_result") or {}
        history = self.get_data("history") or []
        user_info = self.get_data("user_info") or {}

        username = user_info.get("nickname") or user_info.get("username") or "栖影用户"
        user_id = user_info.get("id", "--")
        level = user_info.get("level", "初来乍到")
        is_vip = bool(user_info.get("vip", False))
        avatar_char = username[0] if username else "?"

        current_points = user_info.get("points", latest.get("points", "--"))
        streak = user_info.get("checkin_streak", latest.get("checkin_days", "--"))

        proxy_enabled, proxy_desc = self._get_proxy_status_display()
        signin_mode_name = self._signin_mode_options.get(self._signin_mode, "普通签到")

        series, month_total, month_peak = self._build_month_points_series(history)

        action_labels = {
            "signed": ("签到成功", "success"),
            "already_signed": ("今日已签到", "info"),
            "failed": ("签到失败", "error"),
            "config_required": ("待配置", "warning")
        }
        latest_act = latest.get("action", "")
        act_text, act_color = action_labels.get(latest_act, ("暂无记录", "default"))

        status_chips = [
            {"component": "VChip", "props": {"color": "success" if self._enabled else "default", "variant": "tonal", "size": "small"}, "text": f"插件: {'已启用' if self._enabled else '未启用'}"},
            {"component": "VChip", "props": {"color": "primary", "variant": "tonal", "size": "small"}, "text": f"定时: {self._cron or '未设置'}"},
            {"component": "VChip", "props": {"color": "info" if proxy_enabled else "warning", "variant": "tonal", "size": "small"}, "text": f"梯子: {proxy_desc}"},
            {"component": "VChip", "props": {"color": "purple", "variant": "tonal", "size": "small"}, "text": f"默认模式: {signin_mode_name}"},
            {"component": "VChip", "props": {"color": act_color, "variant": "tonal", "size": "small"}, "text": f"最新状态: {act_text}"},
        ]

        table_rows = []
        for h in history[:15]:
            h_action = h.get("action", "")
            h_text, h_color = action_labels.get(h_action, ("未知", "default"))
            table_rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "props": {"class": "text-caption py-2"}, "text": h.get("timestamp", "--")},
                    {"component": "td", "props": {"class": "py-2"}, "content": [{"component": "VChip", "props": {"size": "x-small", "color": "purple", "variant": "tonal"}, "text": h.get("mode_name", h.get("mode", "--"))}]},
                    {"component": "td", "props": {"class": "py-2"}, "content": [{"component": "VChip", "props": {"size": "x-small", "color": h_color, "variant": "tonal"}, "text": h_text}]},
                    {"component": "td", "props": {"class": "py-2 font-weight-bold", "style": "color: #10b981;"}, "text": f"{h.get('points_awarded', 0):+g}" if h.get("points_awarded") is not None else "--"},
                    {"component": "td", "props": {"class": "py-2 font-weight-bold"}, "text": str(h.get("points", "--"))},
                    {"component": "td", "props": {"class": "py-2 text-caption text-medium-emphasis"}, "text": h.get("proxy_status", "--")},
                    {"component": "td", "props": {"class": "py-2 text-caption"}, "text": h.get("message", "--")},
                ]
            })

        if not table_rows:
            table_rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "props": {"colspan": 7, "class": "text-center text-caption py-4 text-medium-emphasis"}, "text": "暂无历史签到记录"}
                ]
            })

        return [
            {
                "component": "div",
                "props": {"class": "pa-1"},
                "content": [
                    self._section_card(
                        "#f8fafc",
                        "mdi-information-outline",
                        "运行状态与环境",
                        [{"component": "div", "props": {"class": "d-flex flex-wrap ga-2 align-center"}, "content": status_chips}]
                    ),
                    self._section_card(
                        "#f0fdf4",
                        "mdi-account-badge-outline",
                        "栖影账号与积分概览",
                        [
                            {
                                "component": "div",
                                "props": {"class": "d-flex flex-wrap align-center justify-space-between ga-4"},
                                "content": [
                                    {
                                        "component": "div",
                                        "props": {"class": "d-flex align-center ga-3"},
                                        "content": [
                                            {
                                                "component": "VAvatar",
                                                "props": {"color": "primary", "size": 48, "class": "text-h6 font-weight-bold text-white"},
                                                "text": avatar_char
                                            },
                                            {
                                                "component": "div",
                                                "content": [
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "d-flex align-center ga-2"},
                                                        "content": [
                                                            {"component": "span", "props": {"class": "text-h6 font-weight-bold"}, "text": username},
                                                            {"component": "VChip", "props": {"size": "x-small", "color": "info", "variant": "flat"}, "text": level},
                                                            {"component": "VChip", "props": {"size": "x-small", "color": "amber-darken-3", "variant": "flat", "style": f"display: {'inline-flex' if is_vip else 'none'}"}, "text": "VIP会员"}
                                                        ]
                                                    },
                                                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": f"UID: {user_id} · 会话正常"}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "div",
                                        "props": {"class": "d-flex flex-wrap ga-3"},
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {"class": "pa-3 text-center", "style": "background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; min-width: 110px;"},
                                                "content": [
                                                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "当前总积分"},
                                                    {"component": "div", "props": {"class": "text-h6 font-weight-bold text-primary"}, "text": str(current_points)}
                                                ]
                                            },
                                            {
                                                "component": "div",
                                                "props": {"class": "pa-3 text-center", "style": "background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; min-width: 110px;"},
                                                "content": [
                                                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "连续签到"},
                                                    {"component": "div", "props": {"class": "text-h6 font-weight-bold text-success"}, "text": f"{streak} 天"}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    ),
                    self._section_card(
                        "#eff6ff",
                        "mdi-chart-areaspline",
                        f"本月签到积分走势 ({self._month_label()})",
                        [
                            {
                                "component": "div",
                                "props": {"class": "d-flex justify-space-between align-center flex-wrap ga-2 mb-2"},
                                "content": [
                                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "横轴为当月日期，纵轴为当日签到获取积分"},
                                    {
                                        "component": "div",
                                        "props": {"class": "d-flex ga-2"},
                                        "content": [
                                            {"component": "VChip", "props": {"size": "x-small", "color": "primary", "variant": "tonal"}, "text": f"本月累计获得: {month_total:g} 分"},
                                            {"component": "VChip", "props": {"size": "x-small", "color": "cyan", "variant": "tonal"}, "text": f"单日最高: {month_peak:g} 分"}
                                        ]
                                    }
                                ]
                            },
                            self._build_points_chart(series)
                        ]
                    ),
                    self._section_card(
                        "#fffbeb",
                        "mdi-history",
                        "签到历史明细 (近15次记录)",
                        [
                            {
                                "component": "VTable",
                                "props": {"density": "compact", "hover": True},
                                "content": [
                                    {
                                        "component": "thead",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "执行时间"},
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "模式"},
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "状态"},
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "奖励"},
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "余额"},
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "梯子代理"},
                                                    {"component": "th", "props": {"class": "text-caption font-weight-bold"}, "text": "结果详情"},
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "tbody",
                                        "content": table_rows
                                    }
                                ]
                            }
                        ]
                    )
                ]
            }
        ]
