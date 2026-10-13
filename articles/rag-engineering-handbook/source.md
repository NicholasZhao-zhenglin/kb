# rag · 工程知识学习手册

审查日期：2026-10-13（Asia/Shanghai）。项目：`NicholasZhao-zhenglin/rag`；总仓库 `37ac973e4580442542853bb241e3286caa90dfc3`，后端 `3c4cd2ac1f11c862e31f423054cbef7b3960c7b8`，前端 `56fe6519426174e1b6d8f421bdbeb92e742cc4a4`。下文源码路径均相对于 rag 根目录。审查和隔离验证已执行；业务修复与路线图均未实施。

阅读顺序：[01 系统架构分析](01-system-architecture.md) → [02 核心代码调用链](02-core-call-chains.md) → [03 工程问题清单](03-engineering-findings.md) → [04 优化路线图](04-optimization-roadmap.md) → [05 工程知识学习手册](05-engineering-handbook.md) → [06 面试问答手册](06-interview-questions.md)。

## 受众与学习路线

适合了解 Python、TypeScript 和基本 HTTP、准备接手此 RAG 原型的工程师。建议先读 01 看边界，再沿 02 的一次上传/聊天走源码，遇到问题到 03 查证据，最后比较 04 的方案。本手册的练习全部是**建议练习，尚未执行**；本轮已执行的探针有单独编号。

## 1. 版本组合也是系统的一部分

总仓库 main 并不代表两个子模块各自最新 main。`.gitmodules` 给远程身份，gitlink 给提交身份；要重现一个问题必须同时记录三个 SHA。本项目的后端缺登录而前端默认要求登录，说明各自存在文件不能保证组合契约成立。

不变量是“被部署的前端每个请求，都能在其配套后端找到约定行为”。单看前端 TypeScript 编译不会验证 HTTP 路由。短期用 API 清单对照 OpenAPI，长期可由 schema 生成客户端，但生成类型也不代替业务授权与状态测试。

建议练习：从 `frontend/src/api` 提取 method/path，与隔离后端路由表比较；预期观察四个缺失接口。修复后同一检查应为空，并保留未知路径 404 的反例。

## 2. 文档身份、会话身份与检索空间

`create_session` 返回随机字符串，而上传默认用 default；两者只是名字，代码没有建立归属关系。F02 展示了“每段函数各自运行成功，整个操作仍然失败”。

另一个身份问题在 `file_parse.process_item`：内容哈希能回答两段内容是否一样，不能回答它们来自哪份文件。F08 中两份文档的同段内容会落到相同 ES _id。可用 doc/version/chunk 序号表达归属；如果想省空间，需要一个内容实体对应多条来源关系，而非覆盖文档元数据。

建议练习：制作两份各含共享段落与独特段落的合成 TXT，设计预期引用集合；验证去重与不去重两种模型对删除、替换、引用的影响。只用 fake 存储或临时索引，不碰现有资料。

## 3. async 是协作等待，不是自动搬走工作

