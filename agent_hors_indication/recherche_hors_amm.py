import re
from html import escape

import streamlit as st

from agent_hors_indication.llm import MODELE_DEFAUT, creer_client, generer_requetes, synthetiser
from agent_hors_indication.sources import collecter

NOMBRE_PAR_SOURCE = 5

st.title("🔬 Recherche indication hors AMM")
st.caption("Sources : cadres dérogatoires ANSM (CPC, AAC, AAP), PubMed et Europe PMC (méta-analyses, revues "
           "systématiques, recommandations et essais randomisés en priorité), ClinicalTrials.gov et sites officiels. "
           "Posez votre question en français ou en anglais.")

try:
    cfg = dict(st.secrets["llm"])
    cle = cfg["api_key"]
except (KeyError, FileNotFoundError):
    st.warning('Clé API non configurée. Ajoutez dans les secrets :\n\n```toml\n[llm]\napi_key = "sk-..."\nmodel = "gpt-4.1-mini"\n```')
    st.stop()
modele = cfg.get("model", MODELE_DEFAUT)


@st.cache_resource
def client_llm(api_key):
    return creer_client(api_key)


question = st.text_input("Votre question", placeholder="ex : propranolol hors AMM, ou : traitement de la migraine chronique")

if st.button("🔎 Rechercher", type="primary") and question.strip():
    try:
        with st.spinner("Le LLM prépare les requêtes..."):
            plan = generer_requetes(client_llm(cle), modele, question.strip())
        with st.spinner("Interrogation de PubMed, Europe PMC, ClinicalTrials.gov et des sites officiels..."):
            articles, journal = collecter(plan, NOMBRE_PAR_SOURCE)
        with st.spinner("Le LLM rédige la synthèse..."):
            synthese, cites, fiches = synthetiser(client_llm(cle), modele, question.strip(), articles)
        # on garde tout en session pour survivre aux rechargements de la page
        st.session_state["pubmed"] = {
            "question": question.strip(), "plan": plan, "articles": articles, "journal": journal,
            "synthese": synthese, "cites": cites, "fiches": fiches,
        }
    except Exception as e:
        st.error(f"Erreur : {e}")

resultat = st.session_state.get("pubmed")


def synthese_html(texte, articles):
    """Transforme chaque [S#] en lien cliquable vers la source (gras, souligné, orange)."""
    def lien(m):
        i = int(m.group(1))
        if not 1 <= i <= len(articles):
            return ""
        url = escape(articles[i - 1]["url"], quote=True)
        return (f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                f'style="font-weight:700;text-decoration:underline;color:#f97316;">[S{i}]</a>')

    # le texte du LLM est échappé avant d'insérer notre HTML
    return re.sub(r"\[S(\d+)\]", lien, escape(texte, quote=False))


def tableau_fiches_html(articles, fiches):
    """Tableau HTML des fiches : contrairement à st.dataframe, le texte passe à la ligne au lieu d'être coupé.
    Colonnes à largeur minimale : sur un écran étroit, le tableau défile horizontalement."""
    colonnes = [("Source", 170), ("Indication traitée", 260), ("Posologie utilisée", 260), ("Résultat", 360)]
    cellule = "padding:0.5rem 0.6rem;border:1px solid rgba(128,128,128,0.3);vertical-align:top;text-align:left;"
    entete = "".join(f'<th style="{cellule}min-width:{l}px;background:rgba(128,128,128,0.12);">{c}</th>'
                     for c, l in colonnes)
    lignes = []
    for i, a in enumerate(articles, 1):
        if i not in fiches:
            continue
        f = fiches[i]
        source = (f'<a href="{escape(a["url"], quote=True)}" target="_blank" rel="noopener noreferrer">S{i}</a>'
                  f' · {escape(a["source"])}')
        details = " · ".join(escape(str(x)) for x in (a.get("type"), a.get("annee")) if x)
        # textes du LLM échappés : ils ne peuvent pas injecter de HTML
        valeurs = [f"<b>{source}</b><br>{details}"] + [escape(f[k]) for k in ("indication", "posologie", "resultat")]
        lignes.append("<tr>" + "".join(f'<td style="{cellule}">{v}</td>' for v in valeurs) + "</tr>")
    return (
        '<div style="overflow-x:auto;margin-bottom:0.5rem;">'
        f'<table style="border-collapse:collapse;width:100%;font-size:0.9rem;"><tr>{entete}</tr>{"".join(lignes)}</table>'
        "</div>"
    )

