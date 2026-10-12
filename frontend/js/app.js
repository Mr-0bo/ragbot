// frontend/js/app.js

let userId = localStorage.getItem("wm_user_id");
if (!userId) {
  userId = crypto.randomUUID();
  localStorage.setItem("wm_user_id", userId);
}

let sesionActivaId = null;
let pronombreSeleccionado = "neutro";
let regionSeleccionada = "mexico";
let nombreAgenteGlobal = "Agente de Búsqueda";
let datosUsuarioCache = null;

// Control de Sesión a exportar / contextual
let sesionExportarId = null;
let sesionExportarTitulo = "consulta";
let sesionRenombrarId = null;
let menuContextualActivo = null;

// Control de validación de rutas
const estadoRutasValidas = {
  obligatoria: false,
  opc1: true,
  opc2: true
};

// ==========================================
// DIÁLOGO PERSONALIZADO
// ==========================================
function mostrarDialogo({
  icono = "⚠️",
  titulo = "Confirmación",
  mensaje = "¿Deseas continuar?",
  textoConfirmar = "Confirmar",
  textoCancelar = "Cancelar",
  esPeligroso = false,
  soloAlerta = false
}) {
  return new Promise((resolve) => {
    const modal = document.getElementById("custom-dialog-modal");
    const iconEl = document.getElementById("custom-dialog-icon");
    const titleEl = document.getElementById("custom-dialog-title");
    const msgEl = document.getElementById("custom-dialog-msg");
    const btnConfirm = document.getElementById("custom-dialog-confirm-btn");
    const btnCancel = document.getElementById("custom-dialog-cancel-btn");

    iconEl.innerText = icono;
    titleEl.innerText = titulo;
    msgEl.innerText = mensaje;
    btnConfirm.innerText = textoConfirmar;

    if (esPeligroso) {
      btnConfirm.classList.add("danger");
    } else {
      btnConfirm.classList.remove("danger");
    }

    if (soloAlerta) {
      btnCancel.style.display = "none";
      btnConfirm.style.flex = "1";
    } else {
      btnCancel.style.display = "block";
      btnCancel.innerText = textoCancelar;
      btnConfirm.style.flex = "2";
    }

    function cerrar(resultado) {
      modal.style.display = "none";
      btnConfirm.onclick = null;
      btnCancel.onclick = null;
      resolve(resultado);
    }

    btnConfirm.onclick = () => cerrar(true);
    btnCancel.onclick = () => cerrar(false);

    modal.style.display = "flex";
  });
}

// ==========================================
// GESTIÓN DE TEMA (CLARO / OSCURO)
// ==========================================
function inicializarTema() {
  const guardado = localStorage.getItem("wm_theme") || "light";
  document.documentElement.setAttribute("data-theme", guardado);

  const check = document.getElementById("theme-toggle-check");
  const label = document.getElementById("theme-status-text");
  if (check) check.checked = guardado === "dark";
  if (label) label.innerText = guardado === "dark" ? "Modo oscuro" : "Modo claro";
}

function alternarTema(esOscuro) {
  const nuevoTema = esOscuro ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", nuevoTema);
  localStorage.setItem("wm_theme", nuevoTema);

  const label = document.getElementById("theme-status-text");
  if (label) label.innerText = esOscuro ? "Modo oscuro" : "Modo claro";
}

// ==========================================
// NAVEGACIÓN ONBOARDING (WIZARD EN 2 PASOS)
// ==========================================
function avanzarPaso2() {
  const nombre = document.getElementById("user-name-input").value.trim();
  if (!nombre) {
    mostrarDialogo({
      icono: "ℹ️",
      titulo: "Nombre requerido",
      mensaje: "Por favor escribe tu nombre para continuar.",
      textoConfirmar: "Entendido",
      soloAlerta: true
    });
    return;
  }

  document.getElementById("wizard-step-1").style.display = "none";
  document.getElementById("wizard-step-2").style.display = "block";
  document.getElementById("wizard-badge-icon").innerText = "📁";
  document.getElementById("modal-title").innerText = "Repositorio";
  document.getElementById("modal-desc").innerText = "Selecciona tu región y carpetas para indexar.";

  verificarHabilitacionBotonInicio();
}

function volverPaso1() {
  document.getElementById("wizard-step-2").style.display = "none";
  document.getElementById("wizard-step-1").style.display = "block";
  document.getElementById("wizard-badge-icon").innerText = "👋";
  document.getElementById("modal-title").innerText = "¡Bienvenido!";
  document.getElementById("modal-desc").innerText = "Configuremos tu perfil para empezar.";
}

