# rag · 工程问题清单

审查日期：2026-10-13（Asia/Shanghai）。项目：`NicholasZhao-zhenglin/rag`；总仓库 `37ac973e4580442542853bb241e3286caa90dfc3`，后端 `3c4cd2ac1f11c862e31f423054cbef7b3960c7b8`，前端 `56fe6519426174e1b6d8f421bdbeb92e742cc4a4`。下文源码路径均相对于 rag 根目录。审查和隔离验证已执行；业务修复与路线图均未实施。

阅读顺序：[01 系统架构分析](01-system-architecture.md) → [02 核心代码调用链](02-core-call-chains.md) → [03 工程问题清单](03-engineering-findings.md) → [04 优化路线图](04-optimization-roadmap.md) → [05 工程知识学习手册](05-engineering-handbook.md) → [06 面试问答手册](06-interview-questions.md)。

## 判级与证据规则

P0 指有证据支持的灾难事故；本轮未确认 P0。P1 是关键功能失败、数据/资源边界风险；P2 是需排期的一致性、交付或维护缺陷；P3 是低风险演进。优先级依据触发场景，不等于证据强度。

“隔离复现”使用真实函数 AST 与合成数据，绕过模块级外部初始化；不代表应用可完整启动。“静态确认”只覆盖看到的实现；“待确认”不混入已确认问题。所有 F 项当前均**未修复**。

| 编号 | 优先级 | 问题 | 证据 |
| --- | --- | --- | --- |
| F01 | P1 | 登录与历史接口缺失，页面准入链不闭合 | P01，静态前端调用 |
| F02 | P1 | 上传与新聊天使用不同索引 | P02 |
| F03 | P1 | 凭据硬编码且嵌入配置参数被覆盖 | 静态确认，未试用凭据 |
| F04 | P1 | 无服务端授权与路径约束，可写出会话目录 | P03 + 静态读写链 |
| F05 | P1 | bulk 错误被吞并，上传成功不可信 | P04、P07 |
| F06 | P2 | async 路由直接执行同步重任务、缺少服务端上传上限 | 静态路径风险，未压测 |
| F07 | P2 | XLSX/JSON 路径上传未向解析器交付数据 | P06 |
| F08 | P2 | chunk 标识不含文档身份，重复段落覆盖归属 | P05 + bulk index 操作 |
| F09 | P1 | 不可信 Markdown 直接进入 HTML 注入点 | P10 + 静态 DOM 接线 |
| F10 | P2 | 流内错误被当作答案，取消与终态不完整 | P09 + 静态状态机 |
| F11 | P2 | 默认依赖安装失败，现有 lint 门禁不通过 | npm 命令实测 |
| F12 | P2 | 部署入口、资源与依赖缺少可复现闭环 | 静态配置；未启动部署 |

## F01 · 登录与历史接口缺失

**位置：** `backend/app/app_main.py::app`；`router/chat_rt.py` 三个装饰路由；`frontend/src/api/user.ts`、`api/session.ts`、`router/guard/auth.tsx`。

**触发与机制：** 新浏览器没有 token，业务页面默认需要 auth，跳转登录后请求不存在的后端接口；历史入口同样没有实现。**影响：** 该前后端锁定组合无法完成常规登录和会话刷新恢复，不代表所有自定义代理部署都如此。**验证：** P01 对实际路由函数注册出的隔离 FastAPI 应用检查四个接口，均 404。

**修复方向：** 先明确单用户演示或认证产品的契约；实现配套后端或明确关闭不支持的 UI 能力，不能仅在 localStorage 伪造 token。**验收：** 干净浏览器进入、登录/准入、创建会话、刷新恢复有一致行为；前端调用清单全部匹配 OpenAPI，未知路径继续 404。

## F02 · 文件写入 default，聊天查随机 session

**位置：** `frontend/src/api/session.ts::upload/chat`，`pages/index/index.tsx::send`，`backend/app/router/chat_rt.py::upload_files/chat_on_docs`，`file_parse.py::execute_insert_process`。

**触发与机制：** RepositoryUpload 不传 session_id，后端用 default；主页随后新建随机 session 并以其作为 ES 索引查询，没有建立关联。**影响：** 正常上传→新聊天链无法检索刚上传的那份集合。**证据：** P02 记录真实路由对 fake 入库/检索的实参，分别是 default 与新 ID；未模拟 ES 索引存在性。

**修复方向：** 明确 knowledge_base_id 与 conversation_id 的不同职责，短期也可统一显式 ID，但必须验证授权。**验收：** 上传合成标记文本，新建/继续指定知识库会话可返回该标记的引用；另一知识库不会命中。

## F03 · 配置与凭据边界失效

**位置：** `backend/app/service/ragflow/file_parse.py::generate_embedding`，`rag/nlp/model.py::generate_embedding`，`chat.py` 两个模型入口，`rag/utils/es_conn.py::ESConnection.__init__`。

