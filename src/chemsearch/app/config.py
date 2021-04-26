import os
import logging
import pathlib
import yaml

from collections import OrderedDict

from ..paths import DEMO_DIR

_basedir = os.path.abspath(os.path.dirname(__file__))
_logger = logging.getLogger(__name__)
PACKAGE_ROOT = pathlib.Path(__file__).parent.parent.parent.parent


def load_custom_queries():
    default_path = PACKAGE_ROOT.joinpath('config', 'custom_queries.yaml')
    yaml_path = os.environ.get('CUSTOM_QUERIES_YAML', default_path)
    if yaml_path.exists():
        with open(yaml_path, 'r') as infile:
            query_dict = OrderedDict(yaml.load(infile, Loader=yaml.SafeLoader))
    else:
        query_dict = None
    return query_dict


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard to guess string'
    APP_TITLE = os.environ.get('APP_TITLE', 'Chemsearch')
    USE_AUTH = os.environ.get('USE_AUTH', 'off').lower() not in {'off', 'false', '0'}
    if USE_AUTH:
        OAUTH_CREDENTIALS = {
            'google': {
                'id': os.environ.get('GOOGLE_CLIENT_ID'),
                'secret': os.environ.get('GOOGLE_SECRET'),
            }
        }

    MOLECULES_PER_PAGE = os.environ.get('MOLECULES_PER_PAGE', 15)

    SQLALCHEMY_DATABASE_URI = \
        'sqlite:///' + os.path.join(_basedir, 'db.sqlite')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SESSION_TYPE = 'filesystem'
    # SESSION_FILE_DIR = os.environ.get('SESSION_FILE_DIR', os.getcwd())
    # _logger.info(f"{SESSION_FILE_DIR=}")
    MAX_CONTENT_LENGTH = 1024 * 1024  # 1MB request size limit, for uploads
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.googlemail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in \
        ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_SUBJECT_PREFIX = f'[{APP_TITLE}]'
    MAIL_SENDER = os.environ.get('MAIL_SENDER')
    MAIL_ADMIN = os.environ.get('MAIL_ADMIN')

    USE_DRIVE = os.environ.get('USE_DRIVE', 'false').lower() not in {'off', 'false', '0'}
    if USE_DRIVE:
        SHARED_DRIVE_ID = os.environ.get('SHARED_DRIVE_ID')
    if USE_DRIVE or USE_AUTH:
        SERVICE_ACCOUNT_FILE = os.environ.get('SERVICE_ACCOUNT_FILE')
        CREDENTIALS_AS_USER = os.environ.get('CREDENTIALS_AS_USER')
    if USE_AUTH:
        GROUP_KEY = os.environ.get('GROUP_KEY')

    LOCAL_DB_PATH = os.environ.get('LOCAL_DB_PATH', str(DEMO_DIR))
    os.environ.update({'LOCAL_DB_PATH': LOCAL_DB_PATH})
    _logger.debug(f"Using {LOCAL_DB_PATH=}")

    CUSTOM_QUERIES = load_custom_queries()

    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True


class ProductionConfig(Config):
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)

        # email errors to the administrators
        import logging
        from logging.handlers import SMTPHandler
        credentials = None
        secure = None
        if getattr(cls, 'MAIL_USERNAME', None) is not None:
            credentials = (cls.MAIL_USERNAME, cls.MAIL_PASSWORD)
            if getattr(cls, 'MAIL_USE_TLS', None):
                secure = ()
        # print(f"{cls.MAIL_SERVER=}, {cls.MAIL_ADMIN=}, {cls.MAIL_SERVER}")
        if cls.MAIL_ADMIN is not None and cls.MAIL_SENDER is not None:
            mail_handler = SMTPHandler(
                mailhost=(cls.MAIL_SERVER, cls.MAIL_PORT),
                fromaddr=cls.MAIL_SENDER,
                toaddrs=[cls.MAIL_ADMIN],
                subject=cls.MAIL_SUBJECT_PREFIX + ' Application Error',
                credentials=credentials,
                secure=secure)
            mail_handler.setLevel(logging.ERROR)
            app.logger.addHandler(mail_handler)


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,

    'default': DevelopmentConfig
}
