let runDiffChart = null;

async function loadHeroHeadline() {
  const el = document.getElementById("hero-headline");
  if (!el) return;
  try {
    const res = await fetch("/api/team/hero-headline");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load headline");
    }
    const data = await res.json();
    el.textContent = data.headline;
  } catch (e) {
    el.textContent = "";
    el.style.display = "none";
  }
}

async function loadDivisionStandings() {
  const tbody = document.querySelector("#standings-table tbody");
  try {
    const res = await fetch("/api/team/division-standings");
    if (!res.ok) throw new Error("Failed to load standings");
    const data = await res.json();

    tbody.innerHTML = "";
    data.teams.forEach((t) => {
      const tr = document.createElement("tr");
      if (t.is_target) tr.className = "target-row";
      const streakCls = t.streak && t.streak.startsWith("W") ? "streak-w" : t.streak && t.streak.startsWith("L") ? "streak-l" : "";
      tr.innerHTML = `
        <td class="num">${t.division_rank}</td>
        <td class="name">${t.name}</td>
        <td class="num">${t.wins}</td>
        <td class="num">${t.losses}</td>
        <td class="num">${t.pct}</td>
        <td class="num">${t.games_back}</td>
        <td class="num ${streakCls}">${t.streak || "-"}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7">Couldn't load standings: ${e.message}</td></tr>`;
  }
}

async function loadWildcardStandings() {
  const tbody = document.querySelector("#wildcard-table tbody");
  try {
    const res = await fetch("/api/team/wildcard-standings");
    if (!res.ok) throw new Error("Failed to load Wild Card standings");
    const data = await res.json();

    tbody.innerHTML = "";
    data.teams.forEach((t, i) => {
      const tr = document.createElement("tr");
      const classes = [];
      if (t.is_target) classes.push("target-row");
      if (i === 3) classes.push("wc-cutoff");
      tr.className = classes.join(" ");
      const streakCls = t.streak && t.streak.startsWith("W") ? "streak-w" : t.streak && t.streak.startsWith("L") ? "streak-l" : "";
      const status = t.clinched ? '<span class="div-badge">CLINCH</span>' : "";
      tr.innerHTML = `
        <td class="num">${t.wildcard_rank}</td>
        <td class="name">${t.name}${status}</td>
        <td class="num">${t.wins}</td>
        <td class="num">${t.losses}</td>
        <td class="num">${t.pct}</td>
        <td class="num">${t.wildcard_games_back}</td>
        <td class="num">${t.elimination_number}</td>
        <td class="num ${streakCls}">${t.streak || "-"}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8">Couldn't load Wild Card standings: ${e.message}</td></tr>`;
  }
}

async function loadSeasonSeries() {
  const tbody = document.querySelector("#series-table tbody");
  try {
    const res = await fetch("/api/team/season-series");
    if (!res.ok) throw new Error("Failed to load season series");
    const data = await res.json();

    tbody.innerHTML = "";
    data.series.forEach((s) => {
      const tr = document.createElement("tr");
      const result = s.wins > s.losses ? "Winning" : s.wins < s.losses ? "Losing" : "Even";
      const resultCls = s.wins > s.losses ? "delta-up" : s.wins < s.losses ? "delta-down" : "";
      tr.innerHTML = `
        <td class="name">${s.opponent}</td>
        <td class="num">${s.wins}</td>
        <td class="num">${s.losses}</td>
        <td class="num ${resultCls}">${result}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4">Couldn't load season series: ${e.message}</td></tr>`;
  }
}

async function loadBullpen() {
  const tbody = document.querySelector("#bullpen-table tbody");
  try {
    const res = await fetch("/api/team/bullpen");
    if (!res.ok) throw new Error("Failed to load bullpen availability");
    const data = await res.json();

    tbody.innerHTML = "";
    if (!data.pitchers.length) {
      tbody.innerHTML = `<tr><td colspan="6">No relief appearances in the last 5 days.</td></tr>`;
      return;
    }
    data.pitchers.forEach((p) => {
      const tr = document.createElement("tr");
      const statusCls = p.likely_available ? "delta-up" : "delta-down";
      const statusText = p.likely_available ? "Likely available" : "Rest likely needed";
      tr.innerHTML = `
        <td class="name">${p.name}</td>
        <td>${formatGameDate(p.last_pitched)}</td>
        <td class="num">${p.days_rest}</td>
        <td>${p.last_outing}</td>
        <td class="num">${p.appearances_last_3_days}</td>
        <td class="num ${statusCls}">${statusText}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6">Couldn't load bullpen availability: ${e.message}</td></tr>`;
  }
}

function formatGameDate(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" });
}

async function loadUpcomingSchedule() {
  const cards = document.getElementById("upcoming-cards");
  const tbody = document.querySelector("#upcoming-table tbody");
  try {
    const res = await fetch("/api/team/upcoming-schedule");
    if (!res.ok) throw new Error("Failed to load upcoming schedule");
    const data = await res.json();
    const s = data.summary;

    cards.innerHTML = "";
    cards.append(
      card("Avg Opponent PCT", s.avg_opponent_pct != null ? fmtRate(s.avg_opponent_pct) : "-"),
      card("Home / Away", `${s.home_count} / ${s.away_count}`),
      card("Division Games", s.division_game_count)
    );

    tbody.innerHTML = "";
    if (!data.games.length) {
      tbody.innerHTML = `<tr><td colspan="7">No upcoming games scheduled.</td></tr>`;
      return;
    }
    data.games.forEach((g) => {
      const tr = document.createElement("tr");
      if (g.is_division_game) tr.className = "division-game";
      const rec = g.opponent_record;
      const recStr = rec && rec.wins != null ? `${rec.wins}-${rec.losses} (${rec.pct})` : "-";
      const divBadge = g.is_division_game ? `<span class="div-badge">DIV</span>` : "";
      const seriesStr = g.season_series ? `${g.season_series.wins}-${g.season_series.losses}` : "—";
      tr.innerHTML = `
        <td>${formatGameDate(g.date)}</td>
        <td class="name">${g.opponent}${divBadge}</td>
        <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
        <td class="num">${recStr}</td>
        <td class="num">${seriesStr}</td>
        <td>${g.us_probable_pitcher || "TBD"}</td>
        <td>${g.opponent_probable_pitcher || "TBD"}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7">Couldn't load schedule: ${e.message}</td></tr>`;
  }
}

function formatLongDate(dateStr) {
  if (!dateStr) return null;
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

async function loadOnThisDay() {
  const container = document.getElementById("on-this-day-body");
  try {
    const res = await fetch("/api/team/on-this-day");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load On This Day");
    }
    const data = await res.json();
    const g = data.game;

    if (!g) {
      container.innerHTML = `<p class="muted">No historical game found for today's date.</p>`;
      return;
    }

    const resultCls = g.won ? "win" : "loss";
    const resultWord = g.won ? "W" : "L";
    const oppShort = g.opponent.split(" ").pop();
    const matchup = g.home_or_away === "home" ? `Red Sox vs. ${oppShort}` : `Red Sox @ ${oppShort}`;

    const decisions = [
      g.winning_pitcher ? `<b>W:</b> ${g.winning_pitcher}` : null,
      g.losing_pitcher ? `<b>L:</b> ${g.losing_pitcher}` : null,
      g.save_pitcher ? `<b>SV:</b> ${g.save_pitcher}` : null,
    ]
      .filter(Boolean)
      .join(" &nbsp;&nbsp; ");

    container.innerHTML = `
      <div class="game-recap-header ${resultCls}">
        <div class="game-recap-result">${resultWord}</div>
        <div>
          <h3>${g.year} — ${matchup} &nbsp; ${g.our_score}-${g.their_score}</h3>
          <p class="muted small-note">${decisions}</p>
        </div>
      </div>
      <div class="performer-blocks">
        ${buildPerformerList("Red Sox", g.top_performers.us)}
        ${buildPerformerList(oppShort, g.top_performers.them)}
      </div>
      <div class="game-recap-narrative"><p>${g.blurb}</p></div>
    `;
  } catch (e) {
    container.innerHTML = `<p class="muted">Couldn't load On This Day: ${e.message}</p>`;
  }
}

async function loadPlayerHighlight() {
  const container = document.getElementById("highlight-body");
  try {
    const res = await fetch("/api/players/highlight");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load player highlight");
    }
    const p = await res.json();

    const facts = [
      p.position ? `<b>Pos:</b> ${p.position}` : null,
      p.bat_side || p.pitch_hand ? `<b>Bats/Throws:</b> ${(p.bat_side || "-")[0]}/${(p.pitch_hand || "-")[0]}` : null,
      p.height && p.weight ? `<b>Ht/Wt:</b> ${p.height}, ${p.weight} lb` : null,
      p.birthplace ? `<b>From:</b> ${p.birthplace}` : null,
      p.mlb_debut ? `<b>MLB Debut:</b> ${formatLongDate(p.mlb_debut)}` : null,
      p.drafted_by
        ? `<b>Drafted:</b> ${p.drafted_by}, ${p.draft_year}${p.draft_round ? ` (Rd ${p.draft_round}, Pick ${p.draft_pick_number})` : ""}`
        : p.draft_year
        ? `<b>Drafted:</b> ${p.draft_year}`
        : `<b>Signed:</b> International free agent`,
    ].filter(Boolean);

    const paragraphs = (p.narrative || "")
      .split(/\n\s*\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => `<p>${s}</p>`)
      .join("");

    container.innerHTML = `
      <div class="highlight-header">
        <img class="highlight-headshot" src="${p.headshot_url}" alt="${p.name}" onerror="this.style.display='none'" />
        <div>
          <h3 class="highlight-name">${p.name} ${p.jersey_number ? `<span class="jersey">#${p.jersey_number}</span>` : ""}</h3>
          <div class="highlight-facts">${facts.map((f) => `<span>${f}</span>`).join("")}</div>
        </div>
      </div>
      <div class="highlight-narrative">${paragraphs}</div>
    `;
  } catch (e) {
    container.innerHTML = `<p class="muted">Couldn't load today's player highlight: ${e.message}</p>`;
  }
}

function renderBulletText(container, text) {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.startsWith("- "))
    .map((l) => l.slice(2).trim());

  container.innerHTML = "";

  if (!lines.length) {
    container.textContent = text;
    return;
  }

  const ul = document.createElement("ul");
  ul.className = "bullet-list";
  lines.forEach((line) => {
    const li = document.createElement("li");
    const colonIdx = line.indexOf(":");
    if (colonIdx > -1 && colonIdx < 60) {
      const strong = document.createElement("strong");
      strong.textContent = line.slice(0, colonIdx + 1);
      li.appendChild(strong);
      li.appendChild(document.createTextNode(line.slice(colonIdx + 1)));
    } else {
      li.textContent = line;
    }
    ul.appendChild(li);
  });
  container.appendChild(ul);
}

async function loadSummary() {
  const res = await fetch("/api/team/summary");
  if (!res.ok) throw new Error("Failed to load summary");
  return res.json();
}

function card(label, value) {
  const el = document.createElement("div");
  el.className = "card";
  el.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
  return el;
}

function fmtPct(pct) {
  if (pct == null) return "-";
  return `.${String(pct).replace("0.", "").padEnd(3, "0")}`;
}

function renderRecordLine(data) {
  document.getElementById("record-line").textContent =
    `${data.record.wins}-${data.record.losses} (.${data.record.pct?.replace("0.", "")}) ` +
    `• ${data.games_back === "-" ? "1st in div" : data.games_back + " GB"} ` +
    `• WC: ${data.wildcard_games_back ?? "-"} ` +
    `• Streak: ${data.streak ?? "-"}`;
}

function renderOverviewCards(data) {
  const cards = document.getElementById("overview");
  cards.innerHTML = "";
  cards.append(
    card("Last 10", data.last_10 ? `${data.last_10.wins}-${data.last_10.losses}` : "-"),
    card("Home Record", data.home_record ? `${data.home_record.wins}-${data.home_record.losses}` : "-"),
    card("Away Record", data.away_record ? `${data.away_record.wins}-${data.away_record.losses}` : "-"),
    card("Run Differential", data.run_differential > 0 ? `+${data.run_differential}` : data.run_differential),
    card("Expected Record", data.expected_record ? `${data.expected_record.wins}-${data.expected_record.losses}` : "-"),
    card("Recent Form", data.recent_form ? data.recent_form.trending : "-")
  );
}

function renderGamesTable(games) {
  const tbody = document.querySelector("#games-table tbody");
  tbody.innerHTML = "";
  [...games].reverse().forEach((g) => {
    const tr = document.createElement("tr");
    tr.className = g.won ? "win" : "loss";
    const rec = g.record_after ? `${g.record_after.wins}-${g.record_after.losses}` : "-";
    tr.innerHTML = `
      <td>${g.date}</td>
      <td>${g.opponent}</td>
      <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
      <td>${g.our_score}-${g.their_score}</td>
      <td class="result">${g.won ? "W" : "L"}</td>
      <td>${rec}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAnalysis(analysis) {
  const cards = document.getElementById("analysis-cards");
  cards.innerHTML = "";
  cards.append(
    card("vs LHP", analysis.vs_lhp_record ? `${analysis.vs_lhp_record.wins}-${analysis.vs_lhp_record.losses}` : "-"),
    card("vs RHP", analysis.vs_rhp_record ? `${analysis.vs_rhp_record.wins}-${analysis.vs_rhp_record.losses}` : "-"),
    card("One-Run Games", analysis.one_run_record ? `${analysis.one_run_record.wins}-${analysis.one_run_record.losses}` : "-"),
    card("Extra Innings", analysis.extra_innings_record ? `${analysis.extra_innings_record.wins}-${analysis.extra_innings_record.losses}` : "-"),
    card(
      "Strength of Sched (L15)",
      analysis.strength_of_schedule ? fmtPct(analysis.strength_of_schedule.avg_opponent_win_pct) : "-"
    )
  );

  renderRunDiffChart(analysis.rolling_run_diff_series || []);
}

function renderRunDiffChart(series) {
  const ctx = document.getElementById("run-diff-chart");
  if (!ctx || typeof Chart === "undefined") return;

  // Doubleheaders produce two points on the same calendar date, which
  // collide as duplicate x-axis labels and make the line look broken.
  // Disambiguate the second+ game of a date with a "G2"/"G3" suffix.
  const seen = {};
  const labels = series.map((p) => {
    const short = p.date.slice(5);
    seen[p.date] = (seen[p.date] || 0) + 1;
    return seen[p.date] > 1 ? `${short} (G${seen[p.date]})` : short;
  });
  const values = series.map((p) => p.rolling_run_diff);

  if (runDiffChart) {
    runDiffChart.data.labels = labels;
    runDiffChart.data.datasets[0].data = values;
    runDiffChart.update();
    return;
  }

  runDiffChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Rolling 10-Game Run Differential",
          data: values,
          borderColor: "#bd3039",
          backgroundColor: "rgba(189, 48, 57, 0.12)",
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: true } },
      scales: {
        y: { title: { display: true, text: "Run Diff (last 10)" } },
        x: { ticks: { maxTicksLimit: 10 } },
      },
    },
  });
}

let leagueRunDiffChart = null;

function rankClass(rank, of) {
  if (rank == null || !of) return "";
  const pct = rank / of;
  if (pct <= 0.34) return "rank-good";
  if (pct <= 0.67) return "rank-mid";
  return "rank-bad";
}

function ordinal(n) {
  if (n == null) return "-";
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function rankCard(label, block, fmt) {
  const el = document.createElement("div");
  el.className = "card";
  if (!block || block.rank == null) {
    el.innerHTML = `<div class="label">${label}</div><div class="value">-</div>`;
    return el;
  }
  const cls = rankClass(block.rank, block.of);
  el.innerHTML = `
    <div class="label">${label}</div>
    <div class="value">${fmt(block.value)}</div>
    <div class="rank-line"><span class="rank-badge ${cls}">${ordinal(block.rank)} of ${block.of}</span>MLB avg: ${fmt(block.league_avg)}</div>
  `;
  return el;
}

const fmtInt = (v) => (v == null ? "-" : Math.round(v));
const fmtSignedInt = (v) => (v == null ? "-" : v > 0 ? `+${Math.round(v)}` : Math.round(v));
const fmtRate = (v) => (v == null ? "-" : v.toFixed(3).replace(/^0/, ""));
const fmtEra = (v) => (v == null ? "-" : v.toFixed(2));
const fmtPct1 = (v) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);

async function loadLeagueContext() {
  const cards = document.getElementById("league-cards");
  try {
    const res = await fetch("/api/team/league-context");
    if (!res.ok) throw new Error("Failed to load league context");
    const d = await res.json();

    cards.innerHTML = "";
    cards.append(
      rankCard("Run Differential", d.run_differential, fmtSignedInt),
      rankCard("Runs Scored", d.runs_scored, fmtInt),
      rankCard("Runs Allowed", d.runs_allowed, fmtInt),
      rankCard("Team wOBA", d.team_woba, fmtRate),
      rankCard("Team OPS", d.team_ops, fmtRate),
      rankCard("Walk Rate", d.team_bb_pct, fmtPct1),
      rankCard("Strikeout Rate", d.team_k_pct, fmtPct1),
      rankCard("Team ERA", d.team_era, fmtEra),
      rankCard("Team FIP", d.team_fip, fmtEra),
      rankCard("Pitching K-BB%", d.team_k_bb_pct, fmtPct1)
    );

    renderLeagueRunDiffChart(d.run_diff_league_chart || []);
  } catch (e) {
    cards.innerHTML = `<div class="card">Couldn't load league context: ${e.message}</div>`;
  }
}

function renderLeagueRunDiffChart(teams) {
  const ctx = document.getElementById("league-run-diff-chart");
  if (!ctx || typeof Chart === "undefined") return;

  const labels = teams.map((t) => t.team);
  const values = teams.map((t) => t.run_diff);
  const colors = teams.map((t) => (t.is_boston ? "#bd3039" : "rgba(150,150,150,0.45)"));

  if (leagueRunDiffChart) {
    leagueRunDiffChart.data.labels = labels;
    leagueRunDiffChart.data.datasets[0].data = values;
    leagueRunDiffChart.data.datasets[0].backgroundColor = colors;
    leagueRunDiffChart.update();
    return;
  }

  leagueRunDiffChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "Run Differential", data: values, backgroundColor: colors }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { display: false }, grid: { display: false } },
        y: { title: { display: true, text: "Run Differential" } },
      },
    },
  });
}

