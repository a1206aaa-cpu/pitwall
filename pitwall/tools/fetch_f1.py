#!/usr/bin/env python3
"""
피트월 노트 — F1 데이터 수집기
Jolpica(구 Ergast) 공개 API에서 일정/결과/순위/랩차트를 받아 data/live.json 으로 저장.
GitHub Actions에서 하루 한 번 실행되고, 바뀐 게 있을 때만 커밋된다.

브라우저가 아니라 서버(GitHub)에서 돌기 때문에 CORS·User-Agent 제약이 없고,
방문자가 많아져도 API에 부하를 주지 않는다.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
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
    a = ap.parse_args()

    prev = {}
    if os.path.exists(a.out):
        try:
            prev = json.load(open(a.out, encoding="utf-8"))
        except Exception:
            prev = {}
    same_season = prev.get("season") == a.season

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": a.season,
        "schedule": [], "standings": {"d": [], "t": []},
        "drivers": {}, "results": {}, "podium": {}, "fastest": {}, "laps": {},
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

    new_lap_rounds, last_round, idmaps = [], 0, {}
    for r in out["schedule"]:
        rd = str(r["rd"])
        try:
            res = fetch_results(a.season, r["rd"])
        except Exception as e:
            out["errors"].append(f"results r{rd}: {e}")
            res = None
        if res is None:
            if rd in prev_res:
                out["results"][rd] = prev_res[rd]
                out["podium"][rd] = prev.get("podium", {}).get(rd, [])
                last_round = max(last_round, int(rd))
            continue
        idmaps[r["rd"]] = res["idmap"]
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

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    print(f"season={a.season} rounds={len(out['schedule'])} results={len(out['results'])} "
          f"laps={len(out['laps'])} last={last_round} errors={len(out['errors'])}")
    for e in out["errors"]:
        print("  !", e, file=sys.stderr)
    # 에러가 있어도 파일은 쓰고 정상 종료 — 사이트가 빈 화면이 되는 걸 막는다
    return 0


if __name__ == "__main__":
    sys.exit(main())
