# documentos/management/commands/fix_codigos.py
from django.core.management.base import BaseCommand
from django.db import models, transaction
from documentos.models import Documento
import uuid, logging

log = logging.getLogger("documentos")

class Command(BaseCommand):
    help = "Normaliza `codigo`: a menor revisão vira raiz; (codigo,revisao) fica único."

    def handle(self, *args, **opts):
        with transaction.atomic():

            for nome in Documento.objects.values_list("nome", flat=True).distinct():
                docs = Documento.objects.filter(nome=nome).order_by("revisao", "id")

                if not docs:
                    continue

                # -----------------------------------------------------------------
                # 1️⃣  GARANTE que não existam duas linhas (mesmo codigo,mesma revisao)
                # -----------------------------------------------------------------
                revisoes_vistas = set()
                for d in docs:
                    key = (d.codigo, d.revisao)
                    if d.codigo and key not in revisoes_vistas:
                        revisoes_vistas.add(key)
                        continue

                    # já existe outro igual → dê um NOVO uuid provisório
                    d.codigo = uuid.uuid4()
                    d.documento_original = None
                    d.save(update_fields=["codigo", "documento_original"])
                    revisoes_vistas.add((d.codigo, d.revisao))
                    log.debug(f"   └─ separando duplicado #{d.id}")

                # -----------------------------------------------------------------
                # 2️⃣  DEFINE o código-raiz = menor revisão (1ª da lista)
                # -----------------------------------------------------------------
                raiz = docs.first()
                if not raiz.codigo:
                    raiz.codigo = uuid.uuid4()
                    raiz.save(update_fields=["codigo"])
                codigo_raiz = raiz.codigo

                # -----------------------------------------------------------------
                # 3️⃣  PROPAGA o código-raiz para quem ainda não tem
                #     (sem repetir revisões já usadas dentro do raiz)
                # -----------------------------------------------------------------
                revisoes_usadas = set(
                    Documento.objects
                    .filter(codigo=codigo_raiz)
                    .values_list("revisao", flat=True)
                )

                for d in docs:
                    if d.id == raiz.id:
                        continue
                    if d.revisao in revisoes_usadas:
                        # mesmo número de revisão já existe ⇒ mantém
                        # o uuid que demos na etapa 1
                        continue
                    d.codigo = codigo_raiz
                    d.documento_original_id = raiz.id
                    d.save(update_fields=["codigo", "documento_original"])
                    revisoes_usadas.add(d.revisao)

                log.info(f"[{nome}] OK – {len(docs)} linhas normalizadas")

        log.info("==== Saneamento concluído ====")