async function loadRecap() {
  const btn = document.getElementById("regenerate-btn");
  const textEl = document.getElementById("recap-text");
  btn.disabled = true;
  btn.textContent = "Generating…";
  textEl.textContent = "Generating a fresh recap…";
  try {
    const res = await fetch("/api/team/recap");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate recap");
    }
    const data = await res.json();
    textEl.textContent = data.recap;
  } catch (e) {
    textEl.textContent = `Couldn't generate a recap: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Regenerate";
  }
}

async function loadHeadlines() {
  const list = document.getElementById("headlines-list");
  try {
    const res = await fetch("/api/team/headlines");
    if (!res.ok) throw new Error("Failed to load headlines");
    const data = await res.json();

    list.innerHTML = "";
    if (!data.headlines.length) {
      list.innerHTML = '<li class="muted">No recent headlines found.</li>';
      return;
    }

    data.headlines.forEach((h) => {
      const li = document.createElement("li");
      const date = h.published ? new Date(h.published).toLocaleDateString() : "";
      li.innerHTML = `
        <a href="${h.link}" target="_blank" rel="noopener">${h.title}</a>
        <span class="meta">${[h.source, date].filter(Boolean).join(" • ")}</span>
      `;
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="muted">Couldn't load headlines: ${e.message}</li>`;
  }
}

