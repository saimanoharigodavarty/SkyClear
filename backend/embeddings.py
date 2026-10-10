"""Embeddings through Ollama (nomic-embed-text, 768 dimensions). Returns None when Ollama is not reachable."""
import config

DIMENSIONS = 768


def embed(texts, kind="document"):
    """kind is 'document' or 'query' (nomic-embed-text expects these prefixes)."""
    try:
        import ollama
        client = ollama.Client(host=config.OLLAMA_URL)
        out = client.embed(model=config.EMBED_MODEL, input=[f"search_{kind}: {t}" for t in texts])
        return out["embeddings"]
    except Exception as e:  # Ollama missing, model not pulled, network
        print(f"embeddings unavailable ({type(e).__name__}: {e})")
        return None
