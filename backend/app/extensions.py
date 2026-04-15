from __future__ import annotations

from celery import Celery, Task
from flask import has_app_context
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
jwt = JWTManager()
cors = CORS()


class ContextTask(Task):
    def __call__(self, *args, **kwargs):
        if has_app_context():
            return self.run(*args, **kwargs)
        flask_app = self.app.conf.get("flask_app")
        if flask_app is not None:
            with flask_app.app_context():
                return self.run(*args, **kwargs)
        return self.run(*args, **kwargs)


celery = Celery()
celery.Task = ContextTask
