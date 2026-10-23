const TOKEN_KEY = "taskmaster_token";
const SCREENS = ["waiting", "performing", "spectating", "judging", "removed"];
const $ = (id) => document.getElementById(id);

let socket = null;
let retryDelay = 1000;
let retryTimer = null;
let state = null;      // latest snapshot from the server

// The judge's local ballot. Stars tapped here stay on the phone until Lock in.
let draft = {};        // performer id -> stars
let draftTaskId = null;
let editing = false;   // true while changing an already locked ballot

function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showOnly(id) {
  for (const screen of SCREENS) $(screen).hidden = screen !== id;
}

function showError(message) {
  $("error").textContent = message;
}

// ---------- Rendering ----------

function render() {
  if (!state) return;
  if (!state.me) return showOnly("removed");

  $("me-photo").src = state.me.photo_url;
  $("me-name").textContent = state.me.name;

  const task = state.task;
  if (!task) return showOnly("waiting");
  if (task.role === "performer") {
    $("perform-title").textContent = task.title;
    return showOnly("performing");
  }
  if (task.role === "spectator") {
    $("spectate-title").textContent = task.title;
    return showOnly("spectating");
  }
  renderBallot(task);
  showOnly("judging");
}

function renderBallot(task) {
  if (draftTaskId !== task.id) {
    // A new task: start a fresh draft.
    draftTaskId = task.id;
    draft = {};
    editing = false;
    showError("");
  }
  // While locked and not editing, mirror the server. Otherwise keep the local draft,
  // so a snapshot arriving mid-tap (someone else locking in) never wipes your stars.
  if (task.locked && !editing) draft = { ...task.my_scores };

  const locked = task.locked && !editing;
  $("judge-title").textContent = task.title;
  $("judge-hint").textContent = locked
    ? "Locked in. You can still edit until voting closes."
    : "Score every performer from 1 to 5.";
  $("ballot").classList.toggle("locked", locked);

  $("ballot").replaceChildren(
    ...task.performers.map((performer) => {
      const row = el("div", "ballot-row");
      const img = el("img");
      img.src = performer.photo_url;
      img.alt = "";

      const stars = el("div", "stars");
      for (let n = 1; n <= 5; n++) {
        const star = el("button", "star", "★");
        star.type = "button";
        star.disabled = locked;
        star.setAttribute("aria-label", `${n} of 5 for ${performer.name}`);
        if ((draft[performer.id] || 0) >= n) star.classList.add("on");
        star.addEventListener("click", () => {
          draft[performer.id] = n;
          render();
        });
        stars.append(star);
      }
      row.append(img, el("span", "ballot-name", performer.name), stars);
      return row;
    })
  );

  $("lock-in").hidden = locked;
  $("edit").hidden = !locked;
}

// ---------- Actions ----------

$("lock-in").addEventListener("click", async () => {
  const task = state && state.task;
  if (!task) return;
  const missing = task.performers.filter((p) => !draft[p.id]);
  if (missing.length) {
    return showError(`Still need scores for: ${missing.map((p) => p.name).join(", ")}`);
  }

  $("lock-in").disabled = true;
  showError("");
  try {
    const res = await fetch("/api/ballot", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Player-Token": getToken() || "" },
      body: JSON.stringify({
        task_id: task.id,
        scores: task.performers.map((p) => ({ performer_id: p.id, stars: draft[p.id] })),
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showError(typeof data.detail === "string" ? data.detail : "Something went wrong.");
      return;
    }
    editing = false;
    render();
  } catch {
    showError("Could not reach the server. Try again.");
  } finally {
    $("lock-in").disabled = false;
  }
});

$("edit").addEventListener("click", () => {
  editing = true;
  render();
});

$("start-over").addEventListener("click", () => {
  if (!confirm("Start over as a new player? This phone will forget who you are.")) return;
  clearToken();
  location.replace("/join");
});

// ---------- Connection ----------

function connect() {
  clearTimeout(retryTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws/player`);
  socket.onopen = () => {
    socket.send(JSON.stringify({ token: getToken() }));
    retryDelay = 1000;
    $("status").hidden = true;
  };
  socket.onmessage = (event) => {
    state = JSON.parse(event.data);
    render();
  };
  socket.onclose = (event) => {
    if (event.code === 4401) {
      clearToken();
      location.replace("/join");
      return;
    }
    $("status").hidden = false;
    retryTimer = setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 10000);
  };
}

// Phones freeze background tabs. When the screen wakes up, reconnect right away
// instead of waiting out the backoff timer.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && (!socket || socket.readyState === WebSocket.CLOSED)) {
    retryDelay = 1000;
    connect();
  }
});

if (getToken()) connect();
else location.replace("/join");