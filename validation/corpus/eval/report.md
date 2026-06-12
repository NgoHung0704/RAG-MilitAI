# MilitAI validation — evaluation report

Questions evaluated: **50**  ·  reference oracle = catalogue §10.

## Engine accuracy (mean headline score, scored vs oracle gold)

| engine | COMPLETE | MASKED |
|---|---|---|
| nl2cypher | 0.6373 | 0.6623 |
| reference | 1.0 | 1.0 |
| template | 1.0 | 0.9796 |

> `reference` is the oracle (1.0 on COMPLETE by construction); live engines reveal real system error.

## Live-engine coverage (COMPLETE)

| engine | ok | unparseable | query_error | applicable |
|---|---|---|---|---|
| nl2cypher | 44 | 2 | 3 | 49 |
| template | 7 | 0 | 0 | 10 |

## Information degradation (MASKED gold vs COMPLETE truth), by use case

| use case | n | mean recall vs COMPLETE |
|---|---|---|
| anthropometric | 4 | 0.1 |
| bounded | 8 | 0.6397 |
| genealogy | 11 | 0.9254 |
| lookup | 14 | 0.9857 |
| mechanics | 5 | 0.8 |
| migration | 8 | 0.7865 |

## Per-question

| id | ref_query | kind | degradation | nl2cypher | template |
|---|---|---|---|---|---|
| Q-NAME-01a | RQ-NAME-01 | rid_set | 1.0 | 1.0 | 1.0 |
| Q-NAME-01b | RQ-NAME-01 | rid_set | 1.0 | 1.0 | · |
| Q-NAME-02a | RQ-NAME-02 | rid_set | 1.0 | 1.0 | 1.0 |
| Q-NAME-02b | RQ-NAME-02 | rid_set | 1.0 | 1.0 | · |
| Q-NAME-03 | RQ-NAME-03 | rid_set | 1.0 | 1.0 | · |
| Q-COMP-01a | RQ-COMP-01 | rid_set | 1.0 | 1.0 | · |
| Q-COMP-01b | RQ-COMP-01 | rid_set | 1.0 | 1.0 | · |
| Q-COMP-02 | RQ-COMP-02 | rid_set | 1.0 | 1.0 | · |
| Q-ENR-01a | RQ-ENR-01 | rid_set | 0.9 | 0.9268 | 1.0 |
| Q-ENR-01b | RQ-ENR-01 | rid_set | 0.9 | 0.9268 | · |
| Q-BPL-01a | RQ-BPL-01 | rid_set | 1.0 | 0.9333 | 1.0 |
| Q-BPL-01b | RQ-BPL-01 | rid_set | 1.0 | 0.9333 | · |
| Q-REC-01 | RQ-REC-01 | rag_target | 1.0 | · | · |
| Q-ENR-02 | RQ-ENR-02 | rid_set | 0.9178 | 0.9178 | · |
| Q-DTH-01a | RQ-DTH-01 | rid_set | 0.4444 | 0.9231 | 1.0 |
| Q-DTH-01b | RQ-DTH-01 | rid_set | 0.4444 | 0.9231 | · |
| Q-RNK-01a | RQ-RNK-01 | rid_set | 0.5556 | 0.0 | 1.0 |
| Q-RNK-01b | RQ-RNK-01 | rid_set | 0.5556 | 1.0 | · |
| Q-PAR-01a | RQ-PAR-01 | record_fields | 1.0 | · | · |
| Q-PAR-01b | RQ-PAR-01 | record_fields | 1.0 | · | · |
| Q-SIB-01a | RQ-SIB-01 | rid_set | 0.6667 | 0.0 | · |
| Q-SIB-01b | RQ-SIB-01 | rid_set | 0.6667 | 0.0 | · |
| Q-SIB-02 | RQ-SIB-02 | partition | 0.8462 | 0.5714 | · |
| Q-SIB-03 | RQ-SIB-03 | false_merge | 1.0 | 1.0 | · |
| Q-SIB-04 | RQ-SIB-04 | rid_set | 1.0 | 0.0 | · |
| Q-VERT-01a | RQ-VERT-01 | linkage | 1.0 | 0.0 | · |
| Q-VERT-01b | RQ-VERT-01 | linkage | 1.0 | 0.0 | · |
| Q-VERT-02 | RQ-VERT-02 | linkage | 1.0 | 1.0 | · |
| Q-VERT-03 | RQ-VERT-03 | linkage | 1.0 | 1.0 | · |
| Q-VERT-04 | RQ-VERT-04 | linkage | 1.0 | 1.0 | · |
| Q-VERT-05 | RQ-VERT-05 | linkage | 1.0 | 1.0 | · |
| Q-MIG-01a | RQ-MIG-01 | histogram | 0.8889 | 1.0 | · |
| Q-MIG-01b | RQ-MIG-01 | histogram | 0.8889 | 1.0 | · |
| Q-MIG-TOPO | RQ-MIG-01 | count | 0.0 | 0.0 | · |
| Q-MIG-02 | RQ-MIG-02 | histogram | 0.7778 | 0.9268 | · |
| Q-MIG-03 | RQ-MIG-03 | histogram_pair | 0.906 | 0.0 | · |
| Q-MIG-04 | RQ-MIG-04 | record_fields | 1.0 | 1.0 | · |
| Q-ANTH-01a | RQ-ANTH-01 | aggregate | 0.0 | · | · |
| Q-ANTH-01b | RQ-ANTH-01 | aggregate | 0.0 | · | · |
| Q-ANTH-02 | RQ-ANTH-02 | rid_set | 0.4 | 0.0 | · |
| Q-ANTH-03 | RQ-ANTH-03 | aggregate_pair | 0.0 | · | · |
| Q-UNANS-REG | RQ-UNANS-REG | record_fields | 0.0 | 1.0 | · |
| Q-ZERO | RQ-ZERO | rid_set | 1.0 | 1.0 | · |
| Q-DIS | RQ-DIS | disambiguation | 1.0 | 1.0 | · |
| Q-AGG-COUNT | RQ-AGG-COUNT | count | 1.0 | 1.0 | · |
| Q-MULTI | RQ-MULTI | rid_set | 1.0 | 0.0 | · |
| Q-BPL-02 | RQ-BPL-01 | rid_set | 0.9412 | 0.2581 | · |
| Q-DES-01 | RQ-DES-01 | rid_set | 0.2 | 0.9859 | 1.0 |
| Q-MIG-01c | RQ-MIG-01 | histogram | 0.8889 | 0.0 | · |
| Q-COMP-01c | RQ-COMP-01 | rid_set | 1.0 | 1.0 | · |