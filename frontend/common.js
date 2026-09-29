let runDiffChart = null;

// iOS keeps a frozen snapshot of a home-screen-saved page when you switch
// away and back, and JS timers (like the live ticker's poll) get suspended
// in the background too — so returning after a while can show stale data
// even though a real reload would fetch fine. A full reload after a
// meaningful absence fixes both; anything shorter (a quick app-switch) is
// left alone so a normal glance-away doesn't cause a jarring reload.
(function watchForStaleReturn() {
  const STALE_AFTER_MS = 5 * 60 * 1000;
  let hiddenAt = null;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      hiddenAt = Date.now();
    } else if (hiddenAt && Date.now() - hiddenAt > STALE_AFTER_MS) {
      location.reload();
    }
  });
})();

// MLB publishes an on-dark variant of every cap logo; the standard navy
// marks (NYY, DET, TB, ...) are nearly invisible on the dark theme.
function teamLogoUrl(teamId, dark = matchMedia("(prefers-color-scheme: dark)").matches) {
  return dark
    ? `https://www.mlbstatic.com/team-logos/team-cap-on-dark/${teamId}.svg`
    : `https://www.mlbstatic.com/team-logos/${teamId}.svg`;
}

// `onDark`: for surfaces that are navy in both themes (the next-game card and
// the live ticker), where the standard marks vanish even in light mode.
function teamLogo(teamId, { onDark = false } = {}) {
  if (onDark) {
    return `<img class="team-logo-icon" src="${teamLogoUrl(teamId, true)}" alt="" onerror="this.style.display='none'" />`;
  }
  return `<picture><source srcset="${teamLogoUrl(teamId, true)}" media="(prefers-color-scheme: dark)" /><img class="team-logo-icon" src="${teamLogoUrl(teamId, false)}" alt="" onerror="this.style.display='none'" /></picture>`;
}

// player.html only serves the current 40-man Red Sox roster, so this only
// links when an id is actually available — falls back to plain text rather
// than pointing at a page that would 404.
function playerLink(id, name) {
  return id ? `<a href="/player.html?id=${id}" class="player-link">${name}</a>` : name;
}

// MLB's own abbreviations (statsapi /teams). On a phone, tables show these
// instead of full names — "New York Yankees" wrapping under its logo was
// doubling row heights and pushing every table past the screen edge.
const TEAM_ABBR = {
  108: "LAA", 109: "AZ", 110: "BAL", 111: "BOS", 112: "CHC", 113: "CIN", 114: "CLE", 115: "COL",
  116: "DET", 117: "HOU", 118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "ATH", 134: "PIT",
  135: "SD", 136: "SEA", 137: "SF", 138: "STL", 139: "TB", 140: "TEX", 141: "TOR", 142: "MIN",
  143: "PHI", 144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
};

// MLB's short team names (statsapi /teams "teamName").
const TEAM_SHORT = {
  108: "Angels", 109: "D-backs", 110: "Orioles", 111: "Red Sox", 112: "Cubs", 113: "Reds", 114: "Guardians",
  115: "Rockies", 116: "Tigers", 117: "Astros", 118: "Royals", 119: "Dodgers", 120: "Nationals", 121: "Mets",
  133: "Athletics", 134: "Pirates", 135: "Padres", 136: "Mariners", 137: "Giants", 138: "Cardinals", 139: "Rays",
  140: "Rangers", 141: "Blue Jays", 142: "Twins", 143: "Phillies", 144: "Braves", 145: "White Sox", 146: "Marlins",
  147: "Yankees", 158: "Brewers",
};

// "Yankees", "White Sox", "Blue Jays" — never the last word alone, which
// turned the White Sox into "Sox" ("Red Sox top the Sox"). Matches by id when
// the payload has one, else by the full name's ending; historical names
// ("Washington Senators") fall back to the nickname.
function shortTeamName(fullName, id) {
  if (id && TEAM_SHORT[id]) return TEAM_SHORT[id];
  const match = Object.values(TEAM_SHORT)
    .filter((short) => fullName.endsWith(short))
    .sort((a, b) => b.length - a.length)[0];
  if (match) return match;
  return fullName.split(" ").slice(/ (Sox|Jays)$/.test(fullName) ? -2 : -1).join(" ");
}

// Full name on desktop, abbreviation on phones (CSS swaps them).
function teamName(id, name) {
  const abbr = TEAM_ABBR[id];
  return abbr ? `<span class="tn-full">${name}</span><span class="tn-abbr">${abbr}</span>` : name;
}

function teamLink(id, name) {
  return id ? `<a href="/team.html?id=${id}" class="player-link">${teamName(id, name)}</a>` : name;
}

// "vs"/"@" shown inside the opponent cell only on phones, where the
// separate H/A column is hidden to save width.
function haInline(homeOrAway) {
  return `<span class="ha-inline">${homeOrAway === "home" ? "vs" : "@"}</span>`;
}

// Full name on desktop, last name on phones (for dense pitcher columns).
function personName(name) {
  if (!name) return name;
  const last = name.split(" ").slice(1).join(" ") || name;
  return `<span class="pn-full">${name}</span><span class="pn-short">${last}</span>`;
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
        <td class="name">${teamLogo(t.id)}${t.is_target ? teamName(t.id, t.name) : teamLink(t.id, t.name)}</td>
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
  const table = document.getElementById("wildcard-table");
  const tbody = table.querySelector("tbody");
  try {
    const res = await fetch("/api/team/wildcard-standings");
    if (!res.ok) throw new Error("Failed to load Wild Card standings");
    const data = await res.json();

    tbody.innerHTML = "";
    const rows = data.teams.map((t, i) => {
      const tr = document.createElement("tr");
      const classes = [];
      if (t.is_target) classes.push("target-row");
      if (i === 3) classes.push("wc-cutoff");
      tr.className = classes.join(" ");
      const streakCls = t.streak && t.streak.startsWith("W") ? "streak-w" : t.streak && t.streak.startsWith("L") ? "streak-l" : "";
      const status = t.clinched ? '<span class="div-badge">CLINCH</span>' : "";
      tr.innerHTML = `
        <td class="num">${t.wildcard_rank}</td>
        <td class="name">${teamLogo(t.id)}${t.is_target ? teamName(t.id, t.name) : teamLink(t.id, t.name)}${status}</td>
        <td class="num">${t.wins}</td>
        <td class="num">${t.losses}</td>
        <td class="num">${t.pct}</td>
        <td class="num">${t.wildcard_games_back}</td>
        <td class="num">${t.elimination_number}</td>
        <td class="num ${streakCls}">${t.streak || "-"}</td>
      `;
      tbody.appendChild(tr);
      return tr;
    });

    // Always show at least through the Red Sox's own row, even if they've
    // slid outside the top 6 — the whole point of this table is "where do
    // we stand," so their own line should never be the thing hidden.
    const WC_VISIBLE = 6;
    const targetIdx = data.teams.findIndex((t) => t.is_target);
    const visibleCount = targetIdx >= 0 ? Math.max(WC_VISIBLE, targetIdx + 1) : WC_VISIBLE;
    addShowMoreToggle(rows, table.closest(".table-scroll") || table, visibleCount, `Show ${rows.length - visibleCount} more teams`);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8">Couldn't load Wild Card standings: ${e.message}</td></tr>`;
  }
}

