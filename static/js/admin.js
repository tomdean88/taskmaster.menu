const TOKEN_KEY = "taskmaster_admin_token";
const $ = (id) => document.getElementById(id);
let socket = null;
let retryDelay = 1000;

function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* ignore */ }
}

// Build elements with textContent only, never innerHTML.
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, onClick, className = "small-button") {
  const b = el("button", className, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function showError(message) {
  $("error").textContent = message;
}

// ---------- Login and connection ----------

function showLogin() {
  setToken(null);
  if (socket) {
    socket.onclose = null; // stop the auto-reconnect
    socket.close();
    socket = null;
  }
  $("panel-section").hidden = true;
  $("login-section").hidden = false;
}

function showPanel() {
  $("login-section").hidden = true;
  $("panel-section").hidden = false;
  connect();
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws/admin`);
  socket.onopen = () => {
    socket.send(JSON.stringify({ token: getToken() })); // prove who we are first
    retryDelay = 1000;
    $("status").hidden = true;
  };
  socket.onmessage = (event) => render(JSON.parse(event.data));
  socket.onclose = (event) => {
    if (event.code === 4401) return showLogin(); // bad or expired login
    $("status").hidden = false;
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 10000);
  };
}

// Send an action. We never update the screen here: the server
// broadcasts a fresh snapshot, and render() draws it.
async function api(method, path, body) {
  showError("");
  try {
    const res = await fetch(`/api/admin${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-Admin-Token": getToken() || "" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) {
      showLogin();
      return false;
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showError(typeof data.detail === "string" ? data.detail : "Something went wrong.");
      return false;
    }
    return true;
  } catch {
    showError("Could not reach the server.");
    return false;
  }
}

// ---------- Rendering ----------

function render(state) {
  for (const b of document.querySelectorAll("[data-mode]")) {
    b.classList.toggle("selected", b.dataset.mode === state.mode);
  }
  renderTaskGroupOptions(state.groups);
  renderTasks(state.tasks);
  renderPlayers(state.players, state.groups);
  renderGroups(state.groups);
}

function renderTaskGroupOptions(groups) {
  const select = $("task-group");
  const previous = select.value; // keep Lauren's choice when a snapshot redraws the list
  const options = groups.map((g) => {
    const option = el("option", "", `${g.name} performs`);
    option.value = String(g.id);
    return option;
  });
  const finalOption = el("option", "", "Final");
  finalOption.value = "final";
  select.replaceChildren(...options, finalOption);
  if ([...select.options].some((o) => o.value === previous)) select.value = previous;
}

function renderTasks(tasks) {
  const upcoming = tasks.filter((t) => t.status !== "revealed");
  const completed = tasks.filter((t) => t.status === "revealed");

  $("tasks").replaceChildren(
    ...(upcoming.length ? upcoming.map(taskItem) : [el("p", "hint", "No upcoming tasks.")])
  );
  $("completed-summary").textContent = `Completed (${completed.length})`;
  $("completed-tasks").replaceChildren(...completed.map(taskItem));
  $("completed-wrap").hidden = completed.length === 0;
}

function taskItem(task) {
  const info = el("div", "item-info");
  const who = task.stage === "final" ? "Final" : task.group_name;
  info.append(el("strong", "", task.title), el("span", "meta", `${who} · ${task.status}`));

  const actions = el("div", "item-actions");
  const resetTask = (question) => {
    if (confirm(question)) api("POST", `/tasks/${task.id}/reset`);
  };

  if (task.status === "draft") {
    actions.append(button("Start", () => api("POST", `/tasks/${task.id}/start`), "small-button primary"));
  } else if (task.status === "active") {
    actions.append(
      button("Reveal", () => {
        if (confirm(`Close voting and reveal "${task.title}"?`)) api("POST", `/tasks/${task.id}/reveal`);
      }, "small-button primary"),
      button("Cancel", () => resetTask(
        `Cancel "${task.title}"? Any ballots cast so far are discarded, and it goes back to Queue.`
      ))
    );
  } else if (task.status === "revealed") {
    actions.append(
      button("Reopen", () => {
        if (confirm(`Reopen voting on "${task.title}"? Its points leave the board until you reveal again.`)) {
          api("POST", `/tasks/${task.id}/reopen`);
        }
      }),
      button("Back to Queue", () => resetTask(
        `Move "${task.title}" back to Queue? Its ballots and points are cleared so it can be run again fresh.`
      ))
    );
  }

  if (task.status !== "revealed") {
    actions.append(
      button("↑", () => api("POST", `/tasks/${task.id}/move`, { direction: "up" })),
      button("↓", () => api("POST", `/tasks/${task.id}/move`, { direction: "down" }))
    );
  }

  actions.append(
    button("Rename", () => {
      const title = prompt("New task title", task.title);
      if (title !== null) api("PATCH", `/tasks/${task.id}`, { title });
    })
  );

  if (task.status !== "active") {
    const warning = task.status === "revealed" ? " Its points are removed from the leaderboard." : "";
    actions.append(
      button("Delete", () => {
        if (confirm(`Delete "${task.title}"?${warning} This can't be undone.`)) api("DELETE", `/tasks/${task.id}`);
      }, "small-button danger")
    );
  }

  const item = el("div", task.status === "active" ? "item active-task" : "item");
  item.append(info, actions);

  // Performer controls once a task has started.
  if (task.performers.length) {
    const performers = el("div", "performers");
    for (const p of task.performers) {
      const row = el("div", "performer");
      row.append(el("span", "", p.name));
      const choices = el("div", "item-actions");
      for (const [value, label] of [["in", "In"], ["sat_out", "Sat out"], ["dq", "DQ"]]) {
        const b = button(label, () => api("PATCH", `/tasks/${task.id}/performers/${p.player_id}`, { status: value }));
        if (p.status === value) b.classList.add("selected");
        choices.append(b);
      }
      row.append(choices);
      performers.append(row);
    }
    item.append(performers);
  }
  return item;
}

function renderPlayers(players, groups) {
  const list = $("players");
  if (!players.length) return list.replaceChildren(el("p", "hint", "No players yet."));
  // Active players first, removed ones at the bottom.
  const sorted = [...players].sort((a, b) => Number(a.removed) - Number(b.removed));
  list.replaceChildren(
    ...sorted.map((player) => {
      const img = el("img");
      img.src = player.photo_url;
      img.alt = "";

      const group = groups.find((g) => g.id === player.group_id);
      const info = el("div", "item-info");
      info.append(
        el("strong", "", player.name),
        el("span", "meta", player.removed ? "Removed" : group ? group.name : "")
      );

      const actions = el("div", "item-actions");
      if (player.removed) {
        actions.append(button("Restore", () => api("PATCH", `/players/${player.id}`, { removed: false })));
      } else {
        for (const g of groups) {
          if (g.id !== player.group_id) {
            actions.append(button(`To ${g.name}`, () => api("PATCH", `/players/${player.id}`, { group_id: g.id })));
          }
        }
        actions.append(
          button("Rename", () => {
            const name = prompt("New name", player.name);
            if (name !== null) api("PATCH", `/players/${player.id}`, { name });
          }),
          button("Remove", () => {
            if (confirm(`Remove ${player.name}?`)) api("PATCH", `/players/${player.id}`, { removed: true });
          }, "small-button danger")
        );
      }

      const item = el("div", player.removed ? "item removed" : "item");
      item.append(img, info, actions);
      return item;
    })
  );
}

function renderGroups(groups) {
  $("groups").replaceChildren(
    ...groups.map((group) => {
      const info = el("div", "item-info");
      info.append(el("strong", "", group.name));
      const actions = el("div", "item-actions");
      actions.append(
        button("Rename", () => {
          const name = prompt("New group name", group.name);
          if (name !== null) api("PATCH", `/groups/${group.id}`, { name });
        })
      );
      const item = el("div", "item");
      item.append(info, actions);
      return item;
    })
  );
}

// ---------- Event wiring ----------

for (const b of document.querySelectorAll("[data-mode]")) {
  b.addEventListener("click", () => api("PUT", "/tv-mode", { mode: b.dataset.mode }));
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("login-error").textContent = "";
  try {
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("password").value }),
    });
    if (!res.ok) {
      $("login-error").textContent = "Wrong password.";
      return;
    }
    setToken((await res.json()).token);
    $("password").value = "";
    showPanel();
  } catch {
    $("login-error").textContent = "Could not reach the server.";
  }
});

$("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("task-title").value.trim();
  if (!title) return showError("Enter a task title.");
  const choice = $("task-group").value;
  const body = choice === "final"
    ? { title, stage: "final" }
    : { title, stage: "group", group_id: Number(choice) };
  if (await api("POST", "/tasks", body)) $("task-title").value = ""; // only clear on success
});

$("logout").addEventListener("click", showLogin);

// Start: try the saved token. If it's stale, the socket closes with 4401 and we show login.
if (getToken()) showPanel();
else showLogin();