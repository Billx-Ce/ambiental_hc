# Huánuco Ambiental

Aplicación académica para desafíos ambientales de INNOBEST en Huánuco, Perú.
Continúa la aplicación Flask existente y utiliza **el mismo `modelo_ambiental_best.pt`**.
Clasifica imágenes completas como Basura, Incendio o Deforestación. No localiza
objetos ni dibuja recuadros. Toda estimación requiere verificación humana.

## Cuentas e inicio de sesión

La entrada redirige a `/login`. Desde allí puedes ir a `/registro`, introducir
nombre, correo y una contraseña de 10 a 128 caracteres, confirmarla y entrar.
Las cuentas reales se guardan en `ambiental_huanuco.usuarios` (o `MONGODB_DB`).
El correo se normaliza a minúsculas y tiene índice único. Solo se guarda un
hash scrypt de la contraseña, nunca la contraseña original. No hay una cuenta
administradora ni contraseñas predeterminadas.

Se requiere MongoDB disponible para registrar cuentas e iniciar sesión. La
sesión dura hasta 8 horas y permite seguir clasificando si luego cae MongoDB,
indicando que no se guardó el resultado. La cookie contiene solo identificador,
nombre y token de formulario, firmados. Es HttpOnly y SameSite=Lax, y Secure en
Render. La clave privada `SECRET_KEY` se lee de `.env` o del entorno. Se configuró
una clave aleatoria en el `.env` local, excluido de Git/ZIP. Conserva una clave
estable y distinta por entorno. Si falta localmente se genera una temporal por
proceso; en Render su ausencia impide arrancar. `render.yaml` la genera para el
futuro servicio. Para HTTPS fuera de Render configura `COOKIE_SECURE=1`.

La página y `/api/*` requieren sesión. `/health` y los archivos estáticos siguen
públicos. Todos los POST, incluido el cierre de sesión, necesitan token CSRF.
Para una integración propia, toma el token de la sesión y envíalo en
`X-CSRF-Token` junto con la cookie de sesión. Sesión ausente devuelve 401 y token
incorrecto devuelve 403. No se permite seleccionar el propietario mediante
parámetros: el servidor utiliza siempre la cuenta de la sesión.

Cada cuenta consulta solo su historial y estadísticas. Cada nuevo registro
incluye `user_id`. Los registros anteriores sin propietario se conservan en
MongoDB, pero no aparecen en ninguna cuenta. No se reasignaron automáticamente.
Se creó el índice único de correo en Atlas sin crear usuarios de prueba reales.

Hay límites en memoria de 10 intentos de login cada 5 minutos y 5 registros
cada 15 minutos por IP. Son adecuados para el único proceso previsto y se
reinician al reiniciar el servidor. No se persisten IP en la base. No incluye
verificación de correo, recuperación de contraseña ni envío de mensajes.
Cerrar sesión elimina la cookie del navegador; no existe aún un panel para
revocar todas las sesiones en otros dispositivos. Cambiar `SECRET_KEY` invalida
las sesiones existentes.

## Alcance de esta entrega

Desarrollo y pruebas locales. MongoDB y Render quedan preparados para una
configuración posterior. MongoDB está conectado y se comprobaron los índices de
inferencias y cuentas. Se agregó registro/login, probado con cuentas temporales
fuera de Atlas. No se desplegó el servicio. No incluye PowerPoint.

## Instalación y ejecución local

Requiere Python 3.11 y el modelo junto a `app.py`. Desde esta carpeta, en PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Abre **http://localhost:5000** o **http://127.0.0.1:5000**. Detén el servidor con
Ctrl+C. También se conservan `python iniciar_web.py` y `python inferencia_ambiental.py`.
MongoDB es necesario para crear una cuenta y entrar. El primer arranque carga y calienta
el modelo una sola vez por proceso. Las siguientes peticiones lo reutilizan.
PyTorch usa CUDA si la instalación y la GPU local la admiten, y CPU en otro caso.
Cuando Render suministre `RENDER`, el motor utilizará CPU.