**触发与机制：** 源码含可用于凭据位置的硬编码字符串；embedding 函数直接覆盖 api_key/base_url 参数，chat 使用硬编码 fallback，ES 连接也不通过统一配置解析。`.env` 随源码快照提供，但本轮未读取其值。**影响：** 仓库可读者可接触嵌入凭据，调用者难以可靠切换账户；有效性与是否发生滥用未验证。正文和探针结果不保存字面凭据。

**修复方向：** 由维护者轮换相关凭据，移除 fallback 和参数覆盖，启动时校验必需配置；是否清理历史按仓库政策另行决策。**验收：** 无配置时在启动阶段明确失败；注入合成配置时 fake 客户端只收到合成值；扫描输出仅报位置不泄露值；本轮没有执行轮换或改写历史。

## F04 · 路径输入与索引选择没有授权约束

**位置：** `router/chat_rt.py::upload_files`（49 行起）、`chat_on_docs`；`rag/nlp/search_v2.py::retrieval` 的 tenant_ids 拆分；`rag/utils/es_conn.py::search`。

**触发与机制：** 请求者能访问 API 时，session_id、filename 直接交给 os.path.join，未限制父目录/绝对路径；服务端没有 Depends 身份校验，session_id 又直接决定写入或查询索引。**影响：** 可越过预期会话目录写文件，范围受进程文件权限限制；可选择任意字符串作为检索命名空间，实际 ES 可访问数据范围未在线测试。随机 session ID 不是访问控制。

**验证：** P03 只在临时根下分别使用父路径片段，观察到文件落到预期子目录之外，HTTP 200，无真实文件破坏。API 三路由没有鉴权是静态确认。

**修复方向：** 服务端生成存储名；对解析后的路径做根内约束并防符号链接逃逸；通过用户/知识库映射选择索引，不接受任意索引表达式。**验收：** 父路径、绝对路径、另一用户知识库 ID 返回 4xx 且磁盘/ES 零副作用；合法中文文件名可作为展示元数据保留。

## F05 · ES 错误未传播到用户成功状态

**位置：** `file_parse.py::execute_insert_process`（83 行起）；`rag/utils/es_conn.py::insert`（136 行起）；`router/chat_rt.py::upload_files`。

**机制：** ES bulk item 错误以列表返回，调用者忽略；非超时异常分支先 append 错误再将 res 清空，两轮后可返回 []；原文件写入没有回滚。**影响：** 用户看到成功但索引可能部分或完全没有写入。**验证：** P04 注入 bulk 错误列表仍 HTTP 200/success；P07 两次合成非超时异常最终返回 []。二者未接真实 ES。

**修复方向：** 定义 InsertResult 的成功数/失败项，明确重试边界；仅已发布的有效版本标为 ready，保留失败状态供重试。**验收：** 部分失败、认证失败、超时都不返回整体成功；相同操作重试不重复发布、不遗留错误可见版本。bulk 按项结果语义核对 [Elasticsearch 8.11 官方说明](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/docs-bulk.html)。

## F06 · 请求线程承担无界同步工作

**位置：** `router/chat_rt.py::upload_files/chat_on_docs`；`file_parse.py::execute_insert_process`。**触发：** 上传大文件、多文件，或模型/ES 较慢时，async 路由在 await 之后直接调用同步解析、逐块嵌入和检索，期间没有让出事件循环的应用级操作；文件 read 无 size 参数，客户端 5 MiB 限制可绕过。

**影响与限制：** 单个 worker 可被同步工作占用，内存需求随文件大小增长；没有测量耗尽、并发容量或实际延迟，不称为已发生泄漏。settings 中的 DOC_MAXIMUM_SIZE 没被上传入口使用。

**修复方向：** 首先服务端流式计数与配额、明确总超时；有界线程池隔离同步 I/O，CPU/OCR 有需要再迁到任务 worker。**验收：** 超限文件在阈值处停止写入；受控慢依赖下轻量请求可在明确预算内响应；取消后资源释放，并记录队列上限。

## F07 · 格式分支接受路径却使用空 binary

**位置：** `file_parse.py::parse`；`rag/app/naive.py::chunk` XLSX/JSON 分支；`deepdoc/parser/excel_parser.py::__call__` 与 `json_parser.py::__call__`。

**触发与机制：** 上传只传 file_path，binary 默认 None；XLSX 分支把 None 放进 BytesIO 后交 openpyxl，JSON 分支对 None 解码。**验证：** P06 在临时目录生成有效 xlsx/json，实际 chunk 路径得到 BadZipFile/AttributeError。**影响：** 这些格式不能通过当前路径入口，PDF/TXT 不据此判坏。

**修复方向：** 统一 parser 输入协议，显式传 filename 或读取 bytes；格式不支持时在写入昂贵存储前给 4xx。**验收：** 两格式用同一上传入口形成预期非空 chunk；损坏格式明确失败、不报告成功。旧 DOC 的 Tika 适配同样值得复查，但本轮未接线验证。

## F08 · 内容哈希不能表达文档归属

**位置：** `file_parse.py::process_item`（42 行起）、`es_conn.py::insert`。**触发：** 同 session 中两个文件含同一段落。**机制：** chunk hash 仅含内容和 session；ES 使用 index 同 ID 操作，第二份文档覆盖第一份的 doc_id/文档名。**验证：** P05 两个文件得到同一 chunk id 和不同 doc_id；实际 ES 覆盖未在线运行。

