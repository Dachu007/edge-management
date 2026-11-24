"""
Module 4 - Performance Reporting (Section 6.4).

Records every allocation decision and its outcome, plus events such as
fallbacks and capacity warnings, and produces the evaluation metrics:
utilisation, completion time, workload distribution and energy.
"""
import statistics
from collections import deque


class PerformanceReporter:
    def __init__(self, keep=None):
        self.records = deque(maxlen=keep) if keep else []
        self.events = deque(maxlen=200)

    def record(self, rec):
        self.records.append(rec)
        return rec

    def event(self, t, kind, message):
        self.events.append({"time_ms": round(t, 1), "kind": kind, "message": message})

    # ----------------------------------------------------------- metrics
    def summary(self, nodes, horizon_ms=None):
        recs = list(self.records)
        total = len(recs)
        done = [r for r in recs if not r["deferred"]]
        deferred = total - len(done)
        comp = sorted(r["completion_ms"] for r in done)
        if horizon_ms is None:
            horizon_ms = max([r["finish_ms"] for r in done] + [1.0])
        horizon_ms = max(horizon_ms, 1.0)

        def pct(values, p):
            if not values:
                return 0.0
            k = min(len(values) - 1, int(round(p / 100.0 * (len(values) - 1))))
            return values[k]

        per_type = {}
        for r in recs:
            d = per_type.setdefault(r["task_type"], {"total": 0, "met": 0, "comp": []})
            d["total"] += 1
            if r["met"]:
                d["met"] += 1
            if not r["deferred"]:
                d["comp"].append(r["completion_ms"])
        per_type_out = {
            k: {"total": v["total"],
                "deadline_success": round(100.0 * v["met"] / v["total"], 2) if v["total"] else 0.0,
                "avg_completion_ms": round(statistics.mean(v["comp"]), 2) if v["comp"] else 0.0}
            for k, v in per_type.items()
        }

        util = {n.node_id: round(100.0 * n.busy_ms / (n.cores * horizon_ms), 2) for n in nodes}
        share = {n.node_id: n.assigned for n in nodes}
        task_wh = sum(n.task_energy_j for n in nodes) / 3600.0
        idle_wh = sum(n.idle_w for n in nodes) * (horizon_ms / 1000.0) / 3600.0
        met = sum(1 for r in recs if r["met"])

        return {
            "tasks_total": total,
            "tasks_assigned": len(done),
            "tasks_deferred": deferred,
            "avg_completion_ms": round(statistics.mean(comp), 2) if comp else 0.0,
            "p95_completion_ms": round(pct(comp, 95), 2),
            "deadline_success_pct": round(100.0 * met / total, 2) if total else 0.0,
            "per_type": per_type_out,
            "node_utilisation_pct": util,
            "node_task_share": share,
            "utilisation_imbalance": round(statistics.pstdev(util.values()), 2) if util else 0.0,
            "task_energy_wh": round(task_wh, 4),
            "idle_energy_wh": round(idle_wh, 4),
            "total_energy_wh": round(task_wh + idle_wh, 4),
            "energy_per_task_j": round(sum(n.task_energy_j for n in nodes) / len(done), 3) if done else 0.0,
            "avg_decision_us": round(statistics.mean(r["decision_us"] for r in recs), 2) if recs else 0.0,
            "fallbacks": sum(1 for r in recs if r.get("fallback")),
            "horizon_ms": round(horizon_ms, 1),
            "energy_note": "Energy is a model-based estimate (linear idle-to-max power model), not a measurement.",
        }
