"""Start the local frontend and API: python -m everymind_web."""

import argparse
import logging

import uvicorn

from .server import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.getLogger("presidio-analyzer").disabled = True
    logging.getLogger("presidio-anonymizer").disabled = True
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
