# Verificación local · 16 de octubre de 2026

## Registro e inicio de sesión

Se agregaron `/registro`, `/login` y `/logout`, con contraseñas scrypt, cookie
firmada de 8 horas, protección CSRF, cabeceras de seguridad y límites de intentos.
Las rutas de aplicación requieren sesión y el servidor asigna `user_id` a los
resultados. Historial y agregaciones filtran por ese identificador. Los registros
anteriores sin propietario no se asignaron ni borraron.

**70 pruebas backend aprobadas**, también con Flask 3.1.3 y Werkzeug 3.1.9
instalados en una carpeta aislada de pruebas. Cubren registro válido e inválido,
hash de contraseña, duplicado de correo normalizado, login correcto/incorrecto,
cookie manipulada, CSRF, cierre de sesión, cabeceras, límites de intentos,
caída de MongoDB, salida HTML escapada y separación de consultas por usuario,
además de todas las verificaciones de clasificación previas.

Se comprobó en Atlas la colección `usuarios` y su índice único de correo, sin
crear cuentas reales de prueba. Se aumentó a 5 s la selección/conexión inicial
para permitir el establecimiento de conexión al clúster observado. Las cuentas
de las pruebas de navegador existen solo en memoria del servidor de pruebas.
La clave `SECRET_KEY` local se generó en `.env` privado y se excluye del ZIP.
El historial previo de verificaciones que aparece abajo no sustituye esta
actualización ni indica el estado actual de la conexión.

## Umbral ajustable y mínimo de guardado

Se agregaron pruebas del corte fijo de almacenamiento en 60 % para cámara y
carga manual (59,99 %, 60 % y 61 %). Por debajo del corte el resultado es
«No detectado» y se comprueba que no se llama al guardado. El control de
clasificación permite 60–100 %, con 75 % predeterminado, y se valida también
en el servidor, rechazando valores inválidos, NaN e infinito. El backend
actualizado tiene **54 pruebas aprobadas**. El campo `confidence_threshold`
registra el umbral aplicado sin modificar los pesos del modelo.

## Actualización de interfaz de cámara

Por solicitud del usuario, el modo cámara presenta un único bloque con video en
vivo y la categoría y tres barras de probabilidad debajo. Se eliminó la foto fija
y el panel lateral para cámara. La carga manual conserva su vista previa.
Los fotogramas temporales se procesan internamente y no se muestran ni se guardan
como imágenes. No se modificó el modelo ni el almacenamiento de metadatos.
La prueba de navegador se adaptó para comprobar video visible, tres barras,
ausencia de `src` en la foto de resultado de cámara y tamaño de envío interno.
Las referencias a mostrar fotogramas en el registro inicial de abajo describen
la interfaz anterior.

## Actualización de conexión MongoDB

Se agregó carga automática del archivo local `.env`, excluido de Git y del ZIP,
con prioridad para variables del entorno. El usuario autorizó una prueba real
contra Atlas. El clúster respondió, pero rechazó la autenticación (`bad auth`,
código 8000). No se insertaron registros. Falta corregir la credencial privada
y reiniciar el servidor. `scripts/verificar_mongo.py` permite repetir la prueba
sin mostrar la URI. Las verificaciones descritas abajo corresponden a la entrega
local previa y no implican que la conexión actual esté autenticada.

## Resultado

- Backend: **38 pruebas aprobadas**, `python -m pytest -q`, 10,36 s en esta máquina.
- Navegador: **10 grupos de comprobaciones aprobados** en Chrome headless con
  cámara sintética de Chromium. Sin errores JavaScript de página.
- Compilación Python y sintaxis JavaScript comprobadas.
- Fuentes revisadas sin URI MongoDB, claves privadas, contraseñas asignadas ni
  referencias a las categorías antiguas. `.env.example` tiene URI vacía.
- El modelo `.pt` no fue modificado, sustituido ni reentrenado.

## Backend cubierto

`/health` no carga ni ejecuta el modelo y no consulta MongoDB. `/api/estado`, página
y estáticos funcionan. Validación de archivo ausente, vacío, corrupto, checksum PNG,
formato real, JPG/JPEG/PNG/WEBP/BMP, tamaño de archivo, píxeles y orientación EXIF.
Umbral controlado a 74,99 %, 75 % y 90 %, con contrato JSON completo. Sin MongoDB
no se crea ningún cliente y las rutas devuelven `no_configurado` sin error 500.

Pruebas con dobles de PyMongo: registro UTC, serialización de ObjectId/fechas,
estadísticas, conexión fallida simulada, mensajes sin secretos y pausa de reintento.
Cuatro clasificaciones concurrentes comprueban carga única, un calentamiento y
máximo una inferencia activa. Dos peticiones con el modelo real comprueban tarea,
clases, probabilidades y reutilización de la misma instancia.

Las imágenes sintéticas de prueba validan ejecución, no exactitud ambiental.

## Navegador cubierto

1. Inicio sin MongoDB y sin datos ficticios.
2. Carga manual con inferencia real, vista previa y tres probabilidades.
3. Resultado no concluyente controlado con predicción interna separada.
4. Cámara sintética con respuestas retrasadas 1,8 s, un máximo de una petición
   activa y descarte de respuestas tardías al detener.
5. Hash SHA-256 del archivo/fotograma mostrado igual al enviado, resolución
   máxima de 640 píxeles y captura periódica sin superposición.
6. Selector de dispositivo, orientación y cambio de modo liberan pistas anteriores.
7. Anchos 390, 768 y 1440 sin desbordamiento horizontal; capturas revisadas visualmente.
8. Permiso denegado y ausencia de cámara con mensajes comprensibles.
9. Error del servidor con recuperación de controles.
10. Evento de abandono libera todas las pistas.

Las respuestas controladas existen solo dentro de las pruebas del navegador,
sin insertarse en el historial ni mostrarse como datos reales de producción.

## Entorno y comprobaciones pendientes

Python 3.11.9 en Windows, Ultralytics 8.4.51, PyTorch 2.12.0, torchvision 0.27.0,
Flask 2.3.2, Pillow 12.2.0 y PyMongo 4.17.0. Inferencia probada en CPU.

- No se accedió a una cámara física. Debe probarse después la cámara real y la
  alternancia entre varios dispositivos físicos, especialmente en Android/iOS.
- No se conectó MongoDB Atlas. Las consultas/agregaciones se probaron con dobles,
  por lo que falta verificar permisos, red, índices y resultados con un clúster real.
- No se desplegó en Render. Falta medir arranque, memoria y tiempos en ese entorno.
- Entrada WSGI `app:app` comprobada. Gunicorn no se ejecutó en Windows porque
  requiere Unix. Su ejecución real queda pendiente en Linux/Render.
- Script ONNX preparado, sin ejecutar la exportación ni validar paridad numérica.
- No se evaluó exactitud sobre imágenes externas ni se reprodujo el entrenamiento.
- Esta carpeta no era un repositorio Git. Se prepararon exclusiones y un ZIP por
  lista permitida, sin crear commits ni publicar un repositorio.

## Modelo y empaquetado

SHA-256 del archivo entregado `modelo_ambiental_best.pt`:

```text
b6021b3ab464b547e7bdb8fcd7dd9be1241674ba8c9231a9a20bdc4a3205105b
```

`python scripts/empaquetar.py` crea `dist/ambiental_proyecto.zip`, comprueba su
integridad CRC, su lista de entradas y que el modelo comprimido sea idéntico al
archivo del proyecto. Incluye fuentes, modelo, pruebas, configuración y documentación.
Excluye `.env`, cachés, dependencias instaladas, capturas, datasets y otros ZIP.
