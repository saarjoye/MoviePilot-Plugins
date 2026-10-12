# -*- coding: utf-8 -*-
import ast
from calendar import monthrange
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import pytz
import requests
from requests.exceptions import ProxyError, ConnectTimeout, SSLError, RequestException, Timeout, ReadTimeout
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas import NotificationType


class HDHavenError(ValueError):
    """栖影插件基础异常"""
    pass


class SessionVerifyRequiredError(HDHavenError):
    """站点检测到网络出口变动，需要人机验证 (SESSION_VERIFY_REQUIRED)"""
    pass


class SessionDeviceChangedError(HDHavenError):
    """站点检测到登录设备/环境指纹变化，需重新登录或同设备验证 (SESSION_DEVICE_CHANGED)"""
    pass


class ScrapeChallengeRequiredError(HDHavenError):
    """站点触发访问频率风控验证 (SCRAPE_CHALLENGE_REQUIRED)"""
    pass


class AppRequiredError(HDHavenError):
    """站点要求使用官方 OPENAPI 授权凭证接入 (APP_REQUIRED)"""
    pass


class BrowserRequiredError(HDHavenError):
    """站点返回浏览器环境拦截 (BROWSER_REQUIRED)"""
    pass


class UnauthorizedError(HDHavenError):
    """站点登录态失效 (HTTP 401 未知 code)"""
    pass


class CookieSessionRevokedError(HDHavenError):
    """站点主动作废 hdh_session 并限制程序化 Cookie 直连（裸 401 + Set-Cookie 清空）"""
    pass


