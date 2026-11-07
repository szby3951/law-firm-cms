# 基于LLM的律所客户智能管理系统设计与实现 — 架构设计文档

> 后端：FastAPI ｜ 前端：Vue 3 ｜ 数据库：MySQL 8 ｜ 依赖管理：uv（pyproject.toml + uv.lock）
> 亮点：AI 法律小助手（RAG + LLM，统一通过 OpenAI 兼容 API 接入云端大模型）

---

## 一、项目概述

### 1.1 背景

传统律师事务所的客户管理多依赖 Excel、纸质台账或功能单一的 CRM，存在以下痛点：

- 客户信息分散，跟进记录难以追溯，容易流失客户；
- 案件从「立案 → 分案 → 办理 → 结案」的全生命周期缺乏统一跟踪；
- 收费、开票、日程（开庭/截止）靠人工记忆，易遗漏；
- 律师重复性文书工作多，法律检索耗时；
- 委托客户无法自助查看案件进度和账单，与律师沟通成本高。

本系统面向中小型律师事务所，提供「客户—案件—合同—收费—日程—文书」一体化的数字化管理，同时开放客户端让委托客户自助查询进度与在线咨询，并集成 AI 法律小助手，实现法律咨询问答、智能文书生成、合同风险审查等能力。

### 1.2 设计目标

| 目标 | 说明 |
|---|---|
| 业务闭环 | 覆盖客户→案件→收费→结案的全流程，客户可自助查询 |
| 三端角色 | 用户（客户）/ 律师 / 管理员，数据按角色隔离 |
| 智能增强 | AI 小助手嵌入业务场景（非独立聊天玩具） |
| 可扩展 | 分层 + RESTful + 配置化 LLM 接入，便于替换模型与扩展功能 |
| 工程规范 | uv 依赖管理、类型提示、分层架构，便于答辩展示 |

---

## 二、技术选型

| 层次 | 技术 | 版本 | 说明 |
|---|---|---|---|
| 后端框架 | FastAPI | 0.115+ | 原生异步、自动 OpenAPI 文档、Pydantic 校验 |
| Web 服务器 | Uvicorn | 0.30+ | ASGI，开发用 --reload |
| 依赖管理 | **uv** | latest | `pyproject.toml` + `uv.lock`，锁定全量依赖 |
| Python 版本 | Python | 3.11+ | |
| ORM | SQLAlchemy 2.0 (async) | 2.0+ | 异步 ORM，配合 aiomysql |
| 数据校验 | Pydantic v2 | 2.x | 请求/响应模型、序列化、Settings |
| 认证鉴权 | python-jose + passlib[bcrypt] | — | JWT 无状态登录、密码加盐哈希 |
| 数据库 | MySQL 8.0 | 8.0+ | utf8mb4，InnoDB |
| 向量数据库(RAG) | Qdrant | — | 法律条文 embedding 存储，支持过滤检索 |
| AI 模型 | OpenAI 兼容 API（云端） | — | httpx 调用，配置化接入 |
| Embedding | text-embedding 系列（云端 API） | — | 法律条文、案例向量化 |
| 定时任务 | APScheduler | 3.10+ | 开庭/缴费/跟进到期提醒 |
| 文件存储 | 本地磁盘 / MinIO | — | 合同、证据、扫描件 |
| 前端框架 | Vue 3 | 3.4+ | 组合式 API |
| 构建工具 | Vite | 5+ | 快速启动、HMR |
| 状态管理 | Pinia | 2+ | 用户/权限状态 |
| 路由 | Vue Router | 4+ | 动态路由（按角色） |
| UI 组件 | Element Plus | — | 后台中台风格 |
| HTTP | Axios | — | 拦截器统一处理 Token / 错误 |
| 图表 | ECharts (vue-echarts) | — | 统计大屏 |
| 部署 | Docker Compose | — | 一键拉起 MySQL + 后端 + 前端 |

> 向量库使用 Qdrant，支持 Docker 一键部署，提供高效的向量检索和元数据过滤；若需要轻量化方案可降级为 MySQL 存条文 + numpy 余弦相似度，答辩时说明可平滑迁移至 Qdrant 即可。

---

## 三、系统角色与权限

系统共设 **3 个角色**：`用户(client)`、`律师(lawyer)`、`管理员(admin)`。

### 3.1 用户（client）
委托方，注册登录后查看自己的委托事项。

