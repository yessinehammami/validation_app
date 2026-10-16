import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox
from common import (
    NIVEAU_LIBELLE, analyser_ordonnance, load_data, load_rcp, normalize, specialites_pour_dci,
    suggestions,
)

df, file_time = load_data()
labels = sorted(df["label"].dropna().unique())

st.title("🇹🇳 Liste AMMs en Tunisie")
st.caption(
    f"Données du {pd.Timestamp(file_time, unit='s'):%d/%m/%Y} · "
    "Recherchez une spécialité ou une DCI, composez une ordonnance et détectez les interactions."
)

# Initialiser session state pour la liste d'ordonnance
if "ordonnance" not in st.session_state:
    st.session_state.ordonnance = []

# Sélectionner un produit (en haut)
def suggest(term):
    return suggestions(df, "_label", "label", term)

def ajouter(choix):
    if choix and choix not in st.session_state.ordonnance:
        st.session_state.ordonnance.append(choix)


dci_options = df[["dci", "_dci"]].dropna().drop_duplicates("dci").sort_values("dci")


def suggest_dci(term):
    t = normalize(term)
    return dci_options.loc[dci_options["_dci"].str.contains(t, regex=False), "dci"].head(20).tolist()


col_add, col_dci = st.columns(2, gap="large")

with col_add:
    with st.container(border=True):
        st.markdown("#### ➕ Ajouter une spécialité")
        st.caption("Tapez le nom d'une spécialité pour l'ajouter à l'ordonnance.")
        st_searchbox(
            suggest,
            key="sb_specialite",
            default_options=suggest(""),
            placeholder="Tapez une spécialité...",
            clear_on_submit=True,
            submit_function=ajouter,
        )

with col_dci:
    with st.container(border=True):
        st.markdown("#### 🔎 Rechercher par DCI")
        st.caption("Consultation uniquement : n'ajoute rien à l'ordonnance.")
        dci_cherchee = st_searchbox(
            suggest_dci,
            key="sb_dci_recherche",
            default_options=suggest_dci(""),
            placeholder="Tapez une DCI (ex: amoxicilline)...",
        )

if dci_cherchee:
    correspondants = (
        df.loc[df["dci"] == dci_cherchee, "label"].dropna().drop_duplicates().sort_values()
    )
    with st.container(border=True):
        st.markdown(f"**{len(correspondants)} spécialité(s)** pour **{dci_cherchee}**")
        for i, nom in enumerate(correspondants):
            c_nom, c_btn = st.columns([12, 1], vertical_alignment="center")
            c_nom.write(nom)
            deja = nom in st.session_state.ordonnance
            c_btn.button(
                "✓" if deja else "➕",
                key=f"add_dci_{i}",
                disabled=deja,
                help="Déjà dans l'ordonnance" if deja else "Ajouter à l'ordonnance",
                on_click=ajouter,
                args=(nom,),
            )

st.write("")

def valeurs_de(label, colonne):
    vals = sorted(df.loc[df["label"] == label, colonne].dropna().astype(str).str.strip().unique())
    vals = [v for v in vals if v]
    return " + ".join(vals) if vals else "-"


def dci_de(label):
    return valeurs_de(label, "dci")


if not st.session_state.ordonnance:
    st.info("📋 L'ordonnance est vide : ajoutez une spécialité ci-dessus pour commencer.")
else:
    rcp = load_rcp()
    with st.container(border=True):
        titre_col, reset_col = st.columns([4, 1], vertical_alignment="center")
        titre_col.subheader(f"📋 Ordonnance actuelle ({len(st.session_state.ordonnance)})")
        if reset_col.button("🗑️ Réinitialiser", width="stretch"):
            st.session_state.ordonnance = []
            st.rerun()
        poids = [3, 3, 2, 2, 2, 1]
        entete = st.columns(poids)
        for col, titre in zip(entete, ["Spécialité", "DCI", "Classe", "Sous-classe", "Spécialités RCP"]):
            col.caption(titre.upper())
        for idx, label in enumerate(st.session_state.ordonnance):
            st.divider()
            c1, c2, c3, c4, c5, c6 = st.columns(poids, vertical_alignment="center")
            c1.markdown(f"**{label}**")
            c2.write(dci_de(label))
            c3.write(valeurs_de(label, "classe"))
            c4.write(valeurs_de(label, "sous_classe"))
            for d in sorted(df.loc[df["label"] == label, "dci"].dropna().unique()):
                n = len(specialites_pour_dci(rcp, d))
                if n and c5.button(f"{n} spécialité(s) →", key=f"rcp_{idx}_{d}"):
                    st.session_state.rcp_dci = d
                    st.switch_page("donnees_rcp.py")
            if c6.button("❌", key=f"remove_{idx}", help="Retirer de l'ordonnance"):
                st.session_state.ordonnance.pop(idx)
                st.rerun()

    detecter = st.button(
        "🔍 Détecter une interaction",
        type="primary",
        width="stretch",
        disabled=len(st.session_state.ordonnance) < 2,
        help=None if len(st.session_state.ordonnance) >= 2 else "Ajoutez au moins 2 médicaments",
    )
    if detecter:
        medicaments = {
            label: sorted(df.loc[df["label"] == label, "dci"].dropna().unique())
            for label in st.session_state.ordonnance
        }
        interactions, sans_atc = analyser_ordonnance(rcp, medicaments)

        if interactions:
            st.subheader(f"⚠️ {len(interactions)} interaction(s) détectée(s)")
            cols = st.columns(4)
            for col, code in zip(cols, ["CI", "ASDEC", "PE", "APEC"]):
                col.metric(NIVEAU_LIBELLE[code], sum(r["niveau"] == code for r in interactions))
        else:
            st.success("✅ Aucune interaction trouvée dans le Thésaurus ANSM pour ces médicaments.")
        for r in interactions:
            alerte = st.error if r["niveau"] in ("CI", "ASDEC") else st.warning
            with st.container(border=True):
                alerte(f"**{NIVEAU_LIBELLE.get(r['niveau'], r['niveau'])}** : {r['m1']} ↔ {r['m2']}")
                st.caption(f"Thésaurus : {r['a']} + {r['b']} ({r['niveaux'].replace('|', ', ')})")
                if r["conduite"]:
                    st.write(f"**Conduite à tenir :** {r['conduite']}")
                st.write(f"**Mécanisme :** {r['mecanisme']}")
        if sans_atc:
            st.info("Non analysés (aucun code ATC trouvé) : " + ", ".join(sans_atc))
        st.caption(
            "Analyse indicative basée sur le Thésaurus des interactions médicamenteuses de l'ANSM "
            "(sept. 2023, classes partiellement couvertes). Elle ne remplace pas l'avis d'un "
            "pharmacien ni la lecture du RCP."
        )
