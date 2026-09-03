import { el, fetchJSON, renderCardGrid, renderError, renderLoading } from "../lib/utils.js";

const DATA_PATH = "../DCCdata/items.json";

function buildCard(item) {
  const card = el("article", { className: "card" });
  card.appendChild(el("h3", { text: item.name ?? "Unknown" }));

  if (item.type) card.appendChild(el("p", { className: "card-meta", text: item.type }));
  if (item.effects?.length) {
    card.appendChild(el("p", { text: `Effects: ${item.effects.join(", ")}` }));
  }
  if (item.source) card.appendChild(el("p", { text: `Source: ${item.source}` }));
  if (item.summary) card.appendChild(el("p", { className: "card-summary", text: item.summary }));
  return card;
}

export default async function renderItems(container) {
  renderLoading(container);
  let items;
  try {
    items = await fetchJSON(DATA_PATH);
  } catch (err) {
    renderError(container, `Couldn't load items: ${err.message}`);
    return;
  }
  renderCardGrid(container, items, buildCard, "No items yet -- run the extraction pipeline.");
}
