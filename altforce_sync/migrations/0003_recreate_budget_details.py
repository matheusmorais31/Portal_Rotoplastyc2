# altforce_sync/migrations/0002_recreate_budget_details.py
from django.db import migrations

SQL_CREATE_PROD = """
CREATE TABLE IF NOT EXISTS `dApiOrcamentosProduto` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
  `orcamento_id` BIGINT NOT NULL,
  `altforce_id` varchar(64) NOT NULL,
  `item_id` varchar(64) NOT NULL,
  `product_id` varchar(64) NULL,
  `name` varchar(255) NULL,
  `quantity` decimal(14,3) NULL,
  `total_price` decimal(14,2) NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  UNIQUE KEY `uq_dapiorcamentosproduto_orcamento_item` (`orcamento_id`,`item_id`),
  KEY `dApiOrcamen_altforc_af314e_idx` (`altforce_id`,`item_id`),
  KEY `dApiOrcamen_altforc_prod_idx` (`altforce_id`,`product_id`),
  KEY `dApiOrcamentosProduto_orcamento_id_fk_idx` (`orcamento_id`),
  CONSTRAINT `fk_dApiOrcamentosProduto_orcamento`
    FOREIGN KEY (`orcamento_id`) REFERENCES `fApiOrcamentos` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SQL_CREATE_OPC = """
CREATE TABLE IF NOT EXISTS `dApiOrcamentosOpcionais` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
  `orcamento_id` BIGINT NOT NULL,
  `altforce_id` varchar(64) NOT NULL,
  `item_id` varchar(64) NOT NULL,
  `product_id` varchar(64) NULL,
  /* JSON armazenado como texto para compat mais ampla (MySQL 5.6/5.7+) */
  `optionals_selected` longtext NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  UNIQUE KEY `uq_dapiorcamentosopcionais_orcamento_item` (`orcamento_id`,`item_id`),
  KEY `dApiOrcamen_altforc_1314a6_idx` (`altforce_id`,`item_id`),
  KEY `dApiOrcamen_altforc_prod_idx` (`altforce_id`,`product_id`),
  KEY `dApiOrcamentosOpcionais_orcamento_id_fk_idx` (`orcamento_id`),
  CONSTRAINT `fk_dApiOrcamentosOpcionais_orcamento`
    FOREIGN KEY (`orcamento_id`) REFERENCES `fApiOrcamentos` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SQL_CREATE_OBS = """
CREATE TABLE IF NOT EXISTS `dApiOrcamentosObservacoes` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
  `orcamento_id` BIGINT NOT NULL,
  `altforce_id` varchar(64) NOT NULL,
  `item_id` varchar(64) NOT NULL,
  `description_id` varchar(64) NULL,
  `line_index` int NOT NULL DEFAULT 0,
  `description_value` longtext NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  UNIQUE KEY `uq_dapiorcamentosobservacoes_orcamento_item_line` (`orcamento_id`,`item_id`,`line_index`),
  KEY `dApiOrcamen_altforc_d5d44b_idx` (`altforce_id`,`item_id`),
  KEY `dApiOrcamentosObservacoes_orcamento_id_fk_idx` (`orcamento_id`),
  CONSTRAINT `fk_dApiOrcamentosObservacoes_orcamento`
    FOREIGN KEY (`orcamento_id`) REFERENCES `fApiOrcamentos` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SQL_DROP_PROD = "DROP TABLE IF EXISTS `dApiOrcamentosProduto`;"
SQL_DROP_OPC  = "DROP TABLE IF EXISTS `dApiOrcamentosOpcionais`;"
SQL_DROP_OBS  = "DROP TABLE IF EXISTS `dApiOrcamentosObservacoes`;"

class Migration(migrations.Migration):
    dependencies = [
        ("altforce_sync", "0002_recreate_missing_obs"),
    ]
    operations = [
        migrations.RunSQL(SQL_CREATE_PROD, SQL_DROP_PROD),
        migrations.RunSQL(SQL_CREATE_OPC,  SQL_DROP_OPC),
        migrations.RunSQL(SQL_CREATE_OBS,  SQL_DROP_OBS),
    ]
