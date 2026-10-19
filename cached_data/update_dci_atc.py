"""Noms de substances (table_rcp.dci + composants de dpm_produit_raw.dci) -> table substance.

Une ligne par (nom, code ATC niveau 5) ; id_substance = INN anglais, ou nom sans sel si pas d'ATC.
statut : ok (ATC trouvé), sans_atc (déclaré sans ATC), a_verifier (non résolu -> rapport_substances.csv).
Cascade : alias manuel, exact, inn_dci (FR -> EN), sans sel/hydrate, sans 'e' final (FR -> EN).
Télécharge aussi l'ATC et la liste INN/DCI (build.db). Doit tourner après update_dpm.py et update_bdpm.py.
"""
import io
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
import requests

from maj_tables import DB_APP, DB_BUILD, log_update

URL_ATC = "https://data.bioontology.org/ontologies/ATC/download?download_format=csv&apikey=8b5b7825-538d-40e0-9e9e-5ab9274a9aeb"
URL_INN = "https://www.wcoomd.org/-/media/wco/public/global/excel/inn-dci-list.xlsx?db=web"

ALIAS = Path(__file__).with_name("alias_manuels.csv")
RAPPORT = Path(__file__).with_name("rapport_substances.csv")
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
    r"succinate|mesilate|besilate|nitrate|bromure|oxyde)$"
)
# sel entre parenthèses après le nom (format BDPM) : "bisoprolol (fumarate acide de)", "atropine (sulfate d')"
SEL_PARENTHESES = re.compile(r"\s*\([^()]*\b(?:de|d')\s*\)")
ACIDE_INVERSE = re.compile(r"^(.+?) \(acide\)$")  # "clavulanique (acide)" -> "acide clavulanique"


def normalize(text):
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def sans_sel(nom):
    nom = ACIDE_INVERSE.sub(r"acide \1", nom)
    nom = SEL_PARENTHESES.sub("", nom)
    nom = " ".join(m for m in nom.split() if m not in FORMES)
    nom = PREFIXE_SEL.sub("", nom)
    return SUFFIXE_SEL.sub("", nom).strip()


def acide_en(nom):
    """'acide ascorbique' -> 'ascorbic acid' (ordre et suffixe anglais)"""
    m = re.match(r"^acide (\w+?)ique$", nom)
    return f"{m.group(1)}ic acid" if m else None


def charger_references(build):
    """Tables de référence : INN anglais -> codes ATC, FR -> EN, alias manuels."""
    atc = pd.read_sql("SELECT code, inn FROM atc WHERE level = 5 AND inn IS NOT NULL", build)
    inn_dci = pd.read_sql("SELECT inn, dci FROM inn_dci", build).dropna()
    par_inn = atc.assign(inn=atc["inn"].map(normalize)).groupby("inn")["code"].apply(list).to_dict()
    fr_en = {normalize(d): normalize(i) for i, d in zip(inn_dci["inn"], inn_dci["dci"])}
    alias = {}
    if ALIAS.exists():
        a = pd.read_csv(ALIAS, dtype=str).dropna(subset=["dci_bdpm", "inn_en"])
        alias = {normalize(d): normalize(i) for d, i in zip(a["dci_bdpm"], a["inn_en"])}
    return par_inn, fr_en, alias


def resoudre(dci, par_inn, fr_en, alias):
    """Renvoie (méthode, INN anglais retenu, codes ATC, sans_atc) ; méthode None si non résolu."""
    n = normalize(dci)
    if "homeopathiques" in n or n.startswith("virus "):
        return "regle_sans_atc", None, None, True
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
            return methode, None, None, True
        if cible in par_inn:
            return methode, cible, par_inn[cible], False
    return None, None, None, False


