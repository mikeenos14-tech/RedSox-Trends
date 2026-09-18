const PLAYER_ID = new URLSearchParams(location.search).get("id");

function statTile(label, value) {
  return `<div class="card"><div class="label">${label}</div><div class="value">${value ?? "-"}</div></div>`;
}

function renderHero(p) {
  const hero = document.getElementById("player-hero");
  const statusBadge = p.active ? "" : ' <span class="il-badge">IL</span>';
  const nickname = p.verified_nickname ? ` "${p.verified_nickname}"` : "";
  const facts = [
    p.position ? `<b>Pos:</b> ${p.position}` : null,
    p.jersey_number ? `<b>#</b>${p.jersey_number}` : null,
    p.age ? `<b>Age:</b> ${p.age}` : null,
    p.bat_side || p.pitch_hand ? `<b>Bats/Throws:</b> ${(p.bat_side || "-")[0]}/${(p.pitch_hand || "-")[0]}` : null,
    p.height && p.weight ? `<b>Ht/Wt:</b> ${p.height}, ${p.weight} lb` : null,
    p.birthplace ? `<b>From:</b> ${p.birthplace}` : null,
    p.mlb_debut ? `<b>MLB Debut:</b> ${formatLongDate(p.mlb_debut)}` : null,
  ]
    .filter(Boolean)
    .join(" &nbsp;&middot;&nbsp; ");

  document.title = `${p.name} — The Fenway Almanac`;
  hero.innerHTML = `
    <img class="highlight-headshot" src="${p.headshot_url}" alt="${p.name}" />
    <div class="player-hero-info">
      <h2>${p.name}${nickname}${statusBadge}</h2>
      <p class="muted">${facts}</p>
    </div>
  `;
}

function renderSeasonStats(p) {
  const section = document.getElementById("player-season-stats");
  const yearEl = document.getElementById("player-season-year");
  const cards = document.getElementById("player-season-cards");
  const s = p.hitting_this_season || p.pitching_this_season;
  if (!s) {
    section.hidden = true;
    return;
  }

  if (p.hitting_this_season) {
    // avg/ops here come straight from MLB's own stat block as already-
    // formatted strings (".274", ".856"), not numbers — unlike the floats
    // player_stats.py computes elsewhere, so no pctStr() conversion here.
    const h = p.hitting_this_season;
    yearEl.textContent = `${h.games} games`;
    cards.innerHTML = [
      statTile("AVG", h.avg),
      statTile("OPS", h.ops),
      statTile("HR", h.hr),
      statTile("RBI", h.rbi),
    ].join("");
  } else {
    const pit = p.pitching_this_season;
    yearEl.textContent = `${pit.innings_pitched} IP`;
    cards.innerHTML = [
      statTile("ERA", pit.era),
      statTile("W-L", `${pit.wins}-${pit.losses}`),
      statTile("SV", pit.saves),
      statTile("SO", pit.strikeouts),
    ].join("");
  }
}

function renderCareerStats(p) {
  const section = document.getElementById("player-career-stats");
  const cards = document.getElementById("player-career-cards");
  const c = p.hitting_career || p.pitching_career;
  if (!c) return;

  section.hidden = false;
  if (p.hitting_career) {
    cards.innerHTML = [
      statTile("Career AVG", c.avg),
      statTile("Career OPS", c.ops),
      statTile("Career HR", c.hr),
      statTile("Career RBI", c.rbi),
      statTile("Career Games", c.games),
    ].join("");
  } else {
    cards.innerHTML = [
      statTile("Career ERA", c.era),
      statTile("Career W-L", `${c.wins}-${c.losses}`),
      statTile("Career SV", c.saves),
      statTile("Career SO", c.strikeouts),
      statTile("Career IP", c.innings_pitched),
    ].join("");
  }
}

function renderStatcast(p) {
  const section = document.getElementById("player-statcast-section");
  const grid = document.getElementById("player-statcast-grid");
  if (!p.statcast || !p.statcast.stats || !Object.keys(p.statcast.stats).length) return;

  section.hidden = false;
  grid.innerHTML = Object.entries(p.statcast.stats)
    .map(([label, stat]) => statcastMetricRow(label, stat))
    .join("");
}

function renderSplits(p) {
  const yearEl = document.getElementById("player-splits-year");
  const head = document.getElementById("player-splits-head");
  const body = document.querySelector("#player-splits-table tbody");
  if (!p.splits || !p.splits.length) {
    document.getElementById("player-splits-section").hidden = true;
    return;
  }

  const isPitcher = p.player_type === "pitcher";
  const cols = isPitcher
    ? [["ERA", "era"], ["WHIP", "whip"], ["FIP", "fip"], ["K-BB%", "k_bb_pct"], ["IP", "ip_display"]]
    : [["AVG", "avg"], ["OBP", "obp"], ["SLG", "slg"], ["OPS", "ops"], ["HR", "hr"], ["RBI", "rbi"]];

  yearEl.textContent = "this season";
  head.innerHTML = `<tr><th>Split</th>${cols.map(([label]) => `<th>${label}</th>`).join("")}</tr>`;
  body.innerHTML = p.splits
    .map((s) => {
      const cells = cols
        .map(([, key]) => {
          const v = s[key];
          const display = typeof v === "number" && key !== "hr" && key !== "rbi" ? pctStrOrRaw(key, v) : (v ?? "-");
          return `<td class="num">${display}</td>`;
        })
        .join("");
      return `<tr><td class="name">${s.label}</td>${cells}</tr>`;
    })
    .join("");
}

function pctStrOrRaw(key, v) {
  const rateStats = ["avg", "obp", "slg", "ops", "k_bb_pct"];
  return rateStats.includes(key) ? pctStr(v) : v;
}

function shortDate(dateStr) {
  const [, m, d] = dateStr.split("-").map(Number);
  return `${m}/${d}`;
}

function renderGameLog(p) {
  const body = document.querySelector("#player-gamelog-table tbody");
  if (!p.game_log || !p.game_log.length) {
    body.innerHTML = `<tr><td colspan="5">No games played yet this season.</td></tr>`;
    return;
  }

  body.innerHTML = p.game_log
    .map((g) => {
      const resultCls = g.won ? "delta-up" : "delta-down";
      const resultText = g.won ? "W" : "L";
      return `
        <tr>
          <td>${shortDate(g.date)}</td>
          <td class="name">${teamLogo(g.opponent_id)}${g.opponent}</td>
          <td>${g.home_or_away === "home" ? "vs" : "@"}</td>
          <td class="num ${resultCls}">${resultText}</td>
          <td class="line">${g.summary || "-"}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadPlayerProfile() {
  if (!PLAYER_ID) {
    document.getElementById("player-hero").innerHTML = `<p class="muted">No player specified.</p>`;
    return;
  }

  try {
    const res = await fetch(`/api/players/profile?id=${PLAYER_ID}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load player profile");
    }
    const p = await res.json();

    renderHero(p);
    renderSeasonStats(p);
    renderCareerStats(p);
    renderStatcast(p);
    renderSplits(p);
    renderGameLog(p);
  } catch (e) {
    document.getElementById("player-hero").innerHTML = `<p class="muted">Couldn't load this player: ${e.message}</p>`;
  }
}

loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadPlayerProfile();
initSortableTable("player-splits-table");
initSortableTable("player-gamelog-table");
