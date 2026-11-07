# app/ai —— 模型接入层与 RAG（模块9 底座）

```
app/ai/
├── gateway.py              AIGateway：业务代码唯一入口（chat / generate_json / embed）
├── embedding.py            向量化客户端（云端 OpenAI 兼容 / 本地 TEI，9.1 已接入）
├── rag.py                  检索器：向量召回 → 归并分块 → 编号引用 → 上下文拼装（9.3.1）
├── prompts.py              提示词模板：系统提示、问答模板、引用要求、免责声明（9.3.2）
├── masking.py              敏感信息脱敏（9.3.7 / 9.7.4）
├── doc_prompts.py          七类文书的提纲、规则与必备字段（9.4）
├── doc_html.py             Markdown → HTML、富文本 → 纯文本（9.4 / 9.6）
├── contract_text.py        合同/附件文本抽取、条款切分与分批（9.5）
├── contract_prompts.py     14 项风险清单、报告规范化与规则预检（9.5）
├── case_prompts.py         案件摘要六节结构与事实/判断分离约束（9.6）
├── profile_prompts.py      客户画像八字段 JSON 与规范化（9.7）
└── llm_clients/            大模型客户端，按供应商可扩展（9.2）
    ├── base.py             BaseLLMClient 抽象、LLMError、消息与 JSON 解析工具
    ├── openai_client.py    OpenAI 兼容协议实现（httpx + SSE 流式）
    └── __init__.py         供应商注册表与 create_client 工厂
```

业务侧（9.3 RAG、9.4 文书、9.5 审查、9.6 摘要、9.7 画像、9.8 前端接口）**只 import
`app.ai.gateway`**，不要直接用 httpx 调模型，也不要 import 具体客户端。

## 三个方法

```python
from app.ai.gateway import get_gateway

gw = get_gateway()

# 1) 流式对话：逐段 yield，直接喂给 FastAPI 的 StreamingResponse
async for piece in gw.chat("违约金过高可以调整吗", system="你是法律助手。", fallback=True):
    yield f"data: {piece}\n\n"

# 2) 结构化输出：返回 dict，内部已处理代码块围栏、前后解释文字
data = await gw.generate_json(prompt, schema_hint='{"level": "high|mid|low"}')

# 3) 向量化：走 EMBEDDING_PROVIDER 配置的后端，和 9.1 入库用同一模型
vec = await gw.embed_query("违约金过高如何调整")
```

`fallback` 只在**首个 token 之前**失败时生效：

| 值 | 行为 |
|---|---|
| `None` / `False` | 抛 `LLMError`，由 `main.py` 转成 503 |
| `True` | 输出 `exc.friendly`（区分「未配置」「鉴权失败」「暂时不可用」） |
| 字符串 | 输出自定义文案 |

已经吐过部分内容后再失败一律抛异常——半句话不能被当成完整答案。

## 换供应商

只改 `.env`，不动代码：

```ini
LLM_PROVIDER=deepseek                       # deepseek / qwen / moonshot / zhipu / ollama ...
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1    # 必须指向 /v1 这一层
LLM_API_KEY=sk-xxx
LLM_MAX_TOKENS=2048
LLM_TIMEOUT=60
LLM_MAX_RETRIES=2
```

当前实际使用的是阿里云百炼（DashScope 兼容模式）：

```ini
LLM_PROVIDER=qwen
LLM_MODEL=qwen3.8-max
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxx
LLM_ENABLE_THINKING=off
```

只要对方提供 `POST {base_url}/chat/completions`，就在 `llm_clients/__init__.py` 的
`ALIASES` 里加个名字即可。若遇到私有协议，新建 `xxx_client.py` 继承
`BaseLLMClient`、实现 `stream_chat` 与 `health`，打上 `register_client("xxx")` 装饰器，
再在 `llm_clients/__init__.py` 里 import 一次就会自动被发现。

### 思维链开关（`LLM_ENABLE_THINKING`）

qwen3 系列等「混合思考」模型默认会先输出一段思维链（SSE 里叫
`reasoning_content`），然后才给正文。本项目只转发 `delta.content`，思维链不会
进前端、也不会入库，但它**照样消耗 `max_tokens`**，并把首字延迟拉高：

| `qwen3.8-max` 一句话提问 | 首字 | 思维链 |
|---|---|---|
| 默认（思考开） | 3.1s | 159 字 |
| `LLM_ENABLE_THINKING=off` | 1.1s | 0 |

因此 `.env` 里固定 `off`。三个取值：`auto`（不下发该字段，用供应商默认）、
`on`、`off`；写 `true/false` 也能识别。**换成 DeepSeek 之类不认这个字段的
供应商时要改回 `auto`**，否则上游直接 400。


## 失败与降级（9.9.4）

| 场景 | 处理 |
|---|---|
| 未配置 `LLM_API_KEY` | 立刻抛 `LLMError`，文案「AI 服务尚未配置，请联系管理员」 |
| 401 / 403 | 不重试，文案「AI 服务鉴权失败，请联系管理员」 |
| 404 | 提示检查 `LLM_BASE_URL` 是否以 `/v1` 结尾 |
| 429 / 5xx / 连接失败 / 首字节前超时 | 指数退避重试（1s、2s），仍失败则「AI 服务暂时不可用，请稍后重试」 |
| 流中途断开 | 不重试（避免重复文本），前端标记「生成中断」 |
| 上游不支持 `response_format` | 自动退回提示词约束，JSON 仍能解析 |

接口层不需要逐个 try/except：`main.py` 已注册 `LLMError` → 503 的全局处理器，
响应体只给 `{"detail": "AI 服务暂时不可用，请稍后重试"}`，诊断信息写日志。

## 自测

```bash
cd backend

# 当前配置 / 探活（探活不花 token）
.venv/Scripts/python.exe scripts/ai_smoke.py --config --health

# 真实调用（需先配好 Key）
.venv/Scripts/python.exe scripts/ai_smoke.py --all

# 无 Key / 无外网时的离线验证：本地 mock 兼容服务
.venv/Scripts/python.exe scripts/mock_llm_server.py
LLM_BASE_URL=http://127.0.0.1:8099/v1 LLM_API_KEY=test-key \
  .venv/Scripts/python.exe scripts/ai_smoke.py --all
```

mock 支持模拟故障：`MOCK_FAIL_ONCE=2`（前两次 500）、`MOCK_STATUS=401`、
`MOCK_DELAY_MS=3000`（慢响应）、`MOCK_REJECT_JSON_FORMAT=1`（不支持 json_object）。

## 注意

- `LLM_API_KEY` 为空时，AI 相关接口一律降级，但**主系统其他页面不受影响**；
- 管理端展示配置请用 `gateway.describe()`，它不会返回 Key；
- 送模型前必须脱敏（9.3.7 / 9.9.2），脱敏属于业务层职责，不要在网关里做隐式改写，
  否则排查问题时看不到真实输入。

---

# RAG 问答（9.3）

## 一次问答的链路

```
POST /api/ai/chat
      │
      ├─ prepare_chat   校验会话归属 → 脱敏 → 用户消息落库
      │
      └─ stream_reply   meta → stage(检索) → refs → stage(生成) → delta… → done
                             │                    │
                             │                    └─ LLM 流式，每 400 字提交一次
                             └─ rag.retrieve：embed_query → Qdrant top-k → 归并分块
```

`refs` 里的编号就是提示词里的编号，`done.used_refs` 是模型实际引用的编号——
前端点 ``[n]`` 直接取 ``refs[n-1]`` 展示原文，不需要再查库。

## SSE 事件

