# Runs before any test module: points the app at a throwaway database (so tests never touch dynasty_data.db)
# and makes the app's modules importable. Run the tests from the repository folder with: python -m unittest
import atexit
import os
import shutil
import sys
import tempfile

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "basic_os")
REAL_DB = os.path.join(APP_DIR, "dynasty_data.db")

TEMP_DIR = tempfile.mkdtemp(prefix="basic_os_tests_")
atexit.register(shutil.rmtree, TEMP_DIR, ignore_errors=True)
os.environ["BASIC_OS_DB"] = os.path.join(TEMP_DIR, "test.db")
sys.path.insert(0, APP_DIR)
