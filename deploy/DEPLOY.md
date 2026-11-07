# 部署与数据迁移手册

> 适用场景：**Ubuntu 22.04 / 24.04 + 无域名（IP + HTTP）+ Qdrant 用 Docker**
> 目标机器：2 vCPU / 2 GiB
> 约定：`<SERVER_IP>`、`<DB_PASSWORD>`、`<JWT_SECRET>` 等尖括号内容都要替换成你自己的值

**两种终端不要搞混：**

| 标记 | 在哪执行 |
|---|---|
| `【本地】` | 你自己的 Windows，Git Bash（或 Windows Terminal 里的 Git Bash） |
| `【服务器】` | WinTerm SSH 上去的 Ubuntu，root 身份（`sudo -i` 之后） |

---

## 0. 先准备这张表

| 变量 | 取值 | 从哪来 |
|---|---|---|
| `<SERVER_IP>` | 服务器公网 IP | 云控制台 |
| `<DB_PASSWORD>` | 应用数据库密码 | 自己定，16 位以上随机串 |
| `<JWT_SECRET>` | JWT 签名密钥 | 第 5 步用命令生成 |
| `<LLM_API_KEY>` | 百炼 Key（`sk-ws-...`） | 本地 `backend/.env` 的 `LLM_API_KEY` |
| `<FIRM_NAME>` | 律所全称 | 自己填，会写进 AI 提示词 |

---

## 1. 【本地】打包要上传的东西

### 1.1 构建前端

```bash
cd /d/law-firm-cms/frontend
npm run build
```

产出 `dist/`，约 3.8 MB / 126 个文件。**不要在服务器上构建**，vite 峰值要 1 GB 内存，会把 2G 机器打爆。

### 1.2 导出数据库

```bash
cd /d/law-firm-cms
/d/mysql/bin/mysqldump.exe -u root -p \
  --single-transaction --quick --routines --triggers \
  --default-character-set=utf8mb4 --set-gtid-purged=OFF \
  law_firm > .snap/law_firm.sql
```

会提示输入 MySQL root 密码（本机那个）。产出几 MB 的 `.sql`，里面已含 `CREATE TABLE`。

> ⚠️ **不要在生产执行 `db/schema.sql`**，它开头会 `DROP TABLE` 掉全部 25 张表。

### 1.3 导出向量快照（如果还没有）

```bash
cd /d/law-firm-cms
bash deploy/vector-snapshot.sh export .snap
```

已有 `.snap/law_kb-20261107-171114.snapshot`（43 MB）可跳过。**换了 embedding 模型或重建过法条才需要重导。**

### 1.4 打包源码

```bash
cd /d/law-firm-cms
tar -czf .snap/law-firm-src.tar.gz \
  --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='uploads' --exclude='.env' --exclude='.pytest_cache' \
  backend deploy db
```

约 1 MB。排除了 `.venv`（1.5 GB，服务器上重装）、`uploads`（单独传）、`.env`（服务器上重写）。

### 1.5 上传

```bash
cd /d/law-firm-cms
scp .snap/law-firm-src.tar.gz .snap/law_firm.sql .snap/law_kb-*.snapshot \
    root@<SERVER_IP>:/tmp/

scp -r frontend/dist    root@<SERVER_IP>:/tmp/
scp -r backend/uploads  root@<SERVER_IP>:/tmp/
```

合计约 52 MB。上传完可以核对：

```bash
# 【服务器】
ls -lh /tmp/*.tar.gz /tmp/*.sql /tmp/*.snapshot && du -sh /tmp/dist /tmp/uploads
```

---

## 2. 【服务器】基础环境

```bash
sudo -i          # 后面全部用 root
apt update && apt -y upgrade
apt install -y nginx mysql-server docker.io rsync curl
systemctl enable --now nginx mysql docker
```

安装 Docker 只为跑 Qdrant 一个容器（常驻约 100–150 MB）。

### 2.1 建运行用户

```bash
useradd -r -m -d /home/lawfirm -s /bin/bash lawfirm
```

后端以这个身份跑（systemd 里 `User=lawfirm`），不要用 root。

### 2.2 主机调优（swap + MySQL 参数）

```bash
# 打包还没解开的话，先用第 3 步解包，再回来跑这个
bash /opt/law-firm-cms/deploy/host-setup.sh            # 先预览
bash /opt/law-firm-cms/deploy/host-setup.sh --apply    # 确认后执行
systemctl restart mysql
```

做三件事：加 2 GB swap（`swappiness=10`）、MySQL buffer pool 降到 256M 并关掉 `performance_schema`、配日志轮转。

### 2.3 装 Python 3.13

Ubuntu 22.04 自带 3.10、24.04 自带 3.12，**都不够**（项目要求 `>=3.13`）。二选一：

**方案 A：deadsnakes PPA（推荐，系统级）**

```bash
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update
apt install -y python3.13 python3.13-venv python3.13-dev
python3.13 -V
```

**方案 B：uv 自带（A 失败时用）**

