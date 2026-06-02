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
python3 "$SCRIPT" check    --start D --end D      # human-readable status (no write)
python3 "$SCRIPT" context  --start D --end D      # full state as JSON (for you)
python3 "$SCRIPT" calendar --start D --end D [--file plan.json]  # month grid
python3 "$SCRIPT" submit   --file plan.json [--dry-run]
```
`context`/`check`/`calendar` apply `profile.json` defaults (username, hoursPerDay,
fixedLeave) and bundled VN holidays (`reference/vn_holidays.json`) automatically.

## Onboarding (first run / "hướng dẫn", "how do I use this")
Run `onboard` — it prints a setup checklist (token / profile / holidays) + usage
examples. Then **interactively walk the user through whatever is missing**:
1. If no valid token → guide them to grab a curl (step in `onboard` output) and
   run `token --curl /tmp/sra.curl`.
2. If no profile → ask which projects they're assigned to + the % split + language,
   then write `~/.claude/.sra/profile.json` (shape in step 4 below).
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

### 4. Projects & allocation — use the profile
- If `profile.json` has `projects` + ratios, propose that split and ask only to
  confirm/tweak.
- Otherwise propose a split from `context.projects` (history — may be stale), let
  the user correct it, and **write it to `~/.claude/.sra/profile.json`** so next
  time is one step. Profile shape:
  ```json
  {"username":"nhatcl","hoursPerDay":8,"language":"en",
   "projects":[{"projectId":1597,"code":"SSO_2506_OS","name":"Poc Tm Asset","ratio":0.6},
               {"projectId":1422,"code":"SWI_2503_DS","name":"Superwhale","ratio":0.4}],
   "fixedLeave":[]}
  ```
  `projectId 0` = the generic "Other" project.

### 5. Generate beautiful data
For missing/under-logged days build entries:
- **Distribute by ratio**: `hours_per_project ≈ total × ratio`. Prefer
  **contiguous day-blocks per project** over daily switching. Avoid splitting one
  day across many projects unless allocation demands it.
- **Under-logged days**: add only the remaining hours (target − logged).
- **typeOfWork**: weight to the project's `topTypeOfWork` (usually Coding), mix in
  plausible variety (Requirements Development, Review, Bug Fixing, Unit Test). Use
  the integer **id** from the enum in the payload.
- **descriptions**: short (~5–12 words), concrete, on-domain, varied day to day,
  in the profile's language (ask if unset). An occasional 6–7h day is fine, keep
  the period total on target.

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
- Self-contained & shareable: SKILL.md + scripts/ + reference/. Nothing hardcoded
  except the public API base; per-user data lives in `~/.claude/.sra/`.
- Lunar holidays in `vn_holidays.json` follow the government schedule — verify the
  yearly notice; the skill still confirms leave with the user.
