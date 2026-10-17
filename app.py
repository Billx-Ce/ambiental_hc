"""Entrada de desarrollo y Gunicorn: gunicorn app:app."""
from inferencia_ambiental import app, main, preparar_modelo

preparar_modelo()

if __name__ == "__main__":
    main()
