# Pièges

Chacun de ces problèmes a été rencontré pour de vrai. Le point commun : aucun ne
provoque d'erreur. Ils produisent des chiffres d'allure parfaitement plausibles
et pourtant faux. D'où l'importance de connaître le **symptôme** de chacun.

## 1. La variable omise qui inverse l'ordre des types

**Symptôme** — les séances d'endurance ressortent plus rapides que les séances
de tempo une fois l'indice corrigé. Physiologiquement absurde.

**Cause** — le rapport vitesse/%FCR porte deux biais corrélés entre eux :

- une **dérive avec l'intensité**, mécanique et non physiologique : la relation
  vitesse↔FC est affine et non proportionnelle, donc le rapport décroît
  forcément quand la FC monte ;
- un **gonflement par la composante anaérobie** : à FC moyenne donnée, une
  séance fractionnée va plus vite qu'une séance continue.

Intensité et charge anaérobie sont corrélées autour de 0,84 : les fractionnés
ont une FC élevée *et* un ratio gonflé. Un modèle qui omet l'anaérobie attribue
donc à l'intensité une pente bien trop faible. Sur le jeu de référence :

| Modèle | pente d'intensité |
|---|---|
| toutes séances, sans anaérobie | −0,17 |
| séances continues seulement | −0,62 |
| fractionnés seulement | −1,10 |
| toutes séances, **avec anaérobie** | **−0,95** |

C'est un cas d'école de paradoxe de Simpson. La pente intra-groupe est masquée
par la structure entre groupes.

**Correctif** — `fit_index_coefs` estime les deux coefficients conjointement.
Ne jamais les estimer séparément ni en retirer un « pour simplifier ».

**Alerte automatique** — `model.py` prévient si la pente d'intensité est
inférieure à 0,4 en valeur absolue. C'est presque toujours le signe que
`anaerobic_te` est mal renseigné ou constant.

**Limite qui subsiste** — à 0,84 de corrélation, les deux coefficients restent
mal séparés individuellement. Le dire plutôt que de le cacher.

## 2. La régression locale qui extrapole dans le vide

**Symptôme** — une courbe part vers une allure impossible en bout de série
(observé : 4:00/km pour un coureur dont le seuil est à 4:25).

**Cause** — la régression locale de degré 1 corrige le biais de bord, mais elle
extrapole aussi. Quelques points tous situés du même côté du point d'évaluation
suffisent à faire diverger la pente locale. Le risque explose sur les
sous-groupes clairsemés : un type de séance représenté par 4 sorties sur le
dernier mois n'a rien à dire du dernier mois.

**Correctif** — `local_linear` n'évalue la courbe que si la taille d'échantillon
effective (Kish, `(Σw)²/Σw²`) atteint 4 **et** qu'une séance réelle se trouve à
moins d'un sigma. Ailleurs, `NaN` : la courbe s'interrompt. Le gabarit HTML sait
tracer les bandes en segments pour ne pas enjamber les trous.

Mieux vaut une courbe qui s'arrête qu'une courbe qui invente.

## 3. Les timestamps qui tombent hors domaine en silence

**Symptôme** — les températures s'écrasent dans une plage étroite et
invraisemblable (17-23 °C de février à août), avec beaucoup de valeurs
identiques.

**Cause** — `series.astype("int64")` sur du `datetime64[us]` rend des
**microsecondes**, pas des nanosecondes. Diviser par 1e9 donne des timestamps
mille fois trop petits. `np.interp` ne se plaint pas : il renvoie sagement la
valeur de bord pour tout point hors domaine, d'où la constante.

**Correctif** — passer par `.dt.total_seconds()`, sans ambiguïté d'unité.

**Réflexe général** — après toute interpolation, vérifier que la plage de sortie
est physiquement plausible. Une amplitude trop faible sur six mois de météo est
un signal.

## 4. Les découpages par type qui ne tiennent pas

**Par intensité (seuil de FC)** — la FC moyenne d'un coureur qui progresse
**baisse** au fil des mois. Les séances migrent donc de « tempo » vers
« endurance », et un groupe change de définition en cours de période. Symptôme :
la composition mensuelle par type dérive fortement, et les extrémités de chaque
courbe reposent sur presque rien.

