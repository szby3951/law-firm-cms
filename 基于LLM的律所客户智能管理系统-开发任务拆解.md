# 基于LLM的律所客户智能管理系统设计与实现 — 开发任务拆解文档

> 本文档基于《基于LLM的律所客户智能管理系统-架构设计与功能需求-v2.md》拆解，作为开发执行清单。
> 技术栈：FastAPI + SQLAlchemy 2.0(async) + MySQL 8 + Qdrant + Vue 3 + Element Plus + uv
> 约定：每个模块按「后端 → 前端 → 联调 → 验收」四阶段推进，先跑通再优化。

---

## 〇、开发总顺序（依赖关系）

```
阶段0 项目初始化
  │
  ▼
模块1 认证与权限  ←—— 所有模块的前置依赖
  │
  ├─► 模块2 客户关系管理
  │      │
  │      ▼
  │    模块3 案件管理 ←—— 业务核心
  │      │
  │      ├─► 模块4 合同管理
  │      ├─► 模块5 收费管理
  │      ├─► 模块6 日程与通知
  │      ├─► 模块7 文书管理
  │      ├─► 模块8 沟通留言
  │      └─► 模块10 统计报表
  │
  ├─► 模块9 AI法律助手（依赖Qdrant+知识库，可与业务模块并行开发）
  │
  └─► 模块11 系统设置（最后，依赖字典数据）
```

---

## 阶段0：项目初始化

### 0.1 后端工程初始化

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 0.1.1 | 安装 Python 3.11+ 与 uv | 本机环境 | `uv --version` 可执行 |
| 0.1.2 | 创建 `backend/` 目录，执行 `uv init` | `backend/pyproject.toml` | 文件生成 |
| 0.1.3 | 按架构文档写入依赖并 `uv add`：fastapi、uvicorn[standard]、sqlalchemy[asyncio]、aiomysql、pydantic、pydantic-settings、python-jose[cryptography]、passlib[bcrypt]、python-multipart、apscheduler、httpx、qdrant-client、openpyxl、python-docx | `uv.lock` 锁定全量依赖 | `uv sync` 成功，无报错 |
| 0.1.4 | 新建目录骨架：`app/{models,schemas,routers,services,ai,core}`、`scripts/`、`tests/` | 目录结构 | 与架构文档第八章一致 |
| 0.1.5 | 创建 `.env`：DATABASE_URL、JWT_SECRET、QDRANT_URL、LLM_PROVIDER/LLM_MODEL/BASE_URL/API_KEY | 配置文件 | 不提交到 git，.gitignore 忽略 |
| 0.1.6 | 编写 `app/config.py`（pydantic-settings 读取 .env） | 配置类 | 启动时可读取全部配置项 |
| 0.1.7 | 编写 `app/database.py`：async engine + session + Base | 数据库连接层 | 连接 MySQL 测试库成功 |
| 0.1.8 | 编写 `app/main.py`：FastAPI 实例、CORS、路由注册、健康检查 `/health` | 应用入口 | `uv run uvicorn app.main:app --reload` 启动，访问 /health 返回 200 |

### 0.2 前端工程初始化

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 0.2.1 | 安装 Node.js 18+，创建 `frontend/`，执行 `npm create vite@latest . -- --template vue` | Vue3+Vite 工程 | `npm run dev` 可启动 |
| 0.2.2 | 安装依赖：vue-router、pinia、axios、element-plus、echarts、vue-echarts | package.json | 依赖安装成功 |
| 0.2.3 | 搭建目录骨架：`src/{api,router,stores,layouts,views,components,utils}` | 目录结构 | 与架构文档第九章一致 |
| 0.2.4 | 编写 `src/api/request.js`：axios 实例、baseURL、请求/响应拦截器（携带 Token、401 跳登录） | 请求封装 | 拦截器逻辑完整 |
| 0.2.5 | 配置 `vite.config.js`：代理 `/api → http://localhost:8000` | 代理配置 | 前端请求可到达后端 |

### 0.3 基础设施准备

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 0.3.1 | Docker 启动 MySQL 8（utf8mb4），创建数据库 `law_firm` | 业务库 | `mysql -u root -p` 可连接 |
| 0.3.2 | Docker 启动 Qdrant（端口 6333） | 向量库 | 访问 `http://localhost:6333/dashboard` 可打开 |
| 0.3.3 | 申请云端大模型 API Key（OpenAI 兼容接口，如 DeepSeek、通义千问等） | 云端 LLM 配置 | API Key 可正常调用、额度充足 |

---

## 模块1：认证与权限模块

> 所有模块的前置，必须最先完成。

