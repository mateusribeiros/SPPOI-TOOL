from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sppoi_tool', '0003_structured_core_extensions'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sistema',
            name='funcionalidade_principal',
        ),
    ]
