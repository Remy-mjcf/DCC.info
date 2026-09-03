import { el, fetchJSON, renderCardGrid, renderError, renderLoading } from "../lib/utils.js";

const DATA_PATH = "../DCCdata/books.json";

function buildCard(book) {
  const card = el("article", { className: "card" });
  card.appendChild(el("h3", { text: `${book.order}. ${book.title}` }));
  return card;
}

export default async function renderBooks(container) {
  renderLoading(container);
  let books;
  try {
    books = await fetchJSON(DATA_PATH);
  } catch (err) {
    renderError(container, `Couldn't load books: ${err.message}`);
    return;
  }
  books = [...books].sort((a, b) => a.order - b.order);
  renderCardGrid(container, books, buildCard, "No books yet.");
}
