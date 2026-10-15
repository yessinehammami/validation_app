import streamlit as st
import streamlit_authenticator as stauth
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit_authenticator.utilities.exceptions import LoginError

st.set_page_config(page_title="Validation ordonnances", layout="wide")


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

pages = [
    st.Page("conversion_dci.py", title="Liste AMMs en Tunisie", default=True),
    st.Page("donnees_rcp.py", title="Résumé Caractéristiques Produits (France)"),
]
connecte = bool(st.session_state.get("authentication_status"))
# navigation masquée tant que non connecté, sinon l'ancien menu reste affiché
pg = st.navigation(pages, position="sidebar" if connecte else "hidden")

if st.session_state.get("authentication_status") is False:
    st.error("Identifiant ou mot de passe incorrect.")
if not connecte:
    st.stop()

authenticator.logout("Déconnexion", "sidebar")
pg.run()