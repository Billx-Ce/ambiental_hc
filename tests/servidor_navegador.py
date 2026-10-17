"""Servidor exclusivo de pruebas: cuentas en memoria, sin acceso a MongoDB."""
import os
import sys
from copy import deepcopy
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MONGODB_URI"] = ""
os.environ.setdefault("PORT", "5058")

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import almacenamiento


class CuentasTemporales:
    def __init__(self):
        self.records = {}
        self.lock = Lock()

    def insert_one(self, record):
        with self.lock:
            if record["email"] in self.records:
                raise DuplicateKeyError("Duplicado de prueba")
            record = deepcopy(record)
            record["_id"] = ObjectId()
            self.records[record["email"]] = record
            return SimpleNamespace(inserted_id=record["_id"])

    def find_one(self, query):
        return self.records.get(query["email"])


if __name__ == "__main__":
    cuentas = CuentasTemporales()
    almacenamiento.usuarios = lambda: cuentas
    from app import main
    print("Servidor de pruebas: cuentas efímeras, MongoDB desactivado.")
    main()
