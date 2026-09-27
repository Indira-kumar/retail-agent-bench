const state = {
  experiment: null,
  summaries: [],
  tasks: new Map(),
  selectedTaskId: null,
  selectedTrial: null,
  taskQuery: "",
  statusFilter: "all",
  eventMode: "signal",
  eventQuery: "",
  events: [],
  run: null,
  loadToken: 0,
};

const elements = {
  experimentName: document.querySelector("#experiment-name"),
  experimentSummary: document.querySelector("#experiment-summary"),
  taskSearch: document.querySelector("#task-search"),
  taskList: document.querySelector("#task-list"),
  loadingState: document.querySelector("#loading-state"),
  runView: document.querySelector("#run-view"),
  runBreadcrumb: document.querySelector("#run-breadcrumb"),
  runTitle: document.querySelector("#run-title"),
  trialSwitcher: document.querySelector("#trial-switcher"),
  scenario: document.querySelector("#scenario"),
  knownInfo: document.querySelector("#known-info"),
  runStats: document.querySelector("#run-stats"),
  inputAudio: document.querySelector("#input-audio"),
  outputAudio: document.querySelector("#output-audio"),
  eventSearch: document.querySelector("#event-search"),
  eventCount: document.querySelector("#event-count"),
  timeline: document.querySelector("#timeline"),
  actionChecks: document.querySelector("#action-checks"),
  failureNote: document.querySelector("#failure-note"),
  policySections: document.querySelector("#policy-sections"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds))) return "—";
  const total = Math.round(Number(seconds));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function truncate(value, limit = 1000) {
  const text = String(value ?? "");
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}\n\n… ${text.length - limit} more characters. Inspect event data for the full value.`;
}

async function fetchText(path, optional = false) {
  const response = await fetch(path, { cache: "no-store" });
  if (optional && response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} while reading ${path}`);
  return response.text();
}

async function fetchJson(path, optional = false) {
  const text = await fetchText(path, optional);
  return text === null ? null : JSON.parse(text);
}

function groupRuns() {
  return state.summaries.reduce((groups, summary) => {
    const key = String(summary.task_id);
    const runs = groups.get(key) ?? [];
    runs.push(summary);
    runs.sort((left, right) => Number(left.trial) - Number(right.trial));
    groups.set(key, runs);
    return groups;
  }, new Map());
}

function taskPassesStatus(runs) {
  if (state.statusFilter === "all") return true;
  const passed = runs.some((run) => Number(run.reward) === 1);
  return state.statusFilter === "passed" ? passed : !passed;
}

function renderTaskList() {
  const groups = groupRuns();
  const query = state.taskQuery.trim().toLowerCase();
  const items = [...groups.entries()].filter(([taskId, runs]) => {
    const task = state.tasks.get(taskId);
    const reason = task?.user_scenario?.instructions?.reason_for_call ?? "";
    return taskPassesStatus(runs) && `${taskId} ${reason}`.toLowerCase().includes(query);
  });

  if (!items.length) {
    elements.taskList.innerHTML = '<p class="no-tasks">No tasks match this view.</p>';
    return;
  }

  elements.taskList.innerHTML = items
    .map(([taskId, runs]) => {
      const task = state.tasks.get(taskId);
      const reason = task?.user_scenario?.instructions?.reason_for_call ?? "Task details unavailable";
      const mean = runs.reduce((sum, run) => sum + Number(run.reward ?? 0), 0) / runs.length;
      const passed = mean === 1;
      return `
        <button class="task-item ${taskId === state.selectedTaskId ? "active" : ""}" data-task-id="${escapeHtml(taskId)}">
          <span class="task-item-header">
            <span class="task-number">Task ${escapeHtml(taskId)}</span>
            <span class="task-result ${passed ? "passed" : ""}">${mean.toFixed(2)}</span>
          </span>
          <span class="task-reason">${escapeHtml(reason)}</span>
        </button>`;
    })
    .join("");
}

function renderExperimentSummary() {
  const total = state.summaries.length;
  const passed = state.summaries.filter((run) => Number(run.reward) === 1).length;
  const tasks = new Set(state.summaries.map((run) => String(run.task_id))).size;
  elements.experimentName.textContent = state.experiment.experiment_id;
  elements.experimentSummary.innerHTML = `<strong>${tasks}</strong> tasks &nbsp; <strong>${total}</strong> trials &nbsp; <strong>${passed}/${total}</strong> passed`;
}

