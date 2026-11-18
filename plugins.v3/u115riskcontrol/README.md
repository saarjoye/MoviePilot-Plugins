# u115风控参数

杩欐槸涓€涓?MoviePilot 鎻掍欢锛岀敤浜庡湪杩愯鏃朵负 `u115` 瀛樺偍娉ㄥ叆鏇翠繚瀹堢殑闄愭祦鍙傛暟锛岄伩鍏嶆瘡娆″崌绾?MP2 瀹瑰櫒鍚庡張瑕佹墜宸ヤ慨鏀?`u115.py`銆?
当前版本：`0.3.6`

## v0.3.6 MoviePilot v3 历史查询修复

- 修复 v3 环境下扫描崩溃：`TransferHistory.list_by_page(transfer_history._db, ...)` 的 `_db` 在 v3 为 `None`，报 `'NoneType' object has no attribute 'execute'`。
- 改为优先使用 `app.db.session.SessionFactory()` 取会话，失败时回退到旧版 Oper 的 `_db`；两者都不可用时安全跳过本次扫描并记录警告，不再抛异常。
- 会话用完后关闭，避免 v3 连接泄漏。

## v0.3.5 冷却自动上报

- MoviePilot 内部撞限后会直接 `sleep(limit_sleep_seconds)` 再重试，本版用“单次调用耗时异常长”反推硬风控已发生，主动把共享冷却置为不可用，避免新实例拿不到 `_limit_until` 时冷却永远不生效。
- 阈值取 `limit_sleep_seconds * 0.5`，封顶 600 秒，下限 30 秒；HTTP 错误重试的最长等待为 32 秒，不会误判。

## v0.3.4 启动补偿扫描延迟

- 插件启动补偿扫描改为延迟 `retry_failed_delay_seconds`（默认 60 秒）后才执行，避免 MoviePilot 数据库尚未就绪时调用 `TransferHistory.list_by_page` 报 `'NoneType' object has no attribute 'execute'`。

## v0.3.3 115 共享硬风控冷却

- 115 硬风控冷却改为跨 `U115Pan` 实例共享的类级状态：新建实例、插件重载、MP 重启后都不会再从零开始发请求。
- 冷却状态写入插件数据 `native_cooldown`，插件启动时恢复剩余冷却与连续失败轮次。
- 冷却期间所有请求统一等待（叠加 0–90 秒抖动，打散同时醒来的并发请求）；冷却结束后只放行一个探针请求，成功后才恢复正常节奏，失败则整体重新计时。
- 连续多轮硬风控按 1.0、1.5、2.0、2.5、3.0 倍放大冷却，避免每小时整点再次撞上限。
- 探针恢复成功记录事件 `cooldown_recovered`；状态 API 的 `cooldown` 增加 `shared_until`、`guard_active`、`fail_streak`、`probe_in_flight`。

## v0.3.2 任务状态与页面优化

- 兼容 `errmsg`、`error`、`error_msg`、`error_message`、`message`、`reason`、`detail` 及 `result/data/response` 等嵌套错误字段。
- 网络超时和 HTTP 429/502/503/504 允许自动重试；认证、权限、源文件缺失、记录损坏和未知错误不会自动重试。
- 未知或权限类任务支持单条人工重试；人工操作仍受风控冷却、API 安全余量和 24 小时次数限制。
- 任务状态明确区分“冷却中”“可重试”“待人工确认”“需人工处理”，人工任务不显示误导性的自动倒计时。
- 状态 API 增加 `task_summary` 和统一任务状态字段，页面总览显示自动重试、待人工确认和需人工处理数量。
- 页面继续采用打开或手动刷新时的快照，不在页面停留期间逐秒自动刷新。

## v0.3.1 任务剩余时间显示

