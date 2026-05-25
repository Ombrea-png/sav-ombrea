"""
SAV Ombréa® — Outil de suivi des dossiers SAV
Application Streamlit autonome avec SQLite local.
"""

import sqlite3
import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Optional

# ── Configuration ────────────────────────────────────────────────────────────
DB_PATH = "sav.db"

STATUTS = ["Nouveau", "En cours", "En attente client", "En attente fournisseur", "Résolu", "Fermé"]
PRIORITES = ["Basse", "Normale", "Haute", "Urgente"]
NOTE_TYPES = ["Appel", "Courriel", "SMS", "Suivi technique", "Décision", "À rappeler", "Autre"]

st.set_page_config(
    page_title="SAV Ombréa®",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Base de données ──────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dossiers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            id_sav          TEXT UNIQUE NOT NULL,
            nom_client      TEXT NOT NULL,
            telephone       TEXT,
            courriel        TEXT,
            priorite        TEXT DEFAULT 'Normale',
            statut          TEXT DEFAULT 'Nouveau',
            probleme        TEXT,
            pieces          TEXT,
            cause           TEXT,
            actions         TEXT,
            prochaine_etape TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            note_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            dossier_id      INTEGER NOT NULL,
            created_at      TEXT NOT NULL,
            type_note       TEXT NOT NULL,
            texte           TEXT NOT NULL,
            statut_apres    TEXT,
            prochaine_action TEXT,
            date_relance    TEXT,
            priorite        TEXT DEFAULT 'Normale',
            auteur          TEXT DEFAULT 'Antoine',
            FOREIGN KEY (dossier_id) REFERENCES dossiers(id)
        )
    """)
    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def gen_id_sav():
    """Génère un ID automatique type SAV-2026-001."""
    year = datetime.now().year
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM dossiers WHERE id_sav LIKE ?", (f"SAV-{year}-%",)
    ).fetchone()
    conn.close()
    n = row["n"] + 1
    return f"SAV-{year}-{n:03d}"


# ── Dossiers ─────────────────────────────────────────────────────────────────

def create_dossier(data: dict) -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO dossiers (id_sav, nom_client, telephone, courriel, priorite, statut,
            probleme, pieces, cause, actions, prochaine_etape, notes, created_at, updated_at)
        VALUES (:id_sav, :nom_client, :telephone, :courriel, :priorite, :statut,
            :probleme, :pieces, :cause, :actions, :prochaine_etape, :notes, :created_at, :updated_at)
    """, {**data, "created_at": now, "updated_at": now})
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_dossier(dossier_id: int, data: dict):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    conn.execute("""
        UPDATE dossiers SET
            nom_client=:nom_client, telephone=:telephone, courriel=:courriel,
            priorite=:priorite, statut=:statut, probleme=:probleme,
            pieces=:pieces, cause=:cause, actions=:actions,
            prochaine_etape=:prochaine_etape, notes=:notes, updated_at=:updated_at
        WHERE id=:id
    """, {**data, "id": dossier_id, "updated_at": now})
    conn.commit()
    conn.close()


def get_all_dossiers() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT d.*,
            j.texte AS derniere_note,
            j.created_at AS date_note,
            j.date_relance,
            j.prochaine_action
        FROM dossiers d
        LEFT JOIN (
            SELECT dossier_id, texte, created_at, date_relance, prochaine_action,
                   ROW_NUMBER() OVER (PARTITION BY dossier_id ORDER BY created_at DESC) rn
            FROM journal
        ) j ON d.id = j.dossier_id AND j.rn = 1
        ORDER BY
            CASE d.priorite
                WHEN 'Urgente' THEN 1
                WHEN 'Haute'   THEN 2
                WHEN 'Normale' THEN 3
                WHEN 'Basse'   THEN 4
            END,
            d.updated_at DESC
    """, conn)
    conn.close()
    return df


def get_dossier(dossier_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM dossiers WHERE id=?", (dossier_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_dossier(dossier_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM journal WHERE dossier_id=?", (dossier_id,))
    conn.execute("DELETE FROM dossiers WHERE id=?", (dossier_id,))
    conn.commit()
    conn.close()


# ── Journal ──────────────────────────────────────────────────────────────────

def add_note(data: dict) -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO journal (dossier_id, created_at, type_note, texte,
            statut_apres, prochaine_action, date_relance, priorite, auteur)
        VALUES (:dossier_id, :created_at, :type_note, :texte,
            :statut_apres, :prochaine_action, :date_relance, :priorite, :auteur)
    """, {**data, "created_at": now})
    # Mettre à jour le statut du dossier si changé
    if data.get("statut_apres"):
        conn.execute(
            "UPDATE dossiers SET statut=?, updated_at=? WHERE id=?",
            (data["statut_apres"], now, data["dossier_id"])
        )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_journal(dossier_id: int) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM journal WHERE dossier_id=? ORDER BY created_at DESC",
        conn, params=(dossier_id,)
    )
    conn.close()
    return df