function renderTrialSwitcher() {
  const runs = groupRuns().get(state.selectedTaskId) ?? [];
  elements.trialSwitcher.innerHTML = runs
    .map(
      (run) => `
        <button class="trial-button ${Number(run.reward) === 1 ? "passed" : ""} ${Number(run.trial) === state.selectedTrial ? "active" : ""}" data-trial="${Number(run.trial)}">
          Trial ${Number(run.trial)}
          <span>${Number(run.reward ?? 0).toFixed(2)}</span>
        </button>`,
    )
    .join("");
}

function parseEvents(text) {
  if (!text) return [];
  return text
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line, index) => {
      const record = JSON.parse(line);
      return { ...record.event, sourceIndex: index };
    })
    .filter((event) => event && event.occurred_at)
    .sort((left, right) => {
      const order = Date.parse(left.occurred_at) - Date.parse(right.occurred_at);
      return order || left.sourceIndex - right.sourceIndex;
    });
}

function conversationItem(event) {
  if (event.kind !== "session.event" || event.payload?.event_name !== "conversation_item_added") {
    return null;
  }
  const item = event.payload?.event?.item;
  if (item?.type !== "message" || !["assistant", "user"].includes(item.role)) return null;
  const content = Array.isArray(item.content) ? item.content.join("\n") : item.content;
  if (!content) return null;
  return {
    type: item.role,
    role: item.role === "assistant" ? "Agent (LLM → TTS)" : "Customer (STT)",
    kind: item.interrupted ? "interrupted message" : "message",
    content,
    details: item.metrics ?? {},
  };
}

function toolItem(event) {
  const payload = event.payload ?? {};
  if (event.kind === "tool.call.started") {
    return {
      type: "tool-start",
      role: "Tool call",
      kind: payload.tool_name,
      content: JSON.stringify(payload.arguments ?? {}, null, 2),
      details: payload,
    };
  }
  if (event.kind === "tool.call.completed") {
    const result = payload.serialized_result ?? payload.result;
    return {
      type: "tool-complete",
      role: "Tool result",
      kind: payload.tool_name,
      content: truncate(typeof result === "string" ? result : JSON.stringify(result, null, 2)),
      details: payload,
    };
  }
  if (event.kind === "tool.call.failed") {
    return {
      type: "tool-failed",
      role: "Tool error",
      kind: payload.tool_name,
      content: `${payload.error_type ?? "Error"}: ${payload.error_message ?? "Unknown tool failure"}`,
      details: payload,
    };
  }
  return null;
}

function systemItem(event) {
  const payload = event.payload ?? {};
  const eventName = payload.event_name ?? event.kind;
  const nested = payload.event ?? {};
  let content = `${event.source ?? "runtime"} · ${eventName}`;
  if (nested.old_state || nested.new_state) {
    content = `${nested.old_state ?? "unknown"} → ${nested.new_state ?? "unknown"}`;
  } else if (eventName === "user_input_transcribed") {
    content = nested.transcript ?? nested.text ?? content;
  } else if (eventName === "close") {
    content = nested.reason ?? nested.error ?? content;
  }
  const isError = String(event.kind).includes("failed") || eventName === "error";
  return {
    type: isError ? "error" : "system",
    role: isError ? "Runtime error" : "Runtime event",
    kind: eventName,
    content,
    details: payload,
  };
}

function timelineItem(event) {
  return conversationItem(event) ?? toolItem(event) ?? (state.eventMode === "all" ? systemItem(event) : null);
}

function elapsedLabel(timestamp, startTimestamp) {
  const elapsed = Math.max(0, Date.parse(timestamp) - startTimestamp) / 1000;
  const minutes = Math.floor(elapsed / 60);
  return `+${String(minutes).padStart(2, "0")}:${(elapsed % 60).toFixed(3).padStart(6, "0")}`;
}

function renderTimeline() {
  const startTimestamp = state.events.length ? Date.parse(state.events[0].occurred_at) : 0;
  const query = state.eventQuery.trim().toLowerCase();
  const rows = state.events
    .map((event) => ({ event, item: timelineItem(event) }))
    .filter(({ event, item }) => {
      if (!item) return false;
      return !query || JSON.stringify({ event, item }).toLowerCase().includes(query);
    });

  elements.eventCount.textContent = `${rows.length} event${rows.length === 1 ? "" : "s"}`;
  if (!rows.length) {
    elements.timeline.innerHTML = '<div class="empty-timeline">No events match this view.</div>';
    return;
  }

  elements.timeline.innerHTML = rows
    .map(({ event, item }) => {
      const details = Object.keys(item.details ?? {}).length
        ? `<details class="event-details"><summary>Inspect event data</summary><pre class="json-block">${escapeHtml(JSON.stringify(item.details, null, 2))}</pre></details>`
        : "";
      return `
        <article class="timeline-item ${item.type}">
          <div class="event-time">
            <time datetime="${escapeHtml(event.occurred_at)}" title="${escapeHtml(event.occurred_at)}">${escapeHtml(event.occurred_at)}</time>
            <span>${elapsedLabel(event.occurred_at, startTimestamp)}</span>
          </div>
          <span class="event-node" aria-hidden="true"></span>
          <div class="event-card">
            <header class="event-heading">
              <span class="event-role">${escapeHtml(item.role)}</span>
              <span class="event-kind">${escapeHtml(item.kind)}</span>
            </header>
            <p class="event-content">${escapeHtml(item.content)}</p>
            ${details}
          </div>
        </article>`;
    })
    .join("");
}

