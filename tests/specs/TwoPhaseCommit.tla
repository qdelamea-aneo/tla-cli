---- MODULE TwoPhaseCommit ----
\* A simple model of 2-phase commit with 2 resource managers
EXTENDS Naturals, FiniteSets

CONSTANTS RM  \* Set of resource managers

VARIABLES
  rmState,    \* rmState[r] = state of RM r: "working" | "prepared" | "committed" | "aborted"
  tmState,    \* tmState = state of TM: "init" | "committed" | "aborted"
  tmPrepared  \* set of RMs that have sent Prepared to TM

Init ==
  /\ rmState = [r \in RM |-> "working"]
  /\ tmState = "init"
  /\ tmPrepared = {}

RMPrepare(r) ==
  /\ rmState[r] = "working"
  /\ rmState' = [rmState EXCEPT ![r] = "prepared"]
  /\ tmPrepared' = tmPrepared \cup {r}
  /\ UNCHANGED tmState

RMChooseToAbort(r) ==
  /\ rmState[r] = "working"
  /\ rmState' = [rmState EXCEPT ![r] = "aborted"]
  /\ UNCHANGED <<tmState, tmPrepared>>

TMCommit ==
  /\ tmState = "init"
  /\ tmPrepared = RM
  /\ tmState' = "committed"
  /\ rmState' = [r \in RM |-> "committed"]
  /\ UNCHANGED tmPrepared

TMAbort ==
  /\ tmState = "init"
  /\ tmState' = "aborted"
  /\ rmState' = [r \in RM |-> "aborted"]
  /\ UNCHANGED tmPrepared

Next ==
  \/ TMCommit
  \/ TMAbort
  \/ \E r \in RM : RMPrepare(r) \/ RMChooseToAbort(r)

Spec == Init /\ [][Next]_<<rmState, tmState, tmPrepared>>

\* Safety: no RM commits while another aborts
Consistent ==
  \A r1, r2 \in RM : ~(rmState[r1] = "aborted" /\ rmState[r2] = "committed")

TypeOK ==
  /\ rmState \in [RM -> {"working", "prepared", "committed", "aborted"}]
  /\ tmState \in {"init", "committed", "aborted"}
  /\ tmPrepared \subseteq RM

====
