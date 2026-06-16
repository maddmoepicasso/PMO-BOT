from pmoai.app import app
from pmoai.config import SETTINGS


if __name__ == "__main__":
    app.run(host=SETTINGS.host, port=SETTINGS.port, debug=False)

