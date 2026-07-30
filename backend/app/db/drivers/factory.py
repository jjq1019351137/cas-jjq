from __future__ import annotations

from collections.abc import Callable

from app.core.settings import Settings, settings
from app.db.drivers.base import DatabaseDriver
from app.db.drivers.mysql import MySQLDriver
from app.db.drivers.sqlite import SQLiteDriver

_DRIVERS: dict[str, Callable[[Settings], DatabaseDriver]] = {}
_URL_SCHEME_PREFIXES: dict[str, str] = {}


def register_driver(
    name: str,
    factory: Callable[[Settings], DatabaseDriver],
    *,
    url_schemes: tuple[str, ...] = (),
) -> None:
    _DRIVERS[name] = factory
    for scheme in url_schemes:
        _URL_SCHEME_PREFIXES[scheme] = name


register_driver("sqlite3", SQLiteDriver, url_schemes=("sqlite",))
register_driver("mysql", MySQLDriver, url_schemes=("mysql",))


def driver_name_for_url(url: str) -> str | None:
    scheme = str(url or "").split("://", 1)[0].split("+", 1)[0].strip().lower()
    return _URL_SCHEME_PREFIXES.get(scheme)


def create_database_driver(config: Settings | None = None) -> DatabaseDriver:
    cfg = config or settings
    driver = cfg.normalized_db_driver

    override = str(cfg.database_url_override or "").strip()
    if override:
        url_driver = driver_name_for_url(override)
        if url_driver is None:
            raise RuntimeError(
                f"DATABASE_URL 使用了不支持的 scheme: {override.split('://', 1)[0]!r}；"
                f"支持的驱动: {sorted(_DRIVERS)}"
            )
        explicitly_set = "db_driver" in getattr(cfg, "model_fields_set", set())
        if explicitly_set and url_driver != driver:
            raise RuntimeError(
                f"数据库配置冲突: DB_DRIVER={cfg.db_driver!r} 但 DATABASE_URL 指向 {url_driver!r}"
                f"（{override.split('@')[-1]}）。请移除其中一个，或保持两者一致。"
                "提示: DATABASE_URL 优先级最高，backend/.env 中残留的 DATABASE_URL 也会生效。"
            )
        driver = url_driver

    factory = _DRIVERS.get(driver)
    if factory is None:
        raise RuntimeError(f"未知的 DB_DRIVER: {driver!r}；支持的驱动: {sorted(_DRIVERS)}")
    return factory(cfg)
