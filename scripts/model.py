"""Indice de performance course a pied, corrige des facteurs environnementaux.

Entrees  : <data>/activities_base.csv, <data>/details.csv, <data>/weather.csv
Sortie   : <data>/perf.json, consomme par assets/template.html

Usage :
    python model.py --data-dir ./data --hr-rest 48 --hr-max 188

Les choix de methode et les pieges sont expliques dans references/methode.md et
references/pieges.md. Deux points meritent d'etre rappeles ici parce qu'ils sont
faciles a casser en modifiant ce fichier :

  - la derive d'intensite et l'effet anaerobie DOIVENT etre estimes ensemble
    (variable omise, voir fit_index_coefs) ;
  - la regression locale ne doit pas extrapoler (voir local_linear).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260826)
N_MC = 600
SIGMA_DAYS = 12.0       # noyau de la regression locale, toutes seances confondues
SIGMA_TYPE = 21.0       # noyau elargi par type : moins de seances, donc plus de bruit

# Types de seance : la nature de l'effort. Voir references/pieges.md pour les
# decoupages essayes et rejetes (intensite, duree).
ANTE_SPLIT = 2.0
TYPES = [
    ("cont", "Continu", "charge anaérobie < 2"),
    ("frac", "Fractionné", "charge anaérobie ≥ 2"),
]
SERIES = ["all"] + [t[0] for t in TYPES]

# Plages des coefficients issues de la litterature. Elles servent au Monte-Carlo
# qui produit l'intervalle : ce ne sont pas des valeurs ajustees sur les donnees.
PRIORS = {
    # Perte de vitesse par degC de WBGT au-dessus du seuil. Borne basse : Ely et
    # al. 2007 (perte en course maximale). Borne haute : derive cardiaque a
    # intensite fixe (~0.5-1 bpm/degC), plus pertinente ici puisque l'indice est
    # defini a frequence cardiaque constante.
    "k_heat": (0.0015, 0.0065),
    "wbgt0": (8.0, 13.0),            # seuil de contrainte thermique (degC)
    "c_alt": (0.040, 0.080),         # perte de VO2max par 1000 m
    "atten_int": (0.40, 0.80),       # attenuation a intensite sous-maximale
    "acclim_res": (0.30, 0.70),      # part de l'effet subsistant apres acclimatation
    "u_slope": (0.80, 1.20),         # confiance dans l'Adjusted Pace de COROS
}

COMBOS = [(s, t, a) for s in (False, True)
          for t in ("none", "dry", "full")
          for a in (False, True)]


# --------------------------------------------------------------------------
# Meteo : WBGT
# --------------------------------------------------------------------------
def wet_bulb_stull(t, rh):
    """Temperature de bulbe humide (Stull 2011), t en degC, rh en %."""
    rh = np.clip(rh, 5, 99)
    return (t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
            + np.arctan(t + rh) - np.arctan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh)
            - 4.686035)


def wbgt(t, rh, solar):
    """WBGT exterieur estime depuis des donnees meteo standard.

    Globe par la regression de Hunter & Minyard (1999), puis
    WBGT = 0.7*Tw + 0.2*Tg + 0.1*Ta (ISO 7243, plein soleil).
    """
    tw = wet_bulb_stull(t, rh)
    tg = 0.01498 * solar + 1.184 * t - 0.0789 * rh - 2.739
    tg = np.maximum(tg, t)  # le globe ne peut pas etre plus froid que l'air
    return 0.7 * tw + 0.2 * tg + 0.1 * t


# --------------------------------------------------------------------------
# Chargement et fusion
# --------------------------------------------------------------------------
def load(data_dir, hr_rest, hr_max):
    data = Path(data_dir)
    df = pd.read_csv(data / "activities_base.csv").merge(
        pd.read_csv(data / "details.csv"), on="labelId")

    w = pd.read_csv(data / "weather.csv", parse_dates=["time"])
    # Ne PAS faire .astype("int64") // 1e9 : selon la resolution de pandas
    # (datetime64[us] ou [ns]) le facteur change et l'interpolation tombe
    # silencieusement hors domaine. total_seconds() est sans ambiguite.
    w["ts"] = (w["time"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()

    rows = []
    for place, g in w.groupby("place"):
        g = g.sort_values("ts")
        sub = df[df.place == place]
        mid = (sub.start_ts + sub.end_ts) / 2
        rows.append(pd.DataFrame({
            "labelId": sub.labelId.values,
            "temp": np.interp(mid, g.ts, g.temperature_2m),
            "rh": np.interp(mid, g.ts, g.relative_humidity_2m),
            "wind": np.interp(mid, g.ts, g.wind_speed_10m),
            "solar": np.interp(mid, g.ts, g.shortwave_radiation),
            "elev_site": g.elevation.iloc[0],
        }))
    df = df.merge(pd.concat(rows), on="labelId")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df["wbgt_real"] = wbgt(df.temp, df.rh, df.solar)
    df["wbgt_dry"] = wbgt(df.temp, 50.0, df.solar)   # humidite de reference
    df["alt_mean"] = df.elev_site + df.elev_gain / 2

    df["pace_raw_s"] = df.workout_s / df.dist_km
    df["f_slope"] = df.pace_raw_s / df.adj_pace_s    # >1 quand le terrain penalise
    df["hrr"] = (df.hr - hr_rest) / (hr_max - hr_rest)
    df["v_adj"] = 1000.0 / df.adj_pace_s
    df["v_raw"] = 1000.0 / df.pace_raw_s
    df["days"] = (df.date - df.date.min()).dt.days.astype(float)
    df["dur_min"] = df.workout_s / 60.0
    df["alt_days"] = consecutive_altitude_days(df)
    df["typ"] = np.where(df.anaerobic_te >= ANTE_SPLIT, "frac", "cont")

    bad = df[["adj_pace_s", "hr", "dist_km", "workout_s"]].isna().any(axis=1)
    if bad.any():
        raise SystemExit(f"{bad.sum()} séance(s) sans allure, FC ou distance : "
                         f"{df.loc[bad, 'labelId'].tolist()}")
    return df


def consecutive_altitude_days(df, thresh=500.0, gap=4):
    """Jours consecutifs deja passes en altitude au moment de la seance."""
    out, block_start, prev = [], None, None
    for _, r in df.iterrows():
        if r.alt_mean < thresh:
            block_start, prev = None, None
            out.append(0.0)
            continue
        if block_start is None or (r.date - prev).days > gap:
            block_start = r.date
        out.append((r.date - block_start).days)
        prev = r.date
    return np.array(out, dtype=float)


# --------------------------------------------------------------------------
# Facteurs de correction (>1 = conditions penalisantes)
# --------------------------------------------------------------------------
def f_heat(wbgt_val, dur_min, k, wbgt0):
    """Lineaire au-dessus d'un seuil, ponderee par la duree en racine carree :
    la contrainte thermique s'installe puis plafonne."""
    return 1.0 + k * np.maximum(0.0, wbgt_val - wbgt0) * np.sqrt(dur_min / 60.0)


