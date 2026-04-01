# GRAPH_THEORY_001
## Theoretical Basis of the ONTO Relationship Graph

**Document ID:** GRAPH_THEORY_001
**Version:** 1.0
**Date:** 2026-04-01
**Status:** Active — reference document for modules/graph.py
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)
**Source audit:** docs/ONTO_s_Theoretical_Foundations__A_Multi-Domain_Research_Audit.md

---

## Purpose

This document records the scientific and philosophical basis for every
major design decision in modules/graph.py. It is the permanent record
that connects code choices to the research that justified them.

Rule 1.09A: Code, tests, and documentation must always agree.
If graph.py changes, this document must be updated in the same commit.

---

## What the research validated (no change needed)

**Co-occurrence as the association primitive** — correct.
Hebbian learning (LTP), Collins & Loftus spreading activation theory (1975),
and ACT-R all build on co-occurrence as the mechanism that strengthens
associative links. Neurons that fire together wire together.

**BFS at depth 2** — one of the strongest design choices in the system.
Balota & Lorch (1986), McNamara & Altarriba (1988), and Coney (1995)
confirm that spreading activation reliably reaches depth 2 (one
intermediary) but produces negligible signal at depth 3+. The ACT-R
fan effect explains why: activation divides at each node, so by depth 3
with average degree 10, signal has diluted below retrieval threshold.

**Multiplicative axis combination** — defensible.
Stanford's Generative Agents (2023) uses recency × importance × relevance
in the same multiplicative pattern and produced SOTA results.

**Temporal decay as core mechanism** — correct in principle.
Every major memory model includes time-dependent accessibility loss.

**Undirected edges for Stage 1** — appropriate.
Co-occurrence is inherently symmetric. Directed edges become essential
only when typed relationships (is-a, causes, part-of) are introduced,
which is a Stage 2 feature.

**The three axes themselves (Distance, Complexity, Size)** — confirmed.
They map to decay (ACT-R activation decay), structural importance (degree
centrality / fan effect), and practice frequency (TF in TF-IDF) — all
well-established dimensions of memory and information retrieval.

---

## What changed and why

### 1. Decay formula: exponential → power law

**Old:** `weight × exp(−0.02 × days)`
**New:** `weight × (1 + days)^(−d)` where d = DECAY_EXPONENT (default 0.5)

**Why:** Simple exponential decay is empirically incorrect.
Wixted (2004) reviewed decades of forgetting research: "all of these
investigations agree that the simple exponential is not a viable candidate."
Rubin & Wenzel (1996) tested 105 two-parameter functions against 210
forgetting datasets — power law was the top performer.

The critical principle is Jost's Law (1897): if two memories have the
same current strength but different ages, the older one decays more slowly.
Exponential decay violates this (constant proportional rate). Power law
satisfies it (older memories decay proportionally more slowly, producing
the long tail characteristic of human memory).

ACT-R uses d = 0.5 as its standard parameter. This is the default in ONTO.
It is configurable via ONTO_GRAPH_DECAY_EXPONENT.

**Sensitive edges:** d × 1.4 (faster decay) to prevent long-term
persistence of distress-related associations. See wellbeing section.

### 2. Reinforcement: flat increment → spacing-effect increment

**Old:** `new_weight = min(1.0, old_weight + 0.08)` always
**New:** `increment = BASE_REINFORCEMENT × spacing_factor(days_since)`

**Why:** The flat +0.08 increment ignores the spacing effect — one of the
most robust findings in memory science. Cepeda et al. (2006) meta-analysis
of 839 studies confirmed that distributed practice dramatically outperforms
massed practice. Pavlik & Anderson (2005) established the mechanism: the
benefit of a practice event is greater when the memory has partially decayed.

The flat increment also saturated after only 7 reinforcements (0.5 + 6×0.08
≈ 0.98), losing all information about heavily-reinforced relationships.

The spacing factor at implementation:
  0 days elapsed:  × 1.00 (immediate re-study)
  1 day elapsed:   × 1.20
  7 days elapsed:  × 1.61 (week gap)
  30 days elapsed: × 2.00 (maximum, after month gap)

SuperMemo's evolution from SM-2 to SM-18 tells the same story: adaptive
timing-dependent reinforcement dramatically outperforms fixed increments.

### 3. Size axis: raw frequency → TF-IDF inspired

**Old:** `size_factor = 1.0 + 0.2 × (log(1+times_seen) / log(101))`
**New:** `size_factor = 1.0 + 0.25 × TF × IDF`
  where `IDF = log((total_inputs + 1) / (inputs_seen + 1)) + 1`

