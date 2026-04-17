# Panlink115

`Panlink115` 是一个 `MoviePilot v2` 插件，用于在 MP 内手动搜索盘链影视资源，并优先展示 `115` 网盘链接。

## 当前能力

- 手动搜索盘链电影或电视剧
- 自动加载首条结果的详情信息
- 按网盘类型展示资源，支持查看 `115` 分享链接
- 选择 MoviePilot 分类后，直连提交到 `115`
- 目标目录复用 MoviePilot 的 `u115` 存储路径

## 直连 115 说明

- 插件已移除 `CD2` 提交链路
- 分享转存改用 `115` 网页接口 `share/receive`
- 目录解析和目标目录创建复用 MoviePilot 的 `u115` 存储
- 需要在插件配置中提供已登录 `115` 网页的完整 `Cookie`

## 目录结构

```text
plugins.v2/
  panlink115/
    __init__.py
    client.py
    u115_direct.py
    requirements.txt
    dist/
      assets/
    frontend/
```

## 前端构建

前端源码位于 `plugins.v2/panlink115/frontend`，构建命令：

```bash
npm install
npm run build
```

构建产物会输出到 `plugins.v2/panlink115/dist/assets`，供 MoviePilot 按 `render_mode = "vue"` 加载。
