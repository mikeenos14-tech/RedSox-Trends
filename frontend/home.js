loadSummary()
  .then((data) => {
    renderRecordLine(data);
    renderOverviewCards(data);
  })
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadDivisionStandings();
loadWildcardStandings();
loadLastGameRecap();
loadGameSignificance();
loadUpcomingSchedule();
loadHeadlines();
loadSeasonReview();
loadSeasonSeries();
loadLiveGame();
initExpandSection("live-scoring-plays", "Show scoring plays", "Hide scoring plays");
