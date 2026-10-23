const $ = (id) => document.getElementById(id);
let retryDelay = 1000;

// Build elements with textContent only, never innerHTML, so names can't inject code.
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

function renderLobby(state) {
  const count = state.joined_order.length;
  $("joined-count").textContent = `${count} ${count === 1 ? "player" : "players"} joined`;
  $("lobby-faces").replaceChildren(
    ...state.joined_order.map((player) => {
      const face = el("div", "face");
      face.append(avatar(player), el("span", "", player.name));
      return face;
    })
  );
}

function renderGame(state) {
  const task = state.current_task;
  $("task-banner").textContent = task
    ? `Now: ${task.title}${task.group_name ? ` (${task.group_name})` : ""}`
    : "Waiting for the next task";

  $("boards").replaceChildren(
    ...state.boards.map((board) => {
      const column = el("div", "board");
      column.append(el("h2", "", board.name));
      for (const player of board.players) {
        const row = el("div", "row");
        row.append(avatar(player), el("span", "name", player.name), el("span", "points", String(player.points)));
        column.append(row);
      }
      return column;
    })
  );
}

function render(state) {
  $("lobby").hidden = state.mode !== "lobby";
  $("game").hidden = state.mode !== "game";
  for (const node of document.querySelectorAll(".join-url")) node.textContent = state.join_url;
  renderLobby(state);
  renderGame(state);
  $("vote-count").textContent = task
    ? `${task.locked_count} of ${task.judge_count} judges locked in`
    : "";
}

function connect() {
  // Behind the Cloudflare tunnel the page is HTTPS, which requires secure WebSockets (wss).
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws/central`);

  socket.addEventListener("open", () => {
    retryDelay = 1000;
    $("status").hidden = true;
  });
  socket.addEventListener("message", (event) => render(JSON.parse(event.data)));
  socket.addEventListener("close", () => {
    $("status").hidden = false;
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 10000); // 1s, 2s, 4s, 8s, then every 10s
  });
}

connect();