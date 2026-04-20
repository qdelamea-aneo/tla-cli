---- MODULE SyntaxError ----
EXTENDS Naturals

VARIABLES x

Init == x = 0

\* Missing closing parenthesis - syntax error
Next == x' = (x + 1

Spec == Init /\ [][Next]_x

====