**Why:** TF without IDF is acknowledged in information retrieval literature
as a poor discriminator. Sparck Jones (1972) introduced IDF to address
exactly this: frequent-everywhere concepts ("system", "data", "thing")
are not more relevant — they are less discriminative.

Without IDF, a concept mentioned 50 times would dominate navigation results
even if it appeared in every single input (meaning it carries no specific
information about any particular context).

nodes.inputs_seen was added to the schema to support IDF computation.
graph_metadata.total_inputs_processed tracks the IDF denominator.

### 4. Edge scoring: raw co-occurrence → PPMI approximation

**Old:** initial weight 0.5, flat reinforcement, no measure of
         whether co-occurrence exceeds chance
**New:** PPMI-approximated weight modifier in effective_weight()

**Why:** Raw co-occurrence conflates genuine association with spurious
proximity. Bullinaria & Levy (2007, 2012) found PPMI consistently
produced the best semantic representations across all tasks tested.
Jurafsky & Martin describe PMI as "one of the most important concepts
in NLP."

Full PPMI requires a global co-occurrence matrix. Stage 1 approximation:
  expected = sqrt(times_seen_a × times_seen_b)
  pmi_factor = 0.5 + min(1.0, reinforcement_count / expected)
  range: [0.5, 1.5]

This rewards pairs that co-occur more than frequency alone predicts,
without requiring global statistics. Full PPMI is a Stage 2 item.

### 5. Traversal: flat BFS → BFS with fan effect

**Old:** all neighbours treated equally regardless of source degree
**New:** fan_dilution = 1 / log(1 + source_degree)

**Why:** ACT-R (Anderson 1983) formalises the fan effect: activation from
a source node is divided among all its connections. Nodes with many
connections spread less activation per path. In practice, this prevents
high-degree hub concepts from flooding results — being connected to
everything is not the same as being relevant to this query.

### 6. Concept extraction: naive bigrams → RAKE-inspired scoring

**Old:** stopword filter → unigrams + adjacent bigrams, first N wins
**New:** RAKE degree/frequency scoring → ranked unigrams + bigrams from
         top-scored words, up to MAX_CONCEPTS_PER_INPUT

**Why:** RAKE (Rose et al. 2010) observes that content-bearing words
co-occur with many distinct other words (high degree in a local
co-occurrence graph), while functional words repeat frequently in
isolation (high frequency). Scoring by degree/frequency ranks
content words above functional ones without requiring a larger
stopword list.

This is a Stage 1 stdlib-only implementation. Stage 2: replace with
spaCy NER + noun phrase extraction for dramatically improved quality.
The contract (receives str, returns list[str]) is unchanged.

### 7. Wellbeing protection layer (new)

**What was added:**
  _SENSITIVE_CONCEPTS — reduced reinforcement + faster decay
  _CRISIS_CONCEPTS    — never stored; crisis_detected=True returned
  include_sensitive parameter on navigate()

**Why:** Nolen-Hoeksema (1991, 2008) established rumination as a core
transdiagnostic risk factor for depression and anxiety. A system that
uniformly reinforces all co-occurrences — including distress-related
ones — creates a direct mechanism for amplifying negative associations.

Colombetti & Roberts (2024) demonstrated that technology can scaffold
maladaptive psychological processes. ONTO's graph, which grows
strongest where the user spends most attention, is particularly at risk.

The three-part mitigation:
  1. Crisis content is never stored — surface resources immediately
  2. Sensitive content gets reduced reinforcement (0.02 vs 0.08)
  3. Sensitive edges decay faster (exponent × 1.4)
  4. Sensitive edges excluded from navigate() by default

**Recommendation:** mental health professional review of the sensitive
and crisis concept sets before any deployment serving vulnerable users.

### 8. wipe() function (new — GDPR Article 17)

**What was added:** public wipe() function that deletes all nodes,
edges, and metadata counters.

**Why:** GDPR Article 17 — right to erasure. The graph stores personal
associative data. The audit trail (memory.py) is architecturally
separate and records only that a wipe occurred, not what was in the
graph. See docs/PRIVACY_GDPR.md.

### 9. Lazy decay design

**Old:** decay() updated stored weight values in bulk
**New:** decay() only prunes edges below threshold; stored weight
         represents base weight at last reinforcement; effective weight
         is computed at read time in navigate() using the formula

