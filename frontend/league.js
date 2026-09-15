loadSummary()
  .then((data) => {
    renderRecordLine(data);
    renderAnalysis(data.analysis || {});
  })
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

document.getElementById("regenerate-btn").addEventListener("click", loadRecap);
document.getElementById("headlines-summary-btn").addEventListener("click", loadHeadlinesSummary);
document.getElementById("analysis-btn").addEventListener("click", loadAnalysisBriefing);

loadHeadlines();
loadLeagueContext();
