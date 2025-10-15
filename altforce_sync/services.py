from __future__ import annotations

import logging
import unicodedata
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone

from .models import (
    ApiPedido,
    ApiPedidoTecnicon,
    ApiPedidoOrcamento,
    ApiPedidoProduto,       # dApiPedidosProdutos
    ApiOrcamento,           # fApiOrcamentos
    ApiOrcamentoProduto,    # dApiOrcamentosProduto
    ApiOrcamentoOpcional,   # dApiOrcamentosOpcionais
    ApiOrcamentoObservacao, # dApiOrcamentosObservacoes
    ApiLead,                # fApiLeads
    ApiLeadProduto,         # dApiLeadsProdutos
    ApiCliente,             # fApiClientes
)
from .client import get as api_get

logger = logging.getLogger(__name__)

# ======================================================================================
# Feature flags por introspecção do modelo (compatibilidade com esquemas antigos/novos)
# ======================================================================================

def _model_has_field(model, name: str) -> bool:
    """
    Considera tanto o 'name' (ex.: 'item') quanto o 'attname' (ex.: 'item_id' em FKs).
    """
    try:
        for f in model._meta.get_fields():
            if getattr(f, "name", None) == name or getattr(f, "attname", None) == name:
                return True
        return False
    except Exception:
        return False

# orçamentos / produtos / opcionais / observações — suporte à coluna item_id
# (ApiOrcamentoProduto atualmente não possui 'item'/'item_id'; se um dia existir, detectamos)
HAS_ITEM_ID_ORC_PROD = _model_has_field(ApiOrcamentoProduto, "item_id")
HAS_ITEM_ID_OPC      = _model_has_field(ApiOrcamentoOpcional, "item") or _model_has_field(ApiOrcamentoOpcional, "item_id")
HAS_ITEM_ID_OBS      = _model_has_field(ApiOrcamentoObservacao, "item") or _model_has_field(ApiOrcamentoObservacao, "item_id")

# observações: suporte a salvar uma linha por observação (em vez de JSON agregado)
OBS_HAS_VALUE_FIELD    = _model_has_field(ApiOrcamentoObservacao, "value")
OBS_HAS_DESCRIPTION_ID = _model_has_field(ApiOrcamentoObservacao, "description_id")
# no modelo, a coluna chama 'ord' (não 'order')
OBS_HAS_ORDER_FIELD    = _model_has_field(ApiOrcamentoObservacao, "ord")

# =========================
# Utilidades de Data/Hora
# =========================

