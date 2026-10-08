"""
Reconcile the live views against tests/expected.json — figures computed straight from Cricsheet's
raw files by tests/ground_truth.py — asserting EXACT equality (relentless-testing L1/L2).

    EMBABEL_USER=… EMBABEL_PASSWORD=… python3 tests/verify.py [APPLIANCE_URL]
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("APPLIANCE_URL", "http://localhost:11043")
USER, PASSWORD = os.environ.get("EMBABEL_USER"), os.environ.get("EMBABEL_PASSWORD")
if not USER or not PASSWORD:
    sys.exit("Set EMBABEL_USER and EMBABEL_PASSWORD.")
EXPECTED = json.loads((Path(__file__).resolve().parent / "expected.json").read_text())
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
failures = 0


def invoke(name, args):
    req = urllib.request.Request(f"{BASE}/api/v1/views/{name}/invoke", data=json.dumps({"args": args}).encode(),
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        env = json.load(r)
    if env.get("status") != "SUCCEEDED":
        raise RuntimeError(f"{name} {args}: {env.get('status')} {env.get('error')}")
    if env.get("warnings"):
        print(f"      warnings on {name}: {env['warnings']}")
    return env["data"]


def check(label, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got {got!r}" + ("" if ok else f", expected {want!r}"))


seasons = invoke("CountySeasons", {})
check("total matches", sum(s["matches"] for s in seasons), EXPECTED["matches"])
check("matches by season", {str(s["season"]): s["matches"] for s in seasons}, EXPECTED["matchesBySeason"])
check("decided matches", sum(s["decided"] for s in seasons), EXPECTED["results"]["won"])
check("drawn matches", sum(s["drawn"] for s in seasons), EXPECTED["results"]["draw"])

teams = invoke("CountyTeams", {})
check("teams", len(teams), EXPECTED["teams"])
check("matches per team", {t["team"]: t["played"] for t in teams}, EXPECTED["teamMatches"])

for key, want in EXPECTED["table"].items():
    season, stage = key.split("-")
    rows = invoke("CountyTable", {"season": int(season), "stage": int(stage)})
    got = {r["team"]: {k: r[k] for k in ("played", "won", "drawn", "lost", "tied") if r[k]} for r in rows}
    check(f"table {season} {stage}", got, {t: {k: v for k, v in rec.items() if v} for t, rec in want.items()})

for season, want in EXPECTED["topRuns"].items():
    rows = invoke("SeasonBatting", {"season": int(season), "limit": 3})
    check(f"top run-scorers {season}", [{"player": r["player"], "value": r["runs"]} for r in rows], want)
for season, want in EXPECTED["topWickets"].items():
    rows = invoke("SeasonBowling", {"season": int(season), "limit": 3})
    check(f"top wicket-takers {season}", [{"player": r["player"], "value": r["wickets"]} for r in rows], want)

rows = invoke("HighestScores", {"season": 0, "limit": 1})
check("highest score", {"player": rows[0]["player"], "match": rows[0]["matchId"], "season": rows[0]["season"], "runs": rows[0]["runs"]}, EXPECTED["highestScore"])
rows = invoke("BestBowling", {"season": 0, "limit": 1})
check("best bowling", {"player": rows[0]["player"], "match": rows[0]["matchId"], "season": rows[0]["season"], "wickets": rows[0]["wickets"], "runs": rows[0]["runs"]}, EXPECTED["bestBowling"])

rows = invoke("HeadToHead", {"teamA": "Yorkshire", "teamB": "Lancashire"})
tally = {}
for m in rows:
    k = m["winner"] or m["result"]
    tally[k] = tally.get(k, 0) + 1
check("Yorkshire v Lancashire", tally, EXPECTED["yorksVLancs"])
rec = invoke("HeadToHeadRecord", {"teamA": "Yorkshire", "teamB": "Lancashire"})[0]
check("Yorkshire v Lancashire record view", {"Yorkshire": rec["teamAWon"], "Lancashire": rec["teamBWon"], "draw": rec["drawn"]}, EXPECTED["yorksVLancs"])

rows = invoke("MatchInnings", {"matchId": "947089"})
check("match 947089 innings", [[r["team"], r["runs"], r["wickets"], r["declared"], r["forfeited"]] for r in rows], EXPECTED["sampleMatch947089"])

# The same fact shown twice must match: a season's top scorer on the summary and on the leaders page.
a = invoke("SeasonBatting", {"season": 2025, "limit": 10})[0]
b = invoke("SeasonBatting", {"season": 2025, "stage": 0, "team": "", "minInnings": 5, "limit": 50})[0]
check("same top scorer on summary and leaders page", (a["playerId"], a["runs"]), (b["playerId"], b["runs"]))
c = invoke("PlayerBatting", {"playerId": a["playerId"]})
check("player page agrees with the season leaders", next(s["runs"] for s in c if s["season"] == 2025), a["runs"])

print(f"\n{failures} check(s) failed" if failures else "\nall reconciled")
sys.exit(1 if failures else 0)