| event | 数据 | 说明 |
|---|---|---|
| `meta` | `session_id / model / masked / mask_hits / disclaimer` | 第一个事件，前端立刻拿到会话 ID |
| `stage` | `stage / message` | `retrieving` / `generating`，用于显示进度 |
| `warning` | `detail` | 检索为空或向量服务不可用，**不致命** |
| `refs` | `items[]` | 引用列表（含原文快照） |
| `delta` | `text` | 正文增量 |
| `done` | `message_id / refs / used_refs / token_usage / elapsed_ms` | 正常结束 |
| `error` | `detail / retryable` | **回答不完整**，前端应标记「生成中断」 |

POST 带 `Authorization` 头，前端用 `fetch` + `ReadableStream` 读，不能用 `EventSource`。

## 为什么这样设计

| 决定 | 原因 |
|---|---|
| 用户消息先落库，助手消息在首个 token 时建行 | 模型挂掉不留空回答；等待首 token 时不占数据库连接 |
| 每 400 字提交一次 | 用户关页面会取消生成器，分批提交保证断流也有审计记录 |
| 历史消息剥掉旧 `[n]` | 旧编号带进新提示词会让模型把上一轮编号当本轮，引用指错条文 |
| 同一条文的分块合并成一条引用 | 长条文会占满 top-k，正确答案被挤出去 |
| 检索失败不抛异常，只发 `warning` | 9.9.4：模型/向量服务挂掉不能拖垮主系统 |
| 未配置 Key 时先 `check_ready` 再检索 | 否则用户先看到"正在检索"再看到"未配置"，白等两秒 |
| 姓名只脱敏 2 个字 | 取 3~4 字会把"当事人张三欠钱"里的"欠钱"一起打码，把提问改坏 |

## 调参

```ini
FIRM_NAME=示例律师事务所   # 写进系统提示词
RAG_TOP_K=6               # 引用条数，设计文档要求 5~8
RAG_MIN_SCORE=0.35        # 相似度下限，低于此值不送进提示词
RAG_REF_MAX_CHARS=900     # 单条引用正文上限（分块合并后可能很长）
RAG_MAX_CONTEXT_CHARS=5200
AI_HISTORY_MESSAGES=6     # 多轮上下文条数
AI_HISTORY_MAX_CHARS=1200 # 单条历史截断
```

检索效果不理想时先调 `RAG_MIN_SCORE`：调高会让"资料不足"的回答变多，调低会让
模型引用到不相关的条文。**不要**在提示词里写"请务必引用"，检索为空时那会逼模型
编造编号。

## 脱敏（9.3.7）

| 字段 | 原文 | 送入模型 |
|---|---|---|
| 身份证 | 110101199003071234 | 110101********1234 |
| 手机号 | 13800138000 | 138****8000 |
| 银行卡 | 6222021234567890123 | 6222***********0123 |
| 邮箱 | zhangsan@example.com | z***@example.com |
| 姓名 | 当事人：张三 | 当事人：张* |

- 只改**送往模型与日志**的文本，库里存原文（律师回看历史要看得懂事实）；
- 姓名识别需要「称谓 + 常见姓氏」两道闸门，纯姓名（"张三欠钱不还"）识别不了，
  这是正则方案的边界，上线应叠加 NER。

## 自测

```bash
cd backend

# 检索 / 脱敏（不需要后端与 Key）
.venv/Scripts/python.exe scripts/rag_smoke.py --retrieve --mask

# 走真实 HTTP（先起 mock，再起一个指向 mock 的后端）
.venv/Scripts/python.exe scripts/mock_llm_server.py
LLM_BASE_URL=http://127.0.0.1:8099/v1 LLM_API_KEY=test-key \
  .venv/Scripts/python.exe -m uvicorn app.main:app --port 8010
.venv/Scripts/python.exe scripts/rag_smoke.py --chat --base http://127.0.0.1:8010/api
```

`rag_smoke.py --chat` 会断言：事件齐全、有引用、落库回答与流式一致、续接后 4 条消息、
越权 403/404、删除 204，最后自动清理测试会话。

# 智能文书生成（9.4）

## 链路

```
选类型 + 案件ID
   │
   ▼
prepare_document：案件/客户字段 → 缺项清单 → 拼提示词 → 建 ai_session(type=document)
   │
   ▼
stream_document：SSE 逐段输出 Markdown（每 400 字落一次库，断流也留痕）
   │
   ▼
done 事件带 content(Markdown) + html(富文本)
   │
   ▼
律师在编辑器里修改 → POST /api/ai/documents 归档进 document 表
```

**生成不直接入库**是这个模块最重要的取舍。模型初稿一定缺少律师才知道的信息
（被告身份证号、具体诉请金额），若生成即写入文书库，「我的文书」里会堆满
需要逐条删除的半成品。归档动作放在律师确认之后，与手工新建文书走同一个
`doc_service.create_document`，权限规则、客户带出、摘要生成全部复用。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/ai/document-types` | 7 类文书的必备字段、结构大纲与特殊要求 |
| POST | `/api/ai/generate-document` | 生成初稿，`text/event-stream` |
| POST | `/api/ai/documents` | 归档为 `document`（`is_ai_generated=true`） |

`generate-document` 入参：`doc_type`（必填）、`case_id`、`facts`、`requirements`、
`template_id`、`title`。`facts` 缺省取 `cases.description`，两者都为空直接 400——
没有事实的起诉状只是一堆占位符。

## SSE 事件

```
meta     {session_id, doc_type, doc_type_label, title, case_id, model, missing, disclaimer}
context  {fields, missing, title}     # 实际带入的字段，前端可做"信息核对"面板
warning  {detail}                     # 模板类型不符等非致命提示
stage    {stage, message}
delta    {text}
done     {session_id, message_id, title, content, html, missing, token_usage, elapsed_ms}
error    {detail, retryable}
```

`context` / `meta.missing` 是这个功能可用性的关键：律师一眼就能看到
「受理法院、被告身份证号没取到」，比在正文里翻 `【待补充：…】` 快得多。

## 提示词（doc_prompts.py）

与问答提示词的约束方向**相反**：问答越保守越好（没资料就说不知道），文书要求
把骨架填满，但必须满足三条硬约束：

1. **结构不能少**：每类文书有固定 `outline`（起诉状的 8 个章节来自《民诉法》
   第一百二十二条与立案实务），材料不足也要保留章节并写清缺什么；
2. **事实不能编**：姓名、证件号、金额、日期、案号只能来自案件数据，缺失写
   `【待补充：xxx】`；也**不得由姓名推测性别**（否则「林志强」会被写成
   「林志强先生」）；
3. **法条不能造**：法律全称 + 条号，不确定就概括表述，禁止编造司法解释编号。

`rules` 里放的是各类文书最容易出错的地方，例如授权委托书不能只写「全权代理」
（诉讼法上不产生特别授权效力），律师函的期限不能写「尽快」。

引用模板（`template_id`）时，模板正文作为【参考模板骨架】传入；模板里未替换的
`{变量}` 会被要求改写成占位符，不会原样留在文书里。

## 归档时的格式转换（doc_html.py）

模型输出 Markdown，而 `document.content` 存 HTML（前端 wangEditor 编辑、`docx_export`
按 `<p>/<h1>/<li>` 解析排版）。`to_html()` 只实现文书用得到的子集：标题、粗体、
有序/无序列表、引用、段落，并保证：

- 已转义 `<` `>` `&`，正文里的比较符号不会破坏结构；
- **幂等**：前端编辑器回传的 HTML 不会再被转一次（否则标签会被当文本转义）；
- 有序列表保留原编号——法律文书的「1. 2. 3.」是内容的一部分。

## 脱敏的例外

9.3 会把姓名/身份证/电话打码后再送模型，**9.4 不打码**。原因是文书本身就是
「写明张三、身份证 310101…、住址…」的东西，打码后生成的是无法使用的废稿。
这是明确的取舍：9.4 的 PII 出站风险高于问答，只能靠「仅律师可用 + 全量审计日志
+ 供应商不用于训练」来兜，不能靠脱敏。要对外演示时请用虚构案件数据。

## 自测

```bash
cd backend

