# Méthode et références

À lire pour justifier les choix à l'utilisateur, ou avant de modifier un
coefficient.

## L'indice

Les sorties d'entraînement ne sont pas des tests maximaux : l'allure brute
mesure surtout l'intensité choisie ce jour-là. On part donc du rapport
vitesse / réserve cardiaque :

```
%FCR = (FC_moyenne − FC_repos) / (FC_max − FC_repos)
ratio = vitesse_ajustée / %FCR
```

La réserve cardiaque (méthode de Karvonen) suit mieux le %VO₂max que le
pourcentage de FC max, ce qui en fait la normalisation par défaut en
physiologie de l'exercice.

Ce ratio est ensuite débarrassé de deux biais estimés conjointement sur les
données de l'athlète (voir `pieges.md` §1) :

```
log(ratio) = a + b·(%FCR − %FCR_ref) + c·jour + d·charge_anaérobie
```

- **b** capture la dérive avec l'intensité. Elle est mécanique : la relation
  vitesse↔FC est affine et non proportionnelle, donc le rapport décroît
  nécessairement quand la FC monte. Ce n'est pas une propriété de l'athlète.
- **d** capture le gonflement anaérobie : sur le jeu de référence, +2,4 % de
  ratio par unité, soit environ +10 % sur un fractionné franc.
- **c** est la progression, sous-produit utile : elle donne une tendance en
  %/mois indépendante du lissage.

L'indice affiché est l'allure que ce ratio corrigé donnerait à `%FCR_ref`, en
effort continu. Il se lit en minutes par kilomètre, ce qui le rend directement
comparable au vécu de l'athlète.

## Corrections environnementales

Multiplicatives et indépendantes, appliquées à la vitesse. L'indépendance est
une approximation : chaleur et altitude interagissent réellement, mais aux
altitudes concernées (moins de 1500 m) l'effet croisé est petit devant
l'incertitude des coefficients eux-mêmes.

### Pente

L'*Adjusted Pace* de COROS, calculé sur le profil seconde par seconde, est plus
fiable qu'un recalcul depuis le dénivelé agrégé, qui ignore la répartition des
montées. Il repose sur le coût énergétique de la pente mesuré par **Minetti et
al. (2002)**, *J Appl Physiol* 93(3):1039-46.

Le prior `u_slope = (0.80, 1.20)` module la confiance accordée à ce calcul
propriétaire : la correction retenue vaut entre 80 % et 120 % de celle proposée
par COROS.

### Chaleur et humidité

Le WBGT (*wet bulb globe temperature*) résume la contrainte thermique en
combinant température, humidité, rayonnement et vent. Il est reconstruit depuis
la météo standard :

1. bulbe humide — **Stull (2011)**, *J Appl Meteorol Climatol* 50(11):2267-9 ;
2. température de globe — régression de **Hunter & Minyard (1999)** ;
3. combinaison **ISO 7243** en plein soleil :
   `WBGT = 0.7·Tw + 0.2·Tg + 0.1·Ta`.

Limite : la régression de Hunter & Minyard a été calibrée pour des vents
modérés. Le vent est récupéré mais peu exploité.

La dégradation est linéaire au-dessus d'un seuil, pondérée par la racine de la
durée — la contrainte thermique s'installe en 20-30 minutes puis plafonne :

```
f_chaleur = 1 + k · max(0, WBGT − WBGT₀) · √(durée / 60 min)
```

**Ely et al. (2007)**, *Med Sci Sports Exerc* 39(3):487-93, donne la borne basse
de `k` : la perte de performance sur marathon croît quasi linéairement avec le
WBGT, davantage chez les coureurs de milieu de peloton que chez les élites.

La borne haute vient de la dérive cardiaque à intensité fixe (~0,5-1 bpm/°C),
plus pertinente pour un indice défini à FC constante. Voir `pieges.md` §6.

L'humidité n'agit qu'en interaction avec la chaleur. Deux cases indépendantes
seraient physiologiquement fausses : l'interface propose donc « chaleur »
(WBGT à humidité de référence 50 %) puis « humidité » qui raffine vers le WBGT
réel.

### Altitude

**Wehrlin & Hallén (2006)**, *Eur J Appl Physiol* 96(4):404-12 : chez l'athlète
entraîné, le VO₂max décline de façon quasi linéaire **dès le niveau de la mer**,
d'environ 6 % par 1000 m — et non à partir d'un seuil de 1500 m comme on le lit
souvent.

Deux atténuations :

- **intensité sous-maximale** (`atten_int`) — à FC sous-max, la perte de vitesse
  est moindre que la perte de VO₂max ;
- **acclimatation** (`acclim_res`) — l'adaptation à des altitudes modestes est
  rapide ; le modèle l'étale sur 14 jours consécutifs, comptés depuis les
  séjours réels (`consecutive_altitude_days`, tolérance de 4 jours entre deux
  sorties en altitude).

L'altitude retenue est celle du site de départ plus la moitié du dénivelé
positif : une approximation du profil réel.

## L'intervalle

Il ne provient **pas** d'un ajustement sur les données. Chaleur, saison et
progression sont confondues : sur six mois, l'été apporte à la fois la chaleur,
les séjours en altitude et une part de la progression. Les coefficients ne sont
pas identifiables à partir des seules séances.

Ils viennent donc de la littérature, et l'intervalle combine par Monte-Carlo
(600 tirages) :

- les plages plausibles de ces coefficients ;
- un bootstrap des séances, stratifié par type, qui capture le bruit d'une
  séance à l'autre (typiquement 4 % d'écart-type résiduel).

C'est un intervalle sur **l'incertitude du modèle de correction**, pas un
intervalle de confiance statistique ordinaire. Le formuler ainsi.

## Lissage

Régression locale linéaire à noyau gaussien, séances pondérées par la racine de
leur durée. Sigma de 12 jours toutes séances confondues, 21 jours par type
— moins de séances, donc plus de bruit à compenser.

La courbe n'est tracée que là où les données la soutiennent (`pieges.md` §2).

## Ce que le modèle ne peut pas dire

- **Un profil « rapide » ou « endurant ».** Un profil vitesse-durée se lit sur
  des efforts maximaux de durées bien séparées (≈3, 12 et 30 min) et un modèle
  de vitesse critique. Des footings sur une plage d'intensité étroite ne
  permettent pas de trancher : tester la convexité de la relation
  intensité-rendement donne un coefficient non significatif dès qu'on retire la
  contamination anaérobie.
- **Une prédiction de chrono.** L'indice est un indicateur d'efficience à FC
  donnée, pas une extrapolation de performance maximale. Les prédictions de
  `queryFitnessAssessmentOverview` répondent à cette question-là.
- **Une part de fatigue ou de fraîcheur.** Une séance médiocre parce que mal
  dormi ressort comme une baisse de forme. `querySleepData` et
  `queryRecoveryStatus` permettraient d'en tenir compte — non implémenté.
