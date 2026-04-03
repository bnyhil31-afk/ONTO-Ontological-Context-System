"""
api/federation/crdt.py

Conflict-free Replicated Data Types for ONTO federation.

All implementations are pure Python. No library dependency.
The `crdts` PyPI package (if installed) can wrap these in Phase 4.

CRDT assignments (FEDERATION-SPEC-001 §8.1):
  graph_nodes existence  → ORSet        (add-wins, Shapiro 2011)
  graph_edges weight     → LWWRegister  (timestamp tiebreaker)
  audit trail records    → GSet         (grow-only)
  consent records        → GSet + tombstone
  ppmi_counters          → PNCounter    (positive-negative)
  edge_type registry     → GSet         (append-only)

Conflict detection uses VectorClock comparison, not timestamps.
Timestamps are only a tiebreaker when vector clocks are equal.
See FEDERATION-SPEC-001 §8.2.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import time
import uuid
from typing import Any, Dict, FrozenSet, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# VECTOR CLOCK
# ---------------------------------------------------------------------------

class VectorClock:
    """
    Vector clock for causal ordering across ONTO nodes.
    Stored as JSON in graph_nodes.vector_clock / graph_edges.vector_clock.
    """

    def __init__(self, clock: Optional[Dict[str, int]] = None) -> None:
        self._clock: Dict[str, int] = dict(clock) if clock else {}

    def increment(self, node_id: str) -> "VectorClock":
        """Return a new clock with node_id incremented."""
        new = dict(self._clock)
        new[node_id] = new.get(node_id, 0) + 1
        return VectorClock(new)

    def merge(self, other: "VectorClock") -> "VectorClock":
        """Return a new clock with component-wise maximum."""
        all_nodes = set(self._clock) | set(other._clock)
        merged = {
            n: max(self._clock.get(n, 0), other._clock.get(n, 0))
            for n in all_nodes
        }
        return VectorClock(merged)

    def dominates(self, other: "VectorClock") -> bool:
        """
        True if self happened-before other.
        All components of self >= other AND at least one strictly greater.
        """
        all_nodes = set(self._clock) | set(other._clock)
        at_least_one_greater = False
        for n in all_nodes:
            sv = self._clock.get(n, 0)
            ov = other._clock.get(n, 0)
            if sv < ov:
                return False
            if sv > ov:
                at_least_one_greater = True
        return at_least_one_greater

    def is_concurrent_with(self, other: "VectorClock") -> bool:
        """
        True if neither clock dominates the other.
        A concurrent write is a true conflict — escalate to onto_checkpoint.
        """
        return (
            not self.dominates(other) and not other.dominates(self)
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorClock):
            return False
        all_nodes = set(self._clock) | set(other._clock)
        return all(
            self._clock.get(n, 0) == other._clock.get(n, 0)
            for n in all_nodes
        )

    def to_dict(self) -> Dict[str, int]:
        return dict(self._clock)

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "VectorClock":
        return cls(d) if d else cls()

    def __repr__(self) -> str:
        return f"VectorClock({self._clock!r})"


# ---------------------------------------------------------------------------
# OR-SET
# ---------------------------------------------------------------------------

class ORSet:
    """
    Observed-Remove Set CRDT. Add-wins semantics.
    Formally proven convergent (Shapiro et al. 2011).
    Used for: graph_nodes existence.
    """

    def __init__(
        self,
        add_set: Optional[Dict[Any, Set[str]]] = None,
        rem_set: Optional[Dict[Any, Set[str]]] = None,
    ) -> None:
        self._add: Dict[Any, Set[str]] = (
            {k: set(v) for k, v in add_set.items()} if add_set else {}
        )
        self._rem: Dict[Any, Set[str]] = (
            {k: set(v) for k, v in rem_set.items()} if rem_set else {}
        )

    def add(self, element: Any, tag: Optional[str] = None) -> None:
        """Add element with a unique tag (auto-generated if not given)."""
        t = tag or str(uuid.uuid4())
        self._add.setdefault(element, set()).add(t)

    def remove(self, element: Any) -> None:
        """Remove element by moving its current tags to rem_set."""
        tags = self._add.get(element, set())
        if tags:
            self._rem.setdefault(element, set()).update(tags)

    def contains(self, element: Any) -> bool:
        return bool(
            self._add.get(element, set()) - self._rem.get(element, set())
        )

    def elements(self) -> FrozenSet[Any]:
        return frozenset(e for e in self._add if self.contains(e))

    def merge(self, other: "ORSet") -> "ORSet":
        all_elems = set(self._add) | set(other._add)
        new_add = {
            e: self._add.get(e, set()) | other._add.get(e, set())
            for e in all_elems
        }
        all_rem = set(self._rem) | set(other._rem)
        new_rem = {
            e: self._rem.get(e, set()) | other._rem.get(e, set())
            for e in all_rem
        }
        return ORSet(new_add, new_rem)

    def to_dict(self) -> dict:
        return {
            "add": {str(k): list(v) for k, v in self._add.items()},
            "rem": {str(k): list(v) for k, v in self._rem.items()},
        }

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ORSet":
        if not d:
            return cls()
        return cls(
            add_set={k: set(v) for k, v in d.get("add", {}).items()},
            rem_set={k: set(v) for k, v in d.get("rem", {}).items()},
        )


# ---------------------------------------------------------------------------
# LWW-REGISTER
# ---------------------------------------------------------------------------

class LWWRegister:
    """
    Last-Write-Wins Register. Highest timestamp wins on merge.
    Timestamp is only a tiebreaker when vector clocks are equal.
    Used for: graph_edges weight and confidence values.
    """

    def __init__(
        self,
        value: Any = None,
        timestamp: Optional[float] = None,
    ) -> None:
        self._value = value
        self._ts: float = timestamp if timestamp is not None else 0.0

    def set(self, value: Any, timestamp: Optional[float] = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        if ts >= self._ts:
            self._value = value
            self._ts = ts

    def get(self) -> Tuple[Any, float]:
        return self._value, self._ts

    def merge(self, other: "LWWRegister") -> "LWWRegister":
        if other._ts > self._ts:
            return LWWRegister(other._value, other._ts)
        return LWWRegister(self._value, self._ts)

    def to_dict(self) -> dict:
        return {"value": self._value, "timestamp": self._ts}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "LWWRegister":
        if not d:
            return cls()
        return cls(d.get("value"), d.get("timestamp", 0.0))


# ---------------------------------------------------------------------------
# G-SET
# ---------------------------------------------------------------------------

class GSet:
    """
    Grow-Only Set. Elements only added, never removed.
    Used for: audit trail records, edge_type registry, consent tombstones.
    """

    def __init__(self, elements: Optional[Set[Any]] = None) -> None:
        self._elements: Set[Any] = set(elements) if elements else set()

    def add(self, element: Any) -> None:
        self._elements.add(element)

    def contains(self, element: Any) -> bool:
        return element in self._elements

    def elements(self) -> FrozenSet[Any]:
        return frozenset(self._elements)

    def merge(self, other: "GSet") -> "GSet":
        return GSet(self._elements | other._elements)

    def to_dict(self) -> dict:
        return {"elements": list(self._elements)}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "GSet":
        if not d:
            return cls()
        return cls(set(d.get("elements", [])))


# ---------------------------------------------------------------------------
# PN-COUNTER
# ---------------------------------------------------------------------------

class PNCounter:
    """
    Positive-Negative Counter. Merge takes component-wise maximum of each.
    Value = sum(positive) - sum(negative).
    Used for: ppmi_counters marginal co-occurrence counts.
    """

    def __init__(
        self,
        positive: Optional[Dict[str, float]] = None,
        negative: Optional[Dict[str, float]] = None,
    ) -> None:
        self._pos: Dict[str, float] = dict(positive) if positive else {}
        self._neg: Dict[str, float] = dict(negative) if negative else {}

    def increment(self, node_id: str, amount: float = 1.0) -> None:
        self._pos[node_id] = self._pos.get(node_id, 0.0) + amount

    def decrement(self, node_id: str, amount: float = 1.0) -> None:
        self._neg[node_id] = self._neg.get(node_id, 0.0) + amount

    def value(self) -> float:
        return sum(self._pos.values()) - sum(self._neg.values())

    def merge(self, other: "PNCounter") -> "PNCounter":
        all_pos = set(self._pos) | set(other._pos)
        all_neg = set(self._neg) | set(other._neg)
        return PNCounter(
            {n: max(self._pos.get(n, 0.0), other._pos.get(n, 0.0))
             for n in all_pos},
            {n: max(self._neg.get(n, 0.0), other._neg.get(n, 0.0))
             for n in all_neg},
        )

    def to_dict(self) -> dict:
        return {"positive": self._pos, "negative": self._neg}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "PNCounter":
        if not d:
            return cls()
        return cls(d.get("positive"), d.get("negative"))


# ---------------------------------------------------------------------------
# CONFLICT DETECTION
# ---------------------------------------------------------------------------

def detect_conflict(
    local_vclock: Dict[str, int],
    remote_vclock: Dict[str, int],
    local_ts: float,
    remote_ts: float,
) -> str:
    """
    Determine the relationship between two writes.

    Returns one of:
      "local_wins"  — local dominates remote causally
      "remote_wins" — remote dominates local causally
      "concurrent"  — neither dominates; true conflict; escalate to checkpoint
      "true_tie"    — identical vector clocks; timestamp breaks the tie
    """
    lv = VectorClock.from_dict(local_vclock)
    rv = VectorClock.from_dict(remote_vclock)

    if lv == rv:
        return "local_wins" if local_ts >= remote_ts else "remote_wins"

    if lv.dominates(rv):
        return "local_wins"

    if rv.dominates(lv):
        return "remote_wins"

    return "concurrent"
