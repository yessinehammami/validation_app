import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymupdf
import streamlit as st

from common import normalize

FICHIER = Path(__file__).parent / "documents_nomenclature" / "nh2023.pdf"
DB = Path(__file__).parent / "consignation_Nomenclature hospit" / "documents.db"
TABLE = "nomenclature_hospitaliere"
HAUT_PAGE = 60  # l'en-tête de chaque page ("Nomenclature Hospitalière 2023 / Chapitre / n°") est au-dessus de cette ordonnée


@st.cache_data(show_spinner="Chargement du document...")
def pages_pdf(contenu):
    """Une image PNG par page du PDF."""
    with pymupdf.open(stream=contenu, filetype="pdf") as doc:
        return [p.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).tobytes("png") for p in doc]


@st.dialog("Mettre à jour le document")
def dialogue_maj(existe):
    st.caption("Le nouveau PDF remplacera l'actuel." if existe else "Aucun document n'est encore déposé.")
    # la clé change après chaque dépôt pour vider le champ
    cle = f"upload_nomenclature_{st.session_state.get('upload_nomenclature_n', 0)}"
    pdf = st.file_uploader("Fichier PDF", type="pdf", key=cle)
    if pdf and st.button("💾 Enregistrer", type="primary", width="stretch"):
        contenu = pdf.getvalue()
        df = lire_nomenclature(contenu)
        if df.empty:
            st.error("Aucune ligne de nomenclature n'a été détectée dans ce PDF.")
            return
        _enregistrer_tableau(df)
        FICHIER.parent.mkdir(exist_ok=True)
        FICHIER.write_bytes(contenu)
        st.session_state["upload_nomenclature_n"] = st.session_state.get("upload_nomenclature_n", 0) + 1
        st.toast("Document et tableau enregistrés")
        st.rerun()


def _table_exists():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (TABLE,),
        ).fetchone() is not None


def _enregistrer_tableau(df):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        df.to_sql(TABLE, conn, if_exists="replace", index=False)


def _charger_tableau():
    with sqlite3.connect(DB) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{TABLE}"', conn)


def _propre(texte):
    return re.sub(r"\s+", " ", (texte or "").replace("\n", " ")).strip()


@st.cache_data(show_spinner="Lecture de la nomenclature (quelques secondes)...")
def lire_nomenclature(contenu):
    """Un tableau unique : Chapitre, Rubrique (titre au-dessus du tableau), L, DCI, Forme, Classification AWaRe.
    Un tableau sans titre (suite de page) reprend la rubrique du tableau précédent."""
    lignes, rubrique = [], ""
    with pymupdf.open(stream=contenu, filetype="pdf") as doc:
        for page in doc:
            if page.number == 0:  # page de garde
                continue
            tableaux = sorted(page.find_tables().tables, key=lambda t: t.bbox[1])
            if not tableaux:
                continue
            haut = page.get_text().split("\n")
            chapitre = _propre(haut[1]) if len(haut) > 1 else ""
            blocs = page.get_text("blocks")
            precedent = HAUT_PAGE
            for t in tableaux:
                titre = _propre(" ".join(b[4] for b in blocs if precedent - 2 <= b[1] < t.bbox[1] - 1 and b[3] <= t.bbox[1] + 2))
                if titre:
                    rubrique = titre
                precedent = t.bbox[3]
                for r in t.extract():
                    cells = [_propre(c) for c in r] + [""] * 4
                    if cells[0] == "L" and cells[1].upper().startswith("D.C.I"):
                        continue
                    if not cells[1] or len(cells[1]) > 200:  # > 200 : liste des préparations hospitalières, pas une DCI
                        continue
                    lignes.append({
                        "Chapitre": chapitre, "Rubrique": rubrique, "L": cells[0],
                        "DCI": cells[1], "Forme": cells[2], "Classification AWaRe": cells[3],
                    })
    return pd.DataFrame(lignes)


st.title("🏥 Nomenclature Hospitalière")

existe = FICHIER.exists()
col_info, col_btn = st.columns([3, 1], vertical_alignment="top")
if existe:
    modif = datetime.fromtimestamp(FICHIER.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    col_info.caption(f"Nomenclature hospitalière (DPM) - dernière mise à jour le {modif}")
    col_btn.download_button("⬇️ Télécharger", FICHIER.read_bytes(), file_name=FICHIER.name, mime="application/pdf", width="stretch")
else:
    col_info.warning("Aucun document déposé pour le moment.")
if col_btn.button("🔄 Mettre à jour" if existe else "📤 Déposer", width="stretch", key="maj_nomenclature"):
    dialogue_maj(existe)

if not existe:
    st.stop()

if not _table_exists():
    tableau_extrait = lire_nomenclature(FICHIER.read_bytes())
    if tableau_extrait.empty:
        st.error("Aucune ligne de nomenclature n'a été détectée dans ce PDF.")
        st.stop()
    _enregistrer_tableau(tableau_extrait)
df = _charger_tableau()

vue = st.segmented_control("Affichage", ["Tableau filtrable", "Document PDF"], default="Tableau filtrable", key="vue_nomenclature")
if vue == "Document PDF":
    _, centre, _ = st.columns([1, 3, 1])
    with centre:
        for img in pages_pdf(FICHIER.read_bytes()):
            st.image(img, width="stretch")
    st.stop()

st.caption(f"{len(df)} lignes extraites du PDF")

with st.expander("Légende"):
    st.markdown(
        "- **D** : produit de la nomenclature des centres de soins de santé de base (CSSB).\n"
        "- **Case vide** : prescription réservée aux médecins des établissements de 3ème et 2ème lignes, hôpitaux de circonscription "
        "et spécialistes des centres intermédiaires.\n"
        "- **BS** (dans la colonne DCI) : prescription réservée aux médecins des établissements de 3ème, 2ème lignes et hôpitaux de circonscription."
    )

col1, col2 = st.columns(2)
chapitres = list(dict.fromkeys(df["Chapitre"]))
chapitre = col1.selectbox("Chapitre", chapitres, index=None, placeholder="Tous les chapitres", key="nh_chapitre")
options = sorted({v for v in df["DCI"] if v}, key=normalize)
dci = col2.selectbox("DCI", options, index=None, placeholder="Tapez pour rechercher...", key="nh_dci")

masque = pd.Series(True, index=df.index)
if chapitre:
    masque &= df["Chapitre"] == chapitre
if dci:
    masque &= df["DCI"] == dci
st.caption(f"{int(masque.sum())} ligne(s) sur {len(df)}")
st.dataframe(df[masque], hide_index=True, width="stretch", height=600)
