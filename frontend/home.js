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
loadSeasonSeries();
loadLiveGame();
