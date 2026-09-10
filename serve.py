"""
Double-click this file to preview the map locally.

Serves this folder at http://localhost:8765 and opens it in your default
browser. Leave the console window open while you're viewing the map;
close it (or press Ctrl+C) when you're done.
"""
import http.server
import os
import socketserver
import threading
import webbrowser

PORT = 8765

os.chdir(os.path.dirname(os.path.abspath(__file__)))

handler = http.server.SimpleHTTPRequestHandler

def open_browser():
    webbrowser.open(f"http://localhost:{PORT}")

try:
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"Serving the map at http://localhost:{PORT}")
        print("Close this window (or press Ctrl+C) to stop.")
        threading.Timer(0.5, open_browser).start()
        httpd.serve_forever()
except OSError as e:
    print(f"Could not start the server on port {PORT}: {e}")
    print(f"This usually means it's already running -- try opening http://localhost:{PORT} in your browser.")
    input("Press Enter to close...")
except KeyboardInterrupt:
    print("\nStopped.")