### 1.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 1.1.1 | 建表 `user`：id、username(unique)、password_hash、real_name、role('client'/'lawyer'/'admin')、phone、email、avatar、status、created_at、updated_at | models/user.py | 表结构符合架构文档 7.2 |
| 1.1.2 | 建表 `operation_log`：id、user_id、action、target、ip、created_at | models/log.py | 表结构完整 |
| 1.1.3 | 编写 schemas：RegisterIn/LoginIn/TokenOut/UserOut | schemas/auth.py | Pydantic 校验字段完整 |
| 1.1.4 | 编写 `core/security.py`：bcrypt 密码哈希、JWT 生成/校验（含 role、exp） | 安全工具 | 单元测试：哈希可校验、Token 可解析 |
| 1.1.5 | 编写 `services/auth_service.py`：register（客户端注册）、login、获取当前用户 | 业务逻辑 | 注册后密码为哈希存储 |
| 1.1.6 | 编写 `dependencies.py`：`get_db`、`get_current_user`（解析JWT）、`require_role(*roles)` 依赖注入 | 权限依赖 | 无 Token 访问受保护接口返回 401 |
| 1.1.7 | 编写 `routers/auth.py`：POST /api/auth/register、POST /api/auth/login、GET /api/auth/me | 路由 | 登录返回 token + user 信息 |
| 1.1.8 | 编写登录/敏感操作写 `operation_log` 的公共方法 | 审计记录 | 登录行为落库 |

### 1.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 1.2.1 | 编写 `stores/user.js`：token、userInfo、role、登录/登出/获取用户信息 action | Pinia store | 状态持久化到 localStorage |
| 1.2.2 | 编写 `views/auth/Login.vue`、`Register.vue` | 登录/注册页 | 可调用后端接口完成登录/注册 |
| 1.2.3 | 编写 `router/index.js`：路由表 + 全局守卫（未登录跳登录、按 role 重定向到对应端） | 路由守卫 | 三种角色登录后进入不同首页 |
| 1.2.4 | 编写三个布局 `layouts/ClientLayout.vue`、`LawyerLayout.vue`、`AdminLayout.vue`（侧边菜单+顶栏+内容区） | 布局组件 | 菜单按角色显示 |

### 1.3 联调与验收

| 步骤 | 操作 | 验收标准 |
|---|---|---|
| 1.3.1 | 联调注册→登录→获取用户信息全流程 | 前后端联通，Token 正常携带 |
| 1.3.2 | 用 curl/Postman 测试：无 Token 返回 401、错误密码返回 4xx | 权限校验生效 |
| 1.3.3 | 创建三个测试账号（client/lawyer/admin） | 三端登录均正常 |

---

## 模块2：客户关系管理模块

### 2.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 2.1.1 | 建表 `client_profile`：id、user_id(FK)、client_type、id_no、gender、address、source_channel、level、status、lawyer_id(FK)、remark、created_at | models/client.py | 表结构符合架构文档 7.2 |
| 2.1.2 | 建表 `follow_record`：id、client_id(FK)、user_id(FK)、content、method、next_follow_date、created_at | models/follow.py | 表结构完整 |
| 2.1.3 | 编写 schemas：ClientCreate/ClientUpdate/ClientOut/FollowCreate/FollowOut | schemas/client.py | 字段校验完整 |
| 2.1.4 | 编写 `services/client_service.py`：分页查询（多条件：keyword/status/level/source）、新增、修改、删除（软删或校验关联）、跟进记录增查 | 业务逻辑 | 查询按 role 过滤：律师只能查自己负责的；管理员查全部 |
| 2.1.5 | 编写 `routers/clients.py`：GET /api/clients（分页）、POST /api/clients、PUT /api/clients/{id}、DELETE /api/clients/{id}、POST /api/clients/{id}/follows、GET /api/clients/{id}/follows | 路由 | 权限：新增/修改仅 lawyer/admin；删除仅 admin |
| 2.1.6 | 身份证号脱敏工具：展示时中间打码（如 110***********1234） | core/utils.py | 接口返回已脱敏 |
| 2.1.7 | Excel 导出：GET /api/clients/export（openpyxl 生成 xlsx） | 导出接口 | 导出文件可打开，字段正确 |

### 2.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 2.2.1 | `views/lawyer/ClientList.vue`：列表页（筛选条件、分页、标签、导出按钮） | 客户列表 | 筛选/分页正常 |
| 2.2.2 | `views/lawyer/ClientDetail.vue`：详情页（基本信息、跟进时间线、关联案件列表） | 客户详情 | 跟进记录按时间倒序展示 |
| 2.2.3 | 跟进记录弹窗组件（方式、内容、下次跟进日期） | FollowDialog.vue | 新增跟进后列表刷新 |
| 2.2.4 | 客户新增/编辑表单（含来源渠道、标签、状态） | ClientForm.vue | 校验必填字段 |

### 2.3 验收

| 步骤 | 验收标准 |
|---|---|
| 2.3.1 | 律师登录只能看到自己负责的客户列表 |
| 2.3.2 | 管理员能看到全部客户，可导出 Excel |
| 2.3.3 | 新增客户→添加跟进记录→待跟进列表排序 全流程跑通 |

