from django.core.management.base import BaseCommand
from datetime import datetime
from collections import defaultdict, Counter
from rh import api
from rh.models import EntregaEPI
import logging

logger = logging.getLogger(__name__)

def iso(val: str | None):
    try:
        return datetime.fromisoformat(val).date() if val else None
    except Exception:
        return None

def s(v):
    return v or ""

class Command(BaseCommand):
    help = "Importa entregas de EPI com nome do colaborador, CC e descrição do EPI (sem depender do endpoint de lookup)."

    def handle(self, *args, **kwargs):
        entregas = api.list_entregas_epi()
        if not entregas:
            self.stdout.write(self.style.WARNING("Nenhuma entrega retornada."))
            return

        contratos = sorted({e.get("contrato") for e in entregas if e.get("contrato") is not None})
        info_contratos = api.contratos_por_numero(contratos)

        # catálogo local de descrições por maioria
        votos = defaultdict(Counter)
        for e in entregas:
            cod = s(e.get("codigoEstoque"))
            desc = s(e.get("descricaoEPI"))
            if cod and desc:
                votos[cod][desc] += 1

        def best_desc(cod: str) -> str:
            c = votos.get(cod)
            return c.most_common(1)[0][0] if c else ""

        novos = 0
        blanks = {"colaborador":0, "cc":0, "desc_cc":0, "desc_epi":0, "cod":0}

        for row in entregas:
            data_ent = iso(row.get("dataEntrega"))
            data_dev = iso(row.get("dataDevolucao"))
            contrato = row.get("contrato")

            info = info_contratos.get(contrato) or {}
            nome_col = s(info.get("nome"))
            cc2      = s(info.get("centroCusto2"))
            dcc2     = s(info.get("descricaoCentroCusto2"))

            cod = s(row.get("codigoEstoque"))
            desc = s(row.get("descricaoEPI")) or best_desc(cod)

            if not nome_col: blanks["colaborador"] += 1
            if not cc2:      blanks["cc"] += 1
            if not dcc2:     blanks["desc_cc"] += 1
            if not desc:     blanks["desc_epi"] += 1
            if not cod:      blanks["cod"] += 1

            EntregaEPI.objects.update_or_create(
                unidade=s(row.get("unidade")),
                contrato=contrato,
                epi=s(row.get("epi")),
                lote=s(row.get("lote")),
                data_entrega=data_ent,
                defaults={
                    "data_devolucao":      data_dev,
                    "codigo_estoque":      cod,
                    "quantidade_entregue": row.get("quantidadeEntregue") or 0,
                    "colaborador":         nome_col,
                    "centro_custo":        cc2,
                    "descricao_centro_custo": dcc2,
                    "descricao_epi":       desc,
                },
            )
            novos += 1

        logger.info("sync_epi: %s registros processados.", novos)
        logger.info(
            "sync_epi blanks => colaborador=%s, cc=%s, desc_cc=%s, desc_epi=%s, cod=%s",
            blanks["colaborador"], blanks["cc"], blanks["desc_cc"], blanks["desc_epi"], blanks["cod"]
        )
        self.stdout.write(self.style.SUCCESS(f"{novos} registros processados."))