function renderStats(summary, events) {
  const messages = events.filter((event) => conversationItem(event)).length;
  const toolStarts = events.filter((event) => event.kind === "tool.call.started").length;
  const toolFailures = events.filter((event) => event.kind === "tool.call.failed").length;
  const values = [
    ["Reward", Number(summary.reward ?? 0).toFixed(2), Number(summary.reward) === 1 ? "passed" : "failed"],
    ["Termination", summary.termination_reason ?? "—", ""],
    ["Duration", formatDuration(summary.duration_seconds), ""],
    ["Messages", messages, ""],
    ["Tool calls", toolStarts, ""],
    ["Tool errors", toolFailures, toolFailures ? "failed" : "passed"],
  ];
  elements.runStats.innerHTML = values
    .map(
      ([label, value, className]) => `
        <div class="stat">
          <span class="stat-label">${escapeHtml(label)}</span>
          <span class="stat-value ${className}">${escapeHtml(value)}</span>
        </div>`,
    )
    .join("");
}

function renderEvaluation(score, failure) {
  const checks = score?.action_checks ?? [];
  elements.actionChecks.innerHTML = checks.length
    ? checks
        .map((check) => {
          const matched = Boolean(check.action_match);
          return `
            <article class="action-check ${matched ? "matched" : ""}">
              <span class="action-status" title="${matched ? "Matched" : "Missing"}">${matched ? "✓" : "×"}</span>
              <div>
                <div class="action-name">${escapeHtml(check.action?.name ?? "Unknown action")}</div>
                <pre class="action-arguments">${escapeHtml(JSON.stringify(check.action?.arguments ?? {}, null, 2))}</pre>
              </div>
              <span class="action-type">${escapeHtml(check.tool_type ?? "")}</span>
            </article>`;
        })
        .join("")
    : '<p class="empty-timeline">No expected actions were recorded.</p>';

  const labels = failure?.labels ?? [];
  const breakdown = score?.reward_breakdown ?? {};
  elements.failureNote.innerHTML = `
    <h2>${labels.length ? "Failure signals" : "No failure labels"}</h2>
    <div class="failure-labels">
      ${labels.map((label) => `<span class="failure-label">${escapeHtml(label)}</span>`).join("")}
    </div>
    <div class="breakdown">
      ${Object.entries(breakdown)
        .map(([name, value]) => `<div class="breakdown-row"><span>${escapeHtml(name)}</span><strong>${Number(value).toFixed(2)}</strong></div>`)
        .join("")}
    </div>`;
}

function renderPolicy(relevantPolicy) {
  const sections = relevantPolicy?.sections ?? [];
  elements.policySections.innerHTML = sections.length
    ? sections
        .map(
          (section) => `
            <article class="policy-section">
              <h2>${escapeHtml(section.heading)}</h2>
              <pre class="policy-copy">${escapeHtml(cleanPolicy(section))}</pre>
            </article>`,
        )
        .join("")
    : '<p class="empty-timeline">No relevant policy sections were recorded.</p>';
}

function cleanPolicy(section) {
  const heading = String(section.heading ?? "").trim().toLowerCase();
  const lines = String(section.content ?? "").split(/\r?\n/);
  const firstContent = lines.findIndex((line) => line.trim());
  if (firstContent >= 0) {
    const firstLine = lines[firstContent].replace(/^#{1,6}\s+/, "").trim().toLowerCase();
    if (firstLine === heading) lines.splice(firstContent, 1);
  }
  return lines
    .join("\n")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`(.*?)`/g, "$1")
    .trim();
}

function updateHash() {
  const hash = new URLSearchParams({ task: state.selectedTaskId, trial: state.selectedTrial });
  history.replaceState(null, "", `#${hash}`);
}