- 风控冷却和任务等待时间改用“约 X 小时 X 分 X 秒”显示，避免只显示秒数难以判断。
- 待重试任务增加剩余秒数、格式化剩余时间和是否自动重试字段。
- 冷却中的任务显示距自动重试时间；待人工确认和需人工处理的任务明确显示不会自动重试。
- 状态 API 同步返回全局冷却和调度等待的格式化剩余时间。
- 页面仍按打开或手动刷新时的快照更新，MoviePilot 页面停留期间不会自动跳动。

## 当前版本能力

- 鎸佷箙鍖栨櫘閫氭帴鍙?QPS
- 鎸佷箙鍖栦笅杞芥帴鍙?QPS
- 鎸佷箙鍖?`limit_sleep_seconds`
- 鏀寔灏忔椂杞槇鍊?- 鏀寔杈惧埌杞槇鍊煎悗涓诲姩鍐峰嵈
- 鏀寔椋庢帶鍐峰嵈缁撴潫鍚庤嚜鍔ㄩ噸璇?MP 濯掍綋鏁寸悊澶辫触鍘嗗彶
- 鏀寔鍦ㄩ噸璇曟棩蹇椾腑鏄剧ず璇嗗埆鍒扮殑澶辫触浠诲姟鍚嶃€佽烦杩囦换鍔″悕鍜岃烦杩囧師鍥?- 鏀寔鍦ㄧ姸鎬侀〉鏄剧ず澶辫触鏁寸悊閲嶈瘯杩涘害銆佸綋鍓嶄换鍔″拰 MP 鏁寸悊鎺ュ彛鎻愪氦缁撴灉
- 鏀寔鍦ㄧ姸鎬侀〉棣栧睆鏄剧ず褰撳墠鎬荤姸鎬侊細姝ｅ父銆侀鎺т腑銆佸紓甯搞€佺瓑寰呮壂鎻忔垨鏁寸悊鎵ц涓?- 鏀寔鍚屾绛夊緟 MP 鏁寸悊缁撴灉锛屽苟澶嶆煡鏁寸悊鍘嗗彶锛岄伩鍏嶆妸鍚庡彴鍏ラ槦璇垽涓烘暣鐞嗘垚鍔?- 鏀寔璇嗗埆婧愭枃浠朵笉瀛樺湪銆佹病鏈夊彲鏁寸悊濯掍綋鏂囦欢绛変笉鍙嚜鍔ㄤ慨澶嶇殑澶辫触鍘熷洜
- 鏀寔璇嗗埆 MoviePilot 鍐呯疆 `U115Pan._limit_until` 鍐峰嵈绐楀彛锛岄伩鍏?MP 鍐呴儴 sleep 鍚庢彃浠舵紡鎺夐噸璇曡皟搴?- 鏀寔鎻掍欢鍚姩鍚庢墽琛屼竴娆″け璐ユ暣鐞嗚ˉ鍋挎壂鎻忥紝閬垮厤瀹夎鏂扮増鏈椂鍐峰嵈宸茬粡缁撴潫鑰岄敊杩囬噸璇曡皟搴?- 鎻掍欢鍚敤鍚庤嚜鍔ㄤ负鏂板缓鐨?`U115Pan` 瀹炰緥娉ㄥ叆鍙傛暟
- 灏濊瘯涓哄綋鍓嶅凡瀛樺湪鐨?`U115Pan` 瀹炰緥鐑洿鏂板弬鏁?
- 鐘舵€侀〉鏂板寰呴噸璇曚换鍔℃竻鍗曪紝鎸夋潯鏄剧ず澶辫触整理历史、路径、大小、失败时间、重试次数和当前状态。
- 鏀寔閫氳繃鍗曟潯 API 瑙﹀彂澶辫触整理重试，继续遵守冷却、滚动次数和安全余量限制。
- 寰呴噸璇曚换鍔℃竻鍗曟敮鎸佺┖鏁版嵁銆佹暟鎹簱涓嶅彲鐢ㄥ拰闀胯矾寰勬樉绀鸿秺鐣岄€€鍖栥€?

