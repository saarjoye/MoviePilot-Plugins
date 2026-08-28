"""好友买卖自动化编排引擎。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .client import PandaClientError, PandaFriendTradeClient
from .screening import build_submission
from .strategy import (
    choose_interaction,
    choose_work,
    is_target_on_cooldown,
    rank_market_candidates,
    select_commission_team,
)


AuditCallback = Callable[[Dict[str, Any]], None]

TASK_NAMES = {
    "claims": "奖励领取",
    "cultivation": "佣人培养",
    "market": "市场交易",
    "office": "事务所委托",
    "screening": "每日放映",
    "posters": "电影图鉴",
    "refresh": "数据刷新",
    "config": "插件设置",
    "scheduler": "自动调度",
    "plugin": "插件运行",
}
ACTION_NAMES = {
    "friendTradeClaimIncome": "领取佣人收益",
    "friendTradeClaimTaskReward": "领取任务奖励",
    "friendTradeLevelPosterClaim": "领取等级海报",
    "friendTradeAchievementClaim": "领取成就奖励",
    "friendTradeWork": "安排工作",
    "friendTradeInteract": "进行互动",
    "friendTradeBuy": "购买佣人",
    "friendTradeSnatch": "挖角佣人",
    "friendTradeCommissionSettle": "结算委托",
    "friendTradeCommissionStart": "派遣委托",
    "friendTradeScreeningStart": "开始放映挑战",
    "friendTradeScreeningSubmit": "提交放映答案",
    "budget_gate": "检查交易预算",
    "reserve_gate": "检查保留魔力",
    "slot_gate": "检查正式槽位",
    "candidate_gate": "筛选市场候选",
    "circuit_gate": "检查放映熔断",
    "solve": "求解放映挑战",
    "save": "保存设置",
    "run": "执行自动任务",
    "parse_cron": "检查调度时间",
}
WORK_NAMES = {"rest": "休息", "study": "学习", "train": "训练", "perform": "表演", "work": "工作"}
INTERACTION_NAMES = {"praise": "夸奖", "small_reward": "小奖励", "whisper": "说悄悄话", "pat": "摸头"}
SCREENING_NAMES = {"poster_memory": "海报闪记", "film_calibration": "胶片校准", "missing_frame": "缺帧补全"}
REWARD_NAMES = {
    "bonus": "魔力", "magic": "魔力", "reward_bonus": "魔力", "bonus_gain": "魔力", "magic_gain": "魔力",
    "exp": "经验", "experience": "经验", "relationship_exp": "关系经验", "relation_exp": "关系经验", "exp_gain": "经验",
    "mood_change": "心情", "mood_gain": "心情", "intimacy": "亲密度", "intimacy_gain": "亲密度", "affection": "亲密度",
    "poster": "海报", "posters": "海报", "poster_count": "海报", "item": "道具", "items": "道具",
    "reward_text": "奖励", "reward_desc": "奖励",
}


def _format_reward_value(label: str, value: Any) -> Optional[str]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        sign = "+" if value > 0 else ""
        return f"{label} {sign}{value:g}"
    if isinstance(value, str) and value.strip():
        return f"{label} {value.strip()}"
    if isinstance(value, list):
        return f"{label} {len(value)} 项" if value else None
    if isinstance(value, Mapping):
        name = value.get("name") or value.get("title")
        count = value.get("count") or value.get("quantity")
        if name:
            return f"{label} {name}" + (f" x{count}" if count else "")
    return None


def summarize_rewards(response: Mapping[str, Any]) -> str:
    """仅提取响应中明确标记为奖励或变化的字段，不推测最终余额。"""
    data = response.get("data") if isinstance(response, Mapping) else None
    if not isinstance(data, Mapping):
        return ""
    containers: List[Mapping[str, Any]] = []
    for key in ("reward_text", "reward_desc"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("rewards", "reward", "gains", "gain", "changes"):
        value = data.get(key)
        if isinstance(value, Mapping):
            containers.append(value)
    direct = {
        key: value for key, value in data.items()
        if key in REWARD_NAMES and (key.startswith("reward_") or key.endswith(("_gain", "_change")))
    }
    if direct:
        containers.append(direct)
    parts: List[str] = []
    for container in containers:
        for key, value in container.items():
            label = REWARD_NAMES.get(str(key))
            if not label:
                continue
            formatted = _format_reward_value(label, value)
            if formatted and formatted not in parts:
                parts.append(formatted)
    return "、".join(parts)


def enrich_audit_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """为新旧审计记录补齐中文展示字段。"""
    result = dict(record)
    subsystem = str(result.get("subsystem") or "")
    action = str(result.get("action") or "")
    skipped = bool(result.get("skipped") or result.get("planned"))
    result.setdefault("task_name", TASK_NAMES.get(subsystem, "其他任务"))
    result.setdefault("action_name", ACTION_NAMES.get(action, "执行任务"))
    result.setdefault("detail", str(result.get("message") or "无详细说明"))
    if skipped:
        result.setdefault("reward", "无（任务已跳过）")
        result["status"] = "skipped"
    elif result.get("success"):
        result.setdefault("reward", "站点未返回收益明细")
        result["status"] = "success"
    else:
        result.setdefault("reward", "无（执行失败）")
        result["status"] = "failed"
    return result


class AutomationEngine:
    """按配置执行读取、规划和受控写动作。"""

    def __init__(
        self,
        client: PandaFriendTradeClient,
        config: Mapping[str, Any],
        state: Optional[Dict[str, Any]] = None,
        audit: Optional[AuditCallback] = None,
    ) -> None:
        self.client = client
        self.config = dict(config)
        self.state = state if isinstance(state, dict) else {}
        self.audit = audit or (lambda record: None)
        self.state.setdefault("consecutive_failures", 0)
        self.state.setdefault("circuit_open", False)
        self.state.setdefault("target_cooldowns", {})
        self.state.setdefault("daily_trade", {})

    def _record(self, subsystem: str, action: str, success: bool, message: str, **extra: Any) -> Dict[str, Any]:
        record = enrich_audit_record({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "subsystem": subsystem,
            "action": action,
            "success": bool(success),
            "message": str(message),
            **extra,
        })
        self.audit(record)
        return record

    def _success(self) -> None:
        self.state["consecutive_failures"] = 0

    def _failure(self, error: Exception) -> None:
        failures = int(self.state.get("consecutive_failures") or 0) + 1
        self.state["consecutive_failures"] = failures
        if failures >= 3:
            self.state["circuit_open"] = True
            self.state["circuit_reason"] = type(error).__name__

    def refresh(self) -> Dict[str, Any]:
        """并发读取玩法页；失败模块保留同一站点上一轮成功数据。"""
        reads = {
            "home": ("friendTradeInitOrHome", {}),
            "inventory": ("friendTradeInventory", {}),
            "market": ("friendTradeMarketList", {"page": 1, "size": 20, "sort_field": "current_price", "sort_type": "asc", "ownership_filter": "", "keyword": ""}),
            "office": ("friendTradeCommissionBoard", {}),
            "screening": ("friendTradeScreeningHome", {}),
            "poster_board": ("friendTradePosterTaskBoard", {}),
            "poster_collection": ("friendTradePosterCollection", {}),
            "poster_history": ("friendTradePosterHistory", {}),
        }
        site_id = getattr(self.client, "site_id", self.config.get("site_id"))
        previous = self.state.get("snapshot") or {}
        if str(previous.get("site_id")) != str(site_id):
            previous = {}
        attempted_at = datetime.now().astimezone().isoformat(timespec="seconds")
        snapshot: Dict[str, Any] = {
            "site_id": site_id,
            "site_name": getattr(self.client, "site_name", None),
            "refreshed_at": previous.get("refreshed_at"),
            "refresh_attempted_at": attempted_at,
            "errors": {},
            "stale_sections": [],
            "section_updated_at": dict(previous.get("section_updated_at") or {}),
        }

        jobs = {
            key: (lambda action=action, params=params: self.client.post_action(action, params).get("data"))
            for key, (action, params) in reads.items()
        }
        jobs["rankings"] = self.client.get_rankings
        with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as executor:
            futures = {executor.submit(job): key for key, job in jobs.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    snapshot[key] = future.result()
                    snapshot["section_updated_at"][key] = attempted_at
                except Exception as error:
                    snapshot["errors"][key] = str(error) if isinstance(error, PandaClientError) else type(error).__name__
                    if key.startswith("poster_"):
                        poster_name = key.removeprefix("poster_")
                        old_value = (previous.get("posters") or {}).get(poster_name)
                    else:
                        old_value = previous.get(key)
                    snapshot[key] = old_value
                    if old_value is not None:
                        snapshot["stale_sections"].append(key)
        snapshot["posters"] = {
            "board": snapshot.pop("poster_board", None),
            "collection": snapshot.pop("poster_collection", None),
            "history": snapshot.pop("poster_history", None),
        }
        poster_keys = {"poster_board", "poster_collection", "poster_history"}
        if poster_keys.intersection(snapshot["stale_sections"]):
            snapshot["stale_sections"].append("posters")
        if any(snapshot["section_updated_at"].get(key) == attempted_at for key in poster_keys):
            snapshot["section_updated_at"]["posters"] = attempted_at
        snapshot["stale_sections"] = sorted(set(snapshot["stale_sections"]) - poster_keys)
        if not snapshot["errors"]:
            snapshot["refreshed_at"] = attempted_at
        self.state["snapshot"] = snapshot
        if len(snapshot["errors"]) >= 3:
            self._failure(PandaClientError("多个读取模块失败"))
        else:
            self._success()
        return snapshot

    def _can_write(self) -> bool:
        return bool(
            self.config.get("enabled")
            and self.config.get("risk_acknowledged")
            and not self.state.get("paused")
            and not self.state.get("circuit_open")
        )

    def _execute(
        self,
        subsystem: str,
        action: str,
        params: Optional[Mapping[str, Any]] = None,
        detail: Optional[str] = None,
        reward_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._can_write():
            return self._record(subsystem, action, False, detail or "真实写入未启用或被安全门禁阻止", skipped=True)
        try:
            response = self.client.post_action(action, params, write=True)
            self._success()
            reward = summarize_rewards(response) or reward_hint or "站点未返回收益明细"
            message = detail or f"{ACTION_NAMES.get(action, '任务')}执行成功"
            return self._record(subsystem, action, True, message, detail=message, reward=reward, response_ret=response.get("ret"))
        except Exception as error:
            self._failure(error)
            message = str(error)
            if "timeout" in message.lower() or "超时" in message:
                try:
                    self.refresh()
                    message = "写操作超时，已只读刷新状态；结果未知，未重试"
                except Exception:
                    message = "写操作超时且状态确认失败；结果未知，未重试"
                self.state["circuit_open"] = True
                self.state["circuit_reason"] = "unknown_write_result"
            return self._record(subsystem, action, False, message, detail=detail or message)

    def _run_claims(self, home: Mapping[str, Any]) -> List[Dict[str, Any]]:
        records = []
        if float(home.get("claimable_income") or 0) > 0:
            amount = float(home.get("claimable_income") or 0)
            records.append(self._execute("claims", "friendTradeClaimIncome", detail="领取今日佣人收益", reward_hint=f"魔力 +{amount:g}"))
        for task in home.get("task_status") or []:
            if task.get("status") in ("claimable", "completed", "achieved") and not task.get("claimed_at"):
                records.append(self._execute("claims", "friendTradeClaimTaskReward", {"task_key": task.get("task_key")}, detail="领取一项已完成任务奖励"))
        posters = ((home.get("business_summary") or {}).get("level_poster_rewards") or {})
        for level in posters.get("pending_levels") or []:
            records.append(self._execute("claims", "friendTradeLevelPosterClaim", {"level": int(level)}, detail=f"领取 Lv.{int(level)} 等级海报", reward_hint="等级海报 x1"))
        achievements = ((home.get("business_summary") or {}).get("achievements") or {})
        items = achievements.get("items") if isinstance(achievements, Mapping) else achievements
        for item in items or []:
            if item.get("status") in ("claimable", "achieved"):
                key = item.get("type") or item.get("achievement_type")
                if key:
                    records.append(self._execute("claims", "friendTradeAchievementClaim", {"achievement_type": key}, detail="领取一项已达成的成就奖励"))
        return records

    def _run_cultivation(self, home: Mapping[str, Any]) -> List[Dict[str, Any]]:
        records = []
        paid_budget = float(self.config.get("daily_interaction_budget") or 0)
        for index, asset in enumerate(home.get("my_assets") or [], start=1):
            if asset.get("is_temporary"):
                continue
            work = choose_work(asset)
            if work:
                work_name = str(work.get("name") or WORK_NAMES.get(str(work["key"]), "日常工作"))
                detail = f"第 {index} 位佣人执行「{work_name}」；选择原因：{work.get('reason') or '均衡成长'}"
                records.append(self._execute("cultivation", "friendTradeWork", {"target_uid": asset.get("slave_uid"), "work_key": work["key"]}, detail=detail))
            interaction = choose_interaction(asset, paid_budget)
            if interaction:
                interaction_name = INTERACTION_NAMES.get(str(interaction["key"]), "日常互动")
                cost = float(interaction.get("cost") or 0)
                detail = f"与第 {index} 位佣人进行「{interaction_name}」；选择原因：{interaction.get('reason') or '均衡成长'}"
                reward_hint = f"消耗魔力 {cost:g}" if cost > 0 else None
                records.append(self._execute("cultivation", "friendTradeInteract", {"target_uid": asset.get("slave_uid"), "interaction_key": interaction["key"]}, detail=detail, reward_hint=reward_hint))
                paid_budget = max(0.0, paid_budget - float(interaction.get("cost") or 0))
        return records

    def _market_rows(self, first_page: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        rows = list(first_page.get("list") or [])
        pagination = first_page.get("pagination") or {}
        total = int(pagination.get("total") or len(rows))
        size = int(pagination.get("size") or 20)
        max_pages = max(1, int(self.config.get("market_scan_pages") or 10))
        pages = min(max_pages, (total + size - 1) // size)
        for page in range(2, pages + 1):
            data = self.client.post_action("friendTradeMarketList", {"page": page, "size": size, "sort_field": "current_price", "sort_type": "asc", "ownership_filter": "", "keyword": ""}).get("data") or {}
            rows.extend(data.get("list") or [])
        return rows

    def _daily_trade_state(self) -> Dict[str, Any]:
        key = datetime.now().astimezone().date().isoformat()
        ledger = self.state.setdefault("daily_trade", {})
        ledger.setdefault(key, {"count": 0, "spent": 0.0})
        for old_key in list(ledger):
            if old_key != key:
                ledger.pop(old_key, None)
        return ledger[key]

    def _run_market(self, home: Mapping[str, Any], market: Mapping[str, Any], inventory: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        capacity = home.get("capacity_summary") or {}
        assets = home.get("my_assets")
        used_count = len(assets) if isinstance(assets, list) else int(capacity.get("formal_used_count") or 0)
        total_count = int(capacity.get("formal_capacity") or 0)
        if total_count <= 0:
            return [self._record("market", "slot_gate", False, "站点未返回正式佣人槽位上限，未执行交易", skipped=True)]
        free_slots = max(0, total_count - used_count)
        if not capacity.get("can_acquire", free_slots > 0) or free_slots <= 0:
            return [self._record("market", "slot_gate", False, "正式佣人槽位已满，未执行交易", skipped=True)]
        daily_budget = float(self.config.get("daily_trade_budget") or 0)
        single_cap = float(self.config.get("single_trade_cap") or 0)
        if daily_budget <= 0 or single_cap <= 0:
            return [self._record("market", "budget_gate", False, "每日交易预算或单笔上限为 0，未执行交易", skipped=True)]
        ledger = self._daily_trade_state()
        remaining_count = min(free_slots, max(0, int(self.config.get("max_daily_trades") or 3) - int(ledger.get("count") or 0)))
        remaining_budget = max(0.0, daily_budget - float(ledger.get("spent") or 0))
        reserve = float(self.config.get("reserve_bonus") or 100000)
        raw_bonus = (inventory or {}).get("magic_balance")
        if raw_bonus is None or raw_bonus == "":
            return [self._record("market", "reserve_gate", False, "站点未返回当前魔力，未执行交易", skipped=True)]
        available_bonus = float(raw_bonus)
        if available_bonus - reserve <= 0:
            return [self._record("market", "reserve_gate", False, f"当前魔力不足以保留配置的 {reserve:g} 魔力，未执行交易", skipped=True)]

        candidates = rank_market_candidates(self._market_rows(market))
        records = []
        for candidate in candidates:
            if remaining_count <= 0:
                break
            if candidate.score < float(self.config.get("min_market_score") or 70):
                continue
            price = candidate.price * (1.2 if candidate.owned else 1.0)
            if candidate.owned and not self.config.get("allow_snatch", False):
                continue
            if price <= 0 or price > single_cap or price > remaining_budget:
                continue
            cooldown = self.state.get("target_cooldowns", {}).get(str(candidate.uid))
            if is_target_on_cooldown(cooldown, int(self.config.get("target_cooldown_days") or 7)):
                continue
            action = "friendTradeSnatch" if candidate.owned else "friendTradeBuy"
            action_name = "挖角" if candidate.owned else "购买"
            detail = f"{action_name}一名市场候选；策略评分 {candidate.score:g}，预计花费 {price:g} 魔力"
            record = self._execute("market", action, {"target_uid": candidate.uid}, detail=detail, reward_hint=f"消耗魔力 {price:g}")
            record["candidate_score"] = candidate.score
            record["price"] = price
            records.append(record)
            if record.get("success") and not record.get("planned"):
                ledger["count"] = int(ledger.get("count") or 0) + 1
                ledger["spent"] = float(ledger.get("spent") or 0) + price
                self.state.setdefault("target_cooldowns", {})[str(candidate.uid)] = datetime.now().astimezone().isoformat(timespec="seconds")
                remaining_count -= 1
                remaining_budget -= price
        if not records:
            records.append(self._record("market", "candidate_gate", False, "没有候选人同时满足最低评分、预算、冷却时间和挖角设置，未执行交易", skipped=True))
        return records

    def _run_office(self, home: Mapping[str, Any], office: Mapping[str, Any]) -> List[Dict[str, Any]]:
        records = []
        runs = office.get("running") or office.get("runs") or []
        for run in runs:
            if run.get("status") in ("ready", "completed", "settleable") or run.get("is_ready"):
                title = str(run.get("title") or run.get("name") or "已完成委托")
                records.append(self._execute("office", "friendTradeCommissionSettle", {"run_id": run.get("id")}, detail=f"结算委托「{title}」"))
        unlocked = bool(office.get("unlocked", office.get("is_unlocked", bool(runs or office.get("offers") or office.get("today_offers")))))
        if not unlocked:
            return records
        parallel_limit = int(office.get("parallel_limit") or 0)
        active_count = sum(1 for run in runs if run.get("status") not in ("ready", "completed", "settled"))
        slots = max(0, parallel_limit - active_count)
        assets = home.get("my_assets") or office.get("relationships") or []
        offers = office.get("offers") or office.get("today_offers") or []
        offers = sorted(offers, key=lambda item: (float(item.get("base_exp") or 0) + float(item.get("base_bonus") or 0) / 100.0) / max(float(item.get("duration_hours") or 1), 1), reverse=True)
        for offer in offers[:slots]:
            team = select_commission_team(offer, assets, int(office.get("team_size_limit") or 1))
            if team:
                title = str(offer.get("title") or offer.get("name") or "今日委托")
                records.append(self._execute("office", "friendTradeCommissionStart", {"offer_id": offer.get("id"), "relationship_ids": json.dumps(team, separators=(",", ":"))}, detail=f"派遣 {len(team)} 位佣人执行委托「{title}」"))
        return records

    def _run_screening(self, screening: Mapping[str, Any]) -> List[Dict[str, Any]]:
        games_source = screening.get("games") or screening.get("game_list") or screening.get("challenges") or []
        unlocked = bool(screening.get("unlocked", screening.get("is_unlocked", bool(games_source))))
        if not unlocked or int(screening.get("remaining_attempts") or screening.get("attempts_remaining") or 0) <= 0:
            return []
        games = [game.get("key") for game in games_source if game.get("key")]
        enabled = [key for key in ("poster_memory", "film_calibration", "missing_frame") if key in games]
        if not enabled:
            return []
        completed = ((screening.get("variety_bonus") or {}).get("completed_game_keys") or [])
        game_key = next((key for key in enabled if key not in completed), enabled[0])
        screening_circuit = self.state.get("screening_circuit") or {}
        if screening_circuit.get("game") == game_key:
            return [self._record("screening", "circuit_gate", False, f"「{SCREENING_NAMES.get(game_key, '放映挑战')}」已熔断，未执行", skipped=True)]
        if not self._can_write():
            return [self._execute("screening", "friendTradeScreeningStart", {"game_key": game_key})]
        try:
            start = self.client.post_action("friendTradeScreeningStart", {"game_key": game_key}, write=True)
            self._success()
            game_name = SCREENING_NAMES.get(game_key, "放映挑战")
            self._record("screening", "friendTradeScreeningStart", True, f"开始「{game_name}」挑战", detail=f"开始「{game_name}」挑战", reward="挑战尚未结算")
        except Exception as error:
            self._failure(error)
            return [self._record("screening", "friendTradeScreeningStart", False, str(error))]
        challenge = (start.get("data") or {}).get("challenge")
        if not isinstance(challenge, Mapping):
            error = PandaClientError("放映开始响应缺少 challenge")
            self._failure(error)
            return [self._record("screening", "friendTradeScreeningStart", False, str(error))]
        try:
            submission = build_submission(challenge)
        except Exception as error:
            self.state["screening_circuit"] = {"game": game_key, "reason": str(error)}
            return [self._record("screening", "solve", False, str(error))]
        game_name = SCREENING_NAMES.get(game_key, "放映挑战")
        return [self._execute("screening", "friendTradeScreeningSubmit", submission, detail=f"提交「{game_name}」答案")]

    def run(self, modules: Optional[Sequence[str]] = None, force_selected: bool = False) -> Dict[str, Any]:
        """执行指定模块并返回脱敏运行摘要。"""
        selected = set(modules or ("claims", "cultivation", "market", "office", "screening", "posters"))
        snapshot = self.refresh()
        home = snapshot.get("home") or {}
        records: List[Dict[str, Any]] = []
        if "claims" in selected and (force_selected or self.config.get("auto_claim", True)):
            records.extend(self._run_claims(home))
        if "cultivation" in selected and (force_selected or self.config.get("auto_cultivation", True)):
            records.extend(self._run_cultivation(home))
        if "market" in selected and (force_selected or self.config.get("auto_market", False)):
            records.extend(self._run_market(home, snapshot.get("market") or {}, snapshot.get("inventory") or {}))
        if "office" in selected and (force_selected or self.config.get("auto_office", True)):
            records.extend(self._run_office(home, snapshot.get("office") or {}))
        if "screening" in selected and (force_selected or self.config.get("auto_screening", True)):
            records.extend(self._run_screening(snapshot.get("screening") or {}))
        return {
            "success": not any(not record.get("success") and not (record.get("skipped") or record.get("planned")) for record in records),
            "records": records,
            "snapshot": snapshot,
            "circuit_open": bool(self.state.get("circuit_open")),
        }


def nested_value(mapping: Mapping[str, Any], path: Iterable[str], default: Any = None) -> Any:
    """读取嵌套数据，缺失时返回默认值。"""
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return default if current is None else current
