---- MODULE UndefinedConstant ----
EXTENDS Naturals

CONSTANTS MaxVal

VARIABLES x

Init == x = 0
Next == x' = (x + 1) % MaxVal
Spec == Init /\ [][Next]_x

Bounded == x < MaxVal

====
