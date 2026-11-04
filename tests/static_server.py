#!/usr/bin/env python3
"""A tiny static web server for the self-test: serves a folder on 127.0.0.1.

Python's own "python3 -m http.server" looks up the computer's network name when it starts, which can hang
for a long time on some machines without working name lookups. This one skips that.

  python3 static_server.py <port> <folder>
"""
import functools
import http.server
import sys


class Server(http.server.ThreadingHTTPServer):
    def server_bind(self):
        import socketserver
        socketserver.TCPServer.server_bind(self)        # no name lookup
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def main():
    port, folder = int(sys.argv[1]), sys.argv[2]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder)
    handler.log_message = lambda *a: None
    print("serving %s on http://127.0.0.1:%d/" % (folder, port), flush=True)
    Server(("127.0.0.1", port), handler).serve_forever()


if __name__ == "__main__":
    main()
