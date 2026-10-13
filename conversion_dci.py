import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox
from common import load_data, load_rcp, specialites_pour_dci, suggestions

df, file_time = load_data()
labels = sorted(df["label"].dropna().unique())

st.title("Conversion rapide en DCI")
st.caption(f"Données du {pd.Timestamp(file_time, unit='s'):%d/%m/%Y}")

# Initialiser session state pour la liste d'ordonnance
if "ordonnance" not in st.session_state:
    st.session_state.ordonnance = []

# Sélectionner un produit (en haut)
def suggest(term):
    return suggestions(df, "_label", "label", term)

def ajouter(choix):
    if choix and choix not in st.session_state.ordonnance:
        st.session_state.ordonnance.append(choix)


st_searchbox(
    suggest,
    key="sb_specialite",
    default_options=suggest(""),
    placeholder="Tapez une spécialité...",
    clear_on_submit=True,
    submit_function=ajouter,
)

st.divider()


def valeurs_de(label, colonne):
    vals = sorted(df.loc[df["label"] == label, colonne].dropna().astype(str).str.strip().unique())
    vals = [v for v in vals if v]
    return " + ".join(vals) if vals else "-"


def dci_de(label):
    return valeurs_de(label, "dci")


if st.session_state.ordonnance:
    st.subheader("📋 Ordonnance actuelle")
    rcp = load_rcp()
    poids = [3, 3, 2, 2, 2, 1]
    entete = st.columns(poids)
    for col, titre in zip(entete, ["Spécialité", "DCI", "Classe", "Sous-classe", "Spécialités RCP"]):
        col.markdown(f"**{titre}**")
    for idx, label in enumerate(st.session_state.ordonnance):
        c1, c2, c3, c4, c5, c6 = st.columns(poids, vertical_alignment="center")
        c1.write(label)
        c2.write(dci_de(label))
        c3.write(valeurs_de(label, "classe"))
        c4.write(valeurs_de(label, "sous_classe"))
        for d in sorted(df.loc[df["label"] == label, "dci"].dropna().unique()):
            n = len(specialites_pour_dci(rcp, d))
            if n and c5.button(f"{n} spécialité(s) →", key=f"rcp_{idx}_{d}"):
                st.session_state.rcp_dci = d
                st.switch_page("donnees_rcp.py")
        if c6.button("❌", key=f"remove_{idx}"):
            st.session_state.ordonnance.pop(idx)
            st.rerun()
