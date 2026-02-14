#!/usr/bin/env python3
"""Run the Deal Command Center web dashboard."""

import argparse

from deal_command_center.web import run_server


def main():
    parser = argparse.ArgumentParser(description="Deal Command Center - Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
