---
name: coros-perf
description: Construit une courbe de performance en course à pied à partir des données COROS, corrigée des facteurs environnementaux (pente, chaleur, humidité, altitude) avec estimations issues de la littérature scientifique, et la publie comme page interactive. À utiliser dès que l'utilisateur veut analyser sa progression en course à pied, comparer des séances courues dans des conditions différentes, savoir s'il progresse vraiment ou si c'est la météo, neutraliser l'effet de la chaleur ou de l'altitude sur ses allures, ou tracer une courbe de forme sur plusieurs mois — y compris s'il dit simplement « ma progression », « ma forme », « mes perfs COROS » sans mentionner les corrections.
---

# Courbe de performance COROS corrigée des conditions

## Ce que cette skill produit

Une page interactive : une courbe d'allure brute, une courbe corrigée avec son
intervalle, des cases pour activer chaque facteur, et une bascule par type de
séance. Le tout appuyé sur un indice qui rend comparables des sorties courues à
des intensités, des températures et des altitudes différentes.

Le travail difficile n'est pas le code — il est fourni dans `scripts/`. Il est
dans les pièges méthodologiques, dont plusieurs produisent des résultats
plausibles mais faux. **Lis `references/pieges.md` avant de modifier le modèle**,
et `references/methode.md` pour justifier les choix à l'utilisateur.

## Prérequis à vérifier avant de commencer

**Le connecteur COROS.** L'étape d'extraction utilise les outils MCP
`querySportRecords` et `getActivityDetail`. Sans ce connecteur, rien ne
fonctionne : le dire tout de suite plutôt qu'après avoir demandé la FC max.

**Un Python avec numpy et pandas.** Ne pas supposer que `python` fonctionne —
sur Windows c'est souvent le stub Microsoft Store, qui échoue sans message
clair. Repérer un interpréteur utilisable avant de lancer quoi que ce soit :

```bash
python -c "import numpy, pandas; print('ok')" 2>/dev/null \
  || ls ~/miniconda3/envs/*/python.exe ~/anaconda3/envs/*/python.exe 2>/dev/null
```

S'il faut passer par conda, appeler l'interpréteur en chemin absolu
(`C:/Users/<user>/miniconda3/envs/<env>/python.exe`) plutôt que d'activer un
environnement : `conda` n'est pas toujours sur le PATH du shell. Dans la suite,
`python` désigne l'interpréteur ainsi retenu.

`node` n'est pas nécessaire : `validate_palette.py` est un portage Python.

## Le problème que l'indice résout

Les sorties d'entraînement ne sont pas des tests maximaux. L'allure brute mesure
surtout l'intensité choisie ce jour-là, pas la forme. L'indice part donc du
rapport vitesse / réserve cardiaque, puis retire deux biais et trois facteurs
environnementaux pour exprimer chaque séance comme **une allure équivalente à
une FC de référence, en effort continu, dans des conditions neutres**.

## Déroulé

### 1. Cadrer

Demander la période (défaut : 6 derniers mois) et confirmer **FC de repos et FC
max** — tout l'indice se décale si elles sont fausses. Si l'utilisateur ne les
connaît pas, `queryRestingHeartRate` donne la FC de repos ; la FC max se déduit
mal d'une formule d'âge, mieux vaut demander la valeur observée en côte ou en
compétition.

Prévenir que la météo exige d'envoyer coordonnées GPS et horodatages à
Open-Meteo, et obtenir l'accord avant l'étape 3.

### 2. Extraire les données COROS

`querySportRecords` avec les codes course `[100, 102, 103]` sur la période, une
limite large (200+). Écrire `data/activities_base.csv` :

```
labelId,sportType,date,place,lat,lon,start_ts,end_ts,dist_km,hr
412345678901234567,100,2026-08-25,ParcNord,48.500000,2.300,1787678682,1787681186,7.18,137
```

`place` est un identifiant court dérivé du lieu, sans espace ni accent : il sert
à grouper les requêtes météo. Des sorties au même endroit doivent porter le même
`place`, sinon la météo est récupérée plusieurs fois pour rien.

Exclure les séances de moins de 15 minutes : leur indice est très bruité.

Puis `getActivityDetail` pour chaque séance restante — par lots d'une quinzaine
d'appels en parallèle. Écrire `data/details.csv` :

