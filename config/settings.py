"""
Configuración de bases de datos.
Carga las variables de entorno desde .env y expone
las configuraciones de cada cluster.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class MySQLMainConfig:
    """Configuración del cluster MySQL principal (performance)."""
    HOST = os.getenv("MYSQL_MAIN_HOST", "localhost")
    PORT = int(os.getenv("MYSQL_MAIN_PORT", 3306))
    USER = os.getenv("MYSQL_MAIN_USER", "root")
    PASSWORD = os.getenv("MYSQL_MAIN_PASSWORD", "")
    DATABASE = os.getenv("MYSQL_MAIN_DATABASE", "performance")


class MySQLLogsConfig:
    """Configuración del cluster MySQL de logs."""
    HOST = os.getenv("MYSQL_LOGS_HOST", "localhost")
    PORT = int(os.getenv("MYSQL_LOGS_PORT", 3307))
    USER = os.getenv("MYSQL_LOGS_USER", "root")
    PASSWORD = os.getenv("MYSQL_LOGS_PASSWORD", "")
    DATABASE = os.getenv("MYSQL_LOGS_DATABASE", "logs")


class MongoConfig:
    """Configuración del cluster MongoDB (analytics)."""
    HOST = os.getenv("MONGO_HOST", "localhost")
    PORT = int(os.getenv("MONGO_PORT", 27017))
    USER = os.getenv("MONGO_USER", "")
    PASSWORD = os.getenv("MONGO_PASSWORD", "")
    DATABASE = os.getenv("MONGO_DATABASE", "")
    AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "admin")

    @property
    def uri(self) -> str:
        if self.USER and self.PASSWORD:
            return (
                f"mongodb://{self.USER}:{self.PASSWORD}"
                f"@{self.HOST}:{self.PORT}/{self.DATABASE}"
                f"?authSource={self.AUTH_SOURCE}"
            )
        return f"mongodb://{self.HOST}:{self.PORT}/{self.DATABASE}"

