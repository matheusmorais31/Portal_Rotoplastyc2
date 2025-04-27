# ia/management/commands/recalculate_brl_costs.py

from django.core.management.base import BaseCommand
from django.conf import settings
from decimal import Decimal, InvalidOperation
from ia.models import ApiUsageLog # Ajuste o caminho se seu app tiver outro nome

class Command(BaseCommand):
    help = 'Recalcula o campo estimated_cost_brl em ApiUsageLog usando a taxa definida em settings.USD_TO_BRL_RATE.'

    def handle(self, *args, **options):
        usd_to_brl_rate = getattr(settings, 'USD_TO_BRL_RATE', None)

        if not usd_to_brl_rate or not isinstance(usd_to_brl_rate, Decimal) or usd_to_brl_rate <= 0:
            self.stderr.write(self.style.ERROR(
                f"A configuração USD_TO_BRL_RATE não está definida ou é inválida ({usd_to_brl_rate}). Abortando."
            ))
            return

        self.stdout.write(f"Usando a taxa de conversão USD para BRL: {usd_to_brl_rate}")

        logs_to_update = ApiUsageLog.objects.all()
        updated_count = 0
        skipped_count = 0

        for log in logs_to_update:
            try:
                # Garante que temos um valor Decimal válido para USD
                cost_usd = log.estimated_cost if isinstance(log.estimated_cost, Decimal) else Decimal(0)

                new_cost_brl = cost_usd * usd_to_brl_rate

                # Verifica se o valor realmente mudou para evitar escritas desnecessárias
                # Compara com uma precisão razoável (e.g., 6 casas decimais)
                if abs(new_cost_brl - (log.estimated_cost_brl or Decimal(0))) > Decimal('0.000001'):
                    log.estimated_cost_brl = new_cost_brl
                    log.save(update_fields=['estimated_cost_brl'])
                    updated_count += 1
                    if updated_count % 100 == 0: # Log a cada 100 atualizações
                         self.stdout.write(f"Atualizados {updated_count} registros...")
                else:
                    skipped_count +=1 # Conta como pulado se não houve mudança significativa

            except InvalidOperation:
                 self.stderr.write(self.style.WARNING(f"Skipping Log ID {log.id}: Invalid decimal value for estimated_cost ({log.estimated_cost})."))
                 skipped_count += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Erro ao processar Log ID {log.id}: {e}"))
                skipped_count += 1


        self.stdout.write(self.style.SUCCESS(
            f"Processamento concluído. {updated_count} registros ApiUsageLog tiveram estimated_cost_brl atualizado. "
            f"{skipped_count} registros foram pulados (sem alteração, erro ou valor inválido)."
        ))



        #python manage.py recalculate_brl_costs comando para atualizar no terminal