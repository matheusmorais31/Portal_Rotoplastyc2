# documentos/management/commands/fix_codigos.py
"""Normaliza o campo `codigo`.

Objetivos principais
--------------------
1. Um *único* UUID ‑ raiz por documento (mesmo `nome`).  A menor revisão
    aprovada vira a raiz.
2. Garantir que **(codigo, revisao)** seja único no banco como um todo
    – mesmo entre documentos de nomes diferentes.
3. Revisões **reprovadas** nunca herdam o mesmo `codigo` de revisões
    aprovadas; cada uma recebe/retém seu próprio UUID.
4. Não dispara `IntegrityError` mesmo em bases com dados quebrados.
"""

from __future__ import annotations

import logging
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from documentos.models import Documento

log = logging.getLogger("documentos")


STATUS_REPROVADO = "reprovado"  # ajuste aqui se os choices mudarem


class Command(BaseCommand):
    help = "Consolida/repara o par (codigo, revisao) para todos os documentos."

    def handle(self, *args, **options):  # noqa: D401 – django signature
        """Percorre todos os `nome` distintos corrigindo em lote."""

        with transaction.atomic():
            # --- AJUSTE ADICIONADO ---
            # Primeiro, define todos os campos 'codigo' como NULL
            log.info("Definindo todos os campos 'codigo' como NULL...")
            Documento.objects.all().update(codigo=None)
            log.info("Campos 'codigo' definidos como NULL.")
            # --- FIM DO AJUSTE ---

            for nome in (
                Documento.objects.values_list("nome", flat=True).distinct()
            ):
                docs = (
                    Documento.objects.filter(nome=nome)
                    .order_by("revisao", "id")
                )

                if not docs.exists():
                    continue

                # -----------------------------------------------------
                #   Separa aprovados × reprovados (mantendo ordenação)
                # -----------------------------------------------------
                aprovados: list[Documento] = list(
                    docs.exclude(status=STATUS_REPROVADO)
                )
                reprovados: list[Documento] = list(
                    docs.filter(status=STATUS_REPROVADO)
                )

                # Nenhuma revisão aprovada → só isolar reprovadas
                if not aprovados:
                    self._isolar_reprovados(reprovados)
                    log.info(
                        "[%s] só havia revisões reprovadas", nome
                    )
                    continue

                # -----------------------------------------------------
                # 1️⃣  Define a raiz = 1ª revisão APROVADA
                # -----------------------------------------------------
                raiz = aprovados[0]
                # Como todos os códigos foram setados para None,
                # a raiz sempre precisará de um novo UUID.
                raiz.codigo = uuid.uuid4()
                raiz.save(update_fields=["codigo"])
                codigo_raiz = raiz.codigo

                # conjunto das revisões já usando esse uuid
                # Após o reset, este conjunto estará inicialmente vazio para este codigo_raiz
                revisoes_raiz: set[int] = set()
                revisoes_raiz.add(raiz.revisao) # Adiciona a revisão da raiz


                # -----------------------------------------------------
                # 2️⃣  Propaga uuid‑raiz para demais APROVADOS
                #    (evitando colisão global de índice único)
                # -----------------------------------------------------
                for doc in aprovados[1:]:
                    # Como todos os códigos foram resetados, a verificação
                    # 'if doc.codigo == codigo_raiz:' não é mais estritamente
                    # necessária da mesma forma, mas a lógica de colisão permanece.

                    # outro registro (qualquer nome) já usa (uuid_raiz, revisao)?
                    # Esta verificação ainda é crucial para garantir a unicidade de (codigo, revisao)
                    # globalmente, caso haja processamento concorrente ou dados inesperados.
                    existe = (
                        Documento.objects
                        .filter(codigo=codigo_raiz, revisao=doc.revisao)
                        .exclude(pk=doc.pk) # Exclui o próprio documento da verificação
                        .exists()
                    )
                    if existe:
                        # não podemos copiar o uuid → isola
                        # Como o doc.codigo é None, ele sempre receberá um novo UUID aqui.
                        doc.codigo = uuid.uuid4()
                        doc.documento_original = None
                        doc.save(update_fields=["codigo", "documento_original"])
                        log.warning(
                            "[%s] Colisão detectada para rev %d. Novo UUID %s gerado.",
                            nome, doc.revisao, doc.codigo
                        )
                        continue

                    # seguro copiar o uuid‑raiz
                    doc.codigo = codigo_raiz
                    doc.documento_original_id = raiz.id
                    doc.save(update_fields=["codigo", "documento_original"])
                    revisoes_raiz.add(doc.revisao)

                # -----------------------------------------------------
                # 3️⃣  Revisões REPROVADAS mantêm/ganham UUID próprio
                # -----------------------------------------------------
                self._isolar_reprovados(reprovados)

                log.info(
                    "[%s] unificadas %d revisões aprovadas / tratados %d reprovadas",
                    nome,
                    len(aprovados),
                    len(reprovados),
                )

        log.info("==== fix_codigos concluído ====")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _isolar_reprovados(reprovados: list[Documento]) -> None:
        """Garante que cada revisão *reprovada* tenha seu próprio UUID."""
        for doc in reprovados:
            # Como todos os códigos foram setados para None,
            # a condição 'not doc.codigo' será sempre verdadeira.
            # A condição 'doc.documento_original_id is not None' ainda é relevante
            # para desvincular se necessário.
            if doc.documento_original_id is not None or not doc.codigo: # Ajuste na condição
                doc.codigo = uuid.uuid4()
                doc.documento_original = None
                doc.save(update_fields=["codigo", "documento_original"])