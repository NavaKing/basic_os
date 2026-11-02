from functools import wraps

# Page loads build some things more than once (the Weekly Recap feeds both its tab and the Awards tab; coach news feeds
# the Coaches and Offseason tabs). This remembers a builder's result for the rest of one GET request. Requests that
# change data (POST, DELETE) never use it, so a generate-then-show flow always sees its own changes.

def per_request(fn):
    @wraps(fn)
    def wrapper(*args):
        from flask import g, has_request_context, request
        if not has_request_context() or request.method != "GET":
            return fn(*args)
        store = g.setdefault("_per_request", {})
        key = (fn.__module__, fn.__qualname__, args)
        if key not in store:
            store[key] = fn(*args)
        return store[key]
    return wrapper
