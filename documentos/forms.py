from django import forms
from .models import Categoria, Documento
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
import logging
import os

# Se preferir, altere para logger "documentos"
logger = logging.getLogger('documentos')

User = get_user_model()

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome', 'bloqueada']
        labels = {
            'nome': 'Nome da Categoria',
            'bloqueada': 'Bloquear Downloads e Impressões',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'bloqueada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class DocumentoForm(forms.ModelForm):
    aprovador1 = forms.ModelChoiceField(
        queryset=User.objects.none(),  # Inicialmente vazio, será definido no __init__
        label='Aprovador',
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        empty_label="Selecione um aprovador"
    )

    class Meta:
        model = Documento
        fields = ['nome', 'revisao', 'categoria', 'aprovador1', 'documento']
        labels = {
            'nome': 'Nome do Documento',
            'revisao': 'Revisão',
            'categoria': 'Categoria',
            'aprovador1': 'Aprovador',
            'documento': 'Anexar Documento',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'revisao': forms.Select(attrs={'class': 'form-control select2'}),
            'categoria': forms.Select(attrs={'class': 'form-control select2'}),
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt,.xls,.xlsx,.ods'
            }),
        }

    def __init__(self, *args, **kwargs):
        super(DocumentoForm, self).__init__(*args, **kwargs)
        self.fields['aprovador1'].queryset = self._set_aprovadores()
        self.fields['aprovador1'].label_from_instance = self.get_aprovador_label

    def _set_aprovadores(self):
        content_type = ContentType.objects.get_for_model(Documento)
        try:
            permission = Permission.objects.get(content_type=content_type, codename='can_approve')
            aprovadores = User.objects.filter(
                Q(user_permissions=permission) | Q(groups__permissions=permission),
                is_active=True
            ).distinct()
            return aprovadores
        except Permission.DoesNotExist:
            logger.warning("Permissão 'can_approve' não encontrada.")
            return User.objects.none()

    def get_aprovador_label(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return f"{full_name} ({obj.username})" if full_name else obj.username

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário anexar o documento.')
        ext = os.path.splitext(documento.name)[1].lower()
        if ext in ['.doc', '.docx', '.odt']:
            valid_extensions = ['.doc', '.docx', '.odt']
        elif ext in ['.xls', '.xlsx', '.ods']:
            valid_extensions = ['.xls', '.xlsx', '.ods']
        else:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')
        if ext not in valid_extensions:
            raise ValidationError('Formato de arquivo inválido.')
        return documento

def clean(self):
    cleaned_data = super().clean()
    nome = cleaned_data.get('nome')

    # Só bloqueia se já existir OUTRO documento “raiz” com o mesmo nome
    duplicado = Documento.objects.filter(
        nome=nome,
        documento_original__isnull=True  # raiz somente
    ).exclude(status='reprovado')

    if duplicado.exists():
        raise ValidationError(
            'Já existe um documento inicial aprovado ou pendente com este nome.'
        )
    return cleaned_data


class AnaliseDocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['documento']
        labels = {
            'documento': 'Upload do Documento Revisado',
        }
        widgets = {
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt,.xls,.xlsx,.ods'
            }),
        }

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário fazer o upload do documento revisado.')
        ext = os.path.splitext(documento.name)[1].lower()
        if ext in ['.doc', '.docx', '.odt']:
            valid_extensions = ['.doc', '.docx', '.odt']
        elif ext in ['.xls', '.xlsx', '.ods']:
            valid_extensions = ['.xls', '.xlsx', '.ods']
        else:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')
        if ext not in valid_extensions:
            raise ValidationError('Formato de arquivo inválido.')
        return documento

class NovaRevisaoForm(forms.ModelForm):
    """
    Formulário usado na view nova_revisao.
    • Exibe **nome** (editável), revisao, aprovador, documento.
    • Pré-preenche revisão +1 e nome atual.
    • Impede duplicidade de revisão dentro do mesmo documento (código).
    """

    aprovador1 = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Aprovador",
        widget=forms.Select(attrs={"class": "form-control select2"}),
        empty_label="Selecione um aprovador",
    )

    class Meta:
        model = Documento
        fields = ["nome", "revisao", "aprovador1", "documento"]
        labels = {
            "nome": "Nome da Revisão",
            "revisao": "Revisão",
            "aprovador1": "Aprovador",
            "documento": "Anexar Documento",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "revisao": forms.Select(attrs={"class": "form-control select2"}),
            "documento": forms.FileInput(
                attrs={
                    "class": "form-control-file",
                    "accept": ".doc,.docx,.odt,.xls,.xlsx,.ods",
                }
            ),
        }

    # -------------------- INIT --------------------
    def __init__(self, *args, **kwargs):
        self.documento_atual = kwargs.pop("documento_atual", None)
        super().__init__(*args, **kwargs)

        # revisão sugerida = atual + 1
        if self.documento_atual:
            proxima_revisao = self.documento_atual.revisao + 1
            self.fields["revisao"].choices = [(proxima_revisao, f"{proxima_revisao:02d}")]
            self.fields["nome"].initial = self.documento_atual.nome
        else:
            self.fields["revisao"].choices = [(1, "01")]

        # lista de aprovadores
        self.fields["aprovador1"].queryset = self._set_aprovadores()
        self.fields["aprovador1"].label_from_instance = self._get_aprovador_label

    def _set_aprovadores(self):
        content_type = ContentType.objects.get_for_model(Documento)
        try:
            perm = Permission.objects.get(content_type=content_type, codename="can_approve")
            return (
                User.objects.filter(Q(user_permissions=perm) | Q(groups__permissions=perm), is_active=True)
                .distinct()
            )
        except Permission.DoesNotExist:
            logger.warning("Permissão 'can_approve' não encontrada.")
            return User.objects.none()

    @staticmethod
    def _get_aprovador_label(user):
        fn = f"{user.first_name} {user.last_name}".strip()
        return f"{fn} ({user.username})" if fn else user.username

    # -------------------- VALIDATIONS --------------------
    def clean_documento(self):
        doc = self.cleaned_data.get("documento")
        if not doc:
            raise ValidationError("É necessário anexar o documento.")
        ext = os.path.splitext(doc.name)[1].lower()
        if ext not in [".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods"]:
            raise ValidationError(
                "Formato inválido. Utilize .doc, .docx, .odt, .xls, .xlsx ou .ods."
            )
        return doc

def clean(self):
    cleaned = super().clean()
    revisao = cleaned.get("revisao")
    nome    = cleaned.get("nome")

    if self.documento_atual:
        if revisao <= self.documento_atual.revisao:
            raise ValidationError("A revisão deve ser maior que a atual.")

        duplicada = (Documento.objects
                     .filter(codigo=self.documento_atual.codigo, revisao=revisao)
                     .exclude(status='reprovado'))     # ignora reprovados

        if duplicada.exists():
            raise ValidationError("Já existe uma revisão com esse número.")

    if not nome:
        raise ValidationError("O nome não pode ficar em branco.")
    return cleaned
