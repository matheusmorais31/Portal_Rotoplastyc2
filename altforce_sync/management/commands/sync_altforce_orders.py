# altforce_sync/management/commands/sync_altforce_orders.py
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from altforce_sync.conf import config
from altforce_sync.services import sync_orders


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

    if settings.USE_TZ:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_default_timezone())
    # Caso USE_TZ=False, mantemos naive
    return dt


def _fmt_dt_safe(dt: datetime) -> str:
    """
    Se aware -> aplica localtime pra exibir na tz local.
    Se naive -> retorna direto (sem localtime).
    """
    if dt is None:
        return "-"
    if timezone.is_aware(dt):
        return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M:%S%z")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class Command(BaseCommand):
    help = (
        "Sincroniza pedidos (/orders) do AltForce para fApiPedidos e dimensões relacionadas "
        "(dApiPedidosTecnicon, dApiPedidosOrcamento, dApiPedidosProdutos)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=str,
            help="Data inicial (YYYY-MM-DD ou YYYY-MM-DDTHH:MM[:SS])",
        )
        parser.add_argument(
            "--end",
            type=str,
            help="Data final (YYYY-MM-DD ou YYYY-MM-DDTHH:MM[:SS])",
        )
        parser.add_argument(
            "--days",
            type=int,
            help="Atalho: últimos N dias até agora (ignora --start/--end)",
        )

    def handle(self, *args, **options):
        if not (config.company_id and config.api_key):
            self.stderr.write(
                self.style.ERROR(
                    "Configure ALT_FORCE_COMPANY_ID e ALT_FORCE_API_KEY no .env."
                )
            )
            return

        start_dt = None
        end_dt = None
        days = options.get("days")

        if days:
            # timezone.now(): aware se USE_TZ=True, naive se USE_TZ=False
            end_dt = timezone.now()
            start_dt = end_dt - timedelta(days=int(days))

            # Se USE_TZ=True, garanta aware
            if settings.USE_TZ:
                tz = timezone.get_default_timezone()
                if timezone.is_naive(start_dt):
                    start_dt = timezone.make_aware(start_dt, tz)
                if timezone.is_naive(end_dt):
                    end_dt = timezone.make_aware(end_dt, tz)
        else:
            if options.get("start"):
                start_dt = _parse_ymd(options["start"])
            if options.get("end"):
                end_dt = _parse_ymd(options["end"])

        # Log amigável da janela (sem quebrar com naive)
        if start_dt and end_dt:
            self.stdout.write(
                f"Janela: {_fmt_dt_safe(start_dt)} -> {_fmt_dt_safe(end_dt)}"
            )
        elif days:
            self.stdout.write(f"Janela: últimos {days} dias até agora.")
        else:
            self.stdout.write(
                "Sem parâmetros: usará a janela padrão do serviço (últimos 7 dias)."
            )

        # Chama o serviço
        try:
            # Passamos start/end; se algum deles estiver None, o services completa a janela.
            res = sync_orders(start_dt=start_dt, end_dt=end_dt, days=None)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Falha ao sincronizar: {exc}"))
            raise

        # Monta mensagem de sucesso
        count = res.get("count", 0)
        created = res.get("created", 0)
        updated = res.get("updated", 0)
        msg = (
            f"OK: {count} pedidos processados — {created} criados, {updated} atualizados."
        )

        # TECNICON
        if "tecnicon_created" in res or "tecnicon_updated" in res:
            msg += (
                f" TECNICON: {res.get('tecnicon_created', 0)} criados, "
                f"{res.get('tecnicon_updated', 0)} atualizados."
            )

        # ORÇAMENTOS (usar chaves do services: orcamentos_created / orcamentos_deleted)
        if "orcamentos_created" in res or "orcamentos_deleted" in res:
            msg += (
                f" ORÇAMENTOS: {res.get('orcamentos_created', 0)} criados, "
                f"{res.get('orcamentos_deleted', 0)} removidos."
            )

        # PRODUTOS (usar chaves do services: produtos_created / produtos_updated / produtos_deleted)
        if (
            "produtos_created" in res
            or "produtos_updated" in res
            or "produtos_deleted" in res
        ):
            msg += (
                f" PRODUTOS: {res.get('produtos_created', 0)} criados, "
                f"{res.get('produtos_updated', 0)} atualizados, "
                f"{res.get('produtos_deleted', 0)} removidos."
            )

        self.stdout.write(self.style.SUCCESS(msg))

        # Lista erros (se houver)
        errors = res.get("errors") or []
        if errors:
            self.stderr.write(self.style.WARNING(f"Erros: {len(errors)}"))
            for e in errors[:10]:
                self.stderr.write(f" - {e}")
            if len(errors) > 10:
                self.stderr.write(" ... (demais erros omitidos)")