# 格式转换（不需要后端与 Key）
.venv/Scripts/python.exe scripts/doc_smoke.py --format

# 全链路（需后端已启动且 Key 可用）
.venv/Scripts/python.exe scripts/doc_smoke.py --all --case-id 15
```

`doc_smoke.py` 断言：HTML 转换的 6 类标签与幂等性；文书类型接口；SSE 事件齐全、
起诉状 4 个必备章节、无多余开场白；归档后 `is_ai_generated=true` 且正文为 HTML；
客户账号 403、不存在案件 404、非本人在办案件 403、无事实 400、非法类型 422。
跑完自动删除测试文书、会话与临时案件。

# 合同风险审查（9.5）

## 链路

```
合同台账（已上传 docx/pdf/txt）        律师粘贴的正文
        │                                  │
        └──────────┬───────────────────────┘
                   ▼
extract_text：docx(段落+表格) / pdf(文字层) / txt
                   ▼
digest_contract：按「第X条」切条款 + 关键词定位要素 + 扫描空白项
                   ▼
split_batches：按 6000 字打包成 N 批（条号跨批不变）
                   ▼
每批 generate_json（风险清单 + 原文摘录约束）→ normalize_report
                   ▼
merge_risks：跨批去重 + 与规则预检合并 → assemble_report
                   ▼
写回 contract.ai_review_report / ai_review_at，同时落 ai_message 与审计日志
```

**为什么按条款切，不按字数切。** 「前述款项」「该条约定」指向的是同一条内的上文，
按固定字数硬切会把一条约定劈成两半，模型只能看到半句就下判断。按「第X条」切分后，
每批都是完整条款，条号在全文范围内连续，模型说「第 12 条」在任何批次里都指同一处。

**为什么还要规则预检。** 「有没有管辖条款」「有没有一堆空白没填」这类判断不需要模型：
关键词命中率比模型稳定，也更好向客户解释。两边结果并列展示，各标 `source`（`ai` /
`precheck`）；模型已经报过同一清单项时，预检那条自动去掉，避免重复刷屏。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/ai/review-contract/{id}` | `text/event-stream`，逐批回报进度并写回台账 |

请求体可省略（自动读已上传文件），也可传：

```json
{ "text": "粘贴的合同正文（可选）", "focus": "重点看违约金与管辖", "save": true }
```

`save=false` 只出报告不落库，用于「先看一眼」。

SSE 事件：

```
meta      {contract_id, name, type_label, char_count, clause_count, batches, source,
           truncated, model, provider, disclaimer}
precheck  {elements, missing, placeholders, placeholder_count}
stage     {stage: reviewing, batch, total, message}
progress  {batch, total, found, clause_range}
warning   {detail}            # 截断、某批失败，非致命
done      {report, saved, reviewed_at, session_id, token_usage, elapsed_ms}
error     {detail, retryable}
```

**全部批次失败才发 `error`，也才不写库。** 半份报告比没有报告更危险——律师会以为
已经查过了。单批失败只在 `notes` 与 `warning` 里注明「第 N 批未纳入」，其余批次照常。

## 报告结构

```json
{
  "version": 1,
  "summary": "共识别 8 处风险（高 3 / 中 3 / 低 2）。优先处理：……",
  "level": "high", "level_label": "高",
  "counts": {"high": 3, "mid": 3, "low": 2, "total": 8},
  "risks": [{
    "id": 1, "clause_no": 5, "clause_title": "第四条 违约责任",
    "quote": "每逾期一日，应按逾期金额的【 】%向乙方支付违约金",
    "risk": "违约金比例为空白，该条款无法执行……",
    "level": "high", "level_label": "高",
    "suggestion": "填入合理比例，建议不超过日万分之三并设置上限",
    "basis": "《中华人民共和国民法典》第五百八十五条",
    "check": "penalty", "check_label": "违约金比例",
    "located": true, "source": "ai"
  }],
  "missing": ["争议解决"],
  "notes": ["第 2 批审查失败：……"],
  "precheck": {"elements": {}, "missing_dimensions": [], "placeholder_count": 16, "placeholders": []},
  "contract": {"char_count": 1255, "clause_count": 8, "batches": 1, "source": "docx", "truncated": false},
  "model": "qwen3.8-max", "provider": "qwen", "reviewed_at": "2026-11-05T22:26:47",
  "token_usage": 1361, "disclaimer": "……"
}
```

`summary` 由统计生成而不是模型生成：数量、等级、优先级必须和 `risks` 完全对得上，
模型写的摘要偶尔会自己多数一条。

## JSON 解析容错（9.5.3）

`normalize_report` 兜住模型的各种自由发挥：

