# 栖影签到 (HDHavenSignin)

`HDHavenSignin` 是一个专为 `MoviePilot`（深度兼容 V2 及 V3）开发的「栖影 (HDHaven)」站点自动签到插件。

## 🌟 核心功能

- **定时自动签到**: 支持 Cron 表达式自定义调度（默认每天上午 8 点 `0 8 * * *`），带随机延迟防并发识别。
- **双签到模式**:
  - `normal`（普通稳健）：稳定获取基础积分奖励。
  - `gamble`（赌狗签到）：高收益签到，有机会赢得更多积分。
- **积分风控防扣保护**: 当选择赌狗签到时，如果账号当前积分低于设定的风控阈值（默认 20 分），插件会自动降级为普通签到，防止积分被扣为负数。
- **深度兼容 MoviePilot 梯子网络**:
  - 针对国内网络环境，默认开启代理开关（`use_proxy = True`）。
  - 自动无缝接入 MoviePilot 系统设置的梯子代理（`settings.PROXY`）。
  - 支持填入自定义独立代理地址（如 `http://127.0.0.1:7890` 或 `socks5://127.0.0.1:10808`），留空时自动复用系统梯子。
- **多认证模式与官方 OPENAPI 接入**:
  - OPENAPI 授权（推荐长效稳定）：支持配置站点 `openapi_app_id`、`openapi_app_secret` 与 `openapi_user_token`，自动切换至 `/api/openapi/v1/*` 标准接口；
  - Cookie 认证：支持填入 `hdh_session` 单项或浏览器完整 Cookie，插件自动清洗提取；
  - 智能安全拦截分类：精准区分 `SESSION_VERIFY_REQUIRED`（网络出口变化需人机验证）、`SESSION_DEVICE_CHANGED`（登录设备/环境变化需重新登录）、`SCRAPE_CHALLENGE_REQUIRED`（频控退避重试）、`APP_REQUIRED`（引导配置 OPENAPI）与 `BROWSER_REQUIRED`，杜绝误报 Cookie 失效；
  - 账号密码认证：支持自动登录，当遇到 Cloudflare Turnstile 人机验证时友好提示。
- **V3 深度主题自适应与看板**:
  - 完美适配 MoviePilot V3 (Vuetify 3) 深色与浅色模式，根治旧版白底浅字看不清的问题。
  - 可视化展示用户信息、头像、等级头衔、当前总积分、今日签到状态、连续签到天数。
  - 当月签到与积分走势图（SVG 矢量面积折线图，自适应深浅色主题文字与线条）。
  - 完整签到历史明细表格（15 次记录）。
- **通知推送**: 支持 MoviePilot 系统通知，签到成功、重复签到、登录态失效或网络异常时优雅排版推送。

## 📦 安装与使用

1. 将本插件仓库添加到 MoviePilot 的插件源：
   ```text
   https://github.com/saarjoye/MoviePilot-Plugins/
   ```
2. 在 MoviePilot 插件市场中搜索并安装「栖影签到」。
3. 打开插件配置：
   - 填写 Cookie（推荐直接从浏览器复制 `hdh_session=...`）。
   - 确认代理配置（默认自动使用 MP 系统梯子）。
   - 选择签到模式与保护阈值。
4. 保存配置并测试执行。

## 📝 更新日志

