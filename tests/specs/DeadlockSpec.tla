---- MODULE DeadlockSpec ----
EXTENDS Naturals

VARIABLES state

Init == state = 0

\* Only transitions from 0 to 1, then deadlock
Step == state = 0 /\ state' = 1

Next == Step

Spec == Init /\ [][Next]_state

====
