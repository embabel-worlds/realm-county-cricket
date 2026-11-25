/*
 * Runs EVERY view this realm ships against a LIVE appliance and fails on any the engine refuses,
 * any that returns no rows with its defaults, and any case below whose rows lack what they must.
 * A view that has never returned rows in front of you does not exist yet.
 *
 *   EMBABEL_USER=… EMBABEL_PASSWORD=… node tests/views.smoke.mjs            (APPLIANCE_URL defaults to localhost:11043)
 *
 * Every view here reads stored rows — no model, no external source — so the whole run is seconds
 * and anything over SLOW_MS (2000 by default: the app's first-paint budget) is flagged.
 * Exits non-zero if any check failed.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const base = process.env.APPLIANCE_URL ?? 'http://localhost:11043';
const user = process.env.EMBABEL_USER ?? process.env.APPLIANCE_USER;
const password = process.env.EMBABEL_PASSWORD ?? process.env.APPLIANCE_PASSWORD;
if (!user || !password) { console.error('Set EMBABEL_USER and EMBABEL_PASSWORD.'); process.exit(2); }
const SLOW_MS = Number(process.env.SLOW_MS ?? 2000);

/* [view, params, a pattern the rows must contain (null for "some rows")] */
const CASES = [
  ['CountyTable', { season: 2025, stage: 2 }, /Derbyshire|Glamorgan|Leicestershire/],
  ['CountyTable', { season: 2021, stage: 3 }, /played/],
  ['TeamSeasons', { team: 'Yorkshire' }, /"season":2014/],
  ['TeamResults', { team: 'Kent', season: 2024, limit: 50 }, /opponent/],
  ['HeadToHead', { teamA: 'Lancashire', teamB: 'Yorkshire' }, /Old Trafford|Headingley/],
  ['HeadToHeadRecord', { teamA: 'Lancashire', teamB: 'Yorkshire' }, /"teamBWon":4/],
  ['SeasonBatting', { season: 2025, stage: 1, minInnings: 10, limit: 10 }, /average/],
  ['SeasonBatting', { season: 2016, team: 'Durham', limit: 5 }, /Jennings|Stoneman|Borthwick/],
  ['SeasonBowling', { season: 2024, minWickets: 30, limit: 10 }, /economy/],
  ['SeasonBowling', { season: 2019, stage: 1, team: 'Essex', limit: 5 }, /Harmer/],
  ['SeasonBowling', { season: 2019, stage: 2, team: 'Essex', limit: 5 }, null, 'empty'],   // Essex were in Division 1 that year: an empty answer is the right one
  ['HighestScores', { season: 2023, limit: 5 }, /notOut/],
  ['HighestScores', { team: 'Somerset', limit: 5 }, /Somerset/],
  ['BestBowling', { season: 2022, limit: 5 }, /"wickets":[6-9]|"wickets":10/],
  ['PlayerSearch', { name: 'madsen' }, /Madsen/],
  ['PlayerBatting', { playerId: '86e0f3f0' }, /Derbyshire/],
  ['PlayerBowling', { playerId: '5b6d248a' }, /Essex/],
  ['PlayerInnings', { playerId: '86e0f3f0', limit: 20 }, /dismissal/],
  ['PlayerSpells', { playerId: '5b6d248a', limit: 20 }, /maidens/],
  ['MatchSummary', { matchId: '947089' }, /Gloucestershire/],
  ['MatchInnings', { matchId: '947089' }, /"declared":true/],
  ['MatchBatting', { matchId: '947089' }, /Roderick/],
  ['MatchBowling', { matchId: '947089' }, /Magoffin/],
];
/* Parameters that MUST yield nothing: the empty case has to be an empty rows array, loudly — never an error. */
const EMPTY_CASES = [
  ['CountyTable', { season: 2020, stage: 1 }],
  ['PlayerSearch', { name: 'zzzz-nobody' }],
  ['MatchSummary', { matchId: '0' }],
];

