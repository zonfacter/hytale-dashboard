(function() {
  "use strict";

  const POLL_INTERVAL = 5000;
  let pollTimer = null;

  // --- Helpers ---
  function el(id) { return document.getElementById(id); }

  function kv(container, rows) {
    container.innerHTML = rows.map(([k, v]) =>
      `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`
    ).join("");
  }

  function badgeClass(state) {
    if (state === "active") return "badge-active";
    if (state === "failed") return "badge-failed";
    return "badge-inactive";
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
      if (resp.status === 401) {
        location.reload();
        return null;
      }
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

  // --- Refresh Status ---
  async function refreshStatus() {
    const s = await api("/api/status");
    if (!s) return;

    // Service Status
    const srv = s.service || {};
    if (srv.error) {
      kv(el("serverStatus"), [["Fehler", srv.error]]);
    } else {
      const state = srv.ActiveState || "unknown";
      const badge = `<span class="badge ${badgeClass(state)}">${state}</span>`;
      kv(el("serverStatus"), [
        ["ActiveState", badge],
        ["SubState", srv.SubState || "-"],
        ["MainPID", srv.MainPID || "-"],
        ["Startzeit", srv.StartTime || "-"],
      ]);
    }

    // Version
    const ver = s.version || {};
    renderVersion(ver, s.allow_control);

    // Disk
    const disk = s.disk || {};
    if (disk.error) {
      kv(el("diskInfo"), [["Fehler", disk.error]]);
    } else {
      kv(el("diskInfo"), [
        ["Gesamt", disk.total],
        ["Belegt", disk.used],
        ["Frei", disk.free],
      ]);
      const bar = el("diskBar");
      bar.hidden = false;
      el("diskBarFill").style.width = disk.percent_used + "%";
      el("diskBarLabel").textContent = disk.percent_used + "% belegt";
    }

    // Backups
    const backups = s.backups || {};
    const files = backups.files || [];
    const world = s.world || {};
    const activeSeed = world.active_seed && world.active_seed !== "unknown"
      ? `<code>${world.active_seed}</code>`
      : '<span class="muted">n/a</span>';
    kv(el("backupSummary"), [
      ["Anzahl", backups.count || 0],
      ["Letztes Backup", backups.last_backup || "n/a"],
      ["Aktiver Seed", activeSeed],
    ]);

    const tbody = el("backupTable");
    if (files.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="muted">Keine Backups gefunden</td></tr>';
    } else {
      tbody.innerHTML = files.slice(0, 30).map(f => {
        const label = f.label ? `<div><strong>${f.label}</strong></div>` : "";
        const comment = f.comment ? `<div class="muted">${f.comment}</div>` : "";
        return `<tr><td>${label}<code>${f.name}</code>${comment}</td><td>${f.size}</td><td>${f.mtime}</td></tr>`;
      }).join("");
    }

    // Control visibility
    if (s.allow_control) {
      el("serverActions").hidden = false;
      el("backupActions").hidden = false;
      el("settingsCard").hidden = false;
      el("versionActions").hidden = false;
    }
  }

  // --- Version Display ---
  function renderVersion(ver, allowControl) {
    const current = ver.current || "unknown";
    const latest = ver.latest || "unknown";
    const updateAvailable = ver.update_available || false;
    const autoUpdate = ver.update_after_backup || false;

    let statusBadge;
    if (updateAvailable) {
      statusBadge = '<span class="badge badge-update">Update verfuegbar</span>';
    } else if (current === "unknown" || latest === "unknown") {
      statusBadge = '<span class="badge badge-inactive">Unbekannt</span>';
    } else {
      statusBadge = '<span class="badge badge-active">Aktuell</span>';
    }

    const rows = [
      ["Installiert", current],
      ["Verfuegbar", latest !== "unknown" ? latest : '<span class="muted">Noch nicht geprueft</span>'],
      ["Status", statusBadge],
    ];
    if (autoUpdate) {
      rows.push(["Auto-Update", '<span class="badge badge-active">Nach Backup</span>']);
    }
    kv(el("versionInfo"), rows);

    if (allowControl) {
      const updateBtn = el("runUpdate");
      const autoBtn = el("toggleAutoUpdate");
      if (updateAvailable) {
        updateBtn.hidden = false;
        autoBtn.hidden = false;
        autoBtn.textContent = autoUpdate ? "Auto-Update deaktivieren" : "Nach Backup aktualisieren";
      } else {
        updateBtn.hidden = true;
        autoBtn.hidden = true;
      }
    }
  }

  // --- Refresh Logs ---
  async function refreshLogs() {
    const data = await api("/api/logs");
    if (!data) return;
    const logsEl = el("logs");
    logsEl.textContent = (data.lines || []).join("\n");
    if (el("autoScroll").checked) {
      logsEl.scrollTop = logsEl.scrollHeight;
    }
  }

  // --- Config / Settings ---
  async function refreshConfig() {
    const data = await api("/api/config");
    if (!data) return;
    const select = el("backupFrequency");
    if (select) {
      select.value = String(data.backup_frequency);
    }
  }

  // --- Control Actions ---
  function setupControls() {
    // Server start/stop/restart
    document.querySelectorAll("#serverActions button").forEach(btn => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.action;
        if (action === "stop" && !confirm("Server wirklich stoppen?")) return;
        btn.disabled = true;
        const result = await api(`/api/server/${action}`, { method: "POST" });
        if (result && result.ok) toast(`Aktion '${action}' erfolgreich`);
        setTimeout(async () => {
          await refreshStatus();
          await refreshLogs();
          btn.disabled = false;
        }, 2000);
      });
    });

    // Backup now
    const backupBtn = el("runBackup");
    if (backupBtn) {
      backupBtn.addEventListener("click", async () => {
        backupBtn.disabled = true;
        backupBtn.textContent = "Backup laeuft...";
        const result = await api("/api/backup/run", { method: "POST" });
        if (result && result.ok) toast("Backup gestartet");
        setTimeout(async () => {
          await refreshStatus();
          await refreshLogs();
          backupBtn.disabled = false;
          backupBtn.textContent = "Backup jetzt ausführen";
        }, 5000);
      });
    }

    const backupCustomBtn = el("runBackupCustom");
    if (backupCustomBtn) {
      backupCustomBtn.addEventListener("click", async () => {
        const label = (el("backupLabel")?.value || "").trim();
        const comment = (el("backupComment")?.value || "").trim();
        backupCustomBtn.disabled = true;
        backupCustomBtn.textContent = "Backup laeuft...";
        const result = await api("/api/backup/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label, comment }),
        });
        if (result && result.ok) {
          toast("Manuelles Backup erstellt");
          if (el("backupLabel")) el("backupLabel").value = "";
          if (el("backupComment")) el("backupComment").value = "";
        }
        setTimeout(async () => {
          await refreshStatus();
          await refreshLogs();
          backupCustomBtn.disabled = false;
          backupCustomBtn.textContent = "Backup mit Name";
        }, 5000);
      });
    }

    // Settings save
    const saveBtn = el("saveSettings");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const freq = parseInt(el("backupFrequency").value, 10);
        if (!confirm("Backup-Frequenz aendern? Der Server wird neugestartet.")) return;
        saveBtn.disabled = true;
        el("settingsHint").hidden = false;
        const result = await api("/api/config/backup-frequency", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ frequency: freq }),
        });
        if (result && result.ok) {
          toast("Backup-Frequenz gespeichert, Server neugestartet");
        }
        setTimeout(async () => {
          el("settingsHint").hidden = true;
          saveBtn.disabled = false;
          await refreshStatus();
          await refreshConfig();
          await refreshLogs();
        }, 5000);
      });
    }

    // Update log polling
    let logPollTimer = null;
    function startLogPolling() {
      const logEl = el("updateLog");
      logEl.hidden = false;
      logEl.textContent = "Warte auf Ausgabe...";
      logPollTimer = setInterval(async () => {
        const data = await api("/api/update/log");
        if (data && data.log) {
          logEl.textContent = data.log;
          logEl.scrollTop = logEl.scrollHeight;
        }
      }, 2000);
    }
    function stopLogPolling() {
      if (logPollTimer) {
        clearInterval(logPollTimer);
        logPollTimer = null;
      }
      setTimeout(() => { el("updateLog").hidden = true; }, 5000);
    }

    // Version check
    const checkBtn = el("checkVersion");
    if (checkBtn) {
      checkBtn.addEventListener("click", async () => {
        checkBtn.disabled = true;
        checkBtn.textContent = "Pruefe...";
        const hint = el("versionHint");
        hint.textContent = "Version wird geprueft, bitte warten...";
        hint.hidden = false;
        startLogPolling();
        const result = await api("/api/version/check", { method: "POST" });
        stopLogPolling();
        if (result) {
          if (result.update_available) {
            toast("Update verfuegbar: " + result.latest, "success");
          } else {
            toast(result.message || "Server ist aktuell");
          }
        }
        hint.hidden = true;
        checkBtn.disabled = false;
        checkBtn.textContent = "Version pruefen";
        await refreshStatus();
      });
    }

    // Manual update
    const updateBtn = el("runUpdate");
    if (updateBtn) {
      updateBtn.addEventListener("click", async () => {
        if (!confirm("Server jetzt aktualisieren? Der Server wird dabei gestoppt und neu gestartet.")) return;
        updateBtn.disabled = true;
        updateBtn.textContent = "Update laeuft...";
        const hint = el("versionHint");
        hint.textContent = "Update wird durchgefuehrt...";
        hint.hidden = false;
        startLogPolling();
        const result = await api("/api/update/run", { method: "POST" });
        stopLogPolling();
        if (result) {
          if (result.error) {
            toast(result.error, "error");
          } else {
            toast(result.message || "Update abgeschlossen", "success");
          }
        }
        hint.hidden = true;
        updateBtn.disabled = false;
        updateBtn.textContent = "Jetzt aktualisieren";
        await refreshStatus();
        await refreshLogs();
      });
    }

    // Auto-update after backup toggle
    const autoBtn = el("toggleAutoUpdate");
    if (autoBtn) {
      autoBtn.addEventListener("click", async () => {
        autoBtn.disabled = true;
        const result = await api("/api/update/auto", { method: "POST" });
        if (result && result.ok) {
          if (result.update_after_backup) {
            toast("Auto-Update nach Backup aktiviert");
          } else {
            toast("Auto-Update nach Backup deaktiviert");
          }
        }
        autoBtn.disabled = false;
        await refreshStatus();
      });
    }

    // Log refresh button
    el("refreshLogs").addEventListener("click", refreshLogs);
  }

  // --- Init ---
  async function init() {
    setupControls();
    await refreshStatus();
    await refreshConfig();
    await refreshLogs();

    // Start polling
    pollTimer = setInterval(async () => {
      await refreshStatus();
      await refreshLogs();
    }, POLL_INTERVAL);
  }

  init().catch(err => {
    el("logs").textContent = "Initialisierungsfehler: " + err.message;
  });
})();