| 功能 | 说明 |
|---|---|
| 账号注册/登录 | 手机号+密码，JWT 鉴权 |
| 我的案件 | 查看本人委托案件的进度、时间线、开庭日期 |
| 我的账单 | 查看应收费用、已缴费用、发票状态 |
| 文书查看 | 下载律师发来的起诉状/合同等文书 |
| 在线留言 | 给负责律师留言、上传补充证据材料 |
| AI 法律问答 | 使用法律 AI 小助手进行基础法律咨询 |
| 个人中心 | 修改手机号、密码、查看通知 |

### 3.2 律师（lawyer）
律所执业律师，管理自己承办的客户和案件。

| 功能 | 说明 |
|---|---|
| 登录/工作台 | 首页待办、今日开庭、待跟进客户提醒 |
| 客户管理 | 客户档案、跟进记录、客户标签、待跟进列表 |
| 案件管理 | 立案登记、案件时间线、协办协作、上传文书 |
| 合同管理 | 合同台账、上传合同、AI 合同审查 |
| 收费管理 | 登记收款、查看自己案件的收费情况 |
| 日程管理 | 开庭/举证/回访日程，日历视图 |
| 文书管理 | 模板生成、AI 文书初稿、导出 docx |
| AI 助手 | RAG 问答、文书生成、合同审查、案件摘要 |
| 数据权限 | 只能看「本人主办 + 协办」的客户和案件 |

### 3.3 管理员（admin）
律所行政/负责人，全局管理。

| 功能 | 说明 |
|---|---|
| 全部客户/案件 | 查看全所数据，不受行级权限限制 |
| 分案调度 | 立案后分配主办律师、调案 |
| 账号管理 | 律师账号开通/禁用、重置密码、审核客户注册 |
| 收费审核 | 全所账单、发票、回款统计、催收清单 |
| 统计大屏 | 收案趋势、案由分布、律师创收排名、客户来源 |
| 系统设置 | 律所信息、数据字典、文书模板维护 |
| AI 配置 | 模型选择、API 地址/Key、温度参数 |
| 操作审计 | 登录日志、删除/导出等敏感操作留痕 |

### 3.4 权限对比矩阵

| 功能模块 | 用户(client) | 律师(lawyer) | 管理员(admin) |
|---|:-:|:-:|:-:|
| 注册/登录 | ✅ | ✅ | ✅ |
| 查看案件 | ✅（仅本人） | ✅（本人承办） | ✅（全部） |
| 新增客户 | ❌ | ✅ | ✅ |
| 立案/分案 | ❌ | ✅（立案） | ✅（分案） |
| 合同管理 | 查看本人合同 | ✅（本人案件） | ✅（全部） |
| 收费/开票 | 查看本人账单 | 登记收款 | 全所管理 |
| 上传文书/证据 | 上传补充材料 | ✅（本人案件） | ✅ |
| AI 法律问答 | ✅ | ✅ | ✅ |
| 统计大屏 | ❌ | 个人数据 | ✅（全所） |
| 系统/AI 配置 | ❌ | ❌ | ✅ |

---

## 四、系统总体架构

### 4.1 分层架构

