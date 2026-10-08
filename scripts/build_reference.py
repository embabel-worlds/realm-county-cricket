"""
Build the realm's reference data from Cricsheet's County Championship archive.

Cricsheet publishes every County Championship match since 2014 as a ball-by-ball JSON file
(https://cricsheet.org/downloads/cch_json.zip, ODC-By). This script downloads the archive once
into data/source/ (git-ignored), reduces each match to its scorecard, and writes reference/*.yml
in the `{type, data, relations}` shape the host seeds on world load.

What is computed, and the cricket conventions it follows:
  - A batter's balls faced exclude wides and include no balls. Boundaries are runs off the bat
    of exactly 4 or 6 unless Cricsheet flags them `non_boundary` (all run).
  - A bowler is credited with caught, bowled, lbw, stumped, hit wicket and caught-and-bowled;
    run outs, obstructing the field and handled the ball are not his. Runs conceded are runs off
    the bat plus wides and no balls; byes and leg byes are not charged. A maiden is a complete
    over bowled by one bowler conceding nothing.
  - Retired hurt and retired not out are not dismissals: the batter is not out and the team's
    wicket count does not move.
  - A forfeited innings has no deliveries and is stored as such.
  - Division is Cricsheet's `event.group`; 2021 was a conference season of three groups.

Run from the realm root:  python3 scripts/build_reference.py
"""
import io
import json
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"
REFERENCE = ROOT / "reference"
ARCHIVE = "https://cricsheet.org/downloads/cch_json.zip"

BOWLER_CREDIT = {"caught", "bowled", "lbw", "stumped", "hit wicket", "caught and bowled"}
NOT_A_DISMISSAL = {"retired hurt", "retired not out"}


def fetch() -> Path:
    SOURCE.mkdir(parents=True, exist_ok=True)
    target = SOURCE / "cch_json.zip"
    if not target.exists():
        print(f"downloading {ARCHIVE}")
        req = urllib.request.Request(ARCHIVE, headers={"User-Agent": "realm-county-cricket/0.1"})
        with urllib.request.urlopen(req) as r:
            target.write_bytes(r.read())
    return target