async function loadHeadlinesSummary() {
  const btn = document.getElementById("headlines-summary-btn");
  const textEl = document.getElementById("headlines-summary-text");
  btn.disabled = true;
  btn.textContent = "Summarizing…";
  textEl.textContent = "Reading recent coverage…";
  try {
    const res = await fetch("/api/team/headlines/summary");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to summarize coverage");
    }
    const data = await res.json();
    renderBulletText(textEl, data.summary);
  } catch (e) {
    textEl.textContent = `Couldn't summarize coverage: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Summarize Coverage";
  }
}

async function loadAnalysisBriefing() {
  const btn = document.getElementById("analysis-btn");
  const textEl = document.getElementById("analysis-text");
  btn.disabled = true;
  btn.textContent = "Generating…";
  textEl.textContent = "Running the numbers…";
  try {
    const res = await fetch("/api/team/analysis");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate analysis");
    }
    const data = await res.json();
    textEl.textContent = data.analysis;
  } catch (e) {
    textEl.textContent = `Couldn't generate a briefing: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate Briefing";
  }
}

function pctStr(v) {
  if (v == null) return "-";
  return v.toFixed(3).replace(/^0/, "");
}

// Green = above league average (in the direction that's good for this stat),
// yellow = within the "roughly average" band, red = below league average.
// `band` is a relative tolerance (8% of the league-average value by default)
// treated as "at league average" rather than forcing everything into a
// binary above/below call.
function tierClass(v, leagueAvg, higherIsBetter, band = 0.08) {
  if (v == null || leagueAvg == null || leagueAvg === 0) return "";
  const relDiff = (v - leagueAvg) / Math.abs(leagueAvg);
  if (Math.abs(relDiff) <= band) return "heat-avg";
  const isAboveAvg = relDiff > 0;
  const isGood = higherIsBetter ? isAboveAvg : !isAboveAvg;
  return isGood ? "heat-good" : "heat-bad";
}

