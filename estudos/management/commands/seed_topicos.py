import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from estudos.models import Disciplina, PlanoEstudo, Topico


class Command(BaseCommand):
    help = "Importa disciplinas e tópicos do Gran Cursos (data/topicos_gran.json)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Apaga disciplinas/tópicos antes de importar (não apaga sessões órfãs).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = settings.TOPICOS_SEED_PATH
        if not path.exists():
            self.stderr.write(f"Arquivo não encontrado: {path}")
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        plano = PlanoEstudo.get()
        extra = plano.minutos_extra_questoes

        if options["reset"]:
            Topico.objects.all().delete()
            Disciplina.objects.all().delete()
            self.stdout.write("Base de tópicos limpa.")

        criadas = 0
        topicos = 0
        atualizados = 0
        for item in data:
            disciplina, created = Disciplina.objects.update_or_create(
                nome=item["nome"],
                defaults={"ordem": item.get("ordem", 0)},
            )
            if created:
                criadas += 1
            for t in item.get("topicos", []):
                minutos_video = int(t.get("minutos_video") or 0)
                if t.get("minutos_estimados"):
                    minutos_estimados = int(t["minutos_estimados"])
                elif minutos_video:
                    minutos_estimados = minutos_video + extra
                else:
                    minutos_estimados = plano.minutos_padrao_topico

                obj, t_created = Topico.objects.update_or_create(
                    disciplina=disciplina,
                    titulo=t["titulo"],
                    defaults={
                        "ordem": t.get("ordem", 0),
                        "minutos_video": minutos_video,
                        "minutos_estimados": minutos_estimados,
                    },
                )
                if t_created:
                    topicos += 1
                else:
                    atualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OK — disciplinas novas: {criadas}, tópicos novos: {topicos}, "
                f"atualizados: {atualizados}, total: {Topico.objects.count()}"
            )
        )
