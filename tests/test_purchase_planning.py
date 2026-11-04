"""Regressões do planejamento multiportador; não faz chamadas externas."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from bot.purchase_planning import Attendee, MatchOffer, Membership, PurchaseIntent, SalePhase, preflight

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def attendee(person_id, membership=Membership.SOCIO, biometric_verified=True, consent=True):
    return Attendee(person_id, "Vasco", membership, "Gigante" if membership is Membership.SOCIO else None, True, biometric_verified, consent)


def offer(**overrides):
    params = dict(event_id="jogo-1", platform="eleven", sales_phase=SalePhase.SOCIOS,
                  available_sections=frozenset({"Arquibancada", "Social"}), max_tickets_per_order=4,
                  requires_biometric=True, allows_guest_tickets=True, max_guests_per_member=3,
                  commerce_api_authorized=True, observed_at=NOW)
    params.update(overrides)
    return MatchOffer(**params)


def intent(**overrides):
    params = dict(event_id="jogo-1", buyer_person_id="a", attendee_ids=("a", "b"),
                  section="Arquibancada", max_unit_price=Decimal("150"), max_total_price=Decimal("350"),
                  offered_unit_price=Decimal("100"), offered_total_price=Decimal("220"),
                  payment_token_reference="token-opaco", authorized_until=NOW + timedelta(days=1),
                  idempotency_key="intent-jogo-1-a")
    params.update(overrides)
    return PurchaseIntent(**params)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.people = {"a": attendee("a"), "b": attendee("b", Membership.PUBLICO_GERAL)}

    def test_socio_com_convidado_preparado(self):
        self.assertEqual(preflight(intent(), offer(), self.people, NOW), ())

    def test_publico_geral_antes_da_onda(self):
        request = intent(buyer_person_id="b", attendee_ids=("b",))
        self.assertIn("prioridade_exclusiva_socio", preflight(request, offer(), self.people, NOW))

    def test_publico_geral_na_onda_correta(self):
        request = intent(buyer_person_id="b", attendee_ids=("b",))
        self.assertEqual(preflight(request, offer(sales_phase=SalePhase.PUBLICO_GERAL), self.people, NOW), ())

    def test_grupo_nao_pode_conter_duplicatas(self):
        self.assertIn("torcedor_duplicado", preflight(intent(attendee_ids=("a", "a")), offer(), self.people, NOW))

    def test_sem_consentimento(self):
        self.people["b"] = attendee("b", Membership.PUBLICO_GERAL, consent=False)
        self.assertIn("sem_consentimento", preflight(intent(), offer(), self.people, NOW))

    def test_biometria_pendente(self):
        self.people["b"] = attendee("b", biometric_verified=False)
        self.assertIn("biometria_pendente", preflight(intent(), offer(), self.people, NOW))

    def test_limite_de_grupo(self):
        self.assertIn("limite_ingressos_excedido", preflight(intent(), offer(max_tickets_per_order=1), self.people, NOW))

    def test_convidados_nao_autorizados(self):
        self.assertIn("convidados_nao_elegiveis", preflight(intent(), offer(allows_guest_tickets=False), self.people, NOW))

    def test_comercio_nao_autorizado_bloqueia(self):
        self.assertIn("integracao_comercial_nao_autorizada", preflight(intent(), offer(commerce_api_authorized=False), self.people, NOW))

    def test_pagamento_ausente_bloqueia(self):
        self.assertIn("sem_token_pagamento", preflight(intent(payment_token_reference=None), offer(), self.people, NOW))

    def test_orcamento_bloqueia_custo_total(self):
        self.assertIn("limite_financeiro_excedido", preflight(intent(max_total_price=Decimal("200")), offer(), self.people, NOW))

    def test_autorizacao_expirada(self):
        self.assertIn("autorizacao_expirada", preflight(intent(authorized_until=NOW), offer(), self.people, NOW))

    def test_identidade_nao_comprovada(self):
        self.people["b"] = Attendee("b", "Vasco", Membership.PUBLICO_GERAL, None, False, True, True)
        self.assertIn("identidade_nao_verificada", preflight(intent(), offer(), self.people, NOW))

    def test_compra_multipla_publico_geral_depende_do_evento(self):
        self.people["a"] = attendee("a", Membership.PUBLICO_GERAL)
        self.assertIn("compra_multipla_nao_permitida", preflight(intent(), offer(sales_phase=SalePhase.PUBLICO_GERAL, allows_guest_tickets=False), self.people, NOW))


if __name__ == "__main__":
    unittest.main()
