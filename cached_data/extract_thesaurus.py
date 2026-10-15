"""Extrait le Thesaurus des interactions medicamenteuses (ANSM, sept. 2023) du PDF vers un CSV.

Le PDF n'est plus mis a jour : ce script est lance a la main, le CSV est versionne.
Dependance (hors app) : pip install pymupdf
"""
import re
from pathlib import Path

import pandas as pd
import pymupdf

RACINE = Path(__file__).resolve().parent.parent
PDF = next(RACINE.glob("Don*/thesaurus.pdf"))
SORTIE = Path(__file__).with_name("thesaurus_interactions.csv")

# Ordre croissant de gravite
NIVEAUX = ["APEC", "PE", "ASDEC", "CI"]


def niveaux_de(texte):
    """Niveaux (codes) cites dans la premiere ligne de la colonne de droite."""
    t = texte.lower()
    trouves = set()
    if re.search(r"\bci\b|contre-indication", t):
        trouves.add("CI")
    if re.search(r"asdec|d.conseill", t):
        trouves.add("ASDEC")
    if re.search(r"\bpe\b|pr.caution", t):
        trouves.add("PE")
    if re.search(r"apec|prendre en compte", t):
        trouves.add("APEC")
    return [n for n in NIVEAUX[::-1] if n in trouves]


def lignes(doc):
    """(x, taille, texte) de chaque ligne, hors numeros de page."""
    for page in doc:
        for bloc in page.get_text("dict")["blocks"]:
            for ligne in bloc.get("lines", []):
                texte = "".join(s["text"] for s in ligne["spans"]).strip()
                if not texte:
                    continue
                x = ligne["bbox"][0]
                taille = round(ligne["spans"][0]["size"])
                if taille == 8 and x > 200 and texte.isdigit():
                    continue
                yield x, taille, texte


def extraire():
    doc = pymupdf.open(PDF)
    lignes_doc = list(lignes(doc))
    # On ignore la partie introductive : les donnees commencent au premier titre de substance
    debut = next(i for i, (x, t, _) in enumerate(lignes_doc) if t == 10 and x < 40 and _.isupper())

    rows = []
    a = voir_aussi = ""
    cur = None
    dernier = None  # element en cours d'ecriture, pour les lignes qui continuent

    def clore():
        nonlocal cur
        if cur:
            cur["niveaux"] = niveaux_de(cur["_droite"][0]) if cur["_droite"] else []
            cur["niveau_max"] = cur["niveaux"][0] if cur["niveaux"] else ""
            cur["niveaux"] = "|".join(cur["niveaux"])
            cur["niveau_brut"] = cur["_droite"][0] if cur["_droite"] else ""
            cur["conduite_a_tenir"] = " ".join(cur["_droite"][1:])
            cur["mecanisme"] = " ".join(cur["_meca"])
            del cur["_droite"], cur["_meca"]
            rows.append(cur)
            cur = None

    for x, taille, texte in lignes_doc[debut:]:
        if taille == 10 and x < 40:
            if dernier == "a":
                a += " " + texte
            else:
                clore()
                a, voir_aussi = texte, ""
            dernier = "a"
        elif taille == 7 and x < 60:
            if texte.lower().startswith("voir aussi"):
                voir_aussi = texte.split(":", 1)[1].strip() if ":" in texte else texte
            else:
                voir_aussi += " " + texte
            dernier = "voir"
        elif taille == 8 and x < 60 and texte.startswith("+"):
            clore()
            cur = {"a": a, "b": texte[1:].strip(), "voir_aussi_a": voir_aussi,
                   "_droite": [], "_meca": []}
            dernier = "b"
        elif taille == 8 and x < 60 and cur and dernier == "b":
            cur["b"] += " " + texte
        elif cur and taille == 7 and x > 250:
            cur["_droite"].append(texte)
            dernier = "droite"
        elif cur and taille == 7:
            cur["_meca"].append(texte)
            dernier = "meca"
    clore()
    return pd.DataFrame(rows)


def main():
    df = extraire()
    for col in ("a", "b", "voir_aussi_a", "niveau_brut", "conduite_a_tenir", "mecanisme"):
        df[col] = df[col].str.replace(r"\s+", " ", regex=True).str.strip()
    df.insert(0, "source", "thesaurus_ansm_2023")
    df.to_csv(SORTIE, index=False, encoding="utf-8-sig")

    print(f"{len(df)} interactions, {df['a'].nunique()} substances/classes A, {df['b'].nunique()} B")
    print(df["niveau_max"].replace("", "(aucun)").value_counts().to_string())
    print("sans mecanisme :", (df["mecanisme"] == "").sum(), "| sans conduite :",
          (df["conduite_a_tenir"] == "").sum(), "| niveau inconnu :", (df["niveau_max"] == "").sum())
    print("ecrit :", SORTIE)


if __name__ == "__main__":
    main()
