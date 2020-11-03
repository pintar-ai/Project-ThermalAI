import os


basedir = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    SECRET_KEY = '9OLWxND4o83j4K4iuopO'
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite://")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STATIC_FOLDER = f"{os.getenv('APP_FOLDER')}/static"
    TEMPLATE_FOLDER = f"{os.getenv('APP_FOLDER')}/templates"
    TEMPLATES_AUTO_RELOAD = True
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = 'perceptronservices@gmail.com'
    MAIL_PASSWORD = 'wojbjtguzydhkfjj'
