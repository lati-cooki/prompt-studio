export function createModelSelectorState({ allKeys, initialKeys, onChange }) {
  const valid    = new Set(allKeys);
  const selected = new Set(initialKeys.filter(k => valid.has(k)));

  return {
    selectedKeys() { return new Set(selected); },

    toggle(key) {
      if (!valid.has(key)) return;
      if (selected.has(key)) {
        if (selected.size <= 1) return;
        selected.delete(key);
      } else {
        selected.add(key);
      }
      onChange(new Set(selected));
    },
  };
}

export function createModelSelector({ container, models, initialKeys, onChange }) {
  const allKeys = Object.keys(models);
  const state   = createModelSelectorState({ allKeys, initialKeys, onChange });

  const wrap = document.createElement("div");
  wrap.className = "model-selector";

  const groups = { local: [], frontier: [] };
  for (const [key, m] of Object.entries(models)) {
    (groups[m.group] || groups.local).push(key);
  }

  for (const [groupName, keys] of Object.entries(groups)) {
    if (!keys.length) continue;
    const groupLabel = document.createElement("div");
    groupLabel.className   = "model-group-label";
    groupLabel.textContent = groupName.toUpperCase();
    wrap.appendChild(groupLabel);

    for (const key of keys) {
      const row = document.createElement("label");
      row.className = "model-row";

      const cb = document.createElement("input");
      cb.type      = "checkbox";
      cb.checked   = state.selectedKeys().has(key);
      cb.className = "model-cb";

      const name = document.createElement("span");
      name.className   = "model-name";
      name.textContent = key;

      const provider = models[key]?.provider ?? groupName;
      const tag = document.createElement("span");
      tag.className   = `model-tag ${provider}`;
      tag.textContent = provider;

      cb.addEventListener("change", () => {
        state.toggle(key);
        cb.checked = state.selectedKeys().has(key);
      });

      row.appendChild(cb);
      row.appendChild(name);
      row.appendChild(tag);
      wrap.appendChild(row);
    }
  }

  container.appendChild(wrap);
  return { element: wrap, state };
}
