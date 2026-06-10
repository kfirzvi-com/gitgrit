/* Per-stack architecture diagram (read-only).
 *
 * Core: the projects inside this stack, with project-to-project edges. Around
 * the periphery, boundary nodes show the stack's relationships that cross its
 * edge:
 *   - consumers (top)    — workspace projects in other stacks that depend on
 *                          one of ours → our project is public-facing.
 *   - consuming (bottom) — workspace projects (other stacks) we depend on.
 *   - third-party (bottom) — external apps we depend on.
 *
 * Edges are coloured by kind and explained by an on-canvas legend. Built on
 * window.GitGritFlow (flow-common.js).
 */
(function () {
  "use strict";

  var GF = window.GitGritFlow;
  var mount = document.getElementById("stack-flow");
  if (!mount || !GF) return;

  if (!GF.ready()) {
    mount.innerHTML =
      '<div class="p-8 text-center text-sm opacity-60">Could not load the diagram library.</div>';
    return;
  }

  var React = window.React;
  var RF = window.ReactFlow;
  var h = React.createElement;
  var data = GF.readData("stack-architecture-data") || {
    projects: [],
    consumers: [],
    consuming: [],
    thirdparties: [],
    external_consumers: [],
    infrastructure: [],
    edges: [],
  };

  var EDGE_COLOR = GF.EDGE_COLOR;

  // --- Node components -------------------------------------------------------
  function ProjectNode(props) {
    var d = props.data;
    var techs = d.technologies || [];
    var hp = GF.healthProps(d.health);
    return h(
      "div",
      { className: "gg-stack-node gg-clickable " + hp.className, style: hp.style },
      GF.handles(),
      h(
        "div",
        { className: "gg-stack-node__head" },
        h("span", { className: "gg-stack-node__name" }, d.name),
        d.score != null
          ? h(
              "span",
              { className: "badge badge-sm " + GF.scoreBadgeClass(d.score) },
              d.score + "%"
            )
          : null
      ),
      h(
        "div",
        { className: "gg-stack-node__meta" },
        h("span", { className: "badge badge-outline badge-xs" }, d.lifecycle)
      ),
      techs.length
        ? h(
            "div",
            { className: "gg-stack-node__tech" },
            techs.map(function (t) {
              return h("span", { key: t, className: "gg-tech-badge" }, t);
            })
          )
        : null
    );
  }

  // Internal infrastructure (a service's own datastore/queue/cache/storage).
  // A distinct internal node (database glyph), not an external boundary node.
  function InfraNode(props) {
    var d = props.data;
    return h(
      "div",
      { className: "gg-infra-node" },
      GF.handles(),
      h(
        "svg",
        { className: "gg-infra-node__glyph", viewBox: "0 0 24 24", "aria-hidden": "true" },
        h("ellipse", { cx: 12, cy: 5, rx: 8, ry: 3 }),
        h("path", { d: "M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" }),
        h("path", { d: "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" })
      ),
      h(
        "div",
        { className: "gg-infra-node__body" },
        h("div", { className: "gg-infra-node__name" }, d.name),
        d.kind && d.kind !== "other"
          ? h("div", { className: "gg-infra-node__kind" }, d.kind)
          : null
      )
    );
  }

  var nodeTypes = {
    project: ProjectNode,
    consumer: GF.boundaryNode("is-consumer"),
    consuming: GF.boundaryNode("is-consuming"),
    thirdparty: GF.boundaryNode("is-thirdparty"),
    // External consumer: external system that depends on us → public-facing
    // (teal), placed at the top like internal consumers, tagged "External".
    extconsumer: GF.boundaryNode("is-consumer"),
    infra: InfraNode,
  };

  // --- Layout ----------------------------------------------------------------
  // One hierarchical (top-down) pass over every node. Because all edges mean
  // "depends on" (consumer → project → dependency), dagre naturally banks
  // consumers at the top, the stack's projects in the middle, and the things
  // we depend on (workspace + third-party) at the bottom — and orders nodes
  // within each rank to minimise crossings.
  var PROJECT = { w: 240, h: 150 };
  var BOUNDARY = { w: 190, h: 64 };

  var allNodes = []
    .concat(
      data.projects.map(function (p) {
        return { id: p.id, type: "project", data: p, w: PROJECT.w, h: PROJECT.h };
      })
    )
    .concat(
      data.consumers.map(function (n) {
        return { id: n.id, type: "consumer", data: n, w: BOUNDARY.w, h: BOUNDARY.h };
      })
    )
    .concat(
      data.consuming.map(function (n) {
        return { id: n.id, type: "consuming", data: n, w: BOUNDARY.w, h: BOUNDARY.h };
      })
    )
    .concat(
      data.thirdparties.map(function (n) {
        return { id: n.id, type: "thirdparty", data: n, w: BOUNDARY.w, h: BOUNDARY.h };
      })
    )
    .concat(
      (data.external_consumers || []).map(function (n) {
        return { id: n.id, type: "extconsumer", data: n, w: BOUNDARY.w, h: BOUNDARY.h };
      })
    )
    .concat(
      (data.infrastructure || []).map(function (n) {
        return { id: n.id, type: "infra", data: n, w: 168, h: 52 };
      })
    );

  var posMap = GF.dagreLayout(
    allNodes.map(function (n) {
      return { id: n.id, width: n.w, height: n.h };
    }),
    data.edges,
    { rankdir: "TB" }
  );

  var nodes = allNodes.map(function (n) {
    return {
      id: n.id,
      type: n.type,
      position: posMap[n.id] || { x: 0, y: 0 },
      data: n.data,
    };
  });

  var edges = data.edges.map(function (e) {
    var color = EDGE_COLOR[e.kind] || EDGE_COLOR.internal;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label || undefined,
      type: "smoothstep",
      pathOptions: { borderRadius: 10 },
      animated: e.kind === "thirdparty",
      markerEnd: { type: RF.MarkerType.ArrowClosed, color: color, width: 18, height: 18 },
      style: {
        stroke: color,
        strokeWidth: 1.5,
        strokeDasharray: e.kind === "internal" ? undefined : "5 4",
      },
    };
  });

  // --- Legend ----------------------------------------------------------------
  function edgeRow(color, label) {
    return h(
      "div",
      { key: label, className: "gg-legend__row" },
      h("span", { className: "gg-legend__swatch", style: { background: color } }),
      h("span", null, label)
    );
  }

  function healthRow(level) {
    return h(
      "div",
      { key: level, className: "gg-legend__row" },
      h("span", {
        className: "gg-legend__dot",
        style: { background: GF.HEALTH_COLOR[level] },
      }),
      h("span", null, GF.HEALTH_LABEL[level])
    );
  }

  var legend = h(
    RF.Panel,
    { key: "legend", position: "top-right", className: "gg-legend" },
    h(
      "div",
      { key: "health", className: "gg-legend__section" },
      h("div", { className: "gg-legend__title" }, "Project health"),
      healthRow("healthy"),
      healthRow("warning"),
      healthRow("critical"),
      healthRow("unknown")
    ),
    h(
      "div",
      { key: "edges", className: "gg-legend__section" },
      h("div", { className: "gg-legend__title" }, "Edges"),
      edgeRow(EDGE_COLOR.internal, "Within stack"),
      edgeRow(EDGE_COLOR.public, "Public-facing"),
      edgeRow(EDGE_COLOR.consuming, "Consumes (workspace)"),
      edgeRow(EDGE_COLOR.thirdparty, "Third-party app")
    )
  );

  GF.mount(mount, {
    nodes: nodes,
    edges: edges,
    nodeTypes: nodeTypes,
    extraChildren: [legend],
  });
})();
