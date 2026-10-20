// frontend/js/app.js

let tokenGlobal = localStorage.getItem("wm_token");
let sesionActivaId = null;
let pronombreSeleccionado = "neutro";
let regionSeleccionada = "mexico";
let nombreAgenteGlobal = "Copiloto Técnico";
let datosUsuarioCache = null;

// Control de Sesión a exportar / contextual
let sesionExportarId = null;
let sesionExportarTitulo = "consulta";
let sesionRenombrarId = null;
let menuContextualActivo = null;

// Controlador para abortar la generación en curso
let abortControllerActivo = null;

// ==========================================
// INTERCEPTOR FETCH PARA ENVIAR EL TOKEN JWT
// ==========================================
async function fetchConToken(url, options = {}) {
  if (!tokenGlobal) throw new Error("No hay token de sesión");

  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${tokenGlobal}`);

  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    cerrarSesion();
    throw new Error("Sesión expirada");
  }

  return response;
}

// ==========================================
// VALIDACIONES AUXILIARES
// ==========================================
function validarPasswordCliente(password) {
  if (password.length < 6 || password.length > 60) {
    return "La contraseña debe tener entre 6 y 60 caracteres.";
  }
  const tieneLetra = /[A-Za-z]/.test(password);
  const tieneNumero = /\d/.test(password);
  if (!tieneLetra || !tieneNumero) {
    return "La contraseña debe mezclar al menos una letra y un número.";
  }
  return null;
}

// ==========================================
// FLUJO DE INICIALIZACIÓN
// ==========================================
async function inicializar() {
  inicializarTema();

  document.addEventListener("click", (e) => {
    if (menuContextualActivo && !menuContextualActivo.contains(e.target)) {
      cerrarMenuContextual();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      cerrarMenuContextual();
    }
  });

  if (!tokenGlobal) {
    mostrarLogin();
    return;
  }

  await cargarDatosUsuario();
}

// ==========================================
// AUTENTICACIÓN (LOGIN / REGISTRO)
// ==========================================
function mostrarLogin() {
  document.getElementById("login-modal").style.display = "flex";
  document.getElementById("login-form").style.display = "block";
  document.getElementById("register-form").style.display = "none";
  document.getElementById("login-title").innerText = "Iniciar Sesión";
  document.getElementById("login-desc").innerText = "Ingresa tus credenciales para acceder al agente.";
}

function mostrarRegistro() {
  document.getElementById("login-form").style.display = "none";
  document.getElementById("register-form").style.display = "block";
  document.getElementById("login-title").innerText = "Crear Cuenta";
  document.getElementById("login-desc").innerText = "Únete al espacio de consulta técnica de la red local.";
}

function cerrarSesion() {
  localStorage.removeItem("wm_token");
  tokenGlobal = null;
  datosUsuarioCache = null;
  window.location.reload();
}

async function ejecutarLogin() {
  const user = document.getElementById("login-username").value.trim();
  const pass = document.getElementById("login-password").value.trim();

  if (!user || !pass) {
    await mostrarDialogo({ icono: "ℹ️", titulo: "Datos faltantes", mensaje: "Por favor ingresa usuario y contraseña.", soloAlerta: true });
    return;
  }

  const formData = new URLSearchParams();
  formData.append("username", user);
  formData.append("password", pass);

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData
    });

    if (!res.ok) throw new Error("Usuario o contraseña incorrectos.");

    const data = await res.json();
    tokenGlobal = data.access_token;
    localStorage.setItem("wm_token", tokenGlobal);

    document.getElementById("login-modal").style.display = "none";
    await cargarDatosUsuario();
  } catch (err) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Error", mensaje: err.message, soloAlerta: true });
  }
}

async function ejecutarRegistro() {
  const username = document.getElementById("reg-username").value.trim();
  const password = document.getElementById("reg-password").value.trim();

  if (!username || !password) {
    await mostrarDialogo({ icono: "ℹ️", titulo: "Datos faltantes", mensaje: "Completa usuario y contraseña.", soloAlerta: true });
    return;
  }

  const errorValidacion = validarPasswordCliente(password);
  if (errorValidacion) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Contraseña inválida", mensaje: errorValidacion, soloAlerta: true });
    return;
  }

  try {
    const res = await fetch("/api/auth/registrar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "No se pudo crear la cuenta.");
    }

    await mostrarDialogo({ icono: "✅", titulo: "Éxito", mensaje: "Cuenta creada exitosamente. Por favor inicia sesión.", soloAlerta: true });
    mostrarLogin();
  } catch (err) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Error", mensaje: err.message, soloAlerta: true });
  }
}

// ==========================================
// CAMBIO DE CONTRASEÑA (DESDE PERFIL)
// ==========================================
function abrirModalCambiarPassword() {
  document.getElementById("cp-current-password").value = "";
  document.getElementById("cp-new-password").value = "";
  document.getElementById("cp-confirm-password").value = "";
  document.getElementById("change-password-modal").style.display = "flex";
}

function cerrarModalCambiarPassword() {
  document.getElementById("change-password-modal").style.display = "none";
}

async function ejecutarCambioPassword() {
  const actual = document.getElementById("cp-current-password").value.trim();
  const nueva = document.getElementById("cp-new-password").value.trim();
  const confirmacion = document.getElementById("cp-confirm-password").value.trim();

  if (!actual || !nueva || !confirmacion) {
    await mostrarDialogo({ icono: "ℹ️", titulo: "Datos faltantes", mensaje: "Por favor completa todos los campos requeridos.", soloAlerta: true });
    return;
  }

  if (nueva !== confirmacion) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Discrepancia", mensaje: "La nueva contraseña y su confirmación no coinciden.", soloAlerta: true });
    return;
  }

  const errorValidacion = validarPasswordCliente(nueva);
  if (errorValidacion) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Contraseña inválida", mensaje: errorValidacion, soloAlerta: true });
    return;
  }

  try {
    const res = await fetchConToken("/api/auth/cambiar-password", {
      method: "POST",
      body: JSON.stringify({
        password_anterior: actual,
        password_nueva: nueva
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "No se pudo cambiar la contraseña.");
    }

    cerrarModalCambiarPassword();
    await mostrarDialogo({ icono: "✅", titulo: "Contraseña actualizada", mensaje: "Tu clave ha sido cambiada correctamente.", soloAlerta: true });
  } catch (err) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Error", mensaje: err.message, soloAlerta: true });
  }
}

// ==========================================
// CARGA DE USUARIO Y ONBOARDING WIZARD
// ==========================================
async function cargarDatosUsuario() {
  try {
    const res = await fetchConToken(`/api/user/me`);
    datosUsuarioCache = await res.json();

    if (!datosUsuarioCache.disclaimer_aceptado) {
      document.getElementById("disclaimer-modal").style.display = "flex";
    } else {
      procederPostDisclaimer();
    }
  } catch (err) {
    console.error("Error consultando usuario:", err);
  }
}

async function aceptarDisclaimer() {
  const check = document.getElementById("dont-show-disclaimer-check");
  const noVolverAMostrar = check ? check.checked : false;

  try {
    await fetchConToken('/api/user/disclaimer', {
      method: 'POST',
      body: JSON.stringify({ no_volver_a_mostrar: noVolverAMostrar })
    });
  } catch (e) {
    console.error("Error guardando preferencia de disclaimer:", e);
  }

  document.getElementById("disclaimer-modal").style.display = "none";
  procederPostDisclaimer();
}

async function procederPostDisclaimer() {
  if (!datosUsuarioCache.registrado) {
    const inputNombre = document.getElementById("user-name-input");
    if (inputNombre) inputNombre.value = datosUsuarioCache.nombre || "";

    const inputAgente = document.getElementById("agent-name-input");
    if (inputAgente) inputAgente.value = datosUsuarioCache.nombre_agente || "Copiloto Técnico";

    seleccionarPronombre(datosUsuarioCache.pronombre || "neutro", document.getElementById(`pronoun-${datosUsuarioCache.pronombre || "neutro"}`));
    document.getElementById("onboarding-modal").style.display = "flex";
  } else {
    nombreAgenteGlobal = datosUsuarioCache.nombre_agente || "Copiloto Técnico";
    regionSeleccionada = datosUsuarioCache.region || "mexico";
    actualizarTopbar(nombreAgenteGlobal);
    actualizarSidebarPerfil(datosUsuarioCache.nombre, datosUsuarioCache.pronombre);

    await cargarSesiones();
    setTimeout(comprobarSincronizacionFondo, 1500);
  }
}

function seleccionarPronombre(valor, btn) {
  pronombreSeleccionado = valor;
  document.querySelectorAll('#onboarding-modal .pronoun-group .btn-choice').forEach(b => b.classList.remove('active'));
  if (btn) {
    btn.classList.add('active');
  } else {
    const target = document.getElementById(`pronoun-${valor}`);
    if (target) target.classList.add('active');
  }
}

async function finalizarOnboarding() {
  const nombre = document.getElementById("user-name-input").value.trim();
  const nombreAgente = document.getElementById("agent-name-input").value.trim() || "Copiloto Técnico";

  if (!nombre) {
    await mostrarDialogo({ icono: "ℹ️", titulo: "Nombre requerido", mensaje: "Escribe tu nombre para continuar.", soloAlerta: true });
    return;
  }

  try {
    const res = await fetchConToken("/api/user/onboarding", {
      method: "POST",
      body: JSON.stringify({
        nombre: nombre,
        pronombre: pronombreSeleccionado,
        nombre_agente: nombreAgente
      })
    });

    if (!res.ok) throw new Error("Error guardando configuración");

    datosUsuarioCache.registrado = true;
    datosUsuarioCache.nombre = nombre;
    datosUsuarioCache.pronombre = pronombreSeleccionado;
    datosUsuarioCache.nombre_agente = nombreAgente;
    nombreAgenteGlobal = nombreAgente;

    actualizarTopbar(nombreAgenteGlobal);
    actualizarSidebarPerfil(nombre, pronombreSeleccionado);
    document.getElementById("onboarding-modal").style.display = "none";
    await cargarSesiones();
  } catch (err) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Error", mensaje: err.message, soloAlerta: true });
  }
}

function actualizarTopbar(nombre) {
  const nameEl = document.getElementById("topbar-agent-name");
  if (nameEl) nameEl.innerText = nombre;
  const avatar = document.getElementById("agent-avatar-icon");
  if (avatar) avatar.innerText = nombre.charAt(0).toUpperCase();
}

function actualizarSidebarPerfil(nombreUsuario, pronombre) {
  const nameEl = document.getElementById("sidebar-user-name");
  const pronounEl = document.getElementById("sidebar-user-pronoun");
  const avatarEl = document.getElementById("sidebar-user-avatar");

  if (nameEl && nombreUsuario) nameEl.innerText = nombreUsuario;
  if (pronounEl) {
    const etiquetas = { el: "Trato: Él", ella: "Trato: Ella", neutro: "Trato: Neutro" };
    pronounEl.innerText = etiquetas[pronombre] || "Trato: Neutro";
  }
  if (avatarEl && nombreUsuario) {
    avatarEl.innerText = nombreUsuario.charAt(0).toUpperCase();
  }
}

// ==========================================
// IMPORTACIÓN DE CHATS
// ==========================================
function abrirModalImportar() {
  document.getElementById("import-file-input").value = "";
  document.getElementById("import-modal").style.display = "flex";
}

function cerrarModalImportar() {
  document.getElementById("import-modal").style.display = "none";
}

async function ejecutarImportacionWeb() {
  const fileInput = document.getElementById("import-file-input");

  if (!fileInput.files || fileInput.files.length === 0) {
    await mostrarDialogo({ icono: "⚠️", titulo: "Archivo no seleccionado", mensaje: "Por favor selecciona un archivo JSON.", soloAlerta: true });
    return;
  }

  const file = fileInput.files[0];
  const reader = new FileReader();

  reader.onload = async (e) => {
    try {
      const jsonData = JSON.parse(e.target.result);

      const res = await fetchConToken(`/api/sessions/import`, {
        method: "POST",
        body: JSON.stringify(jsonData)
      });

      if (!res.ok) throw new Error("Error procesando el archivo en el servidor.");

      const data = await res.json();
      cerrarModalImportar();
      await cargarSesiones();
      alternarSesion(data.session_id);

      await mostrarDialogo({ icono: "✅", titulo: "Importación exitosa", mensaje: `El chat ha sido restaurado en tu historial.`, soloAlerta: true });

    } catch (error) {
      await mostrarDialogo({ icono: "⚠️", titulo: "Error", mensaje: "El archivo no es un exporte válido de Vértice o está corrupto.", soloAlerta: true });
    }
  };

  reader.readAsText(file);
}

// ==========================================
// SESIONES Y HISTORIAL
// ==========================================
async function cargarSesiones() {
  try {
    const res = await fetchConToken(`/api/sessions`);
    const sesiones = await res.json();
    const listEl = document.getElementById("session-list");
    listEl.innerHTML = "";

    if (sesiones.length === 0) {
      await crearSesion();
      return;
    }

    sesiones.forEach(s => {
      const li = document.createElement("li");
      li.className = `session-item ${s.id === sesionActivaId ? 'active' : ''}`;
      li.onclick = () => alternarSesion(s.id);

      const wrap = document.createElement("div");
      wrap.className = "session-content-wrap";

      if (s.fijado) {
        const pinIcon = document.createElement("span");
        pinIcon.className = "session-pin-icon";
        pinIcon.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"></line><path d="M5 17h14v-2l-2-2V5a1 1 0 0 0-1-1h-8a1 1 0 0 0-1 1v8l-2 2v2z"></path></svg>`;
        wrap.appendChild(pinIcon);
      }

      const titleSpan = document.createElement("span");
      titleSpan.className = "session-title-text";
      titleSpan.innerText = s.titulo;
      wrap.appendChild(titleSpan);

      const btnDots = document.createElement("button");
      btnDots.className = "btn-session-options";
      btnDots.innerHTML = "•••";
      btnDots.onclick = (e) => { e.stopPropagation(); abrirMenuContextual(e, s.id, s.titulo, Boolean(s.fijado), li); };

      li.appendChild(wrap);
      li.appendChild(btnDots);
      listEl.appendChild(li);
    });

    if (!sesionActivaId && sesiones.length > 0) alternarSesion(sesiones[0].id);
  } catch (e) {
    console.error("Error al cargar sesiones:", e);
  }
}

