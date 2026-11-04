# Résultats du banc d'évaluation

3 démonstrations **enregistrées à la main** par une autre personne à partir de consignes écrites (`eval/user_traces/`), jamais vues pendant la mise au point de l'outil.

| Stratégie | Précision | Rappel | F1 | Scénarios exacts | Steps métier retrouvés | Événements / step | Tests exécutables | Appels LLM (rejets) |
|---|---|---|---|---|---|---|---|---|
| `generic` | 3 % | 6 % | 4 % | 0 % | 0 % | 5.4 | 100 % | 0 (0) |
| `rules` | 65 % | 83 % | 73 % | 33 % | 82 % | 7.7 | 100 % | 0 (0) |
| `rules+retrieval` | 76 % | 89 % | 82 % | 67 % | 88 % | 8.4 | 100 % | 0 (0) |

## Détail par scénario

| Scénario | Difficulté | `generic` | `rules` | `rules+retrieval` |
|---|---|---|---|---|
| u01_crossbar | recorded by hand from written instructions | 0/6 | 5/6 | exact |
| u02_ring_fix | recorded by hand from written instructions | 0/6 | exact | exact |
| u03_qos_enter | recorded by hand from written instructions | 1/6 | 4/6 | 4/6 |

*exact* = steps identiques au test manuel, dans le même ordre ; *x/y* = steps attendus retrouvés ; *(KO)* = le test généré échoue à l'exécution.
