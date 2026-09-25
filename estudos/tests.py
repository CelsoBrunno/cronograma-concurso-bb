from datetime import date

from django.test import Client, TestCase

from estudos import cronograma as crono
from estudos.models import Disciplina, ItemCronograma, PlanoEstudo, Topico


class CargaDiariaTests(TestCase):
    def setUp(self):
        self.disciplina = Disciplina.objects.create(nome="Português", ordem=1)
        self.plano = PlanoEstudo.get()
        self.plano.dias_estudo = [0, 1, 2, 3, 4, 5, 6]
        self.plano.data_inicio = date(2026, 9, 28)
        self.plano.data_meta = date(2026, 9, 30)
        self.plano.minutos_extra_questoes = 0
        self.plano.minutos_padrao_topico = 40
        self.plano.modo_distribuicao = "sequencial"
        self.plano.save()

    def _aulas(self, minutos: list[int]) -> None:
        for indice, duracao in enumerate(minutos):
            Topico.objects.create(
                disciplina=self.disciplina,
                titulo=f"Aula {indice}",
                ordem=indice,
                minutos_video=duracao,
                minutos_estimados=duracao,
            )

    def test_uma_aula_por_dia_quando_ha_dias_suficientes(self):
        self._aulas([50, 50, 50])
        info = crono.atualizar_carga_diaria(self.plano, a_partir_de=date(2026, 9, 28))
        self.assertIsNone(info["erro"])
        self.assertEqual(info["minutos_por_dia"], 50)
        self.assertEqual(info["dias"], 3)

    def test_junta_aulas_quando_faltam_dias(self):
        self.plano.data_meta = date(2026, 9, 29)
        self.plano.save()
        self._aulas([50, 50, 50])
        info = crono.atualizar_carga_diaria(self.plano, a_partir_de=date(2026, 9, 28))
        self.assertEqual(info["minutos_por_dia"], 100)

    def test_aula_longa_define_a_carga_do_dia(self):
        self.plano.data_meta = date(2026, 9, 29)
        self.plano.save()
        self._aulas([100, 10, 10])
        info = crono.atualizar_carga_diaria(self.plano, a_partir_de=date(2026, 9, 28))
        self.assertEqual(info["minutos_por_dia"], 100)

    def test_cronograma_nao_passa_da_meta(self):
        self.plano.data_meta = date(2026, 9, 29)
        self.plano.save()
        self._aulas([50, 50, 50])
        resultado = crono.gerar_cronograma(
            regenerar=True, a_partir_de=date(2026, 9, 28)
        )
        self.assertIsNone(resultado["erro"])
        self.assertLessEqual(resultado["data_fim"], date(2026, 9, 29))
        self.assertEqual(resultado["minutos_por_dia"], 100)
        maior_dia = 0
        for data in {date(2026, 9, 28), date(2026, 9, 29)}:
            total = sum(
                ItemCronograma.objects.filter(data=data).values_list(
                    "minutos_planejados", flat=True
                )
            )
            maior_dia = max(maior_dia, total)
        self.assertLessEqual(maior_dia, 100)
        self.assertEqual(ItemCronograma.objects.count(), 3)

    def test_sem_dia_de_estudo_no_intervalo(self):
        self.plano.dias_estudo = [6]
        self.plano.save()
        self._aulas([40])
        info = crono.atualizar_carga_diaria(self.plano, a_partir_de=date(2026, 9, 28))
        self.assertIn("Não há dia de estudo", info["erro"])

    def test_soma_extra_de_questoes(self):
        self.plano.minutos_extra_questoes = 15
        self.plano.data_meta = date(2026, 9, 28)
        self.plano.save()
        self._aulas([30])
        info = crono.atualizar_carga_diaria(self.plano, a_partir_de=date(2026, 9, 28))
        self.assertEqual(info["minutos_por_dia"], 45)


class CronogramaViewTests(TestCase):
    def test_formulario_calcula_carga_a_partir_da_data(self):
        disciplina = Disciplina.objects.create(nome="Matemática", ordem=1)
        for indice, duracao in enumerate([40, 40, 40, 40]):
            Topico.objects.create(
                disciplina=disciplina,
                titulo=f"Aula {indice}",
                ordem=indice,
                minutos_video=duracao,
                minutos_estimados=duracao,
            )
        cliente = Client()
        pagina = cliente.get("/cronograma/")
        self.assertContains(pagina, "Encerrar em")
        self.assertNotContains(pagina, "Minutos por dia")

        resposta = cliente.post(
            "/cronograma/",
            {
                "acao": "gerar",
                "minutos_padrao_topico": "40",
                "minutos_extra_questoes": "0",
                "data_inicio": "2026-09-28",
                "data_meta": "2026-09-29",
                "modo_distribuicao": "sequencial",
                "dias_estudo": ["0", "1", "2", "3", "4", "5", "6"],
            },
        )
        self.assertEqual(resposta.status_code, 302)
        plano = PlanoEstudo.get()
        self.assertEqual(plano.data_meta, date(2026, 9, 29))
        self.assertEqual(plano.minutos_por_dia, 80)
        self.assertFalse(
            ItemCronograma.objects.filter(data__gt=date(2026, 9, 29)).exists()
        )


class CicloEstudosTests(TestCase):
    def setUp(self):
        self.ban = Disciplina.objects.create(nome="Conhecimentos Bancários", ordem=1, peso=1)
        self.port = Disciplina.objects.create(nome="Língua Portuguesa", ordem=2, peso=3)
        self.mat = Disciplina.objects.create(nome="Matemática", ordem=3, peso=4)
        for disc, n in ((self.ban, 4), (self.port, 3), (self.mat, 2)):
            for i in range(n):
                Topico.objects.create(
                    disciplina=disc,
                    titulo=f"{disc.nome} {i}",
                    ordem=i,
                    minutos_video=30,
                    minutos_estimados=30,
                )

    def test_ciclo_intercala_com_mais_blocos_para_prioridade(self):
        fila = crono.ordenar_ciclo(list(Topico.objects.select_related("disciplina")))
        self.assertEqual(len(fila), 9)
        # Nos primeiros itens, Bancários deve aparecer antes de esgotar as outras.
        primeiros = [t.disciplina_id for t in fila[:6]]
        self.assertIn(self.ban.id, primeiros)
        self.assertIn(self.port.id, primeiros)
        # Não pode ser "todas de Bancários primeiro" (modo prioridade).
        self.assertNotEqual(
            [t.disciplina_id for t in fila[:4]],
            [self.ban.id] * 4,
        )

    def test_slots_maior_para_peso_menor(self):
        self.assertGreater(crono.slots_disciplina(1), crono.slots_disciplina(4))
        self.assertGreaterEqual(crono.slots_disciplina(9), 1)

    def test_gerar_cronograma_modo_ciclo(self):
        plano = PlanoEstudo.get()
        plano.dias_estudo = [0, 1, 2, 3, 4, 5, 6]
        plano.data_inicio = date(2026, 9, 28)
        plano.data_meta = date(2026, 10, 10)
        plano.modo_distribuicao = "ciclo"
        plano.minutos_extra_questoes = 0
        plano.save()
        resultado = crono.gerar_cronograma(regenerar=True, a_partir_de=date(2026, 9, 28))
        self.assertIsNone(resultado["erro"])
        self.assertEqual(resultado["itens"], 9)
        self.assertEqual(PlanoEstudo.get().ciclo_ponteiro, 0)
