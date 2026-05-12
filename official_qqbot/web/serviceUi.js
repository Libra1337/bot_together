function canStartService(service = {}) {
  return !service.running && !service.disabled;
}

function startDisabledReason(service = {}) {
  if (service.running) return "服务已在运行";
  if (service.disabled) return "服务未配置";
  return "";
}

function blockedStartHint(service = {}) {
  if (service.state !== "blocked") return "";
  const message = service.health?.message || "依赖服务还没有准备好";
  return `还不能启动：${message}。请先打开对应 NapCat WebUI 扫码登录，等 OneBot 端口连通后再启动。`;
}

function resolveServiceWebUrl(serviceWebUrl = "", currentHost = "") {
  if (!serviceWebUrl) return "";

  try {
    const url = new URL(serviceWebUrl, "http://localhost");
    if (currentHost && ["127.0.0.1", "localhost", "::1"].includes(url.hostname)) {
      url.hostname = currentHost;
    }
    return url.toString();
  } catch {
    if (currentHost && /\/\/(?:127\.0\.0\.1|localhost|::1)(?::\d+)?/i.test(serviceWebUrl)) {
      return serviceWebUrl.replace(
        /\/\/(?:127\.0\.0\.1|localhost|::1)(?::\d+)?/i,
        `//${currentHost}`
      );
    }
    return serviceWebUrl;
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    canStartService,
    startDisabledReason,
    blockedStartHint,
    resolveServiceWebUrl,
  };
}

if (typeof window !== "undefined") {
  window.serviceUi = {
    canStartService,
    startDisabledReason,
    blockedStartHint,
    resolveServiceWebUrl,
  };
}
