# altforce_sync/management/commands/sync_altforce_leads.py
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from altforce_sync.conf import config
from altforce_sync.services import sync_leads


def _parse_ymd(s: str) -> datetime:
    """
    Aceita:
      - 'YYYY-MM-DD'
      - 'YYYY-MM-DDTHH:MM'
      - 'YYYY-MM-DDTHH:MM:SS'
    Retorna datetime coerente com a config do projeto:
      - se USE_TZ=True -> aware na tz padrão
      - se USE_TZ=False -> naive
    """
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s + "T00:00:00")

    if settings.USE_TZ and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_default_timezone())
    return dt


def _fmt_dt_safe(dt: datetime) -> str:
    """
    Se aware -> aplica localtime pra exibir na tz local.
    Se naive -> retorna direto.
    """
    if dt is None:
        return "-"
    if timezone.is_aware(dt):
        return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M:%S%z")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class Command(BaseCommand):
    help = "Sincroniza leads (/leads) do AltForce para fApiLeads e dApiLeadsProdutos."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=str, help="YYYY-MM-DD[THH:MM[:SS]]")
        parser.add_argument("--end",   type=str, help="YYYY-MM-DD[THH:MM[:SS]]")
        parser.add_argument("--days",  type=int, help="Atalho: últimos N dias (ignora --start/--end)")

    def handle(self, *args, **opts):
        if not (config.company_id and config.api_key):
            self.stderr.write(self.style.ERROR("Configure ALT_FORCE_COMPANY_ID e ALT_FORCE_API_KEY no .env."))
            return

        start_dt = None
        end_dt = None
        days = opts.get("days")

        if days:
            end_dt = timezone.now()
            start_dt = end_dt - timedelta(days=int(days))
            if settings.USE_TZ:
                tz = timezone.get_default_timezone()
                if timezone.is_naive(start_dt):
                    start_dt = timezone.make_aware(start_dt, tz)
                if timezone.is_naive(end_dt):
                    end_dt = timezone.make_aware(end_dt, tz)
        else:
            if opts.get("start"):
                start_dt = _parse_ymd(opts["start"])
            if opts.get("end"):
                end_dt = _parse_ymd(opts["end"])

        if start_dt and end_dt:
            self.stdout.write(f"Janela: {_fmt_dt_safe(start_dt)} -> {_fmt_dt_safe(end_dt)}")
        elif days:
            self.stdout.write(f"Janela: últimos {days} dias até agora.")
        else:
            self.stdout.write("Sem parâmetros: usará a janela padrão (últimos 7 dias).")

        try:
            res = sync_leads(start_dt=start_dt, end_dt=end_dt, days=None)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Falha ao sincronizar leads: {exc}"))
            raise

        msg = (
            f"OK: {res.get('count', 0)} leads — "
            f"{res.get('created', 0)} criados, {res.get('updated', 0)} atualizados. "
            f"PRODUTOS: {res.get('lead_produtos_created', 0)} criados, "
            f"{res.get('lead_produtos_updated', 0)} atualizados, "
            f"{res.get('lead_produtos_deleted', 0)} removidos "
            f"(vistos={res.get('lead_produtos_seen', 0)})."
        )
        self.stdout.write(self.style.SUCCESS(msg))

        errors = res.get("errors") or []
        if errors:
            self.stderr.write(self.style.WARNING(f"Erros: {len(errors)}"))
            for e in errors[:10]:
                self.stderr.write(f" - {e}")
            if len(errors) > 10:
                self.stderr.write(" ... (demais erros omitidos)")
