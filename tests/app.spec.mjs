/*
 * The County Cricket page, driven headless against envelopes captured from live view runs
 * (tests/fixtures/envelopes.json — recapture with tests/fixtures/capture.mjs whenever a view or
 * the app's arguments change). No network: the appliance runtime is a stub that resolves each
 * call from the fixtures and THROWS on any call with no fixture, so a missing capture fails
 * rather than passing as "no rows". What runs is the page's own bytes from apps/.
 */
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const fixtures = JSON.parse(readFileSync(join(here, "fixtures/envelopes.json"), "utf8"));
const key = (name, args) => `view:${name}:${JSON.stringify(Object.fromEntries(Object.entries(args).sort()))}`;
const rowsOf = (name, args) => { const f = fixtures[key(name, args)]; if (!f) throw new Error("no fixture " + key(name, args)); return f.data; };
const LATEST = rowsOf("CountySeasons", {}).map(s => s.season).sort((a, b) => b - a)[0];

/* The runtime stub. `overrides` replaces envelopes; `delays` holds a call back, in ms. */
function stub(overrides = {}, delays = {}) {
  return `window.__calls = [];
  window.embabel = (() => {
    const fx = Object.assign(${JSON.stringify(fixtures)}, ${JSON.stringify(overrides)});
    const delays = ${JSON.stringify(delays)};
    const key = (kind, id, args) => kind + ':' + id + ':' + JSON.stringify(Object.fromEntries(Object.entries(args || {}).sort()));
    const invoke = (kind) => async (id, args) => {
      const k = key(kind, id, args);
      window.__calls.push(k);
      if (delays[k]) await new Promise((r) => setTimeout(r, delays[k]));
      const env = fx[k];
      if (!env) throw new Error('NO FIXTURE for ' + k);
      if (env.status === 'FAILED') throw Object.assign(new Error((env.error && env.error.message) || 'failed'), env.error);
      return env;
    };
    const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    return { views: { invoke: invoke('view') }, lenses: { invoke: invoke('lens') }, html: { escape: esc },
             manifest: { ready: Promise.resolve({ ok: true }), preflight: async () => ({ ok: true }) },
             progress: { subscribe: () => () => {}, label() {} }, cache: { invalidate() {}, clear() {} }, EmbabelError: Error };
  })();`;
}

async function open(page, hash = "", overrides = {}, delays = {}, routes = []) {
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.host === "cricket.test") {
      if (url.pathname.includes("/apps-runtime/")) {
        return route.fulfill({ contentType: url.pathname.endsWith(".css") ? "text/css" : "text/javascript", body: url.pathname.endsWith("embabel.js") ? stub(overrides, delays) : "" });
      }
      return route.fulfill({ path: join(root, "apps", url.pathname.replace("/apps/county-cricket/", "")) });
    }
    return route.abort();
  });
  for (const [pattern, handler] of routes) await page.route(pattern, handler);   /* registered last, so they win over the catch-all */
  await page.goto(`http://cricket.test/apps/county-cricket/county-cricket.html${hash}`);
  return errors;
}

test("the latest season renders its tables, leaders and highest scores from the fixtures", async ({ page }) => {
  const errors = await open(page);
  const t1 = rowsOf("CountyTable", { season: LATEST, stage: 1 }), t2 = rowsOf("CountyTable", { season: LATEST, stage: 2 });
  await expect(page.locator('[data-table="1"] [data-table-row]')).toHaveCount(t1.length);
  await expect(page.locator('[data-table="2"] [data-table-row]')).toHaveCount(t2.length);
  await expect(page.locator('[data-table="1"] [data-table-row]').first()).toContainText(t1[0].team);
  const bat = rowsOf("SeasonBatting", { season: LATEST, limit: 10 }), bowl = rowsOf("SeasonBowling", { season: LATEST, limit: 10 });
  await expect(page.locator("#topbat .hb")).toHaveCount(bat.length);
  await expect(page.locator("#topbowl .hb")).toHaveCount(bowl.length);
  if (bat.length) {
    await expect(page.locator("#topbat .hb").first()).toContainText(bat[0].player);
    await expect(page.locator("#stats .stat").nth(1)).toContainText(bat[0].runs.toLocaleString("en-GB"));
  }
  await expect(page.locator("#tophs [data-hs-row]")).toHaveCount(rowsOf("HighestScores", { season: LATEST, limit: 8 }).length);
  await expect(page.locator(`[data-season-pill="${LATEST}"]`)).toHaveClass(/on/);
  expect(errors).toEqual([]);
});