**Par durée** — ne marche que si les sorties sont hétérogènes. Sur le jeu de
référence, les séances continues font 39 ± 10 min : le groupe « sortie longue »
tombait à 5-14 séances et disparaissait certains mois.

**Par seuil bas sur `anaerobic_te`** — attention aux valeurs pivots. La médiane
d'`anaerobic_te` valait exactement 0,5, avec douze séances pile sur cette
valeur : selon que la borne est ouverte ou fermée, l'effectif du groupe changeait
de 12 séances. Ne jamais poser un seuil sur une valeur fréquente ; vérifier
`value_counts()` avant de choisir.

**Ce qui tient** — continu contre fractionné à `anaerobic_te = 2`. Vraie
différence de nature (charge d'entraînement 60 contre 200), composition stable
d'un mois à l'autre, effectifs suffisants des deux côtés.

**Vérification à faire** avant de retenir un découpage :

```python
pd.crosstab(df.date.dt.to_period("M"), df.typ)
```

Si un groupe s'effondre certains mois, il ne donnera pas de courbe exploitable.

## 5. La référence d'intensité placée trop haut

**Symptôme** — l'indice paraît raisonnable mais bouge beaucoup dès qu'on touche
au modèle, et l'intervalle est large.

**Cause** — exprimer l'indice à une FC éloignée du centre de gravité des séances
force une extrapolation avec une pente incertaine. Sur le jeu de référence,
passer de 154 à 145 bpm a fait tomber l'extrapolation de 6,4 à 0,2 point de %FCR.

**Correctif** — `model.py` choisit par défaut la moyenne pondérée par la racine
de la durée. Ne forcer `--ref-bpm` que si l'utilisateur a une raison précise.

**Conséquence à annoncer** — changer la référence déplace toute la courbe.
Entre deux exécutions, une allure « plus lente » peut ne refléter qu'un
changement d'échelle. Le dire explicitement.

## 6. Le coefficient de chaleur calé sur le mauvais protocole

Ely et al. 2007 mesure la perte en **course maximale**. L'indice, lui, est défini
à **FC constante**, où la contrainte thermique passe surtout par la dérive
cardiaque et pèse davantage. Caler la borne haute du prior uniquement sur Ely
sous-corrige la chaleur d'environ un facteur deux.

D'où la plage `k_heat = (0.0015, 0.0065)` : borne basse Ely, borne haute dérive
cardiaque (~0,5-1 bpm/°C). Élargir un prior est plus honnête que de choisir en
silence une valeur centrale trop basse.

## 7. La palette jugée à l'œil

Deux choix qui semblaient bons ont échoué au validateur :

- une courbe de référence en gris neutre à côté d'un teal : ΔE de 7,7 contre 15
  requis, les deux séries se ressemblent trop ;
- un trio bleu / violet / ocre : bleu et violet indistinguables en deutanopie
  (ΔE 2 à 4).

Le teal choisi au départ était par ailleurs sous le plancher de chroma (0,077
contre 0,10) — cette teinte ne l'atteint pas dans la bande de luminosité utile.

Vert et ocre échouent aussi en protanopie (ΔE 3,7). La combinaison robuste est
**bleu et ocre**, sur l'axe bleu-jaune que toutes les formes de daltonisme
préservent.

`scripts/validate_palette.py` calcule tout ça. `node` étant souvent absent, ce
portage Python reprend les seuils et les matrices Machado-Oliveira-Fernandes du
validateur de la skill `dataviz`.

## 8. Deux conventions de signe pour la même quantité

**Symptôme** — l'interface affiche « +3,1 s/km » pour une correction et
« −7,2 s/km » pour leur cumul.

**Cause** — un axe d'allure est inversé (plus petit = meilleur), donc le signe
d'un écart est ambigu pour le lecteur comme pour celui qui code.

**Correctif** — ne pas afficher de signe, écrire le sens en toutes lettres :
« 3,1 s/km plus rapide ». Et rapporter tous les effets à la même référence : un
effet médian sur la période et un écart au dernier jour ne s'additionnent pas.
