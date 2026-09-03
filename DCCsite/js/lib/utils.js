export async function fetchJSON(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path}: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.attrs) {
    for (const [key, value] of Object.entries(options.attrs)) {
      node.setAttribute(key, value);
    }
  }
  for (const child of children) node.appendChild(child);
  return node;
}

export function renderLoading(container) {
  container.replaceChildren(el("p", { className: "loading-state", text: "Loading…" }));
}

export function renderError(container, message) {
  container.replaceChildren(el("p", { className: "error-state", text: message }));
}

export function renderCardGrid(container, items, buildCard, emptyMessage = "No entries yet.") {
  container.replaceChildren();
  if (!items.length) {
    container.appendChild(el("p", { className: "empty-state", text: emptyMessage }));
    return;
  }
  const grid = el("div", { className: "card-grid" });
  for (const item of items) grid.appendChild(buildCard(item));
  container.appendChild(grid);
}
