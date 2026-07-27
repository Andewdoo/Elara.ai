from decimal import Decimal
from datetime import UTC, datetime
from uuid import uuid4
import asyncio

import pytest

from scoring.formulas import (
    EvidenceQuality, WeightedEvidence, article_factual_accuracy, context_completeness,
    evidence_balance, evidence_quality, quote_fidelity, source_independence,
    verdict_confidence,
)
from scoring.labels import InsufficientEvidence, article_label, final_claim_label, support_label
from scoring.service import DeterministicScoringService
from research.extension_errors import WorkflowExtensionError
from agents.schemas import (AtomicClaimOutput, ClaimAmbiguityOutput, ClaimKind, ConfidenceIssue, ContextIssue,
    EvidenceClassificationItemOutput, EvidenceQualityOutput, EvidenceStance,
    FactCheckability, Importance, QuoteFidelityComponentsOutput)
from graph.state import CandidateSource, PassageRecord, ResearchDepth, VerificationState
from graph.runtime import SqlWorkflowStateWriter
from graph.state import WorkflowStage
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database.base import Base
from app.models import (AccessStatus, AtomicClaim, Calculation, EvidenceItem, InputType,
    RunSource, RunStatus, Source, SourcePassage, SourceSnapshot, SourceType, User, VerificationRun)


def test_published_evidence_quality_weight_and_balance_example():
    quality = evidence_quality(EvidenceQuality(
        Decimal("1"), Decimal("1"), Decimal("0.9"), Decimal("0.8"), Decimal("0.7"), Decimal("0.6")
    ))
    assert quality == Decimal("0.88")

    balance = evidence_balance([
        WeightedEvidence(Decimal("-1"), Decimal("0.976"), Decimal("1")),
        WeightedEvidence(Decimal("0.5"), Decimal("0.8"), Decimal("0.35")),
        WeightedEvidence(Decimal("0.5"), Decimal("0.75"), Decimal("0")),
    ])
    assert balance.supporting == Decimal("0.1400")
    assert balance.contradicting == Decimal("0.976")
    assert balance.support.quantize(Decimal("0.1")) == Decimal("12.5")
    assert balance.consistency.quantize(Decimal("0.1")) == Decimal("74.9")


def test_confidence_independence_quote_context_and_article_formulas():
    assert verdict_confidence(coverage=100, average_quality=90, independence=55,
                              consistency=75, primary_access=100, penalties=[Decimal("10")]) == Decimal("74.75")
    assert source_independence(origin_diversity=100, primary_diversity=80,
                               organizational_diversity=50, method_diversity=40) == Decimal("76.00")
    assert quote_fidelity(wording=100, speaker_identity=80, completeness=60,
                          sequence_integrity=40, translation_accuracy=20) == Decimal("71.00")
    assert quote_fidelity(wording=100, speaker_identity=80, completeness=60,
                          sequence_integrity=40) == Decimal("76.66666666666666666666666667")
    assert context_completeness([Decimal("20"), Decimal("25")]) == Decimal("55")
    assert context_completeness([Decimal("80"), Decimal("30")]) == Decimal("0")
    assert article_factual_accuracy([(Decimal("100"), 3), (Decimal("50"), 2), (Decimal("0"), 1)]) == Decimal("66.66666666666666666666666667")


def test_zero_evidence_is_not_a_neutral_support_score():
    balance = evidence_balance([])
    assert balance.support is None
    assert balance.consistency is None


