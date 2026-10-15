import uvicorn
import os

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_env = os.getenv("RELOAD", "false").lower() in ("true", "1")
    print("\n" + "=" * 56)
    print("FilmsOverWeb - Cloud Cinema OTT Server")
    print(f"Serving on: http://{host}:{port}")
    print(f"Default SuperAdmin: test@gmail.com")
    print(f"Default Password:   1q2w3e4r5t")
    print("=" * 56 + "\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload_env)
