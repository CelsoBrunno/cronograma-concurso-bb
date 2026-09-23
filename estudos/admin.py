from django.contrib import admin

from .models import Disciplina, ItemCronograma, PlanoEstudo, SessaoEstudo, Topico


@admin.register(Disciplina)
class DisciplinaAdmin(admin.ModelAdmin):
    list_display = ("ordem", "nome")
    ordering = ("ordem",)


@admin.register(Topico)
class TopicoAdmin(admin.ModelAdmin):
    list_display = (
        "ordem",
        "titulo",
        "disciplina",
        "status",
        "minutos_estimados",
        "minutos_video",
        "proxima_revisao",
        "total_acertos",
        "total_erros",
    )
    list_filter = ("status", "disciplina")
    search_fields = ("titulo",)
    list_editable = ("status", "minutos_estimados", "minutos_video")


@admin.register(SessaoEstudo)
class SessaoEstudoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "iniciada_em",
        "disciplina",
        "topico",
        "segundos_liquidos",
        "acertos",
        "erros",
        "ativa",
    )
    list_filter = ("ativa", "disciplina")


@admin.register(PlanoEstudo)
class PlanoEstudoAdmin(admin.ModelAdmin):
    list_display = (
        "minutos_por_dia",
        "minutos_padrao_topico",
        "data_inicio",
        "data_meta",
        "modo_distribuicao",
        "gerado_em",
    )


@admin.register(ItemCronograma)
class ItemCronogramaAdmin(admin.ModelAdmin):
    list_display = ("data", "ordem", "topico", "minutos_planejados", "concluido")
    list_filter = ("data", "concluido")
    search_fields = ("topico__titulo",)
