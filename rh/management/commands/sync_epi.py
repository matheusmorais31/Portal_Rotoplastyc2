from django.core.management.base import BaseCommand
from datetime import datetime
from rh import api
from rh.models import EntregaEPI


def iso(val: str | None):
    return datetime.fromisoformat(val).date() if val else None


def s(v):
    """None → ''"""
    return v or ""


class Command(BaseCommand):
    help = "Importa entregas de EPI com nome do colaborador e descrição do EPI."

    def handle(self, *args, **kwargs):
        entregas = api.list_entregas_epi()

        # --- dicionários auxiliares ---------------------------------------
        contratos = sorted({e["contrato"] for e in entregas})
        nomes     = api.contratos_por_numero(contratos)

        codigos   = sorted({
            e.get("codigoEstoque") for e in entregas if e.get("codigoEstoque")
        })
        descr_epi = api.descricoes_epi(codigos)

        # --- gravação ------------------------------------------------------
        novos = 0
        for row in entregas:
            data_ent = iso(row["dataEntrega"])
            EntregaEPI.objects.update_or_create(
                unidade=row["unidade"],
                contrato=row["contrato"],
                epi=row["epi"],
                lote=s(row.get("lote")),
                data_entrega=data_ent,
                defaults={
                    "data_devolucao":      iso(row.get("dataDevolucao")),
                    "codigo_estoque":      s(row.get("codigoEstoque")),
                    "quantidade_entregue": row.get("quantidadeEntregue") or 0,
                    "colaborador":         nomes.get(row["contrato"], ""),
                    "descricao_epi":       descr_epi.get(row.get("codigoEstoque", ""), ""),
                },
            )
            novos += 1

        self.stdout.write(self.style.SUCCESS(f"{novos} registros processados."))
