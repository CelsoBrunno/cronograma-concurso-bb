from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from . import cronograma as crono
from . import services
from .models import Disciplina, ItemCronograma, PlanoEstudo, SessaoEstudo, Topico


def dashboard(request: HttpRequest) -> HttpResponse:
    resumo = crono.resumo_cronograma()
    return render(
        request,
        "estudos/dashboard.html",
        {
            "percentual_geral": services.percentual_edital_geral(),
            "horas": services.resumo_horas(),
            "questoes": services.resumo_questoes(),
            "progresso": services.progresso_por_disciplina(),
            "fila": services.fila_diaria(6),
            "sessao_aberta": services.sessao_ativa(),
            "contagem_status": {
                s: Topico.objects.filter(status=s).count()
                for s, _ in Topico.Status.choices
            },
            "cronograma": resumo,
            "streak": services.calcular_streak(),
            "semana": services.resumo_semanal(),
        },
    )


def fila(request: HttpRequest) -> HttpResponse:
    from .models import PlanoEstudo

    return render(
        request,
        "estudos/fila.html",
        {
            "fila": services.fila_diaria(20),
            "sessao_aberta": services.sessao_ativa(),
            "plano": PlanoEstudo.get(),
        },
    )


def disciplinas(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "estudos/disciplinas.html",
        {"progresso": services.progresso_por_disciplina()},
    )


def disciplina_detalhe(request: HttpRequest, pk: int) -> HttpResponse:
    disciplina = get_object_or_404(Disciplina, pk=pk)
    status_filtro = request.GET.get("status", "")
    topicos = disciplina.topicos.all()
    if status_filtro in dict(Topico.Status.choices):
        topicos = topicos.filter(status=status_filtro)
    return render(
        request,
        "estudos/disciplina_detalhe.html",
        {
            "disciplina": disciplina,
            "topicos": topicos,
            "status_filtro": status_filtro,
            "status_choices": Topico.Status.choices,
            "sessao_aberta": services.sessao_ativa(),
            "questoes": services.resumo_questoes_disciplina(disciplina.id),
        },
    )


@require_POST
def atualizar_status(request: HttpRequest, pk: int) -> HttpResponse:
    topico = get_object_or_404(Topico, pk=pk)
    novo = request.POST.get("status", "")
    if novo in dict(Topico.Status.choices):
        topico.status = novo
        if novo in (Topico.Status.COMPLETO, Topico.Status.REVISADO):
            topico._atualizar_srs(acertos=0, erros=0)
        topico.save()
        if novo in (Topico.Status.COMPLETO, Topico.Status.REVISADO):
            crono.sincronizar_conclusao(topico, redistribuir=True)
            messages.success(
                request,
                f"“{topico.titulo}” concluído e cronograma redistribuído.",
            )
        else:
            messages.success(request, f"Status de “{topico.titulo}” atualizado.")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    return redirect(next_url)


@require_http_methods(["GET", "POST"])
def iniciar_sessao(request: HttpRequest) -> HttpResponse:
    aberta = services.sessao_ativa()
    if aberta:
        messages.warning(request, "Já existe uma sessão em andamento.")
        return redirect("estudos:sessao", pk=aberta.pk)

    if request.method == "GET":
        topico_id = request.GET.get("topico")
        disciplina_id = request.GET.get("disciplina")
        topico = get_object_or_404(Topico, pk=topico_id) if topico_id else None
        disciplina = (
            get_object_or_404(Disciplina, pk=disciplina_id)
            if disciplina_id
            else (topico.disciplina if topico else None)
        )
        return render(
            request,
            "estudos/iniciar_sessao.html",
            {
                "topico": topico,
                "disciplina": disciplina,
                "disciplinas": Disciplina.objects.all(),
                "topicos": (
                    Topico.objects.filter(disciplina=disciplina).order_by("ordem")
                    if disciplina
                    else Topico.objects.none()
                ),
            },
        )

    topico_id = request.POST.get("topico") or None
    disciplina_id = request.POST.get("disciplina") or None
    topico = get_object_or_404(Topico, pk=topico_id) if topico_id else None
    disciplina = None
    if disciplina_id:
        disciplina = get_object_or_404(Disciplina, pk=disciplina_id)
    elif topico:
        disciplina = topico.disciplina

    if topico and topico.status == Topico.Status.PENDENTE:
        topico.status = Topico.Status.ESTUDANDO
        topico.save(update_fields=["status", "atualizado_em"])

    sessao = SessaoEstudo.objects.create(topico=topico, disciplina=disciplina)
    return redirect("estudos:sessao", pk=sessao.pk)


