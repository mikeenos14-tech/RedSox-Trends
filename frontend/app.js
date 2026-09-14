let runDiffChart = null;

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

function renderSummary(data) {
  document.getElementById("record-line").textContent =
    `${data.record.wins}-${data.record.losses} (.${data.record.pct?.replace("0.", "")}) ` +
    `• ${data.games_back === "-" ? "1st" : data.games_back + " GB"} • Streak: ${data.streak ?? "-"}`;

  const cards = document.getElementById("cards");
  cards.innerHTML = "";
  cards.append(
    card("Last 10", data.last_10 ? `${data.last_10.wins}-${data.last_10.losses}` : "-"),
    card("Home Record", data.home_record ? `${data.home_record.wins}-${data.home_record.losses}` : "-"),
    card("Away Record", data.away_record ? `${data.away_record.wins}-${data.away_record.losses}` : "-"),
    card("Run Differential", data.run_differential > 0 ? `+${data.run_differential}` : data.run_differential),
    card("Expected Record", data.expected_record ? `${data.expected_record.wins}-${data.expected_record.losses}` : "-"),
    card("Recent Form", data.recent_form ? data.recent_form.trending : "-")
  );

  const tbody = document.querySelector("#games-table tbody");
  tbody.innerHTML = "";
  [...data.recent_games].reverse().forEach((g) => {
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

  renderAnalysis(data.analysis || {});
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

  const labels = series.map((p) => p.date.slice(5));
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
    textEl.textContent = data.summary;
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
    const res = await fetch("/api/players/hot-cold");
    if (!res.ok) throw new Error("Failed to load player stats");
    const data = await res.json();

    hittersBody.innerHTML = "";
    data.hitters.forEach((h) => {
      const s = h.season;
      const r = h.recent;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="name">${h.name}</td>
        <td>${h.position || "-"}</td>
        <td class="num">${pctStr(s.woba)}</td>
        <td class="num">${r ? pctStr(r.woba) : "-"}</td>
        ${deltaCell(h.form_delta_woba, true, h.small_sample)}
        <td class="num">${pctStr(s.babip)}</td>
        <td class="num">${pctStr(s.bb_pct)}</td>
        <td class="num">${pctStr(s.k_pct)}</td>
        <td class="num">${pctStr(s.iso)}</td>
      `;
      hittersBody.appendChild(tr);
    });

    pitchersBody.innerHTML = "";
    data.pitchers.forEach((p) => {
      const s = p.season;
      const r = p.recent;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="name">${p.name}</td>
        <td>${p.role}</td>
        <td class="num">${s.era ?? "-"}</td>
        <td class="num">${r ? (r.era ?? "-") : "-"}</td>
        ${deltaCell(p.form_delta_era, true, p.small_sample)}
        <td class="num">${s.fip ?? "-"}</td>
        <td class="num">${pctStr(s.k_bb_pct)}</td>
        <td class="num">${pctStr(s.babip_against)}</td>
        <td class="num">${pctStr(s.lob_pct)}</td>
      `;
      pitchersBody.appendChild(tr);
    });
  } catch (e) {
    hittersBody.innerHTML = `<tr><td colspan="9">Couldn't load: ${e.message}</td></tr>`;
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
    textEl.textContent = data.notes;
  } catch (e) {
    textEl.textContent = `Couldn't generate notes: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate Player Notes";
  }
}

document.getElementById("regenerate-btn").addEventListener("click", loadRecap);
document.getElementById("headlines-summary-btn").addEventListener("click", loadHeadlinesSummary);
document.getElementById("analysis-btn").addEventListener("click", loadAnalysisBriefing);
document.getElementById("player-notes-btn").addEventListener("click", loadPlayerNotes);

loadSummary()
  .then(renderSummary)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadHeadlines();
loadPlayerHotCold();
