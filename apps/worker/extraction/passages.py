"""Deterministic, structure-aware passage segmentation and hashing."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from agents.deepseek_client import DeepSeekClient, DeepSeekError
from graph.state import EmbeddingRunMetadata, ExtractedBlockRecord, PassageRecord, VerificationState
from research.extension_errors import WorkflowExtensionError


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])|\n+")
_SPEAKER = re.compile(r"^(?P<speaker>[A-Z][\w .'-]{0,79}):\s+.+$")


class PassageSegmenter:
    def __init__(self, *, max_chars: int = 1_200, overlap_chars: int = 160) -> None:
        if max_chars < 300:
            raise ValueError("max_chars must be at least 300")
        if overlap_chars < 0 or overlap_chars >= max_chars // 2:
            raise ValueError("overlap_chars must be non-negative and limited")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def segment(self, state: VerificationState) -> list[PassageRecord]:
        certainty = {
            snapshot.snapshot_id: (
                snapshot.extraction_quality
                if snapshot.extraction_quality is not None
                else Decimal("0.7000")
            )
            for snapshot in state.snapshots
            if snapshot.access_status == "FETCHED"
        }
        passages: list[PassageRecord] = []
        for source in state.extracted_sources:
            blocks = source.blocks or self._fallback_blocks(source.body, source.page_positions)
            current_heading: list[str] = []
            seen: dict[str, int] = {}
            for block_index, block in enumerate(blocks):
                if block.kind == "heading":
                    current_heading = list(block.heading_path) or [block.text]
                    continue
                heading_path = block.heading_path or current_heading
                speaker = block.speaker
                if speaker is None and (match := _SPEAKER.match(block.text)):
                    speaker = match.group("speaker")
                segmentation_text = block.text
                block_metadata = dict(block.metadata)
                if block.kind == "quote":
                    segmentation_text, contextual_speaker = _quote_with_context(blocks, block_index)
                    speaker = speaker or contextual_speaker
                    block_metadata.update(
                        {
                            "exact_quote": block.text,
                            "quote_context_attached": segmentation_text != block.text,
                        }
                    )
                for part_index, (text, overlap) in enumerate(self._split(segmentation_text), start=1):
                    text_hash = hash_passage_text(text)
                    if text_hash in seen:
                        prior = passages[seen[text_hash]]
                        positions = list(prior.metadata.get("duplicate_positions", []))
                        if block.page_or_position and block.page_or_position not in positions:
                            positions.append(block.page_or_position)
                        passages[seen[text_hash]] = prior.model_copy(
                            update={"metadata": {**prior.metadata, "duplicate_positions": positions}}
                        )
                        continue
                    metadata = {
                        "block_kind": block.kind,
                        "part_index": part_index,
                        "has_boundary_overlap": overlap,
                        "untrusted_evidence": True,
                        **block_metadata,
                    }
                    passage = PassageRecord(
                        passage_id=str(uuid5(NAMESPACE_URL, f"elara:{source.snapshot_id}:{text_hash}")),
                        source_ref=source.source_ref,
                        snapshot_id=source.snapshot_id,
                        text=text,
                        text_hash=text_hash,
                        page_or_position=block.page_or_position,
                        heading_path=" > ".join(heading_path) if heading_path else None,
                        paragraph_index=block.paragraph_index,
                        speaker=speaker,
                        table_ref=block.table_ref,
                        extraction_certainty=certainty.get(source.snapshot_id, Decimal("0.7000")),
                        metadata=metadata,
                    )
                    seen[text_hash] = len(passages)
                    passages.append(passage)
        if not passages:
            raise WorkflowExtensionError(
                code="NO_USABLE_PASSAGES",
                public_message="Extracted evidence did not contain usable passages for analysis.",
                details={"extracted_source_count": len(state.extracted_sources)},
            )
        return passages

    def _split(self, text: str) -> list[tuple[str, bool]]:
        normalized = text.strip()
        if len(normalized) <= self.max_chars:
            return [(normalized, False)] if normalized else []
        units = [unit.strip() for unit in _SENTENCE_BOUNDARY.split(normalized) if unit.strip()]
        chunks: list[tuple[str, bool]] = []
        current = ""
        overlap_prefix = ""
        for unit in units:
            if len(unit) > self.max_chars:
                if current:
                    chunks.append((current, bool(overlap_prefix)))
                    current = ""
                    overlap_prefix = ""
                step = self.max_chars - self.overlap_chars
                for start in range(0, len(unit), step):
                    chunk = unit[start : start + self.max_chars].rstrip()
                    if chunk:
                        chunks.append((chunk, start > 0))
                    if start + self.max_chars >= len(unit):
                        break
                continue
            candidate = f"{current} {unit}".strip()
            if current and len(candidate) > self.max_chars:
                chunks.append((current, bool(overlap_prefix)))
                available_overlap = max(0, self.max_chars - len(unit) - 1)
                overlap_prefix = _limited_overlap(current, min(self.overlap_chars, available_overlap))
                current = f"{overlap_prefix} {unit}".strip()
            else:
                current = candidate
        if current:
            chunks.append((current, bool(overlap_prefix)))
        return chunks

    @staticmethod
    def _fallback_blocks(body: str, page_positions: list[str]) -> list[ExtractedBlockRecord]:
        values = [value.strip() for value in re.split(r"\n\s*\n", body) if value.strip()]
        if len(values) == 1:
            values = [value.strip() for value in body.splitlines() if value.strip()]
        return [
            ExtractedBlockRecord(
                kind="transcript_turn" if _SPEAKER.match(text) else "paragraph",
                text=text,
                page_or_position=(page_positions[index] if index < len(page_positions) else f"paragraph {index + 1}"),
                paragraph_index=index + 1,
            )
            for index, text in enumerate(values)
        ]


class PassageEmbeddingService:
    """Attach approved DeepSeek-route vectors, or retain a safe lexical fallback."""

    def __init__(
        self,
        client: DeepSeekClient,
        *,
        expected_dimension: int,
        batch_size: int = 64,
    ) -> None:
        self.client = client
        self.expected_dimension = expected_dimension
        self.batch_size = batch_size
        if expected_dimension < 1:
            raise ValueError("expected_dimension must be positive")
        if not 1 <= batch_size <= 128:
            raise ValueError("batch_size must be between 1 and 128")

    async def apply(self, state: VerificationState, passages: list[PassageRecord]) -> VerificationState:
        configured_model = self.client.config.embedding_model
        if not passages:
            return state.model_copy(
                update={
                    "passages": passages,
                    "embedding_model_version": None,
                    "passage_retrieval_mode": "lexical_metadata_fallback",
                    "embedding_run_metadata": EmbeddingRunMetadata(
                        configured_model=configured_model,
                        status="no_passages",
                    ),
                }
            )
        if not self.client.embedding_available:
            return state.model_copy(
                update={
                    "passages": passages,
                    "embedding_model_version": None,
                    "passage_retrieval_mode": "lexical_metadata_fallback",
                    "embedding_run_metadata": EmbeddingRunMetadata(
                        configured_model=None,
                        status="unconfigured_fallback",
                        error_code="embedding_route_unavailable",
                    ),
                }
            )
        vectors: list[list[float]] = []
        model: str | None = None
        request_count = 0
        latency_ms = 0
        prompt_tokens = 0
        total_tokens = 0
        try:
            for start in range(0, len(passages), self.batch_size):
                batch = passages[start : start + self.batch_size]
                request_count += 1
                response = await self.client.generate_embeddings([item.text for item in batch])
                latency_ms += response.metadata.latency_ms
                prompt_tokens += response.metadata.usage.prompt_tokens
                total_tokens += response.metadata.usage.total_tokens
                if any(len(vector) != self.expected_dimension for vector in response.vectors):
                    raise ValueError("embedding dimension does not match PASSAGE_EMBEDDING_DIMENSION")
                vectors.extend(response.vectors)
                model = response.metadata.model
        except (DeepSeekError, ValueError) as exc:
            provider_error = exc.metadata if isinstance(exc, DeepSeekError) else None
            if provider_error is not None:
                latency_ms += provider_error.latency_ms
            return state.model_copy(
                update={
                    "passages": passages,
                    "embedding_model_version": configured_model,
                    "passage_retrieval_mode": "lexical_metadata_fallback",
                    "embedding_run_metadata": EmbeddingRunMetadata(
                        configured_model=configured_model,
                        status=("provider_fallback" if provider_error else "dimension_fallback"),
                        request_count=request_count,
                        latency_ms=latency_ms,
                        prompt_tokens=prompt_tokens,
                        total_tokens=total_tokens,
                        error_code=(
                            provider_error.error_code
                            if provider_error
                            else "embedding_dimension_mismatch"
                        ),
                        status_code=provider_error.status_code if provider_error else None,
                        retryable=provider_error.retryable if provider_error else False,
                    ),
                }
            )
        embedded = [
            passage.model_copy(update={"embedding": vector, "embedding_model": model})
            for passage, vector in zip(passages, vectors, strict=True)
        ]
        return state.model_copy(
            update={
                "passages": embedded,
                "embedding_model_version": model,
                "passage_retrieval_mode": "hybrid",
                "embedding_run_metadata": EmbeddingRunMetadata(
                    configured_model=configured_model,
                    used_model=model,
                    status="embedded",
                    request_count=request_count,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    total_tokens=total_tokens,
                ),
            }
        )


class PassagePipeline:
    def __init__(self, segmenter: PassageSegmenter, embeddings: PassageEmbeddingService) -> None:
        self.segmenter = segmenter
        self.embeddings = embeddings

    async def process(self, state: VerificationState) -> VerificationState:
        return await self.embeddings.apply(state, self.segmenter.segment(state))


def hash_passage_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _limited_overlap(text: str, limit: int) -> str:
    if limit == 0:
        return ""
    tail = text[-limit:]
    first_space = tail.find(" ")
    return tail[first_space + 1 :] if first_space >= 0 else tail


def _quote_with_context(
    blocks: list[ExtractedBlockRecord], index: int, *, context_chars: int = 320
) -> tuple[str, str | None]:
    quote = blocks[index]
    context_kinds = {"paragraph", "transcript_turn"}
    previous = blocks[index - 1] if index > 0 and blocks[index - 1].kind in context_kinds else None
    following = (
        blocks[index + 1]
        if index + 1 < len(blocks) and blocks[index + 1].kind in context_kinds
        else None
    )
    values = []
    if previous is not None:
        values.append(previous.text[-context_chars:])
    values.append(quote.text)
    if following is not None:
        values.append(following.text[:context_chars])
    return "\n\n".join(values), quote.speaker or (previous.speaker if previous else None)


__all__ = [
    "PassageEmbeddingService",
    "PassagePipeline",
    "PassageSegmenter",
    "hash_passage_text",
]
