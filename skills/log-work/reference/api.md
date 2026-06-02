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
| Create worklogs (batch) | `POST` | `user/worklogs` | body `{"workLogs":[ ... ]}`, content-type `text/plain` |
| Read all worklogs | `GET` | `worklogs?username=<u>` | returns full history; **date filter is ignored** → filter client-side |
| Type-of-work enum | `GET` | `timesheet/type-of-work` | `{"typeOfWorks":[{id,name,description}]}` |
| Update one worklog | `PUT` | `user/worklogs/{id}` | (not used in v1) |
| Delete one worklog | `DELETE` | `user/worklogs/{id}` | (not used in v1) |
| Excel import | `POST` | `timesheet/worklogs/import` | multipart (not used in v1) |

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