async function crearSesion() {
  const res = await fetchConToken(`/api/sessions`, { method: 'POST' });
  const nueva = await res.json();
  sesionActivaId = nueva.id;
  await cargarSesiones();
  alternarSesion(nueva.id);
}

async function alternarSesion(sessionId) {
  if (abortControllerActivo) cancelarGeneracion();
  sesionActivaId = sessionId;
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  await cargarHistorial(sessionId);
  await cargarSesiones();
}

async function cargarHistorial(sessionId) {
  const res = await fetchConToken(`/api/messages/${sessionId}`);
  const mensajes = await res.json();
  const scrollEl = document.getElementById("chat-scroll");
  scrollEl.innerHTML = "";
  mensajes.forEach(m => renderizarBurbuja(m.contenido, m.rol, m.fuentes || []));
}

// ==========================================
// CANCELACIÓN DE GENERACIÓN
// ==========================================
function alternarBotonesGeneracion(generando) {
  const btnSend = document.getElementById("btn-send-query");
  const btnStop = document.getElementById("btn-stop-query");
  if (!btnSend || !btnStop) return;

  if (generando) {
    btnSend.style.display = "none";
    btnStop.style.display = "flex";
  } else {
    btnSend.style.display = "flex";
    btnStop.style.display = "none";
  }
}

