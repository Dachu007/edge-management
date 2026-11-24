"""
Module 1 - Resource Monitoring (Section 6.1).

Keeps a timestamped record for each node. Nodes that stop reporting become
'stale' and snapshots with missing values are flagged 'missing', so that they
never appear falsely attractive to the allocator.
"""
from collections import deque
from dataclasses import replace

from .models import ResourceSnapshot


class ResourceMonitor:
    def __init__(self, nodes, stale_after_ms=2000, keep_history=0):
        self.nodes = {n.node_id: n for n in nodes}
        self.stale_after_ms = stale_after_ms
        self.latest = {}
        self.history = deque(maxlen=keep_history) if keep_history else None

    def _read(self, node, t):
        if node.report_missing:
            # Sensor/agent on the node sends an incomplete report
            return ResourceSnapshot(node.node_id, t, cpu_util=None, mem_used_gb=None,
                                    mem_free_gb=None, bandwidth_mbps=node.bandwidth_mbps,
                                    queue_len=None, est_wait_ms=None,
                                    latency_ms=node.latency_ms, power_w=None)
        used = node.mem_used(t)
        return ResourceSnapshot(
            node.node_id, t,
            cpu_util=round(node.cpu_util(t), 4),
            mem_used_gb=round(used, 3),
            mem_free_gb=round(node.memory_gb - used, 3),
            bandwidth_mbps=node.bandwidth_mbps,
            queue_len=node.queue_len(t),
            est_wait_ms=round(node.est_wait(t), 2),
            latency_ms=node.latency_ms,
            power_w=round(node.power(t), 2),
        )

    def collect(self, t):
        """Return {node_id: validated snapshot} at time t."""
        out = {}
        for nid, node in self.nodes.items():
            if node.online:
                self.latest[nid] = self._read(node, t)
            snap = self.latest.get(nid)
            if snap is None:
                out[nid] = ResourceSnapshot(nid, t, None, None, None, None, None, None, None, None,
                                            status="unavailable", issues=["never reported"])
                continue
            age = t - snap.timestamp
            issues, status = [], "ok"
            if age > self.stale_after_ms:
                status = "stale"
                issues.append(f"no report for {age/1000:.1f}s")
            missing = snap.missing_fields()
            if missing:
                if status == "ok":
                    status = "missing"
                issues.append("missing: " + ", ".join(missing))
            out[nid] = replace(snap, status=status, age_ms=age, issues=issues)
        if self.history is not None:
            self.history.append({nid: s.to_dict() for nid, s in out.items()})
        return out
