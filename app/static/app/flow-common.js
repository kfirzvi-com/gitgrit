/* Shared helpers for the read-only architecture diagrams.
 *
 * React, ReactDOM, the jsx-runtime and @xyflow/react are loaded ahead of this
 * file as UMD globals (see base templates). This module exposes a small
 * `window.GitGritFlow` API the page-specific diagram scripts build on, so the
 * dashboard (stacks) and stack (projects) diagrams share one mount + layout +
 * click-to-navigate behaviour.
 */
window.GitGritFlow = (function () {
  "use strict";

  function ready() {
    return !!(window.React && window.ReactDOM && window.ReactFlow);
  }

  // Health colour codes — single source of truth for node stripes (via the
  // --gg-health custom property) and legend swatches. Kept in step with the
  // levels in app/presentation/health.py.
  var HEALTH_COLOR = {
    healthy: "#34d399",
    warning: "#fbbf24",
    critical: "#f87171",
    unknown: "#64748b",
  };
  var HEALTH_LABEL = {
    healthy: "Healthy",
    warning: "Needs attention",
    critical: "Critical",
    unknown: "No data",
  };

  /* Props to give a node a left health stripe: a marker class plus the
   * --gg-health custom property the stripe pseudo-element paints with. */
  function healthProps(level) {
    return {
      className: "gg-health",
      style: { "--gg-health": HEALTH_COLOR[level] || HEALTH_COLOR.unknown },
    };
  }

  function scoreBadgeClass(score) {
    if (score >= 80) return "badge-success";
    if (score >= 50) return "badge-warning";
    return "badge-error";
  }

  /* Layer nodes by dependency depth (longest path from a root). Nodes with no
   * incoming edges land on row 0; cycles are guarded so a bad edge can't hang
   * the layout. Returns { id: {x, y} } with each row centered on x = 0. */
  function layeredLayout(ids, edges, opts) {
    opts = opts || {};
    var nodeW = opts.nodeW || 240;
    var gapX = opts.gapX || 70;
    var rowH = opts.rowH || 210;
    var baseRow = opts.baseRow || 0;

    var idSet = {};
    ids.forEach(function (id) {
      idSet[id] = true;
    });
    var preds = {};
    ids.forEach(function (id) {
      preds[id] = [];
    });
    edges.forEach(function (e) {
      if (idSet[e.source] && idSet[e.target]) preds[e.target].push(e.source);
    });

    var layer = {};
    function depthOf(id, onPath) {
      if (layer[id] != null) return layer[id];
      if (onPath.has(id)) return 0;
      onPath.add(id);
      var best = 0;
      preds[id].forEach(function (p) {
        best = Math.max(best, depthOf(p, onPath) + 1);
      });
      onPath.delete(id);
      layer[id] = best;
      return best;
    }
    ids.forEach(function (id) {
      depthOf(id, new Set());
    });

    var rows = {};
    ids.forEach(function (id) {
      (rows[layer[id]] = rows[layer[id]] || []).push(id);
    });

    var pos = {};
    var layerCount = 0;
    Object.keys(rows).forEach(function (l) {
      var row = rows[l];
      var rowWidth = row.length * nodeW + (row.length - 1) * gapX;
      row.forEach(function (id, i) {
        pos[id] = {
          x: i * (nodeW + gapX) - rowWidth / 2,
          y: (baseRow + Number(l)) * rowH,
        };
      });
      layerCount = Math.max(layerCount, Number(l) + 1);
    });
    pos.__layerCount = layerCount;
    return pos;
  }

  /* Place a flat list of ids in a single centered row at row index `row`. */
  function rowLayout(ids, row, opts) {
    opts = opts || {};
    var nodeW = opts.nodeW || 240;
    var gapX = opts.gapX || 70;
    var rowH = opts.rowH || 210;
    var rowWidth = ids.length * nodeW + (ids.length - 1) * gapX;
    var pos = {};
    ids.forEach(function (id, i) {
      pos[id] = { x: i * (nodeW + gapX) - rowWidth / 2, y: row * rowH };
    });
    return pos;
  }

  /* Mount a read-only React Flow into `el`. `extraChildren` (array of React
   * elements) render alongside Background/Controls — used for a legend panel. */
  function mount(el, cfg) {
    var React = window.React;
    var ReactDOM = window.ReactDOM;
    var RF = window.ReactFlow;
    var h = React.createElement;

    function App() {
      var children = [
        h(RF.Background, {
          key: "bg",
          gap: 22,
          size: 1,
          color: "rgba(255,255,255,0.06)",
        }),
        h(RF.Controls, { key: "ctl", showInteractive: false }),
      ];
      (cfg.extraChildren || []).forEach(function (c) {
        children.push(c);
      });
      return h(
        RF.ReactFlow,
        {
          nodes: cfg.nodes,
          edges: cfg.edges,
          nodeTypes: cfg.nodeTypes,
          colorMode: "dark",
          fitView: true,
          fitViewOptions: { padding: 0.2 },
          minZoom: 0.15,
          maxZoom: 2,
          proOptions: { hideAttribution: true },
          nodesDraggable: false,
          nodesConnectable: false,
          elementsSelectable: false,
          nodesFocusable: false,
          edgesFocusable: false,
          onNodeClick: function (evt, node) {
            if (node.data && node.data.url) {
              hideTooltip();
              window.location = node.data.url;
            }
          },
          onNodeMouseEnter: function (evt, node) {
            showTooltip(node, evt);
          },
          onNodeMouseMove: function (evt) {
            moveTooltip(evt);
          },
          onNodeMouseLeave: function () {
            hideTooltip();
          },
        },
        children
      );
    }

    ReactDOM.createRoot(el).render(h(App));
  }

  // --- Health hover tooltip --------------------------------------------------
  // A single fixed-position element reused across nodes (so it isn't scaled by
  // the canvas zoom and isn't clipped by the flow container). Shown only for
  // nodes that carry `issues` — i.e. needs-attention / critical.
  function tooltipEl() {
    var el = document.getElementById("gg-flow-tooltip");
    if (!el) {
      el = document.createElement("div");
      el.id = "gg-flow-tooltip";
      el.className = "gg-flow-tooltip";
      el.style.display = "none";
      document.body.appendChild(el);
    }
    return el;
  }

  function showTooltip(node, evt) {
    var d = node.data || {};
    if (!d.issues || !d.issues.length) {
      hideTooltip();
      return;
    }
    var el = tooltipEl();
    el.textContent = "";

    var head = document.createElement("div");
    head.className = "gg-flow-tooltip__head";
    var dot = document.createElement("span");
    dot.className = "gg-flow-tooltip__dot";
    dot.style.background = HEALTH_COLOR[d.health] || HEALTH_COLOR.unknown;
    var label = document.createElement("span");
    label.textContent =
      (d.name ? d.name + " — " : "") + (HEALTH_LABEL[d.health] || "");
    head.appendChild(dot);
    head.appendChild(label);
    el.appendChild(head);

    var list = document.createElement("ul");
    list.className = "gg-flow-tooltip__list";
    d.issues.forEach(function (issue) {
      var li = document.createElement("li");
      li.textContent = issue; // textContent — never trust names as HTML
      list.appendChild(li);
    });
    el.appendChild(list);

    el.style.display = "block";
    moveTooltip(evt);
  }

  function moveTooltip(evt) {
    var el = document.getElementById("gg-flow-tooltip");
    if (!el || el.style.display === "none") return;
    var pad = 14;
    var r = el.getBoundingClientRect();
    var x = evt.clientX + pad;
    var y = evt.clientY + pad;
    if (x + r.width > window.innerWidth) x = evt.clientX - r.width - pad;
    if (y + r.height > window.innerHeight) y = evt.clientY - r.height - pad;
    el.style.left = Math.max(4, x) + "px";
    el.style.top = Math.max(4, y) + "px";
  }

  function hideTooltip() {
    var el = document.getElementById("gg-flow-tooltip");
    if (el) el.style.display = "none";
  }

  function readData(elId) {
    var el = document.getElementById(elId);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  return {
    ready: ready,
    scoreBadgeClass: scoreBadgeClass,
    HEALTH_COLOR: HEALTH_COLOR,
    HEALTH_LABEL: HEALTH_LABEL,
    healthProps: healthProps,
    layeredLayout: layeredLayout,
    rowLayout: rowLayout,
    mount: mount,
    readData: readData,
  };
})();
