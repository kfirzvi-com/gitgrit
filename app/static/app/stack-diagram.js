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
    edges: [],
  };

  var EDGE_COLOR = {
    internal: "rgba(255,255,255,0.32)",
    public: "#5eead4",
    consuming: "#c084fc",
    thirdparty: "#facc15",
  };

  // --- Node components -------------------------------------------------------
  function handles() {
    return [
      h(RF.Handle, {
        key: "t",
        type: "target",
        position: RF.Position.Top,
        isConnectable: false,
      }),
      h(RF.Handle, {
        key: "s",
        type: "source",
        position: RF.Position.Bottom,
        isConnectable: false,
      }),
    ];
  }

  function ProjectNode(props) {
    var d = props.data;
    var techs = d.technologies || [];
    var hp = GF.healthProps(d.health);
    return h(
      "div",
      { className: "gg-stack-node gg-clickable " + hp.className, style: hp.style },
      handles(),
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

  function boundaryNode(kindClass) {
    return function (props) {
      var d = props.data;
      return h(
        "div",
        { className: "gg-boundary-node " + kindClass + " gg-clickable" },
        handles(),
        d.stack_name
          ? h("div", { className: "gg-boundary-node__stack" }, d.stack_name)
          : null,
        h("div", { className: "gg-boundary-node__name" }, d.name)
      );
    };
  }

  var nodeTypes = {
    project: ProjectNode,
    consumer: boundaryNode("is-consumer"),
    consuming: boundaryNode("is-consuming"),
    thirdparty: boundaryNode("is-thirdparty"),
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
