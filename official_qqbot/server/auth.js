const crypto = require("node:crypto");

class SessionStore {
  constructor({ ttlMs = 24 * 60 * 60 * 1000 } = {}) {
    this.ttlMs = ttlMs;
    this.sessions = new Map();
  }

  create(username) {
    const token = crypto.randomBytes(32).toString("hex");
    this.sessions.set(token, {
      username,
      expiresAt: Date.now() + this.ttlMs,
    });
    return token;
  }

  get(token) {
    if (!token) return null;
    const session = this.sessions.get(token);
    if (!session) return null;
    if (session.expiresAt <= Date.now()) {
      this.sessions.delete(token);
      return null;
    }
    return session;
  }

  delete(token) {
    this.sessions.delete(token);
  }
}

function parseCookie(header = "") {
  return Object.fromEntries(
    header
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const index = part.indexOf("=");
        if (index === -1) return [part, ""];
        return [part.slice(0, index), decodeURIComponent(part.slice(index + 1))];
      })
  );
}

function sessionCookie(token) {
  return `qqbot_session=${encodeURIComponent(token)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400`;
}

function clearSessionCookie() {
  return "qqbot_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0";
}

module.exports = {
  SessionStore,
  clearSessionCookie,
  parseCookie,
  sessionCookie,
};

