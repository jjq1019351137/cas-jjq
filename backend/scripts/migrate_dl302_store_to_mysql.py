from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import pymysql  # noqa: E402

TABLES = [
    "dl302_copy_tasks",
    "dl302_copy_task_items",
    "dl302_copy_task_candidates",
    "dl302_cas_tasks",
    "dl302_cas_task_items",
    "dl302_rapid_records",
    "dl302_cas_records",
    "dl302_local_file_hash_cache",
]

TIME_COLS = {"created_at", "updated_at", "finished_at"}
BATCH = 500

_GO_TIME_RE = re.compile(r"\s+m=[+-][\d.]+$")


def parse_go_time(raw):
    if raw is None:
        return None
    text = _GO_TIME_RE.sub("", str(raw).strip())
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z %Z", "%Y-%m-%d %H:%M:%S %z %Z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            # Python %f 只吃 6 位，Go 是 9 位纳秒 → 先截断
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.)(\d+)(.*)$", text)
            candidate = f"{m.group(1)}{m.group(2)[:6]}{m.group(3)}" if m else text
            dt = datetime.strptime(candidate, fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {raw!r}")


def parse_mysql_url(url: str):
    m = re.match(r"^mysql(?:\+\w+)?://([^:/@]+)(?::([^@]*))?@([^:/]+)(?::(\d+))?/([^?]+)", url)
    if not m:
        raise SystemExit(f"[FATAL] 非法 MySQL URL: {url}")
    from urllib.parse import unquote

    return {
        "user": unquote(m.group(1)),
        "password": unquote(m.group(2) or ""),
        "host": m.group(3),
        "port": int(m.group(4) or 3306),
        "database": m.group(5),
        "charset": "utf8mb4",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(BACKEND_DIR / "data" / "dl302.db"))
    parser.add_argument("--dest-url", default=None)
    parser.add_argument("--wipe", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not Path(args.source).exists():
        raise SystemExit(f"[FATAL] 源文件不存在: {args.source}")
    dest_url = args.dest_url
    if not dest_url:
        from app.core.settings import settings

        dest_url = settings.database_url
    if not dest_url.startswith("mysql"):
        raise SystemExit(f"[FATAL] 目标必须是 MySQL URL: {dest_url.split('://', 1)[0]}://...")

    src = sqlite3.connect(args.source)
    src.row_factory = sqlite3.Row
    dst = pymysql.connect(**parse_mysql_url(dest_url))
    cur = dst.cursor()

    cur.execute("SHOW TABLES")
    dst_tables = {r[0] for r in cur.fetchall()}
    missing = [t for t in TABLES if t not in dst_tables]
    if missing:
        raise SystemExit(f"[FATAL] 目标缺表 {missing}，请先用 MySQL 配置启动一次 dl302 建表")

    total = skipped_total = 0
    for table in TABLES:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        if args.dry_run:
            print(f"[DRY] {table}: {len(rows)} 行")
            continue
        if args.wipe:
            cur.execute(f"DELETE FROM `{table}`")
        if not rows:
            continue
        cols = rows[0].keys()
        sql = f"INSERT INTO `{table}` ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"

        def convert(row):
            return [parse_go_time(row[c]) if c in TIME_COLS else row[c] for c in cols]

        copied = skipped = 0
        batch = []
        for row in rows:
            batch.append(convert(row))
            if len(batch) >= BATCH:
                copied, skipped = _flush(cur, sql, batch, table, copied, skipped)
                batch = []
        copied, skipped = _flush(cur, sql, batch, table, copied, skipped)
        dst.commit()
        total += copied
        skipped_total += skipped
        mark = "" if skipped == 0 else f"（跳过 {skipped}）"
        print(f"[OK] {table}: {copied}/{len(rows)} 行{mark}")

    if not args.dry_run:
        print(f"[DONE] 共复制 {total} 行，跳过 {skipped_total} 行")
        mismatch = 0
        for table in TABLES:
            s = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            d = cur.fetchone()[0]
            if s != d:
                mismatch += 1
                print(f"[WARN] 行数不一致 {table}: sqlite={s} mysql={d}")
        if mismatch == 0:
            print("[VERIFY] 全部表行数一致 ✔")
    src.close()
    dst.close()


def _flush(cur, sql, batch, table, copied, skipped):
    if not batch:
        return copied, skipped
    try:
        cur.executemany(sql, batch)
        return copied + len(batch), skipped
    except Exception:
        for row in batch:
            try:
                cur.execute(sql, row)
                copied += 1
            except Exception as exc:
                skipped += 1
                print(f"  [SKIP] {table} id={row[0]!r}: {str(exc).splitlines()[0][:160]}")
        return copied, skipped


if __name__ == "__main__":
    main()
