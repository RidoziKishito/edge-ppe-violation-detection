(() => {
  const toggle = document.getElementById("menu-toggle");
  const opener = document.getElementById("sidebar-open");
  const sidebar = document.getElementById("app-sidebar");
  function setSidebar(open, persist = true) {
    document.body.classList.toggle("sidebar-collapsed", !open);
    sidebar.inert = !open;
    toggle.setAttribute("aria-expanded", String(open));
    opener.setAttribute("aria-expanded", String(open));
    if (persist) { try { localStorage.setItem("trinity-sidebar", open ? "open" : "closed"); } catch (_) {} }
  }
  function temporarilyHideSidebar() {
    const wasOpen = !document.body.classList.contains("sidebar-collapsed");
    if (wasOpen) setSidebar(false, false);
    let restored = false;
    return () => {
      if (restored) return;
      restored = true;
      if (wasOpen) setSidebar(true, false);
    };
  }
  setSidebar(!document.body.classList.contains("sidebar-collapsed"), false);
  toggle?.addEventListener("click", () => { setSidebar(false); opener.focus(); });
  opener?.addEventListener("click", () => { setSidebar(true); toggle.focus(); });

  document.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const dialog = document.querySelector('[role="dialog"]:not(.hidden)');
    if (!dialog) return;
    const controls = [...dialog.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]')].filter(element => element.getClientRects().length);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!first) return;
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.querySelector(".modal-panel"))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });

  function setupSnapshotSpotlight(stage, image, layer, event) {
    if (!stage || !image || !layer) return () => {};
    layer.innerHTML = "";
    stage.classList.remove("spotlight-active");
    const width = Number(event.frame_width) || image.naturalWidth;
    const height = Number(event.frame_height) || image.naturalHeight;
    let workers = Array.isArray(event.scene_workers) ? event.scene_workers : [];
    if (!workers.length && event.worker_id_box) {
      workers = [{
        track_id: event.track_id,
        box: event.worker_id_box,
        confidence: event.confidence,
        violations: event.missing_ppe || [],
      }];
    }
    workers = workers.filter(worker => Array.isArray(worker.box) && worker.box.length === 4 && width > 0 && height > 0);
    if (!workers.length) {
      stage.classList.add("spotlight-unavailable");
      return () => {};
    }
    stage.classList.remove("spotlight-unavailable");
    const controls = [];
    let active = null;
    const subjectWorker = workers.find(
      worker => String(worker.track_id) === String(event.track_id)
    ) || workers[0];
    const describe = worker => {
      const violations = (worker.violations || []).map(window.TrinityUI.ppeLabel);
      return violations.length ? violations.join(", ") : "No confirmed violation";
    };
    const activate = control => {
      if (!control || active === control) return;
      controls.forEach(item => item.classList.remove("active"));
      control.classList.add("active");
      stage.classList.add("spotlight-active");
      active = control;
    };
    const deactivate = () => {
      controls.forEach(item => item.classList.remove("active"));
      stage.classList.remove("spotlight-active");
      active = null;
    };
    [subjectWorker].forEach(worker => {
      const [x1, y1, x2, y2] = worker.box.map(Number);
      const control = document.createElement("button");
      control.type = "button";
      control.className = "snapshot-worker-hitbox";
      control.dataset.subject = "true";
      Object.assign(control.style, {
        left: `${Math.max(0, x1) / width * 100}%`,
        top: `${Math.max(0, y1) / height * 100}%`,
        width: `${Math.max(1, Math.min(width, x2) - Math.max(0, x1)) / width * 100}%`,
        height: `${Math.max(1, Math.min(height, y2) - Math.max(0, y1)) / height * 100}%`,
      });
      const workerName = worker.track_id == null ? "Worker" : `Worker ${worker.track_id}`;
      const status = describe(worker);
      control.setAttribute("aria-label", `${workerName}: ${status}`);
      const boxWidth = Math.max(1, Math.min(width, x2) - Math.max(0, x1));
      const boxHeight = Math.max(1, Math.min(height, y2) - Math.max(0, y1));
      control.innerHTML = `<span class="snapshot-worker-sticker" aria-hidden="true"><img src="${window.TrinityUI.escapeHtml(image.currentSrc || image.src)}" alt=""></span>`;
      const stickerImage = control.querySelector(".snapshot-worker-sticker img");
      Object.assign(stickerImage.style, {
        width: `${width / boxWidth * 100}%`,
        height: `${height / boxHeight * 100}%`,
        left: `${-Math.max(0, x1) / boxWidth * 100}%`,
        top: `${-Math.max(0, y1) / boxHeight * 100}%`,
      });
      control.addEventListener("pointerenter", () => activate(control));
      control.addEventListener("pointerleave", deactivate);
      control.addEventListener("focus", () => activate(control));
      control.addEventListener("blur", deactivate);
      control.addEventListener("click", () => activate(control));
      controls.push(control);
      layer.appendChild(control);
    });
    if (subjectWorker) {
      const [x1, y1, x2] = subjectWorker.box.map(Number);
      const states = subjectWorker.ppe_states && typeof subjectWorker.ppe_states === "object"
        ? subjectWorker.ppe_states
        : {};
      const shortPpe = value => ({ helmet: "HEL", vest: "VST", gloves: "GLV", boots: "BTS", goggles: "EYE" })[value]
        || String(value || "PPE").slice(0, 3).toUpperCase();
      const worn = Object.entries(states).filter(([, state]) => state === "WORN").map(([ppe]) => shortPpe(ppe));
      let notWorn = Object.entries(states).filter(([, state]) => state === "NOT_WORN").map(([ppe]) => shortPpe(ppe));
      if (!notWorn.length) {
        notWorn = (event.missing_ppe || []).map(value => shortPpe(String(value).replace(/^no_/, "")));
      }
      const confidence = Number(subjectWorker.confidence ?? event.confidence ?? 0);
      const card = document.createElement("div");
      card.className = "snapshot-subject-card";
      card.setAttribute("aria-label", `Worker ${subjectWorker.track_id ?? "unknown"} PPE status`);
      Object.assign(card.style, {
        top: `${Math.max(0, y1) / height * 100}%`,
        left: `${(x2 / width) * 100}%`,
      });
      if (x2 / width > .72) {
        card.classList.add("card-left");
        card.style.left = `${Math.max(0, x1) / width * 100}%`;
      }
      card.innerHTML = `
        <strong>WORKER ${window.TrinityUI.escapeHtml(subjectWorker.track_id ?? "—")}</strong>
        <span><b>CONF</b>${Math.round(confidence * 100)}%</span>
        <span><b>WORN</b>${window.TrinityUI.escapeHtml(worn.join(" ") || "—")}</span>
        <span><b>NOT WORN</b>${window.TrinityUI.escapeHtml(notWorn.join(" ") || "—")}</span>`;
      layer.appendChild(card);
    }
    const leave = () => deactivate();
    stage.addEventListener("pointerleave", leave);
    return () => {
      stage.removeEventListener("pointerleave", leave);
      deactivate();
      layer.innerHTML = "";
    };
  }

  window.TrinityUI = {
    temporarilyHideSidebar,
    setupSnapshotSpotlight,
    ppeLabel(value) {
      return ({ no_helmet: "Helmet missing", no_gloves: "Gloves missing", no_boots: "Safety boots missing", no_goggle: "Eye protection missing" })[value]
        || String(value || "Unknown").replaceAll("_", " ");
    },
    escapeHtml(value) {
      const node = document.createElement("span");
      node.textContent = value == null ? "" : String(value);
      return node.innerHTML;
    },
    toast(message, tone = "success") {
      const region = document.getElementById("toast-region");
      if (!region) return;
      const toast = document.createElement("div");
      toast.className = `toast toast-${tone}`;
      toast.textContent = message;
      region.appendChild(toast);
      window.setTimeout(() => toast.remove(), 4200);
    }
  };

  async function refreshRuntime() {
    const led = document.getElementById("sidebar-runtime-led");
    const state = document.getElementById("sidebar-runtime-state");
    const source = document.getElementById("sidebar-runtime-source");
    try {
      const response = await fetch("/api/run", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const run = (await response.json()).run || {};
      const status = String(run.status || "idle").toLowerCase();
      led.className = `status-led ${["running", "starting", "finalizing", "completed", "error"].includes(status) ? status : "idle"}`;
      state.textContent = ({running:"RUN ACTIVE",starting:"LOADING MODEL",finalizing:"PREPARING REPLAY",stopping:"STOPPING",completed:"COMPLETED",error:"RUN ERROR",failed:"RUN ERROR",ready:"VIDEO READY",stopped:"STOPPED"})[status] || "SYSTEM IDLE";
      source.textContent = run.source_name || (run.source ? String(run.source).split(/[\\/]/).pop() : "NO SOURCE");
    } catch (error) {
      led.className = "status-led error";
      state.textContent = "UNAVAILABLE";
      source.textContent = "CHECK SERVICE";
    }
  }
  refreshRuntime();
  window.addEventListener("run-changed", refreshRuntime);
  window.setInterval(refreshRuntime, 5000);
})();
