---- MODULE ProofSyntaxError ----
EXTENDS Naturals, TLAPS

\* Missing PROVE keyword - syntax error
THEOREM <1>1. 1 + 1 = 2
  <1>2. QED
    BY <1>1

====
