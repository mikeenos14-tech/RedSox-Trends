loadSummary()
  .then((data) => {
    renderRecordLine(data);
    renderPostseasonTable(data.postseason);
    renderGamesTable(data.recent_games);
  })
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadOnThisDay();
loadBullpen();