def test_inputs_outside_published_ranges_are_rejected():
    with pytest.raises(ValueError):
        EvidenceQuality(Decimal("1.1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))
    with pytest.raises(ValueError):
        context_completeness([Decimal("-1")])


@pytest.mark.parametrize("value,label", [(90, "Supported"), (75, "Mostly supported"),
    (60, "Leaning supported"), (40, "Mixed or unresolved"), (26, "Leaning refuted"),
    (11, "Mostly refuted"), (10, "Refuted")])
def test_support_label_boundaries(value, label):
    assert support_label(Decimal(value)) == label


def test_insufficient_context_and_essential_claim_gates_override_numeric_label():
    sparse = InsufficientEvidence(total_below_minimum=True)
    assert final_claim_label(support=Decimal("99"), confidence=Decimal("99"),
                             context=Decimal("100"), insufficient=sparse) == "Insufficient evidence"
    assert final_claim_label(support=Decimal("80"), confidence=Decimal("80"),
                             context=Decimal("49"), insufficient=InsufficientEvidence()) == "Technically supported but misleading"
    assert article_label(factual_accuracy=Decimal("95"), insufficient=InsufficientEvidence(),
                         strongly_refuted_essential_claim=True) == "Mostly supported"
    assert article_label(factual_accuracy=Decimal("95"), insufficient=InsufficientEvidence(),
                         strongly_refuted_essential_claim=False,
                         verdict_confidence=Decimal("34")) == "Insufficient evidence"
    assert article_label(factual_accuracy=Decimal("80"), insufficient=InsufficientEvidence(),
                         strongly_refuted_essential_claim=False,
                         context=Decimal("49")) == "Technically supported but misleading"


def test_state_service_scores_only_accepted_evidence_and_emits_audit_records():
    passage_id = str(uuid4())
    state = VerificationState(
        run_id=uuid4(), user_id=uuid4(), research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        claims=[AtomicClaimOutput(claim_ref="c1", text="The value rose", claim_kind=ClaimKind.FACTUAL,
            importance=Importance.ESSENTIAL, importance_weight=3, fact_checkability=FactCheckability.FACT_CHECKABLE,
            verification_scope="Whether the value rose")],
        candidate_sources=[CandidateSource(source_ref="s1", url="https://records.example/value",
            domain="records.example", source_type="PRIMARY", selection_reason="original record")],
        passages=[PassageRecord(passage_id=passage_id, source_ref="s1", snapshot_id=str(uuid4()),
            text="The value rose.", text_hash="abc", extraction_certainty=Decimal("1"))],
        source_dependency_multipliers={"s1": Decimal("1")},
        evidence=[EvidenceClassificationItemOutput(claim_ref="c1", passage_id=passage_id,
            stance=EvidenceStance.STRONGLY_SUPPORTS,
            quality=EvidenceQualityOutput(relevance=1, directness=1, claim_specific_authority=1,
                transparency=1, temporal_fit=1, extraction_certainty=1),
            entity_match=True, time_period_match=True, quotation_or_number_located=True)],
    )
    result = asyncio.run(DeterministicScoringService().process(state))

    assert result.claim_scores[0].evidence_support == 100
    assert result.claim_scores[0].final_label == "Supported"
    assert result.scores.article_factual_accuracy == 100
    assert result.scores.final_label == "Supported"
    assert {"evidence_quality", "adjusted_evidence_weight", "evidence_support",
            "verdict_confidence", "source_independence", "article_factual_accuracy",
            "research_coverage", "context_completeness", "final_label"} <= {
                row.formula_name for row in result.calculations
            }
    coverage = next(
        row for row in result.calculations if row.formula_name == "research_coverage"
    )
    assert coverage.result == {
        "adequate_evidence": "100",
        "insufficient_evidence": "0",
        "inaccessible_source_impact": "0",
    }
    assert all(row.formula_text and row.decimal_context and row.audit_status for row in result.calculations)


def test_scoring_requires_explicit_claim_and_evidence_inputs():
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
    )

    with pytest.raises(WorkflowExtensionError) as caught:
        asyncio.run(DeterministicScoringService().process(state))

    assert caught.value.code == "SCORING_CLAIMS_REQUIRED"


def test_state_service_applies_typed_context_confidence_and_quote_inputs():
    passage_id = str(uuid4())
    state = VerificationState(
        run_id=uuid4(), user_id=uuid4(), research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        claims=[AtomicClaimOutput(claim_ref="quote", text="The speaker said it would happen",
            claim_kind=ClaimKind.QUOTATION, importance=Importance.ESSENTIAL,
            importance_weight=3, fact_checkability=FactCheckability.FACT_CHECKABLE,
            verification_scope="Verify wording and context")],
        candidate_sources=[CandidateSource(source_ref="recording", url="https://records.example/video",
            domain="records.example", source_type="PRIMARY", selection_reason="original recording")],
        passages=[PassageRecord(passage_id=passage_id, source_ref="recording",
            snapshot_id=str(uuid4()), text="It could happen if the policy fails.",
            text_hash="quote-hash", extraction_certainty=Decimal("1"))],
        source_dependency_multipliers={"recording": Decimal("1")},
        evidence=[EvidenceClassificationItemOutput(claim_ref="quote", passage_id=passage_id,
            stance=EvidenceStance.STRONGLY_SUPPORTS,
            quality=EvidenceQualityOutput(relevance=1, directness=1,
                claim_specific_authority=1, transparency=1, temporal_fit=1,
                extraction_certainty=1), entity_match=True, time_period_match=True,
            quotation_or_number_located=True,
            context_issues=[ContextIssue.CONDITIONAL_LANGUAGE_REMOVED,
                            ContextIssue.MATERIAL_QUALIFIER_OMITTED],
            confidence_issues=[ConfidenceIssue.TRANSLATION_UNCERTAIN],
            quote_fidelity=QuoteFidelityComponentsOutput(wording=.8, speaker_identity=1,
                completeness=.6, sequence_integrity=1, translation_accuracy=None))],
    )
    result = asyncio.run(DeterministicScoringService().process(state))

    assert result.claim_scores[0].context_completeness == 60
    assert result.scores.quote_fidelity == 83
    assert result.claim_scores[0].gates["context_issues"] == [
        "conditional_language_removed", "material_qualifier_omitted"]
    confidence_record = next(row for row in result.calculations
                             if row.formula_name == "verdict_confidence" and row.claim_ref == "quote")
    assert confidence_record.inputs["penalties"] == {
        "single_information_cluster": "15",
        "translation_uncertain": "10",
    }
    quote_record = next(row for row in result.calculations if row.formula_name == "quote_fidelity")
    assert quote_record.result == {"score": "83.33333333333333333333333333"}


def test_unresolved_key_fact_gate_is_applied_by_state_service():
    passage_id = str(uuid4())
    state = VerificationState(
        run_id=uuid4(), user_id=uuid4(), research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        claims=[AtomicClaimOutput(claim_ref="c1", text="A named person made the statement",
            claim_kind=ClaimKind.ATTRIBUTION, importance=Importance.ESSENTIAL,
            importance_weight=3, fact_checkability=FactCheckability.FACT_CHECKABLE,
            verification_scope="Resolve the speaker")],
        candidate_sources=[CandidateSource(source_ref="s1", url="https://records.example/item",
            domain="records.example", source_type="PRIMARY", selection_reason="record")],
        passages=[PassageRecord(passage_id=passage_id, source_ref="s1", snapshot_id=str(uuid4()),
            text="The statement appears here.", text_hash="key-fact", extraction_certainty=Decimal("1"))],
        source_dependency_multipliers={"s1": Decimal("1.00")},
        evidence=[EvidenceClassificationItemOutput(claim_ref="c1", passage_id=passage_id,
            stance=EvidenceStance.STRONGLY_SUPPORTS,
            quality=EvidenceQualityOutput(relevance=1, directness=1,
                claim_specific_authority=1, transparency=1, temporal_fit=1,
                extraction_certainty=1), entity_match=True, time_period_match=True,
            confidence_issues=[ConfidenceIssue.SPEAKER_OR_DATE_UNRESOLVED])],
    )
    result = asyncio.run(DeterministicScoringService().process(state))

    assert result.claim_scores[0].final_label == "Insufficient evidence"
    assert "key_definitions_dates_or_identities_unresolved" in result.claim_scores[0].gates["insufficient_evidence"]
    attribution = next(
        row
        for row in result.calculations
        if row.formula_name == "attribution_support" and row.claim_ref is None
    )
    assert attribution.result == {"score": "100"}


def _ambiguity_fixture(
    *,
    claim_text: str = "Meta stock price surpasses $600",
    ambiguity_owner: str = "meta",
    contradiction: bool = False,
    multiplier: Decimal = Decimal("1"),
    source_type: str = "PRIMARY",
) -> VerificationState:
    claims = [
        AtomicClaimOutput(
            claim_ref="meta",
            text=claim_text,
            claim_kind=ClaimKind.NUMERICAL,
            importance=Importance.ESSENTIAL,
            importance_weight=3,
            fact_checkability=FactCheckability.FACT_CHECKABLE,
            verification_scope="Verify the observed Meta stock price.",
        )
    ]
    if ambiguity_owner == "minor":
        claims.append(
            AtomicClaimOutput(
                claim_ref="minor",
                text="The price milestone uses an unstated trading session.",
                claim_kind=ClaimKind.FACTUAL,
                importance=Importance.MINOR,
                importance_weight=1,
                fact_checkability=FactCheckability.FACT_CHECKABLE,
                verification_scope="Identify the trading session.",
            )
        )
    source_ref = "source-1"
    passage_id = str(uuid4())
    evidence = [
        EvidenceClassificationItemOutput(
            claim_ref="meta",
            passage_id=passage_id,
            stance=EvidenceStance.STRONGLY_SUPPORTS,
            quality=EvidenceQualityOutput(
                relevance=1,
                directness=1,
                claim_specific_authority=1,
                transparency=1,
                temporal_fit=1,
                extraction_certainty=1,
            ),
            entity_match=True,
            time_period_match=True,
            quotation_or_number_located=True,
        )
    ]
    if contradiction:
        contradiction_passage_id = str(uuid4())
        evidence.append(
            EvidenceClassificationItemOutput(
                claim_ref="meta",
                passage_id=contradiction_passage_id,
                stance=EvidenceStance.STRONGLY_CONTRADICTS,
                quality=EvidenceQualityOutput(
                    relevance=1,
                    directness=1,
                    claim_specific_authority=1,
                    transparency=1,
                    temporal_fit=1,
                    extraction_certainty=1,
                ),
                entity_match=True,
                time_period_match=True,
                quotation_or_number_located=True,
            )
        )
    passages = [
        PassageRecord(
            passage_id=passage_id,
            source_ref=source_ref,
            snapshot_id=str(uuid4()),
            text="Meta closed above $600.",
            text_hash="meta-support",
            extraction_certainty=Decimal("1"),
        )
    ]
    if contradiction:
        passages.append(
            PassageRecord(
                passage_id=evidence[-1].passage_id,
                source_ref=source_ref,
                snapshot_id=str(uuid4()),
                text="Meta did not close above $600.",
                text_hash="meta-contradiction",
                extraction_certainty=Decimal("1"),
            )
        )
    return VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.1-ambiguity-gate",
        claims=claims,
        claim_ambiguities=[
            ClaimAmbiguityOutput(
                text="The price interpretation does not name a trading session.",
                claim_ref=ambiguity_owner,
            )
        ],
        candidate_sources=[
            CandidateSource(
                source_ref=source_ref,
                url="https://records.example/meta-price",
                domain="records.example",
                source_type=source_type,
                selection_reason="published market record",
            )
        ],
        passages=passages,
        source_dependency_multipliers={source_ref: multiplier},
        evidence=evidence,
    )


