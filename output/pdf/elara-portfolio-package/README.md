# Elara.ai Portfolio Package

This folder contains a complete portfolio case study for Elara.ai, a completed personal evidence-management and automated-verification project built from June 2026 through August 2026.

## Deliverables

- `Elara_Portfolio_Case_Study.pdf` - polished presentation-ready case study.
- `Elara_Portfolio_Case_Study.md` - editable long-form source copy.
- `build_case_study.py` - reproducible ReportLab builder for the presentation PDF.
- `screenshots/` - six selected product screenshots.
- `diagrams/` - three high-resolution architecture and methodology diagrams.

## Screenshot set

1. `01-verification-workspace.png` - claim submission and research-depth selection.
2. `02-completed-report-overview.png` - completed report, verdict, atomic claims, and citation-audited summary.
3. `03-atomic-claim-analysis.png` - claim-level support, confidence, context, and limitations.
4. `04-evidence-comparison.png` - supporting and contradicting evidence shown together.
5. `05-deterministic-score-dashboard.png` - server-calculated score and research-coverage visualizations.
6. `06-citation-source-drawer.png` - exact source passage, retrieval metadata, and citation-audit result.

The report screenshots use Elara's bundled representative report-preview data so that private account information and private evidence are not exposed. The placeholder transit example demonstrates the product contract and interface; it is not a live accuracy benchmark.

## Diagram set

1. `01-system-architecture.png` - browser, API, worker, providers, and durable data flow.
2. `02-verification-workflow.png` - the thirteen controlled verification stages.
3. `03-model-deterministic-boundary.png` - separation between model-assisted language tasks and deterministic controls.

## Portfolio usage

Use the PDF as the primary case study. The Markdown file can be adapted into a personal website, GitHub project page, or interview presentation. The images are exported separately so they can be reused in cards, slides, and social posts.

Rebuild the PDF from the repository root with the bundled workspace Python or another Python environment containing ReportLab, Pillow, and pypdf:

```text
python output/pdf/elara-portfolio-package/build_case_study.py
```