---

## 模块3：案件管理模块（业务核心）

### 3.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 3.1.1 | 建表 `case`：id、case_no(unique)、client_id(FK)、title、case_cause、case_type、court、opposing_party、amount、status、description、created_at、closed_at | models/case.py | 状态枚举：consulting/filed/handling/pending_close/closed/withdrawn |
| 3.1.2 | 建表 `case_lawyer`：case_id(FK)、lawyer_id(FK)、duty('lead'/'assist') | models/case_lawyer.py | 多对多关联 |
| 3.1.3 | 建表 `case_event`：id、case_id(FK)、event_type、event_date、description、created_by | models/case_event.py | 事件类型：filing/accept/hearing/evidence/judgment/other |
| 3.1.4 | 编写 schemas：CaseCreate/CaseUpdate/CaseOut/CaseAssignIn/CaseEventIn | schemas/case.py | 字段完整 |
| 3.1.5 | 编写 `services/case_service.py`：立案（生成案号+创建事件）、分案（主办/协办）、状态流转（校验状态机合法性）、事件登记、案件列表（按角色过滤：律师看主办+协办；客户通过 client_id 关联查询）、案件详情（含时间线、关联档案） | 业务逻辑 | 状态机非法流转被拒绝 |
| 3.1.6 | 编写 `routers/cases.py`：GET /api/cases（律师/管理员）、POST /api/cases（律师立案）、POST /api/cases/{id}/assign（管理员分案）、PATCH /api/cases/{id}/status、POST /api/cases/{id}/events、GET /api/cases/{id} | 路由 | 权限校验完整 |
| 3.1.7 | 客户端接口：GET /api/my/cases（当前登录客户自己的案件列表+进度） | 客户端接口 | 客户只能看到本人案件 |
| 3.1.8 | 案件文件上传：POST /api/cases/{id}/files（上传证据/文书到本地磁盘） | 文件接口 | 文件落盘、返回 URL |

### 3.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 3.2.1 | `views/lawyer/CaseList.vue`：案件列表（按状态/案由/律师筛选，状态标签） | 案件列表 | 筛选分页正常 |
| 3.2.2 | `views/lawyer/CaseDetail.vue`：详情页（基本信息、时间轴组件、案件律师、关联档案 tab） | 案件详情 | 时间轴按事件时间展示 |
| 3.2.3 | 立案表单（含案由、法院、对方当事人、标的额） | CaseForm.vue | 立案成功自动生成案号 |
| 3.2.4 | 状态流转操作（下拉选择+确认，校验合法流转） | 状态操作组件 | 非法流转前端即提示 |
| 3.2.5 | 分案弹窗（选择主办/协办律师） | AssignDialog.vue | 仅管理员可见 |
| 3.2.6 | 时间轴组件 Timeline 组件 | CaseTimeline.vue | 事件节点可视化 |
| 3.2.7 | 客户端 `views/client/MyCases.vue`：我的案件列表+详情（进度、开庭日期、时间线） | 客户端页面 | 客户仅见本人案件 |

### 3.3 验收

| 步骤 | 验收标准 |
|---|---|
| 3.3.1 | 立案→分案→登记开庭事件→状态流转→结案 全生命周期跑通 |
| 3.3.2 | 律师 A 看不到律师 B 的案件；客户只能看到自己的案件 |
| 3.3.3 | 管理员可对任意案件分案、调案 |

---

## 模块4：合同管理模块

### 4.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 4.1.1 | 建表 `contract`：id、case_id(FK)、client_id(FK)、name、contract_type、amount、start_date、end_date、status、file_url、ai_review_report(JSON)、created_at | models/contract.py | 状态枚举：draft/active/expired/terminated |
| 4.1.2 | 编写 schemas：ContractCreate/ContractOut/ContractReviewOut | schemas/contract.py | 字段完整 |
| 4.1.3 | 编写 `services/contract_service.py`：台账 CRUD、上传文件、到期扫描（查询 end_date 在 N 天内）、AI 审查报告存储 | 业务逻辑 | 到期合同列表可查 |
| 4.1.4 | 编写 `routers/contracts.py`：GET/POST /api/contracts、GET /api/contracts/{id}、PUT /api/contracts/{id}、POST /api/contracts/{id}/upload、GET /api/contracts/expiring | 路由 | 权限：律师管理本人案件合同，客户只读 |
| 4.1.5 | 客户端接口：GET /api/my/contracts（客户查看/下载本人合同） | 客户端接口 | 仅返回本人关联合同 |

