import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests
import os
from urllib.parse import urlencode

# -----------------------------
# GOOGLE AUTH
# -----------------------------
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # ⚠️ Only for localhost! Remove in production

CLIENT_ID = st.secrets["google"]["client_id"]
CLIENT_SECRET = st.secrets["google"]["client_secret"]
REDIRECT_URI = st.secrets["google"]["redirect_uri"]

SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]

client_config = {
    "web": {
        "client_id": CLIENT_ID,
        "project_id": "streamlit-expense-tracker",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [REDIRECT_URI]
    }
}

if "credentials" not in st.session_state:
    st.session_state["credentials"] = None

def login():
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt="consent")

    st.markdown(
        f"""
        <style>
            body {{
                background: linear-gradient(135deg, #1f1c2c, #928dab);
                color: white;
                font-family: 'Segoe UI', sans-serif;
            }}
            .login-card {{
                max-width: 450px;
                margin: 100px auto;
                padding: 40px;
                border-radius: 15px;
                background: rgba(0,0,0,0.75);
                box-shadow: 0px 8px 20px rgba(0,0,0,0.5);
                text-align: center;
            }}
            .google-btn {{
                background-color: #4285F4;
                color: white !important;
                border: none;
                padding: 12px 25px;
                font-size: 18px;
                border-radius: 8px;
                cursor: pointer;
                display: inline-block;
                margin-top: 20px;
                text-decoration: none;
                transition: background 0.3s ease;
            }}
            .google-btn:hover {{
                background-color: #3367d6;
            }}
        </style>

        <div class="login-card">
            <h2>💰 Expense Tracker</h2>
            <p>Please login with Google to continue</p>
            <a class="google-btn" href="{auth_url}">🔑 Login with Google</a>
        </div>
        """,
        unsafe_allow_html=True
    )

def callback():
    params = st.query_params
    if "code" in params:
        full_url = f"{REDIRECT_URI}?{urlencode(params, doseq=True)}"
        flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)

        try:
            flow.fetch_token(authorization_response=full_url)
            credentials = flow.credentials

            # ✅ Save both token + user info
            st.session_state["id_token"] = credentials.id_token
            idinfo = id_token.verify_oauth2_token(credentials.id_token, requests.Request(), CLIENT_ID)
            st.session_state["credentials"] = idinfo

            st.query_params.clear()
            return True
        except Exception as e:
            st.error(f"Login failed: {e}")
            return False
    return False


def logout():
    st.session_state["credentials"] = None
    st.query_params.clear()
    st.rerun()

