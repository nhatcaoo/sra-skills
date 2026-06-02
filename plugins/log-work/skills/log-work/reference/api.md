# SRA Timesheet API — cheatsheet

Base URL: `https://sra-api.smartosc.com/api`
Frontend: `https://sra.smartosc.com/time-sheet`

Auth: `Authorization: Bearer <JWT>`. The token is **short-lived (~7 days)** and
is grabbed from the browser — there is no programmatic login (SSO via Google).
The WAF returns **403** to non-browser User-Agents, so requests must send a real
`User-Agent` (the helper script does this).

## Endpoints used by this skill

| Purpose | Method | Path | Notes |
|---|---|---|---|
| Create worklogs (batch) | `POST` | `user/worklogs` | body `{"workLogs":[ ... ]}`, content-type `text/plain`; returns 201 |
| Read all worklogs | `GET` | `worklogs?username=<u>` | returns full history; **date filter is ignored** → filter client-side |
| Type-of-work enum | `GET` | `timesheet/type-of-work` | `{"typeOfWorks":[{id,name,description}]}` |
| **Own user id** | `GET` | `users/current-user` | `{id,username,name,...}` → auto-resolve `userId` (no username→id lookup otherwise) |
| **User + allocation** | `GET` | `users/{id}` | profile + `workingHistory[]` (the "Working Details" allocation, with start/end dates) |
| **VN holidays** | `GET` | `holidays?limit=200&page=1&filter[year]=YYYY` | `{data:[{name,start,end}]}` date ranges → expand to days. Authoritative; auto per-year |
| Loggable projects (today) | `GET` | `datalake/project` | `{available_projects:[...]}` — what the UI dropdown shows; **empty when no active allocation** |
| Delete one worklog | `DELETE` | `user/worklogs/{id}` | returns 204 |
| Update one worklog | `PUT` | `user/worklogs/{id}` | (not used in v1) |
| Excel import | `POST` | `timesheet/worklogs/import` | multipart (not used in v1) |

### projectId restriction is UI-only, not enforced by the API
`datalake/project` returns the projects loggable **right now** (based on active
allocation). When all allocations have ended it returns `[]`, so the SRA UI only
offers "Other" (`projectId 0`). **But the write API does not enforce this** —
`POST user/worklogs` with a real allocated `projectId` for a **past date** succeeds
(verified: HTTP 201, then `DELETE` 204). So the skill logs to the real projects
from `allocation`, regardless of what the current UI dropdown shows.

### `users/{id}` → allocation (the authoritative project list)
`{id}` is the SRA **numeric user id** (e.g. 226), not the username. There is no
username→id *search* for a normal user (`users?username=` returns 403), but
`GET users/current-user` returns your own id — the skill uses that to resolve and
cache `userId` automatically.

```json
{"id":226,"username":"nhatcl","name":"Cao Linh Nhật","totalProjects":13,
 "workingHistory":[
   {"name":"Blockchain: Pre-sale","projectId":1188,"projectCode":"SOSC_BLC_01",
    "startDate":"2026-05-01","endDate":"2026-05-29","totalEffort":168.0,"evaluation":"N/A"},
   {"name":"Project 100","projectId":1729,"projectCode":"SOSC_LnD_100",
    "startDate":"2026-05-01","endDate":"2026-05-29","totalEffort":25.83}
 ]}
```
Filter `workingHistory` to entries overlapping the target period, then split by
`totalEffort` → allocation ratios. These `projectId`s are the real, current ones
to log to (may differ from past worklog projectIds).

## Write payload (POST user/worklogs)

```json
{"workLogs":[
  {"date":"2026-06-03","description":"...","workHours":8,"typeOfWork":6,"projectId":1597}
]}
```

- `date` — `YYYY-MM-DD`
- `workHours` — number (e.g. 8, 6.5)
- `typeOfWork` — **integer id** from the enum below
- `projectId` — **integer**. `0` = the generic "Other" project; real projects
  have their own id (discover via the read endpoint, field `project.id`).
- `description` — free text; keep it realistic, never `n/A`.

## typeOfWork enum (id → name)

Fetch live (`timesheet/type-of-work`) — it has ~37 entries. Common ones:

| id | name |
|---|---|
| 2 | UI/UX Design |
| 3 | Requirements Development |
| 4 | Consulting |
| 5 | Study Requirements |
| 6 | **Coding** |
| 7 | Unit Test |
| 8 | Bug Fixing |
| 9 | Create/Modify Test Documents |
| 10 | Test execution |
| 11 | Review |
| 12 | Project Support |
| 13 | UAT/Go-live/Customer Support |

Note the read endpoint returns `typeOfWork` as a **name string**; the write
endpoint expects the **integer id**. Map via the enum.

## Read response shape (GET worklogs)

```json
{"workLogs":[
  {"id":27035,"username":"nhatcl","date":"2024-01-04T00:00:00+07:00",
   "hours":8.0,"description":"","typeOfWork":"Coding",
   "project":{"name":"Ibc Side Chain","id":1119,"code":"IBC_2401_PB"},
   "allowModify":false, ...}
]}
```

## How to get a fresh curl/token

1. Open `https://sra.smartosc.com/time-sheet`, log in via SSO.
2. DevTools → Network → trigger any request (e.g. switch month).
3. Right-click a request to `sra-api.smartosc.com` → Copy → **Copy as cURL**.
4. Save to a file (e.g. `/tmp/sra.curl`). The script parses the `Bearer` token.
