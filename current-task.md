# 当前任务：rag 六件套入库

2026-10-13（Asia/Shanghai）。知识库基线 main `07ba709fd3d2d549ee5a5670243f1b1db9169299`，初始干净。源项目 rag `37ac973`，backend `3c4cd2a`，frontend `56fe651`。

已新增 rag-system-architecture、rag-core-call-chains、rag-engineering-findings、rag-optimization-roadmap、rag-engineering-handbook、rag-interview-questions，分类 backend-eng，order 5–10。默认授权包含知识库提交推送，不包含源项目提交推送。

构建通过：10 条（含 2 外链）、183 锚点、34 表格、83 代码块；新增正文保留原 Markdown，六篇导航映射为真实文章路由。Mermaid 保留源码。既有 verify.js 检查 147 passed / 0 failed；浏览器逐篇核实标题、目录、正文和 36 个导航链接目标，实际切换六篇；390px 窄屏页面无水平溢出，表格容器 overflow-x:auto。最终构建后重新检查页面。Mermaid 仅源码展示。

首次 verify.js 把 Marked 文档域名中的 .js 误识别为外部脚本 URL；已将两处引用改为已核实的 Marked 官方 GitHub README，保留原有断言，最终检查全通过。

发布单元仅为上述六篇、生成首页、README 和本仓库三份交接文档；目标 origin/main，无源项目提交或推送。推送与部署确认结果保存在本任务 work/rag-import-manifest.json，并在交付时给出实际提交 SHA；本文件不预报尚未发生的上线。
