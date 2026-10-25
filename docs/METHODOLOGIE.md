# Méthodologie

## Échelle des verdicts

| Verdict | Définition | Exemple (taux de chômage officiel 8,3 %) |
|---|---|---|
| **vrai** | Conforme aux données, à l'arrondi près | « 8,3 % » |
| **plutôt vrai** | Petite approximation sans incidence sur le sens | « autour de 8 % », « 8,7 % » |
| **imprécis** | Ordre de grandeur juste mais flou, indicateur mal nommé, ou vrai à une autre date | « 9 % » ; confusion entre taux BIT et demandeurs d'emploi |
| **trompeur** | Sens juste mais ampleur ou contexte déformés | « −3 points depuis 2017 » quand la baisse réelle est de 1,1 point |
| **faux** | Contredit par les données (sens inverse, écart important) | « 5 % » ; « le chômage a augmenté depuis 2017 » |
| **invérifiable** | Pas de donnée fiable pour trancher | — |

## Tolérances (référentiel, `backend/app/referentiel.py`)

| Type | vrai | plutôt vrai | imprécis | au-delà |
|---|---|---|---|---|
| Taux (écart absolu, en points) | ≤ 0,15 | ≤ 0,5 | ≤ 1,0 | faux (niveau) / trompeur (évolution dans le bon sens) |
| Volumes (écart relatif) | ≤ 2 % | ≤ 5 % | ≤ 10 % | idem |
| Évolution dans le mauvais sens | — | — | — | **faux** |
| Record « depuis N ans » | N ≤ réel + 1 an | — | N ≤ réel × 1,5 | faux. Si c'était vrai dans les 2 dernières années : **imprécis** |

Les seuils sont des choix de l'équipe, assumés et affichés. Ils sont modifiables en tête de `referentiel.py`.

Une évolution en volume exprimée en unités (« 1 300 milliards de dette en plus depuis 2017 », « 2 millions d'emplois créés ») est comparée à l'écart absolu de la série, avec les tolérances des volumes.

Hors référentiel (recherche par le modèle), le même barème est demandé dans le prompt. Si le modèle trouve un **taux** officiel pour une affirmation de niveau, le verdict est recalculé en code et ne peut qu'être durci (`verify.rate_verdict`).

## Conventions de période

- « en 2017 » ou « depuis 2017 » → **moyenne annuelle 2017** (série annuelle, comme le déficit : la valeur de 2017) ;
- « au 2e trimestre 2024 » → le trimestre exact (série mensuelle : moyenne des trois mois) ;
- « en septembre 2026 » → le mois exact (série trimestrielle : le trimestre qui le contient) ;
- présent ou « aujourd'hui » → **dernier point publié** à la date de l'analyse (attention : pour un discours ancien, renseigner `date`).

## Pièges métier (à expliquer, pas à sanctionner)

- **Taux de chômage BIT (INSEE)** ≠ **demandeurs d'emploi (France Travail, cat. A, ABC)**. Un orateur qui les confond reçoit `imprecis`, avec l'explication de la différence.
- **Points ≠ pourcentages** : passer de 9,4 % à 8,3 % = −1,1 **point** = −11,7 **%**.
- **France hors Mayotte / France entière / métropole**, **CVS** : toujours précisé dans `sources[].note`.
- **Emploi salarié** (INSEE, estimations) ≠ « emplois créés » au sens des déclarations d'embauche.

## Neutralité et éthique

1. On évalue des **affirmations**, jamais des **personnes**. Les mots « fake », « menteur », « manipulation » sont interdits dans l'UI et les prompts.
2. **Transparence** : chaque verdict a une source cliquable, et la méthode (`referentiel` ou `web`) ainsi que la confiance sont affichées.
3. **Symétrie** : mêmes tolérances, mêmes séries et même prompt pour toutes les personnalités. Pas de liste de personnalités codée en dur.
4. **Score de fiabilité** : affiché seulement à partir de 5 affirmations vérifiées, avec la formule visible (vrai 100, plutôt vrai 75, imprécis 50, trompeur 25, faux 0 ; invérifiable exclu). C'est un indicateur de **précision factuelle sur les chiffres**, pas un jugement global.
5. **Droit de réponse / erreur** : la feuille de route prévoit un bouton « signaler une erreur » et une relecture humaine avant toute publication.
6. **Contexte électoral** : en période de campagne, l'exactitude prime sur la vitesse. En cas de doute, le verdict doit être `inverifiable`, pas `faux`.
