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
  // Consumers on top, internal projects layered in the middle, workspace
  // dependencies and third-party apps stacked below — so every arrow points
  // downward (depends-on).
  var internalIds = data.projects.map(function (p) {
    return p.id;
  });
  var internalEdges = data.edges.filter(function (e) {
    return e.kind === "internal";
  });
  var consumerIds = data.consumers.map(function (n) {
    return n.id;
  });
  var consumingIds = data.consuming.map(function (n) {
    return n.id;
  });
  var thirdpartyIds = data.thirdparties.map(function (n) {
    return n.id;
  });

  var topRows = consumerIds.length ? 1 : 0;
  var posConsumers = GF.rowLayout(consumerIds, 0);
  var posInternal = GF.layeredLayout(internalIds, internalEdges, {
    baseRow: topRows,
  });
  var bottomStart = topRows + (posInternal.__layerCount || 1);
  var posConsuming = GF.rowLayout(consumingIds, bottomStart);
  var posThird = GF.rowLayout(
    thirdpartyIds,
    bottomStart + (consumingIds.length ? 1 : 0)
  );

  function pos(map, id) {
    return map[id] || { x: 0, y: 0 };
  }

  var nodes = []
    .concat(
      data.projects.map(function (p) {
        return { id: p.id, type: "project", position: pos(posInternal, p.id), data: p };
      })
    )
    .concat(
      data.consumers.map(function (n) {
        return { id: n.id, type: "consumer", position: pos(posConsumers, n.id), data: n };
      })
    )
    .concat(
      data.consuming.map(function (n) {
        return { id: n.id, type: "consuming", position: pos(posConsuming, n.id), data: n };
      })
    )
    .concat(
      data.thirdparties.map(function (n) {
        return { id: n.id, type: "thirdparty", position: pos(posThird, n.id), data: n };
      })
    );

  var edges = data.edges.map(function (e) {
    var color = EDGE_COLOR[e.kind] || EDGE_COLOR.internal;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label || undefined,
      type: "default",
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
