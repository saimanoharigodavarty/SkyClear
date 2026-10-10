# Connecting the language model (Ollama)

SkyClear works without it. Connecting it adds: wording of the check explanation and of Ask answers by a model (still only from the rules, still checked), and vector search for the hybrid rule search. Ollama runs on another laptop, never required on this one.

## On the Ollama laptop (once)

Run these on that laptop, not on the one running SkyClear. Nothing from this project is needed there.

### Windows (PowerShell)

1. Install Ollama for Windows from ollama.com/download.
2. Pull the models. Use `qwen2.5:3b` if the laptop has 8 GB of RAM:
   ```
   ollama pull qwen2.5:7b
   ollama pull nomic-embed-text
   ```
3. Listen on the network, then quit Ollama from the system tray and start it again so it reads the setting:
   ```
   setx OLLAMA_HOST "0.0.0.0"
   ```
4. Open the firewall. In PowerShell run as Administrator:
   ```
   New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow
   ```
   If Windows asks to allow access, say yes for the private network.
5. Find the address with `ipconfig` (IPv4 Address of the Wi-Fi adapter).
6. Check on that laptop: `curl http://localhost:11434/api/tags` lists both models.

### macOS or Linux

```
ollama pull qwen2.5:7b            # qwen2.5:3b if it has 8 GB of RAM
ollama pull nomic-embed-text
OLLAMA_HOST=0.0.0.0 ollama serve  # listen on the network, not only on itself
ipconfig getifaddr en0            # its IP address (macOS). Linux: hostname -I
```

Both laptops must be on the same network. If the venue Wi-Fi blocks laptop to laptop traffic, use a phone hotspot.

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
