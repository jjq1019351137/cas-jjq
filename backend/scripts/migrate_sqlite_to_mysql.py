from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, insert, select, text  # noqa: E402

from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  确保全部模型注册到 metadata

BATCH_SIZE = 1000


def _fail(msg: str) -> None:
    print(f"[FATAL] {msg}")
    sys.exit(1)


def _alembic_version(engine) -> str | None:
    with engine.connect() as conn:
        try:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:
            return None


def migrate(source_path: str, dest_url: str, *, wipe: bool, dry_run: bool) -> None:
    src_file = Path(source_path)
    if not src_file.exists():
        _fail(f"源 SQLite 文件不存在: {src_file}")
    if not dest_url.startswith("mysql"):
        _fail(f"目标必须是 MySQL URL，当前: {dest_url.split('://', 1)[0]}://...")

    src_engine = create_engine(f"sqlite:///{src_file}", future=True)
    dst_engine = create_engine(dest_url, future=True, pool_pre_ping=True)

    src_ver, dst_ver = _alembic_version(src_engine), _alembic_version(dst_engine)
    if not dst_ver:
        _fail("目标库没有 alembic_version（请先启动 backend 或执行 alembic upgrade head 建表）")
    if src_ver != dst_ver:
        _fail(f"迁移版本不一致: sqlite={src_ver} mysql={dst_ver}，请先将两侧升级到同一 head")
    print(f"[OK] alembic_version 一致: {src_ver}")

    tables = [t for t in Base.metadata.sorted_tables if t.name != "alembic_version"]

    total_copied = 0
    total_skipped = 0
    with src_engine.connect() as src, dst_engine.connect() as dst:
        dst.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            for table in tables:
                src_count = src.execute(select(text("COUNT(*)")).select_from(table)).scalar() or 0
                if dry_run:
                    print(f"[DRY] {table.name}: {src_count} 行")
                    continue
                if wipe:
                    dst.execute(text(f"DELETE FROM `{table.name}`"))
                if src_count == 0:
                    continue

                copied = skipped = 0
                rows_iter = src.execute(select(table)).mappings()
                batch: list[dict] = []

                def flush(batch: list[dict]) -> tuple[int, int]:
                    if not batch:
                        return 0, 0
                    try:
                        dst.execute(insert(table), batch)
                        return len(batch), 0
                    except Exception:
                        ok = bad = 0
                        for row in batch:
                            try:
                                dst.execute(insert(table), [row])
                                ok += 1
                            except Exception as exc:
                                bad += 1
                                key = row.get("id") or next(iter(row.values()), "?")
                                print(f"  [SKIP] {table.name} row={key!r}: {str(exc).splitlines()[0][:160]}")
                        return ok, bad

                for row in rows_iter:
                    batch.append(dict(row))
                    if len(batch) >= BATCH_SIZE:
                        ok, bad = flush(batch)
                        copied += ok
                        skipped += bad
                        batch = []
                ok, bad = flush(batch)
                copied += ok
                skipped += bad

                dst.commit()
                total_copied += copied
                total_skipped += skipped
                mark = "" if skipped == 0 else f"（跳过 {skipped}）"
                print(f"[OK] {table.name}: {copied}/{src_count} 行{mark}")
        finally:
            dst.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            dst.commit()

    if not dry_run:
        print(f"[DONE] 共复制 {total_copied} 行，跳过 {total_skipped} 行")
        # 校验目标行数
        with src_engine.connect() as src, dst_engine.connect() as dst:
            mismatch = 0
            for table in tables:
                s = src.execute(select(text("COUNT(*)")).select_from(table)).scalar() or 0
                d = dst.execute(select(text("COUNT(*)")).select_from(table)).scalar() or 0
                if s != d:
                    mismatch += 1
                    print(f"[WARN] 行数不一致 {table.name}: sqlite={s} mysql={d}")
            if mismatch == 0:
                print("[VERIFY] 全部表行数一致 ✔")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(BACKEND_DIR / "data" / "app.db"), help="源 SQLite 文件路径")
    parser.add_argument("--dest-url", default=None, help="目标 MySQL URL（默认取 Settings.database_url）")
    parser.add_argument("--wipe", action="store_true", help="迁移前清空目标业务表")
    parser.add_argument("--dry-run", action="store_true", help="只校验与统计，不写入")
    args = parser.parse_args()

    dest_url = args.dest_url
    if not dest_url:
        from app.core.settings import settings

        dest_url = settings.database_url
    migrate(args.source, dest_url, wipe=args.wipe, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
