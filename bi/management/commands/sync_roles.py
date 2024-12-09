# bi/management/commands/sync_roles.py

import json
import subprocess
from django.core.management.base import BaseCommand
from bi.models import BIRole
from django.conf import settings

class Command(BaseCommand):
    help = "Sincroniza as roles do dataset via XMLA usando Tabular Editor CLI."

    def add_arguments(self, parser):
        parser.add_argument('--dataset-id', type=str, required=True, help='ID do dataset que deseja sincronizar')

    def handle(self, *args, **options):
        dataset_id = options['dataset_id']
        # Ajuste o caminho e o script de acordo com seu ambiente
        # Exemplo de script C# inline no Tabular Editor: "return string.Join(\"\\n\", Model.Roles.Select(r => r.Name));"
        # Aqui iremos apenas simular que exportamos roles para stdout

        # Comando Tabular Editor CLI (exemplo):
        # tabulareditor.exe -S "endpoint" -D datasetname -M "script" -O output.json
        # Você precisará do nome do dataset (não apenas o ID).  
        # Caso seja necessário, recupere o nome do dataset pela API do Power BI ou mantenha mapeado.

        endpoint = "powerbi://api.powerbi.com/v1.0/myorg/Portal Rotoplastyc"
        # Para simplificar, assuma que o dataset_id corresponde ao DatabaseName no model. Ajuste conforme necessário.

        # Script C# para listar roles:
        # "return Model.Roles.Select(r => r.Name).ToList();"
        # Tabular Editor CLI vai gerar um JSON com a lista.

        try:
            result = subprocess.run([
                'tabulareditor.exe',
                '-S', endpoint,
                '-D', dataset_id,  # Talvez aqui precise do nome do dataset. Ajuste!
                '-M', 'return Model.Roles.Select(r => r.Name).ToList();',
                '-O', 'roles.json'
            ], check=True, capture_output=True, text=True)

            # Ler roles.json
            with open('roles.json', 'r') as f:
                roles_list = json.load(f)

            # Atualizar BIRole no banco
            # Remover roles antigas desse dataset que não existem mais
            existing_roles = BIRole.objects.filter(dataset_id=dataset_id)
            existing_names = set(existing_roles.values_list('name', flat=True))
            new_names = set(roles_list)

            # Remover roles antigas que não estão na nova lista
            to_remove = existing_roles.exclude(name__in=new_names)
            to_remove.delete()

            # Adicionar roles novas
            for role_name in new_names:
                BIRole.objects.get_or_create(name=role_name, dataset_id=dataset_id)

            self.stdout.write(self.style.SUCCESS(f"Roles sincronizadas com sucesso para o dataset {dataset_id}."))

        except subprocess.CalledProcessError as e:
            self.stderr.write(self.style.ERROR("Erro ao executar o Tabular Editor CLI"))
            self.stderr.write(str(e))