def test_owned_ambiguity_is_non_blocking_for_adequate_unopposed_support():
    first = asyncio.run(DeterministicScoringService().process(_ambiguity_fixture()))
    equivalent = asyncio.run(
        DeterministicScoringService().process(
            _ambiguity_fixture(claim_text="Meta stock surpasses $600")
        )
    )

    assert first.claim_scores[0].final_label == "Supported"
    assert first.scores.final_label == "Supported"
    assert equivalent.claim_scores[0].final_label == first.claim_scores[0].final_label
    assert equivalent.scores.final_label == first.scores.final_label
    assert first.claim_scores[0].gates["confidence_issues"] == [
        "essential_term_ambiguous",
        "single_information_cluster",
    ]
    ambiguity_gate = next(
        row for row in first.calculations
        if row.formula_name == "ambiguity_gate" and row.claim_ref == "meta"
    )
    assert ambiguity_gate.audit_status == "non_blocking"
    assert ambiguity_gate.result == {
        "adequate_accepted_evidence": True,
        "has_accepted_support": True,
        "no_accepted_material_contradiction": True,
        "non_blocking": True,
        "unresolved_key_facts": False,
    }
    assert Decimal(ambiguity_gate.inputs["contradiction_ratio"]) == 0
    assert ambiguity_gate.inputs["scoring_version"] == "1.3-qualified-ambiguity"
    assert "The price interpretation" not in str(ambiguity_gate.inputs)
    assert "reasoning" not in ambiguity_gate.inputs