def sessao(request: HttpRequest, pk: int) -> HttpResponse:
    sessao_obj = get_object_or_404(
        SessaoEstudo.objects.select_related("topico", "disciplina"), pk=pk
    )
    return render(
        request,
        "estudos/sessao.html",
        {
            "sessao": sessao_obj,
            "status_choices": Topico.Status.choices,
        },
    )


@require_POST
def finalizar_sessao(request: HttpRequest, pk: int) -> HttpResponse:
    sessao_obj = get_object_or_404(SessaoEstudo, pk=pk)
    if not sessao_obj.ativa:
        messages.info(request, "Esta sessão já foi finalizada.")
        return redirect("estudos:historico")

    try:
        segundos = int(request.POST.get("segundos_liquidos") or 0)
        acertos = int(request.POST.get("acertos") or 0)
        erros = int(request.POST.get("erros") or 0)
    except ValueError:
        messages.error(request, "Valores inválidos no formulário.")
        return redirect("estudos:sessao", pk=pk)

    notas = request.POST.get("notas", "")
    novo_status = request.POST.get("novo_status") or None
    if novo_status and novo_status not in dict(Topico.Status.choices):
        novo_status = None

    sessao_obj.finalizar(
        segundos_liquidos=segundos,
        acertos=acertos,
        erros=erros,
        notas=notas,
        novo_status=novo_status,
    )
    if sessao_obj.topico_id:
        topico = Topico.objects.filter(pk=sessao_obj.topico_id).first()
        if topico and topico.status in (
            Topico.Status.COMPLETO,
            Topico.Status.REVISADO,
        ):
            redistribuido = crono.sincronizar_conclusao(topico, redistribuir=True)
            if redistribuido and redistribuido.get("erro"):
                messages.warning(request, redistribuido["erro"])

    messages.success(
        request,
        f"Sessão salva: {services.formatar_segundos(segundos)} · "
        f"{acertos} acertos / {erros} erros.",
    )
    return redirect("estudos:dashboard")


def historico(request: HttpRequest) -> HttpResponse:
    sessoes = SessaoEstudo.objects.filter(ativa=False).select_related(
        "topico", "disciplina"
    )[:100]
    return render(request, "estudos/historico.html", {"sessoes": sessoes})


