(() => {
  const $ = id => document.getElementById(id);
  const alertFeed = $("alert-feed");
  const liveFrame = $("live-frame");
  const runReplay = $("run-replay");
  const frameFallback = $("frame-fallback");
  const modal = $("snapshot-modal");
  const modalPanel = modal?.querySelector(".modal-panel");
  const modalImage = $("modal-image");
  const modalStage = $("modal-stage");
  const modalSpotlights = $("modal-spotlights");
  const modalFallback = $("modal-fallback");
  const modalDetails = $("modal-details");
  const modalRecap = $("modal-recap");
  let streamingFeed = false;
  let lastStaticSource = null;
  let lastTrigger = null;
  let overlayProfile = null;
  let lastRunId = null;
  let overlayVisible = false;
  let viewMode = localStorage.getItem("trinity-view-mode") === "debug" ? "debug" : "worker";
  let lastReplaySource = null;
  let thresholdsDirty = false;
  let restoreSidebar = null;
  let cleanupSpotlight = null;
  const overlay = $("monitor-zone-overlay");

  function setThresholdUI(kind, value, fallback) {
    const normalized = Math.min(0.9, Math.max(0.1, Number(value) || fallback));
    $(`${kind}-confidence-range`).value = normalized.toFixed(2);
    const label = `${Math.round(normalized * 100)}%`;
    $(`${kind}-confidence-value`).textContent = label;
  }

  function placeViewToolbarInHud() {
    const hud = document.querySelector(".video-hud");
    const toolbar = document.querySelector(".video-view-toolbar");
    if (!hud || !toolbar) return;
    let primary = hud.querySelector(".video-hud-primary");
    if (!primary) {
      const brand = Array.from(hud.children).find(child => child.id !== "frame-mode");
      primary = document.createElement("div");
      primary.className = "video-hud-primary";
      if (brand) {
        brand.classList.add("video-hud-brand");
        primary.appendChild(brand);
      }
      hud.prepend(primary);
    }
    if (toolbar.parentElement !== primary) primary.appendChild(toolbar);
  }

  function updateViewSwitch() {
    document.querySelectorAll("[data-view-mode]").forEach(button => {
      const active = button.dataset.viewMode === viewMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function setViewMode(mode) {
    viewMode = mode === "debug" ? "debug" : "worker";
    localStorage.setItem("trinity-view-mode", viewMode);
    updateViewSwitch();
    lastStaticSource = null;
    lastReplaySource = null;
    streamingFeed = false;
    liveFrame.removeAttribute("src");
    runReplay.pause();
    runReplay.removeAttribute("src");
    runReplay.load();
    refreshDashboard();
  }

  async function refreshOverlay() {
    try { const response = await fetch("/api/zones"); const payload = await response.json(); overlayProfile = payload.ok ? payload.profile : null; }
    catch { overlayProfile = null; }
    drawOverlay();
  }
  function drawOverlay() {
    if (!overlay) return;
    overlay.classList.toggle("hidden", !overlayVisible || !overlayProfile);
    if (!overlayVisible || !overlayProfile) return;
    const surface = $("video-surface");
    const scale = Math.min(surface.clientWidth / overlayProfile.width, surface.clientHeight / overlayProfile.height);
    const width = overlayProfile.width * scale, height = overlayProfile.height * scale;
    Object.assign(overlay.style, {width:`${width}px`,height:`${height}px`,left:`${(surface.clientWidth-width)/2}px`,top:`${(surface.clientHeight-height)/2}px`});
    overlay.width = overlayProfile.width; overlay.height = overlayProfile.height;
    const ctx = overlay.getContext("2d");
    for (const zone of overlayProfile.zones || []) {
      if (zone.polygon.length < 3) continue;
      const danger = zone.type === "danger_zone";
      ctx.beginPath(); zone.polygon.forEach(([x,y],i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y)); ctx.closePath();
      ctx.fillStyle = danger ? "rgba(213,52,43,.20)" : "rgba(243,167,18,.18)"; ctx.fill();
      ctx.strokeStyle = danger ? "#ff4038" : "#f3a712"; ctx.lineWidth = Math.max(3,overlay.width/450); ctx.stroke();
      ctx.font = `${Math.max(18,overlay.width/70)}px monospace`; ctx.fillStyle = ctx.strokeStyle;
      ctx.fillText(zone.name,zone.polygon[0][0]+8,Math.max(24,zone.polygon[0][1]-8));
    }
  }
  new ResizeObserver(drawOverlay).observe($("video-surface"));

  const formatDate = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  };
  const safe = value => window.TrinityUI.escapeHtml(value);
  modalImage.addEventListener("error", () => {
    modalStage.classList.add("hidden");
    modalFallback.classList.remove("hidden");
  });

  function setRunState(status) {
    const normalized = String(status || "idle").toLowerCase();
    const ledClass = ["running", "starting", "finalizing", "completed", "error"].includes(normalized) ? normalized : "idle";
    $("monitor-status-led").className = `status-led ${ledClass}`;
    $("run-state").textContent = ({running:"Active",starting:"Starting…",finalizing:"Preparing replay…",stopping:"Stopping…",completed:"Completed",error:"Error",failed:"Error",ready:"Ready",stopped:"Stopped"})[normalized] || "Idle";
  }

  function eventKey(event) {
    return `${event.timestamp}|${event.camera_id}|${event.zone}|${event.missing_ppe.join(",")}`;
  }

  function workerLabel(event) {
    return event.track_id == null ? "Worker unavailable" : `Worker ${event.track_id}`;
  }

  function evidenceQuality(confidence) {
    const value = Number(confidence) || 0;
    if (value >= 0.5) return "Strong evidence";
    if (value >= 0.3) return "Review recommended";
    return "Low-confidence evidence";
  }

  function eventRecap(event) {
    const missing = event.missing_ppe.map(window.TrinityUI.ppeLabel).join(", ") || "a zone-presence alert";
    const location = event.zone === "Unassigned" ? "No configured zone was assigned." : `Location: ${event.zone}.`;
    const confirmation = event.confirmation_observations
      ? ` after ${event.confirmation_observations} supporting detections`
      : "";
    if (event.reason_code === "ZONE_ESCALATION") {
      return `${workerLabel(event)} entered ${event.zone} while the active ${missing} violation was retained. Risk escalated to ${event.alert_level}; evidence confidence remains ${Math.round((event.confidence || 0) * 100)}%.`;
    }
    return `${workerLabel(event)} triggered an alert for ${missing}${confirmation}. ${location} Evidence confidence: ${Math.round((event.confidence || 0) * 100)}% (${evidenceQuality(event.confidence).toLowerCase()}).`;
  }

  function renderAlerts(events) {
    alertFeed.innerHTML = "";
    if (!events.length) {
      alertFeed.innerHTML = '<div class="empty-state compact"><strong>No alerts recorded</strong><p>New PPE events will appear here when the edge logger writes them.</p></div>';
      return;
    }
    events.forEach((event, index) => {
      const level = String(event.alert_level || "NORMAL").toLowerCase();
      const button = document.createElement("button");
      button.className = `alert-row alert-${level}`;
      button.type = "button";
      button.dataset.key = eventKey(event);
      button.innerHTML = `
        <span class="alert-index">${String(index + 1).padStart(2, "0")}</span>
        <span class="alert-content">
          <span class="alert-primary"><strong>${safe(event.zone)}</strong><span class="badge badge-${level}">${safe(event.alert_level)}</span></span>
          <span class="alert-meta"><time>${safe(formatDate(event.timestamp))}</time><span>${safe(event.camera_id)}</span></span>
          <span class="alert-worker">${safe(workerLabel(event))} · ${Math.round((event.confidence || 0) * 100)}%${event.reason_code === "ZONE_ESCALATION" ? " · ZONE ESCALATION" : ""}</span>
          <span class="tag-list">${event.missing_ppe.length ? event.missing_ppe.map(item => `<span class="tag">${safe(window.TrinityUI.ppeLabel(item))}</span>`).join("") : '<span class="muted">No PPE label recorded</span>'}</span>
        </span>
        <span class="alert-action" aria-hidden="true">↗</span>`;
      button.addEventListener("click", () => openSnapshot(event, button));
      alertFeed.appendChild(button);
    });
  }

  async function pollAlerts() {
    try {
      const response = await fetch("/api/events?limit=20", { cache: "no-store" });
      if (!response.ok) throw new Error("Could not load alerts");
      renderAlerts((await response.json()).events || []);
    } catch (error) {
      alertFeed.innerHTML = '<div class="empty-state compact error"><strong>Events unavailable</strong><p>Check the dashboard service and try again.</p></div>';
    }
  }

  function openSnapshot(event, trigger) {
    lastTrigger = trigger;
    restoreSidebar?.();
    restoreSidebar = window.TrinityUI.temporarilyHideSidebar();
    modal.classList.remove("hidden");
    document.body.classList.add("modal-open");
    if (modalRecap) modalRecap.textContent = eventRecap(event);
    modalDetails.innerHTML = `
      <div><dt>Timestamp</dt><dd>${safe(formatDate(event.timestamp))}</dd></div>
      <div><dt>Camera</dt><dd>${safe(event.camera_id)}</dd></div>
      <div><dt>Worker</dt><dd>${safe(workerLabel(event))}</dd></div>
      <div><dt>Zone</dt><dd>${safe(event.zone)}</dd></div>
      <div><dt>Alert level</dt><dd><span class="badge badge-${safe(event.alert_level.toLowerCase())}">${safe(event.alert_level)}</span></dd></div>
      <div><dt>Missing PPE</dt><dd>${event.missing_ppe.map(item => safe(window.TrinityUI.ppeLabel(item))).join(", ") || "Not recorded"}</dd></div>
      <div><dt>Evidence quality</dt><dd>${Math.round((event.confidence || 0) * 100)}% · ${safe(evidenceQuality(event.confidence))}</dd></div>
      <div><dt>Confirmation</dt><dd>${event.confirmation_observations ? `${safe(event.confirmation_observations)} supporting detections` : "Legacy event"}</dd></div>`;
    if (event.snapshot_url) {
      cleanupSpotlight?.();
      cleanupSpotlight = null;
      modalImage.onload = () => {
        cleanupSpotlight = window.TrinityUI.setupSnapshotSpotlight(
          modalStage, modalImage, modalSpotlights, event
        );
      };
      modalImage.src = event.snapshot_url;
      modalStage.classList.remove("hidden");
      modalFallback.classList.add("hidden");
    } else {
      modalImage.removeAttribute("src");
      modalStage.classList.add("hidden");
      modalFallback.classList.remove("hidden");
    }
    modalPanel.focus();
  }

  function closeModal() {
    modal.classList.add("hidden");
    document.body.classList.remove("modal-open");
    modalImage.removeAttribute("src");
    cleanupSpotlight?.();
    cleanupSpotlight = null;
    modalSpotlights.innerHTML = "";
    modalStage.classList.add("hidden");
    if (modalRecap) modalRecap.textContent = "";
    restoreSidebar?.();
    restoreSidebar = null;
    lastTrigger?.focus();
  }

  function showFeedImage(url, label, mode) {
    const staticKey = `${mode}|${url}`;
    if (lastStaticSource === staticKey && !liveFrame.classList.contains("hidden")) return;
    lastStaticSource = staticKey;
    lastReplaySource = null;
    streamingFeed = false;
    runReplay.pause();
    runReplay.classList.add("hidden");
    liveFrame.onload = () => {
      if (liveFrame.naturalWidth && liveFrame.naturalHeight) $("video-surface").style.aspectRatio = `${liveFrame.naturalWidth} / ${liveFrame.naturalHeight}`;
      liveFrame.classList.remove("hidden");
      frameFallback.classList.add("hidden");
      $("feed-state").textContent = label;
      $("feed-description").textContent = label;
      $("frame-mode").textContent = mode;
      $("feed-led").className = `status-led ${mode === "LIVE" ? "running" : "completed"}`;
    };
    liveFrame.onerror = showNoFrame;
    liveFrame.src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
  }

  function showLiveStream() {
    if (streamingFeed) return;
    lastStaticSource = null;
    lastReplaySource = null;
    streamingFeed = true;
    runReplay.pause();
    runReplay.classList.add("hidden");
    liveFrame.onload = () => {
      liveFrame.classList.remove("hidden");
      frameFallback.classList.add("hidden");
    };
    liveFrame.onerror = () => { streamingFeed = false; showNoFrame(); };
    liveFrame.src = `/video-feed?mode=${viewMode}&t=${Date.now()}`;
    liveFrame.classList.remove("hidden");
    frameFallback.classList.add("hidden");
    $("feed-state").textContent = "Live stream";
    $("feed-description").textContent = "Receiving local edge frames";
    $("frame-mode").textContent = viewMode === "debug" ? "LIVE / DEBUG" : "LIVE / WORKER";
    $("feed-led").className = "status-led running";
  }

  function showNoFrame() {
    liveFrame.classList.add("hidden");
    runReplay.pause();
    runReplay.classList.add("hidden");
    frameFallback.classList.remove("hidden");
    $("feed-state").textContent = "No frame";
    $("feed-description").textContent = "No active frame";
    $("frame-mode").textContent = "STANDBY";
    $("feed-led").className = "status-led idle";
  }

  function showReplay(run) {
    const kind = viewMode === "debug" ? "debug_video" : "video";
    const url = `/api/runs/${encodeURIComponent(run.run_id)}/files/${kind}?inline=1`;
    const replayKey = `${run.run_id}|${viewMode}`;
    liveFrame.classList.add("hidden");
    frameFallback.classList.add("hidden");
    overlay.classList.add("hidden");
    streamingFeed = false;
    lastStaticSource = null;
    if (lastReplaySource !== replayKey) {
      lastReplaySource = replayKey;
      runReplay.src = url;
      runReplay.load();
    }
    runReplay.classList.remove("hidden");
    runReplay.onerror = () => {
      lastReplaySource = null;
      runReplay.classList.add("hidden");
      showFeedImage(
        `/api/live-frame?mode=${viewMode}`,
        "Final frame · replay unavailable",
        "COMPLETED",
      );
    };
    $("feed-state").textContent = viewMode === "debug" ? "Replay · Debug view" : "Replay · Worker view";
    $("feed-description").textContent = "Saved run · use the timeline to seek";
    $("frame-mode").textContent = viewMode === "debug" ? "REPLAY / DEBUG" : "REPLAY / WORKER";
    $("feed-led").className = "status-led completed";
  }

  async function refreshDashboard() {
    try {
      const [runResponse, statsResponse] = await Promise.all([fetch("/api/run", { cache: "no-store" }), fetch("/api/stats", { cache: "no-store" })]);
      if (!runResponse.ok || !statsResponse.ok) throw new Error("Dashboard API unavailable");
      const runPayload = await runResponse.json();
      const stats = await statsResponse.json();
      const run = runPayload.run || {};
      const status = String(run.status || "idle").toLowerCase();
      const running = ["starting", "running", "stopping", "finalizing"].includes(status);
      if (!thresholdsDirty) {
        setThresholdUI("ppe", run.confidence, 0.4);
        setThresholdUI("person", run.person_confidence, 0.2);
      }
      ["ppe-confidence-range", "person-confidence-range", "apply-confidence-settings"].forEach(id => {
        $(id).disabled = running || !run.source;
      });
      const progress = run.progress || {};
      const feedback = $("run-feedback");
      feedback.classList.toggle("hidden", !running && !["error", "completed", "stopped"].includes(status));
      feedback.dataset.tone = status;
      if (status === "starting") {
        const elapsed = Math.max(0, Math.floor((Date.now() - new Date(run.started_at).getTime()) / 1000));
        feedback.textContent = `${progress.message || "Starting detector…"} · ${elapsed}s. The first frame includes model and inference-backend warm-up.`;
      } else if (status === "running") {
        feedback.textContent = `Frame ${progress.frame || 0} / ${progress.total_frames || "—"} · ${(progress.video_seconds || 0).toFixed(1)}s · ${progress.processing_fps || 0} processing FPS · ${progress.persons || 0} person(s), ${progress.ppe_detections || 0} PPE box(es)`;
      } else if (status === "error") {
        feedback.textContent = `Detection failed: ${run.error_message || "Check this run’s pipeline.log for details."}`;
      } else if (status === "stopping") feedback.textContent = "Stopping detection and finishing the output video…";
      else if (status === "finalizing") feedback.textContent = "Preparing the Worker and Debug videos for browser replay…";
      else feedback.textContent = `${status === "completed" ? "Video completed" : "Detection stopped"}${progress.frame != null ? ` · ${progress.frame} frames processed` : ""}. Press Start detection to replay.`;
      $("start-detection").classList.toggle("hidden",running);
      $("start-detection").disabled = !run.source;
      $("stop-detection").classList.toggle("hidden",!running);
      overlayVisible = !running && (status === "ready" || !!run.zone_preview);
      if (lastRunId !== run.run_id) { lastRunId = run.run_id; await refreshOverlay(); }
      drawOverlay();
      setRunState(status);
      $("camera-source").textContent = `SOURCE / ${run.source_name || (run.source ? String(run.source).split(/[\\/]/).pop() : "—")}`;
      $("alerts-today").textContent = stats.total_alerts_today;
      $("warning-today").textContent = stats.warning_today;
      $("critical-today").textContent = stats.critical_today;

      if (status === "running") {
        showLiveStream();
      } else if (status === "starting" || status === "finalizing") {
        showFeedImage(`/api/live-frame?mode=${viewMode}`, status === "finalizing" ? "Preparing replay…" : "Loading model…", status.toUpperCase());
      } else {
        if (streamingFeed) { streamingFeed = false; liveFrame.removeAttribute("src"); }
        if (status === "completed" && run.run_id && run.return_code === 0) showReplay(run);
        else if (overlayVisible) showFeedImage("/api/zone-frame", "Input preview · saved zones", "PREVIEW");
        else if (stats.live_frame_url) showFeedImage(stats.live_frame_url, status === "completed" ? "Final pipeline frame" : "Latest pipeline frame", status === "completed" ? "COMPLETED" : "LATEST");
        else if (stats.latest_frame_url) showFeedImage(stats.latest_frame_url, "Latest event frame", "SNAPSHOT");
        else showNoFrame();
      }
    } catch (error) {
      setRunState("error");
      showNoFrame();
    }
  }

  placeViewToolbarInHud();
  ["ppe", "person"].forEach(kind => {
    $(`${kind}-confidence-range`).addEventListener("input", event => {
      thresholdsDirty = true;
      $(`${kind}-confidence-value`).textContent = `${Math.round(Number(event.target.value) * 100)}%`;
    });
  });
  $("apply-confidence-settings").addEventListener("click", async () => {
    const button = $("apply-confidence-settings");
    button.disabled = true;
    try {
      const response = await fetch("/api/run/settings", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          confidence: Number($("ppe-confidence-range").value),
          person_confidence: Number($("person-confidence-range").value),
        }),
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.error || "Could not save detection thresholds.");
      thresholdsDirty = false;
      setThresholdUI("ppe", payload.run.confidence, 0.4);
      setThresholdUI("person", payload.run.person_confidence, 0.2);
      window.TrinityUI.toast(`Thresholds saved: PPE ${Math.round(payload.run.confidence * 100)}% · Person ${Math.round(payload.run.person_confidence * 100)}%.`);
      window.dispatchEvent(new Event("run-changed"));
    } catch (error) {
      window.TrinityUI.toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  $("modal-close").addEventListener("click", closeModal);
  document.querySelectorAll("[data-view-mode]").forEach(button => button.addEventListener("click", () => setViewMode(button.dataset.viewMode)));
  modal.addEventListener("click", event => { if (event.target === modal) closeModal(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !modal.classList.contains("hidden")) closeModal(); });
  window.setInterval(() => { $("current-time").textContent = new Date().toLocaleTimeString(); }, 1000);
  $("current-time").textContent = new Date().toLocaleTimeString();
  updateViewSwitch();
  pollAlerts();
  window.addEventListener("zone-profile-changed",async () => { lastStaticSource = null; await refreshOverlay(); refreshDashboard(); });
  window.addEventListener("run-changed", () => { lastStaticSource = null; refreshDashboard(); pollAlerts(); });
  refreshDashboard();
  window.setInterval(pollAlerts, 4000);
  window.setInterval(refreshDashboard, 2500);
})();
