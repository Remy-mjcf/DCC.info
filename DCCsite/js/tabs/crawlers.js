import { el, fetchJSON, renderCardGrid, renderError, renderLoading } from "../lib/utils.js";

const DATA_PATH = "../DCCdata/crawlers.json";

function buildCard(crawler) {
  const card = el("article", { className: "card" });
  card.appendChild(el("h3", { text: crawler.name ?? "Unknown" }));

  const meta = [crawler.class, crawler.species].filter(Boolean).join(" · ");
  if (meta) card.appendChild(el("p", { className: "card-meta", text: meta }));

  card.appendChild(el("p", { text: `Status: ${crawler.status ?? "Unknown"}` }));

  if (crawler.affiliations?.length) {
    card.appendChild(el("p", { text: `Affiliations: ${crawler.affiliations.join(", ")}` }));
  }
  if (crawler.summary) {
    card.appendChild(el("p", { className: "card-summary", text: crawler.summary }));
  }
  return card;
}

export default async function renderCrawlers(container) {
  renderLoading(container);
  let crawlers;
  try {
    crawlers = await fetchJSON(DATA_PATH);
  } catch (err) {
    renderError(container, `Couldn't load crawlers: ${err.message}`);
    return;
  }
  renderCardGrid(container, crawlers, buildCard, "No crawlers yet -- run the extraction pipeline.");
}
