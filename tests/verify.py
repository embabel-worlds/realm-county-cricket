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

# Whether an engine answer is the whole truth. A source that failed under load, a capped page or a
# refused hop leaves the rows looking like an answer while the figure is short; reading the figure
# and ignoring the rest reports drift that is not the realm's. short(d) is None when the answer is
# whole, else what to print in place of the figure: "REFUSED: <why>" or "PARTIAL <n>: <reason>".
# Query answers carry `error`, `reason`, `run` and string `warnings` opening with the engine's code;
# a view envelope carries `status`, `outcome` and `warnings` as {code, message}.
# Raw warning codes that mean rows or values may be missing (the engine's incompleteness kinds).
# Cost notes (FILTERED_IN_GRAPH, AGGREGATE_NOT_PUSHED, EMPTY_NOT_KEPT, PUSHDOWN_VALUE_UNMATCHED),
# FILTER_STARVED (an honest empty), STALE_COPY, FIELDS_WITHHELD and UNKNOWN_VIA leave every row in place.
SHORT_CODES = (
    "PARTIAL_RESULT", "PRODUCER_ERROR", "NEEDS_FILTER", "NEEDS_PRODUCER", "FILTER_REJECTED",
    "UNPUSHED_FILTER", "AMBIGUOUS_LABEL", "INCOMPLETE_TRAVERSAL", "INCOMPLETE_RANKING",
    "INCOMPLETE_AGGREGATE", "INCOMPLETE_INPUT", "MATERIALIZATION_FAILED", "REDUCTION_FAILED",
    "UNPARSEABLE_ANSWER", "TERMS_UNAVAILABLE", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
    "FOLLOW_CAPPED", "UNLINKED_CHILDREN", "RESOLUTION_DROPPED", "AGENTIC_DEGRADED",
    "SOURCE_UNANSWERED",
)
# The typed `reason` a query result carries when it is not a clean answer and not an honest empty.
SHORT_REASONS = ("UNBOUNDED", "PARTIAL_NOT_MATCHED", "UNPUSHED_FILTER", "DISCONNECTED",
                 "INTERNAL_ERROR", "WRITE_IN_PROGRESS", "KILLED", "TOO_EXPENSIVE")
# Public warning codes on a view envelope that mean the same.
SHORT_PUBLIC = ("PARTIAL", "REDUCTION_FAILED", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
                "AGENTIC_DEGRADED", "RATE_LIMITED", "SOURCE_UNAVAILABLE", "SOURCE_REJECTED",
                "INVALID_FILTER", "UNPUSHED_FILTER", "TOO_BROAD", "FETCH_CAPPED",
                "INDEX_UNAVAILABLE", "ARGUMENT_REFUSED")


def short(d, figure=None):
    tag = "PARTIAL" if figure is None else "PARTIAL %s" % (figure,)
    if not isinstance(d, dict):
        return "REFUSED: not an engine answer: " + str(d)[:160]
    if "outcome" in d or "status" in d:  # a view envelope
        err = d.get("error") or {}
        if d.get("status") != "SUCCEEDED":
            return "REFUSED: %s %s" % (d.get("status"), (err.get("code", "") + " " + err.get("message", "")).strip()[:160] if isinstance(err, dict) else str(err)[:160])
        ws = [w for w in d.get("warnings") or [] if isinstance(w, dict) and w.get("code") in SHORT_PUBLIC]
        if d.get("outcome") not in ("OK", "EMPTY") or ws:
            why = ws[0]["code"] + ": " + ws[0].get("message", "") if ws else "outcome " + str(d.get("outcome"))
            return "%s: %s" % (tag, why[:200])
        return None
    if d.get("error"):
        return "REFUSED: " + str(d["error"])[:160]
    if d.get("run"):
        return "%s: the run had not finished (%s)" % (tag, d["run"])
    ws = [w for w in d.get("warnings") or [] if isinstance(w, str) and w.split(":", 1)[0].strip() in SHORT_CODES]
    if ws:
        return "%s: %s" % (tag, ws[0][:200])
    if d.get("reason") in SHORT_REASONS:
        return "%s: reason %s" % (tag, d["reason"])
    return None


def invoke(name, args):
    req = urllib.request.Request(f"{BASE}/api/v1/views/{name}/invoke", data=json.dumps({"args": args}).encode(),
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        env = json.load(r)
    # A short answer stops the run like a refusal does: its rows are not the figure to reconcile.
    s = short(env, len(env.get("data") or []))
    if s:
        raise RuntimeError(f"{name} {args}: {s}")
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

def top3(label, rows, column, want):
    """The view's top three must carry the ground truth's top three VALUES, and each named player's
    figure must equal the ground truth's figure for that player (ties may come back in either order)."""
    truth = {w["player"]: w["value"] for w in want}
    got = [(r["player"], r[column]) for r in rows]
    check(f"{label} values", [v for _, v in got], [w["value"] for w in want[:3]])
    check(f"{label} players", [(p, v) for p, v in got if truth.get(p) != v], [])

for season, want in EXPECTED["topRuns"].items():
    top3(f"top run-scorers {season}", invoke("SeasonBatting", {"season": int(season), "limit": 3}), "runs", want)
for season, want in EXPECTED["topWickets"].items():
    top3(f"top wicket-takers {season}", invoke("SeasonBowling", {"season": int(season), "limit": 3}), "wickets", want)

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
