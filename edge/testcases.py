"""
System test cases from Chapter 7 (Tables 7.3.1 and 7.3.2).
Each function runs the scenario and returns the ACTUAL result and PASS/FAIL,
filling in the "Actual Result" column that was pending in the report.
"""
import random

from .models import build_nodes
from .allocator import EdgeResourceManager, QLearningAgent
from .simulation import make_task


def _mgr(agent=None, **kw):
    return EdgeResourceManager(build_nodes(), policy="ai", agent=agent or QLearningAgent(), seed=1, **kw)


def tc01(agent=None):
    m = _mgr(agent)
    snaps = m.monitor.collect(0.0)
    fields = ("cpu_util", "mem_free_gb", "bandwidth_mbps", "queue_len", "latency_ms", "power_w")
    complete = all(s.status == "ok" and all(getattr(s, f) is not None for f in fields) for s in snaps.values())
    ok = len(snaps) == len(m.nodes) and complete
    return dict(id="TC01", module="Resource Monitoring",
                action="Collect resource snapshots from all edge nodes",
                expected="Timestamped CPU, memory, bandwidth, queue, latency and energy values stored for every node",
                actual=f"{len(snaps)}/{len(m.nodes)} snapshots collected at t=0 ms, all fields present: {complete}",
                passed=ok)


def tc02(agent=None):
    m = _mgr(agent)
    m.monitor.collect(0.0)
    m.node_map["N3"].online = False             # N3 stops reporting
    task = make_task(1, "emergency", 5000.0, random.Random(2))
    snaps = m.monitor.collect(5000.0)
    rec = m.allocate(task)
    ok = snaps["N3"].status == "stale" and rec["node_id"] not in (None, "N3")
    return dict(id="TC02", module="Resource Monitoring",
                action="Simulate a node (N3) that stops reporting",
                expected="Node marked unavailable / stale and excluded from allocation",
                actual=f"N3 status = '{snaps['N3'].status}'; emergency task assigned to {rec['node_id']}",
                passed=ok)


def tc03(agent=None):
    m = _mgr(agent)
    m.node_map["N4"].report_missing = True      # incomplete report from N4
    snaps = m.monitor.collect(0.0)
    task = make_task(1, "environment", 0.0, random.Random(3))
    rec = m.allocate(task)
    s = snaps["N4"]
    ok = s.status == "missing" and s.mem_free_gb is None and rec["node_id"] != "N4"
    return dict(id="TC03", module="Resource Monitoring",
                action="Provide a snapshot with missing values (N4)",
                expected="Reading flagged; not treated as unused capacity",
                actual=f"N4 status = '{s.status}' ({'; '.join(s.issues)}); task assigned to {rec['node_id']}",
                passed=ok)


def tc04(agent=None):
    m = _mgr(agent)
    task = make_task(1, "surveillance", 0.0, random.Random(4), memory_gb=128.0)
    rec = m.allocate(task)
    ok = rec["deferred"] and "Capacity warning" in rec["reason"]
    return dict(id="TC04", module="Task Allocation",
                action="Submit a task whose memory demand (128 GB) exceeds every node",
                expected="Task deferred with a capacity warning",
                actual=f"deferred = {rec['deferred']}; reason = '{rec['reason']}'",
                passed=ok)


def tc05(agent=None):
    m = _mgr(agent)
    rng = random.Random(5)
    # Load N1 and N3 heavily so the nodes have very different loads
    for i in range(30):
        for nid in ("N1", "N3"):
            m.node_map[nid].assign(make_task(1000 + i, "traffic", 0.0, rng), 0.0, rng)
    task = make_task(1, "emergency", 10.0, rng)
    rec = m.allocate(task)
    ok = (not rec["deferred"]) and rec["met"] and rec["node_id"] not in ("N1", "N3")
    return dict(id="TC05", module="Task Allocation",
                action="Submit a high-priority emergency task while nodes have different loads",
                expected="Task assigned to a feasible node that can meet its deadline",
                actual=f"assigned to {rec['node_id']}; completion {rec['completion_ms']:.1f} ms vs deadline {rec['deadline_ms']:.0f} ms",
                passed=ok)


def tc06(agent=None):
    m = _mgr(agent)
    rng = random.Random(6)
    n1 = m.node_map["N1"]
    # Keep N1 saturated for 3 seconds
    for i in range(120):
        n1.assign(make_task(2000 + i, "traffic", 0.0, rng), 0.0, rng)
    for t in range(0, 3001, 250):
        m.balancer.update(m.monitor.collect(float(t)), float(t))
    overloaded = m.balancer.is_overloaded("N1", 3000.0)
    task = make_task(1, "traffic", 3000.0, rng)      # traffic normally maps to N1
    rec = m.allocate(task)
    ok = overloaded and rec["node_id"] not in (None, "N1")
    return dict(id="TC06", module="Load Balancing",
                action="Create sustained overload on N1 (home node for traffic tasks)",
                expected="New suitable work redirected to other nodes",
                actual=f"N1 sustained overload detected = {overloaded}; new traffic task sent to {rec['node_id']}",
                passed=ok)


def tc07(agent=None):
    m = _mgr(agent, learning_enabled=False)
    task = make_task(1, "traffic", 0.0, random.Random(7))
    rec = m.allocate(task)
    logged = any(e["kind"] == "fallback" for e in m.reporter.events)
    ok = rec["fallback"] and rec["policy_used"] == "least_loaded" and logged
    return dict(id="TC07", module="Task Allocation",
                action="Disable the learning policy",
                expected="Fallback basic rule used and the event logged",
                actual=f"policy used = {rec['policy_used']}; fallback = {rec['fallback']}; event logged = {logged}",
                passed=ok)


ALL_TESTS = [tc01, tc02, tc03, tc04, tc05, tc06, tc07]


def run_all(agent=None):
    out = []
    for fn in ALL_TESTS:
        try:
            out.append(fn(agent))
        except Exception as exc:          # report crashes as failures
            out.append(dict(id=fn.__name__.upper(), module="-", action="-", expected="-",
                            actual=f"error: {exc}", passed=False))
    return out
