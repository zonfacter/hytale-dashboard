(function() {
  "use strict";

  function el(id) { return document.getElementById(id); }

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

  // --- Players ---
  async function refreshPlayers() {
    const data = await api("/api/players");
    if (!data) return;
    const tbody = el("playerTable");
    const players = data.players || [];
    if (players.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">Keine Spieler gefunden</td></tr>';
      return;
    }
    tbody.innerHTML = players.map(p => {
      const badge = p.online
        ? '<span class="badge badge-active">Online</span>'
        : '<span class="badge badge-inactive">Offline</span>';
      const login = p.last_login ? p.last_login.replace("T", " ").substring(0, 19) : "-";
      return `<tr>
        <td><strong>${p.name}</strong></td>
        <td>${badge}</td>
        <td>${login}</td>
        <td>${p.world || "-"}</td>
      </tr>`;
    }).join("");
  }

  // --- Console ---
  let consoleLastLine = "";

  async function refreshConsole() {
    const data = await api("/api/console/output");
    if (!data) return;
    const output = el("consoleOutput");
    if (output) {
      output.textContent = (data.lines || []).join("\n");
      output.scrollTop = output.scrollHeight;
    }
  }

  function setupConsole() {
    const input = el("consoleInput");
    const sendBtn = el("consoleSend");
    if (!input || !sendBtn) return;

    async function sendCommand() {
      const cmd = input.value.trim();
      if (!cmd) return;
      input.value = "";
      sendBtn.disabled = true;
      const result = await api("/api/console/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd }),
      });
      if (result && result.ok) {
        toast("Befehl gesendet: " + cmd);
      }
      sendBtn.disabled = false;
      setTimeout(refreshConsole, 1000);
    }

    sendBtn.addEventListener("click", sendCommand);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendCommand();
    });
  }

  // --- Config Editor ---
  let activeConfigTab = "serverConfig";

  async function loadConfigs() {
    const serverData = await api("/api/config/server");
    if (serverData) {
      el("serverConfigEditor").value = JSON.stringify(JSON.parse(serverData.content), null, 2);
    }
    const worldData = await api("/api/config/world");
    if (worldData) {
      el("worldConfigEditor").value = JSON.stringify(JSON.parse(worldData.content), null, 2);
    }
  }

  function setupConfig() {
    // Tab switching
    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        activeConfigTab = btn.dataset.tab;
        el(activeConfigTab + "Tab").classList.add("active");
      });
    });

    // Save
    const saveBtn = el("saveConfig");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const isServer = activeConfigTab === "serverConfig";
        const editor = el(isServer ? "serverConfigEditor" : "worldConfigEditor");
        const endpoint = isServer ? "/api/config/server" : "/api/config/world";

        if (!confirm("Konfiguration speichern?" + (isServer ? " Server-Neustart erforderlich." : ""))) return;

        saveBtn.disabled = true;
        const result = await api(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: editor.value }),
        });
        if (result && result.ok) {
          toast("Konfiguration gespeichert");
          el("configHint").hidden = !isServer;
        }
        saveBtn.disabled = false;
      });
    }
  }

  // --- Backup Management ---
  async function refreshBackups() {
    const data = await api("/api/backups/list");
    if (!data) return;
    const tbody = el("backupMgmtTable");
    const backups = data.backups || [];
    if (backups.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted">Keine Backups</td></tr>';
      return;
    }
    tbody.innerHTML = backups.map(b => {
      const typeBadge = b.type === "backup"
        ? '<span class="badge badge-active">Backup</span>'
        : '<span class="badge badge-inactive">Update</span>';
      const actions = `<button class="btn-del" data-name="${b.name}" data-type="${b.type}">Loeschen</button>`;
      return `<tr>
        <td><code>${b.name}</code></td>
        <td>${b.size}</td>
        <td>${b.mtime}</td>
        <td>${typeBadge}</td>
        <td>${actions}</td>
      </tr>`;
    }).join("");

    // Attach delete handlers
    tbody.querySelectorAll(".btn-del").forEach(btn => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.name;
        if (!confirm(`Backup '${name}' wirklich loeschen?`)) return;
        btn.disabled = true;
        const result = await api(`/api/backups/${encodeURIComponent(name)}`, { method: "DELETE" });
        if (result && result.ok) {
          toast("Backup geloescht");
          await refreshBackups();
        } else {
          btn.disabled = false;
        }
      });
    });
  }

  // --- Mod Management ---
  async function refreshMods() {
    const data = await api("/api/mods");
    if (!data) return;
    const tbody = el("modTable");
    const mods = data.mods || [];
    if (mods.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">Keine Mods installiert</td></tr>';
      return;
    }
    tbody.innerHTML = mods.map(m => {
      const badge = m.enabled
        ? '<span class="badge badge-active">Aktiv</span>'
        : '<span class="badge badge-inactive">Inaktiv</span>';
      const toggleLabel = m.enabled ? "Deaktivieren" : "Aktivieren";
      const actions = `<button class="btn-toggle" data-name="${m.name}">${toggleLabel}</button>
        <button class="btn-del" data-name="${m.name}">Loeschen</button>`;
      return `<tr>
        <td><strong>${m.name}</strong></td>
        <td>${badge}</td>
        <td>${m.size}</td>
        <td>${actions}</td>
      </tr>`;
    }).join("");

    // Toggle handlers
    tbody.querySelectorAll(".btn-toggle").forEach(btn => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        const result = await api(`/api/mods/${encodeURIComponent(btn.dataset.name)}/toggle`, { method: "POST" });
        if (result && result.ok) {
          toast(result.enabled ? "Mod aktiviert" : "Mod deaktiviert");
          await refreshMods();
        } else {
          btn.disabled = false;
        }
      });
    });

    // Delete handlers
    tbody.querySelectorAll(".btn-del").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm(`Mod '${btn.dataset.name}' wirklich loeschen?`)) return;
        btn.disabled = true;
        const result = await api(`/api/mods/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
        if (result && result.ok) {
          toast("Mod geloescht");
          await refreshMods();
        } else {
          btn.disabled = false;
        }
      });
    });
  }

  function setupModUpload() {
    const input = el("modUpload");
    if (!input) return;
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      toast("Mod wird hochgeladen...");
      const result = await api("/api/mods/upload", { method: "POST", body: form });
      if (result && result.ok) {
        toast("Mod '" + result.mod_name + "' hochgeladen");
        await refreshMods();
      }
      input.value = "";
    });
  }

  // --- Init ---
  async function init() {
    setupConsole();
    setupConfig();
    setupModUpload();

    await Promise.all([
      refreshPlayers(),
      refreshConsole(),
      loadConfigs(),
      refreshBackups(),
      refreshMods(),
    ]);

    // Poll players and console
    setInterval(async () => {
      await refreshPlayers();
      await refreshConsole();
    }, 10000);
  }

  init().catch(err => {
    console.error("Init error:", err);
  });
})();
