from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone


class Disciplina(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    ordem = models.PositiveIntegerField(default=0)
    # Menor = maior prioridade na prova (1 primeiro).
    peso = models.PositiveIntegerField(default=50)

    class Meta:
        ordering = ["peso", "ordem", "nome"]

    def __str__(self) -> str:
        return self.nome

    @property
    def total_topicos(self) -> int:
        return self.topicos.count()

    @property
    def topicos_cobertos(self) -> int:
        return self.topicos.filter(
            status__in=[Topico.Status.COMPLETO, Topico.Status.REVISADO]
        ).count()

    @property
    def percentual_coberto(self) -> float:
        total = self.total_topicos
        if not total:
            return 0.0
        return round(100.0 * self.topicos_cobertos / total, 1)


class Topico(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ESTUDANDO = "estudando", "Estudando"
        COMPLETO = "completo", "Completo"
        REVISADO = "revisado", "Revisado"

    disciplina = models.ForeignKey(
        Disciplina, on_delete=models.CASCADE, related_name="topicos"
    )
    titulo = models.CharField(max_length=300)
    ordem = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDENTE, db_index=True
    )
    estudado_em = models.DateTimeField(null=True, blank=True)
    proxima_revisao = models.DateField(null=True, blank=True, db_index=True)
    intervalo_dias = models.PositiveIntegerField(default=0)
    total_acertos = models.PositiveIntegerField(default=0)
    total_erros = models.PositiveIntegerField(default=0)
    minutos_estudados = models.PositiveIntegerField(default=0)
    # Duração real do vídeo (Gran) + estimativa total (vídeo + questões).
    minutos_video = models.PositiveIntegerField(default=0)
    minutos_estimados = models.PositiveIntegerField(default=40)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["disciplina__ordem", "ordem", "id"]
        unique_together = [("disciplina", "titulo")]

    def __str__(self) -> str:
        return f"{self.disciplina.nome}: {self.titulo}"

    @property
    def total_questoes(self) -> int:
        return self.total_acertos + self.total_erros

    @property
    def aproveitamento(self) -> float | None:
        total = self.total_questoes
        if not total:
            return None
        return round(100.0 * self.total_acertos / total, 1)

    @property
    def esta_vencido(self) -> bool:
        if self.proxima_revisao is None:
            return False
        return self.proxima_revisao <= timezone.localdate()

    def registrar_estudo(
        self,
        *,
        segundos: int,
        acertos: int = 0,
        erros: int = 0,
        novo_status: str | None = None,
    ) -> None:
        minutos = max(0, segundos) // 60
        self.minutos_estudados += minutos
        self.total_acertos += max(0, acertos)
        self.total_erros += max(0, erros)
        self.estudado_em = timezone.now()

        # Suaviza a estimativa com o tempo real da sessão (mín. 10 min).
        if minutos >= 5:
            base = self.minutos_estimados or 40
            self.minutos_estimados = max(10, round((base * 0.6) + (minutos * 0.4)))

        if novo_status:
            self.status = novo_status
        elif self.status == self.Status.PENDENTE:
            self.status = self.Status.ESTUDANDO

        self._atualizar_srs(acertos=acertos, erros=erros)
        self.save()

    def _atualizar_srs(self, *, acertos: int, erros: int) -> None:
        hoje = timezone.localdate()
        total = acertos + erros
        taxa = (acertos / total) if total else None

        if self.status in (self.Status.COMPLETO, self.Status.REVISADO):
            if taxa is not None and taxa < 0.6:
                self.intervalo_dias = 1
            elif self.intervalo_dias <= 0:
                self.intervalo_dias = 1
            else:
                self.intervalo_dias = min(self.intervalo_dias * 2, 30)
                if taxa is not None and taxa >= 0.8 and self.status == self.Status.COMPLETO:
                    self.status = self.Status.REVISADO
            self.proxima_revisao = hoje + timedelta(days=self.intervalo_dias)
        elif self.status == self.Status.ESTUDANDO and total > 0:
            self.proxima_revisao = hoje + timedelta(days=1)
            self.intervalo_dias = 1


class SessaoEstudo(models.Model):
    disciplina = models.ForeignKey(
        Disciplina,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessoes",
    )
    topico = models.ForeignKey(
        Topico,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessoes",
    )
    iniciada_em = models.DateTimeField(default=timezone.now)
    finalizada_em = models.DateTimeField(null=True, blank=True)
    segundos_liquidos = models.PositiveIntegerField(default=0)
    acertos = models.PositiveIntegerField(default=0)
    erros = models.PositiveIntegerField(default=0)
    notas = models.TextField(blank=True)
    ativa = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-iniciada_em"]

    def __str__(self) -> str:
        alvo = self.topico or self.disciplina or "livre"
        return f"Sessão {self.pk} — {alvo}"

    @property
    def minutos(self) -> Decimal:
        return Decimal(self.segundos_liquidos) / Decimal(60)

    @property
    def horas_formatadas(self) -> str:
        total = self.segundos_liquidos
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def finalizar(
        self,
        *,
        segundos_liquidos: int,
        acertos: int = 0,
        erros: int = 0,
        notas: str = "",
        novo_status: str | None = None,
    ) -> None:
        self.segundos_liquidos = max(0, segundos_liquidos)
        self.acertos = max(0, acertos)
        self.erros = max(0, erros)
        self.notas = notas.strip()
        self.finalizada_em = timezone.now()
        self.ativa = False
        self.save()

        if self.topico_id:
            self.topico.registrar_estudo(
                segundos=self.segundos_liquidos,
                acertos=self.acertos,
                erros=self.erros,
                novo_status=novo_status,
            )


class PlanoEstudo(models.Model):
    """Configuração única do cronograma (singleton id=1)."""

    minutos_por_dia = models.PositiveIntegerField(
        default=120,
        help_text="Calculado a partir da data da meta: minutos do dia mais cheio",
    )
    # Segunda=0 ... Domingo=6 (igual a date.weekday())
    dias_estudo = models.JSONField(default=list)
    minutos_padrao_topico = models.PositiveIntegerField(
        default=40,
        help_text="Fallback quando a aula não tem duração do vídeo",
    )
    minutos_extra_questoes = models.PositiveIntegerField(
        default=15,
        help_text="Minutos extras por aula para resolver questões",
    )
    incluir_tempo_questoes = models.BooleanField(
        default=True,
        help_text="Se desmarcado, o cronograma usa só a duração do vídeo",
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_meta = models.DateField(
        null=True,
        blank=True,
        help_text="Data em que os tópicos pendentes devem estar concluídos",
    )
    modo_distribuicao = models.CharField(
        max_length=20,
        choices=[
            ("ciclo", "Ciclo de estudos (recomendado)"),
            ("prioridade", "Prioridade na prova (uma matéria por vez)"),
            ("intercalar", "Intercalar 1 a 1"),
            ("sequencial", "Ordem do edital"),
        ],
        default="ciclo",
    )
    # Posição no ciclo: ao concluir um tópico, avança; "Estudar agora" retoma daqui.
    ciclo_ponteiro = models.PositiveIntegerField(default=0)
    gerado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plano de estudo"
        verbose_name_plural = "Plano de estudo"

    def __str__(self) -> str:
        return "Plano de estudo"

    @classmethod
    def get(cls) -> "PlanoEstudo":
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "dias_estudo": [0, 1, 2, 3, 4, 5],  # seg–sáb
                "data_inicio": timezone.localdate(),
            },
        )
        if not obj.dias_estudo:
            obj.dias_estudo = [0, 1, 2, 3, 4, 5]
            obj.save(update_fields=["dias_estudo"])
        return obj

    @property
    def horas_por_dia(self) -> float:
        return round(self.minutos_por_dia / 60, 2)


class ItemCronograma(models.Model):
    data = models.DateField(db_index=True)
    topico = models.ForeignKey(
        Topico, on_delete=models.CASCADE, related_name="itens_cronograma"
    )
    minutos_planejados = models.PositiveIntegerField(default=40)
    ordem = models.PositiveIntegerField(default=0)
    concluido = models.BooleanField(default=False)

    class Meta:
        ordering = ["data", "ordem", "id"]
        unique_together = [("data", "topico")]

    def __str__(self) -> str:
        return f"{self.data} — {self.topico.titulo}"
