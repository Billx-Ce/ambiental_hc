"""Servidor local de clasificación ambiental con Flask."""

from io import BytesIO
from pathlib import Path
from threading import RLock
from time import perf_counter

import os
import math

from almacenamiento import guardar, estado_almacenamiento, historial, estadisticas
from motores import crear_motor
from autenticacion import configurar_auth
from PIL import Image, ImageOps, UnidentifiedImageError

# Conservar el lector original de Pillow antes de importar Ultralytics.
abrir_imagen = Image.open

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException



# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE = Path(__file__).resolve().parent
MODELO = BASE / "modelo_ambiental_best.pt"

ETIQUETAS = {
    "basura": "Basura",
    "deforestacion": "Deforestación",
    "incendio": "Incendio",
}

TAMANO_MAXIMO = 10 * 1024 * 1024
UMBRAL_CONFIANZA = 0.75
UMBRAL_GUARDADO = 0.60
UMBRAL_ADVERTENCIA = 0.90

# Evita imágenes extremadamente grandes que puedan consumir mucha memoria.
Image.MAX_IMAGE_PIXELS = 25_000_000

DISPOSITIVO = "pendiente"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 11 * 1024 * 1024
configurar_auth(app)

bloqueo = RLock()
modelo = None
estado_modelo = "pendiente"


# ============================================================
# MODELO
# ============================================================

def cargar_modelo():
    """Carga el modelo una sola vez y realiza una inferencia inicial."""

    global modelo, DISPOSITIVO, estado_modelo
    with bloqueo:
        if modelo is not None:
            return modelo
        estado_modelo = "cargando"
        try:
            candidato = crear_motor(BASE)
            candidato.predict(Image.new("RGB", (224, 224), color="white"),
                              imgsz=224, device=candidato.device, verbose=False)
            DISPOSITIVO = candidato.device
            modelo = candidato
            estado_modelo = "disponible"
            return modelo
        except Exception:
            estado_modelo = "error"
            raise


def preparar_modelo():
    """Inicialización de cada proceso WSGI, sin impedir diagnosticar un fallo."""
    try:
        cargar_modelo()
    except Exception:
        app.logger.error("Modelo no disponible. Compruebe archivo, dependencias y memoria.")


# ============================================================
# UTILIDADES
# ============================================================

def traducir_etiqueta(nombre):
    """Convierte el nombre interno del modelo en un texto legible."""

    return ETIQUETAS.get(nombre, nombre.replace("_", " ").capitalize())


def evaluar_resultado(categorias, umbral=UMBRAL_CONFIANZA):
    """
    Determina si la predicción puede considerarse concluyente.

    Este filtro reduce falsos positivos, pero no sustituye una clase
    de entrenamiento denominada 'sin_contaminacion'.
    """

    mejor = categorias[0]
    confianza = mejor["probabilidad"]

    if confianza < UMBRAL_GUARDADO:
        return {
            "categoria": "No detectado", "es_concluyente": False,
            "nivel_confianza": "baja",
            "mensaje": "No detectado: la confianza es menor al 60 %. Este resultado no se guarda en MongoDB.",
        }

    if confianza < umbral:
        return {
            "categoria": "No concluyente",
            "es_concluyente": False,
            "nivel_confianza": "baja",
            "mensaje": (
                "La imagen no coincide con suficiente seguridad con las categorías conocidas"
            ),
        }

    if confianza < UMBRAL_ADVERTENCIA:
        nivel = "moderada"
        mensaje = (
            "La clasificación es probable, pero se recomienda "
            "una revisión humana."
        )
    else:
        nivel = "alta"
        mensaje = "Resultado del modelo. Requiere verificación humana."

    return {
        "categoria": mejor["nombre"],
        "es_concluyente": True,
        "nivel_confianza": nivel,
        "mensaje": mensaje,
    }


# ============================================================
# RUTAS
# ============================================================

@app.get("/")
def inicio():
    return render_template("index.html")


@app.get("/api/estado")
def estado():
    """Permite comprobar que el servidor y el modelo están disponibles."""

    try:
        with bloqueo:
            motor = cargar_modelo()

        return jsonify(
            estado="disponible",
            modelo=motor.model_name,
            tipo=motor.task,
            dispositivo=DISPOSITIVO,
            umbral_confianza=UMBRAL_CONFIANZA,
            clases=list(ETIQUETAS.values()),
            almacenamiento=estado_almacenamiento(verificar=True),
            motor=os.environ.get("INFERENCE_BACKEND", "pt"),
        )

    except Exception:
        app.logger.error("No se pudo cargar el modelo. Verifique archivo y dependencias.")

        return jsonify(
            estado="error",
            error="No se pudo cargar el modelo.",
        ), 500



@app.get("/health")
def health():
    # Solo memoria: no espera el lock, no infiere ni consulta MongoDB.
    listo = modelo is not None
    return jsonify(estado="disponible" if listo else "no_preparado",
                   servidor="disponible", estado_modelo=estado_modelo,
                   almacenamiento=estado_almacenamiento(),
                   modelo=modelo.model_name if listo else MODELO.name), 200 if listo else 503


@app.get("/api/historial")
def obtener_historial():
    try:
        limite = int(request.args.get("limit", 50))
        if not 1 <= limite <= 100:
            raise ValueError
    except ValueError:
        return jsonify(error="limit debe ser un entero entre 1 y 100."), 400
    return jsonify(historial(limite, g.usuario["id"]))


@app.get("/api/estadisticas")
def obtener_estadisticas():
    return jsonify(estadisticas(g.usuario["id"]))


@app.errorhandler(413)
def demasiado_grande(error):
    return jsonify(
        error="La imagen supera el límite permitido de 10 MB."
    ), 413