### 4.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 4.2.1 | `views/lawyer/ContractList.vue`：合同台账列表（筛选、到期预警标识） | 合同列表 | 到期合同高亮 |
| 4.2.2 | `views/lawyer/ContractDetail.vue`：详情（基本信息、文件预览、AI 审查报告展示） | 合同详情 | 审查报告渲染 |
| 4.2.3 | 合同上传/编辑表单 | ContractForm.vue | 支持文件上传 |
| 4.2.4 | 客户端 `views/client/MyContracts.vue`：我的合同列表+下载 | 客户端页面 | 可下载 PDF |

### 4.3 验收

| 步骤 | 验收标准 |
|---|---|
| 4.3.1 | 上传合同→登记台账→到期预警 流程跑通 |
| 4.3.2 | 客户端可查看并下载本人签署的合同 |
| 4.3.3 | 合同数据按角色隔离（律师本人案件、客户本人） |

---

## 模块5：收费管理模块

### 5.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 5.1.1 | 建表 `fee_plan`：id、case_id(FK)、fee_type、total_amount、description | models/billing.py | fee_type：fixed/ratio/risk/hourly |
| 5.1.2 | 建表 `fee_period`：id、fee_plan_id(FK)、period_no、due_amount、due_date、status | models/billing.py | 状态：unpaid/partial/paid |
| 5.1.3 | 建表 `payment`：id、fee_period_id(FK)、amount、pay_method、receipt_no、paid_at、created_by | models/billing.py | 支持部分收款 |
| 5.1.4 | 编写 schemas：FeePlanIn/FeePeriodIn/PaymentIn/BillOut | schemas/billing.py | 字段完整 |
| 5.1.5 | 编写 `services/billing_service.py`：收费方案创建、期次生成、收款登记（自动更新期次状态：部分/结清）、催收清单（已到期未结清）、统计（月度营收、回款率） | 业务逻辑 | 部分收款自动联动状态 |
| 5.1.6 | 编写 `routers/billing.py`：POST /api/billing/plans、POST /api/billing/periods/{id}/payments、GET /api/billing/collect-list、GET /api/billing/stats | 路由 | 权限：律师管理本人案件收费，管理员全所 |
| 5.1.7 | 客户端接口：GET /api/my/bills（客户查看本人账单：应收/已缴/发票状态） | 客户端接口 | 客户仅见本人账单 |
| 5.1.8 | 发票登记字段并入 payment（开票信息、发票号） | 发票字段 | 收款时可填发票号 |

### 5.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 5.2.1 | `views/lawyer/BillingList.vue`：收费列表（按案件/状态筛选） | 收费列表 | 筛选正常 |
| 5.2.2 | 收费方案创建表单（方式、金额、分期） | FeePlanForm.vue | 生成期次 |
| 5.2.3 | 收款登记弹窗（金额、方式、发票号） | PaymentDialog.vue | 部分收款后状态更新 |
| 5.2.4 | 催收清单页面 | CollectList.vue | 已到期未结清自动列出 |
| 5.2.5 | 客户端 `views/client/MyBills.vue`：我的账单列表 | 客户端页面 | 显示应收/已缴/状态 |

### 5.3 验收

| 步骤 | 验收标准 |
|---|---|
| 5.3.1 | 建收费方案→分期→部分收款→结清 全流程跑通 |
| 5.3.2 | 未结清到期账单出现在催收清单 |
| 5.3.3 | 客户可查看本人账单和缴费状态 |

---

## 模块6：日程与通知模块

### 6.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 6.1.1 | 建表 `schedule`：id、case_id(FK可空)、client_id(FK可空)、user_id(FK)、title、schedule_type、event_date、remind_at、status | models/schedule.py | 类型：hearing/deadline/visit/meeting；状态：pending/done/cancelled |
| 6.1.2 | 编写 schemas：ScheduleIn/ScheduleOut | schemas/schedule.py | 字段完整 |
| 6.1.3 | 编写 `services/schedule_service.py`：CRUD、按日期范围查询、日历数据、状态标记完成 | 业务逻辑 | 按 role 过滤 |
| 6.1.4 | 编写 `routers/schedule.py`：GET/POST/PUT/PATCH /api/schedule | 路由 | 权限完整 |
| 6.1.5 | 建表 `notification`（站内通知）：id、user_id、title、content、is_read、created_at、related_type、related_id | models/notification.py | 通知可标记已读 |
| 6.1.6 | 编写 `scheduler.py`：APScheduler 每天扫描（开庭提醒、缴费提醒、跟进到期提醒、合同到期预警），生成通知 | 定时任务 | 任务启动时注册，日志可见 |
| 6.1.7 | 客户端通知接口：GET /api/my/notifications（仅开庭/期限等对外通知） | 客户端接口 | 只推送与本人案件相关通知 |

