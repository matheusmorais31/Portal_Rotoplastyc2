# bi/tests.py

from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch
from .models import BIReport
from .tasks import sincronizar_bi_reports

class SynchronizationTestCase(TestCase):
    @patch('bi.utils.get_powerbi_reports')
    def test_sincronizar_bi_reports(self, mock_get_powerbi_reports):
        # Mock da resposta da API de relatórios
        mock_get_powerbi_reports.return_value = [
            {
                'id': 'test-report-id-1',
                'name': 'Test Report 1',
                'embedUrl': 'https://embed.url/test1',
                'groupId': 'test-group-id'
            },
            {
                'id': 'test-report-id-2',
                'name': 'Test Report 2',
                'embedUrl': 'https://embed.url/test2',
                'groupId': 'test-group-id'
            }
        ]

        # Mock da função get_next_update
        with patch('bi.tasks.get_next_update') as mock_get_next_update:
            mock_get_next_update.return_value = timezone.now() + timezone.timedelta(hours=1)

            # Executar a tarefa
            sincronizar_bi_reports()

            # Verificar se os relatórios foram criados
            self.assertEqual(BIReport.objects.count(), 2)

            for report in mock_get_powerbi_reports.return_value:
                bi_report = BIReport.objects.get(report_id=report['id'])
                self.assertEqual(bi_report.title, report['name'])
                self.assertEqual(bi_report.embed_code, report['embedUrl'])
                self.assertIsNotNone(bi_report.last_updated)
                self.assertIsNotNone(bi_report.next_update)
                # Verifique se next_update está no próximo horário inteiro
                expected_next_update = (bi_report.last_updated + timezone.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                self.assertEqual(bi_report.next_update, expected_next_update)