Para cambiar el puerto:

```powershell
$env:PORT="5055"
.\.venv\Scripts\python.exe app.py
```

No uses el servidor de desarrollo de Flask como servidor público de producción.

## Prueba de carga manual

1. Selecciona «Subir imagen» y elige JPG, JPEG, PNG, WEBP o BMP de hasta 10 MB.
2. La vista previa aparece al seleccionar. El servidor valida el contenido real,
   rechaza archivos vacíos o corruptos y aplica la orientación EXIF.
3. El resultado muestra la imagen analizada, categoría, confianza, nivel,
   tiempo de inferencia y probabilidades de las tres clases.
4. Por debajo de 60 % aparece «No detectado» y el resultado no se guarda en MongoDB.
   El control de confianza ajusta el umbral concluyente entre 60 % y 100 %
   (predeterminado: 75 %). Entre 60 % y ese umbral aparece «No concluyente» y
   puede guardarse. La predicción interna se muestra por separado.
   Desde el umbral y por debajo de 90 % el nivel es moderado; desde 90 % es alto.
   Para carga manual pulsa «Volver a analizar» después de cambiar el control.
   En cámara se aplica automáticamente en la siguiente petición. No reentrena
   el modelo ni cambia sus probabilidades: ajusta la decisión sobre la confianza.

La extensión y el MIME del cliente no sustituyen la validación con Pillow.
El límite del archivo es exactamente 10 MiB (10 × 1024 × 1024 bytes). La petición
multipart permite hasta 11 MiB para incluir sus cabeceras. Se rechazan imágenes
de más de 25 millones de píxeles antes de convertirlas a RGB.

## Prueba de cámara

1. Abre la aplicación mediante localhost o 127.0.0.1. En un despliegue futuro,
   utiliza HTTPS. Una dirección HTTP de la red local normalmente no habilita cámara.
2. Selecciona «Usar cámara», pulsa «Iniciar cámara» y concede permiso en el navegador.
3. Se muestra el video en vivo y, debajo, la categoría estimada con las tres
   barras de probabilidad y sus métricas. No hay foto fija ni panel lateral.
   Las barras se actualizan con cada respuesta del modelo.
4. Prueba el selector de dispositivo o la orientación frontal/posterior. La
   orientación es una preferencia: algunos dispositivos solo tienen una cámara.
5. Pulsa «Detener cámara». También se liberan sus pistas al cambiar a carga manual,
   ocultar la pestaña, abandonar la página o recargar.

Cada fotograma mantiene la proporción, tiene lado máximo de 640 píxeles y se
codifica como JPEG con calidad 0,80. Se intenta iniciar un análisis cada 1,5 s.
Si tarda más, se espera su respuesta y al menos 250 ms antes del siguiente.
Hay **una sola petición de clasificación en curso por página**, compartida por
ambos modos. Un único temporizador se programa al terminar el ciclo anterior.
El bloqueo Python serializa las inferencias entre clientes del mismo proceso.

Al detener durante una petición, esta termina normalmente pero su respuesta
tardía no altera la interfaz. No se aborta el `fetch`, porque eso no cancelaría
el trabajo del servidor. Los controles de inicio/carga permanecen deshabilitados
hasta que termine. Se conservan las últimas probabilidades mientras llega otra
respuesta, sin mostrar ni crear una vista previa del fotograma interno. Historial y estadísticas se
actualizan como máximo una vez cada 15 s durante el análisis, o bajo petición.

## Variables y MongoDB preparado

`.env.example` contiene exclusivamente:

```dotenv
MONGODB_URI=
MONGODB_DB=ambiental_huanuco
```

