"""全局配置：基于 pydantic-settings 从 .env 读取，字段名与配置项大小写无关。"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录，用于拼装 .env、上传目录等相对路径
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "律所客户智能管理系统"
    app_env: Literal["dev", "prod"] = "dev"
    debug: bool = True
    api_prefix: str = "/api"
    log_level: str = "INFO"

    # ---------- 数据库 ----------
    database_url: str = (
        "mysql+aiomysql://root:123456@127.0.0.1:3306/law_firm?charset=utf8mb4"
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------- JWT ----------
    jwt_secret: str = "please-generate-your-own-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # ---------- Qdrant ----------
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "law_kb"

    # ---------- 出站网络 ----------
    # 访问大模型、向量服务、Qdrant 时使用的 HTTP 代理，留空表示直连。
    # 留空时**不读取** HTTP_PROXY/HTTPS_PROXY 环境变量：后端由终端/IDE 拉起时
    # 很容易继承到临时调试代理，代理一停，所有模型调用都变成连接超时，
    # 而堆栈会指向 httpx 的 http_proxy，极难定位。需要代理请显式填这里。
    outbound_proxy: str = ""

    # ---------- 云端大模型（OpenAI 兼容 API）----------
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_temperature: float = 0.3
    # 单次回复的 token 上限。法条问答、文书初稿通常 1~2k 足够；
    # 给太大不仅费钱，还会让模型在长上下文里跑偏。
    llm_max_tokens: int = 2048
    # 单次调用超时（秒）。流式响应每收到一段都会重置读超时，
    # 因此这里约束的是「两段输出之间的最大间隔」与非流式调用的整体耗时。
    llm_timeout: int = 60
    # 首字节前的重试次数（429/5xx/连接失败）。流式一旦开始输出就不再重试。
    llm_max_retries: int = 2
    # 是否让「混合思考」模型（qwen3 系列、GLM-4.5 等）在回答前先输出思维链。
    # auto = 不发送该字段，完全用供应商默认值；on/off = 显式要求开启/关闭。
    # 之所以不用 bool|None，是因为 .env 里留空时 pydantic 会直接报错，
    # 而这是一个「可以不管」的开关，留空应当等于 auto。
    llm_enable_thinking: Literal["auto", "on", "off"] = "auto"

    # ---------- Embedding ----------
    # tei    = 自建 Text Embeddings Inference，POST /embed（bge 系列）
    # openai = 任意 OpenAI 兼容接口，POST /embeddings（DashScope、SiliconFlow…）
    # 默认走云端：bge-large 本地推理要 1.4~1.8GB 内存，2C2G 服务器扛不住
    # （详见 rag/README.md 的内存说明）。
    embedding_provider: Literal["tei", "openai"] = "openai"
    embedding_model: str = "qwen3.7-text-embedding"
    embedding_dim: int = 2560
    # OpenAI 兼容接口要带 /v1，代码会在其后拼 /embeddings
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 云端接口的 Key。留空则复用 LLM_API_KEY（同属百炼账号时最省事；
    # 两处填同一把 Key 也无妨）。TEI 是内网服务，不需要 Key。
    embedding_api_key: str = ""
    embedding_batch_size: int = 8
    # 单请求条数硬上限。text-embedding-v3/v4 一次最多 10 条，超出直接 400；
    # 在这里兜底，避免把 embedding_batch_size 调大后整批入库失败。
    embedding_max_batch: int = 10
    # 同时在途的请求数。云端按 QPS 限流，并发太高容易吃 429（本层有退避重试，
    # 但会拖慢整体）；TEI 在 CPU 上串行推理，并发过高只是排队。
    embedding_concurrency: int = 3
    # 单条文本送入向量的最大字符数，超出部分由 kb_service 切块。
    # 取 460 是为了让每条法条分块足够细、检索命中更准；云端模型虽支持 8k token，
    # 但改大这个值等于改变切块口径，会让已有向量失效，非必要不要动。
    embedding_max_chars: int = 460
    # 单次请求超时。云端单请求通常 1~3s，30s 足够；TEI 在 CPU 上排队可能数十秒。
    embedding_timeout: int = 30

    # ---------- 文件上传 ----------
    upload_dir: Path = BASE_DIR / "uploads"
    max_upload_size: int = 20 * 1024 * 1024

    # ---------- RAG 知识库原始资料 ----------
    # 只存放构建知识库用的外部资料（法条 Markdown 等），**不接收任何用户上传**，
    # 与 upload_dir 严格隔离，避免业务附件与语料混在一起被误清理或误备份。
    rag_dir: Path = BASE_DIR / "rag"

    # ---------- RAG 问答（9.3）----------
    # 律所名称，写进系统提示词（"你是XX律所的法律顾问"）
    firm_name: str = "示例律师事务所"
    # 每次检索带入的法条/知识条数。设计文档要求 5~8：太少缺依据，
    # 太多会把上下文塞满、稀释真正相关的条文，还增加费用。
    rag_top_k: int = 6
    # 余弦相似度下限。低于此值基本是"字面相近但语义无关"的片段，
    # 送进提示词只会诱导模型强行引用；宁可让模型说"资料不足"。
    rag_min_score: float = 0.40
    # 单条引用的正文上限（同一法条多个分块合并后会超长）
    rag_ref_max_chars: int = 900
    # 全部参考资料的总字符上限，防止长条文把上下文撑爆
    rag_max_context_chars: int = 5200
    # 多轮对话带多少条历史消息（一回合 = user + assistant）
    ai_history_messages: int = 6
    # 单条历史消息的截断长度，避免旧回答挤占本轮资料的空间
    ai_history_max_chars: int = 1200

    # ---------- 合同风险审查（9.5）----------
    # 单批送审的条款字符数。太小会把相互指代的条款切散（"前述款项""该条约定"
    # 找不到上下文），太大则单批耗时长、超时与限流风险高。6000 字约 4.5k token，
    # 实测单批 20~40 秒。
    contract_review_batch_chars: int = 6000
    # 单份合同送审的字符上限，超出只审前部并在报告里标注 truncated
    contract_review_max_chars: int = 60000
    # 最多分几批：8 × 6000 字已覆盖 4.8 万字，再多说明该走人工分工审查
    contract_review_max_batches: int = 8
    # 单批输出的 token 上限。审查结果是一组结构化风险（单条约 200~300 token），
    # 沿用默认的 2048 会被截断成非法 JSON；4096 可容纳 8~10 条。
    contract_review_max_tokens: int = 4096

    # ---------- 案件摘要（9.6）----------
    # 单份材料送入提示词的字数上限。起诉状、代理词通常 1~3k 字，6000 足够；
    # 超出只取前部并在材料标题里标「已节选」，避免模型把节选当成全文。
    case_summary_item_chars: int = 6000
    # 全部材料的总字数上限。qwen3.8-max 上下文足够，但摘要不是"读得越多越好"：
    # 2.4 万字约 1.8 万 token，既覆盖典型卷宗，又不会让费用与首字延迟失控。
    case_summary_total_chars: int = 24000
    # 最多纳入几份材料。太多会让关键文书被淹没，剩下列进「未纳入材料」提示缺口。
    case_summary_max_materials: int = 20
    # 摘要输出上限：六节结构约 2~3k 字，3000 token 留有余量。
    case_summary_max_tokens: int = 3000

    # ---------- 客户画像（9.7）----------
    # 最近几条跟进进提示词。跟进是判断客户意愿最直接的材料，但十几条旧记录
    # 会把「最近一次说了什么」淹没，8 条足够覆盖一个业务周期。
    client_profile_max_follows: int = 8
    # 单条跟进正文上限，超出截断（长记录多半是复制粘贴的通话纪要）
    client_profile_follow_chars: int = 300
    # 关联案件/合同/收费方案各取最近几项
    client_profile_max_cases: int = 10
    client_profile_max_contracts: int = 6
    client_profile_max_fee_plans: int = 6
    # 沟通留言取最近几条，以及单条上限：客户情绪变化看语气，太长反而稀释信号
    client_profile_max_messages: int = 12
    client_profile_message_chars: int = 150
    # 全部输入的总字数上限，超出从信息密度最低的一类开始裁
    client_profile_max_chars: int = 8000
    # 画像输出上限：8 个字段约 800~1200 字，1500 token 足够，也防止模型长篇发挥
    client_profile_max_tokens: int = 1500

    # ---------- 定时任务（提醒扫描）----------
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 5  # 扫描间隔（分钟）
    remind_ahead_days: int = 3  # 开庭/期限/缴费提前多少天提醒
    contract_expiry_days: int = 30  # 合同到期提前预警天数

    # ---------- CORS（逗号分隔字符串）----------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("llm_enable_thinking", mode="before")
    @classmethod
    def _normalize_thinking(cls, v: object) -> object:
        """``true/false``、``yes/no`` 也接受，避免照抄布尔习惯导致启动失败。"""
        if isinstance(v, bool):
            return "on" if v else "off"
        if isinstance(v, str):
            text = v.strip().lower()
            if text in {"", "auto", "default"}:
                return "auto"
            if text in {"true", "1", "yes", "y", "on", "enable", "enabled"}:
                return "on"
            if text in {"false", "0", "no", "n", "off", "disable", "disabled"}:
                return "off"
        return v

    @field_validator("upload_dir")
    @classmethod
    def _absolutize_upload_dir(cls, v: Path) -> Path:
        """相对路径统一挂到 backend/ 下，避免随启动目录漂移。"""
        return v if v.is_absolute() else (BASE_DIR / v).resolve()

    @field_validator("rag_dir")
    @classmethod
    def _absolutize_rag_dir(cls, v: Path) -> Path:
        return v if v.is_absolute() else (BASE_DIR / v).resolve()

    @model_validator(mode="after")
    def _ensure_rag_dir_isolated(self) -> "Settings":
        """RAG 语料目录不得落在上传目录内，防止与用户附件混用。"""
        rag, upload = (
            str(self.rag_dir).rstrip("/\\"),
            str(self.upload_dir).rstrip("/\\"),
        )
        if rag == upload or rag.startswith(upload + os.sep):
            raise ValueError(
                f"rag_dir（{self.rag_dir}）不能与 upload_dir（{self.upload_dir}）重叠，"
                "知识库语料需与用户上传文件分开存放"
            )
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def llm_enabled(self) -> bool:
        """未配置 API Key 时，AI 模块走降级提示，不影响主系统。"""
        return bool(self.llm_api_key.strip())

    @property
    def llm_thinking_flag(self) -> bool | None:
        """给客户端的 ``enable_thinking`` 取值：``None`` 表示不发送该字段。"""
        return {"on": True, "off": False}.get(self.llm_enable_thinking)

    @property
    def embedding_key(self) -> str:
        """向量化实际使用的 Key：专用 Key 优先，留空时复用大模型 Key。"""
        return self.embedding_api_key.strip() or self.llm_api_key.strip()

    @property
    def embedding_batch(self) -> int:
        """实际生效的单请求条数，既不超过配置值也不超过云端硬上限。"""
        return max(1, min(self.embedding_batch_size, self.embedding_max_batch))

    @property
    def embedding_ready(self) -> bool:
        """向量化是否具备调用条件：TEI 不需要 Key，云端必须有 Key。"""
        if self.embedding_provider == "tei":
            return bool(self.embedding_base_url.strip())
        return bool(self.embedding_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