@app.errorhandler(HTTPException)
def error_http(error):
    mensajes = {400: "Solicitud inválida.", 404: "Ruta no encontrada.",
                405: "Método no permitido para esta ruta."}
    return jsonify(error=mensajes.get(error.code, "No se pudo procesar la solicitud.")), error.code


@app.post("/api/clasificar")
def clasificar():
    archivo = request.files.get("imagen")

    if archivo is None:
        return jsonify(
            error="Selecciona una imagen."
        ), 400

    fuente = request.form.get("origen", "upload")
    if fuente not in {"upload", "camera"}:
        return jsonify(error="Origen de imagen inválido."), 400

    try:
        umbral = float(request.form.get("umbral", UMBRAL_CONFIANZA))
        if not math.isfinite(umbral) or not UMBRAL_GUARDADO <= umbral <= 1:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify(error="El umbral debe ser un número entre 0.60 y 1.00."), 400

    datos = archivo.read(TAMANO_MAXIMO + 1)

    if not datos:
        return jsonify(
            error="El archivo está vacío."
        ), 400

    if len(datos) > TAMANO_MAXIMO:
        return jsonify(
            error="La imagen supera el límite permitido de 10 MB."
        ), 413

    try:
        with abrir_imagen(BytesIO(datos)) as original:
            formato = original.format

            if formato not in {"JPEG", "PNG", "WEBP", "BMP"}:
                return jsonify(
                    error="Usa una imagen JPG, PNG, WEBP o BMP."
                ), 400

            if original.width * original.height > Image.MAX_IMAGE_PIXELS:
                raise Image.DecompressionBombError
            original.verify()
        with abrir_imagen(BytesIO(datos)) as original:
            imagen = ImageOps.exif_transpose(original).convert("RGB")

    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return jsonify(
            error="La imagen tiene dimensiones excesivamente grandes."
        ), 400

    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return jsonify(
            error="El archivo no es una imagen válida."
        ), 400

    try:
        with bloqueo:
            motor = cargar_modelo()

            inicio_tiempo = perf_counter()

            resultado = motor.predict(
                imagen,
                imgsz=224,
                device=DISPOSITIVO,
                verbose=False,
            )[0]

            tiempo_ms = round(
                (perf_counter() - inicio_tiempo) * 1000,
                1,
            )

        if resultado.probs is None:
            raise RuntimeError(
                "El modelo no devolvió probabilidades de clasificación."
            )

        probabilidades = resultado.probs.data.cpu().tolist()
        if (len(probabilidades) != 3 or
                any(not math.isfinite(p) or p < 0 or p > 1 for p in probabilidades) or
                abs(sum(probabilidades) - 1) > 0.01):
            raise ValueError("Probabilidades inválidas.")

        categorias = []

        for indice, probabilidad in enumerate(probabilidades):
            nombre_interno = resultado.names[indice]

            categorias.append({
                "nombre": traducir_etiqueta(nombre_interno),
                "nombre_interno": nombre_interno,
                "probabilidad": float(probabilidad),
                "porcentaje": round(float(probabilidad) * 100, 2),
            })

        categorias.sort(
            key=lambda categoria: categoria["probabilidad"],
            reverse=True,
        )

        evaluacion = evaluar_resultado(categorias, umbral)
        mejor_prediccion = categorias[0]

        registro = {
            "user_id": g.usuario["id"],
            "source": fuente,
            "predicted_class": mejor_prediccion["nombre_interno"],
            "displayed_category": evaluacion["categoria"],
            "confidence": mejor_prediccion["probabilidad"],
            "is_conclusive": evaluacion["es_concluyente"],
            "confidence_level": evaluacion["nivel_confianza"],
            "inference_time_ms": tiempo_ms,
            "probabilities": {c["nombre_interno"]: c["probabilidad"] for c in categorias},
            "model_name": modelo.model_name,
            "device": DISPOSITIVO,
            "confidence_threshold": umbral,
        }
        if mejor_prediccion["probabilidad"] < UMBRAL_GUARDADO:
            almacenamiento = {**estado_almacenamiento(), "guardado": False,
                              "motivo": "confianza_baja",
                              "mensaje": "No guardado: confianza menor al 60 %."}
        else:
            almacenamiento = guardar(registro)
        return jsonify(
            almacenamiento=almacenamiento,
            almacenamiento_guardado=almacenamiento["guardado"],
            categoria=evaluacion["categoria"],
            confianza=mejor_prediccion["probabilidad"],
            porcentaje=mejor_prediccion["porcentaje"],
            es_concluyente=evaluacion["es_concluyente"],
            nivel_confianza=evaluacion["nivel_confianza"],
            mensaje=evaluacion["mensaje"],
            prediccion_modelo=mejor_prediccion["nombre"],
            categorias=categorias,
            tiempo_ms=tiempo_ms,
            dispositivo=DISPOSITIVO,
            umbral_confianza=umbral,
            umbral_guardado=UMBRAL_GUARDADO,
        )

    except Exception:
        app.logger.error("Error durante la inferencia. Verifique el modelo y la memoria disponible.")

        return jsonify(
            error=(
                "No se pudo analizar la imagen. "
                "Revisa la consola del servidor."
            )
        ), 500


# ============================================================
# EJECUCIÓN
# ============================================================

def main():
    print("Cargando modelo...")

    with bloqueo:
        cargar_modelo()

    print(f"Modelo: {modelo.model_name}")
    print(f"Dispositivo: {DISPOSITIVO}")
    print(f"Umbral mínimo: {UMBRAL_CONFIANZA * 100:.0f}%")
    print(f"Abre http://localhost:{os.environ.get('PORT', 5000)} en tu navegador.")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