```bash
apt install -y python3-pip
pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple uv
/usr/local/bin/uv python install 3.13
python3.13 -V || /usr/local/bin/uv python find 3.13
```

### 2.4 起 Qdrant

```bash
mkdir -p /var/lib/qdrant
docker run -d --name qdrant --restart=always \
  -p 127.0.0.1:6333:6333 \
  -v /var/lib/qdrant:/qdrant/storage \
  --log-opt max-size=10m --log-opt max-file=3 \
  qdrant/qdrant:v1.16

sleep 3 && curl -s http://127.0.0.1:6333/ | grep -o '"version":"[^"]*"'
```

端口**只绑 127.0.0.1**，公网访问不到向量库。

> 版本必须 ≥ 本地（1.16.3），低版本恢复不了快照。

---

## 3. 【服务器】部署代码与依赖

```bash
mkdir -p /opt/law-firm-cms
tar -xzf /tmp/law-firm-src.tar.gz -C /opt/law-firm-cms
chown -R lawfirm:lawfirm /opt/law-firm-cms
ls /opt/law-firm-cms      # 应看到 backend  deploy  db
```

### 3.1 装依赖

```bash
cd /opt/law-firm-cms/backend
sudo -u lawfirm python3.13 -m venv .venv
sudo -u lawfirm .venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
sudo -u lawfirm .venv/bin/pip install -r requirements-prod.txt \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

`requirements-prod.txt` 是本地用 `uv export` 从 `uv.lock` 生成的**锁定版本清单**（144 行），保证服务器装到的版本和本地一致。

> 项目没有 `[build-system]`，`pip install -e .` 会失败，所以只装依赖、不装项目本身——`app` 包靠 systemd 的 `WorkingDirectory` 直接 import。

### 3.2 目录与权限

```bash
mkdir -p /var/lib/law-firm/uploads /var/www/law-firm
chown -R lawfirm:lawfirm /var/lib/law-firm/uploads
cp -a /tmp/uploads/. /var/lib/law-firm/uploads/     # 历史附件 1.4 MB
cp -a /tmp/dist /var/www/law-firm/dist              # 前端产物
chown -R www-data:www-data /var/www/law-firm/dist   # nginx 读
ls /var/www/law-firm/dist/index.html && echo OK
```

---

## 4. 【服务器】数据迁移

### 4.1 建库 + 专用账号

```bash
mysql -e "CREATE DATABASE law_firm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

mysql -e "CREATE USER 'lawfirm_app'@'127.0.0.1' IDENTIFIED BY '<DB_PASSWORD>';
GRANT SELECT,INSERT,UPDATE,DELETE ON law_firm.* TO 'lawfirm_app'@'127.0.0.1';
FLUSH PRIVILEGES;"
```

应用账号只要 DML 权限，建表改表由你手动执行——这样即使应用出问题也删不掉表。

### 4.2 导入数据

```bash
mysql law_firm < /tmp/law_firm.sql
```

### 4.3 校验行数

```bash
mysql law_firm -e "
SELECT (SELECT COUNT(*) FROM user) AS users,
       (SELECT COUNT(*) FROM client_profile) AS clients,
       (SELECT COUNT(*) FROM cases) AS cases,
       (SELECT COUNT(*) FROM contract) AS contracts,
       (SELECT COUNT(*) FROM payment) AS payments,
       (SELECT COUNT(*) FROM law_article) AS laws,
       (SELECT COUNT(*) FROM kb_document) AS kb;"
```

数字要和你本地一致（本地跑同一条 SQL 对照）。不一致说明 dump 不完整，**先别继续**。

### 4.4 导入向量库

```bash
cd /opt/law-firm-cms
bash deploy/vector-snapshot.sh import /tmp/law_kb-20261107-171114.snapshot
```

预期输出 `points 2297 / dimension 2560 / Cosine` 和 `√ 向量库可用`。

---

## 5. 【服务器】配置 .env

```bash
cd /opt/law-firm-cms/backend
cp .env.prod.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # 复制这串，下面用
vi .env
chown lawfirm:lawfirm .env && chmod 600 .env
```

逐项替换（其余保持模板值）：

```ini
APP_ENV=prod
DEBUG=false
DATABASE_URL=mysql+aiomysql://lawfirm_app:<DB_PASSWORD>@127.0.0.1:3306/law_firm?charset=utf8mb4
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
JWT_SECRET=<上一步生成的那串>
CORS_ORIGINS=http://<SERVER_IP>
UPLOAD_DIR=/var/lib/law-firm/uploads
OUTBOUND_PROXY=
LLM_API_KEY=<百炼 Key>
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=qwen3.7-text-embedding
EMBEDDING_DIM=2560
EMBEDDING_API_KEY=<留空则复用 LLM_API_KEY>
FIRM_NAME=<律所全称>
SCHEDULER_ENABLED=true
```

`SEED_*` 三项不用填——本次是迁移现有数据，不跑 `create_users.py`。

---

## 6. 【服务器】启动后端

```bash
cp /opt/law-firm-cms/deploy/law-firm-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now law-firm-api
sleep 5
systemctl status law-firm-api --no-pager
journalctl -u law-firm-api -n 30 --no-pager
```

日志里应看到 `字典缓存已加载` 和 `Uvicorn running on http://127.0.0.1:8000`。

