# Sources de données

## Référentiel emploi (`data/referentiel/emploi.json`)

Récupéré le 2026-10-22 via l'**API SDMX de la BDM INSEE** (`https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/<idbank>`, gratuite, sans clé). Tous les identifiants ont été vérifiés un par un.

| Clé | idbank | Série | Périmètre | Historique |
|---|---|---|---|---|
| `taux_chomage_bit` | 001688527 | Taux de chômage BIT, ensemble | France hors Mayotte, CVS | 1975-Q1 → 2026-Q2 |
| `taux_chomage_bit_fe` | 011818543 | Taux de chômage BIT, ensemble | France entière, CVS | 2003-Q1 → |
| `taux_chomage_moins_25` | 001688537 | Taux de chômage BIT, moins de 25 ans | France hors Mayotte, CVS | 1975 → |
| `taux_chomage_50_plus` | 001688531 | Taux de chômage BIT, 50 ans ou plus | France hors Mayotte, CVS | 1975 → |
| `taux_chomage_longue_duree` | 011818581 | Taux de chômage de longue durée | France entière, CVS | 2003 → |
| `nb_chomeurs_bit` | 011818555 | Chômeurs BIT (milliers) | France entière, CVS | 1975 → |
| `halo_chomage` | 011818564 | Halo autour du chômage (milliers) | France entière, CVS | 2003 → |
| `taux_emploi_15_64` | 011818676 | Taux d'emploi 15-64 ans | France entière, CVS | 2003 → |
| `taux_emploi_15_24` | 011818685 | Taux d'emploi 15-24 ans | France entière, CVS | 2003 → |
| `taux_activite_15_64` | 011818737 | Taux d'activité 15-64 ans | France entière, CVS | 2003 → |
| `emploi_salarie_total` | 001796852 | Emploi salarié total (milliers) | France hors Mayotte, CVS | 2010-Q4 → |
| `emploi_salarie_prive` | 001796854 | Emploi salarié privé (milliers) | France hors Mayotte, CVS | 2010-Q4 → |
| `emploi_salarie_public` | 001796853 | Emploi salarié public (milliers) | France hors Mayotte, CVS | 2010-Q4 → |
| `demandeurs_emploi_cat_a` | 010597456 | Demandeurs d'emploi cat. A (milliers) | France hors Mayotte, CVS-CJO | 1996 → |
| `demandeurs_emploi_cat_abc` | 010597571 | Demandeurs d'emploi cat. A, B, C (milliers) | France hors Mayotte, CVS-CJO | 1996 → |

### Notes de l'exploration de l'API

- L'endpoint `SERIES_BDM` renvoie les observations **de la plus récente à la plus ancienne**. Le script les retrie.
- L'attribut `UNIT_MULT="3"` signifie que la valeur est en milliers ; `"0"` signifie des unités. Le script convertit tous les volumes en **milliers**.
- L'INSEE a lancé une nouvelle base « **France entière** » (ids `0118185xx–0118187xx`, depuis 2003). Beaucoup de séries « France hors Mayotte » de l'Enquête Emploi sont marquées « Série arrêtée » à partir de 2026-Q1. Celles retenues ici continuent jusqu'en 2026-Q2. Pour les records (« depuis 40 ans »), on garde les séries hors Mayotte, qui remontent à 1975.
- Il n'existe pas de série 15-24 ans pour le taux de chômage : l'INSEE publie « moins de 25 ans ».
- Les demandeurs d'emploi n'existent pas en « France entière » (seulement hors Mayotte et métropole). Il n'y a pas de série mensuelle CVS courante (les séries mensuelles s'arrêtent en 2018).
- Le dataflow `DEMANDES-EMPLOIS-NATIONALES` est trop gros pour une requête unique (erreur 510) : il faut le requêter par tranches.
- Une requête multi-séries (`id1+id2`) échoue entièrement si un seul id est invalide : il faut tester les ids un par un.

## Ajouter une série / un thème

1. Trouver l'idbank : chercher sur insee.fr (« série chronologique », la page `https://www.insee.fr/fr/statistiques/serie/<idbank>`), ou lister un dataflow : `https://bdm.insee.fr/series/sdmx/data/<DATAFLOW>?lastNObservations=1`. Les dataflows sont listés sur `https://bdm.insee.fr/series/sdmx/dataflow`.
2. Ajouter l'entrée dans `data/referentiel/series.json`, sous un thème existant ou nouveau (ex. `"economie": {...}`).
3. Lancer `python scripts/fetch_insee.py <theme>`. Le fichier `data/referentiel/<theme>.json` est généré et chargé automatiquement au démarrage.
4. La nouvelle clé apparaît dans le prompt d'extraction (`{{INDICATORS}}`) sans autre modification.

## Pistes pour les prochains thèmes

| Thème | Séries / sources |
|---|---|
| Économie | IPC / inflation (INSEE), PIB trimestriel, pouvoir d'achat du RDB (INSEE) |
| Finances publiques | Dette et déficit au sens de Maastricht (INSEE, comptes nationaux), prélèvements obligatoires |
| Immigration | Titres de séjour, demandes d'asile, éloignements (ministère de l'Intérieur, DGEF, data.gouv) |
| Sécurité | Crimes et délits enregistrés (SSMSI, data.gouv) |
| Santé | Dépenses de santé (DREES), déserts médicaux (DREES, data.gouv) |
| Énergie | Prix de l'électricité, mix énergétique (RTE eco2mix, SDES) |
| Comparaisons UE | Eurostat (API SDMX, même logique que l'INSEE) |

Moteur de recherche de jeux de données : `https://www.data.gouv.fr/api/1/datasets/?q=<mots>`.
