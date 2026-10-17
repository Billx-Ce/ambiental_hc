"""Pruebas sin red ni credenciales. Las inferencias controladas prueban el contrato."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from threading import Lock
from time import sleep
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from flask import Flask
from PIL import Image

import almacenamiento as db
import inferencia_ambiental as api


class Datos:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class MotorControlado:
    task = "classify"
    device = "cpu"
    model_name = "modelo_ambiental_best.pt"

    def __init__(self, probabilities=(0.8, 0.1, 0.1)):
        self.probabilities = probabilities
        self.calls = 0
        self.sizes = []

    def predict(self, image, **kwargs):
        self.calls += 1
        self.sizes.append(image.size)
        return [SimpleNamespace(names={0: "basura", 1: "incendio", 2: "deforestacion"},
                                probs=SimpleNamespace(data=Datos(self.probabilities)))]


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setattr(db, "_client", None)
    monkeypatch.setattr(db, "_collection", None)
    monkeypatch.setattr(db, "_retry_at", 0)
    monkeypatch.setattr(db, "_available", False)
    client = MagicMock(side_effect=AssertionError("No se permite una conexión real en pruebas"))
    monkeypatch.setattr(db, "MongoClient", client)


@pytest.fixture
def motor(monkeypatch):
    instance = MotorControlado()
    monkeypatch.setattr(api, "modelo", instance)
    monkeypatch.setattr(api, "estado_modelo", "disponible")
    monkeypatch.setattr(api, "DISPOSITIVO", "cpu")
    return instance


@pytest.fixture
def client(motor):
    return autenticar(api.app.test_client())


def autenticar(client):
    with client.session_transaction() as signed:
        signed["user_id"] = "0" * 24
        signed["nombre"] = "Cuenta de pruebas"
        signed["csrf_token"] = "csrf-prueba"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "csrf-prueba"
    return client


def imagen(format="PNG", size=(32, 24), exif=None):
    data = BytesIO()
    Image.new("RGB", size, "green").save(data, format=format, **({"exif": exif} if exif else {}))
    data.seek(0)
    return data


def enviar(client, content=None, name="imagen.png", origen="upload"):
    return client.post("/api/clasificar", data={"imagen": (content or imagen(), name), "origen": origen})


def test_health_rapido_no_infiere_ni_conecta(client, motor, monkeypatch):
    monkeypatch.setattr(api, "cargar_modelo", MagicMock(side_effect=AssertionError("Health no debe cargar")))
    for _ in range(3):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json["estado_modelo"] == "disponible"
        assert response.json["servidor"] == "disponible"
        assert response.json["almacenamiento"]["estado"] == "no_configurado"
    assert motor.calls == 0
    db.MongoClient.assert_not_called()


def test_health_modelo_fallido(client, monkeypatch):
    monkeypatch.setattr(api, "modelo", None)
    monkeypatch.setattr(api, "estado_modelo", "error")
    assert client.get("/health").status_code == 503


def test_estado_y_pagina(client):
    response = client.get("/api/estado")
    assert response.status_code == 200
    assert response.json["tipo"] == "classify"
    assert set(response.json["clases"]) == {"Basura", "Incendio", "Deforestación"}
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_archivo_ausente(client):
    assert client.post("/api/clasificar").status_code == 400


@pytest.mark.parametrize("content", [b"", b"esto no es una imagen", b"\x89PNG\r\n\x1a\n"])
def test_archivo_vacio_o_corrupto(client, content):
    response = enviar(client, BytesIO(content))
    assert response.status_code == 400
    assert "error" in response.json


def test_formato_real_no_extension(client):
    assert enviar(client, imagen("GIF"), "falso.jpg").status_code == 400
    assert enviar(client, imagen("PNG"), "archivo.jpg").status_code == 200


def test_png_checksum_corrupto(client):
    data = bytearray(imagen().getvalue())
    position = data.index(b"IDAT")
    data[position + 5] ^= 1
    assert enviar(client, BytesIO(data)).status_code == 400


@pytest.mark.parametrize("format,extension", [("JPEG", "jpg"), ("JPEG", "jpeg"), ("PNG", "png"), ("WEBP", "webp"), ("BMP", "bmp")])
def test_formatos_permitidos(client, format, extension):
    response = enviar(client, imagen(format), "archivo." + extension)
    assert response.status_code == 200
    assert len(response.json["categorias"]) == 3


@pytest.mark.parametrize("length", [10 * 1024 * 1024 + 1, 12 * 1024 * 1024])
def test_limite_bytes(client, length):
    response = enviar(client, BytesIO(b"x" * length))
    assert response.status_code == 413
    assert response.is_json


def test_limite_pixeles(client, monkeypatch):
    image = imagen(size=(20, 20))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    assert enviar(client, image).status_code == 400


def test_orientacion_exif(client, motor):
    exif = Image.Exif()
    exif[274] = 6
    assert enviar(client, imagen("JPEG", (40, 20), exif)).status_code == 200
    assert motor.sizes[-1] == (20, 40)


@pytest.mark.parametrize("confidence,expected,level", [(0.7499, False, "baja"), (0.75, True, "moderada"), (0.90, True, "alta")])
def test_umbral_y_contrato(client, motor, confidence, expected, level):
    motor.probabilities = (confidence, (1 - confidence) / 2, (1 - confidence) / 2)
    response = enviar(client)
    assert response.status_code == 200
    result = response.json
    required = {"categoria", "confianza", "porcentaje", "es_concluyente", "nivel_confianza", "mensaje", "prediccion_modelo", "categorias", "tiempo_ms", "dispositivo", "umbral_confianza", "almacenamiento_guardado"}
    assert required <= result.keys()
    assert result["es_concluyente"] is expected
    assert result["categoria"] == ("Basura" if expected else "No concluyente")
    assert result["nivel_confianza"] == level
    assert result["prediccion_modelo"] == "Basura"
    assert result["almacenamiento_guardado"] is False
    assert result["almacenamiento"]["estado"] == "no_configurado"
    if not expected:
        assert result["mensaje"] == "La imagen no coincide con suficiente seguridad con las categorías conocidas"


@pytest.mark.parametrize("origen", ["upload", "camera"])
@pytest.mark.parametrize("confianza,guardado", [(0.5999, False), (0.60, True), (0.61, True)])
def test_minimo_guardado_60(client, motor, monkeypatch, origen, confianza, guardado):
    motor.probabilities = (confianza, (1 - confianza) / 2, (1 - confianza) / 2)
    save = MagicMock(return_value={"guardado": True})
    monkeypatch.setattr(api, "guardar", save)
    result = enviar(client, origen=origen).json
    assert result["almacenamiento_guardado"] is guardado
    assert save.call_count == int(guardado)
    if not guardado:
        assert result["categoria"] == "No detectado"
        assert result["es_concluyente"] is False
        assert result["almacenamiento"]["motivo"] == "confianza_baja"
        db.MongoClient.assert_not_called()


@pytest.mark.parametrize("umbral,concluyente", [("0.60", True), ("0.70", True), ("0.71", False), ("1", False)])
def test_umbral_ajustable(client, motor, monkeypatch, umbral, concluyente):
    motor.probabilities = (.7, .2, .1)
    save = MagicMock(return_value={"guardado": True})
    monkeypatch.setattr(api, "guardar", save)
    result = client.post("/api/clasificar", data={"imagen": (imagen(), "foto.png"), "umbral": umbral}).json
    assert result["es_concluyente"] is concluyente
    assert result["umbral_confianza"] == float(umbral)
    assert result["almacenamiento_guardado"] is True
    assert save.call_args.args[0]["confidence_threshold"] == float(umbral)


@pytest.mark.parametrize("umbral", ["0.59", "1.01", "nan", "inf", "texto", ""])
def test_umbral_invalido(client, umbral):
    assert client.post("/api/clasificar", data={"imagen": (imagen(), "foto.png"), "umbral": umbral}).status_code == 400


def test_origen(client, monkeypatch):
    save = MagicMock(return_value={"guardado": True})
    monkeypatch.setattr(api, "guardar", save)
    for origin in ("upload", "camera"):
        assert enviar(client, origen=origin).status_code == 200
        assert save.call_args.args[0]["source"] == origin
    assert enviar(client, origen="otro").status_code == 400
    assert client.post("/api/clasificar", data={"imagen": (imagen(), "foto.png")}).status_code == 200
    assert save.call_args.args[0]["source"] == "upload"


@pytest.mark.parametrize("limit", ["0", "101", "-1", "1.5", "texto", ""])
def test_limite_historial_invalido(client, limit):
    assert client.get("/api/historial?limit=" + limit).status_code == 400


@pytest.mark.parametrize("limit", [1, 50, 100])
def test_historial_sin_db(client, limit):
    response = client.get(f"/api/historial?limit={limit}")
    assert response.status_code == 200
    assert response.json["estado"] == "no_configurado"
    assert response.json["registros"] == []
    assert client.get("/api/estadisticas").json["estado"] == "no_configurado"
    db.MongoClient.assert_not_called()


def test_guardado_y_serializacion_mongo_simulado(monkeypatch):
    collection = MagicMock()
    monkeypatch.setattr(db, "_connect", lambda: collection)
    assert db.guardar({"source": "camera", "confidence": .8})["guardado"] is True
    record = collection.insert_one.call_args.args[0]
    assert record["created_at"].tzinfo is timezone.utc
    assert set(record) == {"source", "confidence", "created_at"}
    oid = ObjectId()
    collection.find.return_value.sort.return_value.limit.return_value = [{"_id": oid, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "confidence": .8}]
    result = db.historial(50, "0" * 24)
    collection.find.assert_called_once_with({"user_id": "0" * 24}, {"user_id": 0})
    assert result["registros"][0]["_id"] == str(oid)
    assert result["registros"][0]["created_at"].endswith("+00:00")
    assert result["registros"][0]["confidence"] == .8


def test_estadisticas_mongo_simulado(monkeypatch):
    collection = MagicMock()
    monkeypatch.setattr(db, "_connect", lambda: collection)
    collection.aggregate.return_value = [{"resumen": [{"_id": None, "total": 2, "confianza_promedio": .7, "no_concluyentes": 1}], "categorias": [{"_id": "Basura", "cantidad": 1}, {"_id": "No concluyente", "cantidad": 1}], "fuentes": [{"_id": "camera", "cantidad": 2}]}]
    result = db.estadisticas("0" * 24)
    assert collection.aggregate.call_args.args[0][0] == {"$match": {"user_id": "0" * 24}}
    assert result["total"] == 2 and result["no_concluyentes"] == 1
    assert result["por_fuente"] == {"camera": 2}
    assert result["por_categoria"]["No concluyente"] == 1
    collection.aggregate.return_value = [{"resumen": [], "categorias": [], "fuentes": []}]
    assert db.estadisticas("0" * 24)["total"] == 0


def test_caida_mongo_no_rompe_inferencia(client, monkeypatch, caplog):
    # Marcador deliberadamente inválido. MongoClient siempre está simulado.
    monkeypatch.setenv("MONGODB_URI", "MARCADOR_NO_ES_URI")
    db.MongoClient.side_effect = RuntimeError("SECRETO_SIMULADO")
    response = enviar(client)
    assert response.status_code == 200
    assert response.json["almacenamiento_guardado"] is False
    assert response.json["almacenamiento"]["estado"] == "no_disponible"
    assert "SECRETO_SIMULADO" not in caplog.text
    assert client.get("/api/historial").status_code == 200
    assert client.get("/api/estadisticas").status_code == 200
    assert db.MongoClient.call_count == 1  # circuito de reintentos


def test_lock_y_carga_unica(monkeypatch):
    engine = MotorControlado()
    active = 0
    maximum = 0
    counter_lock = Lock()
    original = engine.predict

    def predict(*args, **kwargs):
        nonlocal active, maximum
        with counter_lock:
            active += 1
            maximum = max(maximum, active)
        sleep(.02)
        result = original(*args, **kwargs)
        with counter_lock:
            active -= 1
        return result

    engine.predict = predict
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(api, "modelo", None)
    monkeypatch.setattr(api, "crear_motor", factory)
    def classify(_):
        with api.app.test_client() as client:
            autenticar(client)
            return enviar(client).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(classify, range(4))) == [200] * 4
    assert factory.call_count == 1
    assert engine.calls == 5  # un calentamiento y cuatro solicitudes
    assert maximum == 1


def test_error_motor_sanitizado(client, motor, monkeypatch):
    monkeypatch.setattr(motor, "predict", MagicMock(side_effect=RuntimeError("DATO_PRIVADO")))
    response = enviar(client)
    assert response.status_code == 500
    assert "DATO_PRIVADO" not in response.get_data(as_text=True)


def test_entrada_wsgi(monkeypatch):
    monkeypatch.setattr(api, "preparar_modelo", lambda: None)
    import app as entry
    assert isinstance(entry.app, Flask)
    assert callable(entry.app.wsgi_app)
    assert entry.app is api.app


def test_modelo_real_dos_solicitudes_sin_recargar(monkeypatch):
    monkeypatch.delenv("INFERENCE_BACKEND", raising=False)
    monkeypatch.setattr(api, "modelo", None)
    engine = api.cargar_modelo()
    assert engine.task == "classify"
    assert set(engine.model.names.values()) == {"basura", "incendio", "deforestacion"}
    with api.app.test_client() as client:
        autenticar(client)
        for _ in range(2):
            response = enviar(client)
            assert response.status_code == 200
            assert abs(sum(c["probabilidad"] for c in response.json["categorias"]) - 1) < .001
    assert api.modelo is engine
