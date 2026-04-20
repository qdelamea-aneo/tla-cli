---- MODULE Counter ----
EXTENDS Naturals

VARIABLES counter

Init == counter = 0

Increment == counter' = counter + 1

Next == Increment

Spec == Init /\ [][Next]_counter

TypeInvariant == counter \in Nat

CounterBound == counter <= 5

====
