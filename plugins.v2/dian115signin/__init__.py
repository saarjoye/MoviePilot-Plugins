from calendar import monthrange
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pytz
import random
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas import NotificationType


class Dian115Signin(_PluginBase):
    # 插件名称
    plugin_name = "巅影签到魔改版"
    # 插件描述
    plugin_desc = "癫影站点自动执行每日签到。支持普通签到与运气签到，可配置默认签到模式。"
    # 插件图标 (已转为raw直链以供页面渲染)
    plugin_icon = "https://raw.githubusercontent.com/saarjoye/MoviePilot-Plugins/main/icons/Dian115Signin.svg"
    # 插件版本
    plugin_version = "1.0.4"
    # 插件作者
    plugin_author = "wYw"
    # 作者主页
    author_url = "https://github.com/saarjoye/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "dian115signin_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1

    _enabled: bool = False
    _notify: bool = True
    _onlyonce: bool = False
    _cron: Optional[str] = None
    _portal_token: str = ""
    _use_proxy: bool = False
    _history_count: int = 30
    _random_time_range: str = ""
    _retry_count: int = 0
    _retry_interval: int = 5
    _connect_timeout: int = 10
    _read_timeout: int = 30
    _user_agent: str = ""
    _visitor_id: str = ""
    _signin_mode: str = "normal"
    _browser_proof: str = ""
    _browser_proof_expires_at: float = 0

    _signin_mode_options: Dict[str, str] = {
        "normal": "普通签到",
        "lucky": "运气签到",
    }
    _lucky_tier_options: Dict[str, str] = {
        "jackpot": "大奖",
        "normal": "平手",
        "blank": "空签",
        "penalty": "倒霉",
    }

    _base_url: str = "https://m.dian115.com"
    _default_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    )
    _scheduler: Optional[BackgroundScheduler] = None

    def __init__(self):
        super().__init__()

    @staticmethod
    def _to_bool(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() == "true"
        return bool(val)

    @staticmethod
    def _to_int(val: Any, default: int = 0) -> int:
        try:
            return int(val)
        except Exception:
            return default

    @classmethod
    def _normalize_signin_mode(cls, raw_value: Any) -> str:
        mode = str(raw_value or "normal").strip().lower()
        return mode if mode in cls._signin_mode_options else "normal"

    @staticmethod
    def _now_ts() -> float:
        return datetime.now().timestamp()

    @staticmethod
    def _generate_visitor_id() -> str:
        raw_value = f"v_{int(datetime.now().timestamp() * 1000):x}_{random.random():.12f}"
        return "".join(ch for ch in raw_value if ch.isalnum() or ch in "_.-")[:80]

    @staticmethod
    def _normalize_portal_token(raw_value: Any) -> str:
        """Extract portal_token from a token value, Cookie header, or Set-Cookie-like text."""
        raw_text = str(raw_value or "").strip().strip('"').strip("'")
        if not raw_text:
            return ""

        for line in raw_text.replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line:
                continue
            lower_line = line.lower()
            if lower_line.startswith("cookie:"):
                raw_text = line.split(":", 1)[1].strip()
                break
            if "portal_token=" in line:
                raw_text = line
                break

        if "portal_token=" not in raw_text:
            return raw_text

        try:
            cookie = SimpleCookie()
            cookie.load(raw_text)
            morsel = cookie.get("portal_token")
            if morsel:
                return morsel.value.strip().strip('"').strip("'")
        except Exception:
            pass

        for part in raw_text.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name.strip() == "portal_token":
                return value.strip().strip('"').strip("'")

        return raw_text.split("portal_token=", 1)[1].split(";", 1)[0].strip().strip('"').strip("'")

    @classmethod
    def _normalize_cookie_input(cls, raw_value: Any) -> str:
        """Normalize user input while preserving extra browser cookies when provided."""
        raw_text = str(raw_value or "").strip().strip('"').strip("'")
        if not raw_text:
            return ""

        for line in raw_text.replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line:
                continue
            lower_line = line.lower()
            if lower_line.startswith("cookie:"):
                raw_text = line.split(":", 1)[1].strip()
                break
            if "portal_token=" in line:
                raw_text = line
                break

        if "portal_token=" not in raw_text:
            return cls._normalize_portal_token(raw_text)

        cookie_pairs: Dict[str, str] = {}
        try:
            cookie = SimpleCookie()
            cookie.load(raw_text)
            cookie_pairs = {key: morsel.value for key, morsel in cookie.items() if morsel.value}
        except Exception:
            cookie_pairs = {}

        if not cookie_pairs:
            ignored_attrs = {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite"}
            for part in raw_text.split(";"):
                name, separator, value = part.strip().partition("=")
                if not separator:
                    continue
                name = name.strip()
                if not name or name.lower() in ignored_attrs:
                    continue
                cookie_pairs[name] = value.strip().strip('"').strip("'")

        if "portal_token" not in cookie_pairs:
            cookie_pairs["portal_token"] = cls._normalize_portal_token(raw_text)

        return "; ".join(f"{name}={value}" for name, value in cookie_pairs.items() if value)

    def _get_portal_token_value(self) -> str:
        return self._normalize_portal_token(self._portal_token)

    def _build_cookie_header(self) -> str:
        cookie_text = self._normalize_cookie_input(self._portal_token)
        if not cookie_text:
            return ""
        if "portal_token=" in cookie_text:
            return cookie_text
        return f"portal_token={cookie_text}"

    def _ensure_visitor_id(self) -> str:
        visitor_id = (self._visitor_id or "").strip()
        if visitor_id:
            return visitor_id

        cached_value = ""
        try:
            cached_value = str(self.get_data("visitor_id") or "").strip()
        except Exception:
            cached_value = ""

        visitor_id = cached_value or self._generate_visitor_id()
        self._visitor_id = visitor_id
        try:
            self.save_data("visitor_id", visitor_id)
        except Exception as err:
            logger.debug(f"{self.plugin_name}: 保存 visitor_id 时忽略错误 - {err}")
        return visitor_id

    def _build_request_headers(
            self,
            referer: str,
            include_content_type: bool = False,
            current_path: str = "/me",
            browser_proof: Optional[str] = None
    ) -> Dict[str, str]:
        headers = {
            "User-Agent": self._user_agent or self._default_user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": self._base_url,
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
            "X-Portal-Visitor-ID": self._ensure_visitor_id(),
            "X-Portal-Current-Path": current_path[:160],
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if include_content_type:
            headers["Content-Type"] = "application/json"
        if browser_proof:
            headers["X-Portal-Browser-Proof"] = browser_proof

        cookie_header = self._build_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    @staticmethod
    def _needs_browser_proof_refresh(res_data: Optional[Dict[str, Any]]) -> bool:
        code = str((res_data or {}).get("code") or "").lower()
        message = str((res_data or {}).get("message") or (res_data or {}).get("msg") or (res_data or {}).get("error") or "").lower()
        return code in {"browser_proof_required", "browser_proof_invalid"} or message == "browser proof required"

    @staticmethod
    def _format_http_error(response: requests.Response, res_data: Optional[Dict[str, Any]] = None) -> str:
        if res_data:
            api_message = res_data.get("message") or res_data.get("msg") or res_data.get("error")
            if api_message:
                if str(api_message).lower() == "browser proof required":
                    return (
                        "browser proof required（站点要求浏览器证明；插件已支持自动获取 proof，"
                        "若仍失败请重新保存有效 Cookie，并确认 User-Agent 与登录浏览器一致）"
                    )
                return str(api_message)

        if response.status_code == 403:
            return "HTTP 状态码: 403（服务器拒绝请求，请确认 portal_token 未过期；若只填 token 仍失败，请粘贴浏览器里的完整 Cookie）"
        if response.status_code == 401:
            return "HTTP 状态码: 401（登录凭证无效或已过期，请重新抓取 Cookie）"
        return f"HTTP 状态码: {response.status_code}"

    def _get_browser_proof(self, session: requests.Session, proxies, force_refresh: bool = False) -> Optional[str]:
        now_ts = self._now_ts()
        if not force_refresh and self._browser_proof and self._browser_proof_expires_at - now_ts > 30:
            return self._browser_proof

        url = f"{self._base_url}/api/portal/auth/browser-challenge"
        headers = self._build_request_headers(
            referer=f"{self._base_url}/me",
            include_content_type=True,
            current_path="/me"
        )
        response = session.get(
            url,
            headers=headers,
            proxies=proxies,
            timeout=(self._connect_timeout, self._read_timeout)
        )
        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code != 200:
            raise ValueError(self._format_http_error(response, data))

        if data.get("enabled") is False:
            self._browser_proof = ""
            self._browser_proof_expires_at = 0
            return None

        proof = str(data.get("proof") or "").strip()
        if not proof:
            return None

        ttl = self._to_int(data.get("ttl", 600), 600)
        ttl = max(ttl, 60)
        self._browser_proof = proof
        self._browser_proof_expires_at = now_ts + ttl
        return proof

    def _portal_request(
            self,
            session: requests.Session,
            method: str,
            api_path: str,
            proxies,
            referer_path: str,
            payload: Optional[Dict[str, Any]] = None,
            current_path: str = "/me",
            allow_retry: bool = True
    ) -> Tuple[requests.Response, Dict[str, Any]]:
        proof = self._get_browser_proof(session, proxies)
        headers = self._build_request_headers(
            referer=f"{self._base_url}{referer_path}",
            include_content_type=True,
            current_path=current_path,
            browser_proof=proof
        )
        url = f"{self._base_url}{api_path}"
        kwargs = {
            "headers": headers,
            "proxies": proxies,
            "timeout": (self._connect_timeout, self._read_timeout),
        }
        if payload is not None:
            kwargs["json"] = payload

        response = session.request(method.upper(), url, **kwargs)
        try:
            data = response.json()
        except ValueError:
            data = {}

        if allow_retry and self._needs_browser_proof_refresh(data):
            proof = self._get_browser_proof(session, proxies, force_refresh=True)
            headers = self._build_request_headers(
                referer=f"{self._base_url}{referer_path}",
                include_content_type=True,
                current_path=current_path,
                browser_proof=proof
            )
            kwargs["headers"] = headers
            response = session.request(method.upper(), url, **kwargs)
            try:
                data = response.json()
            except ValueError:
                data = {}

        return response, data

    def init_plugin(self, config: Optional[dict] = None) -> None:
        try:
            self.stop_service()

            if self.plugin_icon and str(self.plugin_icon).startswith(("http://", "https://")):
                parsed_icon = urlparse(str(self.plugin_icon))
                icon_domain = f"{parsed_icon.scheme}://{parsed_icon.netloc}" if parsed_icon.scheme and parsed_icon.netloc else None
                if icon_domain and icon_domain not in settings.SECURITY_IMAGE_DOMAINS:
                    settings.SECURITY_IMAGE_DOMAINS.append(icon_domain)

            self._enabled = False
            self._notify = True
            self._onlyonce = False
            self._cron = "0 10 * * *"
            self._portal_token = ""
            self._use_proxy = False
            self._history_count = 30
            self._random_time_range = ""
            self._retry_count = 0
            self._retry_interval = 5
            self._connect_timeout = 10
            self._read_timeout = 30
            self._user_agent = ""
            self._visitor_id = ""
            self._signin_mode = "normal"
            self._browser_proof = ""
            self._browser_proof_expires_at = 0

            if config:
                self._enabled = self._to_bool(config.get("enabled", False))
                self._notify = self._to_bool(config.get("notify", True))
                self._onlyonce = self._to_bool(config.get("onlyonce", False))
                self._cron = config.get("cron") or "0 10 * * *"
                self._portal_token = self._normalize_cookie_input(config.get("portal_token"))
                self._use_proxy = self._to_bool(config.get("use_proxy", False))
                self._history_count = self._to_int(config.get("history_count", 30), 30)
                self._random_time_range = (config.get("random_time_range") or "").strip()
                self._retry_count = self._to_int(config.get("retry_count", 0), 0)
                self._retry_interval = self._to_int(config.get("retry_interval", 5), 5)
                self._connect_timeout = self._to_int(config.get("connect_timeout", 10), 10)
                self._read_timeout = self._to_int(config.get("read_timeout", 30), 30)
                self._user_agent = (config.get("user_agent") or "").strip()
                self._visitor_id = (config.get("visitor_id") or "").strip()
                self._signin_mode = self._normalize_signin_mode(config.get("signin_mode"))

            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"{self.plugin_name}: 立即执行一次签到任务")
                self._scheduler.add_job(
                    func=self._signin,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="巅影签到魔改版"
                )
                self._onlyonce = False
                self.update_config(self._get_config())

                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

            if not self._enabled:
                logger.info(f"{self.plugin_name}: 插件未启用")
                return

            if self._enabled and self._cron:
                logger.info(f"{self.plugin_name}: 已配置 CRON '{self._cron}'，任务将通过公共服务注册")
        except Exception as err:
            logger.error(f"{self.plugin_name}: 初始化失败 - {err}")
            self._enabled = False

    def get_state(self) -> bool:
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        services = []

        if self._enabled and self._cron:
            services.append({
                "id": "dian115signin",
                "name": "巅影签到魔改版 - 定时任务",
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
                    task_id = f"dian115signin_pending_{task_type}"
                    task_name = f"巅影签到魔改版 - {'随机延迟' if task_type == 'random_delay' else '重试'}"
                    services.append({
                        "id": task_id,
                        "name": task_name,
                        "trigger": "date",
                        "func": self._execute_delayed_signin,
                        "kwargs": {"run_date": run_date},
                    })
                    logger.info(
                        f"{self.plugin_name}: 通过 get_service() 注册 {task_type} 恢复任务 "
                        f"({run_date.strftime('%Y-%m-%d %H:%M:%S')})"
                    )
                else:
                    logger.info(f"{self.plugin_name}: pending 任务时间已过期 ({task_type})，跳过注册并清理")
                    self._clear_pending_task()

        return services

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        version = getattr(settings, "VERSION_FLAG", "v1")
        cron_field_component = "VCronField" if version == "v2" else "VTextField"
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VCard",
                        "props": {
                            "variant": "flat",
                            "class": "mb-6",
                            "color": "surface"
                        },
                        "content": [
                            {
                                "component": "VCardItem",
                                "props": {"class": "px-6 pb-0"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "props": {"class": "d-flex align-center text-h6"},
                                        "content": [
                                            {
                                                "component": "VIcon",
                                                "props": {
                                                    "style": "color: #16b1ff;",
                                                    "class": "mr-3",
                                                    "size": "default"
                                                },
                                                "text": "mdi-calendar-check"
                                            },
                                            {
                                                "component": "span",
                                                "text": "基本设置"
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VDivider",
                                "props": {"class": "mx-4 my-2"}
                            },
                            {
                                "component": "VCardText",
                                "props": {"class": "px-6 pb-6"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "enabled",
                                                            "label": "启用插件",
                                                            "color": "primary",
                                                            "hide-details": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "use_proxy",
                                                            "label": "启用代理",
                                                            "color": "success",
                                                            "hide-details": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "notify",
                                                            "label": "开启通知",
                                                            "color": "info",
                                                            "hide-details": True
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "onlyonce",
                                                            "label": "立即执行一次",
                                                            "color": "warning",
                                                            "hide-details": True
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "visitor_id",
                                                            "label": "Visitor ID",
                                                            "placeholder": "留空自动生成；如需与浏览器一致，可填 localStorage.portal_visitor_id",
                                                            "autocomplete": "off",
                                                            "name": "dian115-signin-visitor-id",
                                                            "prepend-inner-icon": "mdi-fingerprint",
                                                            "persistent-hint": True,
                                                            "hint": "用于获取站点浏览器证明，不是登录凭证；通常留空即可。"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "user_agent",
                                                            "label": "User-Agent",
                                                            "placeholder": "粘贴同一浏览器请求头里的 User-Agent，遇到 browser proof required 时必填",
                                                            "autocomplete": "off",
                                                            "name": "dian115-signin-user-agent",
                                                            "prepend-inner-icon": "mdi-card-account-details-outline",
                                                            "persistent-hint": True,
                                                            "hint": "Cloudflare 浏览器证明通常与 Cookie 和 User-Agent 绑定；建议与抓取 Cookie 的同一请求保持一致。"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "portal_token",
                                                            "label": "Portal Token (Cookie)",
                                                            "placeholder": "请输入抓包获取的 portal_token",
                                                            "autocomplete": "off",
                                                            "name": "dian115-signin-token",
                                                            "prepend-inner-icon": "mdi-cookie",
                                                            "persistent-hint": True,
                                                            "hint": "可填入完整 Cookie 请求头，或只填 portal_token 的值；插件会自动提取并保存 portal_token。"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 4},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "signin_mode",
                                                            "label": "默认签到模式",
                                                            "items": [
                                                                {"title": "普通签到", "value": "normal"},
                                                                {"title": "运气签到", "value": "lucky"},
                                                            ],
                                                            "prepend-inner-icon": "mdi-dice-5-outline",
                                                            "persistent-hint": True,
                                                            "hint": "普通签到较稳健；运气签到可能获得更高积分，也可能 0 分或扣分。"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 4},
                                                "content": [
                                                    {
                                                        "component": cron_field_component,
                                                        "props": {
                                                            "model": "cron",
                                                            "label": "Cron 表达式",
                                                            "placeholder": "0 10 * * *",
                                                            "prepend-inner-icon": "mdi-clock-outline",
                                                            "persistent-hint": True,
                                                            "hint": "默认每天 10:00 执行签到"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 4},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "history_count",
                                                            "label": "历史保留条数",
                                                            "type": "number",
                                                            "min": 1,
                                                            "step": 1,
                                                            "active": True,
                                                            "persistent-hint": True,
                                                            "hint": "默认保留最近 30 条签到记录",
                                                            "placeholder": "默认保留30条",
                                                            "prepend-inner-icon": "mdi-counter"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 4},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "random_time_range",
                                                            "label": "随机时间范围(分钟)",
                                                            "placeholder": "例如: 0-30",
                                                            "prepend-inner-icon": "mdi-timer-outline",
                                                            "persistent-hint": True,
                                                            "hint": "定时任务将在该范围内随机延迟执行，留空则不随机"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "retry_count",
                                                            "label": "失败重试次数",
                                                            "type": "number",
                                                            "min": 0,
                                                            "step": 1,
                                                            "active": True,
                                                            "persistent-hint": True,
                                                            "hint": "签到失败后额外重试次数，默认不重试",
                                                            "placeholder": "默认0次",
                                                            "prepend-inner-icon": "mdi-refresh"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "retry_interval",
                                                            "label": "重试间隔(分钟)",
                                                            "type": "number",
                                                            "min": 1,
                                                            "step": 1,
                                                            "active": True,
                                                            "persistent-hint": True,
                                                            "hint": "每次失败重试之间的等待时间",
                                                            "placeholder": "默认5分钟",
                                                            "prepend-inner-icon": "mdi-timer-refresh-outline"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "connect_timeout",
                                                            "label": "连接超时(秒)",
                                                            "type": "number",
                                                            "min": 1,
                                                            "step": 1,
                                                            "active": True,
                                                            "persistent-hint": True,
                                                            "hint": "建立TCP连接的超时时间",
                                                            "placeholder": "默认10秒",
                                                            "prepend-inner-icon": "mdi-lan-connect"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "sm": 3},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "read_timeout",
                                                            "label": "读取超时(秒)",
                                                            "type": "number",
                                                            "min": 1,
                                                            "step": 1,
                                                            "active": True,
                                                            "persistent-hint": True,
                                                            "hint": "等待服务器返回响应的超时时间",
                                                            "placeholder": "默认30秒",
                                                            "prepend-inner-icon": "mdi-clock-outline"
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
                    {
                        "component": "VCard",
                        "props": {
                            "variant": "flat",
                            "class": "mb-6",
                            "color": "surface"
                        },
                        "content": [
                            {
                                "component": "VCardItem",
                                "props": {"class": "px-6 pb-0"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "props": {"class": "d-flex align-center text-h6 mb-0"},
                                        "content": [
                                            {
                                                "component": "VIcon",
                                                "props": {
                                                    "style": "color: #16b1ff;",
                                                    "class": "mr-3",
                                                    "size": "default"
                                                },
                                                "text": "mdi-information"
                                            },
                                            {
                                                "component": "span",
                                                "text": "使用说明"
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VDivider",
                                "props": {"class": "mx-4 my-2"}
                            },
                            {
                                "component": "VCardText",
                                "props": {"class": "px-6 py-0"},
                                "content": [
                                    {
                                        "component": "VList",
                                        "props": {
                                            "lines": "two",
                                            "density": "comfortable"
                                        },
                                        "content": [
                                            {
                                                "component": "VListItem",
                                                "props": {"lines": "two"},
                                                "content": [
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "d-flex align-items-start"},
                                                        "content": [
                                                            {
                                                                "component": "VIcon",
                                                                "props": {"color": "primary", "class": "mt-1 mr-2"},
                                                                "text": "mdi-cookie"
                                                            },
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "text-subtitle-1 font-weight-regular mb-1"},
                                                                "text": "凭证获取方式"
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "text-body-2 ml-8"},
                                                        "text": "在浏览器中登录癫影，通过开发者工具抓取同一请求的 Cookie 和 User-Agent；可整段粘贴 Cookie，插件会自动提取 portal_token 并保留风控 Cookie。"
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VListItem",
                                                "props": {"lines": "two"},
                                                "content": [
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "d-flex align-items-start"},
                                                        "content": [
                                                            {
                                                                "component": "VIcon",
                                                                "props": {"color": "warning", "class": "mt-1 mr-2"},
                                                                "text": "mdi-run-fast"
                                                            },
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "text-subtitle-1 font-weight-regular mb-1"},
                                                                "text": "立即执行一次"
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "text-body-2 ml-8"},
                                                        "text": "保存配置时勾选后会立刻执行一次签到，完成后自动取消勾选。"
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VListItem",
                                                "props": {"lines": "two"},
                                                "content": [
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "d-flex align-items-start"},
                                                        "content": [
                                                            {
                                                                "component": "VIcon",
                                                                "props": {"color": "error", "class": "mt-1 mr-2"},
                                                                "text": "mdi-history"
                                                            },
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "text-subtitle-1 font-weight-regular mb-1"},
                                                                "text": "历史记录"
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "text-body-2 ml-8"},
                                                        "text": "每次执行结果都会写入插件历史，并在详情页中展示最近记录。"
                                                    }
                                                ]
                                            }
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

        configured = bool(self._portal_token)
        status_text = "已启用" if self._enabled else "未启用"
        
        # 从 API 缓存中读取用户信息
        username = user_info.get("nickname", "未获取 (请先成功执行一次)")
        user_id = user_info.get("id", "--")
        is_vip = user_info.get("vip", False)
        
        # 获取用于生成文字头像的首个字符
        avatar_char = username[0] if username and username != "未获取 (请先成功执行一次)" else "?"
        
        # 优先从 api 获取最新数据，其次取历史记录中的
        current_points = user_info.get("points", latest.get("points", "--"))
        checkin_days = user_info.get("consecutive_signin", latest.get("checkin_days", "--"))
        signin_mode_name = self._signin_mode_options.get(self._normalize_signin_mode(self._signin_mode), "普通签到")

        status_color = "success" if latest.get("success") else ("warning" if latest else "info")
        action_map = {
            "signed": "签到成功",
            "already_signed": "今日已签到",
            "failed": "执行失败",
            "config_required": "待配置",
        }
        action_text = action_map.get(latest.get("action"), "暂无状态")

        history_rows = []
        for item in history[:10]:
            success = item.get("success")
            action = item.get("action")
            action_text_row = action_map.get(action, action or "--")
            action_color = "success" if success else ("warning" if action == "already_signed" else "error")
            action_icon = "mdi-check-circle" if success else ("mdi-alert-circle" if action == "already_signed" else "mdi-close-circle")
            mode_name = item.get("mode_name") or self._signin_mode_options.get(item.get("mode"), "")
            lucky_tier_name = item.get("lucky_tier_name") or self._lucky_tier_options.get(str(item.get("lucky_tier") or ""), "")
            mode_suffix = f"{mode_name} · {lucky_tier_name}" if mode_name and lucky_tier_name else mode_name
            message_text = item.get("message") or "--"
            if mode_suffix and mode_suffix not in message_text:
                message_text = f"{message_text}（{mode_suffix}）"
            history_rows.append({
                "component": "tr",
                "props": {
                    "class": "text-sm"
                },
                "content": [
                    {
                        "component": "td",
                        "props": {"class": "text-center text-high-emphasis"},
                        "content": [
                            {"component": "VIcon", "props": {"color": "info", "size": "x-small", "class": "mr-1"}, "text": "mdi-clock-time-four-outline"},
                            {"component": "span", "text": item.get("timestamp") or "--"}
                        ]
                    },
                    {
                        "component": "td",
                        "props": {"class": "text-center text-high-emphasis"},
                        "content": [
                            {
                                "component": "VChip",
                                "props": {"color": action_color, "size": "small", "variant": "tonal"},
                                "content": [
                                    {"component": "VIcon", "props": {"size": "small", "start": True}, "text": action_icon},
                                    {"component": "span", "text": action_text_row}
                                ]
                            }
                        ]
                    },
                    {
                        "component": "td",
                        "props": {"class": "text-center text-high-emphasis"},
                        "content": [
                            {"component": "VIcon", "props": {"color": "info", "size": "x-small", "class": "mr-1"}, "text": "mdi-counter"},
                            {"component": "span", "text": f"{item.get('checkin_days', '-') or '-'}天"}
                        ]
                    },
                    {
                        "component": "td",
                        "props": {"class": "text-center text-high-emphasis"},
                        "content": [
                            {"component": "VIcon", "props": {"color": "warning", "size": "x-small", "class": "mr-1"}, "text": "mdi-star-circle-outline"},
                            {"component": "span", "text": str(item.get("points_awarded", "-"))}
                        ]
                    },
                    {
                        "component": "td",
                        "props": {"class": "text-center text-high-emphasis"},
                        "content": [
                            {
                                "component": "VChip",
                                "props": {"color": "warning" if item.get("is_retry_task") else "default", "size": "small", "variant": "tonal"},
                                "text": "是" if item.get("is_retry_task") else "否"
                            }
                        ]
                    },
                    {
                        "component": "td",
                        "props": {"class": "text-center text-high-emphasis"},
                        "content": [
                            {"component": "VIcon", "props": {"color": "primary", "size": "x-small", "class": "mr-1"}, "text": "mdi-text-box-outline"},
                            {"component": "span", "text": message_text}
                        ]
                    },
                ]
            })

        if not history_rows:
            history_rows.append({
                "component": "tr",
                "content": [
                    {
                        "component": "td",
                        "props": {"colspan": 6, "class": "text-center text-medium-emphasis"},
                        "text": "暂无签到历史"
                    }
                ]
            })

        month_series, month_total_points, month_peak_points = self._build_month_points_series(history)
        pending_task = self.get_data("pending_task") or {}
        if isinstance(pending_task, dict) and pending_task.get("run_time_str"):
            next_run_text = pending_task.get("run_time_str")
        else:
            next_run_text = f"按 CRON：{self._cron or '--'}"

        status_items = [
            {
                "component": "VCol",
                "props": {"cols": 12, "md": 4},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "text-center py-2"},
                        "content": [
                            {"component": "div", "props": {"class": "text-subtitle-1 text-medium-emphasis mb-2"}, "text": "插件状态"},
                            {
                                "component": "div",
                                "props": {"class": "d-flex align-center justify-center text-h6 font-weight-medium", "style": f"color: {'#52c41a' if self._enabled else '#9e9e9e'};"},
                                "content": [
                                    {"component": "VIcon", "props": {"size": 28, "class": "mr-2", "color": "success" if self._enabled else "grey"}, "text": "mdi-play-circle-outline" if self._enabled else "mdi-pause-circle-outline"},
                                    {"component": "span", "text": status_text}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCol",
                "props": {"cols": 12, "md": 4},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "text-center py-2"},
                        "content": [
                            {"component": "div", "props": {"class": "text-subtitle-1 text-medium-emphasis mb-2"}, "text": "代理状态"},
                            {
                                "component": "div",
                                "props": {"class": "d-flex align-center justify-center text-h6 font-weight-medium", "style": f"color: {'#52c41a' if self._use_proxy else '#9e9e9e'};"},
                                "content": [
                                    {"component": "VIcon", "props": {"size": 28, "class": "mr-2", "color": "success" if self._use_proxy else "grey"}, "text": "mdi-earth" if self._use_proxy else "mdi-earth-off"},
                                    {"component": "span", "text": "已启用" if self._use_proxy else "未启用"}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCol",
                "props": {"cols": 12, "md": 4},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "text-center py-2"},
                        "content": [
                            {"component": "div", "props": {"class": "text-subtitle-1 text-medium-emphasis mb-2"}, "text": "下次执行时间"},
                            {
                                "component": "div",
                                "props": {"class": "d-flex align-center justify-center text-h6 font-weight-medium", "style": "color: #8f8f8f;"},
                                "content": [
                                    {"component": "VIcon", "props": {"size": 28, "class": "mr-2", "color": "grey"}, "text": "mdi-clock-outline"},
                                    {"component": "span", "text": next_run_text}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        account_chips = [
            {"component": "VChip", "props": {"color": "amber-darken-2" if is_vip else "default", "variant": "tonal", "class": "font-weight-medium"}, "content": [
                {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-crown" if is_vip else "mdi-account-outline"},
                {"component": "span", "text": "VIP" if is_vip else "普通用户"}
            ]},
            {"component": "VChip", "props": {"color": "success", "variant": "tonal", "class": "font-weight-medium"}, "content": [
                {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-wallet-outline"},
                {"component": "span", "text": f"余额：{current_points}"}
            ]},
            {"component": "VChip", "props": {"color": "info", "variant": "tonal", "class": "font-weight-medium"}, "content": [
                {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-calendar-check-outline"},
                {"component": "span", "text": f"连签：{checkin_days}天"}
            ]},
            {"component": "VChip", "props": {"color": "purple", "variant": "tonal", "class": "font-weight-medium"}, "content": [
                {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-dice-5-outline"},
                {"component": "span", "text": f"默认：{signin_mode_name}"}
            ]},
        ]

        return [
            {
                "component": "div",
                "props": {"style": "background: #fafafa; padding: 2px 0 6px;"},
                "content": [
                    self._section_card(
                        "#f3e5f5",
                        "mdi-information",
                        "插件运行状态",
                        [{"component": "VRow", "props": {"class": "align-center"}, "content": status_items}]
                    ),
                    self._section_card(
                        "#e3f2fd",
                        "mdi-chart-line",
                        "本月积分获得曲线",
                        [
                            {
                                "component": "div",
                                "props": {"class": "d-flex align-center justify-space-between flex-wrap ga-3 mb-3"},
                                "content": [
                                    {"component": "div", "props": {"class": "text-subtitle-1 text-medium-emphasis"}, "text": f"{self._month_label()} · 每日积分获得"},
                                    {"component": "div", "props": {"class": "d-flex flex-wrap ga-2"}, "content": [
                                        {"component": "VChip", "props": {"color": "info", "variant": "tonal"}, "text": f"本月合计：{self._format_points(month_total_points)}"},
                                        {"component": "VChip", "props": {"color": "cyan", "variant": "tonal"}, "text": f"单日最高：{self._format_points(month_peak_points)}"}
                                    ]}
                                ]
                            },
                            self._build_points_chart(month_series),
                            {
                                "component": "div",
                                "props": {"class": "d-flex align-center justify-center flex-wrap ga-4 mt-2 text-body-2 text-medium-emphasis"},
                                "content": [
                                    {"component": "div", "props": {"class": "d-flex align-center"}, "content": [
                                        {"component": "span", "props": {"style": "width: 12px; height: 12px; border-radius: 4px; background: #0ea5e9; display: inline-block; margin-right: 8px;"}},
                                        {"component": "span", "text": "每日获得积分"}
                                    ]},
                                    {"component": "div", "props": {"class": "d-flex align-center"}, "content": [
                                        {"component": "span", "props": {"style": "width: 12px; height: 12px; border-radius: 4px; background: #f59e0b; display: inline-block; margin-right: 8px;"}},
                                        {"component": "span", "text": signin_mode_name}
                                    ]}
                                ]
                            }
                        ],
                        {
                            "component": "div",
                            "props": {"style": "background: rgba(148, 163, 184, 0.30); color: #3f3f46; border-radius: 999px; padding: 8px 18px; font-weight: 700;"},
                            "content": [
                                {"component": "VIcon", "props": {"size": 20, "class": "mr-1", "color": "deep-orange"}, "text": "mdi-fire"},
                                {"component": "span", "text": str(current_points)}
                            ]
                        }
                    ),
                    self._section_card(
                        "#f1f8e9",
                        "mdi-account-circle-outline",
                        "账号与签到信息",
                        [
                            {
                                "component": "div",
                                "props": {"class": "d-flex flex-wrap align-center justify-space-between ga-4"},
                                "content": [
                                    {"component": "div", "props": {"class": "d-flex align-center ga-4"}, "content": [
                                        {"component": "VAvatar", "props": {"color": "success", "variant": "tonal", "size": 54}, "content": [
                                            {"component": "span", "props": {"class": "text-h5 font-weight-bold"}, "text": avatar_char}
                                        ]},
                                        {"component": "div", "props": {"class": "d-flex flex-column"}, "content": [
                                            {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": username},
                                            {"component": "div", "props": {"class": "text-body-2 text-medium-emphasis d-flex align-center mt-1"}, "content": [
                                                {"component": "VIcon", "props": {"size": "x-small", "class": "mr-1"}, "text": "mdi-smart-card-outline"},
                                                {"component": "span", "text": f"UID: {user_id}"}
                                            ]}
                                        ]}
                                    ]},
                                    {"component": "div", "props": {"class": "d-flex flex-wrap ga-2"}, "content": account_chips}
                                ]
                            }
                        ]
                    ),
                    self._section_card(
                        "#fff7ed",
                        "mdi-table-clock",
                        "最近签到历史",
                        [
                            {
                                "component": "VTable",
                                "props": {"hover": True, "density": "comfortable", "class": "rounded-lg"},
                                "content": [
                                    {
                                        "component": "thead",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {"component": "th", "props": {"class": "text-center text-body-1 font-weight-bold"}, "text": "签到时间"},
                                                    {"component": "th", "props": {"class": "text-center text-body-1 font-weight-bold"}, "text": "状态"},
                                                    {"component": "th", "props": {"class": "text-center text-body-1 font-weight-bold"}, "text": "天数"},
                                                    {"component": "th", "props": {"class": "text-center text-body-1 font-weight-bold"}, "text": "奖励积分"},
                                                    {"component": "th", "props": {"class": "text-center text-body-1 font-weight-bold"}, "text": "重试"},
                                                    {"component": "th", "props": {"class": "text-center text-body-1 font-weight-bold"}, "text": "说明"},
                                                ]
                                            }
                                        ]
                                    },
                                    {"component": "tbody", "content": history_rows}
                                ]
                            },
                            {"component": "div", "props": {"class": "text-caption text-grey mt-2", "style": "background: #f5f5f7; border-radius: 8px; padding: 6px 12px; display: inline-block;"}, "text": f"共显示 {len(history[:10])} 条签到记录"}
                        ]
                    )
                ]
            }
        ]

        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "flat", "class": "mb-6 h-100", "color": "surface"},
                                "content": [
                                    {
                                        "component": "VCardItem",
                                        "props": {"class": "px-6 pb-0"},
                                        "content": [
                                            {
                                                "component": "VCardTitle",
                                                "props": {"class": "d-flex align-center text-h6"},
                                                "content": [
                                                    {"component": "VIcon", "props": {"class": "mr-3", "style": "color: #2196F3;", "size": "default"}, "text": "mdi-movie-check-outline"},
                                                    {"component": "span", "text": "设置状态"}
                                                ]
                                            }
                                        ]
                                    },
                                    {"component": "VDivider", "props": {"class": "mx-4 my-2"}},
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "px-6 pb-6"},
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12, "md": 3},
                                                        "content": [
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "d-flex flex-column justify-space-between", "style": "min-height: 64px;"},
                                                                "content": [
                                                                    {"component": "div", "props": {"class": "text-subtitle-2 text-medium-emphasis"}, "text": "插件状态"},
                                                                    {"component": "VChip", "props": {"color": "success" if self._enabled else "grey", "class": "mt-2 align-self-start"}, "text": status_text}
                                                                ]
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12, "md": 3},
                                                        "content": [
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "d-flex flex-column justify-space-between", "style": "min-height: 64px;"},
                                                                "content": [
                                                                    {"component": "div", "props": {"class": "text-subtitle-2 text-medium-emphasis"}, "text": "账号配置"},
                                                                    {"component": "VChip", "props": {"color": "success" if configured else "warning", "class": "mt-2 align-self-start"}, "text": "已配置" if configured else "未配置"}
                                                                ]
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12, "md": 3},
                                                        "content": [
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "d-flex flex-column justify-space-between", "style": "min-height: 64px;"},
                                                                "content": [
                                                                    {"component": "div", "props": {"class": "text-subtitle-2 text-medium-emphasis"}, "text": "调度周期"},
                                                                    {"component": "div", "props": {"class": "text-body-1 mt-2"}, "text": self._cron or "--"}
                                                                ]
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12, "md": 3},
                                                        "content": [
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "d-flex flex-column justify-space-between", "style": "min-height: 64px;"},
                                                                "content": [
                                                                    {"component": "div", "props": {"class": "text-subtitle-2 text-medium-emphasis"}, "text": "最近状态"},
                                                                    {"component": "VChip", "props": {"color": status_color, "class": "mt-2 align-self-start"}, "text": action_text}
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "flat", "class": "mb-6 h-100", "color": "surface"},
                                "content": [
                                    {
                                        "component": "VCardItem",
                                        "props": {"class": "px-6 pb-0"},
                                        "content": [
                                            {
                                                "component": "VCardTitle",
                                                "props": {"class": "d-flex align-center text-h6"},
                                                "content": [
                                                    {"component": "VIcon", "props": {"class": "mr-3", "style": "color: #4CAF50;", "size": "default"}, "text": "mdi-account-circle-outline"},
                                                    {"component": "span", "text": "账号信息"}
                                                ]
                                            }
                                        ]
                                    },
                                    {"component": "VDivider", "props": {"class": "mx-4 my-2"}},
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "px-6 pb-6 pt-2"},
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {"class": "d-flex flex-wrap align-center justify-space-between ga-4"},
                                                "content": [
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "d-flex align-center ga-4"},
                                                        "content": [
                                                            {
                                                                "component": "VAvatar",
                                                                "props": {"color": "success", "variant": "tonal", "size": "54"},
                                                                "content": [
                                                                    {"component": "span", "props": {"class": "text-h5 font-weight-bold"}, "text": avatar_char}
                                                                ]
                                                            },
                                                            {
                                                                "component": "div",
                                                                "props": {"class": "d-flex flex-column"},
                                                                "content": [
                                                                    {
                                                                        "component": "div",
                                                                        "props": {"class": "text-h6 font-weight-bold"},
                                                                        "text": username
                                                                    },
                                                                    {
                                                                        "component": "div",
                                                                        "props": {"class": "text-body-2 text-medium-emphasis d-flex align-center mt-1"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"size": "x-small", "class": "mr-1"}, "text": "mdi-smart-card-outline"},
                                                                            {"component": "span", "text": f"UID: {user_id}"}
                                                                        ]
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "d-flex flex-wrap ga-2"},
                                                        "content": [
                                                            {
                                                                "component": "VChip",
                                                                "props": {"color": "amber-darken-2" if is_vip else "default", "variant": "tonal", "class": "font-weight-medium"},
                                                                "content": [
                                                                    {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-crown" if is_vip else "mdi-account-outline"},
                                                                    {"component": "span", "text": "VIP" if is_vip else "普通用户"}
                                                                ]
                                                            },
                                                            {
                                                                "component": "VChip",
                                                                "props": {"color": "success", "variant": "tonal", "class": "font-weight-medium"},
                                                                "content": [
                                                                    {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-wallet-outline"},
                                                                    {"component": "span", "text": f"余额：{current_points}"}
                                                                ]
                                                            },
                                                            {
                                                                "component": "VChip",
                                                                "props": {"color": "info", "variant": "tonal", "class": "font-weight-medium"},
                                                                "content": [
                                                                    {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-calendar-check-outline"},
                                                                    {"component": "span", "text": f"连签：{checkin_days}天"}
                                                                ]
                                                            },
                                                            {
                                                                "component": "VChip",
                                                                "props": {"color": "purple", "variant": "tonal", "class": "font-weight-medium"},
                                                                "content": [
                                                                    {"component": "VIcon", "props": {"start": True, "size": "small"}, "text": "mdi-dice-5-outline"},
                                                                    {"component": "span", "text": f"默认：{signin_mode_name}"}
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "flat", "class": "mb-4 elevation-2", "color": "surface", "style": "border-radius: 16px;"},
                                "content": [
                                    {
                                        "component": "VCardItem",
                                        "props": {"class": "pa-6"},
                                        "content": [
                                            {
                                                "component": "VCardTitle",
                                                "props": {"class": "d-flex align-center text-h6"},
                                                "content": [
                                                    {"component": "VIcon", "props": {"class": "mr-3", "style": "color: #9C27B0;", "size": "default"}, "text": "mdi-table-clock"},
                                                    {"component": "span", "text": "最近签到历史"}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "pa-6"},
                                        "content": [
                                            {
                                                "component": "VTable",
                                                "props": {"hover": True, "density": "comfortable", "class": "rounded-lg"},
                                                "content": [
                                                    {
                                                        "component": "thead",
                                                        "content": [
                                                            {
                                                                "component": "tr",
                                                                "content": [
                                                                    {
                                                                        "component": "th",
                                                                        "props": {"class": "text-center text-body-1 font-weight-bold"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"color": "info", "size": "small", "class": "mr-1"}, "text": "mdi-clock-time-four-outline"},
                                                                            {"component": "span", "text": "签到时间"}
                                                                        ]
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {"class": "text-center text-body-1 font-weight-bold"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"color": "success", "size": "small", "class": "mr-1"}, "text": "mdi-check-circle"},
                                                                            {"component": "span", "text": "签到状态"}
                                                                        ]
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {"class": "text-center text-body-1 font-weight-bold"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"color": "info", "size": "small", "class": "mr-1"}, "text": "mdi-counter"},
                                                                            {"component": "span", "text": "签到天数"}
                                                                        ]
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {"class": "text-center text-body-1 font-weight-bold"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"color": "warning", "size": "small", "class": "mr-1"}, "text": "mdi-star-circle-outline"},
                                                                            {"component": "span", "text": "奖励积分"}
                                                                        ]
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {"class": "text-center text-body-1 font-weight-bold"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"color": "warning", "size": "small", "class": "mr-1"}, "text": "mdi-refresh-auto"},
                                                                            {"component": "span", "text": "重试任务"}
                                                                        ]
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {"class": "text-center text-body-1 font-weight-bold"},
                                                                        "content": [
                                                                            {"component": "VIcon", "props": {"color": "primary", "size": "small", "class": "mr-1"}, "text": "mdi-text-box-outline"},
                                                                            {"component": "span", "text": "结果说明"}
                                                                        ]
                                                                    },
                                                                ]
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        "component": "tbody",
                                                        "content": history_rows
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-caption text-grey mt-2",
                                                    "style": "background: #f5f5f7; border-radius: 8px; padding: 6px 12px; display: inline-block;"
                                                },
                                                "content": [
                                                    {"component": "VIcon", "props": {"size": "x-small", "class": "mr-1"}, "text": "mdi-format-list-bulleted"},
                                                    {"component": "span", "text": f"共显示 {len(history[:10])} 条签到记录"}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def _get_config(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron or "",
            "portal_token": self._portal_token,
            "use_proxy": self._use_proxy,
            "history_count": self._history_count,
            "random_time_range": self._random_time_range,
            "retry_count": self._retry_count,
            "retry_interval": self._retry_interval,
            "connect_timeout": self._connect_timeout,
            "read_timeout": self._read_timeout,
            "user_agent": self._user_agent,
            "visitor_id": self._ensure_visitor_id(),
            "signin_mode": self._signin_mode,
        }

    def _save_config(self, config: dict) -> Dict[str, Any]:
        new_config = {
            "enabled": self._to_bool(config.get("enabled", False)),
            "notify": self._to_bool(config.get("notify", False)),
            "onlyonce": self._to_bool(config.get("onlyonce", False)),
            "cron": config.get("cron") or "0 10 * * *",
            "portal_token": self._normalize_cookie_input(config.get("portal_token")),
            "use_proxy": self._to_bool(config.get("use_proxy", False)),
            "history_count": self._to_int(config.get("history_count", 30), 30),
            "random_time_range": (config.get("random_time_range") or "").strip(),
            "retry_count": self._to_int(config.get("retry_count", 0), 0),
            "retry_interval": self._to_int(config.get("retry_interval", 5), 5),
            "connect_timeout": self._to_int(config.get("connect_timeout", 10), 10),
            "read_timeout": self._to_int(config.get("read_timeout", 30), 30),
            "user_agent": (config.get("user_agent") or "").strip(),
            "visitor_id": (config.get("visitor_id") or "").strip(),
            "signin_mode": self._normalize_signin_mode(config.get("signin_mode")),
        }
        self.update_config(new_config)
        self.init_plugin(new_config)
        return {"success": True, "message": "配置保存成功", "data": self._get_config()}

    def _parse_random_time_range(self) -> Tuple[int, int]:
        raw_value = (self._random_time_range or "").strip()
        if not raw_value:
            return 0, 0

        try:
            if "-" in raw_value:
                start_text, end_text = raw_value.split("-", 1)
                start_min = max(0, int(start_text.strip() or 0))
                end_min = max(0, int(end_text.strip() or 0))
            else:
                start_min = 0
                end_min = max(0, int(raw_value))

            if end_min < start_min:
                start_min, end_min = end_min, start_min
            return start_min, end_min
        except Exception:
            logger.warning(f"{self.plugin_name}: 随机时间范围格式无效，已忽略 - {raw_value}")
            return 0, 0

    def _save_pending_task(self, task_type: str, run_time: datetime, **extra) -> None:
        self.save_data("pending_task", {
            "type": task_type,
            "run_time_ts": run_time.timestamp(),
            "run_time_str": run_time.strftime("%Y-%m-%d %H:%M:%S"),
            **extra,
        })
        logger.info(f"{self.plugin_name}: 已保存 pending {task_type} 任务，执行时间: {run_time.strftime('%Y-%m-%d %H:%M:%S')}")

    def _clear_pending_task(self) -> None:
        self.save_data("pending_task", None)
        logger.debug(f"{self.plugin_name}: 已清理 pending 任务数据")

    def _schedule_signin_with_random_delay(self) -> None:
        start_min, end_min = self._parse_random_time_range()
        delay_minutes = random.randint(start_min, end_min) if end_min > 0 else 0

        if delay_minutes <= 0:
            logger.info(f"{self.plugin_name}: 未设置随机延迟，立即执行签到任务")
            self._clear_pending_task()
            self._signin()
            return

        tz = pytz.timezone(settings.TZ)
        run_time = datetime.now(tz=tz) + timedelta(minutes=delay_minutes)
        logger.info(f"{self.plugin_name}: 定时任务触发，已安排在 {delay_minutes} 分钟后执行签到")

        self._save_pending_task("random_delay", run_time)
        self.reregister_plugin()

    def _schedule_retry_signin(self, retry_index: int) -> Optional[str]:
        if retry_index > self._retry_count:
            self._clear_pending_task()
            return None

        retry_interval = max(self._retry_interval, 1)
        tz = pytz.timezone(settings.TZ)
        run_time = datetime.now(tz=tz) + timedelta(minutes=retry_interval)

        self._save_pending_task("retry", run_time, retry_index=retry_index)
        self.reregister_plugin()

        return run_time.strftime("%Y-%m-%d %H:%M:%S")

    def reregister_plugin(self) -> None:
        logger.info(f"{self.plugin_name}: 重新注册插件任务")
        Scheduler().update_plugin_job(self.__class__.__name__)

    def _execute_delayed_signin(self) -> Dict[str, Any]:
        pending = self.get_data("pending_task") or {}
        retry_index = pending.get("retry_index", 0) if isinstance(pending, dict) else 0
        self._clear_pending_task()
        logger.info(f"{self.plugin_name}: 通过 get_service() 执行{'重试' if retry_index > 0 else '延迟'}签到任务 (retry_index={retry_index})")
        return self._signin(retry_index=retry_index)

    def _get_status(self) -> Dict[str, Any]:
        latest = self.get_data("latest_result") or {}
        history = self.get_data("history") or []
        return {
            "enabled": self._enabled,
            "cron": self._cron,
            "notify": self._notify,
            "use_proxy": self._use_proxy,
            "configured": bool(self._portal_token),
            "latest_result": latest,
            "history_count": len(history),
        }

    def _get_history_api(self) -> Dict[str, Any]:
        return {"success": True, "data": self.get_data("history") or []}

    def _run_once(self) -> Dict[str, Any]:
        result = self._signin()
        return {"success": result.get("success", False), "data": result, "message": result.get("message", "")}

    def stop_service(self):
        try:
            Scheduler().remove_plugin_job(self.__class__.__name__.lower())
        except Exception as err:
            logger.debug(f"{self.plugin_name}: 停止服务时忽略错误 - {err}")

        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as err:
            logger.debug(f"{self.plugin_name}: 停止内部调度器时忽略错误 - {err}")

    def _record_history(self, record: Dict[str, Any]) -> None:
        history = self.get_data("history") or []
        history.append(record)
        history = sorted(history, key=lambda x: x.get("timestamp") or "", reverse=True)
        if len(history) > self._history_count:
            history = history[:self._history_count]
        self.save_data("history", history)
        self.save_data("latest_result", record)

    def _notify_result(self, title: str, text: str) -> None:
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=title,
                text=text,
            )

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

    @staticmethod
    def _to_number(raw_value: Any, default: float = 0) -> float:
        try:
            if raw_value in (None, ""):
                return default
            return float(raw_value)
        except Exception:
            return default

    def _build_month_points_series(self, history: List[dict]) -> Tuple[List[Dict[str, Any]], float, float]:
        now = datetime.now()
        days_in_month = monthrange(now.year, now.month)[1]
        points_by_day = {day: 0.0 for day in range(1, days_in_month + 1)}

        for item in history:
            dt_value = self._parse_history_datetime(item.get("timestamp"))
            if not dt_value or dt_value.year != now.year or dt_value.month != now.month:
                continue
            if item.get("action") not in ("signed", "already_signed"):
                continue
            points_by_day[dt_value.day] += self._to_number(item.get("points_awarded"), 0)

        series = [{"day": day, "points": points_by_day[day]} for day in range(1, now.day + 1)]
        if not series:
            series = [{"day": now.day, "points": 0}]

        total_points = sum(item["points"] for item in series)
        max_points = max(item["points"] for item in series)
        return series, total_points, max_points

    @staticmethod
    def _format_points(value: Any) -> str:
        try:
            number = float(value)
            if number.is_integer():
                return str(int(number))
            return f"{number:.1f}"
        except Exception:
            return str(value)

    @staticmethod
    def _month_label() -> str:
        now = datetime.now()
        return f"{now.year}年{now.month}月"

    def _build_points_chart(self, series: List[Dict[str, Any]]) -> Dict[str, Any]:
        width, height = 920, 320
        left, right, top, bottom = 72, 28, 32, 52
        chart_width = width - left - right
        chart_height = height - top - bottom
        values = [self._to_number(item.get("points"), 0) for item in series]
        min_value = min(values + [0])
        max_value = max(values + [0])
        if min_value == max_value:
            min_value -= 1
            max_value += 1
        padding = max((max_value - min_value) * 0.18, 1)
        y_min = min_value - padding
        y_max = max_value + padding

        def x_at(index: int) -> float:
            if len(series) <= 1:
                return left + chart_width / 2
            return left + chart_width * index / (len(series) - 1)

        def y_at(value: float) -> float:
            return top + (y_max - value) * chart_height / (y_max - y_min)

        points = [(x_at(index), y_at(self._to_number(item.get("points"), 0))) for index, item in enumerate(series)]
        path_d = ""
        for index, (x, y) in enumerate(points):
            path_d += ("M" if index == 0 else " L") + f"{x:.1f} {y:.1f}"

        grid_values = [y_min + (y_max - y_min) * i / 4 for i in range(5)]
        grid_nodes = []
        for value in grid_values:
            y = y_at(value)
            grid_nodes.append({"component": "line", "props": {"x1": left, "y1": y, "x2": width - right, "y2": y, "stroke": "#e5e7eb", "stroke-width": 1, "stroke-dasharray": "6 6"}})
            grid_nodes.append({"component": "text", "props": {"x": left - 14, "y": y + 4, "text-anchor": "end", "fill": "#9ca3af", "font-size": 13}, "text": self._format_points(round(value, 1))})

        x_label_indexes = sorted(set([0, len(series) - 1, max(0, len(series) // 3), max(0, len(series) * 2 // 3)]))
        x_labels = [
            {"component": "text", "props": {"x": x_at(index), "y": height - 20, "text-anchor": "middle", "fill": "#9ca3af", "font-size": 13}, "text": f"{series[index]['day']}日"}
            for index in x_label_indexes
            if 0 <= index < len(series)
        ]

        point_nodes = [
            {"component": "circle", "props": {"cx": x, "cy": y, "r": 4.8, "fill": "#0ea5e9", "stroke": "#ffffff", "stroke-width": 2}}
            for x, y in points
        ]

        if not any(values):
            empty_hint = [{
                "component": "text",
                "props": {"x": width / 2, "y": height / 2, "text-anchor": "middle", "fill": "#9ca3af", "font-size": 16},
                "text": "本月暂无积分获得记录"
            }]
        else:
            empty_hint = []

        return {
            "component": "div",
            "props": {"style": "width: 100%; overflow-x: auto;"},
            "content": [
                {
                    "component": "svg",
                    "props": {"viewBox": f"0 0 {width} {height}", "style": "width: 100%; min-width: 640px; height: auto; display: block;"},
                    "content": [
                        *grid_nodes,
                        {"component": "line", "props": {"x1": left, "y1": y_at(0), "x2": width - right, "y2": y_at(0), "stroke": "#cbd5e1", "stroke-width": 1.2}},
                        {"component": "path", "props": {"d": path_d, "fill": "none", "stroke": "#06b6d4", "stroke-width": 5, "stroke-linecap": "round", "stroke-linejoin": "round"}},
                        *point_nodes,
                        *x_labels,
                        *empty_hint,
                    ]
                }
            ]
        }

    @staticmethod
    def _section_card(header_color: str, icon: str, title: str, content: List[dict], badge: Optional[dict] = None) -> Dict[str, Any]:
        header_content = [
            {
                "component": "div",
                "props": {"class": "d-flex align-center ga-3"},
                "content": [
                    {"component": "VIcon", "props": {"size": 28, "color": "primary"}, "text": icon},
                    {"component": "span", "props": {"class": "text-h6 font-weight-bold text-high-emphasis"}, "text": title},
                ]
            }
        ]
        if badge:
            header_content.append(badge)

        return {
            "component": "div",
            "props": {"style": "border: 1px solid #e5e7eb; border-radius: 14px; overflow: hidden; background: #ffffff; margin-bottom: 24px;"},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "d-flex align-center justify-space-between flex-wrap ga-3", "style": f"background: {header_color}; padding: 22px 28px;"},
                    "content": header_content
                },
                {
                    "component": "div",
                    "props": {"style": "padding: 24px 28px;"},
                    "content": content
                }
            ]
        }

    def _fetch_user_profile(self, session: requests.Session, proxies) -> dict:
        """调用 /api/portal/me 接口获取用户信息"""
        response, data = self._portal_request(
            session=session,
            method="GET",
            api_path="/api/portal/me",
            proxies=proxies,
            referer_path="/me",
            current_path="/me"
        )

        if response.status_code != 200:
            raise ValueError(self._format_http_error(response, data))
        
        if data.get("code") == "ok":
            return data.get("user", {})
        return {}

    def _signin(self, retry_index: int = 0) -> Dict[str, Any]:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self._portal_token:
            result = {
                "success": False,
                "timestamp": timestamp,
                "message": "未配置 portal_token (Cookie)",
                "action": "config_required",
            }
            self._record_history(result)
            return result

        try:
            proxies = None
            if self._use_proxy:
                proxies = getattr(settings, "PROXY", None)

            session = requests.Session()
            session.headers.update(self._build_request_headers(referer=f"{self._base_url}/me"))

            # 1. 签到前先请求 /api/portal/me 提取用户信息 (Nickname, VIP, Points 等)
            try:
                user_info = self._fetch_user_profile(session, proxies)
                if user_info:
                    self.save_data("user_info", user_info)
                else:
                    logger.warning(f"{self.plugin_name}: 未能提取到有效的用户信息，可能 Cookie 已过期")
            except Exception as e:
                logger.error(f"{self.plugin_name}: 获取用户信息失败 - {e}")
                user_info = {}

            nickname = user_info.get("nickname", "未知用户")
            is_vip = user_info.get("vip", False)
            vip_str = "👑 VIP" if is_vip else "普通用户"
            signin_mode = self._normalize_signin_mode(self._signin_mode)
            signin_mode_name = self._signin_mode_options.get(signin_mode, "普通签到")

            # 2. 准备发送真正签到的 POST 请求
            payload = {"mode": signin_mode}

            response, res_data = self._portal_request(
                session=session,
                method="POST",
                api_path="/api/portal/signin",
                proxies=proxies,
                referer_path="/me/signin",
                payload=payload,
                current_path="/me/signin"
            )

            # 签到成功处理 (200 OK)
            if response.status_code == 200 and res_data.get("code") == "ok":
                award = res_data.get("award", 0)
                new_balance = res_data.get("new_balance", user_info.get("points", 0))
                streak = res_data.get("streak", user_info.get("consecutive_signin", 0))
                lucky_tier = res_data.get("lucky_tier")
                lucky_tier_name = self._lucky_tier_options.get(str(lucky_tier or ""), "")
                multiplier = res_data.get("multiplier")
                lucky_tier_suffix = f" · {lucky_tier_name}" if lucky_tier_name else ""
                multiplier_line = f"🎯 倍率：{multiplier}x\n" if multiplier is not None else ""

                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": f"{signin_mode_name}成功，获得 {award} 积分",
                    "action": "signed",
                    "mode": signin_mode,
                    "mode_name": signin_mode_name,
                    "points_awarded": award,
                    "points": new_balance,
                    "checkin_days": streak,
                    "lucky_tier": lucky_tier,
                    "lucky_tier_name": lucky_tier_name,
                    "multiplier": multiplier,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【🎬癫影】签到成功 🟢",
                    text=(
                        f"━━━━━━━━━━━━━━\n"
                        f"✨ 状态：✅已签到\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"📊 数据统计\n"
                        f"👤 用户：{nickname} ({vip_str})\n"
                        f"🎲 模式：{signin_mode_name}{lucky_tier_suffix}\n"
                        f"🎁 奖励积分：{award}\n"
                        f"{multiplier_line}"
                        f"⭐ 当前余额：{new_balance}\n"
                        f"📆 连续签到：{streak} 天\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🕐 时间：{timestamp}"
                    ),
                )
                return result

            # 重复签到处理 (409 Conflict)
            elif response.status_code == 409:
                # 409 时服务器有时不返回积分，这里优先提取 user_info 里获取的数据兜底
                new_balance = res_data.get("new_balance", user_info.get("points", "未知"))
                streak = user_info.get("consecutive_signin", "未知")

                result = {
                    "success": True,
                    "timestamp": timestamp,
                    "message": f"今日已签到过，请勿重复操作（默认模式：{signin_mode_name}）",
                    "action": "already_signed",
                    "mode": signin_mode,
                    "mode_name": signin_mode_name,
                    "points": new_balance,
                    "checkin_days": streak,
                }
                self._record_history(result)
                self._clear_pending_task()
                self._notify_result(
                    title="【🎬癫影】签到状态 🟡",
                    text=(
                        f"━━━━━━━━━━━━━━\n"
                        f"✨ 状态：ℹ️今日已签到\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"📊 数据统计\n"
                        f"👤 用户：{nickname} ({vip_str})\n"
                        f"🎲 默认模式：{signin_mode_name}\n"
                        f"⭐ 当前余额：{new_balance}\n"
                        f"📆 连续签到：{streak} 天\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🕐 时间：{timestamp}"
                    ),
                )
                return result

            # 其他未知错误状态
            else:
                error_msg = self._format_http_error(response, res_data)
                raise ValueError(error_msg)

        except Exception as err:
            logger.error(f"{self.plugin_name}: 执行签到失败 - {err}")
            next_retry_time = None
            if retry_index < self._retry_count:
                next_retry_time = self._schedule_retry_signin(retry_index + 1)
            else:
                self._clear_pending_task()

            # 确保获取不到的时候给个占位符，防止报错
            nickname = locals().get("nickname", "未知用户")
            vip_str = locals().get("vip_str", "未知状态")

            result = {
                "success": False,
                "timestamp": timestamp,
                "message": str(err),
                "action": "failed",
                "retry_index": retry_index,
                "next_retry_time": next_retry_time,
                "is_retry_task": retry_index > 0,
            }
            self._record_history(result)
            self._notify_result(
                title="【🎬癫影】签到异常 🔴",
                text=(
                    f"━━━━━━━━━━━━━━\n"
                    f"✨ 状态：❌签到失败\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"👤 用户：{nickname} ({vip_str})\n"
                    f"💬 失败原因：{err}\n"
                    f"🔁 当前重试：{retry_index}/{self._retry_count}\n"
                    f"⏰ 下次重试：{next_retry_time or '无'}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🕐 时间：{timestamp}"
                ),
            )
            return result
