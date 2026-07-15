"""Provider-independent DeepSeek, Brave, and controlled-source acceptance doubles."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import boto3
from botocore.config import Config as BotoConfig
from pydantic import BaseModel

from agents.deepseek_client import (
    CallMetadata,
    DeepSeekUnavailableError,
    EmbeddingResponse,
    ProviderErrorMetadata,
    StructuredResponse,
    TokenUsage,
)
from app.config import Settings
from extraction.service import ExtractionService
from research.fetcher import FetchResult, S3SnapshotStore, SnapshotFileStore
from research.pipeline import RetrievalPipeline
from research.search import SearchResult


_UUID = re.compile(r'"(?:passage_id|passage_ids)"\s*:\s*(?:\[\s*)?"([0-9a-f-]{36})"')


class DeterministicBraveDouble:
    """Stable Brave-shaped search results without provider credentials."""

    async def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        results = [
            SearchResult(
                url="https://evidence.example.test/filing.html",
                title="Controlled quarterly filing",
                snippet="The filing reports Q1 net income of 20 units, up from 10 units.",
                rank=1,
                published_at="2026-04-30",
                profile="Controlled primary evidence",
            ),
            SearchResult(
                url="https://analysis.example.test/analysis.html",
                title="Controlled independent analysis",
                snippet="Independent analysis confirms the reported Q1 comparison.",
                rank=2,
                published_at="2026-05-01",
                profile="Controlled analysis",
            ),
        ]
        return results[:count]

    async def aclose(self) -> None:
        return None


class ControlledSnapshotFetcher:
    """Retrieves immutable fixture bytes into the normal private snapshot store."""

    _documents = {
        "https://evidence.example.test/filing.html": b"""<!doctype html><html><head><title>Controlled quarterly filing</title></head>
        <body><main><h1>Quarterly filing</h1><p>Company X reported Q1 2026 net income of 20 units.
        The comparable Q1 2025 net income was 10 units, so the reported value doubled.</p>
        <p>This controlled primary filing is timestamped and retained for deterministic acceptance testing.</p>
        <a href=\"https://analysis.example.test/analysis.html\">Independent analysis</a></main></body></html>""",
        "https://analysis.example.test/analysis.html": b"""<!doctype html><html><head><title>Controlled independent analysis</title></head>
        <body><main><h1>Independent analysis</h1><p>The controlled filing reports Q1 2026 net income of 20 units,
        compared with 10 units in Q1 2025. The comparison therefore supports the narrow submitted claim.</p>
        <p>The analysis cites the controlled quarterly filing and preserves the period and denominator.</p>
        <a href=\"https://evidence.example.test/filing.html\">Primary filing</a></main></body></html>""",
    }

    def __init__(self, store: S3SnapshotStore) -> None:
        self.store = store

    async def fetch(self, url: str) -> FetchResult:
        content = self._documents[url]
        digest = hashlib.sha256(content).hexdigest()
        path = self.store.write(content, content_hash=digest, suffix=".html")
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            content_length=len(content),
            content_hash=digest,
            storage_path=path,
            redirect_chain=(),
            origin_fetched_at="2026-07-04T12:00:00+00:00",
        )

    def read_content(self, storage_path: str, *, expected_hash: str) -> bytes:
        return self.store.read(storage_path, expected_hash=expected_hash)

    async def aclose(self) -> None:
        return None


