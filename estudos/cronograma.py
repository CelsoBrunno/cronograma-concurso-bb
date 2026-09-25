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


def slots_disciplina(peso: int) -> int:
    """Mais prioridade na prova (peso menor) → mais blocos no ciclo."""
    peso = max(1, int(peso or 50))
    return max(1, 6 - ((peso - 1) // 2))


def padrao_ciclo(disciplinas: list) -> list[int]:
    """Lista intercalada de disciplina_ids; peso menor → mais aparições no ciclo."""
    ordenadas = sorted(disciplinas, key=lambda d: (d.peso, d.ordem, d.id))
    restantes = {d.id: slots_disciplina(d.peso) for d in ordenadas}
    padrao: list[int] = []
    while any(restantes.values()):
        for disc in ordenadas:
            if restantes[disc.id] > 0:
                padrao.append(disc.id)
                restantes[disc.id] -= 1
    return padrao


def ordenar_ciclo(topicos: list[Topico]) -> list[Topico]:
    """Rodízio ponderado: matérias importantes aparecem mais, sem esgotar uma só."""
    ensure_pesos_disciplinas()
    if not topicos:
        return []

    por_disc: dict[int, deque[Topico]] = defaultdict(deque)
    disciplinas_map: dict[int, object] = {}
    for t in sorted(topicos, key=lambda x: (x.disciplina.peso, x.ordem, x.id)):
        por_disc[t.disciplina_id].append(t)
        disciplinas_map[t.disciplina_id] = t.disciplina

    padrao = padrao_ciclo(list(disciplinas_map.values()))
    if not padrao:
        return list(topicos)

    resultado: list[Topico] = []
    while any(por_disc.values()):
        avancou = False
        for did in padrao:
            if por_disc[did]:
                resultado.append(por_disc[did].popleft())
                avancou = True
        if not avancou:
            # Disciplinas sem slot no padrão (nome fora do mapa BB) — esvazia o resto.
            for fila in por_disc.values():
                resultado.extend(fila)
                fila.clear()
            break
    return resultado


def ordenar_topicos(topicos: list[Topico], modo: str) -> list[Topico]:
    if modo == "ciclo":
        return ordenar_ciclo(topicos)
    if modo == "prioridade":
        ensure_pesos_disciplinas()
        return sorted(
            topicos,
            key=lambda t: (t.disciplina.peso, t.disciplina.ordem, t.ordem, t.id),
        )
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


def descrever_ciclo() -> list[dict]:
    """Para a UI: quantos blocos cada disciplina tem no padrão do ciclo."""
    from .models import Disciplina

    ensure_pesos_disciplinas()
    discs = list(Disciplina.objects.order_by("peso", "ordem", "id"))
    return [
        {
            "nome": d.nome,
            "peso": d.peso,
            "blocos": slots_disciplina(d.peso),
        }
        for d in discs
    ]


def avancar_ponteiro_ciclo(topico: Topico | None = None) -> None:
    """Após concluir/estudar: avança o ponteiro para retomar o ciclo no próximo dia."""
    plano = PlanoEstudo.get()
    if plano.modo_distribuicao != "ciclo":
        return
    fila = ordenar_ciclo(list(topicos_pendentes_cronograma()))
    if not fila:
        plano.ciclo_ponteiro = 0
        plano.save(update_fields=["ciclo_ponteiro", "atualizado_em"])
        return
    if topico is not None:
        # Se o tópico ainda está na fila (só estudando), aponta para o próximo depois dele.
        ids = [t.id for t in fila]
        if topico.id in ids:
            plano.ciclo_ponteiro = (ids.index(topico.id) + 1) % len(fila)
        else:
            plano.ciclo_ponteiro = (plano.ciclo_ponteiro + 1) % len(fila)
    else:
        plano.ciclo_ponteiro = (plano.ciclo_ponteiro + 1) % len(fila)
    plano.save(update_fields=["ciclo_ponteiro", "atualizado_em"])


def resetar_ponteiro_ciclo() -> None:
    plano = PlanoEstudo.get()
    if plano.ciclo_ponteiro != 0:
        plano.ciclo_ponteiro = 0
        plano.save(update_fields=["ciclo_ponteiro", "atualizado_em"])


PESOS_PROVA_BB = {
    "Conhecimentos Bancários": 1,
    "Matemática Financeira": 2,
    "Língua Portuguesa": 3,
    "Matemática": 4,
    "Conhecimentos de Informática": 5,
    "Vendas e Negociação": 6,
    "Atualidades do Mercado Financeiro": 7,
    "Língua Inglesa": 8,
    "Redação Discursiva": 9,
}


def ensure_pesos_disciplinas() -> None:
    from .models import Disciplina

    for nome, peso in PESOS_PROVA_BB.items():
        Disciplina.objects.filter(nome=nome).exclude(peso=peso).update(peso=peso)


def aplicar_estimativas(plano: PlanoEstudo) -> None:
    """Vídeo real (+ questões se ligado), ou fallback quando não há duração."""
    extra = plano.minutos_extra_questoes if plano.incluir_tempo_questoes else 0
    for topico in Topico.objects.all():
        if topico.minutos_video > 0:
            estimado = topico.minutos_video + extra
        elif topico.minutos_estimados <= 0:
            estimado = plano.minutos_padrao_topico
        else:
            continue
        if topico.minutos_estimados != estimado:
            topico.minutos_estimados = estimado
            topico.save(update_fields=["minutos_estimados"])


def dias_permitidos(dias_estudo: list[int]) -> set[int]:
    return set(dias_estudo) or {0, 1, 2, 3, 4, 5}


def listar_dias_estudo(inicio: date, fim: date, dias_estudo: list[int]) -> list[date]:
    if fim < inicio:
        return []
    permitidos = dias_permitidos(dias_estudo)
    dias: list[date] = []
    atual = inicio
    while atual <= fim:
        if atual.weekday() in permitidos:
            dias.append(atual)
        atual += timedelta(days=1)
    return dias


def _minutos_topico(topico: Topico, padrao: int) -> int:
    return topico.minutos_estimados or padrao


def distribuir_nos_dias(
    fila: list[Topico],
    minutos_por_dia: int,
    datas: list[date],
    padrao: int,
) -> list[tuple[date, int, Topico, int]] | None:
    """Encaixa cada aula inteira. None se não couber até a última data."""
    if not fila:
        return []
    if not datas or minutos_por_dia <= 0:
        return None

    idx = 0
    usados = 0
    ordem = 0
    itens: list[tuple[date, int, Topico, int]] = []
    for topico in fila:
        minutos = _minutos_topico(topico, padrao)
        if usados > 0 and usados + minutos > minutos_por_dia:
            idx += 1
            usados = 0
            ordem = 0
            if idx >= len(datas):
                return None
        itens.append((datas[idx], ordem, topico, minutos))
        ordem += 1
        usados += minutos
    return itens


def carga_do_dia_mais_cheio(
    fila: list[Topico], datas: list[date], padrao: int
) -> int:
    """Menor ritmo diário que ainda termina até a última data da lista.

    O valor devolvido é o total do dia mais cheio desse encaixe. Uma aula
    maior que a média ocupa o dia inteiro e puxa a carga para cima.
    """
    if not fila:
        return 0
    if not datas:
        return 0

    total = sum(_minutos_topico(t, padrao) for t in fila)
    lo, hi = 1, max(total, 1)
    melhor = hi
    while lo <= hi:
        meio = (lo + hi) // 2
        if distribuir_nos_dias(fila, meio, datas, padrao) is not None:
            melhor = meio
            hi = meio - 1
        else:
            lo = meio + 1

    itens = distribuir_nos_dias(fila, melhor, datas, padrao) or []
    por_dia: dict[date, int] = defaultdict(int)
    for data, _ordem, _topico, minutos in itens:
        por_dia[data] += minutos
    return max(por_dia.values(), default=0)


def _inicio_plano(plano: PlanoEstudo, a_partir_de: date | None) -> date:
    hoje = timezone.localdate()
    if not plano.data_inicio:
        plano.data_inicio = hoje
        plano.save(update_fields=["data_inicio"])
    return a_partir_de or max(plano.data_inicio, hoje)


def atualizar_carga_diaria(
    plano: PlanoEstudo | None = None, *, a_partir_de: date | None = None
) -> dict:
    """Calcula minutos/dia para concluir os pendentes até plano.data_meta."""
    plano = plano or PlanoEstudo.get()
    aplicar_estimativas(plano)
    fila = ordenar_topicos(
        list(topicos_pendentes_cronograma()), plano.modo_distribuicao
    )
    inicio = _inicio_plano(plano, a_partir_de)

    if not plano.data_meta:
        return {
            "erro": "Informe a data em que quer encerrar os estudos.",
            "minutos_por_dia": plano.minutos_por_dia,
            "dias": 0,
        }
    if plano.data_meta < inicio:
        if plano.data_meta < timezone.localdate():
            erro = "A data da meta já passou. Escolha um dia a partir de hoje."
        else:
            erro = "A data da meta precisa ser igual ou posterior à data de início."
        return {
            "erro": erro,
            "minutos_por_dia": plano.minutos_por_dia,
            "dias": 0,
        }

    datas = listar_dias_estudo(inicio, plano.data_meta, plano.dias_estudo)
    if fila and not datas:
        return {
            "erro": (
                "Não há dia de estudo entre o início e a data da meta. "
                "Marque um dia da semana nesse intervalo ou escolha outra data."
            ),
            "minutos_por_dia": plano.minutos_por_dia,
            "dias": 0,
        }

    minutos = carga_do_dia_mais_cheio(fila, datas, plano.minutos_padrao_topico)
    if plano.minutos_por_dia != minutos:
        plano.minutos_por_dia = minutos
        plano.save(update_fields=["minutos_por_dia", "atualizado_em"])
    return {"erro": None, "minutos_por_dia": minutos, "dias": len(datas)}


def gerar_cronograma(*, regenerar: bool = True, a_partir_de: date | None = None) -> dict:
    plano = PlanoEstudo.get()
    info = atualizar_carga_diaria(plano, a_partir_de=a_partir_de)
    if info.get("erro"):
        return {
            "erro": info["erro"],
            "itens": 0,
            "minutos_total": 0,
            "data_fim": None,
            "dias_estudo": 0,
            "minutos_por_dia": info["minutos_por_dia"],
        }

    fila = ordenar_topicos(
        list(topicos_pendentes_cronograma()), plano.modo_distribuicao
    )
    inicio = _inicio_plano(plano, a_partir_de)
    datas = listar_dias_estudo(inicio, plano.data_meta, plano.dias_estudo)
    itens = distribuir_nos_dias(
        fila, plano.minutos_por_dia or 1, datas, plano.minutos_padrao_topico
    )
    if itens is None:
        return {
            "erro": "Não foi possível encaixar as aulas até a data da meta.",
            "itens": 0,
            "minutos_total": 0,
            "data_fim": None,
            "dias_estudo": 0,
            "minutos_por_dia": plano.minutos_por_dia,
        }

    with transaction.atomic():
        if regenerar:
            ItemCronograma.objects.filter(concluido=False).delete()

        criados = 0
        minutos_total = 0
        for data, ordem, topico, minutos in itens:
            if not regenerar and ItemCronograma.objects.filter(
                topico=topico, concluido=False
            ).exists():
                continue
            ItemCronograma.objects.update_or_create(
                data=data,
                topico=topico,
                defaults={
                    "minutos_planejados": minutos,
                    "ordem": ordem,
                    "concluido": False,
                },
            )
            criados += 1
            minutos_total += minutos

        plano.gerado_em = timezone.now()
        update_fields = ["gerado_em", "atualizado_em"]
        if plano.modo_distribuicao == "ciclo":
            plano.ciclo_ponteiro = 0
            update_fields.append("ciclo_ponteiro")
        plano.save(update_fields=update_fields)

    fim = (
        ItemCronograma.objects.filter(concluido=False)
        .order_by("-data")
        .values_list("data", flat=True)
        .first()
    )
    return {
        "erro": None,
        "itens": criados,
        "minutos_total": minutos_total,
        "data_fim": fim,
        "dias_estudo": len({data for data, *_resto in itens}),
        "minutos_por_dia": plano.minutos_por_dia,
    }


def sincronizar_conclusao(topico: Topico, *, redistribuir: bool = True) -> dict | None:
    """Marca o item no cronograma e redistribui o restante a partir de hoje."""
    ItemCronograma.objects.filter(topico=topico, concluido=False).update(concluido=True)
    avancar_ponteiro_ciclo(topico)
    if topico.status not in (Topico.Status.COMPLETO, Topico.Status.REVISADO):
        return None
    if not redistribuir:
        return None
    if not ItemCronograma.objects.exists():
        return None
    if not PlanoEstudo.get().data_meta:
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
    inicio = max(plano.data_inicio or hoje, hoje)
    dias_meta = (
        listar_dias_estudo(inicio, plano.data_meta, plano.dias_estudo)
        if plano.data_meta
        else []
    )
    return {
        "plano": plano,
        "minutos_restantes": minutos,
        "horas_restantes": round(minutos / 60, 1),
        "data_fim": fim,
        "data_meta": plano.data_meta,
        "minutos_por_dia_fmt": formatar_minutos(plano.minutos_por_dia),
        "dias_restantes": len(set(qs.values_list("data", flat=True))),
        "dias_ate_meta": len(dias_meta),
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