**Why:** Lazy computation is more accurate (no staleness between decay
runs), avoids write storms on large graphs, and is consistent with how
ACT-R models activation: base-level activation is a function of the
full retrieval history, computed at retrieval time.

---

## What is deferred to Stage 2

These items were identified by the research audit as improvements worth
pursuing, but are not implemented in Stage 1 because they require either
external dependencies, significant architectural changes, or more data
than is available at Stage 1 scale.

**Personalized PageRank (PPR)** — replace BFS depth-2 traversal.
PPR handles multi-hop reasoning, incorporates global graph structure,
and has been validated in HippoRAG (2024), LinearRAG (2025), MixPR (2024).
Requires NetworkX or a purpose-built PageRank implementation.

**Full PPMI** — replace the approximation with a properly computed
positive PMI using a global co-occurrence matrix. Requires tracking
all pair co-occurrences globally, not just per-edge.

**spaCy NER + noun phrases** — replace RAKE-inspired extraction.
Dramatically improves concept quality, especially for named entities,
technical terms, and multi-word phrases.

**Katz/eigenvector centrality** — replace degree centrality for the
Complexity axis. Better at identifying globally important nodes rather
than just locally well-connected ones.

**Directed edges** — for typed relationships (is-a, causes, part-of).
Essential once ONTO starts handling structured knowledge, not just
conversational context.

**Differential decay per individual** — Sense et al. (2016) showed
forgetting rates are stable within individuals but vary between them.
A user-calibrated decay exponent would be more accurate than a global
default.

**Graph entropy monitoring** — detect when the graph becomes excessively
narrow (few hub nodes dominating everything) and surface a warning.
This is the echo chamber detection mechanism from Domain 6 of the audit.

---

## Philosophical framing (corrected)

The research audit found that describing ONTO as "autopoietic" is
technically incorrect. Maturana & Varela's autopoiesis requires
self-production, operational closure, and boundary production — ONTO
satisfies none of these. Maturana himself stated autopoiesis should
not be applied beyond biology.

**Corrected framing:**
  - "autopoietically-inspired" — not "autopoietic"
  - "extended cognitive system" or "cognitive scaffold" — the strongest
    accurate framing (Clark & Chalmers 1998, extended mind thesis)
  - "conatus-like self-maintenance" — Spinoza's Ethics III, Props 6-7
    maps well to the reinforcement-decay mechanism (things that are used
    persist; things that are neglected lose their being)
  - "cognitive scaffolding" — not "artificial consciousness"

The extended mind thesis (Clark & Chalmers 1998) is ONTO's strongest
philosophical identity: an external cognitive resource that extends the
user's memory and context-retrieval, dynamically shaped by use.

---

## References

Anderson, J.R. (1983). The Architecture of Cognition. Harvard UP.
Balota, D.A. & Lorch, R.F. (1986). Depth of automatic spreading activation.
  Journal of Experimental Psychology: Learning, Memory, and Cognition.
Bullinaria, J.A. & Levy, J.P. (2007). Extracting semantic representations
  from word co-occurrence statistics. Behavior Research Methods.
Cepeda, N.J. et al. (2006). Distributed practice in verbal recall tasks:
  a review and quantitative synthesis. Psychological Bulletin.
Clark, A. & Chalmers, D. (1998). The extended mind. Analysis.
Collins, A.M. & Loftus, E.F. (1975). A spreading activation theory of
  semantic processing. Psychological Review.
Colombetti, G. & Roberts, T. (2024). Scaffolded rumination.
Jurafsky, D. & Martin, J.H. (2024). Speech and Language Processing, 3rd ed.
Maturana, H.R. & Varela, F.J. (1980). Autopoiesis and Cognition. Reidel.
Nolen-Hoeksema, S. (1991). Responses to depression and their effects on
  the duration of depressive episodes. Journal of Abnormal Psychology.
Pavlik, P.I. & Anderson, J.R. (2005). Practice and forgetting effects on
  vocabulary memory. Journal of Experimental Psychology: Applied.
Rose, S. et al. (2010). Automatic keyword extraction from individual
  documents. Text Mining: Applications and Theory.
Rubin, D.C. & Wenzel, A.E. (1996). One hundred years of forgetting.
  Psychological Review.
Sparck Jones, K. (1972). A statistical interpretation of term specificity.
  Journal of Documentation.
Spinoza, B. (1677). Ethics.
Wixted, J.T. (2004). The psychology and neuroscience of forgetting.
  Annual Review of Psychology.

---

*This document is part of the permanent record of ONTO.*
*It can only grow. Changes are visible in the commit history.*
