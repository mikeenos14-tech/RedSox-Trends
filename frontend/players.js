loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

loadPlayerHotCold();
loadStatcast();
loadPlayerHighlight();
loadPlayerNotes();
loadStatcastNotes();

initSortableTable("hitters-table");
initSortableTable("pitchers-table");
initCompareTool();
