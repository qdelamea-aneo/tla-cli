---- MODULE SemanticError ----
EXTENDS Naturals

VARIABLES x

Init == x = 0

\* undeclaredVar is not declared
Next == x' = undeclaredVar + 1

Spec == Init /\ [][Next]_x

====
