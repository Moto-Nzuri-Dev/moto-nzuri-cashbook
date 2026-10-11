"""Start the Cashbook on this computer: python run.py  →  http://localhost:8000

Phones on the same Wi-Fi can open http://<this-computer's-IP>:8000
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
