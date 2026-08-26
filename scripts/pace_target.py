"""Allure à tenir le jour J, compte tenu des conditions attendues.

C'est le modele de `model.py` pris a l'envers : au lieu de ramener une sortie
observee vers des conditions neutres, on projette une allure de reference vers
les conditions d'un lieu et d'une date.

    allure_reelle = allure_neutre × f_pente × f_chaleur × f_altitude

Usage :
    python pace_target.py --pace 4:25 --distance 10 \\
        --place "Paris" --datetime "2027-07-15 10:00"

Meteo : prevision Open-Meteo si la date est a moins de 16 jours, sinon
climatologie — meme jour +/- 3 jours sur les 10 dernieres annees, dont on tire
une mediane et un intervalle. Dans ce second cas l'incertitude vient surtout de
la meteo, pas du modele : c'est dit dans la sortie.
"""
import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request

import numpy as np

from model import PRIORS, f_alt, f_heat, wbgt

CLIMATO_YEARS = 10
CLIMATO_WINDOW = 3      # jours de part et d'autre de la date visée
FORECAST_HORIZON = 16   # au-delà, Open-Meteo ne prévoit plus
HOURLY = "temperature_2m,relative_humidity_2m,shortwave_radiation"


def get(url, params):
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=60) as r:
        return json.loads(r.read().decode())


def geocode(name):
    res = get("https://geocoding-api.open-meteo.com/v1/search",
              {"name": name, "count": 1, "language": "fr"})
    if not res.get("results"):
        raise SystemExit(f"Lieu introuvable : {name!r}. Donner --lat et --lon.")
    r = res["results"][0]
    label = ", ".join(x for x in (r["name"], r.get("admin1"), r.get("country")) if x)
    return r["latitude"], r["longitude"], label


def collect(payload, by_hour, keep=None):
    """Range les valeurs horaires dans by_hour[heure], en gardant les jours voulus."""
    h = payload["hourly"]
    for i, stamp in enumerate(h["time"]):
        ti = dt.datetime.fromisoformat(stamp)
        if keep is not None and ti.date() not in keep:
            continue
        if h["temperature_2m"][i] is None:
            continue
        d = by_hour.setdefault(ti.hour, {"temp": [], "rh": [], "solar": []})
        d["temp"].append(h["temperature_2m"][i])
        d["rh"].append(h["relative_humidity_2m"][i])
        d["solar"].append(h["shortwave_radiation"][i])


def forecast(lat, lon, when):
    p = get("https://api.open-meteo.com/v1/forecast",
            {"latitude": lat, "longitude": lon, "hourly": HOURLY,
             "timezone": "auto", "forecast_days": FORECAST_HORIZON})
    by_hour = {}
    collect(p, by_hour, keep={when.date()})
    if not by_hour:
        raise SystemExit("Date hors de la fenêtre de prévision.")
    return dict(by_hour=by_hour, elev=p.get("elevation"), source="prévision")


def climatology(lat, lon, when):
    """Distribution des conditions du même jour sur les années précédentes."""
    by_hour, elev = {}, None
    for year in range(when.year - CLIMATO_YEARS, when.year):
        try:
            target = when.replace(year=year)
        except ValueError:            # 29 février
            target = when.replace(year=year, day=28)
        p = get("https://archive-api.open-meteo.com/v1/archive",
                {"latitude": lat, "longitude": lon, "hourly": HOURLY, "timezone": "auto",
                 "start_date": (target - dt.timedelta(days=CLIMATO_WINDOW)).strftime("%Y-%m-%d"),
                 "end_date": (target + dt.timedelta(days=CLIMATO_WINDOW)).strftime("%Y-%m-%d")})
        elev = p.get("elevation")
        collect(p, by_hour)
    if not by_hour:
        raise SystemExit("Aucune donnée climatologique récupérée.")
    return dict(by_hour=by_hour, elev=elev,
                source=f"climatologie sur {CLIMATO_YEARS} ans")


def minetti_cost(i):
    """Coût énergétique de la course en pente (Minetti et al. 2002), J/kg/m."""
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


def slope_factor(gain_m, distance_km):
    """Ralentissement d'une boucle montant puis redescendant de `gain_m`.

    On suppose autant de montée que de descente, réparties sur la distance : la
    pente moyenne vaut gain / (moitié du parcours), et le surcoût est la moyenne
    des coûts en montée et en descente rapportée au coût sur le plat.
    """
    if not gain_m:
        return 1.0
    i = gain_m / (distance_km * 1000 / 2)
    return (minetti_cost(i) + minetti_cost(-i)) / 2 / minetti_cost(0.0)


def parse_pace(s):
    m, sec = s.replace("'", ":").split(":")
    return int(m) * 60 + float(sec)


def fmt(sec_per_km):
    return f"{int(sec_per_km // 60)}:{int(round(sec_per_km)) % 60:02d}"


def target_pace(hour_data, alt, alt_days, f_slope, pace0, distance, n=2000, seed=0):
    """Allure à tenir, par Monte-Carlo sur les coefficients ET sur la météo.

    La correction thermique dépend de la durée, qui dépend elle-même de
    l'allure : on itère jusqu'au point fixe (deux ou trois passes suffisent).
    """
    wb = wbgt(np.array(hour_data["temp"], float),
              np.array(hour_data["rh"], float),
              np.array(hour_data["solar"], float))
    rng = np.random.default_rng(seed)
    draws = np.empty(n)
    for k in range(n):
        p = {key: rng.uniform(a, b) for key, (a, b) in PRIORS.items()}
        w = wb[rng.integers(0, len(wb))]        # une météo plausible parmi celles observées
        pace = pace0 * f_slope
        for _ in range(4):
            fh = f_heat(w, pace * distance / 60.0, p["k_heat"], p["wbgt0"])
            fa = f_alt(alt, alt_days, p["c_alt"], p["atten_int"], p["acclim_res"])
            pace = pace0 * f_slope * fh * fa
        draws[k] = pace
    return np.percentile(draws, [10, 50, 90]), wb


