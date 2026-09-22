from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import Disciplina, SessaoEstudo, Topico


def percentual_edital_geral() -> float:
    total = Topico.objects.count()
    if not total:
        return 0.0
    cobertos = Topico.objects.filter(
        status__in=[Topico.Status.COMPLETO, Topico.Status.REVISADO]
    ).count()
    return round(100.0 * cobertos / total, 1)


def resumo_horas() -> dict:
    hoje = timezone.localdate()
    inicio_semana = hoje - timedelta(days=hoje.weekday())

    qs = SessaoEstudo.objects.filter(ativa=False)
    total = qs.aggregate(s=Sum("segundos_liquidos"))["s"] or 0
    hoje_s = (
        qs.filter(finalizada_em__date=hoje).aggregate(s=Sum("segundos_liquidos"))["s"]
        or 0
    )
    semana_s = (
        qs.filter(finalizada_em__date__gte=inicio_semana).aggregate(
            s=Sum("segundos_liquidos")
        )["s"]
        or 0
    )
    return {
        "hoje": hoje_s,
        "semana": semana_s,
        "total": total,
        "hoje_fmt": formatar_segundos(hoje_s),
        "semana_fmt": formatar_segundos(semana_s),
        "total_fmt": formatar_segundos(total),
    }


def resumo_questoes() -> dict:
    agg = Topico.objects.aggregate(
        acertos=Sum("total_acertos"), erros=Sum("total_erros")
    )
    acertos = agg["acertos"] or 0
    erros = agg["erros"] or 0
    total = acertos + erros
    taxa = round(100.0 * acertos / total, 1) if total else None
    return {"acertos": acertos, "erros": erros, "total": total, "taxa": taxa}


def progresso_por_disciplina() -> list[dict]:
    disciplinas = Disciplina.objects.annotate(
        total=Count("topicos"),
        cobertos=Count(
            "topicos",
            filter=Q(
                topicos__status__in=[Topico.Status.COMPLETO, Topico.Status.REVISADO]
            ),
        ),
        estudando=Count(
            "topicos", filter=Q(topicos__status=Topico.Status.ESTUDANDO)
        ),
        pendentes=Count(
            "topicos", filter=Q(topicos__status=Topico.Status.PENDENTE)
        ),
    )
    result = []
    for d in disciplinas:
        pct = round(100.0 * d.cobertos / d.total, 1) if d.total else 0.0
        result.append(
            {
                "disciplina": d,
                "total": d.total,
                "cobertos": d.cobertos,
                "estudando": d.estudando,
                "pendentes": d.pendentes,
                "percentual": pct,
            }
        )
    return result


def fila_diaria(limite: int = 12) -> list[Topico]:
    """Fila simples: revisões vencidas → estudando → pendentes."""
    hoje = timezone.localdate()
    ids: list[int] = []
    escolhidos: list[Topico] = []

    def add(qs, remaining: int) -> int:
        nonlocal ids, escolhidos
        if remaining <= 0:
            return 0
        for t in qs.exclude(id__in=ids)[:remaining]:
            escolhidos.append(t)
            ids.append(t.id)
            remaining -= 1
        return remaining

    restante = limite
    restante = add(
        Topico.objects.filter(proxima_revisao__lte=hoje)
        .exclude(status=Topico.Status.PENDENTE)
        .select_related("disciplina")
        .order_by("proxima_revisao", "ordem"),
        restante,
    )
    restante = add(
        Topico.objects.filter(status=Topico.Status.ESTUDANDO)
        .select_related("disciplina")
        .order_by("estudado_em", "ordem"),
        restante,
    )
    add(
        Topico.objects.filter(status=Topico.Status.PENDENTE)
        .select_related("disciplina")
        .order_by("disciplina__ordem", "ordem"),
        restante,
    )
    return escolhidos


def formatar_segundos(segundos: int) -> str:
    segundos = max(0, int(segundos or 0))
    h, rem = divmod(segundos, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}min"
    if m:
        return f"{m}min {s:02d}s"
    return f"{s}s"


def sessao_ativa() -> SessaoEstudo | None:
    return (
        SessaoEstudo.objects.filter(ativa=True)
        .select_related("topico", "disciplina")
        .order_by("-iniciada_em")
        .first()
    )
