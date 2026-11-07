#!/usr/bin/env bash
# ============================================================================
# 律所客户智能管理系统 —— 2C2G 主机加固脚本
#
# 目的：把一台 2 vCPU / 2GB 的机器调到「MySQL + Qdrant + uvicorn + nginx
# 同时在线也不 OOM」的状态。默认只打印将要做什么，加 --apply 才真正执行。
#
#   sudo bash deploy/host-setup.sh            # 预览
#   sudo bash deploy/host-setup.sh --apply    # 执行
#
# 做四件事：
#   1. 加 2GB swap（swappiness=10）：给 PDF/Excel 解析峰值兜底，不做日常内存；
#   2. MySQL 调参：buffer pool 256M、关 performance_schema、max_connections=80；
#   3. 建目录与日志轮转：/opt/law-firm-cms、/var/log/law-firm；
#   4. 打印内存预算，确认「服务器上不跑任何本地模型」。
#
# 注意：本脚本**不**安装 MySQL/Qdrant/Python，也不改防火墙与证书。
# ============================================================================
set -euo pipefail

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 执行（sudo bash $0 ${1:-}）" >&2
  exit 1
fi

SWAP_FILE=/swapfile
SWAP_MB=2048
MYSQL_CNF=/etc/mysql/mysql.conf.d/zz-lawfirm.cnf

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
run() {
  if [[ $APPLY -eq 1 ]]; then
    echo "  + $*"
    eval "$@"
  else
    echo "  [预览] $*"
  fi
}

say "当前内存 / swap"
free -m | sed 's/^/  /'

# ---------------------------------------------------------------- 1. swap
say "1. swap"
swap_total_mb=$(awk '/SwapTotal/{print int($2/1024)}' /proc/meminfo)
if [[ $swap_total_mb -ge 1900 ]]; then
  echo "  已有 ${swap_total_mb}MB swap，跳过"
else
  echo "  当前仅 ${swap_total_mb}MB，将创建 ${SWAP_MB}MB 的 $SWAP_FILE"
  if [[ ! -f $SWAP_FILE ]]; then
    run "fallocate -l ${SWAP_MB}M $SWAP_FILE || dd if=/dev/zero of=$SWAP_FILE bs=1M count=${SWAP_MB}"
    run "chmod 600 $SWAP_FILE"
    run "mkswap $SWAP_FILE"
  else
    echo "  $SWAP_FILE 已存在，跳过创建"
  fi
  run "swapon --show | grep -q $SWAP_FILE || swapon $SWAP_FILE"
  if ! grep -q "^$SWAP_FILE" /etc/fstab 2>/dev/null; then
    run "echo '$SWAP_FILE none swap sw 0 0' >> /etc/fstab"
  fi
  # swappiness=10：只有真紧张时才用 swap，避免正常业务被磁盘 IO 拖慢
  run "printf 'vm.swappiness=10\\nvm.vfs_cache_pressure=50\\n' > /etc/sysctl.d/99-lawfirm.conf"
  run "sysctl --system >/dev/null"
fi

# ---------------------------------------------------------------- 2. MySQL
say "2. MySQL 调参"
if [[ -d /etc/mysql/mysql.conf.d ]]; then
  echo "  写入 $MYSQL_CNF（需要重启 mysqld 生效）"
  if [[ $APPLY -eq 1 ]]; then
    cat > "$MYSQL_CNF" <<'EOF'
# 律所 CRM：2C2G 机器的内存约束配置
[mysqld]
# 默认 128M 偏小，256M 足够支撑本系统的查询量，再大就要跟 Qdrant/uvicorn 抢
innodb_buffer_pool_size = 256M
# performance_schema 常驻 100MB+，本系统不做性能剖析，直接关掉
performance_schema = OFF
max_connections = 80
# 单条 SQL 的临时表/排序缓冲，默认值在小内存机器上容易被并发放大
tmp_table_size = 32M
max_heap_table_size = 32M
sort_buffer_size = 1M
join_buffer_size = 1M
# 字符集固定 utf8mb4，避免导入历史数据时中文乱码
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
EOF
    echo "  已写入"
  else
    echo "  [预览] cat > $MYSQL_CNF <<< 见脚本内容"
  fi
  echo "  生效：systemctl restart mysql"
else
  echo "  未发现 /etc/mysql/mysql.conf.d，跳过（非 Debian/Ubuntu 或 MySQL 未装）"
fi

# ---------------------------------------------------------------- 3. 目录
say "3. 目录与日志轮转"
run "install -d -m 755 /opt/law-firm-cms"
run "install -d -m 755 /var/log/law-firm"
if [[ $APPLY -eq 1 ]]; then
  cat > /etc/logrotate.d/law-firm <<'EOF'
/var/log/law-firm/*.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
  echo "  + 写入 /etc/logrotate.d/law-firm（保留 14 天）"
else
  echo "  [预览] 写入 /etc/logrotate.d/law-firm（保留 14 天）"
fi

# ---------------------------------------------------------------- 4. 预算
say "4. 内存预算（本系统在 2C2G 上的目标占用）"
cat <<'EOF'
  系统 + systemd         150~250 MB
  MySQL（本脚本调参后）   250~350 MB
  Qdrant（2297 条向量）   150~250 MB
  docker（仅跑 Qdrant）   100~150 MB
  uvicorn 单 worker       200~300 MB
  nginx                    10~ 20 MB
  ------------------------------------
  合计                   0.9~1.3 GB   峰值（PDF 解析）再加 200~400 MB

  结论：2GB 够用，但**不要**在服务器上跑本地向量模型（bge-large 要 1.4~1.8GB）。
  常驻进程只有：nginx、uvicorn、MySQL、Qdrant（Docker 单容器；dockerd + containerd
  另占 100~150MB，已计入上表）。不要在这台机器上跑前端构建（vite 峰值 1GB），
  也不要用这个 Docker 跑别的镜像。
EOF

say "完成"
if [[ $APPLY -eq 0 ]]; then
  echo "以上均为预览，未做任何修改。确认无误后加 --apply 执行。"
else
  echo "已应用。请重启 mysqld 与 nginx 使配置生效，再运行 prod_check.py。"
fi
