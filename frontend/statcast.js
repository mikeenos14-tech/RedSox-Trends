loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadStatcast();
loadStatcastNotes();

initCompareTool();
initTabGroup("statcast-tabs");
initExpandSection("statcast-full-report", "Show full scouting report", "Hide full scouting report");
