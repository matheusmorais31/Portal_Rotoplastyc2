# rh/models.py
from django.db import models
from django.utils import timezone


class EntregaEPI(models.Model):
    # Opções de Status
    STATUS_PENDENTE = 'Pendente'
    STATUS_BAIXADO = 'Baixado'
    STATUS_CHOICES = [
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_BAIXADO, 'Baixado'),
    ]

    # ─────────── chaves / códigos ───────────
    unidade        = models.CharField(max_length=10)
    contrato       = models.IntegerField()
    epi            = models.CharField(max_length=30)
    codigo_estoque = models.CharField(max_length=30, blank=True, null=True)
    lote           = models.CharField(max_length=40, blank=True)

    # ─────────── datas / quantidade ─────────
    data_entrega        = models.DateField()
    data_devolucao      = models.DateField(null=True, blank=True)
    quantidade_entregue = models.PositiveIntegerField(default=0)

    # ─────────── info extra ────────────────
    colaborador   = models.CharField(max_length=120, blank=True, null=True)
    descricao_epi = models.CharField(max_length=120, blank=True, null=True)
    centro_custo  = models.CharField(max_length=100, blank=True, null=True)
    descricao_centro_custo = models.CharField(max_length=255, blank=True, null=True)

    # ─────────── Campos de Status e Baixa ERP (NOVOS) ───────────
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDENTE # Novo campo: status da baixa (Pendente por padrão)
    )
    sequencial_baixa_erp = models.CharField(
        max_length=50,
        blank=True,
        null=True # Novo campo: sequencial da baixa no ERP
    )
    data_baixa_erp = models.DateTimeField(
        blank=True,
        null=True # Novo campo: data e hora da baixa
    )

    # ─────────── controle ──────────────────
    inserido_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-data_entrega"]
        # Mantemos unique_together, mas se o sequencial_baixa_erp for único para uma entrega,
        # isso não impacta o unique_together principal que identifica a entrega em si.
        unique_together = ("unidade", "contrato", "epi", "lote", "data_entrega")

        verbose_name = 'rh'
        default_permissions = ()
        permissions = [
            ('delivery_epis', 'Entrega de EPIs'),

            
        ]




    def __str__(self) -> str:
        return f"{self.contrato} – {self.epi} ({self.data_entrega:%d/%m/%Y}) - {self.get_status_display()}"

    def marcar_como_baixado(self, sequencial: str):
        """Marca a entrega como baixada e registra o sequencial e a data."""
        self.status = self.STATUS_BAIXADO
        self.sequencial_baixa_erp = sequencial
        self.data_baixa_erp = timezone.now()
        self.save()

    def reverter_para_pendente(self):
        """Reverte o status para pendente e limpa os dados de baixa."""
        self.status = self.STATUS_PENDENTE
        self.sequencial_baixa_erp = None
        self.data_baixa_erp = None
        self.save()