/*
 * Whether an engine answer is the whole truth. A source that failed under load, a capped page or a
 * refused hop leaves rows that look like an answer while the figure is short, and a check that reads
 * only the rows reports drift that is not the realm's. Query answers (/admin/kg/execute, /kg/ask)
 * carry `error`, `reason`, `run` and `warnings` as strings opening with the engine's code; a view
 * envelope carries `status`, `outcome` and `warnings` as {code, message}. short(d) is null when
 * whole, else the line to print in place of the figure: "REFUSED: <why>" or "PARTIAL <n>: <reason>".
 */
const SHORT_CODES = new Set(['PARTIAL_RESULT', 'PRODUCER_ERROR', 'NEEDS_FILTER', 'NEEDS_PRODUCER', 'FILTER_REJECTED',
  'UNPUSHED_FILTER', 'AMBIGUOUS_LABEL', 'INCOMPLETE_TRAVERSAL', 'INCOMPLETE_RANKING', 'INCOMPLETE_AGGREGATE',
  'INCOMPLETE_INPUT', 'MATERIALIZATION_FAILED', 'REDUCTION_FAILED', 'UNPARSEABLE_ANSWER', 'TERMS_UNAVAILABLE',
  'COMPUTE_FAILED', 'PROPERTY_NOT_STORED', 'FOLLOW_CAPPED', 'UNLINKED_CHILDREN', 'RESOLUTION_DROPPED',
  'AGENTIC_DEGRADED', 'SOURCE_UNANSWERED'])
const SHORT_REASONS = new Set(['UNBOUNDED', 'PARTIAL_NOT_MATCHED', 'UNPUSHED_FILTER', 'DISCONNECTED',
  'INTERNAL_ERROR', 'WRITE_IN_PROGRESS', 'KILLED', 'TOO_EXPENSIVE'])
const SHORT_PUBLIC = new Set(['PARTIAL', 'REDUCTION_FAILED', 'COMPUTE_FAILED', 'PROPERTY_NOT_STORED',
  'AGENTIC_DEGRADED', 'RATE_LIMITED', 'SOURCE_UNAVAILABLE', 'SOURCE_REJECTED', 'INVALID_FILTER',
  'UNPUSHED_FILTER', 'TOO_BROAD', 'FETCH_CAPPED', 'INDEX_UNAVAILABLE', 'ARGUMENT_REFUSED'])

function short(d, figure = null) {
  const tag = figure === null ? 'PARTIAL' : `PARTIAL ${figure}`
  if (!d || typeof d !== 'object') return `REFUSED: not an engine answer: ${String(d).slice(0, 160)}`
  if ('outcome' in d || 'status' in d) {
    if (d.status !== 'SUCCEEDED') {
      const e = d.error || {}
      return `REFUSED: ${d.status} ${`${e.code || ''} ${e.message || ''}`.trim().slice(0, 160)}`
    }
    const ws = (d.warnings || []).filter(w => w && SHORT_PUBLIC.has(w.code))
    if (!['OK', 'EMPTY'].includes(d.outcome) || ws.length) {
      return `${tag}: ${(ws.length ? `${ws[0].code}: ${ws[0].message || ''}` : `outcome ${d.outcome}`).slice(0, 200)}`
    }
    return null
  }
  if (d.error) return `REFUSED: ${String(d.error).slice(0, 160)}`
  if (d.run) return `${tag}: the run had not finished (${JSON.stringify(d.run)})`
  const ws = (d.warnings || []).filter(w => typeof w === 'string' && SHORT_CODES.has(w.split(':')[0].trim()))
  if (ws.length) return `${tag}: ${ws[0].slice(0, 200)}`
  if (SHORT_REASONS.has(d.reason)) return `${tag}: reason ${d.reason}`
  return null
}

const auth = 'Basic ' + Buffer.from(`${user}:${password}`).toString('base64');
async function invoke(name, args) {
  const started = Date.now();
  const res = await fetch(`${base}/api/v1/views/${encodeURIComponent(name)}/invoke`, {
    method: 'POST', headers: { Authorization: auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ args }),
  });
  const body = await res.json().catch(() => ({}));
  return { http: res.status, ms: Date.now() - started, body };
}

