# TingBookSync

MoviePilot 听书同步插件 dry-run 骨架。

当前版本只做：

- 读取 `watch_dir`。
- 在插件详情页使用“资源存储 + 资源目录”方式选择下载监听目录、STRM 生成目录和 115 目标目录；115 目标目录固定使用 MP 的 `u115` 存储，目录字段只保存选择结果。
- 扫描下载监听目录下的 `.tingbook.ready`，兼容 `staging` 和分类子目录。
- 校验 `metadata.json` 和分集文件。
- 执行上传 dry-run 并写回 `uploaded`。
- 写回 `.tingbook.sync.json`。
- 可选生成 dry-run STRM 文件，并按下载监听目录下的分类子目录自动新建 STRM 分类文件夹。

当前版本不做：

- 115 上传。
- 读取 Cookie、Token 或二维码登录状态。
