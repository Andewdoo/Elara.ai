# Web Guidance

- Use Next.js App Router, strict TypeScript, Tailwind/shadcn-style components, React Hook Form, and Zod.
- Keep server-owned runs, reports, sources, history, graphs, and exports in TanStack Query. Use Zustand only for transient interface state.
- Never call DeepSeek, Brave Search, PostgreSQL, Redis, privileged object storage, or Firebase Admin from the browser.
- Browser Firebase configuration is limited to approved `NEXT_PUBLIC_FIREBASE_*` metadata. Keep credentials and sensitive content out of local storage.
- Use credentialed EventSource for progress, invalidate queries at terminal events, and reload authoritative state from FastAPI/PostgreSQL.
- Consume score and calculation records from the API; do not recompute authoritative scoring in the browser.
- Preserve responsive, keyboard, loading, empty, failure, reconnect, retry, and cancellation behavior.
- Add focused component, hook, accessibility, and contract tests for changed behavior.

Use `elara-task-context` to load only the applicable frontend or report-workspace section from the implementation plan.