const viewsDir = new URL('../views/', import.meta.url).pathname;
const names = readdirSync(viewsDir).filter(f => f.endsWith('.yml')).sort()
  .flatMap(f => [...readFileSync(join(viewsDir, f), 'utf8').matchAll(/^- name:\s*(\S+)/gm)].map(m => m[1]));

let failures = 0;
const report = (ok, line) => { if (!ok) failures++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${line}`); };
/* A short answer is a problem whatever its rows hold: "must be empty" passes only on a whole empty. */
const problemOf = (http, body) => http !== 200
  ? `${http} ${body.status ?? ''} ${body.error?.message?.slice(0, 160) ?? ''}` : short(body, body.data?.length ?? 0);

console.log(`== every view, with its defaults (${names.length})`);
for (const name of names) {
  const { http, ms, body } = await invoke(name, {});
  const rows = body.data?.length ?? 0;
  const problem = problemOf(http, body) ?? (rows === 0 ? 'no rows with its defaults' : null);
  report(!problem, `${name.padEnd(18)} ${String(rows).padStart(4)} rows ${String(ms).padStart(6)}ms${ms > SLOW_MS ? ' SLOW' : ''}${problem ? '  ' + problem : ''}`);
}

console.log(`\n== cases (${CASES.length})`);
for (const [name, args, pattern, expectEmpty] of CASES) {
  const { http, ms, body } = await invoke(name, args);
  const rows = body.data ?? [];
  const text = JSON.stringify(rows);
  const problem = problemOf(http, body) ?? (expectEmpty ? (rows.length ? `${rows.length} rows where none were expected` : null) : rows.length === 0 ? 'no rows' : pattern && !pattern.test(text) ? `rows lack ${pattern}` : null);
  report(!problem, `${name.padEnd(18)} ${JSON.stringify(args).slice(0, 58).padEnd(58)} ${String(ms).padStart(6)}ms${ms > SLOW_MS ? ' SLOW' : ''}${problem ? '  ' + problem : ''}`);
}

console.log(`\n== must be empty (${EMPTY_CASES.length})`);
for (const [name, args] of EMPTY_CASES) {
  const { http, ms, body } = await invoke(name, args);
  const rows = body.data ?? [];
  const problem = problemOf(http, body) ?? (rows.length !== 0 ? `${rows.length} rows where none were expected` : null);
  report(!problem, `${name.padEnd(18)} ${JSON.stringify(args).padEnd(58)} ${String(ms).padStart(6)}ms${problem ? '  ' + problem : ''}`);
}

console.log(`\n== the ask lens (plain English in, rows and the generated query out)`);
{
  const started = Date.now();
  const res = await fetch(`${base}/api/v1/lenses/cricket-ask/invoke?waitSeconds=60`, {
    method: 'POST', headers: { Authorization: auth, 'Content-Type': 'application/json' },
    body: JSON.stringify({ args: { question: 'Who scored the most runs for Kent in 2023?' } }),
  });
  const body = await res.json().catch(() => ({}));
  let d = body.data; if (typeof d === 'string') { try { d = JSON.parse(d); } catch {} }
  const rows = (d && d.rows) || [];
  const problem = res.status !== 200 || body.status === 'FAILED' ? `${res.status} ${body.status ?? ''} ${body.error?.message?.slice(0, 160) ?? ''}`
    : short(body, rows.length)
    /* The lens passes kg.ask's own warnings and reason through: a short ask is short here too. */
    ?? (d && typeof d === 'object' ? short({ warnings: d.warnings, reason: d.reason }, rows.length) : null)
    ?? (!rows.length ? `no rows (${d && d.status})` : !(d && d.cypher) ? 'no generated cypher in the answer' : null);
  report(!problem, `cricket-ask          ${String(rows.length).padStart(4)} rows ${String(Date.now() - started).padStart(6)}ms${problem ? '  ' + problem : ''}`);
}

console.log(failures ? `\n${failures} check(s) failed` : '\nall passed');
process.exit(failures ? 1 : 0);
