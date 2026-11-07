# 生产部署件

**完整操作手册见 [DEPLOY.md](./DEPLOY.md)** —— 从打包、上传、装环境到数据迁移和验收，逐条命令可直接复制。

| 文件 | 作用 |
|---|---|
| `DEPLOY.md` | 部署与数据迁移手册（Ubuntu + IP/HTTP + Docker Qdrant） |
| `release-frontend.sh` | **前端发版**：本地构建 → 上传 → 原子切换 → reload nginx（在本地跑） |
| `host-setup.sh` | 主机调优：2G swap + swappiness、MySQL 调参、日志轮转。默认只打印，`--apply` 才执行 |
| `law-firm-api.service` | 后端 systemd 单元（**单 worker**，原因见文件内注释） |
| `nginx.conf` | HTTPS 版反代配置（有域名后使用） |
| `nginx-http.conf` | HTTP 版反代配置（**无域名临时用**，登录密码明文传输） |
| `vector-snapshot.sh` | 向量库导出 / 导入 / 校验，免去服务器重建向量 |

`frontend/dist` 不入库：vite 每次构建会换掉全部 123 个 assets 文件名，入库等于每次发版给仓库永久加 3.8 MB。
发版只能走 `release-frontend.sh`，服务器上也不要 `npm run build`（2C2G 峰值 1 GB 会 OOM）。

依赖清单用 `uv export` 从 `uv.lock` 生成，见 `backend/requirements-prod.txt`（144 行，版本锁定）。
重新生成：

```bash
cd backend && uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements-prod.txt
```

## 向量库：迁快照还是重建

| | 迁快照 | 服务器重建 |
|---|---|---|
| 耗时 | 1 秒 | 约 80 秒 + embedding 费用 |
| 内容 | 与本地逐字节一致，2297 个点 ID 与 MySQL `vector_id` 天然对应 | 需重算，点 ID 会重新生成 |
| 额外条件 | Qdrant 版本 >= 源版本（当前 1.16.3） | 需上传 `rag/law`（764 KB / 11 个文件） |
| 费用 | 0 | 2284 条 × ~460 字，约 105 万 token |

推荐迁快照。**但有个必须知道的前提**：`kb_builder.py --reindex` 只处理
`vector_id IS NULL` 的条目。如果 MySQL 已经是从本地 dump 过来的（`vector_id` 全部非空），
而 Qdrant 是空的，直接跑 `--reindex` 会**静默跳过全部条目**，日志看起来正常、检索却永远为空。
这种场景必须先 `--reset-vectors` 再 `--reindex`，或者干脆用快照。

反过来，迁快照后新增一部法律时，`--parse` 插入的新行 `vector_id` 为 NULL，
`--reindex` 只补这些新行，增量是正确的。

## 已知坑

- **`db/schema.sql` 开头会 DROP 全部 25 张表**，只能用于全新库，切勿在生产执行。
- **单 worker**：`dict_cache`、AI 配置快照、APScheduler 都是进程内状态，多 worker 会导致
  字典忽新忽旧、定时提醒重复推送。
- **时区**：服务器默认 UTC，代码里有 99 处裸 `datetime.now()`，systemd 里必须保留
  `Environment=TZ=Asia/Shanghai`，否则所有时间偏 8 小时。
- **SSE**：nginx 必须对 `/api/ai/` 关 buffering、`proxy_read_timeout 600s`，
  否则流式回答会整段卡住到最后一次性吐出。
- **前端 `dist` 过期**：`prod_check.py` 会检查 `dist` 里是否含 `assets/dict-*.js`，
  缺了说明打的是旧包。
- **`pip install -e .` 会失败**：`pyproject.toml` 没有 `[build-system]`，
  只装 `requirements-prod.txt`，`app` 包靠 systemd 的 `WorkingDirectory` 加载。