在 `chat_rt.upload_files` 中 await file.read 结束后，普通函数 execute_insert_process 仍在当前调用上下文执行；`chat_on_docs` 的 retrieve_content 同理。async 声明不会让同步 SDK、OCR 自动变成并行任务。官方说明也区分框架调度的普通路径函数和你自己直接调用的工具函数：[FastAPI 并发说明](https://fastapi.tiangolo.com/async/)。

StreamingResponse 又是另一层：当前验证环境 Starlette 用线程池迭代同步 generator。因此不能只看一个 async 关键字就断言整条流都在事件循环里。先标清边界，再决定异步 SDK、线程池或独立 worker；线程池能缓解阻塞，不会免费提供持久任务、无限并发或崩溃恢复。

建议练习：用 Event 控制一个 fake 同步 gateway，在单 worker 测试里同时发轻量请求，记录它何时开始；把外部调用迁入有界执行器后比较。不要使用真实慢接口，不用任意长 sleep 推断容量。

## 4. 成功必须跨越所有需要的提交边界

文件保存、向量计算、bulk 接收、每项写入成功、搜索可见是五个不同事实。本项目 F05 在“bulk 返回错误列表”与“HTTP 报成功”之间丢了信息。Elasticsearch 官方 bulk 文档说明响应要检查 errors 和 items；这支持检查逐项结果，并不意味着数据库与文件系统自动有分布式事务。

最小改造是明确 InsertResult 与 ready 状态；更严格的发布方案可以用版本指针，让读者只看到完整版本。代价是额外状态、存量清理和回滚流程。没有任务状态时，先加一个真实可信的状态机，比先接复杂消息队列更有价值。

建议练习：fake bulk 对三块中的第二块失败；画出原文件、三块、UI 状态的实际值。设计重试规则，要求重复调用不把失败结果发布为 ready，也不丢掉先前已可读版本。

## 5. 适配器的输入与输出都必须保留语义

F07 不是“openpyxl 不能解析 Excel”，而是 `naive.chunk` 接收路径却把 None 传给 ExcelParser。真实库收到空 BytesIO 后报 BadZipFile 完全合理。JSON 同样缺少 binary。修复时必须沿入口跟到底，不能只给下游加 try/except 并返回空列表。

输出侧 Q01 是身份丢失：重排服务若按分数换序返回节点，包装只取分数，调用者又按旧顺序应用，就把 B 的分数给了 A。即使数组长度一致也不代表对应关系正确。本轮只用合成换序 fake 证明这一前提下的风险，未验证自定义包真实返回约定。

建议练习：让适配器接收带 ID 的 A、B、C 并返回 C、A、B；断言 ID 与 score 始终成对传递。为格式入口规定明确的 Path/bytes 类型，拒绝隐式 None。

## 6. 流式接口是状态协议

普通 JSON 请求通常一次成功或失败；SSE 可以先成功发引用、再发半段答案、最后失败。HTTP 200 不代表生成成功，后端 event:error 也不会自动触发 Axios 的非 2xx 错误插件。F10 的 parseData 只看到 content，就把错误当答案。

不变量是消息有明确的开始、增量、失败或完成状态，且资源在终态释放。推荐问题是另一次模型调用，应有独立降级策略。客户端取消、服务端停止读取、供应商停止生成是不同动作，不能用一个 AbortController 宣称计费一定立刻终止。

建议练习：输入 documents→content→error、content→end、自然 EOF 三种假流，分别断言正文、错误、loading 和资源关闭次数。测试流分包时不要假设一次 read 就是一条 SSE 事件。

## 7. Markdown 格式化和安全清洗不同

`components/markdown` 把模型/文档内容送到 Marked，再直接注入 DOM。Markdown parser 负责语法转换，不是 HTML 安全策略。P10 用无破坏的合成属性证明当前版本保留 HTML；Marked 官方也明确要求独立清洗：[Marked 文档](https://github.com/markedjs/marked)。

方案取舍是保留富文本功能与缩小 HTML 能力：只允许段落、表格和代码时可以严格白名单；如果允许外链/图片，需要协议、属性和资源来源规则。纯字符串替换几类危险词无法替代结构化清洗。

建议练习：建立安全 HTML fixture 集，用 DOM 断言验证危险属性被移除，同时表格与引用可用；仅在本地空白页面，不读取或发送浏览器用户信息。

## 8. 可复现验证的四层证据

本轮 60 个 Python 文件语法通过，只说明可解析；AST 探针证明选定函数在 fake 边界下的行为；前端 legacy peer 模式下 build 成功，只说明特定环境能产物；真实 ES/模型/部署尚未验证。这四层不能互相替代。

默认 npm ci 失败与 legacy 模式成功也不是矛盾：前者检查 peer 契约，后者主动放宽该检查。lint 26 errors/10 warnings 是现有门禁状态，不能用 build 成功掩盖。后端无完整锁文件意味着本轮小型 probe 环境也不能冒充生产环境。

建议练习：为一条结论写四行证据台账：源码位置、明确前提、实际命令/观察、未覆盖边界。然后把建议测试和真实执行分开。学习完成的标准是能够解释失败原因和验证限度，而不是背出组件名字。
