loadSummary()
  .then((data) => {
    renderRecordLine(data);
    renderAnalysis(data.analysis || {});
  })
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadHeadlines();
loadLeagueContext();
loadRecap();
loadHeadlinesSummary();
loadAnalysisBriefing();
