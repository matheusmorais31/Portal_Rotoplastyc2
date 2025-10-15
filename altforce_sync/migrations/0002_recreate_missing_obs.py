# altforce_sync/migrations/0002_recreate_missing_obs.py
from django.db import migrations

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
  KEY `dApiOrcamentosObservacoes_orcamento_id_aa6c3b90` (`orcamento_id`),
  CONSTRAINT `dApiOrcamentosObservacoes_orcamento_id_fk`
    FOREIGN KEY (`orcamento_id`) REFERENCES `fApiOrcamentos` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SQL_DROP_OBS = "DROP TABLE IF EXISTS `dApiOrcamentosObservacoes`;"

class Migration(migrations.Migration):
    dependencies = [
        ('altforce_sync', '0001_initial'),
    ]
    operations = [
        migrations.RunSQL(SQL_CREATE_OBS, SQL_DROP_OBS),
    ]