// ==========================================
// SELECCIÓN DE PREFERENCIAS (ONBOARDING)
// ==========================================
function seleccionarPronombre(valor, btn) {
  pronombreSeleccionado = valor;
  document.querySelectorAll('.pronoun-group .btn-choice').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function seleccionarRegion(region) {
  regionSeleccionada = region;
  document.getElementById("region-card-mexico")?.classList.toggle("active", region === "mexico");
  document.getElementById("region-card-cam")?.classList.toggle("active", region === "centroamerica");
  actualizarBadgeRegionSidebar(region);
}

function actualizarBadgeRegionSidebar(region) {
  const badge = document.getElementById("sidebar-region-badge");
  if (badge) {
    badge.innerText = region === "mexico" ? "MEX" : "CAM";
    badge.title = region === "mexico" ? "México" : "Centroamérica";
  }
}

// ==========================================
// EXPLORADOR NATIVO Y VALIDACIÓN DE ONEDRIVE
// ==========================================
async function abrirSelectorDirectorio(targetInputId) {
  try {
    const res = await fetch("/api/browse-directory", { method: "POST" });
    const data = await res.json();
    if (data.ruta) {
      const input = document.getElementById(targetInputId);
      if (input) {
        input.value = data.ruta;
        await validarRutaInput(input);
      }
    }
  } catch (err) {
    console.error("Error al abrir diálogo de selección:", err);
  }
}

async function validarRutaInput(inputEl) {
  const ruta = inputEl.value.trim();
  const idInput = inputEl.id;
  const esObligatorio = idInput.includes("mandatory");
  const badgeId = idInput === "folder-mandatory-input" ? "badge-mandatory"
                : idInput === "folder-opc1-input" ? "badge-opc1"
                : idInput === "folder-opc2-input" ? "badge-opc2" : null;
  const badgeEl = badgeId ? document.getElementById(badgeId) : null;

  if (!ruta) {
    if (esObligatorio) {
      marcarCampoEstado(inputEl, badgeEl, false, "Obligatorio");
      estadoRutasValidas.obligatoria = false;
    } else {
      limpiarCampoEstado(inputEl, badgeEl);
      if (idInput.includes("opc1")) estadoRutasValidas.opc1 = true;
      if (idInput.includes("opc2")) estadoRutasValidas.opc2 = true;
    }
    verificarHabilitacionBotonInicio();
    return;
  }

  try {
    const res = await fetch("/api/validate-directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ruta })
    });

    if (res.ok) {
      const data = await res.json();
      inputEl.value = data.ruta_normalizada;
      marcarCampoEstado(inputEl, badgeEl, true, "✓ Carpeta Válida");
      if (esObligatorio) estadoRutasValidas.obligatoria = true;
      if (idInput.includes("opc1")) estadoRutasValidas.opc1 = true;
      if (idInput.includes("opc2")) estadoRutasValidas.opc2 = true;
    } else {
      const err = await res.json();
      marcarCampoEstado(inputEl, badgeEl, false, err.detail || "Ruta inválida");
      if (esObligatorio) estadoRutasValidas.obligatoria = false;
      if (idInput.includes("opc1")) estadoRutasValidas.opc1 = false;
      if (idInput.includes("opc2")) estadoRutasValidas.opc2 = false;
    }
  } catch (e) {
    marcarCampoEstado(inputEl, badgeEl, false, "Error de validación");
    if (esObligatorio) estadoRutasValidas.obligatoria = false;
  }

  verificarHabilitacionBotonInicio();
}

function marcarCampoEstado(inputEl, badgeEl, esValido, mensaje) {
  inputEl.classList.toggle("input-success", esValido);
  inputEl.classList.toggle("input-error", !esValido);
  if (badgeEl) {
    badgeEl.innerText = mensaje;
    badgeEl.className = `path-status-badge ${esValido ? 'valid' : 'invalid'}`;
    badgeEl.style.display = "inline-block";
  }
}

function limpiarCampoEstado(inputEl, badgeEl) {
  inputEl.classList.remove("input-success", "input-error");
  if (badgeEl) {
    badgeEl.innerText = "";
    badgeEl.style.display = "none";
  }
}

function verificarHabilitacionBotonInicio() {
  const nombre = document.getElementById("user-name-input")?.value.trim();
  const puedeHabilitar = Boolean(nombre && estadoRutasValidas.obligatoria && estadoRutasValidas.opc1 && estadoRutasValidas.opc2);

  const btn = document.getElementById("btn-start-app");
  const tooltipWrapper = document.getElementById("btn-start-tooltip");

  if (btn) {
    if (puedeHabilitar) {
      btn.classList.remove("btn-disabled");
      if (tooltipWrapper) tooltipWrapper.removeAttribute("data-tooltip");
    } else {
      btn.classList.add("btn-disabled");
      if (tooltipWrapper) tooltipWrapper.setAttribute("data-tooltip", "Debes validar la carpeta obligatoria para comenzar");
    }
  }
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

  document.getElementById("user-name-input")?.addEventListener("input", verificarHabilitacionBotonInicio);

  try {
    const res = await fetch(`/api/user/${userId}`);
    datosUsuarioCache = await res.json();

    if (!datosUsuarioCache.disclaimer_aceptado) {
      const modal = document.getElementById("disclaimer-modal");
      if (modal) modal.style.display = "flex";
    } else {
      procederPostDisclaimer();
    }
  } catch (err) {
    console.error("Error consultando usuario:", err);
    const modal = document.getElementById("disclaimer-modal");
    if (modal) modal.style.display = "flex";
  }
}

async function aceptarDisclaimer() {
  const check = document.getElementById("dont-show-disclaimer-check");
  const noVolverAMostrar = check ? check.checked : false;

  try {
    await fetch('/api/user/disclaimer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        no_volver_a_mostrar: noVolverAMostrar
      })
    });
  } catch (e) {
    console.error("Error guardando preferencia de disclaimer:", e);
  }

  const modal = document.getElementById("disclaimer-modal");
  if (modal) modal.style.display = "none";

  procederPostDisclaimer();
}

