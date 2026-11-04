"""Domínio de planejamento de ingressos, sem chamadas a plataformas ou cobrança.

Todos os dados de pessoas são referências internas. Este módulo não manipula
CPF, biometria, senhas nem dados brutos de cartões.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Membership(Enum):
    SOCIO = "socio"
    PUBLICO_GERAL = "publico_geral"


class SalePhase(Enum):
    FECHADA = "fechada"
    SOCIOS = "socios"
    PUBLICO_GERAL = "publico_geral"


@dataclass(frozen=True)
class Attendee:
    """Titular de ingresso com documentação verificada em fluxo separado."""

    person_id: str
    club: str
    membership: Membership
    plan: str | None
    identity_verified: bool
    biometric_verified: bool
    authorized_to_purchase: bool


@dataclass(frozen=True)
class MatchOffer:
    """Regras disponibilizadas/confirmadas por integração autorizada."""

    event_id: str
    platform: str
    sales_phase: SalePhase
    available_sections: frozenset[str]
    max_tickets_per_order: int
    requires_biometric: bool
    allows_guest_tickets: bool
    max_guests_per_member: int
    commerce_api_authorized: bool
    observed_at: datetime


@dataclass(frozen=True)
class PurchaseIntent:
    """Autorização prévia de compra para conjunto de pessoas e limite financeiro."""

    event_id: str
    buyer_person_id: str
    attendee_ids: tuple[str, ...]
    section: str
    max_unit_price: Decimal
    max_total_price: Decimal
    offered_unit_price: Decimal
    offered_total_price: Decimal
    # Referência opaca provida pelo processador/parceiro (nunca PAN/CVV).
    payment_token_reference: str | None
    authorized_until: datetime
    idempotency_key: str


def preflight(intent: PurchaseIntent, offer: MatchOffer, people: dict[str, Attendee], now: datetime) -> tuple[str, ...]:
    """Retorna bloqueios; zero bloqueios NÃO executa uma compra automaticamente.

    Um adaptador oficial ainda deve validar as regras de bilheteria, aplicar
    idempotência persistente, consultar disponibilidade e confirmar pagamento.
    """
    errors: list[str] = []
    if now.tzinfo is None or offer.observed_at.tzinfo is None or intent.authorized_until.tzinfo is None:
        return ("datas_sem_fuso",)
    if offer.event_id != intent.event_id or not intent.event_id:
        errors.append("evento_incompativel")
    if offer.sales_phase is SalePhase.FECHADA:
        errors.append("venda_fechada")
    if not offer.commerce_api_authorized:
        errors.append("integracao_comercial_nao_autorizada")
    if not intent.idempotency_key.strip():
        errors.append("sem_idempotencia")
    if not intent.payment_token_reference or not intent.payment_token_reference.strip():
        errors.append("sem_token_pagamento")
    if now >= intent.authorized_until:
        errors.append("autorizacao_expirada")
    if not intent.section.strip() or intent.section not in offer.available_sections:
        errors.append("setor_indisponivel")
    if not intent.attendee_ids:
        errors.append("sem_torcedores")
    if len(set(intent.attendee_ids)) != len(intent.attendee_ids):
        errors.append("torcedor_duplicado")
    if offer.max_tickets_per_order < 1 or len(intent.attendee_ids) > offer.max_tickets_per_order:
        errors.append("limite_ingressos_excedido")
    if any(
        p < 0 or not p.is_finite()
        for p in (intent.max_unit_price, intent.max_total_price, intent.offered_unit_price, intent.offered_total_price)
    ):
        errors.append("valor_invalido")
    else:
        if intent.offered_unit_price > intent.max_unit_price or intent.offered_total_price > intent.max_total_price:
            errors.append("limite_financeiro_excedido")
        if intent.offered_total_price < intent.offered_unit_price * len(intent.attendee_ids):
            errors.append("total_inconsistente")
    if intent.buyer_person_id not in intent.attendee_ids:
        errors.append("comprador_fora_do_grupo")
    buyer = people.get(intent.buyer_person_id)
    if buyer is None:
        errors.append("comprador_desconhecido")
    else:
        if buyer.membership is Membership.SOCIO and not buyer.plan:
            errors.append("plano_socio_ausente")
        if offer.sales_phase is SalePhase.SOCIOS and buyer.membership is not Membership.SOCIO:
            errors.append("prioridade_exclusiva_socio")
        if len(intent.attendee_ids) > 1:
            if buyer.membership is Membership.SOCIO:
                if not offer.allows_guest_tickets or len(intent.attendee_ids) - 1 > offer.max_guests_per_member:
                    errors.append("convidados_nao_elegiveis")
            else:
                if not offer.allows_guest_tickets:
                    errors.append("compra_multipla_nao_permitida")
    for person_id in intent.attendee_ids:
        attendee = people.get(person_id)
        if attendee is None:
            errors.append("torcedor_desconhecido")
            continue
        if not attendee.authorized_to_purchase:
            errors.append("sem_consentimento")
        if not attendee.identity_verified:
            errors.append("identidade_nao_verificada")
        if offer.requires_biometric and not attendee.biometric_verified:
            errors.append("biometria_pendente")
    return tuple(dict.fromkeys(errors))
