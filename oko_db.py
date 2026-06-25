"""Database access layer for OKO.

A pooled PostgreSQL connection layer (psycopg2 ThreadedConnectionPool) plus the thin query
helpers used across the app. Depends only on oko_config + psycopg2 — no app-level imports,
so it stays free of import cycles.
"""
import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

from oko_config import DATABASE_URL, SCHEMA_PATH


_DB_POOL = None
_DB_POOL_LOCK = threading.Lock()


def _get_db_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Lazily-initialised process-wide connection pool.

    Replaces the previous "open a fresh psycopg2 connection per call" pattern, which under
    concurrent HTTP requests + background workers could exhaust PostgreSQL's max_connections.
    Bounds are configurable via DB_POOL_MIN / DB_POOL_MAX.
    """
    global _DB_POOL
    if _DB_POOL is None:
        with _DB_POOL_LOCK:
            if _DB_POOL is None:
                _DB_POOL = psycopg2.pool.ThreadedConnectionPool(
                    int(os.getenv('DB_POOL_MIN', '2')),
                    int(os.getenv('DB_POOL_MAX', '20')),
                    dsn=DATABASE_URL,
                )
    return _DB_POOL


def close_db_pool():
    """Close all pooled connections — called on graceful shutdown."""
    global _DB_POOL
    pool, _DB_POOL = _DB_POOL, None
    if pool is not None:
        try:
            pool.closeall()
        except Exception:
            pass


@contextmanager
def db_conn():
    """Lease an autocommit connection from the pool and return it on exit.

    Drop-in for the historical ``with db_conn() as conn`` call sites: same usage, but the
    connection is now leased from the pool and returned (not leaked to GC). A connection that
    raises inside the block is discarded instead of being returned dirty to the pool.
    """
    pool = _get_db_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        yield conn
    except Exception:
        pool.putconn(conn, close=True)
        raise
    else:
        pool.putconn(conn)


@contextmanager
def db_tx():
    """Lease a transactional (autocommit=False) pooled connection.

    For the few multi-statement operations that must commit/rollback as a unit. Commits on
    clean exit, rolls back and discards the connection on error.
    """
    pool = _get_db_pool()
    conn = pool.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        finally:
            pool.putconn(conn, close=True)
        raise
    else:
        pool.putconn(conn)


def init_db():
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f'schema_not_found: {SCHEMA_PATH}')
    schema_sql = SCHEMA_PATH.read_text(encoding='utf-8')
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(schema_sql)
    # Cleanup: a previous process may have died mid-submit, leaving zombie 'queued' rows that
    # were never assigned a provider_job_id. The poll worker can't pick those up, so they'd
    # block the export forever. Drop them so retry/queue logic re-creates them on next run.
    try:
        db_exec("DELETE FROM media_transcriptions WHERE status = 'queued' AND provider_job_id IS NULL")
    except Exception:
        pass
    # Cleanup: re-queue exports whose worker thread died mid-flight. Without this they'd wait
    # for the 10-minute staleness threshold in export_worker_loop before restarting.
    try:
        db_exec("UPDATE analysis_exports SET status='queued', updated_at=NOW() WHERE status='processing'")
    except Exception:
        pass
    # Same for QA runs: a process restart abandoned anyone in 'processing'. Re-queue them so
    # qa_worker_loop picks them up immediately rather than waiting 10 minutes for staleness.
    try:
        db_exec("UPDATE qa_analysis_runs SET status='queued', updated_at=NOW() WHERE status='processing'")
    except Exception:
        pass


def db_one(query: str, args: tuple = ()):
    with db_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, args)
        return cur.fetchone()


def db_all(query: str, args: tuple = ()):
    with db_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, args)
        return cur.fetchall()


def db_exec(query: str, args: tuple = ()):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(query, args)
