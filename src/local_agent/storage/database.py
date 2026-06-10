"""Database initialization and session management."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from local_agent.storage.fts import FTS5_TOKENIZE
from local_agent.storage.models import Base

SCHEMA_VERSION = 6


def _enable_wal(dbapi_conn, _connection_record) -> None:
    dbapi_conn.execute("PRAGMA journal_mode=WAL")


def get_engine(db_path: Path, enable_wal: bool = True) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    if enable_wal:
        event.listen(engine, "connect", _enable_wal)
    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar() or 0
        if version < SCHEMA_VERSION:
            _migrate(conn, version)
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
            conn.commit()
        _create_fts(conn)
        conn.commit()


def _migrate(conn, from_version: int) -> None:
    if from_version < 1:
        pass  # initial schema via create_all
    if from_version < 2:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    tool_name TEXT,
                    description TEXT,
                    size_bytes INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_thread "
                "ON artifacts(thread_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_agent "
                "ON artifacts(agent_id)"
            )
        )
    if from_version < 3:
        cols = conn.execute(text("PRAGMA table_info(threads)")).fetchall()
        col_names = {row[1] for row in cols}
        if "config_override" not in col_names:
            conn.execute(
                text("ALTER TABLE threads ADD COLUMN config_override TEXT")
            )
    if from_version < 4:
        cols = conn.execute(text("PRAGMA table_info(messages)")).fetchall()
        col_names = {row[1] for row in cols}
        if "thinking" not in col_names:
            conn.execute(text("ALTER TABLE messages ADD COLUMN thinking TEXT"))
    if from_version < 5:
        _rebuild_fts_tables(conn)
    if from_version < 6:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    agent_id TEXT,
                    thread_id TEXT,
                    schedule_type TEXT NOT NULL,
                    cron_expression TEXT,
                    at_time TEXT,
                    interval_minutes INTEGER,
                    action_type TEXT NOT NULL,
                    action_payload TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    max_runs INTEGER,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    next_run_at TEXT,
                    last_run_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    timeout_secs INTEGER NOT NULL DEFAULT 300,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next "
                "ON scheduled_jobs(enabled, next_run_at)"
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS job_runs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    output TEXT,
                    error TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_job_runs_job "
                "ON job_runs(job_id, started_at DESC)"
            )
        )


def _create_fts(conn) -> None:
    conn.execute(
        text(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                message_id UNINDEXED,
                thread_id UNINDEXED,
                content,
                tokenize='{FTS5_TOKENIZE}'
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS atoms_fts USING fts5(
                atom_id UNINDEXED,
                agent_id UNINDEXED,
                content,
                tokenize='{FTS5_TOKENIZE}'
            )
            """
        )
    )


def _rebuild_fts_tables(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS messages_fts"))
    conn.execute(text("DROP TABLE IF EXISTS atoms_fts"))
    _create_fts(conn)
    conn.execute(
        text(
            """
            INSERT INTO atoms_fts(atom_id, agent_id, content)
            SELECT id, agent_id, content FROM memory_atoms
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO messages_fts(message_id, thread_id, content)
            SELECT id, thread_id, COALESCE(content, thinking)
            FROM messages
            WHERE COALESCE(content, thinking) IS NOT NULL
              AND COALESCE(content, thinking) != ''
            """
        )
    )


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
