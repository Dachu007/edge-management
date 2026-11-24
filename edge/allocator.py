"""
Module 2 - AI-Based Task Allocation (Section 6.2) and baseline methods (Section 5.2.2).

Allocation steps (Section 5.2.1):
  1. receive the task request
  2. read the latest valid resource snapshots
  3. remove nodes that cannot meet memory / bandwidth / availability constraints
  4. (AI) drop sustained-overloaded nodes, prefer nodes that can meet the deadline
  5. apply the policy to the remaining candidates
  6. assign the task or defer it with a capacity warning
  7. record the outcome for evaluation and further training
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass

from .models import EdgeNode, Task, Estimate, ResourceSnapshot, build_nodes, TASK_PROFILES
from .monitor import ResourceMonitor
from .balancer import LoadBalancer
from .reporter import PerformanceReporter

# Fixed node mapping used by the "fixed" and "threshold" baselines
FIXED_MAP = {"traffic": "N1", "surveillance": "N2", "emergency": "N3", "environment": "N4"}

POLICY_LABELS = {
    "fixed": "Fixed mapping",
    "round_robin": "Round robin",
    "least_loaded": "Least loaded (CPU)",
    "threshold": "Threshold reactive",
    "ai": "AI (Q-learning)",
}

AVG_J_PER_MI = 0.0085   # reference value used to normalise energy in the reward


@dataclass
class Candidate:
    node: EdgeNode
    snap: ResourceSnapshot
    est: Estimate


# ==========================================================================
# Reinforcement-learning agent (tabular Q-learning)
# ==========================================================================
class QLearningAgent:
    """
    State  : task type, candidate node, queue-delay bucket of that node,
             and whether the node is predicted to meet the deadline.
    Action : assign the task to one eligible node (deferral handled outside).
    Reward : + deadline success, - completion time ratio, - energy,
             - overload; weighted by task priority.
    Q-values start from the planner's predicted reward and are corrected by
    the ACTUAL outcome (nodes have run-time variability the planner does not
    know about), so the agent learns which nodes are really reliable.
    """

    def __init__(self, alpha=0.15, gamma=0.3, epsilon=0.0, energy_weight=0.2):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.energy_weight = energy_weight
        self.q = {}
        self.visits = {}
        self.pending = None
        self.episodes_trained = 0

    @staticmethod
    def wait_bucket(wait_ms):
        if wait_ms < 20:
            return 0
        if wait_ms < 100:
            return 1
        if wait_ms < 300:
            return 2
        return 3

    def state_key(self, task, cand):
        ok = int(cand.est.completion_ms <= task.deadline_ms)
        return f"{task.task_type}|{cand.node.node_id}|{self.wait_bucket(cand.est.wait_ms)}|{ok}"

    def reward(self, task, outcome: Estimate, overloaded=False):
        ratio = outcome.completion_ms / task.deadline_ms
        r = (1.0 if ratio <= 1.0 else -2.0) - 0.5 * min(ratio, 4.0)
        ref = task.work_mi * AVG_J_PER_MI
        r -= self.energy_weight * (outcome.energy_j / ref)
        if overloaded:
            r -= 0.5
        return r * (1.0 + 0.5 * (task.priority - 1))

    def select(self, task, cands, learn=False, rng=None):
        keys = [self.state_key(task, c) for c in cands]
        for k, c in zip(keys, cands):
            if k not in self.q:
                self.q[k] = self.reward(task, c.est)       # optimistic-informed init
        if learn and self.pending is not None:
            pk, pr = self.pending
            target = pr + self.gamma * max(self.q[k] for k in keys)
            self.q[pk] += self.alpha * (target - self.q[pk])
            self.pending = None
        if learn and rng is not None and rng.random() < self.epsilon:
            idx = rng.randrange(len(cands))
        else:
            idx = max(range(len(cands)), key=lambda i: self.q[keys[i]])
        return idx, keys

    def observe(self, key, reward):
        self.visits[key] = self.visits.get(key, 0) + 1
        self.pending = (key, reward)

    def end_episode(self):
        if self.pending is not None:
            pk, pr = self.pending
            self.q[pk] += self.alpha * (pr - self.q[pk])
            self.pending = None
        self.episodes_trained += 1

    # ------------------------------------------------------------ persistence
    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"q": self.q, "visits": self.visits, "episodes": self.episodes_trained,
                       "alpha": self.alpha, "gamma": self.gamma,
                       "energy_weight": self.energy_weight}, f)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            d = json.load(f)
        a = cls(alpha=d.get("alpha", 0.15), gamma=d.get("gamma", 0.3),
                energy_weight=d.get("energy_weight", 0.2))
        a.q = d["q"]
        a.visits = d.get("visits", {})
        a.episodes_trained = d.get("episodes", 0)
        return a


# ==========================================================================
# Resource manager - ties monitor, balancer, allocator and reporter together
# ==========================================================================
class EdgeResourceManager:
    def __init__(self, nodes=None, policy="ai", agent=None, learning_enabled=True,
                 energy_weight=0.2, seed=0, keep_records=None, keep_history=0):
        self.nodes = nodes or build_nodes()
        self.node_map = {n.node_id: n for n in self.nodes}
        self.monitor = ResourceMonitor(self.nodes, keep_history=keep_history)
        self.balancer = LoadBalancer()
        self.reporter = PerformanceReporter(keep=keep_records)
        self.policy = policy
        self.agent = agent
        self.learning_enabled = learning_enabled
        self.energy_weight = energy_weight
        self.rng = random.Random(seed)
        self._rr = 0

    # ----------------------------------------------------------- filtering
    def feasible(self, task, snaps, t):
        cands, trace = [], []
        for node in self.nodes:
            s = snaps[node.node_id]
            row = {"node_id": node.node_id, "name": node.name, "status": s.status,
                   "reason": "", "est_completion_ms": None, "deadline_ok": None,
                   "overloaded": self.balancer.is_overloaded(node.node_id, t), "score": None}
            if s.status != "ok":
                row["reason"] = f"excluded: {s.status} ({'; '.join(s.issues)})"
            elif task.memory_gb > s.mem_free_gb:
                row["reason"] = f"excluded: needs {task.memory_gb:.2f} GB, only {s.mem_free_gb:.2f} GB free"
            elif task.min_bw_mbps > s.bandwidth_mbps:
                row["reason"] = f"excluded: needs {task.min_bw_mbps} Mbps bandwidth"
            else:
                est = node.estimate(task, t)
                row["est_completion_ms"] = round(est.completion_ms, 1)
                row["deadline_ok"] = est.completion_ms <= task.deadline_ms
                row["reason"] = "eligible"
                cands.append(Candidate(node, s, est))
            trace.append(row)
        return cands, trace

    # ----------------------------------------------------------- baselines
    def _least_loaded(self, cands):
        return min(cands, key=lambda c: (c.snap.cpu_util, c.snap.est_wait_ms, c.node.node_id))

    def _choose_baseline(self, policy, task, cands):
        ids = {c.node.node_id: c for c in cands}
        if policy == "fixed":
            return ids.get(FIXED_MAP[task.task_type])
        if policy == "round_robin":
            order = [n.node_id for n in self.nodes]
            for i in range(len(order)):
                nid = order[(self._rr + i) % len(order)]
                if nid in ids:
                    self._rr = (self._rr + i + 1) % len(order)
                    return ids[nid]
            return None
        if policy == "least_loaded":
            return self._least_loaded(cands)
        if policy == "threshold":
            home = ids.get(FIXED_MAP[task.task_type])
            if home and home.snap.cpu_util < 0.8 and home.snap.est_wait_ms < 150:
                return home
            return self._least_loaded(cands)
        raise ValueError(f"unknown policy {policy}")

    # ----------------------------------------------------------- allocate
    def allocate(self, task: Task, learn=False, with_trace=False):
        t = task.arrival_ms
        t0 = time.perf_counter()
        snaps = self.monitor.collect(t)
        self.balancer.update(snaps, t)
        cands, trace = self.feasible(task, snaps, t)

        policy_used, fallback, chosen, key, reason = self.policy, False, None, None, ""
        if not cands:
            reason = "Capacity warning: no feasible node (memory/bandwidth/availability)"
        elif self.policy == "ai":
            if self.agent is None or not self.learning_enabled:
                policy_used, fallback = "least_loaded", True
                chosen = self._least_loaded(cands)
                self.reporter.event(t, "fallback",
                                    f"Learning policy unavailable - task {task.task_id} used least-loaded fallback")
            else:
                pool = self.balancer.filter(cands, t)
                ok = [c for c in pool if c.est.completion_ms <= task.deadline_ms] or pool
                idx, keys = self.agent.select(task, ok, learn=learn, rng=self.rng)
                chosen, key = ok[idx], keys[idx]
                for row in trace:
                    for c, k in zip(ok, keys):
                        if c.node.node_id == row["node_id"]:
                            row["score"] = round(self.agent.q[k], 3)
        else:
            chosen = self._choose_baseline(self.policy, task, cands)
            if chosen is None:
                reason = "Deferred: mapped node is not feasible for this policy"

        decision_us = (time.perf_counter() - t0) * 1e6

        if chosen is None:
            if not reason:
                reason = "Deferred"
            self.reporter.event(t, "deferral", f"Task {task.task_id} ({task.task_type}) deferred - {reason}")
            rec = dict(task_id=task.task_id, task_type=task.task_type, priority=task.priority,
                       arrival_ms=round(t, 1), node_id=None, deferred=True, reason=reason,
                       net_ms=0, wait_ms=0, exec_ms=0, completion_ms=0, start_ms=0, finish_ms=0,
                       deadline_ms=task.deadline_ms, met=False, energy_j=0,
                       decision_us=round(decision_us, 2), policy=self.policy,
                       policy_used=policy_used, fallback=fallback)
        else:
            overloaded = self.balancer.is_overloaded(chosen.node.node_id, t)
            out = chosen.node.assign(task, t, self.rng)
            if key is not None and learn:
                self.agent.observe(key, self.agent.reward(task, out, overloaded))
            rec = dict(task_id=task.task_id, task_type=task.task_type, priority=task.priority,
                       arrival_ms=round(t, 1), node_id=chosen.node.node_id, deferred=False,
                       reason="assigned" + (" (predicted deadline miss)" if chosen.est.completion_ms > task.deadline_ms else ""),
                       net_ms=round(out.net_ms, 2), wait_ms=round(out.wait_ms, 2),
                       exec_ms=round(out.exec_ms, 2), completion_ms=round(out.completion_ms, 2),
                       start_ms=round(out.start_ms, 2), finish_ms=round(out.finish_ms, 2),
                       deadline_ms=task.deadline_ms, met=out.completion_ms <= task.deadline_ms,
                       energy_j=round(out.energy_j, 4), decision_us=round(decision_us, 2),
                       policy=self.policy, policy_used=policy_used, fallback=fallback)
        self.reporter.record(rec)
        if with_trace:
            rec = dict(rec, trace=trace, task=task.to_dict())
        return rec
