"""ZIP reproducible por lista permitida. Nunca incluye .env, cachés o datasets."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

BASE = Path(__file__).resolve().parents[1]
ARCHIVOS = [
    "app.py", "iniciar_web.py", "inferencia_ambiental.py", "almacenamiento.py",
    "motores.py", "autenticacion.py", "modelo_ambiental_best.pt", "requirements.txt",
    "requirements-dev.txt", "requirements-onnx.txt", "render.yaml", "Procfile",
    ".env.example", ".gitignore", ".python-version", "README.md",
    "VERIFICACION.md", "pytest.ini", "templates/index.html", "static/app.css",
    "static/app.js", "scripts/exportar_onnx.py", "scripts/empaquetar.py",
    "scripts/verificar_mongo.py",
    "tests/test_backend.py", "tests/test_auth.py", "tests/verificar_navegador.cjs",
    "tests/servidor_navegador.py", "templates/auth.html", "static/auth.js",
]


def main():
    target = BASE / "dist" / "ambiental_proyecto.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in ARCHIVOS:
            archive.write(BASE / name, arcname="ambiental/" + name)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(ARCHIVOS)
        assert archive.read("ambiental/modelo_ambiental_best.pt") == (BASE / "modelo_ambiental_best.pt").read_bytes()
    print(f"ZIP verificado: {target}")
    print(f"SHA256: {sha256(target.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
