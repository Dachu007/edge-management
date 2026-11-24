"""
Module 3 - Load Balancing and Energy Awareness (Section 6.3).

Detects *sustained* overload (not one busy moment) so that new suitable work
can be redirected to other nodes.
"""


class LoadBalancer:
    def __init__(self, util_threshold=0.9, wait_threshold_ms=150, sustain_ms=1000):
        self.util_threshold = util_threshold
        self.wait_threshold_ms = wait_threshold_ms
        self.sustain_ms = sustain_ms
        self.since = {}          # node_id -> time overload started

    def update(self, snapshots, t):
        for nid, s in snapshots.items():
            if s.status != "ok":
                self.since.pop(nid, None)
                continue
            hot = s.cpu_util >= self.util_threshold and s.est_wait_ms >= self.wait_threshold_ms
            if hot:
                self.since.setdefault(nid, t)
            else:
                self.since.pop(nid, None)

    def is_overloaded(self, node_id, t):
        start = self.since.get(node_id)
        return start is not None and (t - start) >= self.sustain_ms

    def overloaded_nodes(self, t):
        return [nid for nid in self.since if self.is_overloaded(nid, t)]

    def filter(self, candidates, t):
        """Drop overloaded nodes, but only if some alternative remains."""
        keep = [c for c in candidates if not self.is_overloaded(c.node.node_id, t)]
        return keep or candidates
