loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadPlayerHotCold();
loadFullRoster();
loadPlayerHighlight();
loadPlayerNotes();

initSortableTable("hitters-table");
initSortableTable("pitchers-table");
initSortableTable("roster-hitters-table");
initSortableTable("roster-pitchers-table");

initTabGroup("hotcold-tabs");
initTabGroup("roster-tabs");
initAdvancedToggle("hotcold-advanced-btn", "hotcold-tabs", "Show advanced stats", "Hide advanced stats");
