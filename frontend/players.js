loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadPlayerHotCold();
loadFullRoster();
loadStatcast();
loadPlayerHighlight();
loadPlayerNotes();
loadStatcastNotes();

initSortableTable("hitters-table");
initSortableTable("pitchers-table");
initSortableTable("roster-hitters-table");
initSortableTable("roster-pitchers-table");
initCompareTool();

initTabGroup("hotcold-tabs");
initTabGroup("roster-tabs");
initTabGroup("statcast-tabs");
initExpandSection("statcast-full-report", "Show full scouting report", "Hide full scouting report");
initAdvancedToggle("hotcold-advanced-btn", "hotcold-tabs", "Show advanced stats", "Hide advanced stats");
