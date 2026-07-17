from app import create_app
from app.services.outbox_service import run_dispatcher_forever


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        run_dispatcher_forever()
