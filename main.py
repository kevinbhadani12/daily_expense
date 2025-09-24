# save as app.py (replace your current file)
import streamlit as st
from streamlit.components.v1 import html
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests
import os
from urllib.parse import urlencode
from streamlit_cookies_manager import CookieManager

# -----------------------------
# CONFIG
# -----------------------------
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # ⚠️ Only for localhost! Remove in production
TOKEN_TTL_HOURS = 24  # login persistence lifetime: 24 hours (change if you really wanted 24 seconds)

# Initialize CookieManager and load cookies
cookies = CookieManager()
if not cookies.ready():
    st.stop()

# -----------------------------
# GOOGLE AUTH (from st.secrets)
# -----------------------------
CLIENT_ID = st.secrets["google"]["client_id"]
CLIENT_SECRET = st.secrets["google"]["client_secret"]
REDIRECT_URI = st.secrets["google"]["redirect_uri"]

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

client_config = {
    "web": {
        "client_id": CLIENT_ID,
        "project_id": "streamlit-expense-tracker",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [REDIRECT_URI],
    }
}

# session_state init
if "credentials" not in st.session_state:
    st.session_state["credentials"] = None

def build_flow():
    return Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )

def login():
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt="consent")

    st.markdown(
        f"""
        <div style="text-align:center; margin-top:50px;">
            <h2>Welcome to 💰 Expense Tracker</h2>
            <p>Please login with Google to continue</p>
            <a href="{auth_url}">
                <button style="
                    background-color: #4285F4;
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    font-size: 18px;
                    border-radius: 8px;
                    cursor: pointer;
                ">
                    🔑 Login with Google
                </button>
            </a>
        </div>
        """,
        unsafe_allow_html=True
    )

def callback():
    params = st.query_params.to_dict()
    if "code" in params:
        query_string = urlencode({k: v if isinstance(v, list) else [v] for k, v in params.items()}, doseq=True)
        full_url = f"{REDIRECT_URI}?{query_string}"
        flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)

        try:
            flow.fetch_token(authorization_response=full_url)
            credentials = flow.credentials
            st.session_state["id_token"] = credentials.id_token
            idinfo = id_token.verify_oauth2_token(credentials.id_token, requests.Request(), CLIENT_ID,clock_skew_in_seconds=10 )
            st.session_state["credentials"] = idinfo

            # Save cookie for 24h
            cookies["g_id_token"] = credentials.id_token
            cookies.save()

            st.query_params.clear()
            return True
        except Exception as e:
            st.error(f"Login failed: {e}")
            return False
    return False

def logout():
    st.session_state["credentials"] = None
    st.session_state.pop("id_token", None)
    cookies["g_id_token"] = ""   # Clear cookie
    cookies.save()
    st.query_params.clear()
    st.rerun()


# -----------------------------
# SESSION RESTORE (COOKIES)
# -----------------------------
if "credentials" not in st.session_state or st.session_state["credentials"] is None:
    token = cookies.get("g_id_token")
    if token:
        try:
            idinfo = id_token.verify_oauth2_token(token, requests.Request(), CLIENT_ID, clock_skew_in_seconds=10 )
            st.session_state["credentials"] = idinfo
            st.session_state["id_token"] = token
        except Exception:
            cookies["g_id_token"] = ""
            cookies.save()

    if "credentials" not in st.session_state or st.session_state["credentials"] is None:
        if callback():
            st.success(f"✅ Welcome {st.session_state['credentials']['email']}")
            st.rerun()
        else:
            login()
            st.stop()

# -----------------------------
# DATABASE HELPERS
# -----------------------------
DB_FILE = "expenses_new.db"

def get_conn():
    # checkout same_thread to avoid some streamlit threading issues
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT,
                category TEXT,
                amount REAL,
                payment_method TEXT,
                date TEXT,
                notes TEXT,
                created_at TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_user_date ON expenses (user_email, date)")
        conn.commit()

def add_expense(user_email, category, amount, payment_method, date, notes):
    if amount <= 0:
        return False
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO expenses (user_email, category, amount, payment_method, date, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_email, category, amount, payment_method, date, notes, created_at),
        )
        conn.commit()
    return True

def update_expense(expense_id, user_email, category, amount, payment_method, date, notes):
    if amount <= 0:
        return False
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """UPDATE expenses SET category=?, amount=?, payment_method=?, date=?, notes=?
               WHERE id=? AND user_email=?""",
            (category, amount, payment_method, date, notes, expense_id, user_email),
        )
        conn.commit()
        return c.rowcount > 0

def get_expenses(user_email, search=None, start_date=None, end_date=None):
    with get_conn() as conn:
        c = conn.cursor()
        query = "SELECT * FROM expenses WHERE user_email=?"
        params = [user_email]
        if search:
            query += " AND (category LIKE ? OR payment_method LIKE ? OR notes LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date DESC"
        c.execute(query, params)
        rows = c.fetchall()
    return rows

def delete_expense(expense_id, user_email):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM expenses WHERE id=? AND user_email=?", (expense_id, user_email))
        conn.commit()