### 6.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 6.2.1 | `views/lawyer/Schedule.vue`：日历视图（月/周/日切换，日程标记） | 日历页 | 日历组件渲染日程 |
| 6.2.2 | 日程新增/编辑弹窗（类型、时间、关联案件） | ScheduleForm.vue | 保存后日历刷新 |
| 6.2.3 | 首页待办卡片（今日开庭、待办事项） | 待办组件 | 数据来自通知/日程接口 |
| 6.2.4 | 通知中心组件（未读红点、列表、标记已读） | NotificationBell.vue | 未读计数正确 |
| 6.2.5 | 客户端通知页面 | views/client/Notifications.vue | 仅本人相关通知 |

### 6.3 验收

| 步骤 | 验收标准 |
|---|---|
| 6.3.1 | 创建开庭日程→定时任务生成提醒→首页待办显示 |
| 6.3.2 | 客户端收到开庭/期限通知，且看不到律所内部日程 |
| 6.3.3 | 通知可标记已读 |

---

## 模块7：文书管理模块

### 7.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 7.1.1 | 建表 `doc_template`：id、doc_type、name、content（含 {变量} 占位符） | models/document.py | 模板字段完整 |
| 7.1.2 | 建表 `document`：id、case_id(FK)、doc_type、title、content(LONGTEXT)、is_ai_generated、ai_session_id、file_url、created_by | models/document.py | 结构符合架构 7.2 |
| 7.1.3 | 编写 schemas：TemplateIn/DocumentIn/DocumentOut | schemas/document.py | 字段完整 |
| 7.1.4 | 编写 `services/doc_service.py`：模板 CRUD、文书 CRUD、变量填充（从案件字段取值替换 {客户姓名} {案由}）、docx 导出（python-docx） | 业务逻辑 | 变量替换正确 |
| 7.1.5 | 编写 `routers/documents.py`：GET/POST /api/documents、GET /api/documents/{id}、POST /api/documents/{id}/export、GET/POST /api/doc-templates | 路由 | 权限：律师本人案件文书可管理 |
| 7.1.6 | 客户端接口：GET /api/my/documents（查看/下载本人案件文书） | 客户端接口 | 客户仅见本人文书 |

### 7.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 7.2.1 | `views/lawyer/DocumentList.vue`：文书库列表（按类型筛选） | 文书列表 | 分类筛选正常 |
| 7.2.2 | 文书编辑页（富文本编辑器 wangEditor） | DocumentEditor.vue | 可编辑保存 |
| 7.2.3 | 模板管理页（模板列表、新建、编辑） | TemplateManage.vue | 模板 CRUD 正常 |
| 7.2.4 | 一键生成草稿按钮（选择模板→自动填充案件字段） | 生成功能 | 填充正确 |
| 7.2.5 | 导出 docx 按钮 | 导出功能 | 下载文件可打开 |
| 7.2.6 | 客户端 `views/client/MyDocuments.vue`：我的文书列表+下载 | 客户端页面 | 可下载 |

### 7.3 验收

| 步骤 | 验收标准 |
|---|---|
| 7.3.1 | 模板→选择案件→自动填充→在线编辑→导出 docx 全流程跑通 |
| 7.3.2 | 客户可查看下载本人案件文书 |
| 7.3.3 | 文书按案件归档，律师仅本人案件可见 |

---

## 模块8：沟通留言模块

### 8.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 8.1.1 | 建表 `message`：id、case_id(FK可空)、client_id(FK)、lawyer_id(FK)、sender_role('client'/'lawyer')、content、attachment_url、is_read、created_at | models/message.py | 会话维度可查 |
| 8.1.2 | 编写 schemas：MessageCreate/MessageOut | schemas/message.py | 字段完整 |
| 8.1.3 | 编写 `services/message_service.py`：发送留言（客户→律师 / 律师→客户）、按客户查询会话列表、标记已读、附件上传 | 业务逻辑 | 未读计数正确 |
| 8.1.4 | 编写 `routers/messages.py`：POST /api/messages、GET /api/messages?client_id=、PATCH /api/messages/{id}/read、POST /api/messages/{id}/attachment | 路由 | 权限：客户只能和自己律师沟通 |
| 8.1.5 | 客户端接口：GET /api/my/messages（客户查看与律师的沟通记录） | 客户端接口 | 双向记录可见 |

### 8.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 8.2.1 | `views/lawyer/Messages.vue`：客户留言列表（未读标记、回复框、附件上传） | 律师端留言页 | 回复后客户可见 |
| 8.2.2 | `views/client/Messages.vue`：与律师的聊天窗口（发送留言、上传材料、查看回复） | 客户端留言页 | 消息列表刷新 |
| 8.2.3 | 客户详情页内嵌留言入口 | 入口集成 | 从客户详情可进入沟通 |

### 8.3 验收

| 步骤 | 验收标准 |
|---|---|
| 8.3.1 | 客户留言→律师回复→客户查看 双向闭环跑通 |
| 8.3.2 | 附件（图片/PDF）上传成功并可在对话中查看 |
| 8.3.3 | 未读/已读状态正确 |

