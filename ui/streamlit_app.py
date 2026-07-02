"""Streamlit chat UI for the Mutual Fund FAQ Assistant (Phase 4).

Run:
    streamlit run ui/streamlit_app.py

Calls ``process_chat()`` directly (no separate API process required).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file from ui/; add project root so ``src`` imports work.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from src.api.chat_service import process_chat
from src.ingest.fetcher import load_scheme_urls
from src.rag.generator import DISCLAIMER

PAGE_TITLE = "Mutual Fund FAQ Assistant"
WELCOME_TEXT = (
    "Welcome! I answer factual questions about five HDFC mutual fund schemes "
    "published on Groww. Ask about expense ratios, exit loads, minimum SIP, "
    "tax, holdings, and other facts from the official scheme pages."
)

EXAMPLE_QUESTIONS: list[tuple[str, str]] = [
    (
        "Min SIP Large Cap",
        "What is the minimum SIP for HDFC Large Cap Fund?",
    ),
    (
        "Exit load Small Cap",
        "What is the exit load on HDFC Small Cap Fund?",
    ),
    (
        "Benchmark Mid Cap",
        "What is the benchmark for HDFC Mid Cap Fund?",
    ),
]

ERROR_MESSAGE = (
    "Sorry, something went wrong while processing your question. "
    "Please try again."
)


def _source_label(url: str) -> str:
    if "groww.in" in url:
        return "View on Groww"
    if "amfiindia.com" in url:
        return "AMFI investor education"
    return "Learn more"


def _init_session() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []


def _run_query(question: str) -> None:
    """Append a user question and the assistant response to session history."""
    st.session_state.messages.append({"role": "user", "content": question})
    try:
        response = process_chat(question)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response.answer,
                "source_url": response.source_url,
                "last_updated": response.last_updated,
                "refused": response.refused,
            }
        )
    except Exception:
        st.session_state.messages.append(
            {"role": "assistant", "content": ERROR_MESSAGE, "error": True}
        )


def _render_assistant_message(msg: dict) -> None:
    if msg.get("error"):
        st.error(msg["content"])
        return

    if msg.get("refused"):
        st.markdown(
            f'<div class="refused-msg">{msg["content"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.write(msg["content"])

    if msg.get("source_url"):
        st.link_button(_source_label(msg["source_url"]), msg["source_url"])
    if msg.get("last_updated"):
        st.caption(f"Last updated from sources: {msg['last_updated']}")


def main() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon="📊",
        layout="centered",
    )

    st.markdown(
        """
        <style>
        .disclaimer-banner {
            background: #0b6e4f;
            color: #fff;
            padding: 0.6rem 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            font-size: 0.9rem;
        }
        .refused-msg {
            background: #fff8e6;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            border-left: 4px solid #e6c200;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _init_session()

    st.title(PAGE_TITLE)
    st.markdown(
        f'<div class="disclaimer-banner">{DISCLAIMER}</div>',
        unsafe_allow_html=True,
    )

    with st.expander("About this assistant", expanded=not st.session_state.messages):
        st.markdown(WELCOME_TEXT)
        st.subheader("Supported schemes")
        for entry in load_scheme_urls():
            st.markdown(f"**{entry.scheme}**  \n{entry.category}")

    st.subheader("Try an example")
    cols = st.columns(len(EXAMPLE_QUESTIONS))
    for col, (label, question) in zip(cols, EXAMPLE_QUESTIONS, strict=True):
        if col.button(label, use_container_width=True):
            _run_query(question)
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            else:
                _render_assistant_message(msg)

    if prompt := st.chat_input("Ask a question…"):
        with st.spinner("Thinking…"):
            _run_query(prompt)
        st.rerun()


if __name__ == "__main__":
    main()
