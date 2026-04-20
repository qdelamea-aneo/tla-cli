---- MODULE SimpleProof ----
EXTENDS Naturals, TLAPS

THEOREM 1 + 1 = 2
  BY SMT

THEOREM \A n \in Nat : n + 0 = n
  BY SMT

====
