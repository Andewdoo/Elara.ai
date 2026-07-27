# Elara.ai “Ledger Room” Mockups

These high-fidelity desktop mockups cover every current App Router page. They are visual implementation targets, not screenshots of live data. All were generated with the built-in ImageGen tool in `ui-mockup` mode and saved into the project.

| File | Route | Primary state shown |
|---|---|---|
| `01-workspace.png` | `/` | Lite claim intake, progress ledger, scope, result area |
| `02-full-verifier.png` | `/verify` | Standard-depth full verification intake |
| `03-live-research.png` | `/verify/[runId]` | Active research run with telemetry and conditional actions |
| `04-history.png` | `/history` | Populated history with search, filter, sort, actions, pagination |
| `05-saved.png` | `/saved` | Saved report collection with privacy context and actions |
| `06-methodology.png` | `/methodology` | Principles, score roles, and product boundary language |
| `07-settings.png` | `/settings` | Accurate informational-only settings state |
| `08-report.png` | `/report/[runId]` | Overview tab with claims rail, cited findings, charts, and source drawer |

## Shared prompt direction

```text
Use case: ui-mockup
Asset type: high-fidelity desktop web app screen, 16:10 landscape
Style: realistic production UI; editorial evidence desk; flat, precise, calm, and authoritative
Shell: persistent dark ink navigation rail; warm paper main canvas; opaque sheet surfaces; thin rules
Palette: #18221D, #0C665B, #B44A2D, #D2A33F, #F4F0E8, #FFFCF6, #E9E3D8, #C9C0B2
Typography: Source Serif 4-like headings, Manrope-like body, IBM Plex Mono-like data
Constraints: no gradients; no glassmorphism; no transparency effects; no backdrop blur; no glossy or 3D UI; no decorative stock imagery; no watermark
Product boundary: evaluate only the submitted claim/document against timestamped evidence; never imply lie detection or permanent credibility
```

Each page prompt then supplied the exact route labels, visible controls, state content, and preservation constraints listed in [`../REDESIGN_BRIEF.md`](../REDESIGN_BRIEF.md).

## Important implementation notes

- The imagery proposes a persistent desktop rail. Responsive implementation should collapse this to a compact rail at tablet widths and a five-item labeled primary navigation on mobile.
- Mockup data is illustrative. Implementation must consume existing API/report records and must not add frontend calculations.
- Authentication, loading, empty, error, retry, cancellation, confirmation, pagination, keyboard tab behavior, source-drawer focus trapping, accessible chart tables, and graph summaries remain required even when not simultaneously visible in one static image.
- The report mockup shows the Overview tab. Claims, Evidence, and Graph remain full interactive tabs as documented in the redesign brief.
