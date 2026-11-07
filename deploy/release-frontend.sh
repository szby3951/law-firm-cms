#!/usr/bin/env bash
#
# 前端发版：本地构建 → 整目录上传 → 原子切换 → reload nginx
#
# 在【本地】执行（Windows 用 Git Bash），不要在服务器上跑：
#   服务器是 2C2G，vite 构建峰值约 1GB，会和 MySQL/Qdrant 抢内存导致 OOM。
#
# 用法：
#   bash deploy/release-frontend.sh root@121.40.199.117
#   bash deploy/release-frontend.sh root@1.2.3.4 /var/www/law-firm/dist
#
# 可覆盖的环境变量：
#   TARGET    远端目录，默认 /var/www/law-firm/dist
#   WEB_USER  远端属主，默认 www-data
#   SSH_PORT  SSH 端口，默认 22
#   SKIP_BUILD=1  跳过 npm run build（dist 已经是新的时候用）
#   KEEP_BAK=1    保留上一版 dist.bak（默认也会保留，设为 0 则删除）
#
set -euo pipefail

SERVER="${1:-}"
TARGET="${2:-${TARGET:-/var/www/law-firm/dist}}"
WEB_USER="${WEB_USER:-www-data}"
SSH_PORT="${SSH_PORT:-22}"
SKIP_BUILD="${SKIP_BUILD:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
DIST_DIR="$FRONTEND_DIR/dist"

die() { echo "错误：$*" >&2; exit 1; }

[ -n "$SERVER" ] || die "缺少服务器地址。用法：bash deploy/release-frontend.sh root@<IP>"
case "$TARGET" in
  /?*) : ;;
  *) die "TARGET 必须是绝对路径，当前为：$TARGET" ;;
esac
[ "$TARGET" != "/" ] || die "TARGET 不能是根目录"
[ -d "$FRONTEND_DIR" ] || die "找不到前端目录：$FRONTEND_DIR"

SSH_OPTS=(-p "$SSH_PORT" -o StrictHostKeyChecking=accept-new)

# ---------- 1. 构建 ----------
if [ "$SKIP_BUILD" = "1" ]; then
  echo "==> 跳过构建（SKIP_BUILD=1），使用现有 dist"
else
  echo "==> 构建前端"
  command -v npm >/dev/null 2>&1 || die "本机找不到 npm，请确认 Node 已安装并在 PATH 中"
  ( cd "$FRONTEND_DIR" && npm run build )
fi

[ -f "$DIST_DIR/index.html" ] || die "构建产物缺少 index.html：$DIST_DIR"

FILE_COUNT=$(find "$DIST_DIR" -type f | wc -l | tr -d ' ')
DIST_SIZE=$(du -sh "$DIST_DIR" | cut -f1)
echo "==> 产物：$FILE_COUNT 个文件，$DIST_SIZE"

# 兜底检查：入口 HTML 必须引用 assets，否则说明构建不完整
grep -q "assets/" "$DIST_DIR/index.html" || die "index.html 未引用 assets，构建结果异常"

# ---------- 2. 连通性 ----------
echo "==> 检查 SSH：$SERVER"
ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$SERVER" "echo ok" >/dev/null 2>&1 \
  || die "SSH 连不上（需要免密登录）。先在终端跑一次 ssh $SERVER 确认能进，或配好密钥"

# ---------- 3. 上传并原子切换 ----------
# 先解到同级 dist.new，再 mv 替换：mv 同分区是原子的，nginx 不会出现 404 空窗。
# 目录内逐个覆盖（tar --delete / rm + 解包）会在清空瞬间让线上 404，故不用那种做法。
echo "==> 上传并切换（目标 $TARGET）"
tar -czf - -C "$DIST_DIR" . | ssh "${SSH_OPTS[@]}" "$SERVER" "
  set -e
  NEW='$TARGET.new'
  rm -rf \"\$NEW\"
  mkdir -p \"\$NEW\"
  tar -xzf - -C \"\$NEW\"
  chown -R '$WEB_USER:$WEB_USER' \"\$NEW\"
  if [ -d '$TARGET' ]; then
    rm -rf '$TARGET.bak'
    mv '$TARGET' '$TARGET.bak'
  fi
  mv \"\$NEW\" '$TARGET'
  echo \"  - 已部署 \$(find '$TARGET' -type f | wc -l) 个文件\"
  nginx -t
  systemctl reload nginx
  echo '  - nginx 已重载'
"

# ---------- 4. 验证 ----------
echo "==> 验证"
CODE=$(ssh "${SSH_OPTS[@]}" "$SERVER" \
  "curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' http://127.0.0.1/" || echo "000")
if [ "$CODE" = "200" ]; then
  echo "  - 首页 HTTP 200"
else
  echo "  ! 首页返回 $CODE，请检查 nginx 与 $TARGET 权限" >&2
fi

echo
echo "完成。回滚上一版："
echo "  ssh -p $SSH_PORT $SERVER \"rm -rf $TARGET && mv $TARGET.bak $TARGET && systemctl reload nginx\""
echo
echo "提示：assets 文件名带内容哈希且缓存 30 天，旧文件会随 dist.bak 一起被替换，"
echo "      无需手动清理；用户浏览器因 index.html 设了 no-store，刷新即拿到新版本。"
