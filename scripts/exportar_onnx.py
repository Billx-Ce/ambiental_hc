"""Exportación futura explícita del mismo .pt. No entrena ni sustituye el modelo."""
import hashlib
import json
from pathlib import Path


def main():
    from ultralytics import YOLO
    base = Path(__file__).resolve().parents[1]
    source = base / "modelo_ambiental_best.pt"
    model = YOLO(str(source))
    if model.task != "classify" or set(model.names.values()) != {"basura", "incendio", "deforestacion"}:
        raise ValueError("Se requiere el clasificador ambiental original.")
    output = Path(model.export(format="onnx", imgsz=224, batch=1, dynamic=False,
                               simplify=False, opset=17, device="cpu"))
    manifest = {"source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "export": output.name, "export_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "classes": model.names, "imgsz": 224, "opset": 17,
                "note": "Validar paridad con el .pt y datos externos antes de producción."}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exportado {output.name}. El archivo .pt permanece intacto.")


if __name__ == "__main__":
    main()
