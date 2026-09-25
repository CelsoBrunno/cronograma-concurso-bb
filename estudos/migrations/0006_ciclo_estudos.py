# Generated manually for ciclo de estudos

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estudos", "0005_peso_e_incluir_questoes"),
    ]

    operations = [
        migrations.AddField(
            model_name="planoestudo",
            name="ciclo_ponteiro",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="planoestudo",
            name="modo_distribuicao",
            field=models.CharField(
                choices=[
                    ("ciclo", "Ciclo de estudos (recomendado)"),
                    ("prioridade", "Prioridade na prova (uma matéria por vez)"),
                    ("intercalar", "Intercalar 1 a 1"),
                    ("sequencial", "Ordem do edital"),
                ],
                default="ciclo",
                max_length=20,
            ),
        ),
    ]
