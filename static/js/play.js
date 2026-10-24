const TOKEN_KEY = "taskmaster_token";
const SCREENS = ["waiting", "performing", "spectating", "judging", "removed"];
const TABS = ["play", "board", "me"];
const $ = (id) => document.getElementById(id);

let socket = null;
let retryDelay = 1000;
let retryTimer = null;
let state = null;      // latest snapshot from the server
let lastTaskId = null; // detects when a NEW task starts

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

function avatar(player) {
  const img = el("img");
  img.src = player.photo_url;
  img.alt = "";
  return img;
}

function showOnly(id) {
  for (const screen of SCREENS) $(screen).hidden = screen !== id;
}

function showTab(name) {
  for (const tab of TABS) $(`tab-${tab}`).hidden = tab !== name;
  for (const b of document.querySelectorAll("[data-tab]")) {
    b.classList.toggle("selected", b.dataset.tab === name);
  }
  render();
}

function currentTab() {
  return TABS.find((tab) => !$(`tab-${tab}`).hidden);
}

function showError(message) {
  $("error").textContent = message;
}

// Ties share a rank: your rank is 1 + the number of people strictly ahead of you.
function rankIn(board, player) {
  return board.players.filter((other) => other.points > player.points).length + 1;
}

function ordinal(n) {
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[n % 100 >= 11 && n % 100 <= 13 ? 0 : n % 10] || "th";
  return `${n}${suffix}`;
}

// ---------- Rendering ----------

function render() {
  if (!state) return;
  if (!state.me) {
    for (const tab of TABS) $(`tab-${tab}`).hidden = tab !== "play"; // the message lives on Play
    showOnly("removed");
    return;
  }

  $("me-photo").src = state.me.photo_url;
  $("me-name").textContent = state.me.name;

  renderPlay();
  renderBoards();
  renderMe();

  // Red dot on Play when a ballot is waiting and you're looking at another tab.
  const task = state.task;
  const ballotWaiting = task && task.role === "judge" && (!task.locked || editing);
  $("play-tab").classList.toggle("attention", Boolean(ballotWaiting) && currentTab() !== "play");
}

// Which group is up next. The title is never sent, so tasks stay a surprise.
function upNextText() {
  const next = state.up_next;
  if (!next) return "";
  if (next.stage === "final") return "Up next: the final!";
  return next.group_id === state.me.group_id
    ? `Up next: ${next.group_name} performs. That's you!`
    : `Up next: ${next.group_name} performs. You'll be judging.`;
}

function renderPlay() {
  const task = state.task;
  if (!task) {
    $("up-next").textContent = upNextText();
    return showOnly("waiting");
  }
  if (task.role === "performer") {
    $("perform-title").textContent = task.title;
    $("perform-hint").textContent = task.stage === "final"
      ? "You're in the final. Good luck!"
      : "You're performing. Good luck!";
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
  $("judge-title").textContent = task.stage === "final" ? `The final: ${task.title}` : task.title;
  $("judge-hint").textContent = locked
    ? "Locked in. You can still edit until voting closes."
    : "Score every performer from 1 to 5.";
  $("ballot").classList.toggle("locked", locked);

  $("ballot").replaceChildren(
    ...task.performers.map((performer) => {
      const row = el("div", "ballot-row");
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
      row.append(avatar(performer), el("span", "ballot-name", performer.name), stars);
      return row;
    })
  );

  $("lock-in").hidden = locked;
  $("edit").hidden = !locked;
}

function renderBoards() {
  $("phone-boards").replaceChildren(
    ...state.boards.map((board) => {
      const section = el("section", "phone-board");
      section.append(el("h2", "", board.name));
      for (const player of board.players) {
        const row = el("div", player.id === state.me.id ? "rank-row me" : "rank-row");
        row.append(
          el("span", "rank", String(rankIn(board, player))),
          avatar(player),
          el("span", "rank-name", player.name),
          el("span", "rank-points", String(player.points))
        );
        section.append(row);
      }
      return section;
    })
  );
}

function renderMe() {

  const board = state.boards.find((b) => b.players.some((p) => p.id === state.me.id));
  const mine = board && board.players.find((p) => p.id === state.me.id);
  $("me-stats").textContent = mine
    ? `${ordinal(rankIn(board, mine))} of ${board.players.length} in ${board.name} · ${mine.points} points`
    : "";

  const rows = state.my_results.map((result) => {
    const row = el("div", "result-row");
    const label = result.note ? `${result.title} (${result.note})` : result.title;
    const points = result.points === null ? "–" : `${result.points} pts`;
    row.append(el("span", "", label), el("span", "result-points", points));
    return row;
  });
  if (state.bonus) {
    const row = el("div", "result-row");
    row.append(
      el("span", "", "Host adjustments"),
      el("span", "result-points", `${state.bonus > 0 ? "+" : ""}${state.bonus} pts`)
    );
    rows.push(row);
  }
  if (!rows.length) rows.push(el("p", "hint", "No results yet. They appear after each reveal."));
  $("my-results").replaceChildren(...rows);
}

// ---------- Actions ----------

for (const b of document.querySelectorAll("[data-tab]")) {
  b.addEventListener("click", () => showTab(b.dataset.tab));
}

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

// ---------- Connection ----------

function handleSnapshot(snapshot) {
  state = snapshot;
  const taskId = state.task ? state.task.id : null;
  if (taskId !== null && taskId !== lastTaskId) {
    lastTaskId = taskId;
    showTab("play"); // a new task started: bring everyone to it (showTab also renders)
    return;
  }
  lastTaskId = taskId;
  render();
}

function connect() {
  clearTimeout(retryTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws/player`);
  socket.onopen = () => {
    socket.send(JSON.stringify({ token: getToken() }));
    retryDelay = 1000;
    $("status").hidden = true;
  };
  socket.onmessage = (event) => handleSnapshot(JSON.parse(event.data));
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