# Connecting the language model (Ollama)

SkyClear works without it. Connecting it adds: wording of the check explanation and of Ask answers by a model (still only from the rules, still checked), and vector search for the hybrid rule search. Ollama runs on another laptop, never required on this one.

## On the Ollama laptop (once)

```
ollama pull qwen2.5:7b            # qwen2.5:3b if it has 8 GB of RAM
ollama pull nomic-embed-text
OLLAMA_HOST=0.0.0.0 ollama serve  # listen on the network, not only on itself
ipconfig getifaddr en0            # note this IP address (macOS). Windows: ipconfig
```

Both laptops must be on the same network. If the venue Wi-Fi blocks laptop to laptop traffic, use a phone hotspot. If a firewall asks, allow port 11434.

## On this laptop

1. In `.env` set:
   ```
   USE_LLM=1
   OLLAMA_URL=http://<that-ip>:11434
   ```
2. Check the connection. It says exactly what to fix:
   ```
   python backend/manage.py check-llm
   ```
3. Embed the rules and build the vector index (once, and again whenever the rules change):
   ```
   python backend/load_data.py
   ```
4. Restart the app. The Ask tab shows "AI model connected", and rule search is hybrid.
5. Record the real comparison for the pitch: `cd backend && python eval.py` (keyword vs vector vs hybrid).

## What happens when it is not reachable

Nothing breaks. Check explanations use the plain template, Ask answers are taken straight from the rules, and rule search is keyword only. The app retries every 30 seconds. `GET /health/llm` and the Ask tab show the current state.

## How it is used, and what keeps it honest

- The verdict is decided by code, never by the model.
- The model only words an explanation or an answer from passages we give it. Every citation id must be a real passage, the text must not call a flight safe, and it must not contradict the decided verdict. Otherwise the plain version is used.
- Text from notices and from users is treated as data, never as instructions.
- Hybrid search is one MongoDB aggregation (`$rankFusion` over `$vectorSearch` and Atlas Search), not code in the app.