async function procederPostDisclaimer() {
  if (!datosUsuarioCache || !datosUsuarioCache.onboarding_completado) {
    const onboarding = document.getElementById("onboarding-modal");
    if (onboarding) {
      volverPaso1();
      onboarding.style.display = "flex";
    }
  } else {
    nombreAgenteGlobal = datosUsuarioCache.nombre_agente || "Agente de Búsqueda";
    regionSeleccionada = datosUsuarioCache.region || "mexico";
    actualizarTopbar(nombreAgenteGlobal);
    actualizarSidebarPerfil(datosUsuarioCache.nombre, datosUsuarioCache.pronombre);
    actualizarBadgeRegionSidebar(regionSeleccionada);
    await cargarSesiones();

    setTimeout(comprobarSincronizacionFondo, 1500);
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
    pronounEl.innerText = etiquetas[pronombre] || "Configuración";
  }
  if (avatarEl && nombreUsuario) {
    avatarEl.innerText = nombreUsuario.charAt(0).toUpperCase();
  }
}

// ==========================================
// INGESTA EN TIEMPO REAL CON SSE (SERVER-SENT EVENTS)
// ==========================================
async function iniciarGuardadoEIndexacion() {
  const btn = document.getElementById("btn-start-app");
  if (btn.classList.contains("btn-disabled")) return;

  const nombre = document.getElementById("user-name-input").value.trim();
  const nombreAgente = document.getElementById("agent-name-input").value.trim() || "Agente de Búsqueda";
  const mandatory = document.getElementById("folder-mandatory-input").value.trim();
  const opc1 = document.getElementById("folder-opc1-input")?.value.trim() || null;
  const opc2 = document.getElementById("folder-opc2-input")?.value.trim() || null;

  try {
    btn.classList.add("btn-disabled");
    const res = await fetch("/api/user/onboarding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        nombre: nombre,
        pronombre: pronombreSeleccionado,
        nombre_agente: nombreAgente,
        region: regionSeleccionada,
        directorio_obligatorio: mandatory,
        directorio_opcional_1: opc1,
        directorio_opcional_2: opc2
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error guardando configuración");
    }

    datosUsuarioCache = {
      registrado: true,
      onboarding_completado: true,
      nombre,
      pronombre: pronombreSeleccionado,
      nombre_agente: nombreAgente,
      region: regionSeleccionada,
      directorio_obligatorio: mandatory,
      directorio_opcional_1: opc1,
      directorio_opcional_2: opc2
    };

    nombreAgenteGlobal = nombreAgente;
    actualizarTopbar(nombreAgenteGlobal);
    actualizarSidebarPerfil(nombre, pronombreSeleccionado);
    actualizarBadgeRegionSidebar(regionSeleccionada);

    const progressBox = document.getElementById("onboarding-progress-container");
    progressBox.style.display = "block";

    conectarStreamSincronizacion({
      onProgress: (progreso, mensaje, archivo) => {
        document.getElementById("progress-bar-fill").style.width = `${progreso}%`;
        document.getElementById("progress-percentage").innerText = `${progreso}%`;
        if (archivo) {
          document.getElementById("progress-current-filename").innerText = `Indexando: ${archivo}`;
        }
      },
      onComplete: async () => {
        document.getElementById("progress-bar-fill").style.width = "100%";
        document.getElementById("progress-percentage").innerText = "100%";
        document.getElementById("progress-status-title").innerText = "¡Todo listo!";
        document.getElementById("progress-current-filename").innerText = "Base de datos vectorial generada correctamente.";

        setTimeout(async () => {
          document.getElementById("onboarding-modal").style.display = "none";
          await cargarSesiones();
        }, 800);
      },
      onError: async (errMsg) => {
        btn.classList.remove("btn-disabled");
        await mostrarDialogo({
          icono: "⚠️",
          titulo: "Error de indexación",
          mensaje: errMsg,
          textoConfirmar: "Reintentar",
          soloAlerta: true
        });
      }
    });

  } catch (err) {
    btn.classList.remove("btn-disabled");
    await mostrarDialogo({
      icono: "⚠️",
      titulo: "Error",
      mensaje: err.message || "No se pudo guardar la configuración.",
      textoConfirmar: "Aceptar",
      soloAlerta: true
    });
  }
}

function conectarStreamSincronizacion({ onProgress, onComplete, onError }) {
  const eventSource = new EventSource("/api/sync/stream");

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.tipo === "progreso") {
        onProgress(data.progreso, data.mensaje, data.archivo);
      } else if (data.tipo === "fin") {
        eventSource.close();
        onComplete();
      } else if (data.tipo === "error") {
        eventSource.close();
        onError(data.mensaje);
      }
    } catch (e) {
      console.error("Error parseando evento SSE:", e);
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
    onError("Se interrumpió la conexión con el motor de sincronización.");
  };
}

