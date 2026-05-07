export function renderSources(bubble, results) {
  const line = document.createElement("div");
  line.className = "sources";

  const label = document.createElement("span");
  label.className   = "source-label";
  label.textContent = "sources: ";
  line.appendChild(label);

  results.forEach((r) => {
    const name = r.path.split("/").pop();
    const chip = document.createElement("span");
    chip.textContent = name;
    chip.title       = r.snippet;
    line.appendChild(chip);
  });

  bubble.appendChild(line);
}
