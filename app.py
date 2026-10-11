import streamlit as st

st.set_page_config(page_title="Validation ordonnances", layout="wide")

pg = st.navigation([
    st.Page("conversion_dci.py", title="Conversion rapide en DCI", default=True),
    st.Page("recherche_dci.py", title="Recherche par DCI"),
    st.Page("donnees_rcp.py", title="Données RCP"),
])
pg.run()