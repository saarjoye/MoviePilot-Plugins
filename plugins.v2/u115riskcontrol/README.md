# u115风控参数

这是一个 MoviePilot 插件，用于在运行时为 `u115` 存储注入更保守的限流参数，避免每次升级 MP2 容器后又要手工修改 `u115.py`。

## 当前版本能力

- 持久化普通接口 QPS
- 持久化下载接口 QPS
- 持久化 `limit_sleep_seconds`
- 支持小时软阈值
- 支持达到软阈值后主动冷却
- 支持风控冷却结束后自动重试 MP 媒体整理失败历史
- 插件启用后自动为新建的 `U115Pan` 实例注入参数
- 尝试为当前已存在的 `U115Pan` 实例热更新参数

## 推荐默认值

- `api_qps = 1`
- `download_qps = 1`
- `limit_sleep_seconds = 3600`
- `hourly_soft_limit = 60`
- `hourly_soft_cooldown = 1200`
- `retry_failed_after_cooldown = true`
- `retry_failed_delay_seconds = 60`
- `retry_failed_max_count = 5`

## 参数说明

- `api_qps`：普通接口每秒请求数，建议保持 `1`
- `download_qps`：下载接口每秒请求数，默认 `1`
- `limit_sleep_seconds`：115 明确返回访问上限后的本地冷却秒数
- `hourly_soft_limit`：插件侧自定义的 1 小时请求软阈值，设为 `0` 表示关闭
- `hourly_soft_cooldown`：达到软阈值后的主动冷却秒数，设为 `0` 表示只记录不暂停
- `retry_failed_after_cooldown`：风控冷却结束后是否自动查找 MP 媒体整理失败历史并重试
- `retry_failed_delay_seconds`：冷却结束后额外等待秒数，避免刚恢复就立即重新请求
- `retry_failed_max_count`：单次最多重试失败整理条数，设为 `0` 表示不限制

## 发布说明

如果使用 `D:\开发\github发布\mp_plugin_market_publisher.py` 发布，建议执行：

```powershell
python D:\开发\github发布\mp_plugin_market_publisher.py publish `
  --plugin-source D:\开发\MP插件\u115风控参数\u115riskcontrol `
  --repo-url https://github.com/<你的用户名>/<你的插件仓库> `
  --package-version base `
  --labels 工具,115,风控 `
  --icon-source D:\开发\MP插件\u115风控参数\u115riskcontrol\U115RiskControl.jpg `
  --history-note "首个版本：提供 u115 风控参数持久化配置"
```
