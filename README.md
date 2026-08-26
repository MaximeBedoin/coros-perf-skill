# coros-perf

Une skill [Claude Code](https://claude.com/claude-code) qui transforme des mois
de données COROS en une courbe de performance **corrigée des conditions** :
pente, chaleur, humidité, altitude.

Parce qu'un 10 km couru à 32 °C n'est pas comparable au même 10 km couru à 8 °C,
et qu'un footing en Haute-Loire à 850 m n'est pas un footing en bord de Seine.

![Aperçu de la page produite](docs/capture.png)

## Le problème

Vos sorties d'entraînement ne sont pas des tests maximaux. L'allure brute mesure
surtout l'intensité que vous avez choisie ce jour-là — pas votre forme. Et même à
intensité constante, la météo et le terrain déplacent l'allure de plusieurs
pourcents.

Résultat : une courbe d'allure brute mélange trois choses — votre progression,
l'intensité du jour, et les conditions. Impossible de savoir laquelle bouge.

## Ce que fait la skill

Elle ramène chaque sortie à **une allure équivalente à une fréquence cardiaque de
référence, en effort continu, dans des conditions neutres**, puis produit une
page interactive autonome :

- une courbe brute et une courbe corrigée, avec intervalle ;
- une case par facteur, pour voir ce que chacun coûte ;
- une bascule par type de séance (continu / fractionné) ;
- le détail de chaque sortie au survol — météo, altitude, WBGT.

Les corrections viennent de la littérature scientifique, pas d'un ajustement sur
vos données : sur six mois, la chaleur est confondue avec la saison, elle-même
confondue avec votre progression. Les coefficients ne sont donc pas
identifiables à partir de vos seules séances. L'intervalle affiché est un
Monte-Carlo sur les plages plausibles de ces coefficients, combiné à un bootstrap
des séances.

| Facteur | Source | Ordre de grandeur observé |
|---|---|---|
| Pente | *Adjusted Pace* COROS, d'après Minetti et al. (2002) | jusqu'à +16 % en montagne |
| Chaleur + humidité | WBGT — Stull (2011), Hunter & Minyard (1999), ISO 7243 ; dégradation d'après Ely et al. (2007) | +2 % médian, +6 % en canicule |
| Altitude | Wehrlin & Hallén (2006), atténuée sous-max et par acclimatation | +1 % médian, +4 % à 1200 m |

Détails complets dans [`references/methode.md`](references/methode.md).

## Prérequis

**Un connecteur MCP COROS** relié à votre compte. C'est la vraie barrière : sans
lui, l'extraction ne produit rien. La skill le vérifie en premier.

**Python avec numpy et pandas.** `node` n'est pas nécessaire.

**Votre FC de repos et votre FC max**, les vraies. Tout l'indice se décale si
elles sont fausses, et rien ne le signalera.

## Installation

Copiez la skill elle-même dans vos skills personnelles — seuls `SKILL.md`,
`scripts/`, `references/` et `assets/` en font partie ; le reste du dépôt est de
la documentation :

```bash
git clone https://github.com/MaximeBedoin/coros-perf-skill.git
mkdir -p ~/.claude/skills/coros-perf
cd coros-perf-skill && cp -r SKILL.md scripts references assets ~/.claude/skills/coros-perf/
```

Ou installez le paquet [`dist/coros-perf.skill`](dist/coros-perf.skill) depuis
Claude Code, qui contient exactement ces fichiers.

Pour une équipe, placez le dossier dans `.claude/skills/` d'un dépôt : la skill
devient disponible pour tous ceux qui y travaillent.

## Utilisation

Une fois installée, demandez simplement :

> analyse ma progression en course sur les 6 derniers mois

La description est écrite pour se déclencher aussi sur des formulations
indirectes — « ma forme », « est-ce que je progresse vraiment ou c'est la
météo ». Ou invoquez-la explicitement avec `/coros-perf`.

---

# Refaire la même chose vous-même

La partie intéressante n'est pas cette skill en particulier, c'est la méthode
pour en fabriquer une. Voici comment celle-ci est née, avec les vraies étapes.

## 1. Demander un tour de réflexion avant le code

Le prompt de départ, à peu près :

> j'aimerais une courbe de performance des 6 derniers mois, qui prend en compte
> la chaleur, l'hygrométrie, l'altitude, avec des estimations dérivées de la
> littérature scientifique. **Faisons un tour de réflexion et après tu pourras te
> lancer dans le codage.**

La dernière phrase change tout. Sans elle, Claude produit du code immédiatement
et vous découvrez les mauvais choix trop tard. Avec elle, il explore d'abord vos
données réelles et revient avec ce qui manque — ici : COROS ne stocke ni
température ni humidité, il faut une source météo externe, ce qui suppose
d'envoyer vos coordonnées GPS à un tiers.

C'est aussi le moment où les vraies questions apparaissent. Celle qui comptait :
*qu'est-ce qu'on mesure au juste ?* L'allure brute ne veut rien dire sur des
sorties à intensité libre.

## 2. Le laisser buter sur les données

Plusieurs erreurs n'ont été trouvées qu'en regardant les résultats intermédiaires :

- une interpolation météo qui renvoyait 17–23 °C de février à août — plausible à
  l'œil distrait, absurde en réalité ;
- une courbe qui finissait à 4:00/km pour un coureur dont le seuil est à 4:25 ;
- des séances d'endurance qui ressortaient plus rapides que des séances de tempo.

Aucune n'a produit d'erreur Python. Toutes ont produit des chiffres crédibles.
D'où la règle : **demander à voir les valeurs intermédiaires**, pas seulement le
graphique final. « Montre-moi la plage de températures que tu as récupérée » a
attrapé le premier bug en dix secondes.

## 3. Poser une question qui casse le modèle

La demande suivante était :

> j'aimerais que tu distingues par type de séance

Elle a révélé un défaut de fond : la correction d'intensité était biaisée par une
variable omise. Estimée sur toutes les séances, la pente valait −0,17 ; estimée
correctement, avec la charge anaérobie comme covariable, −0,95. Un cas d'école de
paradoxe de Simpson, invisible tant qu'on ne stratifie pas.

Corollaire utile : **une bonne question de suivi vaut mieux qu'une relecture du
code.** Demandez une découpe, une comparaison, un cas limite — les défauts
apparaissent là.

## 4. Accepter que les données disent non

Trois découpages par type ont été essayés. Deux ont été rejetés :

- **par intensité** — la FC moyenne baisse quand on progresse, donc les séances
  migrent d'un groupe à l'autre et un groupe change de définition en cours de
  période ;
- **par durée** — les sorties étaient trop homogènes (39 ± 10 min) pour qu'un
  groupe « sortie longue » tienne.

Il ne reste que deux types au lieu de trois. C'est le bon résultat : mieux vaut
une distinction qui tient qu'une troisième catégorie décorative.

## 5. Figer avec `/skill-creator`

Une fois l'analyse au point :

> ce serait cool qu'on crée un skill claude pour faire ça à la demande

Claude Code fournit une skill `skill-creator` qui structure le travail :
`SKILL.md` pour le déroulé, `scripts/` pour le code, `references/` pour ce qui ne
tient pas dans le contexte à chaque fois.

## Ce qui fait qu'une skill vaut mieux qu'un prompt

**Encodez les pièges, pas le code.** Le code se régénère. Ce qui ne se régénère
pas, c'est de savoir que `astype("int64")` sur du `datetime64[us]` rend des
microsecondes et que `np.interp` renvoie silencieusement la valeur de bord.
[`references/pieges.md`](references/pieges.md) recense huit erreurs de ce genre,
**indexées par leur symptôme** — parce qu'aucune ne lève d'exception : on les
reconnaît au résultat bizarre, pas au message d'erreur.

**Ajoutez des garde-fous exécutables.** Un `check_data.py` qui refuse une durée
saisie en minutes vaut mieux qu'un paragraphe disant de faire attention. Le
modèle prévient aussi quand un coefficient prend une valeur qui trahit le bug de
variable omise.

**Ne codez pas en dur ce qui peut se calculer.** La FC de référence était fixée à
145 bpm ; elle est maintenant calculée comme le centre de gravité des séances.
La skill fait le bon choix sur n'importe quel jeu de données.

**Écrivez ce que le modèle ne peut pas dire.** `methode.md` se termine par une
liste de questions hors de portée — profil de coureur, prédiction de chrono, part
de la fatigue. Ça évite de sur-interpréter la jolie courbe.

---

## Limites connues

- Intensité et charge anaérobie sont corrélées à ~0,84 : leurs deux coefficients
  sont significatifs mais mal séparés individuellement.
- Les séjours en altitude coïncident souvent avec l'été : les corrections
  d'altitude et de chaleur se cumulent là où elles sont le moins vérifiables.
- L'altitude retenue est celle du départ plus la moitié du dénivelé positif.
- La régression de Hunter & Minyard suppose des vents modérés ; le vent est
  récupéré mais peu exploité.
- La transcription des réponses MCP vers les CSV est manuelle — c'est le maillon
  fragile, d'où `check_data.py`.

## Vie privée

La skill envoie des **coordonnées GPS et des horodatages** à
[Open-Meteo](https://open-meteo.com/) pour reconstituer la météo. Les
coordonnées de départ d'une sortie révèlent souvent un domicile. La skill demande
l'accord avant de le faire.

Aucune donnée personnelle n'est incluse dans ce dépôt : les exemples de CSV sont
fictifs.

## Licence

MIT — voir [LICENSE](LICENSE).

Les modèles physiologiques proviennent des publications citées ; ce dépôt n'en
redistribue que les coefficients, avec les références permettant de les vérifier.