### v1.0.7 (2026-10-12)
- **修复 v1.0.6 仍误报“请更新 hdh_session 会话 Cookie”的最后一层根因：裸 401 + 服务端主动清空会话**:
  - 实测确认站点在判定程序化 Cookie 直连受限时，会返回 **HTTP 401 裸响应（无 `code` 字段）**，并同时下发 `Set-Cookie: hdh_session=; Max-Age=0` **主动作废服务端会话**；真实 48-hex Cookie 与随机假 Cookie 表现完全一致（同码、同清空响应头），证明该 Cookie 已不再被站点视为有效会话；
  - 新增 `CookieSessionRevokedError` 异常与 `_is_session_cookie_revoked()` 检测：解析响应头 `Set-Cookie`（兼容 requests 多值合并与 MagicMock/None），识别 `hdh_session=` 被置空即判定为 **`cookie_session_revoked`**，不再落入普通 `unauthorized`；
  - 主流程新增独立分支：通知文案改为“站点已主动作废 hdh_session 会话，**重新粘贴 Cookie 通常无效**，请改用 OPENAPI 授权模式”，并明确给出「站点 → 个人中心 → OPENAPI」申请 `app_id/app_secret/user_token` 的下一步指引，杜绝误导用户反复重抓 Cookie；
  - 收紧 `APP_REQUIRED` 判定为精确信号匹配，避免“改用 OPENAPI 授权”等措辞被误判为 `APP_REQUIRED`；`cookie_session_revoked` 分支前置于 `app_required` 与 `auth_error`，确保归类唯一；
  - 看板新增红色 `VAlert`（`mdi-cookie-off`）告警卡片与「Cookie已作废」状态标签，设置页 Cookie 说明补充“服务端会在 401 时主动清空 hdh_session，强烈建议优先使用 OPENAPI”。

### v1.0.6 (2026-10-12)
- **修复 v1.0.5 仍误报“Cookie 已失效”的根因：漏识别 `SESSION_DEVICE_CHANGED`**:
  - 站点在登录设备 / UA / 环境指纹变化时返回 **HTTP 401 `{"code":"SESSION_DEVICE_CHANGED"}`**，v1.0.5 未识别该码，被兜底逻辑归入普通 401，从而误报“登录态失效，请更新 hdh_session”；
  - 新增 `session_device_changed` 分类与独立异常分支：**不清理 pending 任务**、不进入 `auth_error`，通知文案改为“登录设备/环境变化，需在浏览器重新登录或使用与插件相同的设备、UA 与网络出口完成验证，随后更新 hdh_session”，并明确标注“这不是 Cookie 过期”；
  - 兜底普通 401 的建议同步收紧：不再直接断言 Cookie 已失效，改为提示先确认是否更换过设备 / 网络出口，并可访问 `/api/security/session` 查看是否要求人机验证；
  - 看板新增“设备变化待登录”状态标签与 `VAlert` 告警卡片，设置页 Cookie 说明补充 UA 一致性提示。

### v1.0.5 (2026-10-12)
- **全面适配站点新版安全风控与拦截码**:
  - **网络出口变动识别 (`SESSION_VERIFY_REQUIRED`)**: 识别 HTTP 401 下由于代理出口变化触发的人机验证拦截，明确提示用户在浏览器中完成人机验证（`/verify-session`）或使代理出口保持一致，不再误报“Cookie 失效”且不取消定时任务；
  - **访问频控自动指数退避 (`SCRAPE_CHALLENGE_REQUIRED`)**: 识别高频请求人机挑战拦截，自动触发指数退避延后重试（60s / 180s / 300s），避免盲目重试加重风控；
  - **官方程序化授权凭证接入 (`APP_REQUIRED`)**: 适配站点针对程序自动化调用的 OPENAPI 强制要求，新增 `openapi_app_id`、`openapi_app_secret`、`openapi_user_token` 凭证配置，自动切换请求路径至 `/api/openapi/v1/*` 并附带授权鉴权头；
  - **收紧认证失效与重试判定**: 仅当无特殊安全拦截码的常规 401 时才判定登录态失效并清理待执行任务，各风控类型分流独立处理；
  - **看板与设置项完善**: 设置表单新增 OPENAPI 配置区块及模式引导说明，面板实时展示当前认证模式与安全状态。

### v1.0.4 (2026-10-11)
- **解决 HDHaven 站点 BROWSER_REQUIRED 403 假失效拦截**:
  - 补充完整浏览器客户端特征请求头：`sec-ch-ua`、`sec-ch-ua-mobile`、`sec-ch-ua-platform`、`sec-fetch-site: same-origin`、`sec-fetch-mode: cors`、`sec-fetch-dest: empty`；
  - 彻底规避站点自动化反爬策略触发的 `HTTP 403 (BROWSER_REQUIRED)` 拦截与误报“登录态失效”；
