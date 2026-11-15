from __future__ import annotations

from app.presentation.map_node import NODE_H, NODE_W, MapNode

GAP_X, ROW_H, MARGIN = 70, 110, 20
MIN_WIDTH = 1000  # the map spans the page; a wider viewBox keeps boxes at their size


class StackMap:
    """The dashboard's small stack map: each stack a box with its projects
    counted by health, dependants above what they depend on. A stack's row
    is how long its chain of dependencies is (those depending on nothing sit
    at the bottom). Edges run from a dependant's bottom to its dependency's
    top."""

    node_w, node_h = NODE_W, NODE_H

    def __init__(self, stack_health, dependencies):
        """``stack_health``: [(stack, ProjectHealthCounts)]; ``dependencies``:
        {(dependant id, dependency id): labels}, ids as strings."""
        stacks = {str(stack.pk): (stack, counts) for stack, counts in stack_health}
        deps = {}
        for src, tgt in dependencies:
            if src in stacks and tgt in stacks:
                deps.setdefault(src, set()).add(tgt)

        rank = {}

        def depth(sid, seen=()):
            if sid in rank:
                return rank[sid]
            if sid in seen:  # a cycle: break it here
                return 0
            value = 1 + max((depth(t, seen + (sid,)) for t in deps.get(sid, ())), default=-1)
            rank[sid] = value
            return value

        for sid in stacks:
            depth(sid)
        rows = max(rank.values(), default=0) + 1
        by_row = [[] for _ in range(rows)]
        for sid, (stack, _) in sorted(stacks.items(), key=lambda kv: kv[1][0].name.lower()):
            by_row[rows - 1 - rank[sid]].append(sid)

        widest = max((len(r) for r in by_row), default=0)
        self.width = int(max(MIN_WIDTH, widest * NODE_W + (widest - 1) * GAP_X + 2 * MARGIN))
        self.height = rows * ROW_H - (ROW_H - NODE_H) + 2 * MARGIN if stacks else 0

        self.nodes, at = [], {}
        for r, row in enumerate(by_row):
            span = len(row) * NODE_W + (len(row) - 1) * GAP_X
            x0 = (self.width - span) / 2
            for i, sid in enumerate(row):
                stack, counts = stacks[sid]
                node = MapNode(stack, counts, int(round(x0 + i * (NODE_W + GAP_X))), MARGIN + r * ROW_H)
                self.nodes.append(node)
                at[sid] = node

        self.edges = []
        for src, targets in deps.items():
            for tgt in sorted(targets):
                a, b = at[src], at[tgt]
                if b.y <= a.y:
                    continue  # only downward edges (a cycle's back edge is left out)
                top, bottom = a.y + NODE_H, b.y - 6
                mid = round(top + (b.y - top) / 2, 2)
                self.edges.append(f"M{a.cx} {top} V{mid} H{b.cx} V{bottom}")
