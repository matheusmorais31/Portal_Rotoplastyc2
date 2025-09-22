from __future__ import annotations

from datetime import timedelta
import json

from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Formulario, Campo

User = get_user_model()


class FormularioForm(forms.ModelForm):
    abre_em = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
        label="Abre em",
    )
    fecha_em = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
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
            "aparece_home",
            "coletar_nome",
            "alvo_resposta",
            "alvo_usuarios",
        ]
        widgets = {
            "alvo_usuarios": forms.SelectMultiple(attrs={"size": 8}),
        }

    @staticmethod
    def _format_duration(td: timedelta | None) -> str:
        if td is None:
            return "00:00:00"
        total_min = int(td.total_seconds() // 60)
        d, rem = divmod(total_min, 24 * 60)
        h, m = divmod(rem, 60)
        return f"{d:02d}:{h:02d}:{m:02d}"

    @staticmethod
    def _parse_duration(s: str) -> timedelta | None:
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["repetir_cada_str"] = self._format_duration(
                getattr(self.instance, "repetir_cada", None)
            )
            for f in ("abre_em", "fecha_em"):
                val = getattr(self.instance, f, None)
                if val:
                    local = timezone.localtime(val) if timezone.is_aware(val) else val
                    self.initial[f] = local.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        data = super().clean()
        try:
            data["repetir_cada"] = self._parse_duration(data.get("repetir_cada_str"))
        except forms.ValidationError as e:
            self.add_error("repetir_cada_str", e)

        abre = data.get("abre_em")
        fecha = data.get("fecha_em")
        if abre and fecha and fecha < abre:
            self.add_error("fecha_em", "A data de fechamento deve ser igual ou posterior à data de abertura.")

        if data.get("aparece_home") and data.get("alvo_resposta") == "MAN":
            usuarios = data.get("alvo_usuarios")
            if not usuarios or len(usuarios) == 0:
                pass

        return data

    def save(self, commit: bool = True):
        obj = super().save(commit=False)
        obj.repetir_cada = self.cleaned_data.get("repetir_cada")
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class CampoForm(forms.ModelForm):
    opcoes_json = forms.CharField(widget=forms.HiddenInput(), required=False)
    valid_json  = forms.CharField(widget=forms.HiddenInput(), required=False)
    ordem       = forms.IntegerField(widget=forms.HiddenInput())
    id          = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    origem_opcoes        = forms.CharField(widget=forms.HiddenInput(), required=False)
    sqlhub_connection_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    sqlhub_query_id      = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    sqlhub_value_field   = forms.CharField(widget=forms.HiddenInput(), required=False)
    sqlhub_label_field   = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Campo
        exclude = ["formulario", "ativo"]
        widgets = {
            "tipo": forms.Select(),
            "ajuda": forms.TextInput(attrs={"placeholder": "Texto de ajuda opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Preenche origem/SQLHub a partir do logica_json
        cfg = getattr(self.instance, "logica_json", {}) or {}
        opt = (cfg.get("options") or {})
        if opt:
            self.initial["origem_opcoes"] = opt.get("source") or "manual"
            sh = opt.get("sqlhub") or {}
            self.initial["sqlhub_connection_id"] = sh.get("connection_id") or ""
            self.initial["sqlhub_query_id"]      = sh.get("query_id") or ""
            self.initial["sqlhub_value_field"]   = sh.get("value_field") or ""
            self.initial["sqlhub_label_field"]   = sh.get("label_field") or ""

        # NOVO: se já for um campo de upload, popular o hidden valid_json
        if getattr(self.instance, "tipo", None) == "arquivo":
            v = getattr(self.instance, "validacao_json", None)
            if v:
                try:
                    self.initial["valid_json"] = json.dumps(v)
                except Exception:
                    pass

    def clean(self):
        data = super().clean()

        tipo   = data.get("tipo")
        source = (self.data.get(f"{self.prefix}-origem_choice") or data.get("origem_opcoes") or "manual").strip()

        lj = dict(data.get("logica_json") or {})

        if tipo == "lista":
            if source == "sqlhub":
                cid = data.get("sqlhub_connection_id") or self.data.get(f"{self.prefix}-sqlhub_connection_id")
                qid = data.get("sqlhub_query_id")      or self.data.get(f"{self.prefix}-sqlhub_query_id")
                vf  = (data.get("sqlhub_value_field")  or self.data.get(f"{self.prefix}-sqlhub_value_field") or "").strip()
                lf  = (data.get("sqlhub_label_field")  or self.data.get(f"{self.prefix}-sqlhub_label_field") or "").strip()

                if cid in ("", None) or qid in ("", None) or not vf or not lf:
                    lj["options"] = {"source": "manual"}
                else:
                    try:  cid_cast = int(cid)
                    except Exception: cid_cast = cid
                    try:  qid_cast = int(qid)
                    except Exception: qid_cast = qid

                    lj["options"] = {
                        "source": "sqlhub",
                        "sqlhub": {
                            "connection_id": cid_cast,
                            "query_id": qid_cast,
                            "value_field": vf,
                            "label_field": lf,
                        },
                    }
            else:
                lj["options"] = {"source": "manual"}
        else:
            if "options" in lj:
                lj["options"] = {"source": "manual"}

        data["logica_json"] = lj

        # Validação de upload (se veio)
        vraw = self.data.get(f"{self.prefix}-valid_json") or self.cleaned_data.get("valid_json")
        if vraw:
            try:
                vcfg = json.loads(vraw)
                self.instance.validacao_json = vcfg
            except Exception:
                pass
        return data

    def save(self, commit: bool = True):
        instance: Campo = super().save(commit=False)
        instance.logica_json = self.cleaned_data.get("logica_json") or {}
        if commit:
            instance.save()
            self.save_m2m()
        return instance


CampoFormSetCreate = inlineformset_factory(
    Formulario, Campo, form=CampoForm, extra=1, can_delete=True
)
CampoFormSetBuilder = inlineformset_factory(
    Formulario, Campo, form=CampoForm, extra=0, can_delete=True
)
