from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Projeto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(default='Projeto Temporário', max_length=100)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('session_key', models.CharField(db_index=True, max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='Sistema',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100)),
                ('descricao', models.TextField(blank=True)),
                ('tipo', models.CharField(max_length=50)),
                ('versao', models.CharField(max_length=20)),
                ('funcionalidade_principal', models.TextField(blank=True)),
                ('protocolos_suportados', models.CharField(max_length=100)),
                ('capacidades_dados', models.CharField(max_length=100)),
                ('email_responsavel', models.CharField(blank=True, max_length=100)),
                ('contato_responsavel', models.CharField(blank=True, max_length=100)),
                ('mantenedor', models.CharField(blank=True, max_length=100)),
                ('requisitos_autenticacao', models.CharField(max_length=50)),
                ('projeto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sistemas', to='sppoi_tool.projeto')),
            ],
        ),
        migrations.CreateModel(
            name='Interface',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100)),
                ('tipo', models.CharField(max_length=50)),
                ('endpoint', models.TextField()),
                ('formato_dados', models.CharField(max_length=20)),
                ('metodos_permitidos', models.CharField(blank=True, max_length=100)),
                ('autenticacao', models.CharField(blank=True, max_length=50)),
                ('operacoes_suportadas', models.TextField(blank=True)),
                ('exemplo_dados', models.TextField(blank=True)),
                ('esquema', models.TextField(blank=True)),
                ('throttling', models.TextField(blank=True)),
                ('projeto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='interfaces_projeto', to='sppoi_tool.projeto')),
                ('sistema', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='interfaces', to='sppoi_tool.sistema')),
            ],
        ),
        migrations.CreateModel(
            name='EstiloIntegracao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estilo', models.CharField(max_length=50)),
                ('detalhes', models.JSONField(blank=True, null=True)),
                ('projeto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='estilos_integracao', to='sppoi_tool.projeto')),
                ('sistema_destino', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='integracoes_destino', to='sppoi_tool.sistema')),
                ('sistema_origem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='integracoes_origem', to='sppoi_tool.sistema')),
            ],
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant'), ('system', 'System')], max_length=20)),
                ('content', models.TextField()),
                ('prompt_used', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('projeto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mensagens', to='sppoi_tool.projeto')),
            ],
        ),
    ]
