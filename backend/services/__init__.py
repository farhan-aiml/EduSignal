"""Backend services: business logic between the Streamlit views and the database.

Views call these functions; these functions enforce permissions, validate input, run related
writes in one transaction, and write an audit entry. They never trust a role or student id
coming from the page without checking it against the signed-in account.
"""
