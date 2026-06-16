"""
Servicio para probar la conectividad a las bases de datos.
"""

from db.connections import MySQLMainConnection, MySQLLogsConnection, MongoConnection


class ConnectionTester:
    """Prueba la conectividad a todas las bases de datos."""

    @staticmethod
    def test_mysql_main() -> bool:
        """Prueba la conexión al cluster MySQL principal."""
        try:
            with MySQLMainConnection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
            print("  ✅ MySQL Principal (performance): conexión exitosa")
            return True
        except Exception as e:
            print(f"  ❌ MySQL Principal (performance): {e}")
            return False

    @staticmethod
    def test_mysql_logs() -> bool:
        """Prueba la conexión al cluster MySQL de logs."""
        try:
            with MySQLLogsConnection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
            print("  ✅ MySQL Logs (logs): conexión exitosa")
            return True
        except Exception as e:
            print(f"  ❌ MySQL Logs (logs): {e}")
            return False

    @staticmethod
    def test_mongo() -> bool:
        """Prueba la conexión al cluster MongoDB."""
        try:
            with MongoConnection() as db:
                db.command("ping")
            print("  ✅ MongoDB (main): conexión exitosa")
            return True
        except Exception as e:
            print(f"  ❌ MongoDB (main): {e}")
            return False

    @classmethod
    def test_all(cls) -> dict[str, bool]:
        """Prueba todas las conexiones y retorna un resumen."""
        print("🔌 Probando conexiones...\n")
        results = {
            "mysql_main": cls.test_mysql_main(),
            "mysql_logs": cls.test_mysql_logs(),
            "mongodb": cls.test_mongo(),
        }
        ok = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"\n{'✅' if ok == total else '⚠️'} Resultado: {ok}/{total} conexiones exitosas.")
        return results