async function loadSeasonSeries() {
  const table = document.getElementById("series-table");
  const tbody = table.querySelector("tbody");
  try {
    const res = await fetch("/api/team/season-series");
    if (!res.ok) throw new Error("Failed to load season series");
    const data = await res.json();

    tbody.innerHTML = "";
    const rows = data.series.map((s) => {
      const tr = document.createElement("tr");
      const result = s.wins > s.losses ? "Winning" : s.wins < s.losses ? "Losing" : "Even";
      const resultCls = s.wins > s.losses ? "delta-up" : s.wins < s.losses ? "delta-down" : "";
      tr.innerHTML = `
        <td class="name">${teamLogo(s.opponent_id)}${teamLink(s.opponent_id, s.opponent)}</td>
        <td class="num">${s.wins}</td>
        <td class="num">${s.losses}</td>
        <td class="num ${resultCls}">${result}</td>
      `;
      tbody.appendChild(tr);
      return tr;
    });

    const SERIES_VISIBLE = 8;
    addShowMoreToggle(
      rows,
      table.closest(".table-scroll") || table,
      SERIES_VISIBLE,
      `Show ${rows.length - SERIES_VISIBLE} more opponents`
    );
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
      tbody.innerHTML = `<tr><td colspan="6">No games in the last 5 days.</td></tr>`;
      return;
    }
    const STATUS_CLASS = {
      "Used today": "delta-down",
      "Likely unavailable": "delta-down",
      Limited: "delta-warn",
      Available: "delta-up",
    };
    data.pitchers.forEach((p) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="name">${playerLink(p.player_id, p.name)}</td>
        <td class="nw">${p.last_pitched ? formatGameDate(p.last_pitched) : "5+ days ago"}</td>
        <td class="num">${p.days_rest ?? "5+"}</td>
        <td>${p.last_outing || "—"}</td>
        <td class="num">${p.appearances_last_3_days}${p.pitches_last_3_days ? ` <span class="muted">(${p.pitches_last_3_days}p)</span>` : ""}</td>
        <td class="num ${STATUS_CLASS[p.status] || ""}">${p.status}</td>
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

// First pitch in Eastern time — the team's home clock, and the one every
// Boston broadcast and ticket uses — with the zone stated so nobody has to
// guess.
// `compact` returns HTML whose " ET" suffix hides on phones (for dense
// table cells); otherwise plain text safe for textContent.
function formatGameTime(utcStr, tbd, { compact = false } = {}) {
  if (!utcStr || tbd) return "TBD";
  const time = new Date(utcStr).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
  return compact ? `${time}<span class="lg-only"> ET</span>` : `${time} ET`;
}

function shortGameDate(dateStr) {
  const [, m, d] = dateStr.split("-").map(Number);
  return `${m}/${d}`;
}

// "ALWC Game 1", "ALDS Game 5 (if nec.)" — the label MLB broadcasts use.
function postseasonGameLabel(ps) {
  if (!ps) return "";
  const game = ps.game_number ? ` Game ${ps.game_number}` : "";
  return `${ps.abbreviation || ps.series}${game}${ps.if_necessary ? " (if nec.)" : ""}`;
}

// One-line read on where Boston stands in October, from the backend's
// deterministic postseason summary (never inferred client-side).
function postseasonStandingText(p) {
  if (!p) return "";
  const vs = `vs. ${shortTeamName(p.opponent, p.opponent_id)}`;
  switch (p.phase) {
    case "eliminated":
      return `Eliminated in the ${p.series} (${p.status})`;
    case "won_world_series":
      return "World Series champions";
    case "awaiting_next_round":
      return `Won the ${p.series} (${p.status})`;
    default:
      return `${p.abbreviation} ${vs}: ${p.status || "Game 1 next"}`;
  }
}

// "Tonight" / "Tomorrow" / "Thu, 10/1", judged on the Eastern calendar (the
// team's, and the one game dates are listed in).
function relativeGameDay(dateStr, now = new Date()) {
  const eastern = (d) => d.toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  const today = eastern(now);
  const tomorrow = eastern(new Date(now.getTime() + 24 * 60 * 60 * 1000));
  if (dateStr === today) return "Tonight";
  if (dateStr === tomorrow) return "Tomorrow";
  return formatGameDate(dateStr);
}

function pitcherLineText(line) {
  if (!line || line.era == null) return "";
  return `${line.wins}-${line.losses}, ${line.era} ERA, ${line.strikeouts} K`;
}

// The first thing a fan wants on Home: who, when, and who's pitching. Built
// from the upcoming-schedule response the page already loads — no extra
// request. Hidden while a game is live (the live ticker takes its place).
function renderNextGame(data) {
  const section = document.getElementById("next-game");
  if (!section) return;
  const g = (data.games || [])[0];
  if (!g) {
    section.hidden = true;
    return;
  }

  const ps = g.postseason;
  const series = data.postseason;
  const opp = shortTeamName(g.opponent, g.opponent_id);
  const when = `${relativeGameDay(g.date)}, ${formatGameTime(g.game_date_utc, g.start_time_tbd)}`;
  document.getElementById("next-game-eyebrow").textContent = ps ? `${postseasonGameLabel(ps)} · ${when}` : `Next game · ${when}`;
  document.getElementById("next-game-status").textContent = ps ? (series && series.status) || "Series begins" : "";

  const rec = (r) => (r && r.wins != null ? `${r.wins}-${r.losses}` : "");
  const side = (logoId, name, record, isUs) => `
    <div class="next-game-team${isUs ? " is-us" : ""}">
      ${teamLogo(logoId, { onDark: true })}
      <span class="next-game-team-name">${name}</span>
      <span class="next-game-team-record">${record}</span>
    </div>`;
  const us = side(111, "Red Sox", rec(data.team_record), true);
  const them = side(g.opponent_id, opp, rec(g.opponent_record), false);
  const away = g.home_or_away === "away";
  document.getElementById("next-game-matchup").innerHTML =
    `${away ? us : them}<span class="next-game-at">@</span>${away ? them : us}`;

  const pitcher = (label, name, id, line, link) => `
    <div class="next-game-pitcher">
      <span class="next-game-pitcher-label">${label}</span>
      <span class="next-game-pitcher-name">${name ? (link ? playerLink(id, name) : name) : "TBD"}</span>
      <span class="next-game-pitcher-line">${pitcherLineText(line)}</span>
    </div>`;
  document.getElementById("next-game-pitchers").innerHTML =
    pitcher("Red Sox", g.us_probable_pitcher, g.us_probable_pitcher_id, g.us_probable_pitcher_line, true) +
    pitcher(opp, g.opponent_probable_pitcher, null, g.opponent_probable_pitcher_line, false);

  document.getElementById("next-game-meta").textContent = g.venue || "";
  section.hidden = false;
}

async function loadUpcomingSchedule() {
  const cards = document.getElementById("upcoming-cards");
  const tbody = document.querySelector("#upcoming-table tbody");
  try {
    const res = await fetch("/api/team/upcoming-schedule");
    if (!res.ok) throw new Error("Failed to load upcoming schedule");
    const data = await res.json();
    const s = data.summary;
    const p = data.postseason;
    renderNextGame(data);

    cards.innerHTML = "";
    if (p && p.phase === "in_series") {
      const next = p.next_game;
      cards.append(
        card("Series", `${p.abbreviation} vs. ${shortTeamName(p.opponent, p.opponent_id)}`),
        card("Series Status", p.status || "Not started"),
        card(
          "Next Game",
          next ? `Gm ${next.game_number} · ${formatGameDate(next.date)}, ${formatGameTime(next.game_date_utc)}` : "TBD"
        )
      );
    } else {
      cards.append(
        card("Avg Opponent PCT", s.avg_opponent_pct != null ? fmtRate(s.avg_opponent_pct) : "-"),
        card("Home / Away", `${s.home_count} / ${s.away_count}`),
        card("Division Games", s.division_game_count)
      );
    }

    tbody.innerHTML = "";
    // The division-games footnote only means something when there are
    // division games in the list (never in October).
    const divisionNote = document.getElementById("upcoming-division-note");
    if (divisionNote) divisionNote.style.display = s.division_game_count ? "" : "none";
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
      // Phones get a compact "Gm 3" — the cards above already name the series.
      const seriesStr = g.postseason
        ? `<span class="lg-only">${postseasonGameLabel(g.postseason)}</span>` +
          `<span class="sm-only"><span class="nw">Gm ${g.postseason.game_number}</span>${g.postseason.if_necessary ? "<br>if nec." : ""}</span>`
        : g.season_series
          ? `${g.season_series.wins}-${g.season_series.losses}`
          : "—";
      tr.innerHTML = `
        <td><span class="nw lg-only">${formatGameDate(g.date)}</span><span class="nw sm-only">${shortGameDate(g.date)}</span><span class="game-time">${formatGameTime(g.game_date_utc, g.start_time_tbd, { compact: true })}</span></td>
        <td class="name">${haInline(g.home_or_away)}${teamLogo(g.opponent_id)}${teamLink(g.opponent_id, g.opponent)}${divBadge}</td>
        <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
        <td class="num">${recStr}</td>
        <td class="${g.postseason ? "" : "num"}">${seriesStr}</td>
        <td>${g.us_probable_pitcher ? playerLink(g.us_probable_pitcher_id, personName(g.us_probable_pitcher)) : "TBD"}</td>
        <td>${g.opponent_probable_pitcher ? personName(g.opponent_probable_pitcher) : "TBD"}</td>
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
    const oppShort = shortTeamName(g.opponent, g.opponent_id);
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
          ${g.postseason_label ? `<p class="small-note on-this-day-series">${g.postseason_label}</p>` : ""}
          <p class="muted small-note">${decisions}</p>
        </div>
      </div>
      ${g.note ? `<p class="on-this-day-note">${g.note}</p>` : ""}
      <div class="performer-blocks">
        ${buildPerformerList("Red Sox", g.top_performers.us)}
        ${buildPerformerList(oppShort, g.top_performers.them)}
      </div>
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
          <h3 class="highlight-name">${playerLink(p.id, p.name)} ${p.jersey_number ? `<span class="jersey">#${p.jersey_number}</span>` : ""}</h3>
          <div class="highlight-facts">${facts.map((f) => `<span>${f}</span>`).join("")}</div>
        </div>
      </div>
      <div class="highlight-narrative"><div class="ai-badge">✨ AI-written</div>${paragraphs}</div>
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

// A card that expands a shared detail panel below the grid when clicked —
// clicking the same card again collapses it. `onExpand(cardEl)` is
// responsible for actually filling in the panel via toggleOverviewDetail.
function expandableCard(label, value, cardId, onExpand) {
  const el = document.createElement("div");
  el.className = "card card-clickable";
  el.dataset.cardId = cardId;
  el.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
  el.addEventListener("click", () => onExpand(el));
  return el;
}

function toggleOverviewDetail(cardEl, title, bodyHtml) {
  const detail = document.getElementById("overview-detail");
  if (!detail) return;
  const cards = document.getElementById("overview");
  const alreadyOpen = !detail.hidden && detail.dataset.openCard === cardEl.dataset.cardId;

  cards.querySelectorAll(".card-clickable").forEach((c) => c.classList.remove("card-active"));

  if (alreadyOpen) {
    detail.hidden = true;
    detail.dataset.openCard = "";
    return;
  }

  cardEl.classList.add("card-active");
  detail.innerHTML = `<h4>${title}</h4>${bodyHtml}`;
  detail.dataset.openCard = cardEl.dataset.cardId;
  detail.hidden = false;
}

function renderGameListDetail(games) {
  if (!games || !games.length) return '<p class="muted">No games to show.</p>';
  const rows = [...games]
    .reverse()
    .map((g) => {
      const cls = g.won ? "win" : "loss";
      return `
        <tr class="${cls}">
          <td class="nw">${formatGameDate(g.date)}</td>
          <td class="name">${haInline(g.home_or_away)}${teamLogo(g.opponent_id)}${teamLink(g.opponent_id, g.opponent)}</td>
          <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
          <td class="num">${g.our_score}-${g.their_score}</td>
          <td class="result">${g.won ? "W" : "L"}</td>
        </tr>
      `;
    })
    .join("");
  return `
    <div class="table-scroll">
      <table class="stat-table gamelist-table">
        <thead><tr><th>Date</th><th>Opp</th><th>H/A</th><th>Score</th><th>Result</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// Baseball-style rate: ".537", "1.000". Accepts MLB's own strings
// (".537", "1.000") as well as raw numbers (0.537).
function fmtPct(pct) {
  if (pct == null || pct === "") return "-";
  const n = Number(pct);
  if (Number.isNaN(n)) return String(pct);
  return n >= 1 ? n.toFixed(3) : n.toFixed(3).replace(/^0/, "");
}

function renderRecordLine(data) {
  const record = `${data.record.wins}-${data.record.losses} (${fmtPct(data.record.pct)})`;
  // Once October starts, games back / Wild Card cushion / regular-season
  // streak are frozen and meaningless — the series is the only standing
  // that matters.
  if (data.postseason) {
    document.getElementById("record-line").textContent = `${record} • ${postseasonStandingText(data.postseason)}`;
    return;
  }
  document.getElementById("record-line").textContent =
    `${record} ` +
    `• ${data.games_back === "-" ? "1st in div" : data.games_back + " GB"} ` +
    `• WC: ${data.wildcard_games_back ?? "-"} ` +
    `• Streak: ${data.streak ?? "-"}`;
}

function renderOverviewCards(data) {
  const cards = document.getElementById("overview");
  const detail = document.getElementById("overview-detail");
  cards.innerHTML = "";
  if (detail) {
    detail.hidden = true;
    detail.dataset.openCard = "";
  }

  const recentGames = data.recent_games || [];

  cards.append(
    expandableCard("Last 10", data.last_10 ? `${data.last_10.wins}-${data.last_10.losses}` : "-", "last10", (el) =>
      toggleOverviewDetail(el, "Last 10 Games", renderGameListDetail(recentGames.slice(-10)))
    ),
    card("Home Record", data.home_record ? `${data.home_record.wins}-${data.home_record.losses}` : "-"),
    card("Away Record", data.away_record ? `${data.away_record.wins}-${data.away_record.losses}` : "-"),
    card("Run Differential", data.run_differential > 0 ? `+${data.run_differential}` : data.run_differential),
    card("Expected Record", data.expected_record ? `${data.expected_record.wins}-${data.expected_record.losses}` : "-"),
    card("Recent Form", data.recent_form ? data.recent_form.trending : "-")
  );
}

// Games page: October results in their own table, above the regular
// season's Last 15 — never blended into it (the Record column there is the
// season record, which a postseason game doesn't have).
function renderPostseasonTable(postseason) {
  const section = document.getElementById("postseason-section");
  if (!section) return;
  if (!postseason || !postseason.games.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  document.getElementById("postseason-sub").textContent = postseasonStandingText(postseason);
  const tbody = section.querySelector("tbody");
  tbody.innerHTML = [...postseason.games]
    .reverse()
    .map(
      (g) => `
      <tr class="${g.won ? "win" : "loss"}">
        <td class="nw">${formatGameDate(g.date)}</td>
        <td>${postseasonGameLabel(g.postseason)}</td>
        <td class="name">${haInline(g.home_or_away)}${teamLogo(g.opponent_id)}${teamLink(g.opponent_id, g.opponent)}</td>
        <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
        <td>${g.our_score}-${g.their_score}</td>
        <td class="result">${g.won ? "W" : "L"}</td>
        <td>${g.postseason.status || "-"}</td>
      </tr>
    `
    )
    .join("");
}

function renderGamesTable(games) {
  const table = document.getElementById("games-table");
  const tbody = table.querySelector("tbody");
  tbody.innerHTML = "";
  const rows = [...games].reverse().map((g) => {
    const tr = document.createElement("tr");
    tr.className = g.won ? "win" : "loss";
    const rec = g.record_after ? `${g.record_after.wins}-${g.record_after.losses}` : "-";
    tr.innerHTML = `
      <td class="nw">${formatGameDate(g.date)}</td>
      <td class="name">${haInline(g.home_or_away)}${teamLogo(g.opponent_id)}${teamLink(g.opponent_id, g.opponent)}</td>
      <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
      <td>${g.our_score}-${g.their_score}</td>
      <td class="result">${g.won ? "W" : "L"}</td>
      <td>${rec}</td>
    `;
    tbody.appendChild(tr);
    return tr;
  });

  const GAMES_VISIBLE = 5;
  addShowMoreToggle(rows, table, GAMES_VISIBLE, `Show all ${rows.length} games`);
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

// Heat class for a 100-scale index (OPS+, ERA-, FIP-): 10+ points either
// side of average is clearly good or bad.
function indexClass(v, higherIsBetter) {
  if (v == null) return "";
  const diff = higherIsBetter ? v - 100 : 100 - v;
  return diff >= 10 ? "heat-good" : diff <= -10 ? "heat-bad" : "";
}
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
      rankCard("Team OPS+", d.team_ops_plus, fmtInt),
      rankCard("Walk Rate", d.team_bb_pct, fmtPct1),
      rankCard("Strikeout Rate", d.team_k_pct, fmtPct1),
      rankCard("Team ERA", d.team_era, fmtEra),
      rankCard("Team ERA-", d.team_era_minus, fmtInt),
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

function addAiBadge(el) {
  el.classList.remove("muted");
  el.insertAdjacentHTML("afterbegin", '<div class="ai-badge">✨ AI-written</div>');
}

async function loadHeadlines() {
  const list = document.getElementById("headlines-list");
  // A cached older page script can still call this on a page that no longer
  // has the list (headlines moved League -> Home); do nothing there.
  if (!list) return;
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
      const date = h.published
        ? new Date(h.published).toLocaleDateString(undefined, { month: "short", day: "numeric" })
        : "";
      li.innerHTML = `
        <a href="${h.link}" target="_blank" rel="noopener">${h.title}</a>
        <span class="meta">${[h.source, date].filter(Boolean).join(" • ")}</span>
      `;
      list.appendChild(li);
    });

    const HEADLINES_VISIBLE = 5;
    addShowMoreToggle(
      [...list.children],
      list,
      HEADLINES_VISIBLE,
      `Show ${data.headlines.length - HEADLINES_VISIBLE} more headlines`
    );
  } catch (e) {
    list.innerHTML = `<li class="muted">Couldn't load headlines: ${e.message}</li>`;
  }
}

async function loadAnalysisBriefing() {
  const textEl = document.getElementById("analysis-text");
  try {
    const res = await fetch("/api/team/analysis");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate analysis");
    }
    const data = await res.json();
    renderBulletText(textEl, data.analysis);
    addAiBadge(textEl);
  } catch (e) {
    textEl.textContent = `Couldn't generate a briefing: ${e.message}`;
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

// `fmt` formats the magnitude in the stat's own convention (".036" for
// wOBA, "1.25" for ERA) so a delta always reads like the stat it's a delta of.
function deltaCell(delta, higherIsBetter, smallSample, fmt, extraClass = "") {
  if (smallSample) return `<td class="num flag ${extraClass}">small sample</td>`;
  if (delta == null) return `<td class="num ${extraClass}">-</td>`;
  const good = higherIsBetter ? delta > 0 : delta < 0;
  const cls = delta === 0 ? "" : good ? "delta-up" : "delta-down";
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  return `<td class="num ${cls} ${extraClass}">${sign}${fmt(Math.abs(delta))}</td>`;
}

// A quick, plain-language read (🔥/🧊/steady) for the default "simple" view
// — the precise delta number lives behind "Show advanced stats" instead of
// being the only signal a casual visitor gets.
const HITTER_HOT_THRESHOLD = 0.025;
// Pitchers are judged on FIP change (see player_stats: ERA over 5 starts is
// mostly sequencing and defense).
const PITCHER_HOT_THRESHOLD = 0.5;

function formBadge(delta, smallSample, hotThreshold) {
  if (smallSample || delta == null) return `<td class="form-cell muted">–</td>`;
  if (delta >= hotThreshold) return `<td class="form-cell form-hot">🔥 Hot</td>`;
  if (delta <= -hotThreshold) return `<td class="form-cell form-cold">🧊 Cold</td>`;
  return `<td class="form-cell form-steady">Steady</td>`;
}

// The table is a "who's actually trending" list, not a full roster
// reference — a player sitting near zero delta isn't the point of it.
function isNotableForm(delta, smallSample, hotThreshold) {
  return !smallSample && delta != null && Math.abs(delta) >= hotThreshold;
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
    const notableHitters = data.hitters.filter((h) =>
      isNotableForm(h.form_delta_woba, h.small_sample, HITTER_HOT_THRESHOLD)
    );
    notableHitters.forEach((h) => {
      const s = h.season;
      const r = h.recent;
      const tr = document.createElement("tr");
      const wobaCls = s ? tierClass(s.woba, b.woba, true) : "";
      const babipCls = s ? warnIfFar(s.babip, b.babip ?? 0.3, 0.03) : "";
      const bbCls = s ? tierClass(s.bb_pct, b.bb_pct, true) : "";
      const kCls = s ? tierClass(s.k_pct, b.k_pct, false) : "";
      const isoCls = s ? tierClass(s.iso, b.iso, true) : "";
      tr.innerHTML = `
        <td class="name">${playerLink(h.id, h.name)}</td>
        <td>${h.position || "-"}</td>
        ${formBadge(h.form_delta_woba, h.small_sample, HITTER_HOT_THRESHOLD)}
        ${deltaCell(h.form_delta_woba, true, h.small_sample, fmtRate)}
        <td class="num">${s ? pctStr(s.avg) : "-"}</td>
        <td class="num">${s ? pctStr(s.ops) : "-"}</td>
        <td class="num">${s && s.hr != null ? s.hr : "-"}</td>
        <td class="num">${s && s.rbi != null ? s.rbi : "-"}</td>
        <td class="num adv-col ${wobaCls}">${s ? pctStr(s.woba) : "-"}</td>
        <td class="num adv-col">${pctStr(r.woba)}</td>
        <td class="num adv-col ${babipCls}">${s ? pctStr(s.babip) : "-"}</td>
        <td class="num adv-col ${bbCls}">${s ? fmtPct1(s.bb_pct) : "-"}</td>
        <td class="num adv-col ${kCls}">${s ? fmtPct1(s.k_pct) : "-"}</td>
        <td class="num adv-col ${isoCls}">${s ? pctStr(s.iso) : "-"}</td>
      `;
      hittersBody.appendChild(tr);
    });

    pitchersBody.innerHTML = "";
    const notablePitchers = data.pitchers.filter((p) =>
      isNotableForm(p.form_delta_fip, p.small_sample, PITCHER_HOT_THRESHOLD)
    );
    notablePitchers.forEach((p) => {
      const s = p.season;
      const r = p.recent;
      const tr = document.createElement("tr");
      const eraCls = s ? tierClass(s.era, b.era, false) : "";
      const fipCls = s ? tierClass(s.fip, b.fip, false) : "";
      const kbbCls = s ? tierClass(s.k_bb_pct, b.k_bb_pct, true) : "";
      const babipAgstCls = s ? warnIfFar(s.babip_against, b.babip ?? 0.3, 0.03) : "";
      const lobCls = s ? warnIfFar(s.lob_pct, b.lob_pct ?? 0.72, 0.08) : "";
      tr.innerHTML = `
        <td class="name">${playerLink(p.id, p.name)}</td>
        <td title="Recent form = ${p.window}">${p.role}</td>
        <td class="num ${fipCls}">${s ? (s.fip ?? "-") : "-"}</td>
        ${formBadge(p.form_delta_fip, p.small_sample, PITCHER_HOT_THRESHOLD)}
        ${deltaCell(p.form_delta_fip, true, p.small_sample, fmtEra)}
        <td class="num adv-col">${r.fip ?? "-"}</td>
        <td class="num adv-col ${eraCls}">${s ? (s.era ?? "-") : "-"}</td>
        <td class="num adv-col">${r.era ?? "-"}</td>
        <td class="num adv-col ${kbbCls}">${s ? fmtPct1(s.k_bb_pct) : "-"}</td>
        <td class="num adv-col ${babipAgstCls}">${s ? pctStr(s.babip_against) : "-"}</td>
        <td class="num adv-col ${lobCls}">${s ? fmtPct1(s.lob_pct) : "-"}</td>
      `;
      pitchersBody.appendChild(tr);
    });
  } catch (e) {
    hittersBody.innerHTML = `<tr><td colspan="14">Couldn't load: ${e.message}</td></tr>`;
  }
}

function sortTableByColumn(table, colIndex, th) {
  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const dir = th.dataset.sortDir === "asc" ? "desc" : "asc";

  table.querySelectorAll("thead th").forEach((h) => {
    h.dataset.sortDir = "";
    h.classList.remove("sort-asc", "sort-desc");
  });
  th.dataset.sortDir = dir;
  th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");

  const valueOf = (tr) => {
    const cell = tr.children[colIndex];
    const raw = cell ? cell.textContent.trim() : "";
    // Normalize the typographic minus used in delta cells so it sorts as negative.
    const num = parseFloat(raw.replace(/\u2212/g, "-").replace(/[%,]/g, ""));
    return raw && !Number.isNaN(num) ? num : raw.toLowerCase();
  };

  rows.sort((a, b) => {
    const va = valueOf(a);
    const vb = valueOf(b);
    const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
    return dir === "asc" ? cmp : -cmp;
  });

  rows.forEach((r) => tbody.appendChild(r));
}

// A drill-down page's "back" link is a fixed href by default (e.g. always
// "/players.html"), which loses the actual tab someone drilled in from —
// clicking a team from Games should return to Games, not always jump to
// League. When the visit genuinely came from elsewhere on this same site,
// history.back() returns to that exact page/scroll position; the href
// itself stays as a sane fallback for a direct link, bookmark, or new tab
// where there's no real "back" to go to.
function wireBackLink(selector) {
  const link = document.querySelector(selector);
  if (!link) return;
  const cameFromThisSite = document.referrer && new URL(document.referrer).origin === location.origin;
  if (!cameFromThisSite) return;
  link.addEventListener("click", (e) => {
    e.preventDefault();
    history.back();
  });
}

function initSortableTable(tableId) {
  const table = document.getElementById(tableId);
  if (!table || table.dataset.sortableInit) return;
  table.dataset.sortableInit = "1";
  table.querySelectorAll("thead th").forEach((th, idx) => {
    th.classList.add("sortable");
    th.addEventListener("click", () => sortTableByColumn(table, idx, th));
  });
}

// Generic Hitters/Pitchers-style tab switcher — a `.tab-group` wraps one
// `.tab-switcher` of `.tab-btn[data-tab]` buttons plus any number of
// `[data-tab-panel]` panels; clicking a button shows the matching panel and
// hides the rest. Works regardless of how deeply the panels are nested,
// since it queries within the group rather than assuming direct children.
function initTabGroup(groupId) {
  const group = document.getElementById(groupId);
  if (!group || group.dataset.tabInit) return;
  group.dataset.tabInit = "1";
  const buttons = group.querySelectorAll(".tab-btn");
  const panels = group.querySelectorAll("[data-tab-panel]");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      panels.forEach((p) => {
        p.hidden = p.dataset.tabPanel !== btn.dataset.tab;
      });
    });
  });
}