---

## 模块9：AI 法律助手模块（系统亮点）

> 依赖：Qdrant 已启动、法律知识库已构建。可与模块2~8并行开发。

### 9.1 知识库构建（RAG 基础）

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.1.1 | 建表 `law_article`：id、law_name、chapter、article_no、content、effective_status、vector_id | models/law_article.py | 表结构符合架构 7.2 |
| 9.1.2 | 收集《民法典》《刑法》《民事诉讼法》《公司法》常用条文文本（脚本 scripts/kb_builder.py 批量导入） | 条文数据 | 约500~2000条入库 |
| 9.1.3 | 按「条」切分，每条 200~500 字，带元数据（法律名、章节、条号） | 切分逻辑 | 切分结果完整 |
| 9.1.4 | 调用 Embedding 模型向量化，写入 Qdrant（collection: law_kb，payload 存元数据） | 向量入库 | 查询相似条文返回 top-k |
| 9.1.5 | 建 `doc_template` 中 FAQ 类模板，管理员可上传律所知识（历史案件摘要、FAQ）入知识库 | 律所知识库 | 上传后可供检索 |

### 9.2 AIGateway 模型接入层

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.2.1 | 编写 `ai/gateway.py`：`AIGateway` 类（async chat 流式、embed、generate_json 三个方法） | 统一接口 | 接口签名完整 |
| 9.2.2 | 编写 `ai/llm_clients/openai_client.py`：OpenAI 兼容 API 调用（httpx 流式） | 在线客户端 | 流式输出正常 |
| 9.2.3 | （预留扩展）`llm_clients/` 目录支持后续新增供应商客户端，当前统一走 OpenAI 兼容 API | 可扩展层 | 当前无需实现本地客户端 |
| 9.2.4 | 配置化接入：读 .env 的 LLM_BASE_URL/API_KEY/MODEL；超时/重试/降级（失败返回友好提示） | 接入逻辑 | 修改配置无需改代码 |

### 9.3 RAG 问答

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.3.1 | 编写 `ai/rag.py`：query 向量化→Qdrant 检索 top-k（5~8）→上下文拼装 | 检索器 | 检索结果相关 |
| 9.3.2 | 编写 `ai/prompts.py`：系统提示词（"你是XX律所法律顾问，仅基于以下材料回答，材料不足时明确告知，不得编造"）+ 问答模板 + 引用标注要求 | Prompt 模板 | 提示词完整 |
| 9.3.3 | 编写 `services/ai_service.py`：chat 流程（检索→prompt→LLM 流式→回答解析引用 [n]→落库） | 问答服务 | 回答含法条引用标注 |
| 9.3.4 | 建表 `ai_session`、`ai_message`：会话与消息记录（含 refs JSON、token_usage） | models/ai.py | 落库完整 |
| 9.3.5 | 会话管理：创建/续接会话、历史查询 | 会话服务 | 多轮上下文可续接 |
| 9.3.6 | 编写 `routers/ai.py`：POST /api/ai/chat（SSE 流式返回） | 问答路由 | 前端可流式接收 |
| 9.3.7 | 敏感信息脱敏：送入 LLM 前对姓名/身份证/电话打码 | 脱敏工具 | 日志与请求中无明文 |

### 9.4 智能文书生成

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.4.1 | 编写文书生成 Prompt：文书类型 + 法律格式规范 + 案件事实 + 当事人信息（结构化） | Prompt | 模板完整 |
| 9.4.2 | 编写 `services/ai_service.py` 的 generate_document 方法：选类型→带案件字段→LLM 流式生成→返回初稿 | 生成逻辑 | 初稿字段填充正确 |
| 9.4.3 | 路由：POST /api/ai/generate-document（SSE） | 路由 | 前端可流式接收 |
| 9.4.4 | 生成结果一键存入 document 表（is_ai_generated=true） | 归档逻辑 | 文书可归档到案件 |

### 9.5 合同风险审查

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.5.1 | 长文处理：合同文本按章节切分→分块抽取（主体/金额/期限/违约/解除/管辖） | 分块逻辑 | 超长合同可处理 |
| 9.5.2 | 风险审查 Prompt：对照风险清单（违约金>30%? 缺管辖? 无限连带责任? 自动续约?） | Prompt | 风险点覆盖 |
| 9.5.3 | 结构化输出：LLM 输出 JSON `[{风险条款, 原文定位, 风险等级, 修改建议}]`，解析容错 | JSON 解析 | 解析失败有兜底 |
| 9.5.4 | 路由：POST /api/ai/review-contract/{id}，结果写回 contract.ai_review_report | 路由 | 报告可保存 |
| 9.5.5 | 前端审查报告渲染（风险列表+原文定位+等级标签） | 报告组件 | 报告展示完整 |

