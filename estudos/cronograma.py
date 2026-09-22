from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import ItemCronograma, PlanoEstudo, Topico


DIAS_NOME = {
    0: "Segunda",
    1: "Terça",
    2: "Quarta",
    3: "Quinta",
    4: "Sexta",
    5: "Sábado",
    6: "Domingo",
}


def topicos_pendentes_cronograma():
    return (
        Topico.objects.exclude(
            status__in=[Topico.Status.COMPLETO, Topico.Status.REVISADO]
        )
        .select_related("disciplina")
        .order_by("disciplina__ordem", "ordem", "id")
    )


def ordenar_topicos(topicos: list[Topico], modo: str) -> list[Topico]:
    if modo != "intercalar":
        return list(topicos)

    por_disc: dict[int, deque[Topico]] = defaultdict(deque)
    ordem_disc: list[int] = []
    for t in topicos:
        did = t.disciplina_id
        if did not in por_disc:
            ordem_disc.append(did)
        por_disc[did].append(t)

    resultado: list[Topico] = []
    while any(por_disc.values()):
        for did in ordem_disc:
            if por_disc[did]:
                resultado.append(por_disc[did].popleft())
    return resultado


def proximo_dia_estudo(dia: date, dias_estudo: list[int]) -> date:
    dias = set(dias_estudo) or {0, 1, 2, 3, 4, 5}
    atual = dia
    for _ in range(14):
        if atual.weekday() in dias:
            return atual
        atual += timedelta(days=1)
    return dia


def gerar_cronograma(*, regenerar: bool = True, a_partir_de: date | None = None) -> dict:
    plano = PlanoEstudo.get()
    if not plano.data_inicio:
        plano.data_inicio = timezone.localdate()
        plano.save(update_fields=["data_inicio"])

    # Aplica estimativa: vídeo real + buffer de questões (ou fallback)
    for topico in Topico.objects.all():
        if topico.minutos_video > 0:
            topico.minutos_estimados = topico.minutos_video + plano.minutos_extra_questoes
            topico.save(update_fields=["minutos_estimados"])
        elif topico.minutos_estimados <= 0:
            topico.minutos_estimados = plano.minutos_padrao_topico
            topico.save(update_fields=["minutos_estimados"])

    pendentes = list(topicos_pendentes_cronograma())
    fila = ordenar_topicos(pendentes, plano.modo_distribuicao)

    hoje = timezone.localdate()
    inicio = a_partir_de or max(plano.data_inicio, hoje)

    with transaction.atomic():
        if regenerar:
            ItemCronograma.objects.filter(concluido=False).delete()

        dia = proximo_dia_estudo(inicio, plano.dias_estudo)
        minutos_dia = 0
        ordem = 0
        criados = 0
        minutos_total = 0

        for topico in fila:
            if not regenerar and ItemCronograma.objects.filter(
                topico=topico, concluido=False
            ).exists():
                continue

            minutos = topico.minutos_estimados or plano.minutos_padrao_topico
            if minutos_dia > 0 and minutos_dia + minutos > plano.minutos_por_dia:
                dia = proximo_dia_estudo(dia + timedelta(days=1), plano.dias_estudo)
                minutos_dia = 0
                ordem = 0

            ItemCronograma.objects.update_or_create(
                data=dia,
                topico=topico,
                defaults={
                    "minutos_planejados": minutos,
                    "ordem": ordem,
                    "concluido": False,
                },
            )
            ordem += 1
            minutos_dia += minutos
            minutos_total += minutos
            criados += 1

        plano.gerado_em = timezone.now()
        plano.save(update_fields=["gerado_em", "atualizado_em"])

    fim = (
        ItemCronograma.objects.filter(concluido=False)
        .order_by("-data")
        .values_list("data", flat=True)
        .first()
    )
    return {
        "itens": criados,
        "minutos_total": minutos_total,
        "data_fim": fim,
        "dias_estudo": len(
            set(
                ItemCronograma.objects.filter(concluido=False).values_list(
                    "data", flat=True
                )
            )
        ),
    }


def sincronizar_conclusao(topico: Topico, *, redistribuir: bool = True) -> dict | None:
    """Marca o item no cronograma e redistribui o restante a partir de hoje."""
    ItemCronograma.objects.filter(topico=topico, concluido=False).update(concluido=True)
    if topico.status not in (Topico.Status.COMPLETO, Topico.Status.REVISADO):
        return None
    if not redistribuir:
        return None
    if not ItemCronograma.objects.exists():
        return None
    return gerar_cronograma(regenerar=True, a_partir_de=timezone.localdate())


def resumo_cronograma() -> dict:
    plano = PlanoEstudo.get()
    qs = ItemCronograma.objects.filter(concluido=False)
    minutos = qs.aggregate(s=Sum("minutos_planejados"))["s"] or 0
    fim = qs.order_by("-data").values_list("data", flat=True).first()
    hoje = timezone.localdate()
    hoje_itens = list(
        ItemCronograma.objects.filter(data=hoje)
        .select_related("topico", "topico__disciplina")
        .order_by("ordem")
    )
    return {
        "plano": plano,
        "minutos_restantes": minutos,
        "horas_restantes": round(minutos / 60, 1),
        "data_fim": fim,
        "dias_restantes": len(set(qs.values_list("data", flat=True))),
        "itens_hoje": hoje_itens,
        "minutos_hoje": sum(i.minutos_planejados for i in hoje_itens),
        "tem_cronograma": qs.exists() or ItemCronograma.objects.exists(),
    }


def dias_cronograma(limite_dias: int | None = None) -> list[dict]:
    qs = (
        ItemCronograma.objects.select_related("topico", "topico__disciplina")
        .order_by("data", "ordem")
    )
    if limite_dias:
        datas = list(qs.values_list("data", flat=True).distinct()[:limite_dias])
        qs = qs.filter(data__in=datas)

    por_dia: dict[date, list[ItemCronograma]] = defaultdict(list)
    for item in qs:
        por_dia[item.data].append(item)

    resultado = []
    for data in sorted(por_dia.keys()):
        itens = por_dia[data]
        resultado.append(
            {
                "data": data,
                "dia_nome": DIAS_NOME[data.weekday()],
                "itens": itens,
                "minutos": sum(i.minutos_planejados for i in itens),
                "concluidos": sum(1 for i in itens if i.concluido),
                "total": len(itens),
            }
        )
    return resultado


def formatar_minutos(minutos: int) -> str:
    minutos = max(0, int(minutos or 0))
    h, m = divmod(minutos, 60)
    if h and m:
        return f"{h}h {m:02d}min"
    if h:
        return f"{h}h"
    return f"{m}min"
