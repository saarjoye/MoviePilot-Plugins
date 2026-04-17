# Agent Notes

## 2026-04-17

### User Request
- 询问：没有 Netflix 账号时，如何监控 Netflix 新上剧集列表。

### Verified Facts
- `Verified fact | 已验证事实`：`Netflix Tudum` 是 Netflix 官方伴随站点，可直接访问；登录 Netflix 账号只会带来个性化体验，不是访问 Tudum 的前提。
  - Source 1: https://help.netflix.com/en/node/123481
  - Source 2: https://www.netflix.com/tudum
  - Verified On: 2026-04-17
- `Verified fact | 已验证事实`：Tudum 存在公开的“`New on Netflix`”栏目，以及按周、按月的新内容页面。
  - Source 1: https://www.netflix.com/tudum/articles/new-on-netflix
  - Source 2: https://www.netflix.com/tudum/articles/new-on-netflix-this-week-november-17-2025
  - Verified On: 2026-04-17
- `Verified fact | 已验证事实`：`JustWatch` 提供公开的 “What’s new on Netflix” 页面，并支持只看 TV shows。
  - Source 1: https://www.justwatch.com/us/provider/netflix/new
  - Source 2: https://www.justwatch.com/us/provider/netflix/new/tv-shows
  - Verified On: 2026-04-17

### Constraints / Boundaries
- `Inference | 基于证据的推断`：没有 Netflix 账号时，最稳妥的公开监控入口是官方 `Tudum` + 第三方聚合站 `JustWatch` 组合。
- `Pending verification | 待验证事实`：是否存在稳定、公开、面向普通用户的 Netflix “新上架目录 API” 未在本轮证据中闭环，不应当作为确定结论对外陈述。
- `Known limitation | 已知限制`：Netflix 上架目录具有地区差异，监控结果需要绑定具体国家/地区，例如 `US`、`UK`。

## 2026-04-17 Update Mark

### New User Request
- 询问：希望把 Netflix 新上/待上监控并入当前插件，尽量保持与现有插件一致的接入方案。

### Local Codebase Findings
- `Verified fact | 已验证事实`：当前插件核心入口是根目录 `__init__.py` 中的 `UpcomingReleases` 类，现有平台抓取统一收口到 `_get_items()`，按开关串行汇总 `_fetch_iqiyi/_fetch_tencent/_fetch_youku/_fetch_mgtv` 的结果，再经 `_finalize_items()` 标准化。
- `Verified fact | 已验证事实`：插件已有统一 item 结构，由 `_build_item()` 产出，关键字段包括 `platform/platform_label/type_key/type_label/title/year/release_date/release_text/poster/detail_link/story/reserve_count/media_id`。
- `Verified fact | 已验证事实`：插件现有模式已包含配置开关、缓存 TTL、定时任务、推荐源、发现源、页面筛选、自动订阅和图片域白名单。
- `Inference | 基于证据的推断`：如果要“和插件方案一样”，最稳妥的方向不是单独新建另一套插件，而是在现有统一抓取管线中新增 `netflix` 平台适配层。

### Integration Constraints
- `Verified fact | 已验证事实`：`About Netflix / New on Netflix` 公开展示当月新上内容，页面结构比 Tudum 更轻，更适合作为“官方月度片单入口”。
  - Source 1: https://about.netflix.com/en/new-to-watch
  - Source 2: https://help.netflix.com/en/node/14422
  - Verified On: 2026-04-17
- `Verified fact | 已验证事实`：`JustWatch` 的 Netflix 新增剧集页说明其列表按日期组织并 `updated daily`，更适合作为“最近新增”补充源。
  - Source 1: https://www.justwatch.com/us/provider/netflix/new/tv-shows
  - Source 2: https://www.justwatch.com/us/provider/netflix/new
  - Verified On: 2026-04-17
- `Known limitation | 已知限制`：当前插件名称与语义偏向“待播/即将上映”，而 `JustWatch` 数据偏“已经新上”，若直接混入会稀释当前插件语义，需要在页面和推送上单独标识。

## 2026-04-17 Update Mark 2

### New User Request
- 询问：先阅读 `jxxghp/MoviePilot` 的插件规范，再基于规范评估当前插件实现方向。

### Verified Facts From Official Repos
- `Verified fact | 已验证事实`：`MoviePilot` 主仓库 README 明确要求插件代码放在 `app/plugins` 目录开发，并指向官方插件库与前端仓库作为配套参考。
  - Source 1: https://github.com/jxxghp/MoviePilot
  - Source 2: https://github.com/jxxghp/MoviePilot-Plugins
  - Verified On: 2026-04-17
- `Verified fact | 已验证事实`：官方插件库要求插件仓库目录与官方仓库一致，`plugins/<pluginclassname>/__init__.py` 为主入口，`package.json` 用于插件市场展示，版本号需与代码中的 `plugin_version` 保持一致。
  - Source 1: https://github.com/jxxghp/MoviePilot-Plugins
  - Verified On: 2026-04-17
- `Verified fact | 已验证事实`：插件支持三类展示页面：`插件配置`、`详情展示`、`仪表板Widget`；界面既可以走 JSON/Vuetify 配置化渲染，也可以走 Vue 模块联邦远程组件。
  - Source 1: https://github.com/jxxghp/MoviePilot-Plugins
  - Source 2: https://github.com/jxxghp/MoviePilot-Frontend
  - Verified On: 2026-04-17