// Toggles a shared "show the dense sabermetric columns" mode: default view
// stays simple (traditional stats + a plain-language Form read), and the
// `.adv-col` columns (wOBA, BABIP, K%, FIP, etc.) only appear once asked
// for, rather than being busy by default.
function initAdvancedToggle(buttonId, groupId, showLabel, hideLabel) {
  const btn = document.getElementById(buttonId);
  const group = document.getElementById(groupId);
  if (!btn || !group || btn.dataset.advInit) return;
  btn.dataset.advInit = "1";
  btn.addEventListener("click", () => {
    const showing = group.classList.toggle("show-advanced");
    btn.textContent = showing ? hideLabel : showLabel;
  });
}

// Hides everything past `visibleCount` in `items` and appends a "Show N
// more" button after `anchorEl` that reveals the rest on click. No-op if
// there's nothing to hide.
function addShowMoreToggle(items, anchorEl, visibleCount, moreLabel) {
  if (items.length <= visibleCount) return;
  items.forEach((el, i) => {
    if (i >= visibleCount) el.hidden = true;
  });

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "show-more-btn";
  btn.textContent = moreLabel || `Show ${items.length - visibleCount} more`;
  btn.addEventListener("click", () => {
    items.forEach((el) => (el.hidden = false));
    btn.remove();
  });
  anchorEl.insertAdjacentElement("afterend", btn);
}

