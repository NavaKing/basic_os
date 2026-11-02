import os
import shutil
import subprocess
import tempfile

# PDF export of the printable issue. Microsoft Edge (on every Windows PC) renders the app's own print view to a PDF
# in headless mode, so no PDF library is needed. Without Edge, the print view's button uses the browser's print dialog.

EDGE_PATHS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
RENDER_SECONDS = 120

def edge_path():
    return shutil.which("msedge") or next((p for p in EDGE_PATHS if os.path.exists(p)), None)

def render_pdf(url):
    """Renders a page of this app to PDF; returns the PDF's bytes."""
    edge = edge_path()
    if not edge:
        raise RuntimeError("Microsoft Edge wasn't found, so the app can't make a PDF itself. Use the print view's button and choose Save as PDF.")
    folder = tempfile.mkdtemp(prefix="basic_os_pdf_")
    try:
        target = os.path.join(folder, "issue.pdf")
        # A throwaway profile keeps this separate from the user's own Edge windows
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=10000",
                        f"--user-data-dir={os.path.join(folder, 'profile')}", f"--print-to-pdf={target}", url],
                       capture_output=True, timeout=RENDER_SECONDS)
        if not os.path.exists(target) or os.path.getsize(target) == 0:
            raise RuntimeError("Edge didn't produce a PDF. Use the print view's button and choose Save as PDF.")
        with open(target, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
