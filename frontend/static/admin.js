const $ = (selector) => document.querySelector(selector);
const loginPanel = $("#login-panel");
const dashboard = $("#dashboard");
const loginForm = $("#login-form");
const caseForm = $("#case-form");
const loginStatus = $("#login-status");
const editorStatus = $("#editor-status");
const adminCaseList = $("#admin-case-list");
const imageInput = $("#image-input");
const imagePreview = $("#image-preview");
let cases = [];
// Each entry is { path, comment, file }. Existing images have a path; new images have a File.
let imageEntries = [];
let editingId = null;

function setStatus(element, message, kind = "") {
  element.textContent = message;
  element.className = `form-status ${kind}`.trim();
}
function formValue(name) { return String(caseForm.elements[name]?.value || "").trim(); }
function safeText(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text ?? "";
  return element;
}
async function api(url_s, options = {}) {
  const response = await fetch(url_s, { credentials: "same-origin", ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
function showDashboard(authenticated) {
  loginPanel.hidden = authenticated;
  dashboard.hidden = !authenticated;
}
async function checkSession() {
  try {
    const result = await api("/api/auth/me");
    showDashboard(result.authenticated);
    if (result.authenticated) await refreshCases();
  } catch { showDashboard(false); }
}
loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus(loginStatus, "Signing in…");
  const form = new FormData(loginForm);
  try {
    await api("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") })
    });
    loginForm.reset();
    setStatus(loginStatus, "");
    showDashboard(true);
    await refreshCases();
  } catch (error) { setStatus(loginStatus, error.message, "error"); }
});
$("#logout-button").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } finally { showDashboard(false); }
});

imageInput.addEventListener("change", () => {
  const chosen = Array.from(imageInput.files || []);
  if (imageEntries.length + chosen.length > 6) {
    setStatus(editorStatus, "A case can have up to 6 images in total.", "error");
    imageInput.value = "";
    return;
  }
  if (chosen.some(file => file.size > 5 * 1024 * 1024)) {
    setStatus(editorStatus, "Each image must be 5 MB or smaller.", "error");
    imageInput.value = "";
    return;
  }
  const validTypes = ["image/png", "image/jpeg", "image/webp", "image/gif"];
  if (chosen.some(file => !validTypes.includes(file.type))) {
    setStatus(editorStatus, "Choose PNG, JPG, WEBP, or GIF images.", "error");
    imageInput.value = "";
    return;
  }
  chosen.forEach(file => imageEntries.push({ path: "", comment: "", file }));
  imageInput.value = "";
  setStatus(editorStatus, "");
  renderImagePreview();
});

function renderImagePreview() {
  imagePreview.replaceChildren();
  if (!imageEntries.length) {
    imagePreview.append(safeText("p", "muted image-preview-empty", "No images added yet. Add screenshots, then write a note for each one."));
    return;
  }
  imageEntries.forEach((entry, index) => {
    const wrap = safeText("article", "image-editor-item");
    const top = safeText("div", "image-editor-top");
    const img = document.createElement("img");
    img.alt = `Bug screenshot ${index + 1}`;
    img.src = entry.file ? URL.createObjectURL(entry.file) : entry.path;
    const info = safeText("div", "image-editor-info");
    info.append(safeText("strong", "", `Image ${index + 1}`));
    info.append(safeText("span", "muted", entry.file ? entry.file.name : "Saved image"));
    const remove = safeText("button", "preview-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove image ${index + 1}`);
    remove.addEventListener("click", () => {
      imageEntries.splice(index, 1);
      renderImagePreview();
    });
    top.append(img, info, remove);
    const label = safeText("label", "image-comment-label", "Comment / explanation for this image");
    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.maxLength = 1000;
    textarea.placeholder = "Example: Before the fix — the API returned a 500 error when the form was submitted.";
    textarea.value = entry.comment || "";
    textarea.addEventListener("input", () => { imageEntries[index].comment = textarea.value; });
    label.append(textarea);
    wrap.append(top, label);
    imagePreview.append(wrap);
  });
}

function resetEditor() {
  caseForm.reset();
  caseForm.elements.case_id.value = "";
  editingId = null;
  imageEntries = [];
  imageInput.value = "";
  renderImagePreview();
  $("#editor-title").textContent = "Create a case study";
  $("#save-button").textContent = "Publish case →";
  setStatus(editorStatus, "");
}
$("#reset-button").addEventListener("click", resetEditor);

async function uploadNewImages() {
  const newEntries = imageEntries.filter(entry => entry.file);
  if (!newEntries.length) return;
  const formData = new FormData();
  newEntries.forEach(entry => formData.append("files", entry.file));
  const result = await api("/api/uploads", { method: "POST", body: formData });
  if (!Array.isArray(result.images) || result.images.length !== newEntries.length) {
    throw new Error("The server did not return all uploaded images.");
  }
  let pathIndex = 0;
  imageEntries = imageEntries.map(entry => entry.file
    ? { path: result.images[pathIndex++].path, comment: entry.comment || "", file: null }
    : entry);
}

caseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const saveButton = $("#save-button");
  saveButton.disabled = true;
  setStatus(editorStatus, "Uploading images and saving case study…");
  try {
    await uploadNewImages();
    const data = new FormData();
    ["title","url", "technology", "summary", "problem", "diagnosis", "solution", "result"].forEach(key => data.set(key, formValue(key)));
    data.set("images", JSON.stringify(imageEntries.map(({ path, comment }) => ({ path, comment }))));
    data.set("published", caseForm.elements.published.checked ? "true" : "false");
    const url = editingId ? `/api/cases/${editingId}` : "/api/cases";
    const method = editingId ? "PUT" : "POST";
    await api(url, { method, body: data });
    resetEditor();
    setStatus(editorStatus, "Case study saved successfully. Each image and its comment are saved.", "success");
    await refreshCases();
  } catch (error) { setStatus(editorStatus, error.message, "error"); }
  finally { saveButton.disabled = false; }
});

