"use strict";
(() => {
  const form = document.getElementById("marking-form");
  if (!form) return;
  const rows = [...form.querySelectorAll(".marking-row")];
  const dialog = document.getElementById("correction-dialog");
  const dialogForm = document.getElementById("correction-form");
  const reasonInput = document.getElementById("correction-reason");
  const correctionQueue = [];
  let pendingCorrection = null;
  let submitAfterCorrections = false;
  let submitting = false;
  const valueOf = row => row.querySelector('input[type="radio"]:checked')?.value || "NOT_MARKED";
  const reasonOf = row => row.querySelector('input[name$="-change_reason"]');
  const needsReason = row => row.dataset.initial !== "NOT_MARKED" && valueOf(row) !== row.dataset.initial;
  rows.forEach(row => {
    row.dataset.current = valueOf(row);
    if (row.dataset.initial !== "NOT_MARKED") {
      row.querySelector('input[value="NOT_MARKED"]').disabled = true;
    }
  });

  const update = () => {
    const counts = { PRESENT: 0, ABSENT: 0, NOT_MARKED: 0 };
    rows.forEach(row => {
      const value = valueOf(row);
      counts[value] += 1;
      row.classList.toggle("changed", value !== row.dataset.initial);
    });
    document.getElementById("present-count").textContent = counts.PRESENT;
    document.getElementById("absent-count").textContent = counts.ABSENT;
    document.getElementById("unmarked-count").textContent = counts.NOT_MARKED;
  };

  const showNextCorrection = () => {
    if (pendingCorrection) return;
    pendingCorrection = correctionQueue.shift() || null;
    if (!pendingCorrection) {
      if (submitAfterCorrections) {
        submitAfterCorrections = false;
        form.requestSubmit();
      }
      return;
    }
    const row = pendingCorrection.row;
    document.getElementById("correction-student").textContent = row.querySelector(".student-name strong").textContent;
    reasonInput.value = reasonOf(row).value;
    reasonInput.setCustomValidity("");
    dialog.returnValue = "";
    dialog.showModal();
    reasonInput.focus();
  };

  const changeRow = (row, previous) => {
    row.dataset.current = valueOf(row);
    if (needsReason(row)) {
      correctionQueue.push({ row, previous });
    } else {
      reasonOf(row).value = "";
    }
  };

  form.addEventListener("change", event => {
    if (!event.target.matches('input[type="radio"]')) return;
    const row = event.target.closest(".marking-row");
    changeRow(row, row.dataset.current);
    update();
    showNextCorrection();
  });

  document.getElementById("mark-all").addEventListener("click", () => {
    rows.forEach(row => {
      const present = row.querySelector('input[value="PRESENT"]');
      const previous = valueOf(row);
      if (!present || previous === "PRESENT") return;
      present.checked = true;
      changeRow(row, previous);
    });
    update();
    showNextCorrection();
  });

  reasonInput.addEventListener("input", () => reasonInput.setCustomValidity(""));
  dialogForm.addEventListener("submit", event => {
    const reason = reasonInput.value.trim();
    if (!reason) {
      event.preventDefault();
      reasonInput.setCustomValidity("Укажите причину правки");
      reasonInput.reportValidity();
      return;
    }
    reasonOf(pendingCorrection.row).value = reason;
    dialog.returnValue = "apply";
  });
  document.getElementById("correction-cancel").addEventListener("click", () => dialog.close("cancel"));
  dialog.addEventListener("close", () => {
    if (!pendingCorrection) return;
    const { row, previous } = pendingCorrection;
    if (dialog.returnValue !== "apply") {
      row.querySelector(`input[type="radio"][value="${previous}"]`).checked = true;
      row.dataset.current = previous;
      submitAfterCorrections = false;
    }
    pendingCorrection = null;
    update();
    showNextCorrection();
  });

  form.addEventListener("submit", event => {
    const missing = rows.filter(row => needsReason(row) && !reasonOf(row).value.trim());
    if (missing.length) {
      event.preventDefault();
      submitAfterCorrections = true;
      missing.forEach(row => correctionQueue.push({ row, previous: valueOf(row) }));
      showNextCorrection();
      return;
    }
    submitting = true;
  });
  window.addEventListener("beforeunload", event => {
    const dirty = rows.some(row => valueOf(row) !== row.dataset.initial);
    if (dirty && !submitting) { event.preventDefault(); event.returnValue = ""; }
  });
  update();
})();

(() => {
  const filters = document.getElementById("teacher-filters");
  if (!filters) return;
  const year = document.getElementById("teacher-year");
  const subject = document.getElementById("teacher-subject");
  const group = document.getElementById("teacher-group");
  year.addEventListener("change", () => {
    subject.value = "";
    group.value = "";
    filters.requestSubmit();
  });
  subject.addEventListener("change", () => {
    group.value = "";
    filters.requestSubmit();
  });
  group.addEventListener("change", () => filters.requestSubmit());
})();
document.querySelectorAll("form[data-delete-dispute]").forEach(form => {
  form.addEventListener("submit", event => {
    if (!window.confirm(form.dataset.deleteDispute)) event.preventDefault();
  });
});
