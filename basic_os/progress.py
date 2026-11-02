import threading
import time

# Live progress for the hub generator. /generate reports each step here; the page polls /generate/progress
# while it waits, so the button can say "Rendering photo 2 of 3" instead of spinning for minutes.

_lock = threading.Lock()
_state = {"running": False, "step": "", "detail": "", "number": 0, "total": 0, "started": None}

STEPS = ["Syncing the save", "Writing storyline chapters", "Checking recruiting commits", "Scouting the opponent",
         "Writing the dispatch", "Writing the social posts", "Rendering the banner photo", "Rendering post photos"]

def start():
    with _lock:
        _state.update(running=True, step="Starting", detail="", number=0, total=len(STEPS), started=time.time())

def step(name, detail=""):
    """Marks one of STEPS as under way (detail is extra text such as 'photo 2 of 3')."""
    with _lock:
        _state.update(step=name, detail=detail, number=STEPS.index(name) + 1 if name in STEPS else _state['number'])

def finish():
    with _lock:
        _state.update(running=False, step="Done", detail="")

def snapshot():
    with _lock:
        state = dict(_state)
    state['elapsed'] = round(time.time() - state['started']) if state['started'] else 0
    state.pop('started')
    return state
