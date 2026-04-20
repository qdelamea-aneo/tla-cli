---- MODULE FailingProof ----
EXTENDS Naturals, TLAPS

\* This proof obligation is intentionally wrong - 1+1 ≠ 3
THEOREM 1 + 1 = 3
  BY SMT

====
