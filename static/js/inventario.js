/**
 * JavaScript propio del sistema de inventario.
 * Usa las librerías que trae la plantilla Mono: jQuery, Bootstrap y ApexCharts.
 *
 * 1. Gráfica de dona del Dashboard
 * 2. Búsqueda de piezas sin recargar la página (fetch)
 * 3. Ventana para confirmar acciones (eliminar, autorizar, desactivar)
 * 4. Ventana para rechazar una solicitud con su motivo
 * 5. Solicitud de material: existencia disponible de la pieza elegida
 * 6. Movimiento: vista previa de cómo quedará la existencia
 * 7. Botón para imprimir el reporte
 */
(function () {
  "use strict";

  /* ======== 1. GRÁFICA DE DONA ======== */
  var grafica = document.getElementById("grafica-estados");
  if (grafica && window.ApexCharts) {
    var series = [
      Number(grafica.dataset.disponibles),
      Number(grafica.dataset.bajas),
      Number(grafica.dataset.agotadas)
    ];
    var total = series[0] + series[1] + series[2];

    if (total > 0) {
      new ApexCharts(grafica, {
        chart: { type: "donut", height: 270, fontFamily: "Roboto, sans-serif" },
        // colores success, warning y danger de la plantilla
        colors: ["#0acb8e", "#fec400", "#fe5461"],
        labels: ["En stock", "Stock bajo", "Agotadas"],
        series: series,
        dataLabels: { enabled: false },
        stroke: { width: 2, colors: ["#ffffff"] },
        legend: {
          position: "right",
          offsetY: 50,
          fontSize: "14px",
          formatter: function (nombre, opciones) {
            var valor = opciones.w.globals.series[opciones.seriesIndex];
            var porcentaje = Math.round((valor / total) * 1000) / 10;
            return nombre + ": " + valor + " (" + porcentaje + " %)";
          }
        },
        plotOptions: {
          pie: {
            donut: {
              size: "68%",
              labels: {
                show: true,
                name: { fontSize: "14px", color: "#8a909d", offsetY: 22 },
                value: { fontSize: "30px", color: "#31343d", offsetY: -18 },
                total: {
                  show: true,
                  label: "piezas",
                  color: "#8a909d",
                  formatter: function () { return total; }
                }
              }
            }
          }
        },
        tooltip: {
          y: { formatter: function (valor) { return valor + (valor === 1 ? " pieza" : " piezas"); } }
        },
        responsive: [{ breakpoint: 576, options: { legend: { position: "bottom", offsetY: 0 } } }]
      }).render();
    } else {
      grafica.textContent = "Todavía no hay piezas registradas.";
    }
  }

  /* ======== 2. BÚSQUEDA DE PIEZAS SIN RECARGAR ======== */
  var filtro = document.getElementById("filtro-piezas");
  var tabla = document.getElementById("tabla-piezas");
  if (filtro && tabla && window.fetch && window.URLSearchParams) {
    var espera = null;
    var turno = 0;

    var actualizarTabla = function () {
      var parametros = new URLSearchParams();
      new FormData(filtro).forEach(function (valor, nombre) {
        if (valor) { parametros.append(nombre, valor); }
      });
      var consulta = parametros.toString();
      var direccion = filtro.getAttribute("action") + (consulta ? "?" + consulta : "");
      var miTurno = ++turno;

      // El servidor hace la búsqueda y devuelve solo la tabla
      fetch(direccion, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
        .then(function (respuesta) {
          // Si la sesión se cerró, el servidor redirige al inicio de sesión
          if (respuesta.redirected || !respuesta.ok) {
            window.location.href = direccion;
            return null;
          }
          return respuesta.text();
        })
        .then(function (html) {
          // Solo se muestra la respuesta de la búsqueda más reciente
          if (html === null || miTurno !== turno) { return; }
          tabla.innerHTML = html;
          window.history.replaceState(null, "", direccion);
        })
        .catch(function () {
          filtro.submit();   // sin conexión con fetch: búsqueda normal
        });
    };

    filtro.addEventListener("input", function () {
      window.clearTimeout(espera);
      espera = window.setTimeout(actualizarTabla, 250);   // espera a que dejen de escribir
    });
    filtro.addEventListener("submit", function (evento) {
      evento.preventDefault();
      window.clearTimeout(espera);
      actualizarTabla();
    });
  }

  /* ======== 3. CONFIRMAR ACCIONES ======== */
  var formularioPorEnviar = null;
  var botonConfirmar = document.getElementById("modal-confirmar-boton");

  // Se escucha en todo el documento porque la tabla de piezas se vuelve a dibujar
  document.addEventListener("click", function (evento) {
    var boton = evento.target.closest ? evento.target.closest("[data-confirmar]") : null;
    if (!boton || !boton.form || !botonConfirmar || !window.jQuery) { return; }

    evento.preventDefault();
    formularioPorEnviar = boton.form;
    document.getElementById("modal-confirmar-titulo").textContent = boton.dataset.titulo || "Confirmar";
    document.getElementById("modal-confirmar-texto").textContent = boton.dataset.confirmar;
    botonConfirmar.textContent = boton.dataset.boton || "Confirmar";
    botonConfirmar.className = "btn btn-pill " + (boton.dataset.clase || "btn-primary");
    window.jQuery("#modal-confirmar").modal("show");
  });

  if (botonConfirmar) {
    botonConfirmar.addEventListener("click", function () {
      if (formularioPorEnviar) {
        botonConfirmar.disabled = true;   // evita enviar dos veces
        formularioPorEnviar.submit();
      }
    });
  }

  /* ======== 4. RECHAZAR UNA SOLICITUD ======== */
  var formularioRechazo = document.getElementById("formulario-rechazar");
  if (formularioRechazo && window.jQuery) {
    document.addEventListener("click", function (evento) {
      var boton = evento.target.closest ? evento.target.closest("[data-rechazar]") : null;
      if (!boton) { return; }
      formularioRechazo.setAttribute("action", boton.dataset.rechazar);
      document.getElementById("modal-rechazar-detalle").textContent = boton.dataset.detalle;
      document.getElementById("comentario-rechazo").value = "";
      window.jQuery("#modal-rechazar").modal("show");
    });
    window.jQuery("#modal-rechazar").on("shown.bs.modal", function () {
      document.getElementById("comentario-rechazo").focus();
    });
  }

  /* ======== 5. SOLICITUD: EXISTENCIA DE LA PIEZA ELEGIDA ======== */
  var formularioSolicitud = document.getElementById("formulario-solicitud");
  if (formularioSolicitud) {
    var piezaSolicitada = formularioSolicitud.querySelector("#pieza_id");
    var cantidadSolicitada = formularioSolicitud.querySelector("#cantidad");
    var ayudaPieza = document.getElementById("ayuda-pieza");

    var mostrarExistencia = function () {
      var opcion = piezaSolicitada.options[piezaSolicitada.selectedIndex];
      if (!opcion || !opcion.value) {
        ayudaPieza.textContent = "Las piezas agotadas no se pueden solicitar.";
        cantidadSolicitada.removeAttribute("max");
        return;
      }
      var existencia = Number(opcion.dataset.existencia);
      ayudaPieza.textContent = "Hay " + existencia + " en existencia. Ubicación: " +
        opcion.dataset.ubicacion + ". Puedes pedir de 1 a " + existencia + ".";
      cantidadSolicitada.max = existencia;   // el navegador avisa si se pide de más
    };
    piezaSolicitada.addEventListener("change", mostrarExistencia);
    mostrarExistencia();
  }

  /* ======== 6. MOVIMIENTO: VISTA PREVIA DE LA EXISTENCIA ======== */
  var formularioMovimiento = document.getElementById("formulario-movimiento");
  if (formularioMovimiento) {
    var piezaMovida = formularioMovimiento.querySelector("#pieza_id");
    var cantidadMovida = formularioMovimiento.querySelector("#cantidad");
    var vistaPrevia = document.getElementById("vista-previa");

    var calcularExistencia = function () {
      var opcion = piezaMovida.options[piezaMovida.selectedIndex];
      var cantidad = parseInt(cantidadMovida.value, 10);
      vistaPrevia.classList.remove("text-danger");
      if (!opcion || !opcion.value || !(cantidad > 0)) {
        vistaPrevia.textContent = "Elige la pieza y la cantidad para ver cómo quedará la existencia.";
        return;
      }
      var actual = Number(opcion.dataset.existencia);
      var esEntrada = formularioMovimiento.querySelector("#tipo-entrada").checked;
      var nueva = esEntrada ? actual + cantidad : actual - cantidad;
      if (nueva < 0) {
        vistaPrevia.textContent = "No se puede: solo hay " + actual + " en existencia.";
        vistaPrevia.classList.add("text-danger");
      } else {
        vistaPrevia.textContent = "La existencia pasará de " + actual + " a " + nueva + ".";
      }
    };
    formularioMovimiento.addEventListener("input", calcularExistencia);
    formularioMovimiento.addEventListener("change", calcularExistencia);
    calcularExistencia();
  }

  /* ======== 7. IMPRIMIR EL REPORTE ======== */
  var botonImprimir = document.querySelector("[data-imprimir]");
  if (botonImprimir) {
    botonImprimir.addEventListener("click", function () {
      window.print();
    });
  }
})();
