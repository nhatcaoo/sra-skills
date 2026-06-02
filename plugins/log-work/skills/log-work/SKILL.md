---
name: log-work
description: Log work / fill timesheet on SmartOSC SRA (sra.smartosc.com/time-sheet). Generates realistic worklog data from a short prompt — detects missing or under-logged days, distributes hours across the user's assigned projects to hit 100%, previews, and submits via the SRA API. Caches the token + a project profile so daily use is one line. Use for "log work", "log giờ", "điền timesheet", "log bù SRA", "check timesheet", "hướng dẫn log work".
---

You log work to the SmartOSC **SRA** timesheet. You turn a short prompt
("log June, off the 15th" / "log today 8h Poc Tm Asset") into clean, realistic
worklog data and submit it via the API — never raw, never `n/A`.

Helper script (stdlib only) — set `SCRIPT` once at the start of a session, then
reuse it in every command below:
```bash
SCRIPT="$CLAUDE_PLUGIN_ROOT/skills/log-work/scripts/sra_worklog.py"
[ -f "$SCRIPT" ] || SCRIPT="$(find ~/.claude -name sra_worklog.py 2>/dev/null | head -1)"
```
(`$CLAUDE_PLUGIN_ROOT` is set when installed as a plugin; the fallback finds it for
a standalone/symlink install.) API + enums: `reference/api.md` (next to this file).
State lives in `~/.claude/.sra/` (token + `profile.json`) — survives plugin updates.

## Hard rules
- **Never POST without a preview + explicit approval.**
- Quality ≥6/10 vs. real work: concrete, varied descriptions in the project's
  domain. **Never** `n/A`, `test`, placeholder, gibberish (the script rejects these).
- Hit target: every in-scope working day reaches the daily target (default 8h);
  project mix matches the confirmed allocation → period totals 100% on the
  **right** projects.
- The token is short-lived (~7 days), cached locally, never committed. When a
  call returns 401/403 or `token` reports expired, ask for a fresh curl.
- Unsure about projects / allocation / leave / language → **ask, then generate.**

## Commands (auth resolves: --token > --curl > cached)
```bash
python3 "$SCRIPT" onboard                        # setup status + getting-started guide
python3 "$SCRIPT" token   --token "<pasted>"     # cache token (raw JWT/Bearer/curl all ok)
python3 "$SCRIPT" token                          # show cached token status
python3 "$SCRIPT" profile                        # show saved profile
python3 "$SCRIPT" allocation --start D --end D [--user-id N]  # assigned projects + ratios (authoritative)
python3 "$SCRIPT" check    --start D --end D      # human-readable status (no write)
python3 "$SCRIPT" context  --start D --end D      # full state as JSON (for you)
python3 "$SCRIPT" calendar --start D --end D [--file plan.json]  # month grid
python3 "$SCRIPT" submit   --file plan.json [--dry-run]
```
`context`/`check`/`calendar` apply `profile.json` defaults (userId, hoursPerDay,
fixedLeave) and fetch VN holidays live from the `holidays` API automatically.

## Onboarding (first run / "hướng dẫn", "how do I use this")
Run `onboard` — it prints a setup checklist (token / profile / holidays) + usage
examples. Then **interactively walk the user through whatever is missing**:
1. If no valid token → guide them to grab a curl (step in `onboard` output) and
   run `token --token "<pasted>"` (or `--curl /tmp/sra.curl`).
2. `userId` is then auto-resolved — no question needed. Optionally ask the user's
   preferred description language and save it (`{"language":"vi"}`).
3. Offer a dry first run: `check` the current month so they see it working with no
   risk. Don't submit anything during onboarding.

## Workflow

### 1. Token
Run `token`. If valid, continue. If missing/expired, ask the user to **paste their
session key / token directly in chat** — then cache it yourself with
`token --token "<pasted value>"` (it accepts a raw JWT, `Bearer x`,
`authorization: Bearer x`, or a whole curl, and auto-caches for ~7 days). A saved
`/tmp/sra.curl` + `--curl` also works. See `reference/api.md` for where to grab it.