function renderAdminList() {
  adminCaseList.replaceChildren();
  $("#case-count").textContent = String(cases.length);
  if (!cases.length) {
    adminCaseList.append(safeText("p", "muted", "No case studies yet. Create your first one using the form."));
    return;
  }
  cases.forEach(item => {
    const row = safeText("article", "admin-case-item");
    const titleRow = safeText("div", "admin-case-title-row");
    titleRow.append(safeText("h3", "", item.title));
    titleRow.append(safeText("span", item.published ? "published-tag" : "draft-tag", item.published ? "Published" : "Draft"));
    row.append(titleRow);
    if (item.technology) row.append(safeText("p", "muted", item.technology));
    const images = Array.isArray(item.images) ? item.images : [];
    if (images.length) {
      const gallery = safeText("div", "admin-case-thumbnails");
      images.forEach((image, index) => {
        const img = document.createElement("img");
        img.src = typeof image === "string" ? image : image.path;
        img.alt = `Image ${index + 1} for ${item.title}`;
        img.title = typeof image === "string" ? `Image ${index + 1}` : (image.comment || `Image ${index + 1}`);
        gallery.append(img);
      });
      row.append(gallery);
      row.append(safeText("p", "muted", `${images.length} image(s), each with its own comment field`));
    }
    const actions = safeText("div", "admin-case-actions");
    const edit = safeText("button", "button button-small button-outline", "Edit images & notes");
    edit.type = "button"; edit.addEventListener("click", () => editCase(item));
    const del = safeText("button", "button button-small button-danger", "Delete");
    del.type = "button"; del.addEventListener("click", () => removeCase(item));
    actions.append(edit, del); row.append(actions);
    adminCaseList.append(row);
  });
}
function editCase(item) {
  editingId = item.id;
  caseForm.elements.case_id.value = String(item.id);
  ["title", "url","technology", "summary", "problem", "diagnosis", "solution", "result"].forEach(key => caseForm.elements[key].value = item[key] || "");
  caseForm.elements.published.checked = item.published;
  imageEntries = (item.images || []).map(image => typeof image === "string"
    ? { path: image, comment: "", file: null }
    : { path: image.path, comment: image.comment || "", file: null });
  imageInput.value = "";
  renderImagePreview();
  $("#editor-title").textContent = "Edit case study and image notes";
  $("#save-button").textContent = "Save changes →";
  setStatus(editorStatus, "Edit each image's comment below its preview. You can also add more images.");
  window.scrollTo({ top: 0, behavior: "smooth" });
}
async function removeCase(item) {
  if (!window.confirm(`Delete "${item.title}"? This cannot be undone.`)) return;
  try {
    await api(`/api/cases/${item.id}`, { method: "DELETE" });
    if (editingId === item.id) resetEditor();
    await refreshCases();
  } catch (error) { window.alert(error.message); }
}
async function refreshCases() {
  cases = await api("/api/cases");
  renderAdminList();
}
renderImagePreview();
checkSession();