// Wires a <details class="expand-section"> so its <summary> label flips
// between show/hide text — purely cosmetic, the native element handles
// the actual expand/collapse.
function initExpandSection(detailsId, showLabel, hideLabel) {
  const details = document.getElementById(detailsId);
  if (!details || details.dataset.expandInit) return;
  details.dataset.expandInit = "1";
  const summary = details.querySelector("summary");
  details.addEventListener("toggle", () => {
    summary.textContent = details.open ? hideLabel : showLabel;
  });
}

// Short label for a player who isn't on the active roster, from MLB's own
// 40-man status code — injured and optioned are different things.
const ROSTER_STATUS_LABELS = { D7: "IL-7", D10: "IL-10", D15: "IL-15", D60: "IL-60", RM: "Minors", BRV: "Bereavement", PL: "Paternity" };
function rosterStatusBadge(player) {
  if (player.active) return "";
  const code = player.roster_status;
  const label = ROSTER_STATUS_LABELS[code] || "Inactive";
  const cls = code && code.startsWith("D") ? "il-badge" : "il-badge status-badge-minor";
  return ` <span class="${cls}">${label}</span>`;
}

async function loadFullRoster() {
  const hittersBody = document.querySelector("#roster-hitters-table tbody");
  const pitchersBody = document.querySelector("#roster-pitchers-table tbody");
  try {
    const res = await fetch("/api/players/full-roster");
    if (!res.ok) throw new Error("Failed to load the full roster");
    const data = await res.json();

    hittersBody.innerHTML = "";
    data.hitters.forEach((h) => {
      const s = h.season;
      const il = rosterStatusBadge(h);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="name">${playerLink(h.id, h.name)}${il}</td>
        <td>${h.position || "-"}</td>
        <td class="num">${pctStr(s.avg)}</td>
        <td class="num">${pctStr(s.ops)}</td>
        <td class="num ${indexClass(s.ops_plus, true)}">${fmtInt(s.ops_plus)}</td>
        <td class="num">${s.hr ?? "-"}</td>
        <td class="num">${s.rbi ?? "-"}</td>
        <td class="num">${fmtPct1(s.bb_pct)}</td>
        <td class="num">${fmtPct1(s.k_pct)}</td>
      `;
      hittersBody.appendChild(tr);
    });

    pitchersBody.innerHTML = "";
    data.pitchers.forEach((p) => {
      const s = p.season;
      const il = rosterStatusBadge(p);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="name">${playerLink(p.id, p.name)}${il}</td>
        <td>${p.role}</td>
        <td class="num">${s.era ?? "-"}</td>
        <td class="num ${indexClass(s.era_minus, false)}">${fmtInt(s.era_minus)}</td>
        <td class="num">${s.fip ?? "-"}</td>
        <td class="num ${indexClass(s.fip_minus, false)}">${fmtInt(s.fip_minus)}</td>
        <td class="num">${fmtPct1(s.k_bb_pct)}</td>
        <td class="num">${s.ip_display ?? "-"}</td>
      `;
      pitchersBody.appendChild(tr);
    });
  } catch (e) {
    hittersBody.innerHTML = `<tr><td colspan="8">Couldn't load the roster: ${e.message}</td></tr>`;
  }
}

