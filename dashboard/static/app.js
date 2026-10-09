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

  window.TrinityUI = {
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
      led.className = `status-led ${["running", "starting", "completed", "error"].includes(status) ? status : "idle"}`;
      state.textContent = ({running:"RUN ACTIVE",starting:"LOADING MODEL",stopping:"STOPPING",completed:"COMPLETED",error:"RUN ERROR",failed:"RUN ERROR",ready:"VIDEO READY",stopped:"STOPPED"})[status] || "SYSTEM IDLE";
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