- `Verified fact | 已验证事实`：官方插件规范支持通过 `get_api()` 对外暴露 API，通过 `get_service()` 注册公共定时服务，通过 `ChainEventType.DiscoverSource` / `RecommendSource` 扩展探索与推荐数据源。
  - Source 1: https://github.com/jxxghp/MoviePilot-Plugins
  - Verified On: 2026-04-17

### Inference
- `Inference | 基于证据的推断`：当前插件已经实现了 `get_api()`、`get_service()`、`DiscoverSource`、`RecommendSource` 和远程组件模式，整体技术路线与官方插件规范一致，适合继续在同一插件内扩展 Netflix 数据源，而不是另起一套不兼容实现。

## 2026-04-17 Update Mark 3

### Formal Integration Proposal
- `Recommendation | 建议`：采用“单插件内新增 `netflix` 平台适配层”的方案，不新建独立插件；第一阶段只做后端接入与现有配置/筛选复用，尽量不改远程 UI 产物。
- `Assumptions | 适用前提`：监控目标接受以 `US` 站点为首个地区；首期允许 Netflix 数据同时包含“即将上线”和“最近新上”两类内容，但要在文案和推送中明确标记来源与状态。
- `Known limit | 已知限制`：当前仓库仅包含打包后的 `ui` 产物，没有前端源码；因此“最稳妥路径”应优先走后端兼容式扩展，避免首期强依赖重新构建前端。

### Planned Change Points
- `__init__.py / 常量区`：新增 `PLATFORM_LABELS`、别名映射、默认配置开关与地区配置项，例如 `enable_netflix`、`netflix_region`、`netflix_source_mode`。
- `__init__.py / _get_items()`：在现有抓取汇总链路中新增 `self._safe_fetch("Netflix", self._fetch_netflix)`。
- `__init__.py / 抓取函数`：新增 `_fetch_netflix()`，内部拆分为 `_fetch_netflix_about()` 与可选的 `_fetch_netflix_justwatch()`。
- `__init__.py / _build_item()` 调用侧`：为 Netflix item 补充 `release_status/source_tag/region_codes` 等扩展字段，保持旧字段兼容。
- `__init__.py / config_state()`、`_build_browser_state()`、`_serialize_browser_item()`：把 Netflix 纳入现有平台选项、统计和页面序列化输出。
- `__init__.py / sync_and_push()`：推送文案中增加平台与状态标记，避免把“新上”误写成“待播”。

## 2026-04-17 Update Mark 4

### User Clarification
- 关键约束：现有插件必须继续支持“明日 / 7天 / 30天 / 敬请期待”等待播时间筛选，自动订阅规则也必须和现有插件语义保持一致。
- 禁止结果：定时推送不能把“新上”当成“待播”。

### Revised Recommendation
- `Recommendation | 建议`：Netflix 接入当前插件时，只纳入“未来待上 / 上线时间未到”的条目进入主 item 池；不要把“已经新上”的 Netflix 条目混入当前插件主列表、时间筛选和自动订阅规则。
- `Inference | 基于证据的推断`：为了保持现有 `tomorrow / 7days / pending` 语义稳定，`JustWatch new` 这类“已新增”数据不应进入当前插件主流程；若后续确实需要监控“新上”，更适合作为单独视图、单独推送类别或独立插件处理。
- `Implementation note | 实施说明`：Netflix 首期数据源应优先挑选可提取未来上线日期的官方月度/周度片单页面，并在抓取阶段直接过滤掉已上线条目。

## 2026-04-17 Update Mark 5

### Implemented Changes
- `Implemented | 已实施`：在 `__init__.py` 中新增 `netflix` 平台常量、别名、默认开关 `enable_netflix`，并将插件描述与版本更新为包含 Netflix 的版本。
- `Implemented | 已实施`：新增 `_fetch_netflix()`，使用官方公开接口 `https://about.netflix.com/api/data/releases?countryCode=us&language=en&page=N` 分页抓取，并在抓取阶段过滤掉当前日期之前的条目。
- `Implemented | 已实施`：Netflix 条目仍复用现有 item 结构，只额外写入 `region_codes=["US"]` 与 `genre_names=[...]`，以便继续复用现有地区/题材筛选和自动订阅规则。
- `Implemented | 已实施`：在 `_match_rule_regions()`、`_match_rule_genres()`、`_get_item_region_text()`、`_get_item_genre_text()` 中优先读取 item 直接携带的地区/题材字段，避免 Netflix 条目过度依赖识别链路。
- `Implemented | 已实施`：在配置页打包文件 `ui/__federation_expose_Config-B-bXzNff.js` 中补充 `Netflix` 平台选项，并新增 `enable_netflix` 开关控件，使平台筛选与订阅规则选项保持一致。

### Verification
- `Verified | 已验证`：`python -m py_compile __init__.py` 通过。
- `Verified | 已验证`：`node --check ui/__federation_expose_Config-B-bXzNff.js` 通过。

### Known Limits
- `Known limit | 已知限制`：当前实现固定抓取 `US + en` 的 Netflix 官方公开片单；如果后续要支持更多地区，需要继续参数化 `countryCode/language`。
- `Known limit | 已知限制`：Netflix 官方接口返回的 collection/genre 编码语义不完全等同于 MoviePilot 现有分类，因此当前 `type_key/genre_names` 采用“官方 genre 映射 + 现有插件语义兼容”的折中映射。
