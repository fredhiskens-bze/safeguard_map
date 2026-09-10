(function () {
  "use strict";

  const DIVISION_COLORS = {
    "Mining": "#2a78d6",
    "Manufacturing": "#eb6834",
    "Electricity, gas, water & waste": "#1baf7a",
    "Transport, postal & warehousing": "#4a3aa7",
    "Other": "#9a9890",
  };
  const UNCLASSIFIED_COLOR = "#9a9890";
  const DEFAULT_COLOR = "#2a78d6";

  const RADIUS_MIN = 5;
  const RADIUS_MAX = 32;
  const RADIUS_FIXED = 7;

  const state = {
    data: null,
    yearIndex: 4,
    includeLegacy: true,
    colorMode: "basic",
    sizeMode: "fixed",
    selectedId: null,
    maxEmissions: 1,
  };

  const markersById = new Map();
  let map, markerLayer, chartInstance;
  let anzsicColors = {};     // specific ANZSIC string -> hex, grouped/shaded by division
  let anzsicByDivision = {}; // division -> [anzsic strings], sorted, for the advanced legend

  // ---------- colour: shade an ANZSIC subclass within its division's hue ----------

  function hexToHsl(hex) {
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;
    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        default: h = (r - g) / d + 4;
      }
      h /= 6;
    }
    return { h, s, l };
  }

  function hslToHex(h, s, l) {
    let r, g, b;
    if (s === 0) {
      r = g = b = l;
    } else {
      const hue2rgb = (p, q, t) => {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1 / 6) return p + (q - p) * 6 * t;
        if (t < 1 / 2) return q;
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
        return p;
      };
      const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
      const p = 2 * l - q;
      r = hue2rgb(p, q, h + 1 / 3);
      g = hue2rgb(p, q, h);
      b = hue2rgb(p, q, h - 1 / 3);
    }
    const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
  }

  // Distinct shades of one division's hue for each specific ANZSIC subclass under
  // it -- keeps the (accessibility-validated) division hue as the primary identity
  // channel and uses lightness as a secondary, finer-grained cue within it.
  function shadeColor(baseHex, index, total) {
    if (total <= 1) return baseHex;
    const { h, s } = hexToHsl(baseHex);
    const minL = 0.32, maxL = 0.66;
    const l = minL + ((maxL - minL) * index) / (total - 1);
    return hslToHex(h, Math.max(s, 0.35), l);
  }

  function buildAnzsicColors(facilities) {
    const byDivision = {};
    for (const f of facilities) {
      if (!f.anzsic || !f.division) continue;
      (byDivision[f.division] = byDivision[f.division] || new Set()).add(f.anzsic);
    }
    const colors = {};
    for (const [division, set] of Object.entries(byDivision)) {
      const list = Array.from(set).sort();
      const base = DIVISION_COLORS[division] || UNCLASSIFIED_COLOR;
      list.forEach((anzsic, i) => {
        colors[anzsic] = shadeColor(base, i, list.length);
      });
      anzsicByDivision[division] = list;
    }
    anzsicColors = colors;
  }

  function niceRound(x) {
    if (!x || x <= 0) return 0;
    const exp = Math.floor(Math.log10(x));
    const base = Math.pow(10, exp);
    const frac = x / base;
    let niceFrac;
    if (frac < 1.5) niceFrac = 1;
    else if (frac < 3.5) niceFrac = 2;
    else if (frac < 7.5) niceFrac = 5;
    else niceFrac = 10;
    return niceFrac * base;
  }

  function fmtNum(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Math.round(n).toLocaleString("en-AU");
  }

  function currentYear() {
    return state.data.year_order[state.yearIndex];
  }

  function isLegacyYear(year) {
    return state.data.legacy_years.includes(year);
  }

  function divisionColor(division) {
    if (!division) return UNCLASSIFIED_COLOR;
    return DIVISION_COLORS[division] || UNCLASSIFIED_COLOR;
  }

  function radiusFor(facility, year) {
    if (state.sizeMode === "fixed") return RADIUS_FIXED;
    const rec = facility.years[year];
    const val = rec && rec.covered_emissions;
    if (!val || val <= 0) return RADIUS_MIN;
    const scaled = Math.sqrt(val / state.maxEmissions);
    return RADIUS_MIN + scaled * (RADIUS_MAX - RADIUS_MIN);
  }

  function colorFor(facility) {
    if (state.colorMode === "advanced" && facility.anzsic && anzsicColors[facility.anzsic]) {
      return anzsicColors[facility.anzsic];
    }
    return divisionColor(facility.division);
  }

  // ---------- map setup ----------

  function initMap() {
    map = L.map("map", { zoomControl: true, minZoom: 3 }).setView([-25.5, 134.5], 4.3);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);
  }

  function buildMarkers() {
    markerLayer.clearLayers();
    markersById.clear();

    for (const f of state.data.facilities) {
      if (f.lat === null || f.lon === null) continue;
      const marker = L.circleMarker([f.lat, f.lon], {
        radius: RADIUS_FIXED,
        weight: 1.5,
        color: "#fff",
        fillColor: DEFAULT_COLOR,
        fillOpacity: 0.85,
      });
      marker.bindTooltip(
        `<div class="facility-tooltip"><div class="t-name"></div><div class="t-owner"></div></div>`,
        { direction: "top", offset: [0, -4], sticky: false }
      );
      marker.on("tooltipopen", (e) => {
        const el = e.tooltip.getElement();
        el.querySelector(".t-name").textContent = f.name;
        el.querySelector(".t-owner").textContent = f.emitter || "";
      });
      marker.on("click", () => selectFacility(f.id));
      marker.addTo(markerLayer);
      markersById.set(f.id, { marker, facility: f });
    }
  }

  function updateMarkersForYear() {
    const year = currentYear();
    for (const { marker, facility } of markersById.values()) {
      const rec = facility.years[year];
      const hasData = !!rec;
      const el = marker.getElement ? marker.getElement() : null;
      if (!hasData) {
        marker.setStyle({ opacity: 0, fillOpacity: 0 });
        if (el) el.style.pointerEvents = "none";
      } else {
        marker.setStyle({
          opacity: 1,
          fillOpacity: 0.85,
          radius: radiusFor(facility, year),
          fillColor: colorFor(facility),
        });
        if (el) el.style.pointerEvents = "auto";
      }
    }
  }

  // ---------- year slider ----------

  function computeSliderBounds() {
    const years = state.data.year_order;
    if (state.includeLegacy) return { min: 0, max: years.length - 1 };
    const firstReformedIdx = years.indexOf(state.data.reformed_years[0]);
    return { min: firstReformedIdx, max: years.length - 1 };
  }

  function renderYearTicks() {
    const wrap = document.getElementById("year-ticks");
    wrap.innerHTML = "";
    const years = state.data.year_order;
    const { min, max } = computeSliderBounds();
    years.forEach((y, i) => {
      const span = document.createElement("span");
      span.textContent = y;
      span.className = isLegacyYear(y) ? "legacy" : "reformed";
      if (i < min || i > max) span.classList.add("disabled");
      wrap.appendChild(span);
    });

    const divider = document.getElementById("year-slider-divider");
    const boundaryIdx = years.indexOf(state.data.reformed_years[0]) - 0.5;
    const pct = (boundaryIdx / (years.length - 1)) * 100;
    if (state.includeLegacy) {
      divider.style.left = pct + "%";
      divider.hidden = false;
    } else {
      divider.hidden = true;
    }
  }

  function applySliderBounds() {
    const slider = document.getElementById("year-slider");
    const { min, max } = computeSliderBounds();
    slider.min = min;
    slider.max = max;
    if (state.yearIndex < min) state.yearIndex = min;
    if (state.yearIndex > max) state.yearIndex = max;
    slider.value = state.yearIndex;
    renderYearTicks();
    updateYearReadout();
  }

  function updateYearReadout() {
    const year = currentYear();
    document.getElementById("year-readout-value").textContent = year;
    document.getElementById("year-readout-mechanism").textContent = isLegacyYear(year)
      ? "Pre-reform mechanism"
      : "Reformed mechanism";
  }

  // ---------- legend ----------

  function renderLegend() {
    const legend = document.getElementById("legend");
    const anzsicBox = document.getElementById("legend-anzsic");
    const sizeBox = document.getElementById("legend-size");

    anzsicBox.hidden = false;
    const divisionRow = (name, color) =>
      `<div class="legend-row"><span class="legend-swatch" style="background:${color}"></span>${name}</div>`;

    if (state.colorMode === "advanced") {
      const groups = Object.keys(DIVISION_COLORS)
        .filter((d) => d !== "Other" && anzsicByDivision[d])
        .map((division) => {
          const rows = anzsicByDivision[division]
            .map((anzsic) => divisionRow(anzsic, anzsicColors[anzsic]))
            .join("");
          return `<div class="legend-group-title">${division}</div>${rows}`;
        })
        .join("");
      anzsicBox.innerHTML =
        `<div class="legend-title">Sector (specific)</div>` +
        `<div id="legend-anzsic-scroll">${groups}${divisionRow("Unclassified", UNCLASSIFIED_COLOR)}</div>` +
        `<div class="legend-note">Sector isn't reported before the 2023-24 reform — shown using each facility's most recent known sector.</div>`;
    } else {
      const rows = Object.entries(DIVISION_COLORS)
        .filter(([name]) => name !== "Other")
        .map(([name, color]) => divisionRow(name, color))
        .join("");
      anzsicBox.innerHTML =
        `<div class="legend-title">Sector</div>` +
        rows +
        divisionRow("Unclassified", UNCLASSIFIED_COLOR) +
        `<div class="legend-note">Sector isn't reported before the 2023-24 reform — shown using each facility's most recent known sector.</div>`;
    }

    if (state.sizeMode === "emissions") {
      sizeBox.hidden = false;
      const refs = [niceRound(state.maxEmissions / 20), niceRound(state.maxEmissions / 4), niceRound(state.maxEmissions)];
      sizeBox.innerHTML =
        `<div class="legend-title">Covered emissions (t CO₂-e)</div>` +
        refs
          .map((v) => {
            const r = RADIUS_MIN + Math.sqrt(v / state.maxEmissions) * (RADIUS_MAX - RADIUS_MIN);
            const d = Math.round(r * 2);
            return `<div class="legend-row"><span class="legend-circle" style="width:${d}px;height:${d}px"></span>${fmtNum(v)}</div>`;
          })
          .join("");
    } else {
      sizeBox.hidden = true;
    }

    legend.hidden = anzsicBox.hidden && sizeBox.hidden;
  }

  // ---------- search ----------

  function setupSearch() {
    const input = document.getElementById("search-input");
    const results = document.getElementById("search-results");

    function render(matches) {
      if (!matches.length) {
        results.hidden = true;
        results.innerHTML = "";
        return;
      }
      results.innerHTML = matches
        .slice(0, 25)
        .map(
          (f) => `<div class="search-result" data-id="${f.id}">
            <div class="name"></div>
            <div class="meta"></div>
          </div>`
        )
        .join("");
      // fill text safely (avoid innerHTML with untrusted facility names)
      [...results.querySelectorAll(".search-result")].forEach((row, i) => {
        const f = matches[i];
        row.querySelector(".name").textContent = f.name;
        const meta = row.querySelector(".meta");
        meta.textContent = f.emitter || "";
        if (f.lat === null) {
          const badge = document.createElement("span");
          badge.className = "no-coords";
          badge.textContent = " (no location yet)";
          meta.appendChild(badge);
        }
        row.addEventListener("click", () => {
          input.value = "";
          results.hidden = true;
          if (f.lat !== null) selectFacility(f.id, true);
        });
      });
      results.hidden = false;
    }

    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      if (!q) {
        results.hidden = true;
        return;
      }
      const matches = state.data.facilities.filter(
        (f) =>
          f.name.toLowerCase().includes(q) ||
          (f.emitter && f.emitter.toLowerCase().includes(q))
      );
      render(matches);
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("#search-wrap")) results.hidden = true;
    });
  }

  // ---------- detail panel & chart ----------

  function reformBoundaryPlugin() {
    return {
      id: "reformBoundary",
      afterDraw(chart) {
        const years = chart.data.labels;
        const idx = years.indexOf(state.data.reformed_years[0]);
        if (idx <= 0) return;
        const xAxis = chart.scales.x;
        const prevX = xAxis.getPixelForValue(idx - 1);
        const curX = xAxis.getPixelForValue(idx);
        const x = (prevX + curX) / 2;
        const { top, bottom } = chart.chartArea;
        const ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = "#c3c2b7";
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#898781";
        ctx.font = "10px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Reform", x, top - 4);
        ctx.restore();
      },
    };
  }

  function renderChart(facility) {
    const years = state.data.year_order;
    const actual = years.map((y) => (facility.years[y] ? facility.years[y].covered_emissions : null));
    const baseline = years.map((y) => (facility.years[y] ? facility.years[y].baseline : null));
    const hasAny = actual.some((v) => v !== null) || baseline.some((v) => v !== null);

    const wrap = document.getElementById("chart-wrap");
    if (!hasAny) {
      wrap.innerHTML = `<div class="no-data">No emissions data available for this facility.</div>`;
      return;
    }
    wrap.innerHTML = `<canvas id="facility-chart"></canvas>`;
    const ctx = document.getElementById("facility-chart").getContext("2d");

    if (chartInstance) chartInstance.destroy();
    chartInstance = new Chart(ctx, {
      type: "line",
      data: {
        labels: years,
        datasets: [
          {
            label: "Covered emissions",
            data: actual,
            borderColor: "#2a78d6",
            backgroundColor: "#2a78d6",
            borderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 5,
            spanGaps: false,
            tension: 0,
          },
          {
            label: "Baseline",
            data: baseline,
            borderColor: "#eb6834",
            backgroundColor: "#eb6834",
            borderWidth: 2,
            borderDash: [5, 3],
            pointRadius: 3,
            pointHoverRadius: 4,
            spanGaps: false,
            tension: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 14, font: { size: 11 }, color: "#52514e" } },
          tooltip: {
            callbacks: {
              label: (item) =>
                `${item.dataset.label}: ${item.parsed.y === null ? "no data" : fmtNum(item.parsed.y) + " t CO₂-e"}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#898781", font: { size: 10 } } },
          y: {
            beginAtZero: true,
            grid: { color: "#e1e0d9" },
            ticks: {
              color: "#898781",
              font: { size: 10 },
              callback: (v) => (v >= 1000 ? v / 1000 + "k" : v),
            },
          },
        },
      },
      plugins: [reformBoundaryPlugin()],
    });
  }

  function selectFacility(id, flyTo) {
    const entry = markersById.get(id);
    if (!entry) return;
    state.selectedId = id;
    const f = entry.facility;

    if (flyTo) map.flyTo([f.lat, f.lon], Math.max(map.getZoom(), 7), { duration: 0.6 });

    const panel = document.getElementById("detail-panel");
    const body = document.getElementById("detail-body");
    panel.hidden = false;

    const latestYear = [...state.data.year_order].reverse().find((y) => f.years[y]);
    const latest = latestYear ? f.years[latestYear] : null;
    const hasMymp = Object.values(f.years).some((y) => y.mymp_baseline !== null && y.mymp_baseline !== undefined);
    const hasSplitYear = Object.values(f.years).some((y) => y.split_year);

    body.innerHTML = `
      <h2></h2>
      <div class="owner"></div>
      <div class="sector"></div>
      <div id="stat-rows"></div>
      <div id="chart-wrap"></div>
      <div class="chart-note">Baseline shown as a dashed reference line. The vertical "Reform" marker is where the Safeguard Mechanism's design changed for 2023-24 onward — pre-reform and post-reform baselines aren't calculated on a like-for-like basis.${
        hasMymp
          ? " This facility used a multi-year monitoring baseline in some years — a single cumulative baseline spanning several years rather than an annual one — so an annual baseline isn't shown for those years."
          : ""
      }${
        hasSplitYear
          ? " Some years combine figures from two responsible emitters (e.g. an ownership change partway through the year)."
          : ""
      }</div>
    `;
    body.querySelector("h2").textContent = f.name;
    body.querySelector(".owner").textContent = f.emitter || "";
    body.querySelector(".sector").textContent = f.anzsic
      ? f.anzsic
      : "Sector not classified (no reformed-mechanism data available)";

    const statRows = body.querySelector("#stat-rows");
    if (latest) {
      const rows = [
        [`Covered emissions (${latestYear})`, fmtNum(latest.covered_emissions) + " t"],
        [`Baseline (${latestYear})`, latest.baseline !== null ? fmtNum(latest.baseline) + " t" : "—"],
        ["Years in scheme", Object.keys(f.years).sort().join(", ")],
      ];
      statRows.innerHTML = rows
        .map(([k, v]) => `<div class="stat-row"><span></span><span class="val"></span></div>`)
        .join("");
      [...statRows.querySelectorAll(".stat-row")].forEach((row, i) => {
        row.children[0].textContent = rows[i][0];
        row.children[1].textContent = rows[i][1];
      });
    }

    renderChart(f);
  }

  function closeDetail() {
    document.getElementById("detail-panel").hidden = true;
    state.selectedId = null;
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
  }

  // ---------- wiring ----------

  function setupControls() {
    document.getElementById("detail-close").addEventListener("click", closeDetail);

    document.querySelectorAll("#color-mode-group .toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#color-mode-group .toggle-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.colorMode = btn.dataset.colorMode;
        updateMarkersForYear();
        renderLegend();
      });
    });

    document.querySelectorAll("#size-mode-group .toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#size-mode-group .toggle-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.sizeMode = btn.dataset.sizeMode;
        updateMarkersForYear();
        renderLegend();
      });
    });

    document.getElementById("legacy-toggle").addEventListener("change", (e) => {
      state.includeLegacy = e.target.checked;
      applySliderBounds();
      updateMarkersForYear();
    });

    document.getElementById("year-slider").addEventListener("input", (e) => {
      state.yearIndex = parseInt(e.target.value, 10);
      updateYearReadout();
      updateMarkersForYear();
    });

    setupSearch();
  }

  // ---------- boot ----------

  fetch("data/facilities.json")
    .then((r) => r.json())
    .then((data) => {
      state.data = data;
      state.yearIndex = data.year_order.length - 1;

      let maxEm = 1;
      for (const f of data.facilities) {
        for (const y of Object.values(f.years)) {
          if (y.covered_emissions && y.covered_emissions > maxEm) maxEm = y.covered_emissions;
        }
      }
      state.maxEmissions = maxEm;
      buildAnzsicColors(data.facilities);

      initMap();
      buildMarkers();
      applySliderBounds();
      updateMarkersForYear();
      renderLegend();
      setupControls();
    })
    .catch((err) => {
      document.getElementById("map").innerHTML =
        `<div style="padding:40px;font-family:system-ui">Could not load facility data (data/facilities.json): ${err}</div>`;
    });
})();