// BABIP and strand rate (LOB%) aren't skill stats where "above average" is
// good or bad — they're luck/sequencing indicators. A hitter with a very
// high BABIP isn't necessarily better, they're either hitting the ball hard
// or running hot; you can't tell which from BABIP alone. So these get a
// single amber "notably far from typical" flag instead of green/red.
function warnIfFar(v, target, tolerance) {
  if (v == null) return "";
  return Math.abs(v - target) > tolerance ? "heat-warn" : "";
}

let statBenchmarks = null;
async function loadStatBenchmarks() {
  try {
    const res = await fetch("/api/team/stat-benchmarks");
    if (res.ok) statBenchmarks = await res.json();
  } catch (e) {
    statBenchmarks = null;
  }
}

function deltaCell(delta, higherIsBetter, smallSample) {
  if (smallSample) return `<td class="num flag">small sample</td>`;
  if (delta == null) return `<td class="num">-</td>`;
  const good = higherIsBetter ? delta > 0 : delta > 0;
  const cls = delta === 0 ? "" : good ? "delta-up" : "delta-down";
  const sign = delta > 0 ? "+" : "";
  return `<td class="num ${cls}">${sign}${delta}</td>`;
}

async function loadPlayerHotCold() {
  const hittersBody = document.querySelector("#hitters-table tbody");
  const pitchersBody = document.querySelector("#pitchers-table tbody");
  try {
    if (!statBenchmarks) await loadStatBenchmarks();
    const b = statBenchmarks || {};

    const res = await fetch("/api/players/hot-cold");
    if (!res.ok) throw new Error("Failed to load player stats");
    const data = await res.json();

    hittersBody.innerHTML = "";
    data.hitters.forEach((h) => {
      const s = h.season;
      const r = h.recent;
      const tr = document.createElement("tr");
      const wobaCls = s ? tierClass(s.woba, b.woba, true) : "";
      const babipCls = s ? warnIfFar(s.babip, b.babip ?? 0.3, 0.03) : "";
      const bbCls = s ? tierClass(s.bb_pct, b.bb_pct, true) : "";
      const kCls = s ? tierClass(s.k_pct, b.k_pct, false) : "";
      const isoCls = s ? tierClass(s.iso, b.iso, true) : "";
      tr.innerHTML = `
        <td class="name">${h.name}</td>
        <td>${h.position || "-"}</td>
        <td class="num ${wobaCls}">${s ? pctStr(s.woba) : "-"}</td>
        <td class="num">${pctStr(r.woba)}</td>
        ${deltaCell(h.form_delta_woba, true, h.small_sample)}
        <td class="num ${babipCls}">${s ? pctStr(s.babip) : "-"}</td>
        <td class="num ${bbCls}">${s ? pctStr(s.bb_pct) : "-"}</td>
        <td class="num ${kCls}">${s ? pctStr(s.k_pct) : "-"}</td>
        <td class="num ${isoCls}">${s ? pctStr(s.iso) : "-"}</td>
        <td class="num">${s ? pctStr(s.avg) : "-"}</td>
        <td class="num">${s ? pctStr(s.ops) : "-"}</td>
        <td class="num">${s && s.hr != null ? s.hr : "-"}</td>
        <td class="num">${s && s.rbi != null ? s.rbi : "-"}</td>
      `;
      hittersBody.appendChild(tr);
    });

    pitchersBody.innerHTML = "";
    data.pitchers.forEach((p) => {
      const s = p.season;
      const r = p.recent;
      const tr = document.createElement("tr");
      const eraCls = s ? tierClass(s.era, b.era, false) : "";
      const fipCls = s ? tierClass(s.fip, b.fip, false) : "";
      const kbbCls = s ? tierClass(s.k_bb_pct, b.k_bb_pct, true) : "";
      const babipAgstCls = s ? warnIfFar(s.babip_against, b.babip ?? 0.3, 0.03) : "";
      const lobCls = s ? warnIfFar(s.lob_pct, b.lob_pct ?? 0.72, 0.08) : "";
      tr.innerHTML = `
        <td class="name">${p.name}</td>
        <td>${p.role}</td>
        <td class="num ${eraCls}">${s ? (s.era ?? "-") : "-"}</td>
        <td class="num">${r.era ?? "-"}</td>
        ${deltaCell(p.form_delta_era, true, p.small_sample)}
        <td class="num ${fipCls}">${s ? (s.fip ?? "-") : "-"}</td>
        <td class="num ${kbbCls}">${s ? pctStr(s.k_bb_pct) : "-"}</td>
        <td class="num ${babipAgstCls}">${s ? pctStr(s.babip_against) : "-"}</td>
        <td class="num ${lobCls}">${s ? pctStr(s.lob_pct) : "-"}</td>
      `;
      pitchersBody.appendChild(tr);
    });
  } catch (e) {
    hittersBody.innerHTML = `<tr><td colspan="13">Couldn't load: ${e.message}</td></tr>`;
  }
}

