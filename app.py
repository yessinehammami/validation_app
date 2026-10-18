import streamlit as st
import streamlit_authenticator as stauth
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit_authenticator.utilities.exceptions import LoginError

st.set_page_config(page_title="Validation ordonnances", page_icon="💊", layout="wide")


def to_dict(obj):
    # st.secrets est en lecture seule : la librairie a besoin de dict modifiables
    if hasattr(obj, "items"):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


try:
    secrets_ok = "credentials" in st.secrets and "cookie" in st.secrets
except (FileNotFoundError, StreamlitSecretNotFoundError):
    secrets_ok = False

if not secrets_ok:
    st.error("Authentification non configurée (secrets manquants).")
    st.stop()

pages = [
    st.Page("conversion_dci.py", title="Liste AMMs en Tunisie", icon="🇹🇳", default=True),
    st.Page("donnees_rcp.py", title="Résumé Caractéristiques Produits (France)", icon="🇫🇷"),
        st.Page("nomenclature_hospitaliere.py", title="Nomenclature Hospitalière", icon="🏥"),    st.Page("consignation.py", title="Produits en consignation avec visa PCT / DPM", icon="📦"),
    st.Page("agent_hors_indication/recherche_hors_amm.py", title="Recherche indication hors AMM", icon="🔬"),
    st.Page("bibliotheque_hors_amm.py", title="Bibliothèque des indications hors AMM", icon="📚"),
]
# Enregistrer les pages AVANT le login : le composant cookie relance le script,
# et sans cela le navigateur perd la page courante (retour à la 1re page au F5).
st.navigation(pages, position="hidden")

authenticator = stauth.Authenticate(
    to_dict(st.secrets["credentials"]),
    st.secrets["cookie"]["name"],
    st.secrets["cookie"]["key"],
    st.secrets["cookie"]["expiry_days"],
    auto_hash=False,
)
try:
    authenticator.login(max_login_attempts=5)
except LoginError:
    # cookie d'un compte supprimé ou renommé : on l'efface et on repart sur le formulaire
    authenticator.cookie_controller.delete_cookie()
    st.warning("Session expirée ou compte supprimé. Rechargez la page (F5) pour vous reconnecter.")
    st.stop()

connecte = bool(st.session_state.get("authentication_status"))
# navigation masquée tant que non connecté, sinon l'ancien menu reste affiché
pg = st.navigation(pages, position="sidebar" if connecte else "hidden")

if st.session_state.get("authentication_status") is False:
    st.error("Identifiant ou mot de passe incorrect.")
if not connecte:
    st.stop()

with st.sidebar:
    st.markdown("### 💊 Validation ordonnances")
    st.caption(f"Connecté : {st.session_state.get('name') or st.session_state.get('username') or ''}")
authenticator.logout("Déconnexion", "sidebar")
pg.run()