test("the Embabel badge is visible, attributed and linked; the how-it-works link reveals the page", async ({ page }) => {
  await open(page);
  const badge = page.locator("#embabel-badge");
  await expect(badge).toBeInViewport();
  await expect(badge).toContainText("Created with");
  await expect(badge.locator("a")).toHaveAttribute("href", /embabel\.com/);
  await page.click("#how-link");
  await expect(page.locator("#how-it-works")).toBeVisible();
  await expect(page.locator("#how-it-works [data-view]")).toHaveCount(20);
  await expect(page.locator("#how-it-works [data-lens]")).toHaveCount(1);
  await expect(page.locator("#main")).toBeHidden();
});

test("the batting leaders page lists every row, sorts on a heading, and refetches on a filter", async ({ page }) => {
  const errors = await open(page, `#/season/${LATEST}/batting`);
  const rows = rowsOf("SeasonBatting", { season: LATEST, stage: 0, team: "", minInnings: 5, limit: 50 });
  await expect(page.locator("[data-bat-row]")).toHaveCount(rows.length);
  if (rows.length > 1) {
    await page.click('th[data-sort="average"]');
    const best = rows.filter(r => r.average != null).sort((a, b) => b.average - a.average)[0];
    await expect(page.locator("[data-bat-row]").first()).toContainText(best.player);
    await page.click('th[data-sort="average"]');
    const worst = rows.filter(r => r.average != null).sort((a, b) => a.average - b.average)[0];
    await expect(page.locator("[data-bat-row]").first()).toContainText(worst.player);
  }
  await page.selectOption('[data-filter="stage"]', "1");
  const d1 = rowsOf("SeasonBatting", { season: LATEST, stage: 1, team: "", minInnings: 5, limit: 50 });
  await expect(page.locator("[data-bat-row]")).toHaveCount(d1.length);
  await page.selectOption('[data-filter="stage"]', "0");
  await page.selectOption('[data-filter="team"]', "Surrey");
  await expect(page.locator("[data-bat-row]")).toHaveCount(rowsOf("SeasonBatting", { season: LATEST, stage: 0, team: "Surrey", minInnings: 5, limit: 50 }).length);
  expect(errors).toEqual([]);
});

test("a county page shows its seasons, its results for the latest season, and a head-to-head on choice", async ({ page }) => {
  const errors = await open(page, "#/team/Surrey");
  await expect(page.locator("[data-team-season]")).toHaveCount(rowsOf("TeamSeasons", { team: "Surrey" }).length);
  const results = rowsOf("TeamResults", { team: "Surrey", season: LATEST, limit: 50 });
  await expect(page.locator("[data-result-row]")).toHaveCount(results.length);
  await expect(page.locator("[data-form] .chip")).toHaveCount(results.length);
  await page.selectOption("[data-h2h-select]", "Kent");
  await expect(page.locator("[data-h2h-row]")).toHaveCount(rowsOf("HeadToHead", { teamA: "Surrey", teamB: "Kent" }).length);
  await expect(page.locator("[data-h2h-record] .stat b").first()).toHaveText(String(rowsOf("HeadToHeadRecord", { teamA: "Surrey", teamB: "Kent" })[0].teamAWon));
  await page.click("[data-result-row]");
  await expect(page).toHaveURL(new RegExp(`#/match/${results[0].matchId}$`));
  expect(errors).toEqual([]);
});