async function loadPlayerNotes() {
  const btn = document.getElementById("player-notes-btn");
  const textEl = document.getElementById("player-notes-text");
  btn.disabled = true;
  btn.textContent = "Generating…";
  textEl.textContent = "Reviewing player form data…";
  try {
    const res = await fetch("/api/players/notes");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate player notes");
    }
    const data = await res.json();
    renderBulletText(textEl, data.notes);
  } catch (e) {
    textEl.textContent = `Couldn't generate notes: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate Player Notes";
  }
}

function buildLineScoreTable(g) {
  const oppShort = g.opponent.split(" ").pop();
  const topLabel = g.home_or_away === "home" ? oppShort : "BOS";
  const bottomLabel = g.home_or_away === "home" ? "BOS" : oppShort;
  const topRuns = g.home_or_away === "home" ? g.line_score.totals.them : g.line_score.totals.us;
  const bottomRuns = g.home_or_away === "home" ? g.line_score.totals.us : g.line_score.totals.them;
  const innings = g.line_score.innings;

  const inningHeaders = innings.map((i) => `<th>${i.num}</th>`).join("");
  const topInnings = innings.map((i) => `<td>${g.home_or_away === "home" ? i.them : i.us}</td>`).join("");
  const bottomInnings = innings.map((i) => `<td>${g.home_or_away === "home" ? i.us : i.them}</td>`).join("");

  return `
    <div class="table-scroll">
      <table class="stat-table linescore-table">
        <thead>
          <tr><th>Team</th>${inningHeaders}<th>R</th><th>H</th><th>E</th></tr>
        </thead>
        <tbody>
          <tr>
            <td class="name">${topLabel}</td>${topInnings}
            <td class="num">${topRuns.runs}</td><td class="num">${topRuns.hits}</td><td class="num">${topRuns.errors}</td>
          </tr>
          <tr>
            <td class="name">${bottomLabel}</td>${bottomInnings}
            <td class="num">${bottomRuns.runs}</td><td class="num">${bottomRuns.hits}</td><td class="num">${bottomRuns.errors}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
}

