# altforce_sync/management/commands/sync_altforce_customers.py
from __future__ import annotations

from django.core.management.base import BaseCommand

from altforce_sync.conf import config
from altforce_sync.services import sync_customers


class Command(BaseCommand):
    help = "Sincroniza clientes (/customers) do AltForce para fApiClientes (full load)."

    def handle(self, *args, **opts):
        if not (config.company_id and config.api_key):
            self.stderr.write(self.style.ERROR("Configure ALT_FORCE_COMPANY_ID e ALT_FORCE_API_KEY no .env."))
            return

        try:
            res = sync_customers()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Falha ao sincronizar customers: {exc}"))
            raise

        msg = (
            f"OK: {res.get('count', 0)} clientes — "
            f"{res.get('created', 0)} criados, {res.get('updated', 0)} atualizados."
        )
        self.stdout.write(self.style.SUCCESS(msg))

        errors = res.get("errors") or []
        if errors:
            self.stderr.write(self.style.WARNING(f"Erros: {len(errors)}"))
            for e in errors[:10]:
                self.stderr.write(f" - {e}")
            if len(errors) > 10:
                self.stderr.write(" ... (demais erros omitidos)")
