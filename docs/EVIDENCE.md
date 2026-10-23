# Evidence it works

Two runs of the same benchmark (`scripts/benchmark.py`, 10 claims, answers set by the latest INSEE / DARES figures). The baseline is always the same model with no data and no tools.

| Engine | Vérif'Pol | Naive baseline | Time per claim |
|---|---|---|---|
| Claude Sonnet 5.5 (22 Oct 2026) | **10/10** (9/10 before the bound fix) | 3/10 | 14 s |
| Gemini 3.5 Flash-Lite, free tier (23 Oct 2026) | **10/10** | 6/10 | 55 s (free-tier rate limits) |

Detail of the latest run:

Benchmark run on 2026-10-23 with `gemini-3.5-flash-lite`: 10 claims dated 2026-10-22 whose answer is set by the latest official INSEE / DARES figures. **Baseline** = the same model with no data and no tools. Script: `scripts/benchmark.py`.

| | Vérif'Pol | Naive baseline |
|---|---|---|
| Correct verdicts | **10/10** | 6/10 |
| Verdicts backed by an official source | **10/10** | 0/10 |
| Average time per claim | 55 s | 17 s |

| Claim | Truth (official figure) | Vérif'Pol | Baseline |
|---|---|---|---|
| Aujourd'hui, le taux de chômage est de 8,3 %. | **vrai** · 8,3 % (INSEE, T2 2026) | vrai ✅ | vrai ✅ |
| Le chômage est tombé à 6,5 %, son plus bas niveau. | **faux** · 8,3 % (INSEE, T2 2026) | faux ✅ | invérifiable ❌ |
| Depuis 2017, le chômage a baissé de plus de trois points. | **faux** · 9,4 % en 2017 → 8,3 % : −1,1 point | trompeur ✅ | vrai ❌ |
| Le chômage des moins de 25 ans dépasse 20 %. | **vrai** · 21,6 % (INSEE, T2 2026) | vrai ✅ | vrai ✅ |
| Le taux d'emploi des 15-64 ans atteint 69 %. | **vrai** · 69,0 % (INSEE, T2 2026) | vrai ✅ | invérifiable ❌ |
| Il y a moins de deux millions de demandeurs d'emploi en catégorie A. | **faux** · 3 323 000 (DARES, T2 2026) | faux ✅ | faux ✅ |
| L'inflation sur un an dépasse aujourd'hui 4 %. | **faux** · 3,1 % (INSEE, sept. 2026) | faux ✅ | faux ✅ |
| L'inflation est repassée au-dessus de 3 % sur un an. | **vrai** · 3,1 % (INSEE, sept. 2026) | vrai ✅ | invérifiable ❌ |
| La dette publique atteint 119 % du PIB. | **vrai** · 119,0 % (INSEE, T2 2026) | vrai ✅ | vrai ✅ |
| La dette publique est d'environ 2 000 milliards d'euros. | **faux** · 3 595,5 Md€ (INSEE, T2 2026) | faux ✅ | faux ✅ |
