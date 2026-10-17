"""Cuentas MongoDB, sesiones firmadas y protección de formularios."""
import hmac
import os
import re
import secrets
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

import almacenamiento

auth = Blueprint("auth", __name__)
_attempts = OrderedDict()
_attempt_lock = Lock()
_dummy_hash = generate_password_hash(secrets.token_urlsafe(24), method="scrypt")


def _limited(kind):
    """Límite acotado en memoria por IP, sin almacenar IP en MongoDB o logs."""
    now = monotonic()
    key = (kind, request.remote_addr)
    window, maximum = (900, 5) if kind == "registro" else (300, 10)
    with _attempt_lock:
        start, count = _attempts.pop(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        _attempts[key] = (start, count + 1)
        while len(_attempts) > 2048:
            _attempts.popitem(last=False)
        return count >= maximum


def _form(kind, error=None, status=200):
    return render_template("auth.html", registro=kind == "registro", error=error,
                           nombre=request.form.get("nombre", "")[:80],
                           email=request.form.get("email", "")[:254]), status


def _identity(user):
    # No incluir correo ni hashes en la cookie de sesión (firmada, no cifrada).
    session.clear()
    session.permanent = True
    session["user_id"] = str(user["_id"])
    session["nombre"] = user["nombre"]
    session["csrf_token"] = secrets.token_urlsafe(32)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(url_for("inicio"))
    if request.method == "GET":
        return _form("login")
    if _limited("login"):
        return _form("login", "Demasiados intentos. Vuelve a intentar en 5 minutos.", 429)
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if len(email) > 254 or not 1 <= len(password) <= 128:
        return _form("login", "Correo o contraseña incorrectos.", 400)
    try:
        user = almacenamiento.usuarios().find_one({"email": email})
        valid = check_password_hash(user["password_hash"] if user else _dummy_hash, password)
    except Exception:
        return _form("login", "No se pudo acceder a las cuentas. Intenta de nuevo más tarde.", 503)
    if not user or not valid:
        return _form("login", "Correo o contraseña incorrectos.", 401)
    _identity(user)
    return redirect(url_for("inicio"))


@auth.route("/registro", methods=["GET", "POST"])
def registro():
    if g.usuario:
        return redirect(url_for("inicio"))
    if request.method == "GET":
        return _form("registro")
    if _limited("registro"):
        return _form("registro", "Demasiados intentos. Vuelve a intentar en 15 minutos.", 429)
    nombre = request.form.get("nombre", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not 2 <= len(nombre) <= 80:
        return _form("registro", "Escribe un nombre de entre 2 y 80 caracteres.", 400)
    if len(email) > 254 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email):
        return _form("registro", "Escribe un correo electrónico válido.", 400)
    if not 10 <= len(password) <= 128:
        return _form("registro", "La contraseña debe tener entre 10 y 128 caracteres.", 400)
    if password != request.form.get("confirmar_password"):
        return _form("registro", "Las contraseñas no coinciden.", 400)
    user = {"nombre": nombre, "email": email,
            "password_hash": generate_password_hash(password, method="scrypt"),
            "created_at": datetime.now(timezone.utc)}
    try:
        result = almacenamiento.usuarios().insert_one(user)
    except DuplicateKeyError:
        return _form("registro", "No se pudo crear la cuenta con ese correo. Prueba iniciar sesión.", 409)
    except Exception:
        return _form("registro", "No se pudo crear la cuenta. Almacenamiento temporalmente no disponible.", 503)
    user["_id"] = result.inserted_id
    _identity(user)
    return redirect(url_for("inicio"))


@auth.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def configurar_auth(app):
    key = os.environ.get("SECRET_KEY")
    if not key and os.environ.get("RENDER"):
        raise RuntimeError("Configura SECRET_KEY antes de iniciar en Render.")
    app.config.update(SECRET_KEY=key or secrets.token_hex(32),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")) or os.environ.get("COOKIE_SECURE") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      SESSION_REFRESH_EACH_REQUEST=False)
    app.register_blueprint(auth)

    @app.before_request
    def proteger():
        uid = session.get("user_id", "")
        g.usuario = {"id": uid, "nombre": session.get("nombre", "Usuario")} if isinstance(uid, str) and re.fullmatch(r"[a-f0-9]{24}", uid) else None
        if request.endpoint in {"static", "health"}:
            return None
        public = request.endpoint in {"auth.login", "auth.registro"}
        if not public and not g.usuario:
            if request.path.startswith("/api/"):
                return jsonify(error="Inicia sesión para continuar.", login_url=url_for("auth.login")), 401
            return redirect(url_for("auth.login"))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not isinstance(supplied, str) or not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
                if request.path.startswith("/api/"):
                    return jsonify(error="La sesión del formulario venció. Recarga la página."), 403
                return _form("registro" if request.endpoint == "auth.registro" else "login",
                             "El formulario venció. Recarga la página e inténtalo otra vez.", 403)
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)

    @app.context_processor
    def contexto_auth():
        return {"usuario": getattr(g, "usuario", None), "csrf_token": session.get("csrf_token", "")}

    @app.after_request
    def cabeceras_seguras(response):
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        return response
