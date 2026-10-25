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
- présent ou « aujourd'hui » → **dernier point disponible à la date du discours** (l'extension envoie la date de publication de la vidéo ou de l'article ; sans date, dernier point publié). On compare aux valeurs révisées d'aujourd'hui ; le délai de publication de quelques semaines n'est pas modélisé ;
- année pas encore publiée (« le déficit à 5 % en 2027 ») → pas de verdict calculé : c'est en général un objectif.

## Confusions d'indicateurs

Si le chiffre avancé est faux pour l'indicateur cité mais juste pour un indicateur voisin (taux d'activité / taux d'emploi, chômage BIT / demandeurs d'emploi, Smic brut / net, premières demandes d'asile / total…), le verdict est **imprécis**, pas faux, et l'explication cite les deux séries (`SIBLINGS` dans `referentiel.py`).

## Fact-checks déjà publiés et budget de recherche

Inspiré de Full Fact, Squash (Duke Reporters' Lab) et Chequeabot : pour chaque affirmation hors séries officielles, on cherche d'abord les fact-checks déjà publiés (Google Fact Check, format ClaimReview) et on garde ceux qui partagent au moins 30 % des mots de l'affirmation. Faute d'éditeur humain pour valider la correspondance, un fact-check publié ne décide jamais seul : il est donné au modèle, qui ne s'en sert que s'il porte sur la même affirmation, et devient alors une source citée.

Les recherches par le modèle sont limitées à 6 par analyse (`CHECK_MAX_WEB`), les affirmations chiffrées d'abord puis par thème (finances publiques, économie, emploi, immigration, sécurité…). Les affirmations couvertes par les séries officielles ne sont jamais limitées. Les autres reviennent « non vérifiée », avec la raison.

## Affirmations répétées

Comme les alertes de Full Fact : une affirmation hors séries officielles déjà vérifiée par recherche dans les 30 derniers jours est réutilisée telle quelle (« Affirmation déjà vérifiée le … »), si elle a le même thème, le même type, le même chiffre, la même période, une similarité d'au moins 60 % (indice de Jaccard, symétrique : un long texte fourre-tout ne capte pas un verdict) et si les deux discours sont datés à moins de 90 jours d'écart.

## Types d'affirmations

Classement repris de Full Fact : chiffre, règle (loi), vote, cause, prédiction, personnel. Les prédictions et les faits personnels ne sont pas vérifiés. Une affirmation de cause à effet n'est tranchée que si une évaluation officielle l'établit ; sinon elle est invérifiable.

## Articles de presse

Sur un article, on vérifie aussi les faits avancés par le texte lui-même et par chaque personne citée. L'explication commence par « Affirmé par l'article » ou « Affirmé par <nom> ». Seules les affirmations de la personnalité indiquée entrent dans son profil de fiabilité.

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