| 模型可能给的 | 处理 |
|---|---|
| 裸数组 `[{...}]` | 直接当作风险列表（设计文档 9.5.3 就是这个形状） |
| `{"risks": [...]}` / `{"风险点": [...]}` / `{"items": [...]}` | 按候选键名逐个尝试 |
| `"风险条款"` | 当作风险描述；条款位置由 `quote` 定位或从文字里的「第X条」反查 |
| `"风险等级": "高" / "HIGH" / "严重" / 3` | 归一成 `high`/`mid`/`low`，无法识别按 `mid` |
| ```json 围栏、前后夹带解释 | `extract_json` 用 `raw_decode` 逐个 `{` 尝试 |

**`quote` 必须能在合同里找到。** `ContractDigest.locate()` 先做规范化精确匹配，再退化为
前 10 字前缀匹配。两者都不中时**保留这条风险但标记 `located=false`**，前端显示「待核对」。
不隐藏是因为模型可能只是摘得不精确；不伪造成原文是因为那样律师会把它当成合同条款引用。

## 提示词（contract_prompts.py）

14 条风险清单，每条带判据与默认等级，覆盖：违约金比例、争议解决与管辖、责任范围与上限、
权利义务对等性、空白与不确定条款、付款与验收、解除与终止、自动续约、保密与知识产权、
主体与签署、服务范围与权限、收费合规（风险代理上限 / 禁止风险代理案件类型）、
不可抗力、通知与送达。

清单是「别忘了查」的备忘，不是「每条都要报」的任务——提示词里明确写了"命中才报，
不要凑数"，并要求 `quote` 单行、40 字以内。

## 配置

```ini
CONTRACT_REVIEW_BATCH_CHARS=6000   # 单批条款字符数
CONTRACT_REVIEW_MAX_CHARS=60000    # 单份合同上限，超出只审前部并标注 truncated
CONTRACT_REVIEW_MAX_BATCHES=8      # 最多几批
CONTRACT_REVIEW_MAX_TOKENS=4096    # 单批输出上限（2048 会把风险数组截断成非法 JSON）
```

`CONTRACT_REVIEW_MAX_TOKENS` 不是可选项：默认的 2048 在实测中会把 8~10 条风险的
JSON 从中间截断，`extract_json` 解析失败后触发纠正重试，最终只拿到一两条风险，
表面看像是"模型没发现问题"。

## 长文与超时

- 6000 字/批，实测单批 20~45 秒；8 批上限对应 4.8 万字，再长就该分工审查了。
- 生产环境若前面有 Nginx，`proxy_read_timeout` 需设到 120s 以上：批次之间是
  一个完整的模型调用，连接上不会有数据。
- 客户端用 `fetch` + `ReadableStream` 读 SSE（axios 拿不到增量，且默认 30s 超时）。

## 自测

```bash
cd backend

# 切分 / 要素定位 / JSON 容错（不需要后端与 Key）
.venv/Scripts/python.exe scripts/contract_smoke.py --digest

# 全链路（需后端已启动、Key 可用、目标合同已上传文件）
.venv/Scripts/python.exe scripts/contract_smoke.py --all --contract-id 8
```

`--digest` 用脚本内置的 11 条合成合同断言：条数、章节归属、要素命中、缺失维度、
空白项、多批切分与截断标记、原文定位与"编造原文不会被误判"。
`--review` 断言 SSE 事件齐全、风险字段完整、存在可核对原文、报告写回台账；
`--guard` 断言客户 403、不存在 404、无文件 400、正文过短 400、`save=false` 不覆盖。

# 案件摘要（9.6）

## 链路

```
案件档案（字段/客户/承办律师）
        ├── 时间线（case_event）
        ├── 待办与逾期日程（schedule）
        ├── 案件文书（document.content → HTML 转纯文本）
        ├── 案件附件（docx/pdf/txt/md → 文本层）
        └── 合同 + 9.5 审查报告（合同全文排在最后，报告更浓缩）
                    ▼
case_summary_service：按优先级排序 → 单份/总量/份数三重预算裁剪
                    ▼
case_prompts：固定六节 + 事实与判断分离 + 出处/缺口要求
                    ▼
LLM 流式 → SSE 逐段转发 → ai_message 落库 + 审计日志
```

**为什么先做材料聚合，而不是把案件所有数据一股脑塞进去。** 一案可能有几十份
材料，全塞会稀释关键文书、超出上下文，还会让模型在无关段落上耗 token。这里按
「对摘要的贡献」排序：案情描述 → 案件文书 → 案件附件 → 合同审查报告 → 合同全文。
被裁掉的材料不会静默消失，标题与原因写进提示词的「未纳入本次摘要的材料」，
让模型在「材料缺口」一节如实说明。

**为什么不脱敏。** 摘要是律师内部工作底稿，姓名、金额、案号必须与卷宗一一对应；
权限收在「仅承办律师/管理员可触发」（架构文档 6.5），不靠打码兜底。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/ai/case-summary/{case_id}` | `text/event-stream`，流式输出六段式摘要 |
| GET | `/api/ai/case-summary/{case_id}` | 读取本人最近一次摘要，供页面刷新回填 |

请求体可省略，也可传：

```json
{ "focus": "重点核对仲裁时效与证据缺口", "include_materials": true }
```

`include_materials=false` 只读档案、时间线与日程，用于材料尚未整理完、先出
一份框架摘要的场景。

SSE 事件：

```
meta     {case_id, case_no, title, session_id, counts, truncated,
          material_count, material_chars, model, provider, disclaimer}
context  {case, timeline, schedules, materials, counts, skipped, focus}
warning  {detail}              # 材料超限/没有可读材料，非致命
stage    {stage: generating, message}
delta    {text}
done     {session_id, message_id, case_id, content, html, materials,
          token_usage, elapsed_ms, generated_at, disclaimer}
error    {detail, retryable}
```

`context` 里的 `materials` 只含元信息（类型/标题/原始字数/是否节选），不回传
正文；前端用它渲染「本次读了什么」，让律师能判断摘要的依据范围。

## 六节结构（9.6.1）

| 小节 | 要求 |
|---|---|
| 一句话概要 | 首行引用块，80 字内说清谁与谁、因何事、处于什么阶段 |
| 一、案件概况 | 案号、案由、双方、标的额、法院、承办律师、立案/结案时间 |
| 二、争议焦点 | 1~4 项，按影响排序，双方主张分开写 |
| 三、事实与证据 | 时间顺序节点「日期｜事件｜出处」+ 证据名称与待证事实 |
| 四、有利与不利 | 有利 / 不利 / 待核实三组，判断加「初步判断：」 |
| 五、下一步与期限 | 待办 + 材料/日程中已出现的期限风险 |
| 六、材料缺口 | 缺少哪些关键材料，缺了影响哪项判断 |

硬约束写在 `case_prompts.build_system_prompt()` 里：只用给定材料、材料未载明
不得补全、材料冲突并列写明、事实与判断分离、金额日期原样引用、不预测裁判结果。

## 材料预算

```ini
CASE_SUMMARY_ITEM_CHARS=6000      # 单份材料上限，超出取前部并标「已节选」
CASE_SUMMARY_TOTAL_CHARS=24000    # 全部材料总上限
CASE_SUMMARY_MAX_MATERIALS=20     # 最多纳入几份
CASE_SUMMARY_MAX_TOKENS=3000      # 摘要输出上限
```

按案件 22（1 份文书 + 1 个附件 + 1 份合同 + 审查报告，共 5,021 字）实测：
约 40 秒生成约 3,000 字摘要，六节齐全，并主动指出材料之间的案号、法院、金额
不一致——这类冲突正是摘要最该暴露、而人工通读容易漏掉的信息。

## 权限与隔离

- 仅 `lawyer` / `admin`；客户账号 403（客户端不展示摘要卡片）。
- 律师必须是该案主办/协办，否则 403；案件不存在 404——复用
  `case_service.get_case_detail` 的行级权限。
- 摘要按 `user_id` 隔离：管理员也看不到他人生成的版本，与 9.3 会话规则一致。
- 每次生成都会建一条 `ai_session(type='case', related_id=case_id)` 与
  `ai_message`，并写 `ai_chat` 审计日志（9.9.3）。

## 安全细节

模型输出不受信任，摘要的 `html` 用 `doc_html.to_html(content, allow_html=False)`
强制按 Markdown 转义后再交给前端 `v-html`，避免模型输出里夹带的标签被执行。
`document.content` 是富文本，读数前用 `doc_html.to_text()` 还原成纯文本。

## 自测

```bash
cd backend

# 提示词结构（不需要后端与 Key）
.venv/Scripts/python.exe scripts/case_summary_smoke.py --prompt

# 全链路（后端已启动、Key 可用、目标案件有材料）
.venv/Scripts/python.exe scripts/case_summary_smoke.py --all --case-id 22
```

`--prompt` 断言六节齐全、材料节选标记、未纳入清单与空材料说明；
`--summary` 断言 SSE 事件齐全、摘要 ≥400 字、六节齐全、HTML 已渲染、
`GET` 回填一致；`--guard` 断言客户 403、不存在 404、关注点超长 422。

# 客户画像（9.7）

## 链路

```
客户档案（类型/来源/状态/分级/负责律师）
        ├── 跟进记录（最近 8 条，含下次跟进与逾期）
        ├── 关联案件（最近 10 个，阶段/标的/法院）
        ├── 合同（最近 6 份，含 9.5 审查发现的风险数）
        ├── 收费方案 → 期次（应收/已收/未收/逾期期次）
        └── 沟通留言（最近 12 条，双向）
                    ▼
client_profile_service：按信息密度排序 → 预算裁剪 → 脱敏（含已知姓名整词替换）
                    ▼
profile_prompts：固定八字段 JSON + 只依据数据 + 数据不足就写「数据不足」
                    ▼
generate_json → normalize_profile（键映射/类型纠正/截断/必填校验）
                    ▼
写回 client_profile.ai_profile / ai_profile_at + 审计日志
```

**为什么不做成 SSE。** 前面几项能力输出几百到几千字的文章，流式能让律师边读边等；
画像是一组结构字段，必须**整体合法**才能写库，半截 JSON 没有意义。一次生成约
15~25 秒，前端显示 loading 即可；代价是 axios 默认 30 秒超时必须放宽（前端已设
120 秒）。

**为什么先聚合再让模型写。** 客户数据散在六张表里，直接丢给模型既超上下文又容易
漏项。聚合层把「客户是谁、谈到哪一步、有没有案子、钱收到哪、客户最近在说什么」
按固定顺序整理好，模型只需要归纳。

## 字段（9.7.3）

| 字段 | 类型 | 说明 |
|---|---|---|
| 客户类型 | string | 一句话刻画身份与决策特征，不是「个人/机构」四个字 |
| 核心诉求 | string | 最想解决的问题、最在意的结果、紧迫程度 |
| 风险点 | array | 最多 3 条，每条 `{point, basis, action}`：风险、依据、应对 |
| 沟通偏好 | string | 渠道、时段、关注点、决策链 |
| 下一步跟进建议 | string | 2~4 条编号短句，含动作与时点 |
| 标签 | array | 3~5 个短词，列表页与检索可复用 |
| 数据依据 | array | 每条关键判断对应哪条记录 |
| 数据缺口 | array | 档案缺失但影响判断的信息 |

硬约束写在 `build_system_prompt()`：只依据给定数据、不推测行业/规模/年龄/性别、
每条判断可回溯、数据不足写「数据不足」、风险最多 3 条、建议必须具体到动作与时点、
不做法律意见。`normalize_profile()` 负责兜底：中英键互转、字符串风险点转对象、
风险截断到 3 条、标签去重、编号换行还原；「客户类型」与「核心诉求」同时为空时判为
无效，不写库、保留上一版。

## 数据预算

```ini
CLIENT_PROFILE_MAX_FOLLOWS=8       # 跟进条数（旧记录会淹没最近一次沟通）
CLIENT_PROFILE_FOLLOW_CHARS=300    # 单条跟进上限
CLIENT_PROFILE_MAX_CASES=10
CLIENT_PROFILE_MAX_CONTRACTS=6
CLIENT_PROFILE_MAX_FEE_PLANS=6
CLIENT_PROFILE_MAX_MESSAGES=12
CLIENT_PROFILE_MESSAGE_CHARS=150
CLIENT_PROFILE_MAX_CHARS=8000      # 总字数，超出从合同→留言→收费→案件→跟进依次裁
CLIENT_PROFILE_MAX_TOKENS=1500
```

被裁掉的条数与原因写进 `inputs.skipped`，提示词单列「未纳入或无法读取的数据」，
让模型在「数据缺口」里如实说明，而不是假设自己看全了。

## 脱敏（9.7.4）

**只作用于送入模型的文本，数据库原文不动。**

| 字段 | 处理 |
|---|---|
| 身份证/统一社会信用代码 | 保留前 4 后 4（`4115**********1010`） |
| 手机号 | 前 3 后 4（`166****2014`） |
| 座机等其余号码 | 前 4 后 2 |
| 邮箱/银行卡 | 复用 `masking.mask_sensitive` |
| 详细地址 | 保留到区县一级，追加「详址已省略」 |
| 个人姓名 | 首字 + `*`（`武庸` → `武*`）；客户姓名还会做**整词替换**，因为案件标题与合同名称是裸串（`武庸土地委派合同`、`邓丽与张伟离婚…`），正则识别不到 |
| 机构名称 | **保留**。它不是自然人敏感信息，且行业与规模是判断客户类型的关键输入 |

提示词额外要求：不得还原或猜测被脱敏内容，指代客户统一用「该客户」。自测脚本会
断言画像正文里没有客户真名。审计日志只写「客户 #id、纳入条数、标签数、脱敏命中」，
不写姓名与电话。

## 权限与存档

- 仅 `lawyer` / `admin`；客户账号 403（画像含「价格敏感」「可能流失」这类内部判断）。
- 律师只能给自己负责的客户生成与读取，复用 `client_service.get_client` 的行级隔离；
  管理员不限。
- 画像**按客户存档**，不是按律师：负责律师换人时，接手的律师直接看到上一份判断，
  这正是客户交接需要的。多次刷新覆盖同一份，不保留版本历史。
- 每次生成写一条 `ai_chat` 审计日志（9.9.3）。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/clients/{id}/ai-profile` | 生成或刷新，JSON 请求体可选 `{"focus": "..."}` |
| GET | `/api/clients/{id}/ai-profile` | 读取已存档画像，未生成时 `profile=null` |

响应（节选）：

```json
{
  "client_id": 67,
  "profile": {
    "client_type": "个人土地纠纷原告，决策快、诉求紧迫",
    "core_demands": "……",
    "risks": [{"point": "剩余 19,200 元律师费未收回", "basis": "应收 30,000 / 已收 10,800", "action": "发送材料清单时同步确认尾款节点"}],
    "communication": "……",
    "next_actions": "1. ……\n2. ……",
    "tags": ["诉求紧迫", "回款待收"],
    "evidence": ["……"],
    "gaps": ["……"]
  },
  "inputs": {
    "counts": {"follows": 1, "cases": 1, "contracts": 1, "messages": 6, "fee_plans": 1, "included": 9},
    "stats": {"due_total": "30000.00", "paid_total": "10800.00", "unpaid_total": "19200.00", "overdue_periods": 0},
    "skipped": ["共有 20 条跟进，仅纳入最近 8 条"],
    "masked": {"hits": {"name": 1, "phone": 1, "id_card": 1, "address": 1},
               "summary": "姓名×1、手机号×1、身份证×1、地址×1"}
  },
  "ai_profile_at": "2026-11-05T22:53:27",
  "model": "qwen3.8-max",
  "elapsed_ms": 19024,
  "disclaimer": "……"
}
```

`inputs` 只回传规模与脱敏命中，不回传任何原文：它用于前端渲染「本次读了什么」，
让律师判断这份画像的依据范围。

## 前端

`components/ClientProfileCard.vue` 接入律师/管理员的客户详情页（基本信息下方）：
标签行 → 客户类型 → 核心诉求 → 沟通偏好 / 跟进建议双栏 → 风险卡（依据 + 应对）→
折叠的「判断依据 / 数据缺口 / 未纳入」→ 读取范围 chips → 脱敏提示。支持关注点、
复制、刷新，客户账号不渲染该卡片。

## 自测

```bash
cd backend

# 提示词结构 + JSON 容错（不需要后端与 Key）
.venv/Scripts/python.exe scripts/profile_smoke.py --prompt

# 全链路（后端已启动、Key 可用、客户有跟进/案件/合同/留言）
.venv/Scripts/python.exe scripts/profile_smoke.py --all --client-id 67
```

`--prompt` 断言八个字段、脱敏/不推测约束、六类数据分节、风险截断到 3 条、中英键映射、
缺必填字段时报错；`--profile` 断言生成耗时、字段完整性、标签数量、依据条数、读取范围
统计、脱敏命中、正文无真名、`GET` 回填一致；`--guard` 断言客户 403、不存在 404、
关注点超长 422。

实测（客户 67，1 跟进 + 1 案件 + 1 合同 + 6 留言 + 1 收费方案）：20 秒生成，4 个标签、
3 条风险、7 条依据，主动指出「漏斗状态仍是潜在，但合同已生效、案件已立案」的登记
矛盾，并给出「发送开庭材料清单时同步确认 19,200 元尾款」这类可执行建议。

## 已知边界

- **数据少的客户只能给「数据不足」。** 这是数据问题不是模型问题：没有跟进与留言时，
  沟通偏好、决策链无从判断，画像会在「数据缺口」里列明，律师应先补录跟进。
- **画像单份覆盖，无版本历史。** 需要对比「上个月与这个月」时应另存快照；当前
  每次刷新都会覆盖，仅审计日志留一条记录。
- **脱敏依赖正则 + 已知姓名替换。** 客户与对方当事人的姓名能覆盖；材料里出现的
  第三方联系人姓名可能漏打码，涉及高度敏感客户时建议人工核对后再生成。
- **收费口径**取 `fee_plan` 下期次汇总，与 `contract.amount` 可能不一致（合同金额
  含税/分期差异）。画像会同时看到两者，若矛盾会在风险或缺口里指出，以收费方案为准。

# 前端 AI 交互（9.8）

## 组件分工

```
components/
├── AiChatWindow.vue        聊天窗：SSE 流式、Markdown、引用锚点、停止/重试/复制
├── LawRefDialog.vue        法条引用弹层：点击 [n] 展开条文原文
├── AiSessionList.vue       历史会话列表：新建、切换、删除、搜索
└── AiAssistantLauncher.vue 右下角悬浮窗：抽屉里复用 AiChatWindow

stores/aiAssistant.js       悬浮窗的开关与预填问题（跨页面唤起）
utils/aiMarkdown.js         模型输出的 Markdown → 安全 HTML
views/ai/AiAssistant.vue    律师/管理员：左会话列表 + 右问答，空态带场景直达
views/client/AiAssistant.vue 客户：单栏问答 + 合规提示，无任何专业功能入口
```

**为什么自己写 Markdown 渲染（`utils/aiMarkdown.js`）。** 项目里没有 marked 之类的依赖，
而第三方解析器默认透传 HTML，还得再叠一层 sanitizer。这里只认模型真会输出的几种结构
（标题/列表/引用块/表格/加粗/行内代码），并且**先转义再加标签**——模型输出里就算夹带
`<script>` 也只会显示成文本。`[n]` 与 `【n】` 都渲染成同一个 `.cite` 锚点，与后端
`extract_used_refs` 的识别口径一致。

**为什么流式期间也做 Markdown 渲染，而不是像案件摘要那样先纯文本后切换。** 摘要是一次性
长文，切换成本低；问答要让人边读边判断是否继续追问，纯文本会在结束后「跳版」。渲染器按行
解析且容错，遇到未闭合的 `**` 或半个 `[1` 就退化成普通段落，不会吞掉后文。

## 流式渲染（9.8.1）

`api/ai.js` 的 `streamPost()` 用 `fetch` + `ReadableStream` 按 `\n\n` 切 SSE 块，逐个
`event` 回调。不用 `EventSource` 是因为它不能带 `Authorization` 头；不用 axios 是因为
XHR 拿不到增量，且全局拦截器设了 30 秒超时——一次问答经常十几秒，审查要几分钟。

事件到界面的映射：

| 事件 | 界面表现 |
|---|---|
| `meta` | 记住 `session_id`（新会话时回填给父组件）、显示脱敏提示、拿 `disclaimer` |
| `stage` | 首 token 未到时的「正在检索法律条文…」 |
| `warning` | 气泡内的黄字提示（检索降级/无法条） |
| `refs` | 引用条数与「引用条文 N 条」区块 |
| `delta` | 追加正文，自动滚动（用户上滑后不再抢滚动） |
| `done` | 用时、token、实际使用的引用高亮 |
| `error` | 红色错误行 + 重试按钮（重试会摘掉失败回答重发原问题） |

「停止」调用 `AbortController.abort()`：后端生成器收到 `CancelledError` 后保留已落库的
分批内容，前端把气泡标记为「已停止生成，以上内容不完整」。

## 引用弹层（9.8.2）

`refs` 与 `done.refs` 都带 `content` 全文（`rag.Reference.to_dict()`），所以点开条文不需要
再发请求。弹层展示法名+条号、章节与效力状态、正文（宋体、首行缩进，便于对照纸质法条）、
检索相关度，并支持复制条文。回答里实际出现过的编号会在引用列表里高亮（`used_refs`），
锚点本身不参与文本选中，避免复制回答时把编号带进正文。

## 全局悬浮窗（9.8.3）

挂在 `AppLayout` 上，因此客户端、律师端、管理端的每个业务页都能唤起；登录页与已经进入
AI 页面的路由不显示（避免同一屏两个输入框）。`Ctrl/Cmd + /` 也能唤起。抽屉复用同一个
`AiChatWindow`，会话存在 `stores/aiAssistant.js` 里，关掉再打开可以接着问。

## 业务页快捷入口（9.8.4）

| 位置 | 行为 |
|---|---|
| 案件详情头部「问 AI」 | 预填「我在办理案件 XXX（案号…，案由…，法院…）」并打开悬浮窗 |
| 合同详情头部「问 AI」 | 预填合同名称、类型、金额、委托客户 |
| 客户案件详情「咨询 AI」 | 预填案件标题与当前进展，客户只需补一句疑问 |
| 案件详情「AI 案件摘要」 | 9.6 的 `CaseSummaryCard`，页内直接生成，不跳转 |
| 合同详情「AI 审查」 | 9.5 的审查按钮，页内生成风险报告 |

预填只是**输入框里的草稿**，不自动发送：律师通常要补一句自己的关注点，直接发出去反而
要等一次没必要的生成。

## 客户端的边界（9.8.6）

客户页面只保留：问答、历史对话、免责声明、联系承办律师入口。没有文书生成、案件摘要、
客户画像、合同审查，也没有「仅法条/仅律所知识」的检索范围选择。权限不在前端兜底：
后端 `/chat` 对客户开放，其余接口对客户一律 403，前端不渲染入口只是少一次无效点击。
客户角色在后端会自动追加「面向当事人」的系统提示词约束（通俗解释、不做胜诉承诺、
不提供诉讼策略）。

## 风格约定

全部沿用既有设计令牌：卡片 `border-radius: 12px` + `--brand-line` 描边，金色只用于
AI 相关的图标与强调（`.cite`、场景图标、悬浮按钮描边），正文 14px / 1.85 行高，辅助
信息 11~12px `--brand-muted`。新增页面没有引入新的色值，保证与客户管理、案件列表等
页面放在一起不突兀。

## 已知边界

- **长回答的渲染成本**：每个 delta 都重渲染整段 Markdown。3k 字以内无感；若以后有
  上万字的回答，应改成「流式期间纯文本 + 结束后渲染」。
- **引用锚点只认 1~2 位数字**：避免把 `[2026]` 这类年份误判成引用。
- **悬浮窗会话与页面会话共用一套接口但不共享状态**：在页面里聊到一半去别的页面用悬浮窗，
  是另一个会话；需要接着聊请从历史会话里点开。

# 出站代理与连接排查

## 问题现象

后端日志出现：

```
ERROR: Exception in ASGI application
  ...
  File "httpcore/_async/http_proxy.py", line 206, in handle_async_request
  ...
  File "httpcore/_async/http11.py", line 106, in handle_async_request
      ) = await self._receive_response_headers(**kwargs)
httpx.ReadTimeout / httpx.RemoteProtocolError / httpx.ConnectError
```

关键词是 `http_proxy.py`：请求没有直连大模型，而是先发给了本机某个代理。

## 根因

httpx 默认 `trust_env=True`，会读取进程环境里的 `HTTP_PROXY` / `HTTPS_PROXY`。
后端常由终端、PyCharm、VS Code 的集成终端启动，会把开发机上临时的代理配置
（Clash、V2Ray、公司代理等）一并继承。于是：

- 代理没启动 → `ConnectError: All connection attempts failed`
- 代理启动后又被关掉 → 连接建立但没有响应头 → `ReadTimeout`
- 本地 TEI / Qdrant 请求被绕到代理 → 明明是内网服务却连不上（现在云端 /embeddings
  反而可能**需要**代理，见 OUTBOUND_PROXY）

而大模型与向量服务本身完全正常，只是「请求走错了路」。

## 现在的约定

所有出站客户端统一由 `app/ai/http_client.py::build_async_client()` 创建：

```python
httpx.AsyncClient(timeout=..., proxy=OUTBOUND_PROXY or None, trust_env=False)
```

- **默认直连**：`OUTBOUND_PROXY` 留空时完全不看环境变量，代理配置从此只来自 `.env`。
- **需要代理**：在 `.env` 写 `OUTBOUND_PROXY=http://127.0.0.1:7890`，模型与向量请求都会走它。
- 覆盖范围：LLM（`openai_client._client`）、Embedding（`embedding.embed_texts` /
  `check_health`）、Qdrant（`kb_service._client`）、各 smoke 脚本访问本地 API 的请求。

启动时会在日志里明确打印出站策略，便于一眼确认：

```
INFO  | 出站代理 | 直连
WARNING | 检测到代理环境变量（HTTPS_PROXY、HTTP_PROXY），已忽略 | 出站为直连；
          如需走代理请在 .env 配置 OUTBOUND_PROXY
```

## 自查顺序

1. 启动日志是「直连」还是代理地址？被忽略的环境变量有哪些？
2. `curl http://127.0.0.1:8000/api/ai/health`（需律师 token）看 `llm.ok` 与
   `embedding.ok`，`llm.error` 会直接写明是超时还是连不上。
3. 仍是 `ReadTimeout` 但日志显示直连 → 看 `LLM_TIMEOUT` 是否太小，或本机 DNS 解析
   `dashscope.aliyuncs.com` 是否正常。
4. 只有检索报错、问答正常 → 看 `/api/ai/health` 里 `embedding.provider`，
   `openai` 档检查 Key 与出网，`tei` 档检查容器（`http://127.0.0.1:8081/health`）；
   再看 Qdrant（`http://127.0.0.1:6333/collections/law_kb`）。

## 顺带加固

`_stream_once` 把 `async with self._client() as client` 一并放进 `try`：代理链路异常时，
异常可能在连接池 `aclose()` 阶段才抛出，原先会被漏到 ASGI 层变成 500。现在统一转成
`LLMError(retryable=True)`，接口层返回 503 与「AI 服务暂时不可用，请稍后重试」。

---

# 9.10 本人业务数据注入（问答能答「我的案件」「我的费用」）

> **本节已被 9.11 取代。** 业务数据不再注入问答链路，改由独立入口「AI督办」承担；
> 下文保留当时的问题分析与取数设计，`personal_context_service` 的取数逻辑仍在使用。

## 之前的窟窿

9.3 的问答只有两个输入：用户问题 + `law_kb` 检索结果。于是：

- 问「我手上这个案子办理到哪一步了」→「现有资料未涵盖您具体案件的实时办理进度」，
  再拿《办案手册》的一审流程顶替，让用户自己去页面查。
- 问「我这个案子的律师费是多少、还差多少」→「无法给出确定数字」，讲收费方式的
  三种类型与付款期限。

用户问的是「我的」，回答的是「一般规定」。而案件、费用、日程数据本来就在
`cases` / `fee_plan` / `fee_period` / `payment` / `schedule` 里，只是没有任何一条
路径把它们送进模型。

## 现在的链路

```
提问 → 意图判定（fact / mixed / knowledge）
     → 按角色取快照（客户=本人；律师=承办；管理员=全所）
     → 脱敏 + 拼成【本人业务数据】
     → 拼提示词（业务数据 + 参考资料 + 问题）
     → 流式生成
```

新增文件：

- `app/ai/context_prompts.py`：意图判定、业务数据段渲染、`BUSINESS_RULES`
- `app/services/personal_context_service.py`：取数与格式化

改动点：`prompts.build_chat_messages(business_context=...)`、`ChatPlan` 增加
`context_*` 字段、`stream_reply` 新增 `context` 事件、`AiChatIn.include_context`。

## 三条硬约束

写在 `BUSINESS_RULES` 里，随系统提示词下发：

1. 本人事实必须用【本人业务数据】回答，**不许再说「我查不到您的案件」**；
2. 金额、案号、日期逐字照抄，没登记就写「系统未登记」，不许按行业惯例估算；
3. 业务数据**不参与 `[n]` 编号**，法条引用体系不受影响。

## 数据范围与脱敏

| 角色 | 数据 | 脱敏 |
| --- | --- | --- |
| 客户 | 本人委托的案件、账单、合同、近期开庭 | 自己姓名保留，其他自然人打码 |
| 律师 | 本人承办案件、按方案的费用明细、催收清单、日程、合同 | 登录人真名保留，客户/对方姓名打码，机构名保留 |
| 管理员 | 全所同口径 | 同上 |

身份证、手机号、详细地址一律不进上下文。金额对客户只出应收/已缴/待缴，不出成本
与利润。取数全部复用 `case_service` / `billing_service` / `contract_service` /
`schedule_service` 的既有方法，**不另写一套权限判定**，避免「AI 看到的比页面多」。

## 预算与降级

- 上限 `PERSONAL_CONTEXT_MAX_CHARS = 2200`（约 1500 token），超出**整块丢弃**，
  不切断单条记录——半个日期比不给更危险。
- 取数异常只记日志并返回空上下文，问答照常走 RAG。
- 纯事实型问题（如「我的案子办到哪了」）跳过向量检索：答案本来就在业务数据里，
  省一次约 1 秒的 embedding + Qdrant 查询。
- 纯知识型问题（如「违约金过高如何调整」）只注入一行概览，不列案件与金额，
  避免模型跑题。

## 前端

`context` 事件带 `items[{kind,label,detail,link}]`，`AiChatWindow` 在回答上方渲染
「已读取 N 条业务数据 · 截至 …」，展开后是可点击的来源标签，点击跳到案件/账单页
核对。历史会话不展示该条（数据库没有存当时快照，回看旧金额会误导）。

## 验证

```bash
cd backend
.venv/Scripts/python.exe scripts/lifecycle_chat_check.py            # 律师
.venv/Scripts/python.exe scripts/lifecycle_chat_check.py --as-user-id 6   # 客户（免密码）
.venv/Scripts/python.exe scripts/lifecycle_chat_check.py --no-context     # 对照旧行为
```

实测（2026-11-06，种子数据）：

- 律师问进度：从「查不到」变为逐案列出 6 件（含状态、案号、法院、标的额、客户、
  下一节点），末尾追问「想重点看哪一件」。
- 律师问费用：按方案给出「武家起诉乔家占福地 ¥30,000 / 已收 ¥10,800 / 未收
  ¥19,200」，并区分「系统未登记收费方案」的 4 件。
- 客户问进度/欠费：给出本人 1 件案件状态、第 1 期待缴 ¥19,200、合同有效期，
  并提示「应缴日期未登记」。
- 关闭注入（`--no-context`）回到旧行为，可用于对比。

---

# 9.11 拆成两个入口：AI 法律问答 / AI督办

9.10 把个人业务数据塞进了问答链路，用关键词判意图切换模板。能用，但三处不对：

- **两套规矩互相稀释**。一边要求「只依据法条、逐条标 `[n]`」，一边要求「数字逐字
  照抄、不标编号」，写在同一条系统提示词里，问费用时模型仍会补一段收费规则。
- **外壳是错的**。查自己的案子却看到「本回答不构成法律意见」和 6 条法条引用，
  像在银行 APP 查余额却弹出一份《储蓄管理条例》。
- **审计分不开**。两类请求在 `ai_session` 里都是 `type='chat'`，事后看不出哪些
  是在问知识、哪些是在查客户数据。

因此拆成两条互不相干的链路，模块名为 **AI督办**（命名取自用户：「督」指盯进度、
催款项、提醒节点，比「查询」更贴近这件事的用途）。

## 两条链路

| | AI 法律问答 | AI督办 |
| --- | --- | --- |
| 接口 | `POST /api/ai/chat` | `POST /api/business/chat` |
| 提示词 | `app/ai/prompts.py` | `app/ai/business_prompts.py` |
| 数据源 | `law_kb` 向量检索 | 业务台账实时快照 |
| 引用 | 逐条 `[n]` | 不引法条、不编号 |
| 会话类型 | `chat` | `business` |
| 免责声明 | 不构成法律意见 | 数据以页面登记为准 |
| 前端 | `AiChatWindow.vue` | `BusinessChatWindow.vue` |

会话不能跨入口续接：拿法律会话 id 调业务接口返回 404，反之亦然。业务会话里全是
金额与进度，续到法律问答会被当成法律事实复述。

## 新增文件

- `app/ai/business_prompts.py`：系统提示词、`BUSINESS_RULES`、整块裁剪的上下文渲染
- `app/services/business_chat_service.py`：`POST` 主流程（读快照 → 生成 → 落库 → 审计）
- `app/routers/business.py`：`/api/business` 下三个端点（问答、会话列表、会话详情）
- `frontend/src/components/BusinessChatWindow.vue`
- `frontend/src/views/ai/MyBusiness.vue`（律师/管理员）、`views/client/MyBusiness.vue`
- `frontend/src/styles/ai-markdown.css`：两端共用的正文排版

`app/services/personal_context_service.py` 原样复用，它只是取数层，与问答无关。

## 督办的九条规则

`BUSINESS_RULES` 里的硬约束，与法律问答最大的差别是**不引法条**：

1. 事实只来自【业务数据】，缺项写「系统未登记该信息」；
2. 不引法条、不标 `[n]`、不做法律分析，用户问法律依据就一句话指回 AI 法律问答；
3. 开头点明「截至 …」，说明这是快照而非实时推送；
4. 先给结论数字，再给明细；
5. 时间是风险，逾期、7 天内开庭、合同 30 天内到期要单独点出来；
6. 权限范围外说「不在你的权限范围或系统无记录」，不猜；
7. 多个在办案件时逐条列出并追问「想重点看哪一件」；
8. 直白对账口吻，不用客套；
9. 收尾一句「接下来最该做的一件事」，只给一条。

第 9 条的日期有一条额外限制：**只能取自台账里登记过的期限**，没有期限就写
「尽快」。首版没写这句限制，模型给出一条「在 11-13 前催收」——那个日期是它自己
按 7 天推算的，用户会当成台账事实。已修正并回归。

## 法律问答的反向引导

拆分后，用户在法律问答里问「我的案子办到哪了」，模型会回一句：

> 本入口只解答法律问题，查询您具体案件的办理进度、开庭时间或缴费情况，请到「AI督办」查询。

只有这一句，不再补通用办案流程与审限规定（`prompts.py` 第 8 条）。实测输出 45 字，
此前是「查不到 + 六步流程 + 审限规定」约 800 字。

## 前端

- 菜单：律师端 `/lawyer/business`、客户端 `/client/business`、管理员端
  `/admin/business`，标签统一「AI督办」。
- 律师/管理员页：左侧历史督办记录（`session-type="business"` 过滤），右侧问答，
  顶部有「去问法律问题」；客户页单栏，保留本人数据口径提示。
- 两边回答上方都有「AI 督办」标识与「数据截至」提示，回答末尾显示数据口径声明；
  不再出现引用编号与法条弹窗。
- 悬浮窗仍只挂法律问答，进入督办页时自动隐藏。

## 验证

```bash
cd backend
.venv/Scripts/python.exe scripts/lifecycle_chat_check.py --mode business   # 督办
.venv/Scripts/python.exe scripts/lifecycle_chat_check.py --mode law        # 法律问答
.venv/Scripts/python.exe scripts/lifecycle_chat_check.py --as-user-id 6 --mode business
.venv/Scripts/python.exe scripts/business_guard_check.py                   # 边界与权限
```

`business_guard_check.py` 覆盖：两会话各自建立、跨入口续接返回 404、会话列表按
`type` 过滤、详情按类型给不同声明、入参守卫、客户只能读到自己的数据。

实测（2026-11-06）：

- 律师问进度：6 件逐条列出（状态/案号/法院/标的额/客户/费用），末尾「联系客户武*
  催收 ¥19,200」；无引用。
- 律师问欠费：未收合计 ¥19,600，明细两笔，其余 4 件写「系统未登记」。
- 客户问欠费：直接答「还差 ¥19,200」，并提示合同 2027-01-07 到期（还剩 62 天）。
- 管理员问全所：在办 5 件、已收 ¥11,400。
- 法律问答问业务问题：45 字引导，未注入业务数据（事件序列无 `context`）。

## 9.11.1 两个入口的消息隔离

会话表是同一张（`ai_session`），隔离靠三层，缺一层都会串：

| 层 | 机制 | 失败时的表现 |
| --- | --- | --- |
| 列表 | 前端固定传 `type`，`AiSessionList` / `SessionHistoryPop` 按入口过滤 | 法律问答的历史里出现「武家起诉乔家占福地」这类督办记录 |
| 详情 | `GET /api/ai/sessions/{id}?type=chat\|business`，类型不符返回 404 | 点开另一端的会话，正文直接串进来 |
| 续接 | `POST /api/ai/chat` 只认 `chat` 会话，`/api/business/chat` 只认 `business` | 在督办里问的金额被当成法律问答的上下文 |

三处的报错统一用 404 而不是 403：告诉调用方「这个 id 存在但不属于当前入口」，
等于泄露了他人会话的存在性。

前端改动：

- `api/ai.js` 的 `getAiSession(id, type)` 带上入口类型；
- `AiChatWindow` 传 `chat`、`BusinessChatWindow` 传 `business`；
- 律师/管理员页 `AiSessionList` 加 `session-type="chat"`；
- 客户端两个页面改用 `SessionHistoryPop`，各自传 `chat` / `business`。

## 9.11.2 客户端删除对话

客户端原来是 popover 里一列标题，只能点开、不能删。新增
`frontend/src/components/SessionHistoryPop.vue`，法律问答与 AI督办 共用：

- 每条右侧一个删除图标，**常显**（压暗 50%），hover 加深。客户不熟悉界面，
  藏到 hover 才出现的删除键基本等于没有。
- 删除前二次确认，文案说明「全部问答记录都会移除，且不可恢复」。
- 删的是当前正在看的那条：先 `emit('select', null)` 让页面清空正文并 `newChat()`，
  再刷新列表——否则输入框还挂着已不存在的会话 id，追问会 404。
- 点条目后调用 `el-popover` 实例的 `hide()` 收起弹层（不用受控 `visible`，
  避免与 `trigger="click"` 打架）。
- 列表首次挂载自己拉一次（`onMounted`），因为 popover 内容懒渲染，
  `@show` 那一刻子组件 ref 可能还没就绪。

律师/管理员端本来就有 `AiSessionList` 的删除能力，这次只补了 `type` 过滤。

验证（`business_guard_check.py` 第 8 组）：

- 删除自己的督办会话 → 204，详情再查 404，列表中消失；
- 客户删律师的会话 → 403。
