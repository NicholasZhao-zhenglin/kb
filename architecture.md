# 知识库当前架构

构建入口 `build.py` 扫描 categories.json 与 articles 的元数据/HTML，调整标题层级、前缀锚点、包装表格，生成内嵌 kb-data JSON 的 index.html。浏览器侧 hash 路由 `#/a/<id>` / `#/c/<cat>`，搜索和目录来自完整正文，星标/最近阅读在 localStorage。没有服务器数据库；部署依赖已有 GitHub Pages 设置，本轮未改。

目前普通分类 data-eng/backend-eng，bookmarks 为导航类外链。2026-10-13 新增 rag 工程审查六篇，仍使用 backend-eng 与稳定 rag 前缀，不改变构建器。六篇 source.md 保留原字节，跨篇链接转换为首页文章路由；Mermaid 仍为代码展示，没有引入 CDN 或渲染器。

`verify.js` 做 jsdom DOM/交互验证；`cdp-verify.js` 是本机 Chrome 渲染测试，可产生截图。具体本轮测试与发布状态见 current-task.md。