async function loadPlayerNotes() {
  const textEl = document.getElementById("player-notes-text");
  try {
    const res = await fetch("/api/players/notes");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate player notes");
    }
    const data = await res.json();
    renderBulletText(textEl, data.notes);
    addAiBadge(textEl);
  } catch (e) {
    textEl.textContent = `Couldn't generate notes: ${e.message}`;
  }
}

function buildLineScoreTable(g) {
  const oppShort = shortTeamName(g.opponent, g.opponent_id);
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

function buildPerformerList(title, performers, isUs = false) {
  if (!performers.length) return "";
  const items = performers
    .map((p) => `<li><span class="name">${isUs ? playerLink(p.id, p.name) : p.name}</span> — ${p.summary}</li>`)
    .join("");
  return `<div class="performer-block"><h4>${title}</h4><ul class="performer-list">${items}</ul></div>`;
}

// Plain templated text from the same deterministic box-score facts as the
// recap below it — no AI call, so it costs nothing and can never drift from
// the actual score. Stays exactly the same until the next game finishes,
// since it's driven by the same game_pk-cached data the recap itself uses.
function renderResultBanner(g) {
  const banner = document.getElementById("result-banner");
  if (!banner || !g) return;

  const oppShort = shortTeamName(g.opponent, g.opponent_id);
  const winScore = Math.max(g.our_score, g.their_score);
  const loseScore = Math.min(g.our_score, g.their_score);

  banner.hidden = false;
  banner.className = `result-banner ${g.won ? "result-win" : "result-loss"}`;
  document.getElementById("result-banner-badge").textContent = g.won ? "W" : "L";
  const headline = g.won
    ? `Red Sox top the ${oppShort}, ${winScore}-${loseScore}`
    : `Red Sox fall to the ${oppShort}, ${winScore}-${loseScore}`;
  const ps = g.postseason;
  document.getElementById("result-banner-text").textContent = ps
    ? `${headline} · ${postseasonGameLabel(ps)}${ps.status ? ` · ${ps.status}` : ""}`
    : headline;
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

    renderResultBanner(g);

    if (!g) {
      container.innerHTML = `<p class="muted">No completed game found yet this season.</p>`;
      return;
    }

    const resultCls = g.won ? "win" : "loss";
    const resultWord = g.won ? "W" : "L";
    const oppShort = shortTeamName(g.opponent, g.opponent_id);
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
          <p class="muted small-note">${[
            formatLongDate(g.date),
            g.venue,
            g.postseason ? `${g.postseason.series}, Game ${g.postseason.game_number}` : null,
            g.postseason?.status,
          ]
            .filter(Boolean)
            .join(" • ")}</p>
        </div>
      </div>
      ${buildLineScoreTable(g)}
      <p class="muted small-note game-decisions">${decisions}</p>
      <div class="performer-blocks">
        ${buildPerformerList("Red Sox", g.top_performers.us, true)}
        ${buildPerformerList(oppShort, g.top_performers.them)}
      </div>
      <div class="chart-wrap">
        <div class="win-prob-canvas"><canvas id="win-prob-chart" aria-label="Red Sox win probability by play"></canvas></div>
        <p class="muted small-note" id="win-prob-note">Loading win probability…</p>
      </div>
      <div class="game-recap-narrative"><div class="ai-badge">✨ AI-written</div>${paragraphs}</div>
    `;

    loadWinProbabilityChart();
  } catch (e) {
    container.innerHTML = `<p class="muted">Couldn't load the last game recap: ${e.message}</p>`;
  }
}

