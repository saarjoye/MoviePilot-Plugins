"""熊猫好友买卖站点客户端。"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urljoin

from app.core.config import settings
from app.helper.sites import SitesHelper
from app.utils.http import RequestUtils


READ_ACTIONS = frozenset({
    "friendTradeInitOrHome",
    "friendTradeInventory",
    "friendTradeMarketList",
    "friendTradeDetail",
    "friendTradeCommissionBoard",
    "friendTradeScreeningHome",
    "friendTradePosterTaskBoard",
    "friendTradePosterCollection",
    "friendTradePosterHistory",
})
WRITE_ACTIONS = frozenset({
    "friendTradeClaimIncome",
    "friendTradeClaimTaskReward",
    "friendTradeLevelPosterClaim",
    "friendTradeAchievementClaim",
    "friendTradeWork",
    "friendTradeInteract",
    "friendTradeBuy",
    "friendTradeSnatch",
    "friendTradeCommissionStart",
    "friendTradeCommissionSettle",
    "friendTradeScreeningStart",
    "friendTradeScreeningSubmit",
})
FORBIDDEN_ACTIONS = frozenset({
    "friendTradeRelease",
    "friendTradeRedeem",
    "friendTradeProtect",
    "friendTradeBuyCapacitySlot",
    "friendTradeInventoryPurchase",
    "friendTradeInventoryUse",
    "friendTradePosterGift",
    "friendTradePosterTaskClaim",
    "friendTradeAlbumRedeem",
})


SAFE_ERROR_FIELDS = frozenset({
    "reason", "message", "code", "error_code", "status",
    "available_at", "can_buy_at", "blocked_until", "retry_at",
})
SAFE_ERROR_CONTAINERS = frozenset({"restriction", "cooldown", "limit"})
BUSINESS_CODE_RULES = {
    "buyback_restricted": ("buyback_restricted", "target"),
    "repurchase_restricted": ("buyback_restricted", "target"),
    "buyback_limit": ("buyback_restricted", "target"),
    "repurchase_limit": ("buyback_restricted", "target"),
    "target_buyback_restricted": ("buyback_restricted", "target"),
    "already_owned": ("already_owned", "target"),
    "already_held": ("already_owned", "target"),
    "player_already_owned": ("already_owned", "target"),
    "protection_period": ("protection_period", "target"),
    "target_protected": ("protection_period", "target"),
    "slot_full": ("slot_full", "market"),
    "capacity_full": ("slot_full", "market"),
    "no_capacity": ("slot_full", "market"),
    "screening_preview_active": ("screening_preview_active", "screening"),
    "poster_preview_active": ("screening_preview_active", "screening"),
}


class PandaClientError(RuntimeError):
    """站点客户端基础异常，仅保存脱敏后的响应元数据。"""

    def __init__(
        self,
        message: str,
        *,
        action: Optional[str] = None,
        ret: Any = None,
        code: Any = None,
        data: Any = None,
        result_unknown: bool = False,
        business_rule: Optional[str] = None,
        rule_scope: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.ret = ret
        self.code = code
        self.data = sanitize_error_data(data)
        self.result_unknown = bool(result_unknown)
        self.business_rule = business_rule
        self.rule_scope = rule_scope


class PandaAuthError(PandaClientError):
    """站点认证不可用。"""


class PandaSchemaError(PandaClientError):
    """站点返回结构不符合契约。"""


class PandaBusinessRuleError(PandaClientError):
    """站点明确拒绝且能够确认写操作未执行。"""


class PandaTransportError(PandaClientError):
    """网络、超时或无响应错误。"""


class PandaServiceError(PandaClientError):
    """结构有效但无法归类为已知业务规则的服务端错误。"""


class PandaClientPolicyError(PandaClientError):
    """本地动作白名单或安全策略错误。"""


class RankTableParser(HTMLParser):
    """从排行榜页面提取表头与有限行数据。"""

    def __init__(self, row_limit: int = 50) -> None:
        super().__init__()
        self.row_limit = row_limit
        self.tables: List[List[List[str]]] = []
        self._table: Optional[List[List[str]]] = None
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None and len(self._table) < self.row_limit + 1:
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            value = " ".join(data.split())
            if value:
                self._cell.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td") and self._cell is not None and self._row is not None:
            self._row.append(" ".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


class PandaFriendTradeClient:
    """复用 MoviePilot 站点配置访问好友买卖接口。"""

    DOMAIN = "pandapt.net"

    def __init__(self, site_id: Optional[int] = None) -> None:
        self.site = self._resolve_site(site_id)
        self.site_id = self.site.get("id")
        self.site_name = str(self.site.get("name") or self.DOMAIN)
        self.base_url = str(self.site.get("url") or "").rstrip("/") + "/"
        self.cookie = str(self.site.get("cookie") or "")
        self.ua = str(self.site.get("ua") or "") or None
        self.timeout = int(self.site.get("timeout") or 15)
        self.proxies = settings.PROXY if self.site.get("proxy") else None
        if not self.base_url or not self.cookie:
            raise PandaAuthError("熊猫站地址或认证配置不可用")

    @classmethod
    def available_sites(cls) -> List[Dict[str, Any]]:
        """返回可选熊猫站的非敏感摘要。"""
        result = []
        for site in SitesHelper().get_indexers() or []:
            url = str(site.get("url") or "")
            if cls.DOMAIN in url:
                result.append({"id": site.get("id"), "name": site.get("name") or cls.DOMAIN, "url": url})
        return result

    @classmethod
    def _resolve_site(cls, site_id: Optional[int]) -> Dict[str, Any]:
        sites = [site for site in (SitesHelper().get_indexers() or []) if cls.DOMAIN in str(site.get("url") or "")]
        if site_id is not None:
            sites = [site for site in sites if str(site.get("id")) == str(site_id)]
        if not sites:
            raise PandaAuthError("MoviePilot 中未找到已配置的熊猫站")
        return dict(sites[0])

    def _request(self) -> RequestUtils:
        return RequestUtils(cookies=self.cookie, ua=self.ua, proxies=self.proxies, timeout=self.timeout)

    @staticmethod
    def _validate_response(action: str, payload: Any, write: bool = False) -> Dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("ret"), int):
            raise PandaSchemaError(
                f"{action} 返回结构无效", action=action,
                data=payload, result_unknown=write,
            )
        if payload.get("ret") != 0:
            message = str(payload.get("msg") or nested_reason(payload.get("data")) or f"{action} 执行失败")
            code = response_code(payload)
            safe_data = sanitize_error_data(payload.get("data"))
            if is_auth_failure_message(message):
                raise PandaAuthError(
                    f"{action} 认证失效", action=action, ret=payload.get("ret"),
                    code=code, data=safe_data,
                )
            business = classify_business_rule(action, code, safe_data, message)
            if business:
                rule, scope = business
                raise PandaBusinessRuleError(
                    safe_error_message(action, message), action=action,
                    ret=payload.get("ret"), code=code, data=safe_data,
                    business_rule=rule, rule_scope=scope,
                )
            raise PandaServiceError(
                safe_error_message(action, message), action=action,
                ret=payload.get("ret"), code=code, data=safe_data,
            )
        if action in READ_ACTIONS and not isinstance(payload.get("data"), (dict, list)):
            raise PandaSchemaError(
                f"{action} 返回 data 类型无效", action=action,
                ret=payload.get("ret"), data=payload.get("data"),
            )
        return payload

    def post_action(self, action: str, params: Optional[Mapping[str, Any]] = None, write: bool = False) -> Dict[str, Any]:
        """执行白名单动作并验证 JSON 响应。"""
        if action in FORBIDDEN_ACTIONS:
            raise PandaClientPolicyError(f"动作被安全策略禁止: {action}", action=action)
        allowed = WRITE_ACTIONS if write else READ_ACTIONS
        if action not in allowed:
            raise PandaClientPolicyError(f"动作不在{'写' if write else '读'}白名单: {action}", action=action)
        body: Dict[str, Any] = {"action": action}
        for key, value in (params or {}).items():
            body[f"params[{key}]"] = value
        try:
            response = self._request().post_res(url=urljoin(self.base_url, "ajax.php"), data=body)
        except Exception as error:
            raise PandaTransportError(
                f"{action} 请求失败: {type(error).__name__}", action=action,
                result_unknown=write,
            ) from error
        if response is None:
            raise PandaTransportError(f"{action} 无响应", action=action, result_unknown=write)
        if response.status_code in (401, 403):
            raise PandaAuthError(f"{action} 认证失败", action=action)
        try:
            payload = response.json()
        except ValueError as error:
            raise PandaSchemaError(
                f"{action} 未返回 JSON", action=action,
                result_unknown=write,
            ) from error
        return self._validate_response(action, payload, write=write)

    def get_rankings(self) -> List[Dict[str, Any]]:
        """只读抓取排行榜页面并返回表格摘要。"""
        response = self._request().get_res(url=urljoin(self.base_url, "friend-trade-rank.php"))
        if response is None or response.status_code != 200:
            raise PandaClientError("排行榜页面读取失败")
        parser = RankTableParser()
        parser.feed(response.text)
        result = []
        for table in parser.tables:
            headers = table[0] if table else []
            if headers and any("玩家" in value or "交易好友" in value for value in headers):
                result.append({"headers": headers, "rows": table[1:]})
        return result


def nested_reason(data: Any) -> Optional[str]:
    """从错误数据中提取非敏感原因文本。"""
    if isinstance(data, Mapping):
        reason = data.get("reason") or data.get("message")
        return str(reason) if reason else None
    return None


def sanitize_error_data(data: Any) -> Dict[str, Any]:
    """仅保留分类和限期判断需要的低风险响应字段。"""
    if not isinstance(data, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key)
        if key in SAFE_ERROR_FIELDS and isinstance(raw_value, (str, int, float, bool)):
            result[key] = raw_value
        elif key in SAFE_ERROR_CONTAINERS and isinstance(raw_value, Mapping):
            nested = sanitize_error_data(raw_value)
            if nested:
                result[key] = nested
    return result


def response_code(payload: Mapping[str, Any]) -> Any:
    """按稳定优先级提取业务代码，不把通用 ret 猜测成业务规则。"""
    if payload.get("code") not in (None, ""):
        return payload.get("code")
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("code", "error_code"):
            if data.get(key) not in (None, ""):
                return data.get(key)
    return None


def normalize_code(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_auth_failure_message(message: str) -> bool:
    """仅匹配明确的认证失效提示，避免把普通登录任务误判为认证故障。"""
    text = " ".join(str(message).split()).lower()
    return any(marker in text for marker in (
        "cookie 失效", "cookie失效", "请先登录", "登录已失效", "登录状态失效",
        "未登录", "需要登录", "重新登录",
    ))


def classify_business_rule(
    action: str,
    code: Any,
    data: Mapping[str, Any],
    message: str,
) -> Optional[Tuple[str, str]]:
    """优先使用结构字段，最后才兼容已确认的站点中文文案。"""
    normalized = normalize_code(code)
    if normalized in BUSINESS_CODE_RULES:
        return BUSINESS_CODE_RULES[normalized]
    if action in {"friendTradeBuy", "friendTradeSnatch"} and any(
        find_error_value(data, key) not in (None, "")
        for key in ("available_at", "can_buy_at", "blocked_until")
    ):
        return "buyback_restricted", "target"
    text = " ".join(str(message).split())
    if "回购限制" in text:
        return "buyback_restricted", "target"
    if "已持有该玩家" in text or "已经持有该玩家" in text:
        return "already_owned", "target"
    if "保护期" in text:
        return "protection_period", "target"
    if "槽位已满" in text or "没有空余槽位" in text:
        return "slot_full", "market"
    if action == "friendTradeScreeningSubmit" and "海报仍在展示中" in text:
        return "screening_preview_active", "screening"
    return None


def find_error_value(data: Mapping[str, Any], key: str) -> Any:
    if key in data:
        return data.get(key)
    for container in SAFE_ERROR_CONTAINERS:
        nested = data.get(container)
        if isinstance(nested, Mapping) and key in nested:
            return nested.get(key)
    return None


def safe_error_message(action: str, message: str) -> str:
    """限制远端错误长度，避免认证材料意外进入日志。"""
    text = " ".join(str(message).split())[:240]
    lowered = text.lower()
    if any(marker in lowered for marker in ("cookie", "authorization", "bearer", "session", "token=")):
        return f"{action} 执行失败（远端错误已脱敏）"
    return text or f"{action} 执行失败"
