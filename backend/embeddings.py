"""Embeddings through Ollama (nomic-embed-text, 768 dimensions). Returns None when Ollama is not reachable."""
import time

import config

DIMENSIONS = 768
COOLDOWN_S = 30
_down_until = 0.0


def embed(texts, kind="document"):
    """kind is 'document' or 'query' (nomic-embed-text expects these prefixes)."""
    global _down_until
    if time.time() < _down_until:
        return None
    try:
        import ollama
        client = ollama.Client(host=config.OLLAMA_URL, timeout=config.ollama_timeout(20))
        out = client.embed(model=config.EMBED_MODEL, input=[f"search_{kind}: {t}" for t in texts])
        return out["embeddings"]
    except Exception as e:  # Ollama missing, model not pulled, network
        print(f"embeddings unavailable at {config.OLLAMA_URL} ({type(e).__name__}); retrying in {COOLDOWN_S}s")
        _down_until = time.time() + COOLDOWN_S
        return None