def telecharger_references():
    """Télécharge l'ATC (BioPortal) et la liste INN/DCI (OMD) dans build.db."""
    r = requests.get(URL_ATC, timeout=300)
    r.raise_for_status()
    atc = pd.read_csv(io.BytesIO(r.content), compression="gzip", low_memory=False)
    atc = atc.rename(columns={"Class ID": "code", "Preferred Label": "inn",
                              "Parents": "parent_code", "ATC LEVEL": "level"})
    # URL BioPortal -> code ATC seul (.../ATC/D11AX06 -> D11AX06)
    atc["code"] = atc["code"].str.rsplit("/", n=1).str[-1]
    atc["parent_code"] = atc["parent_code"].str.rsplit("/", n=1).str[-1]
    atc["level"] = atc["level"].astype("Int64")
    atc["inn"] = atc["inn"].str.lower().str.strip()
    atc = atc[["code", "inn", "parent_code", "level"]]

    r = requests.get(URL_INN, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    if not r.content.startswith(b"PK"):  # un xlsx est un zip
        raise SystemExit("Le fichier INN/DCI téléchargé n'est pas un xlsx valide")
    inn_dci = pd.read_excel(io.BytesIO(r.content), header=2)[["Product (En)", "Produit (Fr)"]]
    inn_dci = inn_dci.rename(columns={"Product (En)": "inn", "Produit (Fr)": "dci"})

    with sqlite3.connect(DB_BUILD) as build:
        atc.to_sql("atc", build, if_exists="replace", index=False)
        build.execute("CREATE INDEX IF NOT EXISTS idx_atc_code ON atc (code)")
        log_update(build, "atc", len(atc))
        inn_dci.to_sql("inn_dci", build, if_exists="replace", index=False)
        log_update(build, "inn_dci", len(inn_dci))
    print(f"atc : {len(atc)} lignes ; inn_dci : {len(inn_dci)} lignes")


def main():
    telecharger_references()
    conn = sqlite3.connect(DB_APP)
    build = sqlite3.connect(DB_BUILD)
    par_inn, fr_en, alias = charger_references(build)
    build.close()

    rcp = pd.read_sql(
        "SELECT dci AS nom, COUNT(DISTINCT code_cis) AS n_produits FROM table_rcp "
        "WHERE dci IS NOT NULL GROUP BY dci",
        conn,
    ).assign(source="rcp")
    # une association DPM s'écrit "A + B" : un nom par composant
    dpm = pd.read_sql("SELECT amm, dci FROM dpm_produit_raw WHERE dci IS NOT NULL AND amm IS NOT NULL", conn)
    dpm = dpm.assign(nom=dpm["dci"].str.split("+")).explode("nom")
    dpm["nom"] = dpm["nom"].str.strip()
    dpm = dpm[dpm["nom"] != ""]
    dpm = (
        dpm.groupby("nom")["amm"].nunique().rename("n_produits").reset_index().assign(source="dpm")
    )

    noms = pd.concat([rcp, dpm])
    noms["nom_normalise"] = noms["nom"].map(normalize)
    # un nom DPM déjà présent côté RCP (même forme normalisée) est fusionné ; sinon une ligne par nom
    sources = noms.groupby("nom_normalise")["source"].apply(lambda s: "+".join(sorted(set(s))))
    produits = noms.groupby("nom_normalise")["n_produits"].sum()
    noms = noms[(noms["source"] == "rcp") | ~noms["nom_normalise"].isin(rcp["nom"].map(normalize))]

    lignes = []
    for nom, nom_norm in zip(noms["nom"], noms["nom_normalise"]):
        methode, inn, codes, sans_atc = resoudre(nom, par_inn, fr_en, alias)
        if codes:
            id_substance, statut = inn, "ok"
        else:
            id_substance = nom_norm if methode == "regle_sans_atc" else sans_sel(nom_norm) or nom_norm
            statut = "sans_atc" if sans_atc else "a_verifier"
        for code in codes or [None]:
            lignes.append({
                "nom": nom, "nom_normalise": nom_norm, "id_substance": id_substance, "inn_en": inn,
                "code_atc": code, "statut": statut, "methode": methode,
                "sources": sources[nom_norm], "n_produits": int(produits[nom_norm]),
            })

    df = pd.DataFrame(lignes).drop_duplicates(["nom", "code_atc"]).sort_values(["nom_normalise", "code_atc"])
    for ancienne in ("dci_atc", "substance_atc", "synonyme", "composition_rcp", "composition_dpm"):
        conn.execute(f"DROP TABLE IF EXISTS {ancienne}")
        conn.execute("DELETE FROM maj_tables WHERE table_name = ?", (ancienne,))
    df.drop(columns="n_produits").to_sql("substance", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_substance_nom ON substance (nom)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_substance_norm ON substance (nom_normalise)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_substance_id ON substance (id_substance)")
    log_update(conn, "substance", len(df))
    conn.commit()
    conn.close()

    noms_uniques = df.drop_duplicates("nom")
    rapport = noms_uniques[noms_uniques["statut"] == "a_verifier"].sort_values("n_produits", ascending=False)
    rapport[["nom", "id_substance", "sources", "n_produits"]].to_csv(RAPPORT, index=False)
    print(f"substance : {len(df)} lignes, {len(noms_uniques)} noms, {df['id_substance'].nunique()} substances")
    print(noms_uniques["statut"].value_counts().to_string())
    print(f"{len(rapport)} à traiter ({RAPPORT.name})")


if __name__ == "__main__":
    main()