def f_alt(alt_m, alt_days, c_alt, atten_int, acclim_residual):
    """Wehrlin & Hallen 2006, attenue par l'intensite sous-max et l'acclimatation."""
    acclim = 1.0 - (1.0 - acclim_residual) * np.minimum(1.0, alt_days / 14.0)
    return 1.0 + c_alt * (alt_m / 1000.0) * atten_int * acclim


# --------------------------------------------------------------------------
# Regression locale lineaire ponderee
# --------------------------------------------------------------------------
def local_linear(x, y, w, grid, sigma=SIGMA_DAYS, min_eff=4.0):
    """Regression locale lineaire, laissee vide la ou les donnees manquent.

    Le degre 1 corrige le biais de bord, mais il extrapole aussi : quelques
    points tous du meme cote suffisent a faire diverger la pente locale, ce qui
    produit des allures impossibles en bout de serie. On n'evalue donc la courbe
    que la ou la taille d'echantillon effective (Kish) atteint min_eff et ou une
    seance reelle se trouve a moins d'un sigma.
    """
    d = grid[:, None] - x[None, :]
    kern = np.exp(-0.5 * (d / sigma) ** 2) * w[None, :]
    s0, s1 = kern.sum(1), (kern * d).sum(1)
    s2 = (kern * d ** 2).sum(1)
    t0, t1 = (kern * y[None, :]).sum(1), (kern * d * y[None, :]).sum(1)
    denom = s0 * s2 - s1 ** 2
    out = np.where(np.abs(denom) > 1e-9, (s2 * t0 - s1 * t1) / denom, np.nan)

    n_eff = s0 ** 2 / np.maximum((kern ** 2).sum(1), 1e-12)
    return np.where((n_eff >= min_eff) & (np.abs(d).min(1) <= sigma), out, np.nan)


