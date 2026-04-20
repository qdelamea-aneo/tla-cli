---- MODULE LivenessViolation ----
EXTENDS Naturals

VARIABLES flag

Init == flag = FALSE

\* flag can stay FALSE forever — liveness violated
Next == flag' = flag

Spec == Init /\ [][Next]_flag

\* This temporal property is violated since flag never becomes TRUE
EventuallyTrue == <>(flag = TRUE)

====
