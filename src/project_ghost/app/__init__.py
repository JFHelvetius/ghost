"""Project Ghost — Streamlit web dashboard.

Install the app extra first::

    pip install 'project-ghost[app,telemetry]'

Then launch::

    ghost-app
    # or
    streamlit run src/project_ghost/app/main.py
"""

from __future__ import annotations


def run() -> None:
    """Entry point for the ``ghost-app`` console script."""
    import sys
    from pathlib import Path

    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(Path(__file__).parent / "main.py")]
    sys.exit(stcli.main())