```
labelId,workout_s,adj_pace_s,power_w,elev_gain,elev_loss,tload,aerobic_te,anaerobic_te,cadence
412345678901234567,2495,348,204,2,3,57,2.3,0.0,185
```

`workout_s` et `adj_pace_s` en secondes (convertir `41:35` → `2495`,
`5:48 /km` → `348`). Les séances sur piste (sportType 103) n'ont pas d'*Adjusted
Pace* : reprendre l'allure moyenne, le dénivelé y est nul.

Cette transcription est l'endroit le plus fragile du pipeline. La vérifier :

```bash
python scripts/check_data.py --data-dir ./data
```

### 3. Météo

```bash
python scripts/fetch_weather.py --data-dir ./data
```

Une requête par lieu, archive ERA5 complétée par l'API forecast pour les jours
récents. Le script rapporte les valeurs manquantes et l'altitude de chaque site.

### 4. Modèle

```bash
python scripts/model.py --data-dir ./data --hr-rest 48 --hr-max 188
```

Écrit `data/perf.json`. Lire la sortie console : elle donne les coefficients
estimés, leurs t, la corrélation intensité~anaérobie et la tendance mensuelle.
Ces chiffres servent à juger si le modèle tient — voir `references/pieges.md`
pour les valeurs qui doivent alerter.

### 5. Page

Le gabarit `assets/template.html` est prêt à l'emploi et déjà validé (thèmes
clair/sombre, palette testée pour le daltonisme, tooltips, bascule par type).

```bash
python scripts/build_page.py --data-dir ./data \
    --template ~/.claude/skills/coros-perf/assets/template.html --out courbe.html
```

Publier avec l'outil Artifact. Si tu modifies les couleurs des séries, revalide-les :

```bash
python scripts/validate_palette.py "#1D6FC0,#B26011" light "#FFFFFF"
```

(`node` est souvent absent ; ce script est un portage Python fidèle du
validateur de la skill `dataviz`, mêmes seuils et mêmes matrices.)

### 6. Restituer

Donner le lien, puis les chiffres qui comptent : allure de départ et d'arrivée,
poids de chaque correction, et ce que le modèle ne peut pas dire. Signaler
explicitement tout changement de référence d'intensité entre deux exécutions —
sinon l'utilisateur compare des allures qui ont l'air d'avoir empiré alors que
seule l'échelle a bougé.

## Les corrections

Multiplicatives et indépendantes, appliquées à la vitesse :
`v_corrigée = v_observée × f_pente × f_chaleur × f_altitude`

| Facteur | Source | Ordre de grandeur |
|---|---|---|
| Pente | *Adjusted Pace* COROS (Minetti et al. 2002) | jusqu'à +16 % en montagne |
| Chaleur + humidité | WBGT (Stull 2011 ; Hunter & Minyard 1999 ; ISO 7243), dégradation d'après Ely et al. 2007 | +2 % médian, +6 % en canicule |
| Altitude | Wehrlin & Hallén 2006, atténuée sous-max et par acclimatation | +1 % médian, +4 % à 1200 m |

L'intervalle **ne vient pas d'un ajustement sur les données** : chaleur, saison
et progression sont confondues, les coefficients ne sont pas identifiables. Il
vient d'un Monte-Carlo sur les plages de la littérature, combiné à un bootstrap
des séances. Le dire à l'utilisateur — c'est un intervalle sur l'incertitude du
modèle de correction, pas un intervalle statistique ordinaire.

## Types de séance

Découpage sur la nature de l'effort : continu (`anaerobic_te < 2`) contre
fractionné. C'est le seul critère stable — voir `references/pieges.md` pour les
découpages par intensité et par durée, essayés et rejetés, avec leurs symptômes.

## Adapter à d'autres cas

- **Autre période** : rien à changer, tout se déduit des dates présentes.
- **Autre sport** : le modèle suppose que la vitesse est la mesure de
  performance. En vélo, remplacer par la puissance et retirer la correction de
  pente, qui n'a pas le même sens.
- **Peu de séances** (moins de ~40) : élargir `SIGMA_DAYS`, et considérer que
  la vue par type n'aura pas assez de matière.
- **Jeu de données long** (plus d'un an) : réduire `SIGMA_DAYS` à 8-10 jours
  pour ne pas lisser les cycles d'entraînement.
