# 知识库维护约定

先读取 `architecture.md`、`current-task.md` 与 README；结构或数据契约变化时增量维护。交付前更新真实验证和发布状态，不把推送当作上线。

项目是 Python 标准库构建器 + 单文件 HTML/CSS/JS。文章放 `articles/<id>/meta.json` 与 `source.html`，Markdown 导入保留原始 `source.md`。分类来自 categories.json，order 全库唯一；源码正文需有 main。index.html 由 build.py 生成，不能手改作为内容来源。

保留 build.py 的元数据、目录、锚点、零外部资源等断言；导入后运行构建及相关页面检查。内容导入时仅提交本任务文章和关联产物/交接文档；功能开发只提交获授权的功能与测试。保留既有文章。不要把密钥、私有环境、业务样本或源码附件导入公开知识库。git 不强推，不擅自改权限和部署配置。

浏览器编辑模块在 `note-editor.js` / `note-editor.css`，构建时内联，发布必须包含重建的 index.html。修改编辑/存储契约时运行 verify.js 和 verify-editor.js。`kb.notes` 是 version=2 的单键内容快照；兼容旧 kb.extra，不能丢弃既有本地内容。正文持久化前校验、过滤活跃 HTML；成功写入后才能显示保存成功。无服务端同步，UI 和文档必须明确本机保存范围。
