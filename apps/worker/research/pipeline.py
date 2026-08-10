"""Typed Step 9 LangGraph extensions for discovery, fetching, and extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import time
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree.ElementTree import ParseError

import fitz

from agents.schemas import SearchQueryOutput
from agents.planning import (
    exact_quote_for_state,
    fact_checkable_claim_refs,
    requires_attribution_check,
    search_budget_for_state,
    search_policy_for_state,
)
from extraction.service import ExtractionService
from graph.state import (
    AuthorityGapRecord,
    AuthorityGapReasonValue,
    AuthorityPreflightQueryRecord,
    AuthorityProfileRecord,
    AuthorityRecordHolderRecord,
    AuthoritySubjectValue,
    CandidateSource,
    CandidateSearchPhaseValue,
    DiscoveryGateRecord,
    ExtractedBlockRecord,
    ExtractedSourceRecord,
    EvidenceIntentValue,
    SearchQueryExecutionRecord,
    SnapshotRecord,
    SourceTypeValue,
    VerificationState,
)
from research.authority import (
    AUTHORITY_GAP_CODE,
    AUTHORITY_POLICY_REGISTRY_VERSION,
    AUTHORITY_PREFLIGHT_PER_CLAIM,
    AUTHORITY_PREFLIGHT_RESULT_LIMIT,
    AUTHORITY_PREFLIGHT_TOTAL_BUDGET,
    AUTHORITY_PROFILE_VERSION,
    build_preflight_query,
    derive_authority_profiles,
    holder_for_profile,
    registered_document_match,
    registered_search_match,
)
from research.cache import RetrievalRateLimiter
from research.extension_errors import WorkflowExtensionError
from research.fetcher import FetchError, SecureFetcher
from research.ranking import (
    RESEARCH_DEPTH_LIMITS,
    RankingSignals,
    lexical_overlap,
    priority_score,
    select_diverse,
)
from research.search import (
    BraveSearchClient,
    SearchExecutionOutcome,
    SearchProviderError,
    SearchResult,
)
from research.search_policy import (
    evaluate_discovery_gate,
    query_state_key,
    select_initial_queries,
    select_reserve_batch,
)
from research.url_guard import UnsafeUrlError, canonicalize_url


_UNTRUSTED_SOURCE_EXTRACTION_ERRORS = (UnicodeError, ParseError, fitz.FileDataError)


class RetrievalPipeline:
    def __init__(
        self,
        *,
        search: BraveSearchClient,
        fetcher: SecureFetcher,
        extractor: ExtractionService | None = None,
        rate_limiter: RetrievalRateLimiter | None = None,
    ) -> None:
        self.search = search
        self.fetcher = fetcher
        self.extractor = extractor or ExtractionService()
        self.rate_limiter = rate_limiter

    async def discover(self, state: VerificationState) -> VerificationState:
        policy = search_policy_for_state(state)
        budget = search_budget_for_state(state)
        fact_claim_refs = fact_checkable_claim_refs(state)
        exact_quote = exact_quote_for_state(state)
        attribution_required = requires_attribution_check(state, exact_quote)
        phase_one, reserve = select_initial_queries(
            state.queries,
            state.objectives,
            fact_checkable_claim_refs=fact_claim_refs,
            attribution_required=attribution_required,
            exact_quote=exact_quote,
            policy=policy,
            budget=budget,
        )
        executions = _ensure_query_executions(state, phase_one, reserve)
        by_url = {
            source.canonical_url or source.url: source for source in state.candidate_sources
        }
        result_counts = dict(state.query_result_counts)
        profiles, ambiguous_profiles = derive_authority_profiles(state)
        authority_gaps = list(state.authority_gaps)
        for claim_ref, subject, reason_code in ambiguous_profiles:
            authority_gaps = _set_authority_gap(
                authority_gaps,
                claim_ref=claim_ref,
                profile_subject=subject,
                reason_code=reason_code,
                preflight_queries=[],
            )
        (
            by_url,
            result_counts,
            authority_queries,
            authority_gaps,
            authority_preflight_used,
        ) = await self._execute_authority_preflight(
            state,
            profiles=profiles,
            by_url=by_url,
            result_counts=result_counts,
            gaps=authority_gaps,
        )
        retryable_errors: list[SearchProviderError] = []
        submitted_source = _submitted_url_source(state)
        if submitted_source is not None:
            # A pasted article is a retrieval seed, not a search result.  It
            # must therefore survive an empty or temporarily unavailable
            # supplementary Brave search.
            by_url[submitted_source.canonical_url or submitted_source.url] = submitted_source

        by_url, result_counts, executions, failures = await self._execute_query_batch(
            phase_one,
            by_url=by_url,
            result_counts=result_counts,
            executions=executions,
        )
        retryable_errors.extend(error for error in failures if error.retryable)
        gate_outcomes = list(state.discovery_gate_outcomes)
        decision = evaluate_discovery_gate(
            list(by_url.values()),
            state.objectives,
            fact_checkable_claim_refs=fact_claim_refs,
            attribution_required=attribution_required,
            policy=policy,
        )
        gate_outcomes.append(_gate_record(decision, policy=policy, phase="phase_one", batch_number=1))

        phase_two_batch = 0
        while not decision.passed:
            attempted_keys = {
                record.query_key
                for record in executions
                if record.execution_status in {"executed", "cache_hit"}
                or record.network_attempt_count > 0
            }
            batch = select_reserve_batch(
                reserve,
                already_executed_keys=attempted_keys,
                batch_size=policy.reserve_batch_size,
                remaining_budget=budget.effective_total_budget - len(attempted_keys),
            )
            if not batch:
                break
            phase_two_batch += 1
            by_url, result_counts, executions, failures = await self._execute_query_batch(
                batch,
                by_url=by_url,
                result_counts=result_counts,
                executions=executions,
            )
            retryable_errors.extend(error for error in failures if error.retryable)
            decision = evaluate_discovery_gate(
                list(by_url.values()),
                state.objectives,
                fact_checkable_claim_refs=fact_claim_refs,
                attribution_required=attribution_required,
                policy=policy,
            )
            gate_outcomes.append(
                _gate_record(
                    decision,
                    policy=policy,
                    phase="phase_two",
                    batch_number=phase_two_batch,
                )
            )

        if decision.passed:
            executions = [
                record.model_copy(
                    update={"execution_status": "not_needed", "skip_reason": "discovery_gate_passed"}
                )
                if record.discovery_phase == "phase_two" and record.execution_status == "planned"
                else record
                for record in executions
            ]

        submitted = [
            source for source in by_url.values() if source.source_origin == "submitted_url"
        ]
        authority = [
            source for source in by_url.values() if source.source_origin == "authority_preflight"
        ]
        broad_discovered = [
            source for source in by_url.values() if source.source_origin == "brave_discovery"
        ]
        discovered_limit = max(
            0, RESEARCH_DEPTH_LIMITS[state.research_depth.value] - len(submitted)
        )
        # Authority-first is not authority-only. Keep room for ordinary Brave
        # corroboration/contradiction even when many profiles return records.
        broad_reserve = min(2, len(broad_discovered), discovered_limit)
        authority_limit = max(0, discovered_limit - broad_reserve)
        selected_authority = (
            select_diverse(
                authority,
                limit=authority_limit,
                reserved_intents=("primary",),
            )
            if authority_limit
            else []
        )
        broad_limit = max(0, discovered_limit - len(selected_authority))
        selected_broad = (
            select_diverse(broad_discovered, limit=broad_limit)
            if broad_limit
            else []
        )
        selected = [
            *submitted,
            *selected_authority,
            *selected_broad,
        ]
        # Keep source refs stable after ranking/deduplication.
        selected = [
            item
            if item.source_origin == "submitted_url"
            else item.model_copy(update={"source_ref": f"source-{index}"})
            for index, item in enumerate(selected, 1)
        ]
        updates = {
            "candidate_sources": selected,
            "query_result_counts": result_counts,
            "search_query_executions": executions,
            "discovery_gate_outcomes": gate_outcomes,
            "search_policy_version": policy.policy_version,
            "search_mandatory_floor": budget.mandatory_floor,
            "search_effective_budget": budget.effective_total_budget,
            "authority_profiles": profiles,
            "authority_preflight_queries": authority_queries,
            "authority_gaps": authority_gaps,
            "authority_profile_version": AUTHORITY_PROFILE_VERSION,
            "authority_registry_version": AUTHORITY_POLICY_REGISTRY_VERSION,
            "authority_preflight_budget": AUTHORITY_PREFLIGHT_TOTAL_BUDGET,
            "authority_preflight_used": authority_preflight_used,
            "known_evidence_gaps": _known_gaps_with_authority(
                state.known_evidence_gaps, authority_gaps
            ),
        }
        updated = state.model_copy(update=updates)
        brave_candidates = [
            source for source in selected if source.source_origin == "brave_discovery"
        ]
        if (
            not decision.passed
            and retryable_errors
            and not brave_candidates
            and submitted_source is None
        ):
            raise WorkflowExtensionError(
                code="SEARCH_PROVIDER_UNAVAILABLE",
                public_message="The configured search provider was temporarily unavailable.",
                retryable=True,
                details={
                    "failure_kind": "provider",
                    "query_count": len(result_counts),
                    "network_attempt_count": sum(
                        record.network_attempt_count for record in executions
                    ),
                },
                state=updated,
            )
        if not brave_candidates and submitted_source is None:
            raise WorkflowExtensionError(
                code="NO_DISCOVERY_RESULTS",
                public_message="The configured search policy returned no evidence candidates.",
                details={
                    "provider": "brave",
                    "query_count": len(result_counts),
                    "search_result_count": sum(result_counts.values()),
                },
                state=updated,
            )
        if not decision.passed:
            finalized_executions = [
                record.model_copy(
                    update={
                        "execution_status": "executed",
                        "executed_at": record.executed_at or datetime.now(UTC),
                        "skip_reason": "provider_failure_retained_partial_results",
                    }
                )
                if record.execution_status == "planned" and record.network_attempt_count > 0
                else record
                for record in updated.search_query_executions
            ]
            limitation = (
                "Independent discovery coverage remained below the deterministic "
                "adaptive-search-v1 gate after the available search budget was used."
            )
            updated = updated.model_copy(
                update={
                    "search_query_executions": finalized_executions,
                    "known_evidence_gaps": [
                        *updated.known_evidence_gaps,
                        *([] if limitation in updated.known_evidence_gaps else [limitation]),
                    ]
                }
            )
        return updated

    async def _execute_authority_preflight(
        self,
        state: VerificationState,
        *,
        profiles: list[AuthorityProfileRecord],
        by_url: dict[str, CandidateSource],
        result_counts: dict[str, int],
        gaps: list[AuthorityGapRecord],
    ) -> tuple[
        dict[str, CandidateSource],
        dict[str, int],
        list[AuthorityPreflightQueryRecord],
        list[AuthorityGapRecord],
        int,
    ]:
        existing = {item.query_key: item for item in state.authority_preflight_queries}
        planned: list[
            tuple[
                AuthorityProfileRecord,
                AuthorityRecordHolderRecord,
                AuthorityPreflightQueryRecord,
            ]
        ] = []
        remaining = AUTHORITY_PREFLIGHT_TOTAL_BUDGET
        for profile in sorted(profiles, key=lambda item: item.claim_ref):
            for holder in profile.record_holders[:AUTHORITY_PREFLIGHT_PER_CLAIM]:
                if remaining <= 0:
                    break
                query = build_preflight_query(profile, holder)
                key = (
                    f"authority:{profile.claim_ref}:{holder.domain}:{holder.source_role}"
                )
                record = existing.get(key) or AuthorityPreflightQueryRecord(
                    query_key=key,
                    claim_ref=profile.claim_ref,
                    query=query,
                    domain_restriction=holder.domain,
                    source_role=holder.source_role,
                    profile_version=profile.profile_version,
                    registry_version=profile.registry_version,
                )
                planned.append((profile, holder, record))
                remaining -= 1

        records: dict[str, AuthorityPreflightQueryRecord] = {
            record.query_key: record for _, _, record in planned
        }
        used = 0
        by_claim_outcomes: dict[str, list[str]] = {
            profile.claim_ref: [] for profile in profiles
        }
        for profile, holder, original in planned:
            record = records[original.query_key]
            if record.execution_status in {"executed", "cache_hit", "not_needed"}:
                if record.verified_candidate_count:
                    by_claim_outcomes[profile.claim_ref].append("VERIFIED")
                elif record.result_count == 0:
                    by_claim_outcomes[profile.claim_ref].append("NO_SEARCH_RESULTS")
                else:
                    by_claim_outcomes[profile.claim_ref].append("NO_VERIFIED_RESULT")
                continue
            used += 1
            try:
                raw_outcome = await self.search.search(
                    record.query, count=AUTHORITY_PREFLIGHT_RESULT_LIMIT
                )
                outcome = _search_outcome(raw_outcome)
            except SearchProviderError as exc:
                result_counts[record.query_key] = 0
                records[record.query_key] = record.model_copy(
                    update={
                        "execution_status": "executed",
                        "result_count": 0,
                        "network_attempt_count": (
                            record.network_attempt_count
                            + max(1, exc.network_attempt_count)
                        ),
                        "executed_at": datetime.now(UTC),
                        "skip_reason": "provider_failure_fallback_to_broad_search",
                        "rejection_reason_codes": ["PROVIDER_FAILURE"],
                    }
                )
                by_claim_outcomes[profile.claim_ref].append("PROVIDER_FAILURE")
                continue
            verified = 0
            rejected: set[str] = set()
            for result in outcome.results:
                match = registered_search_match(profile, holder, result)
                if not match.matched:
                    rejected.update(match.reason_codes)
                    continue
                verified += 1
                _merge_authority_search_result(
                    by_url,
                    state=state,
                    profile=profile,
                    holder=holder,
                    result=result,
                    match_reasons=match.reason_codes,
                    source_type=match.source_type,
                )
            result_counts[record.query_key] = len(outcome.results)
            records[record.query_key] = record.model_copy(
                update={
                    "execution_status": "cache_hit" if outcome.cache_hit else "executed",
                    "result_count": len(outcome.results),
                    "verified_candidate_count": verified,
                    "network_attempt_count": (
                        record.network_attempt_count + outcome.network_attempt_count
                    ),
                    "executed_at": datetime.now(UTC),
                    "skip_reason": None,
                    "rejection_reason_codes": sorted(rejected),
                }
            )
            by_claim_outcomes[profile.claim_ref].append(
                "VERIFIED"
                if verified
                else ("NO_SEARCH_RESULTS" if not outcome.results else "NO_VERIFIED_RESULT")
            )

        for profile in profiles:
            outcomes = by_claim_outcomes.get(profile.claim_ref, [])
            queries = [
                record.query
                for record in records.values()
                if record.claim_ref == profile.claim_ref
            ]
            if "VERIFIED" in outcomes:
                gaps = _remove_authority_gap(gaps, profile.claim_ref)
                continue
            reason = (
                "PREFLIGHT_BUDGET_EXHAUSTED"
                if not outcomes
                else "PROVIDER_FAILURE"
                if outcomes and all(item == "PROVIDER_FAILURE" for item in outcomes)
                else "NO_SEARCH_RESULTS"
                if outcomes and all(item in {"NO_SEARCH_RESULTS", "PROVIDER_FAILURE"} for item in outcomes)
                else "NO_VERIFIED_RESULT"
            )
            gaps = _set_authority_gap(
                gaps,
                claim_ref=profile.claim_ref,
                profile_subject=profile.subject,
                reason_code=reason,
                preflight_queries=queries,
            )
        ordered_records = [records[record.query_key] for _, _, record in planned]
        return by_url, result_counts, ordered_records, gaps, used

    async def _execute_query_batch(
        self,
        queries,
        *,
        by_url: dict[str, CandidateSource],
        result_counts: dict[str, int],
        executions: list[SearchQueryExecutionRecord],
    ) -> tuple[
        dict[str, CandidateSource],
        dict[str, int],
        list[SearchQueryExecutionRecord],
        list[SearchProviderError],
    ]:
        records = {record.query_key: record for record in executions}
        failures: list[SearchProviderError] = []
        for query in queries:
            key = query_state_key(query)
            record = records[key]
            if record.execution_status in {"executed", "cache_hit", "not_needed"}:
                continue
            try:
                raw_outcome = await self.search.search(query.query, count=10)
                outcome = _search_outcome(raw_outcome)
            except SearchProviderError as exc:
                failures.append(exc)
                result_counts[key] = 0
                records[key] = record.model_copy(
                    update={
                        "execution_status": "planned" if exc.retryable else "executed",
                        "result_count": 0,
                        "network_attempt_count": (
                            record.network_attempt_count + max(1, exc.network_attempt_count)
                        ),
                        "executed_at": None if exc.retryable else datetime.now(UTC),
                        "skip_reason": (
                            "retryable_provider_failure"
                            if exc.retryable
                            else "provider_request_rejected"
                        ),
                    }
                )
                continue
            result_counts[key] = len(outcome.results)
            records[key] = record.model_copy(
                update={
                    "execution_status": "cache_hit" if outcome.cache_hit else "executed",
                    "result_count": len(outcome.results),
                    "network_attempt_count": (
                        record.network_attempt_count + outcome.network_attempt_count
                    ),
                    "executed_at": datetime.now(UTC),
                    "skip_reason": None,
                }
            )
            _merge_search_results(
                by_url,
                query=query,
                results=outcome.results,
                search_phase=(
                    "broad_phase_one"
                    if record.discovery_phase == "phase_one"
                    else "broad_phase_two"
                ),
            )
        return by_url, result_counts, [records[item.query_key] for item in executions], failures

    async def retrieve(self, state: VerificationState) -> VerificationState:
        snapshots: list[SnapshotRecord] = []
        resolved_sources: dict[str, CandidateSource] = {}
        profiles = {item.claim_ref: item for item in state.authority_profiles}
        retryable_discovered_failure = False
        for source in state.candidate_sources:
            snapshot_id = str(uuid4())
            retrieved_at = datetime.now(UTC)
            fetch_started = time.perf_counter()
            try:
                if self.rate_limiter and not self.rate_limiter.allow(
                    user_id=str(state.user_id), domain=source.domain or "unknown"
                ):
                    raise FetchError("retrieval rate limit reached", access_status="INACCESSIBLE")
                result = await self.fetcher.fetch(source.canonical_url or source.url)
                final_url = result.final_url
                resolved = source
                if final_url != source.canonical_url:
                    # Google News article wrappers and ordinary public redirects
                    # are fetched only through SecureFetcher.  Its per-hop
                    # validation makes the final publisher URL the canonical
                    # durable identity for the retrieved evidence.
                    resolved = source.model_copy(
                        update={
                            "canonical_url": final_url,
                            "domain": urlsplit(final_url).hostname or source.domain,
                        }
                    )
                    if source.source_origin == "authority_preflight":
                        profile = profiles.get(source.authority_claim_ref or "")
                        holder = (
                            holder_for_profile(
                                profile,
                                domain=resolved.domain or "",
                                source_role=source.authority_source_role or "",
                            )
                            if profile is not None
                            else None
                        )
                        if holder is None:
                            resolved = resolved.model_copy(
                                update={
                                    "source_type": "UNKNOWN",
                                    "authority_match_status": "rejected",
                                    "authority_match_reasons": [
                                        *source.authority_match_reasons,
                                        "REDIRECT_DOMAIN_NOT_REGISTERED",
                                    ],
                                    "selection_reason": (
                                        f"Authority preflight result for claim "
                                        f"{source.authority_claim_ref} redirected outside its "
                                        "registered record-holder domain"
                                    ),
                                }
                            )
                    resolved_sources[source.source_ref] = resolved
                snapshots.append(
                    SnapshotRecord(
                        snapshot_id=snapshot_id,
                        source_ref=source.source_ref,
                        access_status="FETCHED",
                        retrieved_at=retrieved_at,
                        content_hash=result.content_hash,
                        content_type=result.content_type,
                        snapshot_path=result.storage_path,
                        metadata={
                            "requested_url": result.requested_url,
                            "final_url": result.final_url,
                            "redirect_chain": list(result.redirect_chain),
                            "content_length": result.content_length,
                            "origin_fetched_at": result.origin_fetched_at,
                            "cache_hit": result.cache_hit,
                            "fetch_latency_ms": round((time.perf_counter() - fetch_started) * 1000, 3),
                            "source_origin": source.source_origin,
                            "search_phase": source.search_phase,
                            "authority_claim_ref": source.authority_claim_ref,
                            "authority_source_role": source.authority_source_role,
                            "authority_match_status": resolved.authority_match_status,
                            "authority_match_reasons": resolved.authority_match_reasons,
                            "authority_profile_version": source.authority_profile_version,
                            "authority_registry_version": source.authority_registry_version,
                            "untrusted_evidence": True,
                        },
                    )
                )
            except FetchError as exc:
                submitted_failure = source.source_origin == "submitted_url"
                retryable_discovered_failure = (
                    retryable_discovered_failure or (exc.retryable and not submitted_failure)
                )
                snapshots.append(
                    SnapshotRecord(
                        snapshot_id=snapshot_id,
                        source_ref=source.source_ref,
                        # An inaccessible URL is a source limitation. Its
                        # transient outage must not discard snapshots already
                        # retrieved from independent evidence sources.
                        access_status=("INACCESSIBLE" if exc.retryable else exc.access_status),
                        retrieved_at=retrieved_at,
                        failure_reason=_source_failure_reason(exc, submitted=submitted_failure),
                        metadata={
                            "source_origin": source.source_origin,
                            "search_phase": source.search_phase,
                            "authority_claim_ref": source.authority_claim_ref,
                            "authority_source_role": source.authority_source_role,
                            "authority_match_status": source.authority_match_status,
                            "authority_match_reasons": source.authority_match_reasons,
                            "authority_profile_version": source.authority_profile_version,
                            "authority_registry_version": source.authority_registry_version,
                            "inaccessible_reason_code": _inaccessible_reason_code(
                                exc, submitted=submitted_failure
                            ),
                            "untrusted_evidence": True,
                            "fetch_latency_ms": round((time.perf_counter() - fetch_started) * 1000, 3),
                        },
                    )
                )
        updated_sources = [
            resolved_sources.get(source.source_ref, source)
            for source in state.candidate_sources
        ]
        authority_gaps = list(state.authority_gaps)
        fetched_refs = {
            snapshot.source_ref
            for snapshot in snapshots
            if snapshot.access_status == "FETCHED"
        }
        for profile in state.authority_profiles:
            candidates = [
                source
                for source in updated_sources
                if source.authority_claim_ref == profile.claim_ref
            ]
            verified_fetched = [
                source
                for source in candidates
                if source.source_ref in fetched_refs
                and source.authority_match_status != "rejected"
            ]
            if verified_fetched:
                authority_gaps = _remove_authority_gap(authority_gaps, profile.claim_ref)
            elif candidates:
                reason = (
                    "INACCESSIBLE_OR_BLOCKED"
                    if not any(source.source_ref in fetched_refs for source in candidates)
                    else "NO_VERIFIED_RESULT"
                )
                authority_gaps = _set_authority_gap(
                    authority_gaps,
                    claim_ref=profile.claim_ref,
                    profile_subject=profile.subject,
                    reason_code=reason,
                    preflight_queries=[
                        item.query
                        for item in state.authority_preflight_queries
                        if item.claim_ref == profile.claim_ref
                    ],
                )
        accessible_count = sum(snapshot.access_status == "FETCHED" for snapshot in snapshots)
        if not accessible_count:
            submitted_count = sum(
                source.source_origin == "submitted_url" for source in state.candidate_sources
            )
            if submitted_count == len(state.candidate_sources):
                raise WorkflowExtensionError(
                    code="SUBMITTED_URL_INACCESSIBLE",
                    public_message="The submitted URL could not be retrieved safely.",
                    details={
                        "submitted_url_count": submitted_count,
                        "snapshot_count": len(snapshots),
                    },
                )
            if retryable_discovered_failure:
                # Retry the whole task only when transient failures left the run
                # with no usable evidence. A single inaccessible candidate must
                # not discard snapshots already fetched from other sources.
                raise WorkflowExtensionError(
                    code="FETCH_UNAVAILABLE",
                    public_message="A source retrieval service was temporarily unavailable.",
                    retryable=True,
                    details={"failure_kind": "fetch", "error_code": "fetch_unavailable"},
                )
            raise WorkflowExtensionError(
                code="NO_ACCESSIBLE_SOURCES",
                public_message="No selected evidence source could be retrieved safely.",
                details={
                    "candidate_count": len(state.candidate_sources),
                    "snapshot_count": len(snapshots),
                },
            )
        return state.model_copy(
            update={
                "snapshots": snapshots,
                "candidate_sources": updated_sources,
                "authority_gaps": authority_gaps,
                "known_evidence_gaps": _known_gaps_with_authority(
                    state.known_evidence_gaps, authority_gaps
                ),
            }
        )

    async def extract(self, state: VerificationState) -> VerificationState:
        snapshots: list[SnapshotRecord] = []
        extracted: list[ExtractedSourceRecord] = []
        sources = {source.source_ref: source for source in state.candidate_sources}
        claims = {claim.claim_ref: claim.text for claim in state.claims}
        objectives = {objective.objective_ref: objective.claim_ref for objective in state.objectives}
        for snapshot in state.snapshots:
            if snapshot.access_status != "FETCHED" or not snapshot.snapshot_path:
                snapshots.append(snapshot)
                continue
            if not snapshot.content_hash:
                raise WorkflowExtensionError(
                    code="SNAPSHOT_HASH_MISSING",
                    public_message="A retrieved evidence snapshot is incomplete.",
                    details={"snapshot_id": snapshot.snapshot_id},
                )
            source = sources[snapshot.source_ref]
            try:
                content = self.fetcher.read_content(
                    snapshot.snapshot_path, expected_hash=snapshot.content_hash
                )
                expected_terms = tuple(
                    claims[objectives[objective_ref]]
                    for objective_ref in source.objective_refs
                    if objective_ref in objectives and objectives[objective_ref] in claims
                )
                outcome = await self.extractor.extract_with_outcome(
                    content,
                    content_type=snapshot.content_type or "",
                    url=str(snapshot.metadata.get("final_url") or source.canonical_url or source.url),
                    expected_terms=expected_terms,
                    allow_browser_fallback=_browser_fallback_is_justified(source),
                )
            except _UNTRUSTED_SOURCE_EXTRACTION_ERRORS:
                # Malformed untrusted source bytes can make a parser reject this
                # source. Storage, state, and invariant failures intentionally
                # propagate to the worker's internal-error path instead.
                outcome = None
            document = outcome.document if outcome is not None else None
            if document is None:
                failure_reason = (
                    outcome.failure_reason
                    if outcome is not None and outcome.failure_reason
                    else "No safe extractor produced sufficient readable content."
                )
                inaccessible_status = (
                    outcome.inaccessible_status
                    if outcome is not None and outcome.inaccessible_status
                    else "INACCESSIBLE"
                )
                extraction_metadata = {
                    "fallback_attempted": bool(outcome and outcome.fallback_attempted),
                    "fallback_reason": outcome.fallback_reason if outcome else None,
                    "extraction_certainty": None,
                    "inaccessible_status": inaccessible_status,
                    "parser_name": outcome.parser_name if outcome else None,
                    "parser_version": outcome.parser_version if outcome else None,
                }
                snapshots.append(
                    snapshot.model_copy(
                        update={
                            "access_status": inaccessible_status,
                            "failure_reason": failure_reason,
                            "parser_name": outcome.parser_name if outcome else None,
                            "parser_version": outcome.parser_version if outcome else None,
                            "metadata": {**snapshot.metadata, "extraction": extraction_metadata},
                        }
                    )
                )
                continue
            snapshots.append(
                snapshot.model_copy(
                    update={
                        "parser_name": document.parser_name,
                        "parser_version": document.parser_version,
                        "published_at": document.published_at,
                        "updated_at": document.updated_at,
                        "extraction_quality": Decimal(str(document.quality)),
                        "metadata": {
                            **snapshot.metadata,
                            **document.metadata,
                            "extraction": {
                                "title": document.title,
                                "author": document.author,
                                "publisher": document.publisher,
                                "headings": list(document.headings),
                                "table_count": len(document.tables),
                                "quote_count": len(document.quotes),
                                "correction_notices": list(document.correction_notices),
                                "outbound_links": list(document.outbound_links),
                                "page_positions": list(document.page_positions),
                                "fallback_attempted": bool(outcome and outcome.fallback_attempted),
                                "fallback_reason": outcome.fallback_reason if outcome else None,
                                "extraction_certainty": document.metadata.get(
                                    "extraction_certainty", document.quality
                                ),
                                "inaccessible_status": None,
                                "parser_name": document.parser_name,
                                "parser_version": document.parser_version,
                            },
                        },
                    }
                )
            )
            extracted.append(
                ExtractedSourceRecord(
                    source_ref=snapshot.source_ref,
                    snapshot_id=snapshot.snapshot_id,
                    body=document.body,
                    title=document.title,
                    author=document.author,
                    publisher=document.publisher,
                    published_at=document.published_at,
                    updated_at=document.updated_at,
                    headings=list(document.headings),
                    tables=list(document.tables),
                    quotes=list(document.quotes),
                    correction_notices=list(document.correction_notices),
                    outbound_links=list(document.outbound_links),
                    page_positions=list(document.page_positions),
                    blocks=[
                        ExtractedBlockRecord(
                            kind=block.kind,
                            text=block.text,
                            heading_path=list(block.heading_path),
                            page_or_position=block.page_or_position,
                            paragraph_index=block.paragraph_index,
                            speaker=block.speaker,
                            table_ref=block.table_ref,
                            metadata=block.metadata,
                        )
                        for block in document.blocks
                    ],
                )
            )
        parser_versions = dict(state.parser_versions)
        for snapshot in snapshots:
            if snapshot.parser_name and snapshot.parser_version:
                parser_versions[snapshot.parser_name] = snapshot.parser_version
        if not extracted:
            raise WorkflowExtensionError(
                code="NO_EXTRACTED_SOURCES",
                public_message="No retrieved evidence source contained usable extractable content.",
                details={
                    "fetched_snapshot_count": sum(
                        snapshot.access_status == "FETCHED" for snapshot in state.snapshots
                    ),
                    "snapshot_count": len(state.snapshots),
                },
            )
        extracted_by_ref = {item.source_ref: item for item in extracted}
        profiles = {item.claim_ref: item for item in state.authority_profiles}
        validated_sources: list[CandidateSource] = []
        validation_by_source: dict[str, CandidateSource] = {}
        for source in state.candidate_sources:
            if (
                source.source_origin != "authority_preflight"
                or source.authority_match_status == "rejected"
            ):
                validated_sources.append(source)
                continue
            profile = profiles.get(source.authority_claim_ref or "")
            extracted_document = extracted_by_ref.get(source.source_ref)
            holder = (
                holder_for_profile(
                    profile,
                    domain=source.domain or "",
                    source_role=source.authority_source_role or "",
                )
                if profile is not None
                else None
            )
            if profile is None or holder is None or extracted_document is None:
                validated = source.model_copy(
                    update={
                        "source_type": "UNKNOWN",
                        "authority_match_status": "rejected",
                        "authority_match_reasons": [
                            *source.authority_match_reasons,
                            "NO_USABLE_EXTRACTED_DOCUMENT",
                        ],
                    }
                )
            else:
                match = registered_document_match(profile, holder, extracted_document)
                validated = source.model_copy(
                    update={
                        "source_type": match.source_type,
                        "authority_match_status": (
                            "verified_document_match" if match.matched else "rejected"
                        ),
                        "authority_match_reasons": list(match.reason_codes),
                        "selection_reason": (
                            source.selection_reason
                            if match.matched
                            else (
                                f"Authority preflight source for claim {profile.claim_ref} "
                                "did not match the expected document scope"
                            )
                        ),
                    }
                )
            validated_sources.append(validated)
            validation_by_source[source.source_ref] = validated

        validated_snapshots: list[SnapshotRecord] = []
        for snapshot in snapshots:
            validated_source = validation_by_source.get(snapshot.source_ref)
            if validated_source is None:
                validated_snapshots.append(snapshot)
                continue
            validated_snapshots.append(
                snapshot.model_copy(
                    update={
                        "metadata": {
                            **snapshot.metadata,
                            "authority_match_status": validated_source.authority_match_status,
                            "authority_match_reasons": validated_source.authority_match_reasons,
                        }
                    }
                )
            )
        snapshots = validated_snapshots
        authority_gaps = list(state.authority_gaps)
        for profile in state.authority_profiles:
            candidates = [
                source
                for source in validated_sources
                if source.authority_claim_ref == profile.claim_ref
            ]
            if any(
                source.authority_match_status == "verified_document_match"
                for source in candidates
            ):
                authority_gaps = _remove_authority_gap(authority_gaps, profile.claim_ref)
            elif candidates:
                authority_gaps = _set_authority_gap(
                    authority_gaps,
                    claim_ref=profile.claim_ref,
                    profile_subject=profile.subject,
                    reason_code=(
                        "NO_EXACT_CLAIM_EVIDENCE"
                        if any(source.source_ref in extracted_by_ref for source in candidates)
                        else "INACCESSIBLE_OR_BLOCKED"
                    ),
                    preflight_queries=[
                        item.query
                        for item in state.authority_preflight_queries
                        if item.claim_ref == profile.claim_ref
                    ],
                )
        return state.model_copy(
            update={
                "snapshots": snapshots,
                "extracted_sources": extracted,
                "parser_versions": parser_versions,
                "candidate_sources": validated_sources,
                "authority_gaps": authority_gaps,
                "known_evidence_gaps": _known_gaps_with_authority(
                    state.known_evidence_gaps, authority_gaps
                ),
            }
        )

    async def aclose(self) -> None:
        await self.search.aclose()
        await self.fetcher.aclose()


def _ensure_query_executions(
    state: VerificationState,
    phase_one: list[SearchQueryOutput],
    reserve: list[SearchQueryOutput],
) -> list[SearchQueryExecutionRecord]:
    records = {record.query_key: record for record in state.search_query_executions}
    phase_one_keys = {query_state_key(query) for query in phase_one}
    reserve_keys = {query_state_key(query) for query in reserve}
    for query in state.queries:
        key = query_state_key(query)
        if key in records:
            continue
        included = key in phase_one_keys | reserve_keys
        records[key] = SearchQueryExecutionRecord(
            query_key=key,
            discovery_phase="phase_one" if key in phase_one_keys else "phase_two",
            execution_status="planned" if included else "not_needed",
            skip_reason=None if included else "outside_effective_budget",
        )
    return [records[query_state_key(query)] for query in state.queries]


def _search_outcome(value: object) -> SearchExecutionOutcome:
    if isinstance(value, SearchExecutionOutcome):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(item, SearchResult) for item in value):
        # Compatibility for deterministic test doubles and older local adapters.
        return SearchExecutionOutcome(
            results=tuple(value),
            cache_hit=False,
            network_attempt_count=1,
        )
    raise TypeError("search clients must return SearchExecutionOutcome")


def _merge_search_results(
    by_url: dict[str, CandidateSource],
    *,
    query: SearchQueryOutput,
    results: tuple[SearchResult, ...],
    search_phase: CandidateSearchPhaseValue,
) -> None:
    for result in results:
        try:
            canonical = canonicalize_url(result.url)
        except UnsafeUrlError:
            continue
        domain = urlsplit(canonical).hostname or ""
        relevance = lexical_overlap(query.query, result.title, result.snippet)
        intent = query.intent.value
        directness = Decimal("1") if intent == "primary" else Decimal("0.6")
        same_domain_count = sum(item.domain == domain for item in by_url.values())
        same_title_count = sum(
            (item.title or "").casefold() == (result.title or "").casefold()
            for item in by_url.values()
            if result.title
        )
        signals = RankingSignals(
            relevance=relevance,
            directness=directness,
            temporal_fit=Decimal("0.7" if result.published_at else "0.5"),
            diversity=Decimal("1" if same_domain_count == 0 else "0.5"),
            novelty=Decimal("1" if same_title_count == 0 else "0.25"),
            extractability=Decimal("0.8"),
        )
        score = priority_score(signals)
        existing = by_url.get(canonical)
        objective_refs = sorted(
            set((existing.objective_refs if existing else []) + [query.objective_ref])
        )
        evidence_intents = cast(
            list[EvidenceIntentValue],
            sorted(set((existing.evidence_intents if existing else []) + [intent])),
        )
        if existing is not None and existing.authority_match_status in {
            "verified_search_match",
            "verified_document_match",
        }:
            by_url[canonical] = existing.model_copy(
                update={
                    "objective_refs": objective_refs,
                    "evidence_intents": evidence_intents,
                }
            )
        elif existing is None or score > existing.priority:
            by_url[canonical] = CandidateSource(
                source_ref=f"source-{len(by_url) + 1}",
                url=result.url,
                canonical_url=canonical,
                domain=domain,
                snippet=result.snippet,
                objective_refs=objective_refs,
                evidence_intents=evidence_intents,
                title=result.title,
                # Planner intent is not publisher verification. Broad results
                # remain unclassified until another deterministic boundary can
                # establish their source role.
                source_type="UNKNOWN",
                source_origin="brave_discovery",
                selection_reason=f"Brave result for {intent} objective {query.objective_ref}",
                priority=score,
                search_phase=search_phase,
            )
        else:
            by_url[canonical] = existing.model_copy(
                update={
                    "objective_refs": objective_refs,
                    "evidence_intents": evidence_intents,
                }
            )


def _merge_authority_search_result(
    by_url: dict[str, CandidateSource],
    *,
    state: VerificationState,
    profile: AuthorityProfileRecord,
    holder: AuthorityRecordHolderRecord,
    result: SearchResult,
    match_reasons: tuple[str, ...],
    source_type: SourceTypeValue,
) -> None:
    try:
        canonical = canonicalize_url(result.url)
    except UnsafeUrlError:
        return
    domain = urlsplit(canonical).hostname or ""
    objective_refs = sorted(
        objective.objective_ref
        for objective in state.objectives
        if objective.claim_ref == profile.claim_ref
    )
    query_basis = " ".join(
        part
        for part in (
            profile.entity,
            profile.jurisdiction,
            profile.timeframe,
            profile.metric_or_quotation,
            holder.source_role,
        )
        if part
    )
    relevance = lexical_overlap(query_basis, result.title, result.snippet)
    same_domain_count = sum(item.domain == domain for item in by_url.values())
    same_title_count = sum(
        (item.title or "").casefold() == (result.title or "").casefold()
        for item in by_url.values()
        if result.title
    )
    score = priority_score(
        RankingSignals(
            relevance=relevance,
            directness=Decimal("1"),
            temporal_fit=Decimal("0.7" if result.published_at else "0.5"),
            diversity=Decimal("1" if same_domain_count == 0 else "0.5"),
            novelty=Decimal("1" if same_title_count == 0 else "0.25"),
            extractability=Decimal("0.8"),
        )
    )
    existing = by_url.get(canonical)
    if existing is not None:
        objective_refs = sorted(set(existing.objective_refs + objective_refs))
    candidate = CandidateSource(
        source_ref=(existing.source_ref if existing is not None else f"authority-{len(by_url) + 1}"),
        url=result.url,
        canonical_url=canonical,
        domain=domain,
        snippet=result.snippet,
        objective_refs=objective_refs,
        evidence_intents=cast(
            list[EvidenceIntentValue],
            sorted(set((existing.evidence_intents if existing else []) + ["primary"])),
        ),
        title=result.title,
        source_type=source_type,
        source_origin="authority_preflight",
        selection_reason=(
            f"Verified {holder.source_role} for claim {profile.claim_ref} on registered "
            f"record-holder domain {holder.domain}"
        ),
        priority=max(score, existing.priority if existing is not None else Decimal("0")),
        search_phase="authority_preflight",
        authority_claim_ref=profile.claim_ref,
        authority_source_role=holder.source_role,
        authority_match_status="verified_search_match",
        authority_match_reasons=list(match_reasons),
        authority_profile_version=profile.profile_version,
        authority_registry_version=profile.registry_version,
    )
    by_url[canonical] = candidate


def _set_authority_gap(
    gaps: list[AuthorityGapRecord],
    *,
    claim_ref: str,
    profile_subject: AuthoritySubjectValue,
    reason_code: AuthorityGapReasonValue,
    preflight_queries: list[str],
) -> list[AuthorityGapRecord]:
    retained = [item for item in gaps if item.claim_ref != claim_ref]
    return [
        *retained,
        AuthorityGapRecord(
            code=AUTHORITY_GAP_CODE,
            claim_ref=claim_ref,
            profile_subject=profile_subject,
            reason_code=reason_code,
            preflight_queries=list(dict.fromkeys(preflight_queries)),
            recorded_at=datetime.now(UTC),
        ),
    ]


def _remove_authority_gap(
    gaps: list[AuthorityGapRecord], claim_ref: str
) -> list[AuthorityGapRecord]:
    return [item for item in gaps if item.claim_ref != claim_ref]


def _known_gaps_with_authority(
    known: list[str], gaps: list[AuthorityGapRecord]
) -> list[str]:
    values = [item for item in known if item != AUTHORITY_GAP_CODE]
    if gaps:
        values.append(AUTHORITY_GAP_CODE)
    return values


def _gate_record(decision, *, policy, phase: str, batch_number: int) -> DiscoveryGateRecord:
    return DiscoveryGateRecord(
        discovery_phase=phase,
        batch_number=batch_number,
        passed=decision.passed,
        candidate_count=decision.candidate_count,
        domain_count=decision.domain_count,
        minimum_candidate_count=policy.minimum_candidate_count,
        minimum_domain_count=policy.minimum_domain_count,
        reason_codes=list(decision.reason_codes),
        missing_primary_claim_refs=list(decision.missing_primary_claim_refs),
        missing_contradiction_claim_refs=list(decision.missing_contradiction_claim_refs),
        attribution_covered=decision.attribution_covered,
    )


def _browser_fallback_is_justified(source: CandidateSource) -> bool:
    return bool(
        source.priority >= Decimal("0.7500")
        or source.source_type in {"PRIMARY", "OFFICIAL_SELF_REPORT"}
        or {"primary", "correction"}.intersection(source.evidence_intents)
    )


def _submitted_url_source(state: VerificationState) -> CandidateSource | None:
    normalized = state.normalized_input
    if normalized is None or normalized.input_kind.value != "article_url":
        return None
    submitted_url = normalized.normalized_text
    try:
        canonical_url = canonicalize_url(submitted_url)
    except UnsafeUrlError:
        # Intake preserves the original user input.  SecureFetcher is the
        # authoritative URL-policy boundary and will record the safe failure.
        canonical_url = submitted_url
    try:
        domain = urlsplit(canonical_url).hostname or None
    except ValueError:
        domain = None
    return CandidateSource(
        source_ref="submitted-url",
        url=submitted_url,
        canonical_url=canonical_url,
        domain=domain,
        objective_refs=[objective.objective_ref for objective in state.objectives],
        evidence_intents=["support"],
        selection_reason="Submitted article URL retrieval seed",
        source_origin="submitted_url",
        priority=Decimal("1"),
        search_phase="submitted",
    )


def _inaccessible_reason_code(exc: FetchError, *, submitted: bool) -> str:
    prefix = "SUBMITTED_URL" if submitted else "SOURCE"
    status = exc.access_status if exc.access_status in {"PAYWALLED", "BOT_BLOCKED", "UNSUPPORTED"} else "INACCESSIBLE"
    return f"{prefix}_{status}"


def _submitted_url_failure_reason(exc: FetchError) -> str:
    """Return a precise public limitation without propagating transport detail."""
    return {
        "PAYWALLED": "The submitted URL is paywalled or requires authentication.",
        "BOT_BLOCKED": "The submitted URL denied automated retrieval.",
        "UNSUPPORTED": "The submitted URL returned unsupported content.",
    }.get(
        exc.access_status,
        (
            "The submitted URL was temporarily unavailable."
            if exc.retryable
            else "The submitted URL could not be accessed safely."
        ),
    )


def _source_failure_reason(exc: FetchError, *, submitted: bool) -> str:
    """Return a public source limitation without transport or URL details."""
    if submitted:
        return _submitted_url_failure_reason(exc)
    return {
        "PAYWALLED": "The evidence source is paywalled or requires authentication.",
        "BOT_BLOCKED": "The evidence source denied automated retrieval.",
        "UNSUPPORTED": "The evidence source returned unsupported content.",
    }.get(
        exc.access_status,
        (
            "The evidence source was temporarily unavailable."
            if exc.retryable
            else "The evidence source could not be accessed safely."
        ),
    )

__all__ = ["RetrievalPipeline"]
