import renderCrawlers from "./tabs/crawlers.js";
import renderNpcs from "./tabs/npcs.js";
import renderTattoos from "./tabs/tattoos.js";
import renderItems from "./tabs/items.js";
import renderBooks from "./tabs/books.js";

const TAB_RENDERERS = {
  crawlers: renderCrawlers,
  npcs: renderNpcs,
  tattoos: renderTattoos,
  items: renderItems,
  books: renderBooks,
};

const loaded = new Set();

function switchTab(name) {
  for (const button of document.querySelectorAll(".tab-button")) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.dataset.panel === name);
  }
  if (!loaded.has(name)) {
    loaded.add(name);
    TAB_RENDERERS[name](document.getElementById(`panel-${name}`));
  }
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

switchTab("crawlers");
