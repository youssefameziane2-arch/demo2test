# Banc de mutation

Les 12 scénarios générés sont exécutés contre l'application intacte puis contre 9 versions défectueuses. Un mutant est **tué** si au moins un test échoue.

| Vérifications | Nombre de checks | Fausses alertes | Mutants tués | Score de mutation |
|---|---|---|---|---|
| `none` | 0 | 0 | 1/9 | **11 %** |
| `key` | 44 | 0 | 8/9 | **89 %** |
| `llm-unverified` | 34 (1 rejetés) | 6 | 2/9 | **22 %** |
| `llm` | 23 (12 rejetés) | 0 | 7/9 | **78 %** |
| `key+llm` | 48 (12 rejetés) | 0 | 8/9 | **89 %** |

## Détail par mutant

| Mutant (régression injectée) | `none` | `key` | `llm-unverified` | `llm` | `key+llm` |
|---|---|---|---|---|---|
| la règle « un anneau demande 3 extrémités » n'est plus appliquée | **survit** | tué | tué | tué | tué |
| deux ports peuvent porter le même nom | **survit** | tué | tué | tué | tué |
| la netlist générée porte la mauvaise extension | **survit** | tué | **survit** | tué | tué |
| la génération ne se termine jamais | **survit** | tué | **survit** | tué | tué |
| le message de validation inverse initiateurs et cibles | **survit** | tué | **survit** | tué | tué |
| le bouton de génération reste grisé après validation | tué | tué | **survit** | tué | tué |
| la liste affiche AXI quel que soit le protocole choisi | **survit** | tué | **survit** | **survit** | tué |
| plus de message de confirmation après un ajout | **survit** | **survit** | **survit** | **survit** | **survit** |
| la génération devient 10 fois plus lente | **survit** | tué | **survit** | tué | tué |

*Fausses alertes* : scénarios qui échouent contre l'application intacte (une vérification incorrecte). Ces scénarios sont exclus du calcul des mutants tués : un test qui échoue toujours détecterait toutes les régressions sans rien prouver.
