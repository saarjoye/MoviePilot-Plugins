"""熊猫好友买卖站点客户端。"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Dict, List, Mapping, Optional
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


class PandaClientError(RuntimeError):
    """站点客户端基础异常。"""


class PandaAuthError(PandaClientError):
    """站点认证不可用。"""


class PandaSchemaError(PandaClientError):
    """站点返回结构不符合契约。"""


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
    def _validate_response(action: str, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("ret"), int):
            raise PandaSchemaError(f"{action} 返回结构无效")
        if payload.get("ret") != 0:
            message = str(payload.get("msg") or nested_reason(payload.get("data")) or f"{action} 执行失败")
            if "Cookie" in message or "登录" in message:
                raise PandaAuthError(f"{action} 认证失效")
            raise PandaClientError(safe_error_message(action, message))
        if action in READ_ACTIONS and not isinstance(payload.get("data"), (dict, list)):
            raise PandaSchemaError(f"{action} 返回 data 类型无效")
        return payload

    def post_action(self, action: str, params: Optional[Mapping[str, Any]] = None, write: bool = False) -> Dict[str, Any]:
        """执行白名单动作并验证 JSON 响应。"""
        if action in FORBIDDEN_ACTIONS:
            raise PandaClientError(f"动作被安全策略禁止: {action}")
        allowed = WRITE_ACTIONS if write else READ_ACTIONS
        if action not in allowed:
            raise PandaClientError(f"动作不在{'写' if write else '读'}白名单: {action}")
        body: Dict[str, Any] = {"action": action}
        for key, value in (params or {}).items():
            body[f"params[{key}]"] = value
        response = self._request().post_res(url=urljoin(self.base_url, "ajax.php"), data=body)
        if response is None:
            raise PandaClientError(f"{action} 无响应")
        if response.status_code in (401, 403):
            raise PandaAuthError(f"{action} 认证失败")
        try:
            payload = response.json()
        except ValueError as error:
            raise PandaSchemaError(f"{action} 未返回 JSON") from error
        return self._validate_response(action, payload)

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


def safe_error_message(action: str, message: str) -> str:
    """限制远端错误长度，避免认证材料意外进入日志。"""
    text = " ".join(str(message).split())[:240]
    lowered = text.lower()
    if any(marker in lowered for marker in ("cookie", "authorization", "bearer", "session", "token=")):
        return f"{action} 执行失败（远端错误已脱敏）"
    return text or f"{action} 执行失败"
