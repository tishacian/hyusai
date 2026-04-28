import re

import httpx
import streamlit as st

from configurations import FrontendConfig
from src.standalone_interface.api_client import get_client

_auth = FrontendConfig.get().auth
_SKIP_AUTHENTICATION: bool = _auth.skip


def is_valid_email(email: str) -> bool:
    """Basic regex check for valid email."""
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w{2,}$"
    return re.match(pattern, email) is not None


def is_strong_password(password: str) -> bool:
    """Basic password strength checker."""
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    return True


def login_form():
    """Display the login form and handle authentication."""
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login"):
        rerun = False
        try:
            with get_client() as client:
                resp = client.post(
                    "/db/users/verify",
                    json={"email": email.lower(), "password": password},
                )
            if resp.is_success:
                user = resp.json()
                st.session_state["authentication_status"] = True
                st.session_state["username"] = user["email"]
                st.session_state["name"] = user["name"]
                rerun = True
            else:
                st.error("Username/password is incorrect")
        except httpx.HTTPError as e:
            st.error(f"Could not reach authentication service: {e}")
        if rerun:
            st.rerun()


def register_form():
    """Display the registration form and handle user creation."""
    st.subheader("Create an account")

    col1, col2 = st.columns(2)
    with col1:
        email = st.text_input("Email", key="register_email")
        password = st.text_input("Password", type="password", key="register_password")
    with col2:
        name = st.text_input("Full name", key="register_name")
        confirm_password = st.text_input(
            "Confirm password", type="password", key="register_confirm_password"
        )

    if st.button("Sign Up"):
        if not email or not name or not password:
            st.error("Please fill in all fields.")
        elif not is_valid_email(email):
            st.error("Please enter a valid email address.")
        elif not is_strong_password(password):
            st.error(
                "Password must be at least 8 characters long and "
                "include uppercase, lowercase, and a digit."
            )
        elif password != confirm_password:
            st.error("Passwords do not match.")
        else:
            try:
                with get_client() as client:
                    resp = client.post(
                        "/db/users",
                        json={
                            "email": email.lower(),
                            "password": password,
                            "name": name,
                        },
                    )
                if resp.status_code == 409:
                    st.warning("This email is already registered.")
                elif resp.is_success:
                    st.success("User registered successfully!")
                else:
                    st.error("Registration failed. Please try again.")
            except httpx.HTTPError as e:
                st.error(f"Could not reach registration service: {e}")


def reset_session_state(*args, **kwargs):
    """Reset session state."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def auth_component():
    """Display the authentication component."""
    if _SKIP_AUTHENTICATION:
        st.session_state["authentication_status"] = True
        st.session_state["username"] = "dev"
    elif st.session_state.get("authentication_status"):
        if st.sidebar.button("Logout"):
            reset_session_state()
            st.rerun()
    else:
        tab_login, tab_signup = st.tabs(["Login", "Sign Up"])
        with tab_login:
            login_form()
        with tab_signup:
            register_form()
