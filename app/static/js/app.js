(() => {
  const nodes = document.querySelectorAll(".match-time[datetime]");
  if (nodes.length) {
    const formatter = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });

    nodes.forEach((node) => {
      const raw = node.getAttribute("datetime");
      if (!raw) return;
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) return;
      node.textContent = formatter.format(parsed);
      node.setAttribute("title", parsed.toLocaleString());
    });
  }

  document.querySelectorAll("[data-entry-rename-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-entry-rename-open");
      const dlg = id ? document.getElementById(id) : null;
      if (dlg && typeof dlg.showModal === "function") dlg.showModal();
    });
  });

  document.querySelectorAll("[data-entry-rename-cancel]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dlg = btn.closest("dialog");
      if (dlg) dlg.close();
    });
  });
})();
