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
            status=RunStatus.COMPLETED,
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
            ambiguities=["The phrase does not name a trading session."],
            fact_checkable=True,
            final_label="Supported",
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
        db.add(
            Calculation(
                id=uuid4(),
                run_id=run.id,
                atomic_claim_id=claim.id,
                formula_name="ambiguity_gate",
                formula_text="owned ambiguity gate",
                inputs={
                    "scoring_version": "1.1-ambiguity-gate",
                    "owned_ambiguity_count": 1,
                },
                result={"non_blocking": True, "unresolved_key_facts": False},
                units="gate_decision",
                decimal_context={"precision": 28, "rounding": "ROUND_HALF_UP"},
                audit_status="non_blocking",
            )
        )
        db.commit()
        run_id = run.id

    response = client.get(f"/v1/verifications/{run_id}/report")
    assert response.status_code == 200
    calculation = next(
        item
        for item in response.json()["calculations"]
        if item["formula_name"] == "numerical_percentage"
    )
    assert calculation["inputs"]["values"][1]["role"] == "denominator"
    assert calculation["decimal_context"]["precision"] == 28
    assert calculation["audit_status"] == "passed"
    assert calculation["result"]["value"] == "40.0"
    assert response.json()["limitations"] == [
        "Claim claim-1 is supported with an unresolved interpretation "
        "(1 claim-local limitation(s)); accepted evidence was adequate and not materially contradicted."
    ]


def test_report_contract_exposes_reproducibility_roles_and_generation_time(
    client, session_factory, owner
):
    now = datetime(2026, 7, 1, 12, tzinfo=UTC)
    with session_factory() as db:
        methodology = MethodologyVersion(
            version="1.1",
            scoring_config={},
            retrieval_config={"implementation": "targeted-retrieval", "version": "2026.07"},
            released_at=now,
            active=True,
        )
        db.add(methodology)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth=ResearchDepth.QUICK,
            status=RunStatus.COMPLETED,
            submitted_text="A completed claim",
            normalized_target={},
            workflow_version="step-23-test",
            methodology_version_id=methodology.id,
            completed_at=now,
            evidence_reviewed_at=now,
            model_versions={"synthesis": "deepseek-chat"},
            prompt_versions={"synthesis": "v1"},
            parser_versions={"html": "v2"},
        )
        db.add(run)
        db.commit()
        run_id = run.id

    body = client.get(f"/v1/verifications/{run_id}/report").json()
    assert body["generated_at"] == now.isoformat().replace("+00:00", "Z")
    assert body["retrieval_versions"]["version"] == "2026.07"
    assert set(body["score_roles"]) == {
        "evidence_support", "attribution_support", "quote_fidelity",
        "verdict_confidence", "source_independence", "context_completeness",
    }


def test_report_route_preserves_cross_user_non_disclosure(client):
    response = client.get(f"/v1/verifications/{uuid4()}/report")
    assert response.status_code == 404


def test_report_route_rejects_non_completed_drafts(client):
    created = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "research_depth": "QUICK", "text": "A draft claim"},
    )

    response = client.get(f"/v1/verifications/{created.json()['run_id']}/report")

    assert response.status_code == 409
    assert "citation-audited completion" in response.json()["detail"]
