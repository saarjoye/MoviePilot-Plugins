# TingBookSync

MoviePilot 听书同步插件 dry-run 骨架。

当前版本只做：

- 读取 `watch_dir`。
- 扫描 `staging/*/.tingbook.ready`。
- 校验 `metadata.json` 和分集文件。
- 执行上传 dry-run 并写回 `uploaded`。
- 写回 `.tingbook.sync.json`。
- 可选生成 dry-run STRM 文件。

当前版本不做：

- 115 上传。
- 读取 Cookie、Token 或二维码登录状态。
