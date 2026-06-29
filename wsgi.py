import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app

if __name__ == "__main__":
    import waitress
    port = int(os.getenv("PORT", 5000))
    waitress.serve(app, host="0.0.0.0", port=port)
