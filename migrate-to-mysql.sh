#!/usr/bin/env sh
# =============================================================================
# 一键迁移：SQLite -> MySQL（backend 业务库 + dl302 状态库）
#
# 用法：
#   ./migrate-to-mysql.sh [-y] [--dry-run]
#     -y         跳过确认提示（容器 / 自动化场景）
#     --dry-run  只做连通性/版本校验与行数统计，不写入
#
# 前置条件：
#   1. backend/.env（或环境变量）已配置 MySQL：
#        DB_DRIVER=mysql
#        DATABASE_URL=mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4
#   2. 目标库已存在且账号有 ALL PRIVILEGES；
#   3. 源 SQLite 文件位于 backend/data/（app.db / dl302.db，缺哪个跳过哪个）。
#
# 执行内容（幂等，可重复运行；数据导入使用 --wipe 全量覆盖）：
#   [1/4] alembic upgrade head          -> 在 MySQL 建/升级 backend 表结构
#   [2/4] 迁移 app.db 业务数据           -> migrate_sqlite_to_mysql.py --wipe
#   [3/4] dl302 init-store              -> 在 MySQL 建 dl302_* 状态表
#   [4/4] 迁移 dl302.db 状态数据         -> migrate_dl302_store_to_mysql.py --wipe
#
# 容器内：docker exec -it <容器名> /app/migrate-to-mysql.sh -y
# 迁移完成后重启 backend 与 dl302（容器直接 docker restart）。
# =============================================================================
set -eu

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
DATA_DIR="$BACKEND_DIR/data"

ASSUME_YES=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

# ---- python 解释器：优先 backend venv，容器内退回系统 python3 ----
if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PY="$BACKEND_DIR/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi
[ -n "$PY" ] || { echo "[FATAL] 未找到 python"; exit 1; }

# ---- dl302 二进制：容器 /app/dl302 ----
DL302_BIN="${DL302_BIN:-}"
if [ -z "$DL302_BIN" ]; then
  for cand in /app/dl302 "$ROOT_DIR/dl302-master-linux-amd64"; do
    if [ -x "$cand" ]; then DL302_BIN="$cand"; break; fi
  done
fi

# ---- 校验目标必须是 MySQL ----
cd "$BACKEND_DIR"
TARGET_URL="$("$PY" -c '
from app.core.settings import settings
import re
url = settings.database_url
print(url)
' 2>/dev/null | tail -1)"
case "$TARGET_URL" in
  mysql*) ;;
  *)
    echo "[FATAL] 当前生效的 DATABASE_URL 不是 MySQL: ${TARGET_URL%%://*}://..."
    echo "        请先在 backend/.env 配置 DB_DRIVER=mysql + DATABASE_URL=mysql+pymysql://...（见 docs/DATABASE.md）"
    exit 1
    ;;
esac
MASKED="$(printf '%s' "$TARGET_URL" | sed 's#://\([^:/@]*\):[^@]*@#://\1:***@#')"
echo "==> 迁移目标: $MASKED"
echo "==> 源文件:  app.db=$([ -f "$DATA_DIR/app.db" ] && echo 存在 || echo 缺失)  dl302.db=$([ -f "$DATA_DIR/dl302.db" ] && echo 存在 || echo 缺失)"

if [ "$DRY_RUN" -eq 0 ] && [ "$ASSUME_YES" -eq 0 ]; then
  printf "将用 SQLite 数据全量覆盖目标 MySQL 中的同名表，确认继续？[y/N] "
  read -r answer
  case "$answer" in y|Y|yes|YES) ;; *) echo "已取消"; exit 0 ;; esac
fi

EXTRA_FLAG="--wipe"
[ "$DRY_RUN" -eq 1 ] && EXTRA_FLAG="--dry-run"

echo ""
echo "==> [1/4] backend 表结构 (alembic upgrade head)"
"$PY" -m alembic upgrade head >/dev/null
echo "    ok"

if [ -f "$DATA_DIR/app.db" ]; then
  echo "==> [2/4] backend 业务数据 (app.db -> MySQL)"
  "$PY" scripts/migrate_sqlite_to_mysql.py $EXTRA_FLAG
else
  echo "==> [2/4] 跳过：$DATA_DIR/app.db 不存在（全新安装无存量数据）"
fi

echo "==> [3/4] dl302 状态表结构 (init-store)"
if [ -n "$DL302_BIN" ] && [ -x "$DL302_BIN" ]; then
  (cd "$ROOT_DIR" && "$DL302_BIN" init-store)
else
  echo "[FATAL] 未找到 dl302 二进制（尝试过 /app/dl302、$ROOT_DIR/dl302-master-linux-amd64）。 $0"
  exit 1
fi

if [ -f "$DATA_DIR/dl302.db" ]; then
  echo "==> [4/4] dl302 状态数据 (dl302.db -> MySQL)"
  "$PY" scripts/migrate_dl302_store_to_mysql.py $EXTRA_FLAG
else
  echo "==> [4/4] 跳过：$DATA_DIR/dl302.db 不存在"
fi

echo ""
if [ "$DRY_RUN" -eq 1 ]; then
  echo "==> DRY-RUN 完成（未写入任何数据）"
else
  echo "==> 迁移完成 ✔  请重启 backend 与 dl302（容器：docker restart <容器名>）"
fi
