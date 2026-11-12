# Control de inventario MIN (Flask + JavaScript)

Aplicación web para controlar las piezas y refacciones del almacén de una empresa
de mantenimiento de maquinaria industrial. Tiene tres tipos de usuario:

| Tipo de usuario | Qué puede hacer |
|-----------------|-----------------|
| Administrador   | Registra, modifica y elimina piezas; registra entradas y salidas; administra los usuarios; consulta reportes. |
| Gerente         | Consulta el inventario y los movimientos; autoriza o rechaza solicitudes; genera reportes. |
| Técnico         | Consulta las piezas disponibles; solicita material; revisa el estado de sus solicitudes. |

## Cómo ejecutarlo en Ubuntu

Haz cada paso por separado, en la terminal, dentro de la carpeta del proyecto.

**Paso 1.** Entra a la carpeta del proyecto:

```bash
cd inventario_min
```

**Paso 2.** Crea un entorno virtual (solo la primera vez):

```bash
python3 -m venv venv
```

> Si aparece un error que menciona `ensurepip` o `venv`, instala el paquete con
> `sudo apt install python3-venv` y repite el paso 2.

**Paso 3.** Activa el entorno virtual (cada vez que abras una terminal nueva):

```bash
source venv/bin/activate
```

Sabrás que funcionó porque la línea de la terminal empieza con `(venv)`.

**Paso 4.** Instala Flask (solo la primera vez):

```bash
pip install -r requirements.txt
```

**Paso 5.** Inicia la página:

```bash
python3 app.py
```

La primera vez se crea sola la base de datos `inventario.db` con datos de ejemplo.

**Paso 6.** Abre el navegador en: http://127.0.0.1:5000

Para detener la página, regresa a la terminal y presiona `Ctrl + C`.

## Usuarios de prueba

| Tipo de usuario | Usuario    | Contraseña    |
|-----------------|------------|---------------|
| Administrador   | `admin`    | `Admin2026`   |
| Gerente         | `gerente`  | `Gerente2026` |
| Técnico         | `tecnico1` | `Tecnico2026` |
| Técnico         | `tecnico2` | `Tecnico2026` |

## Otros comandos

Ejecutar las pruebas automáticas (usan una base de datos temporal):

```bash
python3 pruebas.py
```

Volver a crear la base de datos con los datos de ejemplo (borra los cambios):

```bash
python3 init_db.py
```

## Estructura

```
inventario_min/
├── app.py            Páginas, inicio de sesión, permisos y validaciones
├── inventario.py     Reglas del inventario: movimientos y solicitudes
├── init_db.py        Crea la base de datos con 24 piezas y datos de ejemplo
├── schema.sql        Tablas y reglas de la base de datos
├── pruebas.py        30 pruebas automáticas de los 9 requisitos
├── requirements.txt  Dependencias (solo Flask)
├── templates/        Páginas HTML (Jinja2) armadas con la plantilla Mono
└── static/
    ├── css/style.css        Hoja de estilos de la plantilla Mono (sin modificar)
    ├── css/inventario.css   Fuentes locales y ajustes menores
    ├── js/mono.js           JavaScript de la plantilla (sin modificar)
    ├── js/inventario.js     JavaScript propio: gráfica, búsqueda, ventanas
    ├── plugins/             Librerías de la plantilla (Bootstrap, jQuery, íconos, gráficas)
    └── fuentes/             Fuentes Karla y Roboto
```

## Tecnologías

- **HTML, CSS y JavaScript** con la plantilla **Mono** (Bootstrap 4, jQuery, ApexCharts).
- **Flask (Python)** para las páginas, la sesión y los permisos.
- **SQLite** como base de datos (un solo archivo, sin instalar nada más).

## Créditos del diseño

- Plantilla **Mono** de Themefisher, licencia MIT (ver `static/LICENCIA-PLANTILLA-MONO.txt`).
- Fuentes **Karla** y **Roboto**, con sus licencias en `static/fuentes/`.

Todos los archivos de diseño están dentro del proyecto, así que la página se ve
igual aunque no haya internet.

## Antes de usarlo en un servidor real

- Definir la variable `INVENTARIO_SECRET_KEY` con una clave larga y secreta.
- Publicarlo con HTTPS y definir `INVENTARIO_HTTPS=1`.
- Cambiar las contraseñas de ejemplo.
- Nunca activar el modo debug (`INVENTARIO_DEBUG`) en el servidor.