## v0.1.17 UI 修复

- 修复待重试任务列表只显示状态色点、任务文本未渲染的问题。
- 列表行改用 MoviePilot 当前支持的 `VListItem` 标题和副标题属性显示任务信息。
- 状态和立即重试按钮改用组件内容插槽显示文字，兼容现有 Vuetify 页面渲染器。

## v0.1.18 UI 修复

- 移除在 MoviePilot 页面中退化为彩色圆点的 `VChip` 状态控件。
- 将任务状态、下次重试时间和失败原因合并到稳定可渲染的列表副标题中。

## v0.2.0 UI 与自动补偿重构

- 状态页拆分为“状态总览”“待重试任务”“风控事件”三个可切换标签。
- 新增每 60 秒一次的独立失败整理补偿扫描，并使用类级锁避免重复调度。
- MP 整理返回提交成功后最多轮询 30 秒确认最终历史状态，避免过早判定失败。

## v0.2.1 标签显示修复

- 修复状态页标签文字在 MoviePilot 页面渲染器中不显示的问题。
- 将标签标题改为使用 `VTab` 默认内容插槽，保留三个视图的切换结构。

## v0.2.2 状态页分区兼容修复

- 修复 `VTabs` 与 `VWindow` 在 MoviePilot 页面中标签和内容无法联动的问题。
- 使用单开 `VExpansionPanels` 显示状态总览、待重试任务和风控事件，保证任务列表与日志可进入查看。

## v0.2.3 状态刷新与操作修复

- 新增有效的“刷新状态”按钮，调用 MoviePilot 页面事件协议并重新读取状态页。
- 修复“立即重试”按钮使用错误链接、文字不显示和无法触发插件 API 的问题。
- 状态页仍是按需刷新；MoviePilot 当前 Vuetify 页面协议不支持插件自行开启定时轮询。

## v0.2.4 失败任务去重与错误详情

- 按 `download_hash + tmdbid + season + episode` 合并同一媒体任务产生的多个失败整理历史，避免新历史 ID 造成重复推送循环。
- 兼容迁移旧版按 `history_id` 保存的重试记录，并合并已有尝试次数。
- 原生整理重试显式关闭 `no_error_log`，保留 MP 返回的网络、HTTP 或 115 业务错误详情。
- 重试状态数据版本提升为 3，旧数据会在下一次扫描时迁移到逻辑任务键。

## v0.3.0 安全重试调度器

- 使用 MoviePilot 原生 `get_service()` 注册固定 60 秒周期扫描，不再维护常驻扫描线程。
- 按不含历史 ID 和目标路径的稳定任务组共享重试次数、退避和冷却状态。
- 重试状态升级为 v4；旧记录会按当前失败历史迁移，无法映射的记录保留为脱敏旧记录。
- 新失败和前三次尝试分别执行 5、15、60 分钟退避，24 小时内最多尝试 3 次。
- 状态页显示调度器、绝对扫描时间、任务组重试时间、等待原因和脱敏错误分类。
- API 仅注册 `/U115RiskControl/status`、`/U115RiskControl/retry` 和 `/U115RiskControl/page_refresh`。

## 鎺ㄨ崘榛樿鍊?
- `api_qps = 1`
- `download_qps = 1`
- `limit_sleep_seconds = 3600`
- `hourly_soft_limit = 60`
- `hourly_soft_cooldown = 1200`
- `retry_failed_after_cooldown = true`
- `retry_failed_on_startup = true`
- `retry_failed_delay_seconds = 60`
- `retry_failed_max_count = 1`

## v0.1.14 补整理策略