# --------------------------------------------------------------------------
# Indice de performance
# --------------------------------------------------------------------------
def fit_index_coefs(df, hrr_ref):
    """Estime CONJOINTEMENT la derive d'intensite et l'effet anaerobie.

    Les estimer separement est une erreur de variable omise : intensite et
    charge anaerobie sont fortement correlees (~0.84 sur un jeu typique), si
    bien qu'un modele sans anaerobie attribue a l'intensite une pente trop
    faible. Le symptome visible est que les seances d'endurance ressortent plus
    rapides que les seances de tempo, ce qui n'a pas de sens physiologique.
    """
    y = np.log((df.v_adj / df.hrr).values)
    A = np.column_stack([np.ones(len(df)), df.hrr.values - hrr_ref,
                         df.days.values, df.anaerobic_te.values])
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    n, k = A.shape
    r = y - A @ c
    se = np.sqrt(np.diag(((r @ r) / (n - k)) * np.linalg.inv(A.T @ A)))
    return ({"hrr": float(c[1]), "ante": float(c[3])},
            {"hrr_se": float(se[1]), "ante_se": float(se[3]),
             "trend_pct_month": float(100 * c[2] * 30),
             "resid_pct": float(100 * r.std()),
             "r2": float(1 - r @ r / ((y - y.mean()) @ (y - y.mean()))),
             "corr_hrr_ante": float(np.corrcoef(df.hrr, df.anaerobic_te)[0, 1])})


def perf_index(v_corr, hrr, coef, hrr_ref, ante=None):
    """Allure equivalente (s/km) a hrr_ref, en effort continu."""
    ratio = (v_corr / hrr) * np.exp(-coef["hrr"] * (hrr - hrr_ref))
    if ante is not None:
        ratio = ratio * np.exp(-coef["ante"] * ante)
    return 1000.0 / (ratio * hrr_ref)


def corrected_speed(df, slope_on, thermal, alt_on, p):
    """Vitesse debarrassee des facteurs actives, pour un jeu de coefficients p."""
    v = df.v_raw.values
    if slope_on:
        v = v * (1.0 + p["u_slope"] * (df.f_slope.values - 1.0))
    if thermal != "none":
        col = df.wbgt_real.values if thermal == "full" else df.wbgt_dry.values
        v = v * f_heat(col, df.dur_min.values, p["k_heat"], p["wbgt0"])
    if alt_on:
        v = v * f_alt(df.alt_mean.values, df.alt_days.values,
                      p["c_alt"], p["atten_int"], p["acclim_res"])
    return v


def fmt(s):
    return f"{int(s) // 60}:{int(round(s)) % 60:02d}/km"


def firstfin(a):
    return next(v for v in a if v is not None and np.isfinite(v))


