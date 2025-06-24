# rh/tasks.py

from celery import shared_task
from . import api
from .models import EntregaEPI
from datetime import datetime

@shared_task
def sync_entregas_epi():
    delivery_data = api.list_entregas_epi() # Esta função deve retornar o campo "descricaoEPI"
    contrato_numbers = list(set(row["contrato"] for row in delivery_data))
    colaborador_info = api.contratos_por_numero(contrato_numbers)

    for row in delivery_data:
        data_entrega = datetime.fromisoformat(row["dataEntrega"]).date()
        contract_num = row["contrato"]

        collaborator_details = colaborador_info.get(contract_num, {
            "nome": "",
            "centroCusto2": "",
            "descricaoCentroCusto2": ""
        })

        colaborador_name = collaborator_details.get("nome", "")
        centro_custo_value = collaborator_details.get("centroCusto2", "")
        descricao_centro_custo_value = collaborator_details.get("descricaoCentroCusto2", "")
        
        # --- NOVIDADE AQUI: Pegando a descricaoEPI do 'row' da API ---
        descricao_epi_value = row.get("descricaoEPI", "") # <--- Pegue a descrição do EPI da resposta da API

        EntregaEPI.objects.update_or_create(
            unidade=row["unidade"],
            contrato=row["contrato"],
            epi=row["epi"],
            lote=row.get("lote", ""),
            data_entrega=data_entrega,
            defaults={
                "quantidade_entregue": row["quantidadeEntregue"],
                "codigo_estoque": row.get("codigoEstoque", ""),
                "colaborador": colaborador_name,
                "centro_custo": centro_custo_value,
                "descricao_centro_custo": descricao_centro_custo_value,
                "descricao_epi": descricao_epi_value, # <--- SALVANDO A NOVA DESCRIÇÃO DO EPI
            },
        )
    print(f"Sincronização de entregas EPI concluída. Total de {len(delivery_data)} registros processados.")