```bash
curl -s http://127.0.0.1:8000/health/db      # 期望 {"status":"ok",...}
```

---

## 7. 【服务器】配 nginx

```bash
rm -f /etc/nginx/sites-enabled/default

cp /opt/law-firm-cms/deploy/nginx-http.conf /etc/nginx/sites-available/law-firm
ln -sf /etc/nginx/sites-available/law-firm /etc/nginx/sites-enabled/law-firm
nginx -t && systemctl reload nginx
```

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/           # 200
curl -s http://127.0.0.1/api/dicts -o /dev/null -w "%{http_code}\n"  # 401（未登录，正常）
```

### 7.1 防火墙

```bash
ufw allow 22/tcp && ufw allow 80/tcp && ufw --force enable
```

云厂商的**安全组**也要放行 80（这一步在控制台，不在服务器里）。

---

## 8. 验收

```bash
cd /opt/law-firm-cms/backend
sudo -u lawfirm .venv/bin/python scripts/prod_check.py --probe-ai
```

期望末尾 `0 FAIL`，并且看到：
- `Qdrant — law_kb / 2297 个点 / 2560 维`
- `Embedding 接口 ... 2560 维`
- `向量库为空` / `向量维度不匹配` 都不能出现

浏览器打开 `http://<SERVER_IP>`，用 `tianting / admin` 登录。

### ⚠️ 登录后第一件事：改密码

迁移过去的管理员是开发环境的弱口令，生产上等于没有密码。立刻执行：

```bash
cd /opt/law-firm-cms/backend
SEED_ADMIN_PASSWORD='<12位以上强密码>' \
SEED_LAWYER_PASSWORD='<12位以上强密码>' \
SEED_CLIENT_PASSWORD='<12位以上强密码>' \
sudo -u lawfirm .venv/bin/python scripts/create_users.py --reset
```

然后用新密码重新登录确认。

---

## 9. 故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 502 Bad Gateway | 后端没起 / 崩了 | `journalctl -u law-firm-api -n 50` |
| 页面空白、资源 404 | dist 路径不对 | `nginx -T \| grep root`，确认 `/var/www/law-firm/dist` |
| 刷新 /admin/xxx 变 404 | 缺 `try_files` | 检查 location / 段 |
| AI 回答一直转圈几十秒才出 | SSE 被缓冲 | 确认 `/api/ai/` 段有 `proxy_buffering off` |
| 上传附件报 413 | nginx 限制 | `client_max_body_size 25m` |
| 时间差 8 小时 | 时区 | service 里 `Environment=TZ=Asia/Shanghai` |
| AI 说"资料不足" | 向量库空 / Qdrant 挂了 | `docker ps`、`vector-snapshot.sh verify` |
| 登录后立刻 401 | JWT_SECRET 改了但旧 token 还在 | 清浏览器 localStorage 重登 |
| 字典下拉空 | 缓存没加载 | `journalctl` 搜「字典缓存」 |

---

## 10. 以后怎么发版

```bash
# 【本地】
cd /d/law-firm-cms/frontend && npm run build
cd /d/law-firm-cms && tar -czf .snap/backend.tar.gz --exclude='.venv' --exclude='__pycache__' --exclude='uploads' backend
scp .snap/backend.tar.gz root@<SERVER_IP>:/tmp/
scp -r frontend/dist root@<SERVER_IP>:/tmp/dist-new

# 【服务器】
systemctl stop law-firm-api
tar -xzf /tmp/backend.tar.gz -C /opt/law-firm-cms
rm -rf /var/www/law-firm/dist && mv /tmp/dist-new /var/www/law-firm/dist
chown -R lawfirm:lawfirm /opt/law-firm-cms
chown -R www-data:www-data /var/www/law-firm/dist
systemctl start law-firm-api && systemctl reload nginx
```

依赖有变动时（`pyproject.toml` 改了），本地重新 `uv export` 生成 `requirements-prod.txt` 一起传，服务器重跑 `pip install -r`。

---

## 11. 备份（配好就跑一次）

```bash
cat > /opt/law-firm-cms/deploy/backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
D=/var/backups/law-firm/$(date +%F)
mkdir -p "$D"
mysqldump --single-transaction --quick --routines --triggers law_firm | gzip > "$D/db.sql.gz"
tar -czf "$D/uploads.tar.gz" -C /var/lib/law-firm uploads
curl -s --noproxy '*' -X POST http://127.0.0.1:6333/collections/law_kb/snapshots >/dev/null
find /var/backups/law-firm -type d -mtime +14 -exec rm -rf {} +
EOF
chmod +x /opt/law-firm-cms/deploy/backup.sh

echo "30 3 * * * root /opt/law-firm-cms/deploy/backup.sh" > /etc/cron.d/law-firm-backup
```
