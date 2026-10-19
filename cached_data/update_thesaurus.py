"""thesaurus_interactions.csv (extrait du PDF ANSM par extract_thesaurus.py) -> tables
thesaurus_interactions (brut) et thesaurus_atc (nom du thesaurus -> codes/préfixes ATC).

Substances : nom -> DCI de table_rcp -> codes de substance. Classes : classes_atc.csv (préfixes ATC).
Doit tourner après update_dci_atc.py.
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

from maj_tables import DB_APP as DB, DB_BUILD, log_update
from update_dci_atc import normalize, sans_sel
CSV = Path(__file__).with_name("thesaurus_interactions.csv")
CLASSES = Path(__file__).with_name("classes_atc.csv")

EXTRAPOLATION = re.compile(r"\s*\(?\s*et,? par extrapolation,?\s*")


def forme_acide(nom):
    """'valproique (acide)' -> 'acide valproique'"""
    m = re.match(r"^(.*?) \(acide\)$", nom)
    return f"acide {m.group(1)}" if m else nom


def candidats(nom):
    """(candidat, origine) : un nom du thesaurus peut citer plusieurs substances."""
    principal, *extras = EXTRAPOLATION.split(normalize(nom))
    parts = [(principal, "nom")] + [(e.strip(" )"), "extrapolation") for e in extras]
    for texte, origine in parts:
        if texte.startswith("autres "):
            continue
        for morceau in texte.split(" + "):
            morceau = forme_acide(morceau.strip())
            yield morceau, origine
            sans_parentheses = re.sub(r"\s*\(.*?\)", "", morceau).strip()
            if sans_parentheses != morceau:
                yield sans_parentheses, origine


def main():
    df = pd.read_csv(CSV, dtype=str).fillna("")

    conn = sqlite3.connect(DB)
    df.to_sql("thesaurus_interactions", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thesaurus_a ON thesaurus_interactions (a)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thesaurus_b ON thesaurus_interactions (b)")
    log_update(conn, "thesaurus_interactions", len(df))

    rcp = pd.read_sql("SELECT DISTINCT dci FROM table_rcp WHERE dci IS NOT NULL", conn)["dci"]
    exact, propre = {}, {}
    for dci in rcp:
        n = forme_acide(normalize(dci))
        exact.setdefault(n, set()).add(dci)
        propre.setdefault(sans_sel(n), set()).add(dci)

    noms = pd.concat([df["a"], df["b"]]).drop_duplicates()
    lignes, non_relies = [], []
    for nom in noms:
        trouve = False
        for cand, origine in candidats(nom):
            for methode, index, cle in (("exact", exact, cand), ("sans_sel", propre, sans_sel(cand))):
                for dci in index.get(cle, ()):
                    lignes.append({"nom_thesaurus": nom, "dci": dci,
                                   "methode": methode if origine == "nom" else f"{methode}_extrapolation"})
                    trouve = True
                if trouve:
                    break
        if not trouve:
            non_relies.append(nom)

    liens = pd.DataFrame(lignes, columns=["nom_thesaurus", "dci", "methode"]).drop_duplicates(
        ["nom_thesaurus", "dci"]
    )
    codes = pd.read_sql("SELECT nom AS dci, code_atc FROM substance WHERE code_atc IS NOT NULL", conn)
    par_substance = liens.merge(codes, on="dci")[["nom_thesaurus", "code_atc"]].drop_duplicates()
    par_substance = par_substance.rename(columns={"code_atc": "prefixe_atc"}).assign(origine="substance")

    classes = pd.read_csv(CLASSES, dtype=str).dropna(subset=["prefixes_atc"])
    classes["prefixe_atc"] = classes["prefixes_atc"].str.split("|")
    par_classe = classes.explode("prefixe_atc")[["nom_thesaurus", "prefixe_atc"]].assign(origine="classe")
    with sqlite3.connect(DB_BUILD) as build:
        connus = set(pd.read_sql("SELECT code FROM atc", build)["code"])
    inconnus = sorted(p for p in par_classe["prefixe_atc"].unique() if not any(c.startswith(p) for c in connus))
    if inconnus:
        print("préfixes sans code dans atc :", inconnus)

    thesaurus_atc = pd.concat([par_classe, par_substance]).drop_duplicates(["nom_thesaurus", "prefixe_atc"])
    thesaurus_atc.to_sql("thesaurus_atc", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thesaurus_atc_nom ON thesaurus_atc (nom_thesaurus)")
    conn.execute("DROP TABLE IF EXISTS thesaurus_substance")
    log_update(conn, "thesaurus_atc", len(thesaurus_atc))
    conn.commit()
    conn.close()

    couverts = set(thesaurus_atc["nom_thesaurus"])
    print(f"thesaurus_interactions : {len(df)} lignes")
    print(f"thesaurus_atc : {len(thesaurus_atc)} lignes, {len(couverts)}/{len(noms)} noms avec un ATC")
    print(f"lignes d'interaction dont A et B ont un ATC : {(df['a'].isin(couverts) & df['b'].isin(couverts)).mean():.0%}")


if __name__ == "__main__":
    main()
