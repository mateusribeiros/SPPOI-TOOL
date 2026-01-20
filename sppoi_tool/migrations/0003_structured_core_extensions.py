from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sppoi_tool', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='sistema',
            name='system_identifier',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='sistema',
            name='tipo_outro',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='sistema',
            name='integration_role',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='sistema',
            name='primary_function_in_flow',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='protocolos_suportados',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sistema',
            name='protocolos_suportados_outro',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='capacidades_dados',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sistema',
            name='capacidades_dados_outro',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='requisitos_autenticacao',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sistema',
            name='requisitos_autenticacao_outro',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='sistema',
            name='technical_contact',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='sistema',
            name='architectural_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='versao',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='interface',
            name='interface_identifier',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='interface',
            name='tipo_outro',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AlterField(
            model_name='interface',
            name='endpoint',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='interface',
            name='formato_dados',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name='interface',
            name='metodos_permitidos',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name='interface',
            name='autenticacao',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='interface',
            name='throttling_unit',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='interface',
            name='technical_interface_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='interface',
            name='detalhes',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='estilointegracao',
            name='estilo_outro',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='estilointegracao',
            name='architectural_rationale',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='estilointegracao',
            name='interfaces_usadas',
            field=models.ManyToManyField(blank=True, related_name='integracoes', to='sppoi_tool.interface'),
        ),
    ]
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sppoi_tool', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='sistema',
            name='system_identifier',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='sistema',
            name='tipo_outro',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='sistema',
            name='integration_role',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='sistema',
            name='primary_function_in_flow',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='protocolos_suportados',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sistema',
            name='protocolos_suportados_outro',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='capacidades_dados',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sistema',
            name='capacidades_dados_outro',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='requisitos_autenticacao',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sistema',
            name='requisitos_autenticacao_outro',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='sistema',
            name='technical_contact',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='sistema',
            name='architectural_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='sistema',
            name='versao',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='interface',
            name='interface_identifier',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='interface',
            name='tipo_outro',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AlterField(
            model_name='interface',
            name='endpoint',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='interface',
            name='formato_dados',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name='interface',
            name='metodos_permitidos',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name='interface',
            name='autenticacao',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='interface',
            name='throttling_unit',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='interface',
            name='technical_interface_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='interface',
            name='detalhes',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='estilointegracao',
            name='estilo_outro',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='estilointegracao',
            name='architectural_rationale',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='estilointegracao',
            name='interfaces_usadas',
            field=models.ManyToManyField(blank=True, related_name='integracoes', to='sppoi_tool.interface'),
        ),
    ]