def lastfin(a):
    return next(v for v in reversed(a) if v is not None and np.isfinite(v))


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--hr-rest", type=float, required=True)
    ap.add_argument("--hr-max", type=float, required=True)
    ap.add_argument("--ref-bpm", type=float, default=None,
                    help="FC de reference ; par defaut le centre de gravite des séances")
    args = ap.parse_args()

    df = load(args.data_dir, args.hr_rest, args.hr_max)
    w = np.sqrt(df.dur_min.values)

    # Reference d'intensite : centre de gravite pondere des seances. La placer
    # ailleurs oblige a extrapoler avec une pente incertaine, et deplace tout
    # l'indice sans rien apprendre de plus.
    if args.ref_bpm is None:
        hrr_ref = float(np.average(df.hrr.values, weights=w))
        ref_bpm = round(args.hr_rest + hrr_ref * (args.hr_max - args.hr_rest))
    else:
        ref_bpm = args.ref_bpm
    hrr_ref = (ref_bpm - args.hr_rest) / (args.hr_max - args.hr_rest)

    coef, stats = fit_index_coefs(df, hrr_ref)
    print(f"Séances : {len(df)}   référence : {ref_bpm:.0f} bpm")
    print(f"  dérive d'intensité   {coef['hrr']:+.3f} "
          f"(t={coef['hrr'] / stats['hrr_se']:+.1f})")
    print(f"  effet anaérobie      {coef['ante']:+.4f}/unité "
          f"(t={coef['ante'] / stats['ante_se']:+.1f})")
    print(f"  corrélation intensité~anaérobie {stats['corr_hrr_ante']:.2f}"
          f"   R²={stats['r2']:.3f}   résidus {stats['resid_pct']:.1f} %")
    print(f"  tendance {stats['trend_pct_month']:+.2f} %/mois")
    if abs(coef["hrr"]) < 0.4:
        print("  ATTENTION : dérive d'intensité faible. Vérifier que la charge "
              "anaérobie est bien renseignée — voir references/pieges.md.")

    x, grid = df.days.values, np.arange(0.0, df.days.max() + 1.0)
    mid = {k: 0.5 * (a + b) for k, (a, b) in PRIORS.items()}
    masks = {"all": np.ones(len(df), bool)}
    masks.update({c: (df.typ == c).values for c, *_ in TYPES})
    sigmas = {"all": SIGMA_DAYS, **{c: SIGMA_TYPE for c, *_ in TYPES}}
    pools = {s: np.flatnonzero(m) for s, m in masks.items()}

    curves, points = {}, {}
    for slope_on, thermal, alt_on in COMBOS:
        key = f"{int(slope_on)}{thermal}{int(alt_on)}"
        idx = perf_index(corrected_speed(df, slope_on, thermal, alt_on, mid),
                         df.hrr.values, coef, hrr_ref, df.anaerobic_te.values)
        points[key] = np.round(idx, 2).tolist()

        curves[key] = {}
        draws = {s: np.empty((N_MC, len(grid))) for s in SERIES}
        for i in range(N_MC):
            p = {k: RNG.uniform(a, b) for k, (a, b) in PRIORS.items()}
            ii = perf_index(corrected_speed(df, slope_on, thermal, alt_on, p),
                            df.hrr.values, coef, hrr_ref, df.anaerobic_te.values)
            for s in SERIES:
                pool = pools[s]
                bs = RNG.choice(pool, len(pool))   # bootstrap au sein de la serie
                draws[s][i] = local_linear(x[bs], ii[bs], w[bs], grid, sigmas[s])

        for s in SERIES:
            pool = pools[s]
            central = local_linear(x[pool], idx[pool], w[pool], grid, sigmas[s])
            lo, hi = np.nanpercentile(draws[s], [2.5, 97.5], axis=0)
            curves[key][s] = {"central": np.round(central, 2).tolist(),
                              "lo": np.round(lo, 2).tolist(),
                              "hi": np.round(hi, 2).tolist()}

    payload = {
        "meta": {
            "hr_rest": args.hr_rest, "hr_max": args.hr_max,
            "hrr_ref": hrr_ref, "hr_ref": ref_bpm, "n": int(len(df)),
            "start": df.date.min().strftime("%Y-%m-%d"),
            "end": df.date.max().strftime("%Y-%m-%d"),
            "sigma_days": SIGMA_DAYS, "sigma_type": SIGMA_TYPE, "n_mc": N_MC,
            "coef": {k: round(v, 4) for k, v in coef.items()},
            "fit": {k: round(v, 4) for k, v in stats.items()},
            "priors": PRIORS,
            "types": [{"id": c, "label": lab, "rule": rule,
                       "n": int((df.typ == c).sum())} for c, lab, rule in TYPES],
        },
        "grid": [int(g) for g in grid],
        "curves": curves, "points": points,
        "sessions": [{
            "d": int(r.days), "date": r.date.strftime("%Y-%m-%d"),
            "place": r.place, "km": round(r.dist_km, 2),
            "min": round(r.dur_min, 1), "hr": int(r.hr),
            "pace": int(r.pace_raw_s), "adj": int(r.adj_pace_s),
            "t": round(r.temp, 1), "rh": int(r.rh),
            "wbgt": round(r.wbgt_real, 1), "alt": int(r.alt_mean),
            "altd": int(r.alt_days), "typ": r.typ, "ante": r.anaerobic_te,
        } for r in df.itertuples()],
    }
    out = Path(args.data_dir) / "perf.json"
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"\n-> {out} ({out.stat().st_size / 1024:.0f} Ko)")

    raw = curves["0none0"]["all"]["central"]
    full = curves["1full1"]["all"]["central"]
    print(f"Allure à {ref_bpm:.0f} bpm, brute    : "
          f"{fmt(firstfin(raw))} -> {fmt(lastfin(raw))}")
    print(f"Allure à {ref_bpm:.0f} bpm, corrigée : "
          f"{fmt(firstfin(full))} -> {fmt(lastfin(full))}")
    for code, lab, _ in TYPES:
        c = curves["1full1"][code]["central"]
        print(f"  {lab:12s} n={int((df.typ == code).sum()):3d}  "
              f"{fmt(firstfin(c))} -> {fmt(lastfin(c))}")


if __name__ == "__main__":
    main()
