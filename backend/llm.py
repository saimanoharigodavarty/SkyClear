"""Is the language model (Ollama, usually on another laptop) reachable, and has it got the models we need?

Cached for 30 seconds so the UI can ask often. OWNER: Nikhil (stream 1).
"""
import time

import config

_cache = {"t": 0.0, "v": None}


def _has(models, wanted):
    base = wanted.split(":")[0]
    return any(m == wanted or (":" not in wanted and m.split(":")[0] == base) or m.startswith(wanted + ":") for m in models)


def status(force=False):
    if not config.USE_LLM:
        return {"enabled": False, "reachable": False, "llm_model_ready": False, "embed_model_ready": False, "url": None}
    if not force and _cache["v"] and time.time() - _cache["t"] < 30:
        return _cache["v"]
    import requests
    out = {"enabled": True, "reachable": False, "llm_model_ready": False, "embed_model_ready": False, "url": config.OLLAMA_URL}
    try:
        r = requests.get(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=3)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        out.update({"reachable": True, "llm_model_ready": _has(names, config.LLM_MODEL), "embed_model_ready": _has(names, config.EMBED_MODEL), "models": names})
    except Exception as e:
        out["error"] = type(e).__name__
    _cache.update(t=time.time(), v=out)
    return out