def _norm_dt_for_db(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Normaliza um datetime para compatibilidade com o backend:
    - Se USE_TZ=True: garante aware na timezone padrão do Django.
    - Se USE_TZ=False: converte para naive na timezone padrão do Django.
    """
    if dt is None:
        return None

    default_tz = timezone.get_default_timezone()

    if settings.USE_TZ:
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, default_tz)
        # ajusta para a tz padrão (sem mudar o instante)
        return dt.astimezone(default_tz)
    else:
        # projeto sem TZ: precisa salvar naive
        if timezone.is_aware(dt):
            return timezone.make_naive(dt, default_tz)
        return dt


def _parse_altforce_date(raw: Any) -> Optional[datetime]:
    """
    Aceita:
      - epoch em milissegundos (int/str)
      - ISO 8601 (ex.: '2025-10-07T12:00:00Z' ou '+00:00')
      - BR 'dd/mm/%Y %H:%M:%S'
    Retorna datetime já normalizado para o DB (vide _norm_dt_for_db).
    """
    if raw in (None, ""):
        return None

    try:
        # 1) epoch ms
        if isinstance(raw, (int, float)) or (isinstance(raw, str) and str(raw).isdigit()):
            dt = datetime.fromtimestamp(int(raw) / 1000.0, tz=dt_timezone.utc)
            return _norm_dt_for_db(dt)

        # 2) ISO 8601 (stdlib)
        if isinstance(raw, str):
            # trata 'Z' como UTC
            iso = raw.strip()
            if iso.endswith("Z"):
                iso = iso[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(iso)
                # se veio sem tz ou com tz, _norm_dt_for_db cuida
                return _norm_dt_for_db(dt)
            except ValueError:
                # 3) BR 'dd/mm/%Y %H:%M:%S'
                try:
                    dt = datetime.strptime(raw, "%d/%m/%Y %H:%M:%S")
                    return _norm_dt_for_db(dt)
                except ValueError:
                    pass

    except Exception:
        logger.exception("Falha ao parsear data %r", raw)
        return None

    logger.warning("Data inválida recebida (formato não reconhecido): %r", raw)
    return None


def _to_ms_utc(dt: datetime) -> int:
    """
    Converte datetime (naive ou aware) para epoch em milissegundos no UTC.
    """
    if dt is None:
        raise ValueError("datetime não pode ser None para conversão em ms")

    # Primeiro normaliza conforme settings
    dt_norm = _norm_dt_for_db(dt)

    # Garante aware UTC para extrair timestamp
    if timezone.is_naive(dt_norm):
        dt_norm = timezone.make_aware(dt_norm, timezone.get_default_timezone())
    dt_utc = dt_norm.astimezone(dt_timezone.utc)
    return int(dt_utc.timestamp() * 1000)


# =========================
# Helpers variados
# =========================

def _coerce_status(s: Optional[str]) -> str:
    """
    Limpa/normaliza o status recebido para os choices do modelo.
    """
    if not s:
        return "request"
    s = str(s).strip()

    # mapeamentos possíveis (ajuste conforme necessário)
    mapping = {
        "request": "request",
        "registered": "request",
        "inprogress": "inProgress",
        "in_progress": "inProgress",
        "processing": "inProgress",
        "concluded": "concluded",
        "finished": "concluded",
        "completed": "concluded",
        "canceled": "canceled",
        "cancelled": "canceled",
    }
    key = s.replace(" ", "").replace("-", "_").lower()
    return mapping.get(key, "request")


def _to_decimal(val: Any) -> Optional[Decimal]:
    if val in (None, ""):
        return None
    try:
        if isinstance(val, Decimal):
            return val
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        # str -> troca vírgula por ponto se vier formato BR
        s = str(val)
        if "," in s and "." not in s:
            s = s.replace(".", "").replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        logger.warning("Valor decimal inválido: %r", val)
        return None


def _g(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Acesso seguro a d[k1][k2]...  -> retorna default se não existir.
    """
    cur = d
    try:
        for k in keys:
            if cur is None:
                return default
            cur = cur.get(k)
        return cur if cur is not None else default
    except AttributeError:
        return default


def _norm_text(s: Optional[str]) -> str:
    """
    Normaliza texto para comparação: strip, lower, remove acentos.
    """
    if not s:
        return ""
    s = str(s).strip().lower()
    nfkd = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


# ====== NEW: helpers para garantir NULL quando user_external_id vier vazio/nulo ======

def _clean_str_or_none(v) -> Optional[str]:
    """
    Converte None, vazio, 'null', 'None' para None. Caso contrário, retorna string stripada.
    """
    if v in (None, "", "null", "None"):
        return None
    s = str(v).strip()
    return s if s else None


def _extract_user_external_id(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extrai exclusivamente o *external* id do usuário.
    NÃO faz fallback para 'id', 'userId', 'uuid' interno nem para altforce_id.
    Se a API entregar null/vazio, retorna None (salva NULL no banco).
    """
    u = _g(payload, "user") or {}
    ext = (
        u.get("external_id")
        or u.get("externalId")
        or payload.get("userExternalId")
        or payload.get("user_external_id")
    )
    return _clean_str_or_none(ext)


# =========================
# AltForce: /orders
# =========================

def _build_orders_path(start_ms: int, end_ms: int) -> str:
    # Evita depender de assinatura do client.get; coloca os params na própria URL.
    return f"/orders?start={start_ms}&end={end_ms}"


def _extract_orders_from_response(j: Any) -> List[Dict[str, Any]]:
    """
    Tenta extrair a lista de pedidos do JSON em formatos comuns.
    """
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for key in ("items", "data", "orders", "content", "results"):
            v = j.get(key)
            if isinstance(v, list):
                return v
    # fallback
    logger.warning("Resposta de /orders não reconhecida como lista. Tipo: %s", type(j).__name__)
    return []


def fetch_orders(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Busca pedidos no AltForce, exigindo 'start'/'end' em milissegundos.
    - Se start/end não forem informados, usa 'days' (padrão=7).
    """
    if not start_dt or not end_dt:
        if days is None:
            days = 7
        end_dt = end_dt or timezone.now()
        start_dt = start_dt or (end_dt - timedelta(days=int(days)))

    if start_dt > end_dt:
        raise ValueError("start_dt não pode ser maior que end_dt")

    start_ms = _to_ms_utc(start_dt)
    end_ms = _to_ms_utc(end_dt)

    path = _build_orders_path(start_ms, end_ms)
    logger.info("Buscando AltForce %s", path)

    # Usa client.get do app (já lida com headers/base URL/erros)
    j = api_get(path)
    pedidos = _extract_orders_from_response(j)
    logger.info("AltForce retornou %d pedidos no intervalo", len(pedidos))
    return pedidos


# ---------- upsert ApiPedido ----------

def upsert_pedido(p: Dict[str, Any]) -> Tuple[ApiPedido, bool]:
    """
    Converte o payload do AltForce e faz update_or_create no modelo ApiPedido.
    Retorna (obj, created)
    """
    # Identificador único
    altforce_id = (
        p.get("id")
        or p.get("uuid")
        or p.get("altforceId")
        or p.get("externalId")
    )
    if not altforce_id:
        raise ValueError(f"Pedido sem ID identificável: {p!r}")
    altforce_id = str(altforce_id)

    status = _coerce_status(p.get("status"))

    # Datas possíveis do payload
    raw_date = (
        p.get("date")
        or p.get("orderDate")
        or p.get("createdAt")
        or _g(p, "timestamps", "createdAt")
    )
    date_dt = _parse_altforce_date(raw_date)

    # >>> CORRIGIDO: sem fallback para userId/id interno <<<
    user_external_id = _extract_user_external_id(p)

    buyer_name = _g(p, "buyer", "name") or p.get("buyerName")
    freight_name = _g(p, "freight", "name") or p.get("freightName")
    payment_method_name = _g(p, "paymentMethod", "name") or p.get("paymentMethodName")
    payment_term_name = _g(p, "paymentTerm", "name") or p.get("paymentTermName")
    price_list_name = _g(p, "priceList", "name") or p.get("priceListName")

    total_price = (
        _to_decimal(p.get("totalPrice"))
        or _to_decimal(_g(p, "totals", "total"))
        or _to_decimal(p.get("total"))
    )
    sub_total_price = (
        _to_decimal(p.get("subTotalPrice"))
        or _to_decimal(_g(p, "totals", "subTotal"))
        or _to_decimal(p.get("subtotal"))
    )

    obj, created = ApiPedido.objects.update_or_create(
        altforce_id=altforce_id,
        defaults=dict(
            status=status,
            date=date_dt,
            user_external_id=user_external_id,
            buyer_name=buyer_name,
            freight_name=freight_name,
            payment_method_name=payment_method_name,
            payment_term_name=payment_term_name,
            price_list_name=price_list_name,
            total_price=total_price,
            sub_total_price=sub_total_price,
        ),
    )
    return obj, created


# ---------- TECNICON (steps) ----------

_TECNICON_STEP_NORM = _norm_text("Número do pedido TECNICON")

def _iter_steps(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Retorna uma lista/iterável de steps a partir do payload do pedido.
    Cobre formatos comuns: 'steps', 'flow.steps', etc.
    """
    steps = _g(payload, "steps") or _g(payload, "flow", "steps") or []
    if isinstance(steps, list):
        return steps
    return []


def _find_tecnicon_step(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Procura o step cujo name (ou stepModel.name) seja 'Número do pedido TECNICON'
    (comparação normalizada sem acentos/caixa).
    """
    for st in _iter_steps(payload):
        name = st.get("name") or _g(st, "stepModel", "name")
        if _norm_text(name) == _TECNICON_STEP_NORM:
            return st
    return None


def upsert_pedido_tecnicon(pedido: ApiPedido, payload: Dict[str, Any]) -> Tuple[Optional[ApiPedidoTecnicon], bool]:
    """
    Cria/atualiza o registro em dApiPedidosTecnicon para o pedido informado.
    Salva APENAS o 'content' do step TECNICON.
    Retorna (obj_ou_none, createdFlag).
    """
    step = _find_tecnicon_step(payload)
    if not step:
        # Nada para salvar – silencioso, mas com debug
        logger.debug("Pedido %s sem step TECNICON.", pedido.altforce_id)
        return None, False

    content = step.get("content")
    step_name = step.get("name") or _g(step, "stepModel", "name") or "Número do pedido TECNICON"
    step_id = step.get("id")

    # Normaliza content para string simples
    if content is None:
        content_str = None
    else:
        content_str = str(content).strip()

    obj, created = ApiPedidoTecnicon.objects.update_or_create(
        altforce_id=pedido.altforce_id,
        defaults=dict(
            pedido=pedido,
            step_id=step_id,
            step_name=step_name,
            content=content_str,
        ),
    )
    return obj, created


# ---------- ORÇAMENTOS (budgets em /orders) ----------

def _extract_budget_ids(payload: Dict[str, Any]) -> tuple[Optional[list[str]], bool]:
    """
    Retorna (lista_de_ids_ou_None, presente_flag)

    - Se o campo existir (em qualquer variação), 'presente_flag' = True e a lista pode ser [].*
    - Se não existir, 'presente_flag' = False e retornamos (None, False) para NÃO alterar nada no banco.
    """
    keys_present = any(k in payload for k in ("budgets_ids", "budgetsIds", "budgets"))
    if not keys_present:
        return None, False

    raw = (
        payload.get("budgets_ids")
        or payload.get("budgetsIds")
        or payload.get("budgets")
        or []
    )

    ids: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                bid = item.get("id")
                if bid:
                    ids.append(str(bid))
            elif item is not None:
                ids.append(str(item))
    elif isinstance(raw, (str, int)):
        ids.append(str(raw))

    # normaliza e filtra vazios
    ids = [x.strip() for x in ids if x and str(x).strip()]
    return ids, True


def upsert_pedido_orcamentos(pedido: ApiPedido, payload: Dict[str, Any]) -> dict:
    """
    Garante que os budgets do pedido no banco reflitam o que veio no payload.

    - Se o campo não vier no payload, NÃO altera nada.
    - Se vier [], apaga todos os vínculos existentes.
    - Se vier lista, cria os faltantes e remove os que não estão mais no payload.
    """
    ids, present = _extract_budget_ids(payload)
    if not present:
        return {"created": 0, "deleted": 0}  # não mexe

    desired: set[str] = set(ids or [])
    existing: set[str] = set(
        ApiPedidoOrcamento.objects.filter(pedido=pedido).values_list("budget_id", flat=True)
    )

    to_create = desired - existing
    to_delete = existing - desired

    created_n = 0
    if to_create:
        objs = [
            ApiPedidoOrcamento(
                pedido=pedido,
                altforce_id=pedido.altforce_id,
                budget_id=bid,
            )
            for bid in sorted(to_create)
        ]
        # Evita erro em duplicidade por concorrência
        ApiPedidoOrcamento.objects.bulk_create(objs, ignore_conflicts=True)
        created_n = len(objs)

    deleted_n = 0
    if to_delete:
        deleted_n, _ = ApiPedidoOrcamento.objects.filter(
            pedido=pedido, budget_id__in=list(to_delete)
        ).delete()

    return {"created": created_n, "deleted": deleted_n}


# ---------- PRODUTOS (products em /orders) ----------

def _products_field_present(payload: Dict[str, Any]) -> bool:
    """Indica se o payload trouxe explicitamente a lista de produtos."""
    return any(k in payload for k in ("products", "items", "itens", "orderProducts"))

def _iter_products(payload: Dict[str, Any]) -> list[dict]:
    """
    Retorna a lista de produtos a partir dos campos mais comuns.
    Prioriza 'products'; cai para 'items'/'itens'/'orderProducts' se necessário.
    """
    for key in ("products", "items", "itens", "orderProducts"):
        lst = payload.get(key)
        if isinstance(lst, list):
            return lst
    return []

def _norm_product_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza uma linha de produto do payload para nosso shape interno.
    Campos esperados no retorno:
      product_id, name, quantity, total_price, total_price_for_order,
      price_liquid, price_with_optionals, mask
    """
    pid = row.get("id") or row.get("uuid") or row.get("productId")
    name = row.get("name") or row.get("productName")

    quantity = _to_decimal(row.get("quantity"))
    total_price = _to_decimal(row.get("totalPrice"))
    total_price_for_order = _to_decimal(row.get("totalPriceForOrder"))

    # variações de chave para preço
    price_liquid = (
        _to_decimal(row.get("priceLiquid"))
        or _to_decimal(row.get("price_liquid"))
        or _to_decimal(row.get("priceNet"))
    )
    price_with_optionals = (
        _to_decimal(row.get("priceWithOptionals"))
        or _to_decimal(row.get("price_with_optionals"))
        or _to_decimal(row.get("priceWithExtras"))
    )

    mask = row.get("mask")

    return {
        "product_id": str(pid) if pid is not None else None,
        "name": name,
        "quantity": quantity,
        "total_price": total_price,
        "total_price_for_order": total_price_for_order,
        "price_liquid": price_liquid,
        "price_with_optionals": price_with_optionals,
        "mask": mask,
    }

def upsert_pedido_produtos(pedido: ApiPedido, payload: Dict[str, Any]) -> dict:
    """
    Sincroniza as linhas de produtos do pedido.

    - Se o payload NÃO trouxer 'products' (ou similar), não altera nada (retorna zeros).
    - Se trouxer, criamos/atualizamos cada product_id e apagamos os que não vieram dessa vez.
    """
    if not _products_field_present(payload):
        return {"created": 0, "updated": 0, "deleted": 0, "seen": 0}

    rows = _iter_products(payload)
    normalized: list[dict] = [_norm_product_row(r) for r in rows]

    # product_id é obrigatório para chave natural; filtra os sem id
    normalized = [r for r in normalized if r.get("product_id")]

    desired_ids: set[str] = {r["product_id"] for r in normalized}
    existing_ids: set[str] = set(
        ApiPedidoProduto.objects.filter(pedido=pedido).values_list("product_id", flat=True)
    )

    to_create = desired_ids - existing_ids
    to_update = desired_ids & existing_ids
    to_delete = existing_ids - desired_ids

    created_n = 0
    updated_n = 0
    deleted_n = 0

    # CREATE em lote
    if to_create:
        objs = []
        for r in normalized:
            if r["product_id"] in to_create:
                objs.append(
                    ApiPedidoProduto(
                        pedido=pedido,
                        altforce_id=pedido.altforce_id,
                        product_id=r["product_id"],
                        name=r["name"],
                        quantity=r["quantity"],
                        total_price=r["total_price"],
                        total_price_for_order=r["total_price_for_order"],
                        price_liquid=r["price_liquid"],
                        price_with_optionals=r["price_with_optionals"],
                        mask=r["mask"],
                    )
                )
        ApiPedidoProduto.objects.bulk_create(objs, ignore_conflicts=True)
        created_n = len(objs)

    # UPDATE linha a linha
    if to_update:
        data_by_id = {r["product_id"]: r for r in normalized}
        for pid in to_update:
            r = data_by_id.get(pid) or {}
            ApiPedidoProduto.objects.filter(pedido=pedido, product_id=pid).update(
                name=r.get("name"),
                quantity=r.get("quantity"),
                total_price=r.get("total_price"),
                total_price_for_order=r.get("total_price_for_order"),
                price_liquid=r.get("price_liquid"),
                price_with_optionals=r.get("price_with_optionals"),
                mask=r.get("mask"),
            )
        updated_n = len(to_update)

    # DELETE dos que saíram
    if to_delete:
        deleted_n, _ = ApiPedidoProduto.objects.filter(
            pedido=pedido, product_id__in=list(to_delete)
        ).delete()

    return {"created": created_n, "updated": updated_n, "deleted": deleted_n, "seen": len(normalized)}


# =========================
# AltForce: /budgets (fApiOrcamentos + dimensões)
# =========================

def _build_budgets_path(start_ms: int, end_ms: int) -> str:
    return f"/budgets?start={start_ms}&end={end_ms}"

def _extract_budgets_from_response(j: Any) -> List[Dict[str, Any]]:
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for key in ("items", "data", "budgets", "content", "results"):
            v = j.get(key)
            if isinstance(v, list):
                return v
    logger.warning("Resposta de /budgets não reconhecida como lista. Tipo: %s", type(j).__name__)
    return []

def fetch_budgets(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Busca orçamentos no AltForce, exigindo 'start'/'end' em milissegundos (como /orders).
    Se não informar start/end, usa 'days' (padrão: 7).
    """
    if not start_dt or not end_dt:
        if days is None:
            days = 7
        end_dt = end_dt or timezone.now()
        start_dt = start_dt or (end_dt - timedelta(days=int(days)))

    if start_dt > end_dt:
        raise ValueError("start_dt não pode ser maior que end_dt")

    start_ms = _to_ms_utc(start_dt)
    end_ms = _to_ms_utc(end_dt)

    path = _build_budgets_path(start_ms, end_ms)
    logger.info("Buscando AltForce %s", path)

    j = api_get(path)
    budgets = _extract_budgets_from_response(j)
    logger.info("AltForce retornou %d budgets no intervalo", len(budgets))
    return budgets

def _addr(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retorna o dict de address tratando também o typo 'adress'.
    """
    return obj.get("address") or obj.get("adress") or {}

def upsert_orcamento(p: Dict[str, Any]) -> Tuple[ApiOrcamento, bool]:
    """
    Converte o payload do AltForce (/budgets) e faz update_or_create em ApiOrcamento.
    """
    # id
    altforce_id = p.get("id") or p.get("uuid") or p.get("altforceId") or p.get("externalId")
    if not altforce_id:
        raise ValueError(f"Orçamento sem ID identificável: {p!r}")
    altforce_id = str(altforce_id)

    # date
    raw_date = p.get("date") or p.get("createdAt") or _g(p, "timestamps", "createdAt")
    date_dt = _parse_altforce_date(raw_date)

    # user.* — prioridade ao 'external_id' conforme solicitado (sem fallback para 'id')
    user = _g(p, "user", default={}) or {}
    user_name = user.get("name")
    user_external_id = _extract_user_external_id(p)

    address = _addr(user)
    user_city_name    = _g(address, "city", "name")
    user_state_name   = _g(address, "state", "name")
    user_country_name = _g(address, "country", "name")

    # buyer.*
    buyer = _g(p, "buyer", default={}) or {}
    buyer_id    = buyer.get("id") or buyer.get("externalId")
    buyer_name  = buyer.get("name")
    buyer_email = buyer.get("email")
    buyer_phone = buyer.get("phone")

    # valores
    total_price     = _to_decimal(p.get("totalPrice")     or _g(p, "totals", "total")    or p.get("total"))
    sub_total_price = _to_decimal(p.get("subTotalPrice")  or _g(p, "totals", "subTotal") or p.get("subtotal"))

    # freight
    freight_name = _g(p, "freight", "name") or p.get("freightName")

    obj, created = ApiOrcamento.objects.update_or_create(
        altforce_id=altforce_id,
        defaults=dict(
            date=date_dt,
            user_external_id=user_external_id,
            user_name=user_name,
            user_city_name=user_city_name,
            user_state_name=user_state_name,
            user_country_name=user_country_name,
            buyer_id=str(buyer_id) if buyer_id is not None else None,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            total_price=total_price,
            sub_total_price=sub_total_price,
            freight_name=freight_name,
        ),
    )
    return obj, created

# ---------- helpers de produtos de /budgets ----------

def fetch_budget_detail_by_id(altforce_id: str) -> Optional[Dict[str, Any]]:
    """
    Tenta buscar o orçamento completo por ID.
    Suporta alguns formatos comuns da API: /budgets/{id}, /budgets?ids=, /budgets?id=
    Retorna um único dict do orçamento ou None.
    """
    paths = [
        f"/budgets/{altforce_id}",
        f"/budgets?ids={altforce_id}",
        f"/budgets?id={altforce_id}",
    ]
    for path in paths:
        try:
            j = api_get(path)
        except Exception:
            logger.exception("Falha ao buscar detalhe do orçamento %s em %s", altforce_id, path)
            continue

        # se vier dict do orçamento direto
        if isinstance(j, dict) and (j.get("id") or j.get("uuid") or j.get("altforceId")):
            jid = str(j.get("id") or j.get("uuid") or j.get("altforceId"))
            if jid == str(altforce_id):
                return j

        # se vier lista, procura o id
        if isinstance(j, list):
            for x in j:
                xid = x.get("id") or x.get("uuid") or x.get("altforceId")
                if xid and str(xid) == str(altforce_id):
                    return x

        # se vier dict com wrapper (items/data/results/etc.)
        if isinstance(j, dict):
            for key in ("items", "data", "budgets", "content", "results"):
                v = j.get(key)
                if isinstance(v, list):
                    for x in v:
                        xid = x.get("id") or x.get("uuid") or x.get("altforceId")
                        if xid and str(xid) == str(altforce_id):
                            return x
    return None

def _budgets_products_field_present(payload: Dict[str, Any]) -> bool:
    return any(k in payload for k in ("products", "items", "itens", "budgetProducts"))

def _iter_budget_products(payload: Dict[str, Any]) -> list[dict]:
    for key in ("products", "items", "itens", "budgetProducts"):
        lst = payload.get(key)
        if isinstance(lst, list):
            return lst
    return []

def _extract_item_id(row: Dict[str, Any], idx: int) -> str:
    """
    Extrai um 'item_id' lógico da linha do AltForce.
    (Hoje não usamos para FK; mantido por compat.)
    """
    raw = (
        row.get("item_id")
        or row.get("itemId")
        or row.get("lineId")
        or row.get("line_id")
        or None
    )
    if raw is None:
        raw = idx + 1  # 1-based
    return str(raw)

def _norm_budget_product_row(row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """
    Campos normalizados:
      - item_id        (id lógico da linha no payload; não é FK)
      - product_id     (id do produto AltForce)
      - name           (nome do produto)
      - quantity       (qtde)
      - total_price    (total da linha)
    """
    pid = row.get("id") or row.get("uuid") or row.get("productId")
    name = row.get("name") or row.get("productName")
    quantity = _to_decimal(row.get("quantity"))
    total_price = _to_decimal(row.get("totalPrice"))
    item_id = _extract_item_id(row, idx)

    return {
        "item_id": item_id,
        "product_id": str(pid) if pid is not None else None,
        "name": name,
        "quantity": quantity,
        "total_price": total_price,
    }

# ---------- dApiOrcamentosProduto ----------

def upsert_orcamento_produtos(orcamento: ApiOrcamento, payload: Dict[str, Any]) -> dict:
    """
    Sincroniza as linhas de produtos do orçamento.

    Compat com 2 esquemas:
      - *novo*: chave natural (orcamento, item_id)  [ativado se ApiOrcamentoProduto tiver item_id]
      - *antigo*: chave natural (orcamento, product_id)

    - Se o payload NÃO trouxer 'products' (ou similar), não altera nada.
    - Se trouxer, upsert e remove os que não vierem na carga.
    """
    if not _budgets_products_field_present(payload):
        return {"created": 0, "updated": 0, "deleted": 0, "seen": 0}

    rows = _iter_budget_products(payload)
    normalized: list[dict] = [_norm_budget_product_row(r, idx) for idx, r in enumerate(rows)]
    # product_id é obrigatório para salvar
    normalized = [r for r in normalized if r.get("product_id")]

    key_name = "item_id" if HAS_ITEM_ID_ORC_PROD else "product_id"

    desired_ids: set[str] = {r[key_name] for r in normalized}
    if HAS_ITEM_ID_ORC_PROD:
        existing_ids: set[str] = set(
            ApiOrcamentoProduto.objects.filter(orcamento=orcamento).values_list("item_id", flat=True)
        )
    else:
        existing_ids = set(
            ApiOrcamentoProduto.objects.filter(orcamento=orcamento).values_list("product_id", flat=True)
        )

    to_create = desired_ids - existing_ids
    to_update = desired_ids & existing_ids
    to_delete = existing_ids - desired_ids

    created_n = 0
    updated_n = 0
    deleted_n = 0

    if to_create:
        objs = []
        for r in normalized:
            if r[key_name] in to_create:
                kwargs = dict(
                    orcamento=orcamento,
                    altforce_id=orcamento.altforce_id,
                    product_id=r["product_id"],
                    name=r["name"],
                    quantity=r["quantity"],
                    total_price=r["total_price"],
                )
                if HAS_ITEM_ID_ORC_PROD:
                    kwargs["item_id"] = r["item_id"]
                objs.append(ApiOrcamentoProduto(**kwargs))
        ApiOrcamentoProduto.objects.bulk_create(objs, ignore_conflicts=True)
        created_n = len(objs)

    if to_update:
        data_by_id = {r[key_name]: r for r in normalized}
        for kid in to_update:
            r = data_by_id.get(kid) or {}
            qs = ApiOrcamentoProduto.objects.filter(orcamento=orcamento)
            qs = qs.filter(item_id=kid) if HAS_ITEM_ID_ORC_PROD else qs.filter(product_id=kid)
            update_fields = dict(
                product_id=r.get("product_id"),
                name=r.get("name"),
                quantity=r.get("quantity"),
                total_price=r.get("total_price"),
            )
            if HAS_ITEM_ID_ORC_PROD:
                update_fields["item_id"] = r.get("item_id")
            qs.update(**update_fields)
        updated_n = len(to_update)

    if to_delete:
        qs = ApiOrcamentoProduto.objects.filter(orcamento=orcamento)
        qs = qs.filter(item_id__in=list(to_delete)) if HAS_ITEM_ID_ORC_PROD else qs.filter(product_id__in=list(to_delete))
        deleted_n, _ = qs.delete()

    return {"created": created_n, "updated": updated_n, "deleted": deleted_n, "seen": len(normalized)}

# ---------- dApiOrcamentosOpcionais (products[].optionalsSelected) ----------

def _infer_selected_from_groups(row: Dict[str, Any]) -> list[str]:
    """
    Coleta IDs selecionados a partir de products[].optionals[] e products[].acessories[]
    (ou 'accessories'), olhando para optionalSelected.id ou variações.
    """
    out: list[str] = []
    for coll_key in ("optionals", "options", "acessories", "accessories"):
        coll = row.get(coll_key) or []
        if not isinstance(coll, list):
            continue
        for g in coll:
            if not isinstance(g, dict):
                continue
            # Seleção simples por grupo
            sel_id = _g(g, "optionalSelected", "id") or _g(g, "optional_selected", "id") or g.get("optionalSelectedId")
            if sel_id:
                out.append(str(sel_id))

            # Multi-seleção dentro do grupo (variações vistas em alguns payloads)
            grp_sel = g.get("optionalsSelected") or g.get("selectedOptionals")
            if isinstance(grp_sel, list):
                for s in grp_sel:
                    if isinstance(s, dict):
                        sid = s.get("id") or s.get("value") or s.get("code")
                        if sid:
                            out.append(str(sid))
                    elif s:
                        out.append(str(s))

    # de-dup mantendo ordem
    dedup: list[str] = []
    seen = set()
    for x in out:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def _has_optionals_key(row: Dict[str, Any]) -> bool:
    """
    Considera presença de chave no nível do produto OU seleção inferida via grupos.
    """
    if any(k in row for k in ("optionalsSelected", "optionals_selected", "selectedOptionals")):
        return True
    return len(_infer_selected_from_groups(row)) > 0


def _get_optionals_value(row: Dict[str, Any]) -> Optional[list]:
    """
    Retorna:
      - lista de IDs selecionados (strings) se houve sinal explícito (no produto ou grupos);
      - [] quando explicitamente vazio;
      - None quando não há sinal nenhum (não tocar no banco).
    """
    # 1) Preferir campo no nível do produto quando presente
    for k in ("optionalsSelected", "optionals_selected", "selectedOptionals"):
        if k in row:
            val = row[k]
            # Vazio? Tentar inferir pelos grupos antes de concluir []
            if val in (None, "", {}, (), []):
                fallback = _infer_selected_from_groups(row)
                return fallback if fallback else []
            if isinstance(val, (list, tuple)):
                norm: list[str] = []
                for v in val:
                    if isinstance(v, dict):
                        sid = v.get("id") or v.get("value") or v.get("code")
                        if sid is not None:
                            norm.append(str(sid))
                    elif v is not None:
                        norm.append(str(v))
                if not norm:
                    fallback = _infer_selected_from_groups(row)
                    return fallback if fallback else []
                return norm
            if isinstance(val, dict):
                # Padrões comuns
                if "ids" in val and isinstance(val["ids"], list):
                    norm = [str(x.get("id") if isinstance(x, dict) else x) for x in val["ids"] if x is not None]
                    if norm:
                        return norm
                if "id" in val and val["id"] is not None:
                    return [str(val["id"])]
                fallback = _infer_selected_from_groups(row)
                return fallback if fallback else []
            # Escalar
            return [str(val)]

    # 2) Sem campo no produto → inferir pelos grupos
    inferred = _infer_selected_from_groups(row)
    return inferred if inferred else None


def _find_item_pk_for_product(orcamento: ApiOrcamento, product_id: str) -> Optional[int]:
    """
    Localiza o id (PK) do item em dApiOrcamentosProduto para (orcamento, product_id).
    """
    return ApiOrcamentoProduto.objects.filter(
        orcamento=orcamento, product_id=product_id
    ).values_list("id", flat=True).first()


def upsert_orcamento_opcionais(
    orcamento: ApiOrcamento,
    payload: Dict[str, Any],
    allow_refetch: bool = True,           # controla refetch do detalhe
    overwrite_empty_optionals: bool = False,  # NOVO: evita gravar [] quando a API vier vazia
    _refetched: bool = False,             # evita recursão infinita
) -> dict:
    """
    Salva opcionais (products[].optionalsSelected) dos produtos do orçamento.

    Regras:
      - Se o payload NÃO trouxer 'products' (ou similar), faz 1 refetch do detalhe (quando habilitado).
      - Se a chave de opcionais NÃO vier no produto, não altera nada para aquele item.
      - Se vier vazia:
            * só gravamos [] quando 'confirmado' (após refetch OU quando refetch foi explicitamente desabilitado);
            * E **apenas** se overwrite_empty_optionals=True. Caso contrário, ignoramos para não apagar dados válidos.
      - Se vier com conteúdo, gravamos/atualizamos.
    """
    products = _iter_budget_products(payload)

    # Sem products → tentar refetch 1 vez
    if not products:
        if allow_refetch and not _refetched:
            detail = fetch_budget_detail_by_id(orcamento.altforce_id)
            if detail:
                logger.info("Refetch (sem products) para orçamento %s.", orcamento.altforce_id)
                return upsert_orcamento_opcionais(
                    orcamento, detail, allow_refetch=False,
                    overwrite_empty_optionals=overwrite_empty_optionals,
                    _refetched=True
                )
        return {"created": 0, "updated": 0, "seen": 0, "deleted": 0}

    created_n = 0
    updated_n = 0
    seen_n = 0

    # Vazio "confirmado": pós-refetch OU quando refetch está desativado
    confirm_empty = _refetched or (not allow_refetch)

    # Pré-scan para decidir refetch (caso haja ausentes/vazios)
    needs_refetch = False
    for row in products:
        val = _get_optionals_value(row)  # None, [] ou lista
        if val is None or (isinstance(val, list) and not val):
            needs_refetch = True

    if allow_refetch and needs_refetch and not _refetched:
        detail = fetch_budget_detail_by_id(orcamento.altforce_id)
        if detail:
            logger.info("Refetch (preencher opcionais) orçamento %s.", orcamento.altforce_id)
            return upsert_orcamento_opcionais(
                orcamento, detail, allow_refetch=False,
                overwrite_empty_optionals=overwrite_empty_optionals,
                _refetched=True
            )

    # Processa por item
    for row in products:
        pid = row.get("id") or row.get("uuid") or row.get("productId")
        if not pid:
            continue
        pid = str(pid)

        optionals_raw = _get_optionals_value(row)  # None -> não tocar; []/lista -> explícito
        if optionals_raw is None:
            continue
        seen_n += 1

        # NÃO sobrescrever com [] se veio vazio e não solicitamos isso
        if optionals_raw == [] and not (confirm_empty and overwrite_empty_optionals):
            # ignoramos para não apagar o que já existe
            continue

        # tenta resolver FK do item (quando o modelo suporta)
        item_pk = None
        if HAS_ITEM_ID_OPC:
            item_pk = _find_item_pk_for_product(orcamento, pid)
            if not item_pk:
                logger.warning(
                    "Item de produto não encontrado para orçamento=%s product_id=%s ao salvar opcionais.",
                    orcamento.altforce_id, pid
                )

        qs = ApiOrcamentoOpcional.objects.filter(orcamento=orcamento, product_id=pid)
        if HAS_ITEM_ID_OPC and item_pk:
            qs = qs.filter(item_id=item_pk)
        obj = qs.first()

        # CREATE
        if obj is None:
            # cria se houver conteúdo, ou se vazio-confirmado + overwrite solicitado
            if optionals_raw or (confirm_empty and overwrite_empty_optionals):
                kwargs = dict(
                    orcamento=orcamento,
                    altforce_id=orcamento.altforce_id,
                    product_id=pid,
                    optionals_selected=optionals_raw or [],
                )
                if HAS_ITEM_ID_OPC and item_pk:
                    kwargs["item_id"] = item_pk
                ApiOrcamentoOpcional.objects.create(**kwargs)
                created_n += 1
            continue

        # UPDATE
        update_fields = []

        if obj.altforce_id != orcamento.altforce_id:
            obj.altforce_id = orcamento.altforce_id
            update_fields.append("altforce_id")

        if HAS_ITEM_ID_OPC and item_pk and getattr(obj, "item_id", None) != item_pk:
            obj.item_id = item_pk
            update_fields.append("item_id")

        if optionals_raw:
            if obj.optionals_selected != optionals_raw:
                obj.optionals_selected = optionals_raw
                update_fields.append("optionals_selected")
        else:
            # só limpar para [] quando explicitamente permitido
            if confirm_empty and overwrite_empty_optionals and obj.optionals_selected != []:
                obj.optionals_selected = []
                update_fields.append("optionals_selected")

        if update_fields:
            obj.save(update_fields=update_fields)
            updated_n += 1

    return {"created": created_n, "updated": updated_n, "seen": seen_n, "deleted": 0}



# ---------- dApiOrcamentosObservacoes (products[].descriptions[].value) ----------

def _extract_descriptions_values_with_meta(row: Dict[str, Any]) -> list[dict]:
    """
    Coleta products[].descriptions como lista de dicts com:
      {"value": <str>, "id": <str|None>}

    Aceita 'descriptions' (lista/dict/str) e 'description' (compat).
    """
    desc = row.get("descriptions") or row.get("description") or None
    out: list[dict] = []
    if not desc:
        return out

    if isinstance(desc, list):
        for item in desc:
            if isinstance(item, dict):
                v = item.get("value")
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                did = item.get("id")
                out.append({"value": s, "id": str(did) if did is not None else None})
            elif isinstance(item, str):
                s = item.strip()
                if s:
                    out.append({"value": s, "id": None})
    elif isinstance(desc, dict):
        v = desc.get("value")
        if v is not None:
            s = str(v).strip()
            if s:
                did = desc.get("id")
                out.append({"value": s, "id": str(did) if did is not None else None})
    elif isinstance(desc, str):
        s = desc.strip()
        if s:
            out.append({"value": s, "id": None})

    return out

def upsert_orcamento_observacoes(orcamento: ApiOrcamento, payload: Dict[str, Any]) -> dict:
    """
    Salva observações de cada produto do orçamento.

    NOVO ESQUEMA (preferencial):
      - Se a tabela possuir as colunas 'item_id' e 'value', gravamos **uma linha por observação**:
            orcamento_id, item_id, product_id, [description_id], [ord], value
        (apagamos as linhas anteriores daquele item antes de recriar)

    ESQUEMA ANTIGO (fallback):
      - Se 'value' não existir, mantém o comportamento antigo agregando em JSON (descriptions_values)
        por (orcamento, product_id) (ou item_id se existir).
    """
    products = _iter_budget_products(payload)
    if not products:
        return {"created": 0, "updated": 0, "seen": 0, "deleted": 0}

    created_n = 0
    updated_n = 0
    seen_n = 0
    deleted_n = 0

    # PREFETCH para evitar N+1 ao resolver item_pk
    item_pk_by_product: dict[str, int] = {}
    if HAS_ITEM_ID_OBS:
        item_pk_by_product = dict(
            ApiOrcamentoProduto.objects.filter(orcamento=orcamento)
            .values_list("product_id", "id")
        )

    for idx, row in enumerate(products):
        pid = row.get("id") or row.get("uuid") or row.get("productId")
        if pid is None:
            continue
        pid = str(pid)

        has_desc_key = ("descriptions" in row) or ("description" in row)
        if not has_desc_key:
            continue

        # --- caminho 1: novo esquema (linha por observação) ---
        if OBS_HAS_VALUE_FIELD:
            # item_id (FK) => aponta para o PK do item em dApiOrcamentosProduto
            item_pk = item_pk_by_product.get(pid) if HAS_ITEM_ID_OBS else None

            # apaga o grupo anterior (por item_id se existir, senão por product_id)
            qs = ApiOrcamentoObservacao.objects.filter(orcamento=orcamento)
            if HAS_ITEM_ID_OBS and item_pk:
                qs = qs.filter(item_id=item_pk)
            else:
                qs = qs.filter(product_id=pid)
            dcount, _ = qs.delete()
            deleted_n += dcount

            items = _extract_descriptions_values_with_meta(row)
            objs = []
            for order_idx, item in enumerate(items, start=1):
                val = item.get("value")
                if not val:
                    continue
                kwargs = dict(
                    orcamento=orcamento,
                    altforce_id=orcamento.altforce_id,
                    product_id=pid,
                    value=val,
                )
                if HAS_ITEM_ID_OBS and item_pk:
                    kwargs["item_id"] = item_pk
                if OBS_HAS_DESCRIPTION_ID:
                    kwargs["description_id"] = item.get("id")
                if OBS_HAS_ORDER_FIELD:
                    kwargs["ord"] = order_idx
                objs.append(ApiOrcamentoObservacao(**kwargs))
            if objs:
                ApiOrcamentoObservacao.objects.bulk_create(objs, ignore_conflicts=True)
                created_n += len(objs)
            seen_n += 1
        else:
            # --- caminho 2: esquema antigo (JSON agregado em descriptions_values) ---
            values = [i["value"] for i in _extract_descriptions_values_with_meta(row)]
            if values is None:
                continue
            seen_n += 1

            # upsert por (orcamento, item_id?) ou (orcamento, product_id)
            defaults = dict(
                altforce_id=orcamento.altforce_id,
                descriptions_values=values,
                product_id=pid,
            )
            if HAS_ITEM_ID_OBS:
                item_pk = item_pk_by_product.get(pid)
                if item_pk:
                    defaults["item_id"] = item_pk
                _, created = ApiOrcamentoObservacao.objects.update_or_create(
                    orcamento=orcamento,
                    product_id=pid,  # mantemos chave natural por product_id
                    defaults=defaults,
                )
            else:
                _, created = ApiOrcamentoObservacao.objects.update_or_create(
                    orcamento=orcamento,
                    product_id=pid,
                    defaults=defaults,
                )
            if created:
                created_n += 1
            else:
                updated_n += 1

    return {"created": created_n, "updated": updated_n, "seen": seen_n, "deleted": deleted_n}


def sync_budgets(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    days: Optional[int] = None,
    refetch_optionals_detail: bool = True,     # controla se vamos refazer GET do detalhe dos opcionais
    overwrite_empty_optionals: bool = False,   # quando True, permite sobrescrever com [] opcionais vazios “confirmados”
) -> Dict[str, Any]:
    """
    Busca /budgets e faz upsert em:
      - fApiOrcamentos
      - dApiOrcamentosProduto
      - dApiOrcamentosOpcionais
      - dApiOrcamentosObservacoes

    Parâmetros:
      start_dt / end_dt / days:
        - Janela de busca. Se start/end não forem informados, usa 'days' (padrão do fetch_budgets = 7).
      refetch_optionals_detail:
        - Se True, quando products[].optionalsSelected vier ausente/vazio, tenta 1 refetch do detalhe (/budgets/{id})
          para evitar gravar [] indevidamente.
      overwrite_empty_optionals:
        - Se False (padrão): não sobrescreve no banco com [] quando a API retornar vazio; preserva o que já estava salvo.
        - Se True: quando o vazio estiver “confirmado” (pós-refetch ou refetch desativado), escreve [].
    """
    budgets = fetch_budgets(start_dt=start_dt, end_dt=end_dt, days=days)

    created_count = 0
    updated_count = 0

    prod_created_total = 0
    prod_updated_total = 0
    prod_deleted_total = 0
    prod_seen_total    = 0

    opt_created_total = 0
    opt_updated_total = 0
    opt_deleted_total = 0  # mantido para consistência
    opt_seen_total    = 0

    obs_created_total = 0
    obs_updated_total = 0
    obs_deleted_total = 0  # mantido para consistência
    obs_seen_total    = 0

    errors: List[str] = []

    for b in budgets:
        try:
            # Cabeçalho do orçamento (fApiOrcamentos)
            orc_obj, created = upsert_orcamento(b)
            if created:
                created_count += 1
            else:
                updated_count += 1

            # Produtos do orçamento (dApiOrcamentosProduto)
            try:
                pr = upsert_orcamento_produtos(orc_obj, b)
                prod_created_total += int(pr.get("created", 0) or 0)
                prod_updated_total += int(pr.get("updated", 0) or 0)
                prod_deleted_total += int(pr.get("deleted", 0) or 0)
                prod_seen_total    += int(pr.get("seen", 0) or 0)
            except Exception as e:
                logger.exception("Falha ao salvar produtos para orçamento %s", orc_obj.altforce_id)
                errors.append(f"orc_produtos:{orc_obj.altforce_id}:{e}")

            # Opcionais por produto (dApiOrcamentosOpcionais)
            try:
                op = upsert_orcamento_opcionais(
                    orcamento=orc_obj,
                    payload=b,
                    allow_refetch=refetch_optionals_detail,
                    overwrite_empty_optionals=overwrite_empty_optionals,
                )
                opt_created_total += int(op.get("created", 0) or 0)
                opt_updated_total += int(op.get("updated", 0) or 0)
                opt_deleted_total += int(op.get("deleted", 0) or 0)
                opt_seen_total    += int(op.get("seen", 0) or 0)
            except Exception as e:
                logger.exception("Falha ao salvar opcionais para orçamento %s", orc_obj.altforce_id)
                errors.append(f"orc_opcionais:{orc_obj.altforce_id}:{e}")

            # Observações (descriptions[].value) por produto (dApiOrcamentosObservacoes)
            try:
                ob = upsert_orcamento_observacoes(orc_obj, b)
                obs_created_total += int(ob.get("created", 0) or 0)
                obs_updated_total += int(ob.get("updated", 0) or 0)
                obs_deleted_total += int(ob.get("deleted", 0) or 0)
                obs_seen_total    += int(ob.get("seen", 0) or 0)
            except Exception as e:
                logger.exception("Falha ao salvar observações para orçamento %s", orc_obj.altforce_id)
                errors.append(f"orc_observacoes:{orc_obj.altforce_id}:{e}")

        except Exception as e:
            logger.exception("Falha ao processar orçamento: %r", b)
            errors.append(str(e))

    total = len(budgets)
    summary = {
        "count": total,
        "created": created_count,
        "updated": updated_count,
        # produtos
        "orc_produtos_created": prod_created_total,
        "orc_produtos_updated": prod_updated_total,
        "orc_produtos_deleted": prod_deleted_total,
        "orc_produtos_seen":    prod_seen_total,
        # opcionais
        "orc_opcionais_created": opt_created_total,
        "orc_opcionais_updated": opt_updated_total,
        "orc_opcionais_deleted": opt_deleted_total,
        "orc_opcionais_seen":    opt_seen_total,
        # observações
        "orc_observacoes_created": obs_created_total,
        "orc_observacoes_updated": obs_updated_total,
        "orc_observacoes_deleted": obs_deleted_total,
        "orc_observacoes_seen":    obs_seen_total,
        "errors": errors,
    }
    logger.info("Sync AltForce (budgets) concluído: %s", summary)
    return summary



# =========================
# Orquestração principal de /orders
# =========================

def sync_orders(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Orquestra a busca e o upsert dos pedidos.
    Também persiste o número TECNICON (quando existir no step), os budgets_ids e os products.
    Retorna um resumo com contagens.
    """
    pedidos = fetch_orders(start_dt=start_dt, end_dt=end_dt, days=days)

    created_count = 0
    updated_count = 0
    tecnicon_created = 0
    tecnicon_updated = 0
    orc_created_total = 0
    orc_deleted_total = 0
    produtos_created_total = 0
    produtos_updated_total = 0
    produtos_deleted_total = 0
    produtos_seen_total = 0
    errors: List[str] = []

    for p in pedidos:
        try:
            pedido_obj, created = upsert_pedido(p)
            if created:
                created_count += 1
            else:
                updated_count += 1

            # TECNICON
            try:
                tecnicon_obj, t_created = upsert_pedido_tecnicon(pedido_obj, p)
                if tecnicon_obj:
                    if t_created:
                        tecnicon_created += 1
                    else:
                        tecnicon_updated += 1
            except Exception as e:
                logger.exception("Falha ao salvar TECNICON para pedido %s", pedido_obj.altforce_id)
                errors.append(f"tecnicon:{pedido_obj.altforce_id}:{e}")

            # ORÇAMENTOS
            try:
                oc = upsert_pedido_orcamentos(pedido_obj, p)
                orc_created_total += int(oc.get("created", 0) or 0)
                orc_deleted_total += int(oc.get("deleted", 0) or 0)
            except Exception as e:
                logger.exception("Falha ao salvar budgets para pedido %s", pedido_obj.altforce_id)
                errors.append(f"orcamentos:{pedido_obj.altforce_id}:{e}")

            # PRODUTOS
            try:
                pr = upsert_pedido_produtos(pedido_obj, p)
                produtos_created_total += int(pr.get("created", 0) or 0)
                produtos_updated_total += int(pr.get("updated", 0) or 0)
                produtos_deleted_total += int(pr.get("deleted", 0) or 0)
                produtos_seen_total    += int(pr.get("seen", 0) or 0)
            except Exception as e:
                logger.exception("Falha ao salvar produtos para pedido %s", pedido_obj.altforce_id)
                errors.append(f"produtos:{pedido_obj.altforce_id}:{e}")

        except Exception as e:
            logger.exception("Falha ao processar pedido: %r", p)
            errors.append(str(e))

    total = len(pedidos)

    summary = {
        "count": total,                 # compat com o comando atual
        "total_received": total,        # alias mantido
        "created": created_count,
        "updated": updated_count,
        "tecnicon_created": tecnicon_created,
        "tecnicon_updated": tecnicon_updated,
        "orcamentos_created": orc_created_total,
        "orcamentos_deleted": orc_deleted_total,
        "produtos_created": produtos_created_total,
        "produtos_updated": produtos_updated_total,
        "produtos_deleted": produtos_deleted_total,
        "produtos_seen":    produtos_seen_total,
        "errors": errors,
    }
    logger.info("Sync AltForce concluído: %s", summary)
    return summary


# =========================
# AltForce: /leads (fApiLeads + dApiLeadsProdutos)
# =========================

def _build_leads_path(start_ms: int, end_ms: int) -> str:
    return f"/leads?start={start_ms}&end={end_ms}"

def _extract_leads_from_response(j: Any) -> List[Dict[str, Any]]:
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for key in ("items", "data", "leads", "content", "results"):
            v = j.get(key)
            if isinstance(v, list):
                return v
    logger.warning("Resposta de /leads não reconhecida como lista. Tipo: %s", type(j).__name__)
    return []

def fetch_leads(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if not start_dt or not end_dt:
        if days is None:
            days = 7
        end_dt = end_dt or timezone.now()
        start_dt = start_dt or (end_dt - timedelta(days=int(days)))

    if start_dt > end_dt:
        raise ValueError("start_dt não pode ser maior que end_dt")

    start_ms = _to_ms_utc(start_dt)
    end_ms = _to_ms_utc(end_dt)

    path = _build_leads_path(start_ms, end_ms)
    logger.info("Buscando AltForce %s", path)

    j = api_get(path)
    leads = _extract_leads_from_response(j)
    logger.info("AltForce retornou %d leads no intervalo", len(leads))
    return leads

def _coerce_lead_status(s: Any) -> Optional[str]:
    """
    Normaliza minimamente o status (trim). Mantemos valores do provedor.
    """
    if s in (None, ""):
        return None
    s = str(s).strip()
    return s or None

def _lead_cliente_id(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extrai lead/Cliente/id com alguma tolerância a variações simples.
    """
    return (
        _g(payload, "lead", "Cliente", "id")
        or _g(payload, "lead", "cliente", "id")
        or _g(payload, "lead", "Client", "id")
        or _g(payload, "Cliente", "id")
        or _g(payload, "client", "id")
        or _g(payload, "cliente", "id")
    )

def _lead_interest_level(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extrai 'lead/Nivel de interesse' com variações comuns.
    """
    return (
        _g(payload, "lead", "Nivel de interesse")
        or _g(payload, "lead", "Nível de interesse")
        or _g(payload, "lead", "nivel_de_interesse")
        or _g(payload, "lead", "interestLevel")
        or _g(payload, "Nivel de interesse")
        or _g(payload, "Nível de interesse")
    )

def upsert_lead(p: Dict[str, Any]) -> Tuple[ApiLead, bool]:
    """
    Converte payload do AltForce (/leads) e faz update_or_create em fApiLeads.
    """
    # id
    altforce_id = p.get("id") or p.get("uuid") or p.get("altforceId") or p.get("externalId")
    if not altforce_id:
        raise ValueError(f"Lead sem ID identificável: {p!r}")
    altforce_id = str(altforce_id)

    # date
    raw_date = p.get("date") or p.get("createdAt") or _g(p, "timestamps", "createdAt")
    date_dt = _parse_altforce_date(raw_date)

    # status
    status = _coerce_lead_status(p.get("status"))

    # user.* (sem fallback para 'id' interno)
    user = _g(p, "user", default={}) or {}
    user_name = user.get("name")
    user_external_id = _extract_user_external_id(p)

    # lead/Cliente/id & lead/Nivel de interesse
    cliente_id = _lead_cliente_id(p)
    interest_level = _lead_interest_level(p)

    obj, created = ApiLead.objects.update_or_create(
        altforce_id=altforce_id,
        defaults=dict(
            date=date_dt,
            status=status,
            user_name=user_name,
            user_external_id=user_external_id,
            cliente_id=str(cliente_id) if cliente_id is not None else None,
            interest_level=interest_level,
        ),
    )
    return obj, created

# ---------- categorias de produto de interesse do lead (dApiLeadsProdutos) ----------

def _lead_products_field_present(payload: Dict[str, Any]) -> bool:
    """
    Indica se o payload do /leads traz explicitamente o campo
    'Qual categoria de produto tem interesse' (ou variações).
    """
    lead = _g(payload, "lead") or {}
    if not isinstance(lead, dict):
        return False
    return any(k in lead for k in (
        "Qual categoria de produto tem interesse",
        "qual_categoria_de_produto_tem_interesse",
        "qualCategoriaDeProdutoTemInteresse",
        "productInterestCategories",
        "product_categories",
        "categorias",
        "categories",
    ))

def _iter_lead_product_interests(payload: Dict[str, Any]) -> list[dict]:
    """
    Retorna uma lista de dicts normalizados com as categorias de interesse.
    Cada item: {"product_id": str, "category_name": str}
    Aceita vários formatos: lista de dicts/strings, dict único, string única.
    """
    lead = _g(payload, "lead") or {}
    raw = (
        _g(lead, "Qual categoria de produto tem interesse")
        or _g(lead, "qual_categoria_de_produto_tem_interesse")
        or _g(lead, "qualCategoriaDeProdutoTemInteresse")
        or _g(lead, "productInterestCategories")
        or _g(lead, "product_categories")
        or _g(lead, "categorias")
        or _g(lead, "categories")
        or None
    )

    if raw is None:
        return []

    # normaliza para lista
    if isinstance(raw, (str, dict)):
        raw_list = [raw]
    elif isinstance(raw, list):
        raw_list = raw
    else:
        return []

    out: list[dict] = []
    for item in raw_list:
        pid = None
        name = None

        if isinstance(item, dict):
            pid = item.get("id") or item.get("uuid") or item.get("externalId")
            # tenta pegar o rótulo por diversas chaves comuns
            name = (
                item.get("name") or item.get("label") or item.get("categoria")
                or item.get("value") or item.get("title")
            )
        elif isinstance(item, str):
            name = item.strip()

        # se não temos pelo menos um nome, ignora
        if not name:
            continue

        # se não veio id, gera um id estável baseado no nome normalizado
        if pid is None:
            pid = f"name:{_norm_text(name)}"

        out.append({
            "product_id": str(pid),
            "category_name": str(name).strip(),
        })

    return out

def upsert_lead_produtos(lead_obj: ApiLead, payload: Dict[str, Any]) -> dict:
    """
    Sincroniza dApiLeadsProdutos para um lead.

    Regras:
    - Se o payload NÃO trouxer explicitamente o campo de categorias, não altera nada.
    - Se trouxer, criamos/atualizamos os itens vistos e removemos os que não vieram.
    """
    if not _lead_products_field_present(payload):
        return {"created": 0, "updated": 0, "deleted": 0, "seen": 0}

    normalized = _iter_lead_product_interests(payload)
    if not normalized:
        # campo veio mas vazio -> apaga tudo
        deleted_n, _ = ApiLeadProduto.objects.filter(lead=lead_obj).delete()
        return {"created": 0, "updated": 0, "deleted": deleted_n, "seen": 0}

    desired_ids = {r["product_id"] for r in normalized}
    existing_qs = ApiLeadProduto.objects.filter(lead=lead_obj)
    existing_ids = set(existing_qs.values_list("product_id", flat=True))

    to_create = desired_ids - existing_ids
    to_update = desired_ids & existing_ids
    to_delete = existing_ids - desired_ids

    created_n = 0
    updated_n = 0
    deleted_n = 0

    # CREATE em lote
    if to_create:
        data_by_id = {r["product_id"]: r for r in normalized}
        objs = []
        for pid in to_create:
            r = data_by_id[pid]
            objs.append(ApiLeadProduto(
                lead=lead_obj,
                altforce_id=lead_obj.altforce_id,
                product_id=r["product_id"],
                category_name=r["category_name"],
            ))
        ApiLeadProduto.objects.bulk_create(objs, ignore_conflicts=True)
        created_n = len(objs)

    # UPDATE (atualiza rótulo caso tenha mudado)
    if to_update:
        data_by_id = {r["product_id"]: r for r in normalized}
        for pid in to_update:
            r = data_by_id.get(pid) or {}
            ApiLeadProduto.objects.filter(lead=lead_obj, product_id=pid).update(
                category_name=r.get("category_name"),
            )
        updated_n = len(to_update)

    # DELETE dos que saíram
    if to_delete:
        deleted_n, _ = ApiLeadProduto.objects.filter(
            lead=lead_obj, product_id__in=list(to_delete)
        ).delete()

    return {"created": created_n, "updated": updated_n, "deleted": deleted_n, "seen": len(normalized)}


def sync_leads(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Busca /leads e faz upsert em fApiLeads + dApiLeadsProdutos.
    """
    leads = fetch_leads(start_dt=start_dt, end_dt=end_dt, days=days)

    created_count = 0
    updated_count = 0

    prod_created_total = 0
    prod_updated_total = 0
    prod_deleted_total = 0
    prod_seen_total    = 0

    errors: List[str] = []

    for p in leads:
        try:
            lead_obj, created = upsert_lead(p)
            if created:
                created_count += 1
            else:
                updated_count += 1

            # Produtos de interesse (categorias)
            try:
                pr = upsert_lead_produtos(lead_obj, p)
                prod_created_total += int(pr.get("created", 0) or 0)
                prod_updated_total += int(pr.get("updated", 0) or 0)
                prod_deleted_total += int(pr.get("deleted", 0) or 0)
                prod_seen_total    += int(pr.get("seen", 0) or 0)
            except Exception as e:
                logger.exception("Falha ao salvar produtos de interesse para lead %s", lead_obj.altforce_id)
                errors.append(f"lead_produtos:{lead_obj.altforce_id}:{e}")

        except Exception as e:
            logger.exception("Falha ao processar lead: %r", p)
            errors.append(str(e))

    total = len(leads)
    summary = {
        "count": total,
        "created": created_count,
        "updated": updated_count,
        # métricas de dApiLeadsProdutos
        "lead_produtos_created": prod_created_total,
        "lead_produtos_updated": prod_updated_total,
        "lead_produtos_deleted": prod_deleted_total,
        "lead_produtos_seen":    prod_seen_total,
        "errors": errors,
    }
    logger.info("Sync AltForce (leads) concluído: %s", summary)
    return summary


# =========================
# AltForce: /customers (fApiClientes — full load)
# =========================

def _extract_customers_from_response(j: Any) -> List[Dict[str, Any]]:
    """
    Tenta localizar a lista de customers no JSON em formatos comuns.
    """
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for key in ("items", "data", "customers", "content", "results"):
            v = j.get(key)
            if isinstance(v, list):
                return v
    logger.warning("Resposta de /customers não reconhecida como lista. Tipo: %s", type(j).__name__)
    return []

def fetch_customers() -> List[Dict[str, Any]]:
    """
    Carregamento completo do endpoint /customers (sem janelas).
    """
    path = "/customers"
    logger.info("Buscando AltForce %s", path)
    j = api_get(path)
    customers = _extract_customers_from_response(j)
    logger.info("AltForce retornou %d customers", len(customers))
    return customers

def upsert_cliente(p: Dict[str, Any]) -> Tuple[ApiCliente, bool]:
    """
    Converte o payload do /customers e faz update_or_create em fApiClientes.
    Campos: id, name, email, phone, adress.{city/state/country}.name
    """
    altforce_id = p.get("id") or p.get("uuid") or p.get("altforceId") or p.get("externalId")
    if not altforce_id:
        raise ValueError(f"Cliente sem ID identificável: {p!r}")
    altforce_id = str(altforce_id)

    name  = p.get("name")
    email = p.get("email")
    phone = p.get("phone")

    # compat: alguns payloads trazem "address", outros "adress"
    address = _addr(p)

    city_name    = _g(address, "city", "name")
    state_name   = _g(address, "state", "name")
    country_name = _g(address, "country", "name")

    obj, created = ApiCliente.objects.update_or_create(
        altforce_id=altforce_id,
        defaults=dict(
            name=name,
            email=email,
            phone=phone,
            city_name=city_name,
            state_name=state_name,
            country_name=country_name,
        ),
    )
    return obj, created

def sync_customers() -> Dict[str, Any]:
    """
    Busca todos os /customers e sincroniza fApiClientes.
    """
    customers = fetch_customers()

    created_count = 0
    updated_count = 0
    errors: List[str] = []

    for c in customers:
        try:
            _, created = upsert_cliente(c)
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception as e:
            logger.exception("Falha ao processar cliente: %r", c)
            errors.append(str(e))

    total = len(customers)
    summary = {
        "count": total,
        "created": created_count,
        "updated": updated_count,
        "errors": errors,
    }
    logger.info("Sync AltForce (customers) concluído: %s", summary)
    return summary
