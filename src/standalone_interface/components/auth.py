import streamlit as st
import streamlit_authenticator as stauth

from configuration import get_standalone_interface_config
from src.db.users import Users


def get_usernames_from_db() -> dict:
    """Get usernames from the database for authentication."""
    users = Users.get_all()
    return {
        user.email: {
            "name": user.name,
            "email": user.email,
            "password": user.password_hash,
        }
        for user in users
    }


def get_authenticator() -> stauth.Authenticate:
    """Get the authenticator instance, initializing it if necessary."""
    credentials = st.session_state.get("credentials")
    if credentials is None:
        st.session_state["credentials"] = {"usernames": get_usernames_from_db()}
    else:
        st.session_state["credentials"]["usernames"] = get_usernames_from_db()
    auth = st.session_state.get("authenticator")
    if auth is None:
        st.session_state["authenticator"] = stauth.Authenticate(
            st.session_state["credentials"],
            get_standalone_interface_config().cookie_name,
            get_standalone_interface_config().cookie_key,
            get_standalone_interface_config().cookie_expiry_days,
        )
    return st.session_state["authenticator"]


def login_form():
    """Display the login form and handle authentication."""
    auth = get_authenticator()
    try:
        auth.login(fields={"Username": "Email"})
        if st.session_state.get("authentication_status") is False:
            st.error("Username/password is incorrect")
    except Exception as e:
        st.error(e)


def register_form():
    """Display the registration form and handle user creation."""
    st.subheader("Create an account")

    col1, col2 = st.columns(2)
    with col1:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
    with col2:
        name = st.text_input("Full name")
        confirm_password = st.text_input("Confirm password", type="password")

    if st.button("Sign Up"):
        if not email or not name or not password:
            st.error("Please fill in all fields.")
        elif password != confirm_password:
            st.error("Passwords do not match.")
        elif Users.get_by_email(email.lower()):
            st.warning("This email is already registered.")
        else:
            Users.add_user(
                email=email.lower(),
                password=password,
                name=name,
            )
            st.success("User registered successfully!")

def reset_session_state(*args, **kwargs):
    """Reset session state"""
    for key in st.session_state.keys():
        del st.session_state[key]

def auth_component():
    """Display the authentication component."""
    if st.session_state.get("authentication_status"):
        if "logout" not in st.session_state:
            st.session_state["logout"] = False
        auth = get_authenticator()
        auth.logout("Logout", "sidebar", callback=reset_session_state)
    else:
        tab_login, tab_signup = st.tabs(["Login", "Sign Up"])
        with tab_login:
            login_form()
        with tab_signup:
            register_form()
