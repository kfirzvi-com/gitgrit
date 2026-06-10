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

  // Last-mounted React Flow instance, captured via onInit so callers can
  // re-fit the view after the container is resized (e.g. expand/collapse).
  var _instance = null;
  function refit(opts) {
    if (_instance) _instance.fitView(opts || { padding: 0.2 });
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

  /* Hierarchical (top-down) layout via dagre. Every edge means "depends on"
   * (source → target), so a top-down rank naturally puts consumers at the top
   * and dependencies at the bottom, and dagre orders nodes within each rank to
   * minimise edge crossings. `items` is [{id, width, height}]; returns
   * { id: {x, y} } as top-left positions for React Flow. Cycles are fine —
   * dagre breaks them internally. */
  function dagreLayout(items, edges, opts) {
    opts = opts || {};
    var dagre = window.dagre;
    var g = new dagre.graphlib.Graph();
    g.setGraph({
      rankdir: opts.rankdir || "TB",
      nodesep: opts.nodesep || 55,
      ranksep: opts.ranksep || 90,
      marginx: 20,
      marginy: 20,
    });
    g.setDefaultEdgeLabel(function () {
      return {};
    });
    var dims = {};
    items.forEach(function (it) {
      dims[it.id] = { width: it.width, height: it.height };
      g.setNode(it.id, { width: it.width, height: it.height });
    });
    edges.forEach(function (e) {
      if (dims[e.source] && dims[e.target]) g.setEdge(e.source, e.target);
    });
    dagre.layout(g);
    var pos = {};
    items.forEach(function (it) {
      var n = g.node(it.id); // dagre returns the node centre
      pos[it.id] = { x: n.x - it.width / 2, y: n.y - it.height / 2 };
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
      // Hover focus: hovering a node lights it + its direct neighbours (and the
      // connecting edges); hovering an edge lights it + its two endpoints.
      // Everything else fades back, to cut through a busy graph.
      var focusState = React.useState(null);
      var focus = focusState[0]; // {kind:"node"|"edge", id} | null
      var setFocus = focusState[1];

      var nodes = cfg.nodes;
      var edges = cfg.edges;
      if (focus) {
        var keepNodes = {};
        var keepEdges = {};
        if (focus.kind === "edge") {
          cfg.edges.forEach(function (e) {
            if (e.id === focus.id) {
              keepEdges[e.id] = 1;
              keepNodes[e.source] = 1;
              keepNodes[e.target] = 1;
            }
          });
        } else {
          // node: keep the node, its neighbours, and incident edges
          keepNodes[focus.id] = 1;
          cfg.edges.forEach(function (e) {
            if (e.source === focus.id || e.target === focus.id) {
              keepEdges[e.id] = 1;
              keepNodes[e.source] = 1;
              keepNodes[e.target] = 1;
            }
          });
        }

        nodes = cfg.nodes.map(function (n) {
          return keepNodes[n.id]
            ? n
            : Object.assign({}, n, {
                className: (n.className ? n.className + " " : "") + "gg-faded",
              });
        });
        edges = cfg.edges.map(function (e) {
          if (keepEdges[e.id]) {
            // emphasise the single hovered edge; neighbourhood edges stay normal
            return focus.kind === "edge"
              ? Object.assign({}, e, {
                  className: (e.className ? e.className + " " : "") + "gg-edge-focus",
                  zIndex: 1000,
                })
              : e;
          }
          return Object.assign({}, e, {
            className: (e.className ? e.className + " " : "") + "gg-faded",
          });
        });
      }

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
          nodes: nodes,
          edges: edges,
          nodeTypes: cfg.nodeTypes,
          colorMode: "dark",
          fitView: true,
          fitViewOptions: { padding: 0.2 },
          minZoom: 0.15,
          maxZoom: 2,
          proOptions: { hideAttribution: true },
          onInit: function (inst) {
            _instance = inst;
          },
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
            setFocus({ kind: "node", id: node.id });
          },
          onNodeMouseMove: function (evt) {
            moveTooltip(evt);
          },
          onNodeMouseLeave: function () {
            hideTooltip();
            setFocus(null);
          },
          onEdgeMouseEnter: function (evt, edge) {
            setFocus({ kind: "edge", id: edge.id });
          },
          onEdgeMouseLeave: function () {
            setFocus(null);
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
    refit: refit,
    scoreBadgeClass: scoreBadgeClass,
    HEALTH_COLOR: HEALTH_COLOR,
    HEALTH_LABEL: HEALTH_LABEL,
    healthProps: healthProps,
    dagreLayout: dagreLayout,
    mount: mount,
    readData: readData,
  };
})();
