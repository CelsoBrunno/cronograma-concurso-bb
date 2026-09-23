from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estudos", "0003_planoestudo_minutos_extra_questoes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="planoestudo",
            name="data_meta",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Data em que os tópicos pendentes devem estar concluídos",
            ),
        ),
        migrations.AlterField(
            model_name="planoestudo",
            name="minutos_por_dia",
            field=models.PositiveIntegerField(
                default=120,
                help_text="Calculado a partir da data da meta: minutos do dia mais cheio",
            ),
        ),
    ]