`SECRET_KEY` en `.env.example` es un marcador vacío para la clave privada de sesión.
El programa lee variables del entorno del proceso y carga el archivo local
privado `.env` automáticamente. Las variables del proceso tienen prioridad.
Con cuentas activadas, configura MongoDB para poder registrarte e iniciar sesión.
`MONGODB_URI` vacío o ausente da estado `no_configurado`, sin crear un cliente ni
hacer conexiones. El historial indica «Historial disponible cuando se configure
MongoDB». No se simulan datos almacenados ni se guardan resultados en un sustituto
local. Los resultados no guardados no se recuperan después.

Para comprobar una configuración local sin imprimir la URI ni insertar datos
de prueba, ejecuta `python scripts/verificar_mongo.py`. Comprueba ping, índice
y lectura. Después de cambiar `.env`, reinicia el servidor para cargar los valores.
El archivo privado está excluido de Git y del ZIP. No compartas su contenido.

En una etapa futura, configura Atlas en su consola: crea un clúster, un usuario
con permisos sobre la base necesaria y acceso de red restringido al servicio.
Obtén la URI desde «Connect / Drivers» y configúrala como variable secreta
`MONGODB_URI` en el entorno de ejecución, fuera del código y de Git. No la pegues
en README, capturas ni registros. `MONGODB_DB` es opcional y predetermina
`ambiental_huanuco`. La colección `inferencias` y su índice de fecha se crean
cuando se use por primera vez una configuración válida.

Solo se almacenan `created_at` UTC, `source`, `predicted_class`,
`displayed_category`, `confidence`, `is_conclusive`, `confidence_level`,
`inference_time_ms`, `probabilities`, `model_name` y `device`.
No se almacenan imágenes, fotogramas, rostros, IP ni datos biométricos en MongoDB.
La imagen viaja al servidor para inferencia y se descarta después de la petición.
Los archivos de subida no se escriben en disco.

Una caída de almacenamiento no impide clasificar. Los tiempos de selección y
conexión son 5 s y el de socket 2 s. Después de un fallo hay una pausa de
reintentos de 30 s. Un fallo puede añadir algunos segundos a una petición;
no es una cola de almacenamiento en segundo plano. Los errores del driver se
registran con mensajes genéricos, sin imprimir la URI ni la excepción original.
`/health` muestra el estado conocido, sin probar la conexión en cada llamada.

## API

| Método y ruta | Comportamiento |
|---|---|
| `GET /` | Interfaz en español |
| `GET /health` | Estado de servidor, modelo y almacenamiento, nombre del modelo. Sin inferencia, lock ni consulta de red. 200 si el modelo está preparado, 503 en otro caso |
| `GET /api/estado` | Diagnóstico del modelo, dispositivo, clases, umbral y almacenamiento |
| `POST /api/clasificar` | `multipart/form-data`: archivo `imagen`, `origen` opcional (`upload` o `camera`, predeterminado `upload`) |
| `GET /api/historial?limit=50` | Registros recientes. `limit` entero de 1 a 100 |
| `GET /api/estadisticas` | Total, cantidades por categoría mostrada, no concluyentes, confianza media y distribución por origen |

Clasificación devuelve `categoria`, `confianza` (0–1), `porcentaje`,
`es_concluyente`, `nivel_confianza`, `mensaje`, `prediccion_modelo`, `categorias`,
`tiempo_ms`, `dispositivo`, `umbral_confianza`, `almacenamiento_guardado` y un
objeto `almacenamiento` con estado y mensaje. Cada categoría incluye `nombre`,
`nombre_interno`, `probabilidad` y `porcentaje`. El tiempo mide inferencia,
excluyendo espera del lock, subida, decodificación y almacenamiento.

El formulario admite además `umbral`, un número entre 0.60 y 1.00. La respuesta
informa `umbral_confianza` aplicado y `umbral_guardado` (0.60). Si la confianza
es menor de 0.60, devuelve «No detectado», `almacenamiento_guardado: false` y
`almacenamiento.motivo: confianza_baja`, sin llamar a MongoDB. En 0.60 exacto
se permite guardar. Los registros guardados incluyen `confidence_threshold`
para interpretar la decisión que se tomó con el control seleccionado.

