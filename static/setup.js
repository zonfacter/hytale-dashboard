(function() {
  "use strict";

  function el(id) { return document.getElementById(id); }

  function kv(container, rows) {
    container.innerHTML = rows.map(([k, v]) =>
      `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`
    ).join("");
  }

  function toast(msg, type) {
    const t = document.createElement("div");
    t.className = `toast toast-${type || "success"}`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  async function api(url, opts) {
    try {
      const resp = await fetch(url, opts || {});
      if (resp.status === 401) { location.reload(); return null; }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        toast(err.detail || "Fehler", "error");
        return null;
      }
      return await resp.json();
    } catch (e) {
      toast("Netzwerkfehler: " + e.message, "error");
      return null;
    }
  }

  async function refreshAuthStatus() {
    const data = await api("/api/auth/status");
    if (!data) return;

    const tokenFile = data.token_file_exists
      ? '<span class="badge badge-active">Vorhanden</span>'
      : '<span class="badge badge-failed">Fehlt</span>';
    const tokenState = data.token_missing
      ? '<span class="badge badge-failed">Nicht konfiguriert</span>'
      : '<span class="badge badge-active">Konfiguriert</span>';
    const tokenGrant = data.token_error
      ? '<span class="badge badge-failed">Auth-Grant Fehler</span>'
      : '<span class="badge badge-active">Kein Grant-Fehler</span>';

    kv(el("authStatus"), [
      ["auth.enc", tokenFile],
      ["Server Token", tokenState],
      ["Grant Status", tokenGrant],
    ]);

    const lines = data.auth_lines || [];
    el("authLog").textContent = lines.length ? lines.join("\n") : "Keine Auth-Eintraege gefunden.";
  }

  async function refreshTokenBackups() {
    const data = await api("/api/token/backups");
    if (!data) return;

    const allowControl = document.body.dataset.allowControl === "true";
    const tbody = el("tokenBackupTable");
    const backups = data.backups || [];
    if (backups.length === 0) {
      const colspan = allowControl ? 4 : 3;
      tbody.innerHTML = `<tr><td colspan="${colspan}" class="muted">Keine Token-Backups</td></tr>`;
      return;
    }

    tbody.innerHTML = backups.map(b => {
      const action = allowControl
        ? `<button class="btn-restore-token" data-name="${b.name}">Restore</button>`
        : "";
      return `<tr>
        <td><code>${b.name}</code></td>
        <td>${b.size}</td>
        <td>${b.mtime}</td>
        ${allowControl ? `<td>${action}</td>` : ""}
      </tr>`;
    }).join("");

    tbody.querySelectorAll(".btn-restore-token").forEach(btn => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.name;
        if (!confirm(`Token-Backup '${name}' wiederherstellen? Server wird neu gestartet.`)) return;
        btn.disabled = true;
        const result = await api("/api/token/restore", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        if (result && result.ok) {
          toast("Token erfolgreich wiederhergestellt", "success");
          await refreshAuthStatus();
          await refreshTokenBackups();
        } else {
          btn.disabled = false;
        }
      });
    });
  }

  function setupActions() {
    async function sendAuthLogin(mode) {
      const payload = mode ? { mode } : {};
      let result = await api("/api/auth/login/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      // Backwards-compatible fallback for mixed runtime states:
      // if setup route wiring differs, send command via generic console API.
      if (!result) {
        const command = mode ? `/auth login ${mode}` : "/auth login";
        result = await api("/api/console/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command }),
        });
      }
      return result;
    }

    const authBtn = el("authLoginStart");
    if (authBtn) {
      authBtn.addEventListener("click", async () => {
        authBtn.disabled = true;
        const result = await sendAuthLogin("");
        if (result && result.ok) {
          toast(result.message || "Befehl gesendet", "success");
          setTimeout(refreshAuthStatus, 1500);
        }
        authBtn.disabled = false;
      });
    }

    const authBrowserBtn = el("authLoginBrowser");
    if (authBrowserBtn) {
      authBrowserBtn.addEventListener("click", async () => {
        authBrowserBtn.disabled = true;
        const result = await sendAuthLogin("browser");
        if (result && result.ok) {
          toast(result.message || "Browser-Login gesendet", "success");
          setTimeout(refreshAuthStatus, 1500);
        }
        authBrowserBtn.disabled = false;
      });
    }

    const authDeviceBtn = el("authLoginDevice");
    if (authDeviceBtn) {
      authDeviceBtn.addEventListener("click", async () => {
        authDeviceBtn.disabled = true;
        const result = await sendAuthLogin("device");
        if (result && result.ok) {
          toast(result.message || "Device-Login gesendet", "success");
          setTimeout(refreshAuthStatus, 1500);
        }
        authDeviceBtn.disabled = false;
      });
    }

    const authRefreshBtn = el("authStatusRefresh");
    if (authRefreshBtn) {
      authRefreshBtn.addEventListener("click", refreshAuthStatus);
    }

    const tokenBackupBtn = el("tokenBackupNow");
    if (tokenBackupBtn) {
      tokenBackupBtn.addEventListener("click", async () => {
        tokenBackupBtn.disabled = true;
        const result = await api("/api/token/backup", { method: "POST" });
        if (result && result.ok) {
          toast("Token-Backup erstellt", "success");
          await refreshTokenBackups();
        }
        tokenBackupBtn.disabled = false;
      });
    }
  }

  async function init() {
    setupActions();
    await refreshAuthStatus();
    await refreshTokenBackups();
  }

  init().catch(err => {
    console.error(err);
    toast("Setup-Seite konnte nicht geladen werden", "error");
  });
})();
