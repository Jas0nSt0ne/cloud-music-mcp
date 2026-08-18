from .auth import login_via_qrcode
from .log import setup_logging

if __name__ == "__main__":
    setup_logging("run_login")
    result = login_via_qrcode()
    print(result)
