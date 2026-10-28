"""Question Paper Duplicate Finder: upload several Word papers and analyse them together.

Run with: streamlit run app.py
The results page is the same index.html used by api.py (uvicorn api:app), with its own CSS unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from analysis import analyse

PAGE = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")

# The page's upload card needs the FastAPI server, so it is hidden here: papers are added in the
# uploader above. Everything else on the page works in the browser.
EMBED_CSS = """
#form, #status, .hero { display: none !important; }
body { min-height: 0 !important; background: transparent; }
body.dark {
  --bg: transparent; --surface: #1d2430; --subtle: #252e3d; --line: #323d50; --line-2: #3f4b62;
  --ink: #e8edf6; --ink-2: #c3cddd; --ink-3: #939fb4; --primary-bg: #1f2d4a; --dup-bg: #3a2323;
  --sem-bg: #242a4a;
}
"""
BOOT = """
    // Follow Streamlit's light or dark theme, so the page blends into the app background.
    const darkTheme = (() => {
      try {
        const app = window.parent.document.querySelector('[data-testid="stApp"]') || window.parent.document.body;
        const rgb = getComputedStyle(app).backgroundColor.match(/[\d.]+/g).map(Number);
        return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] < 128;
      } catch (e) {
        return window.matchMedia("(prefers-color-scheme: dark)").matches;
      }
    })();
    document.body.classList.toggle("dark", darkTheme);
    SELECTED.clear();
    defaultPaperNumbers().forEach(n => SELECTED.add(n));
    render();
    // Make the frame exactly as tall as the page, so the page scrolls with the screen, not inside a box.
    const fitFrame = () => {
      try { window.frameElement.style.height = (document.documentElement.scrollHeight + 24) + "px"; } catch (e) {}
    };
    new ResizeObserver(fitFrame).observe(document.body);
    fitFrame();
"""

st.set_page_config(page_title="Question Paper Duplicate Finder", layout="wide")


@st.cache_data(show_spinner=False)
def run_analysis(papers_in: tuple[tuple[str, bytes], ...]):
    return analyse(list(papers_in))


def page_html(result: dict) -> str:
    """The original results page, with this analysis loaded into it."""
    data = json.dumps(result, ensure_ascii=False).replace("</", "<\\/")
    html = PAGE.replace("    let DATA = null;", f"    let DATA = {data};", 1)
    html = html.replace("</head>", f"<style>{EMBED_CSS}</style>\n</head>", 1)
    end = html.rindex("</script>")
    return html[:end] + BOOT + html[end:]


st.title("Question Paper Duplicate Finder")
uploads = st.file_uploader("Question papers (.docx)", type=["docx"], accept_multiple_files=True,
                           help="Add several papers. Each stays in the list until you remove it.")
if st.button(f"Analyse {len(uploads)} paper{'s' if len(uploads) != 1 else ''} together",
             type="primary", disabled=not uploads):
    with st.status("Reading the papers…", expanded=True) as status:
        st.write("Removing headings, instructions, rough work and blank pages")
        st.write("Comparing the questions of all papers together")
        result, problems = run_analysis(tuple((f.name, f.getvalue()) for f in uploads))
        status.update(label="Analysis complete", state="complete", expanded=False)
    st.session_state["analysis"] = {"result": result, "problems": problems}

analysis = st.session_state.get("analysis")
if analysis is None:
    st.info("Add question papers, then press Analyse. Every paper is read first and then all questions "
            "are compared together.")
    st.stop()

for problem in analysis["problems"]:
    st.warning(problem)
if analysis["result"] is None:
    st.error("No questions were found in the papers.")
    st.stop()

components.html(page_html(analysis["result"]), height=900, scrolling=False)