@pytest.mark.parametrize(
    ("fixture", "expected_claim_label"),
    [
        (_ambiguity_fixture(contradiction=True), "Insufficient evidence"),
        (_ambiguity_fixture(multiplier=Decimal("0.35")), "Insufficient evidence"),
        (_ambiguity_fixture(source_type="OFFICIAL_SELF_REPORT"), "Insufficient evidence"),
    ],
)
def test_owned_ambiguity_keeps_existing_claim_safety_gates(
    fixture: VerificationState, expected_claim_label: str
):
    result = asyncio.run(DeterministicScoringService().process(fixture))

    assert result.claim_scores[0].final_label == expected_claim_label


def test_well_supported_generic_ambiguity_with_limited_counterevidence_is_qualified():
    state = _ambiguity_fixture(contradiction=True)
    qualified_claim = state.claims[0].model_copy(
        update={
            "text": "Apples are healthy",
            "claim_kind": ClaimKind.FACTUAL,
            "verification_scope": "Assess the health benefits of apples.",
        }
    )
    limited_counterevidence = state.evidence[1].model_copy(
        update={
            "stance": EvidenceStance.PARTIALLY_CONTRADICTS,
            "quality": EvidenceQualityOutput(
                relevance=Decimal("0.2"),
                directness=Decimal("0.2"),
                claim_specific_authority=Decimal("0.2"),
                transparency=Decimal("0.2"),
                temporal_fit=Decimal("0.2"),
                extraction_certainty=Decimal("0.2"),
            ),
            "confidence_issues": [ConfidenceIssue.SPEAKER_OR_DATE_UNRESOLVED],
        }
    )
    result = asyncio.run(
        DeterministicScoringService().process(
            state.model_copy(
                update={"claims": [qualified_claim], "evidence": [state.evidence[0], limited_counterevidence]}
            )
        )
    )

    claim = result.claim_scores[0]
    assert claim.evidence_support == 91
    assert claim.final_label == "Supported"
    assert result.scores.final_label == "Supported"
    ambiguity_gate = next(
        row for row in result.calculations
        if row.formula_name == "ambiguity_gate" and row.claim_ref == "meta"
    )
    assert ambiguity_gate.audit_status == "non_blocking"
    assert ambiguity_gate.result["no_accepted_material_contradiction"] is True
    assert Decimal(ambiguity_gate.inputs["contradiction_ratio"]) <= Decimal("0.15")


