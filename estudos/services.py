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
    """Totais a partir das sessões finalizadas (funciona com ou sem tópico)."""
    agg = SessaoEstudo.objects.filter(ativa=False).aggregate(
        acertos=Sum("acertos"), erros=Sum("erros")
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

    questao_por_disc = {
        row["disciplina_id"]: row
        for row in SessaoEstudo.objects.filter(ativa=False, disciplina_id__isnull=False)
        .values("disciplina_id")
        .annotate(acertos=Sum("acertos"), erros=Sum("erros"))
    }

    result = []
    for d in disciplinas:
        pct = round(100.0 * d.cobertos / d.total, 1) if d.total else 0.0
        q = questao_por_disc.get(d.id, {})
        acertos = q.get("acertos") or 0
        erros = q.get("erros") or 0
        total_q = acertos + erros
        taxa = round(100.0 * acertos / total_q, 1) if total_q else None
        result.append(
            {
                "disciplina": d,
                "total": d.total,
                "cobertos": d.cobertos,
                "estudando": d.estudando,
                "pendentes": d.pendentes,
                "percentual": pct,
                "acertos": acertos,
                "erros": erros,
                "questoes_total": total_q,
                "taxa": taxa,
            }
        )
    return result


def resumo_questoes_disciplina(disciplina_id: int) -> dict:
    agg = SessaoEstudo.objects.filter(
        ativa=False, disciplina_id=disciplina_id
    ).aggregate(acertos=Sum("acertos"), erros=Sum("erros"))
    acertos = agg["acertos"] or 0
    erros = agg["erros"] or 0
    total = acertos + erros
    taxa = round(100.0 * acertos / total, 1) if total else None
    return {"acertos": acertos, "erros": erros, "total": total, "taxa": taxa}

def fila_diaria(limite: int = 12) -> list[Topico]:
    """Fila do dia: no ciclo, prioriza o calendário de hoje e retoma o ponteiro."""
    from . import cronograma as crono
    from .models import ItemCronograma, PlanoEstudo

    hoje = timezone.localdate()
    plano = PlanoEstudo.get()

    if plano.modo_distribuicao == "ciclo":
        escolhidos: list[Topico] = []
        ids: set[int] = set()

        for item in (
            ItemCronograma.objects.filter(data=hoje, concluido=False)
            .select_related("topico", "topico__disciplina")
            .order_by("ordem")
        ):
            if item.topico_id not in ids:
                escolhidos.append(item.topico)
                ids.add(item.topico_id)
            if len(escolhidos) >= limite:
                return escolhidos

        for t in (
            Topico.objects.filter(proxima_revisao__lte=hoje)
            .exclude(status=Topico.Status.PENDENTE)
            .exclude(id__in=ids)
            .select_related("disciplina")
            .order_by("proxima_revisao", "ordem")[: max(0, limite - len(escolhidos))]
        ):
            escolhidos.append(t)
            ids.add(t.id)

        if len(escolhidos) >= limite:
            return escolhidos

        fila = crono.ordenar_ciclo(list(crono.topicos_pendentes_cronograma()))
        if not fila:
            return escolhidos
        n = len(fila)
        inicio = plano.ciclo_ponteiro % n
        for i in range(n):
            t = fila[(inicio + i) % n]
            if t.id in ids:
                continue
            escolhidos.append(t)
            ids.add(t.id)
            if len(escolhidos) >= limite:
                break
        return escolhidos

    ids_list: list[int] = []
    escolhidos: list[Topico] = []

    def add(qs, remaining: int) -> int:
        nonlocal ids_list, escolhidos
        if remaining <= 0:
            return 0
        for t in qs.exclude(id__in=ids_list)[:remaining]:
            escolhidos.append(t)
            ids_list.append(t.id)
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
        .order_by("disciplina__peso", "disciplina__ordem", "ordem"),
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


def calcular_streak() -> dict:
    """Dias consecutivos com pelo menos uma sessão finalizada."""
    datas = {
        d
        for d in SessaoEstudo.objects.filter(ativa=False, finalizada_em__isnull=False)
        .dates("finalizada_em", "day")
    }
    hoje = timezone.localdate()
    cursor = hoje if hoje in datas else hoje - timedelta(days=1)
    streak = 0
    while cursor in datas:
        streak += 1
        cursor -= timedelta(days=1)
    estudou_hoje = hoje in datas
    return {"dias": streak, "estudou_hoje": estudou_hoje}


def resumo_semanal() -> dict:
    hoje = timezone.localdate()
    inicio = hoje - timedelta(days=hoje.weekday())
    qs = SessaoEstudo.objects.filter(
        ativa=False, finalizada_em__date__gte=inicio, finalizada_em__date__lte=hoje
    )
    segundos = qs.aggregate(s=Sum("segundos_liquidos"))["s"] or 0
    acertos = qs.aggregate(s=Sum("acertos"))["s"] or 0
    erros = qs.aggregate(s=Sum("erros"))["s"] or 0
    total_q = acertos + erros
    taxa = round(100.0 * acertos / total_q, 1) if total_q else None

    por_disc = []
    rows = (
        qs.filter(disciplina_id__isnull=False)
        .values("disciplina_id", "disciplina__nome")
        .annotate(
            segundos=Sum("segundos_liquidos"),
            acertos=Sum("acertos"),
            erros=Sum("erros"),
        )
        .order_by("-segundos")
    )
    for row in rows:
        tq = (row["acertos"] or 0) + (row["erros"] or 0)
        por_disc.append(
            {
                "nome": row["disciplina__nome"],
                "segundos": row["segundos"] or 0,
                "horas_fmt": formatar_segundos(row["segundos"] or 0),
                "acertos": row["acertos"] or 0,
                "erros": row["erros"] or 0,
                "taxa": round(100.0 * (row["acertos"] or 0) / tq, 1) if tq else None,
            }
        )

    por_dia = []
    for i in range(7):
        dia = inicio + timedelta(days=i)
        if dia > hoje:
            break
        s = (
            qs.filter(finalizada_em__date=dia).aggregate(s=Sum("segundos_liquidos"))["s"]
            or 0
        )
        por_dia.append(
            {
                "data": dia,
                "segundos": s,
                "horas_fmt": formatar_segundos(s),
                "tem_estudo": s > 0,
            }
        )

    return {
        "inicio": inicio,
        "fim": hoje,
        "segundos": segundos,
        "horas_fmt": formatar_segundos(segundos),
        "acertos": acertos,
        "erros": erros,
        "total_questoes": total_q,
        "taxa": taxa,
        "sessoes": qs.count(),
        "por_disciplina": por_disc,
        "por_dia": por_dia,
    }
