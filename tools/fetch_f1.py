#!/usr/bin/env python3
"""
피트월 노트 — F1 데이터 수집기
Jolpica(구 Ergast) 공개 API에서 일정/결과/순위/랩차트를 받아 data/live.json 으로 저장.
GitHub Actions에서 하루 한 번 실행되고, 바뀐 게 있을 때만 커밋된다.

브라우저가 아니라 서버(GitHub)에서 돌기 때문에 CORS·User-Agent 제약이 없고,
방문자가 많아져도 API에 부하를 주지 않는다.
"""
import argparse, hashlib, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = "https://api.jolpi.ca/ergast/f1"
UA = "pitwall-note/1.0 (personal F1 companion; github pages)"
LIMIT = 100          # Jolpica 최대값
SLEEP = 0.35         # 요청 간격 (rate limit 여유)

# API driverId -> 앱 내부 3글자 id (API의 code 필드가 없거나 다를 때만 필요)
JID = {
    "russell": "rus", "max_verstappen": "ver", "antonelli": "ant", "hamilton": "ham",
    "leclerc": "lec", "norris": "nor", "piastri": "pia", "hadjar": "had",
    "lawson": "law", "arvid_lindblad": "lin", "tsunoda": "tsu", "gasly": "gas",
    "colapinto": "col", "bearman": "bea", "ocon": "oco", "bortoleto": "bor",
    "hulkenberg": "hul", "albon": "alb", "sainz": "sai", "alonso": "alo",
    "stroll": "str", "perez": "per", "bottas": "bot",
}
# API constructorId -> 앱 내부 팀 id
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


def race_week(schedule, before=4, after=2):
    """결승 기준 -before일 ~ +after일 사이면 레이스 주간."""
    now = datetime.now(timezone.utc)
    for r in schedule or []:
        iso = r.get("race")
        if not iso:
            continue
        try:
            t = datetime.strptime(iso[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        d = (t - now).total_seconds() / 86400.0
        if -after <= d <= before:
            return r.get("rd")
    return None


def payload_key(d):
    """`checked`/`generated` 같은 시각 필드를 뺀 알맹이만 — 바뀌었는지 비교용."""
    keep = {k: d.get(k) for k in
            ("season", "lastRound", "schedule", "standings", "drivers",
             "results", "podium", "fastest", "laps", "qualifying")}
    return hashlib.sha256(
        json.dumps(keep, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _near(race_iso, days=4):
    """결승이 앞뒤 N일 이내인가 — 주말 중인 라운드만 예선을 확인한다."""
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
    """API 드라이버 객체 -> 내부 3글자 id"""
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
    """'2026-03-08' + '04:00:00Z' -> '2026-03-08T04:00:00Z'"""
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
    """예선 결과. {rows:[[code, pos, q1, q2, q3], ...]}"""
    md = get(f"{season}/{rd}/qualifying")
    races = md["RaceTable"]["Races"]
    if not races:
        return None
    rows = []
    for r in races[0].get("QualifyingResults", []):
        rows.append([dcode(r["Driver"]), int(r["position"]),
                     r.get("Q1", ""), r.get("Q2", ""), r.get("Q3", "")])
    return {"rows": rows} if rows else None


def fetch_laps(season, rd, idmap=None):
    """랩별 포지션. {laps:N, d:{code:[pos,...]}}"""
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
        if offset > 6000:                      # 안전장치
            break
    if not per or not total:
        return None
    out = {}
    for code, m in per.items():
        last, seq = None, []
        for n in range(1, total + 1):
            v = m.get(n)
            if v is None:
                v = last                        # 피트/리타이어 직전 값 유지
            else:
                last = v
            seq.append(v or 0)
        out[code] = seq
    return {"laps": total, "d": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--out", default="data/live.json")
    ap.add_argument("--max-new-laps", type=int, default=3,
                    help="한 번 실행에서 새로 받아올 랩차트 라운드 수 (API 부담 방지)")
    ap.add_argument("--force", action="store_true",
                    help="주기 판정을 건너뛰고 무조건 받아온다 (수동 실행용)")
    ap.add_argument("--quiet-hours", type=float, default=48,
                    help="레이스 주간이 아닐 때 최소 간격(시간)")
    ap.add_argument("--heartbeat-days", type=float, default=7,
                    help="데이터가 안 바뀌어도 이 주기로는 한 번 커밋 (예약 실행이 꺼지는 걸 막음)")
    a = ap.parse_args()

    prev = {}
    if os.path.exists(a.out):
        try:
            prev = json.load(open(a.out, encoding="utf-8"))
        except Exception:
            prev = {}
    same_season = prev.get("season") == a.season

    # ── 지금 받아올 때인가? ─────────────────────────────────
    rw = race_week(prev.get("schedule")) if same_season else None
    since = _hours_since(prev.get("checked") or prev.get("generated"))
    if a.force:
        why = "수동/강제 실행"
    elif rw:
        why = f"R{rw} 레이스 주간"
    elif since >= a.quiet_hours:
        why = f"평시 — 마지막 확인 {since:.0f}시간 전"
    else:
        print(f"skip: 레이스 주간 아님 · 마지막 확인 {since:.1f}시간 전 "
              f"(기준 {a.quiet_hours:.0f}시간) — API 호출 없음")
        return 0
    print(f"run: {why}")

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": a.season,
        "schedule": [], "standings": {"d": [], "t": []},
        "drivers": {}, "results": {}, "podium": {}, "fastest": {}, "laps": {},
        "qualifying": {},
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

    # 결과: 전체 라운드를 매번 확인 (레이스당 1요청 — 가볍다)
    prev_res = prev.get("results", {}) if same_season else {}
    prev_laps = prev.get("laps", {}) if same_season else {}
    out["laps"] = dict(prev_laps)

    prev_qual = prev.get("qualifying", {}) if same_season else {}
    out["qualifying"] = dict(prev_qual)
    new_lap_rounds, last_round, idmaps = [], 0, {}
    for r in out["schedule"]:
        rd = str(r["rd"])
        try:
            res = fetch_results(a.season, r["rd"])
        except Exception as e:
            out["errors"].append(f"results r{rd}: {e}")
            res = None
        if res is None:
            # 결승 전이라도 예선은 끝나 있을 수 있다 — 주말이 임박한 라운드만 확인
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

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["checked"] = now_iso
    key = payload_key(out)
    changed = key != prev.get("key")
    stale = _hours_since(prev.get("checked") or prev.get("generated")) >= a.heartbeat_days * 24

    if changed:
        out["generated"] = now_iso            # 데이터가 실제로 바뀐 시각
    else:
        out["generated"] = prev.get("generated", now_iso)
    out["key"] = key

    if not (changed or stale or a.force):
        print(f"no-change: 받아왔지만 내용이 같음 — 파일 그대로 둠 (마지막 변경 {out['generated']})")
        return 0

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    print(f"{'changed' if changed else 'heartbeat'} · season={a.season} rounds={len(out['schedule'])} results={len(out['results'])} "
          f"laps={len(out['laps'])} qual={len(out['qualifying'])} last={last_round} errors={len(out['errors'])}")
    for e in out["errors"]:
        print("  !", e, file=sys.stderr)
    # 에러가 있어도 파일은 쓰고 정상 종료 — 사이트가 빈 화면이 되는 걸 막는다
    return 0


if __name__ == "__main__":
    sys.exit(main())
