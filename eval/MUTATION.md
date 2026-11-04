# Banc de mutation

Les 12 scénarios générés sont exécutés contre l'application intacte puis contre 9 versions défectueuses. Un mutant est **tué** si au moins un test échoue.

| Vérifications | Nombre de checks | Fausses alertes | Mutants tués | Score de mutation |
|---|---|---|---|---|
| `none` | 0 | 0 | 1/9 | **11 %** |
| `key` | 42 | 0 | 8/9 | **89 %** |

## Détail par mutant

| Mutant (régression injectée) | `none` | `key` |
|---|---|---|
| la règle « un anneau demande 3 extrémités » n'est plus appliquée | **survit** | tué |
| deux ports peuvent porter le même nom | **survit** | tué |
| la netlist générée porte la mauvaise extension | **survit** | tué |
| la génération ne se termine jamais | **survit** | tué |
| le message de validation inverse initiateurs et cibles | **survit** | tué |
| le bouton de génération reste grisé après validation | tué | tué |
| la liste affiche AXI quel que soit le protocole choisi | **survit** | tué |
| plus de message de confirmation après un ajout | **survit** | **survit** |
| la génération devient 10 fois plus lente | **survit** | tué |

*Fausses alertes* : scénarios qui échouent contre l'application intacte (une vérification incorrecte). Ces scénarios sont exclus du calcul des mutants tués : un test qui échoue toujours détecterait toutes les régressions sans rien prouver.