### 9.6 案件摘要（可选加分项）

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.6.1 | 编写摘要 Prompt：案件描述/材料→要点总结 | Prompt | 模板完整 |
| 9.6.2 | 路由：POST /api/ai/case-summary/{case_id}（SSE） | 路由 | 流式返回摘要 |

### 9.7 客户画像（LLM×客户管理强关联亮点）

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.7.1 | `client_profile` 表加 `ai_profile`(JSON)、`ai_profile_at`(DATETIME) 字段，model 同步 | 表结构 | 迁移成功 |
| 9.7.2 | 编写 `services/ai_service.py` 的 generate_client_profile 方法：聚合客户基本信息+跟进记录+关联案件+合同+沟通记录→拼装结构化文本 | 数据聚合 | 数据完整无遗漏 |
| 9.7.3 | 编写客户画像 Prompt（见下方模板）：要求输出 JSON（客户类型/核心诉求/风险点/沟通偏好/跟进建议） | Prompt | 输出结构稳定，可解析 |
| 9.7.4 | 敏感字段脱敏后送入 LLM（身份证/电话打码） | 脱敏工具复用 | 日志无明文 |
| 9.7.5 | 路由：POST /api/clients/{id}/ai-profile（生成/刷新）、GET /api/clients/{id}/ai-profile（读取） | 路由 | 权限：仅负责律师/管理员 |

客户画像 Prompt 模板（可直接使用）：

```text
你是律师事务所的资深客户经理。请基于以下客户数据生成客户画像，严格只输出 JSON，不要多余文字：
{"客户类型": "", "核心诉求": "", "风险点": [], "沟通偏好": "", "下一步跟进建议": ""}

客户基本信息：{姓名/类型/来源渠道/状态/分级}
跟进记录：{最近3条跟进内容与时间}
关联案件：{案件名称/案由/状态}
沟通记录：{最近沟通摘要}
收费情况：{收费方案/回款状态}

要求：1. 严格输出 JSON；2. 风险点最多 3 条；3. 跟进建议具体可执行，结合客户状态。
```

### 9.8 前端 AI 交互

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 9.7.1 | AI 聊天窗组件：SSE 流式渲染（fetch + ReadableStream）、Markdown 渲染、引用 [n] 锚点 | AiChatWindow.vue | 流式逐字显示 |
| 9.7.2 | 法条引用弹层（点击 [n] 展示法条原文） | LawRefDialog.vue | 弹层正确 |
| 9.7.3 | 全局悬浮窗入口（右下角，任意业务页可唤起） | 悬浮窗 | 全局可用 |
| 9.8.4 | 案件/合同页内快捷按钮（AI摘要、AI审查） | 快捷按钮 | 跳转/唤起正确 |
| 9.8.5 | 客户详情页"AI客户画像"卡片（生成按钮+画像展示+刷新） | ClientProfileCard.vue | 画像展示完整，可刷新 |
| 9.8.6 | 客户端 AI 问答页（受限：仅基础问答+免责声明） | views/client/AiAssistant.vue | 无专业功能入口 |

### 9.9 合规与安全（贯穿）

| 步骤 | 验收标准 |
|---|---|
| 9.9.1 | AI 回答自动附加"本内容仅供参考，不构成法律意见" |
| 9.9.2 | 送 LLM 前敏感字段脱敏，日志无明文 |
| 9.9.3 | 所有 AI 会话/消息落库可审计 |
| 9.9.4 | 模型服务不可用时主系统不受影响（降级提示） |

### 9.10 验收

| 步骤 | 验收标准 |
|---|---|
| 9.10.1 | 问"违约金过高如何调整"→流式回答+法条引用 [1][2]→点击展开原文 |
| 9.10.2 | 选案件→一键生成起诉状初稿→修改→归档→导出 docx |
| 9.10.3 | 上传合同→生成风险审查报告（JSON 渲染） |
| 9.10.4 | 修改 .env 更换不同云端模型供应商→问答正常 |
| 9.10.5 | 律师端客户详情→生成客户画像→展示类型/诉求/风险/建议→刷新可更新 |

---

## 模块10：统计报表模块

### 10.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 10.1.1 | 编写 `services/stat_service.py`：收案趋势（月度/案由）、案件状态分布、律师办案量、创收排名、客户来源占比、回款率、合同到期数、待办日程数 | 统计逻辑 | 各指标 SQL 正确 |
| 10.1.2 | 编写 `routers/stats.py`：GET /api/stats/dashboard（管理员全所）、GET /api/stats/my（律师个人工作台） | 路由 | 按角色返回不同范围 |

### 10.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 10.2.1 | `views/admin/Dashboard.vue`：ECharts 大屏（折线收案趋势、饼图案由/来源、柱状律师创收、卡片指标） | 管理员大屏 | 图表渲染正确 |
| 10.2.2 | `views/lawyer/Workbench.vue`：个人工作台（待办开庭、待跟进客户、在办案件数、本月创收卡片） | 律师工作台 | 数据正确 |
| 10.2.3 | 首页卡片组件（指标卡片） | StatCards.vue | 复用 |