async function loadGameSignificance() {
  const section = document.getElementById("significance");
  const body = document.getElementById("significance-body");
  if (!section) return;

  try {
    const res = await fetch("/api/team/last-game-significance");
    if (!res.ok) throw new Error("Failed to load game significance");
    const data = await res.json();

    // No real callouts this game (the common, correct case) — stay hidden
    // rather than show an empty section.
    if (!data.narration) {
      section.hidden = true;
      return;
    }

    renderBulletText(body, data.narration);
    addAiBadge(body);
    section.hidden = false;
  } catch (e) {
    section.hidden = true;
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
    const oppShort = shortTeamName(g.opponent, g.opponent_id);

    if (winProbChart) winProbChart.destroy();
    winProbChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Red Sox win probability",
            data: values,
            borderColor: "#bd3039",
            // Fill relative to the 50% line, so the shading itself shows
            // who was ahead.
            fill: { target: { value: 50 }, above: "rgba(189, 48, 57, 0.16)", below: "rgba(128, 128, 128, 0.14)" },
            tension: 0.15,
            // Scoring plays get a marker; everything else stays a line.
            pointRadius: g.points.map((p) => (p.is_scoring_play ? 3.5 : 0)),
            pointHoverRadius: g.points.map((p) => (p.is_scoring_play ? 5 : 3)),
            pointBackgroundColor: "#bd3039",
            borderWidth: 2,
          },
          {
            label: "Even",
            data: values.map(() => 50),
            borderColor: "rgba(128, 128, 128, 0.55)",
            borderDash: [4, 4],
            borderWidth: 1,
            pointRadius: 0,
            pointHoverRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: (item) => item.datasetIndex === 0,
            callbacks: {
              title: (items) => {
                const p = g.points[items[0].dataIndex];
                return `${p.half === "top" ? "Top" : "Bottom"} ${ordinal(p.inning)}`;
              },
              label: (item) => `Red Sox ${item.parsed.y.toFixed(0)}%`,
              afterLabel: (item) => {
                const p = g.points[item.dataIndex];
                return p.is_scoring_play && p.description ? p.description : "";
              },
            },
          },
        },
        scales: {
          y: { min: 0, max: 100, ticks: { stepSize: 25, callback: (v) => `${v}%` } },
          x: { ticks: { maxTicksLimit: 10, maxRotation: 0 } },
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
      <div class="statcast-card-name">${playerLink(player.player_id, player.name)}${player.pa ? `<span class="statcast-card-sample">${player.pa} PA</span>` : ""}</div>
      ${metrics}
    </div>
  `;
}

// One team-rank card: real rank among 30 clubs from Savant's team
// leaderboards (display strings come pre-formatted from the backend).
function teamStatcastCard(block) {
  const el = document.createElement("div");
  el.className = "card";
  el.innerHTML = `
    <div class="label">${block.label}</div>
    <div class="value">${block.display}</div>
    <div class="rank-line"><span class="rank-badge ${rankClass(block.rank, block.of)}">${ordinal(block.rank)} of ${block.of}</span>MLB avg: ${block.league_avg_display}</div>
  `;
  return el;
}

// Plain-English read of actual vs. expected wOBA. Deliberately descriptive,
// not a grade: results running ahead of contact quality is good news for
// hitters and bad news for pitchers, and small gaps are just noise.
function luckPhrase(diff) {
  const size = Math.abs(diff);
  if (size < 0.005) return "right in line with";
  return `${size >= 0.015 ? "well" : "slightly"} ${diff > 0 ? "ahead of" : "behind"}`;
}

function renderTeamStatcast(profile) {
  const fill = (id, blocks) => {
    const el = document.getElementById(id);
    el.innerHTML = "";
    Object.values(blocks || {}).forEach((b) => el.append(teamStatcastCard(b)));
    if (!el.children.length) el.innerHTML = '<p class="muted">Team Statcast data unavailable right now.</p>';
  };
  fill("team-statcast-hitting", profile.hitting);
  fill("team-statcast-pitching", profile.pitching);

  const h = profile.hitting_luck;
  const p = profile.pitching_luck;
  const luck = document.getElementById("team-statcast-luck");
  if (!h && !p) return;
  const signed = (d) => `${d > 0 ? "+" : d < 0 ? "−" : "±"}${fmtRate(Math.abs(d))}`;
  const parts = [];
  if (h) {
    parts.push(
      `<b>Hitters:</b> a ${fmtRate(h.woba)} wOBA against a ${fmtRate(h.xwoba)} xwOBA (${signed(h.diff)}), results ${luckPhrase(h.diff)} their contact quality.`
    );
  }
  if (p) {
    parts.push(
      `<b>Pitchers:</b> opponents have a ${fmtRate(p.woba)} wOBA against a ${fmtRate(p.xwoba)} xwOBA (${signed(p.diff)}), results ${luckPhrase(p.diff)} the contact allowed.`
    );
  }
  luck.innerHTML = `<span class="statcast-luck-label">Results vs. expected</span> ${parts.join(" ")}`;
  luck.hidden = false;
}

function leaderboardBlock(label, entries) {
  const items = entries
    .map(
      (e) => `
      <li class="${e.is_red_sox ? "is-sox" : ""}">
        <span class="lb-name">${e.is_red_sox ? playerLink(e.id, e.name) : e.name}</span>
        <span class="lb-team">${e.team}</span>
        <span class="lb-value">${e.value}</span>
      </li>
    `
    )
    .join("");
  return `<div class="leaderboard"><h4>${label}</h4><ol>${items}</ol></div>`;
}

let statcastLeagueLeaders = null;

function populateLeaderboardPicker(leagueLeaders, flagshipLabels) {
  const picker = document.getElementById("leaderboard-picker");
  if (!picker) return;

  picker.innerHTML = "";
  const groups = [
    ["Hitters", leagueLeaders.hitters || {}, flagshipLabels.hitters || []],
    ["Pitchers", leagueLeaders.pitchers || {}, flagshipLabels.pitchers || []],
  ];

  let firstValue = null;
  groups.forEach(([groupLabel, leaders, flagship]) => {
    const labels = Object.keys(leaders).filter((label) => !flagship.includes(label));
    if (!labels.length) return;
    const optgroup = document.createElement("optgroup");
    optgroup.label = groupLabel;
    labels.forEach((label) => {
      const opt = document.createElement("option");
      opt.value = `${groupLabel}::${label}`;
      opt.textContent = label;
      optgroup.appendChild(opt);
      if (!firstValue) firstValue = opt.value;
    });
    picker.appendChild(optgroup);
  });

  if (firstValue) {
    picker.value = firstValue;
    renderPickedLeaderboard(firstValue);
  }
}

function renderPickedLeaderboard(value) {
  const resultEl = document.getElementById("leaderboard-explorer-result");
  if (!resultEl || !value || !statcastLeagueLeaders) return;
  const [groupLabel, label] = value.split("::");
  const leaders = groupLabel === "Hitters" ? statcastLeagueLeaders.hitters : statcastLeagueLeaders.pitchers;
  resultEl.innerHTML = leaderboardBlock(label, (leaders || {})[label] || []);
}

document.getElementById("leaderboard-picker")?.addEventListener("change", (e) => {
  renderPickedLeaderboard(e.target.value);
});

async function loadStatcast() {
  const hittersEl = document.getElementById("statcast-hitters-grid");
  const pitchersEl = document.getElementById("statcast-pitchers-grid");
  const leadersEl = document.getElementById("statcast-leaders");

  try {
    const res = await fetch("/api/players/statcast");
    if (!res.ok) throw new Error("Failed to load Statcast data");
    const data = await res.json();

    if (data.team_profile) renderTeamStatcast(data.team_profile);

    hittersEl.innerHTML = data.hitters.length
      ? data.hitters.map(statcastCard).join("")
      : '<p class="muted">Not enough Statcast-qualified hitters yet.</p>';

    pitchersEl.innerHTML = data.pitchers.length
      ? data.pitchers.map(statcastCard).join("")
      : '<p class="muted">Not enough Statcast-qualified pitchers yet.</p>';

    const flagship = data.flagship_leader_labels || { hitters: [], pitchers: [] };
    const leaderBlocks = [
      ...Object.entries(data.league_leaders.hitters || {}).filter(([label]) => flagship.hitters.includes(label)),
      ...Object.entries(data.league_leaders.pitchers || {}).filter(([label]) => flagship.pitchers.includes(label)),
    ].map(([label, entries]) => leaderboardBlock(label, entries));
    leadersEl.innerHTML = leaderBlocks.join("");

    statcastLeagueLeaders = data.league_leaders;
    populateLeaderboardPicker(data.league_leaders, flagship);
  } catch (e) {
    hittersEl.innerHTML = `<p class="muted">Couldn't load Statcast data: ${e.message}</p>`;
  }
}

