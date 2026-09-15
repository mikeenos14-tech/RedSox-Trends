loadSummary()
  .then(renderRecordLine)
  .catch((e) => {
    document.getElementById("record-line").textContent = `Couldn't load data: ${e.message}`;
  });

document.getElementById("player-notes-btn").addEventListener("click", loadPlayerNotes);
document.getElementById("statcast-notes-btn").addEventListener("click", loadStatcastNotes);

loadPlayerHotCold();
loadStatcast();
loadPlayerHighlight();
