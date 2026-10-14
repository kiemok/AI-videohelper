"""数据库基础设施：引擎缓存、建表、会话作用域。

同时兼容两种后端：
- SQLite（默认，零配置，本地单文件）
- MySQL（设置页改一行 db_url 即可切换：mysql+pymysql://user:pwd@127.0.0.1:3306/ccd）
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, inspect, text
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
    """建表（幂等）+ 补齐新增列，返回引擎。"""
    from app.db.models import Base  # 延迟导入，避免循环依赖

    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    _ensure_new_columns(engine)
    return engine


def _ensure_new_columns(engine: Engine) -> list[str]:
    """轻量迁移：为已存在的表补齐模型里新增的列（不重建表、不丢数据）。

    ``create_all`` 只会建"不存在的表"，**不会**给已存在的表加列；因此版本升级新增字段后，
    旧数据库会因缺列报错。这里按模型定义逐列比对，缺哪列补哪列：

    - SQLite 与 MySQL 都支持 ``ALTER TABLE ... ADD COLUMN``；
    - 只处理可空列（或有默认值的列），带 NOT NULL 且无默认值的列无法安全补齐，跳过并记警告；
    - 全部改动在一个事务里完成。
    """
    from app.db.models import Base

    added: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    logger.warning("跳过补列（NOT NULL 且无默认值）：%s.%s", table.name, column.name)
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}')
                )
                added.append(f"{table.name}.{column.name}")
    if added:
        logger.info("数据库已补齐新增列：%s", "、".join(added))
    return added


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
