"""EduSignal launcher.

Run from the project root:  streamlit run app.py

    frontend/  Streamlit UI (main.py, views/, assets/)
    backend/   config, database, services, ML pipeline, data and models
"""
from frontend.main import main

main()