class DeterministicDeepSeekDouble:
    """Schema-aware language-step double; deterministic gates remain production code."""

    def __init__(self, submitted_text: str, *, embedding_dimension: int) -> None:
        self.submitted_text = submitted_text
        self.embedding_dimension = embedding_dimension
        self.config = SimpleNamespace(embedding_model="deepseek-acceptance-embedding-double")
        self.reject_citations = "[citation-rejection]" in submitted_text
        self.fail_provider = "[provider-failure]" in submitted_text
        self.slow_for_cancellation = "[cancellation]" in submitted_text

    @property
    def embedding_available(self) -> bool:
        return True

    async def generate_structured(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        output_schema: type[BaseModel],
        prompt_version: str,
        temperature: float,
        **_: Any,
    ) -> StructuredResponse[Any]:
        if self.slow_for_cancellation:
            await asyncio.sleep(1)
        if self.fail_provider:
            raise DeepSeekUnavailableError(
                "Deterministic provider outage",
                metadata=ProviderErrorMetadata(
                    model="deepseek-acceptance-double",
                    prompt_version=prompt_version,
                    temperature=temperature,
                    latency_ms=1,
                    status_code=503,
                    error_code="provider_unavailable",
                    retryable=True,
                ),
            )
        content = "\n".join(message["content"] for message in messages)
        passage_ids = list(dict.fromkeys(_UUID.findall(content)))
        name = output_schema.__name__
        payload: dict[str, Any]
        if name == "IntakeClassificationOutput":
            payload = {
                "input_kind": "claim",
                "normalized_text": self.submitted_text,
                "detected_language": "English",
                "fact_checkability": "fact_checkable",
                "claim_kinds": ["numerical"],
                "entities": [{"name": "Company X", "entity_type": "company"}],
                "dates": ["Q1 2026", "Q1 2025"],
                "metrics": [{"name": "net income", "unit": "units", "period": "Q1"}],
                "comparisons": ["20 units compared with 10 units"],
            }
        elif name == "DecompositionOutput":
            payload = {
                "atomic_claims": [{
                    "claim_ref": "claim-1",
                    "text": "Company X doubled net income in Q1 2026.",
                    "claim_kind": "numerical",
                    "importance": "essential",
                    "importance_weight": 3,
                    "fact_checkability": "fact_checkable",
                    "entities": [{"name": "Company X", "entity_type": "company"}],
                    "time_period": "Q1 2026 compared with Q1 2025",
                    "metrics": [{"name": "net income", "unit": "units", "period": "Q1"}],
                    "comparison": "20 compared with 10",
                    "verification_scope": "Compare the two Q1 net-income values.",
                }]
            }
        elif name == "PlanningDraftOutput":
            payload = {
                "objectives": [
                    {"claim_ref": "claim-1", "intent": "primary", "target": "Find the filing.", "priority": 1, "queries": [{"query": "Company X Q1 2026 net income filing", "priority": 1}]},
                    {"claim_ref": "claim-1", "intent": "contradiction", "target": "Find contrary evidence.", "priority": 0.8, "queries": [{"query": "Company X Q1 2026 net income correction", "priority": 0.8}]},
                ],
                "primary_source_targets": ["Controlled quarterly filing"],
            }
        elif name == "EvidenceClassificationOutput":
            payload = {"classifications": [
                {
                    "claim_ref": "claim-1", "passage_id": passage_id,
                    "stance": "strongly_supports",
                    "quality": {"relevance": 1, "directness": 1, "claim_specific_authority": 1, "transparency": 1, "temporal_fit": 1, "extraction_certainty": 1},
                    "explicit_support": "The passage reports 20 units compared with 10 units.",
                    "entity_match": True, "time_period_match": True,
                    "quotation_or_number_located": True,
                }
                for passage_id in passage_ids[:2]
            ]}
        elif name == "SynthesisOutput":
            passage_id = passage_ids[0]
            payload = {
                "title": "Controlled Company X net-income assessment",
                "summary_sentences": [{
                    "sentence_ref": "summary-1",
                    "text": "The controlled evidence reports net income of 20 units versus 10 units for the comparable period.",
                    "passage_ids": [passage_id],
                }],
                "limitations": ["This deterministic fixture evaluates only the submitted claim."],
            }
        elif name == "CitationAuditOutput":
            passage_id = passage_ids[0]
            rejected = self.reject_citations
            payload = {
                "sentence_audits": [{
                    "sentence_ref": "summary-1", "passage_id": passage_id,
                    "entailment": "not_entailed" if rejected else "entailed",
                    "support_explanation": "Forced rejection fixture." if rejected else "The exact values and comparison appear in the passage.",
                    "suggested_revision": "Remove the sentence." if rejected else None,
                }],
                "unsupported_sentence_refs": ["summary-1"] if rejected else [],
                "needs_revision": rejected,
            }
        else:
            raise AssertionError(f"No deterministic output for {name}")
        output = output_schema.model_validate(payload)
        return StructuredResponse(
            output=output,
            metadata=CallMetadata(
                model="deepseek-acceptance-double",
                prompt_version=prompt_version,
                temperature=temperature,
                latency_ms=1,
                response_id=f"acceptance-{prompt_version}",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            ),
        )

    async def generate_embeddings(self, texts: Sequence[str]) -> EmbeddingResponse:
        vectors = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            vectors.append([seed] + [0.0] * (self.embedding_dimension - 1))
        return EmbeddingResponse(
            vectors=vectors,
            metadata=CallMetadata(
                model="deepseek-acceptance-embedding-double",
                prompt_version="embedding-v1",
                temperature=0,
                latency_ms=1,
            ),
        )

    async def aclose(self) -> None:
        return None


def build_acceptance_adapters(settings: Settings, submitted_text: str):
    if not settings.acceptance_test_mode or settings.environment != "test":
        raise RuntimeError("Deterministic acceptance adapters require test-only acceptance mode")
    object_client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    store = S3SnapshotStore(
        client=object_client,
        bucket=settings.s3_bucket_name,
        staging=SnapshotFileStore(Path(settings.fetch_storage_dir)),
        create_bucket_if_missing=True,
        region=settings.s3_region,
    )
    model = DeterministicDeepSeekDouble(
        submitted_text,
        embedding_dimension=settings.passage_embedding_dimension,
    )
    pipeline = RetrievalPipeline(
        search=DeterministicBraveDouble(),
        fetcher=ControlledSnapshotFetcher(store),
        extractor=ExtractionService(),
    )
    return model, pipeline


__all__ = [
    "ControlledSnapshotFetcher",
    "DeterministicBraveDouble",
    "DeterministicDeepSeekDouble",
    "build_acceptance_adapters",
]