def get_relances_du_jour() -> pd.DataFrame:
    today = date.today().isoformat()
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT j.*, d.id_sav, d.nom_client, d.produit, d.statut
        FROM journal j
        JOIN dossiers d ON j.dossier_id = d.id
        WHERE j.date_relance <= ? AND j.date_relance != ''
          AND d.statut NOT IN ('Résolu', 'Fermé')
        ORDER BY j.date_relance ASC
    """, conn, params=(today,))
    conn.close()
    return df


# ── UI ───────────────────────────────────────────────────────────────────────

def badge_priorite(p: str) -> str:
    colors = {"Urgente": "🔴", "Haute": "🟠", "Normale": "🟡", "Basse": "🟢"}
    return f"{colors.get(p, '')} {p}"


def badge_statut(s: str) -> str:
    colors = {
        "Nouveau": "🆕", "En cours": "🔄",
        "En attente client": "⏳", "En attente fournisseur": "📦",
        "Résolu": "✅", "Fermé": "🔒"
    }
    return f"{colors.get(s, '')} {s}"


def render_tableau(df: pd.DataFrame) -> Optional[int]:
    """Affiche le tableau des dossiers. Retourne l'id sélectionné."""
    if df.empty:
        st.info("Aucun dossier trouvé.")
        return None

    cols_display = {
        "id_sav": "N° SAV",
        "nom_client": "Client",
        "telephone": "Téléphone",
        "priorite": "Priorité",
        "statut": "Statut",
        "prochaine_etape": "Prochaine étape",
        "date_relance": "Relance",
        "derniere_note": "Dernière note",
    }
    today = date.today().isoformat()

    df_show = df[[c for c in cols_display if c in df.columns]].copy()
    df_show = df_show.rename(columns=cols_display)
    df_show = df_show.fillna("")

    selected = st.dataframe(
        df_show,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    if selected and selected.selection.rows:
        idx = selected.selection.rows[0]
        return int(df.iloc[idx]["id"])

    return None


def render_kanban(df: pd.DataFrame):
    """Vue Kanban par statut avec boutons de changement de statut."""
    actifs = [s for s in STATUTS if s not in ("Résolu", "Fermé")]
    cols = st.columns(len(actifs))

    for i, statut in enumerate(actifs):
        subset = df[df["statut"] == statut]
        with cols[i]:
            st.markdown(f"**{badge_statut(statut)}** ({len(subset)})")
            st.divider()
            for _, row in subset.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['id_sav']}** — {row['nom_client']}")
                    st.markdown(badge_priorite(row["priorite"]))
                    if row.get("prochaine_etape"):
                        st.caption(str(row["prochaine_etape"])[:60])

                    # Boutons statut suivant / précédent
                    idx_actuel = STATUTS.index(statut)
                    b1, b2 = st.columns(2)
                    if idx_actuel > 0:
                        precedent = STATUTS[idx_actuel - 1]
                        if b1.button(f"← {precedent[:8]}", key=f"prev_{row['id']}"):
                            now = datetime.utcnow().isoformat()
                            conn = get_conn()
                            conn.execute("UPDATE dossiers SET statut=?, updated_at=? WHERE id=?",
                                         (precedent, now, int(row["id"])))
                            conn.commit()
                            conn.close()
                            st.rerun()
                    if idx_actuel < len(STATUTS) - 1:
                        suivant = STATUTS[idx_actuel + 1]
                        if b2.button(f"{suivant[:8]} →", key=f"next_{row['id']}"):
                            now = datetime.utcnow().isoformat()
                            conn = get_conn()
                            conn.execute("UPDATE dossiers SET statut=?, updated_at=? WHERE id=?",
                                         (suivant, now, int(row["id"])))
                            conn.commit()
                            conn.close()
                            st.rerun()


def render_fiche(dossier: dict):
    """Affiche la fiche complète d'un dossier."""
    st.subheader(f"{dossier['id_sav']} — {dossier['nom_client']}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**Téléphone** : {dossier.get('telephone') or '—'}")
        st.markdown(f"**Courriel** : {dossier.get('courriel') or '—'}")
    with col2:
        st.markdown(f"**Priorité** : {badge_priorite(dossier.get('priorite', ''))}")
        st.markdown(f"**Statut** : {badge_statut(dossier.get('statut', ''))}")
    with col3:
        st.markdown(f"**Créé le** : {dossier.get('created_at', '')[:10]}")
        st.markdown(f"**Mis à jour** : {dossier.get('updated_at', '')[:10]}")

    if dossier.get("probleme"):
        st.markdown(f"**Problème** : {dossier['probleme']}")
    if dossier.get("pieces"):
        st.markdown(f"**Pièces concernées** : {dossier['pieces']}")
    if dossier.get("cause"):
        st.markdown(f"**Cause probable** : {dossier['cause']}")
    if dossier.get("actions"):
        st.markdown(f"**Actions** : {dossier['actions']}")
    if dossier.get("prochaine_etape"):
        st.markdown(f"**Prochaine étape** : {dossier['prochaine_etape']}")
    if dossier.get("notes"):
        st.markdown(f"**Notes** : {dossier['notes']}")


