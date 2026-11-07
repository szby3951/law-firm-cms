#!/usr/bin/env bash
# =============================================================================
# 知识库向量快照：导出 / 导入 / 校验
#
# 用途：把本地已经建好的 law_kb 向量库整体搬到服务器，服务器上就不用再跑
#       scripts/kb_builder.py --reindex（也就不会产生 embedding 调用费用）。
#
# 关键前提：快照里的 point id 与 MySQL 的 law_article.vector_id、
#          kb_document.vector_id 是一一对应的 UUID，所以**快照必须与同一份
#          MySQL 备份配套使用**。不能拿 A 机器的 MySQL 配 B 机器的旧快照，
#          否则检索命中的 point id 在库里查不到对应条文。
#
# 用法：
#   ./vector-snapshot.sh export [输出目录]   # 本机执行，产出 <collection>-<时间>.snapshot
#   ./vector-snapshot.sh import <快照文件>   # 服务器执行（会覆盖同名 collection）
#   ./vector-snapshot.sh verify              # 两端都可执行，查点数 / 维度
#
# 环境变量：
#   QDRANT_URL          默认 http://127.0.0.1:6333
#   QDRANT_API_KEY      默认空；生产若开了鉴权要带上
#   QDRANT_COLLECTION   默认 law_kb
#
# 注意：快照跨版本恢复要求目标 Qdrant 版本 >= 源版本（1.16 的快照不要往 1.12 导）。
# =============================================================================
set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
QDRANT_API_KEY="${QDRANT_API_KEY:-}"
COLLECTION="${QDRANT_COLLECTION:-law_kb}"
DIM="${EMBEDDING_DIM:-2560}"

api() {
    local method="$1" path="$2"
    shift 2
    if [ -n "$QDRANT_API_KEY" ]; then
        curl -sS -f --noproxy '*' -X "$method" \
            -H "api-key: $QDRANT_API_KEY" "$@" "${QDRANT_URL}${path}"
    else
        curl -sS -f --noproxy '*' -X "$method" "$@" "${QDRANT_URL}${path}"
    fi
}

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少命令：$1" >&2; exit 1; }; }

collection_info() {
    api GET "/collections/${COLLECTION}"
}

cmd_verify() {
    local info points dim distance
    if ! info="$(collection_info 2>/dev/null)"; then
        echo "× collection ${COLLECTION} 不存在或 Qdrant 不可达（${QDRANT_URL}）" >&2
        return 1
    fi
    points="$(printf '%s' "$info" | grep -o '"points_count":[0-9]*' | head -1 | cut -d: -f2)"
    dim="$(printf '%s' "$info" | grep -o '"size":[0-9]*' | head -1 | cut -d: -f2)"
    distance="$(printf '%s' "$info" | grep -o '"distance":"[A-Za-z]*"' | head -1 | cut -d'"' -f4)"

    echo "collection : ${COLLECTION}"
    echo "points     : ${points:-0}"
    echo "dimension  : ${dim:-?} (期望 ${DIM})"
    echo "distance   : ${distance:-?} (期望 Cosine)"

    [ "${points:-0}" -gt 0 ] || { echo "× 向量点数为 0，检索会全部落空" >&2; return 1; }
    [ "${dim:-0}" = "$DIM" ] || { echo "× 维度与 EMBEDDING_DIM 不一致，写入/检索会失败" >&2; return 1; }
    echo "√ 向量库可用"
}

cmd_export() {
    need curl
    local out_dir="${1:-.}" resp name file
    mkdir -p "$out_dir"

    echo "== 在当前 Qdrant（${QDRANT_URL}）上创建快照 =="
    resp="$(api POST "/collections/${COLLECTION}/snapshots")"
    name="$(printf '%s' "$resp" | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    [ -n "$name" ] || { echo "× 未能解析快照名：$resp" >&2; return 1; }
    echo "快照名：$name"

    file="${out_dir%/}/${COLLECTION}-$(date +%Y%m%d-%H%M%S).snapshot"
    echo "== 下载到 ${file} =="
    # 下载走 GET，不能用 api() 的 -X POST
    if [ -n "$QDRANT_API_KEY" ]; then
        curl -sS -f --noproxy '*' -H "api-key: $QDRANT_API_KEY" \
            -o "$file" "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${name}"
    else
        curl -sS -f --noproxy '*' -o "$file" \
            "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${name}"
    fi
    echo "√ 已导出：$file （$(du -h "$file" | cut -f1)）"
    echo
    echo "下一步：scp 到服务器后执行"
    echo "  ./vector-snapshot.sh import $(basename "$file")"
}

cmd_import() {
    need curl
    local file="${1:-}"
    [ -n "$file" ] && [ -f "$file" ] || { echo "用法：$0 import <快照文件>" >&2; return 1; }

    echo "== 确保 collection ${COLLECTION} 存在 =="
    # 已存在时 Qdrant 返回 400，忽略即可；不存在则建一个同维度的空集合，
    # 紧接着的 upload 会用快照里的内容整体替换它。
    api PUT "/collections/${COLLECTION}" \
        -H "Content-Type: application/json" \
        -d "{\"vectors\":{\"size\":${DIM},\"distance\":\"Cosine\"}}" >/dev/null 2>&1 || true

    echo "== 上传快照并恢复（会覆盖 ${COLLECTION} 现有数据）=="
    api POST "/collections/${COLLECTION}/snapshots/upload?priority=snapshot" \
        -F "snapshot=@${file}" >/dev/null
    echo "√ 恢复完成"
    echo
    cmd_verify
}

case "${1:-}" in
    export) shift; cmd_export "$@" ;;
    import) shift; cmd_import "$@" ;;
    verify) cmd_verify ;;
    *)
        sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