function cancelarGeneracion() {
  if (abortControllerActivo) {
    abortControllerActivo.abort();
    abortControllerActivo = null;
    alternarBotonesGeneracion(false);
    removerIndicadorPensando();
  }
}

// ==========================================
// STREAMING DE MENSAJE (TOKEN A TOKEN)
// ==========================================
async function enviarMensaje() {
  const input = document.getElementById("query-input");
  const texto = input.value.trim();
  if (!texto || !sesionActivaId) return;

  input.value = "";
  renderizarBurbuja(texto, "user", []);
  mostrarIndicadorPensando();

  alternarBotonesGeneracion(true);
  abortControllerActivo = new AbortController();

  let contenedorBurbuja = null;
  let contenidoAcumulado = "";
  let fuentesAcumuladas = [];

  try {
    const res = await fetchConToken("/api/chat", {
      method: "POST",
      signal: abortControllerActivo.signal,
      body: JSON.stringify({
        session_id: sesionActivaId,
        pregunta: texto
      })
    });

    if (!res.ok) throw new Error("Inconveniente al procesar la respuesta.");

    removerIndicadorPensando();

    // Crear la burbuja del asistente en blanco para llenarla con el stream
    contenedorBurbuja = crearBurbujaAsistenteVacia();

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lineas = buffer.split("\n\n");
      buffer = lineas.pop();

      for (const bloque of lineas) {
        if (!bloque.startsWith("data: ")) continue;
        const payload = JSON.parse(bloque.replace("data: ", "").trim());

        if (payload.tipo === "meta") {
          fuentesAcumuladas = payload.fuentes || [];
        } else if (payload.tipo === "token") {
          contenidoAcumulado += payload.contenido;
          actualizarBurbujaEnVivo(contenedorBurbuja, contenidoAcumulado, fuentesAcumuladas);
        } else if (payload.tipo === "fin") {
          actualizarBurbujaEnVivo(contenedorBurbuja, contenidoAcumulado, fuentesAcumuladas, true);
        }
      }
    }

    await cargarSesiones();

  } catch (err) {
    removerIndicadorPensando();
    if (err.name === "AbortError") {
      if (contenedorBurbuja && contenidoAcumulado) {
        contenidoAcumulado += "\n\n*(Generación detenida por el usuario)*";
        actualizarBurbujaEnVivo(contenedorBurbuja, contenidoAcumulado, fuentesAcumuladas, true);
      }
    } else {
      console.error("Error en streaming:", err);
      renderizarBurbuja("Inconveniente al comunicarse con el servidor. Inténtalo nuevamente.", "assistant", []);
    }
  } finally {
    abortControllerActivo = null;
    alternarBotonesGeneracion(false);
  }
}