def render_journal(dossier_id: int):
    df = get_journal(dossier_id)
    if df.empty:
        st.info("Aucune note pour ce dossier.")
        return
    st.markdown(f"**{len(df)} note(s)**")
    today = date.today().isoformat()
    for _, note in df.iterrows():
        created = str(note.get("created_at", ""))[:16].replace("T", " ")
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.markdown(f"**{created}**")
            c2.markdown(f"Type : **{note.get('type_note', '')}**")
            c3.markdown(f"Statut : **{note.get('statut_apres', '')}**")
            c4.markdown(f"Par : {note.get('auteur', 'Antoine')}")
            st.markdown(note.get("texte", ""))
            if note.get("prochaine_action"):
                st.markdown(f"Action : *{note['prochaine_action']}*")
            if note.get("date_relance"):
                relance = str(note["date_relance"])
                late = relance <= today
                st.markdown(
                    f"{'🔴' if late else '📅'} {'**Relance en retard**' if late else 'Relance'} : {relance}"
                )


def render_form_note(dossier_id: int):
    st.subheader("Ajouter une note")
    with st.form(key=f"note_{dossier_id}"):
        col1, col2 = st.columns(2)
        with col1:
            type_note = st.selectbox("Type", NOTE_TYPES)
            priorite = st.selectbox("Priorité", ["Faible", "Normale", "Urgente"], index=1)
            statut_apres = st.selectbox("Nouveau statut", ["(inchangé)"] + STATUTS)
        with col2:
            date_relance = st.date_input("Date de relance", value=None)
            auteur = st.text_input("Par", value="Antoine")
        texte = st.text_area("Note *", height=150)
        prochaine_action = st.text_input("Prochaine action")
        submitted = st.form_submit_button("Enregistrer", type="primary")

        if submitted:
            if not texte.strip():
                st.error("La note ne peut pas être vide.")
                return
            add_note({
                "dossier_id":       dossier_id,
                "type_note":        type_note,
                "texte":            texte.strip(),
                "statut_apres":     statut_apres if statut_apres != "(inchangé)" else "",
                "prochaine_action": prochaine_action.strip(),
                "date_relance":     date_relance.isoformat() if date_relance else "",
                "priorite":         priorite,
                "auteur":           auteur.strip() or "Antoine",
            })
            st.success("Note enregistrée.")
            st.rerun()


def render_form_dossier(existing: Optional[dict] = None):
    """Formulaire création / édition d'un dossier."""
    is_edit = existing is not None
    titre = "Modifier le dossier" if is_edit else "Nouveau dossier"
    st.subheader(titre)

    with st.form(key=f"dossier_{'edit' if is_edit else 'new'}"):
        col1, col2 = st.columns(2)
        with col1:
            nom_client = st.text_input("Nom client *", value=existing.get("nom_client", "") if is_edit else "")
            telephone = st.text_input("Téléphone", value=existing.get("telephone", "") if is_edit else "")
            courriel = st.text_input("Courriel", value=existing.get("courriel", "") if is_edit else "")
        with col2:
            priorite = st.selectbox("Priorité", PRIORITES,
                index=PRIORITES.index(existing["priorite"]) if is_edit and existing.get("priorite") in PRIORITES else 1)
            statut = st.selectbox("Statut", STATUTS,
                index=STATUTS.index(existing["statut"]) if is_edit and existing.get("statut") in STATUTS else 0)

        probleme = st.text_area("Problème", value=existing.get("probleme", "") if is_edit else "", height=100)
        col3, col4 = st.columns(2)
        with col3:
            pieces = st.text_input("Pièces concernées", value=existing.get("pieces", "") if is_edit else "")
            cause = st.text_input("Cause probable", value=existing.get("cause", "") if is_edit else "")
        with col4:
            actions = st.text_input("Actions", value=existing.get("actions", "") if is_edit else "")
            prochaine_etape = st.text_input("Prochaine étape", value=existing.get("prochaine_etape", "") if is_edit else "")
        notes = st.text_area("Notes / tâches", value=existing.get("notes", "") if is_edit else "", height=80)

        submitted = st.form_submit_button("Enregistrer le dossier", type="primary")

        if submitted:
            if not nom_client.strip():
                st.error("Le nom du client est obligatoire.")
                return

            data = {
                "nom_client": nom_client.strip(),
                "telephone":  telephone.strip(),
                "courriel":   courriel.strip(),
                "priorite":   priorite,
                "statut":     statut,
                "probleme":   probleme.strip(),
                "pieces":     pieces.strip(),
                "cause":      cause.strip(),
                "actions":    actions.strip(),
                "prochaine_etape": prochaine_etape.strip(),
                "notes":      notes.strip(),
            }

            if is_edit:
                update_dossier(existing["id"], data)
                st.success("Dossier mis à jour.")
            else:
                data["id_sav"] = gen_id_sav()
                create_dossier(data)
                st.success(f"Dossier {data['id_sav']} créé.")

            st.rerun()


