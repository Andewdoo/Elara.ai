# Elara.ai UI/UX Redesign — The Ledger Room

## Intent

Make Elara feel like a calm, modern evidence desk: analytical without looking like generic enterprise software, editorial without becoming decorative, and explicit about provenance and uncertainty. The redesign changes frontend presentation only. Backend contracts and product functions remain untouched.

## Non-negotiable visual rules

- No gradients.
- No glassmorphism.
- No backdrop blur or translucent decorative surfaces.
- No glossy 3D UI, neon, or ornamental effects.
- Use solid paper-like backgrounds, thin rules, decisive typography, and direct state labels.
- Never present Elara as a lie detector or a permanent credibility score.

## Global shell

- Desktop: 232px solid ink navigation rail with Elara mark, Workspace, Verify, History, Saved, and Methodology. User identity and account utility sit at the bottom.
- Tablet: compact icon-and-label rail.
- Mobile: simple top utility bar plus five labeled primary destinations; account and Settings use the utility menu.
- Main content uses a 12-column grid, adaptive 24-40px gutters, and a maximum readable width per content type.
- Active navigation uses a solid paper tab with a left ink rule; focus always uses a visible teal ring.

## Visual system

| Token | Value | Use |
|---|---|---|
| Ink | `#18221D` | Navigation, primary text, strong borders |
| Deep teal | `#0C665B` | Primary actions, focus, supporting evidence |
| Rust | `#B44A2D` | Contradicting evidence, destructive emphasis |
| Ochre | `#D2A33F` | Warnings, inaccessible evidence |
| Paper | `#F4F0E8` | App background |
| Sheet | `#FFFCF6` | Panels and cards |
| Muted paper | `#E9E3D8` | Secondary grouping and selected rows |
| Rule | `#C9C0B2` | Dividers and input borders |

- Headings: Source Serif 4.
- Interface copy: Manrope.
- Data and provenance: IBM Plex Mono with tabular figures.
- Corners: 2-6px; avoid pill-shaped containers except compact status labels.
- Elevation: borders first; hard `3px 3px 0` menu/dialog shadow only.
- Motion: 150-220ms state transitions, progress changes only; respect reduced motion.

## Page mockup inventory

### 1. Workspace `/`

- Lite evidence-library label and citation-audited scope.
- Large claim composer with sample prompts.
- Run Lite report, Cancel, Retry, and Clear states.
- Six-step Lite progress ledger.
- Report scope summary.
- Result workspace below, reusing the complete report UI.

### 2. Full verifier `/verify`

- Research-depth selection for Quick, Standard, and Deep.
- Exact claim input with limits, validation, and authentication error.
- Create verification as the single primary action.
- Small explanatory panel for durable state, server-authoritative scores, and citation audit.

### 3. Live research `/verify/[runId]`

- All run stages from Queued through Citation audit.
- Current public status message, elapsed time, progress, source counts, and inaccessible count.
- Refresh, Cancel research, Retry verification, and Open report actions.
- Durable failure and cancellation-requested states.

### 4. History `/history`

- Search, status filter, date sort, confidence sort, and pagination.
- Run status, depth, verdict, confidence, date, and saved state.
- Open report/live run, Save/Unsave, and Delete actions.
- Loading, authentication, error/retry, and empty states.

### 5. Saved `/saved`

- Account-owned saved-report explanation.
- Saved-only report collection.
- Open report, Unsave, and Delete actions.
- Loading, authentication, error/retry, empty, and pagination states.

### 6. Methodology `/methodology`

- Evidence-management scope statement.
- Narrow conclusion, evidence traceability, source independence, and deterministic scoring.
- Six score-role definitions.
- No language implying person-level credibility.

### 7. Settings `/settings`

- Current informational state for Account, Security, and Interface preferences.
- Clear explanation that account-managed settings are not yet available.
- Route remains available through the account utility menu.

### 8. Report `/report/[runId]`

- Report title, reviewed/generated timestamps, scope, verdict, depth, and completion state.
- Save/Remove saved, Export JSON, prepared-download fallback, export hash, and export history.
- Overview, Claims, Evidence, and Graph tabs with keyboard navigation.
- Atomic-claim search and label filtering.
- Supporting, contradicting, neutral, and inaccessible evidence filters.
- Exact citation-audited sentences, limitations, server score charts, numerical audit, and accessible chart tables.
- Filterable source-dependency graph.
- Source drawer with source metadata, correction history, exact passages, citation audit, passage selection, external-source link, Escape close, and focus trapping.
- Loading, sign-in required, run incomplete, error/retry, and partial-resource states.

## Interaction and accessibility rules

- All controls have visible labels and at least a 44px target.
- Status is communicated by text and icon, never color alone.
- Route changes focus the main heading.
- Destructive actions are separated from primary actions and require confirmation.
- Loading areas reserve space and use skeletons for waits longer than one second.
- Empty states explain why the area is empty and offer the next useful action.
- Charts retain accessible table alternatives; graph summaries remain keyboard reachable.
- Desktop, tablet, 375px mobile, and landscape layouts must avoid horizontal page scrolling.