function alPresionarTecla(e) { if (e.key === "Enter") enviarMensaje(); }

function crearBurbujaAsistenteVacia() {
  const scrollEl = document.getElementById("chat-scroll");
  const row = document.createElement("div");
  row.className = "message-row assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = "<span class='cursor-blink'>▋</span>";

  row.appendChild(bubble);
  scrollEl.appendChild(row);
  scrollEl.scrollTop = scrollEl.scrollHeight;
  return bubble;
}

function actualizarBurbujaEnVivo(bubbleEl, texto, fuentes = [], finalizado = false) {
  marked.setOptions({ breaks: true });
  let html = marked.parse(texto);

  if (!finalizado) {
    html += "<span class='cursor-blink' style='opacity: 0.7;'>▋</span>";
  }

  if (fuentes && fuentes.length > 0) {
    html += `<div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-subtle); font-size: 12px;">
      <strong>Fuente(s):</strong> ${fuentes.map(f => `<span class="source-tag">${f}</span>`).join(" ")}
    </div>`;
  }

  bubbleEl.innerHTML = html;
  const scrollEl = document.getElementById("chat-scroll");
  scrollEl.scrollTop = scrollEl.scrollHeight;
}

function renderizarBurbuja(texto, rol, fuentes = []) {
  const scrollEl = document.getElementById("chat-scroll");
  const row = document.createElement("div");
  row.className = `message-row ${rol}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  marked.setOptions({ breaks: true });
  bubble.innerHTML = marked.parse(texto);

  if (fuentes.length > 0) {
    const fuentesDiv = document.createElement("div");
    fuentesDiv.innerHTML = "<strong>Fuente(s):</strong> " + fuentes.map(f => `<span class="source-tag">${f}</span>`).join(" ");
    bubble.appendChild(fuentesDiv);
  }

  row.appendChild(bubble);
  scrollEl.appendChild(row);
  scrollEl.scrollTop = scrollEl.scrollHeight;
}

function mostrarIndicadorPensando() {
  const scrollEl = document.getElementById("chat-scroll");
  const row = document.createElement("div");
  row.className = "message-row assistant";
  row.id = "thinking-bubble";
  row.innerHTML = `<div class="bubble">Consultando repositorio...</div>`;
  scrollEl.appendChild(row);
  scrollEl.scrollTop = scrollEl.scrollHeight;
}

function removerIndicadorPensando() {
  const thinking = document.getElementById("thinking-bubble");
  if (thinking) thinking.remove();
}

async function eliminarTodosLosChats() {
  const confirmado = await mostrarDialogo({
    icono: "🚨", titulo: "¿Vaciar historial?", mensaje: "Se eliminarán permanentemente todas las consultas registradas.", textoConfirmar: "Eliminar todo", textoCancelar: "Cancelar", esPeligroso: true
  });
  if (!confirmado) return;

  const res = await fetchConToken(`/api/sessions/clear-all`, { method: "DELETE" });
  if (res.ok) {
    document.getElementById("chat-scroll").innerHTML = "";
    sesionActivaId = null;
    await crearSesion();
  }
}

async function eliminarChatIndividual(sessionId, sessionTitle) {
  const confirmado = await mostrarDialogo({
    icono: "🗑️", titulo: "Eliminar consulta", mensaje: `¿Deseas eliminar permanentemente "${sessionTitle}"?`, textoConfirmar: "Eliminar", textoCancelar: "Cancelar", esPeligroso: true
  });
  if (!confirmado) return;

  await fetchConToken(`/api/sessions/single/${sessionId}`, { method: "DELETE" });
  if (sesionActivaId === sessionId) {
      document.getElementById("chat-scroll").innerHTML = "";
      sesionActivaId = null;
  }
  await cargarSesiones();
}

function abrirMenuContextual(event, sessionId, sessionTitle, estaFijado, itemEl) {
  cerrarMenuContextual();
  itemEl.classList.add("options-open");

  const menu = document.createElement("div");
  menu.className = "chat-context-menu";

  const textoPin = estaFijado ? "Desfijar chat" : "Fijar chat";
  menu.innerHTML = `
    <button class="context-menu-item" id="opt-export">Exportar chat</button>
    <button class="context-menu-item" id="opt-pin">${textoPin}</button>
    <button class="context-menu-item" id="opt-rename">Cambiar nombre</button>
    <div class="context-menu-divider"></div>
    <button class="context-menu-item danger" id="opt-delete">Borrar chat</button>
  `;
  document.body.appendChild(menu);

  const rect = event.currentTarget.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.left, window.innerWidth - 185)}px`;
  menu.style.top = `${rect.bottom + 5}px`;

  menuContextualActivo = menu;

  menu.querySelector("#opt-export").onclick = (e) => { e.stopPropagation(); cerrarMenuContextual(); abrirModalExportar(sessionId, sessionTitle); };
  menu.querySelector("#opt-pin").onclick = async (e) => { e.stopPropagation(); cerrarMenuContextual(); await alternarFijarSesion(sessionId); };
  menu.querySelector("#opt-rename").onclick = (e) => { e.stopPropagation(); cerrarMenuContextual(); abrirModalRenombrar(sessionId, sessionTitle); };
  menu.querySelector("#opt-delete").onclick = async (e) => { e.stopPropagation(); cerrarMenuContextual(); await eliminarChatIndividual(sessionId, sessionTitle); };
}

