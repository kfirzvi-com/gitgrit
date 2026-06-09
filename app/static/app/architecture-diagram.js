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
        d.project_count + (d.project_count === 1 ? " project" : " projects")
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

  var pos = GF.layeredLayout(
    data.stacks.map(function (s) {
      return s.id;
    }),
    data.dependencies
  );

  var nodes = data.stacks.map(function (s) {
    return {
      id: s.id,
      type: "stack",
      position: pos[s.id] || { x: 0, y: 0 },
      data: s,
    };
  });

  var edges = data.dependencies.map(function (dep) {
    return {
      id: dep.id,
      source: dep.source,
      target: dep.target,
      label: dep.label || undefined,
      type: "default",
      markerEnd: { type: RF.MarkerType.ArrowClosed, width: 18, height: 18 },
      style: { stroke: "rgba(255,255,255,0.28)", strokeWidth: 1.5 },
    };
  });

  // Health legend.
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
    h("div", { className: "gg-legend__title" }, "Health"),
    healthRow("healthy"),
    healthRow("warning"),
    healthRow("critical"),
    healthRow("unknown")
  );

  GF.mount(mount, {
    nodes: nodes,
    edges: edges,
    nodeTypes: { stack: StackNode },
    extraChildren: [legend],
  });
})();
