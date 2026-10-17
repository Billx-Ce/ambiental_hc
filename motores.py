"""Mismo modelo entrenado, dos motores explícitos y sin fallback silencioso."""
import ast
import os
from types import SimpleNamespace

CLASES = {"basura", "incendio", "deforestacion"}


class MotorPT:
    def __init__(self, base):
        import torch
        from ultralytics import YOLO
        self.device = "cpu" if os.environ.get("RENDER") else (
            "cuda:0" if torch.cuda.is_available() else "cpu")
        self.model_name = "modelo_ambiental_best.pt"
        self.model = YOLO(str(base / self.model_name))
        self.task = self.model.task
        if self.task != "classify" or set(self.model.names.values()) != CLASES:
            raise ValueError("Se requiere el clasificador ambiental de tres clases.")

    def predict(self, image, **kwargs):
        return self.model.predict(image, **kwargs)


class MotorONNX:
    def __init__(self, base):
        import onnxruntime as ort
        self.device = "cpu"
        self.task = "classify"
        self.model_name = "modelo_ambiental_best.onnx"
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(base / self.model_name), options,
                                           providers=["CPUExecutionProvider"])
        metadata = self.session.get_modelmeta().custom_metadata_map
        self.names = ast.literal_eval(metadata["names"])
        if metadata.get("task") != "classify" or set(self.names.values()) != CLASES:
            raise ValueError("ONNX no corresponde al clasificador ambiental.")

    def predict(self, image, **kwargs):
        import numpy as np
        from PIL import Image
        # Ultralytics 8.4.51: Resize(shortest=224, bilinear), CenterCrop, ToTensor.
        w, h = image.size
        size = (224, int(224 * h / w)) if w <= h else (int(224 * w / h), 224)
        image = image.resize(size, Image.Resampling.BILINEAR)
        left, top = round((size[0] - 224) / 2), round((size[1] - 224) / 2)
        image = image.crop((left, top, left + 224, top + 224))
        tensor = np.asarray(image, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        values = self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0][0]
        if not np.isfinite(values).all() or len(values) != 3:
            raise ValueError("Salida ONNX inválida.")
        # La exportación de clasificación incluye softmax. No aplicarlo dos veces.
        values = values / values.sum()
        class Datos:
            def cpu(self):
                return self
            def tolist(self):
                return values.tolist()
        return [SimpleNamespace(probs=SimpleNamespace(data=Datos()), names=self.names)]


def crear_motor(base):
    backend = os.environ.get("INFERENCE_BACKEND", "pt")
    if backend == "pt":
        return MotorPT(base)
    if backend == "onnx":
        return MotorONNX(base)
    raise ValueError("INFERENCE_BACKEND debe ser pt u onnx.")
