from datetime import datetime
from pathlib import Path
import sqlite3

import fitz
import pandas as pd
import streamlit as st

from common import normalize

DOSSIER = Path(__file__).parent / "documents_consignation"
DB = Path(__file__).parent / "consignation_Nomenclature hospit" / "documents.db"
CATEGORIES = {"Hospitalier": "hospitalier", "Officinal": "officinal"}
VISAS = {"Visa DPM": "dpm", "Visa PCT": "pct"}
TABLES = {
    "hospitalier_dpm": "consignation_hospitalier_dpm",
    "hospitalier_pct": "consignation_hospitalier_pct",
    "officinal_dpm": "consignation_officinal_dpm",
    "officinal_pct": "consignation_officinal_pct",
}


@st.cache_data(show_spinner="Chargement du document...")
def pages_pdf(contenu):
    """Une image PNG par page du PDF."""
    with fitz.open(stream=contenu, filetype="pdf") as doc:
        return [p.get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).tobytes("png") for p in doc]


@st.cache_data(show_spinner="Lecture du tableau...")
def tableau_pdf(contenu):
    """Fusionne les tableaux de toutes les pages ; la première ligne sert d'en-tête. None si aucun tableau."""
    lignes = []
    with fitz.open(stream=contenu, filetype="pdf") as doc:
        for page in doc:
            for t in page.find_tables().tables:
                lignes += [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
    if len(lignes) < 2:
        return None
    entete = lignes[0]
    noms, vus = [], {}
    for i, n in enumerate(entete):
        n = n or f"Colonne {i + 1}"
        vus[n] = vus.get(n, 0) + 1
        noms.append(n if vus[n] == 1 else f"{n} ({vus[n]})")
    largeur = len(noms)
    corps = [(r + [""] * largeur)[:largeur] for r in lignes[1:] if r != entete and any(r)]
    return pd.DataFrame(corps, columns=noms)


def _table_exists(nom_table):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (nom_table,),
        ).fetchone() is not None


def _enregistrer_tableau(nom_table, df):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        df.to_sql(nom_table, conn, if_exists="replace", index=False)


def _charger_tableau(nom_table):
    with sqlite3.connect(DB) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{nom_table}"', conn)


def _colonne(df, mot):
    return next((c for c in df.columns if mot in normalize(c)), None)


def afficher_tableau(df):
    """Deux filtres à liste déroulante avec suggestions pendant la saisie : DCI (colonne BESOIN) et Spécialité."""
    filtres = [("DCI", _colonne(df, "besoin")), ("Spécialité", _colonne(df, "specialite"))]
    masque = pd.Series(True, index=df.index)
    cols = st.columns(2)
    for (titre, nom), col in zip(filtres, cols):
        if nom is None:
            col.warning(f"Colonne « {titre} » introuvable dans le tableau.")
            continue
        options = sorted({v for v in df[nom] if v}, key=normalize)
        choix_val = col.selectbox(titre, options, index=None, placeholder="Tapez pour rechercher...", key=f"cons_{choix}_{titre}")
        if choix_val:
            masque &= df[nom] == choix_val
    st.caption(f"{int(masque.sum())} ligne(s) sur {len(df)}")
    st.dataframe(df[masque], hide_index=True, width="stretch", height=600)


st.title("📦 Produits en consignation avec visa PCT / DPM")

type_ = st.segmented_control("Type", list(CATEGORIES), default=None, key="consignation_type")
if not type_:
    st.info("Choisissez d'abord le type : Hospitalier ou Officinal.")
    st.stop()

visa = st.segmented_control("Visa", list(VISAS), default=None, key="consignation_visa")
if not visa:
    st.info("Choisissez maintenant le visa : DPM ou PCT.")
    st.stop()

choix = f"{type_} - {visa}"
fichier = DOSSIER / f"{CATEGORIES[type_]}_{VISAS[visa]}.pdf"
nom_table = TABLES[fichier.stem]

@st.dialog("Mettre à jour le document")
def dialogue_maj(fichier, existe):
    st.caption("Le nouveau PDF remplacera l'actuel." if existe else "Aucun document n'est encore déposé.")
    # la clé change après chaque dépôt pour vider le champ
    cle = f"upload_{fichier.stem}_{st.session_state.get('upload_n', 0)}"
    pdf = st.file_uploader("Fichier PDF", type="pdf", key=cle)
    if pdf and st.button("💾 Enregistrer", type="primary", width="stretch"):
        contenu = pdf.getvalue()
        df = tableau_pdf(contenu)
        if df is None or df.empty:
            st.error("Aucun tableau n'a été détecté dans ce PDF.")
            return
        _enregistrer_tableau(nom_table, df)
        DOSSIER.mkdir(exist_ok=True)
        fichier.write_bytes(contenu)
        st.session_state["upload_n"] = st.session_state.get("upload_n", 0) + 1
        st.toast("Document et tableau enregistrés")
        st.rerun()


existe = fichier.exists()
col_info, col_btn = st.columns([3, 1], vertical_alignment="top")
if existe:
    modif = datetime.fromtimestamp(fichier.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    col_info.caption(f"Document {choix.lower()} - dernière mise à jour le {modif}")
    col_btn.download_button(
        "⬇️ Télécharger", fichier.read_bytes(), file_name=fichier.name, mime="application/pdf", width="stretch"
    )
else:
    col_info.warning(f"Aucun document {choix.lower()} déposé pour le moment.")
if col_btn.button("🔄 Mettre à jour" if existe else "📤 Déposer", width="stretch", key=f"maj_{choix}"):
    dialogue_maj(fichier, existe)

if existe:
    contenu = fichier.read_bytes()
    if not _table_exists(nom_table):
        tableau_extrait = tableau_pdf(contenu)
        if tableau_extrait is not None and not tableau_extrait.empty:
            _enregistrer_tableau(nom_table, tableau_extrait)
    df = _charger_tableau(nom_table) if _table_exists(nom_table) else None
    if df is None:
        st.info("Aucun tableau détecté dans ce PDF : affichage du document.")
        vue = "Document PDF"
    else:
        vue = st.segmented_control("Affichage", ["Tableau filtrable", "Document PDF"], default="Tableau filtrable", key=f"vue_{choix}")
    if vue == "Tableau filtrable":
        afficher_tableau(df)
    else:
        _, centre, _ = st.columns([1, 3, 1])
        with centre:
            for img in pages_pdf(contenu):
                st.image(img, width="stretch")
