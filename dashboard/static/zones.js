(() => {
  const $ = id => document.getElementById(id);
  const canvas = $("zone-canvas");
  const context = canvas.getContext("2d");
  const sourceImage = new Image();
  const colors = {
    danger_zone: { line: "#ff3b30", fill: "rgba(255, 59, 48, .22)" },
    warning_zone: { line: "#f3a712", fill: "rgba(243, 167, 18, .20)" }
  };
  let profile = null;
  let selectedIndex = -1;
  let mode = "select";
  let dragPoint = -1;
  let dirty = false;
  let imageReady = false;
  let saving = false;
  let assets = [];
  let activeAssetId = null;
  let listExpanded = false;
  let history = [];
  let editingField = null;

  const safe = value => window.TrinityUI.escapeHtml(value);

  function setDirty(value) {
    dirty = value;
    $("save-zones").disabled = !profile || saving;
    $("editor-state").textContent = value ? "Unsaved changes" : profile ? (activeAssetId ? "Profile loaded" : "New profile") : "Unavailable";
    $("editor-state").classList.toggle("warning", value);
  }

  function cloneProfile(value) {
    return value ? JSON.parse(JSON.stringify(value)) : null;
  }

  function rememberChange() {
    if (!profile) return;
    history.push({ profile: cloneProfile(profile), selectedIndex, mode, dirty });
    if (history.length > 60) history.shift();
  }

  function undoLastChange() {
    if (!history.length || saving) {
      window.TrinityUI.toast("Nothing to undo.");
      return;
    }
    const previous = history.pop();
    profile = previous.profile;
    selectedIndex = Math.min(previous.selectedIndex, profile.zones.length - 1);
    dragPoint = -1;
    listExpanded = false;
    setMode(previous.mode === "draw" && selectedIndex >= 0 ? "draw" : "select");
    setDirty(previous.dirty);
    renderZoneList();
    draw();
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "Request failed");
    return payload;
  }

  function renderAssets() {
    const list = $("editor-asset-list");
    $("editor-asset-count").textContent = String(assets.length);
    list.innerHTML = "";
    if (!assets.length) {
      list.innerHTML = '<div class="empty-state compact"><strong>No zone assets</strong><p>This is a new profile. Draw a polygon and choose Save asset.</p></div>';
      return;
    }
    assets.forEach(asset => {
      const selected = asset.id === activeAssetId;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `editor-asset-item ${selected ? "selected" : ""}`;
      button.setAttribute("aria-pressed", String(selected));
      button.innerHTML = `<span class="asset-mark" aria-hidden="true">◇</span><span><strong>${safe(asset.name)}</strong><small>${safe(asset.updated_at || asset.source_name || "Saved asset")}</small></span><span class="badge">${selected ? "Loaded" : "Edit"}</span>`;
      button.addEventListener("click", () => applyAsset(asset));
      list.appendChild(button);
    });
  }

  async function refreshAssets(autoSelect = false) {
    const payload = await requestJson("/api/zone-assets", {cache: "no-store"});
    assets = payload.assets || [];
    activeAssetId = payload.active_id || null;
    let selected = assets.find(asset => asset.id === activeAssetId) || null;
    if (autoSelect && !selected && assets.length) {
      selected = assets[0];
      await requestJson("/api/zone-assets/apply", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: selected.id}),
      });
      activeAssetId = selected.id;
    }
    renderAssets();
    return selected;
  }

  async function applyAsset(asset) {
    if (saving || asset.id === activeAssetId) return;
    if (dirty && !confirm("Discard unsaved changes and load this zone asset?")) return;
    $("editor-asset-list").inert = true;
    try {
      await requestJson("/api/zone-assets/apply", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: asset.id}),
      });
      activeAssetId = asset.id;
      renderAssets();
      await loadProfile(asset.name);
      window.TrinityUI.toast(`Loaded ${asset.name}.`);
    } catch (error) {
      window.TrinityUI.toast(error.message, "error");
    } finally {
      $("editor-asset-list").inert = false;
    }
  }

  function setMode(next) {
    mode = next;
    $("select-tool").classList.toggle("active", mode === "select");
    $("draw-tool").classList.toggle("active", mode === "draw");
    $("select-tool").setAttribute("aria-pressed", String(mode === "select"));
    $("draw-tool").setAttribute("aria-pressed", String(mode === "draw"));
    canvas.classList.toggle("drawing", mode === "draw");
    $("canvas-help").textContent = mode === "draw" ? "Click the frame to add vertices. Finish when the boundary is complete." : "Select a polygon or drag one of its vertices to refine the boundary.";
    updateControls();
  }

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(profile.width, (event.clientX - rect.left) * canvas.width / rect.width)),
      Math.max(0, Math.min(profile.height, (event.clientY - rect.top) * canvas.height / rect.height))
    ];
  }

  function polygonContains(point, polygon) {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [xi, yi] = polygon[i]; const [xj, yj] = polygon[j];
      const intersects = ((yi > point[1]) !== (yj > point[1])) && point[0] < (xj - xi) * (point[1] - yi) / ((yj - yi) || 1) + xi;
      if (intersects) inside = !inside;
    }
    return inside;
  }

  function nearestVertex(point, polygon) {
    const rect = canvas.getBoundingClientRect();
    const threshold = 14 * canvas.width / rect.width;
    let best = -1; let distance = Infinity;
    polygon.forEach((candidate, index) => {
      const current = Math.hypot(candidate[0] - point[0], candidate[1] - point[1]);
      if (current < distance && current <= threshold) { best = index; distance = current; }
    });
    return best;
  }

  function draw() {
    if (!profile) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (imageReady) context.drawImage(sourceImage, 0, 0, canvas.width, canvas.height);
    else { context.fillStyle = "#090a0d"; context.fillRect(0, 0, canvas.width, canvas.height); }
    if (!$("overlay-toggle").checked) return;

    profile.zones.forEach((zone, zoneIndex) => {
      if (!zone.polygon.length) return;
      const color = colors[zone.type] || colors.warning_zone;
      context.beginPath();
      zone.polygon.forEach((point, index) => index ? context.lineTo(point[0], point[1]) : context.moveTo(point[0], point[1]));
      if (zone.polygon.length >= 3 && !(mode === "draw" && zoneIndex === selectedIndex)) context.closePath();
      context.fillStyle = color.fill;
      if (zone.polygon.length >= 3) context.fill();
      context.strokeStyle = color.line;
      context.lineWidth = zoneIndex === selectedIndex ? Math.max(3, canvas.width / 500) : Math.max(2, canvas.width / 700);
      context.stroke();

      context.font = `${Math.max(14, canvas.width / 75)}px JetBrains Mono, monospace`;
      context.textBaseline = "bottom";
      const anchor = zone.polygon[0];
      const label = `${zone.id} / ${zone.name}`;
      const textWidth = context.measureText(label).width;
      context.fillStyle = "rgba(8, 9, 12, .86)";
      context.fillRect(anchor[0], Math.max(0, anchor[1] - 30), textWidth + 16, 28);
      context.fillStyle = color.line;
      context.fillText(label, anchor[0] + 8, Math.max(22, anchor[1] - 7));

      if (zoneIndex === selectedIndex) {
        zone.polygon.forEach((point, index) => {
          context.beginPath();
          context.arc(point[0], point[1], Math.max(6, canvas.width / 260), 0, Math.PI * 2);
          context.fillStyle = index === dragPoint ? "#ffffff" : color.line;
          context.fill();
          context.strokeStyle = "#0b0b0f";
          context.lineWidth = Math.max(2, canvas.width / 800);
          context.stroke();
        });
      }
    });
  }

  function renderZoneList(refreshForm = true) {
    const list = $("zone-list");
    list.innerHTML = "";
    if (!profile || !profile.zones.length) {
      list.innerHTML = '<div class="empty-state compact"><strong>No zones configured</strong><p>Use + to choose a zone type and begin drawing.</p></div>';
    } else {
      const entries = selectedIndex >= 0 && !listExpanded
        ? [[profile.zones[selectedIndex], selectedIndex]]
        : profile.zones.map((zone, index) => [zone, index]);
      entries.forEach(([zone, index]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `zone-list-item ${index === selectedIndex ? "selected" : ""}`;
        button.innerHTML = `<span class="zone-swatch ${zone.type}"></span><span><strong>${safe(zone.name)}</strong><small>${safe(zone.id)} · ${zone.polygon.length} vertices</small></span><span aria-hidden="true">›</span>`;
        button.addEventListener("click", () => selectZone(index));
        list.appendChild(button);
      });
      if (profile.zones.length > 1) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "zone-list-toggle";
        toggle.innerHTML = listExpanded
          ? '<span>Collapse list</span><span aria-hidden="true">↑</span>'
          : `<span>Choose another zone</span><strong>${profile.zones.length}</strong>`;
        toggle.addEventListener("click", () => { listExpanded = !listExpanded; renderZoneList(false); });
        list.appendChild(toggle);
      }
    }
    if (refreshForm) populateForm();
  }

  function populateForm() {
    const zone = profile?.zones[selectedIndex];
    $("zone-form").classList.toggle("hidden", !zone);
    updateControls();
    if (!zone) return;
    $("zone-id").value = zone.id;
    $("zone-name").value = zone.name;
    $("zone-type").value = zone.type;
    $("point-count").textContent = zone.polygon.length;
    updateControls();
  }

  function selectZone(index) {
    selectedIndex = index;
    dragPoint = -1;
    listExpanded = false;
    closeZoneCreator();
    setMode("select");
    renderZoneList();
    draw();
  }

  function updateControls() {
    const zone = profile?.zones[selectedIndex];
    const count = zone?.polygon.length || 0;
    $("add-zone").disabled = !profile || !imageReady;
    $("create-warning-zone").disabled = !profile || !imageReady;
    $("create-danger-zone").disabled = !profile || !imageReady;
    $("select-tool").disabled = !profile || !imageReady;
    $("draw-tool").disabled = !zone || !imageReady;
    $("redraw-zone").disabled = !zone || !imageReady;
    $("undo-point").disabled = !zone || !count;
    $("finish-polygon").disabled = !zone || mode !== "draw" || count < 3;
    if (zone) $("point-count").textContent = count;
  }

  function nextZoneId() {
    const used = new Set(profile.zones.map(zone => zone.id));
    let value = 1;
    while (used.has(`Z${String(value).padStart(2, "0")}`)) value += 1;
    return `Z${String(value).padStart(2, "0")}`;
  }

  function closeZoneCreator() {
    $("zone-create-panel").classList.add("hidden");
    $("add-zone").classList.remove("active");
    $("add-zone").setAttribute("aria-expanded", "false");
  }

  function toggleZoneCreator() {
    if (!profile || !imageReady) return;
    const incompleteIndex = profile.zones.findIndex(zone => zone.polygon.length < 3);
    if (incompleteIndex >= 0) {
      selectedIndex = incompleteIndex;
      listExpanded = false;
      setMode("draw");
      renderZoneList();
      draw();
      window.TrinityUI.toast("Finish the current polygon before creating another zone.", "error");
      return;
    }
    if (dirty && profile.zones.length) {
      window.TrinityUI.toast("Save the current zone asset before creating another zone.", "error");
      return;
    }
    const panel = $("zone-create-panel");
    const opening = panel.classList.contains("hidden");
    panel.classList.toggle("hidden", !opening);
    $("add-zone").classList.toggle("active", opening);
    $("add-zone").setAttribute("aria-expanded", String(opening));
    if (opening) $("create-warning-zone").focus();
  }

  function addZone(type = "warning_zone") {
    if (!profile || $("zone-create-panel").classList.contains("hidden")) return;
    rememberChange();
    const id = nextZoneId();
    const label = type === "danger_zone" ? "Danger zone" : "Warning zone";
    profile.zones.push({ id, name: `${label} ${profile.zones.length + 1}`, type, polygon: [] });
    selectedIndex = profile.zones.length - 1;
    listExpanded = false;
    closeZoneCreator();
    setDirty(true);
    renderZoneList();
    setMode("draw");
    draw();
    $("zone-name").focus();
    $("zone-name").select();
  }

  function finishPolygon() {
    const zone = profile?.zones[selectedIndex];
    if (!zone || zone.polygon.length < 3) {
      window.TrinityUI.toast("A polygon needs at least three points.", "error");
      return;
    }
    setMode("select");
    renderZoneList();
    draw();
  }

  async function loadProfile(assetName = null) {
    imageReady = false;
    dragPoint = -1;
    history = [];
    listExpanded = false;
    closeZoneCreator();
    setMode("select");
    $("reload-zones").disabled = true;
    $("zone-canvas-state").classList.remove("hidden");
    $("zone-canvas-state").innerHTML = '<span class="spinner"></span><strong>Preparing source frame</strong><p>Loading the saved profile and camera image.</p>';
    $("save-zones").disabled = true;
    try {
      const response = await fetch("/api/zones", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Zone profile unavailable");
      profile = payload.profile;
      if (!profile.width || !profile.height) throw new Error("Source dimensions are unavailable");
      profile.zones = Array.isArray(profile.zones) ? profile.zones : [];
      canvas.width = profile.width;
      canvas.height = profile.height;
      $("zone-source").textContent = payload.source_name || "Active source";
      $("zone-resolution").textContent = `${profile.width} × ${profile.height} · ${payload.profile_name}`;
      const selectedAsset = assets.find(asset => asset.id === activeAssetId);
      $("asset-name").value = assetName || selectedAsset?.name || `${payload.source_name || "Video"} zones`;
      sourceImage.onload = () => { imageReady = true; $("zone-canvas-state").classList.add("hidden"); updateControls(); draw(); };
      sourceImage.onerror = () => { imageReady = false; $("zone-canvas-state").innerHTML = '<strong>Preview unavailable</strong><p>Check that the source file is available, then reload the profile.</p>'; updateControls(); draw(); };
      sourceImage.src = `${payload.frame_url}?t=${Date.now()}`;
      selectedIndex = profile.zones.length ? 0 : -1;
      setDirty(false);
      // A loaded working profile can be saved or updated unchanged.
      $("save-zones").disabled = false;
      renderZoneList();
      draw();
    } catch (error) {
      profile = null;
      selectedIndex = -1;
      $("editor-state").textContent = "Unavailable";
      $("zone-source").textContent = "No editable source";
      $("zone-canvas-state").innerHTML = `<strong>Zone editor unavailable</strong><p>${safe(error.message)}. Start a pipeline run with a valid source and zone profile.</p>`;
      renderZoneList();
    } finally {
      $("reload-zones").disabled = false;
    }
  }

  async function saveProfile() {
    if (!profile || saving) return;
    const incomplete = profile.zones.find(zone => zone.polygon.length < 3);
    if (incomplete) {
      selectZone(profile.zones.indexOf(incomplete));
      window.TrinityUI.toast(`${incomplete.name} needs at least three points.`, "error");
      return;
    }
    $("save-zones").disabled = true;
    $("save-zones").classList.add("busy");
    $("save-zones").setAttribute("aria-label", "Saving zone asset");
    saving = true;
    document.querySelector(".zone-workspace").inert = true;
    $("reload-zones").disabled = true;
    try {
      const response = await fetch("/api/zones", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({...profile, save_asset:true, asset_name:$("asset-name").value}) });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Could not save zones");
      profile = payload.profile;
      setMode("select");
      setDirty(false);
      history = [];
      listExpanded = false;
      closeZoneCreator();
      const selectedAsset = await refreshAssets(false);
      if (selectedAsset) $("asset-name").value = selectedAsset.name;
      setDirty(false);
      renderZoneList();
      draw();
      window.TrinityUI.toast("Zone asset saved and loaded.");
    } catch (error) {
      setDirty(true);
      window.TrinityUI.toast(error.message, "error");
    } finally {
      saving = false;
      document.querySelector(".zone-workspace").inert = false;
      $("reload-zones").disabled = false;
      $("save-zones").disabled = !profile;
      $("save-zones").classList.remove("busy");
      $("save-zones").setAttribute("aria-label", "Save zone asset");
    }
  }

  canvas.addEventListener("pointerdown", event => {
    if (!profile || !imageReady || selectedIndex < 0) return;
    canvas.focus({ preventScroll: true });
    const point = canvasPoint(event);
    const zone = profile.zones[selectedIndex];
    if (mode === "draw") {
      rememberChange();
      zone.polygon.push(point.map(Math.round));
      setDirty(true); renderZoneList(false); updateControls(); draw(); return;
    }
    const vertex = nearestVertex(point, zone.polygon);
    if (vertex >= 0) {
      rememberChange();
      dragPoint = vertex; canvas.setPointerCapture(event.pointerId); draw(); return;
    }
    const zoneIndex = profile.zones.findIndex(item => item.polygon.length >= 3 && polygonContains(point, item.polygon));
    if (zoneIndex >= 0) selectZone(zoneIndex);
  });
  canvas.addEventListener("pointermove", event => {
    if (dragPoint < 0 || selectedIndex < 0) return;
    profile.zones[selectedIndex].polygon[dragPoint] = canvasPoint(event).map(Math.round);
    setDirty(true); draw();
  });
  canvas.addEventListener("pointerup", event => { if (dragPoint >= 0) { dragPoint = -1; canvas.releasePointerCapture(event.pointerId); renderZoneList(); draw(); } });
  canvas.addEventListener("pointercancel", () => { dragPoint = -1; draw(); });

  $("add-zone").addEventListener("click", toggleZoneCreator);
  $("create-warning-zone").addEventListener("click", () => addZone("warning_zone"));
  $("create-danger-zone").addEventListener("click", () => addZone("danger_zone"));
  $("cancel-create-zone").addEventListener("click", closeZoneCreator);
  $("select-tool").addEventListener("click", () => setMode("select"));
  $("draw-tool").addEventListener("click", () => setMode("draw"));
  $("finish-polygon").addEventListener("click", finishPolygon);
  function removeLastPoint() {
    const zone = profile?.zones[selectedIndex];
    if (!zone?.polygon.length) return;
    rememberChange();
    zone.polygon.pop();
    setDirty(true);
    updateControls();
    renderZoneList();
    draw();
  }
  $("undo-point").addEventListener("click", removeLastPoint);
  $("overlay-toggle").addEventListener("change", draw);
  $("redraw-zone").addEventListener("click", () => { const zone = profile?.zones[selectedIndex]; if (zone) { rememberChange(); zone.polygon = []; setDirty(true); renderZoneList(); setMode("draw"); draw(); } });
  $("delete-zone").addEventListener("click", () => { const zone = profile?.zones[selectedIndex]; if (!zone || !confirm(`Delete ${zone.name}?`)) return; rememberChange(); profile.zones.splice(selectedIndex, 1); selectedIndex = Math.min(selectedIndex, profile.zones.length - 1); listExpanded = false; setDirty(true); renderZoneList(); draw(); });
  [["zone-id", "id"], ["zone-name", "name"], ["zone-type", "type"]].forEach(([elementId, key]) => {
    $(elementId).addEventListener("input", event => {
      const zone = profile?.zones[selectedIndex];
      if (!zone) return;
      if (editingField !== elementId) { rememberChange(); editingField = elementId; }
      zone[key] = event.target.value;
      setDirty(true);
      renderZoneList(false);
      draw();
    });
    $(elementId).addEventListener("blur", () => { editingField = null; });
  });
  $("reload-zones").addEventListener("click", () => { if (!dirty || confirm("Discard unsaved changes and reload the saved profile?")) loadProfile(); });
  $("save-zones").addEventListener("click", saveProfile);
  $("asset-name").addEventListener("input", () => setDirty(true));
  window.TrinityZones = {isDirty:() => dirty, allowNavigation:() => { dirty = false; }};
  window.addEventListener("zone-profile-changed", async () => { const selected = await refreshAssets(false); await loadProfile(selected?.name); });
  document.addEventListener("keydown", event => {
    const isEditable = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if (saving) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !isEditable) {
      event.preventDefault();
      undoLastChange();
      return;
    }
    if (isEditable || ["BUTTON", "A"].includes(document.activeElement.tagName)) return;
    if (event.key === "Backspace") { event.preventDefault(); removeLastPoint(); }
    if (event.key === "Enter" && mode === "draw") finishPolygon();
    if (event.key === "Escape") setMode("select");
  });
  window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
  (async () => {
    try {
      const selected = await refreshAssets(true);
      await loadProfile(selected?.name);
    } catch (error) {
      $("editor-asset-list").innerHTML = `<div class="empty-state compact error"><strong>Assets unavailable</strong><p>${safe(error.message)}</p></div>`;
      await loadProfile();
    }
  })();
})();
