from django.urls import path

from . import views

app_name = "estudos"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("fila/", views.fila, name="fila"),
    path("cronograma/", views.cronograma_view, name="cronograma"),
    path("disciplinas/", views.disciplinas, name="disciplinas"),
    path("disciplinas/<int:pk>/", views.disciplina_detalhe, name="disciplina"),
    path("topicos/<int:pk>/status/", views.atualizar_status, name="atualizar_status"),
    path("sessao/iniciar/", views.iniciar_sessao, name="iniciar_sessao"),
    path("sessao/<int:pk>/", views.sessao, name="sessao"),
    path("sessao/<int:pk>/finalizar/", views.finalizar_sessao, name="finalizar_sessao"),
    path("historico/", views.historico, name="historico"),
]
