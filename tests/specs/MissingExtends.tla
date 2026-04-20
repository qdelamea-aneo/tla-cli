---- MODULE MissingExtends ----
EXTENDS NonExistentModule

VARIABLES x

Init == x = 0
Next == x' = x + 1

====
