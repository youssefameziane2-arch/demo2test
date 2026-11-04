# Résultats du banc d'évaluation

12 démonstrations enregistrées sur l'application réelle (`eval/traces/`), comparées au test qu'un ingénieur QA écrirait à la main.

| Stratégie | Précision | Rappel | F1 | Scénarios exacts | Steps métier retrouvés | Événements / step | Tests exécutables | Appels LLM (rejets) |
|---|---|---|---|---|---|---|---|---|
| `generic` | 2 % | 4 % | 3 % | 0 % | 0 % | 8.3 | 100 % | 0 (0) |
| `rules` | 88 % | 94 % | 91 % | 75 % | 94 % | 12.9 | 100 % | 0 (0) |
| `rules+retrieval` | 91 % | 96 % | 93 % | 83 % | 96 % | 13.1 | 100 % | 0 (0) |
| `rules+llm` | 100 % | 100 % | 100 % | 100 % | 100 % | 13.9 | 100 % | 4 (2) |
| `rules+retrieval+llm` | 100 % | 100 % | 100 % | 100 % | 100 % | 13.9 | 100 % | 3 (2) |

## Détail par scénario

| Scénario | Difficulté | `generic` | `rules` | `rules+retrieval` | `rules+llm` | `rules+retrieval+llm` |
|---|---|---|---|---|---|---|
| s01_happy_path | nominal, asynchronous generation | 0/5 | exact | exact | exact | exact |
| s02_protocol_first | protocol chosen before the name | 0/4 | exact | exact | exact | exact |
| s03_typo | typing mistake corrected | 0/4 | exact | exact | exact | exact |
| s04_noise_clicks | useless clicks in the middle of a form | 0/4 | 3/4 | exact | exact | exact |
| s05_enter_key | form submitted with Enter instead of the button | 0/4 | 3/4 | 3/4 | exact | exact |
| s06_ring_error | design rule error + checkpoint | 0/4 | exact | exact | exact | exact |
| s07_duplicate | rejected duplicate name + checkpoint | 0/3 | exact | exact | exact | exact |
| s08_qos | check box with no business step | 1/5 | exact | exact | exact | exact |
| s09_two_initiators | repeated step + async + checkpoint | 0/6 | exact | exact | exact | exact |
| s10_late_edit | isolated edit after the project setup | 1/5 | exact | exact | exact | exact |
| s11_enter_permuted | Enter key + protocol after the name | 0/4 | 3/4 | 3/4 | exact | exact |
| s12_hesitation | abandoned fields and reverted choice | 0/4 | exact | exact | exact | exact |

*exact* = steps identiques au test manuel, dans le même ordre ; *x/y* = steps attendus retrouvés ; *(KO)* = le test généré échoue à l'exécution.
