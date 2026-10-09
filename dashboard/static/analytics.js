(() => {
  const ppeTypes = window.TRINITY_PPE_TYPES || [];
  const chartText = "#4b4b4b";
  const chartGrid = "rgba(0,0,0,.12)";
  if (window.Chart) {
    Chart.defaults.color = chartText;
    Chart.defaults.font.family = "Inter, sans-serif";
  }

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      legend: { labels: { color: chartText, usePointStyle: true, boxWidth: 8, padding: 20 } },
      tooltip: { backgroundColor: "#000000", titleColor: "#ffffff", bodyColor: "#eeeeee", padding: 12, cornerRadius: 0, displayColors: true }
    },
    scales: {
      x: { border: { display: false }, grid: { color: chartGrid }, ticks: { color: chartText, maxRotation: 0 } },
      y: { beginAtZero: true, border: { display: false }, grid: { color: chartGrid }, ticks: { color: chartText, precision: 0 } }
    }
  };

  const dayKey = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const within = (event, duration) => Date.now() - new Date(event.timestamp).getTime() <= duration && Date.now() >= new Date(event.timestamp).getTime();
  const topCount = values => {
    const counts = values.reduce((result, value) => { result[value] = (result[value] || 0) + 1; return result; }, {});
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || null;
  };

  function renderSummary(events) {
    document.getElementById("metric-24h").textContent = events.filter(event => within(event, 86400000)).length;
    document.getElementById("metric-7d").textContent = events.filter(event => within(event, 604800000)).length;
    const zone = topCount(events.map(event => event.zone));
    const ppe = topCount(events.flatMap(event => event.missing_ppe));
    document.getElementById("metric-zone").textContent = zone ? `${zone[0]} · ${zone[1]}` : "—";
    document.getElementById("metric-ppe").textContent = ppe ? `${window.TrinityUI.ppeLabel(ppe[0])} · ${ppe[1]}` : "—";
  }

  function hourlyData(events) {
    const now = new Date(); const labels = []; const counts = [];
    for (let i = 23; i >= 0; i -= 1) { const hour = new Date(now.getTime() - i * 3600000); labels.push(`${String(hour.getHours()).padStart(2, "0")}:00`); counts.push(0); }
    events.forEach(event => { const diff = Math.floor((now - new Date(event.timestamp)) / 3600000); if (diff >= 0 && diff < 24) counts[23 - diff] += 1; });
    return { labels, counts };
  }

  function levelData(events) {
    const labels = []; const warning = []; const critical = []; const now = new Date();
    for (let i = 6; i >= 0; i -= 1) {
      const date = new Date(now.getTime() - i * 86400000); const key = dayKey(date);
      labels.push(key.slice(5));
      warning.push(events.filter(event => dayKey(new Date(event.timestamp)) === key && event.alert_level === "WARNING").length);
      critical.push(events.filter(event => dayKey(new Date(event.timestamp)) === key && event.alert_level === "CRITICAL").length);
    }
    return { labels, warning, critical };
  }

  function renderHeatmap(events) {
    const zones = [...new Set(events.map(event => event.zone))].sort();
    const tbody = document.querySelector("#heatmap-table tbody");
    tbody.innerHTML = zones.map(zone => `<tr><th>${window.TrinityUI.escapeHtml(zone)}</th>${ppeTypes.map(type => { const count = events.filter(event => event.zone === zone && event.missing_ppe.includes(type)).length; return `<td><span class="heat-value heat-${Math.min(4, count)}">${count}</span></td>`; }).join("")}</tr>`).join("");
  }

  async function initialize() {
    try {
      const response = await fetch("/api/events", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const events = (await response.json()).events || [];
      document.getElementById("analytics-state").textContent = `${events.length} recorded events`;
      renderSummary(events);
      if (!events.length) {
        document.getElementById("analytics-content").classList.add("hidden");
        document.getElementById("analytics-empty").classList.remove("hidden");
        return;
      }
      renderHeatmap(events);
      if (!window.Chart) {
        document.querySelectorAll(".chart-panel").forEach(panel => {
          panel.querySelector(".chart-wrap").innerHTML = '<div class="empty-state"><strong>Chart library unavailable</strong><p>Check your connection and reload. Event totals and the zone matrix are still available.</p></div>';
        });
        return;
      }
      const hourly = hourlyData(events); const levels = levelData(events);
      new Chart(document.getElementById("hour-chart"), { type: "bar", data: { labels: hourly.labels, datasets: [{ label: "Violations", data: hourly.counts, backgroundColor: "#d5342b", borderRadius: 0, maxBarThickness: 22 }] }, options: baseOptions });
      new Chart(document.getElementById("ppe-chart"), { type: "bar", data: { labels: ppeTypes.map(window.TrinityUI.ppeLabel), datasets: [{ label: "Events", data: ppeTypes.map(type => events.filter(event => event.missing_ppe.includes(type)).length), backgroundColor: ["#050505", "#d5342b", "#777777", "#c67a00"], borderRadius: 0 }] }, options: { ...baseOptions, indexAxis: "y", scales: { x: baseOptions.scales.y, y: baseOptions.scales.x } } });
      new Chart(document.getElementById("level-chart"), { type: "line", data: { labels: levels.labels, datasets: [{ label: "Warning", data: levels.warning, borderColor: "#c67a00", pointBackgroundColor: "#c67a00", tension: 0 }, { label: "Critical", data: levels.critical, borderColor: "#d5342b", pointBackgroundColor: "#d5342b", tension: 0 }] }, options: baseOptions });
    } catch (error) {
      document.getElementById("analytics-state").textContent = "Data unavailable";
      document.getElementById("analytics-content").classList.add("hidden");
      const empty = document.getElementById("analytics-empty"); empty.classList.remove("hidden"); empty.classList.add("error"); empty.querySelector("strong").textContent = "Analytics unavailable";
    }
  }
  initialize();
})();
