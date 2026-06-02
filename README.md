# sra-skills

A Claude Code **plugin marketplace** for the SmartOSC **SRA** portal
(`sra.smartosc.com`).

## Install (recommended — via marketplace)

```text
/plugin marketplace add nhatcaoo/sra-skills
/plugin install log-work@sra-skills
```

That's it — no clone, no symlink. Updates: `/plugin marketplace update sra-skills`.

To use a local checkout instead (e.g. while developing):
```text
/plugin marketplace add /absolute/path/to/sra-skills
/plugin install log-work@sra-skills
```
Or load it for a single session without installing:
```bash
claude --plugin-dir /absolute/path/to/sra-skills/plugins/log-work
```

## Plugins

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

Example prompts (the skill is model-invoked — just talk to Claude):
```
hướng dẫn log work          # guided onboarding
check timesheet tháng này   # status only, no write
log work tháng 6, nghỉ ngày 15
log hôm nay 8h Poc Tm Asset # daily fast-path
```

## How auth works
There is no programmatic login (SSO via Google). Grab a fresh **session key /
bearer token** from the browser (DevTools → Network → an `sra-api.smartosc.com`
request → copy `authorization: Bearer …`, or *Copy as cURL*) and **paste it into
the chat**. The skill caches it under `~/.claude/.sra/token` (chmod 600,
gitignored) until it expires (~7 days), then asks for a fresh one.

## Repository layout
```
sra-skills/                              # marketplace repo
├── .claude-plugin/marketplace.json      # marketplace catalog
└── plugins/
    └── log-work/                        # the plugin
        ├── .claude-plugin/plugin.json
        └── skills/log-work/             # the skill
            ├── SKILL.md
            ├── scripts/sra_worklog.py   # stdlib-only CLI
            └── reference/{api.md, vn_holidays.json}
```
State (token, profile) lives in `~/.claude/.sra/` — never in the repo, and it
survives plugin updates.

## Notes
- The helper script uses `$CLAUDE_PLUGIN_ROOT` to locate itself, so it works from
  the plugin cache regardless of install path.
- Lunar holidays in `vn_holidays.json` follow the yearly government schedule —
  verify the official notice; the skill still confirms leave with you.
- The read username defaults to `nhatcl`; pass `--username` for other accounts.
- Validate locally before publishing changes: `claude plugin validate .`