function buildPerformerList(title, performers) {
  if (!performers.length) return "";
  const items = performers
    .map((p) => `<li><span class="name">${p.name}</span> — ${p.summary}</li>`)
    .join("");
  return `<div class="performer-block"><h4>${title}</h4><ul class="performer-list">${items}</ul></div>`;
}

async function loadLastGameRecap() {
  const container = document.getElementById("last-game-body");
  try {
    const res = await fetch("/api/team/last-game-recap");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load last game recap");
    }
    const data = await res.json();
    const g = data.game;

    if (!g) {
      container.innerHTML = `<p class="muted">No completed game found yet this season.</p>`;
      return;
    }

    const resultCls = g.won ? "win" : "loss";
    const resultWord = g.won ? "W" : "L";
    const oppShort = g.opponent.split(" ").pop();
    const matchup = g.home_or_away === "home" ? `Red Sox vs. ${oppShort}` : `Red Sox @ ${oppShort}`;
    const finalScore = `${g.our_score}-${g.their_score}`;

    const decisions = [
      g.winning_pitcher ? `<b>W:</b> ${g.winning_pitcher}` : null,
      g.losing_pitcher ? `<b>L:</b> ${g.losing_pitcher}` : null,
      g.save_pitcher ? `<b>SV:</b> ${g.save_pitcher}` : null,
    ]
      .filter(Boolean)
      .join(" &nbsp;&nbsp; ");

    const paragraphs = (g.narrative || "")
      .split(/\n\s*\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => `<p>${s}</p>`)
      .join("");

    container.innerHTML = `
      <div class="game-recap-header ${resultCls}">
        <div class="game-recap-result">${resultWord}</div>
        <div>
          <h3>${matchup} &nbsp; ${finalScore}</h3>
          <p class="muted small-note">${formatLongDate(g.date)} • ${g.venue || ""}</p>
        </div>
      </div>
      ${buildLineScoreTable(g)}
      <p class="muted small-note game-decisions">${decisions}</p>
      <div class="performer-blocks">
        ${buildPerformerList("Red Sox", g.top_performers.us)}
        ${buildPerformerList(oppShort, g.top_performers.them)}
      </div>
      <div class="chart-wrap">
        <canvas id="win-prob-chart" height="90"></canvas>
        <p class="muted small-note" id="win-prob-note">Loading win probability…</p>
      </div>
      <div class="game-recap-narrative">${paragraphs}</div>
    `;

    loadWinProbabilityChart();
  } catch (e) {
    container.innerHTML = `<p class="muted">Couldn't load the last game recap: ${e.message}</p>`;
  }
}