# -----------------------------
# APP UI
# -----------------------------
st.set_page_config(page_title="Expense Tracker", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
      body, .stApp { background-color: #0f172a; color: #f1f5f9; }
      .sidebar .sidebar-content { background-color: #1e293b; }
      .stButton>button {
          background: linear-gradient(90deg, #6366f1, #3b82f6);
          color: white;
          font-weight:600;
          border-radius: 10px;
          padding: 0.6em 1.2em;
          border:none;
      }
      .stButton>button:hover {
          background: linear-gradient(90deg, #3b82f6, #2563eb);
      }
      .metric-card {
          background: #1e293b;
          padding: 18px;
          border-radius: 12px;
          box-shadow: 0 2px 6px rgba(0,0,0,0.6);
          color: white;
      }
      .block-container { padding-top: 1rem; padding-bottom: 1rem; }
      h1,h2,h3,h4 { color: #f8fafc; font-weight:700; }
      .stDataFrame { background: #1e293b; border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# If no session, try callback (if redirected), else show login
if st.session_state["credentials"] is None:
    if callback():
        # callback handles rerun on success
        pass
    else:
        login()
        st.stop()

# At this point we should have credentials
user_info = st.session_state["credentials"]
user_email = user_info.get("email")
user_picture = user_info.get("picture", None)
user_name = user_info.get("name", user_email)

# Sidebar
with st.sidebar:
    if user_picture:
        st.image(user_picture, width=64, caption=user_name)
    st.write(f"**{user_name}**")
    st.write(user_email)
    st.button("🚪 Logout", on_click=logout)
    menu = st.radio("Menu", ["Home", "Add Expense", "View & Edit Expenses", "Reports"])

# Ensure DB ready
init_db()

# -----------------------------
# HOME
# -----------------------------
if menu == "Home":
    st.title("🏠 Dashboard")
    rows = get_expenses(user_email)
    df = pd.DataFrame(rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])

    if not df.empty:
        # ensure Date column is datetime
        df["Date"] = pd.to_datetime(df["Date"])
        now = datetime.now()
        this_month = df[(df["Date"].dt.month == now.month) & (df["Date"].dt.year == now.year)]["Amount"].sum()
        total = df["Amount"].sum()
        top_category = df.groupby("Category")["Amount"].sum().idxmax() if not df.empty else "—"

        cols = st.columns(3)
        with cols[0]:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.metric("💵 Total Spent", f"₹{total:,.2f}")
            st.markdown('</div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.metric("📅 This Month", f"₹{this_month:,.2f}")
            st.markdown('</div>', unsafe_allow_html=True)
        with cols[2]:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.metric("🏆 Top Category", top_category)
            st.markdown('</div>', unsafe_allow_html=True)

        st.subheader("Recent Expenses")
        recent_df = df.sort_values("Date", ascending=False).head(6).drop(columns=["User Email", "Created At"])
        st.dataframe(recent_df, use_container_width=True)
    else:
        st.info("No expenses recorded yet. Start adding some!")

# -----------------------------
# ADD EXPENSE
# -----------------------------
elif menu == "Add Expense":
    st.title("➕ Add New Expense")
    col1, col2 = st.columns(2)
    with col1:
        category = st.selectbox("Category", ["Food", "Travel", "Entertainment", "Healthcare", "Shopping", "Bills", "Other"])
        amount = st.number_input("Amount (₹)", min_value=0.01, step=0.01, format="%.2f")
        payment_method = st.selectbox("Payment Method", ["Cash", "Card", "UPI", "Other"])
    with col2:
        date = st.date_input("Date", value=datetime.now().date())
        notes = st.text_area("Notes", height=120)

    if st.button("Save Expense"):
        if add_expense(user_email, category, float(amount), payment_method, str(date), notes):
            st.success("✅ Expense added successfully!")
            st.rerun()
        else:
            st.error("❌ Amount must be greater than zero.")

# -----------------------------
# VIEW & EDIT
# -----------------------------
elif menu == "View & Edit Expenses":
    st.title("📋 Expense List")

    # search + date filters
    col1, col2, col3 = st.columns([3, 1, 1])
    search = col1.text_input("Search by category, payment, or notes:")
    # For date inputs, provide sensible defaults (min/max in DB) to avoid None errors
    all_rows = get_expenses(user_email)
    all_df = pd.DataFrame(all_rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])
    all_df["Date"] = pd.to_datetime(all_df["Date"]) if not all_df.empty else pd.Series(dtype="datetime64[ns]")

    if not all_df.empty:
        min_date = all_df["Date"].min().date()
        max_date = all_df["Date"].max().date()
    else:
        min_date = datetime.now().date()
        max_date = datetime.now().date()

    start_date = col2.date_input("From Date", value=min_date)
    end_date = col3.date_input("To Date", value=max_date)

    start_str = str(start_date) if start_date else None
    end_str = str(end_date) if end_date else None

    rows = get_expenses(user_email, search, start_str, end_str)
    df = pd.DataFrame(rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])

    if not df.empty:
        st.dataframe(df.drop(columns=["User Email", "Created At"]), use_container_width=True, hide_index=True)

        # Export CSV
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download CSV", csv, "expenses.csv", "text/csv")

        # Pie chart
        st.subheader("📊 Expenses by Category")
        category_summary = df.groupby("Category")["Amount"].sum().reset_index()
        fig = px.pie(category_summary, names="Category", values="Amount", hole=0.3)
        st.plotly_chart(fig, use_container_width=True)

        # Edit option
        st.subheader("✏️ Edit Expense")
        edit_id = st.selectbox("Select Expense ID to Edit", df["ID"].tolist())
        if edit_id:
            expense = df[df["ID"] == edit_id].iloc[0]
            with st.form("edit_form"):
                category_options = ["Food", "Travel", "Entertainment", "Healthcare", "Shopping", "Bills", "Other"]
                try:
                    idx = category_options.index(expense["Category"])
                except Exception:
                    idx = 0
                edit_category = st.selectbox("Category", category_options, index=idx)
                edit_amount = st.number_input("Amount (₹)", min_value=0.01, step=0.01, value=float(expense["Amount"]))
                payment_options = ["Cash", "Card", "UPI", "Other"]
                try:
                    pidx = payment_options.index(expense["Payment Method"])
                except Exception:
                    pidx = 0
                edit_payment = st.selectbox("Payment Method", payment_options, index=pidx)
                edit_date = st.date_input("Date", value=pd.to_datetime(expense["Date"]).date())
                edit_notes = st.text_area("Notes", value=expense["Notes"])
                if st.form_submit_button("Update Expense"):
                    ok = update_expense(edit_id, user_email, edit_category, float(edit_amount), edit_payment, str(edit_date), edit_notes)
                    if ok:
                        st.success(f"✅ Expense ID {edit_id} updated!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to update. Check amount and permissions.")

        # Delete option
        st.subheader("🗑️ Delete Expense")
        delete_id = st.selectbox("Select Expense ID to Delete", df["ID"].tolist(), key="del_select")
        if st.button("Delete"):
            delete_expense(delete_id, user_email)
            st.warning(f"Deleted expense ID {delete_id}")
            st.rerun()
    else:
        st.info("No expenses found for the selected filters.")

# -----------------------------
# REPORTS
# -----------------------------
elif menu == "Reports":
    st.title("📈 Expense Reports")

    rows = get_expenses(user_email)
    df = pd.DataFrame(rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])

    if df.empty:
        st.info("No expenses to analyze.")
    else:
        df["Date"] = pd.to_datetime(df["Date"])
        report_type = st.radio("Report Type", ["Weekly", "Monthly", "Yearly", "Custom Range"])

        now = datetime.now()
        if report_type == "Weekly":
            start_date = now - timedelta(days=7)
            filtered = df[df["Date"] >= start_date]
        elif report_type == "Monthly":
            start_date = now.replace(day=1)
            filtered = df[df["Date"] >= start_date]
        elif report_type == "Yearly":
            start_date = now.replace(month=1, day=1)
            filtered = df[df["Date"] >= start_date]
        else:
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("Start Date", df["Date"].min().date())
            with col2:
                end_date = st.date_input("End Date", df["Date"].max().date())
            filtered = df[(df["Date"] >= pd.to_datetime(start_date)) & (df["Date"] <= pd.to_datetime(end_date))]

        if not filtered.empty:
            total = filtered["Amount"].sum()
            avg_daily = total / max(1, (filtered["Date"].max() - filtered["Date"].min()).days + 1)
            top_category = filtered.groupby("Category")["Amount"].sum().idxmax()
            top_payment = filtered.groupby("Payment Method")["Amount"].sum().idxmax()

            cols = st.columns(4)
            with cols[0]:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("💵 Total Spent", f"₹{total:,.2f}")
                st.markdown('</div>', unsafe_allow_html=True)
            with cols[1]:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("📅 Avg Daily", f"₹{avg_daily:,.2f}")
                st.markdown('</div>', unsafe_allow_html=True)
            with cols[2]:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("🏆 Top Category", top_category)
                st.markdown('</div>', unsafe_allow_html=True)
            with cols[3]:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("💳 Top Payment", top_payment)
                st.markdown('</div>', unsafe_allow_html=True)

            st.subheader("📊 Expenses by Category")
            fig = px.bar(filtered.groupby("Category")["Amount"].sum().reset_index(), x="Category", y="Amount")
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("📅 Expenses Over Time")
            time_summary = filtered.groupby(filtered["Date"].dt.date)["Amount"].sum().reset_index()
            time_summary.columns = ["Date", "Amount"]
            fig2 = px.line(time_summary, x="Date", y="Amount", title="Expenses Trend")
            st.plotly_chart(fig2, use_container_width=True)

            st.subheader("Detailed Expenses")
            st.dataframe(filtered.drop(columns=["User Email", "Created At"]), use_container_width=True)
        else:
            st.warning("No expenses in this time range.")
