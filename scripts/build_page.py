"""Injecte perf.json dans le gabarit HTML et produit la page finale.

Usage :
    python build_page.py --data-dir ./data --template ../assets/template.html \
                         --out courbe.html

Le gabarit contient le marqueur __DATA__, remplace par le contenu de perf.json.
La page qui en sort est autonome (aucune ressource externe hors Google Fonts) et
peut etre publiee telle quelle comme Artifact.
"""
import argparse
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", default="courbe.html")
    args = ap.parse_args()

    tpl = Path(args.template).read_text(encoding="utf-8")
    if "__DATA__" not in tpl:
        raise SystemExit(f"{args.template} ne contient pas le marqueur __DATA__")
    payload = Path(args.data_dir, "perf.json").read_text(encoding="utf-8")

    out = Path(args.out)
    out.write_text(tpl.replace("__DATA__", payload), encoding="utf-8")
    size = out.stat().st_size / 1024
    print(f"-> {out} ({size:.0f} Ko)")
    if size > 16 * 1024:
        print("ATTENTION : au-delà de 16 Mo, la publication en Artifact échoue.")


if __name__ == "__main__":
    main()