- 单条失败历史改为 24 小时滚动窗口内最多重试 3 次，不再累计 3 次后永久跳过。
- 每条失败历史保存 `attempt_timestamps`、`last_attempt_ts`、`next_retry_after`、`success`、`message`、`manual_required`。
- 达到 24 小时窗口上限时显示“等待冷却后重试”，跳过不记为全局异常。
- 补整理前检查最近 1 小时请求安全余量，接近 `hourly_soft_limit` 时延后重试。
- 默认每轮只补 1 条，避免风控刚结束时集中触发请求。
- 优先使用 MoviePilot 原生 `TransferChain.redo_transfer_history(history_id)`，不可用时兼容回退 `manual_transfer`。
- 成功判定会复查同源路径、目标路径、`download_hash`、`tmdbid + season + episode` 的成功历史；确认目标已存在时也会视为已处理。
- `manual_required` 仅在源文件缺失、记录损坏或连续多个周期无法处理时设置。

## v0.1.15 多集种子修复

- 修复多集种子中同 `download_hash` 任意一集成功就误判当前失败集已成功的问题。
- `download_hash` 现在只作为候选范围，必须同时匹配 `tmdbid`、`seasons`、`episodes` 才能确认成功。
- 旧版误写的 `success=true` 会在下一轮扫描时重新复查；如果没有同季同集成功记录，会自动回到滚动重试队列。

## 参数说明

- `api_qps`锛氭櫘閫氭帴鍙ｆ瘡绉掕姹傛暟锛屽缓璁繚鎸?`1`
- `download_qps`锛氫笅杞芥帴鍙ｆ瘡绉掕姹傛暟锛岄粯璁?`1`
- `limit_sleep_seconds`锛?15 鏄庣‘杩斿洖璁块棶涓婇檺鍚庣殑鏈湴鍐峰嵈绉掓暟
- `hourly_soft_limit`：插件侧自定义的 1 小时请求软阈值，设为 `0` 表示关闭
- `hourly_soft_cooldown`锛氳揪鍒拌蒋闃堝€煎悗鐨勪富鍔ㄥ喎鍗寸鏁帮紝璁句负 `0` 琛ㄧず鍙褰曚笉鏆傚仠
- `retry_failed_after_cooldown`锛氶鎺у喎鍗寸粨鏉熷悗鏄惁鑷姩鏌ユ壘 MP 濯掍綋鏁寸悊澶辫触鍘嗗彶骞堕噸璇?- `retry_failed_on_startup`锛氭彃浠跺惎鍔ㄥ悗鏄惁琛ュ伩鎵弿涓€娆″け璐ユ暣鐞嗗巻鍙诧紝閫傚悎澶勭悊瀹夎鏂扮増鏈椂鍐峰嵈宸茬粡缁撴潫鐨勫満鏅?- `retry_failed_delay_seconds`锛氬喎鍗寸粨鏉熷悗棰濆绛夊緟绉掓暟锛岄伩鍏嶅垰鎭㈠灏辩珛鍗抽噸鏂拌姹?- `retry_failed_max_count`锛氬崟娆℃渶澶氶噸璇曞け璐ユ暣鐞嗘潯鏁帮紝璁句负 `0` 琛ㄧず涓嶉檺鍒?
## 发布说明

濡傛灉浣跨敤 `D:\寮€鍙慭github鍙戝竷\mp_plugin_market_publisher.py` 鍙戝竷锛屽缓璁墽琛岋細

```powershell
python D:\寮€鍙慭github鍙戝竷\mp_plugin_market_publisher.py publish `
  --plugin-source D:\寮€鍙慭MP鎻掍欢\u115椋庢帶鍙傛暟\u115riskcontrol `
  --repo-url https://github.com/<浣犵殑鐢ㄦ埛鍚?/<浣犵殑鎻掍欢浠撳簱> `
  --package-version base `
  --labels 工具,115,风控 `
  --icon-source D:\寮€鍙慭MP鎻掍欢\u115椋庢帶鍙傛暟\u115riskcontrol\U115RiskControl.jpg `
  --history-note "棣栦釜鐗堟湰锛氭彁渚?u115 椋庢帶鍙傛暟鎸佷箙鍖栭厤缃?
```


