# altforce_sync/management/commands/backfill_altforce_orders.py
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from django.core.management.base import BaseCommand

# usa o serviço que você já tem
from altforce_sync.services import sync_orders


MICRO = timedelta(microseconds=1)


def _parse_any_dt(s: str) -> datetime:
    """
    Aceita:
      - ISO:    2025-10-07, 2025-10-07 12:34, 2025-10-07T12:34, 2025-10-07T12:34:56
      - BR:     07/10/2025, 07/10/2025 12:34
    Retorna datetime **naive**.
    """
    s = s.strip()
    tried = []
    # Tenta fromisoformat primeiro
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception as e:
        tried.append(f"fromisoformat:{e}")

    # Tenta formatos comuns
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except Exception as e:
            tried.append(f"{fmt}:{e}")

    raise ValueError(f"Não foi possível interpretar a data '{s}'. Tentativas: {tried}")


def _fmt_dt(dt: datetime) -> str:
    # apenas para logs bonitinhos, mantendo microssegundos como nos seus prints
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


class Command(BaseCommand):
    help = (
        "Faz backfill de pedidos AltForce em janelas (padrão 30 dias) "
        "até alcançar a data final. Garante progresso entre janelas para não entrar em loop."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_dt",
            type=str,
            default=None,
            help="Data inicial (ex: 2023-10-01, 2023-10-01T00:00, 01/10/2023). "
                 "Padrão: hoje-730 dias, 00:00:00.",
        )
        parser.add_argument(
            "--to",
            "--until",
            dest="to_dt",
            type=str,
            default=None,
            help="Data final (ex: 2025-10-07, 2025-10-07T23:59). Padrão: agora.",
        )
        parser.add_argument(
            "--window-days",
            "--janela-dias",
            dest="window_days",
            type=int,
            default=30,
            help="Tamanho da janela em dias (padrão: 30).",
        )
        parser.add_argument(
            "--overlap-minutes",
            dest="overlap_minutes",
            type=int,
            default=0,
            help="Sobreposição (minutos) entre janelas. Padrão: 0. "
                 "Se quiser reforçar deduplicação, pode usar 1.",
        )
        parser.add_argument(
            "--sleep-seconds",
            dest="sleep_seconds",
            type=float,
            default=0.0,
            help="Espera entre janelas (segundos) para aliviar rate limits. Padrão: 0.",
        )
        parser.add_argument(
            "--max-windows",
            dest="max_windows",
            type=int,
            default=2000,
            help="Limite de janelas para evitar loops acidentais. Padrão: 2000.",
        )

    def handle(self, *args, **opts):
        # --- resolve datas (sempre NAIVE) ---
        now = datetime.now()

        to_dt: datetime
        if opts.get("to_dt"):
            to_dt = _parse_any_dt(opts["to_dt"])
        else:
            to_dt = now  # já NAIVE

        # normaliza: to_dt inclusive (deixamos como está; no cálculo da janela aplicamos -1 microsegundo)
        from_dt: datetime
        if opts.get("from_dt"):
            from_dt = _parse_any_dt(opts["from_dt"])
        else:
            # 2 anos atrás, início do dia
            two_years = timedelta(days=730)
            base = (to_dt - two_years)
            from_dt = datetime(year=base.year, month=base.month, day=base.day)  # 00:00:00

        window_days: int = int(opts["window_days"])
        overlap_minutes: int = int(opts["overlap_minutes"])
        sleep_seconds: float = float(opts["sleep_seconds"])
        max_windows: int = int(opts["max_windows"])

        if window_days <= 0:
            raise ValueError("--window-days deve ser > 0")
        if overlap_minutes < 0:
            raise ValueError("--overlap-minutes não pode ser negativo")
        if max_windows <= 0:
            raise ValueError("--max-windows deve ser > 0")

        # --- laço principal ---
        current_start: datetime = from_dt
        previous_span: Optional[tuple[datetime, datetime]] = None

        i = 0
        while True:
            i += 1
            if i > max_windows:
                self.stderr.write(self.style.WARNING(
                    f"Atingiu --max-windows={max_windows}. Encerrando para evitar loop."
                ))
                break

            # Se já passamos do limite, fim.
            if current_start > to_dt:
                break

            # Calcula fim da janela: start + N dias - 1 microseg, limitado a to_dt
            candidate_end = current_start + timedelta(days=window_days) - MICRO
            current_end = candidate_end if candidate_end <= to_dt else to_dt

            # Guarda e loga a janela
            span = (current_start, current_end)

            # Se por algum motivo repetimos exatamente a mesma janela, encerra (failsafe).
            if previous_span is not None and span == previous_span:
                self.stderr.write(self.style.WARNING(
                    "Detectada repetição de janela idêntica. Encerrando para evitar loop."
                ))
                break
            previous_span = span

            self.stdout.write(self.style.NOTICE(
                f"[{i}] Janela: {_fmt_dt(current_start)}  ->  {_fmt_dt(current_end)}"
            ))

            # --- chama o serviço ---
            try:
                summary = sync_orders(start_dt=current_start, end_dt=current_end)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # não deixa a execução morrer; reporta e segue
                self.stderr.write(self.style.ERROR(f"   ✗ ERRO ao sincronizar: {e}"))
                summary = {}

            # Normaliza métricas
            received = int(summary.get("count", 0) or 0)
            created = int(summary.get("created", 0) or 0)
            updated = int(summary.get("updated", 0) or 0)
            errors = int(summary.get("errors", 0) or summary.get("error_count", 0) or 0)

            self.stdout.write(self.style.SUCCESS(
                f"   ✓ OK — recebidos={received}, criados={created}, "
                f"atualizados={updated}, erros={errors}"
            ))

            # Se já atingimos a última janela, encerra.
            if current_end >= to_dt:
                break

            # Pausa opcional
            if sleep_seconds > 0:
                try:
                    time.sleep(sleep_seconds)
                except KeyboardInterrupt:
                    # respeita Ctrl+C no sleep
                    self.stderr.write(self.style.WARNING("Interrompido durante o sleep."))
                    break

            # --- calcula próxima janela (com guardas contra loop) ---
            # Avança 1 µs além do fim atual para garantir progresso
            next_start = current_end + MICRO

            # Aplica sobreposição (se houver), mas NUNCA permitindo voltar ou ficar igual
            if overlap_minutes > 0:
                next_start_with_overlap = next_start - timedelta(minutes=overlap_minutes)
                if next_start_with_overlap > current_start:
                    next_start = next_start_with_overlap
                # se não for estritamente maior, mantém o next_start sem overlap

            # Failsafe adicional: garante progresso
            if next_start <= current_start:
                next_start = current_end + MICRO

            current_start = next_start

        # Fim
        self.stdout.write(self.style.SUCCESS("Backfill finalizado."))
