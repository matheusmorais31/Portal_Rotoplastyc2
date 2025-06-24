# ia/models.py
from django.db import models
from django.conf import settings
from django.db.models import Sum, Count, F # F não está sendo usado, mas pode ser útil no futuro
from django.utils import timezone
from decimal import Decimal

class Chat(models.Model):
    """
    Representa uma conversa única de um usuário com a IA.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, # Se o usuário for excluído, suas conversas também são
        related_name='chats',     # Permite acessar user.chats
        verbose_name="Usuário"
    )
    title = models.CharField(
        max_length=255,
        default='Nova Conversa',
        verbose_name="Título"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )
    active_spreadsheet_attachment_id = models.PositiveIntegerField(
        null=True, blank=True
    )
    
    active_spreadsheet_columns_json = models.TextField(
        null=True, blank=True
    )

    active_spreadsheet_original_columns_json = models.TextField(
        null=True, blank=True
    )


    assistant_thread_id = models.CharField(
        max_length=120, null=True, blank=True
    )


    

    class Meta:
        verbose_name = "Conversa IA"
        verbose_name_plural = "Conversas IA"
        ordering = ['-updated_at'] # Ordena da mais recente para a mais antiga por padrão

    def __str__(self):
        # Retorna título ou um identificador padrão se o título for o default
        display_title = self.title if self.title and self.title != 'Nova Conversa' else f"Conversa {self.id}"
        return f"{display_title} (Usuário: {self.user.username})"

    def get_message_count(self):
        """Retorna a contagem de mensagens nesta conversa."""
        return self.messages.count()


class ChatMessage(models.Model):
    """
    Representa uma única mensagem dentro de uma conversa (Chat).
    Pode ser do usuário ('user') ou da inteligência artificial ('ai').
    """
    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE, # Se a conversa for excluída, as mensagens também são
        related_name='messages',  # Permite acessar chat.messages
        verbose_name="Conversa"
    )
    sender = models.CharField(
        max_length=50,
        choices=[('user', 'Usuário'), ('ai', 'IA')], # Limita as opções
        verbose_name="Remetente"
    )
    text = models.TextField(
        verbose_name="Texto da Mensagem"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Enviado em"
    )

    metadata = models.JSONField(
        null=True, blank=True
    )

    class Meta:
        verbose_name = "Mensagem IA"
        verbose_name_plural = "Mensagens IA"
        ordering = ['created_at'] # Ordena da mais antiga para a mais recente

    def __str__(self):
        # Mostra os primeiros 60 caracteres do texto para identificação
        preview = (self.text[:60] + '...') if len(self.text) > 60 else self.text
        return f"Msg {self.id} ({self.get_sender_display()}) em Chat {self.chat.id}: \"{preview}\""


class ChatAttachment(models.Model):
    """
    Representa um arquivo anexado a uma mensagem específica dentro de uma conversa.
    Usado principalmente para imagens enviadas pelo usuário para a IA.
    """
    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE, # Se a conversa for excluída, os anexos também são
        related_name='chat_attachments', # Nome distinto para evitar conflito com ChatMessage.attachments
        verbose_name="Conversa (Anexo)" # Nome um pouco diferente para clareza no admin
    )
    # Liga o anexo à mensagem do usuário que o enviou
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE, # Se a mensagem for excluída, o anexo também é
        related_name='attachments', # Permite acessar message.attachments
        null=True, # Pode ser nulo temporariamente antes de associar
        blank=True, # Permite ser nulo no admin/forms
        verbose_name="Mensagem Associada"
    )
    file = models.FileField(
        upload_to='chat_attachments/', # Diretório dentro de MEDIA_ROOT
        verbose_name="Arquivo"
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Enviado em"
    )

    metadata = models.JSONField(           
        null=True,
        blank=True,
        help_text="Info auxiliar (ex.: {'oa_file_id': 'file_abc123'})"
    )

  

    class Meta:
        verbose_name = "Anexo IA"
        verbose_name_plural = "Anexos IA"
        ordering = ['-uploaded_at']

    def __str__(self):
        filename = self.file.name.split('/')[-1] # Pega apenas o nome do arquivo
        if self.message_id:
            return f"Anexo '{filename}' (Msg: {self.message_id}, Chat: {self.chat.id})"
        else:
            # Caso raro onde o anexo pode não estar ligado a uma mensagem (upload legado?)
            return f"Anexo '{filename}' (Chat: {self.chat.id}, Sem Mensagem)"

    def get_filename(self):
        """Retorna apenas o nome do arquivo, sem o caminho."""
        try:
            return self.file.name.split('/')[-1]
        except:
            return self.file.name # Fallback


class ApiUsageLog(models.Model):
    """
    Registra o uso da API generativa para fins de monitoramento de custos.
    Cada registro corresponde a uma resposta bem-sucedida da IA.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Mantém o log mesmo se o usuário for excluído
        null=True,                 # Permite log de sistema (sem usuário)
        blank=True,                # Permite ser nulo no admin/forms
        related_name='api_usage_logs',
        verbose_name="Usuário"
    )
    model_name = models.CharField(
        max_length=100,
        db_index=True,             # Indexa para filtragem mais rápida
        verbose_name="Modelo Utilizado"
    )
    # Link para a mensagem de resposta da IA que gerou este custo
    ai_message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL, # Mantém o log se a mensagem for excluída
        null=True,
        blank=True,
        related_name='usage_log_entry', # Permite message.usage_log_entry (se for OneToOne seria melhor)
                                       # Vamos manter ForeignKey por simplicidade agora
        verbose_name="Mensagem IA Associada"
    )
    input_tokens = models.PositiveIntegerField(
        default=0,
        help_text="Tokens enviados para a API (prompt + histórico).",
        verbose_name="Tokens de Entrada"
    )
    output_tokens = models.PositiveIntegerField(
        default=0,
        help_text="Tokens recebidos da API (resposta gerada).",
        verbose_name="Tokens de Saída"
    )
    image_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Número de imagens enviadas na requisição.",
        verbose_name="Qtd. Imagens"
    )
    # Custo base em USD, conforme precificação da API
    estimated_cost = models.DecimalField(
        max_digits=10,          # Ex: 9999.999999 (ajuste conforme necessário)
        decimal_places=6,       # Precisão comum para custos por token/milhão
        default=Decimal('0.0'), # Usa Decimal no default
        help_text="Custo estimado (USD) desta chamada, baseado nos tokens/imagens.",
        verbose_name="Custo Estimado (USD)"
    )
    # Custo convertido para BRL (ou outra moeda local)
    estimated_cost_brl = models.DecimalField(
        max_digits=12,          # Permite valores maiores em BRL (Ex: 999999.999999)
        decimal_places=6,       # Manter precisão ou reduzir (e.g., 4)
        default=Decimal('0.0'), # Usa Decimal no default
        help_text="Custo estimado (BRL) convertido a partir do USD.",
        verbose_name="Custo Estimado (BRL)"
    )
    timestamp = models.DateTimeField(
        default=timezone.now,     # Usa timezone.now para default ciente do timezone
        db_index=True,            # Indexa para filtragem por data
        verbose_name="Timestamp da Requisição"
    )

    class Meta:
        ordering = ['-timestamp'] # Ordena do mais recente para o mais antigo por padrão
        permissions = [
            # Permissão para ver a página de monitoramento com dados de todos
            ('view_all_api_costs', 'Pode visualizar custos de API de todos os usuários'),
            ('chat_pag', 'Chat IA'),
            ('cost_monitor', 'Custos IA'),
            ('model_2.5_pro', 'Modelo mais caro Gemini 2.5 Pro'),
            ('model_1.5_pro', 'Modelo  Gemini 1.5 Pro'),
            ('rotoplastyc_ia', 'Modelo  Rotoplastyc IA para documentos'),
            ('gpt_4o_mini', 'Modelo GPT-4o Mini'),
            ('gpt_4o', 'Modelo GPT-4o'),
            
        ]
        verbose_name = "Log de Uso da API"
        verbose_name_plural = "Logs de Uso da API"

    def __str__(self):
        user_str = self.user.username if self.user else "Sistema"
        # Formata custos para exibição mais legível
        cost_usd_str = f"{self.estimated_cost:.6f}".rstrip('0').rstrip('.') if self.estimated_cost else "0"
        cost_brl_str = f"{self.estimated_cost_brl:.6f}".rstrip('0').rstrip('.') if self.estimated_cost_brl else "0"
        return (f"Log {self.id} - {self.timestamp.strftime('%d/%m/%y %H:%M')} - {user_str} - "
                f"{self.model_name} - ${cost_usd_str} / R${cost_brl_str}")

    @staticmethod
    def get_cost_summary(user=None, start_date=None, end_date=None, model_name=None):
        """
        Calcula o custo total (USD e BRL) e agrupa por usuário e modelo.
        Filtra pelos argumentos fornecidos.
        """
        filters = {}
        if user:
            filters['user'] = user
        if start_date:
            filters['timestamp__gte'] = start_date
        if end_date:
            try:
                filters['timestamp__lt'] = end_date + timezone.timedelta(days=1)
            except TypeError:
                 filters['timestamp__lte'] = end_date
        if model_name:
             filters['model_name'] = model_name

        # Agregações
        base_query = ApiUsageLog.objects.filter(**filters)

        total_cost_agg = base_query.aggregate(
            total_usd=Sum('estimated_cost'), total_brl=Sum('estimated_cost_brl')
        )
        total_cost_usd = total_cost_agg.get('total_usd') or Decimal(0)
        total_cost_brl = total_cost_agg.get('total_brl') or Decimal(0)

        cost_by_user = list(base_query.values('user__username').annotate(
            total_cost_usd=Sum('estimated_cost'), total_cost_brl=Sum('estimated_cost_brl'),
            total_requests=Count('id')).order_by('-total_cost_brl'))

        cost_by_model = list(base_query.values('model_name').annotate(
            total_cost_usd=Sum('estimated_cost'), total_cost_brl=Sum('estimated_cost_brl'),
            total_requests=Count('id')).order_by('-total_cost_brl'))

        cost_by_user_model = list(base_query.values('user__username', 'model_name').annotate(
            total_cost_usd=Sum('estimated_cost'), total_cost_brl=Sum('estimated_cost_brl'),
            total_requests=Count('id'), total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'), total_images=Sum('image_count')
        ).order_by('user__username', '-total_cost_brl'))

        return {
            'total_cost_usd': total_cost_usd,
            'total_cost_brl': total_cost_brl,
            'cost_by_user': cost_by_user,
            'cost_by_model': cost_by_model,
            'cost_by_user_model': cost_by_user_model,
            'filters_applied': {'user': user, 'start_date': start_date, 'end_date': end_date, 'model_name': model_name}
        }