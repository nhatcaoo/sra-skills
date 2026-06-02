#!/usr/bin/env python3
"""SRA timesheet worklog helper (SmartOSC).

Deterministic I/O + state layer for the log-work skill. Claude generates the
plan; this script reads SRA state, manages the cached token/profile, renders
previews, and submits a reviewed plan.

No third-party deps (urllib + stdlib only).

State (under ~/.claude/.sra/, chmod 600, never committed)
  token          cached bearer token (short-lived, ~7 days)
  profile.json   {username, hoursPerDay, language, projects:[{projectId,code,name,ratio}], fixedLeave:[]}

Subcommands
  token     Show/set the cached token + its expiry. --curl FILE | --token JWT
  profile   Print the saved profile and its path.
  context   Read SRA state for a date range -> clean JSON (for the model).
  check     Same data as `context` but a short human-readable report.
  calendar  Render a month grid: weekends / holidays / logged / planned / missing.
  submit    POST a reviewed plan file ({"workLogs":[...]}). --dry-run to preview.

Auth resolution order for any command: --token > --curl > cached token.
A fresh --curl/--token is cached automatically (unless --no-save).
"""

import argparse
import base64
import calendar as _cal
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "https://sra-api.smartosc.com/api"
ORIGIN = "https://sra.smartosc.com"
# The SmartOSC WAF returns 403 to non-browser User-Agents, so present a real one.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

STATE_DIR = os.path.expanduser("~/.claude/.sra")
TOKEN_FILE = os.path.join(STATE_DIR, "token")
PROFILE_FILE = os.path.join(STATE_DIR, "profile.json")
HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "..", "reference",
                             "vn_holidays.json")


# --------------------------------------------------------------------------- #
# small utils
# --------------------------------------------------------------------------- #
def die(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str):
    print(f"note: {msg}", file=sys.stderr)


