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

import json

# -----------------------------
# GOOGLE AUTH
# -----------------------------
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # For localhost testing only

# Load from Streamlit Secrets
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
    st.write(f"[🔑 Login with Google]({auth_url})")

def callback():
    params = st.experimental_get_query_params()
    if "code" in params:
        full_url = f"{st.secrets['google']['redirect_uri']}?{urlencode(params, doseq=True)}"

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uris": [REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=SCOPES,
        )
        flow.redirect_uri = REDIRECT_URI

        try:
            flow.fetch_token(authorization_response=full_url)
            credentials = flow.credentials
            idinfo = id_token.verify_oauth2_token(credentials.id_token, requests.Request(), CLIENT_ID)
            st.session_state["credentials"] = idinfo

            # After successful login, clear query params so token exchange is not retried
            st.experimental_set_query_params()
            return True
        except Exception as e:
            st.error(f"Login failed: {e}")
            return False
    return False

def logout():
    st.session_state["credentials"] = None
    st.experimental_set_query_params()  # clear URL params so old code isn’t retried
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
    conn.commit()
    conn.close()

def add_expense(user_email, category, amount, payment_method, date, notes):
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO expenses (user_email, category, amount, payment_method, date, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_email, category, amount, payment_method, date, notes, created_at))
    conn.commit()
    conn.close()

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

# Google login
if st.session_state["credentials"] is None:
    if callback():
        st.success(f"✅ Welcome {st.session_state['credentials']['email']}")
    else:
        login()
        st.stop()

# Logged-in user email
user_email = st.session_state["credentials"]["email"]

# Logout button
st.sidebar.button("🚪 Logout", on_click=logout)

# Initialize DB
init_db()

# Sidebar Menu
menu = st.sidebar.radio("Menu", ["Home", "Add Expense", "View Expenses", "Reports"])

# -----------------------------
# Home
# -----------------------------
if menu == "Home":
    st.header(f"🏠 Welcome {user_email}")
    st.write("Track and visualize your expenses securely with Google login + SQLite.")

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
        add_expense(user_email, category, amount, payment_method, str(date), notes)
        st.success("✅ Expense added successfully!")

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

        # Delete option
        st.subheader("🗑️ Delete Expense")
        delete_id = st.number_input("Enter Expense ID to Delete", min_value=1, step=1)
        if st.button("Delete"):
            delete_expense(delete_id, user_email)
            st.warning(f"Deleted expense ID {delete_id}")
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
            fig2 = px.bar(time_summary, x="Date", y="Amount", title="Expenses Trend")
            st.plotly_chart(fig2, use_container_width=True)

            st.dataframe(filtered.drop(columns=["User Email"]), use_container_width=True)
        else:
            st.warning("No expenses in this time range.")
