/* Prueba opcional de interfaz con cámara sintética de Chromium. Sin cámara física. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:5058';
const output = path.resolve('.test-artifacts');
const checks = [];
const ok = (text) => { checks.push(text); console.log('OK ' + text); };
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');

(async () => {
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch({channel: 'chrome', headless: true,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']});
  let page;
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, permissions: ['camera']});
    await context.addInitScript(() => {
      window.__qa = {active: 0, maxActive: 0, sent: [], completed: [], streams: [], timestamps: [], origins: [], sizes: [], thresholds: []};
      const hash = async (blob) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))).map((x) => x.toString(16).padStart(2, '0')).join('');
      window.__hash = hash;
      window.__blobs = {};
      const createUrl = URL.createObjectURL.bind(URL), revokeUrl = URL.revokeObjectURL.bind(URL);
      URL.createObjectURL = (blob) => { const url = createUrl(blob); window.__blobs[url] = blob; return url; };
      URL.revokeObjectURL = (url) => { delete window.__blobs[url]; revokeUrl(url); };
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (url, options) => {
        if (!String(url).includes('/api/clasificar')) return originalFetch(url, options);
        const qa = window.__qa;
        qa.active++; qa.maxActive = Math.max(qa.maxActive, qa.active);
        const digest = await hash(options.body.get('imagen'));
        const bitmap = await createImageBitmap(options.body.get('imagen'));
        qa.sizes.push([bitmap.width, bitmap.height]); bitmap.close();
        qa.sent.push(digest); qa.origins.push(options.body.get('origen')); qa.timestamps.push(Date.now());
        qa.thresholds.push(options.body.get('umbral'));
        try { const response = await originalFetch(url, options); if (response.ok) qa.completed.push(digest); return response; }
        finally { qa.active--; }
      };
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        // Video sintético determinista: no depende de una cámara del sistema.
        const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
        const ctx = canvas.getContext('2d'); let tick = 0;
        const draw = () => { ctx.fillStyle = `rgb(20,${80 + (++tick % 100)},50)`; ctx.fillRect(0, 0, 640, 480); };
        draw(); const clock = setInterval(draw, 100);
        const stream = canvas.captureStream(10);
        for (const track of stream.getTracks()) {
          const stop = track.stop.bind(track);
          track.stop = () => { clearInterval(clock); stop(); };
        }
        window.__qa.streams.push(stream); return stream;
      };
    });
    page = await context.newPage();
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(base);
    await page.waitForURL('**/login');
    assert.equal(await page.getByRole('heading', {name: 'Inicia sesión'}).isVisible(), true);
    await page.screenshot({path: path.join(output, 'login.png'), fullPage: true});
    await page.getByRole('link', {name: 'Crea tu cuenta'}).click();
    await page.setViewportSize({width: 390, height: 1000});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({path: path.join(output, 'registro-mobile.png'), fullPage: true});
    await page.setViewportSize({width: 1440, height: 1000});
    const accountEmail = `prueba-${Date.now()}@example.test`;
    const accountPassword = 'Frase temporal para prueba 234!';
    await page.locator('#nombre').fill('Cuenta de navegador');
    await page.locator('#email').fill(accountEmail);
    await page.locator('#password').fill(accountPassword);
    await page.locator('#confirmar-password').fill(accountPassword);
    await page.getByRole('button', {name: 'Crear cuenta y entrar'}).click();
    await page.waitForURL(base + '/');
    assert.match(await page.locator('.account-nav').innerText(), /Cuenta de navegador/);
    ok('Registro, sesión y acceso al sistema con cuenta temporal');
    await page.waitForFunction(() => document.querySelector('#server-state').textContent.includes('disponible'));
    assert.match(await page.locator('#history-status').innerText(), /Historial disponible cuando se configure MongoDB/);
    assert.equal(await page.locator('#stats').isVisible(), false);
    ok('Inicio sin MongoDB y sin datos ficticios');
    await page.locator('#image').setInputFiles({name: 'prueba.png', mimeType: 'image/png', buffer: png});
    await page.locator('#result').waitFor({state: 'visible'});
    assert.equal(await page.locator('#selected-preview').isVisible(), true);
    assert.equal(await page.locator('#probabilities progress').count(), 3);
    assert.match(await page.locator('#save-state').innerText(), /no guardado/i);
    assert.equal(await page.locator('#category').innerText(), 'No detectado');
    assert.equal(await page.evaluate(async () => window.__hash(window.__blobs[document.querySelector('#preview').src])), await page.evaluate(() => window.__qa.completed.at(-1)));
    await page.screenshot({path: path.join(output, 'desktop.png'), fullPage: true});
    ok('Carga manual real, vista previa, tres probabilidades y mismo archivo del resultado');

    // Respuesta controlada: prueba visual de umbral, sin guardar datos simulados.
    await page.route('**/api/clasificar', async (route) => route.fulfill({json: {
      categoria: 'No concluyente', confianza: .74, porcentaje: 74, es_concluyente: false,
      umbral_confianza: .75,
      nivel_confianza: 'baja', mensaje: 'La imagen no coincide con suficiente seguridad con las categorías conocidas',
      prediccion_modelo: 'Basura', tiempo_ms: 20, almacenamiento_guardado: false,
      almacenamiento: {estado: 'no_configurado', disponible: false, mensaje: 'Resultado de prueba no guardado.'},
      categorias: [{nombre: 'Basura', probabilidad: .74}, {nombre: 'Incendio', probabilidad: .16}, {nombre: 'Deforestación', probabilidad: .1}]
    }}));
    await page.locator('#image').setInputFiles({name: 'umbral.png', mimeType: 'image/png', buffer: png});
    await page.waitForFunction(() => document.querySelector('#category').textContent === 'No concluyente' && document.querySelector('#confidence').textContent === '74.0 %' && !document.querySelector('#image').disabled);
    assert.equal(await page.locator('#internal-prediction').isVisible(), true);
    ok('No concluyente y predicción interna claramente separada');
    await page.unroute('**/api/clasificar');

    await page.locator('#camera-mode').click();
    await page.route('**/api/clasificar', async (route) => { await new Promise((resolve) => setTimeout(resolve, 1800)); await route.continue(); });
    await page.locator('#start-camera').click();
    await page.waitForFunction(() => window.__qa.completed.length >= 4, {timeout: 25000});
    // Detener mientras otra petición se procesa: conserva resultado completado.
    await page.waitForFunction(() => window.__qa.active === 1, {timeout: 12000});
    const previousSrc = await page.locator('#preview').getAttribute('src');
    await page.locator('#stop-camera').click();
    const sentAtStop = await page.evaluate(() => window.__qa.sent.length);
    await page.waitForFunction(() => window.__qa.active === 0, {timeout: 15000});
    await page.waitForTimeout(1800);
    assert.equal(await page.evaluate(() => window.__qa.sent.length), sentAtStop);
    assert.equal(await page.locator('#preview').getAttribute('src'), previousSrc);
    assert.equal(await page.evaluate(() => window.__qa.maxActive), 1);
    assert.equal(await page.evaluate(() => window.__qa.streams.every((s) => s.getTracks().every((t) => t.readyState === 'ended'))), true);
    assert.equal(await page.evaluate(() => window.__qa.origins.slice(2).every((origin) => origin === 'camera')), true);
    const times = await page.evaluate(() => window.__qa.timestamps.slice(2));
    assert.ok(times.slice(1).every((time, index) => time - times[index] >= 1450));
    ok('Cámara sintética periódica con servidor lento: máximo una petición, parada y descarte de respuesta tardía');
    await page.unroute('**/api/clasificar');

    await page.locator('#start-camera').click();
    await page.waitForFunction(() => document.querySelector('#result').hidden === false && window.__qa.active === 0 && window.__qa.completed.length >= 6, {timeout: 15000});
    // Cámara: solo video y barras, sin ninguna fotografía fija ni panel lateral.
    assert.equal(await page.locator('#preview').isVisible(), false);
    assert.equal(await page.locator('#preview').getAttribute('src'), null);
    assert.equal(await page.locator('#frame-label').isVisible(), false);
    assert.equal(await page.locator('#camera-results #result').isVisible(), true);
    assert.equal(await page.locator('#video').isVisible(), true);
    assert.equal(await page.locator('#camera-results progress').count(), 3);
    const frameSize = await page.evaluate(() => window.__qa.sizes.at(-1));
    assert.ok(Math.max(...frameSize) <= 640);
    await page.screenshot({path: path.join(output, 'camera.png'), fullPage: true});
    await page.locator('#stop-camera').click();
    await page.waitForFunction(() => window.__qa.active === 0);
    ok('Video y tres barras en vivo debajo, sin foto fija ni panel lateral; envío interno limitado a 640 píxeles');

    await page.locator('#start-camera').click();
    await page.waitForFunction(() => document.querySelector('#camera-status').textContent.includes('Cámara activa'));
    await page.waitForFunction(() => !document.querySelector('#camera-select').disabled);
    const devicesBefore = await page.evaluate(() => window.__qa.streams.length);
    await page.locator('#camera-select').selectOption('');
    await page.waitForFunction((n) => window.__qa.streams.length > n, devicesBefore);
    assert.equal(await page.evaluate(() => window.__qa.streams.slice(0, -1).every((s) => s.getTracks().every((t) => t.readyState === 'ended'))), true);
    await page.waitForFunction(() => !document.querySelector('#facing-select').disabled);
    const oldCount = await page.evaluate(() => window.__qa.streams.length);
    await page.locator('#facing-select').selectOption('user');
    await page.waitForFunction((n) => window.__qa.streams.length > n, oldCount);
    assert.equal(await page.evaluate(() => window.__qa.streams.slice(0, -1).every((s) => s.getTracks().every((t) => t.readyState === 'ended'))), true);
    await page.locator('#upload-mode').click();
    assert.equal(await page.evaluate(() => window.__qa.streams.every((s) => s.getTracks().every((t) => t.readyState === 'ended'))), true);
    ok('Selector de dispositivo, orientación y cambio de modo liberan la cámara anterior');

    await page.waitForFunction(() => window.__qa.active === 0);
    await page.locator('#image').setInputFiles({name: 'responsive.png', mimeType: 'image/png', buffer: png});
    await page.locator('#result').waitFor({state: 'visible'});
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({width, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      await page.screenshot({path: path.join(output, `responsive-${width}.png`), fullPage: true});
    }
    ok('Sin desbordamiento horizontal en móvil, tablet y escritorio');

    await page.waitForFunction(() => window.__qa.active === 0);
    await page.locator('#camera-mode').click();
    await page.evaluate(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Prueba', 'NotAllowedError'); }; });
    await page.locator('#start-camera').click();
    await page.waitForFunction(() => document.querySelector('#camera-status').textContent.includes('Permiso denegado'));
    await page.evaluate(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Prueba', 'NotFoundError'); }; });
    await page.locator('#start-camera').click();
    await page.waitForFunction(() => document.querySelector('#camera-status').textContent.includes('No se encontró'));
    ok('Permiso denegado y ausencia de cámara muestran mensajes comprensibles');

    await page.locator('#upload-mode').click();
    await page.route('**/api/clasificar', async (route) => route.fulfill({status: 503, json: {error: 'Servidor temporalmente no disponible.'}}));
    await page.locator('#image').setInputFiles({name: 'servidor.png', mimeType: 'image/png', buffer: png});
    await page.waitForFunction(() => document.querySelector('#status').textContent.includes('Servidor temporalmente'));
    assert.equal(await page.locator('#image').isEnabled(), true);
    await page.unroute('**/api/clasificar');
    ok('Error del servidor recupera los controles y muestra el mensaje');

    await page.locator('#confidence-threshold').evaluate((el) => { el.value = '90'; el.dispatchEvent(new Event('input')); });
    assert.equal(await page.locator('#threshold-value').innerText(), '90 %');
    await page.locator('#reanalyze').click();
    await page.waitForFunction(() => !document.querySelector('#image').disabled && document.querySelector('#category').textContent === 'No detectado');
    assert.equal(await page.evaluate(() => window.__qa.thresholds.at(-1)), '0.9');
    ok('Control de confianza envía el umbral elegido y permite volver a analizar');

    await page.reload();
    await page.locator('#camera-mode').click();
    await page.locator('#start-camera').click();
    await page.waitForFunction(() => document.querySelector('#camera-status').textContent.includes('Cámara activa'));
    await page.evaluate(() => {
      window.__qa.beforeUnloadStopped = false;
      window.addEventListener('beforeunload', () => {
        window.__qa.beforeUnloadStopped = window.__qa.streams.every((s) => s.getTracks().every((t) => t.readyState === 'ended'));
      });
      window.dispatchEvent(new Event('beforeunload'));
    });
    assert.equal(await page.evaluate(() => window.__qa.beforeUnloadStopped), true);
    ok('Evento de abandono libera todas las pistas');
    await page.getByRole('button', {name: 'Cerrar sesión'}).click();
    await page.waitForURL('**/login');
    await page.locator('#email').fill(accountEmail);
    await page.locator('#password').fill('incorrecta');
    await page.getByRole('button', {name: 'Entrar al sistema'}).click();
    await page.getByRole('alert').waitFor();
    await page.locator('#password').fill(accountPassword);
    await page.getByRole('button', {name: 'Entrar al sistema'}).click();
    await page.waitForURL(base + '/');
    ok('Cierre de sesión, rechazo de contraseña errónea y reingreso');
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(output, 'browser-results.json'), JSON.stringify({checks, errors, camera: 'sintética de Chromium'}, null, 2));
    await context.close();
  } catch (error) {
    if (page && !page.isClosed()) {
      console.error(await page.evaluate(() => ({status: document.querySelector('#status').textContent,
        camera: document.querySelector('#camera-status').textContent, hidden: document.hidden,
        qa: {...window.__qa, streams: window.__qa.streams.map((s) => s.getTracks().map((t) => t.readyState))}})));
      await page.screenshot({path: path.join(output, 'failure.png'), fullPage: true});
    }
    throw error;
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