if resultat:
    plan = resultat["plan"]
    with st.expander("🧠 Recherches effectuées", expanded=False):
        st.write(f"**Médicament** : {plan.get('medicament_fr') or plan.get('medicament_en') or '-'}  ·  **Pathologie** : {plan.get('pathologie_en') or '-'}")
        for j in resultat["journal"]:
            st.write(f"**{j['outil']}** : {j['trouves']} trouvé(s), {j['nouveaux']} nouveau(x)" + (f" ⚠️ {j['erreur']}" if j["erreur"] else ""))
            st.code(j["requete"], language=None)
        st.caption("Les filtres de niveau de preuve sont ajoutés par le programme, pas par le LLM.")

    # cadre officiel ANSM affiché à part, avant la synthèse : c'est une information réglementaire, pas une étude
    ansm = [a for a in resultat["articles"] if a.get("cadres")]
    medicament = plan.get("medicament_fr") or plan.get("medicament_en")
    if ansm:
        st.subheader("🏛️ Cadre officiel ANSM")
        for a in ansm:
            lignes = "\n".join(f"- **{c['cadre']}** – {c['statut']}  \n  {c['indication']}" for c in a["cadres"])
            st.info(f"**[{a['titre']}]({a['url']})**\n\n{lignes}")
        st.caption("Cadres trouvés pour la substance : vérifier que l'indication correspond à la question.")
    elif medicament:
        st.caption(f"🏛️ Aucun cadre dérogatoire ANSM (CPC, AAC, AAP) trouvé pour « {medicament} » "
                   "(recherche par nom de substance sur ansm.sante.fr).")

    if not resultat["articles"]:
        st.info("Aucun article trouvé. Reformulez la question.")
    else:
        st.subheader("📝 Synthèse")
        st.markdown(synthese_html(resultat["synthese"], resultat["articles"]) or "_Le LLM n'a rien pu synthétiser._", unsafe_allow_html=True)
        st.caption("Synthèse générée à partir des résumés ci-dessous ; à vérifier dans les sources.")

        fiches = resultat.get("fiches", {})
        if fiches:
            st.subheader("📋 Détail par source")
            st.markdown(tableau_fiches_html(resultat["articles"], fiches), unsafe_allow_html=True)
            st.caption("Extrait par le LLM du résumé de chaque source ; « Non précisé dans le résumé » quand "
                       "l'information n'y figure pas. À vérifier dans la source.")
        st.subheader("📚 Sources")
    for i, a in enumerate(resultat["articles"], 1):
        cite = "✅ citée" if i in resultat["cites"] else "non citée"
        niveau = " · ".join(str(x) for x in (a.get("type"), a.get("annee")) if x)
        with st.expander(f"[S{i}] {a['titre'] or a['url']} · :orange[**{a['source']}**] · {niveau + ' · ' if niveau else ''}{cite}"):
            st.markdown(
                f'<span style="font-weight:700;text-decoration:underline;color:#f97316;">{escape(a["source"])}</span>'
                + (f" · {escape(a['journal'])}" if a.get("journal") else ""),
                unsafe_allow_html=True,
            )
            st.markdown(f"[{a['url']}]({a['url']})")
            fiche = resultat.get("fiches", {}).get(i)
            if fiche:
                st.markdown(
                    f"**Indication traitée** : {fiche['indication']}  \n"
                    f"**Posologie utilisée** : {fiche['posologie']}  \n"
                    f"**Résultat** : {fiche['resultat']}"
                )
            st.write(a["resume"] or "_Pas de résumé disponible._")
