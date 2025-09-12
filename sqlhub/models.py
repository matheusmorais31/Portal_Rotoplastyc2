# sqlhub/models.py
from django.db import models
from django.conf import settings
from .fields import EncryptedTextField


class DBEngine(models.TextChoices):
    FIREBIRD = "firebird", "Firebird"
    POSTGRES = "postgresql", "PostgreSQL"
    MYSQL = "mysql", "MySQL/MariaDB"
    SQLSERVER = "mssql", "SQL Server"


class DBConnection(models.Model):
    name = models.CharField(
        "Nome", max_length=80, unique=True, db_column="nome"
    )
    engine = models.CharField(
        "Engine", max_length=20, choices=DBEngine.choices, db_column="tipo_banco"
    )
    host = models.CharField(
        "Host", max_length=200, blank=True, default="", db_column="host"
    )
    port = models.PositiveIntegerField(
        "Porta", null=True, blank=True, db_column="porta"
    )

    # Importante: opcional para SQL Server (usa o DB padrão do login se vazio)
    database = models.CharField(
        "Banco/Serviço",
        max_length=300,
        blank=True,
        default="",
        help_text="Para Firebird use o caminho completo do .FDB. Para SQL Server pode deixar vazio.",
        db_column="banco_servico",
    )

    username = models.CharField(
        "Usuário", max_length=200, db_column="usuario"
    )
    password = EncryptedTextField(
        "Senha", db_column="senha"  # criptografado em repouso
    )
    options = models.JSONField(
        "Opções",
        default=dict,
        blank=True,
        help_text='Ex.: {"odbc_driver": "ODBC Driver 18 for SQL Server", "charset": "UTF8"}',
        db_column="opcoes",
    )
    read_only = models.BooleanField(
        "Somente leitura", default=True, db_column="somente_leitura"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dbconns",
        verbose_name="Criado por",
        db_column="criado_por_id",
    )
    created_at = models.DateTimeField(
        "Criado em", auto_now_add=True, db_column="criado_em"
    )

    class Meta:
        db_table = "sqlhub_conexao"
        verbose_name = "Conexão de banco"
        verbose_name_plural = "Conexões de banco"
        ordering = ("name",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.get_engine_display()})"


class SavedQuery(models.Model):
    name = models.CharField(
        "Nome", max_length=120, db_column="nome"
    )
    connection = models.ForeignKey(
        DBConnection,
        on_delete=models.CASCADE,
        related_name="queries",
        verbose_name="Conexão",
        db_column="conexao_id",
    )
    sql_text = models.TextField(
        "SQL (somente SELECT)",
        help_text="Apenas SELECT. WHERE/ORDER BY permitidos. Evite ';'.",
        db_column="sql_texto",
    )
    default_limit = models.PositiveIntegerField(
        "Limite padrão", default=1000, db_column="limite_padrao"
    )
    is_active = models.BooleanField(
        "Ativa?", default=True, db_column="ativa"
    )
    meta = models.JSONField(
        "Metadados", default=dict, blank=True, db_column="metadados"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="queries_created",
        verbose_name="Criada por",
        db_column="criada_por_id",
    )
    updated_at = models.DateTimeField(
        "Atualizada em", auto_now=True, db_column="atualizada_em"
    )

    class Meta:
        db_table = "sqlhub_consulta"
        verbose_name = "Consulta"
        verbose_name_plural = "Consultas"
        unique_together = ("connection", "name")
        ordering = ("connection__name", "name")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.connection.name} :: {self.name}"


class QueryCache(models.Model):
    query = models.ForeignKey(
        SavedQuery,
        on_delete=models.CASCADE,
        related_name="caches",
        verbose_name="Consulta",
        db_column="consulta_id",
    )
    params_hash = models.CharField(
        "Hash dos parâmetros", max_length=64, db_index=True, db_column="hash_parametros"
    )
    rows = models.JSONField(
        "Linhas", default=list, blank=True, db_column="linhas"
    )  # [[v1,v2,...],...]
    columns = models.JSONField(
        "Colunas", default=list, blank=True, db_column="colunas"
    )  # ["col","col2",...]
    expires_at = models.DateTimeField(
        "Expira em", db_index=True, db_column="expira_em"
    )

    class Meta:
        db_table = "sqlhub_cache_consulta"
        verbose_name = "Cache de consulta"
        verbose_name_plural = "Caches de consulta"
        indexes = [
            models.Index(fields=["query", "params_hash", "expires_at"])
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Cache {self.query_id} #{self.params_hash[:8]}..."