def y(v):
    """A YAML scalar. Strings go through JSON, which is valid YAML double-quoting."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(y(x) for x in v) + "]"
    return json.dumps(v, ensure_ascii=False)


class Changed:
    """Write-if-changed: an unchanged reference file keeps its bytes and mtime, so the host does not re-seed it."""
    def __init__(self, path):
        self.path, self.buf = Path(path), io.StringIO()
    def __enter__(self):
        return self.buf
    def __exit__(self, *exc):
        new = self.buf.getvalue()
        if not self.path.exists() or self.path.read_text() != new:
            self.path.write_text(new)
            print(f"  wrote {self.path.name}")


def record(out, type_, data, relations=()):
    out.write(f"- type: {type_}\n  data:\n")
    for k, v in data.items():
        if v is None:
            continue
        out.write(f"    {k}: {y(v)}\n")
    if relations:
        out.write("  relations:\n")
        for predicate, to_type, key, value in relations:
            out.write(f"  - predicate: {predicate}\n    to: {{ type: {to_type}, {key}: {y(value)} }}\n")


def overs_text(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def margin_text(by: dict) -> str:
    if "innings" in by:
        return f"an innings and {by.get('runs', 0)} runs"
    if "runs" in by:
        return f"{by['runs']} runs"
    if "wickets" in by:
        return f"{by['wickets']} wickets"
    return ""


def reduce_match(match_id: str, j: dict):
    info = j["info"]
    season = int(info["season"])
    event = info.get("event", {})
    stage = int(event.get("group") or 0)
    stage_name = f"Group {stage}" if season == 2021 else f"Division {stage}"
    teams = info["teams"]
    dates = info["dates"]
    outcome = info["outcome"]
    winner = outcome.get("winner")
    by = outcome.get("by", {})
    result = "won" if winner else outcome.get("result", "draw")
    toss = info.get("toss", {})
    registry = info["registry"]["people"]
    pid = lambda name: registry.get(name, name)

    match = {
        "matchId": match_id,
        "season": season,
        "stage": stage,
        "stageName": stage_name,
        "competition": event.get("name"),
        "startDate": dates[0],
        "endDate": dates[-1],
        "days": len(dates),
        "venue": info.get("venue"),
        "city": info.get("city"),
        "team1": teams[0],
        "team2": teams[1],
        "tossWinner": toss.get("winner"),
        "tossDecision": toss.get("decision"),
        "tossUncontested": bool(toss.get("uncontested", False)),
        "result": result,
        # A draw has no winner: stored as the empty string and zero margins rather than absent, so a
        # result set of draws does not read as "a property no source fills".
        "winner": winner or "",
        "loser": ((teams[1] if winner == teams[0] else teams[0]) if winner else ""),
        "margin": margin_text(by) if winner else ("tie" if result == "tie" else ""),
        "marginRuns": (by.get("runs") or 0) if winner else 0,
        "marginWickets": (by.get("wickets") or 0) if winner else 0,
        "byInnings": bool(winner and "innings" in by),
        "url": f"https://www.espncricinfo.com/ci/engine/match/{match_id}.html",
    }

    team_innings, batting, bowling = [], [], []
    for n, inn in enumerate(j["innings"], start=1):
        team = inn["team"]
        other = teams[1] if team == teams[0] else teams[0]
        base = dict(matchId=match_id, inningsNo=n, season=season, stage=stage,
                    date=dates[0], venue=info.get("venue"))
        if inn.get("forfeited"):
            team_innings.append(dict(key=f"{match_id}-{n}", matchId=match_id, inningsNo=n, season=season,
                                     team=team, bowlingTeam=other, runs=0, wickets=0, balls=0, overs="0.0",
                                     declared=False, forfeited=True, allOut=False, extras=0, byes=0,
                                     legbyes=0, wides=0, noballs=0, penalty=0))
            continue

        batters, order = {}, []
        bowlers, bowl_order = {}, []
        totals = dict(runs=0, wickets=0, balls=0, byes=0, legbyes=0, wides=0, noballs=0, penalty=0)

        def batter(name):
            if name not in batters:
                order.append(name)
                batters[name] = dict(position=len(order), runs=0, balls=0, fours=0, sixes=0,
                                     notOut=True, dismissal="not out", bowler=None, fielders=None)
            return batters[name]

        def bowler(name):
            if name not in bowlers:
                bowl_order.append(name)
                bowlers[name] = dict(bowlOrder=len(bowl_order), balls=0, maidens=0, runs=0, wickets=0,
                                     dots=0, fours=0, sixes=0, wides=0, noballs=0)
            return bowlers[name]

        for over in inn.get("overs", []):
            over_bowlers = set()
            over_balls = defaultdict(int)
            over_runs = defaultdict(int)
            for d in over["deliveries"]:
                runs, ex = d["runs"], d.get("extras", {})
                wides, noballs = ex.get("wides", 0), ex.get("noballs", 0)
                byes, legbyes, pen = ex.get("byes", 0), ex.get("legbyes", 0), ex.get("penalty", 0)
                legal = wides == 0 and noballs == 0
                boundary = not runs.get("non_boundary", False)
                bat = batter(d["batter"])
                batter(d["non_striker"])
                bw = bowler(d["bowler"])
                over_bowlers.add(d["bowler"])

                totals["runs"] += runs["total"]
                totals["byes"] += byes
                totals["legbyes"] += legbyes
                totals["wides"] += wides
                totals["noballs"] += noballs
                totals["penalty"] += pen
                if legal:
                    totals["balls"] += 1
                    bw["balls"] += 1
                    over_balls[d["bowler"]] += 1

                if wides == 0:
                    bat["balls"] += 1
                bat["runs"] += runs["batter"]
                if runs["batter"] == 4 and boundary:
                    bat["fours"] += 1
                    bw["fours"] += 1
                if runs["batter"] == 6 and boundary:
                    bat["sixes"] += 1
                    bw["sixes"] += 1

                conceded = runs["batter"] + wides + noballs
                bw["runs"] += conceded
                bw["wides"] += wides
                bw["noballs"] += noballs
                over_runs[d["bowler"]] += conceded
                if runs["total"] == 0:
                    bw["dots"] += 1

                for w in d.get("wickets", []):
                    kind, out = w["kind"], w["player_out"]
                    b = batter(out)
                    fielders = ", ".join(f["name"] for f in w.get("fielders", []) if f.get("name")) or None
                    b["dismissal"] = kind
                    b["fielders"] = fielders
                    if kind in NOT_A_DISMISSAL:
                        continue
                    b["notOut"] = False
                    totals["wickets"] += 1
                    if kind in BOWLER_CREDIT:
                        bw["wickets"] += 1
                        b["bowler"] = d["bowler"]
            if len(over_bowlers) == 1:
                (who,) = over_bowlers
                if over_balls[who] == info.get("balls_per_over", 6) and over_runs[who] == 0:
                    bowlers[who]["maidens"] += 1

        penalty_post = sum((inn.get("penalty_runs") or {}).values()) if isinstance(inn.get("penalty_runs"), dict) else 0
        absent = len(inn.get("absent_hurt", []))
        team_innings.append(dict(
            key=f"{match_id}-{n}", matchId=match_id, inningsNo=n, season=season, team=team, bowlingTeam=other,
            runs=totals["runs"] + penalty_post, wickets=totals["wickets"], balls=totals["balls"],
            overs=overs_text(totals["balls"]), declared=bool(inn.get("declared", False)), forfeited=False,
            allOut=totals["wickets"] >= 10 - absent and totals["wickets"] > 0,
            extras=totals["byes"] + totals["legbyes"] + totals["wides"] + totals["noballs"] + totals["penalty"],
            byes=totals["byes"], legbyes=totals["legbyes"], wides=totals["wides"], noballs=totals["noballs"],
            penalty=totals["penalty"] + penalty_post,
        ))
        for name in order:
            b = batters[name]
            batting.append(dict(base, key=f"{match_id}-{n}-{b['position']}", team=team, opponent=other,
                                playerId=pid(name), player=name, **b))
        for name in bowl_order:
            bw = bowlers[name]
            bowling.append(dict(base, key=f"{match_id}-{n}-{pid(name)}", team=other, opponent=team,
                                playerId=pid(name), player=name, overs=overs_text(bw["balls"]), **bw))

    players = {pid(name): (name, team) for team, names in info["players"].items() for name in names}
    return match, team_innings, batting, bowling, players


def main():
    archive = fetch()
    z = zipfile.ZipFile(archive)
    files = sorted(n for n in z.namelist() if n.endswith(".json"))
    print(f"{len(files)} matches")

    matches, innings, batting, bowling = [], [], [], []
    teams = {}
    people = {}
    for name in files:
        match_id = name[:-5]
        m, ti, ba, bo, players = reduce_match(match_id, json.loads(z.read(name)))
        matches.append(m)
        innings.extend(ti)
        batting.extend(ba)
        bowling.extend(bo)
        for t in (m["team1"], m["team2"]):
            e = teams.setdefault(t, dict(name=t, firstSeason=m["season"], lastSeason=m["season"], matches=0))
            e["firstSeason"] = min(e["firstSeason"], m["season"])
            e["lastSeason"] = max(e["lastSeason"], m["season"])
            e["matches"] += 1
        for pid_, (pname, team) in players.items():
            p = people.setdefault(pid_, dict(playerId=pid_, name=pname, teams=[], firstSeason=m["season"],
                                             lastSeason=m["season"], matches=0, _latest=m["startDate"]))
            if team not in p["teams"]:
                p["teams"].append(team)
            p["firstSeason"] = min(p["firstSeason"], m["season"])
            if m["startDate"] >= p["_latest"]:
                p["_latest"], p["name"] = m["startDate"], pname
            p["lastSeason"] = max(p["lastSeason"], m["season"])
            p["matches"] += 1

    REFERENCE.mkdir(exist_ok=True)
    header = "# Generated by scripts/build_reference.py from Cricsheet's County Championship archive (ODC-By) — do not edit by hand.\n\n"

    with Changed(REFERENCE / "cricket-01-teams.yml") as out:
        out.write(header)
        for t in sorted(teams.values(), key=lambda t: t["name"]):
            record(out, "CountyTeam", t)
    with Changed(REFERENCE / "cricket-02-players.yml") as out:
        out.write(header)
        for p in sorted(people.values(), key=lambda p: p["playerId"]):
            record(out, "CricketPlayer", {k: v for k, v in p.items() if not k.startswith("_")})
    with Changed(REFERENCE / "cricket-03-matches.yml") as out:
        out.write(header)
        for m in sorted(matches, key=lambda m: (m["startDate"], m["matchId"])):
            record(out, "CountyMatch", m, [("TEAM", "CountyTeam", "name", m["team1"]),
                                           ("TEAM", "CountyTeam", "name", m["team2"])])
    with Changed(REFERENCE / "cricket-04-team-innings.yml") as out:
        out.write(header)
        for ti in innings:
            record(out, "TeamInnings", ti, [("IN_MATCH", "CountyMatch", "matchId", ti["matchId"])])
    for season in sorted({b["season"] for b in batting}):
        with Changed(REFERENCE / f"cricket-05-batting-{season}.yml") as out:
            out.write(header)
            for b in batting:
                if b["season"] == season:
                    record(out, "BattingInnings", b, [("IN_MATCH", "CountyMatch", "matchId", b["matchId"]),
                                                      ("BY", "CricketPlayer", "playerId", b["playerId"])])
        with Changed(REFERENCE / f"cricket-06-bowling-{season}.yml") as out:
            out.write(header)
            for b in bowling:
                if b["season"] == season:
                    record(out, "BowlingInnings", b, [("IN_MATCH", "CountyMatch", "matchId", b["matchId"]),
                                                      ("BY", "CricketPlayer", "playerId", b["playerId"])])

    print(f"teams {len(teams)}  players {len(people)}  matches {len(matches)}  team innings {len(innings)}  "
          f"batting innings {len(batting)}  bowling innings {len(bowling)}")


if __name__ == "__main__":
    sys.exit(main())
