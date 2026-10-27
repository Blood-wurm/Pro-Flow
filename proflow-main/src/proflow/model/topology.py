"""Directed sewer network topology: validation and calculation order.

A pipe runs from its upstream structure to its downstream structure. A
supported network is a tree draining to one outfall: every structure has at
most one outgoing pipe, every pipe's route ends at that outfall, and there
are no cycles. Branches join (several pipes into one structure); flow never
splits. Anything else is reported as an issue with a code, never repaired.

The analysis works on plain links, so it serves Pro-Flow networks and
topology-only test data alike.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# Issue codes. "error": the network is invalid as entered. "unsupported":
# valid hydraulics, but this version does not calculate it.
ERRORS = (
    "no_pipes",
    "unknown_structure",
    "self_loop",
    "outfall_has_outlet",
    "dead_end",
    "cycle",
    "no_outfall",
    "disconnected",
)
UNSUPPORTED = ("flow_split", "several_outfalls")


@dataclass(frozen=True)
class Link:
    pipe: str
    upstream: str
    downstream: str


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    ref: str = ""

    @property
    def level(self) -> str:
        if self.code in UNSUPPORTED:
            return "unsupported"
        return "error" if self.code in ERRORS else "info"

    def __str__(self) -> str:
        where = f" [{self.ref}]" if self.ref else ""
        return f"{self.level}: {self.code}{where}: {self.message}"


@dataclass(frozen=True)
class Topology:
    outfall: str
    links: dict[str, Link]
    downstream: dict[str, str | None]  # pipe -> the pipe it flows into
    upstream: dict[str, tuple[str, ...]]  # pipe -> pipes entering its upstream end
    order: tuple[str, ...]  # outfall pipes first; every pipe after its downstream
    issues: tuple[Issue, ...] = field(default_factory=tuple)  # info only

    @property
    def outfall_pipes(self) -> tuple[str, ...]:
        """The pipes discharging into the outfall (they start at its tailwater)."""
        return tuple(p for p in self.order if self.downstream[p] is None)

    @property
    def headwaters(self) -> tuple[str, ...]:
        return tuple(p for p in self.order if not self.upstream[p])

    @property
    def junctions(self) -> dict[str, tuple[str, ...]]:
        """Structures where two or more pipes join -> the joining pipes."""
        return {
            self.links[p].upstream: self.upstream[p]
            for p in self.order
            if len(self.upstream[p]) > 1
        }

    def downstream_first(self) -> tuple[str, ...]:
        return self.order

    def upstream_first(self) -> tuple[str, ...]:
        return tuple(reversed(self.order))

    def route(self, pipe: str) -> tuple[str, ...]:
        """The pipes from this one down to the outfall, in flow order."""
        out = [pipe]
        while (nxt := self.downstream[out[-1]]) is not None:
            out.append(nxt)
        return tuple(out)


def analyse(
    links: Iterable[Link],
    structures: Iterable[str],
    outfalls: Iterable[str],
) -> tuple[Topology | None, list[Issue]]:
    """Validate the directed network; a Topology only when it is supported."""
    links = list(links)
    known = set(structures)
    outfall_set = set(outfalls)
    issues: list[Issue] = []
    if not links:
        return None, [Issue("no_pipes", "the network has no pipes")]

    for link in links:
        for end in ("upstream", "downstream"):
            sid = getattr(link, end)
            if sid not in known:
                issues.append(
                    Issue(
                        "unknown_structure",
                        f"{end} structure {sid!r} does not exist",
                        link.pipe,
                    )
                )
        if link.upstream == link.downstream:
            issues.append(
                Issue("self_loop", "starts and ends at one structure", link.pipe)
            )

    leaving: dict[str, list[Link]] = {}
    entering: dict[str, list[Link]] = {}
    for link in links:
        leaving.setdefault(link.upstream, []).append(link)
        entering.setdefault(link.downstream, []).append(link)

    for sid, out in sorted(leaving.items()):
        if len(out) > 1:
            names = ", ".join(sorted(x.pipe for x in out))
            issues.append(
                Issue(
                    "flow_split",
                    f"{len(out)} pipes leave this structure ({names}); flow "
                    f"splits and diversions are not supported",
                    sid,
                )
            )
        if sid in outfall_set:
            issues.append(
                Issue(
                    "outfall_has_outlet",
                    f"an outfall cannot have a pipe leaving it ({out[0].pipe})",
                    sid,
                )
            )
    for sid in sorted(set(entering) - set(leaving) - outfall_set):
        names = ", ".join(sorted(x.pipe for x in entering[sid]))
        issues.append(
            Issue(
                "dead_end",
                f"pipes end here ({names}) but nothing leaves and it is not an outfall",
                sid,
            )
        )
    reached = sorted(outfall_set & set(entering))
    if not reached:
        issues.append(Issue("no_outfall", "no pipe reaches an outfall"))
    elif len(reached) > 1:
        issues.append(
            Issue(
                "several_outfalls",
                f"pipes reach {len(reached)} outfalls ({', '.join(reached)}); "
                f"calculate one system per network",
            )
        )
    for sid in sorted(known - set(leaving) - set(entering)):
        issues.append(Issue("isolated_structure", "no pipe reaches it", sid))

    # Follow each pipe downstream (using the first outgoing pipe where a
    # split was already reported) to find cycles and pipes that never reach
    # the outfall.
    by_up = {sid: out[0] for sid, out in leaving.items()}
    cycle_pipes: set[str] = set()
    for link in links:
        seen: list[str] = []
        cur: Link | None = link
        while cur is not None and cur.pipe not in seen:
            seen.append(cur.pipe)
            cur = by_up.get(cur.downstream)
        if cur is not None:  # came back to a pipe already on this route
            loop = seen[seen.index(cur.pipe) :]
            if not cycle_pipes & set(loop):
                issues.append(
                    Issue("cycle", f"pipes form a loop: {' -> '.join(loop)}", loop[0])
                )
            cycle_pipes |= set(loop)
    if len(reached) == 1:
        target = reached[0]
        for link in links:
            cur, seen = link, set()
            while cur.downstream != target and cur.pipe not in seen:
                seen.add(cur.pipe)
                nxt = by_up.get(cur.downstream)
                if nxt is None:
                    break
                cur = nxt
            if cur.downstream != target and link.pipe not in cycle_pipes:
                issues.append(
                    Issue(
                        "disconnected",
                        f"its route does not reach outfall {target}",
                        link.pipe,
                    )
                )

    if any(i.level != "info" for i in issues):
        return None, issues

    outfall = reached[0]
    by_pipe = {x.pipe: x for x in links}
    downstream = {
        x.pipe: (by_up[x.downstream].pipe if x.downstream in by_up else None)
        for x in links
    }
    upstream = {
        x.pipe: tuple(sorted(y.pipe for y in entering.get(x.upstream, [])))
        for x in links
    }
    order, queue = [], sorted(x.pipe for x in entering[outfall])
    while queue:
        pipe = queue.pop(0)
        order.append(pipe)
        queue.extend(upstream[pipe])
    return (
        Topology(outfall, by_pipe, downstream, upstream, tuple(order), tuple(issues)),
        issues,
    )


def network_topology(net) -> tuple[Topology | None, list[Issue]]:
    """Topology of a proflow.model.network.Network."""
    return analyse(
        (Link(p.id, p.upstream, p.downstream) for p in net.pipes),
        (s.id for s in net.structures),
        (s.id for s in net.structures if s.kind == "outfall"),
    )
