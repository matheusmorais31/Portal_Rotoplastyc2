# bi/models.py
from __future__ import annotations

import re
from typing import List, Dict, Any

from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group

_GUID_RE = r"[0-9a-fA-F-]{36}"


def _lower_or_empty(s: str | None) -> str:
    return (s or "").strip().lower()


class BIReport(models.Model):
    # Metadados básicos
    title = models.CharField(max_length=200)
    embed_code = models.TextField(blank=True, null=True)

    # Controle de acesso
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="bi_reports", blank=True
    )
    allowed_groups = models.ManyToManyField(
        Group, related_name="bi_reports", blank=True
    )
    all_users = models.BooleanField(default=False)  # acesso para todos

    # IDs “legados” (mantidos por compatibilidade com código existente)
    report_id = models.CharField(max_length=100, unique=True)
    group_id = models.CharField(
        max_length=100,
        default="dc152d8a-7555-42d7-b53d-fbe1ce0dff28",  # workspace padrão
    )

    # IDs “claros” usados pelas utils/views novas — mantidos em sincronia
    pbi_report_id = models.CharField(
        max_length=36,
        blank=True,
        null=True,
        db_index=True,
        help_text="ReportId (GUID). Se vazio, será herdado de report_id.",
    )
    pbi_group_id = models.CharField(
        max_length=36,
        blank=True,
        null=True,
        db_index=True,
        help_text="GroupId/Workspace (GUID). Se vazio, será herdado de group_id.",
    )

    # Dataset e horários
    dataset_id = models.CharField(max_length=100, blank=True, null=True)
    last_updated = models.DateTimeField(blank=True, null=True)
    next_update = models.DateTimeField(blank=True, null=True)

    # 🔹 Dataflows a atualizar antes deste relatório
    # Ex.: [{"group_id": "...", "dataflow_id": "...", "name": "Opcional"}]
    upstream_dataflows = models.JSONField(default=list, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "Relatório BI"
        verbose_name_plural = "Relatórios BI"
        indexes = [
            models.Index(fields=["report_id"]),
            models.Index(fields=["group_id"]),
            models.Index(fields=["last_updated"]),
            models.Index(fields=["pbi_report_id"]),
            models.Index(fields=["pbi_group_id"]),
        ]

    def __str__(self) -> str:
        return self.title

    # ---------- Helpers ----------
    @staticmethod
    def extract_ids_from_embed(embed_code: str) -> tuple[str | None, str | None]:
        """
        Tenta extrair (group_id, report_id) do embed_code:
        .../groups/<gid>/reports/<rid>
        """
        if not embed_code:
            return None, None
        m = re.search(rf"/groups/({_GUID_RE})/reports/({_GUID_RE})", embed_code, re.I)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def ensure_ids_from_embed(self) -> None:
        """
        Se faltarem IDs, tenta preenchê-los a partir do embed_code.
        """
        if (not self.group_id or not self.report_id) or (
            not self.pbi_group_id or not self.pbi_report_id
        ):
            gid, rid = self.extract_ids_from_embed(self.embed_code or "")
            if gid and not self.group_id:
                self.group_id = gid
            if rid and not self.report_id:
                self.report_id = rid
            if gid and not self.pbi_group_id:
                self.pbi_group_id = gid
            if rid and not self.pbi_report_id:
                self.pbi_report_id = rid

    @property
    def effective_group_id(self) -> str:
        """
        Retorna o group/workspace preferindo pbi_group_id.
        """
        return (
            self.pbi_group_id
            or self.group_id
            or getattr(settings, "POWERBI_GROUP_ID_DEFAULT", "")
            or ""
        )

    @property
    def effective_report_id(self) -> str:
        """
        Retorna o reportId preferindo pbi_report_id.
        """
        return self.pbi_report_id or self.report_id or ""

    def clean_upstream_dataflows(self) -> None:
        """
        Normaliza upstream_dataflows em uma lista de dicts {group_id, dataflow_id, name?}
        e força GUIDs para lowercase para garantir correspondência estável no UI.
        """
        norm: List[Dict[str, Any]] = []
        raw = self.upstream_dataflows or []
        if isinstance(raw, dict):
            raw = [raw]
        for it in (raw if isinstance(raw, list) else []):
            df = _lower_or_empty(
                it.get("dataflow_id") or it.get("id") or it.get("objectId")
            )
            gid = _lower_or_empty(
                it.get("group_id")
                or it.get("workspaceId")
                or it.get("groupId")
                or self.effective_group_id
            )
            nm = (it.get("name") or "").strip()
            if df and gid:
                item = {"group_id": gid, "dataflow_id": df}
                if nm:
                    item["name"] = nm
                norm.append(item)
        self.upstream_dataflows = norm

    def _lowercase_ids(self) -> None:
        """
        Força GUIDs conhecidos para lowercase (report/group/pbi_*/dataset).
        """
        if isinstance(self.report_id, str):
            self.report_id = _lower_or_empty(self.report_id)
        if isinstance(self.group_id, str):
            self.group_id = _lower_or_empty(self.group_id)
        if isinstance(self.pbi_report_id, str):
            self.pbi_report_id = _lower_or_empty(self.pbi_report_id)
        if isinstance(self.pbi_group_id, str):
            self.pbi_group_id = _lower_or_empty(self.pbi_group_id)
        if isinstance(self.dataset_id, str):
            self.dataset_id = _lower_or_empty(self.dataset_id)

    def save(self, *args, **kwargs):
        # 1) tenta preencher IDs a partir do embed, quando faltam
        self.ensure_ids_from_embed()

        # 2) mantém pbi_* em sincronia com legados (sem sobrescrever quando já há GUID)
        if not self.pbi_group_id and self.group_id:
            self.pbi_group_id = self.group_id
        if not self.pbi_report_id and self.report_id:
            self.pbi_report_id = self.report_id
        if not self.group_id and self.pbi_group_id:
            self.group_id = self.pbi_group_id
        if not self.report_id and self.pbi_report_id:
            self.report_id = self.pbi_report_id

        # 3) normaliza GUIDs para lowercase (evita mismatch no front)
        self._lowercase_ids()

        # 4) normaliza a lista de dataflows
        self.clean_upstream_dataflows()

        super().save(*args, **kwargs)


class BIAccess(models.Model):
    bi_report = models.ForeignKey("BIReport", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()  # desativa permissões padrão
        permissions = [
            ("view_bi", "Lista geral BI"),
            ("edit_bi", "Editar BI"),
            ("view_access", "Visualizar Acessos"),
            ("permission_report", "Relatório de permissões de BI"),
            ("refresh_bi", "Atualizar BI"),
        ]
        verbose_name = "Acesso a BI"
        verbose_name_plural = "Acessos a BI"
        indexes = [
            models.Index(fields=["bi_report", "user"]),
            models.Index(fields=["accessed_at"]),
        ]
        ordering = ["-accessed_at"]

    def __str__(self) -> str:
        return f"{self.user.username} acessou {self.bi_report.title} em {self.accessed_at}"


class BIUserReportState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bi_report = models.ForeignKey("BIReport", on_delete=models.CASCADE)
    # Exemplo de estrutura:
    # {
    #   "reportFilters": [...],
    #   "activePage": "Página 1",
    #   "slicers": {"Página 1": {<visualName>: {...}}},
    #   "bookmarkState": "<string>"
    # }
    state = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        unique_together = ("user", "bi_report")
        indexes = [
            models.Index(fields=["user", "bi_report"]),
            models.Index(fields=["updated_at"]),
        ]
        verbose_name = "Estado do Relatório por Usuário"
        verbose_name_plural = "Estados de Relatório por Usuário"

    def __str__(self) -> str:
        return f"Estado {self.user} → {self.bi_report}"


class BISavedView(models.Model):
    """
    Visão salva (favorito) de um relatório, com possibilidade de compartilhamento.
    Não altera permissões de acesso ao BI — só organiza estados prontos de visualização.
    """
    bi_report = models.ForeignKey(
        "BIReport", on_delete=models.CASCADE, related_name="saved_views"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views"
    )

    name = models.CharField("Nome", max_length=120)
    description = models.CharField("Descrição", max_length=240, blank=True, null=True)

    # Estado consolidado do embed (priorize bookmarkState ao aplicar)
    state = models.JSONField(default=dict, blank=True)

    # Compartilhamento
    is_public = models.BooleanField(
        default=False
    )  # visível a qualquer usuário que JÁ tenha acesso ao BI
    shared_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="saved_views_shared"
    )
    shared_groups = models.ManyToManyField(
        Group, blank=True, related_name="saved_views_shared"
    )

    # Preferência do dono
    is_default = models.BooleanField(default=False)

    # Token curto para link compartilhável (?view=<share_token>)
    share_token = models.CharField(max_length=40, unique=True, db_index=True)

    # Auditoria
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [
            # Evita nomes duplicados por dono dentro do mesmo BI
            models.UniqueConstraint(
                fields=["bi_report", "owner", "name"],
                name="uniq_savedview_name_owner_bi",
            ),
        ]
        permissions = [
            ("manage_saved_views", "Gerenciar visões salvas de BI"),
        ]
        verbose_name = "Visão Salva"
        verbose_name_plural = "Visões Salvas"
        indexes = [
            models.Index(fields=["bi_report", "owner"]),
            models.Index(fields=["owner", "is_default"]),
            models.Index(fields=["updated_at"]),
        ]
        ordering = ["owner", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.owner})"

    def save(self, *args, **kwargs):
        # Gera token compartilhável se não existir
        if not self.share_token:
            import uuid

            self.share_token = uuid.uuid4().hex[:12]

        super_default = self.is_default
        super().save(*args, **kwargs)
        if super_default:
            type(self).objects.filter(
                bi_report=self.bi_report, owner=self.owner, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)

    def can_view(self, user) -> bool:
        """
        Regras de visibilidade (pressupõe que o usuário já tenha acesso ao BI).
        """
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if user == self.owner:
            return True
        if self.is_public:
            return True
        if self.shared_users.filter(pk=user.pk).exists():
            return True
        # Em auth padrão, a relação é Group.user_set
        if self.shared_groups.filter(user__id=user.id).exists():
            return True
        return False

    def as_brief(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "owner": getattr(self.owner, "username", ""),
            "is_public": self.is_public,
            "is_default": self.is_default,
            "share_token": self.share_token,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
