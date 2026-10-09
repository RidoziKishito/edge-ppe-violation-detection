(() => {
  const $ = id => document.getElementById(id);
  const fileName = value => value ? String(value).split(/[\\/]/).pop() : "Unavailable";
  const formatDate = value => { if (!value) return "Unavailable"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); };
  const yesNo = value => value === true ? "Enabled" : value === false ? "Disabled" : "Unavailable";
  const safe = value => window.TrinityUI.escapeHtml(value == null || value === "" ? "Unavailable" : value);

  function detailRows(items) {
    return items.map(([label, value, title]) => `<div><dt>${safe(label)}</dt><dd${title ? ` title="${safe(title)}"` : ""}>${safe(value)}</dd></div>`).join("");
  }

  async function loadStatus() {
    $("refresh-status").disabled = true;
    try {
      const response = await fetch("/api/run", { cache: "no-store" });
      if (!response.ok) throw new Error("Runtime API unavailable");
      const payload = await response.json(); const run = payload.run;
      if (!payload.active || !run) {
        $("status-led").className = "status-led idle large";
        $("status-title").textContent = "No active run";
        $("status-description").textContent = "Start the edge pipeline to publish runtime metadata.";
        $("status-updated").textContent = "Unavailable";
        return;
      }
      const status = String(run.status || "unknown").toLowerCase();
      $("status-led").className = `status-led ${["running", "starting", "completed", "error"].includes(status) ? status : "unknown"} large`;
      $("status-title").textContent = ({running:"Edge run active",starting:"Loading detector…",stopping:"Stopping run…",completed:"Run completed",error:"Run reported an error",failed:"Run reported an error",ready:"Video ready to start",stopped:"Run stopped"})[status] || "Runtime status unknown";
      $("status-description").textContent = `${run.camera_id || "Local source"} · ${run.source_name || fileName(run.source)}`;
      $("status-updated").textContent = formatDate(run.finished_at || run.updated_at || run.started_at || run.prepared_at);
      $("input-details").innerHTML = detailRows([["Source", run.source_name || fileName(run.source), run.source], ["Camera ID", run.camera_id], ["Zone profile", fileName(run.zone_profile), run.zone_profile], ["Headless mode", yesNo(run.headless)]]);
      $("model-details").innerHTML = detailRows([["Model", fileName(run.model), run.model], ["Confidence threshold", run.confidence], ["IoU threshold", run.iou], ["Inference interval", run.inference_interval ? `Every ${run.inference_interval} frame(s)` : null]]);
      $("rule-details").innerHTML = detailRows([["Temporal smoothing", run.smoothing_frames ? `${run.smoothing_frames} consecutive frames` : null], ["Alert cooldown", run.alert_cooldown_seconds != null ? `${run.alert_cooldown_seconds} seconds` : null], ["Live preview target", run.live_preview_fps != null ? `${run.live_preview_fps} FPS` : null], ["Frame push", run.frame_push_url ? "Configured" : "Disabled", run.frame_push_url]]);
      $("output-details").innerHTML = detailRows([["Run ID", run.run_id], ["Started", formatDate(run.started_at)], ["Finished", formatDate(run.finished_at)], ["Return code", run.return_code == null ? "Unavailable" : run.return_code]]);
    } catch (error) {
      $("status-led").className = "status-led error large"; $("status-title").textContent = "Runtime unavailable"; $("status-description").textContent = "The dashboard could not read active run metadata."; $("status-updated").textContent = "Unavailable";
    } finally { $("refresh-status").disabled = false; }
  }
  $("refresh-status").addEventListener("click", loadStatus);
  loadStatus();
})();
