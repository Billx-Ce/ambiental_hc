"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const percent = (value) => (value * 100).toFixed(1) + " %";
  const video = $("video"), input = $("image");
  let mode = "upload", stream = null, starting = false, timer = null;
  let generation = 0, inFlight = null, selectedUrl = null, resultUrl = null;
  let dashboardBusy = false, lastDashboard = 0;
  const interval = 1500;

  async function apiFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      stopCamera();
      window.location.assign("/login");
      throw new Error("Tu sesión terminó. Inicia sesión otra vez.");
    }
    return response;
  }

  function status(text, error = false) {
    $("status").textContent = text;
    $("status").className = error ? "error" : "";
  }

  function controls() {
    input.disabled = Boolean(inFlight);
    $("start-camera").disabled = starting || Boolean(stream) || Boolean(inFlight);
    $("stop-camera").disabled = !stream && !starting;
    $("camera-select").disabled = starting || Boolean(inFlight);
    $("facing-select").disabled = starting || Boolean(inFlight);
    $("reanalyze").disabled = Boolean(inFlight) || !input.files.length;
    $("result-panel").setAttribute("aria-busy", String(Boolean(inFlight)));
  }

  function revokeResult() {
    if (resultUrl) URL.revokeObjectURL(resultUrl);
    resultUrl = null;
  }

  function stopCamera() {
    generation++;
    clearTimeout(timer); timer = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null; starting = false; video.srcObject = null;
    $("camera-status").textContent = "Cámara detenida. Se liberaron las pistas de video.";
    // No abortar fetch: eso no cancela una inferencia ya enviada al servidor.
    // La petición termina y bloquea cualquier envío nuevo hasta responder.
    controls();
  }

  function setMode(next) {
    if (next === mode) return;
    stopCamera(); mode = next;
    $("upload-panel").hidden = mode !== "upload";
    $("camera-panel").hidden = mode !== "camera";
    $("reanalyze").hidden = mode === "camera";
    $("analisis").classList.toggle("camera-active", mode === "camera");
    // En cámara, integrar el resultado debajo del video, sin panel lateral.
    (mode === "camera" ? $("camera-results") : document.querySelector(".workspace")).append($("result-panel"));
    $("result-panel").hidden = mode === "camera";
    $("upload-mode").setAttribute("aria-pressed", String(mode === "upload"));
    $("camera-mode").setAttribute("aria-pressed", String(mode === "camera"));
    $("result").hidden = true; $("empty-result").hidden = false;
    revokeResult();
    status(mode === "camera" ? "Inicia la cámara para ver las probabilidades en vivo." : "Selecciona una imagen para comenzar.");
  }

  function showResult(prediction, blob, origin, capturedAt) {
    revokeResult();
    const live = origin === "camera";
    $("preview").hidden = live;
    $("frame-label").hidden = live;
    if (live) {
      $("preview").removeAttribute("src");
    } else {
      resultUrl = URL.createObjectURL(blob);
      $("preview").src = resultUrl;
    }
    $("category").textContent = prediction.categoria;
    $("confidence").textContent = percent(prediction.confianza);
    $("confidence-level").textContent = prediction.nivel_confianza;
    $("timing").textContent = prediction.tiempo_ms + " ms";
    $("conclusive").textContent = prediction.es_concluyente ? "Concluyente" : "No concluyente";
    $("conclusive").className = "badge" + (prediction.es_concluyente ? "" : " uncertain");
    $("warning").textContent = prediction.mensaje;
    $("internal-prediction").hidden = prediction.es_concluyente;
    $("internal-prediction").textContent = "Predicción interna del modelo: " + prediction.prediccion_modelo + ". No alcanza el umbral aplicado (" + percent(prediction.umbral_confianza) + ").";
    const bars = $("probabilities"); bars.replaceChildren();
    for (const item of prediction.categorias) {
      const row = document.createElement("div"); row.className = "row";
      const labels = document.createElement("div"), name = document.createElement("span"), value = document.createElement("span");
      name.textContent = item.nombre; value.textContent = percent(item.probabilidad); labels.append(name, value);
      const bar = document.createElement("progress"); bar.max = 1; bar.value = item.probabilidad; bar.setAttribute("aria-label", item.nombre);
      row.append(labels, bar); bars.append(row);
    }
    $("analysis-time").textContent = live ? "Actualización en vivo: " + new Date().toLocaleTimeString("es-PE") : "Imagen enviada: " + capturedAt.toLocaleTimeString("es-PE") + ". Último análisis: " + new Date().toLocaleTimeString("es-PE");
    $("save-state").textContent = prediction.almacenamiento.mensaje;
    $("result").hidden = false; $("empty-result").hidden = true;
    $("result-panel").hidden = false;
    $("storage-state").textContent = "MongoDB: " + prediction.almacenamiento.estado.replaceAll("_", " ");
    $("storage-state").classList.toggle("ready", prediction.almacenamiento.disponible);
  }

  async function analyze(blob, origin, token, capturedAt) {
    if (inFlight) return;
    const data = new FormData();
    data.append("imagen", blob, origin === "camera" ? "fotograma.jpg" : blob.name);
    data.append("origen", origin);
    data.append("umbral", Number($("confidence-threshold").value) / 100);
    status(origin === "camera" ? "Actualizando probabilidades en vivo…" : "Analizando imagen…");
    // El blob permanece asociado a esta petición y a su resultado.
    const task = (async () => {
      const response = await apiFetch("/api/clasificar", {method: "POST", body: data,
        headers: {"X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content}});
      let prediction;
      try { prediction = await response.json(); }
      catch { throw new Error("El servidor devolvió una respuesta no válida."); }
      if (!response.ok) throw new Error(prediction.error || "No se pudo analizar la imagen.");
      if (token !== generation) return;
      showResult(prediction, blob, origin, capturedAt);
      status(origin === "camera" ? "Clasificación en vivo activa. Requiere verificación humana." : "Análisis completado. Requiere verificación humana.");
      if (Date.now() - lastDashboard > 15000) void refreshDashboard();
    })();
    inFlight = task; controls();
    try { await task; }
    catch (error) {
      if (token === generation) status(error instanceof TypeError ? "No se pudo conectar con el servidor. Comprueba la conexión." : error.message, true);
    } finally {
      if (inFlight === task) inFlight = null;
      controls();
    }
  }

  input.addEventListener("change", async () => {
    if (inFlight) return;
    const token = ++generation, file = input.files[0];
    if (selectedUrl) URL.revokeObjectURL(selectedUrl);
    selectedUrl = null; $("selected-preview").hidden = true;
    $("result").hidden = true; $("empty-result").hidden = false; revokeResult();
    if (!file) { status("Selecciona una imagen para comenzar."); return; }
    if (file.size > 10 * 1024 * 1024) { status("La imagen supera los 10 MB.", true); return; }
    if (!/\.(jpe?g|png|webp|bmp)$/i.test(file.name)) { status("Usa una imagen JPG, JPEG, PNG, WEBP o BMP.", true); return; }
    selectedUrl = URL.createObjectURL(file); $("selected-preview").src = selectedUrl; $("selected-preview").hidden = false;
    await analyze(file, "upload", token, new Date());
  });

  async function listCameras() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const current = stream?.getVideoTracks()[0]?.getSettings().deviceId || $("camera-select").value;
    const select = $("camera-select"); select.replaceChildren(new Option("Cámara automática", ""));
    devices.filter((device) => device.kind === "videoinput").forEach((device, index) => {
      select.add(new Option(device.label || "Cámara " + (index + 1), device.deviceId));
    });
    if ([...select.options].some((option) => option.value === current)) select.value = current;
  }

  async function cameraLoop(token) {
    if (!stream || token !== generation) return;
    const began = Date.now();
    try {
      if (inFlight) await inFlight.catch(() => {});
      if (!stream || token !== generation) return;
      if (!video.videoWidth || video.readyState < 2) throw new Error("Esperando imagen de la cámara…");
      const canvas = document.createElement("canvas");
      const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      const capturedAt = new Date();
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", .8));
      if (!blob) throw new Error("No se pudo capturar el fotograma.");
      if (token !== generation || !stream) return;
      await analyze(blob, "camera", token, capturedAt);
    } catch (error) {
      if (token === generation) status(error.message, true);
    } finally {
      if (stream && token === generation) timer = setTimeout(() => {
        timer = null; void cameraLoop(token);
      }, Math.max(250, interval - (Date.now() - began)));
    }
  }

  async function startCamera() {
    if (starting || stream || inFlight) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      $("camera-status").textContent = "Cámara no disponible. Abre la aplicación en localhost, 127.0.0.1 o HTTPS y usa un navegador compatible."; return;
    }
    const token = ++generation; starting = true; controls();
    $("camera-status").textContent = "Solicitando permiso para usar la cámara…";
    const deviceId = $("camera-select").value;
    try {
      const nextStream = await navigator.mediaDevices.getUserMedia({audio: false, video: {
        width: {ideal: 640}, height: {ideal: 480},
        ...(deviceId ? {deviceId: {exact: deviceId}} : {facingMode: {ideal: $("facing-select").value}})
      }});
      if (token !== generation || mode !== "camera") { nextStream.getTracks().forEach((track) => track.stop()); return; }
      stream = nextStream; video.srcObject = stream; await video.play();
      if (token !== generation) return;
      stream.getVideoTracks().forEach((track) => track.addEventListener("ended", () => {
        if (token === generation) { stopCamera(); $("camera-status").textContent = "La cámara se desconectó. Puedes volver a iniciarla."; }
      }));
      $("camera-status").textContent = "Cámara activa. Clasificación del fotograma completo.";
      try { await listCameras(); } catch { /* La captura funciona sin enumeración. */ }
      if (token === generation) void cameraLoop(token);
    } catch (error) {
      if (token !== generation) return;
      stopCamera();
      const messages = {
        NotAllowedError: "Permiso denegado. Habilita la cámara en los permisos del navegador.",
        NotFoundError: "No se encontró una cámara conectada.",
        NotReadableError: "No se pudo abrir la cámara. Comprueba si otra aplicación la está usando.",
        OverconstrainedError: "La cámara seleccionada no está disponible. Elige Cámara automática."
      };
      $("camera-status").textContent = messages[error.name] || "No se pudo iniciar la cámara. Revisa el dispositivo y los permisos.";
      status("No se pudo iniciar la cámara.", true);
    } finally {
      if (token === generation) starting = false;
      controls();
    }
  }

  async function refreshDashboard() {
    if (dashboardBusy) return;
    dashboardBusy = true; lastDashboard = Date.now(); $("refresh-history").disabled = true;
    try {
      const responses = await Promise.all([apiFetch("/api/historial?limit=50"), apiFetch("/api/estadisticas")]);
      if (responses.some((response) => !response.ok)) throw new Error();
      const [history, stats] = await Promise.all(responses.map((response) => response.json()));
      $("history-status").textContent = history.disponible ? (history.registros.length ? "Últimos " + history.registros.length + " resultados guardados. Horario de tu dispositivo." : "Todavía no hay resultados guardados.") : history.mensaje;
      $("history-table").hidden = !history.disponible || !history.registros.length; $("history-body").replaceChildren();
      for (const record of history.registros) {
        const row = document.createElement("tr");
        for (const text of [new Date(record.created_at).toLocaleString("es-PE"), record.source === "camera" ? "Cámara" : "Carga manual", record.displayed_category, percent(record.confidence), record.inference_time_ms + " ms"]) {
          const cell = document.createElement("td"); cell.textContent = text; row.append(cell);
        }
        $("history-body").append(row);
      }
      $("stats").hidden = !stats.disponible;
      $("stats-status").textContent = stats.disponible ? "Calculadas sobre los resultados guardados en MongoDB." : stats.mensaje;
      if (stats.disponible) {
        $("stat-total").textContent = stats.total; $("stat-inconclusive").textContent = stats.no_concluyentes;
        $("stat-average").textContent = percent(stats.confianza_promedio || 0);
        const entriesById = [
          ["category-distribution", ["Basura", "Incendio", "Deforestación", "No concluyente"].map((name) => [name, stats.por_categoria[name] || 0])],
          ["source-distribution", [["Carga manual", stats.por_fuente.upload || 0], ["Cámara", stats.por_fuente.camera || 0]]]
        ];
        for (const [id, entries] of entriesById) {
          $(id).replaceChildren();
          for (const [name, count] of entries) { const item = document.createElement("li"); item.textContent = name + ": " + count; $(id).append(item); }
        }
      }
    } catch {
      $("history-status").textContent = "No se pudo consultar el historial. Puedes volver a actualizar.";
      $("stats-status").textContent = "No se pudieron consultar las estadísticas.";
      $("stats").hidden = true; $("history-table").hidden = true;
    } finally { dashboardBusy = false; $("refresh-history").disabled = false; }
  }

  async function refreshState() {
    try {
      const response = await apiFetch("/api/estado"), state = await response.json();
      if (!response.ok) throw new Error();
      $("server-state").textContent = "Servidor disponible · Modelo " + state.dispositivo.toUpperCase(); $("server-state").classList.add("ready");
      $("storage-state").textContent = "MongoDB: " + state.almacenamiento.estado.replaceAll("_", " ");
      $("storage-state").classList.toggle("ready", state.almacenamiento.disponible);
    } catch { $("server-state").textContent = "Servidor o modelo no disponible"; $("server-state").classList.remove("ready"); }
  }

  $("upload-mode").addEventListener("click", () => setMode("upload"));
  $("confidence-threshold").addEventListener("input", () => {
    $("threshold-value").textContent = $("confidence-threshold").value + " %";
  });
  $("reanalyze").addEventListener("click", () => input.dispatchEvent(new Event("change")));
  $("camera-mode").addEventListener("click", () => setMode("camera"));
  $("start-camera").addEventListener("click", () => void startCamera());
  $("stop-camera").addEventListener("click", () => { stopCamera(); status("Cámara detenida. Se conserva el último resultado completado."); });
  $("camera-select").addEventListener("change", () => { if (stream) { stopCamera(); void startCamera(); } });
  $("facing-select").addEventListener("change", () => { $("camera-select").value = ""; if (stream) { stopCamera(); void startCamera(); } });
  $("refresh-history").addEventListener("click", () => { void refreshDashboard(); void refreshState(); });
  navigator.mediaDevices?.addEventListener?.("devicechange", () => { void listCameras().catch(() => {}); });
  document.addEventListener("visibilitychange", () => { if (document.hidden && (stream || starting)) stopCamera(); });
  function cleanup() { stopCamera(); revokeResult(); if (selectedUrl) URL.revokeObjectURL(selectedUrl); }
  window.addEventListener("pagehide", cleanup); window.addEventListener("beforeunload", cleanup);
  controls(); void refreshState(); void refreshDashboard();
})();
