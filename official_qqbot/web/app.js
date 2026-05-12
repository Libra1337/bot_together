const state = {
  logs: [],
  services: [],
  eventSource: null,
  selectedLogService: "",
};

const serviceUi = window.serviceUi || {};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatUptime(seconds) {
  if (!seconds) return "-";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}h ${m}m ${s}s`;
}

function formatLog(entry) {
  const service = entry.serviceName || entry.serviceId || "bot";
  return `[${entry.ts}] [${service}] [${entry.stream}] ${entry.line}`;
}

function notify(message, type = "info") {
  const toast = $("#toast");
  if (!toast) {
    window.alert(message);
    return;
  }
  toast.textContent = message;
  toast.dataset.type = type;
  toast.classList.remove("hidden");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.add("hidden"), 7000);
}

function renderLogs() {
  const visibleLogs = state.selectedLogService
    ? state.logs.filter((entry) => entry.serviceId === state.selectedLogService)
    : state.logs;
  $("#recentLogs").textContent = state.logs.slice(-80).map(formatLog).join("\n");
  $("#fullLogs").textContent = visibleLogs.map(formatLog).join("\n");
  $("#fullLogs").scrollTop = $("#fullLogs").scrollHeight;
}

function renderPlugins(plugins) {
  $("#pluginCount").textContent = String(plugins.length);
  $("#pluginList").innerHTML = plugins
    .map(
      (plugin) => `
        <article class="plugin-item">
          <div>
            <h3>${escapeHtml(plugin.name)}</h3>
            <p>${escapeHtml(plugin.description || "无描述")}</p>
            <div class="plugin-meta">
              <span>ID: ${escapeHtml(plugin.id)}</span>
              <span>类型: ${escapeHtml(plugin.type)}</span>
              <span>命令: ${escapeHtml((plugin.commands || []).join(", ") || "-")}</span>
            </div>
          </div>
          <button data-plugin="${escapeHtml(plugin.id)}" data-enabled="${plugin.enabled}">
            ${plugin.enabled ? "停用" : "启用"}
          </button>
        </article>
      `
    )
    .join("");
}

function serviceStateText(service) {
  if (service.disabled) return "未配置";
  if (service.running) return "运行中";
  if (service.state === "blocked") return "等待 NapCat 登录";
  return "已停止";
}

function healthText(service) {
  if (!service.health || service.health.status === "none") return "无健康检查";
  return service.health.message || service.health.status;
}

function webUrlButton(service) {
  if (!service.webUrl) return "";
  const webUrl =
    serviceUi.resolveServiceWebUrl?.(service.webUrl, window.location.hostname) || service.webUrl;
  return `<a class="button ghost" href="${escapeHtml(webUrl)}" target="_blank" rel="noreferrer">打开 WebUI</a>`;
}

function startTitle(service) {
  if (service.state === "blocked") {
    return serviceUi.blockedStartHint?.(service) || "依赖还没准备好";
  }
  return serviceUi.startDisabledReason?.(service) || "启动";
}

function renderLogFilter() {
  const current = state.selectedLogService;
  $("#logServiceFilter").innerHTML = [
    '<option value="">全部服务</option>',
    ...state.services.map(
      (service) =>
        `<option value="${escapeHtml(service.id)}" ${
          service.id === current ? "selected" : ""
        }>${escapeHtml(service.name)}</option>`
    ),
  ].join("");
}

function renderServices(services) {
  state.services = services || [];
  const running = state.services.filter((service) => service.running).length;
  $("#serviceSummary").textContent = `${running}/${state.services.length} 运行中`;
  renderLogFilter();
  $("#serviceList").innerHTML = state.services
    .map((service) => {
      const canStart =
        serviceUi.canStartService?.(service) ?? (!service.running && !service.disabled);
      return `
        <article class="service-card" data-state="${escapeHtml(service.state)}">
          <div class="service-head">
            <div>
              <h3>${escapeHtml(service.name)}</h3>
              <p>${escapeHtml(service.kind || "process")} · ${escapeHtml(service.cwd || "-")}</p>
            </div>
            <span class="status-badge">${serviceStateText(service)}</span>
          </div>
          <dl class="service-meta">
            <dt>PID</dt>
            <dd>${service.pid || "-"}</dd>
            <dt>运行时间</dt>
            <dd>${formatUptime(service.uptimeSeconds)}</dd>
            <dt>健康检查</dt>
            <dd>${escapeHtml(healthText(service))}</dd>
          </dl>
          <div class="service-actions">
            <button class="primary" data-service-start="${escapeHtml(service.id)}" title="${escapeHtml(startTitle(service))}" ${
              canStart ? "" : "disabled"
            }>启动</button>
            <button class="danger" data-service-stop="${escapeHtml(service.id)}" ${
              !service.running ? "disabled" : ""
            }>停止</button>
            ${webUrlButton(service)}
          </div>
        </article>
      `;
    })
    .join("");
}

function renderStatus(data) {
  const { bot, services, plugins, config } = data;
  const serviceList = services || [];
  const runningCount = serviceList.filter((service) => service.running).length;
  $("#statusTitle").textContent = `${runningCount}/${serviceList.length} 个服务运行中`;
  $("#pidValue").textContent = bot?.pid || "-";
  $("#uptimeValue").textContent = formatUptime(bot?.uptimeSeconds || 0);
  $("#cfgHost").textContent = `${config.server.host}:${config.server.port}`;
  $("#cfgCommand").textContent = `${config.bot.command} ${config.bot.entry} ${(config.bot.args || []).join(" ")}`;
  $("#cfgServices").textContent = String(serviceList.length);
  $("#cfgPlugins").textContent = config.paths.pluginsDir;
  renderServices(serviceList);
  renderPlugins(plugins);
}

async function refreshStatus() {
  const data = await api("/api/status");
  renderStatus(data);
}

async function refreshLogs() {
  const serviceParam = state.selectedLogService
    ? `&serviceId=${encodeURIComponent(state.selectedLogService)}`
    : "";
  const data = await api(`/api/logs?limit=300${serviceParam}`);
  state.logs = data.logs || [];
  renderLogs();
}

function connectLogStream() {
  if (state.eventSource) {
    state.eventSource.close();
  }
  state.eventSource = new EventSource("/api/logs/stream", { withCredentials: true });
  state.eventSource.onmessage = (event) => {
    state.logs.push(JSON.parse(event.data));
    state.logs = state.logs.slice(-800);
    renderLogs();
  };
}

async function showApp() {
  $("#loginView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  await Promise.all([refreshStatus(), refreshLogs()]);
  connectLogStream();
}

function showLogin() {
  $("#appView").classList.add("hidden");
  $("#loginView").classList.remove("hidden");
}

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#loginError").textContent = "";
  try {
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("#username").value.trim(),
        password: $("#password").value,
      }),
    });
    await showApp();
  } catch (error) {
    $("#loginError").textContent = error.message;
  }
});

$("#logoutBtn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  showLogin();
});

$("#refreshBtn").addEventListener("click", async () => {
  await Promise.all([refreshStatus(), refreshLogs()]);
});

$("#reloadPluginsBtn").addEventListener("click", refreshStatus);

$("#clearLogsBtn").addEventListener("click", () => {
  state.logs = [];
  renderLogs();
});

$("#logServiceFilter").addEventListener("change", async (event) => {
  state.selectedLogService = event.target.value;
  await refreshLogs();
});

$("#serviceList").addEventListener("click", async (event) => {
  const startButton = event.target.closest("button[data-service-start]");
  const stopButton = event.target.closest("button[data-service-stop]");
  if (!startButton && !stopButton) return;

  const serviceId = startButton ? startButton.dataset.serviceStart : stopButton.dataset.serviceStop;
  const service = state.services.find((item) => item.id === serviceId);
  const action = startButton ? "start" : "stop";

  if (action === "start" && service?.state === "blocked") {
    notify(serviceUi.blockedStartHint?.(service) || "依赖还没准备好", "warn");
  }

  const id = encodeURIComponent(serviceId);
  const webWindow =
    action === "start" && service?.webUrl
      ? window.open("about:blank", "_blank", "noopener,noreferrer")
      : null;
  try {
    const result = await api(`/api/services/${id}/${action}`, { method: "POST" });
    if (action === "start" && result.service?.webUrl) {
      const webUrl =
        serviceUi.resolveServiceWebUrl?.(result.service.webUrl, window.location.hostname) ||
        result.service.webUrl;
      if (webWindow) {
        webWindow.location.href = webUrl;
      } else {
        window.open(webUrl, "_blank", "noopener,noreferrer");
      }
    } else if (webWindow) {
      webWindow.close();
    }
  } catch (error) {
    if (webWindow) webWindow.close();
    notify(error.message, "error");
  }
  await Promise.all([refreshStatus(), refreshLogs()]);
});

$("#pluginList").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-plugin]");
  if (!button) return;
  const id = encodeURIComponent(button.dataset.plugin);
  const action = button.dataset.enabled === "true" ? "disable" : "enable";
  await api(`/api/plugins/${id}/${action}`, { method: "POST" });
  await refreshStatus();
});

$$(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.remove("active"));
    $$(".view").forEach((view) => view.classList.remove("active"));
    button.classList.add("active");
    $(`#${button.dataset.view}`).classList.add("active");
  });
});

api("/api/me")
  .then(showApp)
  .catch(showLogin);

setInterval(() => {
  if (!$("#appView").classList.contains("hidden")) {
    refreshStatus().catch(() => {});
  }
}, 5000);