let winProbChart = null;

async function loadWinProbabilityChart() {
  const ctx = document.getElementById("win-prob-chart");
  const note = document.getElementById("win-prob-note");
  if (!ctx || typeof Chart === "undefined") return;

  try {
    const res = await fetch("/api/team/win-probability");
    if (!res.ok) throw new Error("Failed to load win probability");
    const data = await res.json();
    const g = data.game;
    if (!g) {
      note.textContent = "Win probability not available for this game.";
      return;
    }

    const labels = g.points.map((p) => `${p.half === "top" ? "T" : "B"}${p.inning}`);
    const values = g.points.map((p) => p.us_win_pct);
    const oppShort = g.opponent.split(" ").pop();

    if (winProbChart) winProbChart.destroy();
    winProbChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Red Sox Win Probability",
            data: values,
            borderColor: "#bd3039",
            backgroundColor: "rgba(189, 48, 57, 0.12)",
            fill: true,
            tension: 0.15,
            pointRadius: 0,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true } },
        scales: {
          y: { min: 0, max: 100, title: { display: true, text: "Win Probability %" } },
          x: { ticks: { maxTicksLimit: 12 } },
        },
      },
    });

    const swing = g.biggest_swing;
    note.textContent = swing
      ? `Biggest swing: ${swing.description} (${swing.swing.toFixed(1)} pt shift, ${swing.half === "top" ? "top" : "bottom"} ${swing.inning} vs. ${oppShort})`
      : "";
  } catch (e) {
    note.textContent = `Couldn't load win probability: ${e.message}`;
  }
}

