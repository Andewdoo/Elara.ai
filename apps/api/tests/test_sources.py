from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.models import AccessStatus, AtomicClaim, EvidenceItem, EvidenceStance, ReportCitation, RunSource, Source, SourcePassage, SourceSnapshot


def test_sources_exposes_exact_passage_snapshot_and_citation_details(client, session_factory):
    run_id = UUID(client.post("/v1/verifications", json={"input_type": "CLAIM", "text": "A sourced claim"}).json()["run_id"])
    now = datetime(2026, 7, 1, 15, tzinfo=UTC)
    with session_factory() as db:
        source = Source(canonical_url="https://records.example/filing", domain="records.example", title="Filed record", publisher="Records office", source_type="PRIMARY", content_type="text/html", first_seen_at=now, last_seen_at=now)
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(source_id=source.id, version_number=2, retrieved_at=now, access_status=AccessStatus.FETCHED, content_hash="sha256:record", parser_name="trafilatura", parser_version="2.0", snapshot_metadata={"language": "en"})
        db.add(snapshot)
        db.flush()
        db.add(RunSource(run_id=run_id, source_id=source.id, snapshot_id=snapshot.id, role="PRIMARY", retrieval_reason="Original filing", selected_rank=1))
        passage = SourcePassage(snapshot_id=snapshot.id, source_id=source.id, text="Revenue was 40 million dollars.", text_hash="passage-hash", heading_path="Results > Revenue", page_or_position="paragraph 12", paragraph_index=12, extraction_certainty=1, passage_metadata={"selector": "#revenue"})
        db.add(passage)
        db.flush()
        claim = AtomicClaim(run_id=run_id, claim_text="Revenue was 40 million dollars.", claim_type="numerical", importance_weight=3, entities=[], locations=[], metrics=[], ambiguities=[], fact_checkable=True, gates={})
        db.add(claim)
        db.flush()
        db.add(EvidenceItem(atomic_claim_id=claim.id, passage_id=passage.id, stance=EvidenceStance.STRONGLY_SUPPORTS, stance_value=Decimal("1"), relevance=Decimal("1"), directness=Decimal("1"), authority=Decimal("1"), transparency=Decimal("1"), temporal_fit=Decimal("1"), extraction_certainty=Decimal("1"), base_quality=Decimal("1"), dependency_multiplier=Decimal("1"), adjusted_weight=Decimal("1"), citation_status="accepted"))
        db.add(ReportCitation(run_id=run_id, report_section="summary", sentence_text="The filing reports revenue of 40 million dollars.", passage_id=passage.id, audit_status="passed", audit_note="Exact numerical support"))
        db.commit()

    response = client.get(f"/v1/verifications/{run_id}/sources")
    assert response.status_code == 200
    item = response.json()["sources"][0]
    assert item["snapshot_version"] == 2
    assert item["parser_name"] == "trafilatura"
    # SQLite drops the timezone offset; PostgreSQL retains the timezone-aware value.
    assert item["retrieved_at"].startswith("2026-07-01T15:00:00")
    assert item["passages"][0]["text"] == "Revenue was 40 million dollars."
    assert item["passages"][0]["citations"][0]["audit_status"] == "passed"
    graph = client.get(f"/v1/verifications/{run_id}/source-graph").json()
    source_node = next(node for node in graph["nodes"] if node["type"] == "source")
    assert source_node["data"]["atomicClaimIds"] == [str(claim.id)]
    assert source_node["data"]["evidenceUsed"] is True


def test_sources_preserves_cross_user_non_disclosure(client):
    from uuid import uuid4
    assert client.get(f"/v1/verifications/{uuid4()}/sources").status_code == 404
