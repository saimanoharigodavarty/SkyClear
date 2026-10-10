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


def warm_up():
    """Load the model on the Ollama laptop in the background, so the first real question is not slow."""
    if not config.USE_LLM:
        return
    import threading

    def go():
        try:
            import ollama
            ollama.Client(host=config.OLLAMA_URL, timeout=config.ollama_timeout()).chat(
                model=config.LLM_MODEL, messages=[{"role": "user", "content": "ok"}], options={"num_predict": 1}, keep_alive=config.LLM_KEEP_ALIVE)
            print(f"[llm] {config.LLM_MODEL} loaded on {config.OLLAMA_URL}")
        except Exception as e:
            print(f"[llm] warm-up skipped ({type(e).__name__}), the app works without it")
    threading.Thread(target=go, daemon=True).start()
