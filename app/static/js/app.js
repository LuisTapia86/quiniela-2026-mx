(() => {
  const nodes = document.querySelectorAll(".match-time[datetime]");
  if (!nodes.length) return;

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
})();
