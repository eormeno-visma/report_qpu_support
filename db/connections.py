"""
Clases de conexión a bases de datos.
Cada cluster tiene su propia clase con context manager.
"""

from typing import cast

import mysql.connector
from mysql.connector.abstracts import MySQLConnectionAbstract
from pymongo import MongoClient
from pymongo.database import Database

from config import MySQLMainConfig, MySQLLogsConfig, MongoConfig


# =============================================================================
# MYSQL GENÉRICO
# =============================================================================

class MySQLConnection:
    """Gestiona una conexión MySQL con context manager."""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._connection: MySQLConnectionAbstract | None = None

    def connect(self) -> MySQLConnectionAbstract:
        """Abre la conexión y la retorna."""
        self._connection = cast(MySQLConnectionAbstract, mysql.connector.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
        ))
        return self._connection

    def close(self):
        """Cierra la conexión si está abierta."""
        if self._connection and self._connection.is_connected():
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> MySQLConnectionAbstract | None:
        return self._connection

    def __enter__(self) -> MySQLConnectionAbstract:
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self) -> str:
        return f"MySQLConnection({self._host}:{self._port}/{self._database})"


# =============================================================================
# MYSQL PRINCIPAL (PERFORMANCE)
# =============================================================================

class MySQLMainConnection(MySQLConnection):
    """Conexión al cluster MySQL principal (performance)."""

    def __init__(self):
        cfg = MySQLMainConfig()
        super().__init__(
            host=cfg.HOST,
            port=cfg.PORT,
            user=cfg.USER,
            password=cfg.PASSWORD,
            database=cfg.DATABASE,
        )


# =============================================================================
# MYSQL LOGS
# =============================================================================

class MySQLLogsConnection(MySQLConnection):
    """Conexión al cluster MySQL de logs."""

    def __init__(self):
        cfg = MySQLLogsConfig()
        super().__init__(
            host=cfg.HOST,
            port=cfg.PORT,
            user=cfg.USER,
            password=cfg.PASSWORD,
            database=cfg.DATABASE,
        )


# =============================================================================
# MONGODB (ANALYTICS)
# =============================================================================

class MongoConnection:
    """Gestiona una conexión MongoDB con context manager."""

    def __init__(self):
        self._config = MongoConfig()
        self._client: MongoClient | None = None
        self._db: Database | None = None

    def connect(self) -> Database:
        """Abre la conexión y retorna la base de datos."""
        self._client = MongoClient(self._config.uri)
        self._db = self._client[self._config.DATABASE]
        return self._db

    def close(self):
        """Cierra el cliente MongoDB."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None

    @property
    def database(self) -> Database | None:
        return self._db

    @property
    def client(self) -> MongoClient | None:
        return self._client

    def __enter__(self) -> Database:
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self) -> str:
        return f"MongoConnection({self._config.HOST}:{self._config.PORT}/{self._config.DATABASE})"

