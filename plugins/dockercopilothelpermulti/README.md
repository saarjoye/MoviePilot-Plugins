# DC助手多源版

作者：wYw

## 功能

- 支持配置多个 DockerCopilot 源。
- 支持跨源容器更新通知。
- 支持按源执行自动更新、进度汇报、镜像清理。
- 支持对所有启用源执行自动备份并汇总通知。
- 容器选择值使用 `source_id::container_name`，避免多个 DC 中同名容器误更新。

## 配置示例

在插件配置页的 `DockerCopilot 源 JSON` 中填写：

```json
[
  {
    "id": "pve_lxc_01",
    "name": "PVE-LXC-01",
    "host": "http://dc-lxc-01:12712",
    "secretKey": "请替换为真实 secretKey",
    "enabled": true
  },
  {
    "id": "pve_lxc_02",
    "name": "PVE-LXC-02",
    "host": "http://dc-lxc-02:12712",
    "secretKey": "请替换为真实 secretKey",
    "enabled": true
  }
]
```

## 安全提醒

- `secretKey`、真实 DC 地址、LXC 主机信息属于敏感配置。
- 不要把真实配置截图或日志发到公开渠道。
- 插件通知与日志不会输出 `secretKey` 明文。
