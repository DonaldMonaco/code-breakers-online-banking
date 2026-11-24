"""
Code Breakers Online Banking - CSC 430 final project
Start the web app:   python3 app.py   then open http://127.0.0.1:5050

The MySQL password is never stored in the code. Set it first:
    export DB_PASSWORD='your-mysql-root-password'
or just run the app and type it when asked.
"""
import getpass
import os

if not os.environ.get("DB_PASSWORD"):
    os.environ["DB_PASSWORD"] = getpass.getpass("MySQL password for user '%s': " % os.environ.get("DB_USER", "root"))

from bank import create_app  # noqa: E402  (imported after the password is set)

app = create_app()

if __name__ == "__main__":
    print("Online Banking is running at  http://127.0.0.1:5050   (press Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5050, debug=False)
