# views.py
from __future__ import annotations

import csv
import io
import re
import unicodedata
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Tuple, Set, Optional

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import (
    Http404,
    HttpRequest,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from .models import DBConnection, SavedQuery, DBEngine

logger = logging.getLogger(__name__)


# =========================
# Forms
# =========================

class DBConnectionForm(forms.ModelForm):
    class Meta:
        model = DBConnection
        fields = [
            "name",
            "engine",
            "host",
            "port",
            "database",
            "username",
            "password",
            "options",
            "read_only",
        ]
        widgets = {
            "password": forms.PasswordInput(render_value=True),
            "options": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        engine = cleaned.get("engine")
        database = (cleaned.get("database") or "").strip()
        if engine in (DBEngine.FIREBIRD, DBEngine.POSTGRES, DBEngine.MYSQL) and not database:
            raise ValidationError({"database": "Este campo é obrigatório para este banco."})
        return cleaned


class SavedQueryForm(forms.ModelForm):
    class Meta:
        model = SavedQuery
        fields = ["name", "connection", "sql_text", "default_limit", "is_active"]
        widgets = {
            "sql_text": forms.Textarea(attrs={"rows": 12, "spellcheck": "false"}),
        }


# =========================
# Helpers / Execução
# =========================

class DriverMissing(Exception):
    pass


def _open_dbapi(conn: DBConnection):
    engine = conn.engine
    host = conn.host or "localhost"
    port = conn.port
    db = (conn.database or "").strip()
    user = conn.username
    pwd = conn.password
    opts: Dict[str, Any] = conn.options or {}

    if engine == DBEngine.POSTGRES:
        try:
            import psycopg2
        except Exception:
            raise DriverMissing("psycopg2 não instalado.")
        py_conn = psycopg2.connect(
            host=host,
            port=port or 5432,
            dbname=db,
            user=user,
            password=pwd,
            connect_timeout=opts.get("connect_timeout", 5),
        )
        return py_conn, py_conn.cursor()

    if engine == DBEngine.MYSQL:
        try:
            import pymysql
        except Exception:
            raise DriverMissing("pymysql não instalado.")
        py_conn = pymysql.connect(
            host=host,
            port=int(port or 3306),
            user=user,
            password=pwd,
            database=db,
            connect_timeout=int(opts.get("connect_timeout", 5)),
            charset=opts.get("charset", "utf8mb4"),
            cursorclass=pymysql.cursors.Cursor,
        )
        return py_conn, py_conn.cursor()

    if engine == DBEngine.SQLSERVER:
        try:
            import pyodbc
        except Exception:
            raise DriverMissing("pyodbc não instalado.")
        driver = opts.get("odbc_driver", "ODBC Driver 18 for SQL Server")
        encrypt = opts.get("Encrypt", "yes")
        trust = opts.get("TrustServerCertificate", "yes")
        port_part = f",{port}" if port else ""
        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={host}{port_part}",
            f"UID={user}",
            f"PWD={pwd}",
            f"Encrypt={encrypt}",
            f"TrustServerCertificate={trust}",
        ]
        if db:
            parts.append(f"DATABASE={db}")
        cn_str = ";".join(parts) + ";"
        py_conn = pyodbc.connect(cn_str, timeout=int(opts.get("connect_timeout", 5)))
        return py_conn, py_conn.cursor()

    if engine == DBEngine.FIREBIRD:
        try:
            from firebird.driver import connect as fb_connect
            dsn = f"{host}/{port or 3050}:{db}" if host else db
            py_conn = fb_connect(
                dsn=dsn,
                user=user,
                password=pwd,
                timeout=int(opts.get("connect_timeout", 5)),
                charset=opts.get("charset", "UTF8"),
            )
            return py_conn, py_conn.cursor()
        except Exception:
            try:
                import fdb
                py_conn = fdb.connect(
                    host=host or "localhost",
                    port=port or 3050,
                    database=db,
                    user=user,
                    password=pwd,
                    charset=opts.get("charset", "UTF8"),
                )
                return py_conn, py_conn.cursor()
            except Exception:
                raise DriverMissing("firebird-driver/fdb não instalado(s).")

    raise Http404("Engine não suportado.")


def _validate_select(sql: str) -> None:
    s = (sql or "").strip().lower()
    if not s.startswith("select"):
        raise ValueError("A consulta deve iniciar com SELECT.")
    proibidos = ["insert", "update", "delete", "drop", "alter", "create", "grant", "revoke", "use "]
    if any(tok in s for tok in proibidos):
        raise ValueError("Somente consultas de leitura (SELECT) são permitidas.")
    if ";" in s:
        raise ValueError("Remova ';' do SQL. Apenas uma instrução SELECT é permitida.")


def _clamp_limit(raw: Any, soft_max: int = 1000) -> int:
    try:
        v = int(raw)
    except Exception:
        v = soft_max
    v = max(1, min(v, max(soft_max, 5000)))
    return v


def _engine_placeholder(engine: str) -> str:
    if engine in (DBEngine.POSTGRES, DBEngine.MYSQL):
        return "%s"
    return "?"


# ----- WHERE dinâmico (seguro) -----

_WHERE_KEY_RE = re.compile(r"^where\[(\d+)\]\[(field|op|value)\]$")
_VALID_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_where_filters(request: HttpRequest) -> List[Dict[str, Any]]:
    items: Dict[int, Dict[str, Any]] = {}

    def feed(d: Dict[str, Any]):
        for k, v in d.items():
            m = _WHERE_KEY_RE.match(k)
            if not m:
                continue
            idx = int(m.group(1))
            key = m.group(2)
            items.setdefault(idx, {})[key] = v

    feed(request.GET)
    if request.method == "POST":
        feed(request.POST)

    out: List[Dict[str, Any]] = []
    for idx in sorted(items.keys()):
        out.append(items[idx])
    return out


def _build_sql_with_filters(base_sql: str, engine: str, filters: List[Dict[str, Any]]):
    base_sql = (base_sql or "").strip().rstrip(";")
    if not filters:
        return base_sql, []

    ph = _engine_placeholder(engine)
    conditions, params = [], []

    for f in filters:
        field = (f.get("field") or "").strip()
        op = (f.get("op") or "eq").strip().lower()
        value = f.get("value", "")

        if not field or not _VALID_FIELD_RE.match(field):
            continue

        if op in ("eq", "=", "=="):
            conditions.append(f"src.{field} = {ph}");                params.append(value)
        elif op in ("ne", "neq", "!="):
            conditions.append(f"src.{field} <> {ph}");               params.append(value)
        elif op in ("gt", ">"):
            conditions.append(f"src.{field} > {ph}");                params.append(value)
        elif op in ("gte", ">="):
            conditions.append(f"src.{field} >= {ph}");               params.append(value)
        elif op in ("lt", "<"):
            conditions.append(f"src.{field} < {ph}");                params.append(value)
        elif op in ("lte", "<="):
            conditions.append(f"src.{field} <= {ph}");               params.append(value)
        elif op in ("contains",):
            conditions.append(f"src.{field} LIKE {ph}");             params.append(f"%{value}%")
        elif op in ("startswith", "starts_with"):
            conditions.append(f"src.{field} LIKE {ph}");             params.append(f"{value}%")
        elif op in ("endswith", "ends_with"):
            conditions.append(f"src.{field} LIKE {ph}");             params.append(f"%{value}")
        elif op in ("isnull", "is_null"):
            conditions.append(f"src.{field} IS NULL")
        elif op in ("notnull", "not_null"):
            conditions.append(f"src.{field} IS NOT NULL")
        else:
            continue

    if not conditions:
        return base_sql, []

    where_sql = " AND ".join(conditions)
    wrapped = f"SELECT * FROM (\n{base_sql}\n) src WHERE {where_sql}"
    return wrapped, params


# ====== Normalização util ======

def _norm(s: Any) -> str:
    try:
        t = str(s or "")
        t = unicodedata.normalize("NFKD", t)
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        return t.lower()
    except Exception:
        return str(s or "").lower()


def _canon_name(s: Any) -> str:
    try:
        t = str(s or "")
        t = unicodedata.normalize("NFKD", t)
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        return t.lower()
    except Exception:
        return str(s or "").lower()


def _find_col_index(cols: List[str], name: str | None, default: int = 0) -> int:
    if not cols or not name:
        return default
    try:
        return cols.index(name)
    except ValueError:
        pass
    canon = {_canon_name(c): i for i, c in enumerate(cols)}
    return canon.get(_canon_name(name), default)


# ====== Cache LRU/TTL curto ======

class _TTLCache:
    def __init__(self, maxsize=512, ttl=45.0):
        self.data = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl
    def _purge(self):
        now = time.monotonic()
        for k in list(self.data.keys()):
            t, _ = self.data[k]
            if now - t > self.ttl:
                self.data.pop(k, None)
        while len(self.data) > self.maxsize:
            self.data.popitem(last=False)
    def get(self, key):
        self._purge()
        item = self.data.pop(key, None)
        if not item:
            return None
        t, v = item
        if time.monotonic() - t > self.ttl:
            return None
        self.data[key] = (time.monotonic(), v)
        return v
    def set(self, key, value):
        self._purge()
        self.data[key] = (time.monotonic(), value)

_OPTIONS_CACHE = _TTLCache(maxsize=512, ttl=45.0)
_BADCOLS_CACHE  = _TTLCache(maxsize=256, ttl=300.0)

def _badkey(qpk: int, col: str) -> tuple:
    return ("badcol", int(qpk), (col or "").upper())

def _mark_bad_col(qpk: int, col: str) -> None:
    try:
        _BADCOLS_CACHE.set(_badkey(qpk, col), True)
    except Exception:
        pass

def _is_bad_col(qpk: int, col: str) -> bool:
    try:
        return bool(_BADCOLS_CACHE.get(_badkey(qpk, col)))
    except Exception:
        return False


# ====== SQL genérico para busca por engine, sem amarrar a nomes ======

def _like_expr_by_engine(
    engine: str,
    col: str,
    q_mode: str = "contains",
    is_text: Optional[bool] = None,
) -> str:
    """
    Constrói expressão de filtro para a coluna `src.col` conforme engine.
    - Não usa nomes específicos; só depende do tipo inferido (texto ou não).
    - Em Firebird, evita casts de charset para não provocar "Malformed string".
    """
    c = f"src.{col}"
    # quando não temos certeza se é texto, converta para texto de forma genérica
    as_text = c if is_text else f"CAST({c} AS VARCHAR(512))"

    if engine == DBEngine.FIREBIRD:
        if q_mode == "prefix":
            # STARTING WITH é rápido com índice; UPPER para case-insensitive
            return f"UPPER({as_text}) STARTING WITH UPPER($$PARAM$$)"
        # contains é case-insensitive por natureza no FB
        return f"{as_text} CONTAINING $$PARAM$$"

    if engine == DBEngine.POSTGRES:
        # ILIKE é case-insensitive
        return f"CAST({c} AS TEXT) ILIKE $$PARAM$$"

    if engine == DBEngine.MYSQL:
        return f"LOWER(CAST({c} AS CHAR)) LIKE LOWER($$PARAM$$)"

    if engine == DBEngine.SQLSERVER:
        return f"UPPER(CAST({c} AS NVARCHAR(4000))) LIKE UPPER($$PARAM$$)"

    # fallback genérico
    return f"CAST({c} AS TEXT) LIKE $$PARAM$$"


def _build_options_db_filter_sql(
    base_sql: str,
    engine: str,
    search_cols: List[str],
    qtext: str | None = None,
    limit: int | None = None,
    q_mode: str | None = None,  # "prefix" | "contains" | None
    text_cols: Optional[Set[str]] = None,
) -> Tuple[str, List[Any]]:
    """
    Constrói SELECT sobre (base_sql) aplicando WHERE de busca nas colunas indicadas.
    Não depende de nomes específicos; usa `text_cols` (inferido por amostra) para decidir
    se precisa CAST genérico (sem charset) ou pode usar a coluna diretamente.
    """
    base_sql = (base_sql or "").strip().rstrip(";")
    ph = _engine_placeholder(engine)

    safe_cols = [c for c in (search_cols or []) if c and _VALID_FIELD_RE.match(c)]
    if not safe_cols:
        return base_sql, []

    mode = q_mode or "contains"
    exprs: List[str] = []
    params: List[Any] = []

    for c in safe_cols:
        is_text = (text_cols is not None and c in text_cols)
        expr = _like_expr_by_engine(engine, c, mode, is_text=is_text).replace("$$PARAM$$", ph)
        exprs.append(f"({expr})")

        if qtext is None:
            params.append(None)
        else:
            if engine == DBEngine.FIREBIRD:
                # no Firebird o termo vai “puro”
                params.append(qtext if mode != "prefix" else qtext)
            else:
                params.append(f"{qtext}%" if mode == "prefix" else f"%{qtext}%")

    where_sql = " OR ".join(exprs)
    final_sql = f"SELECT * FROM (\n{base_sql}\n) src WHERE {where_sql}"

    # LIMIT/TOP/ROWS
    if limit and isinstance(limit, int) and limit > 0:
        n = int(limit)
        if engine in (DBEngine.POSTGRES, DBEngine.MYSQL):
            final_sql += " ORDER BY 1 LIMIT %s"
            params.append(n)
        elif engine == DBEngine.SQLSERVER:
            final_sql = re.sub(r"(?is)^\s*SELECT\s+", f"SELECT TOP {n} ", final_sql, count=1)
            final_sql += " ORDER BY 1"
        elif engine == DBEngine.FIREBIRD:
            # deixar sem ORDER BY para FB poder usar índice
            final_sql += f" ROWS {n}"

    return final_sql, params


def _dbfilter_firebird_greedy(
    qpk: int,
    conn: DBConnection,
    base_sql: str,
    search_cols: List[str],
    qtext: str,
    limit: int,
    vf_idx: int,
    text_cols: Optional[Set[str]],
) -> Tuple[List[List[Any]], List[str], List[str]]:
    """
    Firebird: Tenta prefixo por coluna; se necessário, tenta contains.
    Não depende de nomes de colunas. Usa `text_cols` para evitar CAST desnecessário.
    Retorna (rows, good_cols, bad_cols).
    """
    rows: List[List[Any]] = []
    seen: Set[Any] = set()
    good_cols: List[str] = []
    bad_cols: List[str] = []

    # 1ª passada: prefix
    for col in search_cols:
        try:
            rem = max(1, limit - len(rows))
            sql_col, params = _build_options_db_filter_sql(
                base_sql, DBEngine.FIREBIRD, [col], qtext=qtext, limit=rem, q_mode="prefix", text_cols=text_cols
            )
            logger.debug("fb-greedy col=%s sql=%s", col, sql_col)
            py_conn, cur = _open_dbapi(conn)
            try:
                cur.execute(sql_col, params)
                got_any = False
                while len(rows) < limit:
                    batch = cur.fetchmany(min(limit - len(rows), 2000))
                    if not batch:
                        break
                    for r in batch:
                        rr = list(r)
                        key = rr[vf_idx] if vf_idx < len(rr) else tuple(rr)
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(rr)
                        got_any = True
                        if len(rows) >= limit:
                            break
                if got_any:
                    good_cols.append(col)
            finally:
                try: cur.close()
                except Exception: pass
                try: py_conn.close()
                except Exception: pass
        except Exception as e:
            bad_cols.append(col)
            if "Malformed string" in str(e) or "SQLCODE: -104" in str(e):
                _mark_bad_col(qpk, col)
            logger.debug("fb-greedy(prefix): pulando coluna %s por erro %r", col, e)

        if len(rows) >= limit:
            break

    # 2ª passada: contains
    if len(rows) < limit:
        for col in search_cols:
            if col in good_cols or col in bad_cols or _is_bad_col(qpk, col):
                continue
            try:
                rem = max(1, limit - len(rows))
                sql_col, params = _build_options_db_filter_sql(
                    base_sql, DBEngine.FIREBIRD, [col], qtext=qtext, limit=rem, q_mode="contains", text_cols=text_cols
                )
                logger.debug("fb-greedy (contains) col=%s sql=%s", col, sql_col)
                py_conn, cur = _open_dbapi(conn)
                try:
                    cur.execute(sql_col, params)
                    got_any = False
                    while len(rows) < limit:
                        batch = cur.fetchmany(min(limit - len(rows), 2000))
                        if not batch:
                            break
                        for r in batch:
                            rr = list(r)
                            key = rr[vf_idx] if vf_idx < len(rr) else tuple(rr)
                            if key in seen:
                                continue
                            seen.add(key)
                            rows.append(rr)
                            got_any = True
                            if len(rows) >= limit:
                                break
                    if got_any:
                        good_cols.append(col)
                finally:
                    try: cur.close()
                    except Exception: pass
                    try: py_conn.close()
                    except Exception: pass
            except Exception as e:
                bad_cols.append(col)
                if "Malformed string" in str(e) or "SQLCODE: -104" in str(e):
                    _mark_bad_col(qpk, col)
                logger.debug("fb-greedy(contains): pulando coluna %s por erro %r", col, e)

            if len(rows) >= limit:
                break

    return rows, good_cols, bad_cols


# =========================
# Execução de preview/página
# =========================

def _fetch_preview(
    conn: DBConnection,
    sql: str,
    limit: int,
    filters: List[Dict[str, Any]] | None = None,
) -> Tuple[List[str], List[List[Any]]]:
    _validate_select(sql)
    limit = _clamp_limit(limit)
    engine = conn.engine
    final_sql, params = _build_sql_with_filters(sql, engine, filters or [])

    py_conn, cur = _open_dbapi(conn)
    try:
        if params:
            cur.execute(final_sql, params)
        else:
            cur.execute(final_sql)

        columns = [d[0] for d in (cur.description or [])]
        rows: List[List[Any]] = []
        batch = cur.fetchmany(limit)
        while batch:
            rows.extend([list(r) for r in batch])
            if len(rows) >= limit:
                break
            batch = cur.fetchmany(limit - len(rows))
        return columns, rows
    finally:
        try: cur.close()
        except Exception: pass
        try: py_conn.close()
        except Exception: pass


def _fetch_page(
    conn: DBConnection,
    sql: str,
    offset: int,
    limit: int,
    filters: List[Dict[str, Any]] | None = None,
    skip_batch: int = 1000,
) -> Tuple[List[str], List[List[Any]], bool]:
    _validate_select(sql)
    offset = max(0, int(offset))
    limit = _clamp_limit(limit, soft_max=2000)

    engine = conn.engine
    final_sql, params = _build_sql_with_filters(sql, engine, filters or [])

    py_conn, cur = _open_dbapi(conn)
    try:
        if params:
            cur.execute(final_sql, params)
        else:
            cur.execute(final_sql)

        columns = [d[0] for d in (cur.description or [])]

        to_skip = offset
        while to_skip > 0:
            n = min(skip_batch, to_skip)
            chunk = cur.fetchmany(n)
            if not chunk:
                return columns, [], False
            to_skip -= len(chunk)

        rows = cur.fetchmany(limit + 1)
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        return columns, [list(r) for r in rows], has_more
    finally:
        try: cur.close()
        except Exception: pass
        try: py_conn.close()
        except Exception: pass


# =========================
# Conexões (CBVs)
# =========================

class ConnectionList(LoginRequiredMixin, ListView):
    model = DBConnection
    template_name = "sqlhub/conn_list.html"
    context_object_name = "connections"


class ConnectionCreate(LoginRequiredMixin, CreateView):
    model = DBConnection
    form_class = DBConnectionForm
    template_name = "sqlhub/conn_form.html"
    success_url = reverse_lazy("sqlhub:conn_list")

    def form_valid(self, form):
        obj: DBConnection = form.save(commit=False)
        obj.created_by = self.request.user
        if not obj.port:
            defaults = {"postgresql": 5432, "mysql": 3306, "mssql": 1433, "firebird": 3050}
            obj.port = defaults.get(obj.engine)
        obj.save()
        messages.success(self.request, "Conexão criada com sucesso.")
        return super().form_valid(form)


class ConnectionUpdate(LoginRequiredMixin, UpdateView):
    model = DBConnection
    form_class = DBConnectionForm
    template_name = "sqlhub/conn_form.html"
    success_url = reverse_lazy("sqlhub:conn_list")

    def form_valid(self, form):
        messages.success(self.request, "Conexão atualizada com sucesso.")
        return super().form_valid(form)


@login_required
def test_connection_view(request: HttpRequest, pk: int) -> JsonResponse:
    conn = get_object_or_404(DBConnection, pk=pk)
    try:
        py_conn, cur = _open_dbapi(conn)
        try:
            test_sql = "SELECT 1 FROM RDB$DATABASE" if conn.engine == DBEngine.FIREBIRD else "SELECT 1"
            cur.execute(test_sql)
            _ = cur.fetchone()
        finally:
            try: cur.close()
            except Exception: pass
            try: py_conn.close()
            except Exception: pass
        return JsonResponse({"ok": True, "message": "Conexão OK"})
    except DriverMissing as e:
        return JsonResponse({"ok": False, "message": f"Driver ausente: {e}"}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Falha ao conectar: {e}"}, status=400)


# =========================
# Consultas (CBVs + APIs)
# =========================

class QueryList(ListView):
    model = SavedQuery
    template_name = "sqlhub/query_list.html"
    context_object_name = "queries"

    def get_queryset(self):
        qs = super().get_queryset().select_related("connection").order_by(
            "connection__name", "name"
        )
        ativo = self.request.GET.get("active")
        if ativo in ("1", "0"):
            qs = qs.filter(is_active=(ativo == "1"))
        conn_id = self.request.GET.get("connection")
        if conn_id:
            qs = qs.filter(connection_id=conn_id)
        return qs


class QueryCreate(LoginRequiredMixin, CreateView):
    model = SavedQuery
    form_class = SavedQueryForm
    template_name = "sqlhub/query_form.html"
    success_url = reverse_lazy("sqlhub:query_list")

    def form_valid(self, form):
        obj: SavedQuery = form.save(commit=False)
        obj.created_by = self.request.user
        obj.save()
        messages.success(self.request, "Consulta salva com sucesso.")
        return super().form_valid(form)


class QueryUpdate(LoginRequiredMixin, UpdateView):
    model = SavedQuery
    form_class = SavedQueryForm
    template_name = "sqlhub/query_form.html"
    success_url = reverse_lazy("sqlhub:query_list")

    def form_valid(self, form):
        messages.success(self.request, "Consulta atualizada com sucesso.")
        return super().form_valid(form)



def query_preview(request: HttpRequest, pk: int) -> JsonResponse:
    q = get_object_or_404(SavedQuery, pk=pk, is_active=True)
    limit = _clamp_limit(request.GET.get("limit") or q.default_limit or 100)
    filters = _parse_where_filters(request)

    try:
        cols, rows = _fetch_preview(q.connection, q.sql_text, limit=limit, filters=filters)
        return JsonResponse({"ok": True, "columns": cols, "rows": rows})
    except DriverMissing as e:
        return JsonResponse({"ok": False, "message": f"Driver ausente: {e}"}, status=400)
    except ValueError as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Erro ao executar preview: {e}"}, status=400)


@login_required
def query_columns(request: HttpRequest, pk: int) -> JsonResponse:
    q = get_object_or_404(SavedQuery, pk=pk, is_active=True)
    try:
        cols, _ = _fetch_preview(q.connection, q.sql_text, limit=1, filters=None)
        return JsonResponse({"ok": True, "columns": cols})
    except DriverMissing as e:
        return JsonResponse({"ok": False, "message": f"Driver ausente: {e}"}, status=400)
    except ValueError as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Erro ao obter colunas: {e}"}, status=400)


def query_options_api(request: HttpRequest, pk: int) -> JsonResponse:
    """
    GET /sqlhub/api/query/<id>/options/
      ?value_field=...&label_field=...&limit=200
      &q=<texto>               # filtra server-side
      &q_fields=COL1,COL2,...  # restringe colunas de busca (opcional)
      &scan=<int>              # teto da varredura no fallback (default 2000; com q → 50000)
      + where[...] opcionais
      &q_mode=prefix|contains  # força modo (opcional)
      &cache=0                 # desliga cache curto (opcional)
      &skip_cols=COL1,COL2     # força pular colunas específicas
    """
    qobj = get_object_or_404(SavedQuery, pk=pk, is_active=True)
    value_field = (request.GET.get("value_field") or request.GET.get("value") or "").strip()
    label_field = (request.GET.get("label_field") or request.GET.get("label") or "").strip()
    limit = _clamp_limit(request.GET.get("limit") or 200)
    filters = _parse_where_filters(request)
    qtext = (request.GET.get("q") or "").strip()

    # Descobre colunas e 1ª linha para inferir tipos textuais
    try:
        cols, sample_rows = _fetch_preview(qobj.connection, qobj.sql_text, limit=1, filters=filters)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Falha ao inspecionar colunas: {e}"}, status=400)

    sample = sample_rows[0] if sample_rows else []
    text_cols: Set[str] = set()
    for i, c in enumerate(cols):
        try:
            v = sample[i] if i < len(sample) else None
            if isinstance(v, (str, bytes)) or v is None:
                text_cols.add(c)
        except Exception:
            # se der erro para inspecionar, não marca como texto
            pass

    # Índices value/label (fallback: primeira/segunda coluna, se existirem)
    vf_idx = cols.index(value_field) if value_field in cols else (0 if cols else 0)
    lf_idx = cols.index(label_field) if label_field in cols else (1 if len(cols) > 1 else 0)

    engine = qobj.connection.engine

    # Colunas de busca:
    # - se q_fields informado, usa as pedidas (presentes e válidas)
    # - senão, usa TODAS as colunas em ordem do SQL,
    #     mas dá preferência às textuais (as primeiras N serão textuais)
    q_fields_param = (request.GET.get("q_fields") or request.GET.get("q_cols") or "").strip()
    if q_fields_param:
        asked = [c.strip() for c in q_fields_param.split(",") if c.strip()]
        search_cols_ordered = [c for c in asked if c in cols]
    else:
        text_first = [c for c in cols if c in text_cols]
        non_text   = [c for c in cols if c not in text_cols]
        search_cols_ordered = text_first + non_text

    # aplicar skip_cols e blacklist TTL
    skip_cols_param = (request.GET.get("skip_cols") or "").strip()
    skip_cols = {c.strip() for c in skip_cols_param.split(",") if c.strip()}
    search_cols_ordered = [
        c for c in search_cols_ordered
        if c not in skip_cols and not _is_bad_col(qobj.id, c)
    ]

    # mantenha no máximo 4 colunas no caminho DB (tuneável via GET se quiser)
    max_cols = int(request.GET.get("max_cols") or 4)
    if max_cols > 0:
        search_cols_ordered = search_cols_ordered[:max_cols]

    # cache curto (funciona com e sem q)
    cache_enabled = (request.GET.get("cache", "1") != "0")
    cache_key = None
    if cache_enabled:
        filt_key = tuple(
            (f.get("field",""), f.get("op",""), str(f.get("value","")))
            for f in (filters or [])
        )
        cache_key = ("opt", pk, tuple(search_cols_ordered), vf_idx, lf_idx, (qtext or "").lower(), limit, filt_key)
        hit = _OPTIONS_CACHE.get(cache_key)
        if hit:
            return JsonResponse(hit)

    # ---------- 1) Caminho server-side quando tem q ----------
    if qtext and (request.GET.get("db_search", "1") != "0"):
        logger.debug("options_api pk=%s engine=%s q=%r search_cols=%s", pk, engine, qtext, search_cols_ordered)
        if engine == DBEngine.FIREBIRD:
            try:
                base_sql, _ = _build_sql_with_filters(qobj.sql_text, engine, filters or [])
                rows, good_cols, bad_cols = _dbfilter_firebird_greedy(
                    qobj.id, qobj.connection, base_sql, search_cols_ordered, qtext, limit, vf_idx, text_cols
                )
                if rows:
                    options = []
                    for r in rows[:limit]:
                        try:
                            options.append({"value": r[vf_idx], "label": r[lf_idx]})
                        except Exception:
                            continue
                    payload = {"ok": True, "columns": cols, "options": options}
                    if cache_key:
                        _OPTIONS_CACHE.set(cache_key, payload)
                    return JsonResponse(payload)

                # sem linhas no greedy → combinado prefix e depois contains
                try_cols = good_cols or [c for c in search_cols_ordered if c not in bad_cols and not _is_bad_col(qobj.id, c)]

                rows2: List[List[Any]] = []
                if try_cols:
                    sql_db, params = _build_options_db_filter_sql(
                        qobj.sql_text, engine, try_cols, qtext=qtext, limit=limit, q_mode="prefix", text_cols=text_cols
                    )
                    logger.debug("options_api FB combined(prefix) cols=%s sql=%s", try_cols, sql_db)
                    py_conn, cur = _open_dbapi(qobj.connection)
                    try:
                        cur.execute(sql_db, params)
                        while len(rows2) < limit:
                            batch = cur.fetchmany(min(limit - len(rows2), 2000))
                            if not batch:
                                break
                            rows2.extend([list(r) for r in batch])
                    finally:
                        try: cur.close()
                        except Exception: pass
                        try: py_conn.close()
                        except Exception: pass

                if not rows2 and try_cols:
                    sql_db, params = _build_options_db_filter_sql(
                        qobj.sql_text, engine, try_cols, qtext=qtext, limit=limit, q_mode="contains", text_cols=text_cols
                    )
                    logger.debug("options_api FB combined(contains) cols=%s sql=%s", try_cols, sql_db)
                    py_conn, cur = _open_dbapi(qobj.connection)
                    try:
                        cur.execute(sql_db, params)
                        while len(rows2) < limit:
                            batch = cur.fetchmany(min(limit - len(rows2), 2000))
                            if not batch:
                                break
                            rows2.extend([list(r) for r in batch])
                    finally:
                        try: cur.close()
                        except Exception: pass
                        try: py_conn.close()
                        except Exception: pass

                if rows2:
                    options = []
                    for r in rows2[:limit]:
                        try:
                            options.append({"value": r[vf_idx], "label": r[lf_idx]})
                        except Exception:
                            continue
                    payload = {"ok": True, "columns": cols, "options": options}
                    if cache_key:
                        _OPTIONS_CACHE.set(cache_key, payload)
                    return JsonResponse(payload)

            except Exception as e:
                logger.warning("options_api pk=%s FB caminho server-side falhou (%r) → fallback client-side", pk, e)
        else:
            # Demais engines: uma consulta combinada
            try:
                sql_db, params = _build_options_db_filter_sql(
                    qobj.sql_text, engine, search_cols_ordered, qtext=qtext, limit=limit, q_mode=(request.GET.get("q_mode") or None), text_cols=text_cols
                )
                logger.debug(
                    "options_api DB-FILTER sql=%s | search_cols=%s | params_count=%s",
                    sql_db, search_cols_ordered, len(params)
                )
                py_conn, cur = _open_dbapi(qobj.connection)
                try:
                    cur.execute(sql_db, params)
                    rows: List[List[Any]] = []
                    while len(rows) < limit:
                        batch = cur.fetchmany(min(limit - len(rows), 2000))
                        if not batch:
                            break
                        rows.extend([list(r) for r in batch])
                finally:
                    try: cur.close()
                    except Exception: pass
                    try: py_conn.close()
                    except Exception: pass

                options = []
                for r in rows:
                    try:
                        options.append({"value": r[vf_idx], "label": r[lf_idx]})
                    except Exception:
                        continue

                payload = {"ok": True, "columns": cols, "options": options}
                if cache_key:
                    _OPTIONS_CACHE.set(cache_key, payload)
                return JsonResponse(payload)
            except Exception as e:
                logger.warning("options_api pk=%s DB-FILTER falhou (%r) → fallback client-side", pk, e)

    # ---------- 2) Fallback (varredura client-side) ----------
    scan_soft_max = 50000 if qtext else 5000
    scan_limit = _clamp_limit(request.GET.get("scan") or (2000 if not qtext else 50000), soft_max=scan_soft_max)
    logger.debug(
        "options_api pk=%s Fallback scan_limit=%s (soft_max=%s) q=%r engine=%s",
        pk, scan_limit, scan_soft_max, qtext, engine
    )

    base_sql, base_params = _build_sql_with_filters(qobj.sql_text, engine, filters or [])

    # Índices de busca no fallback: use as colunas escolhidas
    search_idx = [cols.index(c) for c in search_cols_ordered if c in cols]
    logger.debug("options_api pk=%s Fallback search idx=%s names=%s", pk, search_idx, [cols[i] for i in search_idx])

    matches: List[List[Any]] = []
    looked = 0

    try:
        py_conn, cur = _open_dbapi(qobj.connection)
        try:
            if base_params:
                cur.execute(base_sql, base_params)
            else:
                cur.execute(base_sql)

            if qtext:
                chunk = 2000
                nq = _norm(qtext)
                while len(matches) < limit and looked < scan_limit:
                    batch = cur.fetchmany(min(chunk, scan_limit - looked))
                    if not batch:
                        break
                    looked += len(batch)
                    for r in batch:
                        rr = list(r)
                        hit = False
                        for i in search_idx:
                            try:
                                if nq in _norm(rr[i]):
                                    hit = True
                                    break
                            except Exception:
                                continue
                        if hit:
                            matches.append(rr)
                            if len(matches) >= limit:
                                break
            else:
                remaining = limit - len(matches)
                while remaining > 0:
                    batch = cur.fetchmany(min(2000, remaining))
                    if not batch:
                        break
                    looked += len(batch)
                    take = min(remaining, len(batch))
                    matches.extend([list(r) for r in batch[:take]])
                    remaining -= take
                    if remaining <= 0:
                        break

            logger.debug(
                "options_api pk=%s Fallback looked=%s found=%s limit=%s q=%r",
                pk, looked, len(matches), limit, qtext
            )
        finally:
            try: cur.close()
            except Exception: pass
            try: py_conn.close()
            except Exception: pass
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Falha ao executar varredura: {e}"}, status=400)

    options = []
    for r in matches:
        try:
            options.append({"value": r[vf_idx], "label": r[lf_idx]})
        except Exception:
            continue

    payload = {"ok": True, "columns": cols, "options": options}
    if cache_key:
        _OPTIONS_CACHE.set(cache_key, payload)
    return JsonResponse(payload)


# ----- Ad-hoc (editor de consulta) -----

@login_required
@require_POST
def query_preview_adhoc(request: HttpRequest) -> JsonResponse:
    try:
        conn_id = int(request.POST.get("connection_id") or 0)
        sql_text = request.POST.get("sql_text") or ""
        limit = _clamp_limit(request.POST.get("limit") or 100)
    except Exception:
        return JsonResponse({"ok": False, "message": "Parâmetros inválidos."}, status=400)

    if not conn_id or not sql_text.strip():
        return JsonResponse({"ok": False, "message": "Informe conexão e SQL."}, status=400)

    filters = _parse_where_filters(request)
    conn = get_object_or_404(DBConnection, pk=conn_id)

    try:
        cols, rows = _fetch_preview(conn, sql_text, limit=limit, filters=filters)
        return JsonResponse({"ok": True, "columns": cols, "rows": rows})
    except DriverMissing as e:
        return JsonResponse({"ok": False, "message": f"Driver ausente: {e}"}, status=400)
    except ValueError as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Erro ao executar preview: {e}"}, status=400)


@login_required
@require_POST
def query_page_adhoc(request: HttpRequest) -> JsonResponse:
    try:
        conn_id = int(request.POST.get("connection_id") or 0)
        sql_text = request.POST.get("sql_text") or ""
        offset = int(request.POST.get("offset") or 0)
        limit = _clamp_limit(request.POST.get("limit") or 1000, soft_max=2000)
    except Exception:
        return JsonResponse({"ok": False, "message": "Parâmetros inválidos."}, status=400)

    if not conn_id or not sql_text.strip():
        return JsonResponse({"ok": False, "message": "Informe conexão e SQL."}, status=400)

    filters = _parse_where_filters(request)
    conn = get_object_or_404(DBConnection, pk=conn_id)

    try:
        cols, rows, has_more = _fetch_page(conn, sql_text, offset=offset, limit=limit, filters=filters)
        next_offset = offset + len(rows)
        return JsonResponse({"ok": True, "columns": cols, "rows": rows, "next_offset": next_offset, "has_more": has_more})
    except DriverMissing as e:
        return JsonResponse({"ok": False, "message": f"Driver ausente: {e}"}, status=400)
    except ValueError as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Erro ao carregar página: {e}"}, status=400)


@login_required
@require_POST
def query_export_adhoc(request: HttpRequest) -> StreamingHttpResponse:
    try:
        conn_id = int(request.POST.get("connection_id") or 0)
        sql_text = request.POST.get("sql_text") or ""
    except Exception:
        return StreamingHttpResponse("Parâmetros inválidos.", status=400)

    if not conn_id or not sql_text.strip():
        return StreamingHttpResponse("Informe conexão e SQL.", status=400)

    filename = (request.POST.get("filename") or "export.csv").strip() or "export.csv"
    conn = get_object_or_404(DBConnection, pk=conn_id)
    filters = _parse_where_filters(request)

    def row_stream() -> Iterable[str]:
        # BOM para Excel reconhecer UTF-8
        yield "\ufeff"
        engine = conn.engine
        final_sql, params = _build_sql_with_filters(sql_text, engine, filters or [])

        py_conn, cur = _open_dbapi(conn)
        try:
            if params:
                cur.execute(final_sql, params)
            else:
                cur.execute(final_sql)

            columns = [d[0] for d in (cur.description or [])]

            # header
            buf = io.StringIO()
            writer = csv.writer(buf, delimiter=";", lineterminator="\n")
            writer.writerow(columns)
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

            # stream de dados
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                for r in batch:
                    writer.writerow(list(r))
                s = buf.getvalue()
                if s:
                    yield s
                buf.seek(0); buf.truncate(0)
        finally:
            try: cur.close()
            except Exception: pass
            try: py_conn.close()
            except Exception: pass

    resp = StreamingHttpResponse(row_stream(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
@require_POST
def query_count_adhoc(request: HttpRequest) -> JsonResponse:
    try:
        conn_id = int(request.POST.get("connection_id") or 0)
        sql_text = request.POST.get("sql_text") or ""
    except Exception:
        return JsonResponse({"ok": False, "message": "Parâmetros inválidos."}, status=400)

    if not conn_id or not (sql_text or "").strip():
        return JsonResponse({"ok": False, "message": "Informe conexão e SQL."}, status=400)

    filters = _parse_where_filters(request)
    conn = get_object_or_404(DBConnection, pk=conn_id)

    try:
        engine = conn.engine
        final_sql, params = _build_sql_with_filters(sql_text, engine, filters or [])
        count_sql = f"SELECT COUNT(*) FROM ({final_sql}) t"

        py_conn, cur = _open_dbapi(conn)
        try:
            if params:
                cur.execute(count_sql, params)
            else:
                cur.execute(count_sql)
            row = cur.fetchone()
            total = int(row[0]) if row else 0
            return JsonResponse({"ok": True, "count": total})
        finally:
            try: cur.close()
            except Exception: pass
            try: py_conn.close()
            except Exception: pass
    except DriverMissing as e:
        return JsonResponse({"ok": False, "message": f"Driver ausente: {e}"}, status=400)
    except ValueError as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": f"Erro ao contar: {e}"}, status=400)


@login_required
def connections_list_api(request: HttpRequest) -> JsonResponse:
    data = [
        {"id": c.id, "name": c.name, "engine": c.engine}
        for c in DBConnection.objects.all().order_by("name")
    ]
    return JsonResponse({"ok": True, "connections": data})


@login_required
def queries_list_api(request: HttpRequest) -> JsonResponse:
    qs = SavedQuery.objects.select_related("connection").filter(is_active=True)
    conn_id = request.GET.get("connection")
    if conn_id and str(conn_id).isdigit():
        qs = qs.filter(connection_id=int(conn_id))
    qs = qs.order_by("connection__name", "name")

    data = [
        {
            "id": q.id,
            "name": q.name,
            "connection_id": q.connection_id,
            "connection_name": q.connection.name,
        }
        for q in qs
    ]
    return JsonResponse({"ok": True, "queries": data})