def test_owned_minor_claim_ambiguity_does_not_downgrade_essential_claim_or_article():
    result = asyncio.run(
        DeterministicScoringService().process(_ambiguity_fixture(ambiguity_owner="minor"))
    )

    essential = next(row for row in result.claim_scores if row.claim_ref == "meta")
    minor = next(row for row in result.claim_scores if row.claim_ref == "minor")
    assert essential.final_label == "Supported"
    assert result.scores.final_label == "Supported"
    assert minor.final_label == "Insufficient evidence"


def test_scoring_records_are_persisted_with_decimal_audit_metadata():
    passage_id, snapshot_id = uuid4(), uuid4()
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    with factory() as db:
        user = User(auth_provider="firebase", auth_subject="scoring-owner", email="scoring@example.test",
                    plan_tier="free", role="user", usage_limits={})
        db.add(user)
        db.flush()
        run = VerificationRun(user_id=user.id, input_type=InputType.CLAIM, research_depth="STANDARD",
            status=RunStatus.SCORING, submitted_text="The value rose", normalized_target={}, workflow_version="step-12-test")
        db.add(run)
        db.flush()
        claim = AtomicClaim(run_id=run.id, claim_text="The value rose", claim_type="factual",
            importance_weight=3, entities=[], locations=[], metrics=[], ambiguities=[], fact_checkable=True,
            gates={"claim_ref": "c1", "importance": "essential", "fact_checkability": "fact_checkable"})
        source = Source(canonical_url="https://records.example/value", domain="records.example",
            source_type=SourceType.PRIMARY, first_seen_at=now, last_seen_at=now)
        db.add_all([claim, source])
        db.flush()
        snapshot = SourceSnapshot(id=snapshot_id, source_id=source.id, version_number=1,
            retrieved_at=now, access_status=AccessStatus.FETCHED, content_hash="hash")
        db.add(snapshot)
        db.flush()
        db.add(RunSource(run_id=run.id, source_id=source.id, snapshot_id=snapshot.id,
            role="primary", selected_rank=1))
        db.add(SourcePassage(id=passage_id, snapshot_id=snapshot.id, source_id=source.id,
            text="The value rose.", text_hash="abc", extraction_certainty=Decimal("1"), passage_metadata={}))
        db.commit()
        run_id, user_id = run.id, user.id

    state = VerificationState(run_id=run_id, user_id=user_id, research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        claims=[AtomicClaimOutput(claim_ref="c1", text="The value rose", claim_kind=ClaimKind.FACTUAL,
            importance=Importance.ESSENTIAL, importance_weight=3, fact_checkability=FactCheckability.FACT_CHECKABLE,
            verification_scope="Whether the value rose")],
        candidate_sources=[CandidateSource(source_ref="s1", url="https://records.example/value",
            domain="records.example", source_type="PRIMARY", selection_reason="record")],
        passages=[PassageRecord(passage_id=str(passage_id), source_ref="s1", snapshot_id=str(snapshot_id),
            text="The value rose.", text_hash="abc", extraction_certainty=Decimal("1"))],
        source_dependency_multipliers={"s1": Decimal("1")},
        evidence=[EvidenceClassificationItemOutput(claim_ref="c1", passage_id=str(passage_id),
            stance=EvidenceStance.STRONGLY_SUPPORTS,
            quality=EvidenceQualityOutput(relevance=1, directness=1, claim_specific_authority=1,
                transparency=1, temporal_fit=1, extraction_certainty=1),
            entity_match=True, time_period_match=True, quotation_or_number_located=True)])
    scored = asyncio.run(DeterministicScoringService().process(state)).complete(WorkflowStage.SCORING)
    asyncio.run(SqlWorkflowStateWriter(factory).save(stage=WorkflowStage.SCORING, state=scored))

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(EvidenceItem)) == 1
        assert db.scalar(select(func.count()).select_from(Calculation)) == len(scored.calculations)
        stored = db.scalar(select(Calculation).where(Calculation.formula_name == "evidence_quality"))
        assert stored.formula_text and stored.units == "ratio"
        assert stored.decimal_context == {"precision": 28, "rounding": "ROUND_HALF_UP"}
        persisted_run = db.get(VerificationRun, run_id)
        assert persisted_run.verdict == "Supported" and persisted_run.evidence_support == 100