```
┌───────────────────────────────────────────────────────────────┐
│  表现层 (Vue 3 SPA)                                              │
│  客户端(/client)  律师端(/lawyer)  管理端(/admin)                │
│  (Element Plus + Pinia + Vue Router + ECharts + Axios)          │
└───────────────▲───────────────────────────────┬────────────────┘
                │  HTTPS / JSON (REST)          │  SSE(流式)
┌───────────────┴───────────────────────────────▼────────────────┐
│  接口层 (FastAPI Router)                                         │
│  /api/auth  /api/clients  /api/cases  /api/contracts            │
│  /api/billing  /api/schedule  /api/documents  /api/stats        │
│  /api/ai  /api/admin                                             │
│  —— Pydantic 校验 · JWT 依赖注入 · 角色权限装饰器 ——              │
└───────────────▲────────────────────────────────────────────────┘
                │
┌───────────────┴────────────────────────────────────────────────┐
│  业务服务层 (Services)                                            │
│  AuthService  ClientService  CaseService  ContractService        │
│  BillingService  ScheduleService  DocService  StatService        │
│  AIGatewayService                                                │
└───────────────┬──────────────────────────────────┬─────────────┘
                │                                  │
┌───────────────▼───────────────┐  ┌────────────────▼──────────────┐
│  数据层                        │  │  AI 服务层 (RAG + LLM)          │
│  SQLAlchemy + MySQL 8          │  │  知识加载→切分→Embedding→检索   │
│  (user/client/case/...)        │  │  →Prompt 编排→LLM→后处理        │
│  Qdrant 向量库 (法律语料)       │  │  流式输出 (SSE)                │
└───────────────────────────────┘  └────────────────────────────────┘
                │                                  │
┌───────────────▼──────────────────────────────────▼─────────────┐
│  基础设施：文件存储 · APScheduler 定时任务 · 日志 · 配置管理       │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 关键设计决策

- **前后端分离**：Vue SPA 通过 REST 与后端通信，AI 流式回复走 SSE，避免长连接阻塞。
- **JWT 无状态鉴权**：登录发 Token，后续请求 `Authorization: Bearer <token>`，后端用 FastAPI 依赖注入统一校验 + 角色校验。
- **配置化 LLM 接入**：模型地址/Key/名称放 `.env`，统一通过 OpenAI 兼容 API 接入云端大模型。
- **AI 与业务解耦**：`AIGatewayService` 统一封装 LLM 调用，业务模块通过它获取能力，替换模型不影响业务。
- **行级数据隔离**：律师只能看「本人主办 + 协办」的案件/客户；用户只能看「本人」委托的案件；管理员看全部，通过查询条件注入实现。
- **uv 依赖管理**：使用 `uv` 替代传统 `requirements.txt`，`pyproject.toml` 声明依赖，`uv.lock` 锁定全量传递依赖，保证开发/测试/生产环境一致。

### 4.3 部署架构

```
浏览器 ──► Nginx ──► Vue 静态资源（/client、/lawyer、/admin 三个路由段）
          └────► Uvicorn (FastAPI, 8000)
                   ├──► MySQL 8 (3306)
                   ├──► Qdrant 向量库
                   └──► LLM (OpenAI 兼容 API)
