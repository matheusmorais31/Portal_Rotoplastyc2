from django.contrib import admin
from rh.models import EntregaEPI


@admin.register(EntregaEPI)
class EntregaEPIAdmin(admin.ModelAdmin):
    date_hierarchy = "data_entrega"

    list_display = (
        "data_entrega", "contrato", "colaborador",
        "epi", "descricao_epi", "quantidade_entregue",
    )

    search_fields = (
        "contrato", "colaborador",
        "epi", "descricao_epi", "lote", "codigo_estoque",
    )

    list_filter = (            # ← removido 'estoque'
        "unidade",
        "epi",
    )
