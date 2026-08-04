# Fuiture Implemetnaiton

## Report workspace issues to address

Observed on the desktop report workspace for report `af6563bf-02cf-4214-9946-21b3672e5c76` at `/report/af6563bf-02cf-4214-9946-21b3672e5c76`.

### 1. Evidence is not being classified or displayed

#### Observed behavior

- The Evidence tab shows `0 records` for Supporting evidence.
- The Evidence tab shows `0 records` for Contradicting evidence.
- No Neutral evidence section or records are shown.
- Both visible categories display `No evidence in this category.` even though the report contains evidence and citations elsewhere in the workspace.
- Selecting `All evidence` does not populate any evidence category.

#### Expected behavior

- Every durable evidence record associated with the report should be displayed in the Evidence tab.
- Evidence should be grouped using its stored stance into:
  - supporting evidence,
  - contradicting evidence,
  - neutral evidence.
- The `All evidence` filter should show every available evidence record across all three classifications.
- Category counts should match the number of records displayed.
- Each displayed record should retain its atomic claim, source passage, citation status, stance, and provenance links.
- The browser must not invent or recompute authoritative classifications. The UI should consume the stored API classification and only normalize the supported contract values for presentation.
- An empty-category message should appear only when that specific category genuinely has no records. If the report contains evidence but none can be mapped to a supported stance, show an explicit data or contract error instead of a misleading all-empty state.

#### Acceptance criteria

- A report containing supporting, contradicting, and neutral evidence displays each record in the correct section.
- The category counts and filter results are accurate.
- Switching between All, Supporting, Contradicting, and Neutral does not lose records or alter their durable classification.
- Evidence cards still open the correct source record and exact cited passage.
- Focused tests cover every supported evidence stance and an unknown or malformed stance.

### 2. Right source-drawer background extends indefinitely downward

#### Observed behavior

- On desktop, the pale yellow/tinted area behind the right source drawer continues far below the last drawer control.
- The drawer content ends after the passage selector, but its background stretches to match the much taller center report column.
- This creates a large empty colored strip and makes the drawer appear infinitely tall.

#### Expected behavior

- The source drawer should have a clear, bounded vertical layout.
- Its background should end with its content, or the drawer should use a viewport-bounded sticky panel with its own scrolling.
- The right column must not visually stretch to the full height of the center report content when the drawer has less content.
- Desktop behavior should preserve access to source metadata and passages while scrolling the report.
- Mobile behavior should remain a full-screen or bottom-sheet drawer as required by the report-workspace design.

#### Acceptance criteria

- No empty tinted strip appears below the source drawer content.
- At desktop widths, the drawer is content-height or bounded to the available viewport height.
- Long source records scroll within the bounded drawer without expanding the entire page unexpectedly.
- Closing and reopening the drawer does not change the center column height or introduce layout jumps.
- The fix is verified with short and long report content at desktop and mobile breakpoints.

## Likely implementation areas

- `apps/web/components/report/report-workspace.tsx`
  - `EvidenceColumns` and `EvidenceGroup` for stance grouping and empty states.
  - The desktop workspace grid and `SourceDrawer` sizing/alignment classes for the stretched right column.
- The report API/adapter contract that supplies evidence `stance` values, if the UI is receiving missing or unsupported classifications.
- Focused report-workspace and API contract tests.

## Product boundary

These changes must continue to evaluate only the submitted claim or document against timestamped evidence. Evidence groupings are report-specific classifications, not permanent credibility labels or lie-detection results.
