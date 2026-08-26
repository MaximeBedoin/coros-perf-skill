"""Verifie les CSV d'entree avant de lancer le pipeline.

La transcription des reponses MCP vers details.csv se fait a la main, seance par
seance : c'est l'endroit du pipeline ou une erreur est la plus probable et la
plus silencieuse. Ce script attrape les cas typiques (lignes manquantes,
doublons, allures aberrantes, durees en minutes au lieu de secondes).

Usage :
    python check_data.py --data-dir ./data
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

BASE_COLS = ["labelId", "sportType", "date", "place", "lat", "lon",
             "start_ts", "end_ts", "dist_km", "hr"]
DET_COLS = ["labelId", "workout_s", "adj_pace_s", "power_w", "elev_gain",
            "elev_loss", "tload", "aerobic_te", "anaerobic_te", "cadence"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    data = Path(args.data_dir)
    problems, warnings = [], []

    for name, cols in (("activities_base.csv", BASE_COLS), ("details.csv", DET_COLS)):
        if not (data / name).exists():
            problems.append(f"{name} absent")
    if problems:
        print("\n".join("ERREUR : " + p for p in problems))
        sys.exit(1)

    base = pd.read_csv(data / "activities_base.csv")
    det = pd.read_csv(data / "details.csv")

    for name, df, cols in (("activities_base.csv", base, BASE_COLS),
                           ("details.csv", det, DET_COLS)):
        missing = [c for c in cols if c not in df.columns]
        if missing:
            problems.append(f"{name} : colonnes manquantes {missing}")
        dup = df.labelId[df.labelId.duplicated()].tolist()
        if dup:
            problems.append(f"{name} : labelId en double {dup}")

    only_base = set(base.labelId) - set(det.labelId)
    only_det = set(det.labelId) - set(base.labelId)
    if only_base:
        problems.append(f"{len(only_base)} séance(s) sans détail : {sorted(only_base)[:5]}")
    if only_det:
        problems.append(f"{len(only_det)} détail(s) sans séance : {sorted(only_det)[:5]}")

    if not problems:
        df = base.merge(det, on="labelId")
        pace = df.workout_s / df.dist_km
        # une allure de course plausible tient entre 2:30 et 12:00 au km
        odd = df[(pace < 150) | (pace > 720)]
        for r in odd.itertuples():
            problems.append(f"{r.date} {r.labelId} : allure {pace[r.Index]:.0f} s/km "
                            f"({r.dist_km} km en {r.workout_s} s) — durée en minutes ?")
        far = df[(df.adj_pace_s - pace).abs() > 90]
        for r in far.itertuples():
            warnings.append(f"{r.date} : adj_pace {r.adj_pace_s} s/km loin de "
                            f"l'allure brute {pace[r.Index]:.0f} — vérifier la transcription")
        if (df.anaerobic_te > 5.5).any() or (df.anaerobic_te < 0).any():
            problems.append("anaerobic_te hors de [0, 5.5]")
        if df.hr.between(80, 210).all() is False:
            problems.append("FC moyenne hors de [80, 210] bpm")
        short = df[df.workout_s < 900]
        if len(short):
            warnings.append(f"{len(short)} séance(s) de moins de 15 min : "
                            f"les exclure, leur indice est très bruité")

    for w in warnings:
        print("attention :", w)
    if problems:
        print("\n".join("ERREUR : " + p for p in problems))
        sys.exit(1)
    print(f"OK — {len(base)} séances, colonnes et valeurs cohérentes.")


if __name__ == "__main__":
    main()
