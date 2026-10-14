"""table_rcp.dci -> codes ATC (niveau 5) -> table dci_atc.

Cascade : alias manuel, exact, inn_dci (FR -> EN), sans sel/hydrate, sans 'e' final (FR -> EN).
Doit tourner après update_bdpm.py, update_dci_inn.py et update_atc.py.
"""
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

from maj_tables import log_update

DB = Path(__file__).with_name("cached_data.db")
ALIAS = Path(__file__).with_name("alias_manuels.csv")
RAPPORT = Path(__file__).with_name("rapport_dci_atc.csv")
SANS_ATC = "sans_atc"

FORMES = {
    "anhydre", "anhydrique", "monohydrate", "dihydrate", "trihydrate", "tetrahydrate",
    "pentahydrate", "hexahydrate", "heptahydrate", "hemihydrate", "sesquihydrate",
    "sodique", "potassique", "calcique", "magnesique", "disodique", "dipotassique",
    "hydrate", "base", "element",
}
# sels en préfixe : "chlorhydrate de X", "fumarate d'X"
PREFIXE_SEL = re.compile(
    r"^(?:mono|di|tri|hemi)?(?:chlorhydrate|bromhydrate|sulfate|nitrate|phosphate|acetate|"
    r"citrate|tartrate|maleate|fumarate|succinate|mesilate|besilate|tosilate|lactate|oxalate|"
    r"valerate|propionate|dipropionate|benzoate|bitartrate|hydrogenotartrate|"
    r"hydrochlorure|chlorure|bromure|iodure|oxyde|hydroxyde|carbonate|bicarbonate|"
    r"stearate|palmitate|napsilate|pamoate|furoate|embonate) (?:de |d')"
)
# esters et sels en suffixe : "candesartan cilexetil"
SUFFIXE_SEL = re.compile(
    r" (?:cilexetil|medoxomil|axetil|proxetil|pivoxil|hexetil|fumarate|maleate|tartrate|"
    r"succinate|mesilate|besilate)$"
)


def normalize(text):
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def sans_sel(nom):
    nom = " ".join(m for m in nom.split() if m not in FORMES)
    nom = PREFIXE_SEL.sub("", nom)
    return SUFFIXE_SEL.sub("", nom).strip()


def acide_en(nom):
    """'acide ascorbique' -> 'ascorbic acid' (ordre et suffixe anglais)"""
    m = re.match(r"^acide (\w+?)ique$", nom)
    return f"{m.group(1)}ic acid" if m else None


def main():
    conn = sqlite3.connect(DB)
    rcp = pd.read_sql(
        "SELECT dci, COUNT(DISTINCT code_cis) AS n_cis FROM table_rcp "
        "WHERE dci IS NOT NULL GROUP BY dci",
        conn,
    )
    atc = pd.read_sql("SELECT code, inn FROM atc WHERE level = 5 AND inn IS NOT NULL", conn)
    inn_dci = pd.read_sql("SELECT INN, DCI FROM inn_dci", conn).dropna()

    par_inn = atc.assign(inn=atc["inn"].map(normalize)).groupby("inn")["code"].apply(list).to_dict()
    fr_en = {normalize(d): normalize(i) for i, d in zip(inn_dci["INN"], inn_dci["DCI"])}
    alias = {}
    if ALIAS.exists():
        a = pd.read_csv(ALIAS, dtype=str).dropna(subset=["dci_bdpm", "inn_en"])
        alias = {normalize(d): normalize(i) for d, i in zip(a["dci_bdpm"], a["inn_en"])}

    def chercher(dci):
        n = normalize(dci)
        if "homeopathiques" in n or n.startswith("virus "):
            return "regle_sans_atc", None, True
        propre = sans_sel(n)
        essais = [
            ("alias", alias.get(n)),
            ("exact", n),
            ("inn_dci", fr_en.get(n)),
            ("sans_sel", propre),
            ("sans_sel_inn_dci", fr_en.get(propre)),
            ("sans_e_final", n[:-1] if n.endswith("e") else None),
            ("sans_sel_sans_e", propre[:-1] if propre.endswith("e") else None),
            ("acide", acide_en(n) or acide_en(propre)),
        ]
        for methode, cible in essais:
            if cible == SANS_ATC:
                return methode, None, True
            if cible in par_inn:
                return methode, par_inn[cible], False
        return None, None, False

    lignes, sans = [], set()
    for dci in rcp["dci"]:
        methode, codes, sans_atc = chercher(dci)
        if sans_atc:
            sans.add(dci)
        for code in codes or []:
            lignes.append({"dci": dci, "code_atc": code, "methode": methode})

    df = pd.DataFrame(lignes, columns=["dci", "code_atc", "methode"])
    df.to_sql("dci_atc", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dci_atc_dci ON dci_atc (dci)")
    log_update(conn, "dci_atc", len(df))
    conn.commit()
    conn.close()

    reliees = set(df["dci"])
    rapport = rcp[~rcp["dci"].isin(reliees | sans)].sort_values("n_cis", ascending=False)
    rapport.to_csv(RAPPORT, index=False)
    print(
        f"dci_atc : {len(df)} lignes, {len(reliees)}/{len(rcp)} DCI reliées, "
        f"{len(sans)} sans ATC, {len(rapport)} à traiter ({RAPPORT.name})"
    )
    print(df.drop_duplicates("dci")["methode"].value_counts().to_string())


if __name__ == "__main__":
    main()
