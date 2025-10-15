# altforce_sync/models.py
from django.db import models


class ApiPedido(models.Model):
    """
    Tabela física: fApiPedidos
    Guarda somente os campos requeridos do /orders.
    Obs.: mantemos um ID interno auto (pk) e um altforce_id único.
    """
    altforce_id = models.CharField("ID AltForce", max_length=64, unique=True, db_index=True)

    STATUS_CHOICES = [
        ("request", "Registrado"),
        ("inProgress", "Em Progresso"),
        ("concluded", "Concluído"),
        ("canceled", "Cancelado"),
    ]
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, db_index=True)

    date = models.DateTimeField("Data do pedido", null=True, blank=True, db_index=True)

    user_external_id    = models.CharField("User External ID", max_length=64,  null=True, blank=True)
    buyer_name          = models.CharField("Comprador (nome)", max_length=255, null=True, blank=True)
    freight_name        = models.CharField("Frete (nome)", max_length=255, null=True, blank=True)
    payment_method_name = models.CharField("Método de Pagamento (nome)", max_length=255, null=True, blank=True)
    payment_term_name   = models.CharField("Prazo de Pagamento (nome)", max_length=255, null=True, blank=True)
    price_list_name     = models.CharField("Lista de Preço (nome)", max_length=255, null=True, blank=True)

    total_price     = models.DecimalField("Total",    max_digits=14, decimal_places=2, null=True, blank=True)
    sub_total_price = models.DecimalField("Subtotal", max_digits=14, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "fApiPedidos"
        indexes = [
            models.Index(fields=["status", "date"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • {self.status}"


class ApiPedidoTecnicon(models.Model):
    """
    Tabela física: dApiPedidosTecnicon
    Armazena o número TECNICON extraído de steps[] quando step.name == 'Número do pedido TECNICON'.
    """
    pedido = models.OneToOneField(
        "altforce_sync.ApiPedido",
        on_delete=models.CASCADE,
        related_name="tecnicon",
    )

    # espelhamos o ID do pedido no AltForce para debug/auditoria
    altforce_id = models.CharField("ID AltForce", max_length=64, unique=True, db_index=True)

    step_id   = models.CharField("Step ID", max_length=64, null=True, blank=True)
    step_name = models.CharField("Step name", max_length=255)  # deve ser 'Número do pedido TECNICON'
    content   = models.CharField("Content", max_length=255, null=True, blank=True)  # ex.: "45353"

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiPedidosTecnicon"
        indexes = [
            models.Index(fields=["step_name"]),
            models.Index(fields=["content"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • TECNICON={self.content or '-'}"


class ApiPedidoOrcamento(models.Model):
    """
    Tabela física: dApiPedidosOrcamento
    Relaciona um pedido AltForce a um budget_id (1:N).
    """
    pedido = models.ForeignKey(
        "altforce_sync.ApiPedido",
        on_delete=models.CASCADE,
        related_name="orcamentos",
    )

    # espelhamos o ID do pedido no AltForce para consultas rápidas
    altforce_id = models.CharField("ID AltForce", max_length=64, db_index=True)

    # ID do orçamento (vem do campo budgets_ids do /orders)
    budget_id = models.CharField("Budget ID", max_length=64, db_index=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiPedidosOrcamento"
        constraints = [
            models.UniqueConstraint(
                fields=["pedido", "budget_id"],
                name="uq_dapipedidosorcamento_pedido_budget",
            )
        ]
        indexes = [
            models.Index(fields=["altforce_id", "budget_id"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • budget={self.budget_id}"


class ApiPedidoProduto(models.Model):
    """
    Tabela física: dApiPedidosProdutos
    Uma linha por produto do pedido no AltForce (/orders.products[]).
    """
    pedido = models.ForeignKey(
        "altforce_sync.ApiPedido",
        on_delete=models.CASCADE,
        related_name="produtos",
    )

    # espelho do ID do pedido no AltForce para consultas rápidas
    altforce_id = models.CharField("ID AltForce", max_length=64, db_index=True)

    # products[].id do payload
    product_id = models.CharField("Product ID", max_length=64, db_index=True)

    name = models.CharField("Nome do produto", max_length=255, null=True, blank=True)
    quantity = models.DecimalField("Quantidade", max_digits=14, decimal_places=3, null=True, blank=True)
    total_price = models.DecimalField("Total da linha", max_digits=14, decimal_places=2, null=True, blank=True)
    total_price_for_order = models.DecimalField("Total p/ pedido", max_digits=14, decimal_places=2, null=True, blank=True)
    price_liquid = models.DecimalField("Preço líquido", max_digits=14, decimal_places=2, null=True, blank=True)
    price_with_optionals = models.DecimalField("Preço c/ opcionais", max_digits=14, decimal_places=2, null=True, blank=True)
    mask = models.CharField("Máscara", max_length=255, null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiPedidosProdutos"
        constraints = [
            models.UniqueConstraint(
                fields=["pedido", "product_id"],
                name="uq_dapipedidosprodutos_pedido_product",
            )
        ]
        indexes = [
            models.Index(fields=["altforce_id", "product_id"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • prod={self.product_id} • {self.name or '-'}"


class ApiOrcamento(models.Model):
    """
    Tabela física: fApiOrcamentos
    Guarda campos do endpoint /budgets.
    """
    altforce_id = models.CharField("ID Orçamento (AltForce)", max_length=64, unique=True, db_index=True)

    date = models.DateTimeField("Data do orçamento", null=True, blank=True, db_index=True)

    # user.* (services garantem usar somente user.external_id)
    user_external_id = models.CharField("User External ID", max_length=64, null=True, blank=True)
    user_name        = models.CharField("User Name", max_length=255, null=True, blank=True)
    user_city_name   = models.CharField("Cidade (user.address.city.name)", max_length=255, null=True, blank=True)
    user_state_name  = models.CharField("Estado (user.address.state.name)", max_length=255, null=True, blank=True)
    user_country_name= models.CharField("País (user.address.country.name)", max_length=255, null=True, blank=True)

    # buyer.*
    buyer_id    = models.CharField("Buyer ID", max_length=64, null=True, blank=True, db_index=True)
    buyer_name  = models.CharField("Buyer Name", max_length=255, null=True, blank=True)
    buyer_email = models.CharField("Buyer Email", max_length=255, null=True, blank=True)
    buyer_phone = models.CharField("Buyer Phone", max_length=64,  null=True, blank=True)

    # valores
    total_price     = models.DecimalField("Total",    max_digits=14, decimal_places=2, null=True, blank=True)
    sub_total_price = models.DecimalField("Subtotal", max_digits=14, decimal_places=2, null=True, blank=True)

    # freight
    freight_name = models.CharField("Frete (nome)", max_length=255, null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "fApiOrcamentos"
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["buyer_id"]),
            models.Index(fields=["user_external_id"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • {self.user_name or '-'}"


class ApiOrcamentoProduto(models.Model):
    """
    Tabela física: dApiOrcamentosProduto
    Uma linha por produto dentro de um orçamento (/budgets.products[]).

    Campos pedidos:
      - id (product_id)
      - products/name (name)
      - products/quantity (quantity)
      - products/totalPrice (total_price)
    """
    orcamento = models.ForeignKey(
        "altforce_sync.ApiOrcamento",
        on_delete=models.CASCADE,
        related_name="produtos",
    )

    # espelho do ID do orçamento no AltForce para consultas rápidas
    altforce_id = models.CharField("ID Orçamento (AltForce)", max_length=64, db_index=True)

    product_id  = models.CharField("Product ID", max_length=64, db_index=True)
    name        = models.CharField("Nome do produto", max_length=255, null=True, blank=True)
    quantity    = models.DecimalField("Quantidade", max_digits=14, decimal_places=3, null=True, blank=True)
    total_price = models.DecimalField("Total da linha", max_digits=14, decimal_places=2, null=True, blank=True)

    created_at  = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at  = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiOrcamentosProduto"
        ordering = ["id"]  # ordenar por id ASC
        constraints = [
            models.UniqueConstraint(
                fields=["orcamento", "product_id"],
                name="uq_dapiorcamentosproduto_orcamento_product",
            )
        ]
        indexes = [
            models.Index(fields=["altforce_id", "product_id"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • prod={self.product_id} • {self.name or '-'}"


class ApiOrcamentoOpcional(models.Model):
    """
    Tabela física: dApiOrcamentosOpcionais
    Guarda, por orçamento e por produto, o conteúdo de products[].optionalsSelected.
    Agora inclui item_id (FK para dApiOrcamentosProduto).
    """
    orcamento = models.ForeignKey(
        "altforce_sync.ApiOrcamento",
        on_delete=models.CASCADE,
        related_name="opcionais",
    )  # cria a coluna orcamento_id
    altforce_id = models.CharField("ID Orçamento (AltForce)", max_length=64, db_index=True)
    product_id = models.CharField("Product ID", max_length=64, db_index=True)

    # novo vínculo direto ao item do produto
    item = models.ForeignKey(
        "altforce_sync.ApiOrcamentoProduto",
        on_delete=models.CASCADE,
        related_name="opcionais_set",
        null=True, blank=True,
        db_column="item_id",
    )

    optionals_selected = models.JSONField("Opcionais selecionados", null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiOrcamentosOpcionais"
        ordering = ["id"]  # ordenar por id ASC
        constraints = [
            models.UniqueConstraint(
                fields=["orcamento", "product_id"],
                name="uq_dapiorcamentosopcionais_orcamento_product",
            )
        ]
        indexes = [
            models.Index(fields=["altforce_id", "product_id"]),
            models.Index(fields=["item"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • prod={self.product_id} • opcionais"


class ApiOrcamentoObservacao(models.Model):
    """
    Tabela física: dApiOrcamentosObservacoes
    Agora armazena 1 linha por observação (descriptions[].value) por produto.
    Inclui item_id (FK para dApiOrcamentosProduto) e ordem.
    """
    orcamento = models.ForeignKey(
        "altforce_sync.ApiOrcamento",
        on_delete=models.CASCADE,
        related_name="observacoes",
    )  # cria a coluna orcamento_id
    altforce_id = models.CharField("ID Orçamento (AltForce)", max_length=64, db_index=True)
    product_id  = models.CharField("Product ID", max_length=64, db_index=True)

    # novo vínculo direto ao item do produto
    item = models.ForeignKey(
        "altforce_sync.ApiOrcamentoProduto",
        on_delete=models.CASCADE,
        related_name="observacoes_set",
        null=True, blank=True,
        db_column="item_id",
    )

    # 1 linha por observação
    description_id = models.CharField("Description ID", max_length=64, null=True, blank=True)
    value = models.TextField("Observação", blank=True, default="")
    ord = models.PositiveIntegerField("Ordem", default=0)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiOrcamentosObservacoes"
        ordering = ["id"]  # ordenar por id ASC
        constraints = [
            models.UniqueConstraint(
                fields=["orcamento", "product_id", "ord"],
                name="uq_dapiorcamentosobservacoes_orc_prod_ord",
            )
        ]
        indexes = [
            models.Index(fields=["altforce_id", "product_id"]),
            models.Index(fields=["item"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • prod={self.product_id} • {self.value[:40]}"


class ApiLead(models.Model):
    """
    Tabela física: fApiLeads
    Armazena leads do AltForce (/leads).
    """
    altforce_id = models.CharField("ID Lead (AltForce)", max_length=64, unique=True, db_index=True)

    date = models.DateTimeField("Data do lead", null=True, blank=True, db_index=True)
    status = models.CharField("Status", max_length=40, null=True, blank=True, db_index=True)

    # user.*
    user_name        = models.CharField("User Name", max_length=255, null=True, blank=True)
    user_external_id = models.CharField("User External ID", max_length=64,  null=True, blank=True, db_index=True)

    # lead/Cliente/id
    cliente_id = models.CharField("Cliente ID (lead.Cliente.id)", max_length=64, null=True, blank=True, db_index=True)

    # lead/Nivel de interesse
    interest_level = models.CharField("Nível de interesse", max_length=255, null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "fApiLeads"
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["user_external_id"]),
            models.Index(fields=["cliente_id"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • {self.status or '-'}"


class ApiLeadProduto(models.Model):
    """
    Tabela física: dApiLeadsProdutos
    Uma linha por categoria de produto de interesse do lead (/leads).

    Mapeamentos:
      - id  -> product_id
      - lead/Qual categoria de produto tem interesse -> category_name
    """
    lead = models.ForeignKey(
        "altforce_sync.ApiLead",
        on_delete=models.CASCADE,
        related_name="produtos",
    )  # cria coluna lead_id (FK para fApiLeads)

    # espelho do ID do lead no AltForce para consultas rápidas
    altforce_id = models.CharField("ID Lead (AltForce)", max_length=64, db_index=True)

    # id do item/categoria no payload; se não vier, gerado no serviço
    product_id = models.CharField("Product ID", max_length=128, db_index=True)

    # rótulo/nome da categoria de produto de interesse
    category_name = models.CharField("Categoria de interesse", max_length=255)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "dApiLeadsProdutos"
        ordering = ["id"]  # ordenar a coluna id em ascendente
        constraints = [
            models.UniqueConstraint(
                fields=["lead", "product_id"],
                name="uq_dapileadsprodutos_lead_product",
            )
        ]
        indexes = [
            models.Index(fields=["altforce_id", "product_id"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • prod={self.product_id} • {self.category_name}"


class ApiCliente(models.Model):
    """
    Tabela física: fApiClientes
    Campos mínimos do endpoint /customers solicitados.
    """
    altforce_id = models.CharField("ID Cliente (AltForce)", max_length=64, unique=True, db_index=True)

    name  = models.CharField("Nome", max_length=255, null=True, blank=True)
    email = models.CharField("Email", max_length=255, null=True, blank=True, db_index=True)
    phone = models.CharField("Telefone", max_length=64,  null=True, blank=True, db_index=True)

    city_name    = models.CharField("Cidade (adress.city.name)",   max_length=255, null=True, blank=True)
    state_name   = models.CharField("Estado (adress.state.name)",  max_length=255, null=True, blank=True)
    country_name = models.CharField("País (adress.country.name)",  max_length=255, null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        db_table = "fApiClientes"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["city_name"]),
            models.Index(fields=["state_name"]),
            models.Index(fields=["country_name"]),
        ]

    def __str__(self):
        return f"{self.altforce_id} • {self.name or '-'}"
