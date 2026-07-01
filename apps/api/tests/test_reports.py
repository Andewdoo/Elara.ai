from datetime import UTC, datetime
from uuid import uuid4

from app.models import (
    AtomicClaim,
    Calculation,
    InputType,
    MethodologyVersion,
    ResearchDepth,
    RunStatus,
    VerificationRun,
)


def test_report_exposes_calculation_inputs_decimal_context_and_audit_status(
    client, session_factory, owner
):
    now = datetime(2026, 7, 1, 12, tzinfo=UTC)
    with session_factory() as db:
        methodology = MethodologyVersion(
            version="1.0",
            scoring_config={},
            retrieval_config={},
            released_at=now,
            active=True,
        )
        db.add(methodology)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth=ResearchDepth.STANDARD,
            status=RunStatus.SCORING,
            submitted_text="Two of five cases passed.",
            normalized_target={},
            workflow_version="step-13-test",
            methodology_version_id=methodology.id,
            verdict="Supported",
            evidence_support=100,
            evidence_reviewed_at=now,
        )
        db.add(run)
        db.flush()
        claim = AtomicClaim(
            run_id=run.id,
            claim_text="Two of five cases passed.",
            claim_type="numerical",
            importance_weight=3,
            entities=[],
            locations=[],
            metrics=[],
            ambiguities=[],
            fact_checkable=True,
            gates={"claim_ref": "claim-1"},
        )
        db.add(claim)
        db.flush()
        db.add(
            Calculation(
                id=uuid4(),
                run_id=run.id,
                atomic_claim_id=claim.id,
                formula_name="numerical_percentage",
                formula_text="(numerator / denominator) * 100",
                inputs={
                    "values": [
                        {"role": "numerator", "value": "2", "unit": "cases"},
                        {"role": "denominator", "value": "5", "unit": "cases"},
                    ]
                },
                result={"value": "40.0", "denominator": "5", "issues": []},
                units="%",
                decimal_context={
                    "precision": 28,
                    "rounding": "ROUND_HALF_UP",
                    "applied_rounding": None,
                },
                audit_status="passed",
            )
        )
        db.commit()
        run_id = run.id

    response = client.get(f"/v1/verifications/{run_id}/report")
    assert response.status_code == 200
    calculation = response.json()["calculations"][0]
    assert calculation["inputs"]["values"][1]["role"] == "denominator"
    assert calculation["decimal_context"]["precision"] == 28
    assert calculation["audit_status"] == "passed"
    assert calculation["result"]["value"] == "40.0"


def test_report_route_preserves_cross_user_non_disclosure(client):
    response = client.get(f"/v1/verifications/{uuid4()}/report")
    assert response.status_code == 404
