from http.server import SimpleHTTPRequestHandler, HTTPServer
import os

PORT = 8000
DIRECTORY = "zipped_media"


class LocalOnlyHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = super().translate_path(path)
        relpath = os.path.relpath(path, os.getcwd())
        return os.path.join(os.getcwd(), DIRECTORY, os.path.basename(relpath))

    def log_message(self, format, *args):
        pass  # silence logs


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), LocalOnlyHandler)
    print(f"Serving on http://127.0.0.1:{PORT}")
    server.serve_forever()