Ausencia o caída de MongoDB devuelve 200 y `disponible: false` en sus consultas.
No es una historia vacía supuestamente guardada. Las estadísticas no disponibles
no se sustituyen por números inventados. Los ObjectId se serializan como cadenas
y las fechas como ISO 8601 UTC. Archivos inválidos y parámetros incorrectos dan
400, exceso de tamaño 413, fallos de inferencia 500 con mensajes sin datos internos.

Verificación rápida en PowerShell, con el servidor iniciado:

```powershell
Invoke-RestMethod http://localhost:5000/health
Invoke-RestMethod http://localhost:5000/api/estado
Invoke-RestMethod http://localhost:5000/api/historial?limit=50
Invoke-RestMethod http://localhost:5000/api/estadisticas
```

## Preparación de Render (sin despliegue en esta etapa)

`render.yaml`, `Procfile` y `.python-version` preparan Python 3.11, health check
`/health` y el comando:

```sh
gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app
```

Usa **un solo worker**, sin `--preload`, para mantener una copia del modelo y su
lock. Gunicorn requiere un sistema compatible con Unix, no funciona nativamente
en Windows. En Windows usa `python app.py`. La compatibilidad de entrada WSGI
`app:app` se comprueba localmente, pero no equivale a ejecutar Gunicorn en Linux.

Para una etapa futura: sube el proyecto a un repositorio propio sin `.env`,
datasets, ZIP, cachés ni resultados de entrenamiento. Incluye el `.pt` original.
En Render podrás crear un Web Service desde ese repositorio o su Blueprint,
revisar el build y start de `render.yaml`, configurar las variables necesarias y
comprobar `/health`. `PORT` lo suministra Render. MongoDB seguirá siendo opcional.
No publiques el servicio como listo hasta comprobar inferencia y memoria allí.

El build preparado instala PyTorch para CPU y reemplaza OpenCV por su variante
headless para evitar dependencias de escritorio. Esto no garantiza caber en un
plan con poca RAM. PyTorch/Ultralytics pueden superar la memoria disponible,
especialmente al arrancar. Un worker y un lock reducen duplicación, pero **hay que
medir la memoria y el tiempo en el futuro servicio real**.

## ONNX como alternativa futura explícita

No se ha exportado ni sustituido el modelo en esta etapa. El motor predeterminado
sigue siendo `pt`. `scripts/exportar_onnx.py` comprueba la tarea y las clases,
exporta el mismo modelo y genera un manifiesto SHA-256, conservando el `.pt`.
En un entorno de desarrollo separado con las dependencias de Ultralytics:

```powershell
python -m pip install onnx onnxruntime
python scripts/exportar_onnx.py
```

Antes de usarlo, compara probabilidades y categorías PT/ONNX sobre imágenes
externas, formatos y orientaciones distintas, incluidos casos próximos a 75 %.
`motores.py` contiene un motor opcional ONNX Runtime en CPU, con el
preprocesamiento de clasificación de Ultralytics 8.4.51: resize del lado corto
a 224, recorte central, RGB, escala 0–1. La exportación incluye softmax.
La versión opcional no está validada con una exportación real en esta entrega.
El hash y la comparación de resultados deben verificarse antes de producción.

Después de exportar y validar, un entorno independiente puede instalar
`requirements-onnx.txt`, incluir el `.onnx` y seleccionar explícitamente
`INFERENCE_BACKEND=onnx`. Para un futuro Render ONNX, cambia también el build
a `pip install -r requirements-onnx.txt`. Nunca se activa como fallback automático.
No instales ambos archivos de dependencias en el entorno de producción ligero.

## Pruebas reproducibles

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas bloquean conexiones reales a MongoDB, prueban almacenamiento con
dobles y ejecutan dos clasificaciones con el modelo real. Cubren estados,
validación, límites, EXIF, umbral exacto, JSON, guardado simulado, estadísticas,
caída de almacenamiento, reutilización del modelo y concurrencia del lock.
Las imágenes sintéticas comprueban ejecución, no exactitud ambiental.

