# Panlink115

`Panlink115` 是一个 `MoviePilot v2` 插件，用来在 MP 内手动搜索盘链影视资源，并优先展示 `115` 网盘链接。

## 当前能力

- 手动搜索盘链电影或电视剧
- 加载指定条目的网盘资源详情
- 优先展示 `115` 资源，也可切换为展示全部网盘
- 提供“加入 115”占位接口，先记录待处理队列
- 插件详情页已切换为 `Vue + Module Federation` 远程组件

## 当前限制

- “加入 115”目前只会加入待处理队列，不会真实转存到你的 `115`
- 真实 `115` 转存逻辑需要后续单独补齐

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