### 10.3 验收

| 步骤 | 验收标准 |
|---|---|
| 10.3.1 | 管理员大屏各图表数据与数据库一致 |
| 10.3.2 | 律师工作台只显示本人数据 |

---

## 模块11：系统设置模块

### 11.1 后端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 11.1.1 | 建表 `dict_item`：id、dict_type、label、sort | models/dict.py | 字典表结构 |
| 11.1.2 | 建表 `firm_info`（律所信息）：id、name、logo、address、phone、intro | models/setting.py | 单行配置 |
| 11.1.3 | 建表 `ai_config`：provider、base_url、api_key、model、temperature、status（存数据库，可页面配置） | models/setting.py | 配置项完整 |
| 11.1.4 | 编写 `services/setting_service.py`：字典 CRUD、律所信息读写、AI 配置读写 | 业务逻辑 | 读写正确 |
| 11.1.5 | 编写 `routers/settings.py`：/api/admin/dicts、/api/admin/firm、/api/admin/ai-config（仅 admin） | 路由 | 权限仅管理员 |
| 11.1.6 | 编写 `routers/admin.py`：律师账号管理（开通/禁用/重置密码）、客户注册审核、操作日志查询 | 管理路由 | 权限校验完整 |
| 11.1.7 | 初始化脚本：默认 admin 账号、字典数据（案由/合同类型/文书类型） | scripts/init_data.py | 首次启动自动建数据 |

### 11.2 前端

| 步骤 | 操作 | 产出 | 验收标准 |
|---|---|---|---|
| 11.2.1 | `views/admin/Settings.vue`：字典管理页、律所信息页、AI 配置页（模型选择/参数） | 设置页 | 保存生效 |
| 11.2.2 | `views/admin/UserManage.vue`：律师账号管理、客户审核 | 账号管理页 | 禁用后无法登录 |
| 11.2.3 | `views/admin/Logs.vue`：操作日志查询 | 日志页 | 分页查询正常 |

### 11.3 验收

| 步骤 | 验收标准 |
|---|---|
| 11.3.1 | 管理员新增字典项→下拉列表同步更新 |
| 11.3.2 | 修改 AI 配置（模型/API Key）→AI 模块生效 |
| 11.3.3 | 禁用律师账号→该账号登录被拒 |

---

## 阶段N：集成测试与部署

### N.1 后端测试

| 步骤 | 操作 | 验收标准 |
|---|---|---|
| N.1.1 | 编写 pytest 用例：认证、权限隔离、案件状态机、收费联动（tests/ 目录） | 核心逻辑用例通过 |
| N.1.2 | 接口测试：各模块 CRUD、SSE 流式、文件上传 | 接口返回正确 |
| N.1.3 | 性能抽查：核心接口并发请求（如 /api/cases）响应时间合理 | 无明显卡顿 |

### N.2 前端测试与联调

| 步骤 | 操作 | 验收标准 |
|---|---|---|
| N.2.1 | 三端全流程走查（按架构文档"答辩演示脚本"逐条执行） | 演示脚本全通过 |
| N.2.2 | 权限越权测试：客户访问律师接口返回 403 | 权限拦截生效 |
| N.2.3 | 流式渲染、引用弹层、文件下载等交互验证 | 交互正常 |

### N.3 部署

| 步骤 | 操作 | 验收标准 |
|---|---|---|
| N.3.1 | 编写 backend Dockerfile + frontend Dockerfile + docker-compose.yml（MySQL+Qdrant+backend+frontend+nginx） | compose 文件 | 一键拉起 |
| N.3.2 | 配置 Nginx：静态资源 + /api 反向代理 | 反向代理 | 浏览器访问正常 |
| N.3.3 | 初始化数据脚本执行：默认账号、字典、法律条文 | 初始化 | 登录后数据齐全 |

---

## 附：模块依赖与里程碑

| 里程碑 | 包含模块 | 判定标准 |
|---|---|---|
| M1（第1~2周） | 阶段0 + 模块1 | 三端可登录、路由守卫生效 |
| M2（第3~4周） | 模块2 + 模块3 | 客户→立案→分案→时间线 跑通 |
| M3（第5周） | 模块4 + 模块5 | 合同台账、收费联动跑通 |
| M4（第6周） | 模块6 + 模块7 + 模块8 | 日程提醒、文书、留言跑通 |
| M5（第7~8周） | 模块9 | RAG 问答、文书生成、合同审查可用 |
| M6（第8~9周） | 模块10 + 模块11 | 大屏、设置、账号管理完成 |
| M7（第10周） | 阶段N | 测试通过、部署完成、演示脚本全通过 |