async function loadStatcastNotes() {
  const textEl = document.getElementById("statcast-notes-text");
  try {
    const res = await fetch("/api/players/statcast-notes");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate scouting notes");
    }
    const data = await res.json();
    renderBulletText(textEl, data.notes);
    addAiBadge(textEl);
  } catch (e) {
    textEl.textContent = `Couldn't generate scouting notes: ${e.message}`;
  }
}

let liveGamePollTimer = null;
const LIVE_GAME_POLL_MS = 15000;

async function loadLiveGame() {
  const section = document.getElementById("live-ticker");
  if (!section) return;

  try {
    const res = await fetch("/api/team/live-game");
    if (!res.ok) throw new Error("Failed to load live game");
    const data = await res.json();
    const g = data.game;

    document.getElementById("next-game")?.classList.toggle("is-live", !!g);
    if (!g) {
      section.hidden = true;
      return;
    }

    section.hidden = false;

    const oppShort = shortTeamName(g.opponent, g.opponent_id);
    const psPrefix = g.postseason ? `${postseasonGameLabel(g.postseason)} · ` : "";
    document.getElementById("live-inning-label").textContent =
      `${psPrefix}${g.inning_half === "top" ? "Top" : "Bot"} ${ordinal(g.inning)} — ${g.home_or_away === "home" ? "vs" : "@"} ${oppShort}`;

    document.getElementById("live-logo-them").src = teamLogoUrl(g.opponent_id, true);  // ticker is navy in both themes
    document.getElementById("live-name-them").textContent = oppShort;
    document.getElementById("live-score-them").textContent = g.them_score;
    document.getElementById("live-score-us").textContent = g.us_score;

    document.getElementById("base-first").classList.toggle("occupied", g.bases.first);
    document.getElementById("base-second").classList.toggle("occupied", g.bases.second);
    document.getElementById("base-third").classList.toggle("occupied", g.bases.third);

    const outsDots = document.querySelectorAll("#live-outs-dots .out-dot");
    outsDots.forEach((dot, i) => dot.classList.toggle("filled", i < g.outs));

    document.getElementById("live-count-value").textContent = `${g.balls}-${g.strikes}`;

    document.getElementById("live-pitcher").textContent = g.pitcher || "";
    document.getElementById("live-batter").textContent = g.batter || "";
    document.getElementById("live-last-play").textContent = g.last_play || "";

    const scoringSection = document.getElementById("live-scoring-plays");
    const scoringList = document.getElementById("live-scoring-plays-list");
    if (g.scoring_plays && g.scoring_plays.length) {
      scoringSection.hidden = false;
      scoringList.innerHTML = g.scoring_plays
        .map(
          (p) => `
          <li>
            <span class="live-scoring-play-inning">${p.half === "top" ? "Top" : "Bot"} ${ordinal(p.inning)}</span>
            <span class="live-scoring-play-desc">${p.description}</span>
            <span class="live-scoring-play-score">${p.us_score}-${p.them_score}</span>
          </li>
        `
        )
        .join("");
    } else {
      scoringSection.hidden = true;
    }

    // The pitcher is always on defense and the batter always on offense, so
    // whichever side is "us" flips every half-inning — label each side by
    // team so it's clear who's who, not just what role they're playing.
    const pitcherLabel = document.getElementById("live-pitcher-label");
    const batterLabel = document.getElementById("live-batter-label");
    const pitcherSide = document.getElementById("live-pitcher-side");
    const batterSide = document.getElementById("live-batter-side");
    pitcherLabel.textContent = g.batting_team_is_us ? `${oppShort} Pitching` : "Red Sox Pitching";
    batterLabel.textContent = g.batting_team_is_us ? "Red Sox At Bat" : `${oppShort} At Bat`;
    pitcherSide.classList.toggle("is-us", !g.batting_team_is_us);
    batterSide.classList.toggle("is-us", g.batting_team_is_us);

    if (!liveGamePollTimer) {
      liveGamePollTimer = setInterval(loadLiveGame, LIVE_GAME_POLL_MS);
    }
  } catch (e) {
    // A transient fetch failure shouldn't yank the ticker away mid-game —
    // just leave the last-known state showing and try again next poll.
    if (!liveGamePollTimer) {
      liveGamePollTimer = setInterval(loadLiveGame, LIVE_GAME_POLL_MS);
    }
  }
}