def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# token: cache + JWT expiry
# --------------------------------------------------------------------------- #
def jwt_exp(token: str):
    """Return the token's expiry as a datetime (local), or None if unreadable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return dt.datetime.fromtimestamp(claims["exp"])
    except Exception:
        return None


def save_token(token: str):
    ensure_state_dir()
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token.strip())
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def clean_token(s: str) -> str:
    """Extract a JWT from anything the user pastes: a raw token, 'Bearer x',
    'authorization: Bearer x', or a whole curl blob."""
    s = s.strip().strip("'\"")
    m = re.search(r"[Bb]earer\s+([A-Za-z0-9._\-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", s)
    return m.group(0) if m else s


def token_from_curl(path: str) -> str:
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        die(f"cannot read curl file {path!r}: {e}")
    m = re.search(r"[Bb]earer\s+([A-Za-z0-9._\-]+)", text)
    if not m:
        die("no 'Bearer <token>' found in the curl file")
    return m.group(1)


def resolve_token(args, required=True):
    """--token > --curl > cache. Caches fresh tokens; checks expiry."""
    token = None
    fresh = False
    if getattr(args, "token", None):
        token, fresh = clean_token(args.token), True
    elif getattr(args, "curl", None):
        token, fresh = token_from_curl(args.curl), True
    elif os.path.exists(TOKEN_FILE):
        token = open(TOKEN_FILE, encoding="utf-8").read().strip()

    if not token:
        if required:
            die("no token: pass --curl <file> or --token <jwt> "
                "(none cached yet)")
        return None

    exp = jwt_exp(token)
    if not exp:
        warn("token has no readable JWT expiry — make sure you pasted the full key.")
    if exp:
        now = dt.datetime.now()
        if exp < now:
            die(f"token expired at {exp:%Y-%m-%d %H:%M}. "
                "Grab a fresh curl from the browser and pass --curl.")
        left = exp - now
        hrs = left.total_seconds() / 3600
        when = f"valid until {exp:%Y-%m-%d %H:%M} (~{left.days}d {int(hrs) % 24}h left)"
        if hrs < 24:
            warn(f"token {when} — expiring soon, consider refreshing.")
        else:
            warn(f"token {when}.")

    if fresh and not getattr(args, "no_save", False):
        save_token(token)
        warn("token cached.")
    return token


# --------------------------------------------------------------------------- #
# profile + holidays
# --------------------------------------------------------------------------- #
def load_profile() -> dict:
    if os.path.exists(PROFILE_FILE):
        try:
            return json.load(open(PROFILE_FILE, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            warn(f"profile unreadable ({e}); ignoring.")
    return {}


def save_profile(updates: dict) -> dict:
    """Merge updates into profile.json (created if absent)."""
    prof = load_profile()
    prof.update(updates)
    ensure_state_dir()
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(PROFILE_FILE, 0o600)
    except OSError:
        pass
    return prof


def load_holidays(years) -> dict:
    """{date_iso: name} for the requested years, from the bundled JSON."""
    out = {}
    try:
        data = json.load(open(HOLIDAYS_FILE, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    for y in years:
        out.update(data.get(str(y), {}))
    return out


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #
def api(method, path, token, base, body=None):
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("authorization", f"Bearer {token}")
    req.add_header("accept", "application/json, text/plain, */*")
    req.add_header("origin", ORIGIN)
    req.add_header("referer", ORIGIN + "/")
    req.add_header("user-agent", USER_AGENT)
    if data is not None:
        req.add_header("content-type", "text/plain")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}
    except urllib.error.URLError as e:
        die(f"network error calling {url}: {e}")


# --------------------------------------------------------------------------- #
# dates
# --------------------------------------------------------------------------- #
def parse_date(s):
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        die(f"bad date {s!r}, expected YYYY-MM-DD")


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


# --------------------------------------------------------------------------- #
# core: gather state
# --------------------------------------------------------------------------- #
def gather(token, base, username, start, end, exclude, target):
    st, tow = api("GET", "timesheet/type-of-work", token, base)
    if st != 200:
        die(f"type-of-work fetch failed (HTTP {st}): {tow}")
    type_of_work = {t["id"]: t["name"] for t in tow.get("typeOfWorks", [])}

    st, wl = api("GET", f"worklogs?username={username}", token, base)
    if st != 200:
        die(f"worklogs fetch failed (HTTP {st}): {wl}")
    logs = wl.get("workLogs", []) or []

    holidays = {k: v for k, v in load_holidays(range(start.year, end.year + 1)).items()
                if start.isoformat() <= k <= end.isoformat()}
    excl = set(exclude or []) | set(holidays)

    projects, in_range = {}, {}
    for l in logs:
        p = l.get("project") if isinstance(l.get("project"), dict) else None
        pid = p.get("id") if p else 0
        agg = projects.setdefault(pid, {
            "projectId": pid, "code": (p.get("code") if p else "") or "",
            "name": (p.get("name") if p else "Other") or "Other",
            "logs": 0, "hours": 0.0, "lastDate": "", "typeOfWork": {}})
        agg["logs"] += 1
        agg["hours"] += l.get("hours") or 0
        tw = l.get("typeOfWork")
        if tw:
            agg["typeOfWork"][tw] = agg["typeOfWork"].get(tw, 0) + 1
        day = (l.get("date") or "")[:10]
        if day and agg["lastDate"] < day:
            agg["lastDate"] = day
        if day and start.isoformat() <= day <= end.isoformat():
            in_range[day] = in_range.get(day, 0) + (l.get("hours") or 0)

    proj_list = sorted(projects.values(), key=lambda a: a["lastDate"], reverse=True)
    for a in proj_list:
        a["topTypeOfWork"] = sorted(a["typeOfWork"], key=a["typeOfWork"].get,
                                    reverse=True)

    workdays, missing, under = [], [], {}
    for d in daterange(start, end):
        if d.weekday() >= 5:
            continue
        iso = d.isoformat()
        if iso in excl:
            continue
        workdays.append(iso)
        if iso not in in_range:
            missing.append(iso)
        elif in_range[iso] < target:
            under[iso] = round(in_range[iso], 2)

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "username": username,
        "targetHoursPerDay": target,
        "typeOfWork": type_of_work,
        "projects": proj_list,
        "holidaysApplied": holidays,
        "excludedDates": sorted(excl),
        "alreadyLogged": {d: round(h, 2) for d, h in sorted(in_range.items())},
        "workingDays": workdays,
        "missingWorkingDays": missing,
        "underLoggedDays": dict(sorted(under.items())),
    }


def context_args(args):
    """Resolve username/target/exclude using the profile as defaults."""
    prof = load_profile()
    username = args.username or prof.get("username") or "nhatcl"
    target = args.target_hours if args.target_hours is not None \
        else float(prof.get("hoursPerDay", 8))
    exclude = [s.strip() for s in (args.exclude or "").split(",") if s.strip()]
    exclude += prof.get("fixedLeave", [])
    return username, target, exclude


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #
def cmd_onboard(args):
    """First-run guide: shows setup status + exact next steps. No network."""
    ok, todo = "✓", "•"
    print("\n=== log-work · Hướng dẫn sử dụng ===\n")

    # Step 1 — token
    tok = open(TOKEN_FILE, encoding="utf-8").read().strip() \
        if os.path.exists(TOKEN_FILE) else None
    exp = jwt_exp(tok) if tok else None
    token_ready = bool(tok and exp and exp > dt.datetime.now())
    print(f"[{ok if token_ready else todo}] 1. Token SRA")
    if token_ready:
        print(f"      Đã cache, hạn tới {exp:%Y-%m-%d %H:%M}.")
    else:
        msg = "hết hạn" if tok else "chưa có"
        print(f"      Token {msg}. Cách nhanh nhất: DÁN session key vào chat,")
        print("      mình tự cache (không cần lưu file).")
        print("      Lấy session key: mở https://sra.smartosc.com/time-sheet (đăng")
        print("      nhập SSO) → F12 → Network → bấm 1 request sra-api → copy giá trị")
        print("      header 'authorization: Bearer ...' (hoặc Copy as cURL) rồi dán.")

    # Step 2 — profile
    prof = load_profile()
    prof_ready = bool(prof.get("projects"))
    print(f"\n[{ok if prof_ready else todo}] 2. Profile (dự án + tỉ lệ)")
    if prof_ready:
        who = prof.get("username", "?")
        line = ", ".join(f"{p['code']} {int(p.get('ratio',0)*100)}%"
                         for p in prof["projects"])
        print(f"      {who} · {prof.get('hoursPerDay',8)}h/ngày · {line}")
    else:
        print(f"      Chưa có. Sẽ tạo ở lần log đầu khi bạn chốt dự án + tỉ lệ.")
        print(f"      File: {PROFILE_FILE}")

    # Step 2b — SRA user id (for auto allocation)
    uid = prof.get("userId")
    print(f"\n[{ok if uid else todo}] 2b. SRA user id (tự lấy allocation)")
    if uid:
        print(f"      userId={uid} — chạy `allocation` để lấy dự án + tỉ lệ thật.")
    else:
        print("      Chưa có. Mở trang profile trên SRA, lấy số trong URL users/<id>")
        print("      (vd users/226) → mình lưu 1 lần, sau đó tự đọc allocation.")

    # Step 3 — holidays
    hol = load_holidays([dt.date.today().year])
    print(f"\n[{ok if hol else todo}] 3. Lịch lễ VN {dt.date.today().year}"
          f"  ({len(hol)} ngày, tự loại khỏi ngày công)")

    # Usage
    print("\n--- Cách dùng hằng ngày ---")
    print("  • Kiểm tra timesheet:   \"check timesheet tháng này\"")
    print("  • Log bù cả tháng:      \"log work tháng 6, nghỉ ngày 15\"")
    print("  • Log nhanh hôm nay:    \"log hôm nay 8h Poc Tm Asset\"")
    print("  Luồng: đọc trạng thái → đề xuất dữ liệu đẹp → preview (bảng + lịch)")
    print("         → bạn duyệt → submit → verify lại. Không bao giờ ghi khi chưa duyệt.")

    ready = token_ready and prof_ready
    print(f"\n=> Trạng thái: {'SẴN SÀNG ✓' if ready else 'cần hoàn tất bước ' + ('1' if not token_ready else '2') + ' ở trên'}\n")


def cmd_token(args):
    if args.curl or args.token:
        resolve_token(args)  # caches + reports expiry
        return
    if not os.path.exists(TOKEN_FILE):
        print("no cached token. Pass --curl <file> or --token <jwt> to set one.")
        return
    tok = open(TOKEN_FILE, encoding="utf-8").read().strip()
    exp = jwt_exp(tok)
    if not exp:
        print("cached token present (expiry unreadable).")
    elif exp < dt.datetime.now():
        print(f"cached token EXPIRED at {exp:%Y-%m-%d %H:%M}. Refresh with --curl.")
    else:
        left = exp - dt.datetime.now()
        print(f"cached token valid until {exp:%Y-%m-%d %H:%M} (~{left.days}d left).")


def cmd_profile(args):
    prof = load_profile()
    print(f"profile: {PROFILE_FILE}")
    if not prof:
        print("(none yet — create it with the projects/allocation you confirm)")
        return
    print(json.dumps(prof, ensure_ascii=False, indent=2))


def cmd_context(args):
    token = resolve_token(args)
    start, end = parse_date(args.start), parse_date(args.end)
    if start > end:
        die("--start is after --end")
    username, target, exclude = context_args(args)
    data = gather(token, args.base, username, start, end, exclude, target)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_check(args):
    token = resolve_token(args)
    start, end = parse_date(args.start), parse_date(args.end)
    username, target, exclude = context_args(args)
    d = gather(token, args.base, username, start, end, exclude, target)
    logged_full = [x for x in d["workingDays"]
                   if x in d["alreadyLogged"] and x not in d["underLoggedDays"]]
    print(f"Timesheet {d['range']['start']} .. {d['range']['end']}  "
          f"(user {username}, target {target:g}h/day)")
    print(f"  working days   : {len(d['workingDays'])}")
    print(f"  fully logged   : {len(logged_full)}")
    print(f"  under-logged   : {len(d['underLoggedDays'])}  "
          + (", ".join(f"{k}({v:g}h)" for k, v in d['underLoggedDays'].items())
             if d['underLoggedDays'] else ""))
    print(f"  missing (0h)   : {len(d['missingWorkingDays'])}  "
          + (", ".join(d['missingWorkingDays']) if d['missingWorkingDays'] else ""))
    if d["holidaysApplied"]:
        print("  holidays       : "
              + ", ".join(f"{k} {v}" for k, v in d["holidaysApplied"].items()))
    need = sum(target - d["alreadyLogged"].get(x, 0) for x in d["missingWorkingDays"]) \
        + sum(target - h for h in d["underLoggedDays"].values())
    print(f"  hours to log   : {need:g}h to reach target on all working days")


def cmd_calendar(args):
    token = resolve_token(args)
    start, end = parse_date(args.start), parse_date(args.end)
    username, target, exclude = context_args(args)
    d = gather(token, args.base, username, start, end, exclude, target)
    logged, holidays = d["alreadyLogged"], d["holidaysApplied"]

    plan = {}  # date -> (hours, code)
    if args.file and os.path.exists(args.file):
        try:
            pj = json.load(open(args.file, encoding="utf-8"))
            code_by_id = {p["projectId"]: p["code"] for p in d["projects"]}
            for w in pj.get("workLogs", []):
                hrs, pid = w.get("workHours", 0), w.get("projectId")
                cur = plan.get(w["date"], (0, ""))
                plan[w["date"]] = (cur[0] + hrs,
                                   code_by_id.get(pid, str(pid))[:7])
        except (OSError, json.JSONDecodeError, KeyError) as e:
            warn(f"plan file ignored ({e}).")

    def cell(day):
        iso = day.isoformat()
        if not (start <= day <= end):
            return " " * 12
        if day.weekday() >= 5:
            return f"{day.day:2} ·weekend"[:12].ljust(12)
        if iso in holidays:
            return f"{day.day:2} HOLIDAY"[:12].ljust(12)
        if iso in plan:
            h, c = plan[iso]
            return f"{day.day:2} +{h:g} {c}"[:12].ljust(12)
        if iso in logged:
            mark = "✓" if logged[iso] >= target else "◐"
            return f"{day.day:2} {mark}{logged[iso]:g}"[:12].ljust(12)
        return f"{day.day:2} —miss"[:12].ljust(12)

    print(f"  {d['range']['start']} .. {d['range']['end']}   "
          f"✓=full ◐=partial +=planned —=missing  (target {target:g}h)\n")
    hdr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print("  " + " ".join(h.ljust(12) for h in hdr))
    # walk full weeks covering the range
    first = start - dt.timedelta(days=start.weekday())
    last = end + dt.timedelta(days=(6 - end.weekday()))
    d2 = first
    while d2 <= last:
        row = [cell(d2 + dt.timedelta(days=i)) for i in range(7)]
        print("  " + " ".join(row))
        d2 += dt.timedelta(days=7)


def cmd_allocation(args):
    """Assigned projects + ratios for a range, from users/<id>.workingHistory.
    This is the authoritative allocation source (the SRA 'Working Details')."""
    token = resolve_token(args)
    start, end = parse_date(args.start), parse_date(args.end)
    prof = load_profile()
    uid = args.user_id or prof.get("userId")
    if not uid:
        die("no SRA user id. Pass --user-id <n> — find it in the users/<id> URL "
            "on your SRA profile page (DevTools/Network). It will be saved to the "
            "profile so you only do this once.")
    if args.user_id and prof.get("userId") != args.user_id:
        save_profile({"userId": args.user_id})
        warn(f"saved userId={args.user_id} to profile.")

    st, u = api("GET", f"users/{uid}", token, args.base)
    if st != 200:
        die(f"users/{uid} fetch failed (HTTP {st}): {u}")

    s, e = start.isoformat(), end.isoformat()
    agg = {}
    for w in u.get("workingHistory", []) or []:
        ws, we = (w.get("startDate") or "")[:10], (w.get("endDate") or "")[:10]
        if not ws or not we or ws > e or we < s:  # no overlap with [start,end]
            continue
        pid = w.get("projectId")
        a = agg.setdefault(pid, {"projectId": pid,
                                 "code": w.get("projectCode", ""),
                                 "name": w.get("name", ""), "effort": 0.0})
        a["effort"] += w.get("totalEffort") or 0

    total = sum(a["effort"] for a in agg.values())
    projects = sorted(agg.values(), key=lambda a: a["effort"], reverse=True)
    for a in projects:
        a["effort"] = round(a["effort"], 2)
        a["ratio"] = round(a["effort"] / total, 3) if total else 0

    print(json.dumps({
        "userId": uid, "name": u.get("name"), "username": u.get("username"),
        "range": {"start": s, "end": e},
        "allocations": projects,
        "totalEffort": round(total, 2),
        "note": "Ratios from allocated effort (workingHistory) overlapping the "
                "range — authoritative source for which projects to log to."
                if projects else
                "No allocation overlaps this range (period may not be planned "
                "yet). Fall back to the most recent allocation or ask the user.",
    }, ensure_ascii=False, indent=2))


def cmd_submit(args):
    token = resolve_token(args)
    try:
        payload = json.load(open(args.file, encoding="utf-8"))
    except OSError as e:
        die(f"cannot read plan file: {e}")
    except json.JSONDecodeError as e:
        die(f"plan file is not valid JSON: {e}")
    if "workLogs" not in payload or not isinstance(payload["workLogs"], list):
        die('plan must be {"workLogs":[{date,description,workHours,'
            'typeOfWork,projectId}, ...]}')
    required = {"date", "description", "workHours", "typeOfWork", "projectId"}
    for i, w in enumerate(payload["workLogs"]):
        miss = required - set(w)
        if miss:
            die(f"workLogs[{i}] missing fields: {sorted(miss)}")
        if not str(w["description"]).strip() or str(w["description"]).strip().lower() in {"n/a", "na", "test"}:
            die(f"workLogs[{i}] has an empty/placeholder description "
                f"({w['description']!r}) — generate a real one.")

    total = sum(w["workHours"] for w in payload["workLogs"])
    print(f"{len(payload['workLogs'])} worklog(s), {total:g}h total", file=sys.stderr)
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("dry-run: nothing sent.", file=sys.stderr)
        return
    st, resp = api("POST", "user/worklogs", token, args.base, body=payload)
    print(json.dumps({"httpStatus": st, "response": resp},
                     ensure_ascii=False, indent=2))
    if st >= 300:
        sys.exit(1)


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="SRA timesheet worklog helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    def auth(sp):
        sp.add_argument("--token", help="session key / bearer token (raw JWT, "
                        "'Bearer x', or a pasted curl — all accepted)")
        sp.add_argument("--curl", help="path to a file containing the SRA curl")
        sp.add_argument("--no-save", action="store_true",
                        help="do not cache a fresh token")
        sp.add_argument("--base", default=DEFAULT_BASE)

    def range_args(sp):
        sp.add_argument("--start", required=True, help="YYYY-MM-DD")
        sp.add_argument("--end", required=True, help="YYYY-MM-DD")
        sp.add_argument("--username", default=None)
        sp.add_argument("--exclude", help="comma-separated YYYY-MM-DD to skip")
        sp.add_argument("--target-hours", type=float, default=None,
                        help="hours per working day (default profile or 8)")

    ob = sub.add_parser("onboard", help="first-run guide + setup status")
    ob.set_defaults(func=cmd_onboard)

    t = sub.add_parser("token", help="show/set cached token + expiry")
    auth(t)
    t.set_defaults(func=cmd_token)

    pr = sub.add_parser("profile", help="print saved profile")
    pr.set_defaults(func=cmd_profile)

    c = sub.add_parser("context", help="read SRA state -> JSON")
    auth(c); range_args(c); c.set_defaults(func=cmd_context)

    ck = sub.add_parser("check", help="human-readable timesheet status")
    auth(ck); range_args(ck); ck.set_defaults(func=cmd_check)

    cal = sub.add_parser("calendar", help="render a month grid")
    auth(cal); range_args(cal)
    cal.add_argument("--file", help="optional plan JSON to overlay as planned")
    cal.set_defaults(func=cmd_calendar)

    al = sub.add_parser("allocation",
                        help="assigned projects + ratios for a range (users/<id>)")
    auth(al)
    al.add_argument("--start", required=True, help="YYYY-MM-DD")
    al.add_argument("--end", required=True, help="YYYY-MM-DD")
    al.add_argument("--user-id", type=int, default=None,
                    help="SRA numeric user id (saved to profile on first use)")
    al.set_defaults(func=cmd_allocation)

    s = sub.add_parser("submit", help="POST a reviewed plan file")
    auth(s)
    s.add_argument("--file", required=True, help="plan JSON file")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_submit)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
