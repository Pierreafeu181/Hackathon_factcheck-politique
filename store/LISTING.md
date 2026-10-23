# Chrome Web Store — dossier de publication Vérif'Pol

À recopier dans le tableau de bord développeur (https://chrome.google.com/webstore/devconsole).

## Fichiers

| Élément | Fichier |
|---|---|
| Paquet à envoyer | `store/verifpol-1.0.0.zip` |
| Icône 128 × 128 | `extension/static/icons/icon128.png` |
| Captures 1280 × 800 | `store/screenshot-1-verdicts.png`, `store/screenshot-2-profils.png`, `store/screenshot-3-veille.png` |
| Politique de confidentialité | https://01a16824-5586-7784-b544-269ed9694450-8080.eur-1.aiven.app/privacy |

## Fiche

- **Nom** : Vérif'Pol
- **Catégorie** : Actualités et météo (News & Weather)
- **Langue** : français

**Description courte (132 caractères max)**
> Vérifie les affirmations des responsables politiques français dans les vidéos et articles, sources officielles à l'appui.

**Description détaillée**
> Vérif'Pol vérifie ce que disent les responsables politiques français, pendant que vous regardez une vidéo ou lisez un article.
>
> • Ouvrez une interview sur YouTube, un article de presse, un TikTok ou un Reel : les affirmations chiffrées sont repérées et vérifiées automatiquement.
> • Chaque verdict (vrai, trompeur, faux, invérifiable) est accompagné d'une explication, d'une correction et de la source officielle : INSEE, DARES, Eurostat, Banque mondiale, Assemblée nationale, data.gouv.fr.
> • Les chiffres sont comparés par le programme aux séries officielles, pas « devinés » par une IA. Sans source fiable, le verdict est « invérifiable » : rien n'est inventé.
> • Un clic sur ▶ renvoie au moment exact de la vidéo où la phrase est prononcée.
> • Mode Direct : vérification en temps réel du son d'un onglet (direct TV, débat, vidéo réservée aux abonnés).
> • Chat : posez vos questions sur les chiffres et la méthode.
> • Profils : fiabilité de chaque personnalité, calculée à partir des affirmations vérifiées.
>
> Neutralité : Vérif'Pol juge des affirmations, jamais des personnes, et ne donne aucune consigne de vote.
> Gratuit, sans compte, sans publicité. Une limite d'utilisation quotidienne protège le service.

## Objectif unique (single purpose)

> Vérifier les affirmations factuelles des responsables politiques français présentes dans la page ou la vidéo consultée, à partir de sources publiques officielles.

## Justification des autorisations

| Autorisation | Justification à recopier |
|---|---|
| `sidePanel` | Afficher les verdicts et le chat dans le panneau latéral, à côté de la vidéo ou de l'article. |
| `scripting` | Lire, dans l'onglet consulté et seulement quand le panneau est ouvert, le texte de l'article ou les sous-titres de la vidéo à vérifier, et déplacer la vidéo au moment d'une affirmation. |
| `tabs` | Savoir quelle page est affichée (adresse, titre) pour la vérifier quand l'utilisateur change de vidéo ou d'onglet. |
| `storage` | Garder localement les réglages et l'historique des pages déjà vérifiées. |
| `contextMenus` | Proposer « Vérifier cette phrase » et « Vérifier en direct » au clic droit. |
| `tabCapture` | Mode Direct, lancé par l'utilisateur : transcrire le son de l'onglet pour vérifier un direct ou une vidéo sans sous-titres. |
| Accès à tous les sites (`<all_urls>`) | Les déclarations politiques sont publiées sur de très nombreux sites (presse, chaînes vidéo, réseaux sociaux) : l'extension doit pouvoir lire la page consultée, quel que soit le site, lorsque l'utilisateur ouvre le panneau. |
| Code distant | Non : tout le code est inclus dans le paquet. Le serveur ne renvoie que des données (verdicts, sources). |

## Pratiques de confidentialité (formulaire)

- **Données collectées** : « Contenu des sites Web » (texte et sous-titres de la page vérifiée, son de l'onglet en mode Direct). Aucune autre catégorie (pas d'identité, de localisation, de données de santé, financières, d'authentification, de communications personnelles ni d'historique de navigation complet).
- **Usage** : uniquement pour la fonctionnalité unique de l'extension.
- **Certifications à cocher** : les données ne sont pas vendues à des tiers ; elles ne sont pas utilisées ni transférées à des fins sans rapport avec la fonctionnalité unique ; elles ne sont pas utilisées pour déterminer la solvabilité ou accorder des prêts.

## Avant d'envoyer

1. Créer le compte développeur (frais d'inscription unique, vérification d'identité).
2. Vérifier que la politique de confidentialité s'ouvre à l'adresse ci-dessus.
3. Envoyer `store/verifpol-1.0.0.zip`, remplir la fiche avec ce document, joindre les 3 captures et l'icône.
4. Prévoir plusieurs jours d'examen : l'accès à tous les sites et la capture d'onglet déclenchent un examen approfondi.