@require_http_methods(["GET", "POST"])
def cronograma_view(request: HttpRequest) -> HttpResponse:
    plano = PlanoEstudo.get()

    if request.method == "POST":
        acao = request.POST.get("acao", "salvar")
        try:
            minutos_padrao = int(request.POST.get("minutos_padrao_topico") or 40)
            minutos_extra = int(request.POST.get("minutos_extra_questoes") or 15)
        except ValueError:
            messages.error(request, "Valores inválidos.")
            return redirect("estudos:cronograma")

        dias = [int(x) for x in request.POST.getlist("dias_estudo") if x.isdigit()]
        data_inicio_raw = request.POST.get("data_inicio") or ""
        data_meta_raw = request.POST.get("data_meta") or ""
        try:
            data_inicio = date.fromisoformat(data_inicio_raw) if data_inicio_raw else date.today()
        except ValueError:
            data_inicio = date.today()
        try:
            data_meta = date.fromisoformat(data_meta_raw) if data_meta_raw else None
        except ValueError:
            data_meta = None

        modo = request.POST.get("modo_distribuicao") or "ciclo"
        if modo not in ("ciclo", "intercalar", "sequencial", "prioridade"):
            modo = "ciclo"

        aplicar_padrao = request.POST.get("aplicar_padrao") == "1"
        incluir_questoes = request.POST.get("incluir_tempo_questoes") == "1"

        if data_meta is None:
            messages.error(request, "Informe a data em que quer encerrar os estudos.")
            return redirect("estudos:cronograma")

        modo_anterior = plano.modo_distribuicao
        plano.minutos_padrao_topico = max(10, minutos_padrao)
        plano.minutos_extra_questoes = max(0, minutos_extra)
        plano.incluir_tempo_questoes = incluir_questoes
        plano.dias_estudo = dias or [0, 1, 2, 3, 4, 5]
        plano.data_inicio = data_inicio
        plano.data_meta = data_meta
        plano.modo_distribuicao = modo
        if modo == "ciclo" and (modo_anterior != "ciclo" or acao == "gerar"):
            plano.ciclo_ponteiro = 0
        plano.save()

        crono.ensure_pesos_disciplinas()
        crono.aplicar_estimativas(plano)

        if aplicar_padrao:
            Topico.objects.filter(minutos_video=0).update(
                minutos_estimados=plano.minutos_padrao_topico
            )

        if acao == "gerar":
            resultado = crono.gerar_cronograma(regenerar=True)
        else:
            resultado = crono.atualizar_carga_diaria(plano)

        if resultado.get("erro"):
            messages.error(request, resultado["erro"])
            return redirect("estudos:cronograma")

        carga = crono.formatar_minutos(resultado["minutos_por_dia"])
        meta = data_meta.strftime("%d/%m/%Y")
        if acao == "gerar":
            extra = ""
            if modo == "ciclo":
                extra = " Modo ciclo: matérias importantes aparecem mais vezes, intercaladas."
            messages.success(
                request,
                f"Para encerrar em {meta}, reserve {carga} por dia de estudo. "
                f"{resultado['itens']} aulas em {resultado['dias_estudo']} dias.{extra}",
            )
        else:
            messages.success(
                request,
                f"Para encerrar em {meta}, reserve {carga} por dia de estudo.",
            )
        return redirect("estudos:cronograma")

    return render(
        request,
        "estudos/cronograma.html",
        {
            "plano": plano,
            "resumo": crono.resumo_cronograma(),
            "dias": crono.dias_cronograma(),
            "dias_opcoes": list(crono.DIAS_NOME.items()),
            "fmt_min": crono.formatar_minutos,
            "ciclo_padrao": crono.descrever_ciclo() if plano.modo_distribuicao == "ciclo" else [],
        },
    )


def resumo(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "estudos/resumo.html",
        {
            "semana": services.resumo_semanal(),
            "streak": services.calcular_streak(),
            "horas": services.resumo_horas(),
            "questoes": services.resumo_questoes(),
            "progresso": services.progresso_por_disciplina(),
        },
    )


@require_http_methods(["GET", "POST"])
def backup(request: HttpRequest) -> HttpResponse:
    db_path = Path(settings.DATABASES["default"]["NAME"])
    if request.method == "POST":
        arquivo = request.FILES.get("arquivo")
        if not arquivo or not arquivo.name.endswith(".sqlite3"):
            messages.error(request, "Envie um arquivo .sqlite3 válido.")
            return redirect("estudos:backup")
        bak = db_path.with_suffix(".sqlite3.bak")
        if db_path.exists():
            shutil.copy2(db_path, bak)
        with open(db_path, "wb") as dest:
            for chunk in arquivo.chunks():
                dest.write(chunk)
        messages.success(
            request,
            "Backup restaurado. Reinicie o servidor (pare e rode de novo) para carregar os dados.",
        )
        return redirect("estudos:backup")

    return render(
        request,
        "estudos/backup.html",
        {
            "db_nome": db_path.name,
            "db_existe": db_path.exists(),
            "db_tamanho": db_path.stat().st_size if db_path.exists() else 0,
        },
    )


def backup_exportar(request: HttpRequest) -> HttpResponse:
    db_path = Path(settings.DATABASES["default"]["NAME"])
    if not db_path.exists():
        messages.error(request, "Banco local não encontrado.")
        return redirect("estudos:backup")
    nome = f"estudos-bb-{timezone.localdate().isoformat()}.sqlite3"
    return FileResponse(open(db_path, "rb"), as_attachment=True, filename=nome)
