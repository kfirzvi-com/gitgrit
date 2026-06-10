/* Workspace architecture diagram (read-only).
 *
 * Stacks as nodes (with technologies aggregated from their projects and a
 * rolled-up compliance score), stack-to-stack dependencies as edges. Clicking
 * a stack opens its stack view. Built on window.GitGritFlow (flow-common.js),
 * which is loaded ahead of this file along with the React/@xyflow UMD globals.
 */
(function () {
  "use strict";

  var GF = window.GitGritFlow;
  var mount = document.getElementById("architecture-flow");
  if (!mount || !GF) return;

  if (!GF.ready()) {
    mount.innerHTML =
      '<div class="p-8 text-center text-sm opacity-60">Could not load the diagram library.</div>';
    return;
  }

  var h = window.React.createElement;
  var RF = window.ReactFlow;
  var data = GF.readData("architecture-data") || {
    stacks: [],
    external_providers: [],
    external_consumers: [],
    dependencies: [],
  };

  function StackNode(props) {
    var d = props.data;
    var techs = d.technologies || [];
    var hp = GF.healthProps(d.health);
    return h(
      "div",
      { className: "gg-stack-node gg-clickable " + hp.className, style: hp.style },
      h(RF.Handle, {
        type: "target",
        position: RF.Position.Top,
        isConnectable: false,
      }),
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
      d.description
        ? h("p", { className: "gg-stack-node__desc" }, d.description)
        : null,
      h(
        "div",
        { className: "gg-stack-node__meta" },
        d.project_count + (d.project_count === 1 ? " project" : " projects"),
        d.analyzing
          ? h("span", { className: "gg-regenerating" }, " · regenerating…")
          : null
      ),
      techs.length
        ? h(
            "div",
            { className: "gg-stack-node__tech" },
            techs.map(function (t) {
              return h("span", { key: t, className: "gg-tech-badge" }, t);
            })
          )
        : null,
      h(RF.Handle, {
        type: "source",
        position: RF.Position.Bottom,
        isConnectable: false,
      })
    );
  }

  // Nodes: stacks, plus external services aggregated to the workspace —
  // providers at the bottom (we depend on them), consumers at the top.
  var STACK = { w: 240, h: 150 };
  var BOUNDARY = { w: 190, h: 64 };
  var allNodes = []
    .concat(
      data.stacks.map(function (s) {
        return { id: s.id, type: "stack", data: s, w: STACK.w, h: STACK.h };
      })
    )
    .concat(
      (data.external_providers || []).map(function (n) {
        return { id: n.id, type: "extprovider", data: n, w: BOUNDARY.w, h: BOUNDARY.h };
      })
    )
    .concat(
      (data.external_consumers || []).map(function (n) {
        return { id: n.id, type: "extconsumer", data: n, w: BOUNDARY.w, h: BOUNDARY.h };
      })
    );

  var posMap = GF.dagreLayout(
    allNodes.map(function (n) {
      return { id: n.id, width: n.w, height: n.h };
    }),
    data.dependencies,
    { rankdir: "TB" }
  );

  var nodes = allNodes.map(function (n) {
    return { id: n.id, type: n.type, position: posMap[n.id] || { x: 0, y: 0 }, data: n.data };
  });

  var nodeTypes = {
    stack: StackNode,
    extprovider: GF.boundaryNode("is-thirdparty"),
    extconsumer: GF.boundaryNode("is-consumer"),
  };

  var edges = data.dependencies.map(function (dep) {
    var color = GF.EDGE_COLOR[dep.kind] || GF.EDGE_COLOR.workspace;
    return {
      id: dep.id,
      source: dep.source,
      target: dep.target,
      label: dep.label || undefined,
      type: "smoothstep",
      pathOptions: { borderRadius: 10 },
      markerEnd: { type: RF.MarkerType.ArrowClosed, color: color, width: 18, height: 18 },
      style: {
        stroke: color,
        strokeWidth: 1.5,
        strokeDasharray: dep.kind === "workspace" ? undefined : "5 4",
      },
    };
  });

  // Legend: health (dots) + edges (lines).
  function healthRow(level) {
    return h(
      "div",
      { key: level, className: "gg-legend__row" },
      h("span", { className: "gg-legend__dot", style: { background: GF.HEALTH_COLOR[level] } }),
      h("span", null, GF.HEALTH_LABEL[level])
    );
  }
  function edgeRow(kind, label) {
    return h(
      "div",
      { key: kind, className: "gg-legend__row" },
      h("span", { className: "gg-legend__swatch", style: { background: GF.EDGE_COLOR[kind] } }),
      h("span", null, label)
    );
  }

  var legend = h(
    RF.Panel,
    { key: "legend", position: "top-right", className: "gg-legend" },
    h(
      "div",
      { key: "health", className: "gg-legend__section" },
      h("div", { className: "gg-legend__title" }, "Health"),
      healthRow("healthy"),
      healthRow("warning"),
      healthRow("critical"),
      healthRow("unknown")
    ),
    h(
      "div",
      { key: "edges", className: "gg-legend__section" },
      h("div", { className: "gg-legend__title" }, "Edges"),
      edgeRow("workspace", "Stack dependency"),
      edgeRow("public", "External consumer"),
      edgeRow("thirdparty", "External service")
    )
  );

  GF.mount(mount, {
    nodes: nodes,
    edges: edges,
    nodeTypes: nodeTypes,
    extraChildren: [legend],
  });
})();
