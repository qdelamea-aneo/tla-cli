---- MODULE InductiveProof ----
EXTENDS Naturals, TLAPS

VARIABLES counter

TypeInvariant == counter \in Nat

Init == counter = 0
Next == counter' = counter + 1

THEOREM Init => TypeInvariant
  BY DEF Init, TypeInvariant

THEOREM TypeInvariant /\ Next => TypeInvariant'
  BY DEF TypeInvariant, Next

====