- **优化账号密码登录模式的人机防护识别**:
  - 识别站点 Cloudflare Turnstile 人机验证拦截（HTTP 400 `请先完成人机验证`），友好提示需改用 Cookie 模式并填入 `hdh_session`；
- **新增 `/api/account/overview` 聚合接口明细解析**:
  - 优先从站点 overview 聚合接口提取最新 notifications 与 ledger 变动记录，精准解析连续签到天数、获得经验（EXP）、获得积分及最新余额，杜绝 0 积分与虚假明细；

### v1.0.3
- **彻底根治 403 登录态失效误报已打卡得 0 分**:
  - 彻底切断认证失效时静默回退旧缓存的漏洞；401/403 登录态失效立即向上抛出并中断执行，严禁将历史残留的 `checkin_today: True` 误判为今日已在站点签到；
  - 识别认证失效后立即取消后续重试调度（`_clear_pending_task`），推送醒目的 `【栖影签到】登录态失效 🔴` 告警，精准提示更新 `hdh_session`；
  - 赌狗签到在通知缺失奖励数值时明确提示“以站点账单为准”，不再伪造虚假的 `+0 积分`；
  - 用户画像数据增加 `_updated_date` 时间戳校验，彻底杜绝历史残留数据污染当月每日走势图；
  - 完善网络与请求超时（`Read timed out`/`Timeout`）防护与友好诊断提示，Site 端异常时快速进入失败重试机制，绝不伪造已打卡。
- **全面适配 MoviePilot V3 (Vuetify 3) 深色/浅色模式**:
  - 移除所有硬编码白色/浅色背景（`#ffffff`、`#f8fafc` 等），全面解决 V3 深色模式下“白底白字、内容隐形看不清”的严重视觉问题；
  - 面板卡片重构为 Vuetify 3 原生 `VCard(variant="flat", color="surface", border=True)` 与数据统计块 `VCard(variant="tonal")`；
  - 登录态失效时，看板顶部呈现醒目的 `VAlert` 警报横条与 `"登录态失效"` 红色状态芯片；
  - SVG 当月积分走势图的网格线、基线及刻度文本采用 `stroke/fill: currentColor` 搭配透明度，深浅模式下文字线条自适应且清晰锐利。

### v1.0.2
- **消除并发重复执行与重复记分**: 引入 `_signin_lock` 线程非阻塞锁，防止 MoviePilot 配置保存或勾选即时执行时并发运行导致同秒多条重复记录与积分翻倍累加；
- **历史明细去重与清洗机制**: 新增 `_clean_history`，自动合并秒级重复记录与同日已签到重复项，看板加载时自动修复存量历史数据；
- **补全已签到积分奖励展示**: 修复今日已签到分支（`checkin_today` 与 409 状态码）缺失 `points_awarded` 字段的问题，历史明细表格“奖励”列正常显示 `+5`，通知中明确显示 `🎁 今日奖励：+5 积分`；
- **月度走势图波峰与视觉呈现**: 修复整月积分全为 0 贴地水平线的问题，单日严格只计一次签到收益，SVG 折线图新增半透明渐变面积填充、签到得分高亮绿点与直接数值浮标（如 `+5`），数据起伏一目了然；
- **调度器生命周期加固**: 优化即时执行一次 (`onlyonce`) 逻辑，执行前安全释放旧调度器实例，修正时区对象引用。

### v1.0.1
- **优化称谓与等级提取**: 防御字典结构直接输出，自动从复杂对象/字符串中提纯等级中文名称（如“初来乍到”）。
- **用户展示去重**: 当 UID 与用户名为同一标识时自动合并显示，消除 `user (UID: user)` 冗余。
- **签到结算明细解析**: 接入站点通知消息接口，自动提取连续签到天数、获得经验值（EXP）、结算公式与当前余额；未获取到文字通知时根据加成规则智能合成公式。
- **连续签到天数修正**: 今日已签到状态下连续天数保底为 1 天，修复显示 0 天的问题。
- **调度器时区修复**: 修正后台延迟调度中时区对象引用的潜在异常。