/*
 * Capture the envelopes the app's own calls return from a LIVE appliance, as the browser harness's
 * fixtures (tests/fixtures/envelopes.json). Every key is `view:<name>:<sorted args JSON>` — the same
 * key the stub resolves — and every argument set below is one the app really sends (see the view()
 * calls in apps/county-cricket.html). Re-run whenever a view or the app's arguments change.
 *
 *   EMBABEL_USER=… EMBABEL_PASSWORD=… node tests/fixtures/capture.mjs
 */
import { writeFileSync } from 'node:fs';

const base = process.env.APPLIANCE_URL ?? 'http://localhost:11043';
const user = process.env.EMBABEL_USER ?? process.env.APPLIANCE_USER;
const password = process.env.EMBABEL_PASSWORD ?? process.env.APPLIANCE_PASSWORD;
if (!user || !password) { console.error('Set EMBABEL_USER and EMBABEL_PASSWORD.'); process.exit(2); }

export const CALLS = [
  ['CountySeasons', {}],
  ['CountyTeams', {}],
  ['CountyTable', { season: 2026, stage: 1 }],
  ['CountyTable', { season: 2026, stage: 2 }],
  ['SeasonBatting', { season: 2026, limit: 10 }],
  ['SeasonBatting', { season: 2026, stage: 0, team: '', minInnings: 5, limit: 50 }],
  ['SeasonBatting', { season: 2026, stage: 1, team: '', minInnings: 5, limit: 50 }],
  ['SeasonBatting', { season: 2026, stage: 0, team: 'Surrey', minInnings: 5, limit: 50 }],
  ['SeasonBowling', { season: 2026, limit: 10 }],
  ['SeasonBowling', { season: 2026, stage: 0, team: '', minWickets: 5, limit: 50 }],
  ['HighestScores', { season: 2026, limit: 8 }],
  ['HighestScores', { season: 0, limit: 25 }],
  ['BestBowling', { season: 0, limit: 25 }],
  ['TeamSeasons', { team: 'Surrey' }],
  ['TeamResults', { team: 'Surrey', season: 2026, limit: 50 }],
  ['HeadToHead', { teamA: 'Surrey', teamB: 'Kent' }],
  ['HeadToHeadRecord', { teamA: 'Surrey', teamB: 'Kent' }],
  ['PlayerSearch', { name: 'madsen' }],
  ['PlayerBatting', { playerId: '86e0f3f0' }],
  ['PlayerBowling', { playerId: '86e0f3f0' }],
  ['PlayerInnings', { playerId: '86e0f3f0' }],
  ['PlayerSpells', { playerId: '86e0f3f0' }],
  ['MatchSummary', { matchId: '947089' }],
  ['MatchInnings', { matchId: '947089' }],
  ['MatchBatting', { matchId: '947089' }],
  ['MatchBowling', { matchId: '947089' }],
];
const key = (name, args) => `view:${name}:${JSON.stringify(Object.fromEntries(Object.entries(args).sort()))}`;
const auth = 'Basic ' + Buffer.from(`${user}:${password}`).toString('base64');
const out = {};
for (const [name, args] of CALLS) {
  const res = await fetch(`${base}/api/v1/views/${encodeURIComponent(name)}/invoke`, {
    method: 'POST', headers: { Authorization: auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ args }),
  });
  const env = await res.json();
  if (res.status !== 200 || env.status !== 'SUCCEEDED') { console.error(`${name} ${JSON.stringify(args)}: ${res.status} ${env.status} ${env.error?.message ?? ''}`); process.exit(1); }
  out[key(name, args)] = env;
  console.log(`${key(name, args)}  ${env.data.length} rows`);
}
// the ask lens, through the lens endpoint, with the question the app's example chip sends
for (const question of ['Who scored the most runs for Kent in 2023?']) {
  const res = await fetch(`${base}/api/v1/lenses/cricket-ask/invoke?waitSeconds=60`, { method: 'POST', headers: { Authorization: auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ args: { question } }) });
  const env = await res.json();
  if (res.status !== 200 || env.status === 'FAILED') { console.error(`cricket-ask: ${res.status} ${env.status} ${env.error?.message ?? ''}`); process.exit(1); }
  out[`lens:cricket-ask:${JSON.stringify({ question })}`] = env;
  console.log(`lens:cricket-ask ${question}`);
}
writeFileSync(new URL('./envelopes.json', import.meta.url), JSON.stringify(out, null, 1));
console.log(`wrote ${Object.keys(out).length} envelopes`);
