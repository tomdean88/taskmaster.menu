const TOKEN_KEY = "taskmaster_token";
const PHOTO_SIZE = 512;

let selectedGroupId = null;
let photoBlob = null;

const $ = (id) => document.getElementById(id);

// localStorage can throw in some private-browsing modes, so wrap it.
function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function saveToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ignore */ }
}

function showJoined(player) {
  $("join-section").hidden = true;
  $("joined-section").hidden = false;
  $("me-photo").src = player.photo_url;
  $("me-name").textContent = player.name;
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
  showJoined(await res.json());
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

// Center-crop to a square and shrink to PHOTO_SIZE pixels as a JPEG.
function resizeToSquare(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const side = Math.min(img.naturalWidth, img.naturalHeight);
      const sx = (img.naturalWidth - side) / 2;
      const sy = (img.naturalHeight - side) / 2;
      const canvas = document.createElement("canvas");
      canvas.width = PHOTO_SIZE;
      canvas.height = PHOTO_SIZE;
      canvas.getContext("2d").drawImage(img, sx, sy, side, side, 0, 0, PHOTO_SIZE, PHOTO_SIZE);
      URL.revokeObjectURL(url);
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("Could not process that photo."))),
        "image/jpeg",
        0.85
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read that photo. Try another one."));
    };
    img.src = url;
  });
}

$("photo").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  showError("");
  try {
    photoBlob = await resizeToSquare(file);
    $("preview").src = URL.createObjectURL(photoBlob);
    $("preview").hidden = false;
    $("photo-hint").hidden = true;
  } catch (err) {
    photoBlob = null;
    showError(err.message);
  }
});

$("join-form").addEventListener("submit", async (event) => {
  event.preventDefault(); // stop the browser from doing a full page reload
  const name = $("name").value.trim();
  if (!name) return showError("Enter your name.");
  if (!selectedGroupId) return showError("Pick a group.");
  if (!photoBlob) return showError("Take a selfie.");

  const form = new FormData();
  form.append("name", name);
  form.append("group_id", selectedGroupId);
  form.append("photo", photoBlob, "selfie.jpg");

  $("submit").disabled = true;
  showError("");
  try {
    const res = await fetch("/api/join", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      showError(typeof data.detail === "string" ? data.detail : "Something went wrong.");
      return;
    }
    saveToken(data.token);
    showJoined(data.player);
  } catch {
    showError("Could not reach the server. Check your Wi-Fi and try again.");
  } finally {
    $("submit").disabled = false;
  }
});

(async () => {
  if (!(await checkExistingPlayer())) await loadGroups();
})();