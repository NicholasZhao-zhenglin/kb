# 知识库维护约定

先读取 `architecture.md`、`current-task.md` 与 README；结构或数据契约变化时增量维护。交付前更新真实验证和发布状态，不把推送当作上线。

项目是 Python 标准库构建器 + 单文件 HTML/CSS/JS。文章放 `articles/<id>/meta.json` 与 `source.html`，Markdown 导入保留原始 `source.md`。分类来自 categories.json，order 全库唯一；源码正文需有 main。index.html 由 build.py 生成，不能手改作为内容来源。

保留 build.py 的元数据、目录、锚点、零外部资源等断言；导入后运行构建及相关页面检查。仅提交本任务文章和关联产物/交接文档，保留既有文章。不要把密钥、私有环境、业务样本或源码附件导入公开知识库。git 不强推，不擅自改权限和部署配置。
