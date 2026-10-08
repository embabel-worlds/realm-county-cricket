"""
Ground truth, computed INDEPENDENTLY of scripts/build_reference.py, straight from Cricsheet's
ball-by-ball files — the numbers every view is judged against (relentless-testing L0).

It deliberately does not import the builder: the same arithmetic written twice by one author is
not independent, so this is written the plain way — walk every delivery, add things up — and
prints a JSON map of expected figures. tests/verify.py compares the live views to it.

    python3 tests/ground_truth.py            # prints JSON to stdout
"""
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parent.parent / "data" / "source" / "cch_json.zip"
CREDITED = {"caught", "bowled", "lbw", "stumped", "hit wicket", "caught and bowled"}
RETIRED = {"retired hurt", "retired not out"}


def main():
    z = zipfile.ZipFile(ARCHIVE)
    files = [n for n in z.namelist() if n.endswith(".json")]
    matches_by_season = Counter()
    results = Counter()
    table = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))  # season -> stage -> team -> W/D/L
    runs_by = defaultdict(Counter)                            # season -> player -> runs
    inns_by = defaultdict(Counter)
    notout_by = defaultdict(Counter)
    hundreds_by = defaultdict(Counter)
    wkts_by = defaultdict(Counter)                            # season -> player -> wickets
    conceded_by = defaultdict(Counter)
    highest = (0, None)
    best = (0, 10**6, None)
    h2h = Counter()
    team_matches = Counter()
    sample = {}

    for n in files:
        j = json.loads(z.read(n))
        i = j["info"]
        season = int(i["season"])
        stage = int(i["event"].get("group") or 0)
        t1, t2 = i["teams"]
        matches_by_season[season] += 1
        team_matches[t1] += 1
        team_matches[t2] += 1
        w = i["outcome"].get("winner")
        res = "won" if w else i["outcome"].get("result")
        results[res] += 1
        for t in (t1, t2):
            tb = table[season][stage][t]
            tb["played"] += 1
            if w == t:
                tb["won"] += 1
            elif w:
                tb["lost"] += 1
            elif res == "draw":
                tb["drawn"] += 1
            else:
                tb["tied"] += 1
        if {t1, t2} == {"Yorkshire", "Lancashire"}:
            h2h[w or res] += 1

        mid = n[:-5]
        match_totals = []
        for inn in j["innings"]:
            total = 0
            wk = 0
            batted = {}
            faced = Counter()
            bowl_w = Counter()
            bowl_r = Counter()
            for ov in inn.get("overs", []):
                for d in ov["deliveries"]:
                    ex = d.get("extras", {})
                    total += d["runs"]["total"]
                    batted.setdefault(d["batter"], True)
                    batted.setdefault(d["non_striker"], True)
                    faced[d["batter"]] += d["runs"]["batter"]
                    bowl_r[d["bowler"]] += d["runs"]["batter"] + ex.get("wides", 0) + ex.get("noballs", 0)
                    for wic in d.get("wickets", []):
                        batted.setdefault(wic["player_out"], True)
                        if wic["kind"] in RETIRED:
                            continue
                        wk += 1
                        batted[wic["player_out"]] = False
                        if wic["kind"] in CREDITED:
                            bowl_w[d["bowler"]] += 1
            pr = inn.get("penalty_runs") or {}
            total += sum(pr.values()) if isinstance(pr, dict) else 0
            match_totals.append((inn["team"], total, wk, bool(inn.get("declared")), bool(inn.get("forfeited"))))
            for name, not_out in batted.items():
                r = faced.get(name, 0)
                runs_by[season][name] += r
                inns_by[season][name] += 1
                if not_out:
                    notout_by[season][name] += 1
                if r >= 100:
                    hundreds_by[season][name] += 1
                if r > highest[0]:
                    highest = (r, {"player": name, "match": mid, "season": season})
            for name, wv in bowl_w.items():
                wkts_by[season][name] += wv
            for name, rv in bowl_r.items():
                conceded_by[season][name] += rv
                wv = bowl_w.get(name, 0)
                if (wv, -rv) > (best[0], -best[1]):
                    best = (wv, rv, {"player": name, "match": mid, "season": season})
        if mid == "947089":
            sample[mid] = match_totals

    def top(counter, k=3):
        return [{"player": p, "value": v} for p, v in counter.most_common(k)]

    out = {
        "matches": len(files),
        "matchesBySeason": dict(sorted(matches_by_season.items())),
        "results": dict(results),
        "teams": len(team_matches),
        "teamMatches": dict(team_matches),
        "table": {f"{s}-{st}": dict(ts) for s, stages in table.items() for st, ts in stages.items()},
        # ten, not three: two players level on the third-place figure can legitimately come back in
        # either order, so verify.py checks the view's top three against these by value.
        "topRuns": {str(s): top(runs_by[s], 10) for s in runs_by},
        "topWickets": {str(s): top(wkts_by[s], 10) for s in wkts_by},
        "hundreds2025": top(hundreds_by[2025], 3),
        "highestScore": highest[1] | {"runs": highest[0]},
        "bestBowling": best[2] | {"wickets": best[0], "runs": best[1]},
        "yorksVLancs": dict(h2h),
        "sampleMatch947089": sample.get("947089"),
    }
    json.dump(out, sys.stdout, indent=1, default=lambda o: dict(o))


if __name__ == "__main__":
    main()
