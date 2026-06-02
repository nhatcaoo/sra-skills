# sra-skills

Claude Code skills for the **SmartOSC SRA** portal (`sra.smartosc.com`).

## Skills

### `log-work` — timesheet logging
Turns a short prompt into clean, realistic worklog data and submits it to the SRA
timesheet via its API.

- Detects **missing** and **under-logged** working days in any period.
- Distributes hours across your assigned projects to hit 100% on the right ones.
- Auto-skips weekends + Vietnam public holidays.
- Caches your session token (~7 days) and a project **profile** so daily use is
  one line.
- Always **previews** (table + month calendar) and waits for approval before it
  writes anything. Never logs placeholder/`n/A` descriptions.

Example prompts:
```
hướng dẫn log work          # guided onboarding
check timesheet tháng này   # status only, no write
log work tháng 6, nghỉ ngày 15
log hôm nay 8h Poc Tm Asset # daily fast-path
```

## Install

Make the skill visible to Claude Code by linking (or copying) it into your skills
folder:

```bash
git clone git@github.com:nhatcaoo/sra-skills.git
ln -s "$PWD/sra-skills/skills/log-work" ~/.claude/skills/log-work
# or: cp -r sra-skills/skills/log-work ~/.claude/skills/
```

Then in Claude Code: `hướng dẫn log work` (runs onboarding) or `log work ...`.

## How auth works
There is no programmatic login (SSO via Google). Grab a fresh **session key /
bearer token** from the browser (DevTools → Network → an `sra-api.smartosc.com`
request → copy `authorization: Bearer …`, or *Copy as cURL*) and paste it into the
chat. The skill caches it under `~/.claude/.sra/token` (chmod 600, gitignored)
until it expires (~7 days), then asks for a fresh one.

## CLI (used by the skill)
```bash
python3 skills/log-work/scripts/sra_worklog.py onboard
python3 skills/log-work/scripts/sra_worklog.py token   --token "<paste>"
python3 skills/log-work/scripts/sra_worklog.py check    --start 2026-06-01 --end 2026-06-30
python3 skills/log-work/scripts/sra_worklog.py calendar --start 2026-06-01 --end 2026-06-30
python3 skills/log-work/scripts/sra_worklog.py submit   --file plan.json --dry-run
```
Stdlib only — no dependencies. State (token, profile) lives in `~/.claude/.sra/`,
never in the repo.

## Notes
- Lunar holidays in `skills/log-work/reference/vn_holidays.json` follow the yearly
  government schedule — verify the official notice; the skill still confirms leave
  with you.
- The read username defaults to `nhatcl`; pass `--username` for other accounts.
