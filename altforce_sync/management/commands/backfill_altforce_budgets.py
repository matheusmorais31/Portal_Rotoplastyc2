# altforce_sync/management/commands/backfill_altforce_budgets.py
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from django.core.management.base import BaseCommand

from altforce_sync.services import sync_budgets

MICRO = timedelta(microseconds=1)


def _parse_any_dt(s: str) -> datetime:
    s = s.strip()
    tried = []
    try:
        # aceita ISO com/sem 'Z'
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception as e:
        tried.append(f"fromisoformat:{e}")
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
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


class Command(BaseCommand):
    help = (
        "Backfill de /budgets em janelas (padrão 30 dias) com guardas contra loop. "
        "Por padrão força limpeza de opcionais vazios para garantir atualização completa."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_dt",
            type=str,
            default=None,
            help="Data inicial (ex: 2023-10-01, 01/10/2023). Padrão: hoje-730 dias 00:00.",
        )
        parser.add_argument(
            "--to",
            "--until",
            dest="to_dt",
            type=str,
            default=None,
            help="Data final (ex: 2025-10-07 23:59). Padrão: agora.",
        )
        parser.add_argument(
            "--window-days",
            "--janela-dias",
            dest="window_days",
            type=int,
            default=30,
            help="Tamanho da janela em dias (padrão 30).",
        )
        parser.add_argument(
            "--overlap-minutes",
            dest="overlap_minutes",
            type=int,
            default=0,
            help="Sobreposição entre janelas (minutos).",
        )
        parser.add_argument(
            "--sleep-seconds",
            dest="sleep_seconds",
            type=float,
            default=0.0,
            help="Pausa entre janelas.",
        )
        parser.add_argument(
            "--max-windows",
            dest="max_windows",
            type=int,
            default=2000,
            help="Limite de janelas (failsafe).",
        )
        # controla o refetch do detalhe dos opcionais (ver services.sync_budgets)
        parser.add_argument(
            "--refetch-optionals-detail",
            dest="refetch_optionals_detail",
            action="store_true",
            help="Quando presente, tenta refetch do detalhe para preencher opcionais vazios/ausentes.",
        )
        parser.add_argument(
            "--no-refetch-optionals-detail",
            dest="refetch_optionals_detail",
            action="store_false",
            help="Desativa o refetch do detalhe (padrão).",
        )
        # força limpar opcionais vazios durante o backfill (garante atualização)
        parser.add_argument(
            "--overwrite-empty-optionals",
            dest="overwrite_empty_optionals",
            action="store_true",
            help="Força gravar [] quando opcionais vierem vazios (padrão: ligado).",
        )
        parser.add_argument(
            "--no-overwrite-empty-optionals",
            dest="overwrite_empty_optionals",
            action="store_false",
            help="Não força limpeza de opcionais vazios.",
        )
        # defaults: backfill conservador em refetch, agressivo em overwrite
        parser.set_defaults(refetch_optionals_detail=False, overwrite_empty_optionals=True)

    def handle(self, *args, **opts):
        # estilos (há projetos sem NOTICE; faz fallback para WARNING)
        style_notice = getattr(self.style, "NOTICE", self.style.WARNING)

        now = datetime.now()
        to_dt = _parse_any_dt(opts["to_dt"]) if opts.get("to_dt") else now

        if opts.get("from_dt"):
            from_dt = _parse_any_dt(opts["from_dt"])
        else:
            base = to_dt - timedelta(days=730)
            from_dt = datetime(base.year, base.month, base.day)  # 00:00:00

        window_days = int(opts["window_days"])
        overlap_minutes = int(opts["overlap_minutes"])
        sleep_seconds = float(opts["sleep_seconds"])
        max_windows = int(opts["max_windows"])
        refetch_optionals_detail = bool(opts.get("refetch_optionals_detail", False))
        overwrite_empty_optionals = bool(opts.get("overwrite_empty_optionals", True))
        verbosity = int(opts.get("verbosity", 1))

        if window_days <= 0:
            raise ValueError("--window-days deve ser > 0")
        if overlap_minutes < 0:
            raise ValueError("--overlap-minutes não pode ser negativo")
        if max_windows <= 0:
            raise ValueError("--max-windows deve ser > 0")

        current_start: datetime = from_dt
        previous_span: Optional[tuple[datetime, datetime]] = None

        i = 0
        while True:
            i += 1
            if i > max_windows:
                self.stderr.write(
                    self.style.WARNING(f"Atingiu --max-windows={max_windows}. Encerrando.")
                )
                break

            if current_start > to_dt:
                break

            candidate_end = current_start + timedelta(days=window_days) - MICRO
            current_end = candidate_end if candidate_end <= to_dt else to_dt

            span = (current_start, current_end)
            if previous_span is not None and span == previous_span:
                self.stderr.write(
                    self.style.WARNING("Janela repetida detectada. Encerrando para evitar loop.")
                )
                break
            previous_span = span

            self.stdout.write(
                style_notice(
                    f"[{i}] Janela: {_fmt_dt(current_start)} -> {_fmt_dt(current_end)}"
                )
            )

            try:
                summary = sync_budgets(
                    start_dt=current_start,
                    end_dt=current_end,
                    # importante: por padrão, evitamos refetch no backfill (pode ser ligado por flag)
                    refetch_optionals_detail=refetch_optionals_detail,
                    # importante: por padrão, forçamos limpar opcionais vazios no backfill
                    overwrite_empty_optionals=overwrite_empty_optionals,
                )
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"   ✗ ERRO ao sincronizar: {e}"))
                summary = {}

            received = int((summary or {}).get("count", 0) or 0)
            created = int((summary or {}).get("created", 0) or 0)
            updated = int((summary or {}).get("updated", 0) or 0)
            errors_n = len((summary or {}).get("errors", []) or [])

            self.stdout.write(
                self.style.SUCCESS(
                    f"   ✓ OK — recebidos={received}, criados={created}, atualizados={updated}, erros={errors_n}"
                )
            )

            # Detalhes adicionais quando verbosity >= 2
            if verbosity >= 2:
                op = {
                    "prod": (
                        (summary or {}).get("orc_produtos_created", 0),
                        (summary or {}).get("orc_produtos_updated", 0),
                        (summary or {}).get("orc_produtos_deleted", 0),
                        (summary or {}).get("orc_produtos_seen", 0),
                    ),
                    "opc": (
                        (summary or {}).get("orc_opcionais_created", 0),
                        (summary or {}).get("orc_opcionais_updated", 0),
                        (summary or {}).get("orc_opcionais_deleted", 0),
                        (summary or {}).get("orc_opcionais_seen", 0),
                    ),
                    "obs": (
                        (summary or {}).get("orc_observacoes_created", 0),
                        (summary or {}).get("orc_observacoes_updated", 0),
                        (summary or {}).get("orc_observacoes_deleted", 0),
                        (summary or {}).get("orc_observacoes_seen", 0),
                    ),
                }
                self.stdout.write(
                    f"      dApiOrcamentosProduto: +{op['prod'][0]} ~{op['prod'][1]} -{op['prod'][2]} (seen={op['prod'][3]})"
                )
                self.stdout.write(
                    f"      dApiOrcamentosOpcionais: +{op['opc'][0]} ~{op['opc'][1]} -{op['opc'][2]} (seen={op['opc'][3]})"
                )
                self.stdout.write(
                    f"      dApiOrcamentosObservacoes: +{op['obs'][0]} ~{op['obs'][1]} -{op['obs'][2]} (seen={op['obs'][3]})"
                )
                if errors_n:
                    self.stdout.write("      errors:")
                    for err in (summary or {}).get("errors", []):
                        self.stdout.write(f"        - {err}")

            if current_end >= to_dt:
                break

            if sleep_seconds > 0:
                try:
                    time.sleep(sleep_seconds)
                except KeyboardInterrupt:
                    self.stderr.write(self.style.WARNING("Interrompido durante o sleep."))
                    break

            next_start = current_end + MICRO
            if overlap_minutes > 0:
                with_overlap = next_start - timedelta(minutes=overlap_minutes)
                if with_overlap > current_start:
                    next_start = with_overlap
            if next_start <= current_start:
                next_start = current_end + MICRO

            current_start = next_start

        self.stdout.write(self.style.SUCCESS("Backfill de budgets finalizado."))