const compareSelection = { a: null, b: null };
const compareSearchTimers = { a: null, b: null };

function debounceSearch(side, query) {
  clearTimeout(compareSearchTimers[side]);
  const resultsEl = document.getElementById(`compare-results-${side}`);
  if (!query.trim()) {
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    return;
  }
  compareSearchTimers[side] = setTimeout(() => runCompareSearch(side, query), 300);
}

async function runCompareSearch(side, query) {
  const resultsEl = document.getElementById(`compare-results-${side}`);
  try {
    const res = await fetch(`/api/players/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) throw new Error("Search failed");
    const data = await res.json();
    const results = data.results || [];

    resultsEl.innerHTML = results.length
      ? results
          .map(
            (p, i) => `
        <div class="compare-result" data-idx="${i}">
          <span class="compare-result-name">${p.name}</span>
          <span class="compare-result-meta">${p.team} · ${p.type === "hitter" ? "Hitter" : "Pitcher"}</span>
        </div>
      `
          )
          .join("")
      : '<div class="compare-result-empty">No matches</div>';
    resultsEl.hidden = false;

    resultsEl.querySelectorAll(".compare-result").forEach((el, i) => {
      el.addEventListener("click", () => selectComparePlayer(side, results[i]));
    });
  } catch (e) {
    resultsEl.innerHTML = `<div class="compare-result-empty">Couldn't search: ${e.message}</div>`;
    resultsEl.hidden = false;
  }
}

async function selectComparePlayer(side, player) {
  const resultsEl = document.getElementById(`compare-results-${side}`);
  const selectedEl = document.getElementById(`compare-selected-${side}`);
  const inputEl = document.getElementById(`compare-search-${side}`);
  resultsEl.hidden = true;
  resultsEl.innerHTML = "";
  inputEl.value = "";

  selectedEl.innerHTML = `<div class="compare-chip">${player.name} <span class="compare-chip-meta">(${player.team})</span> <button class="compare-chip-clear" aria-label="Clear">×</button></div>`;
  selectedEl.querySelector(".compare-chip-clear").addEventListener("click", () => clearComparePlayer(side));

  try {
    const res = await fetch(`/api/players/compare?player_id=${player.player_id}&type=${player.type}`);
    if (!res.ok) throw new Error("Failed to load player profile");
    compareSelection[side] = await res.json();
  } catch (e) {
    compareSelection[side] = null;
    selectedEl.innerHTML += `<p class="muted small-note">Couldn't load stats: ${e.message}</p>`;
  }

  renderCompareTape();
}

function clearComparePlayer(side) {
  compareSelection[side] = null;
  document.getElementById(`compare-selected-${side}`).innerHTML = "";
  renderCompareTape();
}

function tapeStatRow(label, statA, statB) {
  return `
    <div class="tape-stat">
      <div class="tape-label">${label}</div>
      <div class="tape-row">
        <span class="tape-val tape-val-a">${statA.value ?? "-"} <span class="tape-pctl">(${ordinal(statA.percentile)})</span></span>
        <div class="tape-track">
          <div class="tape-half tape-half-a"><div class="tape-fill" style="width:${statA.percentile}%"></div></div>
          <div class="tape-half tape-half-b"><div class="tape-fill" style="width:${statB.percentile}%"></div></div>
        </div>
        <span class="tape-val tape-val-b">${statB.value ?? "-"} <span class="tape-pctl">(${ordinal(statB.percentile)})</span></span>
      </div>
    </div>
  `;
}

function renderCompareTape() {
  const tapeEl = document.getElementById("compare-tape");
  if (!tapeEl) return;

  const a = compareSelection.a;
  const b = compareSelection.b;

  if (!a || !b) {
    tapeEl.innerHTML = "";
    return;
  }

  if (a.type !== b.type) {
    tapeEl.innerHTML = `<p class="muted small-note">${a.name} (${a.type}) and ${b.name} (${b.type}) don't share the same Statcast metrics — pick two hitters or two pitchers to compare.</p>`;
    return;
  }

  const sharedLabels = Object.keys(a.stats).filter((label) => label in b.stats);
  if (!sharedLabels.length) {
    tapeEl.innerHTML = `<p class="muted small-note">Not enough shared Statcast data between ${a.name} and ${b.name} to compare.</p>`;
    return;
  }

  const rows = sharedLabels.map((label) => tapeStatRow(label, a.stats[label], b.stats[label])).join("");
  tapeEl.innerHTML = `
    <div class="tape-header">
      <span class="tape-header-name tape-header-a">${a.name}</span>
      <span class="tape-header-name tape-header-b">${b.name}</span>
    </div>
    ${rows}
  `;
}

function initCompareTool() {
  ["a", "b"].forEach((side) => {
    const input = document.getElementById(`compare-search-${side}`);
    if (!input) return;
    input.addEventListener("input", (e) => debounceSearch(side, e.target.value));
    input.addEventListener("focus", (e) => {
      if (e.target.value.trim()) debounceSearch(side, e.target.value);
    });
    document.addEventListener("click", (e) => {
      const resultsEl = document.getElementById(`compare-results-${side}`);
      if (!resultsEl || resultsEl.hidden) return;
      if (!resultsEl.contains(e.target) && e.target !== input) resultsEl.hidden = true;
    });
  });
}

// Runs on every page (common.js is shared) so a live game is visible from
// the nav even while browsing League/Players/Games, not just Home.
const NAV_LIVE_CHECK_MS = 60000;

async function updateNavLiveIndicator() {
  const dot = document.querySelector(".nav-live-dot");
  if (!dot) return;
  try {
    const res = await fetch("/api/team/live-game");
    if (!res.ok) return;
    const data = await res.json();
    dot.hidden = !data.game;
  } catch (e) {
    // Leave the indicator as-is on a transient failure — no need to flicker
    // it off just because one poll dropped.
  }
}

updateNavLiveIndicator();
setInterval(updateNavLiveIndicator, NAV_LIVE_CHECK_MS);
