import uvicorn
import os

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print("\n" + "=" * 56)
    print("FilmsOverWeb - Cloud Cinema OTT Server")
    print(f"Serving on: http://{host}:{port}")
    print(f"Default SuperAdmin: drmnbot@gmail.com")
    print(f"Default Password:   SuperAdmin@2026")
    print("=" * 56 + "\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
