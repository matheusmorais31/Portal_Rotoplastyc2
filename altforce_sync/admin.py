# altforce_sync/admin.py
from django.contrib import admin, messages
from .models import ApiPedido
from .tasks import backfill_altforce_all_2y_task, sync_altforce_all_30d_task

@admin.register(ApiPedido)
class ApiPedidoAdmin(admin.ModelAdmin):
    list_display = ("altforce_id", "status", "date", "buyer_name", "total_price", "sub_total_price", "updated_at")
    search_fields = ("altforce_id", "buyer_name", "payment_method_name", "price_list_name")
    list_filter = ("status", "date", "updated_at")

    actions = ["action_sync_30d_all", "action_backfill_2y_all"]

    @admin.action(description="🟢 Sincronizar últimos 30 dias (todos os endpoints)")
    def action_sync_30d_all(self, request, queryset):
        async_result = sync_altforce_all_30d_task.delay()
        messages.info(request, f"Tarefa enfileirada: sync_altforce_all_30d_task (task_id={async_result.id}).")

    @admin.action(description="🧹 Backfill 2 anos (todos os endpoints)")
    def action_backfill_2y_all(self, request, queryset):
        # padrão: budgets com refetch=True e SEM sobrescrever opcionais vazios
        async_result = backfill_altforce_all_2y_task.delay(
            window_days=30,
            refetch_optionals_detail=True,
            overwrite_empty_optionals=False,
        )
        messages.info(request, f"Tarefa enfileirada: backfill_altforce_all_2y_task (task_id={async_result.id}).")