// ==========================================
// COMPROBACIÓN SILENCIOSA Y BANNER DE CAMBIOS
// ==========================================
async function comprobarSincronizacionFondo() {
  try {
    const res = await fetch("/api/sync/check");
    if (!res.ok) return;
    const data = await res.json();

    if (data.requiere_sincronizacion) {
      const banner = document.getElementById("sync-notification-banner");
      const desc = document.getElementById("sync-banner-desc");
      if (desc) {
        desc.innerText = `Se detectaron ${data.total_pendientes} cambios (${data.nuevos} nuevos, ${data.modificados} modificados, ${data.eliminados} eliminados) en tus carpetas.`;
      }
      if (banner) banner.style.display = "flex";
    }
  } catch (e) {
    console.debug("Check silencioso de sincronización omitido:", e);
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

// ==========================================
// MODAL DE AJUSTES TÉCNICOS (SIDEBAR)
// ==========================================
function abrirModalAjustes() {
  const modal = document.getElementById("settings-modal");
  if (datosUsuarioCache) {
    document.getElementById("settings-mandatory-input").value = datosUsuarioCache.directorio_obligatorio || "";
    document.getElementById("settings-opc1-input").value = datosUsuarioCache.directorio_opcional_1 || "";
    document.getElementById("settings-opc2-input").value = datosUsuarioCache.directorio_opcional_2 || "";
    cambiarRegionAjustes(datosUsuarioCache.region || "mexico");
  }
  modal.style.display = "flex";
}

function cerrarModalAjustes() {
  document.getElementById("settings-modal").style.display = "none";
}

function cambiarRegionAjustes(region) {
  regionSeleccionada = region;
  document.getElementById("settings-region-mexico")?.classList.toggle("active", region === "mexico");
  document.getElementById("settings-region-cam")?.classList.toggle("active", region === "centroamerica");
}

async function guardarAjustesDirectorios() {
  const mandatory = document.getElementById("settings-mandatory-input").value.trim();
  const opc1 = document.getElementById("settings-opc1-input").value.trim() || null;
  const opc2 = document.getElementById("settings-opc2-input").value.trim() || null;

  if (!mandatory) {
    await mostrarDialogo({
      icono: "⚠️",
      titulo: "Directorio obligatorio",
      mensaje: "No puedes dejar la aplicación sin al menos una carpeta principal configurada.",
      textoConfirmar: "Entendido",
      soloAlerta: true
    });
    return;
  }

  try {
    const res = await fetch("/api/config/directories", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        region: regionSeleccionada,
        directorio_obligatorio: mandatory,
        directorio_opcional_1: opc1,
        directorio_opcional_2: opc2
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error al actualizar directorios");
    }

    datosUsuarioCache.region = regionSeleccionada;
    datosUsuarioCache.directorio_obligatorio = mandatory;
    datosUsuarioCache.directorio_opcional_1 = opc1;
    datosUsuarioCache.directorio_opcional_2 = opc2;

    actualizarBadgeRegionSidebar(regionSeleccionada);
    cerrarModalAjustes();

    await mostrarDialogo({
      icono: "✓",
      titulo: "Configuración guardada",
      mensaje: "Rutas y región actualizadas con éxito.",
      textoConfirmar: "Aceptar",
      soloAlerta: true
    });
  } catch (e) {
    await mostrarDialogo({
      icono: "⚠️",
      titulo: "Error",
      mensaje: e.message,
      textoConfirmar: "Aceptar",
      soloAlerta: true
    });
  }
}

async function comprobarActualizacionesManuales() {
  const progressBox = document.getElementById("settings-progress-container");
  progressBox.style.display = "block";

  conectarStreamSincronizacion({
    onProgress: (progreso, mensaje, archivo) => {
      document.getElementById("settings-bar-fill").style.width = `${progreso}%`;
      document.getElementById("settings-progress-percentage").innerText = `${progreso}%`;
      if (archivo) {
        document.getElementById("settings-current-file").innerText = `Procesando: ${archivo}`;
      }
    },
    onComplete: async () => {
      document.getElementById("settings-bar-fill").style.width = "100%";
      document.getElementById("settings-progress-percentage").innerText = "100%";
      document.getElementById("settings-current-file").innerText = "Sincronización finalizada.";
      setTimeout(() => {
        progressBox.style.display = "none";
      }, 1500);
    },
    onError: async (errMsg) => {
      progressBox.style.display = "none";
      await mostrarDialogo({
        icono: "⚠️",
        titulo: "Error",
        mensaje: errMsg,
        textoConfirmar: "Aceptar",
        soloAlerta: true
      });
    }
  });
}

// ==========================================
// SESIONES Y HISTORIAL
// ==========================================
async function cargarSesiones() {
  try {
    const res = await fetch(`/api/sessions/${userId}`);
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
        pinIcon.title = "Chat fijado";
        pinIcon.innerHTML = `
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="17" x2="12" y2="22"></line>
            <path d="M5 17h14v-2l-2-2V5a1 1 0 0 0-1-1h-8a1 1 0 0 0-1 1v8l-2 2v2z"></path>
          </svg>
        `;
        wrap.appendChild(pinIcon);
      }

      const titleSpan = document.createElement("span");
      titleSpan.className = "session-title-text";
      titleSpan.innerText = s.titulo;
      wrap.appendChild(titleSpan);

      const btnDots = document.createElement("button");
      btnDots.className = "btn-session-options";
      btnDots.innerHTML = "•••";
      btnDots.title = "Opciones";
      btnDots.onclick = (e) => {
        e.stopPropagation();
        abrirMenuContextual(e, s.id, s.titulo, Boolean(s.fijado), li);
      };

      li.appendChild(wrap);
      li.appendChild(btnDots);
      listEl.appendChild(li);
    });

    if (!sesionActivaId && sesiones.length > 0) {
      alternarSesion(sesiones[0].id);
    }
  } catch (e) {
    console.error("Error al cargar sesiones:", e);
  }
}

