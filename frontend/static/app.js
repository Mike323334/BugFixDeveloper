const caseGrid = document.querySelector("#case-grid");
const caseEmpty = document.querySelector("#case-empty");
document.querySelector("#year").textContent = new Date().getFullYear();

function makeElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function renderCase(item) {
  const card = makeElement("article", "case-card");
  const cover = makeElement("div", "case-cover");
  const images = Array.isArray(item.images) ? item.images.map(image => typeof image === "string" ? { path: image, comment: "" } : image) : [];
  if (images.length) {
    const img = document.createElement("img");
    img.src = images[0].path;
    img.alt = `Bug screenshot for ${item.title}`;
    img.loading = "lazy";
    img.addEventListener("error", () => { img.remove(); cover.append(makeElement("span", "cover-placeholder", "BUG / FIX")); }, { once: true });
    cover.append(img);
    if (images.length > 1) cover.append(makeElement("span", "image-count", `${images.length} images`));
  } else {
    cover.append(makeElement("span", "cover-placeholder", "BUG / FIX"));
    cover.append(makeElement("span", "cover-code", "</>"));
  }
 const body = makeElement("div", "case-card-body");

// Display technology and the affected website URL together.
const metadata = makeElement("div", "case-metadata");

if (item.technology) {
metadata.append(
makeElement("span", "case-tech", item.technology)
);
}

if (item.url && String(item.url).trim()) {
const rawUrl = String(item.url).trim();


try {
  const normalizedUrl = /^https?:\/\//i.test(rawUrl)
    ? rawUrl
    : `https://${rawUrl}`;

  const parsedUrl = new URL(normalizedUrl);

  if (parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:") {
    const link = makeElement("a", "case-url", "View affected page ↗");

    link.href = parsedUrl.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = rawUrl;

    metadata.append(link);
  }
} catch (error) {
  console.warn("Invalid problem URL:", rawUrl, error);
}


}

if (metadata.childElementCount > 0) {
body.append(metadata);
}

body.append(makeElement("h3", "", item.title));
body.append(
makeElement("p", "case-summary", item.summary || item.problem)
);


  if (images.length) {
    const galleryDetails = makeElement("details", "case-image-details");
    const galleryToggle = makeElement("summary", "", `View bug screenshots and notes (${images.length})`);
    const gallery = makeElement("div", "case-image-gallery");
    images.forEach((image, index) => {
      const figure = makeElement("figure", "case-image-item");
      const screenshot = document.createElement("img");
      screenshot.src = image.path;
      screenshot.alt = `Screenshot ${index + 1} for ${item.title}`;
      screenshot.loading = "lazy";
      const caption = makeElement("figcaption", "", image.comment || `Screenshot ${index + 1}`);
      figure.append(screenshot, caption);
      gallery.append(figure);
    });
    galleryDetails.append(galleryToggle, gallery);
    body.append(galleryDetails);
  }

  const details = makeElement("details", "case-details");
  details.append(makeElement("summary", "", "Read the repair notes"));
  details.append(makeElement("h4", "", "The problem"), makeElement("p", "", item.problem));
  if (item.diagnosis) details.append(makeElement("h4", "", "Root cause"), makeElement("p", "", item.diagnosis));
  details.append(makeElement("h4", "", "The fix"), makeElement("p", "", item.solution));
  if (item.result) details.append(makeElement("h4", "", "Result"), makeElement("p", "", item.result));
  body.append(details);
  card.append(cover, body);
  return card;
}

async function loadCases() {
  try {
    const response = await fetch("/api/cases");
    if (!response.ok) throw new Error("Could not load case studies.");
    const cases = await response.json();
    caseGrid.replaceChildren();
    if (!cases.length) {
      caseEmpty.hidden = false;
      caseGrid.hidden = true;
      return;
    }
    caseEmpty.hidden = true;
    caseGrid.hidden = false;
    cases.forEach(item => caseGrid.append(renderCase(item)));
  } catch {
    caseGrid.replaceChildren(makeElement("p", "empty-state", "Case studies could not be loaded right now."));
  }
}
loadCases();

document.querySelector("#contact-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const name = String(form.get("name") || "").trim();
  const email = String(form.get("email") || "").trim();
  const technology = String(form.get("technology") || "Not specified");
  const message = String(form.get("message") || "").trim();
  const subject = encodeURIComponent(`Bug fixing request from ${name}`);
  const body = encodeURIComponent(`Name: ${name}\nEmail: ${email}\nTechnology: ${technology}\n\nProblem:\n${message}`);
  const status = document.querySelector("#contact-status");
  status.textContent = "Opening your email app. If nothing opens, email details are not sent automatically by this demo form.";
  // Replace this address with the business email before publishing.
  window.location.href = `mailto:hello@example.com?subject=${subject}&body=${body}`;
});
