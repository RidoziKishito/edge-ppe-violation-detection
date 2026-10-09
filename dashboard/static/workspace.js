(() => {
  const $ = id => document.getElementById(id);
  const safe = window.TrinityUI.escapeHtml;
  let videos = [], pending = false, trigger = null;
  const menu = $("source-menu");

  function toggleMenu(open) {
    menu.classList.toggle("hidden", !open);
    $("source-menu-toggle").setAttribute("aria-expanded", String(open));
  }
  function openPicker(id, button) {
    toggleMenu(false); trigger = button;
    $(id).classList.remove("hidden"); document.body.classList.add("modal-open");
    $(id).querySelector(".modal-panel").focus();
  }
  function closePickers() {
    if (pending) return;
    ["video-picker", "asset-picker"].forEach(id => $(id).classList.add("hidden"));
    document.body.classList.remove("modal-open"); trigger?.focus();
  }
  async function json(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "Request failed. Please try again.");
    return payload;
  }
  function canReplaceSource() {
    return !window.TrinityZones?.isDirty() || confirm("Discard the unsaved polygon changes and select another video?");
  }
  async function selectVideo(body) {
    if (pending || !canReplaceSource()) return;
    pending = true; $("video-feedback").textContent = "Preparing video preview…";
    $("video-list").inert = true; $("upload-video-button").disabled = true;
    try {
      await json("/api/videos", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
      window.TrinityZones?.allowNavigation(); window.location.href = "/";
    } catch (error) { $("video-feedback").textContent = error.message; }
    finally { pending = false; $("video-list").inert = false; $("upload-video-button").disabled = false; }
  }
  function renderVideos() {
    const query = $("video-search").value.toLowerCase().trim();
    const split = $("video-split").value;
    const matches = videos.filter(video => (!query || video.name.toLowerCase().includes(query)) && (!split || video.split === split));
    $("video-list").innerHTML = "";
    if (!matches.length) { $("video-list").innerHTML = '<div class="empty-state compact"><strong>No matching videos</strong><p>Choose another split or browse your computer.</p></div>'; return; }
    matches.forEach(video => {
      const button = document.createElement("button"); button.type = "button"; button.className = "picker-item";
      button.innerHTML = `<span class="file-symbol" aria-hidden="true">▶</span><span><strong>${safe(video.name)}</strong><small>Camera/video ${safe(video.camera_id)}</small></span><span class="badge">${safe(video.split)}</span><span aria-hidden="true">↗</span>`;
      button.addEventListener("click", () => selectVideo({id:video.id})); $("video-list").appendChild(button);
    });
  }
  $("source-menu-toggle").addEventListener("click", () => toggleMenu(menu.classList.contains("hidden")));
  document.addEventListener("click", event => { if (!event.target.closest(".source-menu-wrap")) toggleMenu(false); });
  $("change-camera").addEventListener("click", () => { toggleMenu(false); window.TrinityUI.toast("Change camera is coming soon. Please choose Input video for now."); });
  $("choose-video").addEventListener("click", async () => {
    openPicker("video-picker", $("source-menu-toggle"));
    try { videos = (await json("/api/videos")).videos; renderVideos(); $("video-search").focus(); }
    catch (error) { $("video-list").textContent = error.message; }
  });
  ["video-search", "video-split"].forEach(id => $(id).addEventListener("input", renderVideos));
  $("upload-video-button").addEventListener("click", () => $("video-file").click());
  $("video-file").addEventListener("change", () => {
    const file = $("video-file").files[0];
    if (!file || pending || !canReplaceSource()) { $("video-file").value = ""; return; }
    if (file.size > 2 * 1024 ** 3) { window.TrinityUI.toast("Upload limit: 2 GB. Use the local library for larger CMOT files.", "error"); return; }
    pending = true; $("video-list").inert = true; $("upload-video-button").disabled = true;
    const data = new FormData(); data.append("video", file);
    const xhr = new XMLHttpRequest(); xhr.open("POST", "/api/videos");
    $("video-feedback").textContent = `Uploading ${file.name}…`;
    xhr.upload.onprogress = event => { if (event.lengthComputable) $("video-feedback").textContent = `${Math.round(event.loaded / event.total * 100)}% uploaded · ${file.name}`; };
    xhr.onload = () => {
      try {
        const payload = JSON.parse(xhr.responseText);
        if (xhr.status >= 400 || !payload.ok) throw new Error(payload.error || "Upload failed.");
        window.TrinityZones?.allowNavigation(); window.location.href = "/";
      } catch (error) { $("video-feedback").textContent = error.message; }
    };
    xhr.onerror = () => { $("video-feedback").textContent = "Upload connection lost. Please try again."; };
    xhr.onloadend = () => { pending = false; $("video-list").inert = false; $("upload-video-button").disabled = false; $("video-file").value = ""; };
    xhr.send(data);
  });
  $("choose-asset").addEventListener("click", async () => {
    openPicker("asset-picker", $("choose-asset")); $("asset-list").textContent = "Loading saved assets…";
    try {
      const payload = await json("/api/zone-assets");
      $("asset-source").textContent = payload.source_name ? `Compatible assets / ${payload.source_name}` : "Select an input video first.";
      $("asset-list").innerHTML = "";
      if (!payload.assets.length) $("asset-list").innerHTML = '<div class="empty-state compact"><strong>No saved assets for this video</strong><p>Open Zone editor, draw the boundaries and choose Save asset.</p></div>';
      payload.assets.forEach(asset => {
        const button = document.createElement("button"); button.className = "picker-item"; button.type = "button";
        button.innerHTML = `<span class="file-symbol" aria-hidden="true">◇</span><span><strong>${safe(asset.name)}</strong><small>${safe(asset.source_name)}</small></span><span class="badge">${asset.id === payload.active_id ? "Selected" : "Apply"}</span>`;
        button.addEventListener("click", async () => {
          if (pending || !canReplaceSource()) return;
          pending = true; $("asset-list").inert = true;
          try {
            await json("/api/zone-assets/apply", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({id:asset.id})});
            window.TrinityZones?.allowNavigation(); pending = false; closePickers();
            window.dispatchEvent(new Event("zone-profile-changed"));
            window.TrinityUI.toast(`Applied ${asset.name}.`);
          } catch (error) { window.TrinityUI.toast(error.message,"error"); }
          finally { pending = false; $("asset-list").inert = false; }
        }); $("asset-list").appendChild(button);
      });
    } catch (error) { $("asset-list").textContent = error.message; }
  });
  document.querySelectorAll("[data-close-picker]").forEach(button => button.addEventListener("click",closePickers));
  ["video-picker", "asset-picker"].forEach(id => $(id).addEventListener("click",event => { if (event.target === $(id)) closePickers(); }));
  document.addEventListener("keydown", event => { if (event.key === "Escape") { toggleMenu(false); closePickers(); } });
  for (const [id, endpoint] of [["start-detection","start"],["stop-detection","stop"]]) {
    $(id)?.addEventListener("click",async () => {
      $(id).disabled = true;
      try { await json(`/api/run/${endpoint}`,{method:"POST"}); window.dispatchEvent(new Event("run-changed")); }
      catch (error) { window.TrinityUI.toast(error.message,"error"); }
      finally { $(id).disabled = false; }
    });
  }
})();