### 2. Scope
Read the prompt for the period and any days off. Default period = current month.
The script auto-skips weekends + VN holidays; **confirm personal leave** and pass
via `--exclude` (or store recurring leave in the profile).

### 3. Read state — `check` then `calendar`
`check` for the gap summary, `calendar` for a glanceable grid. **Only fill
`missingWorkingDays` (0h) and `underLoggedDays` (below target)** — never duplicate
a full day.

### 4. Projects & allocation — fetch FRESH every time (never persist)
Run `allocation --start D --end D`. It reads the user's real assignments
(`users/<id>.workingHistory`, the SRA "Working Details") and returns the projects
**actually allocated in that exact period** with effort-based ratios.

- **`userId` is auto-resolved** (via `users/current-user`) and cached — no manual
  entry. The profile stores only stable prefs: `userId`, `hoursPerDay`, `language`,
  `fixedLeave`. **Do NOT persist projects/ratios** — allocations expire (each entry
  has start/end dates) and change month to month, so a frozen list goes stale.
  Always re-run `allocation` for the period being logged.
- `projectId 0` = the generic "Other" project (the only one the SRA UI offers when
  no allocation is active — but see note below: the API accepts the real ids).
- If `allocation` returns empty (period not planned yet), tell the user and ask
  which project(s) to use (or fall back to `0`/Other).

### 5. Ask what the user actually did, THEN generate
Do **not** invent work blindly. For the projects in scope, **ask the user a short
narrative first** — e.g. "Trên *Blockchain: Pre-sale* tháng này bạn làm gì? (vd: 5
ngày liền fix bug ở staging, 2 ngày làm API…)". Use their answer to drive:
- **which days go to which project** (honour their "5 ngày liền" etc.), staying
  close to the allocation ratio for the totals;
- **typeOfWork** per day (their narrative says bug fixing → `Bug Fixing` id 8,
  etc.); fall back to the project's historical `topTypeOfWork` only for gaps;
- **descriptions**: short (~5–12 words), concrete, on-domain, varied, in the
  profile's language — derived from what they told you, never `n/A`/placeholder.

Then build entries for the missing/under-logged days:
- **Distribute by ratio**: `hours_per_project ≈ total × ratio`; prefer contiguous
  day-blocks; under-logged days get only the remaining hours (target − logged).
- An occasional 6–7h day is fine; keep the period total on target.

### 6. Preview → approve
Write the plan, render `calendar --file plan.json`, and show a table
`Date | Project (code) | Type of Work | Hours | Description` with per-project and
grand totals vs. target. Accept natural-language edits ("đổi ngày 10 sang Bug
Fixing", "dồn hết vào Superwhale") and re-render. Get explicit approval.

### 7. Submit → verify
```bash
python3 "$SCRIPT" submit --file /tmp/plan.json --dry-run
python3 "$SCRIPT" submit --file /tmp/plan.json
```
Then re-run `check` for the period and report count / hours / per-project breakdown.

## Fast path — daily logging
For "log today 8h Coding Poc Tm Asset" / "log hôm nay" / "log this week": skip the
month flow. Use the profile (or a single project named in the prompt), build a
1–N day plan for today/the current week, show a one-line preview, on "ok" submit.
Still never write placeholder descriptions.

## Notes
- Batch all entries in one `submit`.
- **projectId ≠ 0 works.** The SRA UI only shows "Other" (0) when no allocation is
  active *today* (`datalake/project` → `available_projects:[]`), but the **API
  accepts any allocated projectId for past dates** (verified: POST 201). So log to
  the real allocated projects from `allocation`, not just `0`.
- Holidays are fetched **live** from the `holidays` API (auto-correct per year);
  `vn_holidays.json` is only an offline fallback. Still confirm personal leave.
- `userId` is auto-resolved via `users/current-user`; stored in the profile.
- Self-contained & shareable: SKILL.md + scripts/ + reference/. Nothing hardcoded
  except the public API base; per-user state lives in `~/.claude/.sra/`.
