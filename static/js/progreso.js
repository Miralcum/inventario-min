/* Barra de carga de la plantilla (NProgress).
   En la plantilla original este código va escrito dentro del HTML; aquí está en
   un archivo para que el navegador no tenga que permitir scripts en línea. */
if (window.NProgress) {
  NProgress.configure({ showSpinner: false });
  NProgress.start();
  window.addEventListener("load", function () {
    NProgress.done();
  });
}

/* La plantilla usa la librería "hotkeys" (cargada desde internet) solo para su
   buscador del encabezado, que este sistema no tiene. Se define vacía para que
   mono.js, que se usa sin modificar, no marque error. */
window.hotkeys = window.hotkeys || function () {};
