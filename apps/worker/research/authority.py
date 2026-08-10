"""Deterministic authority profiles and source-role verification.

The planner may describe desirable source types, but it never gets to invent a
trusted publisher.  This module is the maintained policy boundary that maps a
claim to a small set of registered record holders and verifies search/document
matches before an authoritative source role is assigned.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Iterable, Literal
from urllib.parse import urlsplit

from agents.schemas import ClaimKind, FactCheckability, InputKind

if TYPE_CHECKING:
    from graph.state import (
        AuthorityProfileRecord,
        AuthorityRecordHolderRecord,
        ExtractedSourceRecord,
        VerificationState,
    )
    from research.search import SearchResult


AuthoritySubject = Literal[
    "compensation",
    "legal",
    "medical",
    "product",
    "corporate",
    "quotation",
    "public_record",
]
AuthoritySourceType = Literal["PRIMARY", "OFFICIAL_SELF_REPORT"]

AUTHORITY_PROFILE_VERSION = "authority-profile-v1"
AUTHORITY_POLICY_REGISTRY_VERSION = "authority-registry-v1"
AUTHORITY_PREFLIGHT_TOTAL_BUDGET = 6
AUTHORITY_PREFLIGHT_PER_CLAIM = 2
AUTHORITY_PREFLIGHT_RESULT_LIMIT = 5

AUTHORITY_GAP_CODE: Literal["APPLICABLE_AUTHORITATIVE_SOURCE_NOT_FOUND"] = (
    "APPLICABLE_AUTHORITATIVE_SOURCE_NOT_FOUND"
)


@dataclass(frozen=True, slots=True)
class RegisteredRecordHolder:
    subject: AuthoritySubject
    source_role: str
    domain: str
    entity: str
    entity_aliases: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    query_terms: tuple[str, ...]
    document_terms: tuple[str, ...]
    source_type: AuthoritySourceType = "PRIMARY"
    priority: int = 100
    entity_match_required: bool = False
    allow_unknown_jurisdiction: bool = False


@dataclass(frozen=True, slots=True)
class AuthorityDerivation:
    profile: AuthorityProfileRecord | None
    subject: AuthoritySubject | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorityMatch:
    matched: bool
    source_type: AuthoritySourceType | Literal["UNKNOWN"]
    reason_codes: tuple[str, ...]


_HOLDERS: tuple[RegisteredRecordHolder, ...] = (
    # Employment terms. Multiple holders are deliberately registered because
    # the applicable bargaining unit/employer may be uncertain at intake.
    RegisteredRecordHolder(
        "compensation", "union_agreement", "ona.org", "Ontario Nurses' Association",
        ("ontario nurses association", "ona", "registered nurse", "registered nurses", "rn", "nurse", "nurses"),
        ("ontario",), ("collective agreement", "wage grid"),
        ("collective agreement", "wage", "salary", "pay grid", "hourly rate"), priority=10,
    ),
    RegisteredRecordHolder(
        "compensation", "government_labour_record", "ontario.ca", "Ontario Ministry of Labour",
        ("ontario", "ministry of labour"), ("ontario",), ("labour record", "wage"),
        ("wage", "employment standards", "collective agreement", "labour"), priority=20,
    ),
    RegisteredRecordHolder(
        "compensation", "union_agreement", "una.ca", "United Nurses of Alberta",
        ("united nurses of alberta", "una", "registered nurse", "rn", "nurse", "nurses"),
        ("alberta",), ("collective agreement", "salary appendix"),
        ("collective agreement", "salary", "wage", "pay grid"), priority=10,
    ),
    RegisteredRecordHolder(
        "compensation", "government_labour_record", "alberta.ca", "Government of Alberta",
        ("alberta",), ("alberta",), ("labour record", "wage"),
        ("wage", "employment standards", "collective agreement", "labour"), priority=20,
    ),
    RegisteredRecordHolder(
        "compensation", "government_labour_record", "dol.gov", "United States Department of Labor",
        ("united states", "u.s.", "us", "department of labor"), ("united states", "us", "u.s."),
        ("wage record", "employment terms"), ("wage", "salary", "employment", "labor"), priority=30,
    ),
    # Law, regulation, enforcement, and court records.
    RegisteredRecordHolder(
        "legal", "official_statute_regulation", "laws-lois.justice.gc.ca", "Justice Laws Website",
        ("canada", "federal"), ("canada", "federal"), ("act", "regulation"),
        ("act", "regulation", "statute", "law"), priority=10, allow_unknown_jurisdiction=True,
    ),
    RegisteredRecordHolder(
        "legal", "court_regulator_tribunal_record", "scc-csc.ca", "Supreme Court of Canada",
        ("supreme court of canada", "scc", "canada"), ("canada", "federal"),
        ("judgment", "decision"), ("judgment", "decision", "reasons for judgment", "docket"), priority=10,
    ),
    RegisteredRecordHolder(
        "legal", "official_statute_regulation", "ontario.ca", "Government of Ontario",
        ("ontario",), ("ontario",), ("law", "regulation"),
        ("act", "regulation", "statute", "law"), priority=10,
    ),
    RegisteredRecordHolder(
        "legal", "court_regulator_tribunal_record", "canlii.org", "CanLII",
        ("canada", "ontario", "court", "tribunal"), ("canada", "ontario"),
        ("decision", "judgment"), ("decision", "judgment", "citation", "docket"), priority=20,
    ),
    RegisteredRecordHolder(
        "legal", "official_statute_regulation", "congress.gov", "United States Congress",
        ("united states", "u.s.", "us", "congress"), ("united states", "us", "u.s."),
        ("bill", "public law"), ("bill", "public law", "statute", "congress"), priority=10,
    ),
    RegisteredRecordHolder(
        "legal", "court_regulator_tribunal_record", "justice.gov", "United States Department of Justice",
        ("united states", "u.s.", "us", "department of justice", "doj"),
        ("united states", "us", "u.s."), ("enforcement action", "court filing"),
        ("complaint", "indictment", "enforcement", "settlement", "court"), priority=20,
    ),
    # Medical and public-health guidance.
    RegisteredRecordHolder(
        "medical", "public_health_guidance", "who.int", "World Health Organization",
        ("world health organization", "who"), (), ("guidance", "systematic review"),
        ("guideline", "guidance", "recommendation", "systematic review", "study"), priority=20,
        allow_unknown_jurisdiction=True,
    ),
    RegisteredRecordHolder(
        "medical", "public_health_guidance", "canada.ca", "Health Canada / Public Health Agency of Canada",
        ("health canada", "public health agency of canada", "phac", "canada"), ("canada",),
        ("health guidance", "advisory"), ("guidance", "advisory", "recommendation", "safety"), priority=10,
    ),
    RegisteredRecordHolder(
        "medical", "public_health_guidance", "cdc.gov", "Centers for Disease Control and Prevention",
        ("centers for disease control", "cdc", "united states", "u.s.", "us"),
        ("united states", "us", "u.s."), ("clinical guidance", "health guidance"),
        ("guidance", "recommendation", "clinical", "health"), priority=10,
    ),
    RegisteredRecordHolder(
        "medical", "regulator_guidance", "fda.gov", "U.S. Food and Drug Administration",
        ("food and drug administration", "fda", "united states", "u.s.", "us"),
        ("united states", "us", "u.s."), ("safety communication", "guidance"),
        ("safety communication", "guidance", "approval", "recall"), priority=15,
    ),
    # Product documentation, certification, and recalls.
    RegisteredRecordHolder(
        "product", "manufacturer_documentation", "apple.com", "Apple",
        ("apple", "iphone", "ipad", "macbook", "airpods"), (), ("technical specifications", "support"),
        ("technical specifications", "specifications", "user guide", "support"),
        source_type="OFFICIAL_SELF_REPORT", priority=10, entity_match_required=True,
    ),
    RegisteredRecordHolder(
        "product", "manufacturer_documentation", "tesla.com", "Tesla",
        ("tesla", "model 3", "model y", "model s", "model x", "cybertruck"), (),
        ("specifications", "owner manual"), ("specifications", "owner's manual", "owner manual", "support"),
        source_type="OFFICIAL_SELF_REPORT", priority=10, entity_match_required=True,
    ),
    RegisteredRecordHolder(
        "product", "recall_database", "recalls-rappels.canada.ca", "Government of Canada Recalls and Safety Alerts",
        ("canada", "recall"), ("canada",), ("recall", "safety alert"),
        ("recall", "safety alert", "affected products"), priority=20,
    ),
    RegisteredRecordHolder(
        "product", "recall_database", "cpsc.gov", "U.S. Consumer Product Safety Commission",
        ("cpsc", "united states", "u.s.", "us", "recall"), ("united states", "us", "u.s."),
        ("recall", "product safety"), ("recall", "hazard", "consumer product"), priority=20,
    ),
    RegisteredRecordHolder(
        "product", "recall_database", "nhtsa.gov", "National Highway Traffic Safety Administration",
        ("nhtsa", "vehicle", "car", "truck", "united states", "u.s.", "us"),
        ("united states", "us", "u.s."), ("vehicle recall", "safety recall"),
        ("recall", "vehicle", "safety", "campaign number"), priority=15,
    ),
    # Corporate filings and issuer records.
    RegisteredRecordHolder(
        "corporate", "securities_regulator_record", "sec.gov", "U.S. Securities and Exchange Commission",
        ("company", "corporation", "issuer", "revenue", "earnings", "ownership", "filing", "annual report"),
        ("united states", "us", "u.s."), ("10-k", "10-q", "8-k", "company filing"),
        ("10-k", "10-q", "8-k", "annual report", "filing", "form"), priority=10,
        allow_unknown_jurisdiction=True,
    ),
    RegisteredRecordHolder(
        "corporate", "securities_regulator_record", "sedarplus.ca", "SEDAR+",
        ("company", "corporation", "issuer", "revenue", "earnings", "ownership", "filing", "annual report"),
        ("canada",), ("annual filing", "financial statements", "material change"),
        ("annual report", "financial statements", "management discussion", "material change"), priority=15,
        allow_unknown_jurisdiction=True,
    ),
    RegisteredRecordHolder(
        "corporate", "issuer_filing", "apple.com", "Apple",
        ("apple",), (), ("investor relations", "annual report"),
        ("annual report", "financial results", "investor relations"),
        source_type="OFFICIAL_SELF_REPORT", priority=20, entity_match_required=True,
    ),
    RegisteredRecordHolder(
        "corporate", "issuer_filing", "tesla.com", "Tesla",
        ("tesla",), (), ("investor relations", "annual report"),
        ("annual report", "financial results", "investor relations"),
        source_type="OFFICIAL_SELF_REPORT", priority=20, entity_match_required=True,
    ),
    RegisteredRecordHolder(
        "corporate", "issuer_filing", "microsoft.com", "Microsoft",
        ("microsoft",), (), ("investor relations", "annual report"),
        ("annual report", "financial results", "investor relations"),
        source_type="OFFICIAL_SELF_REPORT", priority=20, entity_match_required=True,
    ),
    # Original quotation and contemporaneous public-statement records.
    RegisteredRecordHolder(
        "quotation", "original_recording_or_transcript", "whitehouse.gov", "The White House",
        ("president", "white house", "united states", "u.s.", "us"),
        ("united states", "us", "u.s."), ("remarks", "transcript"),
        ("remarks", "transcript", "briefing", "statement"), priority=10,
        allow_unknown_jurisdiction=True,
    ),
    RegisteredRecordHolder(
        "quotation", "original_recording_or_transcript", "pm.gc.ca", "Prime Minister of Canada",
        ("prime minister", "canada", "carney", "trudeau"), ("canada",),
        ("statement", "transcript", "remarks"), ("statement", "transcript", "remarks", "speech"), priority=10,
        allow_unknown_jurisdiction=True,
    ),
    RegisteredRecordHolder(
        "quotation", "original_recording_or_transcript", "c-span.org", "C-SPAN",
        ("congress", "president", "united states", "u.s.", "us"),
        ("united states", "us", "u.s."), ("video", "transcript"),
        ("video", "transcript", "remarks", "hearing"), priority=20,
        allow_unknown_jurisdiction=True,
    ),
    # Elections, public programs, and official statistics.
    RegisteredRecordHolder(
        "public_record", "election_body_record", "elections.ca", "Elections Canada",
        ("election", "vote", "ballot", "canada"), ("canada",), ("official voting results", "election results"),
        ("official voting results", "election results", "polls reporting", "validated results"), priority=10,
    ),
    RegisteredRecordHolder(
        "public_record", "official_statistic", "statcan.gc.ca", "Statistics Canada",
        ("statistics canada", "statcan", "canada", "population", "employment", "inflation"), ("canada",),
        ("data table", "official statistics"), ("data table", "survey", "census", "statistics"), priority=10,
    ),
    RegisteredRecordHolder(
        "public_record", "official_statistic", "census.gov", "United States Census Bureau",
        ("census", "population", "united states", "u.s.", "us"), ("united states", "us", "u.s."),
        ("data table", "official statistics"), ("data table", "survey", "census", "statistics"), priority=10,
    ),
    RegisteredRecordHolder(
        "public_record", "official_statistic", "bls.gov", "U.S. Bureau of Labor Statistics",
        ("employment", "unemployment", "inflation", "wage", "united states", "u.s.", "us"),
        ("united states", "us", "u.s."), ("data series", "official statistics"),
        ("data series", "news release", "survey", "statistics"), priority=10,
    ),
)


_SUBJECT_TERMS = {
    "compensation": (
        "wage", "wages", "salary", "salaries", "pay", "benefit", "benefits",
        "hourly rate", "employment terms", "collective agreement", "compensation",
    ),
    "legal": (
        "law", "statute", "regulation", "court", "judgment", "ruling", "tribunal",
        "enforcement", "lawsuit", "charged", "convicted", "settlement", "legislation",
    ),
    "medical": (
        "medical", "medicine", "health", "disease", "vaccine", "treatment", "drug",
        "clinical", "public health", "safety guidance", "diagnosis", "infection",
    ),
    "product": (
        "product", "specification", "specifications", "certification", "certified",
        "recall", "model", "device", "battery", "vehicle", "technical", "feature",
    ),
    "corporate": (
        "revenue", "earnings", "profit", "financial", "ownership", "shareholder",
        "acquisition", "merger", "expansion", "locations", "annual report", "filing",
        "subsidiary", "market share",
    ),
    "quotation": ("said", "stated", "claimed", "announced", "remarks", "quote", "quotation"),
    "public_record": (
        "election", "votes", "ballots", "government program", "census", "population",
        "unemployment", "inflation", "official statistic", "statistics agency",
    ),
}

_METRIC_TERMS = {
    "compensation": ("wage", "salary", "pay", "benefit", "hourly", "rate", "step"),
    "legal": ("law", "act", "regulation", "decision", "judgment", "ruling", "enforcement"),
    "medical": ("guidance", "recommendation", "risk", "dose", "rate", "treatment", "safety"),
    "product": ("specification", "specifications", "certification", "recall", "model", "capacity", "range"),
    "corporate": ("revenue", "earnings", "profit", "ownership", "locations", "filing", "annual report"),
    "quotation": ("remarks", "statement", "transcript", "said", "stated", "announced"),
    "public_record": ("results", "votes", "population", "rate", "percentage", "total", "statistics"),
}

_STOP_WORDS = {
    "about", "after", "again", "against", "also", "among", "because", "before", "being",
    "between", "claim", "could", "does", "from", "have", "into", "more", "most", "other",
    "over", "said", "says", "than", "that", "their", "there", "these", "they", "this", "through",
    "under", "were", "what", "when", "where", "which", "while", "with", "would",
}


def derive_authority_profiles(state: VerificationState) -> tuple[list[AuthorityProfileRecord], list[tuple[str, str, str]]]:
    """Return useful profiles and deterministic ambiguous-profile gaps.

    Gap tuples contain ``(claim_ref, subject, reason_code)`` and deliberately do
    not carry model prose.
    """

    profiles: list[AuthorityProfileRecord] = []
    gaps: list[tuple[str, str, str]] = []
    for claim in state.claims:
        if claim.fact_checkability == FactCheckability.NOT_FACT_CHECKABLE:
            continue
        derived = derive_authority_profile(state, claim.claim_ref)
        if derived.profile is not None:
            profiles.append(derived.profile)
        elif derived.subject and derived.reason_code:
            gaps.append((claim.claim_ref, derived.subject, derived.reason_code))
    return profiles, gaps


def derive_authority_profile(state: VerificationState, claim_ref: str) -> AuthorityDerivation:
    from graph.state import AuthorityProfileRecord, AuthorityRecordHolderRecord

    claim = next((item for item in state.claims if item.claim_ref == claim_ref), None)
    if claim is None:
        return AuthorityDerivation(None)
    normalized = state.normalized_input
    text = " ".join(
        part for part in (
            claim.text,
            claim.original_text_span or "",
            claim.verification_scope,
            " ".join(item.name for item in claim.entities),
            " ".join(claim.locations),
            claim.time_period or "",
        ) if part
    )
    subject = _subject_for_claim(
        text,
        claim_kind=claim.claim_kind,
        input_kind=normalized.input_kind if normalized is not None else None,
    )
    if subject is None:
        return AuthorityDerivation(None)
    entity = _first_entity(
        [item.name for item in claim.entities]
        or ([item.name for item in normalized.entities] if normalized is not None else [])
    )
    jurisdiction = _jurisdiction(
        [*claim.locations, *(normalized.locations if normalized is not None else [])], text
    )
    timeframe = claim.time_period or _first_year(text)
    metric_or_quotation = _metric_or_quotation(state, claim_ref, subject)
    holders = _matching_holders(subject, text=text, entity=entity, jurisdiction=jurisdiction)
    if not holders:
        return AuthorityDerivation(None, subject, "AUTHORITY_PROFILE_AMBIGUOUS")
    records = [
        AuthorityRecordHolderRecord(
            domain=holder.domain,
            source_role=holder.source_role,
            entity=holder.entity,
            jurisdictions=list(holder.jurisdictions),
            query_terms=list(holder.query_terms),
            document_terms=list(holder.document_terms),
            source_type=holder.source_type,
        )
        for holder in holders
    ]
    return AuthorityDerivation(
        AuthorityProfileRecord(
            claim_ref=claim.claim_ref,
            subject=subject,
            entity=entity,
            jurisdiction=jurisdiction,
            timeframe=timeframe,
            metric_or_quotation=metric_or_quotation,
            expected_source_roles=list(dict.fromkeys(holder.source_role for holder in holders)),
            record_holders=records,
            profile_version=AUTHORITY_PROFILE_VERSION,
            registry_version=AUTHORITY_POLICY_REGISTRY_VERSION,
            created_at=state.started_at,
        )
    )


def build_preflight_query(profile: AuthorityProfileRecord, holder: AuthorityRecordHolderRecord) -> str:
    components = [
        profile.entity,
        profile.jurisdiction,
        profile.timeframe,
        *holder.query_terms,
        profile.metric_or_quotation,
    ]
    parts = [f"site:{holder.domain}"]
    for value in components:
        phrase = _safe_query_phrase(value)
        if not phrase:
            continue
        token = f'"{phrase}"'
        if len(" ".join([*parts, token])) > 500:
            break
        parts.append(token)
    return " ".join(parts)


def registered_search_match(
    profile: AuthorityProfileRecord,
    holder: AuthorityRecordHolderRecord,
    result: SearchResult,
) -> AuthorityMatch:
    domain = _hostname(result.url)
    reasons: list[str] = []
    if not _domain_matches(domain, holder.domain):
        return AuthorityMatch(False, "UNKNOWN", ("DOMAIN_NOT_REGISTERED",))
    reasons.append("DOMAIN_REGISTERED")
    searchable = f"{result.title or ''} {result.snippet or ''} {result.profile or ''}".casefold()
    if not _contains_any(searchable, holder.document_terms):
        reasons.append("DOCUMENT_ROLE_NOT_MATCHED")
    else:
        reasons.append("DOCUMENT_ROLE_MATCHED")
    if profile.entity and not _contains_entity(searchable, profile.entity, holder.entity):
        # A registry-bound publisher can establish the responsible entity when
        # a terse Brave result omits the organization name.
        reasons.append("ENTITY_BOUND_TO_REGISTERED_DOMAIN")
    else:
        reasons.append("ENTITY_MATCHED")
    if profile.jurisdiction and not (
        _contains_phrase(searchable, profile.jurisdiction)
        or any(_contains_phrase(profile.jurisdiction.casefold(), item) for item in holder.jurisdictions)
    ):
        reasons.append("JURISDICTION_NOT_MATCHED")
    else:
        reasons.append("JURISDICTION_MATCHED")
    timeframe_year = _first_year(profile.timeframe or "")
    if timeframe_year and timeframe_year not in searchable:
        reasons.append("TIMEFRAME_NOT_MATCHED")
    else:
        reasons.append("TIMEFRAME_MATCHED")
    if profile.metric_or_quotation and not _metric_matches(
        searchable, profile.metric_or_quotation, profile.subject
    ):
        reasons.append("CLAIM_FOCUS_NOT_MATCHED")
    else:
        reasons.append("CLAIM_FOCUS_MATCHED")
    _append_context_requirement_reasons(reasons, profile, searchable)
    matched = not any(code.endswith("NOT_MATCHED") for code in reasons)
    return AuthorityMatch(matched, holder.source_type if matched else "UNKNOWN", tuple(reasons))


def registered_document_match(
    profile: AuthorityProfileRecord,
    holder: AuthorityRecordHolderRecord,
    document: ExtractedSourceRecord,
) -> AuthorityMatch:
    searchable = " ".join(
        [
            document.title or "",
            document.publisher or "",
            *document.headings,
            document.body,
        ]
    ).casefold()
    reasons: list[str] = ["DOMAIN_REGISTERED"]
    reasons.append(
        "DOCUMENT_ROLE_MATCHED"
        if _contains_any(searchable, holder.document_terms)
        else "DOCUMENT_ROLE_NOT_MATCHED"
    )
    reasons.append(
        "ENTITY_MATCHED"
        if _contains_entity(searchable, profile.entity, holder.entity)
        else "ENTITY_NOT_MATCHED"
    )
    if profile.jurisdiction:
        reasons.append(
            "JURISDICTION_MATCHED"
            if _contains_phrase(searchable, profile.jurisdiction)
            or any(_contains_phrase(profile.jurisdiction.casefold(), item) for item in holder.jurisdictions)
            else "JURISDICTION_NOT_MATCHED"
        )
    else:
        reasons.append("JURISDICTION_MATCHED")
    year = _first_year(profile.timeframe or "")
    reasons.append(
        "TIMEFRAME_MATCHED" if not year or year in searchable else "TIMEFRAME_NOT_MATCHED"
    )
    reasons.append(
        "CLAIM_FOCUS_MATCHED"
        if not profile.metric_or_quotation
        or _metric_matches(searchable, profile.metric_or_quotation, profile.subject)
        else "CLAIM_FOCUS_NOT_MATCHED"
    )
    _append_context_requirement_reasons(reasons, profile, searchable)
    matched = not any(code.endswith("NOT_MATCHED") for code in reasons)
    return AuthorityMatch(matched, holder.source_type if matched else "UNKNOWN", tuple(reasons))


def holder_for_profile(
    profile: AuthorityProfileRecord, *, domain: str, source_role: str
) -> AuthorityRecordHolderRecord | None:
    return next(
        (
            holder
            for holder in profile.record_holders
            if holder.source_role == source_role and _domain_matches(domain, holder.domain)
        ),
        None,
    )


def _subject_for_claim(
    text: str, *, claim_kind: ClaimKind, input_kind: InputKind | None
) -> AuthoritySubject | None:
    lowered = text.casefold()
    if claim_kind in {ClaimKind.QUOTATION, ClaimKind.ATTRIBUTION} or input_kind == InputKind.QUOTE:
        return "quotation"
    if claim_kind == ClaimKind.LEGAL:
        return "legal"
    ordered_subjects: tuple[AuthoritySubject, ...] = (
        "compensation",
        "legal",
        "medical",
        "product",
        "corporate",
        "public_record",
    )
    for subject in ordered_subjects:
        if _contains_any(lowered, _SUBJECT_TERMS[subject]):
            return subject
    if claim_kind == ClaimKind.SCIENTIFIC and _contains_any(lowered, _SUBJECT_TERMS["medical"]):
        return "medical"
    if _contains_any(lowered, _SUBJECT_TERMS["quotation"]):
        return "quotation"
    return None


def _matching_holders(
    subject: AuthoritySubject, *, text: str, entity: str | None, jurisdiction: str | None
) -> list[RegisteredRecordHolder]:
    haystack = f"{text} {entity or ''}".casefold()
    entity_text = (entity or "").casefold()
    matches: list[tuple[RegisteredRecordHolder, bool]] = []
    for holder in _HOLDERS:
        if holder.subject != subject:
            continue
        entity_matches = _contains_any(haystack, holder.entity_aliases)
        explicit_entity_match = bool(
            entity_text and _contains_any(entity_text, holder.entity_aliases)
        )
        if holder.entity_match_required and not entity_matches:
            continue
        if holder.jurisdictions:
            jurisdiction_matches = bool(
                jurisdiction
                and any(
                    _contains_phrase(jurisdiction.casefold(), value)
                    or _contains_phrase(value, jurisdiction.casefold())
                    for value in holder.jurisdictions
                )
            )
            if not jurisdiction_matches and not holder.allow_unknown_jurisdiction:
                continue
        matches.append((holder, explicit_entity_match))
    if any(explicit for _, explicit in matches):
        matches = [
            (holder, explicit)
            for holder, explicit in matches
            if explicit
            or (
                subject == "corporate"
                and holder.source_role == "securities_regulator_record"
            )
            or (subject == "product" and holder.source_role == "recall_database")
        ]
    return [
        holder
        for holder, _ in sorted(
            matches,
            key=lambda item: (
                not item[1],
                item[0].priority,
                item[0].domain,
                item[0].source_role,
            ),
        )
    ]


def _metric_or_quotation(
    state: VerificationState, claim_ref: str, subject: AuthoritySubject
) -> str | None:
    claim = next(item for item in state.claims if item.claim_ref == claim_ref)
    if subject == "quotation":
        return (claim.original_text_span or claim.text)[:180]
    metrics = [item.name for item in claim.metrics]
    if not metrics and state.normalized_input is not None:
        metrics = [item.name for item in state.normalized_input.metrics]
    if metrics:
        return " ".join(metrics)[:180]
    lowered = claim.text.casefold()
    return next((term for term in _METRIC_TERMS[subject] if _contains_phrase(lowered, term)), None)


def _jurisdiction(locations: Iterable[str], text: str) -> str | None:
    location = next((item.strip() for item in locations if item and item.strip()), None)
    if location:
        return location[:200]
    lowered = text.casefold()
    known = (
        "Ontario", "Alberta", "Canada", "United States", "U.S.", "US",
        "United Kingdom", "European Union",
    )
    return next((item for item in known if _contains_phrase(lowered, item.casefold())), None)


def _first_entity(values: Iterable[str]) -> str | None:
    return next((value.strip()[:300] for value in values if value and value.strip()), None)


def _first_year(value: str) -> str | None:
    match = re.search(r"\b(?:19|20)\d{2}\b", value)
    return match.group(0) if match else None


def _metric_matches(searchable: str, focus: str, subject: str) -> bool:
    if _contains_any(searchable, _METRIC_TERMS[subject]):
        return True
    focus_terms = _significant_terms(focus)
    if not focus_terms:
        return True
    found = _significant_terms(searchable)
    required = 2 if len(focus_terms) >= 4 else 1
    return len(focus_terms & found) >= required


def _append_context_requirement_reasons(
    reasons: list[str], profile: AuthorityProfileRecord, searchable: str
) -> None:
    """Require claim-specific qualifiers before an official document is usable."""

    entity = (profile.entity or "").casefold()
    nursing_profile = _contains_any(
        entity, ("nurse", "nurses", "registered nurse", "rn")
    ) or any("nurse" in holder.entity.casefold() for holder in profile.record_holders)
    if profile.subject != "compensation" or not nursing_profile:
        return
    requirements = (
        ("EMPLOYMENT_SECTOR", ("employment sector", "hospital", "long-term care", "community", "employer")),
        ("EMPLOYMENT_STATUS", ("full-time", "full time", "part-time", "part time")),
        ("WAGE_STEP", ("wage step", "pay step", "step", "wage grid", "pay grid")),
    )
    for label, terms in requirements:
        reasons.append(
            f"{label}_MATCHED"
            if _contains_any(searchable, terms)
            else f"{label}_NOT_MATCHED"
        )


def _contains_entity(searchable: str, profile_entity: str | None, holder_entity: str) -> bool:
    values = [holder_entity]
    if profile_entity:
        values.append(profile_entity)
    return any(
        len(terms := _significant_terms(value)) > 0 and bool(terms & _significant_terms(searchable))
        for value in values
    )


def _significant_terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3 and token not in _STOP_WORDS
    }


def _contains_any(value: str, terms: Iterable[str]) -> bool:
    return any(_contains_phrase(value, term.casefold()) for term in terms)


def _contains_phrase(value: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase.casefold())}(?![a-z0-9])", value.casefold()))


def _safe_query_phrase(value: object) -> str:
    if value is None:
        return ""
    # Profile fields originate in user/model language. Quoting a conservative
    # character set prevents injected Brave operators from weakening the
    # registry-owned site restriction.
    normalized = re.sub(r"[^A-Za-z0-9\s$%.,'()/+-]", " ", str(value))
    normalized = re.sub(r"\b(?:site|inurl|intitle)\s*:\s*\S+", " ", normalized, flags=re.I)
    normalized = re.sub(r"\b(?:AND|OR|NOT)\b", " ", normalized, flags=re.I)
    return " ".join(normalized.split())[:180]


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def _domain_matches(actual: str, registered: str) -> bool:
    actual = actual.casefold().rstrip(".")
    registered = registered.casefold().rstrip(".")
    return actual == registered or actual.endswith(f".{registered}")


__all__ = [
    "AUTHORITY_GAP_CODE",
    "AUTHORITY_POLICY_REGISTRY_VERSION",
    "AUTHORITY_PREFLIGHT_PER_CLAIM",
    "AUTHORITY_PREFLIGHT_RESULT_LIMIT",
    "AUTHORITY_PREFLIGHT_TOTAL_BUDGET",
    "AUTHORITY_PROFILE_VERSION",
    "AuthorityDerivation",
    "AuthorityMatch",
    "build_preflight_query",
    "derive_authority_profile",
    "derive_authority_profiles",
    "holder_for_profile",
    "registered_document_match",
    "registered_search_match",
]