Prueba opcional de navegador: Node.js, Chrome instalado y Playwright.
No necesita encender una cámara física. Inicia el servidor exclusivo de pruebas
en 5058, con cuentas efímeras en memoria y MongoDB desactivado:

```powershell
python tests/servidor_navegador.py
```

En otra terminal:

```powershell
npm install --no-save --package-lock=false playwright
node tests/verificar_navegador.cjs
```

Usa una cámara sintética de Chromium, retraso del servidor y una respuesta de
umbral controlada. Comprueba carga real, hash del archivo manual, cámara sin foto fija, ausencia
de envíos simultáneos, parada, cambio de orientación/modo, errores de permisos
y anchos 390/768/1440. Evidencia en `.test-artifacts/` (excluida del ZIP y Git).
`TEST_BASE_URL` permite otro servidor. `PLAYWRIGHT_MODULE` puede indicar un
módulo Playwright ya instalado fuera del proyecto. La prueba sintética no
sustituye probar cámaras físicas, navegadores móviles ni una cuenta Atlas real.

## Limitaciones y problemas comunes

- **Evaluación pequeña:** datos registrados por el autor: 100 épocas, Tesla T4,
  YOLOv8n Classification. 114 imágenes de entrenamiento, 27 de validación y
  19 de test. Top-1/Top-5 registrados de 100 % proceden de esos 19 ejemplos de los
  mismos datasets. No se reprodujo el entrenamiento ni se auditó el dataset.
  Valida con imágenes externas y agrega una clase «sin contaminación».
- **Confianza alta fuera del dominio:** el umbral no convierte el modelo en
  detector de ausencia de contaminación ni garantiza que el resultado sea correcto.
- **Cámara bloqueada:** revisa permisos, usa localhost/127.0.0.1 o HTTPS y cierra
  otras aplicaciones que la utilicen. Si falta un dispositivo, elige automática.
- **Demora o cámara sin nuevos resultados:** CPU lenta, conexión pendiente o
  servidor caído pueden mantener un análisis en curso. La interfaz no abre otra
  petición mientras no termine. Revisa el servidor y recarga si la conexión queda
  indefinidamente pendiente. El video en vivo no espera la inferencia.
- **Modelo no disponible:** comprueba que el `.pt` exista y que las dependencias
  se instalaron en el mismo Python. Un modelo de detección o con otras clases se
  rechaza. Solo carga archivos de modelo confiables.
- **Sin GPU:** una instalación CPU de PyTorch usará CPU aunque haya hardware GPU.
  Instala una versión CUDA compatible si deseas habilitarla localmente.
- **Puerto ocupado:** define otro `PORT`; visita ese mismo puerto en el navegador.
- **MongoDB sin configurar:** impide crear cuentas o iniciar sesión. Una sesión
  ya iniciada permite clasificar durante una caída, sin guardar resultados.
- **Privacidad:** el historial y las estadísticas se filtran por usuario. Revisa
  la retención y los registros de acceso antes de un despliegue público.

## Estructura y paquete final

`app.py` exporta WSGI e inicializa el modelo. `inferencia_ambiental.py` conserva
Flask, validación, evaluación y rutas. `motores.py` encapsula la carga del mismo
modelo. `almacenamiento.py` prepara PyMongo opcional. `templates/` y `static/`
contienen la interfaz, y `tests/` las verificaciones. `VERIFICACION.md` registra
el alcance real de las pruebas. El ZIP contiene fuentes, modelo y documentación,
excluyendo dependencias instaladas, imágenes de prueba, cachés y secretos.

Referencias técnicas para la configuración futura:
[Flask en Render](https://render.com/docs/deploy-flask),
[Python en Render](https://render.com/docs/python-version),
[Health checks](https://render.com/docs/health-checks),
[Conexión PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/),
[Exportación Ultralytics](https://docs.ultralytics.com/modes/export/).