def main():
    # la console Windows sort en cp1252 par defaut, ce qui casse accents et symboles
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pace", required=True, help="allure de référence, min:sec par km")
    ap.add_argument("--distance", type=float, required=True, help="km")
    ap.add_argument("--datetime", required=True, help="'AAAA-MM-JJ HH:MM' (heure locale)")
    ap.add_argument("--place", help="nom du lieu, géocodé automatiquement")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--elevation-gain", type=float, default=0.0, help="D+ en mètres")
    ap.add_argument("--altitude-days", type=float, default=0.0,
                    help="jours déjà passés en altitude (acclimatation)")
    ap.add_argument("--scan", metavar="H-H", default=None,
                    help="compare les créneaux de départ, ex. 7-20")
    args = ap.parse_args()

    when = dt.datetime.fromisoformat(args.datetime)
    if args.place:
        lat, lon, label = geocode(args.place)
    elif args.lat is not None and args.lon is not None:
        lat, lon, label = args.lat, args.lon, f"{args.lat:.3f}, {args.lon:.3f}"
    else:
        raise SystemExit("Donner --place, ou --lat et --lon.")

    days_ahead = (when - dt.datetime.now()).days
    w = (forecast(lat, lon, when) if 0 <= days_ahead < FORECAST_HORIZON
         else climatology(lat, lon, when))
    if when.hour not in w["by_hour"]:
        raise SystemExit(f"Pas de données pour {when.hour} h.")

    alt = (w["elev"] or 0.0) + args.elevation_gain / 2
    f_slope = slope_factor(args.elevation_gain, args.distance)
    pace0 = parse_pace(args.pace)
    climato = w["source"].startswith("clim")

    (lo, med, hi), wb = target_pace(w["by_hour"][when.hour], alt, args.altitude_days,
                                    f_slope, pace0, args.distance)
    d = w["by_hour"][when.hour]
    temp = np.array(d["temp"], float)

    print()

    print(f"{label}  ·  {when:%d/%m/%Y à %Hh%M}  ·  {args.distance:g} km")
    print(f"altitude {alt:.0f} m"
          + (f", D+ {args.elevation_gain:g} m" if args.elevation_gain else ""))
    print()
    print(f"Conditions attendues ({w['source']}) :")
    if len(temp) > 1:
        q = np.percentile(temp, [10, 50, 90])
        print(f"  température   {q[1]:.0f} °C   (10-90 % : {q[0]:.0f} à {q[2]:.0f})")
    else:
        print(f"  température   {temp[0]:.1f} °C")
    print(f"  humidité      {np.median(d['rh']):.0f} %")
    print(f"  WBGT          {np.median(wb):.1f} °C")

    print()

    print(f"Allure de référence   {fmt(pace0)} /km")
    print(f"Allure à viser        {fmt(med)} /km   (80 % : {fmt(lo)} à {fmt(hi)})")
    delta = med - pace0
    print(f"Écart                 {abs(delta):.0f} s/km plus "
          f"{'lent' if delta > 0 else 'rapide'}"
          f"   ·   {abs(delta) * args.distance / 60:.1f} min sur {args.distance:g} km")

    print()

    print("Décomposition, à l'allure visée :")
    mid = {k: 0.5 * (a + b) for k, (a, b) in PRIORS.items()}
    fh = f_heat(np.median(wb), med * args.distance / 60.0, mid["k_heat"], mid["wbgt0"])
    fa = f_alt(alt, args.altitude_days, mid["c_alt"], mid["atten_int"], mid["acclim_res"])
    for lab, f in (("chaleur", fh), ("altitude", fa), ("pente", f_slope)):
        sec = pace0 * (f - 1)
        print(f"  {lab:9s} +{sec:4.1f} s/km")

    if args.scan:
        h0, h1 = (int(x) for x in args.scan.split("-"))
        print()
        print(f"Selon l'heure de départ :")
        rows = []
        for h in range(h0, h1 + 1):
            if h not in w["by_hour"]:
                continue
            (_, m, _), wbh = target_pace(w["by_hour"][h], alt, args.altitude_days,
                                         f_slope, pace0, args.distance, n=400, seed=h)
            rows.append((h, np.median(w["by_hour"][h]["temp"]), np.median(wbh), m))
        best = min(r[3] for r in rows)
        for h, t, wv, m in rows:
            bar = "=" * max(1, round((m - pace0) * 2))
            mark = "  <-- meilleur" if m <= best + 0.25 else ""
            print(f"  {h:2d} h   {t:4.0f} °C   WBGT {wv:4.1f}   {fmt(m)} /km  {bar}{mark}")
        gap = max(r[3] for r in rows) - best
        print()
        print(f"  Du meilleur au pire créneau : {gap:.0f} s/km, "
              f"soit {gap * args.distance / 60:.1f} min sur {args.distance:g} km.")

    if climato:
        print()
        print("À cette échéance l'incertitude vient surtout de la météo, pas du modèle.")
        print("Relancer dans les 15 jours précédant la course pour une vraie prévision.")


if __name__ == "__main__":
    main()