test("player search finds people and a player page shows career, innings strip and spells", async ({ page }) => {
  const errors = await open(page, "#/players");
  await page.fill("[data-player-search]", "madsen");
  const hits = rowsOf("PlayerSearch", { name: "madsen" });
  await expect(page.locator("[data-player-hit]")).toHaveCount(hits.length);
  await page.click('[data-player-hit="86e0f3f0"]');
  const inns = rowsOf("PlayerInnings", { playerId: "86e0f3f0" });
  await expect(page.locator("[data-innings-strip] i")).toHaveCount(inns.length);
  await expect(page.locator("[data-innings-row]")).toHaveCount(inns.length);
  await expect(page.locator("[data-bat-season]")).toHaveCount(rowsOf("PlayerBatting", { playerId: "86e0f3f0" }).length);
  await expect(page.locator("[data-spell-row]")).toHaveCount(rowsOf("PlayerSpells", { playerId: "86e0f3f0" }).length);
  const total = rowsOf("PlayerBatting", { playerId: "86e0f3f0" }).reduce((a, s) => a + s.runs, 0);
  await expect(page.locator("#phead .stat").first()).toContainText(total.toLocaleString("en-GB"));
  expect(errors).toEqual([]);
});

test("a scorecard renders every innings, batter and bowler the fixtures hold", async ({ page }) => {
  const errors = await open(page, "#/match/947089");
  const inns = rowsOf("MatchInnings", { matchId: "947089" });
  await expect(page.locator("[data-scorecard-innings]")).toHaveCount(inns.length);
  await expect(page.locator("[data-bat-line]")).toHaveCount(rowsOf("MatchBatting", { matchId: "947089" }).length);
  await expect(page.locator("[data-bowl-line]")).toHaveCount(rowsOf("MatchBowling", { matchId: "947089" }).length);
  await expect(page.locator("[data-result]")).toContainText("Match drawn");
  await expect(page.locator('[data-innings-summary="3"] b')).toContainText("337-7 dec");
  expect(errors).toEqual([]);
});

test("the records page lists the highest scores and best bowling", async ({ page }) => {
  const errors = await open(page, "#/records");
  await expect(page.locator("[data-record-hs]")).toHaveCount(rowsOf("HighestScores", { season: 0, limit: 25 }).length);
  await expect(page.locator("[data-record-bb]")).toHaveCount(rowsOf("BestBowling", { season: 0, limit: 25 }).length);
  expect(errors).toEqual([]);
});

test("empty and failed answers are said out loud, never shown as blank", async ({ page }) => {
  const errors = await open(page, "", {
    [key("SeasonBatting", { season: LATEST, limit: 10 })]: { status: "SUCCEEDED", data: [], warnings: ["SEEDING: still being written"] },
    [key("CountyTable", { season: LATEST, stage: 2 })]: { status: "FAILED", error: { message: "engine refused the query" } },
  });
  await expect(page.locator('#topbat [data-state="empty"]')).toBeVisible();
  await expect(page.locator('#topbat [data-state="warning"]')).toContainText("SEEDING");
  await expect(page.locator('[data-table="2"] [data-state="error"]')).toContainText("engine refused");
  await expect(page.locator('[data-table="1"] [data-table-row]')).toHaveCount(rowsOf("CountyTable", { season: LATEST, stage: 1 }).length);
  expect(errors).toEqual([]);
});

test("an unknown player id and an unknown match are named, not blank", async ({ page }) => {
  await open(page, "#/player/nobody", {
    [key("PlayerBatting", { playerId: "nobody" })]: { status: "SUCCEEDED", data: [], warnings: [] },
    [key("PlayerBowling", { playerId: "nobody" })]: { status: "SUCCEEDED", data: [], warnings: [] },
    [key("PlayerInnings", { playerId: "nobody" })]: { status: "SUCCEEDED", data: [], warnings: [] },
    [key("PlayerSpells", { playerId: "nobody" })]: { status: "SUCCEEDED", data: [], warnings: [] },
  });
  await expect(page.locator('#phead [data-state="empty"]')).toContainText("nobody");
});

test("a tab switch during a slow call responds at once and the slow answer never paints the new page", async ({ page }) => {
  const errors = await open(page, "", {}, { [key("SeasonBowling", { season: LATEST, limit: 10 })]: 600 });
  await expect(page.locator("#topbowl [data-state='loading']")).toBeVisible();
  await page.click('[data-tab="teams"]');
  await expect(page.locator("[data-team-card]")).toHaveCount(rowsOf("CountyTeams", {}).length);
  await page.waitForTimeout(800);
  await expect(page.locator("[data-team-card]")).toHaveCount(rowsOf("CountyTeams", {}).length);
  await expect(page.locator("#topbowl")).toHaveCount(0);
  await page.click('[data-tab="summary"]');
  await expect(page.locator("#topbowl .hb")).toHaveCount(rowsOf("SeasonBowling", { season: LATEST, limit: 10 }).length);
  expect(errors).toEqual([]);
});