function cerrarMenuContextual() {
  if (menuContextualActivo) {
    document.querySelectorAll(".session-item.options-open").forEach(el => el.classList.remove("options-open"));
    if (menuContextualActivo.parentNode) menuContextualActivo.parentNode.removeChild(menuContextualActivo);
    menuContextualActivo = null;
  }
}

async function alternarFijarSesion(sessionId) {
  const res = await fetchConToken(`/api/sessions/${sessionId}/pin`, { method: "PATCH" });
  if (!res.ok) await mostrarDialogo({ icono: "📌", titulo: "Límite", mensaje: "Solo puedes fijar 3 consultas.", soloAlerta: true });
  else await cargarSesiones();
}

function abrirModalRenombrar(sessionId, sessionTitle) {
  sesionRenombrarId = sessionId;
  document.getElementById("rename-input").value = sessionTitle;
  document.getElementById("rename-modal").style.display = "flex";
}

function cerrarModalRenombrar() { document.getElementById("rename-modal").style.display = "none"; }

async function guardarRenombrar() {
  const nuevoTitulo = document.getElementById("rename-input").value.trim();
  if (!nuevoTitulo || !sesionRenombrarId) return;
  await fetchConToken(`/api/sessions/${sesionRenombrarId}/rename`, { method: "PATCH", body: JSON.stringify({ titulo: nuevoTitulo }) });
  cerrarModalRenombrar();
  await cargarSesiones();
}

