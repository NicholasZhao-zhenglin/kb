# 知识库当前架构

构建入口 `build.py` 扫描 categories.json 与 articles 的元数据/HTML，调整标题层级、前缀锚点、包装表格，生成内嵌 kb-data JSON 的 index.html。浏览器侧 hash 路由 `#/a/<id>` / `#/c/<cat>`，搜索和目录来自完整正文，星标/最近阅读在 localStorage。没有服务器数据库；部署依赖已有 GitHub Pages 设置，本轮未改。

目前普通分类 data-eng/backend-eng，bookmarks 为导航类外链。2026-10-13 新增 rag 工程审查六篇，仍使用 backend-eng 与稳定 rag 前缀，不改变构建器。六篇 source.md 保留原字节，跨篇链接转换为首页文章路由；Mermaid 仍为代码展示，没有引入 CDN 或渲染器。

`verify.js` 做 jsdom DOM/交互验证；`cdp-verify.js` 是本机 Chrome 渲染测试，可产生截图。具体本轮测试与发布状态见 current-task.md。

## 浏览器笔记编辑（2026-10-13 已实施）

`build.py` 将 `note-editor.js` / `.css` 内联到 index.html，仍是无外部依赖单文件。文章页打开原生 dialog，通过 contenteditable 编辑正文、输入框编辑元数据。保存经过字段校验和 HTML 白名单过滤，重新生成目录/字数；基于文章 ID 的本地副本覆盖内置/导入条目，并重建搜索与视图。仓库 articles 源文件没有被浏览器写入。

`localStorage['kb.notes']` 保存 `{version:2, extra:[], edits:{id:完整笔记}}`，一次 setItem 完成内容写入；旧 `kb.extra` 首次读取兼容，成功写入后以新键为准。星标和历史沿用原键。保存先比较打开时快照，发现其他标签页已写入则拒绝覆盖；storage 事件更新未编辑页面。配额/权限失败留在编辑器；关闭/刷新未保存内容有提示。恢复原文移除 override，重新展示当前发布版本或最初导入版本。

备份格式保持 type=kb-extra，version 升为 2，包含 arts/edits/favs/hist。导入兼容旧数组和 v1，校验所有内容后单次提交内容快照；覆盖修改需确认。笔记正文过滤脚本、嵌入对象、事件属性和不安全 URL，粘贴仅纯文本、阻止拖入活跃 HTML。外链收藏不提供正文编辑。

尚未实施：登录、服务端持久化、跨设备自动同步、浏览器回写 GitHub。备份是本地修改迁移通道；清理网站数据会丢失未导出的本地副本。
