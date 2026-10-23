const TOKEN_KEY = "taskmaster_token";
const PHOTO_SIZE = 512;   // size of the uploaded square, in pixels
const MAX_SOURCE = 1600;  // shrink huge camera photos once, so dragging stays smooth

let selectedGroupId = null;

// Photo editor state. (cx, cy) is the crop center, in source-image pixels.
const photo = { source: null, cx: 0, cy: 0, zoom: 1 };

const $ = (id) => document.getElementById(id);

// localStorage can throw in some private-browsing modes, so wrap it.
function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function saveToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ignore */ }
}

function showError(message) {
  $("error").textContent = message;
}

// If this phone already has a valid token, skip the form.
async function checkExistingPlayer() {
  const token = getToken();
  if (!token) return false;
  const res = await fetch("/api/me", { headers: { "X-Player-Token": token } });
  if (!res.ok) return false;
  location.replace("/play");
  return true;
}

async function loadGroups() {
  const res = await fetch("/api/groups");
  const groups = await res.json();
  const container = $("groups");
  container.replaceChildren();
  for (const group of groups) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice";
    button.textContent = group.name;
    button.addEventListener("click", () => {
      selectedGroupId = group.id;
      for (const b of container.children) {
        b.classList.toggle("selected", b === button);
      }
    });
    container.append(button);
  }
}

// ---------- Photo editor ----------

// Decode the file and shrink it to at most MAX_SOURCE pixels on the long edge.
function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, MAX_SOURCE / Math.max(img.naturalWidth, img.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read that photo. Try another one."));
    };
    img.src = url;
  });
}

// How many source pixels the circle currently shows, edge to edge.
function cropSide() {
  return Math.min(photo.source.width, photo.source.height) / photo.zoom;
}

// Keep the crop inside the photo, so the circle never shows empty space.
function clampCenter() {
  const half = cropSide() / 2;
  photo.cx = Math.min(Math.max(photo.cx, half), photo.source.width - half);
  photo.cy = Math.min(Math.max(photo.cy, half), photo.source.height - half);
}

// The ONE drawing function. Preview and upload both use it, so they always match.
function drawCrop(canvas, size) {
  const side = cropSide();
  canvas.width = size;
  canvas.height = size;
  canvas.getContext("2d").drawImage(
    photo.source,
    photo.cx - side / 2, photo.cy - side / 2, side, side, // area of the photo to take
    0, 0, size, size                                      // where to draw it
  );
}

function renderPreview() {
  const canvas = $("photo-canvas");
  // Draw at the screen's real pixel density so the preview looks sharp.
  drawCrop(canvas, Math.round(canvas.clientWidth * (window.devicePixelRatio || 1)));
}

function exportPhoto() {
  return new Promise((resolve, reject) => {
    const canvas = document.createElement("canvas");
    drawCrop(canvas, PHOTO_SIZE);
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Could not process that photo."))),
      "image/jpeg",
      0.85
    );
  });
}

async function handlePhotoChosen(event) {
  const file = event.target.files[0];
  if (!file) return;
  showError("");
  try {
    photo.source = await loadImage(file);
    photo.zoom = 1;
    $("zoom").value = 1;
    photo.cx = photo.source.width / 2;
    photo.cy = photo.source.height / 2;
    $("photo-picker").hidden = true;
    $("photo-editor").hidden = false; // unhide BEFORE drawing, or clientWidth is 0
    renderPreview();
  } catch (err) {
    photo.source = null;
    showError(err.message);
  }
  event.target.value = ""; // lets "Retake" pick the same file again if needed
}

// Camera button and photo-library link both feed the same editor.
$("photo").addEventListener("change", handlePhotoChosen);
$("photo-library").addEventListener("change", handlePhotoChosen);

// Pointer Events handle mouse, finger, and stylus with the same code.
const previewCanvas = $("photo-canvas");
let drag = null;

previewCanvas.addEventListener("pointerdown", (event) => {
  drag = { x: event.clientX, y: event.clientY };
  previewCanvas.setPointerCapture(event.pointerId); // keep tracking even if the finger slides off
});

previewCanvas.addEventListener("pointermove", (event) => {
  if (!drag || !photo.source) return;
  const pixelsPerScreenPixel = cropSide() / previewCanvas.clientWidth;
  // Minus sign: dragging the photo right means the crop center moves left.
  photo.cx -= (event.clientX - drag.x) * pixelsPerScreenPixel;
  photo.cy -= (event.clientY - drag.y) * pixelsPerScreenPixel;
  drag = { x: event.clientX, y: event.clientY };
  clampCenter();
  renderPreview();
});

const endDrag = () => { drag = null; };
previewCanvas.addEventListener("pointerup", endDrag);
previewCanvas.addEventListener("pointercancel", endDrag);

$("zoom").addEventListener("input", (event) => {
  photo.zoom = Number(event.target.value);
  clampCenter(); // zooming out can push the crop past an edge
  renderPreview();
});

// ---------- Submit ----------

$("join-form").addEventListener("submit", async (event) => {
  event.preventDefault(); // stop the browser from doing a full page reload
  const name = $("name").value.trim();
  if (!name) return showError("Enter your name.");
  if (!selectedGroupId) return showError("Pick a group.");
  if (!photo.source) return showError("Take a selfie.");

  $("submit").disabled = true;
  showError("");
  try {
    const form = new FormData();
    form.append("name", name);
    form.append("group_id", selectedGroupId);
    form.append("photo", await exportPhoto(), "selfie.jpg");

    const res = await fetch("/api/join", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      showError(typeof data.detail === "string" ? data.detail : "Something went wrong.");
      return;
    }
    saveToken(data.token);
    location.href = "/play";
  } catch {
    showError("Could not reach the server. Check your Wi-Fi and try again.");
  } finally {
    $("submit").disabled = false;
  }
});

(async () => {
  if (!(await checkExistingPlayer())) await loadGroups();
})();