#!/usr/bin/env python3
import http.server
import ssl
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Serve a directory over HTTPS.")
    parser.add_argument("--port", type=int, default=8443, help="Port to listen on")
    parser.add_argument("--dir", default=os.getcwd(), help="Directory to serve")
    args = parser.parse_args()

    os.chdir(args.dir)
    handler = http.server.SimpleHTTPRequestHandler

    httpd = http.server.HTTPServer(("0.0.0.0", args.port), handler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile="server.crt", keyfile="server.key")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    print(f"Serving {args.dir} on https://0.0.0.0:{args.port}")
    httpd.serve_forever()

if __name__ == "__main__":
    main()
