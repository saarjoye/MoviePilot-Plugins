"""MoviePilot v2 熊猫好友买卖助手。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from threading import Condition
from typing import Any, Dict, List, Mapping, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.schemas.types import NotificationType

from .client import (
    PandaAuthError,
    PandaClientError,
    PandaClientPolicyError,
    PandaFriendTradeClient,
    PandaSchemaError,
    safe_error_message,
)
from .engine import (
    AutomationEngine,
    build_daily_summary,
    build_failure_notification,
    enrich_audit_record,
    failure_context,
)
from .presentation import build_home_view
from .strategy import market_candidate_decision, rank_market_candidates


DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "site_id": None,
    "risk_acknowledged": False,
    "auto_claim": True,
    "auto_work": True,
    "auto_interaction": True,
    "auto_market": False,
    "auto_office": True,
    "auto_screening": True,
    "cron": "0 8,12,18,23 * * *",
    "market_watch_cron": "*/10 * * * *",
    "reserve_bonus": 100000,
    "daily_interaction_budget": 0,
    "single_trade_cap": 0,
    "daily_trade_budget": 0,
    "max_daily_trades": 3,
    "min_market_score": 70,
    "allow_snatch": False,
    "target_cooldown_days": 7,
    "market_scan_pages": 10,
    "history_retention_days": 30,
    "notify_failures": True,
    "notify_success": False,
    "daily_summary_enabled": True,
    "daily_summary_time": "00:05",
    "notification_include_details": True,
}

SENSITIVE_KEYS = {
    "authorization", "cookie", "cookies", "ua", "user_agent", "proxy", "proxies",
    "token", "challenge_token", "headers", "session", "password",
}
MODULES = {"claims", "cultivation", "work", "interaction", "market", "office", "screening", "posters"}


def normalize_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """合并安全默认值并约束配置类型与范围。"""
    result = deepcopy(DEFAULT_CONFIG)
    incoming = dict(config or {})
    result.update({key: incoming[key] for key in DEFAULT_CONFIG if key in incoming})
    # 0.2.17 及更早版本只有一个培养开关，升级时保持原有选择。
    if "auto_cultivation" in incoming:
        if "auto_work" not in incoming:
            result["auto_work"] = bool(incoming["auto_cultivation"])
        if "auto_interaction" not in incoming:
            result["auto_interaction"] = bool(incoming["auto_cultivation"])
    for key in ("enabled", "risk_acknowledged", "auto_claim", "auto_work", "auto_interaction",
                "auto_market", "auto_office", "auto_screening", "allow_snatch",
                "notify_failures", "notify_success", "daily_summary_enabled",
                "notification_include_details"):
        result[key] = bool(result.get(key))
    for key in ("reserve_bonus", "daily_interaction_budget", "single_trade_cap", "daily_trade_budget"):
        result[key] = max(0.0, float(result.get(key) or 0))
    result["max_daily_trades"] = max(0, min(20, int(result.get("max_daily_trades") or 0)))
    result["min_market_score"] = max(0, min(100, int(result.get("min_market_score") or 70)))
    result["target_cooldown_days"] = max(0, min(365, int(result.get("target_cooldown_days") or 7)))
    result["market_scan_pages"] = max(1, min(50, int(result.get("market_scan_pages") or 10)))
    result["history_retention_days"] = max(1, min(365, int(result.get("history_retention_days") or 30)))
    result["cron"] = str(result.get("cron") or DEFAULT_CONFIG["cron"]).strip()
    result["market_watch_cron"] = str(result.get("market_watch_cron") or DEFAULT_CONFIG["market_watch_cron"]).strip()
    summary_time = str(result.get("daily_summary_time") or DEFAULT_CONFIG["daily_summary_time"]).strip()
    try:
        hour_text, minute_text = summary_time.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
        result["daily_summary_time"] = f"{hour:02d}:{minute:02d}"
    except (TypeError, ValueError):
        result["daily_summary_time"] = DEFAULT_CONFIG["daily_summary_time"]
    result["site_id"] = int(result["site_id"]) if result.get("site_id") is not None else None
    if not result["risk_acknowledged"] or result["site_id"] is None:
        result["enabled"] = False
    return result


def sanitize(value: Any) -> Any:
    """递归移除认证、请求头和挑战令牌。"""
    if isinstance(value, Mapping):
        return {
            str(key): sanitize(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item) for item in value]
    return value


class PandaTradeAssistant(_PluginBase):
    plugin_name = "熊猫交易助手"
    plugin_desc = "汇总好友买卖玩法并提供受控的奖励、培养、市场、事务所和每日放映自动化。"
    plugin_icon = "pandatradeassistant.png"
    plugin_version = "0.2.23"
    plugin_author = "wYw"
    author_url = ""
    plugin_config_prefix = "pandatradeassistant_"
    plugin_order = 30
    auth_level = 1

    def __init__(self) -> None:
        super().__init__()
        self._config = normalize_config(None)
        self._state: Dict[str, Any] = {}
        self._history: List[Dict[str, Any]] = []
        self._run_condition = Condition()
        self._run_active = False
        self._active_run_kind: Optional[str] = None
        self._scheduled_waiters = 0

    def init_plugin(self, config: Optional[dict] = None) -> None:
        self._config = normalize_config(config)
        auto_selected_site = False
        if self._config.get("site_id") is None:
            available_sites = PandaFriendTradeClient.available_sites()
            if len(available_sites) == 1 and available_sites[0].get("id") is not None:
                self._config = normalize_config({
                    **self._config,
                    "site_id": available_sites[0]["id"],
                    "enabled": False,
                })
                auto_selected_site = True
        stored_state = self.get_data("state") or {}
        stored_history = self.get_data("history") or []
        self._state = dict(stored_state) if isinstance(stored_state, Mapping) else {}
        self._history = list(stored_history) if isinstance(stored_history, list) else []
        if auto_selected_site:
            self._audit({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "subsystem": "config",
                "action": "site_auto_select",
                "success": True,
                "message": "检测到唯一熊猫站点，已自动选择；自动执行保持关闭",
            })
        invalid_snapshot = "snapshot" in self._state and not self._snapshot_matches_site()
        if invalid_snapshot:
            self._state.pop("snapshot", None)
        snapshot_errors = (self._state.get("snapshot") or {}).get("errors") or {}
        legacy_read_circuit = bool(
            self._state.get("circuit_open")
            and not self._state.get("circuit_scope")
            and self._state.get("circuit_reason") == "PandaClientError"
            and len(snapshot_errors) >= 3
        )
        if legacy_read_circuit:
            self._state["circuit_open"] = False
            self._state["consecutive_failures"] = 0
            self._state.pop("circuit_reason", None)
        self._prune_history()
        self.update_config(self._config)
        if auto_selected_site or invalid_snapshot or legacy_read_circuit:
            self._persist()

    def get_state(self) -> bool:
        # 宿主必须保持插件运行，才能提供设置、只读页面、API 和联邦资源。
        # 自动写入由 config.enabled 及风险门禁独立控制。
        return True

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets-v0223"

    @staticmethod
    def get_sidebar_nav() -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        sites = PandaFriendTradeClient.available_sites()
        site_items = [{"title": item["name"], "value": item["id"]} for item in sites]
        form = [{"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VSelect", "props": {"model": "site_id", "label": "熊猫站点", "items": site_items}}
                ]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VTextField", "props": {"model": "cron", "label": "自动调度 Cron"}}
                ]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VTextField", "props": {"model": "market_watch_cron", "label": "空槽补位巡检 Cron"}}
                ]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VTextField", "props": {"model": "daily_summary_time", "label": "每日汇总时间（HH:MM）"}}
                ]},
            ]},
            {"component": "VSwitch", "props": {"model": "risk_acknowledged", "label": "我已知晓站规与账号风险"}},
            {"component": "VSwitch", "props": {"model": "enabled", "label": "启用自动执行与调度"}},
            {"component": "VSwitch", "props": {"model": "auto_work", "label": "自动安排工作"}},
            {"component": "VSwitch", "props": {"model": "auto_interaction", "label": "自动进行互动"}},
            {"component": "VSwitch", "props": {"model": "notify_failures", "label": "异常即时通知"}},
            {"component": "VSwitch", "props": {"model": "notify_success", "label": "成功任务通知"}},
            {"component": "VSwitch", "props": {"model": "daily_summary_enabled", "label": "每日汇总通知"}},
            {"component": "VSwitch", "props": {"model": "notification_include_details", "label": "每日汇总包含完成任务明细"}},
        ]}]
        return form, deepcopy(DEFAULT_CONFIG)

    @staticmethod
    def get_page() -> List[dict]:
        return []

    def get_service(self) -> List[dict]:
        if not self._config.get("enabled"):
            return []
        services = []
        try:
            trigger = CronTrigger.from_crontab(self._config["cron"])
        except ValueError:
            self._audit({"subsystem": "scheduler", "action": "parse_cron", "success": False, "message": "Cron 表达式无效"})
        else:
            services.append({
                "id": "PandaTradeAssistant",
                "name": "熊猫交易助手自动任务",
                "trigger": trigger,
                "func": self.run_scheduled,
                "kwargs": {},
            })
        if self._config.get("auto_market"):
            try:
                market_trigger = CronTrigger.from_crontab(self._config["market_watch_cron"])
            except ValueError:
                self._audit({"subsystem": "scheduler", "action": "parse_market_cron", "success": False, "message": "空槽补位巡检 Cron 表达式无效"})
            else:
                services.append({
                    "id": "PandaTradeAssistantMarketWatch",
                    "name": "熊猫交易助手空槽补位巡检",
                    "trigger": market_trigger,
                    "func": self.run_market_watch,
                    "kwargs": {},
                })
        if self._config.get("daily_summary_enabled"):
            hour, minute = self._config["daily_summary_time"].split(":")
            services.append({
                "id": "PandaTradeAssistantSummary",
                "name": "熊猫交易助手每日汇总",
                "trigger": CronTrigger.from_crontab(f"{int(minute)} {int(hour)} * * *"),
                "func": self.send_daily_summary,
                "kwargs": {},
            })
        return services

    def stop_service(self) -> None:
        self._state["stopped_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self._persist()

    def _client(self) -> PandaFriendTradeClient:
        return PandaFriendTradeClient(self._config.get("site_id"))

    def _audit(self, record: Dict[str, Any]) -> None:
        clean = sanitize(record)
        clean.setdefault("trigger", getattr(self, "_active_trigger", "系统内部"))
        clean.setdefault("phase", getattr(self, "_active_phase", "系统处理"))
        self._history.append(clean)
        self._prune_history()

    def _prune_history(self) -> None:
        cutoff = datetime.now().astimezone() - timedelta(days=int(self._config.get("history_retention_days") or 30))
        retained = []
        for record in self._history[-2000:]:
            try:
                if datetime.fromisoformat(str(record.get("time"))) >= cutoff:
                    retained.append(record)
            except (TypeError, ValueError):
                continue
        self._history = retained

    def _persist(self) -> None:
        self.save_data("state", sanitize(self._state))
        self.save_data("history", sanitize(self._history))

    def _snapshot_matches_site(self) -> bool:
        snapshot = self._state.get("snapshot")
        if not isinstance(snapshot, Mapping) or self._config.get("site_id") is None:
            return False
        return str(snapshot.get("site_id")) == str(self._config.get("site_id"))

    def _post_notification(self, title: str, text: str) -> bool:
        """发送通知并隔离渠道异常，禁止通知失败递归触发通知。"""
        try:
            self.post_message(mtype=NotificationType.Plugin, title=title, text=text[:500])
            return True
        except Exception as error:
            reason = safe_error_message("通知推送", str(error))
            self._audit({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "subsystem": "notification", "action": "dispatch", "success": False,
                "message": reason, "failure_reason": reason,
                "error_type": type(error).__name__, "impact": "本次通知未送达",
                "action_required": True,
                "recovery_hint": "检查 MoviePilot 全局通知渠道配置",
                "severity": "warning",
            })
            try:
                self._persist()
            except Exception:
                pass
            return False

    def _notify_failure(self, title: str, text: str) -> None:
        if self._config.get("notify_failures"):
            self._post_notification(title, text)

    def _notification_text(self, records: List[Mapping[str, Any]], prefix: str) -> str:
        lines = [prefix]
        if self._config.get("notification_include_details"):
            for raw in records[:8]:
                record = enrich_audit_record(raw)
                status = {"success": "成功", "skipped": "已跳过", "failed": "失败"}.get(
                    str(record.get("status")), "未知状态"
                )
                lines.append(
                    f"- {record['task_name']} · {record['action_name']}："
                    f"{status}；{record['reward']}"
                )
            if len(records) > 8:
                lines.append(f"- 另有 {len(records) - 8} 条，请在审计记录中查看")
        return "\n".join(lines)[:500]

    def _notify_success(self, records: List[Mapping[str, Any]]) -> None:
        completed = [item for item in records if item.get("success") and not (item.get("skipped") or item.get("planned"))]
        if self._config.get("notify_success") and completed:
            self._post_notification(
                "熊猫交易助手执行完成",
                self._notification_text(completed, f"本次成功完成 {len(completed)} 项任务。"),
            )

    def _notify_run_failure(
        self, result: Mapping[str, Any], circuit_before: bool, trigger: str = "未标明",
    ) -> None:
        failed = [
            enrich_audit_record(item)
            for item in (result.get("records") or [])
            if not item.get("success") and not (item.get("skipped") or item.get("planned"))
        ]
        circuit_open = bool(result.get("circuit_open") or self._state.get("circuit_open"))
        if circuit_open and circuit_before:
            return
        if failed or circuit_open:
            title, text = build_failure_notification(
                failed, trigger=trigger, circuit_open=circuit_open,
                consecutive_failures=int(self._state.get("consecutive_failures") or 0),
                read_failure_streak=int(self._state.get("read_failure_streak") or 0),
            )
            self._notify_failure(title, text)

    def _execution_gate_message(self) -> Optional[str]:
        if self._config.get("site_id") is None:
            return "请先在设置中选择熊猫站点"
        if not self._config.get("risk_acknowledged") or not self._config.get("enabled"):
            return "请先确认风险并启用自动执行"
        if self._state.get("paused"):
            return "插件已暂停，未执行任何任务；请点击“恢复”后重试"
        if self._state.get("circuit_open"):
            return "插件已熔断，未执行任何任务；请检查审计记录并点击“恢复”"
        return None

    def _acquire_run_slot(self, run_kind: str) -> Tuple[bool, bool]:
        """常规任务等待当前运行结束；市场和手动任务不排队。"""
        with self._run_condition:
            if run_kind == "scheduled":
                waited = self._run_active
                self._scheduled_waiters += 1
                try:
                    while self._run_active:
                        self._run_condition.wait()
                    self._run_active = True
                    self._active_run_kind = run_kind
                    return True, waited
                finally:
                    self._scheduled_waiters -= 1
            if self._run_active or self._scheduled_waiters:
                return False, False
            self._run_active = True
            self._active_run_kind = run_kind
            return True, False

    def _release_run_slot(self) -> None:
        with self._run_condition:
            self._run_active = False
            self._active_run_kind = None
            self._run_condition.notify_all()

    def _remember_run_result(
        self, result: Mapping[str, Any], modules: Optional[List[str]], trigger: str,
        run_kind: str, finished_at: str,
    ) -> Dict[str, Any]:
        snapshot = sanitize({
            "success": bool(result.get("success")),
            "time": finished_at,
            "modules": list(modules or ["all"]),
            "trigger": trigger,
            "run_kind": run_kind,
            "records": list(result.get("records") or [])[-50:],
            "post_refresh": result.get("post_refresh"),
        })
        self._state["last_run_at"] = finished_at
        self._state["last_result"] = snapshot
        state_key = {
            "scheduled": "last_scheduled_result",
            "market": "last_market_watch_result",
            "manual": "last_manual_result",
        }.get(run_kind)
        if state_key:
            self._state[state_key] = dict(snapshot)
        return snapshot

    def _run(
        self, modules: Optional[List[str]] = None, force_selected: bool = False,
        trigger: str = "手动执行", run_kind: str = "manual",
    ) -> Dict[str, Any]:
        gate_message = self._execution_gate_message()
        if gate_message:
            return {"success": False, "message": gate_message}
        acquired, waited = self._acquire_run_slot(run_kind)
        if not acquired:
            if run_kind == "market":
                return {
                    "success": True, "busy": True, "skipped": True,
                    "message": "常规自动任务正在执行或等待，市场巡检跳过本轮",
                }
            return {"success": False, "busy": True, "message": "已有任务正在执行"}
        circuit_before = bool(self._state.get("circuit_open"))
        phase = "站点初始化"
        if waited and run_kind == "scheduled":
            trigger = "常规定时（冲突后补跑）"
        self._active_trigger = trigger
        self._active_phase = phase
        try:
            gate_message = self._execution_gate_message()
            if gate_message:
                return {"success": False, "message": gate_message}
            if waited and run_kind == "scheduled":
                self._active_phase = "调度协调"
                self._audit({
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "subsystem": "scheduler", "action": "deferred_run", "success": True,
                    "message": "市场巡检结束后补跑本轮常规自动任务",
                    "trigger": trigger, "phase": "调度协调",
                })
            client = self._client()
            phase = "实时读取与任务执行"
            self._active_phase = phase
            engine = AutomationEngine(
                client, self._config, self._state, self._audit, trigger=trigger,
            )
            result = sanitize(engine.run(modules, force_selected=force_selected))
            phase = "结果保存"
            self._active_phase = phase
            finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._remember_run_result(result, modules, trigger, run_kind, finished_at)
            self._persist()
            phase = "通知发送"
            self._active_phase = phase
            if not result["success"] or result.get("circuit_open"):
                self._notify_run_failure(result, circuit_before, trigger)
            else:
                self._notify_success(result.get("records") or [])
            return result
        except Exception as error:
            should_circuit = isinstance(error, (PandaAuthError, PandaSchemaError, PandaClientPolicyError)) or not isinstance(error, PandaClientError)
            if should_circuit:
                self._state["circuit_open"] = True
                self._state["circuit_scope"] = "write"
                self._state["circuit_reason"] = type(error).__name__
            self._state["last_error"] = type(error).__name__
            reason = safe_error_message("插件任务", str(error))
            record = {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "subsystem": "plugin", "action": "run", "success": False,
                "message": reason, "failure_reason": reason,
                "error_type": type(error).__name__,
                "result_unknown": bool(getattr(error, "result_unknown", False)),
                "trigger": trigger, "phase": phase,
            }
            record.update(failure_context(
                record, circuit_open=bool(self._state.get("circuit_open")),
                read_failure_streak=int(self._state.get("read_failure_streak") or 0),
            ))
            self._audit(record)
            finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._remember_run_result(
                {"success": False, "records": [record]}, modules, trigger, run_kind, finished_at,
            )
            self._persist()
            title, text = build_failure_notification(
                [record], trigger=trigger,
                circuit_open=bool(self._state.get("circuit_open")),
                consecutive_failures=int(self._state.get("consecutive_failures") or 0),
                read_failure_streak=int(self._state.get("read_failure_streak") or 0),
            )
            self._notify_failure(title, text)
            return {"success": False, "message": reason}
        finally:
            self._active_phase = "系统处理"
            self._release_run_slot()

    def run_scheduled(self) -> Dict[str, Any]:
        return self._run(trigger="常规定时", run_kind="scheduled")

    def run_market_watch(self) -> Dict[str, Any]:
        """定期检查真实佣人数量，在存在空槽时按市场策略补位。"""
        return self._run(
            ["market"], force_selected=True, trigger="市场补位", run_kind="market",
        )

    def send_daily_summary(self) -> None:
        if not self._config.get("daily_summary_enabled"):
            return
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        records = [item for item in self._history if str(item.get("time", "")).startswith(today)]
        self._post_notification(
            f"熊猫交易助手 · {now.month}月{now.day}日汇总",
            build_daily_summary(
                records,
                include_details=bool(self._config.get("notification_include_details")),
                state=self._state,
            ),
        )

    def _snapshot_section(self, key: str) -> Any:
        snapshot = self._state.get("snapshot") or {}
        if not self._snapshot_matches_site():
            return None
        value = snapshot.get(key)
        return sanitize(value) if isinstance(value, (Mapping, list)) else None

    def _section_response(self, key: str, label: str) -> Dict[str, Any]:
        value = self._snapshot_section(key)
        if value is None:
            return {"success": False, "message": f"{label}未获取到本次实时数据，请刷新并检查 MoviePilot 站点配置"}
        return {"success": True, "data": value}

    def api_status(self) -> Dict[str, Any]:
        daily_ledgers = self._state.get("daily_trade") or {}
        today_ledger = daily_ledgers.get(datetime.now().astimezone().date().isoformat()) or {}
        daily_budget = float(self._config.get("daily_trade_budget") or 0)
        return {"success": True, "data": sanitize({
            "enabled": self._config.get("enabled"),
            "configured": self._config.get("site_id") is not None,
            "risk_acknowledged": self._config.get("risk_acknowledged"),
            "paused": self._state.get("paused", False), "circuit_open": self._state.get("circuit_open", False),
            "circuit_reason": self._state.get("circuit_reason"), "circuit_scope": self._state.get("circuit_scope"),
            "consecutive_failures": int(self._state.get("consecutive_failures") or 0),
            "screening_circuit": self._state.get("screening_circuit"),
            "read_failure_streak": int(self._state.get("read_failure_streak") or 0),
            "last_run_at": self._state.get("last_run_at"),
            "last_result": self._state.get("last_result"),
            "last_scheduled_result": self._state.get("last_scheduled_result"),
            "last_market_watch_result": self._state.get("last_market_watch_result"),
            "last_manual_result": self._state.get("last_manual_result"),
            "snapshot_at": (self._state.get("snapshot") or {}).get("refreshed_at") if self._snapshot_matches_site() else None,
            "refresh_attempted_at": (self._state.get("snapshot") or {}).get("refresh_attempted_at") if self._snapshot_matches_site() else None,
            "snapshot_valid": self._snapshot_matches_site(),
            "source_site_id": (self._state.get("snapshot") or {}).get("site_id") if self._snapshot_matches_site() else None,
            "source_site_name": (self._state.get("snapshot") or {}).get("site_name") if self._snapshot_matches_site() else None,
            "refresh_errors": (self._state.get("snapshot") or {}).get("errors", {}) if self._snapshot_matches_site() else {},
            "stale_sections": (self._state.get("snapshot") or {}).get("stale_sections", []) if self._snapshot_matches_site() else [],
            "section_updated_at": (self._state.get("snapshot") or {}).get("section_updated_at", {}) if self._snapshot_matches_site() else {},
            "automation": {
                "schedule": self._config.get("cron"),
                "market_watch_schedule": self._config.get("market_watch_cron"),
                "daily_interaction_budget": self._config.get("daily_interaction_budget"),
                "modules": {
                    "claims": self._config.get("auto_claim"),
                    "work": self._config.get("auto_work"),
                    "interaction": self._config.get("auto_interaction"),
                    "market": self._config.get("auto_market"),
                    "office": self._config.get("auto_office"),
                    "screening": self._config.get("auto_screening"),
                },
            },
            "budget_remaining": max(0.0, daily_budget - float(today_ledger.get("spent") or 0)),
            "daily_trade_count": int(today_ledger.get("count") or 0),
            "sites": [{"id": item["id"], "name": item["name"]} for item in PandaFriendTradeClient.available_sites()],
        })}

    def api_config(self) -> Dict[str, Any]:
        """返回可公开给插件页面的配置，不包含任何站点认证材料。"""
        return {"success": True, "data": {
            "config": sanitize({key: self._config.get(key) for key in DEFAULT_CONFIG}),
            "sites": [
                {"id": item["id"], "name": item["name"]}
                for item in PandaFriendTradeClient.available_sites()
            ],
        }}

    def api_save_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """保存配置白名单；未知字段和认证材料不会进入插件配置。"""
        incoming = config if isinstance(config, Mapping) else {}
        allowed = {key: incoming[key] for key in DEFAULT_CONFIG if key in incoming}
        previous_site_id = self._config.get("site_id")
        self._config = normalize_config({**self._config, **allowed})
        if str(previous_site_id) != str(self._config.get("site_id")):
            self._state.pop("snapshot", None)
        self.update_config(self._config)
        self._audit({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "subsystem": "config",
            "action": "save",
            "success": True,
            "message": "插件配置已更新",
        })
        self._persist()
        return self.api_config()

    def api_assets(self) -> Dict[str, Any]:
        home = self._snapshot_section("home")
        inventory = self._snapshot_section("inventory")
        if home is None:
            return {"success": False, "message": "个人资产未获取到本次实时数据，请刷新并检查 MoviePilot 站点 Cookie"}
        return {"success": True, "data": {
            "home": home,
            "view": sanitize(build_home_view(home, inventory or {})),
            "inventory": inventory,
        }}

    def api_market(self) -> Dict[str, Any]:
        market = self._snapshot_section("market")
        if market is None:
            return {"success": False, "message": "公开市场未获取到本次实时数据，请刷新并检查 MoviePilot 站点 Cookie"}
        rows = market.get("list") or []
        if isinstance(rows, list):
            inventory = self._snapshot_section("inventory") or {}
            available_bonus = float(inventory.get("magic_balance") or 0)
            strategy_rows = []
            for item in rank_market_candidates(rows):
                decision = market_candidate_decision(item, self._config, available_bonus)
                strategy_rows.append(sanitize({
                    **item.candidate,
                    "strategy_score": item.score,
                    "strategy_breakdown": item.breakdown,
                    "decision_status": decision["status"],
                    "decision_label": decision["label"],
                }))
            market["strategy_rows"] = strategy_rows
        return {"success": True, "data": market}

    def api_detail(self, target_uid: int) -> Dict[str, Any]:
        try:
            payload = self._client().post_action("friendTradeDetail", {"target_uid": int(target_uid)})
            return {"success": True, "data": sanitize(payload.get("data") or {})}
        except PandaClientError as error:
            return {"success": False, "message": str(error)}

    def api_office(self) -> Dict[str, Any]:
        return self._section_response("office", "事务所")

    def api_screening(self) -> Dict[str, Any]:
        return self._section_response("screening", "每日放映")

    def api_posters(self) -> Dict[str, Any]:
        return self._section_response("posters", "电影图鉴")

    def api_history(self) -> Dict[str, Any]:
        rows = [enrich_audit_record(item) for item in reversed(self._history[-500:])]
        return {"success": True, "data": sanitize(rows)}

    def api_refresh(self) -> Dict[str, Any]:
        if self._config.get("site_id") is None:
            return {"success": False, "message": "请先在设置中选择熊猫站点"}
        acquired, _ = self._acquire_run_slot("manual")
        if not acquired:
            return {"success": False, "busy": True, "message": "已有任务正在执行"}
        try:
            engine = AutomationEngine(self._client(), self._config, self._state, self._audit)
            snapshot = sanitize(engine.refresh())
            self._persist()
            return {"success": True, "data": snapshot}
        except PandaClientError as error:
            return {"success": False, "message": str(error)}
        finally:
            self._release_run_slot()

    def api_run(self, module: str) -> Dict[str, Any]:
        if module not in MODULES and module != "all":
            return {"success": False, "message": "未知模块"}
        return self._run(
            None if module == "all" else [module],
            force_selected=module != "all", trigger="手动执行", run_kind="manual",
        )

    def api_pause(self) -> Dict[str, Any]:
        self._state["paused"] = True
        self._persist()
        return {"success": True, "message": "已暂停自动写入"}

    def api_resume(self) -> Dict[str, Any]:
        self._state["paused"] = False
        self._state["circuit_open"] = False
        self._state["consecutive_failures"] = 0
        self._state.pop("circuit_reason", None)
        self._state.pop("circuit_scope", None)
        self._state.pop("screening_circuit", None)
        self._persist()
        return {"success": True, "message": "已恢复并重置熔断"}

    def get_api(self) -> List[dict]:
        return [
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"], "summary": "运行状态", "auth": "bear"},
            {"path": "/config", "endpoint": self.api_config, "methods": ["GET"], "summary": "读取配置", "auth": "bear"},
            {"path": "/config", "endpoint": self.api_save_config, "methods": ["POST"], "summary": "保存配置", "auth": "bear"},
            {"path": "/assets", "endpoint": self.api_assets, "methods": ["GET"], "summary": "资产和背包", "auth": "bear"},
            {"path": "/market", "endpoint": self.api_market, "methods": ["GET"], "summary": "市场", "auth": "bear"},
            {"path": "/detail/{target_uid}", "endpoint": self.api_detail, "methods": ["GET"], "summary": "玩家详情", "auth": "bear"},
            {"path": "/office", "endpoint": self.api_office, "methods": ["GET"], "summary": "事务所", "auth": "bear"},
            {"path": "/screening", "endpoint": self.api_screening, "methods": ["GET"], "summary": "每日放映", "auth": "bear"},
            {"path": "/posters", "endpoint": self.api_posters, "methods": ["GET"], "summary": "电影图鉴", "auth": "bear"},
            {"path": "/history", "endpoint": self.api_history, "methods": ["GET"], "summary": "审计记录", "auth": "bear"},
            {"path": "/refresh", "endpoint": self.api_refresh, "methods": ["POST"], "summary": "只读刷新", "auth": "bear"},
            {"path": "/run/{module}", "endpoint": self.api_run, "methods": ["POST"], "summary": "执行模块", "auth": "bear"},
            {"path": "/pause", "endpoint": self.api_pause, "methods": ["POST"], "summary": "暂停", "auth": "bear"},
            {"path": "/resume", "endpoint": self.api_resume, "methods": ["POST"], "summary": "恢复", "auth": "bear"},
        ]
