# altforce_sync/tasks.py
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from celery import shared_task
from django.utils import timezone

from .services import (
    sync_orders,
    sync_budgets,
    sync_leads,
    sync_customers,
)

MICRO = timedelta(microseconds=1)

# ============================================================
# Helpers
# ============================================================

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # tolera “Z” no final
    ss = s.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(ss)

def _window_loop(
    *,
    run_fn,
    from_dt: datetime,
    to_dt: datetime,
    window_days: int = 30,
    overlap_minutes: int = 0,
    sleep_seconds: float = 0.0,
    run_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Laço genérico de backfill em janelas (igual aos management commands).
    Executa localmente (sem subtasks), portanto não bloqueia com .get().
    """
    run_kwargs = run_kwargs or {}

    current_start = from_dt
    previous_span = None
    total = {
        "windows": 0,
        "received": 0,
        "created": 0,
        "updated": 0,
        "errors": 0,
    }

    while True:
        if current_start > to_dt:
            break

        candidate_end = current_start + timedelta(days=window_days) - MICRO
        current_end = candidate_end if candidate_end <= to_dt else to_dt

        span = (current_start, current_end)
        if previous_span is not None and span == previous_span:
            # failsafe contra loop
            break
        previous_span = span

        try:
            summary = run_fn(start_dt=current_start, end_dt=current_end, days=None, **run_kwargs)
        except Exception as e:
            summary = {"errors": [str(e)]}

        total["windows"]  += 1
        total["received"] += int(summary.get("count", 0) or 0)
        total["created"]  += int(summary.get("created", 0) or 0)
        total["updated"]  += int(summary.get("updated", 0) or 0)
        total["errors"]   += len(summary.get("errors", []) or [])

        if current_end >= to_dt:
            break

        next_start = current_end + MICRO
        if overlap_minutes > 0:
            with_overlap = next_start - timedelta(minutes=overlap_minutes)
            if with_overlap > current_start:
                next_start = with_overlap
        if next_start <= current_start:
            next_start = current_end + MICRO
        current_start = next_start

        if sleep_seconds > 0:
            try:
                time.sleep(sleep_seconds)
            except KeyboardInterrupt:
                break

    return total

# ============================================================
# Tasks unitárias por endpoint (mantidas)
# ============================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_altforce_orders_task(self, *, start_dt: Optional[str] = None, end_dt: Optional[str] = None, days: Optional[int] = 30) -> Dict[str, Any]:
    sdt = _parse_iso(start_dt)
    edt = _parse_iso(end_dt)
    return sync_orders(start_dt=sdt, end_dt=edt, days=days)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_altforce_budgets_task(
    self,
    *,
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    days: Optional[int] = 30,
    refetch_optionals_detail: bool = True,
    overwrite_empty_optionals: bool = False,
) -> Dict[str, Any]:
    sdt = _parse_iso(start_dt)
    edt = _parse_iso(end_dt)
    return sync_budgets(
        start_dt=sdt,
        end_dt=edt,
        days=days,
        refetch_optionals_detail=refetch_optionals_detail,
        overwrite_empty_optionals=overwrite_empty_optionals,
    )

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_altforce_leads_task(self, *, start_dt: Optional[str] = None, end_dt: Optional[str] = None, days: Optional[int] = 30) -> Dict[str, Any]:
    sdt = _parse_iso(start_dt)
    edt = _parse_iso(end_dt)
    return sync_leads(start_dt=sdt, end_dt=edt, days=days)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_altforce_customers_task(self) -> Dict[str, Any]:
    return sync_customers()

# ============================================================
# Backfill genérico (continua sendo uma task, mas sem .get())
# ============================================================

@shared_task(bind=True, max_retries=0)
def backfill_altforce_endpoint_task(
    self,
    *,
    endpoint: str,                 # "orders" | "budgets" | "leads"
    from_dt: Optional[str] = None, # ISO
    to_dt: Optional[str] = None,   # ISO
    window_days: int = 30,
    overlap_minutes: int = 0,
    sleep_seconds: float = 0.0,
    # budgets fine-tune:
    refetch_optionals_detail: bool = True,
    overwrite_empty_optionals: bool = False,
) -> Dict[str, Any]:
    now = timezone.now()
    _to_dt = _parse_iso(to_dt) or now
    base = _to_dt - timedelta(days=730)
    _from_dt = _parse_iso(from_dt) or datetime(year=base.year, month=base.month, day=base.day)

    endpoint = (endpoint or "").lower().strip()
    if endpoint == "orders":
        run_fn = sync_orders
        run_kwargs = {}
    elif endpoint == "leads":
        run_fn = sync_leads
        run_kwargs = {}
    elif endpoint == "budgets":
        run_fn = sync_budgets
        run_kwargs = dict(
            refetch_optionals_detail=refetch_optionals_detail,
            overwrite_empty_optionals=overwrite_empty_optionals,
        )
    else:
        raise ValueError("endpoint deve ser 'orders', 'leads' ou 'budgets'.")

    return _window_loop(
        run_fn=run_fn,
        from_dt=_from_dt,
        to_dt=_to_dt,
        window_days=window_days,
        overlap_minutes=overlap_minutes,
        sleep_seconds=sleep_seconds,
        run_kwargs=run_kwargs,
    )

# ============================================================
# Orquestrações ALL (sem subtasks síncronas)
# ============================================================

@shared_task(bind=True, max_retries=0)
def backfill_altforce_all_2y_task(
    self,
    *,
    window_days: int = 30,
    refetch_optionals_detail: bool = True,
    overwrite_empty_optionals: bool = False,
) -> Dict[str, Any]:
    """
    Backfill completo (2 anos) executado **dentro desta própria task**:
      - orders, leads e budgets em janelas; customers em full load.
    """
    now = timezone.now()
    to_dt = now
    base = to_dt - timedelta(days=730)
    from_dt = datetime(year=base.year, month=base.month, day=base.day)

    orders = _window_loop(
        run_fn=sync_orders,
        from_dt=from_dt, to_dt=to_dt,
        window_days=window_days,
    )
    leads = _window_loop(
        run_fn=sync_leads,
        from_dt=from_dt, to_dt=to_dt,
        window_days=window_days,
    )
    budgets = _window_loop(
        run_fn=sync_budgets,
        from_dt=from_dt, to_dt=to_dt,
        window_days=window_days,
        run_kwargs=dict(
            refetch_optionals_detail=refetch_optionals_detail,
            overwrite_empty_optionals=overwrite_empty_optionals,
        ),
    )
    customers = sync_customers()

    return {
        "orders": orders,
        "leads": leads,
        "budgets": budgets,
        "customers": customers,
    }

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_altforce_all_30d_task(self) -> Dict[str, Any]:
    """
    Sincroniza últimos 30 dias de TODOS os endpoints (executa localmente).
    """
    orders = sync_orders(days=30)
    budgets = sync_budgets(days=30, refetch_optionals_detail=True, overwrite_empty_optionals=False)
    leads = sync_leads(days=30)
    customers = sync_customers()

    return {
        "orders": orders,
        "budgets": budgets,
        "leads": leads,
        "customers": customers,
    }