async function selectRun(taskId, trial) {
  const runs = groupRuns().get(String(taskId)) ?? [];
  const summary = runs.find((run) => Number(run.trial) === Number(trial)) ?? runs[0];
  if (!summary) return;

  state.selectedTaskId = String(taskId);
  state.selectedTrial = Number(summary.trial);
  state.eventQuery = "";
  elements.eventSearch.value = "";
  const loadToken = ++state.loadToken;
  renderTaskList();
  renderTrialSwitcher();
  updateHash();

  const base = `/data/${summary.artifact_path}`;
  const [task, score, failure, simulation, relevantPolicy, eventText] = await Promise.all([
    fetchJson(`${base}/task.json`),
    fetchJson(`${base}/score.json`, true),
    fetchJson(`${base}/failure.json`, true),
    fetchJson(`${base}/simulation.json`, true),
    fetchJson(`${base}/relevant_policy.json`, true),
    fetchText(`${base}/events.jsonl`),
  ]);
  if (loadToken !== state.loadToken) return;

  state.events = parseEvents(eventText);
  state.run = { summary, task, score, failure, simulation, relevantPolicy };
  const instructions = task?.user_scenario?.instructions ?? {};
  elements.runBreadcrumb.textContent = `${state.experiment.experiment_id} / trial ${state.selectedTrial}`;
  elements.runTitle.textContent = `Task ${state.selectedTaskId}`;
  elements.scenario.textContent = instructions.reason_for_call ?? "No scenario description recorded.";
  const context = [instructions.known_info, instructions.unknown_info, instructions.task_instructions].filter(Boolean);
  elements.knownInfo.textContent = context.join(" · ");
  elements.inputAudio.src = `${base}/input.wav`;
  elements.outputAudio.src = `${base}/output.wav`;
  renderStats(summary, state.events);
  renderTimeline();
  renderEvaluation(score, failure);
  renderPolicy(relevantPolicy);
  elements.loadingState.hidden = true;
  elements.runView.hidden = false;
  document.title = `Task ${state.selectedTaskId} · ${state.experiment.experiment_id}`;
}

function activatePanel(name) {
  document.querySelectorAll(".panel-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === name);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `${name}-panel`);
  });
}

function bindEvents() {
  elements.taskSearch.addEventListener("input", (event) => {
    state.taskQuery = event.target.value;
    renderTaskList();
  });
  elements.taskList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-task-id]");
    if (!button) return;
    const runs = groupRuns().get(button.dataset.taskId) ?? [];
    selectRun(button.dataset.taskId, runs[0]?.trial);
  });
  document.querySelector(".status-filter").addEventListener("click", (event) => {
    const button = event.target.closest("[data-status]");
    if (!button) return;
    state.statusFilter = button.dataset.status;
    document.querySelectorAll("[data-status]").forEach((item) => item.classList.toggle("active", item === button));
    renderTaskList();
  });
  elements.trialSwitcher.addEventListener("click", (event) => {
    const button = event.target.closest("[data-trial]");
    if (button) selectRun(state.selectedTaskId, Number(button.dataset.trial));
  });
  document.querySelector(".panel-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-panel]");
    if (button) activatePanel(button.dataset.panel);
  });
  document.querySelector(".event-mode").addEventListener("click", (event) => {
    const button = event.target.closest("[data-event-mode]");
    if (!button) return;
    state.eventMode = button.dataset.eventMode;
    document.querySelectorAll("[data-event-mode]").forEach((item) => item.classList.toggle("active", item === button));
    renderTimeline();
  });
  elements.eventSearch.addEventListener("input", (event) => {
    state.eventQuery = event.target.value;
    renderTimeline();
  });
}

async function initialize() {
  bindEvents();
  try {
    const [experiment, summaries] = await Promise.all([
      fetchJson("/data/experiment.json"),
      fetchJson("/data/summary.json"),
    ]);
    state.experiment = experiment;
    state.summaries = summaries;
    const groups = groupRuns();
    await Promise.all(
      [...groups.entries()].map(async ([taskId, runs]) => {
        const task = await fetchJson(`/data/${runs[0].artifact_path}/task.json`);
        state.tasks.set(taskId, task);
      }),
    );
    renderExperimentSummary();
    renderTaskList();

    const hash = new URLSearchParams(location.hash.slice(1));
    const requestedTask = hash.get("task");
    const firstTask = groups.has(requestedTask) ? requestedTask : groups.keys().next().value;
    const requestedTrial = Number(hash.get("trial"));
    const trials = groups.get(firstTask) ?? [];
    const firstTrial = trials.some((run) => Number(run.trial) === requestedTrial) ? requestedTrial : trials[0]?.trial;
    await selectRun(firstTask, firstTrial);
  } catch (error) {
    elements.loadingState.innerHTML = `<div class="load-error"><strong>Could not load this experiment.</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

initialize();
