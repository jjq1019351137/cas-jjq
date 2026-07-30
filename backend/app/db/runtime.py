from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import settings
from app.db.drivers import DatabaseDriver, create_database_driver

logger = logging.getLogger(__name__)


def _mask_url(url: str) -> str:
    return re.sub(r"(://[^:/@]+):[^@]*@", r"\1:***@", url)


@dataclass(frozen=True)
class DatabaseRuntime:
    driver: DatabaseDriver
    engine: object
    SessionLocal: sessionmaker


def build_runtime(*, for_migrations: bool = False) -> DatabaseRuntime:
    driver = create_database_driver(settings)
    errors = driver.validation_errors()
    if errors:
        raise RuntimeError("; ".join(errors))
    driver.prepare_environment()
    logger.info("database driver=%s url=%s", driver.name, _mask_url(driver.url))
    engine = create_engine(
        driver.url,
        connect_args=driver.connect_args(),
        **driver.engine_kwargs(for_migrations=for_migrations),
    )
    driver.configure_engine(engine)
    try:
        with engine.connect() as conn:
            conn.execute(text(driver.healthcheck_sql()))
    except Exception as exc:
        raise RuntimeError(
            f"数据库连接失败 driver={driver.name} url={_mask_url(driver.url)}: {exc}"
        ) from exc
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    return DatabaseRuntime(driver=driver, engine=engine, SessionLocal=session_local)


runtime = build_runtime()
driver = runtime.driver
engine = runtime.engine
SessionLocal = runtime.SessionLocal


@contextmanager
def session_scope() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