# ── App principale ───────────────────────────────────────────────────────────

init_db()

# Sidebar
st.sidebar.title("SAV Ombréa®")
vue = st.sidebar.radio("Vue", ["Tableau", "Kanban", "Relances du jour"])
st.sidebar.divider()

if "show_new" not in st.session_state:
    st.session_state.show_new = False
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False

if st.sidebar.button("+ Nouveau dossier", type="primary"):
    st.session_state.show_new = True
    st.session_state.selected_id = None
    st.session_state.edit_mode = False

# Filtres sidebar
st.sidebar.subheader("Filtres")
search = st.sidebar.text_input("Recherche (client, ID...)")
filtre_statut = st.sidebar.selectbox("Statut", ["Tous"] + STATUTS)
filtre_priorite = st.sidebar.selectbox("Priorité", ["Tous"] + PRIORITES)

# Titre
st.title("🔧 SAV Ombréa®")

# Formulaire nouveau dossier
if st.session_state.show_new:
    render_form_dossier()
    if st.button("Annuler"):
        st.session_state.show_new = False
        st.rerun()
    st.stop()

# Charger les dossiers
df = get_all_dossiers()

# Appliquer filtres
if search.strip():
    mask = pd.Series(False, index=df.index)
    for col in ["nom_client", "id_sav", "telephone", "courriel", "probleme"]:
        if col in df.columns:
            mask |= df[col].astype(str).str.contains(search, case=False, na=False)
    df = df[mask]

if filtre_statut != "Tous":
    df = df[df["statut"] == filtre_statut]
if filtre_priorite != "Tous":
    df = df[df["priorite"] == filtre_priorite]

# Statistiques rapides
col_stats = st.columns(5)
df_all = get_all_dossiers()
col_stats[0].metric("Total", len(df_all))
col_stats[1].metric("Urgents", len(df_all[df_all["priorite"] == "Urgente"]))
col_stats[2].metric("En cours", len(df_all[df_all["statut"] == "En cours"]))
col_stats[3].metric("En attente", len(df_all[df_all["statut"].str.startswith("En attente", na=False)]))
today_str = date.today().isoformat()
relances = df_all[df_all["date_relance"].notna() & (df_all["date_relance"] <= today_str) & (~df_all["statut"].isin(["Résolu", "Fermé"]))]
col_stats[4].metric("Relances dues", len(relances))

st.divider()

# Vue principale
if vue == "Tableau":
    st.markdown(f"**{len(df)} dossier(s)**")
    selected_id = render_tableau(df)
    if selected_id:
        st.session_state.selected_id = selected_id
        st.session_state.edit_mode = False

elif vue == "Kanban":
    render_kanban(df_all)
    st.stop()

elif vue == "Relances du jour":
    st.subheader(f"Relances du jour — {date.today().strftime('%d/%m/%Y')}")
    df_rel = df_all[
        df_all["date_relance"].notna() &
        (df_all["date_relance"] <= today_str) &
        (~df_all["statut"].isin(["Résolu", "Fermé"]))
    ].copy()
    if df_rel.empty:
        st.success("Aucune relance pour aujourd'hui.")
    else:
        selected_id = render_tableau(df_rel)
        if selected_id:
            st.session_state.selected_id = selected_id

# Fiche dossier sélectionné
if st.session_state.selected_id:
    dossier = get_dossier(st.session_state.selected_id)
    if dossier:
        st.divider()

        # Boutons actions
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 6])
        with btn_col1:
            if st.button("Modifier"):
                st.session_state.edit_mode = True
        with btn_col2:
            if st.button("Supprimer", type="secondary"):
                delete_dossier(st.session_state.selected_id)
                st.session_state.selected_id = None
                st.session_state.edit_mode = False
                st.rerun()

        if st.session_state.edit_mode:
            render_form_dossier(existing=dossier)
            if st.button("Annuler la modification"):
                st.session_state.edit_mode = False
                st.rerun()
        else:
            render_fiche(dossier)
            st.divider()
            tab_journal, tab_note = st.tabs(["Journal des notes", "Ajouter une note"])
            with tab_journal:
                render_journal(dossier["id"])
            with tab_note:
                render_form_note(dossier["id"])