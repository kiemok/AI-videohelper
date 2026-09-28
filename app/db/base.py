"""数据库基础设施：引擎缓存、建表、会话作用域。

同时兼容两种后端：
- SQLite（默认，零配置，本地单文件）
- MySQL（设置页改一行 db_url 即可切换：mysql+pymysql://user:pwd@127.0.0.1:3306/ccd）
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker] = {}


def _is_sqlite(db_url: str) -> bool:
    return db_url.startswith("sqlite")


def get_engine(db_url: str) -> Engine:
    """按 db_url 缓存引擎，避免重复创建连接池。"""
    if db_url in _engines:
        return _engines[db_url]

    kwargs: dict = {"future": True, "echo": False}
    if _is_sqlite(db_url):
        # 桌面端多处线程会访问同一连接，需放开线程检查
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    else:
        kwargs.update({"pool_pre_ping": True, "pool_recycle": 3600})

    engine = create_engine(db_url, **kwargs)

    if _is_sqlite(db_url):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    _engines[db_url] = engine
    _session_factories[db_url] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    logger.info("数据库引擎已创建: %s", db_url.split("@")[-1])
    return engine


def init_db(db_url: str) -> Engine:
    """建表（幂等），返回引擎。"""
    from app.db.models import Base  # 延迟导入，避免循环依赖

    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(db_url: str) -> sessionmaker:
    if db_url not in _session_factories:
        get_engine(db_url)
    return _session_factories[db_url]


@contextmanager
def session_scope(db_url: str) -> Iterator[Session]:
    """事务性会话上下文：正常提交，异常回滚。"""
    session = get_session_factory(db_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engines() -> None:
    """释放所有引擎（切换数据库配置或退出时调用）。"""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _session_factories.clear()
