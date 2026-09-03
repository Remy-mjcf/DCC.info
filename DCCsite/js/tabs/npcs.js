import { el, fetchJSON, renderCardGrid, renderError, renderLoading } from "../lib/utils.js";

const DATA_PATH = "../DCCdata/npcs.json";

function buildCard(npc) {
  const card = el("article", { className: "card" });
  card.appendChild(el("h3", { text: npc.name ?? "Unknown" }));

  const meta = [npc.role, npc.species].filter(Boolean).join(" · ");
  if (meta) card.appendChild(el("p", { className: "card-meta", text: meta }));

  if (npc.related_crawlers?.length) {
    card.appendChild(el("p", { text: `Related crawlers: ${npc.related_crawlers.join(", ")}` }));
  }
  if (npc.summary) {
    card.appendChild(el("p", { className: "card-summary", text: npc.summary }));
  }
  return card;
}

export default async function renderNpcs(container) {
  renderLoading(container);
  let npcs;
  try {
    npcs = await fetchJSON(DATA_PATH);
  } catch (err) {
    renderError(container, `Couldn't load NPCs: ${err.message}`);
    return;
  }
  renderCardGrid(container, npcs, buildCard, "No NPCs yet -- run the extraction pipeline.");
}
