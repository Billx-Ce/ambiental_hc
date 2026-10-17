"""Historial de metadatos. Fallos de MongoDB nunca impiden inferir."""
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from bson import ObjectId

from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv

# Configuración local privada; las variables del servidor tienen prioridad.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

log = logging.getLogger(__name__)
_client = None
_collection = None
_lock = Lock()
_retry_at = 0
_available = False
_users = None
_users_lock = Lock()


def usuarios():
    """Colección de cuentas con correo único. No devuelve datos al navegador."""
    global _users
    collection = _connect()
    if collection is None:
        raise RuntimeError("Almacenamiento de cuentas no disponible")
    with _users_lock:
        if _users is None:
            candidate = collection.database["usuarios"]
            candidate.create_index("email", unique=True)
            _users = candidate
    return _users


def serializar(value):
    """JSON estándar, sin Extended JSON, para historial y pruebas."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: serializar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializar(item) for item in value]
    return value


def _failure():
    global _retry_at, _available
    _available = False
    _retry_at = monotonic() + 30
    # No registrar excepciones del driver: pueden contener hosts o credenciales.
    log.warning("MongoDB temporalmente no disponible. Reintento en 30 segundos.")


def _connect():
    global _client, _collection, _available
    if not os.environ.get("MONGODB_URI") or monotonic() < _retry_at:
        return None
    with _lock:
        if monotonic() < _retry_at:
            return None
        try:
            if _client is None:
                _client = MongoClient(os.environ["MONGODB_URI"],
                                     serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                                     socketTimeoutMS=2000, tz_aware=True)
            if _collection is None:
                _client.admin.command("ping")
                candidate = _client[os.environ.get("MONGODB_DB") or "ambiental_huanuco"]["inferencias"]
                candidate.create_index([("created_at", DESCENDING)])
                candidate.create_index([("user_id", 1), ("created_at", DESCENDING)])
                _collection = candidate
            _available = True
            return _collection
        except Exception:
            _failure()
            return None


def estado_almacenamiento(verificar=False):
    configured = bool(os.environ.get("MONGODB_URI"))
    if verificar and configured:
        collection = _connect()
        if collection is not None:
            try:
                _client.admin.command("ping")
            except Exception:
                _failure()
    available = configured and _available
    state = "no_configurado" if not configured else (
        "disponible" if available else "no_disponible")
    message = "Historial disponible cuando se configure MongoDB" if not configured else (
        "Almacenamiento disponible" if available else
        "Almacenamiento temporalmente no disponible. Los resultados no se guardan.")
    return {"estado": state, "disponible": available, "configurado": configured,
            "mensaje": message}


def guardar(record):
    collection = _connect()
    saved = False
    if collection is not None:
        try:
            collection.insert_one({**record, "created_at": datetime.now(timezone.utc)})
            saved = True
        except Exception:
            _failure()
    state = estado_almacenamiento()
    return {**state, "disponible": saved, "guardado": saved,
            "mensaje": "Resultado guardado" if saved else state["mensaje"] + " Resultado no guardado."}


def historial(limit, user_id):
    collection = _connect()
    if collection is not None:
        try:
            records = list(collection.find({"user_id": user_id}, {"user_id": 0}).sort("created_at", -1).limit(limit))
            return {"estado": "disponible", "disponible": True, "registros": serializar(records)}
        except Exception:
            _failure()
    return {**estado_almacenamiento(), "registros": []}


def estadisticas(user_id):
    collection = _connect()
    if collection is not None:
        try:
            # Una sola agregación evita leer todas las inferencias en memoria.
            data = list(collection.aggregate([{"$match": {"user_id": user_id}}, {"$facet": {
                "resumen": [{"$group": {"_id": None, "total": {"$sum": 1},
                    "confianza_promedio": {"$avg": "$confidence"},
                    "no_concluyentes": {"$sum": {"$cond": ["$is_conclusive", 0, 1]}}}}],
                "categorias": [{"$group": {"_id": "$displayed_category", "cantidad": {"$sum": 1}}}],
                "fuentes": [{"$group": {"_id": "$source", "cantidad": {"$sum": 1}}}]
            }}], maxTimeMS=2000))[0]
            summary = data["resumen"][0] if data["resumen"] else {
                "total": 0, "confianza_promedio": 0, "no_concluyentes": 0}
            summary.pop("_id", None)
            return {"disponible": True, **summary,
                    "por_categoria": {x["_id"]: x["cantidad"] for x in data["categorias"]},
                    "por_fuente": {x["_id"]: x["cantidad"] for x in data["fuentes"]}}
        except Exception:
            _failure()
    return estado_almacenamiento()