# -----------------------------
# DATABASE FUNCTIONS
# -----------------------------
def init_db():
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT,
                    category TEXT,
                    amount REAL,
                    payment_method TEXT,
                    date TEXT,
                    notes TEXT,
                    created_at TEXT
                )''')
    # ✅ Add index for faster queries
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_date ON expenses (user_email, date)")
    conn.commit()
    conn.close()

def add_expense(user_email, category, amount, payment_method, date, notes):
    if amount <= 0:
        return False
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO expenses (user_email, category, amount, payment_method, date, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_email, category, amount, payment_method, date, notes, created_at))
    conn.commit()
    conn.close()
    return True

def get_expenses(user_email, search=None):
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    if search:
        query = """SELECT * FROM expenses 
                   WHERE user_email=? 
                   AND (category LIKE ? OR payment_method LIKE ? OR notes LIKE ?)"""
        c.execute(query, (user_email, f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        c.execute("SELECT * FROM expenses WHERE user_email=?", (user_email,))
    rows = c.fetchall()
    conn.close()
    return rows

def delete_expense(expense_id, user_email):
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id=? AND user_email=?", (expense_id, user_email))
    conn.commit()
    conn.close()

# -----------------------------
# MAIN APP
# -----------------------------
st.set_page_config(page_title="Expense Tracker", layout="wide")
st.title("💰 Google Authenticated Expense Tracker")

# -----------------------------
# Google login (persistent)
# -----------------------------
if "credentials" not in st.session_state or st.session_state["credentials"] is None:
    if "id_token" in st.session_state:
        try:
            idinfo = id_token.verify_oauth2_token(st.session_state["id_token"], requests.Request(), CLIENT_ID)
            st.session_state["credentials"] = idinfo
        except Exception:
            login()
            st.stop()
    else:
        if callback():
            st.success(f"✅ Welcome {st.session_state['credentials']['email']}")
        else:
            login()
            st.stop()

user_email = st.session_state["credentials"]["email"]

# Sidebar
st.sidebar.button("🚪 Logout", on_click=logout)
menu = st.sidebar.radio("Menu", ["Home", "Add Expense", "View Expenses", "Reports"])

# Init DB
init_db()

# -----------------------------
# Home
# -----------------------------
if menu == "Home":
    st.header(f"🏠 Welcome {user_email}")
    rows = get_expenses(user_email)
    df = pd.DataFrame(rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])

    if not df.empty:
        total = df["Amount"].sum()
        this_month = df[pd.to_datetime(df["Date"]).dt.month == datetime.now().month]["Amount"].sum()
        top_category = df.groupby("Category")["Amount"].sum().idxmax()

        c1, c2, c3 = st.columns(3)
        c1.metric("💵 Total Spent", f"₹{total:,.2f}")
        c2.metric("📅 This Month", f"₹{this_month:,.2f}")
        c3.metric("🏆 Top Category", top_category)
    else:
        st.info("No expenses recorded yet. Start adding some!")

# -----------------------------
# Add Expense
# -----------------------------
elif menu == "Add Expense":
    st.header("➕ Add New Expense")

    col1, col2 = st.columns(2)
    with col1:
        category = st.selectbox("Category", ["Food", "Travel", "Entertainment", "Healthcare", "Shopping", "Bills", "Other"])
        amount = st.number_input("Amount", min_value=0.0, step=0.01)
        payment_method = st.selectbox("Payment Method", ["Cash", "Card", "UPI", "Other"])
    with col2:
        date = st.date_input("Date")
        notes = st.text_area("Notes")

    if st.button("Save Expense"):
        if add_expense(user_email, category, amount, payment_method, str(date), notes):
            st.success("✅ Expense added successfully!")
        else:
            st.error("❌ Amount must be greater than zero.")

# -----------------------------
# View Expenses
# -----------------------------
elif menu == "View Expenses":
    st.header("📋 Expense Index")

    search = st.text_input("Search:")
    rows = get_expenses(user_email, search)
    df = pd.DataFrame(rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])

    if not df.empty:
        st.dataframe(df.drop(columns=["User Email"]), use_container_width=True)

        # Export CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download CSV", csv, "expenses.csv", "text/csv")

        # Pie chart
        st.subheader("📊 Expenses by Category")
        category_summary = df.groupby("Category")["Amount"].sum().reset_index()
        fig = px.pie(category_summary, names="Category", values="Amount")
        st.plotly_chart(fig, use_container_width=True)

        # Delete option (better UX)
        st.subheader("🗑️ Delete Expense")
        delete_id = st.selectbox("Select Expense ID", df["ID"].tolist())
        if st.button("Delete"):
            delete_expense(delete_id, user_email)
            st.warning(f"Deleted expense ID {delete_id}")
            st.rerun()
    else:
        st.info("No expenses found.")

# -----------------------------
# Reports
# -----------------------------
elif menu == "Reports":
    st.header("📈 Expense Reports")

    rows = get_expenses(user_email)
    df = pd.DataFrame(rows, columns=["ID", "User Email", "Category", "Amount", "Payment Method", "Date", "Notes", "Created At"])

    if df.empty:
        st.info("No expenses to analyze.")
    else:
        df["Date"] = pd.to_datetime(df["Date"])

        report_type = st.radio("Report Type", ["Weekly", "Monthly", "Custom Range"])

        if report_type == "Weekly":
            start_date = datetime.now() - timedelta(days=7)
            filtered = df[df["Date"] >= start_date]

        elif report_type == "Monthly":
            start_date = datetime.now() - timedelta(days=30)
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
            top_category = filtered.groupby("Category")["Amount"].sum().idxmax()
            top_payment = filtered.groupby("Payment Method")["Amount"].sum().idxmax()

            c1, c2, c3 = st.columns(3)
            c1.metric("💵 Total Spent", f"₹{total:,.2f}")
            c2.metric("🏆 Top Category", top_category)
            c3.metric("💳 Most Used Payment", top_payment)

            st.subheader("📊 Expenses by Category")
            fig = px.pie(filtered, names="Category", values="Amount")
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("📅 Expenses Over Time")
            time_summary = filtered.groupby(filtered["Date"].dt.date)["Amount"].sum().reset_index()
            fig2 = px.line(time_summary, x="Date", y="Amount", title="Expenses Trend")  # ✅ Changed to line chart
            st.plotly_chart(fig2, use_container_width=True)

            st.dataframe(filtered.drop(columns=["User Email"]), use_container_width=True)
        else:
            st.warning("No expenses in this time range.")
