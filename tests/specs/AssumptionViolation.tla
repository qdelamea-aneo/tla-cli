---- MODULE AssumptionViolation ----
EXTENDS Naturals

ASSUME 1 = 2

VARIABLES x

Init == x = 0
Next == x' = x + 1
Spec == Init /\ [][Next]_x

====
