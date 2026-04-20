---- MODULE SafetyViolation ----
EXTENDS Naturals

VARIABLES counter

Init == counter = 0

Increment == counter' = counter + 1

Next == Increment

Spec == Init /\ [][Next]_counter

\* This invariant will be violated: counter can exceed 3
BoundedCounter == counter <= 3

====
