---- MODULE SimpleSuccess ----
EXTENDS Naturals

VARIABLES x

Init == x = 0

Step == x' = 1 - x  \* toggles between 0 and 1

Next == Step

Spec == Init /\ [][Next]_x

BoolInvariant == x \in {0, 1}

====
