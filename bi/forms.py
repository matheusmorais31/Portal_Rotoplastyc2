# bi/forms.py
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import BIReport


User = get_user_model()


class BIReportForm(forms.ModelForm):
    """
    Formulário de CRIAÇÃO do BIReport.
    - Permite informar title, embed_code, report_id, group_id, participantes e all_users.
    - Se report_id/group_id vierem vazios, tentamos extrair do embed_code.
    """
    class Meta:
        model = BIReport
        fields = [
            "title",
            "embed_code",
            "report_id",
            "group_id",
            "allowed_users",
            "allowed_groups",
            "all_users",
        ]
        labels = {
            "title": "Título",
            "embed_code": "Código Embed",
            "report_id": "ID do Relatório",
            "group_id": "ID do Grupo (Workspace)",
            "allowed_users": "Usuários Permitidos",
            "allowed_groups": "Grupos Permitidos",
            "all_users": "Permitir a todos os usuários",
        }
        widgets = {
            "embed_code": forms.Textarea(attrs={"rows": 4}),
            "allowed_users": forms.CheckboxSelectMultiple(),
            "allowed_groups": forms.CheckboxSelectMultiple(),
            "all_users": forms.CheckboxInput(),
        }

    def clean(self):
        cleaned = super().clean()

        # Se o usuário marcou "todos", não exigimos os M2M
        all_users = bool(cleaned.get("all_users"))
        if all_users:
            # Apenas para a validação do form — as views fazem o clear.
            cleaned["allowed_users"] = []
            cleaned["allowed_groups"] = []

        # Tenta extrair IDs do embed_code se faltarem
        embed = (cleaned.get("embed_code") or "").strip()
        group_id = (cleaned.get("group_id") or "").strip()
        report_id = (cleaned.get("report_id") or "").strip()

        if embed and (not group_id or not report_id):
            gid, rid = BIReport.extract_ids_from_embed(embed)
            if gid and not group_id:
                cleaned["group_id"] = gid
            if rid and not report_id:
                cleaned["report_id"] = rid

        return cleaned


class BIReportEditForm(forms.ModelForm):
    """
    Formulário de EDIÇÃO do BIReport.
    - Mostra title/embed_code como SOMENTE LEITURA (disabled=True).
    - Mantém campos de permissão (all_users, allowed_users, allowed_groups).
    - Não tenta salvar mudanças em title/embed_code (proteção extra).
    """
    class Meta:
        model = BIReport
        fields = [
            "title",
            "embed_code",
            "allowed_users",
            "allowed_groups",
            "all_users",
        ]
        labels = {
            "title": "Título",
            "embed_code": "Código Embed",
            "allowed_users": "Usuários Permitidos",
            "allowed_groups": "Grupos Permitidos",
            "all_users": "Permitir a todos os usuários",
        }
        widgets = {
            "embed_code": forms.Textarea(attrs={"rows": 4}),
            "allowed_users": forms.CheckboxSelectMultiple(),
            "allowed_groups": forms.CheckboxSelectMultiple(),
            "all_users": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Desabilita campos somente leitura na edição
        self.fields["title"].disabled = True
        self.fields["embed_code"].disabled = True

        # Evita qualquer exigência indevida caso venham desmarcados no POST
        self.fields["title"].required = False
        self.fields["embed_code"].required = False
        self.fields["allowed_users"].required = False
        self.fields["allowed_groups"].required = False

        # Pequeno toque visual
        self.fields["title"].widget.attrs.update({"readonly": True})
        self.fields["embed_code"].widget.attrs.update({"readonly": True})

    # Proteção extra: mesmo que alguém tente forçar via devtools, devolvemos o valor original
    def clean_title(self):
        return self.instance.title

    def clean_embed_code(self):
        return self.instance.embed_code

    def clean(self):
        cleaned = super().clean()
        # Se "todos os usuários" está marcado, não exigimos M2M
        if cleaned.get("all_users"):
            cleaned["allowed_users"] = []
            cleaned["allowed_groups"] = []
        return cleaned
