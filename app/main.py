from fastapi import FastAPI

app = FastAPI(title="Taskmaster Menu")


@app.get("/health")
def health():
    """Quick check that the server is up. Handy at the venue."""
    return {"status": "ok"}