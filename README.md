# realm-county-cricket

The County Championship as a graph: every match Cricsheet records, ball by ball, reduced to
scorecards and stored in the world — each team innings, every batter's innings and every bowler's
spell, seasons 2014 to 2026 (no 2020), all 18 first-class counties. Keyless; nothing to configure.

| Type | Records | What it is |
|---|---|---|
| `CountyTeam` | 18 | A county, with its span and matches |
| `CricketPlayer` | 1,080 | A player by Cricsheet registry id, with the counties played for |
| `CountyMatch` | 1,483 | Teams, dates, venue, toss, result, margin, ESPNcricinfo link. `-[:TEAM]->CountyTeam` |
| `TeamInnings` | 5,220 | Total, wickets, overs, declared/forfeited, extras. `-[:IN_MATCH]->CountyMatch` |
| `BattingInnings` | 51,173 | One batter in one innings: runs, balls, 4s, 6s, how out. `-[:IN_MATCH]->`, `-[:BY]->CricketPlayer` |
| `BowlingInnings` | 29,542 | One bowler in one innings: overs, maidens, runs, wickets. `-[:IN_MATCH]->`, `-[:BY]->CricketPlayer` |

Nineteen views answer the questions people ask of it — `CountyTable`, `SeasonBatting`,
`SeasonBowling`, `TeamResults`, `HeadToHead`, `PlayerBatting`, `PlayerInnings`, `MatchBatting` and
the rest (`views/cricket.yml`) — and `apps/county-cricket.html` puts them on a page: season tables,
leaders with filters, every county's results and head-to-heads, player careers innings by innings,
records, and the full scorecard of any match.

## What it does not hold

- **Official championship points.** Bonus points depend on where the first 110 overs ended and
  over-rate deductions are applied by the umpires; neither is in the ball-by-ball record. Tables
  here rank by wins then draws and say so.
- 2020 (the Bob Willis Trophy), seasons before 2014, and the one-day and T20 competitions.
- Fielding aggregates, fall of wickets, partnerships, players' dates of birth.

## Conventions

A batter's balls faced exclude wides and include no balls. A bowler is credited with caught,
bowled, lbw, stumped, hit wicket and caught-and-bowled, and charged runs off the bat plus wides
and no balls; byes and leg byes are the keeper's. A maiden is a complete over by one bowler
conceding none of those. Retired hurt and retired not out are not dismissals. Averages divide runs
by dismissals (batting) or wickets (bowling); economy is runs per six legal balls.

## Rebuilding the reference data

```bash
pip install pyyaml
python3 scripts/build_reference.py       # downloads cch_json.zip into data/source/, writes reference/
python3 scripts/inject_how_it_works.py   # copies each view's Cypher into the app's How-it-works page
```

The first load of the realm seeds about 88,500 records, which takes a while (around two hours on a
laptop appliance); `realm_status` reports each type `seeding` until it is written, and views over
a type still seeding carry a `SEEDING` warning. Later loads skip the seed while the reference files
are unchanged.

## Tests

```bash
python3 tests/ground_truth.py > tests/expected.json       # L0: figures straight from the raw files
EMBABEL_USER=… EMBABEL_PASSWORD=… python3 tests/verify.py  # L1/L2: every view reconciled to those figures
EMBABEL_USER=… EMBABEL_PASSWORD=… node tests/views.smoke.mjs   # every view, defaults and varied params
npm install && npm run test:app                            # the app, headless, over captured envelopes
```

`tests/questions.yml` is the natural-language battery, including the questions the data cannot
answer, for the ask surface.

## Licence and attribution

The realm's own files are GPL-3.0. The match data is from [Cricsheet](https://cricsheet.org/)
under the ODC Attribution License (ODC-By); `reference/` is derived from it and carries the same
attribution. Match pages link to ESPNcricinfo, whose match ids Cricsheet shares.
