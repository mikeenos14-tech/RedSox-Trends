// Pure display helpers from common.js, run in Node with a minimal browser stub:
//   node --test frontend/tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../common.js", import.meta.url), "utf8");

function loadCommon({ dark = false } = {}) {
  const context = vm.createContext({
    document: { addEventListener() {}, querySelector: () => null, getElementById: () => null, querySelectorAll: () => [] },
    matchMedia: () => ({ matches: dark }),
    fetch: () => Promise.reject(new Error("no network in tests")),
    setInterval: () => 0,
    location: { reload() {} },
    console,
  });
  vm.runInContext(source, context);
  return (expr) => vm.runInContext(expr, context);
}

const run = loadCommon();

test("fmtPct renders baseball rates from MLB strings and numbers", () => {
  // The header showed "(..537)" when a pre-formatted ".537" got a second dot.
  assert.equal(run(`fmtPct(".537")`), ".537");
  assert.equal(run(`fmtPct(0.52)`), ".520");
  assert.equal(run(`fmtPct("1.000")`), "1.000");
  assert.equal(run(`fmtPct(null)`), "-");
});

test("deltaCell formats deltas in the stat's own convention", () => {
  assert.match(run(`deltaCell(0.036, true, false, fmtRate)`), />\+\.036</);
  assert.match(run(`deltaCell(-0.05, true, false, fmtRate)`), />−\.050</);
  assert.match(run(`deltaCell(1.25, true, false, fmtEra)`), />\+1\.25</);
  assert.match(run(`deltaCell(0.1, true, true, fmtRate)`), /small sample/);
});

test("fmtPct1 shows percentages, not decimals", () => {
  assert.equal(run(`fmtPct1(0.11)`), "11.0%");
  assert.equal(run(`fmtPct1(0.252)`), "25.2%");
});

test("postseason labels", () => {
  assert.equal(run(`postseasonGameLabel({ abbreviation: "ALWC", game_number: 3, if_necessary: true })`), "ALWC Game 3 (if nec.)");
  const summary = (phase, status) =>
    run(`postseasonStandingText(${JSON.stringify({ phase, status, series: "AL Wild Card Series", abbreviation: "ALWC", opponent: "New York Yankees" })})`);
  assert.equal(summary("in_series", null), "ALWC vs. Yankees: Game 1 next");
  assert.equal(summary("in_series", "BOS leads 1-0"), "ALWC vs. Yankees: BOS leads 1-0");
  assert.equal(summary("eliminated", "NYY wins 2-1"), "Eliminated in the AL Wild Card Series (NYY wins 2-1)");
  assert.equal(summary("won_world_series", "BOS wins 4-2"), "World Series champions");
});

test("first pitch is shown in Eastern time", () => {
  assert.equal(run(`formatGameTime("2026-09-30T00:00:00Z", false)`), "8:00 PM ET");
  assert.equal(run(`formatGameTime("2026-09-30T00:00:00Z", true)`), "TBD");
  assert.match(run(`formatGameTime("2026-09-30T00:00:00Z", false, { compact: true })`), /8:00 PM<span class="lg-only"> ET<\/span>/);
});

test("team and player names carry a phone-width short form", () => {
  assert.equal(run(`teamName(147, "New York Yankees")`), '<span class="tn-full">New York Yankees</span><span class="tn-abbr">NYY</span>');
  assert.equal(run(`teamName(999, "Unknown Team")`), "Unknown Team");
  assert.equal(run(`personName("Cam Schlittler")`), '<span class="pn-full">Cam Schlittler</span><span class="pn-short">Schlittler</span>');
  assert.equal(run(`Object.keys(TEAM_ABBR).length`), 30);
});

test("dark theme uses MLB's on-dark team logos", () => {
  assert.equal(run(`teamLogoUrl(147, false)`), "https://www.mlbstatic.com/team-logos/147.svg");
  assert.equal(run(`teamLogoUrl(147, true)`), "https://www.mlbstatic.com/team-logos/team-cap-on-dark/147.svg");
  assert.equal(loadCommon({ dark: true })(`teamLogoUrl(147)`), "https://www.mlbstatic.com/team-logos/team-cap-on-dark/147.svg");
});

test("short team names never split two-word nicknames", () => {
  assert.equal(run(`shortTeamName("Chicago White Sox", 145)`), "White Sox");
  assert.equal(run(`shortTeamName("Chicago White Sox")`), "White Sox");
  assert.equal(run(`shortTeamName("Toronto Blue Jays")`), "Blue Jays");
  assert.equal(run(`shortTeamName("New York Yankees", 147)`), "Yankees");
  assert.equal(run(`shortTeamName("Washington Senators")`), "Senators"); // historical
});

test("next game day is judged on the Eastern calendar", () => {
  // 11:30 PM ET on 9/28 is already 9/29 in UTC — still "Tomorrow" for 9/29.
  const lateNight = `new Date("2026-09-29T03:30:00Z")`;
  assert.equal(run(`relativeGameDay("2026-09-29", ${lateNight})`), "Tomorrow");
  assert.equal(run(`relativeGameDay("2026-09-28", ${lateNight})`), "Tonight");
  assert.equal(run(`relativeGameDay("2026-10-01", ${lateNight})`), "Thu, 10/1");
});

test("results-vs-expected phrasing treats small gaps as noise", () => {
  assert.equal(run(`luckPhrase(0.002)`), "right in line with");
  assert.equal(run(`luckPhrase(0.007)`), "slightly ahead of");
  assert.equal(run(`luckPhrase(-0.02)`), "well behind");
});

test("outside text is escaped before it becomes HTML", () => {
  assert.equal(run(`esc('<img src=x onerror="alert(1)"> & Sox\\'s')`), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; Sox&#39;s");
  assert.equal(run(`esc(null)`), "");
  assert.equal(run(`safeUrl("https://news.google.com/a?b=1&c=2")`), "https://news.google.com/a?b=1&amp;c=2");
  assert.equal(run(`safeUrl("javascript:alert(1)")`), "#");
});
