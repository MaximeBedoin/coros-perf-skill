"""Recupere la meteo horaire pour chaque lieu present dans activities_base.csv.

Open-Meteo, sans cle d'API. L'archive ERA5 accuse environ 5 jours de retard, on
complete donc les jours recents avec l'API forecast (past_days, max 92).

Usage :
    python fetch_weather.py --data-dir ./data

Sortie : <data>/weather.csv, avec la colonne `elevation` qui donne l'altitude du
site (utilisee ensuite comme altitude de depart de chaque sortie).

Note de confidentialite : ce script envoie des coordonnees GPS et des dates a un
service tiers. Demander l'accord de l'utilisateur avant de le lancer.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HOURLY = "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation"
COLS = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "shortwave_radiation"]


def get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(full, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            print(f"  reprise {attempt + 1} ({e})")
            time.sleep(3 * (attempt + 1))


def to_frame(payload, place, lat, lon):
    df = pd.DataFrame(payload["hourly"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["place"], df["lat"], df["lon"] = place, lat, lon
    df["elevation"] = payload.get("elevation")
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    data = Path(args.data_dir)

    acts = pd.read_csv(data / "activities_base.csv", parse_dates=["date"])
    places = acts.groupby("place").agg(lat=("lat", "mean"), lon=("lon", "mean")).reset_index()
    # une journee de marge de chaque cote : les sorties tot le matin ou tard le
    # soir peuvent tomber hors de la fenetre en heure UTC
    start = (acts.date.min() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = (acts.date.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    frames = []
    for _, row in places.iterrows():
        base = dict(latitude=round(row.lat, 3), longitude=round(row.lon, 3),
                    hourly=HOURLY, timezone="UTC")
        arch = get("https://archive-api.open-meteo.com/v1/archive",
                   {**base, "start_date": start, "end_date": end})
        df = to_frame(arch, row.place, row.lat, row.lon)

        if df["temperature_2m"].isna().any():
            n = int(df["temperature_2m"].isna().sum())
            print(f"{row.place}: {n} h manquantes dans l'archive, complétées par forecast")
            fc = get("https://api.open-meteo.com/v1/forecast",
                     {**base, "past_days": 92, "forecast_days": 1})
            fdf = to_frame(fc, row.place, row.lat, row.lon).set_index("time")
            df = df.set_index("time")
            for col in COLS:
                df[col] = df[col].fillna(fdf[col].reindex(df.index))
            df = df.reset_index()

        miss = int(df["temperature_2m"].isna().sum())
        print(f"{row.place}: alt={df['elevation'].iloc[0]:.0f} m, {len(df)} h, "
              f"{miss} manquante(s)")
        frames.append(df)
        time.sleep(1)

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(data / "weather.csv", index=False)
    total_missing = int(out["temperature_2m"].isna().sum())
    print(f"\n-> {data / 'weather.csv'} : {len(out)} lignes, "
          f"{total_missing} valeur(s) manquante(s)")
    if total_missing:
        print("Des trous subsistent : les séances concernées seront corrigées "
              "avec une météo interpolée depuis les heures voisines.")


if __name__ == "__main__":
    main()
