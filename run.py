"""Start CheckFlow: python run.py [--no-browser] [--local-only]
Serves the UI and API on port 8765 (PORT env to change). By default it listens on the office network so
accounts-receivable users can open it from their own computers; --local-only (or CHECKFLOW_LOCAL=1) keeps it private."""
import os, sys, socket, threading, webbrowser

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return None

def main():
    port = int(os.environ.get("PORT", 8765))
    local = "--local-only" in sys.argv or bool(os.environ.get("CHECKFLOW_LOCAL"))
    import uvicorn
    from checkflow import app as appmod
    from checkflow.extract import engine
    engine()                                   # load OCR models before the first upload
    ip = lan_ip()
    print("CheckFlow is running.")
    print(f"  On this computer:          http://127.0.0.1:{port}")
    if not local and ip: print(f"  Other computers (network): http://{ip}:{port}")
    print("  First sign-in: admin / admin  (change it under your name > Change password)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(appmod.app, host="127.0.0.1" if local else "0.0.0.0", port=port, log_level="warning")

if __name__ == "__main__":
    main()
