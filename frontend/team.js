const TEAM_ID = new URLSearchParams(location.search).get("id");

function renderTeamHero(t) {
  const hero = document.getElementById("team-hero");
  const facts = [
    `<b>Record:</b> ${t.wins}-${t.losses} (${t.pct})`,
    t.division_rank ? `<b>Div Rank:</b> ${ordinal(Number(t.division_rank))}` : null,
    t.games_back ? `<b>GB:</b> ${t.games_back}` : null,
    t.streak ? `<b>Streak:</b> ${t.streak}` : null,
    t.last_10 ? `<b>Last 10:</b> ${t.last_10}` : null,
  ]
    .filter(Boolean)
    .join(" &nbsp;&middot;&nbsp; ");

  document.title = `${t.name} — The Fenway Almanac`;
  hero.innerHTML = `
    <img class="team-logo" style="width: 80px; height: 80px;" src="https://www.mlbstatic.com/team-logos/${t.id}.svg" alt="${t.name}" />
    <div class="player-hero-info">
      <h2>${t.name}</h2>
      <p class="muted">${facts}</p>
    </div>
  `;
}

function renderSeasonSeries(t) {
  const section = document.getElementById("team-series-section");
  const cards = document.getElementById("team-series-cards");
  const s = t.season_series_vs_us;
  if (!s) return;

  section.hidden = false;
  const result = s.wins > s.losses ? "Red Sox winning" : s.wins < s.losses ? "Red Sox losing" : "Even";
  cards.innerHTML = [card("Red Sox Wins", s.wins), card("Their Wins", s.losses), card("Series", result)]
    .map((el) => el.outerHTML)
    .join("");
}

function renderTeamRank(t) {
  const cards = document.getElementById("team-rank-cards");
  const d = t.league_rank;
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
}

function renderTopHitters(t) {
  const hitters = t.top_performers.hitters;
  if (!hitters.length) return;

  document.getElementById("team-hitters-section").hidden = false;
  const body = document.querySelector("#team-hitters-table tbody");
  body.innerHTML = hitters
    .map(
      (h) => `
      <tr>
        <td class="name">${h.name}</td>
        <td>${h.position || "-"}</td>
        <td class="num">${pctStr(h.season.avg)}</td>
        <td class="num">${pctStr(h.season.ops)}</td>
        <td class="num">${h.season.hr ?? "-"}</td>
        <td class="num">${h.season.rbi ?? "-"}</td>
      </tr>
    `
    )
    .join("");
}

function renderTopPitchers(t) {
  const pitchers = t.top_performers.pitchers;
  if (!pitchers.length) return;

  document.getElementById("team-pitchers-section").hidden = false;
  const body = document.querySelector("#team-pitchers-table tbody");
  body.innerHTML = pitchers
    .map(
      (p) => `
      <tr>
        <td class="name">${p.name}</td>
        <td>${p.role}</td>
        <td class="num">${p.season.era ?? "-"}</td>
        <td class="num">${p.season.fip ?? "-"}</td>
        <td class="num">${fmtPct1(p.season.k_bb_pct)}</td>
        <td class="num">${p.season.ip_display ?? "-"}</td>
      </tr>
    `
    )
    .join("");
}

function renderNextMatchup(t) {
  const g = t.next_matchup;
  if (!g) return;

  document.getElementById("team-next-section").hidden = false;
  const matchup = g.home_or_away === "home" ? `vs. ${t.name}` : `@ ${t.name}`;
  const pitcher = g.us_probable_pitcher ? playerLink(g.us_probable_pitcher_id, g.us_probable_pitcher) : "TBD";
  document.getElementById("team-next-body").innerHTML =
    `${formatLongDate(g.date)} &nbsp;${matchup} &nbsp;&middot;&nbsp; Our probable pitcher: ${pitcher}`;
}

async function loadTeamProfile() {
  if (!TEAM_ID) {
    document.getElementById("team-hero").innerHTML = `<p class="muted">No team specified.</p>`;
    return;
  }

  try {
    const res = await fetch(`/api/team/profile?id=${TEAM_ID}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load team profile");
    }
    const t = await res.json();

    renderTeamHero(t);
    renderSeasonSeries(t);
    renderTeamRank(t);
    renderTopHitters(t);
    renderTopPitchers(t);
    renderNextMatchup(t);
  } catch (e) {
    document.getElementById("team-hero").innerHTML = `<p class="muted">Couldn't load this team: ${e.message}</p>`;
  }
}

loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadTeamProfile();
initSortableTable("team-hitters-table");
initSortableTable("team-pitchers-table");
