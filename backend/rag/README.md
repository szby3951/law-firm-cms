# RAG 语料目录

本目录**只存放构建知识库用的外部原始资料**，由 `scripts/kb_builder.py` 读写。

## 与 `uploads/` 的区别（务必不要混用）

| 目录 | 内容 | 谁写入 | 是否入库（MySQL） |
|---|---|---|---|
| `rag/` | 法条原文等公开语料，可随时重新下载 | `kb_builder.py --fetch` | 解析后写 `law_article` 表 |
| `uploads/` | 当事人上传的案卷、合同、文书、留言附件 | 各业务接口 | 只存路径，不进入知识库 |

两者生命周期完全不同：`uploads/` 里是当事人隐私材料，**不得**被检索、不得送 LLM、
不得随语料一起重新下载或清理；`rag/` 里的语料是公开法条，可随时删除重建。
因此 `app/config.py` 中 `rag_dir` 与 `upload_dir` 被模型校验强制隔离，
把 `rag_dir` 配到 `uploads` 内部会直接启动失败。

## 目录结构

```
rag/
└── law/                         # 法条 Markdown（源：GitHub LawRefBook/Laws）
    ├── 民法典/                   # 按编拆分（总则、合同、物权、侵权责任…）
    ├── 刑法/
    ├── 民法商法/                 # 公司法
    └── 诉讼与非诉讼程序法/        # 民事诉讼法
```

## 重建流程

```bash
cd backend

python scripts/kb_builder.py --check      # 看现状：条数 / 向量数 / 服务健康
python scripts/kb_builder.py --fetch      # 重新下载到 rag/law（已存在则跳过）
python scripts/kb_builder.py --parse      # 解析入库（幂等）
python scripts/kb_builder.py --index      # 向量化写 Qdrant（支持断点续跑）
```

**换向量模型 / 换 provider 后必须整体重建**，否则新旧向量混在一起，检索全是噪音：

```bash
python scripts/kb_builder.py --reset-vectors --reindex
```

`--reset-vectors` 会删 collection，并把法条**与律所知识**的 `vector_id` 一起清空。

## 向量化后端

由 `.env` 的 `EMBEDDING_PROVIDER` 决定，两种后端对外接口一致：

| provider | 接口 | 内存占用 | 适用 |
|---|---|---|---|
| `openai`（默认） | `POST {EMBEDDING_BASE_URL}/embeddings`，DashScope `text-embedding-v4` | 0（纯 HTTP） | 2C2G 等小机器、绝大多数部署 |
| `tei` | `POST {EMBEDDING_BASE_URL}/embed`，自建 TEI + `bge-large-zh-v1.5` | 1.4~1.8GB | ≥4GB 且要求完全离线 |

2C2G 服务器**不要**用 `tei`：bge-large 权重就 1.3GB，加上 MySQL/Qdrant/uvicorn
必然被 OOM killer 杀掉（`prod_check.py` 会拦这一项）。

新增一部法律：在 `kb_builder.py` 的 `SOURCES` 里加一条（相对路径 + 法律名），
再执行 `--fetch --parse --index`。增量只算新条文，不会重复向量化。

## 禁止事项

- 不要把 `uploads/` 的文件复制进来"顺便入库"，当事人材料需脱敏与授权；
- 不要在本目录放数据库备份、模型文件、向量快照（向量在 Qdrant，模型由服务商托管）；
- 本目录可按需清空重建，**不要**在其中保存唯一副本。
