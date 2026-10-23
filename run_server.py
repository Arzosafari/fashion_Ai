"""
Fashion STT Server Runner
"""

import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "=" * 60)
    print("👗 Atelier Voice Fashion STT Server is RUNNING!")
    print(f"👉 Open in your browser: http://localhost:{port} or http://127.0.0.1:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("fashion_stt.server:app", host="0.0.0.0", port=port, log_level="info")
