from __future__ import annotations

from typing import Dict, Set
from datetime import timedelta
from pathlib import Path
import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import hashlib

FILE_CATS: Dict[str, Set[str]] = {
    "documento":    {"doc", "docx", "odt", "rtf", "txt"},
    "apresentação": {"ppt", "pptx", "odp"},
    "planilha":     {"xls", "xlsx", "ods", "csv"},
    "desenho":      {"dwg", "dxf", "svg"},
    "pdf":          {"pdf"},
    "imagem":       {"png", "jpg", "jpeg", "gif", "webp"},
    "vídeo":        {"mp4", "mov", "mkv", "avi"},
    "áudio":        {"mp3", "wav", "ogg", "aac"},
}


class Formulario(models.Model):
    titulo        = models.CharField(_('Título'), max_length=200)
    descricao     = models.TextField(_('Descrição'), blank=True)
    dono          = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='formularios'
    )

    publico       = models.BooleanField(_('Visível sem login?'), default=False)
    abre_em       = models.DateTimeField(_('Abre em'), null=True, blank=True)
    fecha_em      = models.DateTimeField(_('Fecha em'), null=True, blank=True)

    limite_resps  = models.PositiveIntegerField(_('Limite de respostas'), null=True, blank=True)
    tema_json     = models.JSONField(_('Tema'), default=dict, blank=True)
    versao        = models.PositiveIntegerField(default=1, editable=False)

    aceita_respostas = models.BooleanField(_('Aceitando respostas?'), default=True)

    # Home popup
    aparece_home  = models.BooleanField(_('Aparece na home?'), default=False)
    coletar_nome  = models.BooleanField(_('Coletar o nome do usuário?'), default=False)
    repetir_cada  = models.DurationField(_('Repetir a cada'), null=True, blank=True)

    class AlvoChoices(models.TextChoices):
        ALL   = '100', _('100%')
        HALF  = '050', _('50%')
        MAN   = 'MAN', _('Selecionar usuários manualmente')

    alvo_resposta = models.CharField(
        _('Quem vai responder'),
        max_length=3, choices=AlvoChoices.choices, default=AlvoChoices.ALL, blank=True
    )
    alvo_usuarios = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='formularios_alvo',
        verbose_name=_('Usuários selecionados (manual)')
    )

    criado_em     = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'formulário'
        verbose_name_plural = 'formulários'
        permissions = [
            
            ('pode_gerenciar', 'Pode gerenciar formulário'),
            ('listar_meus', 'Listar meus formulários'),
            ('pode_criar', 'Criar formulário'),
            
            ('pode_excluir_formulario', 'Pode excluir formulário'),
            ('pode_excluir_respostas', 'Pode excluir respostas'),
            
            
        ]

    def __str__(self) -> str:
        return self.titulo

    def can_user_view(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self.dono_id == getattr(user, "id", None):
            return True
        return self.colaboradores.filter(usuario=user, pode_ver=True).exists()

    def can_user_edit(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self.dono_id == getattr(user, "id", None):
            return True
        return self.colaboradores.filter(usuario=user, pode_editar=True).exists()

    def repetir_cada_display(self) -> str:
        if not self.repetir_cada:
            return "00:00:00"
        total_min = int(self.repetir_cada.total_seconds() // 60)
        dias, resto = divmod(total_min, 24 * 60)
        horas, mins = divmod(resto, 60)
        return f"{dias:02d}:{horas:02d}:{mins:02d}"

    def _passes_targeting(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self.alvo_resposta == self.AlvoChoices.ALL:
            return True
        if self.alvo_resposta == self.AlvoChoices.MAN:
            return self.alvo_usuarios.filter(pk=user.pk).exists()
        if self.alvo_resposta == self.AlvoChoices.HALF:
            seed = f'{self.pk}:{user.pk}'.encode('utf-8')
            bucket = int(hashlib.sha256(seed).hexdigest(), 16) % 100
            return bucket < 50
        return True

    def should_show_on_home(self, user) -> bool:
        now = timezone.now()
        if not self.aparece_home:
            return False
        if not self.aceita_respostas:
            return False
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if not self._passes_targeting(user):
            return False

        if self.abre_em and now < self.abre_em:
            return False
        if self.fecha_em and now > self.fecha_em:
            return False
        if self.limite_resps and self.respostas.count() >= self.limite_resps:
            return False

        st = FormularioUserState.objects.filter(
            formulario=self, usuario=user
        ).only('last_answered_at').first()

        if not st or not st.last_answered_at:
            return True

        td = self.repetir_cada
        if not td or td.total_seconds() == 0:
            return False
        return (st.last_answered_at + td) <= now


class Campo(models.Model):
    class TipoCampo(models.TextChoices):
        TEXTO_CURTO = 'texto_curto', _('Texto curto')
        PARAGRAFO   = 'paragrafo',   _('Parágrafo')
        MULTIPLA    = 'multipla',    _('Múltipla escolha')
        CHECKBOX    = 'checkbox',    _('Caixas de seleção')
        LISTA       = 'lista',       _('Lista suspensa')
        ESCALA      = 'escala',      _('Escala 1-10')
        DATA        = 'data',        _('Data')
        HORA        = 'hora',        _('Hora')
        ARQUIVO     = 'arquivo',     _('Upload de arquivo')

    formulario     = models.ForeignKey(Formulario, on_delete=models.CASCADE, related_name='campos')
    ordem          = models.PositiveIntegerField(_('Ordem'))
    tipo           = models.CharField(_('Tipo'), max_length=20, choices=TipoCampo.choices)
    rotulo         = models.CharField(_('Rótulo'), max_length=255)
    ajuda          = models.CharField(_('Texto de ajuda'), max_length=255, blank=True)
    obrigatorio    = models.BooleanField(default=False)
    validacao_json = models.JSONField(_('Validação'), default=dict, blank=True)
    logica_json    = models.JSONField(_('Lógica condicional'), default=dict, blank=True)
    ativo          = models.BooleanField(default=True)

    class Meta:
        ordering = ['ordem']

    def __str__(self) -> str:
        return f'{self.ordem}. {self.rotulo}'

    @property
    def accept_string(self) -> str:
        if self.tipo != self.TipoCampo.ARQUIVO:
            return ""
        cfg = self.validacao_json or {}
        if cfg.get('tipos_livres', True):
            return ""
        allowed_exts: Set[str] = set()
        for cat in cfg.get('categorias', []):
            allowed_exts.update(FILE_CATS.get(cat, set()))
        return ",".join(f".{ext}" for ext in sorted(allowed_exts))

    # ======= Helpers usados no template/responder para SQLHub =======
    @property
    def origem_opcoes(self) -> str:
        try:
            return (self.logica_json or {}).get('options', {}).get('source', 'manual')
        except Exception:
            return 'manual'

    def _sqlhub_dict(self) -> dict:
        opts = (self.logica_json or {}).get('options', {})
        if opts.get('source') != 'sqlhub':
            return {}
        return opts.get('sqlhub', {}) or {}

    @property
    def sqlhub_connection_id(self):
        return self._sqlhub_dict().get('connection_id')

    @property
    def sqlhub_query_id(self):
        return self._sqlhub_dict().get('query_id')

    @property
    def sqlhub_value_field(self) -> str:
        return self._sqlhub_dict().get('value_field') or ''

    @property
    def sqlhub_label_field(self) -> str:
        return self._sqlhub_dict().get('label_field') or ''


class OpcaoCampo(models.Model):
    campo = models.ForeignKey(Campo, on_delete=models.CASCADE, related_name='opcoes')
    texto = models.CharField(max_length=255)
    valor = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'Opção'
        verbose_name_plural = 'Opções'

    def __str__(self) -> str:
        return self.texto


class Colaborador(models.Model):
    formulario  = models.ForeignKey(Formulario, on_delete=models.CASCADE, related_name='colaboradores')
    usuario     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    pode_editar = models.BooleanField(default=True)
    pode_ver    = models.BooleanField(default=True)

    class Meta:
        unique_together = ('formulario', 'usuario')
        verbose_name = 'Colaborador'
        verbose_name_plural = 'Colaboradores'


class Resposta(models.Model):
    formulario  = models.ForeignKey(Formulario, on_delete=models.CASCADE, related_name='respostas')
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='respostas_formularios'
    )
    ip            = models.GenericIPAddressField(null=True, blank=True)
    enviado_em    = models.DateTimeField(auto_now_add=True)
    rascunho      = models.BooleanField(default=False)
    versao_form   = models.PositiveIntegerField()
    nome_coletado = models.CharField(_('Nome (informado)'), max_length=255, blank=True)

    class Meta:
        ordering = ['-enviado_em']


class FormularioUserState(models.Model):
    formulario       = models.ForeignKey(Formulario, on_delete=models.CASCADE, related_name='user_states')
    usuario          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='form_states')
    last_answered_at = models.DateTimeField(null=True, blank=True)
    answered_count   = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('formulario', 'usuario')
        indexes = [
            models.Index(fields=['usuario', 'formulario']),
        ]

    def __str__(self) -> str:
        return f'{self.usuario_id} ⇢ form {self.formulario_id} ({self.answered_count} respostas)'


def upload_para(instancia: "ValorResposta", nome: str) -> str:
    # pasta única para todos os uploads do app
    base_dir = "formularios/uploads"

    # preserva a extensão original, em minúsculas
    ext = Path(nome).suffix.lower()  # ex: ".pdf", ".jpg" (ou "" se não tiver)

    # nome único: timestamp + uuid (evita colisões)
    uniq = f"{timezone.now():%Y%m%d%H%M%S%f}-{uuid.uuid4().hex}"

    return f"{base_dir}/{uniq}{ext}"



class ValorResposta(models.Model):
    resposta      = models.ForeignKey(Resposta, on_delete=models.CASCADE, related_name='valores')
    campo         = models.ForeignKey(Campo, on_delete=models.CASCADE)
    valor_texto   = models.TextField(blank=True)
    valor_arquivo = models.FileField(upload_to=upload_para, blank=True, null=True)

    def __str__(self) -> str:
        return f'Resposta {self.resposta_id} – Campo {self.campo_id}'