**修复方向：** 用文档稳定 ID、版本、chunk 序号确定身份；如确需内容去重，将内容实体与多文档归属分开。**验收：** 相同段落属于多个文件时保留全部来源；替换同名文档后旧版本不混入检索；失败版本不替换已发布版本。

## F09 · Markdown 的 HTML 信任边界未建立

**位置：** `frontend/src/components/markdown/index.tsx::Markdown`；调用点含聊天回答与引用 Drawer。**触发：** 模型输出或文档引用含原始 HTML/事件属性。**机制：** Marked.parse 结果未经清洗直接进入 dangerouslySetInnerHTML。**证据：** P10 对锁定 Marked 15.0.7 的合成字符串验证属性保留；未在浏览器执行攻击代码，也未读取真实 token。风险级别考虑浏览器用户状态同源可访问，不能据此声称凭据已被窃取。

**修复方向：** 采用严格标签/属性白名单，或禁用原始 HTML；同时保留需要的引用标记。**验收：** 合成危险属性与协议被移除，中文、表格、代码块和引用链接仍正确。官方明确 Markdown 解析并不提供 HTML 清洗：[Marked 文档](https://github.com/markedjs/marked)。

## F10 · 流的错误、结束与取消状态不对称

**位置：** `chat.py::get_chat_completion`、`frontend/src/pages/chat/index.tsx::sendChat/read/parseData`。**触发：** 后端生成器发 event:error、模型非 stop 结束、用户离开页面。**机制：** 前端忽略 event/role，error content 被拼入 assistant 正文；end 不是必需终态；卸载不主动 cancel。**验证：** P09 用真实 parseData 函数收到 role:error 后，target.content 增加而 target.error 未设置。其他分支静态确认，未测供应商取消计费行为。

**修复方向：** 定义 message/documents/error/end 的状态机和总预算，绑定 AbortController/reader 生命周期；推荐问题失败不应抹去已完成答案。**验收：** 故障显示独立错误且保留已生成内容；所有结束原因有终态；中断可被追踪，不无条件自动重发整次付费请求。

## F11 · 默认安装与质量门禁无法直接重现

**位置：** `frontend/package.json`、`package-lock.json`、`eslint.config.js` 及 lint 报告定位。**验证：** Node 24.21.0 下默认 `npm ci --ignore-scripts --no-audit --no-fund` 退出 1（ahooks 3.8.4 peer React ≤18 与 React 19 冲突）。在隔离副本用 legacy peer 模式后构建成功；lint 退出 1，26 errors、10 warnings。

**影响：** 新环境默认安装不通，门禁不能直接作为绿色基线；并不证明 React 19 在所有 UI 场景运行失败。**修复方向：** 选择相互支持的依赖组合并锁定 Node/npm，修复或有理由地调整规则；不将忽略 peer 作为默认质量结论。**验收：** 干净检出默认安装、build、lint 都成功，核心 React hooks/stream 行为有回归覆盖。

## F12 · 启动与发布依赖隐含本机条件

**位置：** `backend/app/Dockerfile`、`docker-compose.yml`、`nginx_certbot/https.conf`、`start_backend.sh`、`rag/nlp/rag_tokenizer.py`、`deepdoc/parser/pdf_parser.py`。

**机制与前提：** 自定义基础镜像来源缺失；模型/NLP 资源需要外部准备；后端关键 SDK 版本未锁定；ES 客户端固定使用 Compose DNS，与宿主机启动方式不天然相容；单独 Nginx 目标端口与当前主机映射不一致。**影响：** 新机器或把零散配置拼为部署时可能启动失败、降级分词或不能转发 API。只确认配置差异，没有做 Docker 构建、DNS/端口实测。

**修复方向：** 定义一种可复现开发方式和一种部署拓扑；统一 Settings、固定依赖/资源摘要、startup/readiness 自检与部署契约。**验收：** 空缓存环境按文档启动，缺资源可诊断；API→ES、代理→API 与 SSE 首帧实测；不要求本轮新增部署基础设施。

## 待确认与覆盖限制

Q01：重排适配器是否按得分重新排序、分数与候选 ID 是否错配。P08 仅验证此返回顺序下当前包装会丢身份；实际 `llama-index-postprocessor-dashscope-rerank-custom` 没有锁定版本，本轮不下载调用供应商，不能列为已证实生产排序缺陷。

没有执行线上负载、OCR 质量评测、模型输出正确性或真实 ES 写入。本轮不对所有内嵌 DeepDOC 算法作全仓安全审计，也不把尚未接线的 eval/演示代码认定为当前 HTTP 可达漏洞。

本地 `evidence/probe_backend.py`、`probe_frontend.cjs` 与两份 results.json 保存小型复现；探针断言的是缺陷存在，修复后应改成正确行为的回归测试。证据附件只留项目本地，不随六篇公开正文上传；正文已包含触发条件、结果和边界。