class HDHavenSignin(_PluginBase):
    # 插件元数据
    plugin_name = "栖影签到"
    plugin_desc = "栖影 (HDHaven) 站点自动签到插件。支持普通稳健签到与赌狗高收益签到、积分风控保护、深度兼容MoviePilot系统梯子网络、签到走势看板及通知推送。"
    plugin_icon = "HDHavenSignin.svg"
    plugin_version = "1.0.9"
    _signin_lock = threading.Lock()
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

    # 账号认证配置
    _auth_mode: str = "cookie"
    _cookie: str = ""
    _openapi_app_id: str = ""
    _openapi_app_key: str = ""
    _openapi_user_token: str = ""
    _openapi_redirect_uri: str = ""
    _openapi_scope: str = ""
    _openapi_authorize_code: str = ""
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
        "cookie": "Cookie 会话 (需保持代理出口一致)",
        "openapi": "OPENAPI 授权 (推荐/官方API模式，免人机验证)",
        "password": "账号密码登录 (站点已开启人机验证，目前不可用)",
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

    def _normalize_auth_mode(self, mode: Optional[str], has_cookie: bool = False, has_openapi: bool = False) -> str:
        val = str(mode or "").strip().lower()
        if val in self._auth_mode_options:
            return val
        if has_openapi:
            return "openapi"
        return "cookie" if has_cookie else "cookie"

    def _normalize_signin_mode(self, mode: Optional[str]) -> str:
        val = str(mode or "").strip().lower()
        if val in self._signin_mode_options:
            return val
        return "normal"

    @property
    def _is_openapi_active(self) -> bool:
        """判断当前是否激活 OPENAPI 模式"""
        return bool(
            self._auth_mode == "openapi"
            or (self._openapi_app_key and self._openapi_user_token)
        )

    def _api_url(self, endpoint: str) -> str:
        """
        构建请求 API 路径。
        激活 OPENAPI 授权模式时，自动将 /api/* 切换为 /api/openapi/v1/*
        """
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            parsed = urlparse(endpoint)
            path = parsed.path
            if parsed.query:
                path += f"?{parsed.query}"
            base = f"{parsed.scheme}://{parsed.netloc}"
        else:
            path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
            base = self._base_url.rstrip("/")

        if self._is_openapi_active:
            path_guard = path.split("?", 1)[0]
            if path_guard.startswith("/api/openapi/"):
                # 已是完整 OPENAPI 路径（含 oauth/token 等非 /v1 端点），不得二次改写
                return f"{base}{path}"
            # 站点真实 OPENAPI 契约：端点路径与网页接口不同，必须显式映射
            openapi_path_map = {
                "/api/auth/me": "/me",
                "/api/account/checkin": "/checkin",
                "/api/account/checkin/gamble": "/checkin/gamble",
                "/api/notifications": "/notifications",
            }
            path_only, _, query = path.partition("?")
            mapped = openapi_path_map.get(path_only)
            if mapped:
                path = f"/api/openapi/v1{mapped}"
                if query:
                    path += f"?{query}"
            elif not path_only.startswith("/api/openapi/v1/") and path_only.startswith("/api/"):
                # 未列入映射表的接口按同名前缀兜底，避免误拼接
                path = f"/api/openapi/v1{path_only[4:]}"
                if query:
                    path += f"?{query}"

        return f"{base}{path}"

    def _openapi_token_url(self) -> str:
        """站点 OAuth 换取用户 Token 的端点（不在 /v1 前缀下）"""
        return f"{self._base_url.rstrip('/')}/api/openapi/oauth/token"

    def _build_openapi_authorize_url(self, state: str = "") -> str:
        """
        生成站点 OAuth 授权链接，供用户在自己的浏览器完成授权后取回 authorization code。
        所有凭证（client_id / 回调 / scope）均来自用户自己的配置，插件不内置任何凭证。
        """
        params = {
            "response_type": "code",
            "client_id": (self._openapi_app_id or "").strip(),
            "redirect_uri": (self._openapi_redirect_uri or "").strip(),
        }
        scope = (self._openapi_scope or "").strip()
        if scope:
            params["scope"] = scope
        if state:
            params["state"] = state
        return f"{self._base_url.rstrip('/')}/oauth/authorize?{urlencode(params)}"

    def _extract_openapi_code(self, raw: Any) -> str:
        """从用户粘贴的回调链接 / 裸授权码中提取 code；无法解析时原样返回"""
        val = str(raw or "").strip()
        if not val:
            return ""
        if val.startswith("http://") or val.startswith("https://"):
            parsed = urlparse(val)
            for seg in (parsed.query, parsed.fragment):
                if not seg:
                    continue
                code = (parse_qs(seg).get("code") or [""])[0].strip()
                if code:
                    return code
        return val

    def _exchange_openapi_code(self, code: str) -> str:
        """
        用用户自己的应用凭证 (hda_) + 授权码换取用户授权 Token (hdt_)。
        凭证只来自用户配置，绝不在插件内内置或回显明文。
        """
        app_key = (self._openapi_app_key or "").strip()
        if not app_key:
            raise AppRequiredError("未配置应用凭证 (hda_)，无法换取用户授权 Token")
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": (self._openapi_redirect_uri or "").strip(),
        }
        res = requests.post(
            self._openapi_token_url(),
            headers={
                "X-HDHaven-App-Key": app_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data=payload,
            proxies=self._get_proxies(),
            timeout=(self._connect_timeout, self._read_timeout),
        )
        try:
            data = res.json() or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        token = str(data.get("access_token") or "").strip()
        if not token and isinstance(data.get("data"), dict):
            token = str((data.get("data") or {}).get("access_token") or "").strip()
        if res.status_code not in (200, 201) or not token:
            err_type = self._classify_site_error(res, data)
            if err_type == "app_required":
                raise AppRequiredError("换取用户授权 Token 失败：应用凭证无效或未通过审核，请核对 应用凭证(hda_) 与应用状态")
            if err_type == "unauthorized":
                raise UnauthorizedError("换取用户授权 Token 失败：授权码无效或已过期，请重新在浏览器完成授权")
            msg = str(data.get("message") or data.get("error") or "")
            raise ValueError(f"换取用户授权 Token 失败 (HTTP {res.status_code})" + (f" - {msg}" if msg else ""))
        return token

    def _app_required_message(self) -> str:
        """
        站点返回 APP_REQUIRED 时的提示文案。
        已配置 OPENAPI 凭证仍被拒时，问题在凭证本身，不能引导用户再去申请。
        """
        if self._is_openapi_active:
            return (
                "站点返回 APP_REQUIRED，说明当前 OPENAPI 凭证未通过审核或已失效；"
                "请核对 应用编号(client_id)/应用凭证(hda_)/用户授权 Token(hdt_) 是否正确、应用是否已审核通过、用户授权是否有效"
            )
        return "站点已要求程序接入改用 OPENAPI 授权，请前往 站点 → 个人中心 → OPENAPI 申请应用并回填 应用编号 / 应用凭证 / 用户授权 Token"

    @staticmethod
    def _is_session_cookie_revoked(res: Any) -> bool:
        """
        检测响应头是否通过 Set-Cookie 主动清空 hdh_session。

        站点在判定程序化 Cookie 直连受限时，会返回裸 401 并下发
        Set-Cookie: hdh_session=; Max-Age=0，主动作废本地会话。
        该信号与普通“Cookie 已过期”有本质区别，需单独分类。
        """
        if res is None or not hasattr(res, "headers"):
            return False
        try:
            headers = res.headers
            if headers is None:
                return False
            set_cookie = headers.get("Set-Cookie")
        except Exception:
            return False
        # 兼容 MagicMock / 非常规响应对象：只处理真实字符串
        if not isinstance(set_cookie, str) or "hdh_session" not in set_cookie:
            return False
        # requests 会把多条 Set-Cookie 以 ", " 合并，需按属性边界拆分
        for part in re.split(r",(?=[^;=]+=)", set_cookie):
            match = re.search(r"hdh_session=([^;]*)", part, flags=re.IGNORECASE)
            if match and match.group(1).strip() == "":
                return True
        return False

    def _classify_site_error(self, res: Any, data: Optional[dict] = None) -> str:
        """
        统一解析响应体状态码与拦截 code 字段。
        返回 ("browser_required"|"session_verify_required"|"session_device_changed"|"scrape_challenge_required"|"app_required"|"cookie_session_revoked"|"unauthorized"|"ok")
        """
        if res is None:
            return "ok"

        status_code = getattr(res, "status_code", 200)
        if isinstance(res, int):
            status_code = res

        if status_code in (200, 201, 409):
            return "ok"

        res_data = data or {}
        text_content = ""
        if hasattr(res, "json"):
            try:
                res_data = res.json() or {}
            except Exception:
                res_data = {}
        elif isinstance(res, dict):
            res_data = res

        if hasattr(res, "text"):
            try:
                text_content = res.text or ""
            except Exception:
                text_content = ""
        elif isinstance(res_data, dict):
            text_content = str(res_data)

        code_val = ""
        if isinstance(res_data, dict):
            code_val = str(res_data.get("code") or "").strip().upper()
            if not code_val and isinstance(res_data.get("error"), dict):
                code_val = str(res_data["error"].get("code") or "").strip().upper()

        if code_val == "SESSION_VERIFY_REQUIRED" or "SESSION_VERIFY_REQUIRED" in text_content:
            return "session_verify_required"
        if code_val == "SESSION_DEVICE_CHANGED" or "SESSION_DEVICE_CHANGED" in text_content:
            return "session_device_changed"
        if code_val == "SCRAPE_CHALLENGE_REQUIRED" or "SCRAPE_CHALLENGE_REQUIRED" in text_content:
            return "scrape_challenge_required"
        if code_val in ("APP_REQUIRED", "INVALID_APP_CREDENTIAL", "TOKEN_APPLICATION_MISMATCH", "APP_IP_DENIED", "APP_USER_DENIED") or "APP_REQUIRED" in text_content:
            return "app_required"
        if code_val == "INVALID_ACCESS_TOKEN" or "INVALID_ACCESS_TOKEN" in text_content:
            return "unauthorized"
        if code_val == "BROWSER_REQUIRED" or "BROWSER_REQUIRED" in text_content:
            return "browser_required"
        if code_val == "COOKIE_SESSION_REVOKED" or "COOKIE_SESSION_REVOKED" in text_content:
            return "cookie_session_revoked"

        if status_code == 401:
            # 裸 401 且服务端通过 Set-Cookie 主动清空 hdh_session：
            # 说明会话已被服务端作废（并非普通 Cookie 过期），程序化 Cookie 直连已受限
            if self._is_session_cookie_revoked(res):
                return "cookie_session_revoked"
            return "unauthorized"
        if status_code == 403:
            return "browser_required"

        return "ok"

    def _is_configured(self) -> bool:
        if self._is_openapi_active:
            return bool(self._openapi_app_key and self._openapi_user_token)
        if self._auth_mode == "openapi":
            return bool(self._openapi_app_key and self._openapi_user_token)
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
            "sec-ch-ua": '"Google Chrome";v="134", "Chromium";v="134", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if self._cookie and self._cookie.strip():
            headers["Cookie"] = self._cookie.strip()
        if self._is_openapi_active:
            # 站点真实契约：应用凭证头为 X-HDHaven-App-Key，用户授权 Token 走 Bearer
            if self._openapi_app_key:
                headers["X-HDHaven-App-Key"] = self._openapi_app_key.strip()
            if self._openapi_user_token:
                headers["Authorization"] = f"Bearer {self._openapi_user_token.strip()}"
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
            self._openapi_app_id = ""
            self._openapi_app_key = ""
            self._openapi_user_token = ""
            self._openapi_redirect_uri = ""
            self._openapi_scope = ""
            self._openapi_authorize_code = ""
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
                self._openapi_app_id = (config.get("openapi_app_id") or "").strip()
                # 兼容旧配置键 openapi_app_secret；凭证一律来自用户配置，插件不内置任何密钥
                self._openapi_app_key = (
                    config.get("openapi_app_key") or config.get("openapi_app_secret") or ""
                ).strip()
                self._openapi_user_token = (config.get("openapi_user_token") or "").strip()
                self._openapi_redirect_uri = (config.get("openapi_redirect_uri") or "").strip()
                self._openapi_scope = (config.get("openapi_scope") or "").strip()
                self._openapi_authorize_code = self._extract_openapi_code(config.get("openapi_authorize_code"))
                has_openapi = bool(self._openapi_app_key and self._openapi_user_token)
                self._auth_mode = self._normalize_auth_mode(config.get("auth_mode"), bool(self._cookie), has_openapi)
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

                # 用户粘贴 OAuth 授权码后，用其自己的应用凭证自动换取 hdt_ Token（一次性），并回写本机配置
                if self._openapi_authorize_code and self._openapi_app_key:
                    exchanged_token = ""
                    try:
                        exchanged_token = self._exchange_openapi_code(self._openapi_authorize_code)
                    except Exception as e:
                        # 不输出授权码 / Token / 密钥明文
                        logger.warning(f"{self.plugin_name}: OPENAPI 授权码换取用户 Token 失败 - {e}")
                    if exchanged_token:
                        self._openapi_user_token = exchanged_token
                        self._openapi_authorize_code = ""
                        self._auth_mode = "openapi"
                        logger.info(f"{self.plugin_name}: 已用用户自填授权码换取 OPENAPI 用户授权 Token (hdt_)，凭证仅保存在本机")
                        try:
                            self.update_config(self._get_config())
                        except Exception as e:
                            logger.warning(f"{self.plugin_name}: 回写 OPENAPI 用户 Token 到本机配置失败 - {e}")

            if self._onlyonce:
                self._onlyonce = False
                self.update_config(self._get_config())
                if self._scheduler:
                    try:
                        self._scheduler.shutdown(wait=False)
                    except Exception:
                        pass
                    self._scheduler = None
                tz_obj = self._get_timezone()
                self._scheduler = BackgroundScheduler(timezone=tz_obj)
                logger.info(f"{self.plugin_name}: 立即执行一次签到任务")
                self._scheduler.add_job(
                    func=self._signin,
                    trigger="date",
                    run_date=datetime.now(tz=tz_obj) + timedelta(seconds=2),
                    name="栖影签到-即时执行"
                )
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

    @staticmethod
    def _extract_level_name(val: Any) -> str:
        """从字典、字符串或复杂对象中提纯等级名称"""
        if not val:
            return "初来乍到"
        if isinstance(val, dict):
            return str(val.get("name") or val.get("chinese") or val.get("title") or val.get("english") or val.get("key") or "初来乍到")
        if isinstance(val, str):
            s = val.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    parsed = ast.literal_eval(s)
                    if isinstance(parsed, dict):
                        return str(parsed.get("name") or parsed.get("chinese") or parsed.get("title") or parsed.get("english") or parsed.get("key") or "初来乍到")
                except Exception:
                    pass
                try:
                    import json
                    parsed = json.loads(s.replace("'", '"'))
                    if isinstance(parsed, dict):
                        return str(parsed.get("name") or parsed.get("chinese") or parsed.get("title") or parsed.get("english") or parsed.get("key") or "初来乍到")
                except Exception:
                    pass
            return s
        return str(val)

    @staticmethod
    def _format_user_display(user_info: Dict[str, Any]) -> str:
        """优雅格式化用户名，去重冗余的 UID: username 展现"""
        if not isinstance(user_info, dict):
            return "栖影用户"
        nickname = str(user_info.get("nickname") or "").strip()
        username = str(user_info.get("username") or "").strip()
        user_id = str(user_info.get("id") or "").strip()

        display_name = nickname or username or "栖影用户"
        if not user_id or user_id in ("--", "None", "null", "") or user_id == display_name or user_id == username:
            return display_name
        return f"{display_name} (UID: {user_id})"

    @staticmethod
    def _extract_streak_from_dict(data: Any) -> Optional[int]:
        """递归/多字段安全提取连续签到天数"""
        if not isinstance(data, dict):
            return None
        for k in ("streak", "checkin_streak", "consecutive_signin", "continuous_days", "continuous_checkins", "signin_streak"):
            if k in data and data[k] is not None:
                try:
                    v = int(data[k])
                    if v >= 0:
                        return v
                except (ValueError, TypeError):
                    pass
        for sub_key in ("stats", "checkin", "points_info", "points", "data", "user"):
            sub = data.get(sub_key)
            if isinstance(sub, dict):
                res = HDHavenSignin._extract_streak_from_dict(sub)
                if res is not None:
                    return res
        return None

    @staticmethod
    def _parse_checkin_notice_text(text: str) -> Dict[str, Any]:
        """
        从站点通知文本中提取连续签到天数、获得经验、结算公式及积分余额
        示例: '普通签到 5 + 等级加成 0 + 会员加成 0 = 5 积分；连续签到 1 天，获得 5 经验，当前余额 25 积分。'
        """
        res: Dict[str, Any] = {}
        if not text or not isinstance(text, str):
            return res

        m_streak = re.search(r"连续签到\s*([0-9]+)\s*天", text)
        if m_streak:
            res["streak"] = int(m_streak.group(1))

        m_exp = re.search(r"获得\s*([0-9]+)\s*(?:点)?(?:经验|EXP|exp)", text, re.I)
        if m_exp:
            res["exp"] = int(m_exp.group(1))

        m_bal = re.search(r"(?:当前余额|积分余额|当前积分)\s*([0-9.]+)\s*积分", text)
        if m_bal:
            try:
                res["balance"] = float(m_bal.group(1))
            except ValueError:
                pass

        m_formula = re.search(r"((?:普通|赌狗|阶梯)?签到\s*[0-9.+-/*\s]+=\s*[0-9.]+\s*积分)", text)
        if m_formula:
            res["formula"] = m_formula.group(1).strip()
        else:
            m_alt_formula = re.search(r"([^；;\n\r]+?=\s*[0-9.]+\s*积分)", text)
            if m_alt_formula:
                res["formula"] = m_alt_formula.group(1).strip()

        m_earned = re.search(r"(?:[+＋]|获得\s*|=\s*)([0-9.]+)\s*积分", text)
        if m_earned:
            try:
                res["earned"] = float(m_earned.group(1))
            except ValueError:
                pass

        return res

    def _synthesize_checkin_formula(self, mode: str, earned: float, user_info: Dict[str, Any]) -> str:
        """当未从通知接口获取到文字明细时，根据用户等级和VIP加成合成结算明细"""
        if mode == "gamble":
            return f"赌狗签到结算：获得 {earned:+g} 积分"
        level_info = user_info.get("level_info")
        if not isinstance(level_info, dict):
            raw_lvl = user_info.get("level")
            level_info = raw_lvl if isinstance(raw_lvl, dict) else {}
        bonus = self._to_number(level_info.get("checkin_bonus", 0), 0)
        vip_bonus = 0
        base = 5
        return f"普通签到 {base} + 等级加成 {int(bonus)} + 会员加成 {vip_bonus} = {int(earned) if earned == int(earned) else earned:g} 积分"

    def _fetch_latest_checkin_notice(self, session: requests.Session, proxies: Optional[dict]) -> Tuple[Optional[str], Dict[str, Any]]:
        """尝试从站点消息通知接口获取最近的签到结算明细"""
        if self._is_openapi_active:
            # OPENAPI 仅提供 /notifications，网页侧 overview/unread/messages 不可用
            candidate_urls = [self._api_url("/api/openapi/v1/notifications?limit=5")]
        else:
            candidate_urls = [
                self._api_url("/api/account/overview"),
                self._api_url("/api/account/unread"),
                self._api_url("/api/account/notifications?page=1&limit=5"),
                self._api_url("/api/notifications?limit=5"),
                self._api_url("/api/account/messages?limit=5"),
            ]
        for url in candidate_urls:
            try:
                resp = session.get(
                    url,
                    headers=self._build_request_headers(referer=f"{self._base_url}/me#account-points"),
                    proxies=proxies,
                    timeout=(self._connect_timeout, self._read_timeout)
                )
                if resp.status_code != 200:
                    continue
                try:
                    payload = resp.json()
                except Exception:
                    continue

                # 1. 优先解析 overview 聚合接口返回的 notifications 与 ledger
                if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                    data_obj = payload.get("data") or {}
                    notifs = data_obj.get("notifications") or []
                    ledger = data_obj.get("ledger") or []
                    for it in notifs:
                        if not isinstance(it, dict):
                            continue
                        title = str(it.get("title") or "")
                        content = str(it.get("message") or it.get("content") or "")
                        combined = f"{title}；{content}".strip("； ")
                        if "签到" in combined or "checkin" in combined.lower() or "积分" in combined:
                            parsed = self._parse_checkin_notice_text(combined)
                            for l_it in ledger:
                                if isinstance(l_it, dict) and ("签到" in str(l_it.get("reason", "")) or "checkin" in str(l_it.get("reason", "")).lower()):
                                    if parsed.get("earned") is None and l_it.get("delta") is not None:
                                        parsed["earned"] = self._to_number(l_it.get("delta"))
                                    if parsed.get("balance") is None and l_it.get("balance") is not None:
                                        parsed["balance"] = self._to_number(l_it.get("balance"))
                                    break
                            return combined, parsed

                items = []
                if isinstance(payload, list):
                    items = payload
                elif isinstance(payload, dict):
                    items = payload.get("data") or payload.get("items") or payload.get("notifications") or payload.get("messages") or []
                    if not isinstance(items, list):
                        items = [payload]

                for it in items:
                    if not isinstance(it, dict):
                        continue
                    title = str(it.get("title") or it.get("subject") or "")
                    content = str(it.get("content") or it.get("message") or it.get("body") or it.get("text") or "")
                    combined = f"{title} {content}".strip()
                    if "签到" in combined or "checkin" in combined.lower() or "积分" in combined:
                        text_to_parse = combined if title else content
                        parsed = self._parse_checkin_notice_text(text_to_parse)
                        return text_to_parse, parsed
            except Exception as err:
                logger.debug(f"{self.plugin_name}: 请求通知接口 {url} 异常 - {err}")
                continue
        return None, {}

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
            if "turnstile" in err_text.lower() or "cloudflare" in err_text.lower() or "人机" in err_text or "验证" in err_text or res.status_code in (400, 403):
                raise ValueError("检测到站点启用了 Cloudflare 人机验证 (Turnstile)，密码登录受阻。请在插件配置中切换为【Cookie 模式】并填入 hdh_session 会话。")
            raise ValueError(f"账号密码登录失败 - {err_text}")
        except RequestException as e:
            if isinstance(e, (ProxyError, ConnectTimeout, Timeout)):
                raise ValueError(f"代理网络异常，无法连接到栖影站点: {e}")
            raise

    def _fetch_user_profile(self, session: requests.Session, proxies: Optional[dict]) -> dict:
        url = self._api_url("/api/auth/me")
        res = session.get(
            url,
            headers=self._build_request_headers(referer=f"{self._base_url}/me"),
            proxies=proxies,
            timeout=(self._connect_timeout, self._read_timeout)
        )
        res_data = {}
        try:
            res_data = res.json()
        except Exception:
            res_data = {}

        err_type = self._classify_site_error(res, res_data)
        if err_type == "session_verify_required":
            raise SessionVerifyRequiredError("站点检测到网络出口变化，需在浏览器完成一次人机验证（/verify-session），或将插件代理出口与浏览器登录时保持一致")
        elif err_type == "session_device_changed":
            raise SessionDeviceChangedError("站点检测到登录设备或环境指纹变化，需在浏览器重新登录栖影，或在同一设备/网络环境完成验证后更新 hdh_session")
        elif err_type == "scrape_challenge_required":
            raise ScrapeChallengeRequiredError("触发站点访问频率风控 (SCRAPE_CHALLENGE_REQUIRED)，需延后重试")
        elif err_type == "app_required":
            raise AppRequiredError(self._app_required_message())
        elif err_type == "browser_required":
            msg = res_data.get("message") or res_data.get("error") or ""
            raise BrowserRequiredError(f"站点返回安全浏览器拦截 (HTTP 403: BROWSER_REQUIRED - {msg})")
        elif err_type == "cookie_session_revoked":
            raise CookieSessionRevokedError("站点已主动作废该 hdh_session 会话（响应头 Set-Cookie 清空），网页接口现已限制程序化 Cookie 直连；请改用 OPENAPI 授权模式，重新粘贴 Cookie 通常无效")
        elif err_type == "unauthorized":
            raise UnauthorizedError("登录态失效 (HTTP 401)，请更新 hdh_session 会话 Cookie")
        elif res.status_code != 200:
            raise ValueError(f"获取用户信息失败 - HTTP {res.status_code}")

        data = res_data

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

                raw_lvl = data_dict.get("level") or data_dict.get("class")
                if isinstance(raw_lvl, dict):
                    data_dict["level_info"] = raw_lvl
                data_dict["level"] = self._extract_level_name(raw_lvl or data_dict.get("class_name") or data_dict.get("role") or "初来乍到")

                checked = data_dict.get("checkin_today") if "checkin_today" in data_dict else data_dict.get("checkedInToday", False)
                data_dict["checkin_today"] = bool(checked)
                data_dict["checkedInToday"] = bool(checked)

                extracted_streak = self._extract_streak_from_dict(data_dict)
                if data_dict["checkin_today"] and (extracted_streak is None or extracted_streak < 1):
                    extracted_streak = 1
                streak = extracted_streak if extracted_streak is not None else 0
                data_dict["streak"] = streak
                data_dict["checkin_streak"] = streak

                data_dict["points"] = self._to_number(data_dict.get("points"), 0.0)
                data_dict["_updated_date"] = datetime.now().strftime("%Y-%m-%d")
                return data_dict
        return {}

    def _execute_checkin(self, session: requests.Session, proxies: Optional[dict], target_mode: str) -> Tuple[int, dict]:
        if target_mode == "gamble":
            url = self._api_url("/api/account/checkin/gamble")
        else:
            url = self._api_url("/api/account/checkin")

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

        err_type = self._classify_site_error(res, res_data)
        if err_type == "session_verify_required":
            raise SessionVerifyRequiredError("站点检测到网络出口变化，需在浏览器完成一次人机验证（/verify-session），或将插件代理出口与浏览器登录时保持一致")
        elif err_type == "session_device_changed":
            raise SessionDeviceChangedError("站点检测到登录设备或环境指纹变化，需在浏览器重新登录栖影，或在同一设备/网络环境完成验证后更新 hdh_session")
        elif err_type == "scrape_challenge_required":
            raise ScrapeChallengeRequiredError("触发站点访问频率风控 (SCRAPE_CHALLENGE_REQUIRED)，需延后重试")
        elif err_type == "app_required":
            raise AppRequiredError(self._app_required_message())
        elif err_type == "browser_required":
            msg = res_data.get("message") or res_data.get("error") or "BROWSER_REQUIRED"
            raise BrowserRequiredError(f"签到请求被站点拦截 (HTTP 403: BROWSER_REQUIRED - {msg})")
        elif err_type == "cookie_session_revoked":
            raise CookieSessionRevokedError("站点已主动作废该 hdh_session 会话（响应头 Set-Cookie 清空），网页接口现已限制程序化 Cookie 直连；请改用 OPENAPI 授权模式，重新粘贴 Cookie 通常无效")
        elif err_type == "unauthorized":
            raise UnauthorizedError("登录态失效 (HTTP 401)，请更新 hdh_session 会话 Cookie")

        return res.status_code, res_data

    def _signin(self, retry_index: int = 0) -> Dict[str, Any]:
        if not self._signin_lock.acquire(blocking=False):
            logger.warning(f"{self.plugin_name}: 已有签到任务正在执行中，跳过本次并发请求")
            return {
                "success": False,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": "已有签到任务正在执行中，跳过并发执行",
                "action": "skipped"
            }
        try:
            return self._execute_signin_flow(retry_index)
        finally:
            self._signin_lock.release()

    def _execute_signin_flow(self, retry_index: int = 0) -> Dict[str, Any]:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self._is_configured():
            if self._is_openapi_active or self._auth_mode == "openapi":
                msg = "未配置栖影 OPENAPI 凭证 (需填写你自己的 应用凭证 hda_ 与 用户授权 Token hdt_；应用编号 client_id 仅 OAuth 授权时使用)"
            elif self._auth_mode == "cookie":
                msg = "未配置栖影 Cookie (hdh_session)"
            else:
                msg = "未配置用户名或密码"
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

            # 1. 账号身份认证校验（实时获取最新状态）
            user_info = None
            try:
                user_info = self._fetch_user_profile(session, proxies)
                if user_info:
                    user_info["_updated_date"] = datetime.now().strftime("%Y-%m-%d")
                    self.save_data("user_info", user_info)
            except Exception as e:
                err_text = str(e)
                # 命中已知安全拦截或认证失效时，必须直接向外抛出中断执行
                if (
                    isinstance(e, (HDHavenError, SessionVerifyRequiredError, SessionDeviceChangedError, ScrapeChallengeRequiredError, AppRequiredError, BrowserRequiredError, UnauthorizedError))
                    or any(k in err_text for k in ("401", "403", "登录态失效", "SESSION_VERIFY_REQUIRED", "SESSION_DEVICE_CHANGED", "SCRAPE_CHALLENGE_REQUIRED", "APP_REQUIRED", "BROWSER_REQUIRED"))
                ):
                    raise
                # 超时与网络类异常 (Timeout, RequestException) 直接抛出，立即进入失败重试调度，
                # 避免在网络已阻断时仍盲目发起二次超时签到请求
                if isinstance(e, (RequestException, Timeout)) or "Timeout" in type(e).__name__ or "Connect" in type(e).__name__:
                    raise
                # 其他异常（如解析异常）：记录警告，允许尝试使用历史缓存兜底展示基础信息，但严禁将历史缓存当作今日签到依据！
                logger.warning(f"{self.plugin_name}: 获取用户信息异常 - {e}")
                user_info = None

            profile_for_display = user_info or (self.get_data("user_info") or {})
            user_display = self._format_user_display(profile_for_display)
            level_name = self._extract_level_name(profile_for_display.get("level"))
            is_vip = bool(profile_for_display.get("vip", False))
            vip_suffix = " (VIP)" if is_vip else ""
            current_points = self._to_number(profile_for_display.get("points", 0))

            # 检查今日是否已在其他端完成签到（必须以本次实时请求返回为准，绝对不能使用历史缓存）
            if user_info and user_info.get("checkin_today") is True:
                streak = self._extract_streak_from_dict(user_info)
                if streak is None or streak < 1:
                    streak = 1

                notice_text, notice_parsed = self._fetch_latest_checkin_notice(session, proxies)
                if notice_parsed.get("streak"):
                    streak = notice_parsed["streak"]
                if notice_parsed.get("balance") is not None:
                    current_points = self._to_number(notice_parsed["balance"], current_points)

                earned_val = notice_parsed.get("earned")
                if earned_val is None:
                    if self._signin_mode == "normal":
                        earned_val = 5.0
                        reward_display = "+5 积分"
                        formula = "今日已在站点完成签到 (普通签到基础奖励)"
                    else:
                        earned_val = 0.0
                        reward_display = "以站点账单为准"
                        formula = "今日已在站点完成签到 (博弈签到积分以站点账单为准)"
                else:
                    reward_display = f"+{earned_val:g} 积分"
                    formula = notice_parsed.get("formula") or f"获得 +{earned_val:g} 积分"

                exp_text = f"\n⭐ 获得经验：+{notice_parsed['exp']} EXP" if "exp" in notice_parsed else ""

                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": "今日已在其他端完成签到，无需重复操作",
                    "action": "already_signed",
                    "status": "already_signed_in",
                    "points_awarded": earned_val,
                    "points_change": earned_val,
                    "risk_downgraded": False,
                    "detail": f"今日已签到 ({formula})" if formula else "今日已签到，无需重复签到",
                    "mode": self._signin_mode,
                    "mode_name": self._signin_mode_options.get(self._signin_mode, "普通签到"),
                    "points": current_points,
                    "checkin_days": streak,
                    "proxy_status": proxy_desc,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【栖影签到】今日已签到 🟡",
                    text=(
                        f"━━━━━━━━━━━━━━━\n"
                        f"✨ 状态：今日已完成签到\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"👤 用户：{user_display}\n"
                        f"🎖️ 等级：{level_name}{vip_suffix}\n"
                        f"🎲 签到模式：{self._signin_mode_options.get(self._signin_mode, '普通签到')}\n"
                        f"🎁 今日奖励：{reward_display}\n"
                        f"💰 当前总积分：{current_points:g} 积分\n"
                        f"📅 连续签到：{streak} 天{exp_text}\n"
                        f"📝 签到明细：{formula}\n"
                        f"🌐 网络环境：{proxy_desc}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 检查时间：{timestamp}"
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
                        updated_profile["_updated_date"] = datetime.now().strftime("%Y-%m-%d")
                        self.save_data("user_info", updated_profile)
                        user_info = updated_profile
                        new_points = updated_profile.get("points", new_points)
                        streak = updated_profile.get("checkin_streak", 1)
                    else:
                        streak = self._extract_streak_from_dict(data_obj) or 1
                except Exception:
                    streak = self._extract_streak_from_dict(data_obj) or 1

                if streak is None or streak < 1:
                    streak = 1

                notice_text, notice_parsed = self._fetch_latest_checkin_notice(session, proxies)
                if notice_parsed.get("streak"):
                    streak = notice_parsed["streak"]
                if notice_parsed.get("balance") is not None:
                    new_points = notice_parsed["balance"]

                new_points_num = self._to_number(new_points, current_points + earned)
                formula = notice_parsed.get("formula") or self._synthesize_checkin_formula(target_mode, earned, user_info)
                exp_text = f"\n⭐ 获得经验：+{notice_parsed['exp']} EXP" if "exp" in notice_parsed else ""

                user_display = self._format_user_display(user_info)
                level_name = self._extract_level_name(user_info.get("level"))
                vip_suffix = " (VIP)" if is_vip else ""

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
                    "detail": formula or signed_msg,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【栖影签到】成功 🟢",
                    text=(
                        f"━━━━━━━━━━━━━━━\n"
                        f"✨ 状态：签到成功\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"👤 用户：{user_display}\n"
                        f"🎖️ 等级：{level_name}{vip_suffix}\n"
                        f"🎲 签到模式：{mode_name}\n"
                        f"🎁 获得积分：{earned:+g} 积分\n"
                        f"💰 当前总积分：{new_points_num:g} 积分\n"
                        f"📅 连续签到：{streak} 天{exp_text}\n"
                        f"📝 结算明细：{formula}\n"
                        f"🌐 网络环境：{proxy_desc}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 签到时间：{timestamp}"
                    ),
                )
                return result

            # HTTP 409 Conflict: 今日已签到
            elif status_code == 409:
                streak = self._extract_streak_from_dict(profile_for_display) or 1
                if streak < 1:
                    streak = 1

                notice_text, notice_parsed = self._fetch_latest_checkin_notice(session, proxies)
                if notice_parsed.get("streak"):
                    streak = notice_parsed["streak"]
                if notice_parsed.get("balance") is not None:
                    current_points = self._to_number(notice_parsed["balance"], current_points)

                earned_val = notice_parsed.get("earned")
                if earned_val is None:
                    if target_mode == "normal":
                        earned_val = 5.0
                        reward_display = "+5 积分"
                        formula = "今日已在站点完成签到 (普通签到基础奖励)"
                    else:
                        earned_val = 0.0
                        reward_display = "以站点账单为准"
                        formula = "今日已在站点完成签到 (博弈签到积分以站点账单为准)"
                else:
                    reward_display = f"+{earned_val:g} 积分"
                    formula = notice_parsed.get("formula") or f"获得 +{earned_val:g} 积分"

                exp_text = f"\n⭐ 获得经验：+{notice_parsed['exp']} EXP" if "exp" in notice_parsed else ""

                user_display = self._format_user_display(profile_for_display)
                level_name = self._extract_level_name(profile_for_display.get("level"))
                vip_suffix = " (VIP)" if is_vip else ""

                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": f"今日已完成签到，请勿重复操作 ({mode_name})",
                    "action": "already_signed",
                    "status": "already_signed_in",
                    "points_awarded": earned_val,
                    "points_change": earned_val,
                    "risk_downgraded": False,
                    "detail": f"今日已签到 ({formula})" if formula else "今日已签到，无需重复签到",
                    "mode": target_mode,
                    "mode_name": mode_name,
                    "points": current_points,
                    "checkin_days": streak,
                    "proxy_status": proxy_desc,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【栖影签到】今日已签到 🟡",
                    text=(
                        f"━━━━━━━━━━━━━━━\n"
                        f"✨ 状态：今日已完成签到\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"👤 用户：{user_display}\n"
                        f"🎖️ 等级：{level_name}{vip_suffix}\n"
                        f"🎲 签到模式：{mode_name}\n"
                        f"🎁 今日奖励：{reward_display}\n"
                        f"💰 当前总积分：{current_points:g} 积分\n"
                        f"📅 连续签到：{streak} 天{exp_text}\n"
                        f"📝 签到明细：{formula}\n"
                        f"🌐 网络环境：{proxy_desc}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 检查时间：{timestamp}"
                    ),
                )
                return result

            # 401 需先按 code 精确分类，避免把设备/出口变化误判为 Cookie 失效
            elif status_code == 401:
                err_type = self._classify_site_error(status_code, res_data)
                if err_type == "session_verify_required":
                    raise SessionVerifyRequiredError("站点检测到网络出口变化，需在浏览器完成一次人机验证（/verify-session），或将插件代理出口与浏览器登录时保持一致")
                if err_type == "session_device_changed":
                    raise SessionDeviceChangedError("站点检测到登录设备或环境指纹变化，需在浏览器重新登录栖影，或在同一设备/网络环境完成验证后更新 hdh_session")
                if err_type == "scrape_challenge_required":
                    raise ScrapeChallengeRequiredError("触发站点访问频率风控 (SCRAPE_CHALLENGE_REQUIRED)，需延后重试")
                if err_type == "app_required":
                    raise AppRequiredError(self._app_required_message())
                if err_type == "cookie_session_revoked":
                    raise CookieSessionRevokedError("站点已主动作废该 hdh_session 会话（响应头 Set-Cookie 清空），网页接口现已限制程序化 Cookie 直连；请改用 OPENAPI 授权模式")
                if err_type == "browser_required":
                    raise BrowserRequiredError("站点返回安全浏览器拦截 (HTTP 401: BROWSER_REQUIRED)")
                raise UnauthorizedError("登录态失效 (HTTP 401)，请更新 hdh_session 会话 Cookie")

            # 403 明确标识访问受限 / 安全拦截
            elif status_code == 403:
                err_text = self._format_http_error(None, res_data) if res_data else "HTTP 403 Forbidden"
                if "browser" in err_text.lower():
                    raise ValueError(f"签到请求被站点拦截 (HTTP 403: {err_text})")
                raise ValueError(f"签到请求访问受限 (HTTP 403) - {err_text}")

            # 其它 HTTP 异常状态码处理
            else:
                err_text = f"HTTP {status_code}: {res_data.get('message') or res_data.get('error') or '接口响应异常'}"
                raise ValueError(err_text)

        except Exception as err:
            err_msg = str(err)
            if isinstance(err, (ProxyError, ConnectTimeout)) or "ProxyError" in type(err).__name__:
                err_msg = f"代理梯子连接失败，请检查MoviePilot全局代理或自定义代理设置是否可用 ({err})"
            elif isinstance(err, (Timeout, ConnectTimeout)) or "Timeout" in type(err).__name__:
                err_msg = f"连接栖影站点超时，请检查代理梯子连通性或稍后重试 ({err})"
            logger.error(f"{self.plugin_name}: 执行签到失败 - {err_msg}")

            is_session_verify = (
                isinstance(err, SessionVerifyRequiredError)
                or "SESSION_VERIFY_REQUIRED" in err_msg
                or "网络出口变化" in err_msg
            )
            is_session_device_changed = (
                isinstance(err, SessionDeviceChangedError)
                or "SESSION_DEVICE_CHANGED" in err_msg
                or "登录设备" in err_msg
                or "环境指纹" in err_msg
            )
            is_scrape_challenge = (
                isinstance(err, ScrapeChallengeRequiredError)
                or "SCRAPE_CHALLENGE_REQUIRED" in err_msg
                or "访问频率风控" in err_msg
            )
            is_cookie_session_revoked = (
                isinstance(err, CookieSessionRevokedError)
                or "COOKIE_SESSION_REVOKED" in err_msg
                or "主动作废该 hdh_session" in err_msg
                or "Set-Cookie 清空" in err_msg
            )
            # APP_REQUIRED 仅认精确信号，避免与 Cookie 作废提示中的“改用 OPENAPI 授权”措辞混淆
            is_app_required = (
                not is_cookie_session_revoked
                and (
                    isinstance(err, AppRequiredError)
                    or "APP_REQUIRED" in err_msg
                    or "必须通过已审核应用调用" in err_msg
                )
            )
            is_auth_error = (
                isinstance(err, (UnauthorizedError, BrowserRequiredError))
                or (
                    not (is_session_verify or is_session_device_changed or is_scrape_challenge or is_app_required or is_cookie_session_revoked)
                    and any(k in err_msg for k in ("401", "403", "登录态失效", "BROWSER_REQUIRED", "Cookie 已失效"))
                )
            )

            next_retry_time = None
            if is_session_verify:
                # 网络出口变化：保留现有 pending 任务，严禁清空 pending_task，避免误判为失效
                action = "session_verify_required"
                status = "session_verify_required"
                title = "【栖影签到】网络出口变动 ⚠️"
                state_text = "⚠️ 状态：网络出口变动，需人机验证"
                advice = "站点检测到网络出口变化，需在浏览器完成一次人机验证（/verify-session），或将插件代理出口与浏览器登录时保持一致"
            elif is_session_device_changed:
                # 设备/环境指纹变化：保留现有 pending 任务，严禁清空 pending_task 或误报 Cookie 失效
                action = "session_device_changed"
                status = "session_device_changed"
                title = "【栖影签到】登录设备变化 ⚠️"
                state_text = "⚠️ 状态：登录设备/环境变化，需重新登录"
                advice = "站点检测到登录设备或环境指纹变化。请在浏览器重新登录栖影（或使用与插件相同的设备、UA 与网络出口完成验证），随后更新 hdh_session；这不是 Cookie 过期。"
            elif is_scrape_challenge:
                # 触发站点访问频率风控：归入 rate_limit 类，走指数退避自动重试
                action = "rate_limit"
                status = "rate_limit"
                title = "【栖影签到】频控拦截 ⚠️"
                state_text = "⚠️ 状态：触发站点访问频率风控，已自动延后重试"
                advice = "站点访问频次过高，插件已自动延后重试，请耐心等待，切勿频繁手动重试"
                backoff_delays = [60, 180, 300]
                delay_sec = backoff_delays[min(retry_index, len(backoff_delays) - 1)]
                if retry_index < self._retry_count:
                    next_retry_time = self._schedule_retry_signin(retry_index + 1, delay_sec=delay_sec)
                else:
                    self._clear_pending_task()
            elif is_cookie_session_revoked:
                # 服务端主动清空 hdh_session：程序化 Cookie 直连已被限制，引导改用 OPENAPI
                self._clear_pending_task()
                action = "cookie_session_revoked"
                status = "cookie_session_revoked"
                title = "【栖影签到】Cookie 会话已被站点作废 🔴"
                state_text = "⚠️ 状态：站点已作废 hdh_session，需改用 OPENAPI"
                advice = "站点在返回 401 的同时通过 Set-Cookie 主动清空了 hdh_session，说明服务端已作废该会话并限制程序化 Cookie 直连，重新粘贴 Cookie 通常无效。请前往 站点 → 个人中心 → OPENAPI 申请应用，并回填 应用编号 / 应用凭证(hda_) / 用户授权 Token(hdt_) 后切换到 OPENAPI 授权模式"
            elif is_app_required:
                # 站点要求官方 OPENAPI 授权：清理 pending 任务并给出与当前配置相符的指引
                self._clear_pending_task()
                action = "app_required"
                status = "app_required"
                if self._is_openapi_active:
                    # 已配置 OPENAPI 凭证仍被拒：问题是凭证本身，不能引导用户再去申请
                    title = "【栖影签到】OPENAPI 凭证未通过 ⚠️"
                    state_text = "⚠️ 状态：已配置 OPENAPI 凭证但被站点拒绝"
                    advice = "站点返回 APP_REQUIRED，说明当前 OPENAPI 凭证未通过审核或已失效。请核对 应用编号(client_id) / 应用凭证(hda_) / 用户授权 Token(hdt_) 是否正确、应用是否已审核通过、用户授权是否有效，或前往 站点 → 个人中心 → OPENAPI 确认应用状态"
                else:
                    title = "【栖影签到】需OPENAPI授权 ⚠️"
                    state_text = "⚠️ 状态：站点要求改用 OPENAPI 授权接入"
                    advice = "站点已要求程序接入改用 OPENAPI 授权，请前往 站点 → 个人中心 → OPENAPI 申请应用并回填 应用编号 / 应用凭证(hda_) / 用户授权 Token(hdt_)"
            elif is_auth_error:
                # 认证失效 / 浏览器拦截：清理 pending 任务并告警
                self._clear_pending_task()
                action = "auth_error"
                status = "auth_error"
                title = "【栖影签到】登录态失效 🔴"
                state_text = "⚠️ 状态：登录态已失效 (需更新配置)"
                if "browser" in err_msg.lower() or "403" in err_msg:
                    advice = "请求被站点安全策略拦截 (403 BROWSER_REQUIRED)，请检查浏览器伪装头或改用 OPENAPI 授权模式"
                else:
                    advice = "若确认未更换设备或网络出口，再更新 hdh_session；也可先在浏览器访问 /api/security/session 查看是否要求人机验证，避免把设备/出口变化误判为 Cookie 过期"
            else:
                action = "failed"
                status = "failed"
                if retry_index < self._retry_count:
                    next_retry_time = self._schedule_retry_signin(retry_index + 1)
                else:
                    self._clear_pending_task()
                title = "【栖影签到】异常 🔴"
                state_text = "⚠️ 状态：签到执行失败"
                advice = ""

            user_info = self.get_data("user_info") or {}
            user_display = self._format_user_display(user_info)
            result = {
                "success": False,
                "timestamp": timestamp,
                "message": err_msg,
                "action": action,
                "status": status,
                "detail": err_msg,
                "points_change": 0,
                "risk_downgraded": False,
                "retry_index": retry_index,
                "next_retry_time": next_retry_time,
                "is_retry_task": retry_index > 0,
                "proxy_status": proxy_desc,
            }
            self._record_history(result)

            if is_session_verify or is_session_device_changed or is_app_required or is_cookie_session_revoked or is_auth_error:
                notify_body = (
                    f"━━━━━━━━━━━━━━━\n"
                    f"{state_text}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"👤 用户：{user_display}\n"
                    f"❌ 失败原因：{err_msg}\n"
                    f"💡 处理建议：{advice}\n"
                    f"🌐 网络环境：{proxy_desc}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🕒 执行时间：{timestamp}"
                )
            elif is_scrape_challenge:
                notify_body = (
                    f"━━━━━━━━━━━━━━━\n"
                    f"{state_text}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"👤 用户：{user_display}\n"
                    f"❌ 拦截原因：{err_msg}\n"
                    f"💡 处理建议：{advice}\n"
                    f"🔄 重试进度：{retry_index}/{self._retry_count}\n"
                    f"⏰ 下次重试：{next_retry_time or '已达上限'}\n"
                    f"🌐 网络环境：{proxy_desc}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🕒 执行时间：{timestamp}"
                )
            else:
                notify_body = (
                    f"━━━━━━━━━━━━━━━\n"
                    f"{state_text}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"👤 用户：{user_display}\n"
                    f"❌ 失败原因：{err_msg}\n"
                    f"🔄 重试进度：{retry_index}/{self._retry_count}\n"
                    f"⏰ 下次重试：{next_retry_time or '无'}\n"
                    f"🌐 网络环境：{proxy_desc}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🕒 执行时间：{timestamp}"
                )
            self._notify_result(title=title, text=notify_body)
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
                self._scheduler = BackgroundScheduler(timezone=tz_obj)
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

    def _schedule_retry_signin(self, next_retry_index: int, delay_sec: Optional[int] = None) -> Optional[str]:
        interval = delay_sec if delay_sec is not None else max(self._retry_interval, 5)
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
                self._scheduler = BackgroundScheduler(timezone=tz_obj)
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

    def _clean_history(self, history: List[dict]) -> List[dict]:
        """
        清洗历史记录：
        1. 剔除完全重复或同时间戳（秒级）的冗余记录
        2. 同一自然日若有多条 already_signed，仅保留最新一条，防止单日重复记录
        3. 为旧记录自动补全 points_awarded，使历史明细与走势图正常展示
        """
        if not history or not isinstance(history, list):
            return []

        cleaned: List[dict] = []
        seen_timestamps = set()
        seen_day_already_signed = set()

        sorted_hist = sorted(history, key=lambda x: str(x.get("timestamp") or ""), reverse=True)

        for item in sorted_hist:
            if not isinstance(item, dict):
                continue
            ts = str(item.get("timestamp") or "").strip()
            if not ts:
                continue

            # 1. 剔除同时间戳冗余
            if ts in seen_timestamps:
                continue
            seen_timestamps.add(ts)

            # 2. 补全 points_awarded 字段（兼容旧版历史数据）
            if item.get("points_awarded") is None and item.get("action") in ("signed", "already_signed"):
                pts = self._to_number(item.get("points_change"))
                if pts is None or pts == 0:
                    detail_str = str(item.get("detail") or "") + " " + str(item.get("message") or "")
                    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*积分", detail_str)
                    if m:
                        pts = self._to_number(m.group(1), 5.0)
                    else:
                        pts = 5.0 if item.get("mode") != "gamble" else 0.0
                item["points_awarded"] = pts

            # 3. 同一自然日内的重复 already_signed 去重
            dt_val = self._parse_history_datetime(ts)
            if dt_val:
                day_key = dt_val.strftime("%Y-%m-%d")
                if item.get("action") == "already_signed":
                    if day_key in seen_day_already_signed:
                        continue
                    seen_day_already_signed.add(day_key)

            cleaned.append(item)

        return cleaned

    def _record_history(self, record: Dict[str, Any]) -> None:
        history = self.get_data("history") or []
        if not isinstance(history, list):
            history = []

        new_ts = str(record.get("timestamp") or "").strip()
        new_dt = self._parse_history_datetime(new_ts)
        new_day = new_dt.strftime("%Y-%m-%d") if new_dt else None
        new_action = record.get("action")

        updated = False
        # 如果历史中已经存在同时间戳或同一天的 already_signed 记录，直接更新替换
        for idx, item in enumerate(history):
            if not isinstance(item, dict):
                continue
            item_ts = str(item.get("timestamp") or "").strip()
            if item_ts == new_ts:
                history[idx] = record
                updated = True
                break
            if new_action == "already_signed" and item.get("action") == "already_signed" and new_day:
                item_dt = self._parse_history_datetime(item_ts)
                if item_dt and item_dt.strftime("%Y-%m-%d") == new_day:
                    history[idx] = record
                    updated = True
                    break

        if not updated:
            history.insert(0, record)

        # 执行清洗与截断
        history = self._clean_history(history)
        if len(history) > self._history_count:
            history = history[:self._history_count]

        self.save_data("history", history)
        self.save_data("latest_result", record)

    def _notify_result(self, title: str, text: str) -> None:
        if not self._notify:
            return
        try:
            mtype = getattr(NotificationType, "SiteMessage", getattr(NotificationType, "Plugin", getattr(NotificationType, "Manual", None)))
            self.post_message(
                mtype=mtype,
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
        recorded_days = set()

        for item in history:
            if not isinstance(item, dict):
                continue
            dt_val = self._parse_history_datetime(item.get("timestamp"))
            if not dt_val or dt_val.year != now.year or dt_val.month != now.month:
                continue
            if item.get("action") not in ("signed", "already_signed"):
                continue

            day = dt_val.day
            # 关键：同一自然日只计入一次有效签到积分，坚决防止重复记分
            if day in recorded_days:
                continue

            awarded = self._to_number(item.get("points_awarded"))
            if awarded is None:
                awarded = 5.0 if item.get("mode") != "gamble" else 0.0

            points_by_day[day] = awarded
            recorded_days.add(day)

        # 保底检查：若当前账号今日已签到，但当天历史缺失或为0，计入 5.0 分 (防旧缓存污染：必须是今日更新的数据)
        user_info = self.get_data("user_info") or {}
        today_str = now.strftime("%Y-%m-%d")
        if user_info.get("checkin_today") and user_info.get("_updated_date") == today_str and points_by_day[now.day] == 0:
            points_by_day[now.day] = 5.0

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

        zero_y = y_at(0)
        area_d = f"{path_d} L {pts[-1][0]:.1f} {zero_y:.1f} L {pts[0][0]:.1f} {zero_y:.1f} Z"

        grid_nodes = []
        for i in range(5):
            val = y_min + (y_max - y_min) * i / 4
            y = y_at(val)
            grid_nodes.append({
                "component": "line",
                "props": {"x1": left, "y1": y, "x2": width - right, "y2": y, "stroke": "currentColor", "stroke-opacity": 0.15, "stroke-width": 1, "stroke-dasharray": "4 4"}
            })
            grid_nodes.append({
                "component": "text",
                "props": {"x": left - 10, "y": y + 4, "text-anchor": "end", "fill": "currentColor", "fill-opacity": 0.65, "font-size": 11},
                "text": f"{val:.0f}"
            })

        x_indexes = sorted(set([0, len(series) - 1, max(0, len(series) // 4), max(0, len(series) // 2), max(0, len(series) * 3 // 4)]))
        x_labels = [
            {"component": "text", "props": {"x": x_at(idx), "y": height - 16, "text-anchor": "middle", "fill": "currentColor", "fill-opacity": 0.65, "font-size": 11}, "text": f"{series[idx]['day']}日"}
            for idx in x_indexes if 0 <= idx < len(series)
        ]

        chart_elements = [
            {
                "component": "defs",
                "content": [
                    {
                        "component": "linearGradient",
                        "props": {"id": "hdh_chart_grad", "x1": "0%", "y1": "0%", "x2": "0%", "y2": "100%"},
                        "content": [
                            {"component": "stop", "props": {"offset": "0%", "stop-color": "#3b82f6", "stop-opacity": "0.35"}},
                            {"component": "stop", "props": {"offset": "100%", "stop-color": "#3b82f6", "stop-opacity": "0.02"}}
                        ]
                    }
                ]
            },
            *grid_nodes,
            {"component": "line", "props": {"x1": left, "y1": zero_y, "x2": width - right, "y2": zero_y, "stroke": "currentColor", "stroke-opacity": 0.35, "stroke-width": 1.2}},
            {"component": "path", "props": {"d": area_d, "fill": "url(#hdh_chart_grad)"}},
            {"component": "path", "props": {"d": path_d, "fill": "none", "stroke": "#3b82f6", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round"}},
        ]

        for i, it in enumerate(series):
            x, y = pts[i]
            p_val = self._to_number(it.get("points"), 0.0)
            if p_val > 0:
                chart_elements.append({
                    "component": "circle",
                    "props": {"cx": x, "cy": y, "r": 5.5, "fill": "#10b981", "stroke": "currentColor", "stroke-opacity": 0.8, "stroke-width": 2}
                })
                chart_elements.append({
                    "component": "text",
                    "props": {"x": x, "y": y - 10, "text-anchor": "middle", "fill": "#10b981", "font-size": 11, "font-weight": "bold"},
                    "text": f"+{p_val:g}"
                })
            elif p_val < 0:
                chart_elements.append({
                    "component": "circle",
                    "props": {"cx": x, "cy": y, "r": 5.5, "fill": "#ef4444", "stroke": "currentColor", "stroke-opacity": 0.8, "stroke-width": 2}
                })
                chart_elements.append({
                    "component": "text",
                    "props": {"x": x, "y": y + 16, "text-anchor": "middle", "fill": "#ef4444", "font-size": 11, "font-weight": "bold"},
                    "text": f"{p_val:g}"
                })
            else:
                chart_elements.append({
                    "component": "circle",
                    "props": {"cx": x, "cy": y, "r": 3.0, "fill": "#3b82f6", "fill-opacity": 0.7}
                })

        chart_elements.extend(x_labels)

        return {
            "component": "div",
            "props": {"style": "width: 100%; overflow-x: auto;"},
            "content": [
                {
                    "component": "svg",
                    "props": {"viewBox": f"0 0 {width} {height}", "style": "width: 100%; min-width: 600px; height: auto; display: block;"},
                    "content": chart_elements
                }
            ]
        }

    @staticmethod
    def _section_card(color_or_bg: str, icon: str, title: str, content: List[dict], badge: Optional[dict] = None) -> Dict[str, Any]:
        color_map = {
            "#f8fafc": "primary",
            "#f0fdf4": "success",
            "#eff6ff": "info",
            "#fffbeb": "warning",
        }
        icon_color = color_map.get(color_or_bg, color_or_bg)
        if not icon_color or icon_color.startswith("#"):
            icon_color = "primary"

        header_items = [
            {
                "component": "div",
                "props": {"class": "d-flex align-center ga-2"},
                "content": [
                    {"component": "VIcon", "props": {"size": 22, "color": icon_color}, "text": icon},
                    {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold"}, "text": title},
                ]
            }
        ]
        if badge:
            header_items.append(badge)

        return {
            "component": "VCard",
            "props": {
                "variant": "flat",
                "color": "surface",
                "border": True,
                "class": "mb-4 rounded-lg overflow-hidden",
            },
            "content": [
                {
                    "component": "VCardItem",
                    "props": {"class": "px-4 pt-4 pb-2"},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "d-flex align-center justify-space-between flex-wrap ga-2"},
                            "content": header_items,
                        }
                    ]
                },
                {
                    "component": "VCardText",
                    "props": {"class": "px-4 pb-4 pt-1"},
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
            "openapi_app_id": self._openapi_app_id,
            "openapi_app_key": self._openapi_app_key,
            "openapi_user_token": self._openapi_user_token,
            "openapi_redirect_uri": self._openapi_redirect_uri,
            "openapi_scope": self._openapi_scope,
            "openapi_authorize_code": self._openapi_authorize_code,
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
                                                                {"title": "Cookie 会话模式 (站点已限制直连，需保持出口一致)", "value": "cookie"},
                                                                {"title": "OPENAPI 授权模式 (推荐/官方API模式，免人机验证)", "value": "openapi"},
                                                                {"title": "账号密码模式 (站点已开启人机验证，不可用)", "value": "password"}
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
                                                            "hint": "站点已限制程序化 Cookie 直连，服务端会在 401 时主动清空 hdh_session，强烈建议优先使用 OPENAPI。若仍使用 Cookie，请确保插件代理出口、User-Agent 与浏览器登录时完全一致，避免触发 SESSION_VERIFY_REQUIRED / SESSION_DEVICE_CHANGED。",
                                                            "persistent-hint": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "openapi_app_id", "label": "OPENAPI 应用编号 / client_id (选填)", "placeholder": "站点 个人中心 → OPENAPI → 我的应用", "hint": "OAuth 授权用，非机密；每位用户填写自己申请的应用编号", "persistent-hint": True}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "openapi_app_key", "label": "OPENAPI 应用凭证 / hda_ 应用密钥 (选填)", "type": "password", "placeholder": "审核通过后由站点签发，形如 hda_...", "hint": "仅保存在本机插件配置，插件不内置、不上传任何密钥", "persistent-hint": True}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "openapi_user_token", "label": "OPENAPI 用户授权 Token / hdt_ (选填)", "type": "password", "placeholder": "完成 OAuth 授权后换取，形如 hdt_...", "hint": "每位用户各自授权、各自填写，长期有效", "persistent-hint": True}}]},
                                            {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "comfortable", "class": "mb-2", "text": "OPENAPI 凭证必须由每位用户使用自己在站点申请的应用：插件不内置、不共享任何应用编号/应用凭证/Token。审核通过后在站点复制应用凭证(hda_)，按下方 OAuth 步骤授权换取自己的用户 Token(hdt_)。"}}]},
                                            {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VAlert", "props": {"type": "warning", "variant": "tonal", "density": "comfortable", "class": "mb-2", "text": "OAuth 换取 hdt_ 步骤：① 填好你自己的应用编号与 hda_ 应用凭证并保存；② 在浏览器打开 https://hdhaven.com/oauth/authorize?response_type=code&client_id=你的应用编号&redirect_uri=你的回调地址&scope=你的授权范围&state=任意随机串 ；③ 授权后从回调地址复制 code=... 或整条链接；④ 粘贴到下方「OAuth 授权码 / 回调链接」并保存，插件会用你的 hda_ 自动换取 hdt_。"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "openapi_redirect_uri", "label": "OAuth 回调地址 redirect_uri (选填)", "placeholder": "须与申请应用时登记的回调一致", "hint": "用于换取 hdt_ 用户 Token，需与站点应用登记的回调地址一致", "persistent-hint": True}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "openapi_scope", "label": "OAuth 授权范围 scope (选填)", "placeholder": "如 checkin account，多个以空格分隔；留空用站点默认", "persistent-hint": True}}]},
                                            {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextField", "props": {"model": "openapi_authorize_code", "label": "OAuth 授权码 / 回调链接 (选填，保存后自动换取 hdt_ Token)", "placeholder": "粘贴浏览器授权后回调地址里的 code=... 或整条回调链接", "hint": "每位用户使用自己应用的授权；保存后插件用你的 hda_ 自动换取 hdt_ 并清空此栏", "persistent-hint": True}}]},
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
        raw_history = self.get_data("history") or []
        history = self._clean_history(raw_history)
        if len(history) != len(raw_history) or any(h.get("points_awarded") != r.get("points_awarded") for h, r in zip(history, raw_history) if isinstance(h, dict) and isinstance(r, dict)):
            self.save_data("history", history)

        latest = self.get_data("latest_result") or (history[0] if history else {})
        user_info = self.get_data("user_info") or {}

        username = self._format_user_display(user_info)
        user_id = str(user_info.get("id", "--")).strip()
        level = self._extract_level_name(user_info.get("level", "初来乍到"))
        is_vip = bool(user_info.get("vip", False))
        avatar_char = (user_info.get("nickname") or user_info.get("username") or "栖")[0].upper()

        current_points = user_info.get("points", latest.get("points", "--"))
        raw_streak = self._extract_streak_from_dict(user_info)
        if raw_streak is None or raw_streak == 0:
            raw_streak = latest.get("checkin_days")
        if user_info.get("checkin_today") and (not raw_streak or raw_streak == "--" or raw_streak == 0):
            raw_streak = 1
        streak = raw_streak if raw_streak is not None and raw_streak != "" else "--"

        if not user_id or user_id in ("--", "None", "null", "") or user_id == username or user_id == str(user_info.get("nickname", "")) or user_id == str(user_info.get("username", "")):
            uid_subtitle = "账号会话正常"
        else:
            uid_subtitle = f"UID: {user_id} · 会话正常"

        proxy_enabled, proxy_desc = self._get_proxy_status_display()
        signin_mode_name = self._signin_mode_options.get(self._signin_mode, "普通签到")

        series, month_total, month_peak = self._build_month_points_series(history)

        auth_display = "OPENAPI 授权" if self._is_openapi_active else ("Cookie 会话" if self._auth_mode == "cookie" else "账号密码")
        action_labels = {
            "signed": ("签到成功", "success"),
            "already_signed": ("今日已签到", "info"),
            "failed": ("签到失败", "error"),
            "auth_error": ("登录态失效", "error"),
            "config_required": ("待配置", "warning"),
            "session_verify_required": ("出口变化待验证", "warning"),
            "session_device_changed": ("设备变化待登录", "warning"),
            "rate_limit": ("频控延后重试", "warning"),
            "app_required": ("需OPENAPI授权", "warning"),
            "cookie_session_revoked": ("Cookie已作废", "error"),
        }
        latest_act = latest.get("action", "")
        act_text, act_color = action_labels.get(latest_act, ("暂无记录", "default"))

        status_chips = [
            {"component": "VChip", "props": {"color": "success" if self._enabled else "default", "variant": "tonal", "size": "small"}, "text": f"插件: {'已启用' if self._enabled else '未启用'}"},
            {"component": "VChip", "props": {"color": "primary", "variant": "tonal", "size": "small"}, "text": f"定时: {self._cron or '未设置'}"},
            {"component": "VChip", "props": {"color": "info" if proxy_enabled else "warning", "variant": "tonal", "size": "small"}, "text": f"梯子: {proxy_desc}"},
            {"component": "VChip", "props": {"color": "indigo", "variant": "tonal", "size": "small"}, "text": f"鉴权: {auth_display}"},
            {"component": "VChip", "props": {"color": "purple", "variant": "tonal", "size": "small"}, "text": f"默认模式: {signin_mode_name}"},
            {"component": "VChip", "props": {"color": act_color, "variant": "tonal", "size": "small"}, "text": f"最新状态: {act_text}"},
        ]

        table_rows = []
        for h in history[:15]:
            h_action = h.get("action", "")
            h_text, h_color = action_labels.get(h_action, ("未知", "default"))
            awarded = h.get("points_awarded")
            if awarded is not None:
                awarded_num = self._to_number(awarded, 0.0)
                awarded_display = f"{awarded_num:+g}"
                if awarded_num > 0:
                    awarded_class = "py-2 font-weight-bold text-success"
                elif awarded_num < 0:
                    awarded_class = "py-2 font-weight-bold text-error"
                else:
                    awarded_class = "py-2 font-weight-bold text-medium-emphasis"
            else:
                awarded_display = "--"
                awarded_class = "py-2 font-weight-bold text-medium-emphasis"

            table_rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "props": {"class": "text-caption py-2"}, "text": h.get("timestamp", "--")},
                    {"component": "td", "props": {"class": "py-2"}, "content": [{"component": "VChip", "props": {"size": "x-small", "color": "purple", "variant": "tonal"}, "text": h.get("mode_name", h.get("mode", "--"))}]},
                    {"component": "td", "props": {"class": "py-2"}, "content": [{"component": "VChip", "props": {"size": "x-small", "color": h_color, "variant": "tonal"}, "text": h_text}]},
                    {"component": "td", "props": {"class": awarded_class}, "text": awarded_display},
                    {"component": "td", "props": {"class": "py-2 font-weight-bold"}, "text": str(h.get("points", "--"))},
                    {"component": "td", "props": {"class": "py-2 text-caption text-medium-emphasis"}, "text": h.get("proxy_status", "--")},
                    {"component": "td", "props": {"class": "py-2 text-caption text-truncate", "style": "max-width: 260px;"}, "text": h.get("message", "--")},
                ]
            })

        if not table_rows:
            table_rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "props": {"colspan": 7, "class": "text-center text-caption py-4 text-medium-emphasis"}, "text": "暂无历史签到记录"}
                ]
            })

        page_cards = []
        if latest_act == "auth_error":
            page_cards.append({
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "icon": "mdi-alert-circle-outline",
                    "class": "mb-4 rounded-lg",
                    "title": "栖影站点登录态已失效 (HTTP 401/403)",
                    "text": f"最近一次签到失败：{latest.get('message', '登录态失效')}。请前往插件设置中更新 hdh_session 会话 Cookie 并保存。"
                }
            })
        elif latest_act == "session_verify_required":
            page_cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "icon": "mdi-shield-alert-outline",
                    "class": "mb-4 rounded-lg",
                    "title": "站点检测到网络出口变化 (SESSION_VERIFY_REQUIRED)",
                    "text": f"最近一次签到被拦截：{latest.get('message', '')}。请保持插件代理与浏览器登录出口一致，并在浏览器访问 /verify-session 完成人机验证。"
                }
            })
        elif latest_act == "session_device_changed":
            page_cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "icon": "mdi-laptop-off",
                    "class": "mb-4 rounded-lg",
                    "title": "站点检测到登录设备/环境变化 (SESSION_DEVICE_CHANGED)",
                    "text": f"最近一次签到被拦截：{latest.get('message', '')}。请在浏览器重新登录栖影（或使用与插件相同的设备、UA 与网络出口完成验证）后更新 hdh_session；这不是 Cookie 过期。"
                }
            })
        elif latest_act in ("rate_limit", "scrape_challenge_required"):
            page_cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "icon": "mdi-speedometer-slow",
                    "class": "mb-4 rounded-lg",
                    "title": "触发站点访问频率风控 (SCRAPE_CHALLENGE_REQUIRED)",
                    "text": f"最近一次签到触发站点频率风控：{latest.get('message', '')}。插件已自动延后指数退避重试，无需重新配置。"
                }
            })
        elif latest_act == "app_required":
            if self._is_openapi_active:
                app_req_title = "OPENAPI 凭证未通过 (APP_REQUIRED)"
                app_req_text = f"最近一次签到失败：{latest.get('message', '')}。已配置 OPENAPI 凭证但被站点拒绝，请核对 应用编号 / 应用凭证(hda_) / 用户授权 Token(hdt_)、应用审核状态与授权是否有效。"
            else:
                app_req_title = "站点要求改用 OPENAPI 授权 (APP_REQUIRED)"
                app_req_text = f"站点已限制程序直连：{latest.get('message', '')}。请前往 站点 → 个人中心 → OPENAPI 申请凭证并在插件设置中配置。"
            page_cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "icon": "mdi-api",
                    "class": "mb-4 rounded-lg",
                    "title": app_req_title,
                    "text": app_req_text
                }
            })
        elif latest_act == "cookie_session_revoked":
            page_cards.append({
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "icon": "mdi-cookie-off",
                    "class": "mb-4 rounded-lg",
                    "title": "站点已主动作废 hdh_session 会话 (COOKIE_SESSION_REVOKED)",
                    "text": f"最近一次签到失败：{latest.get('message', '')}。站点在返回 401 的同时通过 Set-Cookie 清空了 hdh_session，重新粘贴 Cookie 通常无效。请改用 OPENAPI 授权模式（站点 → 个人中心 → OPENAPI）。"
                }
            })

        page_cards.extend([
            self._section_card(
                "primary",
                "mdi-information-outline",
                "运行状态与环境",
                [{"component": "div", "props": {"class": "d-flex flex-wrap ga-2 align-center"}, "content": status_chips}]
            ),
            self._section_card(
                "success",
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
                                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": uid_subtitle}
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "div",
                                "props": {"class": "d-flex flex-wrap ga-3"},
                                "content": [
                                    {
                                        "component": "VCard",
                                        "props": {
                                            "variant": "tonal",
                                            "color": "primary",
                                            "class": "pa-3 text-center rounded-lg",
                                            "style": "min-width: 110px;",
                                        },
                                        "content": [
                                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "当前总积分"},
                                            {"component": "div", "props": {"class": "text-h6 font-weight-bold text-primary"}, "text": str(current_points)}
                                        ]
                                    },
                                    {
                                        "component": "VCard",
                                        "props": {
                                            "variant": "tonal",
                                            "color": "success",
                                            "class": "pa-3 text-center rounded-lg",
                                            "style": "min-width: 110px;",
                                        },
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
                "info",
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
                "warning",
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
        ])

        return [
            {
                "component": "div",
                "props": {"class": "pa-1"},
                "content": page_cards
            }
        ]
