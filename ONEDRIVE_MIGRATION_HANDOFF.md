# Elara.ai OneDrive Migration Handoff

## Objective

Finish moving Elara.ai completely out of OneDrive. The canonical project must be:

```text
C:\Users\aliua\Elara.ai
```

The old duplicate must be removed entirely:

```text
C:\Users\aliua\OneDrive\Desktop\Elara.ai
```

Do not create a junction or redirect at the old OneDrive path. The user wants the project and active development workflow fully outside OneDrive.

## Verified state before handoff

- Both directories exist and currently identify the same Git commit: `7bc31574bceb92d4c1d43479023b4e4463606926`.
- Both working trees were clean on branch `main`, tracking `origin/main`.
- The GitHub remote is `https://github.com/Andewdoo/Elara.ai.git`.
- The full project was copied, including `.git`, ignored environment files, dependencies, and the API virtual environment.
- `project-context/prompts` points to `C:\Users\aliua\Elara.ai`; no project-file references to the old OneDrive path were found.
- The API virtual environment was refreshed and reports its prefix as `C:\Users\aliua\Elara.ai\apps\api\.venv`.
- Verification from the new directory passed:
  - Web tests: 9 passed.
  - Web lint: passed.
  - Web typecheck: passed.
  - API tests: 67 passed.
  - Worker tests: 106 passed.
- The earlier deferred migration helper was stopped. It must not be restarted because it was designed to leave a junction in OneDrive.

## Instructions for the new Codex thread

First read:

- `AGENTS.md`
- `project-context/AGENTS.md`
- `project-context/IMPLEMENTATION_PLAN.md`
- `project-context/prompts`

Then complete these steps.

### 1. Confirm this thread is attached to the new project

Run:

```powershell
(Resolve-Path .).Path
git rev-parse --show-toplevel
```

Both must return `C:\Users\aliua\Elara.ai`. Stop if either command resolves into OneDrive.

### 2. Reconfirm the two copies before deletion

Run:

```powershell
$new = 'C:\Users\aliua\Elara.ai'
$old = 'C:\Users\aliua\OneDrive\Desktop\Elara.ai'

git -C $new rev-parse HEAD
git -C $old rev-parse HEAD
git -C $new status --short --branch
git -C $old status --short --branch
git -C $new remote get-url origin
git -C $old remote get-url origin
```

Requirements before deletion:

- Both commits match.
- Both working trees are clean.
- Both remotes match.
- The new project contains `.git`, `.env.private`, and `apps\web\.env.local` if those files still exist in the old project.

Compare the ignored environment files without displaying their contents:

```powershell
Get-FileHash "$new\.env.private", "$old\.env.private"
Get-FileHash "$new\apps\web\.env.local", "$old\apps\web\.env.local"
```

Matching files must have matching hashes. If commits, status, remotes, or required secret-file hashes differ, stop and reconcile the differences before deleting anything.

### 3. Ensure nothing still uses the old path

Run:

```powershell
$old = 'C:\Users\aliua\OneDrive\Desktop\Elara.ai'
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($old, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 } |
    Select-Object ProcessId, Name, CommandLine
```

Ignore only the inspection PowerShell command itself. Close or safely stop editors, terminals, development servers, and other processes genuinely using the old path. Do not kill processes blindly or discard unsaved editor changes.

Also confirm no old deferred helper remains:

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*finish-elara-move.ps1*' } |
    Select-Object ProcessId, Name, CommandLine
```

Stop such a process if one exists and verify its identity first.

### 4. Delete only the verified OneDrive duplicate

Use PowerShell end-to-end. Resolve and compare the absolute paths before recursive deletion:

```powershell
$oldExpected = 'C:\Users\aliua\OneDrive\Desktop\Elara.ai'
$newExpected = 'C:\Users\aliua\Elara.ai'
$oldResolved = (Resolve-Path -LiteralPath $oldExpected).Path.TrimEnd('\')
$newResolved = (Resolve-Path -LiteralPath $newExpected).Path.TrimEnd('\')

if ($oldResolved -ne $oldExpected) { throw 'Old-path verification failed.' }
if ($newResolved -ne $newExpected) { throw 'New-path verification failed.' }
if ($oldResolved -eq $newResolved) { throw 'Source and destination unexpectedly resolve to the same directory.' }
if (-not (Test-Path -LiteralPath (Join-Path $newResolved '.git') -PathType Container)) {
    throw 'The canonical destination is not a Git project.'
}

Set-Location -LiteralPath $newResolved
Remove-Item -LiteralPath $oldResolved -Recurse -Force
```

Do not delete `C:\Users\aliua\Elara.ai`.

### 5. Verify final state

Run:

```powershell
$new = 'C:\Users\aliua\Elara.ai'
$old = 'C:\Users\aliua\OneDrive\Desktop\Elara.ai'

Test-Path -LiteralPath $old
git -C $new status --short --branch
git -C $new remote -v
& "$new\apps\api\.venv\Scripts\python.exe" -c "import sys; print(sys.prefix)"
```

Expected results:

- The old-path check returns `False`.
- Git remains on `main`, tracking `origin/main`.
- The remote still points to GitHub.
- Python reports the new C: path, not OneDrive.

Remove the obsolete helper artifacts after confirming no helper process is running:

```powershell
Remove-Item -LiteralPath 'C:\tmp\finish-elara-move.ps1' -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath 'C:\tmp\finish-elara-move.log' -Force -ErrorAction SilentlyContinue
```

### 6. Reconnect the local workflow

- Open `C:\Users\aliua\Elara.ai` directly in Codex and VS Code.
- Update or remove shortcuts, terminal profiles, and recent-workspace entries that explicitly reference the OneDrive path.
- Start development commands only from the new directory.
- GitHub, Firebase, Vercel, Docker Compose, and remote deployment connections are repository/configuration based and should not require reconnection solely because the local path changed.
- If a local tool stored an absolute project path, update it to `C:\Users\aliua\Elara.ai`.

## Suggested prompt for the new thread

```text
Read ONEDRIVE_MIGRATION_HANDOFF.md and the required project-context instructions. Verify that this thread is rooted at C:\Users\aliua\Elara.ai, then execute the remaining OneDrive cleanup and reconnection steps safely. Do not create a junction at the old path. Confirm the old directory is gone and the new Git repository, environment files, Python environment, and remote remain intact.
```