```

开发期：Vite dev server 代理 `/api → localhost:8000`，避免跨域。

---

## 五、功能模块设计

系统共 11 个模块，按三角色分别暴露功能：律师/管理员在后台管理端操作，客户端用户仅可见与本人相关的自助功能。

### 5.1 模块总览

| # | 模块 | 律师/管理员端 | 客户端（用户） | 优先级 |
|---|---|---|---|---|
| 1 | 认证与权限 | 登录、账号管理、角色权限、审计日志 | 注册、登录、个人中心 | 必须 |
| 2 | 客户关系管理 | 客户档案、跟进记录、标签分级（管理员看全部，律师看本人） | ❌ | 必须 |
| 3 | 案件管理 | 立案、分案、时间线、状态流转、协办协作 | 查看本人案件进度、时间线、上传补充材料 | 必须 |
| 4 | 合同管理 | 合同台账、上传、AI 审查、到期预警 | 查看/下载本人合同 | 必须 |
| 5 | 收费管理 | 收费方案、登记收款、发票、催收清单、创收统计 | 查看本人账单、缴费状态 | 必须 |
| 6 | 日程与通知 | 内部日程（开庭/举证/会议）、APScheduler 提醒 | 仅接收开庭/期限等对外通知推送 | 重要 |
| 7 | 文书管理 | 模板库、AI 生成、编辑、导出、归档 | 查看/下载本人案件文书 | 重要 |
| 8 | 沟通留言 | 回复客户留言、上传证据材料 | 给律师留言、上传补充材料 | 重要 |
| 9 | AI 法律助手 | RAG 问答、文书生成、合同审查、案件摘要 | RAG 基础法律咨询（附免责声明） | 亮点 |
| 10 | 统计报表 | 管理员全所大屏 / 律师个人工作台 | ❌ | 重要 |
| 11 | 系统设置 | 律所信息、数据字典、AI 配置、操作日志 | ❌ | 一般 |

### 5.2 认证与权限模块

- **注册/登录**：客户端可自助注册（手机号+密码）；律师/管理员账号由管理员开通。
- **密码**：bcrypt 加盐哈希。
- **JWT**：Token 内含 `user_id`、`role`、`team_id`；前端按角色动态生成路由与按钮。
- **数据隔离**：
  - client：只能看本人委托的案件、账单、文书；
  - lawyer：只能看「我主办 / 我协办」的案件与客户；
  - admin：全局可见。
- **操作日志**：登录、删除、导出等敏感操作记录审计日志。

### 5.3 客户关系管理模块（律师/管理员端）

> 客户端用户不存在此菜单，客户视角通过"我的案件"等自助页面体现。

- 客户档案：个人/机构客户、基本信息、联系方式、证件号（脱敏展示）、来源渠道。
- 跟进管理：每次接触生成跟进记录（时间、方式、内容、下次跟进时间），待跟进列表按到期日排序。
- 客户 ↔ 案件：一个客户可关联多个案件（一对多）。
- 标签/分级：VIP、潜在 → 成交的状态流转（客户漏斗）。
- 查询与导出：多条件筛选、分页、Excel 导出（openpyxl）。

### 5.4 案件管理模块（业务核心）

案件全生命周期状态机：

```
咨询中 → 已立案 → 办理中 → 待结案 → 已结案 / 已退案
```

**律师/管理员端**：

- 立案：案由（民事/刑事/行政/商事）、案件类型（诉讼/非诉）、受理法院、对方当事人、标的额。
- 分案与协作：主办律师 + 协办律师（多对多），管理员可分案、调案。
- 案件时间线：立案、受理、开庭、举证、判决等节点登记，时间轴可视化。
- 关联档案：合同、证据材料、文书、聊天记录（文件上传）。
- 承办费用：案件关联收费方案，结案后自动生成对账数据。

**客户端**：

- 查看本人委托案件的状态、进度、开庭日期、时间线。
- 上传补充证据材料（照片/PDF）到对应案件。

### 5.5 合同管理模块

**律师/管理员端**：

- 合同台账：名称、类型（委托代理/风险代理）、关联客户/案件、金额、起止日期、状态。
- 合同模板：常用合同模板库，一键引用生成草稿。
- **AI 合同风险审查**：上传合同 → AI 提取关键条款 → 标出风险点 → 生成审查报告。
- 到期预警：APScheduler 扫描，提前 N 天提醒续期。

**客户端**：查看和下载本人签署的合同 PDF。

### 5.6 收费管理模块

**律师/管理员端**：

- 收费方式：固定收费、按标的比例、风险代理、计时收费。
- 收费方案：案件下可建多期收费（首期/二期/尾款）。
- 账单 → 收款：登记实收，支持部分收款；应收未收自动生成催收清单。
- 发票登记：开票信息、发票号。
- 统计：月度营收、律师创收排名、回款率。

**客户端**：查看本人案件的账单明细、应收/已缴金额、发票状态。

### 5.7 日程与通知模块

**律师/管理员端（内部日程）**：

- 日程类型：开庭、期限（举证/上诉/缴费）、客户回访、内部会议。
- 关联：日程挂接案件/客户，展示承办律师。
- 提醒：APScheduler 每天扫描未来 N 天事项，写入站内通知 + 首页待办。
- 日历视图：月/周/日视图。

**客户端（对外通知）**：

- 仅接收与本人案件相关的开庭提醒、期限提醒、进度更新通知。
- 不展示律师内部的其他日程安排。

### 5.8 文书管理模块

**律师端**：

- 文书库：起诉状、答辩状、律师函、法律意见书、委托书等分类。
- 模板管理：变量占位符（`{客户姓名}` `{案由}`），选择案件 → 自动填充 → 在线编辑。
- **AI 文书生成**：选择文书类型 + 案件事实 → LLM 生成初稿 → 律师修改 → 归档。
- 导出：docx 导出（python-docx）。

**客户端**：查看和下载律师发布到本人案件下的文书。

### 5.9 沟通留言模块（新增）

**客户端**：

- 向负责律师发送文字留言、上传补充材料（图片/PDF）。
- 查看律师回复记录。

**律师端**：

- 在客户详情页查看和回复留言。
- 对留言进行标记（已读/未读、待跟进）。

### 5.10 AI 法律助手模块

**律师端（全功能）**：

- RAG 法律问答（带法条引用）。
- 智能文书生成（起诉状、律师函等初稿）。
- 合同风险审查（结构化报告）。
- 案件摘要（长卷宗自动总结要点）。

**客户端（受限）**：

- 仅开放基础法律问答，回答末尾附「本内容仅供参考，不构成法律意见」。
- 不开放文书生成、合同审查等专业功能。
- 不提供案件数据摘要，避免越权。

### 5.11 统计报表模块（ECharts 大屏）

- **管理员**：收案趋势（月度/案由分布）、案件状态分布、律师办案量与创收排名、客户来源占比、回款率、到期合同预警数。
- **律师**：个人工作台——本人待办开庭、待跟进客户、在办案件数、本月创收。
- **客户端**：无统计页面。

### 5.12 系统设置模块

- 律所信息、数据字典（案由、合同类型等下拉项维护）、文书模板维护。
- AI 配置页：模型选择、API 地址/Key、温度参数（管理员可见）。
- 操作日志查询。

---

## 六、AI 法律小助手（系统亮点）

### 6.1 定位

不是「套个聊天框」，而是嵌入业务场景的 AI 能力层：

- 对律师/助理：文书起草、合同审查、法条检索、类案参考；
- 对客户：基础法律问答 + 引导预约咨询（附合规免责声明）。

### 6.2 核心能力

| # | 能力 | 说明 | 技术实现 | 难度 |
|---|---|---|---|:-:|
| ① | 法律咨询问答 | 基于法律条文库的 RAG 问答，答案附法条出处 | 向量检索 + Prompt 编排 + LLM | ★★★ |
| ② | 智能文书生成 | 起诉状/律师函/意见书初稿，按案件事实填充 | 模板 + 结构化 Prompt + 流式输出 | ★★★ |
| ③ | 合同风险审查 | 上传合同 → 关键条款抽取 + 风险点标注 + 报告 | 长文分块 + JSON 结构化输出 | ★★★★ |
| ④ | 相似案例推荐 | 输入案情，推荐相似历史案件 + 相关法条 | 向量相似度检索 | ★★★ |
| ⑤ | 案件摘要 | 长卷宗/材料自动总结要点 | LLM 摘要 + 流式 | ★★ |
| ⑥ | 对话记忆 | 多轮上下文、会话历史可回看 | 会话表 + 上下文窗口管理 | ★★ |
| ⑦ | 客户画像 | 聚合客户档案、跟进、案件、沟通、收费数据，自动生成客户类型、核心诉求、风险点、跟进建议 | 数据聚合 + JSON 结构化输出 | ★★ |

### 6.3 AI 能力 × 客户生命周期映射

> 核心设计：LLM 不是外挂聊天机器人，而是嵌入客户全生命周期的智能引擎，每个 AI 能力都以客户业务数据为基础。

| 客户生命周期 | 业务环节 | AI 能力 | 服务的客户数据 |
|---|---|---|---|
| 线索获取 | 新客户登记、首次咨询 | 法律咨询问答（①） | 咨询内容、意向信息 |
| 洽谈跟进 | 跟进记录、回访计划 | 对话记忆（⑥）、跟进摘要与回复建议 | 跟进记录、沟通留言 |
| 签约委托 | 合同签订、收费方案 | 合同风险审查（③） | 合同文本、收费数据 |
| 服务中 | 案件办理、客户自助查询 | 案件摘要（⑤）、智能文书生成（②）、相似案例推荐（④） | 案件信息、卷宗材料 |
| 流失管理 | 客户状态变化、挽回 | 客户画像（⑦） | 客户全量数据（档案/跟进/案件/沟通/收费） |

### 6.4 RAG 问答流程

```
用户问题
   │
   ▼