function abrirMenuContextual(event, sessionId, sessionTitle, estaFijado, itemEl) {
  cerrarMenuContextual();
  itemEl.classList.add("options-open");

  const menu = document.createElement("div");
  menu.className = "chat-context-menu";

  const textoPin = estaFijado ? "Desfijar chat" : "Fijar chat";
  const iconoPin = estaFijado ? `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="2" y1="2" x2="22" y2="22"></line>
      <path d="M12 17v5"></path>
      <path d="M9 9l-4 4v2h14v-2l-1.5-1.5"></path>
      <path d="M9 4h6a1 1 0 0 1 1 1v7"></path>
    </svg>
  ` : `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="17" x2="12" y2="22"></line>
      <path d="M5 17h14v-2l-2-2V5a1 1 0 0 0-1-1h-8a1 1 0 0 0-1 1v8l-2 2v2z"></path>
    </svg>
  `;

  menu.innerHTML = `
    <button class="context-menu-item" id="opt-export">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"></path>
        <polyline points="16 6 12 2 8 6"></polyline>
        <line x1="12" y1="2" x2="12" y2="15"></line>
      </svg>
      Exportar chat
    </button>
    <button class="context-menu-item" id="opt-pin">
      ${iconoPin}
      ${textoPin}
    </button>
    <button class="context-menu-item" id="opt-rename">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
      </svg>
      Cambiar nombre
    </button>
    <div class="context-menu-divider"></div>
    <button class="context-menu-item danger" id="opt-delete">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
      </svg>
      Borrar chat
    </button>
  `;

  document.body.appendChild(menu);

  const rect = event.currentTarget.getBoundingClientRect();
  const menuWidth = 175;
  let left = rect.left;
  if (left + menuWidth > window.innerWidth - 10) {
    left = window.innerWidth - menuWidth - 10;
  }
  menu.style.left = `${left}px`;
  menu.style.top = `${rect.bottom + 5}px`;

  menuContextualActivo = menu;

  menu.querySelector("#opt-export").onclick = (e) => {
    e.stopPropagation();
    cerrarMenuContextual();
    abrirModalExportar(sessionId, sessionTitle);
  };

  menu.querySelector("#opt-pin").onclick = async (e) => {
    e.stopPropagation();
    cerrarMenuContextual();
    await alternarFijarSesion(sessionId);
  };

  menu.querySelector("#opt-rename").onclick = (e) => {
    e.stopPropagation();
    cerrarMenuContextual();
    abrirModalRenombrar(sessionId, sessionTitle);
  };

  menu.querySelector("#opt-delete").onclick = async (e) => {
    e.stopPropagation();
    cerrarMenuContextual();
    await eliminarChatIndividual(sessionId, sessionTitle);
  };
}

