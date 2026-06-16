"""
Ejecutores de queries para MySQL y MongoDB.
"""

from typing import Any
from mysql.connector.abstracts import MySQLConnectionAbstract
from pymongo.database import Database


class MySQLQueryExecutor:
    """Ejecuta queries SQL sobre una conexión MySQL."""

    def __init__(self, connection: MySQLConnectionAbstract):
        self._connection = connection

    def fetch_all(self, query: str) -> list[dict[str, Any]]:
        """Ejecuta una query y retorna todos los resultados como lista de dicts."""
        cursor = self._connection.cursor(dictionary=True)
        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()
        return results  # type: ignore[return-value]

    def fetch_one(self, query: str) -> dict[str, Any] | None:
        """Ejecuta una query y retorna solo el primer resultado."""
        cursor = self._connection.cursor(dictionary=True)
        cursor.execute(query)
        result = cursor.fetchone()
        cursor.close()
        return result  # type: ignore[return-value]

    def execute(self, query: str) -> int:
        """Ejecuta una query sin retorno de datos (INSERT, UPDATE, DELETE).
        Retorna el número de filas afectadas."""
        cursor = self._connection.cursor()
        cursor.execute(query)
        self._connection.commit()
        affected = cursor.rowcount
        cursor.close()
        return affected


class MongoQueryExecutor:
    """Ejecuta consultas sobre una base de datos MongoDB."""

    def __init__(self, database: Database):
        self._db = database

    def aggregate(self, collection_name: str, pipeline: list) -> list[dict]:
        """Ejecuta un pipeline de agregación y retorna los resultados."""
        collection = self._db[collection_name]
        return list(collection.aggregate(pipeline))

    def find(self, collection_name: str, query: dict, projection: dict | None = None) -> list[dict]:
        """Ejecuta un find y retorna los documentos encontrados."""
        collection = self._db[collection_name]
        return list(collection.find(query, projection))

    def find_one(self, collection_name: str, query: dict, projection: dict | None = None) -> dict | None:
        """Ejecuta un find y retorna solo el primer documento."""
        collection = self._db[collection_name]
        return collection.find_one(query, projection)

    def count(self, collection_name: str, query: dict) -> int:
        """Cuenta documentos que coincidan con el filtro."""
        collection = self._db[collection_name]
        return collection.count_documents(query)

