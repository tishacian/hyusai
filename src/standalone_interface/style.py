import streamlit as st


def center_buttons():
    st.markdown(
        """
        <style>
        div.stButton > button:first-child {
            width: 100%;
            display: block;
            margin: 0 auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


HEADER_METRICS = """
                    <style>
                    .app-header {
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background-color: #f0f2f6;
                        padding: 10px;
                        border-radius: 10px;
                        margin-bottom: 20px;
                    }
                    .app-header img {
                        margin-right: 10px;
                        border-radius: 50%;
                        width: 50px;
                        height: 50px;
                    }
                    .app-header h1 {
                        color: #262730;
                        font-size: 2.5rem;
                        margin: 0;
                    }
                    .metrics-container {
                        background-color: transparent;
                        padding: 5px;
                        margin-top: 5px;
                        text-align: right;
                    }
                    .metric {
                        display: inline-block;
                        margin-left: 15px;
                        font-size: 12px;
                    }
                    .metric-name {
                        color: #888;
                    }
                    .metric-value {
                        font-weight: bold;
                        margin-left: 3px;
                    }
                    .red {
                        color: #ff4b4b;
                    }
                    .green {
                        color: #00c853;
                    }
                    n: 0 !important;
                    }
                    </style>
                    """
BUTTONS = """
                <style>
                .stButton > button {
                    border: none !important;
                    text-align: center !important;
                    font-size: 14px !important;
                    padding: 5px 10px !important;
                    width: 100% !important;
                    background-color: transparent !important;
                    color: white !important;
                    transition: background-color 0.3s ease !important;
                }
                
                .stButton > button:hover {
                    background-color: #f0f0f0 !important;
                    color: #262730 !important;
                }
                
                /* Chat history buttons */
                button[key^="chat_"] {
                    display: flex !important;
                    justify-content: space-between !important;
                    align-items: center !important;
                    width: 100% !important;
                    margin-bottom: 5px !important;
                    transition: background-color 0.3s ease !important;
                }
                
                button[key^="chat_"]:hover {
                    background-color: #f0f0f0 !important;
                }
                
                /* Delete button */
                button[key^="delete_"] {
                    background-color: transparent !important;
                    color: #ff4b4b !important;
                    padding: 0 !important;
                    font-size: 18px !important;
                    width: auto !important;
                    float: right !important;
                    transition: background-color 0.3s ease !important;
                }
                
                button[key^="delete_"]:hover {
                    background-color: #f0f0f0 !important;
                }
                
                /* Highlight for chat hover */
                button[key^="chat_"]:focus {
                    background-color: #e6f3ff !important;
                }
                
                /* Download styler */
                .stDownloadButton > button {
                    border: none !important;
                    text-align: center !important;
                    font-size: 12px !important;
                    padding: 5px !important;
                    width: 100% !important;
                    margin-bottom: 5px !important;
                    transition: background-color 0.3s ease !important;
                }
                
                .stDownloadButton > button:hover {
                    background-color: #f0f0f0 !important;
                }
                
                /* Auto-hide sidebar */
                [data-testid="stSidebar"] {
                    position: fixed !important;
                    left: -299px;
                    top: -10px;
                    height: 100vh;
                    width: 300px;
                    min-width: 300px;
                    max-width: 300px;
                    transition: left 0.3s ease-in-out;
                    z-index: 100; /* Ensure sidebar is above other elements */
                }

                /* Enable scrolling */
                [data-testid="stSidebar"] > div > div {
                    overflow-y: auto !important;
                    max-height: 100vh !important;
                }

                /* Sidebar hover effect for expansion */
                [data-testid="stSidebar"]:hover {
                    left: 0 !important;
                }
                
                /* Adjust main content when sidebar is hidden or shown */
                .main .block-container {
                    transition: padding-left 0.3s ease-in-out;
                }
                
                [data-testid="stSidebar"]:hover + .main .block-container {
                    padding-left: 380px;
                }
                </style>
                
                <script>
                // Use localStorage to persist the sidebar state (expanded/collapsed) across page reloads
                document.addEventListener('DOMContentLoaded', function () {
                    const sidebar = document.querySelector('[data-testid="stSidebar"]');
                    const mainContainer = document.querySelector('.main .block-container');
                    
                    // Check if the sidebar state is saved in localStorage
                    const isSidebarExpanded = localStorage.getItem('sidebarExpanded');
                
                    if (isSidebarExpanded === 'true') {
                        sidebar.style.left = '0';
                        mainContainer.style.paddingLeft = '320px';
                    } else {
                        sidebar.style.left = '-240px';
                        mainContainer.style.paddingLeft = '20px';
                    }
                
                    // Add hover event listener to expand the sidebar
                    sidebar.addEventListener('mouseenter', function () {
                        sidebar.style.left = '0';
                        mainContainer.style.paddingLeft = '320px';
                        localStorage.setItem('sidebarExpanded', 'true');  // Save expanded state
                    });
                
                    // Add event listener to collapse the sidebar on mouse leave
                    sidebar.addEventListener('mouseleave', function () {
                        sidebar.style.left = '-240px';
                        mainContainer.style.paddingLeft = '20px';
                        localStorage.setItem('sidebarExpanded', 'false');  // Save collapsed state
                    });
                });
                </script>
                    """

THINKING_SPINNER = """
                        <style>
                        .thinking-animation::after {
                            content: '';
                            animation: thinking 2s infinite;
                        }
                        
                        @keyframes thinking {
                            0% { content: 'Contextualizing.'; }
                            33% { content: 'Contextualizing..'; }
                            66% { content: 'Contextualizing...'; }
                            100% { content: 'Contextualizing.'; }
                        }
                        
                        .stSpinner > div {
                            visibility: hidden;
                        }
                        .stSpinner::before {
                            content: "▌";
                            display: block;
                            animation: cursor 1s infinite;
                            font-family: monospace;
                        }
                        @keyframes cursor {
                            0% { opacity: 0; }
                            50% { opacity: 1; }
                            100% { opacity: 0; }
                        }
                        </style>
                        """


PADDINGS = """
            <style>
            /* Force padding on main container */
            .stApp {
                max-width: calc(100% - 40rem) !important;
                margin-left: auto !important;
                margin-right: auto !important;
                padding-left: 20rem !important;
                padding-right: 20rem !important;
            }
            
            /* Adjust container width */
            [data-testid="stAppViewContainer"] > .main {
                max-width: 100% !important;
                padding-left: 20rem !important;
                padding-right: 20rem !important;
            }
            
            /* Ensure content respects padding */
            [data-testid="stAppViewContainer"] {
                max-width: 100% !important;
            }
            
            [data-testid="stHeader"] {
                max-width: calc(100% - 40rem) !important;
                margin-left: auto !important;
                margin-right: auto !important;
            }
            
            /* Responsive adjustments */
            @media (max-width: 1600px) {
                .stApp,
                [data-testid="stAppViewContainer"] > .main,
                [data-testid="stHeader"] {
                    max-width: calc(100% - 20rem) !important;
                    padding-left: 10rem !important;
                    padding-right: 10rem !important;
                }
            }
            
            @media (max-width: 1200px) {
                .stApp,
                [data-testid="stAppViewContainer"] > .main,
                [data-testid="stHeader"] {
                    max-width: calc(100% - 10rem) !important;
                    padding-left: 5rem !important;
                    padding-right: 5rem !important;
                }
            }
            
            @media (max-width: 768px) {
                .stApp,
                [data-testid="stAppViewContainer"] > .main,
                [data-testid="stHeader"] {
                    max-width: calc(100% - 2rem) !important;
                    padding-left: 1rem !important;
                    padding-right: 1rem !important;
                }
            }
            
            /* Keep existing styles */
            .app-header {
                display: flex;
                align-items: center;
                justify-content: center;
                background-color: #f0f2f6;
                padding: 10px;
                border-radius: 10px;
                margin-bottom: 20px;
            }
            """

FILE_UPLOADER = """
                    <style>
                    [data-testid="stFileUploader"] {
                        width: 100%;
                    }
                    
                    [data-testid="stFileUploader"] section {
                        padding: 30px;
                        display: flex;
                        flex-direction: column;
                        justify-content: center;
                        align-items: center;
                        min-height: 170px !important;
                        border: 1px dashed #4e8cff !important;
                        border-radius: 10px !important;
                        background-color: rgba(78, 140, 255, 0.05) !important;
                    }
                    
                    [data-testid="stFileUploader"] section input {
                        height: 100%;
                    }
                    
                    [data-testid="stFileUploader"] section div[data-testid="stMarkdownContainer"] p {
                        font-size: 1.2em;
                        font-weight: bold;
                    }
                    
                    [data-testid="stFileUploader"] section button {
                        display: none;
                    }
                    
                    / Hide the default text and replace with custom text /
                    [data-testid="stFileUploader"] section div.css-1v0mbdj.e115fcil1 > p {
                    font-size: 1.2em;
                    font-weight: bold;
                    }
                    [data-testid="stFileUploader"] section div.css-1v0mbdj.e115fcil1 > p::before {
                    content: "Drag and drop document collections here";
                    display: block;
                    }
                    [data-testid="stFileUploader"] section div.css-1v0mbdj.e115fcil1 > p span {
                    display: none;
                    }

                    </style>
                    """

BACKGROUND = f"""
                <style>
                [data-testid="stAppViewContainer"] > .main {{
                background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(0, 91, 140, 0.9), rgba(0, 120, 174, 0.8), rgba(30, 144, 195, 0.7));
                background-size: cover;
                background-position: center center;
                background-repeat: no-repeat;
                background-attachment: fixed;
                }}
                [data-testid="stHeader"] {{
                background: rgba(0,0,0,0);
                }}
                [data-testid="stBottomBlockContainer"] {{
                background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(0, 91, 140, 0.9), rgba(0, 120, 174, 0.8), rgba(30, 144, 195, 0.7));
                background-size: cover;
                background-position: center center;
                background-repeat: no-repeat;
                background-attachment: fixed;
                }}
                [data-testid="stSidebarContent"] {{
                background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(0, 91, 140, 0.9), rgba(0, 120, 174, 0.8), rgba(30, 144, 195, 0.7));
                background-size: cover;
                background-position: center center;
                background-repeat: no-repeat;
                background-attachment: fixed;
                }}
                </style>
                """

SELECT_INPUT_STYLE = """
                    <style>
                    div[data-baseweb="select"] {
                        background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(87, 91, 140, 0.9));
                        border-radius: 5px;
                    }
                    div[data-baseweb="select"] {
                        background-image: linear-gradient(to left, rgba(0, 48, 87, 0.9), rgba(87, 91, 140, 0.9));
                        border-radius: 5px;
                    }
                    div[data-baseweb="select"] > div {
                        background: transparent !important;
                        border: none !important;
                    }
                    div[data-baseweb="select"] input {
                        color: white !important;
                    }
                    div[data-baseweb="select"] div[data-testid="stMarkdown"] p {
                        color: white !important;
                    }
                    div[role="listbox"] {
                        background-image: linear-gradient(to right, rgba(0, 48, 87, 0.95), rgba(0, 91, 140, 0.95)) !important;
                    }
                    div[role="listbox"] {
                        background-image: linear-gradient(to left, rgba(0, 48, 87, 0.95), rgba(0, 91, 140, 0.95)) !important;
                    }
                    div[role="listbox"] div[role="option"] {
                        color: white !important;
                    }
                    div[role="listbox"] div[role="option"]:hover {
                        background-color: rgba(30, 144, 195, 0.7) !important;
                    }
                    div[data-baseweb="input"] {
                        background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(0, 91, 140, 0.9));
                        border-radius: 5px;
                    }
                    div[data-baseweb="input"] {
                        background-image: linear-gradient(to left, rgba(0, 48, 87, 0.9), rgba(0, 91, 140, 0.9));
                        border-radius: 5px;
                    }
                    div[data-baseweb="input"] > div {
                        background: transparent !important;
                        border: none !important; 
                    }
                    div[data-baseweb="input"] input {
                        color: white !important;
                    }
                    label[data-testid="stText"] {
                        color: white !important;
                    }
                    div[data-baseweb="select"] svg {
                        color: white !important;
                    }
                    div[data-baseweb="input"] input::placeholder,
                    div[data-baseweb="select"] input::placeholder {
                        color: rgba(255, 255, 255, 0.7) !important;
                    }
                    div[data-baseweb="select"]:focus-within,
                    div[data-baseweb="input"]:focus-within {
                        box-shadow: 0 0 5px rgba(30, 144, 195, 0.8) !important;
                    }
                    div[data-baseweb="menu"] li,
                    ul[role="listbox"] li,
                    div[role="listbox"] li,
                    [data-testid="stSelectbox"] ul li,
                    ul[data-baseweb="menu"],
                    div[data-baseweb="menu"] div,
                    div[data-baseweb="popover"] li {
                        background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(87, 91, 140, 0.9)) !important;
                        border-bottom: 1px solid rgba(100, 120, 180, 0.1) !important;
                        color: white !important;
                    }
                    div[data-baseweb="menu"] li:hover,
                    ul[role="listbox"] li:hover,
                    div[role="listbox"] li:hover,
                    div[role="option"]:hover,
                    [data-testid="stSelectbox"] ul li:hover,
                    div[data-baseweb="menu"] div:hover {
                        background-image: none !important;
                        background-color: white !important;
                        color: rgba(0, 48, 87, 1) !important;
                    }
                    div[data-baseweb="menu"] {
                        background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(87, 91, 140, 0.9)) !important;
                    }
                    div[data-baseweb="popover"] div {
                        background-image: linear-gradient(to right, rgba(0, 48, 87, 0.9), rgba(87, 91, 140, 0.9)) !important;
                    }
                    </style>
                    """
