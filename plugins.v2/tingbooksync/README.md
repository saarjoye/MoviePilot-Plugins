# TingBookSync

MoviePilot 听书同步插件 dry-run 骨架。

当前版本只做：

- 读取 `watch_dir`。
- 在插件详情页使用“资源存储 + 资源目录”方式选择下载监听目录、STRM 生成目录和 115 目标目录；115 目标目录固定使用 MP 的 `u115` 存储，目录字段只保存选择结果。
- 可自动接管下载监听目录下的散音频文件或普通音频文件夹，整理为 `staging/书名/`。
- 可选联网刮削补全书籍信息：当前使用清洗后的书名关键词查询 Google Books / Open Library，默认关闭。
- 扫描下载监听目录下的 `.tingbook.ready`，兼容 `staging` 和分类子目录。
- 校验 `metadata.json` 和分集文件。
- `dry_run=true` 时执行上传 dry-run 并写回 `uploaded`。
- `dry_run=false` 时调用 MoviePilot `StorageChain().upload_file()` 真实上传到 `u115`，上传成功拿到 `pickcode` 后再生成 STRM。
- STRM 写入本插件 `/api/v1/plugin/TingBookSync/play/{token}` 播放地址，播放时换取 115 临时下载 URL 并返回 302。
- 写回 `.tingbook.sync.json`。
- 可选生成 STRM 文件，并按下载监听目录下的分类子目录自动新建 STRM 分类文件夹。

当前版本不做：

- 读取 Cookie、Token 或二维码登录状态。
- 向外部元数据站点发送完整本地路径、115 目录或凭证。
- 把 115 Cookie、Token 或临时下载直链写入 STRM。
