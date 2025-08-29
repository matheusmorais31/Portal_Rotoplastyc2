from __future__ import annotations

from typing import Dict, Set
from datetime import timedelta

from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


# -----------------------------------------------------------------------------
# Categorias de arquivos (extensões permitidas por categoria)
# -----------------------------------------------------------------------------
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

    # Visibilidade / janela de validade
    publico       = models.BooleanField(_('Visível sem login?'), default=False)
    abre_em       = models.DateTimeField(_('Abre em'), null=True, blank=True)
    fecha_em      = models.DateTimeField(_('Fecha em'), null=True, blank=True)

    # Limites / tema / versão
    limite_resps  = models.PositiveIntegerField(_('Limite de respostas'), null=True, blank=True)
    tema_json     = models.JSONField(_('Tema'), default=dict, blank=True)
    versao        = models.PositiveIntegerField(default=1, editable=False)

    # Controle geral
    aceita_respostas = models.BooleanField(_('Aceitando respostas?'), default=True)

    # ====================== NOVAS CONFIGURAÇÕES (HOME POPUP) ======================
    aparece_home  = models.BooleanField(_('Aparece na home?'), default=False)

    coletar_nome  = models.BooleanField(_('Coletar o nome do usuário?'), default=False)

    # Intervalo para voltar a disparar na home (quando aparece_home=True)
    # None = sem controle (não reabre automaticamente); 00:00:00 = pode reaparecer na próxima visita
    repetir_cada  = models.DurationField(_('Repetir a cada'), null=True, blank=True)

    class AlvoChoices(models.TextChoices):
        ALL   = '100', _('100%')
        HALF  = '050', _('50%')
        MAN   = 'MAN', _('Selecionar usuários manualmente')

    # Quem verá o popup (somente quando aparece_home=True)
    alvo_resposta = models.CharField(
        _('Quem vai responder'),
        max_length=3, choices=AlvoChoices.choices, default=AlvoChoices.ALL, blank=True
    )
    alvo_usuarios = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='formularios_alvo',
        verbose_name=_('Usuários selecionados (manual)')
    )
    # ==================== /NOVAS CONFIGURAÇÕES (HOME POPUP) =====================

    criado_em     = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'formulário'
        verbose_name_plural = 'formulários'
        permissions = [
            ('pode_responder', 'Pode responder formulário'),
            ('pode_gerenciar', 'Pode gerenciar formulário'),
            ('listar_meus', 'Listar meus formulários'),
            ('criar_formulario', 'Criar formulário')
        ]

    def __str__(self) -> str:
        return self.titulo

    # ---------- Helpers de permissão ----------
    def can_user_view(self, user) -> bool:
        """Dono ou colaborador com pode_ver=True."""
        if not user or not user.is_authenticated:
            return False
        if self.dono_id == getattr(user, "id", None):
            return True
        return self.colaboradores.filter(usuario=user, pode_ver=True).exists()

    def can_user_edit(self, user) -> bool:
        """Dono ou colaborador com pode_editar=True."""
        if not user or not user.is_authenticated:
            return False
        if self.dono_id == getattr(user, "id", None):
            return True
        return self.colaboradores.filter(usuario=user, pode_editar=True).exists()

    # ---------- Helpers de exibição ----------
    def repetir_cada_display(self) -> str:
        """
        Retorna o intervalo em formato DD:HH:MM (dias:horas:minutos).
        Se None, retorna '00:00:00' apenas para preencher o campo de UI.
        """
        if not self.repetir_cada:
            return "00:00:00"
        total_min = int(self.repetir_cada.total_seconds() // 60)
        dias, resto = divmod(total_min, 24 * 60)
        horas, mins = divmod(resto, 60)
        return f"{dias:02d}:{horas:02d}:{mins:02d}"


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
    validacao_json = models.JSONField(_('Validação'), default=dict, blank=True)     # regras extras (arquivo etc.)
    logica_json    = models.JSONField(_('Lógica condicional'), default=dict, blank=True)
    ativo          = models.BooleanField(default=True)  # <<< NOVO: arquiva pergunta sem deletar

    class Meta:
        ordering = ['ordem']

    def __str__(self) -> str:
        return f'{self.ordem}. {self.rotulo}'

    @property
    def accept_string(self) -> str:
        """
        Gera a string adequada para o atributo HTML 'accept' do input de arquivo, com base
        em validacao_json → { tipos_livres: bool, categorias: [str] }.
        """
        if self.tipo != self.TipoCampo.ARQUIVO:
            return ""
        cfg = self.validacao_json or {}
        if cfg.get('tipos_livres', True):
            return ""  # aceita qualquer extensão
        allowed_exts: Set[str] = set()
        for cat in cfg.get('categorias', []):
            allowed_exts.update(FILE_CATS.get(cat, set()))
        # Ex.: ".pdf,.docx,.png"
        return ",".join(f".{ext}" for ext in sorted(allowed_exts))


class OpcaoCampo(models.Model):
    campo = models.ForeignKey(Campo, on_delete=models.CASCADE, related_name='opcoes')
    texto = models.CharField(max_length=255)
    valor = models.CharField(max_length=255, blank=True)  # se 'valor' ≠ texto

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
    versao_form   = models.PositiveIntegerField()  # snapshot

    # NOVO: armazena nome digitado quando coletar_nome=True para anônimos
    nome_coletado = models.CharField(_('Nome (informado)'), max_length=255, blank=True)

    class Meta:
        ordering = ['-enviado_em']


def upload_para(instancia: "ValorResposta", nome: str) -> str:
    """Pasta de upload: formularios/<campo_id>/<resposta_id>/<nome_arquivo>"""
    return f'formularios/{instancia.campo.id}/{instancia.resposta.id}/{nome}'


class ValorResposta(models.Model):
    resposta      = models.ForeignKey(Resposta, on_delete=models.CASCADE, related_name='valores')
    campo         = models.ForeignKey(Campo, on_delete=models.CASCADE)
    valor_texto   = models.TextField(blank=True)
    valor_arquivo = models.FileField(upload_to=upload_para, blank=True, null=True)

    def __str__(self) -> str:
        return f'Resposta {self.resposta_id} – Campo {self.campo_id}'
