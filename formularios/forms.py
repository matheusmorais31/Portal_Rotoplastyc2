# forms.py
from __future__ import annotations

import json
from datetime import timedelta

from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Formulario, Campo

User = get_user_model()


# ------------------------------------------------------------------
# 1) Form principal (cabeçalho)
# ------------------------------------------------------------------
class FormularioForm(forms.ModelForm):
    """
    - 'abre_em' e 'fecha_em' usam <input type="datetime-local"> com
      formato HTML5 (YYYY-MM-DDTHH:MM) para não sumirem após reload.
    - 'repetir_cada_str' exibe/recebe DD:HH:MM e é convertido para
      DurationField (repetir_cada) no clean().
    - Quando aparece_home=True e alvo_resposta='MAN', não bloqueamos
      o save se ainda não houver 'alvo_usuarios' — a própria lógica
      de exibição na home impedirá que apareça para alguém até que
      a lista seja preenchida.
    """

    # Campos de data/hora com widget já no formato correto
    abre_em = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        label="Abre em",
    )
    fecha_em = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        label="Fecha em",
    )

    repetir_cada_str = forms.CharField(
        required=False,
        label="Repetir a cada (dias:horas:minutos)",
        widget=forms.TextInput(
            attrs={
                "placeholder": "00:00:00",
                "pattern": r"^\d{2}:\d{2}:\d{2}$",
                "title": "Use o formato DD:HH:MM (ex.: 00:04:00)",
            }
        ),
        help_text="Use DD:HH:MM. Ex.: 00:04:00 (4h). 00:00:00 = não repete (mostra uma única vez por usuário).",
    )

    class Meta:
        model = Formulario
        fields = [
            "titulo",
            "descricao",
            "publico",
            "abre_em",
            "fecha_em",
            "aceita_respostas",
            # ==== Config (Home) ====
            "aparece_home",
            "coletar_nome",
            "alvo_resposta",
            "alvo_usuarios",
            # repetir_cada é populado via repetir_cada_str
        ]
        widgets = {
            "alvo_usuarios": forms.SelectMultiple(attrs={"size": 8}),
        }

    # --------- helpers internos ---------
    @staticmethod
    def _format_duration(td: timedelta | None) -> str:
        """Formata timedelta como DD:HH:MM (zero-padded)."""
        if td is None:
            return "00:00:00"
        total_min = int(td.total_seconds() // 60)
        d, rem = divmod(total_min, 24 * 60)
        h, m = divmod(rem, 60)
        return f"{d:02d}:{h:02d}:{m:02d}"

    @staticmethod
    def _parse_duration(s: str) -> timedelta | None:
        """
        Converte 'DD:HH:MM' -> timedelta.
        '00:00:00' => timedelta(0)  (não repete).
        Vazio => None (tratado como não repetir na lógica de exibição).
        """
        s = (s or "").strip()
        if not s:
            return None
        if s == "00:00:00":
            return timedelta(0)
        try:
            dd, hh, mm = [int(x) for x in s.split(":")]
            return timedelta(days=dd, hours=hh, minutes=mm)
        except Exception:
            raise forms.ValidationError("Formato inválido. Use DD:HH:MM (ex.: 00:04:00).")

    # --------- lifecycle ---------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Preenche repetir_cada_str (GET / primeira carga)
        if not self.is_bound:
            self.initial["repetir_cada_str"] = self._format_duration(
                getattr(self.instance, "repetir_cada", None)
            )

            # Garante que os datetime apareçam no controle e no timezone local
            for f in ("abre_em", "fecha_em"):
                val = getattr(self.instance, f, None)
                if val:
                    local = timezone.localtime(val) if timezone.is_aware(val) else val
                    self.initial[f] = local.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        data = super().clean()

        # Converte repetir_cada_str -> repetir_cada
        try:
            data["repetir_cada"] = self._parse_duration(data.get("repetir_cada_str"))
        except forms.ValidationError as e:
            self.add_error("repetir_cada_str", e)

        # Validação: fecha_em não pode ser menor que abre_em
        abre  = data.get("abre_em")
        fecha = data.get("fecha_em")
        if abre and fecha and fecha < abre:
            self.add_error("fecha_em", "A data de fechamento deve ser igual ou posterior à data de abertura.")

        # NÃO bloquear o save quando alvo = MAN sem usuários.
        # A exibição na home já impede aparecer para alguém até que a lista seja preenchida.
        # (Se preferir fallback automático para 100%, troque o 'pass' por: data["alvo_resposta"] = Formulario.AlvoChoices.ALL)
        if data.get("aparece_home") and data.get("alvo_resposta") == "MAN":
            usuarios = data.get("alvo_usuarios")
            if not usuarios or len(usuarios) == 0:
                pass

        return data

    def save(self, commit: bool = True):
        obj = super().save(commit=False)
        # seta o DurationField a partir do cleaned_data
        obj.repetir_cada = self.cleaned_data.get("repetir_cada")
        if commit:
            obj.save()
            self.save_m2m()
        return obj


# ------------------------------------------------------------------
# 2) Form de cada Campo / Pergunta
# ------------------------------------------------------------------
class CampoForm(forms.ModelForm):
    """
    • 'ordem' é oculto e preenchido pelo JS.
    • 'opcoes_json' → multipla / checkbox / lista (Hidden)
    • 'valid_json'  → regras extras (arquivo)         (Hidden)
    • NÃO expõe 'ativo' (arquivamento controlado pela view).
    """
    opcoes_json = forms.CharField(widget=forms.HiddenInput(), required=False)
    valid_json = forms.CharField(widget=forms.HiddenInput(), required=False)
    ordem = forms.IntegerField(widget=forms.HiddenInput())
    id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Se já existe 'validacao_json' no modelo, preenche o hidden 'valid_json' com o JSON string
        if self.instance and self.instance.pk and getattr(self.instance, "validacao_json", None):
            self.initial["valid_json"] = json.dumps(self.instance.validacao_json)

    class Meta:
        model = Campo
        exclude = ["formulario", "ativo"]  # <<< NÃO editar o flag 'ativo' no form
        widgets = {
            "tipo": forms.Select(),
            "ajuda": forms.TextInput(attrs={"placeholder": "Texto de ajuda opcional"}),
        }


# ------------------------------------------------------------------
# 3) Formsets
# ------------------------------------------------------------------
CampoFormSetCreate = inlineformset_factory(
    Formulario, Campo, form=CampoForm, extra=1, can_delete=True
)

CampoFormSetBuilder = inlineformset_factory(
    Formulario, Campo, form=CampoForm, extra=0, can_delete=True
)
