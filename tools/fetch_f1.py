#!/usr/bin/env python3
"""
피트월 노트 — F1 데이터 수집기
Jolpica(구 Ergast) 공개 API에서 일정/결과/순위/랩차트를 받아 data/live.json 으로 저장.
브라우저가 아니라 서버(GitHub)에서 돌기 때문에 CORS·User-Agent 제약이 없다.
"""
import argparse, hashlib, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = "https://api.jolpi.ca/ergast/f1"
UA = "pitwall-note/1.0 (personal F1 companion; github pages)"
LIMIT = 100
SLEEP = 0.35

JID = {
    "russell": "rus", "max_verstappen": "ver", "antonelli": "ant", "hamilton": "ham",
    "leclerc": "lec", "norris": "nor", "piastri": "pia", "hadjar": "had",
    "lawson": "law", "arvid_lindblad": "lin", "tsunoda": "tsu", "gasly": "gas",
    "colapinto": "col", "bearman": "bea", "ocon": "oco", "bortoleto": "bor",
    "hulkenberg": "hul", "albon": "alb", "sainz": "sai", "alonso": "alo",
    "stroll": "str", "perez": "per", "bottas": "bot",
}
TID = {
    "mercedes": "mer", "ferrari": "fer", "mclaren": "mcl", "red_bull": "rbr",
    "rb": "rb", "alphatauri": "rb", "racing_bulls": "rb", "alpine": "alp",
    "haas": "haa", "audi": "aud", "sauber": "aud", "kick_sauber": "aud",
    "williams": "wil", "aston_martin": "ast", "cadillac": "cad",
}


