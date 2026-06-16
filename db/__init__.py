"""
Paquete de base de datos.
Conexiones y ejecutores de queries.
"""

from .connections import MySQLConnection, MySQLMainConnection, MySQLLogsConnection, MongoConnection
from .executors import MySQLQueryExecutor, MongoQueryExecutor

__all__ = [
    "MySQLConnection",
    "MySQLMainConnection",
    "MySQLLogsConnection",
    "MongoConnection",
    "MySQLQueryExecutor",
    "MongoQueryExecutor",
]

