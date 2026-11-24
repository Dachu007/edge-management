"""
Edge computing simulation (Section 3.9.3): workload generation, training of
the Q-learning agent, and fair comparison of all policies on the SAME workload
and infrastructure.
"""
import random

from .models import Task, TASK_PROFILES, build_nodes
from .allocator import EdgeResourceManager, QLearningAgent, POLICY_LABELS


def burst_multiplier(task_type, t_ms, duration_ms, burst):
    """Rush-hour burst in the middle third for traffic and surveillance."""
    if burst and task_type in ("traffic", "surveillance") and duration_ms / 3 <= t_ms < 2 * duration_ms / 3:
        return 2.5
    return 1.0


def make_task(task_id, task_type, t_ms, rng, **overrides):
    p = TASK_PROFILES[task_type]
    task = Task(
        task_id=task_id, task_type=task_type,
        work_mi=round(rng.uniform(*p["work"]), 1),
        memory_gb=round(rng.uniform(*p["mem"]), 3),
        data_mb=round(rng.uniform(*p["data"]), 3),
        min_bw_mbps=p["min_bw"], priority=p["priority"],
        deadline_ms=p["deadline"], arrival_ms=t_ms,
    )
    for k, v in overrides.items():
        if v is not None and hasattr(task, k):
            setattr(task, k, v)
    return task


def generate_arrivals(t_from, t_to, rng, burst=False, rate_scale=1.0, duration_ms=None):
    """Poisson arrivals for every task type in [t_from, t_to)."""
    out = []
    for ttype, p in TASK_PROFILES.items():
        t = t_from
        while True:
            mult = burst_multiplier(ttype, t, duration_ms, burst) if duration_ms else (2.5 if burst and ttype in ("traffic", "surveillance") else 1.0)
            rate = p["rate"] * rate_scale * mult / 1000.0   # per ms
            t += rng.expovariate(rate)
            if t >= t_to:
                break
            out.append((t, ttype))
    out.sort()
    return out


def generate_workload(duration_s=30, seed=1, burst=True, rate_scale=1.0):
    rng = random.Random(seed)
    duration_ms = duration_s * 1000.0
    arrivals = generate_arrivals(0, duration_ms, rng, burst, rate_scale, duration_ms)
    return [make_task(i + 1, tt, round(t, 2), rng) for i, (t, tt) in enumerate(arrivals)]


def run_policy(policy, tasks, agent=None, seed=7, energy_weight=0.2, learn=False):
    mgr = EdgeResourceManager(build_nodes(), policy=policy, agent=agent,
                              energy_weight=energy_weight, seed=seed)
    for task in tasks:
        mgr.allocate(task, learn=learn)
    if learn and agent is not None:
        agent.end_episode()
    return mgr


def timeline(mgr, duration_ms, step_ms=1000):
    """Per-node CPU utilisation (%) and queue length per time bin."""
    horizon = max(duration_ms, max([r["finish_ms"] for r in mgr.reporter.records if not r["deferred"]] + [0]))
    bins = int(horizon // step_ms) + 1
    util = {n.node_id: [0.0] * bins for n in mgr.nodes}
    queue = {n.node_id: [0] * bins for n in mgr.nodes}
    cores = {n.node_id: n.cores for n in mgr.nodes}
    for r in mgr.reporter.records:
        if r["deferred"]:
            continue
        nid, s, f, a = r["node_id"], r["start_ms"], r["finish_ms"], r["arrival_ms"]
        b0, b1 = int(s // step_ms), int(f // step_ms)
        for b in range(b0, min(b1, bins - 1) + 1):
            lo, hi = b * step_ms, (b + 1) * step_ms
            util[nid][b] += max(0.0, min(f, hi) - max(s, lo))
        for b in range(int(a // step_ms) + 1, min(int(s // step_ms), bins - 1) + 1):
            queue[nid][b] += 1      # waiting at the bin boundary
    for nid in util:
        util[nid] = [round(100.0 * v / (cores[nid] * step_ms), 1) for v in util[nid]]
    return {"seconds": list(range(bins)), "util": util, "queue": queue}


def compare_policies(policies, duration_s=30, seed=1, burst=True, rate_scale=1.0,
                     energy_weight=0.2, agent=None):
    tasks = generate_workload(duration_s, seed, burst, rate_scale)
    results, timelines, managers = {}, {}, {}
    for p in policies:
        mgr = run_policy(p, tasks, agent=agent if p == "ai" else None, seed=seed + 1000,
                         energy_weight=energy_weight)
        summary = mgr.reporter.summary(mgr.nodes)
        summary["label"] = POLICY_LABELS.get(p, p)
        results[p] = summary
        timelines[p] = timeline(mgr, duration_s * 1000.0)
        managers[p] = mgr
    return {"tasks": len(tasks), "results": results, "timelines": timelines}, managers


def train_agent(episodes=60, duration_s=30, seed=100, energy_weight=0.2, agent=None, log=None):
    agent = agent or QLearningAgent(energy_weight=energy_weight)
    agent.energy_weight = energy_weight
    curve = []
    for ep in range(episodes):
        agent.epsilon = max(0.02, 0.3 * (1 - ep / max(1, episodes - 1)))
        tasks = generate_workload(duration_s, seed + ep, burst=(ep % 2 == 0), rate_scale=random.Random(ep).uniform(0.8, 1.3))
        mgr = run_policy("ai", tasks, agent=agent, seed=seed + 5000 + ep, energy_weight=energy_weight, learn=True)
        s = mgr.reporter.summary(mgr.nodes)
        curve.append({"episode": ep + 1, "deadline_success_pct": s["deadline_success_pct"],
                      "avg_completion_ms": s["avg_completion_ms"], "epsilon": round(agent.epsilon, 3)})
        if log:
            log(curve[-1])
    agent.epsilon = 0.0
    return agent, curve