test("the Ask tab answers a question with rows and the query it wrote, and says when nothing matched", async ({ page }) => {
  const q = "Who scored the most runs for Kent in 2023?";
  const errors = await open(page, `#/ask/${encodeURIComponent(q)}`, {
    [`lens:cricket-ask:${JSON.stringify({ question: "nothing here" })}`]: { status: "SUCCEEDED", data: { kind: "cricket-ask", question: "nothing here", status: "EMPTY", warnings: [], rows: [], rowCount: 0, cypher: "MATCH (p:CricketPlayer) WHERE false RETURN p LIMIT 1", limits: [] } },
    [`lens:cricket-ask:${JSON.stringify({ question: "how many points did Surrey get" })}`]: { status: "SUCCEEDED", data: { kind: "cricket-ask", question: "how many points did Surrey get", status: "EMPTY", reason: "NOT_HELD", hint: "No championship points, bonus points or deductions are held in this realm (they are not in the ball-by-ball record), so a points question has no answer here. Tables are wins, draws and losses.", warnings: [], rows: [], rowCount: 0, cypher: null, limits: [] } },
  });
  const d = fixtures[`lens:cricket-ask:${JSON.stringify({ question: q })}`].data;
  await expect(page.locator("[data-ask-rows] tbody tr")).toHaveCount(d.rows.length);
  await expect(page.locator("[data-ask-rows]")).toContainText(d.rows[0].player);
  await expect(page.locator("[data-ask-cypher]")).toContainText("MATCH");
  await page.fill("[data-ask-input]", "nothing here");
  await page.click("[data-ask-go]");
  await expect(page.locator('#askout [data-state="empty"]')).toContainText("matched nothing");
  await page.fill("[data-ask-input]", "how many points did Surrey get");
  await page.click("[data-ask-go]");
  await expect(page.locator("#askout [data-not-held]")).toContainText("No championship points");
  expect(errors).toEqual([]);
});

test("the Twelfth Man answers through the agent endpoint, keeps the conversation, and says loudly when the agent is not there", async ({ page }) => {
  let calls = 0;
  const agent = async (route) => {
    const body = route.request().postDataJSON();
    calls++;
    if (calls === 1) return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { message: "agent twelfth-man is not signed" } }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "x", object: "chat.completion", created: 0, model: "twelfth-man",
      choices: [{ index: 0, message: { role: "assistant", content: `You sent ${body.messages.length} message(s) on ${body.embabel_conversation}.\n\n| Player | Runs |\n|---|---|\n| SA Northeast | 410 |` }, finish_reason: "stop" }],
      embabel: { calls: [{ name: "HighestScores" }] } }) });
  };
  const errors = await open(page, "#/ask", {}, {}, [["**/api/v1/agents/twelfth-man/v1/chat/completions", agent]]);
  await expect(page.locator("#chatcard")).toContainText("Twelfth Man");
  await page.fill("[data-chat-input]", "hello");
  await page.click("[data-chat-form] button");
  await expect(page.locator("[data-chat-error]")).toContainText("not signed");
  await page.fill("[data-chat-input]", "fun fact please");
  await page.click("[data-chat-form] button");
  await expect(page.locator("[data-chat-tm]")).toHaveCount(1);
  await expect(page.locator("[data-chat-tm] table")).toContainText("SA Northeast");
  await expect(page.locator("[data-chat-tm] .ev")).toContainText("HighestScores");
  await expect(page.locator("[data-chat-me]")).toHaveCount(2);
  await page.click('[data-tab="teams"]');
  await page.click('[data-tab="ask"]');
  await expect(page.locator("[data-chat-tm]")).toHaveCount(1);
  /* the browser logs the deliberate 404 as a failed resource; nothing else may be logged */
  expect(errors.filter(e => !/404/.test(e))).toEqual([]);
});
