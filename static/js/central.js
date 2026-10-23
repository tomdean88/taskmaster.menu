const $ = (id) => document.getElementById(id);
const MODES = ["lobby", "game", "results", "champion"];
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

function upNextLine(state) {
  const next = state.up_next;
  if (!next) return "";
  return next.stage === "final" ? "Up next: the final!" : `Up next: ${next.group_name} performs`;
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

  let banner = upNextLine(state) || "Waiting for the next task";
  if (task && task.stage === "final") banner = `The final: ${task.title}`;
  else if (task) banner = `Now: ${task.title}${task.group_name ? ` (${task.group_name})` : ""}`;
  $("task-banner").textContent = banner;

  $("vote-count").textContent = task
    ? `${task.locked_count} of ${task.judge_count} judges locked in`
    : "";

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

function renderResults(state) {
  const result = state.last_result;

  let title = "No results yet";
  if (result && result.stage === "final") title = `Final results: ${result.title}`;
  else if (result) title = `Results: ${result.title}${result.group_name ? ` (${result.group_name})` : ""}`;
  $("results-title").textContent = title;

  $("results-rows").replaceChildren(
    ...(result ? result.rows : []).map((row) => {
      const line = el("div", "result-line");
      const detail = row.status === "dq" ? "Disqualified" : `${row.total} from the judges`;
      line.append(
        avatar(row),
        el("span", "name", row.name),
        el("span", "detail", detail),
        el("span", "award", `+${row.points}`)
      );
      return line;
    })
  );
  $("results-next").textContent = upNextLine(state);
}

function renderChampion(state) {
  const { finalists, champion_ids: championIds } = state.final;
  const champions = finalists.filter((p) => championIds.includes(p.id));

  if (champions.length) {
    $("champion-kicker").textContent = champions.length > 1
      ? "It's a tie! Your co-champions are..."
      : "Your Taskmaster champion is...";
    $("champion-faces").replaceChildren(...champions.map(avatar));
    $("champion-name").textContent = champions.map((p) => p.name).join(" & ");
  } else {
    $("champion-kicker").textContent = "The final is still to come";
    $("champion-faces").replaceChildren();
    $("champion-name").textContent = "";
  }

  $("final-scores").replaceChildren(
    ...finalists.map((p) => {
      const line = el("div", "final-line");
      line.append(el("span", "name", p.name), el("span", "award", `${p.final_points} pts`));
      return line;
    })
  );
}

function render(state) {
  for (const mode of MODES) $(mode).hidden = state.mode !== mode;
  for (const node of document.querySelectorAll(".join-url")) node.textContent = state.join_url;
  renderLobby(state);
  renderGame(state);
  renderResults(state);
  renderChampion(state);
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