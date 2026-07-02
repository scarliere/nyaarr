import os

from nyaarr import create_app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("NYAARR_HOST", "127.0.0.1")
    port = int(os.environ.get("NYAARR_PORT", "1269"))
    debug = os.environ.get("NYAARR_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug, use_reloader=False)