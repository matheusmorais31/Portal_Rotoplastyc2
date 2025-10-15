from celery import shared_task
from . import api
from .models import EntregaEPI
from datetime import datetime
from collections import defaultdict, Counter
import logging

logger = logging.getLogger(__name__)

def _iso_to_date(val):
    try:
        return datetime.fromisoformat(val).date() if val else None
    except Exception:
        return None

def _s(v):
    return v or ""

@shared_task
def sync_entregas_epi():
    entregas = api.list_entregas_epi()
    if not entregas:
        logger.info("sync_entregas_epi: nada retornado da API.")
        return

    # ---- mapa de contratos (com backoff já no api.contratos_por_numero) ---
    contratos = sorted({e.get("contrato") for e in entregas if e.get("contrato") is not None})
    info_contratos = api.contratos_por_numero(contratos)

    # ---- construção do "catálogo" local de descrições por código ----------
    votos = defaultdict(Counter)  # {codigo: Counter({descricao: contagem})}
    for e in entregas:
        cod = _s(e.get("codigoEstoque"))
        desc = _s(e.get("descricaoEPI"))
        if cod and desc:
            votos[cod][desc] += 1

    def best_desc(cod: str) -> str:
        c = votos.get(cod)
        return c.most_common(1)[0][0] if c else ""

    # ---- contadores de qualidade ------------------------------------------
    q_blank = {"colaborador":0, "centro_custo":0, "descricao_cc":0, "descricao_epi":0, "codigo_estoque":0}
    total = 0

    # ---- upsert ------------------------------------------------------------
    for row in entregas:
        total += 1
        data_entrega = _iso_to_date(row.get("dataEntrega"))
        data_devol   = _iso_to_date(row.get("dataDevolucao"))

        contrato = row.get("contrato")
        info = info_contratos.get(contrato) or {}
        colaborador_name   = _s(info.get("nome"))
        centro_custo_val   = _s(info.get("centroCusto2"))
        desc_cc_val        = _s(info.get("descricaoCentroCusto2"))

        codigo_estoque     = _s(row.get("codigoEstoque"))
        descricao_epi      = _s(row.get("descricaoEPI")) or best_desc(codigo_estoque)

        if not colaborador_name: q_blank["colaborador"] += 1
        if not centro_custo_val: q_blank["centro_custo"] += 1
        if not desc_cc_val:      q_blank["descricao_cc"] += 1
        if not descricao_epi:    q_blank["descricao_epi"] += 1
        if not codigo_estoque:   q_blank["codigo_estoque"] += 1

        EntregaEPI.objects.update_or_create(
            unidade=_s(row.get("unidade")),
            contrato=contrato,
            epi=_s(row.get("epi")),
            lote=_s(row.get("lote")),
            data_entrega=data_entrega,
            defaults={
                "data_devolucao":      data_devol,
                "codigo_estoque":      codigo_estoque,
                "quantidade_entregue": row.get("quantidadeEntregue") or 0,
                "colaborador":         colaborador_name,
                "centro_custo":        centro_custo_val,
                "descricao_centro_custo": desc_cc_val,
                "descricao_epi":       descricao_epi,
            },
        )

    logger.info(
        "sync_entregas_epi: %s registros processados. Blanks => colaborador=%s, cc=%s, desc_cc=%s, desc_epi=%s, cod_estoque=%s",
        total, q_blank["colaborador"], q_blank["centro_custo"], q_blank["descricao_cc"],
        q_blank["descricao_epi"], q_blank["codigo_estoque"]
    )