[1] 查询改写      LLM 将口语问题改写为检索 query
   │
   ▼
[2] 向量化        Embedding 模型对 query 编码
   │
   ▼
[3] 向量检索      Qdrant 中对法律条文 top-k（k=5~8）+ 元数据过滤
   │
   ▼
[4] 重排融合      向量分 + 关键词(BM25) 混合排序
   │
   ▼
[5] Prompt 编排   系统提示词 + 检索条文 + 用户问题
   │
   ▼
[6] LLM 生成      流式输出（SSE）逐字渲染
   │
   ▼
[7] 引用标注      回答中标注 [1][2] 对应法条，前端可点击展开原文
   │
   ▼
[8] 落库          会话与问答记录写入 DB（审计 + 后续优化）
```

RAG 语料来源：
- **法律条文库**：预置《民法典》《刑法》《民事诉讼法》《公司法》常用章节，按「条」切分入库；
- **律所知识库**：历史案件摘要、法律文书、常见问题 FAQ（管理员后台上传维护）。

### 6.5 合规与安全

- **免责声明**：AI 回答附「本内容仅供参考，不构成法律意见」；
- **数据脱敏**：送入 LLM 前对客户身份证号、电话等敏感字段脱敏；
- **权限控制**：AI 功能仅登录用户可用，律师案件数据仅本人可触发摘要；
- **留痕审计**：所有 AI 问答与生成记录落库可追溯；
- **降级策略**：模型服务不可用时返回友好提示，不影响管理系统主功能。

---

## 七、数据库设计（MySQL 8，utf8mb4）

### 7.1 E-R 核心关系

```
user(1) ──< case_lawyer >── (1)case        user(1, client) ──< case(n)
case(1) ──< contract(n)                    case(1) ──< fee_plan(1) ──< fee_period(n)
case(1) ──< document(n)                   case(1) ──< schedule(n)
case(1) ──< case_event(n)                 user(1, client) ──< follow_record(n)
user(1) ──< ai_session(1) ──< ai_message(n)
dict_item(字典)   law_article(法律条文库, 元数据+向量ID)
```

### 7.2 核心表结构

> 角色统一在 `user.role` 字段区分：`client`（客户）/ `lawyer`（律师）/ `admin`（管理员）。

#### user（用户表，三角色共用）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 用户 ID |
| username | VARCHAR(64) UNIQUE | 登录账号（客户用手机号，律师/管理员用工号） |
| password_hash | VARCHAR(255) | bcrypt 哈希 |
| real_name | VARCHAR(64) | 真实姓名 / 客户姓名 |
| role | ENUM('client','lawyer','admin') | 角色 |
| phone | VARCHAR(20) | 手机号 |
| email | VARCHAR(128) | 邮箱 |
| avatar | VARCHAR(255) | 头像 URL |
| status | TINYINT | 1 正常 / 0 禁用 |
| created_at | DATETIME | 注册时间 |
| updated_at | DATETIME | 更新时间 |

#### client_profile（客户扩展档案，仅 role=client 时有记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| user_id | BIGINT FK → user.id | 关联登录账号 |
| client_type | ENUM('personal','company') | 个人/机构 |
| id_no | VARCHAR(18) | 证件号（加密存储，展示脱敏） |
| gender | VARCHAR(8) | 性别 |
| address | VARCHAR(255) | 联系地址 |
| source_channel | VARCHAR(32) | 来源渠道（转介绍/网络/门店） |
| level | ENUM('vip','normal') | 客户分级 |
| status | ENUM('potential','deal','lost') | 客户状态 |
| lawyer_id | BIGINT FK → user.id | 负责律师（owner） |
| ai_profile | JSON | AI 客户画像（客户类型/核心诉求/风险点/跟进建议，可刷新） |
| ai_profile_at | DATETIME | 画像生成时间 |
| remark | TEXT | 备注 |

#### follow_record（跟进记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| client_id | BIGINT FK → client_profile.id | 客户 |
| user_id | BIGINT FK → user.id | 跟进人（律师） |
| content | TEXT | 跟进内容 |
| method | ENUM('phone','wechat','visit','email') | 跟进方式 |
| next_follow_date | DATE | 下次跟进日期 |
| created_at | DATETIME | |

#### case（案件）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| case_no | VARCHAR(64) | 案号 |
| client_id | BIGINT FK → client_profile.id | 委托客户 |
| title | VARCHAR(255) | 案件标题 |
| case_cause | VARCHAR(64) | 案由 |
| case_type | ENUM('litigation','non_litigation') | 诉讼/非诉 |
| court | VARCHAR(255) | 受理法院/机构 |
| opposing_party | VARCHAR(255) | 对方当事人 |
| amount | DECIMAL(12,2) | 标的额 |
| status | ENUM('consulting','filed','handling','pending_close','closed','withdrawn') | 案件状态 |
| description | TEXT | 案情描述 |
| created_at | DATETIME | |
| closed_at | DATETIME | 结案时间 |

#### case_lawyer（案件-律师关联，多对多）

| 字段 | 类型 | 说明 |
|---|---|---|
| case_id | BIGINT FK → case.id | |
| lawyer_id | BIGINT FK → user.id | |
| duty | ENUM('lead','assist') | 主办/协办 |

#### case_event（案件节点时间线）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| event_type | ENUM('filing','accept','hearing','evidence','judgment','other') | 节点类型 |
| event_date | DATETIME | 节点时间 |
| description | VARCHAR(500) | 说明 |
| created_by | BIGINT FK → user.id | 登记人 |

#### contract（合同）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| client_id | BIGINT FK → client_profile.id | |
| name | VARCHAR(255) | 合同名称 |
| contract_type | VARCHAR(32) | 委托代理/风险代理/其他 |
| amount | DECIMAL(12,2) | 合同金额 |
| start_date | DATE | 生效日期 |
| end_date | DATE | 到期日期 |
| status | ENUM('draft','active','expired','terminated') | 状态 |
| file_url | VARCHAR(500) | 合同文件 |
| ai_review_report | JSON | AI 审查结果 |
| created_at | DATETIME | |

#### fee_plan / fee_period / payment（收费）

- **fee_plan**：id, case_id, fee_type(fixed/ratio/risk/hourly), total_amount, description
- **fee_period**：id, fee_plan_id, period_no, due_amount, due_date, status(unpaid/partial/paid)
- **payment**：id, fee_period_id, amount, pay_method, receipt_no, paid_at, created_by

#### document（文书）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| doc_type | VARCHAR(32) | complaint/response/lawyer_letter/opinion... |
| title | VARCHAR(255) | |
| content | LONGTEXT | 富文本内容 |
| is_ai_generated | BOOLEAN | 是否 AI 生成 |
| ai_session_id | BIGINT | 关联 AI 会话 |
| file_url | VARCHAR(500) | 导出的 docx 文件 |
| created_by | BIGINT FK → user.id | |

#### doc_template（文书模板）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| doc_type | VARCHAR(32) | 文书类型 |
| name | VARCHAR(128) | 模板名称 |
| content | TEXT | 含 `{变量}` 占位符 |

#### schedule（日程）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | 可空 |
| client_id | BIGINT FK → client_profile.id | 可空 |
| user_id | BIGINT FK → user.id | 承办律师 |
| title | VARCHAR(255) | |
| schedule_type | ENUM('hearing','deadline','visit','meeting') | 开庭/期限/回访/会议 |
| event_date | DATETIME | 时间 |
| remind_at | DATETIME | 提醒时间 |
| status | ENUM('pending','done','cancelled') | |

#### ai_session / ai_message（AI 会话）

- **ai_session**：id, user_id, type(chat/document/contract/case), related_id, title, created_at
- **ai_message**：id, session_id, role(user/assistant), content, refs(JSON 法条引用), token_usage, created_at

#### law_article（法律条文库）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| law_name | VARCHAR(64) | 法律名称（民法典/刑法...） |
| chapter | VARCHAR(128) | 章节 |
| article_no | VARCHAR(32) | 条号 |
| content | TEXT | 条文内容 |
| effective_status | VARCHAR(16) | 生效状态 |
| vector_id | VARCHAR(64) | Qdrant 中的向量点 ID |

#### dict_item（数据字典）/ operation_log（操作日志）

- **dict_item**：id, dict_type(case_cause/contract_type...), label, sort
- **operation_log**：id, user_id, action, target, ip, created_at

**索引要点**：case(client_id), case(status), case_lawyer(lawyer_id), fee_period(due_date), schedule(remind_at), ai_message(session_id), user(username)。

---

## 八、后端项目结构（FastAPI + uv）

### 8.1 依赖管理（uv）

项目根目录使用 `pyproject.toml` 声明依赖，`uv.lock` 锁定全量版本：

```toml
# pyproject.toml
[project]
name = "law-firm-crm"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "aiomysql>=0.2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "python-multipart>=0.0.9",
    "apscheduler>=3.10.0",
    "httpx>=0.27.0",
    "qdrant-client>=1.12.0",
    "openpyxl>=3.1.0",
    "python-docx>=1.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.6.0",
]
```

常用命令：

```bash
uv sync                  # 安装依赖并生成/同步 uv.lock
uv add fastapi           # 新增依赖
uv run uvicorn app.main:app --reload
uv run pytest
```

### 8.2 目录结构

```
backend/
├── app/
│   ├── main.py                # 应用入口、CORS、路由注册、启动定时任务
│   ├── config.py              # pydantic-settings 读取 .env
│   ├── database.py            # async engine + session
│   ├── dependencies.py        # get_db, get_current_user(JWT), require_role
│   ├── models/                # SQLAlchemy ORM 模型
│   │   ├── user.py  client.py  case.py  contract.py  billing.py ...
│   ├── schemas/               # Pydantic 请求/响应模型
│   ├── routers/                # 路由层（薄，只做校验与编排）
│   │   ├── auth.py  clients.py  cases.py  contracts.py  billing.py
│   │   ├── schedule.py  documents.py  stats.py  ai.py  admin.py
│   ├── services/               # 业务逻辑层（核心）
│   │   ├── client_service.py  case_service.py  contract_service.py
│   │   ├── billing_service.py  stat_service.py  ai_service.py
│   ├── ai/                     # AI 能力层（亮点）
│   │   ├── gateway.py         # AIGateway: chat/embed/json 统一接口
│   │   ├── rag.py              # 检索器: 向量检索+重排+上下文拼装
│   │   ├── prompts.py          # 各场景 Prompt 模板
│   │   ├── kb_builder.py      # 法律条文库导入/切分/向量化
│   │   └── llm_clients/        # openai_client.py（可扩展多供应商）
│   ├── core/                   # security(JWT/密码)、logging
│   └── scheduler.py            # APScheduler: 提醒/到期扫描
├── scripts/                   # 初始化数据、条文导入
├── tests/
├── .env
├── pyproject.toml
├── uv.lock
└── Dockerfile
```

### 8.3 关键 API

```
POST   /api/auth/register                客户端注册
POST   /api/auth/login                   登录（返回 role）
GET    /api/clients?page&keyword&status  客户分页（律师/管理员）
POST   /api/clients/{id}/follows         新增跟进记录
GET    /api/cases?status=&cause=&lawyer=  案件列表（按角色过滤）
POST   /api/cases                        立案（律师）
POST   /api/cases/{id}/assign            分案（管理员）
PATCH  /api/cases/{id}/status            状态流转
GET    /api/my/cases                     客户端：我的案件
GET    /api/my/bills                     客户端：我的账单
POST   /api/contracts                    上传合同
POST   /api/ai/chat                      RAG 问答（SSE 流式）
POST   /api/ai/generate-document         文书生成（SSE）
POST   /api/ai/review-contract/{id}     合同审查（JSON 报告）
GET    /api/stats/dashboard              大屏数据
```

---

## 九、前端项目结构（Vue 3）

```
frontend/
├── src/
│   ├── api/               # axios 封装: request.js + 各模块接口
│   ├── router/            # 路由 + 按角色守卫（/client /lawyer /admin）
│   ├── stores/            # Pinia: user(信息/角色/Token)
│   ├── layouts/           # 三端布局：客户端简洁布局 + 律所后台布局
│   ├── views/
│   │   ├── auth/          # 登录、注册
│   │   ├── client/        # 客户端：我的案件、我的账单、文书、留言、AI 咨询
│   │   ├── lawyer/        # 律师端：客户、案件、合同、收费、日程、文书
│   │   ├── admin/          # 管理端：全所数据、分案、账号、统计、设置
│   │   ├── dashboard/      # 首页待办 + 统计
│   │   └── ai/            # AI 助手对话窗
│   ├── components/        # AI 聊天窗(流式)、法条引用弹层、时间轴、状态标签
│   └── utils/
├── vite.config.js          # 代理 /api → :8000
├── package.json
└── pnpm-lock.yaml
```

---

## 十、开发计划（8 周）

| 阶段 | 周期 | 内容 |
|---|---|---|
| 1 需求与设计 | 1 周 | 需求分析、原型、数据库设计、技术选型（本文档） |
| 2 后端基础 | 1.5 周 | uv 工程搭建、JWT 认证、三角色权限、客户 CRUD |
| 3 业务核心 | 2 周 | 案件全生命周期、合同、收费、日程、定时提醒 |
| 4 前端 | 1.5 周 | 三端布局/路由/权限、各业务页面、首页统计 |
| 5 AI 亮点 | 2 周 | RAG 问答、文书生成、合同审查、SSE 流式 |
| 6 测试完善 | 1 周 | 功能/接口测试、Bug 修复、Docker 部署 |
| 7 论文 | 1 周 | 撰写论文 + 答辩 PPT |

### 答辩演示脚本

1. 登录（分别展示客户端、律师端、管理员端）；
2. 客户端：注册 → 查看我的案件进度 → 在线留言；
3. 律师端：工作台待办 → 登记客户跟进 → 立案分案 → 上传合同；
4. 管理员端：统计大屏 → 分案调度 → AI 配置管理；
5. AI 演示：问"违约金过高如何调整" → 流式回答 + 法条引用；
6. AI 演示：上传合同 → 生成风险审查报告；
7. AI 演示：选案件一键生成起诉状初稿 → 导出 docx。

---

## 十一、论文可写的技术亮点

1. **面向律所业务的三端三角色架构**：客户端自助查询 + 律师工作台 + 管理端调度，行级数据权限隔离；
2. **基于 RAG 的法律知识问答**：法律条文向量化、混合检索、带引用溯源，抑制大模型幻觉；
3. **结构化驱动的文书生成**：案件字段 → 文书初稿，AI 深度嵌入业务流；
4. **JSON Schema 约束的合同风险审查**：长文分块 + 结构化风险报告 + 原文定位；
5. **可配置的模型接入网关**：统一 OpenAI 兼容接口，可平滑切换不同云端模型供应商；
6. **uv 工程化依赖管理**：`pyproject.toml + uv.lock` 保证环境一致性；
7. **敏感数据脱敏 + 全量 AI 审计留痕的合规设计**。
