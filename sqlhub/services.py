# sqlhub/services.py
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL
from urllib.parse import quote_plus
from datetime import datetime, timedelta
from django.utils import timezone
from .models import DBConnection, SavedQuery, QueryCache

def build_sqlalchemy_url(conn: DBConnection) -> str:
    u, p, h, prt, db = conn.username, conn.password, conn.host or "localhost", conn.port, conn.database
    opts = conn.options or {}
    if conn.engine == "postgresql":
        return f"postgresql+psycopg://{quote_plus(u)}:{quote_plus(p)}@{h}:{prt or 5432}/{db}"
    if conn.engine == "mysql":
        return f"mysql+pymysql://{quote_plus(u)}:{quote_plus(p)}@{h}:{prt or 3306}/{db}"
    if conn.engine == "mssql":
        drv = opts.get("odbc_driver", "ODBC Driver 18 for SQL Server")
        dsn = f"DRIVER={drv};SERVER={h},{prt or 1433};DATABASE={db};UID={u};PWD={p};TrustServerCertificate=yes"
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(dsn)}"
    if conn.engine == "firebird":
        charset = opts.get("charset", "UTF8")
        # Ex.: host/port:path/to/db.fdb
        hostport = f"{h}/{prt or 3050}" if h else ""
        return f"firebird+firebirdsql://{quote_plus(u)}:{quote_plus(p)}@{hostport}:{db}?charset={charset}"
    raise ValueError("Engine não suportado.")

def _assert_select_only(sql: str):
    s = (sql or "").strip().lower()
    # bloqueios simples: precisa começar com select; sem ; extra; sem ddl/dml óbvios
    if not s.startswith("select"):
        raise ValueError("A consulta precisa começar com SELECT.")
    if ";" in s[:-1]:  # permite ; apenas no final, e mesmo assim é melhor evitar
        raise ValueError("Remova ';' intermediários da consulta.")
    forbidden = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "create ")
    if any(tok in s for tok in forbidden):
        raise ValueError("Somente SELECT é permitido nesta área.")

def test_connection(conn: DBConnection) -> tuple[bool, str]:
    try:
        url = build_sqlalchemy_url(conn)
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
        with engine.connect() as cx:
            cx.execute(text("SELECT 1"))
        return True, "Conexão OK"
    except Exception as e:
        return False, str(e)

def run_select(query: SavedQuery, *, limit: int | None = None, timeout_s: int = 5, params: dict | None = None):
    _assert_select_only(query.sql_text)
    url = build_sqlalchemy_url(query.connection)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    sql = query.sql_text.strip()
    if limit and "limit" not in sql.lower():
        sql = f"{sql}\nLIMIT {int(limit)}"
    # Execução com timeout (genérico). Alguns dialetos têm “statement_timeout”; aqui usamos nível de driver.
    with engine.connect() as cx:
        cx = cx.execution_options(stream_results=False)
        res = cx.execute(text(sql), params or {})
        cols = list(res.keys())
        rows = [list(r) for r in res.fetchall()]
    return cols, rows