async function alternarFijarSesion(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${sessionId}/pin`, { method: "PATCH" });
    if (!res.ok) {
      const err = await res.json();
      await mostrarDialogo({
        icono: "📌",
        titulo: "Límite de fijados",
        mensaje: err.detail || "Solo puedes fijar un máximo de 3 consultas.",
        textoConfirmar: "Entendido",
        soloAlerta: true
      });
      return;
    }
    await cargarSesiones();
  } catch (err) {
    console.error("Error al fijar/desfijar sesión:", err);
  }
}

function abrirModalRenombrar(sessionId, sessionTitle) {
  sesionRenombrarId = sessionId;
  const inputEl = document.getElementById("rename-input");
  inputEl.value = sessionTitle;
  document.getElementById("rename-modal").style.display = "flex";
  inputEl.focus();
}

function cerrarModalRenombrar() {
  document.getElementById("rename-modal").style.display = "none";
  sesionRenombrarId = null;
}

async function guardarRenombrar() {
  if (!sesionRenombrarId) return;
  const inputEl = document.getElementById("rename-input");
  const nuevoTitulo = inputEl.value.trim();

  if (!nuevoTitulo) return;

  try {
    const res = await fetch(`/api/sessions/${sesionRenombrarId}/rename`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ titulo: nuevoTitulo })
    });

    if (!res.ok) throw new Error("No se pudo actualizar el nombre");

    cerrarModalRenombrar();
    await cargarSesiones();
  } catch (err) {
    console.error(err);
  }
}

async function eliminarChatIndividual(sessionId, sessionTitle) {
  const confirmado = await mostrarDialogo({
    icono: "🗑️",
    titulo: "Eliminar consulta",
    mensaje: `¿Deseas eliminar permanentemente "${sessionTitle}"?`,
    textoConfirmar: "Eliminar",
    textoCancelar: "Cancelar",
    esPeligroso: true
  });

  if (!confirmado) return;

  try {
    const res = await fetch(`/api/sessions/single/${sessionId}`, { method: "DELETE" });
    if (!res.ok) return;

    const scrollEl = document.getElementById("chat-scroll");
    if (scrollEl) scrollEl.innerHTML = "";
    sesionActivaId = null;

    await crearSesion();
  } catch (err) {
    console.error("Error eliminando chat individual:", err);
  }
}

function cerrarMenuContextual() {
  if (menuContextualActivo) {
    const m = menuContextualActivo;
    m.classList.add("closing");
    document.querySelectorAll(".session-item.options-open").forEach(el => el.classList.remove("options-open"));
    setTimeout(() => {
      if (m.parentNode) m.parentNode.removeChild(m);
    }, 120);
    menuContextualActivo = null;
  }
}

// ==========================================
// EXPORTACIÓN DE CHATS
// ==========================================
function abrirModalExportar(sessionId, sessionTitle) {
  sesionExportarId = sessionId || sesionActivaId;
  sesionExportarTitulo = sessionTitle || "consulta";
  document.getElementById("export-modal").style.display = "flex";
}

function cerrarModalExportar() {
  document.getElementById("export-modal").style.display = "none";
  sesionExportarId = null;
}

async function ejecutarExportacion(formato) {
  const sid = sesionExportarId || sesionActivaId;
  if (!sid) return;

  try {
    const res = await fetch(`/api/messages/${sid}`);
    const mensajes = await res.json();

    const nombreUsuario = (datosUsuarioCache && datosUsuarioCache.nombre) || "Usuario";
    const nombreAgente = nombreAgenteGlobal || "Agente de Búsqueda";

    if (formato === "json") {
      exportarComoJSON(mensajes, nombreUsuario, nombreAgente);
    } else if (formato === "html") {
      exportarComoHTML(mensajes, nombreUsuario, nombreAgente);
    }

    cerrarModalExportar();
  } catch (err) {
    console.error("Error al exportar:", err);
  }
}

function descargarArchivo(contenido, nombreArchivo, mimeType) {
  const blob = new Blob([contenido], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombreArchivo;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportarComoJSON(mensajes, nombreUsuario, nombreAgente) {
  const data = {
    titulo: sesionExportarTitulo,
    region: regionSeleccionada,
    fecha_exportacion: new Date().toISOString(),
    usuario: nombreUsuario,
    agente: nombreAgente,
    mensajes: mensajes.map(m => ({
      remitente: m.rol === "user" ? nombreUsuario : nombreAgente,
      rol: m.rol,
      contenido: m.contenido,
      fuentes: m.fuentes || []
    }))
  };

  const nombreLimpio = sesionExportarTitulo.replace(/[^a-z0-9]/gi, '_').toLowerCase();
  descargarArchivo(JSON.stringify(data, null, 2), `${nombreLimpio}.json`, "application/json");
}

function exportarComoHTML(mensajes, nombreUsuario, nombreAgente) {
  const temaActual = document.documentElement.getAttribute("data-theme") || "light";
  const esOscuro = temaActual === "dark";

  const colorFondo = esOscuro ? '#15181C' : '#F8F9FC';
  const colorTexto = esOscuro ? '#EDEDED' : '#12161A';
  const colorBorde = esOscuro ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 30, 96, 0.1)';
  const colorBurbujaAsistente = esOscuro ? '#20242A' : '#FFFFFF';
  const colorTextoAsistente = esOscuro ? '#F0F2F5' : '#12161A';
  const colorTagTexto = esOscuro ? '#4DBDF5' : '#001E60';

  marked.setOptions({ breaks: true });

  let filasHtml = "";
  mensajes.forEach(m => {
    const esUser = m.rol === "user";
    const remitente = esUser ? nombreUsuario : nombreAgente;
    let fuentesHtml = "";

    if (m.fuentes && m.fuentes.length > 0) {
      const tags = m.fuentes.map(f => `<span class="source-tag">${f}</span>`).join("");
      fuentesHtml = `<div class="sources-box"><strong>Fuente(s):</strong> ${tags}</div>`;
    }

    const contenidoHtml = marked.parse(m.contenido);

    filasHtml += `
      <div class="msg-row ${esUser ? 'user' : 'assistant'}">
        <div class="msg-sender">${remitente}</div>
        <div class="msg-bubble">
          <div class="msg-text">${contenidoHtml}</div>
          ${fuentesHtml}
        </div>
      </div>
    `;
  });

  const cssReglas = `
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    body { background-color: ${colorFondo}; color: ${colorTexto}; display: flex; justify-content: center; padding: 40px 20px; }
    .chat-container { width: 100%; max-width: 840px; display: flex; flex-direction: column; gap: 22px; }
    .chat-header { padding-bottom: 20px; border-bottom: 1px solid ${colorBorde}; }
    .chat-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
    .chat-header span { font-size: 13px; color: #8898AA; }
    .msg-row { display: flex; flex-direction: column; width: 100%; }
    .msg-row.user { align-items: flex-end; }
    .msg-row.assistant { align-items: flex-start; }
    .msg-sender { font-size: 11.5px; font-weight: 600; color: #8898AA; margin-bottom: 5px; padding: 0 4px; }
    .msg-bubble { max-width: 75%; padding: 16px 20px; font-size: 14.5px; line-height: 1.6; border-radius: 18px; box-shadow: 0 4px 14px rgba(0,0,0,0.04); }
    .msg-row.user .msg-bubble { background: #0053E2; color: #FFFFFF; border-bottom-right-radius: 4px; }
    .msg-row.assistant .msg-bubble { background: ${colorBurbujaAsistente}; color: ${colorTextoAsistente}; border: 1px solid ${colorBorde}; border-bottom-left-radius: 4px; }
    .sources-box { margin-top: 12px; padding-top: 10px; border-top: 1px solid ${colorBorde}; font-size: 12px; }
    .source-tag { display: inline-block; background: rgba(77, 189, 245, 0.18); color: ${colorTagTexto}; border-radius: 6px; padding: 3px 8px; margin: 3px 4px 3px 0; font-weight: 600; }
    table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13.5px; }
    th, td { border: 1px solid ${colorBorde}; padding: 8px 12px; text-align: left; }
    th { background: rgba(0,0,0,0.04); font-weight: 600; }
  `;

  const encabezadoHtml = `<!DOCTYPE html>\n<html lang="es">\n<head>\n<meta charset="UTF-8">\n<title>${sesionExportarTitulo}</title>\n<style>${cssReglas}</style>\n</head>\n<body>\n<div class="chat-container">\n<div class="chat-header">\n<h1>${sesionExportarTitulo}</h1>\n<span>Exportado el ${new Date().toLocaleDateString()} • Asistente: ${nombreAgente}</span>\n</div>\n`;
  const pieHtml = `</div>\n</body>\n</html>`;

  const nombreLimpio = sesionExportarTitulo.replace(/[^a-z0-9]/gi, '_').toLowerCase();
  descargarArchivo(encabezadoHtml + filasHtml + pieHtml, `${nombreLimpio}.html`, "text/html");
}

// ==========================================
// OPERACIONES DEL CHAT
// ==========================================
async function crearSesion() {
  const res = await fetch(`/api/sessions/${userId}`, { method: 'POST' });
  const nueva = await res.json();
  sesionActivaId = nueva.id;
  await cargarSesiones();
  alternarSesion(nueva.id);
}

async function alternarSesion(sessionId) {
  sesionActivaId = sessionId;
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  await cargarHistorial(sessionId);
  await cargarSesiones();
}

async function cargarHistorial(sessionId) {
  try {
    const res = await fetch(`/api/messages/${sessionId}`);
    const mensajes = await res.json();
    const scrollEl = document.getElementById("chat-scroll");
    scrollEl.innerHTML = "";

    mensajes.forEach(m => renderizarBurbuja(m.contenido, m.rol, m.fuentes || []));
  } catch (e) {
    console.error("Error al cargar historial:", e);
  }
}

async function eliminarTodosLosChats() {
  const confirmado = await mostrarDialogo({
    icono: "🚨",
    titulo: "¿Vaciar historial?",
    mensaje: "Se eliminarán permanentemente todas las consultas registradas.",
    textoConfirmar: "Eliminar todo",
    textoCancelar: "Cancelar",
    esPeligroso: true
  });

  if (!confirmado) return;

  try {
    const res = await fetch(`/api/sessions/${userId}/clear-all`, { method: "DELETE" });
    if (res.ok) {
      document.getElementById("session-list").innerHTML = "";
      document.getElementById("chat-scroll").innerHTML = "";
      sesionActivaId = null;
      await crearSesion();
    }
  } catch (err) {
    console.error("Error al vaciar chats:", err);
  }
}

function mostrarIndicadorPensando() {
  const scrollEl = document.getElementById("chat-scroll");
  const row = document.createElement("div");
  row.className = "message-row assistant";
  row.id = "thinking-bubble";

  row.innerHTML = `
    <div class="typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  scrollEl.appendChild(row);
  scrollEl.scrollTop = scrollEl.scrollHeight;
}

function removerIndicadorPensando() {
  const thinking = document.getElementById("thinking-bubble");
  if (thinking) thinking.remove();
}

async function renderizarBurbuja(texto, rol, fuentes = []) {
  const scrollEl = document.getElementById("chat-scroll");
  const row = document.createElement("div");
  row.className = `message-row ${rol}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  marked.setOptions({ breaks: true });
  bubble.innerHTML = marked.parse(texto);

  row.appendChild(bubble);
  scrollEl.appendChild(row);

  if (fuentes && fuentes.length > 0) {
    const fuentesDiv = document.createElement("div");
    fuentesDiv.className = "sources-container";
    fuentesDiv.innerHTML = "<strong>Fuente(s):</strong> ";
    fuentes.forEach(f => {
      const tag = document.createElement("span");
      tag.className = "source-tag";
      tag.innerText = f;
      fuentesDiv.appendChild(tag);
    });
    bubble.appendChild(fuentesDiv);
  }

  scrollEl.scrollTo({ top: scrollEl.scrollHeight, behavior: 'smooth' });
}

async function enviarMensaje() {
  const input = document.getElementById("query-input");
  const texto = input.value.trim();
  if (!texto || !sesionActivaId) return;

  input.value = "";
  renderizarBurbuja(texto, "user", []);
  mostrarIndicadorPensando();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        session_id: sesionActivaId,
        pregunta: texto
      })
    });
    const data = await res.json();

    removerIndicadorPensando();
    await renderizarBurbuja(data.respuesta, "assistant", data.fuentes);
    await cargarSesiones();
  } catch (err) {
    removerIndicadorPensando();
    renderizarBurbuja("Ocurrió un inconveniente al consultar los archivos locales. Inténtalo de nuevo.", "assistant", []);
  }
}

function alPresionarTecla(e) {
  if (e.key === "Enter") enviarMensaje();
}

// ==========================================
// MODAL DE PERFIL DE USUARIO
// ==========================================
let pronombrePerfilSeleccionado = "neutro";

function abrirModalPerfil() {
  const modal = document.getElementById("profile-modal");
  if (datosUsuarioCache) {
    document.getElementById("profile-name-input").value = datosUsuarioCache.nombre || "";
    document.getElementById("profile-agent-input").value = datosUsuarioCache.nombre_agente || "";
    seleccionarPronombrePerfil(datosUsuarioCache.pronombre || "neutro", document.getElementById(`profile-pronoun-${datosUsuarioCache.pronombre || "neutro"}`));
  }
  modal.style.display = "flex";
}

function cerrarModalPerfil() {
  document.getElementById("profile-modal").style.display = "none";
}

function seleccionarPronombrePerfil(valor, btn) {
  pronombrePerfilSeleccionado = valor;
  document.querySelectorAll('#profile-modal .btn-choice').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

async function guardarAjustesPerfil() {
  const nombre = document.getElementById("profile-name-input").value.trim();
  const agente = document.getElementById("profile-agent-input").value.trim() || "Agente de Búsqueda";

  if (!nombre) {
    await mostrarDialogo({
      icono: "ℹ️", titulo: "Nombre requerido", mensaje: "Por favor escribe tu nombre.", textoConfirmar: "Entendido", soloAlerta: true
    });
    return;
  }

  try {
    // Reutilizamos el endpoint de onboarding pasando los datos existentes de carpetas
    const res = await fetch("/api/user/onboarding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        nombre: nombre,
        pronombre: pronombrePerfilSeleccionado,
        nombre_agente: agente,
        region: datosUsuarioCache.region,
        directorio_obligatorio: datosUsuarioCache.directorio_obligatorio,
        directorio_opcional_1: datosUsuarioCache.directorio_opcional_1,
        directorio_opcional_2: datosUsuarioCache.directorio_opcional_2
      })
    });

    if (!res.ok) throw new Error("Error al guardar el perfil");

    // Actualizar caché y UI
    datosUsuarioCache.nombre = nombre;
    datosUsuarioCache.pronombre = pronombrePerfilSeleccionado;
    datosUsuarioCache.nombre_agente = agente;
    nombreAgenteGlobal = agente;

    actualizarTopbar(agente);
    actualizarSidebarPerfil(nombre, pronombrePerfilSeleccionado);
    cerrarModalPerfil();

    await mostrarDialogo({
      icono: "✓", titulo: "Perfil actualizado", mensaje: "Tus datos se guardaron correctamente.", textoConfirmar: "Aceptar", soloAlerta: true
    });
  } catch (e) {
    await mostrarDialogo({
      icono: "⚠️", titulo: "Error", mensaje: e.message, textoConfirmar: "Aceptar", soloAlerta: true
    });
  }
}

// ==========================================
// NUEVO FLUJO DE IMPORTACIÓN DESDE MODAL DEDICADO
// ==========================================
function abrirModalImportar() {
  document.getElementById("import-path-input").value = "";
  document.getElementById("import-modal").style.display = "flex";
}

function cerrarModalImportar() {
  document.getElementById("import-modal").style.display = "none";
}

async function abrirSelectorArchivoNativo() {
  try {
    const res = await fetch("/api/browse-file", { method: "POST" });
    const data = await res.json();
    if (data.ruta) {
      document.getElementById("import-path-input").value = data.ruta;
    }
  } catch (err) {
    console.error("Error al abrir el selector de archivo:", err);
  }
}

async function ejecutarImportacion() {
  const ruta = document.getElementById("import-path-input").value.trim();

  if (!ruta || !ruta.toLowerCase().endsWith('.json')) {
    await mostrarDialogo({
      icono: "⚠️",
      titulo: "Archivo no válido",
      mensaje: "Por favor, selecciona o escribe la ruta de un archivo .json válido.",
      textoConfirmar: "Entendido",
      soloAlerta: true
    });
    return;
  }

  try {
    const res = await fetch(`/api/sessions/${userId}/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ruta_archivo: ruta })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error en la importación.");
    }

    const data = await res.json();

    cerrarModalImportar();
    await cargarSesiones();
    alternarSesion(data.session_id);

    await mostrarDialogo({
      icono: "✅",
      titulo: "Importación exitosa",
      mensaje: `El chat se ha restaurado correctamente en tu historial.`,
      textoConfirmar: "Aceptar",
      soloAlerta: true
    });

  } catch (error) {
    console.error(error);
    await mostrarDialogo({
      icono: "⚠️",
      titulo: "Error de importación",
      mensaje: error.message || "El archivo JSON no se pudo leer o está corrupto.",
      textoConfirmar: "Aceptar",
      soloAlerta: true
    });
  }
}

window.onload = inicializar;