def _hours_since(iso):
    if not iso:
        return 1e9
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return 1e9
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def _parse(iso_s):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(iso_s if fmt[-1] == "Z" else iso_s[:10], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def recent_session(schedule, lo=3.0, hi=36.0):
    """최근에 끝난 세션이 있으면 (라운드, 종류, 몇 시간 전).
       세션 시작 후 lo시간~hi시간 사이만 본다 — 경기가 끝난 다음에 받아오기 위함."""
    now = datetime.now(timezone.utc)
    best = None
    for r in schedule or []:
        ses = r.get("sessions") or {}
        cands = [("결승", r.get("race")), ("예선", ses.get("qual")),
                 ("스프린트", ses.get("sprint")),
                 ("스프린트 예선", ses.get("sq") or ses.get("ss"))]
        for ko, iso_s in cands:
            if not iso_s:
                continue
            t = _parse(iso_s)
            if not t:
                continue
            age = (now - t).total_seconds() / 3600.0
            if lo <= age <= hi and (best is None or age < best[2]):
                best = (r.get("rd"), ko, age)
    return best


def payload_key(d):
    keep = {k: d.get(k) for k in
            ("season", "lastRound", "schedule", "standings", "drivers",
             "results", "podium", "fastest", "laps", "qualifying", "careers")}
    return hashlib.sha256(
        json.dumps(keep, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _near(race_iso, days=4):
    if not race_iso:
        return False
    try:
        t = datetime.strptime(race_iso[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return abs((t - datetime.now(timezone.utc)).days) <= days


def get(path, **params):
    params.setdefault("limit", LIMIT)
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}/{path}.json?{q}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(SLEEP)
                return json.load(r)["MRData"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def dcode(d):
    did = d.get("driverId", "")
    if did in JID:
        return JID[did]
    c = d.get("code")
    if c:
        return c.lower()
    return did[:3].lower()


def tcode(c):
    cid = c.get("constructorId", "")
    return TID.get(cid, cid[:3].lower())


def iso(date, t):
    if not date:
        return None
    return f"{date}T{t}" if t else f"{date}T00:00:00Z"


def fetch_schedule(season):
    md = get(f"{season}/races")
    out = []
    for r in md["RaceTable"]["Races"]:
        loc = r["Circuit"]["Location"]
        ses = {}
        for key, field in [("fp1", "FirstPractice"), ("fp2", "SecondPractice"),
                           ("fp3", "ThirdPractice"), ("qual", "Qualifying"),
                           ("sprint", "Sprint"), ("sq", "SprintQualifying"),
                           ("ss", "SprintShootout")]:
            s = r.get(field)
            if s:
                ses[key] = iso(s.get("date"), s.get("time"))
        out.append({
            "rd": int(r["round"]),
            "name": r["raceName"],
            "circuitId": r["Circuit"]["circuitId"],
            "circuit": r["Circuit"]["circuitName"],
            "locality": loc.get("locality", ""),
            "country": loc.get("country", ""),
            "race": iso(r.get("date"), r.get("time")),
            "sessions": ses,
        })
    return out


def fetch_standings(season):
    d, t, drivers = [], [], {}
    md = get(f"{season}/driverstandings")
    lists = md["StandingsTable"].get("StandingsLists", [])
    if lists:
        for s in lists[0]["DriverStandings"]:
            code = dcode(s["Driver"])
            d.append([code, float(s["points"])])
            cons = s.get("Constructors") or [{}]
            drivers[code] = {
                "no": int(s["Driver"].get("permanentNumber", 0) or 0),
                "given": s["Driver"].get("givenName", ""),
                "family": s["Driver"].get("familyName", ""),
                "team": tcode(cons[-1]),
            }
    md = get(f"{season}/constructorstandings")
    lists = md["StandingsTable"].get("StandingsLists", [])
    if lists:
        for s in lists[0]["ConstructorStandings"]:
            t.append([tcode(s["Constructor"]), float(s["points"])])
    return {"d": d, "t": t}, drivers


def fetch_results(season, rd):
    md = get(f"{season}/{rd}/results")
    races = md["RaceTable"]["Races"]
    if not races:
        return None
    rows, podium, fastest, idmap = [], [], None, {}
    for r in races[0]["Results"]:
        code = dcode(r["Driver"])
        idmap[r["Driver"]["driverId"]] = code
        grid = int(r.get("grid", 0) or 0)
        status = r.get("status", "")
        pos = int(r["position"])
        classified = status == "Finished" or status.startswith("+")
        rows.append([code, grid, pos if classified else 0])
        if classified and pos <= 3:
            podium.append((pos, code))
        fl = r.get("FastestLap")
        if fl and fl.get("rank") == "1":
            fastest = {"code": code, "lap": int(fl.get("lap", 0) or 0),
                       "time": (fl.get("Time") or {}).get("time", "")}
    podium = [c for _, c in sorted(podium)]
    return {"rows": rows, "podium": podium, "fastest": fastest, "idmap": idmap}


def fetch_qualifying(season, rd):
    md = get(f"{season}/{rd}/qualifying")
    races = md["RaceTable"]["Races"]
    if not races:
        return None
    rows = []
    for r in races[0].get("QualifyingResults", []):
        rows.append([dcode(r["Driver"]), int(r["position"]),
                     r.get("Q1", ""), r.get("Q2", ""), r.get("Q3", "")])
    return {"rows": rows} if rows else None


def fetch_career(season, driver_id):
    """드라이버가 뛴 팀과 연도. [[constructorId, 시작, 끝], ...] (최신 순)"""
    md = get(f"drivers/{driver_id}/constructors")
    cons = [c["constructorId"] for c in md.get("ConstructorTable", {}).get("Constructors", [])]
    spans = []
    for cid in cons:
        md2 = get(f"drivers/{driver_id}/constructors/{cid}/seasons", limit=LIMIT)
        yrs = sorted(int(s["season"]) for s in md2.get("SeasonTable", {}).get("Seasons", []))
        if not yrs:
            continue
        start = prev_y = yrs[0]
        for y in yrs[1:]:
            if y != prev_y + 1:
                spans.append([cid, start, prev_y])
                start = y
            prev_y = y
        spans.append([cid, start, prev_y])
    spans.sort(key=lambda s: (-s[2], -s[1]))
    return spans


def fetch_laps(season, rd, idmap=None):
    idmap = idmap or {}
    per, total, offset = {}, None, 0
    while True:
        md = get(f"{season}/{rd}/laps", limit=LIMIT, offset=offset)
        races = md["RaceTable"]["Races"]
        if not races:
            break
        for lap in races[0].get("Laps", []):
            n = int(lap["number"])
            total = max(total or 0, n)
            for t in lap["Timings"]:
                did = t["driverId"]
                code = idmap.get(did) or dcode({"driverId": did})
                per.setdefault(code, {})[n] = int(t["position"])
        offset += LIMIT
        if offset >= int(md.get("total", 0)):
            break
        if offset > 6000:
            break
    if not per or not total:
        return None
    out = {}
    for code, m in per.items():
        last, seq = None, []
        for n in range(1, total + 1):
            v = m.get(n)
            if v is None:
                v = last
            else:
                last = v
            seq.append(v or 0)
        out[code] = seq
    return {"laps": total, "d": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--out", default="data/live.json")
    ap.add_argument("--max-new-laps", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet-hours", type=float, default=72)
    ap.add_argument("--max-new-careers", type=int, default=25)
    ap.add_argument("--heartbeat-days", type=float, default=7)
    a = ap.parse_args()

    prev = {}
    if os.path.exists(a.out):
        try:
            prev = json.load(open(a.out, encoding="utf-8"))
        except Exception:
            prev = {}
    same_season = prev.get("season") == a.season

    rs = recent_session(prev.get("schedule")) if same_season else None
    since = _hours_since(prev.get("checked") or prev.get("generated"))
    if a.force:
        why = "수동/강제 실행"
    elif rs:
        why = f"R{rs[0]} {rs[1]} 끝난 지 {rs[2]:.0f}시간"
    elif since >= a.quiet_hours:
        why = f"평시 — 마지막 확인 {since:.0f}시간 전"
    else:
        print(f"skip: 최근 끝난 세션 없음 · 마지막 확인 {since:.1f}시간 전 (기준 {a.quiet_hours:.0f}시간) — API 호출 없음")
        return 0
    print(f"run: {why}")

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": a.season,
        "schedule": [], "standings": {"d": [], "t": []},
        "drivers": {}, "results": {}, "podium": {}, "fastest": {}, "laps": {},
        "qualifying": {},
        "careers": {},
        "errors": [],
    }

    try:
        out["schedule"] = fetch_schedule(a.season)
    except Exception as e:
        out["errors"].append(f"schedule: {e}")
        out["schedule"] = prev.get("schedule", []) if same_season else []

    try:
        out["standings"], out["drivers"] = fetch_standings(a.season)
    except Exception as e:
        out["errors"].append(f"standings: {e}")
        if same_season:
            out["standings"] = prev.get("standings", {"d": [], "t": []})
            out["drivers"] = prev.get("drivers", {})

    prev_res = prev.get("results", {}) if same_season else {}
    prev_laps = prev.get("laps", {}) if same_season else {}
    out["laps"] = dict(prev_laps)

    prev_qual = prev.get("qualifying", {}) if same_season else {}
    out["qualifying"] = dict(prev_qual)
    out["careers"] = dict(prev.get("careers", {}))
    new_lap_rounds, last_round, idmaps = [], 0, {}
    for r in out["schedule"]:
        rd = str(r["rd"])
        try:
            res = fetch_results(a.season, r["rd"])
        except Exception as e:
            out["errors"].append(f"results r{rd}: {e}")
            res = None
        if res is None:
            if _near(r.get("race")) and rd not in out["qualifying"]:
                try:
                    q = fetch_qualifying(a.season, r["rd"])
                    if q:
                        out["qualifying"][rd] = q
                except Exception as e:
                    out["errors"].append(f"qualifying r{rd}: {e}")
            if rd in prev_res:
                out["results"][rd] = prev_res[rd]
                out["podium"][rd] = prev.get("podium", {}).get(rd, [])
                last_round = max(last_round, int(rd))
            continue
        idmaps[r["rd"]] = res["idmap"]
        if rd not in out["qualifying"]:
            try:
                q = fetch_qualifying(a.season, r["rd"])
                if q:
                    out["qualifying"][rd] = q
            except Exception as e:
                out["errors"].append(f"qualifying r{rd}: {e}")
        out["results"][rd] = res["rows"]
        out["podium"][rd] = res["podium"]
        if res["fastest"]:
            out["fastest"][rd] = res["fastest"]
        last_round = max(last_round, int(rd))
        if rd not in out["laps"]:
            new_lap_rounds.append(r["rd"])

    out["lastRound"] = last_round

    for rd in new_lap_rounds[-a.max_new_laps:]:
        try:
            lp = fetch_laps(a.season, rd, idmaps.get(rd))
            if lp:
                out["laps"][str(rd)] = lp
        except Exception as e:
            out["errors"].append(f"laps r{rd}: {e}")

    # ── 팀 이력: 아직 없거나 올해가 빠진 드라이버만 ──
    jid_rev = {v: k for k, v in JID.items()}
    todo = []
    for code in out.get("drivers", {}):
        cur = out["careers"].get(code)
        if not cur or not cur.get("t") or max((s[2] for s in cur["t"]), default=0) < a.season:
            todo.append(code)
    for code in todo[:a.max_new_careers]:
        did = jid_rev.get(code)
        if not did:
            continue
        try:
            spans = fetch_career(a.season, did)
            if spans:
                out["careers"][code] = {"t": spans}
        except Exception as e:
            out["errors"].append(f"career {code}: {e}")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["checked"] = now_iso
    key = payload_key(out)
    changed = key != prev.get("key")
    stale = _hours_since(prev.get("checked") or prev.get("generated")) >= a.heartbeat_days * 24

    if changed:
        out["generated"] = now_iso
    else:
        out["generated"] = prev.get("generated", now_iso)
    out["key"] = key

    if not (changed or stale or a.force):
        print(f"no-change: 받아왔지만 내용이 같음 — 파일 그대로 둠 (마지막 변경 {out['generated']})")
        return 0

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    print(f"{'changed' if changed else 'heartbeat'} · season={a.season} rounds={len(out['schedule'])} results={len(out['results'])} laps={len(out['laps'])} qual={len(out['qualifying'])} career={len(out['careers'])} last={last_round} errors={len(out['errors'])}")
    for e in out["errors"]:
        print("  !", e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
