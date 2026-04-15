# Panlink115

`Panlink115` 是一个 `MoviePilot v2` 插件，用来在 MP 内手动搜索盘链影视资源，并优先展示 `115` 网盘链接。

## 当前能力

- 手动搜索盘链电影或电视剧
- 搜索后自动加载首条结果的盘链详情页信息
- 以详情页布局展示海报、别名、导演、主演、语言、更新时间、剧情简介
- 分网盘类型展示资源，并通过弹层查看 `115` 链接列表
- 下载任务直接选择当前 `MoviePilot` 已配置的分类，而不是插件自定义媒体类型
- 提供“下载到 115”占位接口，先记录待处理队列
- 插件详情页已切换为 `Vue + Module Federation` 远程组件

## 当前限制

- “下载”目前只会创建待处理任务，不会真实转存到你的 `115`
- 尚未接入真实的 `115` 转存与 `MoviePilot` 手动整理接口

## 目录结构

```text
plugins.v2/
  panlink115/
    __init__.py
    client.py
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
