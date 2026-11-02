"""``python -m app`` — serve on loopback only, with a single worker (spec section 2.3)."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)
