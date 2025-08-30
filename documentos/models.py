"""
models.py – app documentos
Cada documento raiz e suas revisões compartilham um único UUID (`codigo`)
e a combinação (`codigo`, `revisao`) é única no banco.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone               # <— importação adicionada
from django.utils.text import slugify

logger = logging.getLogger("documentos")
User = get_user_model()


# -----------------------------------------------------------------------------
# Armazenamento que sobrescreve arquivos com mesmo nome
# -----------------------------------------------------------------------------
class OverwriteStorage(FileSystemStorage):
    def get_available_name(self, name: str, max_length: Optional[int] = None) -> str:
        if self.exists(name):
            try:
                self.delete(name)
                logger.debug(f"[OverwriteStorage] removido: {name}")
            except Exception as exc:
                logger.error(f"[OverwriteStorage] falhou ao remover {name}: {exc}")
        return name


protected_storage = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=None)


# -----------------------------------------------------------------------------
# Helpers para caminhos de upload
# -----------------------------------------------------------------------------
def documento_upload_path(instance: "Documento", filename: str) -> Path:
    return Path("documentos") / "editaveis" / filename


def pdf_upload_path(instance: "Documento", filename: str) -> Path:
    return Path("documentos") / "pdf" / filename


def spreadsheet_upload_path(instance: "Documento", filename: str) -> Path:
    return Path("documentos") / "spreadsheet" / filename


# -----------------------------------------------------------------------------
# Categoria
# -----------------------------------------------------------------------------
class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    bloqueada = models.BooleanField(
        default=False,
        help_text="Marque se esta categoria deve bloquear download e impressão.",
    )

    def __str__(self) -> str:
        return self.nome


# -----------------------------------------------------------------------------
# Documento
# -----------------------------------------------------------------------------
class Documento(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ("pdf", "PDF"),
        ("spreadsheet", "Planilha"),
        ("pdf_spreadsheet", "PDF da Planilha"),
    ]
    STATUS_CHOICES = [
        ("aguardando_analise", "Aguardando Análise"),
        ("analise_concluida", "Análise Concluída"),
        ("aguardando_elaborador", "Aguardando Aprovação do Elaborador"),
        ("aguardando_aprovador1", "Aguardando Aprovação do Aprovador"),
        ("aprovado", "Aprovado"),
        ("reprovado", "Reprovado"),
    ]

    codigo = models.UUIDField(
        editable=False,
        db_index=True,
        null=True,
        help_text="UUID que liga todas as revisões de um mesmo documento",
    )
    nome = models.CharField(max_length=200)
    revisao = models.IntegerField(choices=[(i, f"{i:02d}") for i in range(0, 101)])
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)

    aprovador1 = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="aprovador1_documentos",
    )
    elaborador = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="documentos_criados",
    )
    solicitante = models.ForeignKey(
        User, on_delete=models.CASCADE, default=38, related_name="+"
    )
    analista = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documentos_analisados",
    )

    documento = models.FileField(upload_to=documento_upload_path)
    documento_pdf = models.FileField(
        upload_to=pdf_upload_path,
        storage=protected_storage,
        editable=False,
        null=True,
        blank=True,
    )

    data_criacao = models.DateTimeField(auto_now_add=True)
    data_analise = models.DateTimeField(null=True, blank=True)
    data_aprovado_elaborador = models.DateTimeField(null=True, blank=True)
    data_aprovado_aprovador = models.DateTimeField(null=True, blank=True)

    aprovado_por_aprovador1 = models.BooleanField(default=False)
    reprovado = models.BooleanField(default=False)
    motivo_reprovacao = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True, help_text="Se o documento está ativo.")
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default="aguardando_analise"
    )
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default="pdf",
        help_text="Tipo do documento: PDF ou Planilha.",
    )

    documento_original = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="revisoes",
    )

    text_content = models.TextField(blank=True, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["codigo", "revisao"], name="uniq_codigo_revisao")
        ]
        permissions = [
            ("view_documentos", "Listar Documentos"),
            ("can_add_documento", "Adicionar Documento"),
            ("can_active", "Ativar/Inativar Documentos"),
            ("view_acessos_documento", "Visualizar Acessos"),
            ("can_view_revisions", "Visualizar Revisões"),
            ("replace_document", "Substituir PDF"),
            ("view_documentos_ina", "Listar Inativos"),
            ("list_pending_approvals", "Ver Pendências"),
            ("list_reproaches", "Ver Reprovações"),
            ("monitor_documents", "Monitorar Documentos"),
            ("delete_documento", "Deletar Documento"),
            ("can_approve", "Pode aprovar documentos"),
            ("can_analyze", "Pode analisar documentos"),
            ("can_view_editables", "Listar Editáveis"),
            ("view_categoria", "Listar Categorias"),
            ("add_categoria", "Adicionar Categoria"),
            ("change_categoria", "Editar Categoria"),
            ("delete_categoria", "Deletar Categoria"),
        ]

    def __str__(self) -> str:
        ativo = "Ativo" if self.is_active else "Inativo"
        return f"{self.nome} – Rev {self.revisao:02d} – {self.get_status_display()} – {ativo}"

    def save(self, *args, **kwargs):
        logger.debug(f"[save] Documento '{self.nome}' (id={self.pk})")

        if not self.codigo:
            if self.documento_original_id:
                self.codigo = self.documento_original.codigo
            else:
                self.codigo = uuid.uuid4()

        if self.documento and self.document_type != "pdf_spreadsheet":
            ext = os.path.splitext(self.documento.name)[1].lower()
            if ext in [".doc", ".docx", ".odt"]:
                self.document_type = "pdf"
            elif ext in [".xls", ".xlsx", ".ods"]:
                self.document_type = "spreadsheet"
            else:
                raise ValidationError("Formato de arquivo inválido.")

        super().save(*args, **kwargs)

    def gerar_pdf(self) -> str:
        logger.debug(f"[gerar_pdf] Iniciando para '{self.nome}' (tipo={self.document_type})")

        if self.document_type == "pdf_spreadsheet" and self.documento_pdf:
            return self.documento_pdf.path

        if self.document_type == "spreadsheet":
            src = self.documento.path
            safe = slugify(self.nome)
            rel = Path("documentos") / "spreadsheet" / f"{safe}_v{self.revisao}{Path(src).suffix}"
            dst = Path(settings.MEDIA_ROOT) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if self.documento_pdf and self.documento_pdf.storage.exists(self.documento_pdf.name):
                self.documento_pdf.delete(save=False)
            shutil.copy(src, dst)
            self.documento_pdf.name = rel.as_posix()
            self.save(update_fields=["documento_pdf"])
            return self.documento_pdf.path

        if self.document_type in ("pdf",):
            if self.documento_pdf and os.path.exists(self.documento_pdf.path):
                return self.documento_pdf.path

            src = self.documento.path
            soffice = getattr(settings, "LIBREOFFICE_PATH", "/usr/bin/soffice") or "/usr/bin/soffice"

            # Ambiente: **sempre** garanta diretórios padrão no PATH
            env = os.environ.copy()
            base_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            env["PATH"] = f"{base_path}:{env.get('PATH','')}"
            env["HOME"] = env.get("HOME") or "/tmp"

            with tempfile.TemporaryDirectory(prefix="lo_profile_") as lo_profile, \
                tempfile.TemporaryDirectory(prefix="lo_out_") as tmp_out:

                user_install = f"file://{lo_profile}"
                cmd = [
                    soffice,
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation={user_install}",
                    "--convert-to", "pdf:writer_pdf_Export",
                    "--outdir", tmp_out,
                    src,
                ]

                logger.debug(f"[gerar_pdf] Executando: {' '.join(cmd)}")
                logger.debug(f"[gerar_pdf] PATH efetivo: {env['PATH']}  HOME={env['HOME']}")

                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    timeout=180,
                )

                if proc.returncode != 0:
                    logger.error(
                        f"[gerar_pdf] LO falhou: rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                    )
                    # rc=127 é “command not found” dentro do wrapper → tipicamente PATH parcial
                    if proc.returncode == 127:
                        raise RuntimeError(
                            "Falha na conversão LibreOffice (rc=127). "
                            "PATH do processo provavelmente está sem /usr/bin. "
                            "Reveja o unit do systemd e/ou mantenha o ajuste de PATH dentro do método."
                        )
                    raise RuntimeError("Falha na conversão LibreOffice.")

                nome_pdf = Path(src).with_suffix(".pdf").name
                pdf_tmp = Path(tmp_out) / nome_pdf
                if not pdf_tmp.exists():
                    candidates = list(Path(tmp_out).glob("*.pdf"))
                    if len(candidates) == 1:
                        pdf_tmp = candidates[0]
                    else:
                        raise FileNotFoundError("PDF não gerado pelo LibreOffice.")

                if self.documento_pdf and self.documento_pdf.storage.exists(self.documento_pdf.name):
                    self.documento_pdf.delete(save=False)

                safe = slugify(self.nome)
                rel = Path("documentos") / "pdf" / f"{safe}_v{self.revisao}.pdf"
                dst = Path(settings.MEDIA_ROOT) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(pdf_tmp), dst)

                self.documento_pdf.name = rel.as_posix()
                self.save(update_fields=["documento_pdf"])
                return self.documento_pdf.path

        raise ValueError(f"Tipo inválido: {self.document_type}")





class DocumentoNomeHistorico(models.Model):
    documento = models.ForeignKey(
        Documento, on_delete=models.CASCADE, related_name="historicos_nome"
    )
    nome_antigo = models.CharField(max_length=200)
    nome_novo = models.CharField(max_length=200)
    data_hora = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    def __str__(self) -> str:
        return (
            f"{self.documento.codigo} | {self.nome_antigo} → {self.nome_novo} "
            f"({self.data_hora:%d/%m/%Y %H:%M})"
        )


class Acesso(models.Model):
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data_acesso = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.usuario.username} – {self.documento.nome}"


class DocumentoDeletado(models.Model):
    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="documentos_deletados"
    )
    documento_nome = models.CharField(max_length=200)
    revisao = models.IntegerField()
    data_hora = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return (
            f"{self.documento_nome} (Rev {self.revisao}) "
            f"deletado por {self.usuario.username} em {self.data_hora:%d/%m/%Y %H:%M}"
        )
