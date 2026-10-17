"""Registro y sesiones sin cuentas reales ni conexiones de red."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash

import almacenamiento as db
import autenticacion as auth
import inferencia_ambiental as api

PASSWORD = "Frase de prueba 234!"


class UsuariosPrueba:
    def __init__(self):
        self.records = {}

    def insert_one(self, record):
        if record["email"] in self.records:
            raise DuplicateKeyError("Correo repetido")
        record = deepcopy(record)
        record["_id"] = ObjectId()
        self.records[record["email"]] = record
        return SimpleNamespace(inserted_id=record["_id"])

    def find_one(self, query):
        return self.records.get(query["email"])


@pytest.fixture
def cuentas(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setattr(db, "MongoClient", MagicMock(side_effect=AssertionError("Sin red")))
    auth._attempts.clear()
    users = UsuariosPrueba()
    monkeypatch.setattr(db, "usuarios", lambda: users)
    return users


@pytest.fixture
def client(cuentas):
    return api.app.test_client()


def token(client, page="/login"):
    client.get(page)
    with client.session_transaction() as signed:
        return signed["csrf_token"]


def registro(client, **kwargs):
    data = {"nombre": "Ana Ambiental", "email": "ana@example.test", "password": PASSWORD,
            "confirmar_password": PASSWORD, "csrf_token": token(client, "/registro")}
    data.update(kwargs)
    return client.post("/registro", data=data)


def test_rutas_requieren_sesion(client):
    response = client.get("/")
    assert response.status_code == 302 and response.location.endswith("/login")
    for route in ("/api/clasificar", "/api/estado", "/api/historial", "/api/estadisticas"):
        response = client.post(route) if route.endswith("clasificar") else client.get(route)
        assert response.status_code == 401
        assert response.json["login_url"] == "/login"
    assert client.get("/login").status_code == 200
    assert client.get("/registro").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/health").status_code in {200, 503}


def test_registro_hash_sesion_y_salida(client, cuentas):
    before = token(client, "/registro")
    assert registro(client).status_code == 302
    user = cuentas.records["ana@example.test"]
    assert check_password_hash(user["password_hash"], PASSWORD)
    assert user["password_hash"] != PASSWORD and user["password_hash"].startswith("scrypt:")
    assert "password" not in user and "confirmar_password" not in user
    assert user["created_at"].tzinfo is not None
    with client.session_transaction() as signed:
        assert signed["user_id"] == str(user["_id"])
        assert signed["csrf_token"] != before
        assert "email" not in signed and "password_hash" not in signed
        csrf = signed["csrf_token"]
    page = client.get("/")
    assert page.status_code == 200 and "Ana Ambiental" in page.get_data(as_text=True)
    assert client.post("/logout", data={"csrf_token": csrf}).status_code == 302
    assert client.get("/api/historial").status_code == 401


def test_login_normaliza_correo_y_rechaza_password(client, cuentas):
    registro(client)
    client = api.app.test_client()
    csrf = token(client)
    response = client.post("/login", data={"email": " ANA@example.test ", "password": "incorrecta", "csrf_token": csrf})
    assert response.status_code == 401
    assert "Correo o contraseña incorrectos" in response.get_data(as_text=True)
    response = client.post("/login", data={"email": " ANA@example.test ", "password": PASSWORD, "csrf_token": csrf})
    assert response.status_code == 302
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("changes", [{"nombre": "A"}, {"email": "no-es-correo"}, {"password": "corta", "confirmar_password": "corta"}, {"confirmar_password": "diferente"}])
def test_validacion_registro(client, cuentas, changes):
    assert registro(client, **changes).status_code == 400
    assert not cuentas.records


def test_correo_duplicado_case_insensitive(client, cuentas):
    assert registro(client).status_code == 302
    second = api.app.test_client()
    assert registro(second, email="ANA@EXAMPLE.TEST").status_code == 409
    assert len(cuentas.records) == 1


def test_csrf_faltante_incorrecto_y_unicode(client, cuentas):
    token(client)
    for csrf in ("", "incorrecto", "áéí"):
        assert client.post("/login", data={"csrf_token": csrf}).status_code == 403
    registro(client)
    assert client.post("/api/clasificar").status_code == 403
    assert client.post("/logout").status_code == 403
    assert client.get("/").status_code == 200


def test_no_hay_redireccion_externa(client):
    assert registro(client).status_code == 302
    assert client.get("/login?next=https://example.test").location == "/"


def test_sesion_manipulada_rechazada(client):
    token(client)
    response = client.get("/login")
    cookie = response.headers.get("Set-Cookie", "")
    # Otra aplicación con otra clave no puede firmar una identidad válida aquí.
    from flask.sessions import SecureCookieSessionInterface
    from flask import Flask
    other = Flask("otro")
    other.secret_key = "otra-clave-solo-prueba"
    forged = SecureCookieSessionInterface().get_signing_serializer(other).dumps({"user_id": "a" * 24})
    client.set_cookie("session", forged)
    assert client.get("/api/historial").status_code == 401


def test_headers_y_cookie(client):
    response = client.get("/login")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_login_rate_limit(client):
    csrf = token(client)
    for _ in range(10):
        assert client.post("/login", data={"email": "nadie@example.test", "password": PASSWORD, "csrf_token": csrf}).status_code == 401
    assert client.post("/login", data={"email": "nadie@example.test", "password": PASSWORD, "csrf_token": csrf}).status_code == 429


def test_mongo_caido_no_crea_sesion(client, monkeypatch):
    def unavailable():
        raise RuntimeError("NO_EXHIBIR_URI")
    monkeypatch.setattr(db, "usuarios", unavailable)
    response = registro(client)
    assert response.status_code == 503
    assert "NO_EXHIBIR_URI" not in response.get_data(as_text=True)
    with client.session_transaction() as signed:
        assert "user_id" not in signed


def test_historial_estadisticas_aislados(client, monkeypatch):
    registro(client)
    with client.session_transaction() as signed:
        uid = signed["user_id"]
    history = MagicMock(return_value={"registros": []})
    stats = MagicMock(return_value={"total": 0})
    monkeypatch.setattr(api, "historial", history)
    monkeypatch.setattr(api, "estadisticas", stats)
    client.get("/api/historial?user_id=otro&limit=10")
    client.get("/api/estadisticas?user_id=otro")
    history.assert_called_once_with(10, uid)
    stats.assert_called_once_with(uid)


def test_registro_escapa_html(client):
    registro(client, nombre="<script>alert(1)</script>")
    html = client.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