function abrirModalExportar(sessionId, sessionTitle) {
  sesionExportarId = sessionId;
  sesionExportarTitulo = sessionTitle;
  document.getElementById("export-modal").style.display = "flex";
}
function cerrarModalExportar() { document.getElementById("export-modal").style.display = "none"; }

async function ejecutarExportacion(formato) {
  const res = await fetchConToken(`/api/messages/${sesionExportarId}`);
  const mensajes = await res.json();
  const nombreUsuario = (datosUsuarioCache && datosUsuarioCache.nombre) || "Usuario";
  const nombreAgente = nombreAgenteGlobal || "Copiloto Técnico";

  if (formato === "json") exportarComoJSON(mensajes, nombreUsuario, nombreAgente);
  else if (formato === "html") exportarComoHTML(mensajes, nombreUsuario, nombreAgente);
  cerrarModalExportar();
}

function descargarArchivo(contenido, nombreArchivo, mimeType) {
  const blob = new Blob([contenido], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = nombreArchivo;
  a.click(); URL.revokeObjectURL(url);
}

function exportarComoJSON(mensajes, nombreUsuario, nombreAgente) {
  const data = {
    titulo: sesionExportarTitulo,
    mensajes: mensajes.map(m => ({ remitente: m.rol === "user" ? nombreUsuario : nombreAgente, rol: m.rol, contenido: m.contenido, fuentes: m.fuentes || [] }))
  };
  descargarArchivo(JSON.stringify(data, null, 2), `${sesionExportarTitulo}.json`, "application/json");
}

function exportarComoHTML(mensajes, nombreUsuario, nombreAgente) {
  let filasHtml = mensajes.map(m => `<div><strong>${m.rol === 'user' ? nombreUsuario : nombreAgente}:</strong> <p>${m.contenido}</p></div>`).join("");
  descargarArchivo(`<html><body><h2>${sesionExportarTitulo}</h2>${filasHtml}</body></html>`, `${sesionExportarTitulo}.html`, "text/html");
}

// ==========================================
// MODAL DE PERFIL Y AJUSTES
// ==========================================
function abrirModalPerfil() {
  document.getElementById("profile-name-input").value = (datosUsuarioCache && datosUsuarioCache.nombre) || "";
  document.getElementById("profile-agent-input").value = (datosUsuarioCache && datosUsuarioCache.nombre_agente) || "";
  seleccionarPronombrePerfil((datosUsuarioCache && datosUsuarioCache.pronombre) || "neutro");
  document.getElementById("profile-modal").style.display = "flex";
}
function cerrarModalPerfil() { document.getElementById("profile-modal").style.display = "none"; }

function seleccionarPronombrePerfil(valor, btn) {
  pronombreSeleccionado = valor;
  document.querySelectorAll('#profile-modal .pronoun-group .btn-choice').forEach(b => b.classList.remove('active'));
  if (btn) {
    btn.classList.add('active');
  } else {
    const target = document.getElementById(`profile-pronoun-${valor}`);
    if (target) target.classList.add('active');
  }
}

async function guardarAjustesPerfil() {
  const nombre = document.getElementById("profile-name-input").value.trim();
  const agente = document.getElementById("profile-agent-input").value.trim() || "Copiloto Técnico";

  await fetchConToken("/api/user/onboarding", {
    method: "POST",
    body: JSON.stringify({ nombre: nombre, pronombre: pronombreSeleccionado, nombre_agente: agente })
  });

  datosUsuarioCache.nombre = nombre;
  datosUsuarioCache.pronombre = pronombreSeleccionado;
  datosUsuarioCache.nombre_agente = agente;
  nombreAgenteGlobal = agente;

  actualizarTopbar(agente);
  actualizarSidebarPerfil(nombre, pronombreSeleccionado);
  cerrarModalPerfil();
}

function abrirModalAjustes() { document.getElementById("settings-modal").style.display = "flex"; }
function cerrarModalAjustes() { document.getElementById("settings-modal").style.display = "none"; }

// ==========================================
// SINCRONIZACIÓN Y REPOSITORIO
// ==========================================
async function comprobarSincronizacionFondo() {
  try {
    const res = await fetchConToken("/api/sync/check");
    if (!res.ok) return;
    const data = await res.json();

    const banner = document.getElementById("sync-notification-banner");
    if (!banner) return;

    if (data.requiere_sincronizacion) {
      document.getElementById("sync-banner-desc").innerText =
        `Se detectaron ${data.total_pendientes} archivos nuevos o modificados en el repositorio central.`;
      banner.style.display = "flex";
    } else {
      banner.style.display = "none";
    }
  } catch (e) {
    console.debug("Check de sincronización de fondo omitido:", e);
  }
}

function cerrarBannerSync() {
  const banner = document.getElementById("sync-notification-banner");
  if (banner) banner.style.display = "none";
}

function ejecutarSincronizacionDesdeBanner() {
  cerrarBannerSync();
  abrirModalAjustes();
  comprobarActualizacionesManuales();
}

async function comprobarActualizacionesManuales() {
  const container = document.getElementById("settings-progress-container");
  const barFill = document.getElementById("settings-bar-fill");
  const percText = document.getElementById("settings-progress-percentage");
  const fileText = document.getElementById("settings-current-file");
  const titleText = document.getElementById("settings-progress-title");

  if (!container) return;

  container.style.display = "block";
  barFill.style.width = "0%";
  percText.innerText = "0%";
  titleText.innerText = "Sincronizando base vectorial híbrida...";
  fileText.innerText = "Conectando con el servidor...";

  try {
    const res = await fetchConToken("/api/sync/stream");
    if (!res.ok) throw new Error("No se pudo iniciar el servicio de sincronización.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lineas = buffer.split("\n\n");
      buffer = lineas.pop();

      for (const bloque of lineas) {
        if (!bloque.startsWith("data: ")) continue;
        const payload = JSON.parse(bloque.replace("data: ", "").trim());

        if (payload.tipo === "progreso") {
          barFill.style.width = `${payload.progreso}%`;
          percText.innerText = `${payload.progreso}%`;
          fileText.innerText = `[${payload.progreso}%] ${payload.archivo} (${payload.mensaje})`;
        } else if (payload.tipo === "telemetria") {
          const d = payload.datos;
          if (d.omitido) {
            fileText.innerText = `⏭️ Omitido: ${d.nombre} (Sin cambios detectados)`;
          } else {
            fileText.innerText = `✅ Indexado: ${d.nombre} | ${d.chunks} chunks en ${d.tiempo_total_s}s`;
          }
        } else if (payload.tipo === "error_archivo") {
          console.warn(`Error en archivo ${payload.archivo}:`, payload.error);
        } else if (payload.tipo === "fin") {
          barFill.style.width = "100%";
          percText.innerText = "100%";
          titleText.innerText = "Sincronización completada";
          fileText.innerText = "Base vectorial híbrida actualizada con éxito.";
          setTimeout(() => {
            mostrarDialogo({ icono: "✅", titulo: "Completado", mensaje: "Repositorio sincronizado e indexado correctamente.", soloAlerta: true });
          }, 600);
        } else if (payload.tipo === "error") {
          throw new Error(payload.mensaje);
        }
      }
    }
  } catch (err) {
    console.error("Error en streaming de sincronización:", err);
    fileText.innerText = `Error: ${err.message}`;
    mostrarDialogo({ icono: "⚠️", titulo: "Error de sincronización", mensaje: err.message, soloAlerta: true });
  }
}

// ==========================================
// DIÁLOGO PERSONALIZADO Y TEMAS
// ==========================================
function mostrarDialogo({ icono="⚠️", titulo="Alerta", mensaje="", textoConfirmar="OK", textoCancelar="Cancelar", soloAlerta=false }) {
  return new Promise((resolve) => {
    const modal = document.getElementById("custom-dialog-modal");
    document.getElementById("custom-dialog-icon").innerText = icono;
    document.getElementById("custom-dialog-title").innerText = titulo;
    document.getElementById("custom-dialog-msg").innerText = mensaje;

    document.getElementById("custom-dialog-confirm-btn").onclick = () => { modal.style.display="none"; resolve(true); };
    if (soloAlerta) {
        document.getElementById("custom-dialog-cancel-btn").style.display = "none";
    } else {
        document.getElementById("custom-dialog-cancel-btn").style.display = "block";
        document.getElementById("custom-dialog-cancel-btn").onclick = () => { modal.style.display="none"; resolve(false); };
    }
    modal.style.display = "flex";
  });
}

function inicializarTema() {
  const guardado = localStorage.getItem("wm_theme") || "light";
  document.documentElement.setAttribute("data-theme", guardado);
  if(document.getElementById("theme-toggle-check")) document.getElementById("theme-toggle-check").checked = (guardado === "dark");
}

function alternarTema(esOscuro) {
  const t = esOscuro ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("wm_theme", t);
}

window.onload = inicializar;