function statcastMetricRow(label, stat) {
  return `
    <div class="statcast-metric">
      <div class="statcast-metric-label">
        <span>${label}</span>
        <span class="stat-value">${stat.value ?? "-"}</span>
      </div>
      <div class="statcast-bar">
        <div class="statcast-bar-marker" style="left: ${stat.percentile}%"></div>
      </div>
      <div class="statcast-percentile">${ordinal(stat.percentile)} percentile</div>
    </div>
  `;
}

function statcastCard(player) {
  const metrics = Object.entries(player.stats)
    .map(([label, stat]) => statcastMetricRow(label, stat))
    .join("");
  return `
    <div class="statcast-card">
      <div class="statcast-card-name">${player.name}</div>
      ${metrics}
    </div>
  `;
}

function statcastSnapshotCards(snapshot) {
  const cards = [];
  Object.entries(snapshot.hitters || {}).forEach(([label, pct]) => {
    cards.push(card(`${label} (Hitters)`, `${ordinal(pct)} pctl`));
  });
  Object.entries(snapshot.pitchers || {}).forEach(([label, pct]) => {
    cards.push(card(`${label} (Pitchers)`, `${ordinal(pct)} pctl`));
  });
  return cards;
}

function leaderboardBlock(label, entries) {
  const items = entries
    .map(
      (e) => `
      <li class="${e.is_red_sox ? "is-sox" : ""}">
        <span class="lb-name">${e.name}</span>
        <span class="lb-team">${e.team}</span>
        <span class="lb-value">${e.value}</span>
      </li>
    `
    )
    .join("");
  return `<div class="leaderboard"><h4>${label}</h4><ol>${items}</ol></div>`;
}

async function loadStatcast() {
  const snapshotEl = document.getElementById("statcast-snapshot");
  const hittersEl = document.getElementById("statcast-hitters-grid");
  const pitchersEl = document.getElementById("statcast-pitchers-grid");
  const leadersEl = document.getElementById("statcast-leaders");

  try {
    const res = await fetch("/api/players/statcast");
    if (!res.ok) throw new Error("Failed to load Statcast data");
    const data = await res.json();

    snapshotEl.innerHTML = "";
    snapshotEl.append(...statcastSnapshotCards(data.team_snapshot || {}));

    hittersEl.innerHTML = data.hitters.length
      ? data.hitters.map(statcastCard).join("")
      : '<p class="muted">Not enough Statcast-qualified hitters yet.</p>';

    pitchersEl.innerHTML = data.pitchers.length
      ? data.pitchers.map(statcastCard).join("")
      : '<p class="muted">Not enough Statcast-qualified pitchers yet.</p>';

    const leaderBlocks = [
      ...Object.entries(data.league_leaders.hitters || {}),
      ...Object.entries(data.league_leaders.pitchers || {}),
    ].map(([label, entries]) => leaderboardBlock(label, entries));
    leadersEl.innerHTML = leaderBlocks.join("");
  } catch (e) {
    hittersEl.innerHTML = `<p class="muted">Couldn't load Statcast data: ${e.message}</p>`;
  }
}

async function loadStatcastNotes() {
  const btn = document.getElementById("statcast-notes-btn");
  const textEl = document.getElementById("statcast-notes-text");
  btn.disabled = true;
  btn.textContent = "Generating…";
  textEl.textContent = "Digging through the batted-ball data…";
  try {
    const res = await fetch("/api/players/statcast-notes");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate scouting notes");
    }
    const data = await res.json();
    renderBulletText(textEl, data.notes);
  } catch (e) {
    textEl.textContent = `Couldn't generate scouting notes: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate Scouting Notes";
  }
}
