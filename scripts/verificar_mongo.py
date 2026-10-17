"""Verifica MongoDB con la configuración privada, sin imprimir la URI."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import almacenamiento  # Carga .env sin reemplazar variables del entorno.
from pymongo import MongoClient


def main():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("MongoDB no configurado.")
        return 1
    client = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000,
                             connectTimeoutMS=5000, socketTimeoutMS=5000)
        client.admin.command("ping")
        collection = client[os.environ.get("MONGODB_DB") or "ambiental_huanuco"]["inferencias"]
        collection.create_index([("created_at", -1)])
        collection.database["usuarios"].create_index("email", unique=True)
        total = collection.count_documents({})
        print("Conexión, índices de inferencias/cuentas y lectura correctos.")
        print(f"Colección: ambiental_huanuco.inferencias. Registros: {total}")
        return 0
    except Exception as error:
        # No imprimir el mensaje original del driver: podría incluir datos privados.
        code = getattr(error, "code", None)
        print(f"Conexión fallida: {type(error).__name__}. Código: {code}")
        detail = str(error).lower()
        if code == 18 or "bad auth" in detail or "authentication failed" in detail:
            print("Atlas rechazó la autenticación. Revisa el usuario y su contraseña.")
        elif code == 13:
            print("El usuario no tiene permisos suficientes sobre la base.")
        else:
            print("Comprueba conexión de red, acceso de red en Atlas y configuración del clúster.")
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
