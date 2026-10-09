(() => {
  let allEvents = []; let filteredEvents = []; let page = 1; let sortKey = "timestamp"; let sortDirection = "desc";
  const pageSize = 20;
  const tbody = document.querySelector("#events-table tbody");
  const safe = value => window.TrinityUI.escapeHtml(value);
  const filters = ["filter-start", "filter-end", "filter-camera", "filter-zone", "filter-level", "filter-ppe"];
  let modalTrigger = null;
  let cameraOptions = [], optionIndex = -1, exactCamera = "";
  let selectionVersion = 0;
  document.getElementById("event-modal-image").addEventListener("error", () => {
    document.getElementById("event-modal-image").classList.add("hidden");
    document.getElementById("event-modal-fallback").classList.remove("hidden");
  });

  const formatDate = value => { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); };
  const badge = level => `<span class="badge badge-${safe(String(level).toLowerCase())}">${safe(level)}</span>`;
  const tags = items => items?.length ? items.map(item => `<span class="tag">${safe(window.TrinityUI.ppeLabel(item))}</span>`).join("") : '<span class="muted">Not recorded</span>';

  function currentFilters() {
    return { start: $("filter-start").value, end: $("filter-end").value, camera: $("filter-camera").value.toLowerCase(), zone: $("filter-zone").value.toLowerCase(), level: $("filter-level").value, ppe: $("filter-ppe").value };
  }
  function $(id) { return document.getElementById(id); }
  function passes(event, query) {
    const date = event.timestamp.slice(0, 10);
    const zoneTypes = event.zone_types || [];
    return !(query.start && date < query.start) && !(query.end && date > query.end) && !(query.camera && (exactCamera ? event.camera_id !== exactCamera : !event.camera_id.startsWith(query.camera))) && !(query.zone && !zoneTypes.includes(query.zone)) && !(query.level && event.alert_level !== query.level) && !(query.ppe && !event.missing_ppe.includes(query.ppe));
  }
  function sorted(events) {
    const direction = sortDirection === "asc" ? 1 : -1;
    return [...events].sort((a, b) => {
      if (sortKey === "confidence") return ((a.confidence || 0) - (b.confidence || 0)) * direction;
      if (sortKey === "timestamp") return (new Date(a.timestamp) - new Date(b.timestamp)) * direction;
      return String(a[sortKey]).localeCompare(String(b[sortKey])) * direction;
    });
  }
  function applyFilters() { filteredEvents = sorted(allEvents.filter(event => passes(event, currentFilters()))); page = 1; render(); }
  function render() {
    const start = (page - 1) * pageSize; const visible = filteredEvents.slice(start, start + pageSize);
    tbody.innerHTML = "";
    visible.forEach(event => {
      const row = document.createElement("tr");
      row.innerHTML = `<td class="mono-cell"><time>${safe(formatDate(event.timestamp))}</time></td><td class="mono-cell">${safe(event.camera_id)}</td><td>${safe(event.zone)}</td><td>${badge(event.alert_level)}</td><td><div class="tag-list">${tags(event.missing_ppe)}</div></td><td class="mono-cell">${Math.round((event.confidence || 0) * 100)}%</td><td><button class="table-action" type="button">View <span aria-hidden="true">↗</span></button></td>`;
      row.querySelector(".table-action").addEventListener("click", click => openEvent(event, click.currentTarget));
      tbody.appendChild(row);
    });
    const totalPages = Math.max(1, Math.ceil(filteredEvents.length / pageSize));
    $("page-summary").textContent = `${filteredEvents.length} events · Page ${page} of ${totalPages}`;
    $("event-count").textContent = `${filteredEvents.length} / ${allEvents.length} events`;
    $("export-csv").disabled = !filteredEvents.length;
    $("prev-page").disabled = page === 1;
    $("next-page").disabled = page >= totalPages;
    $("events-empty").classList.toggle("hidden", visible.length > 0);
    $("events-empty").querySelector("strong").textContent = allEvents.length ? "No matching events" : "No events recorded";
    $("events-empty").querySelector("p").textContent = allEvents.length ? "Adjust the filters or clear them to see all events." : "Events will appear here after the pipeline records a safety alert.";
    document.querySelector("#events-table").classList.toggle("hidden", visible.length === 0);
  }
  function updateSortButtons() {
    document.querySelectorAll(".sort-button").forEach(button => { const active = button.dataset.sort === sortKey; button.classList.toggle("active", active); button.querySelector("span").textContent = active ? (sortDirection === "asc" ? "↑" : "↓") : "↕"; });
  }
  function openEvent(event, trigger) {
    modalTrigger = trigger; const modal = $("event-modal"); const image = $("event-modal-image"); const fallback = $("event-modal-fallback");
    $("event-modal-details").innerHTML = `<div><dt>Timestamp</dt><dd>${safe(formatDate(event.timestamp))}</dd></div><div><dt>Camera</dt><dd>${safe(event.camera_id)}</dd></div><div><dt>Zone</dt><dd>${safe(event.zone)}</dd></div><div><dt>Alert</dt><dd>${badge(event.alert_level)}</dd></div><div><dt>Missing PPE</dt><dd>${event.missing_ppe.map(item => safe(window.TrinityUI.ppeLabel(item))).join(", ") || "Not recorded"}</dd></div><div><dt>Confidence</dt><dd>${Math.round((event.confidence || 0) * 100)}%</dd></div>`;
    if (event.snapshot_url) { image.src = event.snapshot_url; image.classList.remove("hidden"); fallback.classList.add("hidden"); } else { image.removeAttribute("src"); image.classList.add("hidden"); fallback.classList.remove("hidden"); }
    modal.classList.remove("hidden"); document.body.classList.add("modal-open"); modal.querySelector(".modal-panel").focus();
  }
  function closeEvent() { $("event-modal").classList.add("hidden"); document.body.classList.remove("modal-open"); $("event-modal-image").removeAttribute("src"); modalTrigger?.focus(); }
  function exportCsv() {
    const header = ["run_id", "timestamp", "camera_id", "zone", "alert_level", "missing_ppe", "confidence"];
    const rows = filteredEvents.map(event => [event.run_id || "", event.timestamp, event.camera_id, event.zone, event.alert_level, event.missing_ppe.join("|"), event.confidence]);
    const csv = [header, ...rows].map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = "trinity_events.csv"; link.click(); URL.revokeObjectURL(url);
  }
  async function initialize() {
    const version = ++selectionVersion;
    const runId = $("filter-run").value;
    allEvents = []; applyFilters();
    $("archive-detail").classList.add("hidden");
    $("archive-summary").textContent = "Loading saved results…";
    try {
      const response = await fetch(runId ? `/api/events?run_id=${encodeURIComponent(runId)}` : "/api/events?scope=all", {cache:"no-store"});
      if (!response.ok) throw new Error();
      const payload = await response.json();
      let run = null;
      if (runId) {
        const detail = await fetch(`/api/runs/${encodeURIComponent(runId)}`, {cache:"no-store"});
        if (!detail.ok) throw new Error();
        run = (await detail.json()).run;
      }
      if (version !== selectionVersion) return;
      allEvents = payload.events || []; applyFilters();
      $("archive-summary").textContent = run ? `${run.status.toUpperCase()} · ${run.frames ?? "—"} frames · ${run.event_count} safety events · ${run.model}` : "Combined events across all saved detection runs. Select a run for its video and runtime log.";
      if (run) {
        $("archive-detail").classList.remove("hidden");
        $("archive-files").replaceChildren();
        const labels = {video:"Download detected video", events:"Download event CSV", log:"Download runtime log", metadata:"Run configuration", progress:"Processing summary", zones:"Initial zone configuration"};
        for (const [kind,file] of Object.entries(run.files)) {
          const link = document.createElement("a"); link.className = "button button-secondary button-compact";
          link.href = file.url; link.download = ""; link.textContent = labels[kind] || file.name;
          $("archive-files").appendChild(link);
        }
        $("archive-folder").textContent = `Saved on this computer: ${run.folder}`;
        $("archive-log-text").textContent = run.log_tail || "Runtime log is empty.";
        if (!allEvents.length) $("events-empty").querySelector("p").textContent = "This run recorded no safety alerts. Its video and runtime log are still saved above; this does not prove PPE compliance.";
      }
    } catch (error) {
      if (version !== selectionVersion) return;
      $("archive-summary").textContent = "Could not load saved results. Refresh history to retry.";
      $("event-count").textContent = "Data unavailable";
    }
  }
  async function loadRuns() {
    $("refresh-runs").disabled = true;
    try {
      const response = await fetch("/api/runs", {cache:"no-store"});
      if (!response.ok) throw new Error();
      const runs = (await response.json()).runs;
      const selected = $("filter-run").value || new URLSearchParams(location.search).get("run_id") || "";
      $("filter-run").replaceChildren(new Option("All runs — combined events", ""));
      for (const run of runs) $("filter-run").add(new Option(`${formatDate(run.started_at)} · ${run.source_name} · ${run.status} · ${run.event_count} events`,run.id));
      $("filter-run").value = runs.some(run => run.id === selected) ? selected : "";
      await initialize();
      if (!runs.length) $("archive-summary").textContent = "No detection runs saved yet. Select a video in Live Monitor and press Start detection.";
    } catch { $("archive-summary").textContent = "Run history unavailable. Try Refresh history."; }
    finally { $("refresh-runs").disabled = false; }
  }
  function hideCameraOptions() { $("camera-options").classList.add("hidden"); $("filter-camera").setAttribute("aria-expanded","false"); $("filter-camera").removeAttribute("aria-activedescendant"); optionIndex = -1; }
  function renderCameraOptions() {
    const prefix = $("filter-camera").value;
    const list = $("camera-options"); list.innerHTML = ""; optionIndex = -1;
    if (!prefix) { hideCameraOptions(); return; }
    const matches = cameraOptions.filter(item => item.id.startsWith(prefix));
    matches.forEach((item,index) => {
      const option = document.createElement("button"); option.type = "button"; option.id = `camera-option-${index}`; option.setAttribute("role","option"); option.setAttribute("aria-selected","false"); option.tabIndex = -1;
      option.innerHTML = `<span><strong>${safe(prefix)}</strong><span class="completion-suffix">${safe(item.id.slice(prefix.length))}</span></span><small>${safe(item.splits.join(" / "))}</small>`;
      option.addEventListener("mousedown",event => event.preventDefault());
      option.addEventListener("click",() => { $("filter-camera").value = item.id; exactCamera = item.id; hideCameraOptions(); applyFilters(); $("filter-camera").focus(); });
      list.appendChild(option);
    });
    if (!matches.length) list.innerHTML = '<p class="no-options">No matching CMOT video</p>';
    list.classList.remove("hidden"); $("filter-camera").setAttribute("aria-expanded","true");
  }
  fetch("/api/videos").then(response => response.json()).then(payload => {
    const catalog = new Map();
    (payload.videos || []).filter(video => ["train","valid","test"].includes(video.split) && /^\d+$/.test(video.camera_id)).forEach(video => {
      if (!catalog.has(video.camera_id)) catalog.set(video.camera_id, new Set());
      catalog.get(video.camera_id).add(video.split);
    });
    cameraOptions = [...catalog].map(([id,splits]) => ({id,splits:[...splits]})).sort((a,b) => a.id.localeCompare(b.id));
    if (document.activeElement === $("filter-camera") && $("filter-camera").value) renderCameraOptions();
  }).catch(() => {});
  filters.filter(id => id !== "filter-camera").forEach(id => $(id).addEventListener("input", applyFilters));
  $("filter-camera").addEventListener("input", () => { $("filter-camera").value = $("filter-camera").value.replace(/\D/g,""); exactCamera = ""; renderCameraOptions(); applyFilters(); });
  $("filter-camera").addEventListener("focus", () => { if (!exactCamera) renderCameraOptions(); });
  $("filter-camera").addEventListener("blur", hideCameraOptions);
  $("filter-camera").addEventListener("keydown",event => {
    if (event.key === "Escape") { hideCameraOptions(); return; }
    if (!["ArrowDown","ArrowUp","Enter"].includes(event.key)) return;
    if ($("camera-options").classList.contains("hidden")) renderCameraOptions();
    const options = [...$("camera-options").querySelectorAll('[role="option"]')]; if (!options.length) return;
    event.preventDefault();
    if (event.key === "Enter") { if (optionIndex >= 0) options[optionIndex].click(); return; }
    optionIndex = (optionIndex + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    options.forEach((option,index) => option.setAttribute("aria-selected",String(index === optionIndex)));
    $("filter-camera").setAttribute("aria-activedescendant",options[optionIndex].id); options[optionIndex].scrollIntoView({block:"nearest"});
  });
  $("clear-filters").addEventListener("click", () => { filters.forEach(id => $(id).value = ""); exactCamera = ""; hideCameraOptions(); applyFilters(); });
  document.querySelectorAll(".sort-button").forEach(button => button.addEventListener("click", () => { const key = button.dataset.sort; sortDirection = sortKey === key && sortDirection === "desc" ? "asc" : "desc"; sortKey = key; updateSortButtons(); filteredEvents = sorted(filteredEvents); render(); }));
  $("prev-page").addEventListener("click", () => { page = Math.max(1, page - 1); render(); });
  $("next-page").addEventListener("click", () => { page = Math.min(Math.max(1, Math.ceil(filteredEvents.length / pageSize)), page + 1); render(); });
  $("export-csv").addEventListener("click", exportCsv);
  $("event-modal-close").addEventListener("click", closeEvent);
  $("event-modal").addEventListener("click", event => { if (event.target === $("event-modal")) closeEvent(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("event-modal").classList.contains("hidden")) closeEvent(); });
  $("filter-run").addEventListener("change", () => {
    filters.forEach(id => $(id).value = ""); exactCamera = ""; hideCameraOptions();
    const url = new URL(location.href); const id = $("filter-run").value;
    if (id) url.searchParams.set("run_id",id); else url.searchParams.delete("run_id");
    history.replaceState(null,"",url); initialize();
  });
  $("refresh-runs").addEventListener("click",loadRuns);
  loadRuns();
})();
