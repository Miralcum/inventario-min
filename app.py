"""
Control de inventario de piezas y refacciones (Flask + SQLite + JavaScript).

Tres tipos de usuario:
  - administrador: registra, modifica y da de baja piezas, registra entradas y
                   salidas, y administra los usuarios.
  - gerente:       consulta el inventario, autoriza o rechaza solicitudes y
                   genera reportes.
  - tecnico:       consulta las piezas, solicita materiales y revisa el estado
                   de sus solicitudes.

Uso:  python3 app.py   y abrir http://127.0.0.1:5000
"""
import csv
import io
import math
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import inventario as inv

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
SIGLAS = "MIN"
NOMBRE_EMPRESA = "Mantenimiento Industrial del Norte"
ROLES = {"administrador": "Administrador", "gerente": "Gerente", "tecnico": "Técnico"}
CATEGORIAS = [
    "Bandas y transmisión", "Filtros", "Hidráulica y neumática", "Lubricantes",
    "Material eléctrico", "Motores", "Rodamientos", "Sensores", "Tornillería",
]
ESTADOS_PIEZA = {"disponible": "En stock", "bajo": "Stock bajo", "agotada": "Agotada"}
ESTADOS_SOLICITUD = {"pendiente": "Pendiente", "aprobada": "Aprobada", "rechazada": "Rechazada"}
MAX_INTENTOS = 5                  # intentos fallidos antes de bloquear la cuenta
MINUTOS_BLOQUEO = 5               # duración del bloqueo temporal
INACTIVIDAD = timedelta(minutes=30)   # la sesión se cierra sola tras este tiempo
VERSION = "1"                     # cambiar cuando se modifiquen el CSS o el JS

app.config.update(
    BASE_DATOS=os.environ.get("INVENTARIO_BD", os.path.join(app.root_path, "inventario.db")),
    # llave que firma la cookie de sesión para que nadie pueda alterarla
    SECRET_KEY=os.environ.get("INVENTARIO_SECRET_KEY") or secrets.token_hex(32),
    PERMANENT_SESSION_LIFETIME=INACTIVIDAD,
    SESSION_COOKIE_HTTPONLY=True,     # JavaScript no puede leer la cookie
    SESSION_COOKIE_SAMESITE="Lax",    # no se envía desde otros sitios
    SESSION_COOKIE_SECURE=os.environ.get("INVENTARIO_HTTPS") == "1",
    SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=1),  # el navegador guarda CSS, JS e íconos
)


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
def obtener_bd():
    """Una conexión por petición; se cierra sola al terminar."""
    if "bd" not in g:
        g.bd = sqlite3.connect(app.config["BASE_DATOS"])
        g.bd.row_factory = sqlite3.Row
        g.bd.execute("PRAGMA foreign_keys = ON")
    return g.bd


@app.teardown_appcontext
def cerrar_bd(_error):
    bd = g.pop("bd", None)
    if bd is not None:
        bd.close()


# ---------------------------------------------------------------------------
# Sesión, permisos y protecciones
# ---------------------------------------------------------------------------
def token_csrf():
    """Token secreto que deben llevar todos los formularios."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def cargar_usuario():
    """Identifica al usuario de la sesión y revisa que siga activo."""
    g.usuario = None
    if request.endpoint == "static":
        return None
    session.permanent = True
    if "usuario_id" not in session:
        return None

    ahora = datetime.now()
    ultimo = datetime.fromisoformat(session.get("ultimo_acceso", ahora.isoformat()))
    if ahora - ultimo > INACTIVIDAD:
        session.clear()
        flash("Tu sesión se cerró después de 30 minutos sin actividad. "
              "Vuelve a iniciar sesión.", "info")
        return redirect(url_for("login"))

    # El rol se lee de la base de datos en cada petición: si el administrador
    # desactiva una cuenta o le cambia el rol, el cambio aplica de inmediato.
    fila = obtener_bd().execute(
        "SELECT id, usuario, nombre, rol, activo FROM usuarios WHERE id = ?",
        (session["usuario_id"],)).fetchone()
    if fila is None or not fila["activo"]:
        session.clear()
        flash("Tu cuenta fue desactivada. Consulta al administrador.", "warning")
        return redirect(url_for("login"))

    g.usuario = fila
    session["ultimo_acceso"] = ahora.isoformat()
    return None


@app.before_request
def verificar_csrf():
    """Rechaza formularios enviados desde otro sitio (ataque CSRF)."""
    if request.method != "POST":
        return None
    enviado = request.form.get("csrf", "")
    esperado = session.get("csrf", "")
    if not esperado or not secrets.compare_digest(enviado, esperado):
        flash("La página estuvo abierta demasiado tiempo. Vuelve a intentarlo.", "info")
        return redirect(url_for("inicio"))
    return None


@app.after_request
def encabezados_seguridad(respuesta):
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    # El navegador solo ejecuta scripts de este mismo sitio (nada en línea ni externo).
    # Los estilos en línea se permiten porque la plantilla y las gráficas los usan.
    respuesta.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    if request.endpoint != "static":
        # las páginas con datos no se guardan en la caché del navegador
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


def requiere_rol(*roles):
    """Solo deja pasar a usuarios con sesión iniciada y con alguno de los roles.

    Sin roles, basta con haber iniciado sesión. El permiso se revisa SIEMPRE en
    el servidor: ocultar un botón en la página no es suficiente.
    """
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if g.usuario is None:
                flash("Inicia sesión para continuar.", "info")
                return redirect(url_for("login"))
            if roles and g.usuario["rol"] not in roles:
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def entero(texto, minimo, maximo):
    """Convierte el texto a entero si está dentro del rango; si no, devuelve None."""
    texto = (texto or "").strip()
    if not (texto.isascii() and texto.isdigit()) or len(texto) > 7:
        return None
    valor = int(texto)
    return valor if minimo <= valor <= maximo else None


def fecha_valida(texto, por_defecto):
    """Devuelve una fecha a partir de 'AAAA-MM-DD'; si no es válida, la de por_defecto."""
    try:
        return datetime.strptime(texto or "", "%Y-%m-%d").date()
    except ValueError:
        return por_defecto


def contar_estados(bd):
    """Cuántas piezas hay en total, en stock, con stock bajo y agotadas."""
    fila = bd.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(cantidad = 0), 0) AS agotadas,
                  COALESCE(SUM(cantidad > 0 AND cantidad <= minimo), 0) AS bajas,
                  COALESCE(SUM(cantidad > minimo), 0) AS disponibles,
                  COALESCE(SUM(cantidad), 0) AS unidades
           FROM piezas WHERE activo = 1""").fetchone()
    return dict(fila)


def piezas_en_alerta(bd, limite=None):
    """Piezas agotadas o con stock bajo; primero las agotadas y las más urgentes."""
    sql = f"""SELECT p.*, {inv.ESTADO_SQL} AS estado
              FROM piezas p
              WHERE p.activo = 1 AND p.cantidad <= p.minimo
              ORDER BY (p.cantidad = 0) DESC,
                       CAST(p.cantidad AS REAL) / MAX(p.minimo, 1), p.codigo"""
    if limite:
        sql += f" LIMIT {int(limite)}"
    return bd.execute(sql).fetchall()


SQL_SOLICITUDES = """
    SELECT s.*, p.codigo, p.nombre AS pieza, p.cantidad AS existencia,
           t.nombre AS tecnico, r.nombre AS gerente
    FROM solicitudes s
    JOIN piezas p ON p.id = s.pieza_id
    JOIN usuarios t ON t.id = s.tecnico_id
    LEFT JOIN usuarios r ON r.id = s.gerente_id
"""

SQL_MOVIMIENTOS = """
    SELECT m.*, p.codigo, p.nombre AS pieza, u.nombre AS usuario, t.nombre AS entregado_a
    FROM movimientos m
    JOIN piezas p ON p.id = m.pieza_id
    JOIN usuarios u ON u.id = m.usuario_id
    LEFT JOIN solicitudes s ON s.id = m.solicitud_id
    LEFT JOIN usuarios t ON t.id = s.tecnico_id
"""


@app.context_processor
def datos_generales():
    """Datos que usan todas las páginas (menú, campana de alertas, etc.)."""
    datos = {
        "siglas": SIGLAS, "empresa": NOMBRE_EMPRESA, "roles": ROLES, "version": VERSION,
        "estados_pieza": ESTADOS_PIEZA, "estados_solicitud": ESTADOS_SOLICITUD,
        "token_csrf": token_csrf, "usuario_actual": g.get("usuario"),
    }
    if g.get("usuario"):
        bd = obtener_bd()
        datos["campana_alertas"] = piezas_en_alerta(bd, limite=6)
        datos["total_alertas"] = bd.execute(
            "SELECT COUNT(*) FROM piezas WHERE activo = 1 AND cantidad <= minimo").fetchone()[0]
        if g.usuario["rol"] == "tecnico":
            datos["total_pendientes"] = bd.execute(
                "SELECT COUNT(*) FROM solicitudes WHERE estado = 'pendiente' AND tecnico_id = ?",
                (g.usuario["id"],)).fetchone()[0]
        else:
            datos["total_pendientes"] = bd.execute(
                "SELECT COUNT(*) FROM solicitudes WHERE estado = 'pendiente'").fetchone()[0]
    return datos


@app.template_filter("fecha")
def formato_fecha(texto):
    """'2026-11-12 09:05:00' -> '12/11/2026 09:05'."""
    return datetime.fromisoformat(texto).strftime("%d/%m/%Y %H:%M") if texto else ""


@app.template_filter("folio")
def formato_folio(solicitud_id):
    return inv.folio(solicitud_id)


@app.template_filter("iniciales")
def iniciales(nombre):
    """'Carlos Mendoza Ruiz' -> 'CM'."""
    return "".join(parte[0] for parte in (nombre or "").split()[:2]).upper()


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario is not None:
        return redirect(url_for("inicio"))

    usuario = ""
    error = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip().lower()
        contrasena = request.form.get("contrasena", "")
        bd = obtener_bd()
        # consulta parametrizada (?): evita la inyección SQL
        fila = bd.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
        ahora = datetime.now()

        bloqueado_hasta = None
        if fila and fila["bloqueado_hasta"]:
            bloqueado_hasta = datetime.fromisoformat(fila["bloqueado_hasta"])

        if bloqueado_hasta and bloqueado_hasta > ahora:
            minutos = math.ceil((bloqueado_hasta - ahora).total_seconds() / 60)
            error = (f"Esta cuenta está bloqueada por varios intentos fallidos. "
                     f"Intenta de nuevo en {minutos} min.")
        elif fila and fila["activo"] and check_password_hash(fila["contrasena_hash"], contrasena):
            bd.execute("UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL "
                       "WHERE id = ?", (fila["id"],))
            bd.commit()
            session.clear()   # sesión nueva al entrar
            session.permanent = True
            session["usuario_id"] = fila["id"]
            session["ultimo_acceso"] = ahora.isoformat()
            return redirect(url_for("inicio"))
        else:
            # mismo mensaje si el usuario no existe, está inactivo o la contraseña
            # está mal: así no se revela qué usuarios existen
            error = "Usuario o contraseña incorrectos."
            if fila:
                intentos = fila["intentos_fallidos"] + 1
                bloqueo = None
                if intentos >= MAX_INTENTOS:
                    bloqueo = (ahora + timedelta(minutes=MINUTOS_BLOQUEO)).isoformat()
                    intentos = 0
                    error += f" Por seguridad, la cuenta quedó bloqueada {MINUTOS_BLOQUEO} minutos."
                bd.execute("UPDATE usuarios SET intentos_fallidos = ?, bloqueado_hasta = ? "
                           "WHERE id = ?", (intentos, bloqueo, fila["id"]))
                bd.commit()

    return render_template("login.html", usuario=usuario, error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Cerraste sesión.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
@requiere_rol()
def inicio():
    bd = obtener_bd()
    rol = g.usuario["rol"]
    datos = {"conteo": contar_estados(bd), "alertas": piezas_en_alerta(bd, limite=5)}

    if rol == "tecnico":
        datos["mis_solicitudes"] = bd.execute(
            SQL_SOLICITUDES + " WHERE s.tecnico_id = ? ORDER BY s.id DESC LIMIT 5",
            (g.usuario["id"],)).fetchall()
    elif rol == "gerente":
        datos["por_autorizar"] = bd.execute(
            SQL_SOLICITUDES + " WHERE s.estado = 'pendiente' ORDER BY s.id").fetchall()
    else:
        datos["ultimos_movimientos"] = bd.execute(
            SQL_MOVIMIENTOS + " ORDER BY m.id DESC LIMIT 6").fetchall()

    return render_template("dashboard.html", **datos)


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------
@app.route("/piezas")
@requiere_rol()
def piezas():
    """Consulta y búsqueda de piezas (todos los usuarios)."""
    bd = obtener_bd()
    q = request.args.get("q", "").strip()[:60]
    categoria = request.args.get("categoria", "")
    estado = request.args.get("estado", "")

    condiciones = ["p.activo = 1"]
    parametros = []
    if q:
        # se escapan % y _ para que se busquen como texto normal
        patron = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        condiciones.append("(p.codigo LIKE ? ESCAPE '\\' OR p.nombre LIKE ? ESCAPE '\\' "
                           "OR p.ubicacion LIKE ? ESCAPE '\\')")
        parametros += [patron, patron, patron]
    if categoria in CATEGORIAS:
        condiciones.append("p.categoria = ?")
        parametros.append(categoria)
    filtros_estado = {
        "disponible": "p.cantidad > p.minimo",
        "bajo": "p.cantidad > 0 AND p.cantidad <= p.minimo",
        "agotada": "p.cantidad = 0",
        "alerta": "p.cantidad <= p.minimo",
    }
    if estado in filtros_estado:
        condiciones.append(filtros_estado[estado])

    lista = bd.execute(
        f"""SELECT p.*, {inv.ESTADO_SQL} AS estado FROM piezas p
            WHERE {' AND '.join(condiciones)} ORDER BY p.codigo""", parametros).fetchall()
    total = bd.execute("SELECT COUNT(*) FROM piezas WHERE activo = 1").fetchone()[0]

    contexto = dict(piezas=lista, total=total, q=q, categoria=categoria, estado=estado,
                    categorias=CATEGORIAS)
    # El JavaScript pide solo la tabla para actualizarla sin recargar la página
    if request.headers.get("X-Requested-With") == "fetch":
        return render_template("_piezas_tabla.html", **contexto)
    return render_template("piezas.html", **contexto)


def leer_formulario_pieza(es_nueva):
    """Lee y valida los campos de una pieza. Devuelve (datos, errores)."""
    datos = {
        "codigo": request.form.get("codigo", "").strip().upper(),
        "nombre": " ".join(request.form.get("nombre", "").split()),
        "categoria": request.form.get("categoria", ""),
        "minimo": request.form.get("minimo", "").strip(),
        "ubicacion": " ".join(request.form.get("ubicacion", "").split()),
        "cantidad": request.form.get("cantidad", "").strip(),
    }
    errores = {}
    if not re.fullmatch(r"[A-Z0-9-]{2,12}", datos["codigo"]):
        errores["codigo"] = "Usa de 2 a 12 letras, números o guiones, sin espacios."
    if not 3 <= len(datos["nombre"]) <= 80:
        errores["nombre"] = "Escribe un nombre de 3 a 80 caracteres."
    if datos["categoria"] not in CATEGORIAS:
        errores["categoria"] = "Elige una categoría de la lista."
    if entero(datos["minimo"], 0, inv.CANTIDAD_MAXIMA) is None:
        errores["minimo"] = "Escribe un número entero de 0 en adelante."
    if not 2 <= len(datos["ubicacion"]) <= 60:
        errores["ubicacion"] = "Escribe la ubicación (de 2 a 60 caracteres)."
    if es_nueva and entero(datos["cantidad"], 0, inv.CANTIDAD_MAXIMA) is None:
        errores["cantidad"] = "Escribe un número entero de 0 en adelante."
    return datos, errores


def codigo_repetido(bd, codigo, excepto_id=0):
    fila = bd.execute("SELECT activo FROM piezas WHERE codigo = ? AND id != ?",
                      (codigo, excepto_id)).fetchone()
    if fila is None:
        return None
    if fila["activo"]:
        return f"El código {codigo} ya pertenece a otra pieza."
    return f"El código {codigo} pertenece a una pieza dada de baja. Usa otro código."


@app.route("/piezas/nueva", methods=["GET", "POST"])
@requiere_rol("administrador")
def pieza_nueva():
    bd = obtener_bd()
    datos = {"codigo": "", "nombre": "", "categoria": "", "minimo": "", "ubicacion": "",
             "cantidad": ""}
    errores = {}
    if request.method == "POST":
        datos, errores = leer_formulario_pieza(es_nueva=True)
        if "codigo" not in errores:
            repetido = codigo_repetido(bd, datos["codigo"])
            if repetido:
                errores["codigo"] = repetido
        if not errores:
            cantidad = int(datos["cantidad"])
            with bd:   # se guarda todo o nada
                nueva = bd.execute(
                    """INSERT INTO piezas (codigo, nombre, categoria, cantidad, minimo, ubicacion)
                       VALUES (?, ?, ?, 0, ?, ?)""",
                    (datos["codigo"], datos["nombre"], datos["categoria"],
                     int(datos["minimo"]), datos["ubicacion"]))
                if cantidad > 0:
                    # la existencia inicial entra como movimiento, para que quede en el historial
                    inv.registrar_movimiento(bd, nueva.lastrowid, "entrada", cantidad,
                                             "Alta de pieza: existencia inicial", g.usuario["id"])
            flash(f"Pieza {datos['codigo']} registrada.", "success")
            return redirect(url_for("piezas"))

    codigo_http = 422 if errores else 200
    return render_template("pieza_form.html", pieza=None, datos=datos, errores=errores,
                           categorias=CATEGORIAS), codigo_http


@app.route("/piezas/<int:pieza_id>/editar", methods=["GET", "POST"])
@requiere_rol("administrador")
def pieza_editar(pieza_id):
    bd = obtener_bd()
    pieza = bd.execute("SELECT * FROM piezas WHERE id = ? AND activo = 1", (pieza_id,)).fetchone()
    if pieza is None:
        abort(404)

    datos = dict(pieza)
    errores = {}
    if request.method == "POST":
        datos, errores = leer_formulario_pieza(es_nueva=False)
        if "codigo" not in errores:
            repetido = codigo_repetido(bd, datos["codigo"], excepto_id=pieza_id)
            if repetido:
                errores["codigo"] = repetido
        if not errores:
            with bd:
                bd.execute(
                    """UPDATE piezas SET codigo = ?, nombre = ?, categoria = ?, minimo = ?,
                           ubicacion = ? WHERE id = ?""",
                    (datos["codigo"], datos["nombre"], datos["categoria"],
                     int(datos["minimo"]), datos["ubicacion"], pieza_id))
            flash(f"Pieza {datos['codigo']} actualizada.", "success")
            return redirect(url_for("piezas"))

    codigo_http = 422 if errores else 200
    return render_template("pieza_form.html", pieza=pieza, datos=datos, errores=errores,
                           categorias=CATEGORIAS), codigo_http


@app.route("/piezas/<int:pieza_id>/eliminar", methods=["POST"])
@requiere_rol("administrador")
def pieza_eliminar(pieza_id):
    """Da de baja la pieza. No se borra de la base de datos para conservar su historial."""
    bd = obtener_bd()
    pieza = bd.execute("SELECT * FROM piezas WHERE id = ? AND activo = 1", (pieza_id,)).fetchone()
    if pieza is None:
        abort(404)

    pendientes = bd.execute(
        "SELECT COUNT(*) FROM solicitudes WHERE pieza_id = ? AND estado = 'pendiente'",
        (pieza_id,)).fetchone()[0]
    if pendientes:
        flash(f"No se puede eliminar {pieza['codigo']}: tiene {pendientes} "
              f"{'solicitud pendiente' if pendientes == 1 else 'solicitudes pendientes'}. "
              f"El gerente debe responderlas primero.", "danger")
        return redirect(url_for("piezas"))

    with bd:
        if pieza["cantidad"] > 0:
            inv.registrar_movimiento(bd, pieza_id, "salida", pieza["cantidad"],
                                     "Baja de la pieza del catálogo", g.usuario["id"])
        bd.execute("UPDATE piezas SET activo = 0 WHERE id = ?", (pieza_id,))
    flash(f"Pieza {pieza['codigo']} eliminada del catálogo. Su historial se conserva.", "success")
    return redirect(url_for("piezas"))


@app.route("/alertas")
@requiere_rol()
def alertas():
    lista = piezas_en_alerta(obtener_bd())
    return render_template(
        "alertas.html",
        agotadas=[p for p in lista if p["estado"] == "agotada"],
        bajas=[p for p in lista if p["estado"] == "bajo"])


# ---------------------------------------------------------------------------
# Solicitudes de material
# ---------------------------------------------------------------------------
@app.route("/solicitudes")
@requiere_rol()
def solicitudes():
    bd = obtener_bd()
    estado = request.args.get("estado", "")
    condiciones, parametros = [], []
    if g.usuario["rol"] == "tecnico":
        # el técnico solo ve SUS solicitudes; se usa su sesión, nunca un dato de la URL
        condiciones.append("s.tecnico_id = ?")
        parametros.append(g.usuario["id"])
    if estado in ESTADOS_SOLICITUD:
        condiciones.append("s.estado = ?")
        parametros.append(estado)

    sql = SQL_SOLICITUDES
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY (s.estado = 'pendiente') DESC, s.id DESC"
    return render_template("solicitudes.html", solicitudes=bd.execute(sql, parametros).fetchall(),
                           estado=estado)


@app.route("/solicitudes/nueva", methods=["GET", "POST"])
@requiere_rol("tecnico")
def solicitud_nueva():
    bd = obtener_bd()
    lista = bd.execute(
        f"SELECT p.*, {inv.ESTADO_SQL} AS estado FROM piezas p WHERE p.activo = 1 ORDER BY p.nombre"
    ).fetchall()
    datos = {"pieza_id": request.args.get("pieza", ""), "cantidad": "", "motivo": ""}
    errores = {}

    if request.method == "POST":
        datos = {
            "pieza_id": request.form.get("pieza_id", ""),
            "cantidad": request.form.get("cantidad", "").strip(),
            "motivo": " ".join(request.form.get("motivo", "").split()),
        }
        pieza_id = entero(datos["pieza_id"], 1, 10**6)
        cantidad = entero(datos["cantidad"], 1, inv.CANTIDAD_MAXIMA)
        if pieza_id is None:
            errores["pieza_id"] = "Elige una pieza de la lista."
        if cantidad is None:
            errores["cantidad"] = "Escribe un número entero mayor que cero."
        if not 5 <= len(datos["motivo"]) <= 200:
            errores["motivo"] = "Explica para qué se usará (de 5 a 200 caracteres)."
        if not errores:
            try:
                with bd:
                    nueva = inv.crear_solicitud(bd, g.usuario["id"], pieza_id, cantidad,
                                                datos["motivo"])
                flash(f"Solicitud {inv.folio(nueva)} enviada. El gerente debe autorizarla.",
                      "success")
                return redirect(url_for("solicitudes"))
            except inv.ErrorInventario as error:
                errores["cantidad"] = str(error)

    codigo_http = 422 if errores else 200
    return render_template("solicitud_form.html", piezas=lista, datos=datos,
                           errores=errores), codigo_http


def destino_despues_de_responder():
    return url_for("inicio") if request.form.get("volver") == "inicio" else url_for("solicitudes")


@app.route("/solicitudes/<int:solicitud_id>/aprobar", methods=["POST"])
@requiere_rol("gerente")
def solicitud_aprobar(solicitud_id):
    bd = obtener_bd()
    try:
        with bd:   # la solicitud, la existencia y el movimiento se guardan juntos
            existencia = inv.aprobar_solicitud(bd, solicitud_id, g.usuario["id"])
        flash(f"Solicitud {inv.folio(solicitud_id)} autorizada. Se registró la salida y la "
              f"existencia quedó en {existencia}.", "success")
    except inv.ErrorInventario as error:
        flash(str(error), "danger")
    return redirect(destino_despues_de_responder())


@app.route("/solicitudes/<int:solicitud_id>/rechazar", methods=["POST"])
@requiere_rol("gerente")
def solicitud_rechazar(solicitud_id):
    bd = obtener_bd()
    comentario = " ".join(request.form.get("comentario", "").split())
    if not 5 <= len(comentario) <= 200:
        flash("Para rechazar una solicitud escribe el motivo (de 5 a 200 caracteres).", "danger")
        return redirect(destino_despues_de_responder())
    try:
        with bd:
            inv.rechazar_solicitud(bd, solicitud_id, g.usuario["id"], comentario)
        flash(f"Solicitud {inv.folio(solicitud_id)} rechazada. Las existencias no cambiaron.",
              "success")
    except inv.ErrorInventario as error:
        flash(str(error), "danger")
    return redirect(destino_despues_de_responder())


# ---------------------------------------------------------------------------
# Movimientos (entradas y salidas)
# ---------------------------------------------------------------------------
@app.route("/movimientos")
@requiere_rol("administrador", "gerente")
def movimientos():
    bd = obtener_bd()
    tipo = request.args.get("tipo", "")
    q = request.args.get("q", "").strip()[:60]
    condiciones, parametros = [], []
    if tipo in ("entrada", "salida"):
        condiciones.append("m.tipo = ?")
        parametros.append(tipo)
    if q:
        patron = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        condiciones.append("(p.codigo LIKE ? ESCAPE '\\' OR p.nombre LIKE ? ESCAPE '\\' "
                           "OR m.motivo LIKE ? ESCAPE '\\')")
        parametros += [patron, patron, patron]

    sql = SQL_MOVIMIENTOS
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY m.id DESC LIMIT 200"
    return render_template("movimientos.html", movimientos=bd.execute(sql, parametros).fetchall(),
                           tipo=tipo, q=q)


@app.route("/movimientos/nuevo", methods=["GET", "POST"])
@requiere_rol("administrador")
def movimiento_nuevo():
    """El administrador registra una entrada (compra, devolución) o una salida (ajuste)."""
    bd = obtener_bd()
    lista = bd.execute("SELECT * FROM piezas WHERE activo = 1 ORDER BY nombre").fetchall()
    tipo_inicial = request.args.get("tipo", "entrada")
    datos = {"pieza_id": request.args.get("pieza", ""),
             "tipo": tipo_inicial if tipo_inicial in ("entrada", "salida") else "entrada",
             "cantidad": "", "motivo": ""}
    errores = {}

    if request.method == "POST":
        datos = {
            "pieza_id": request.form.get("pieza_id", ""),
            "tipo": request.form.get("tipo", ""),
            "cantidad": request.form.get("cantidad", "").strip(),
            "motivo": " ".join(request.form.get("motivo", "").split()),
        }
        pieza_id = entero(datos["pieza_id"], 1, 10**6)
        cantidad = entero(datos["cantidad"], 1, inv.CANTIDAD_MAXIMA)
        if pieza_id is None or not any(p["id"] == pieza_id for p in lista):
            errores["pieza_id"] = "Elige una pieza de la lista."
        if datos["tipo"] not in ("entrada", "salida"):
            errores["tipo"] = "Elige entrada o salida."
        if cantidad is None:
            errores["cantidad"] = "Escribe un número entero mayor que cero."
        if not 5 <= len(datos["motivo"]) <= 120:
            errores["motivo"] = "Escribe el motivo (de 5 a 120 caracteres)."
        if not errores:
            try:
                with bd:
                    existencia = inv.registrar_movimiento(
                        bd, pieza_id, datos["tipo"], cantidad, datos["motivo"], g.usuario["id"])
                flash(f"{'Entrada' if datos['tipo'] == 'entrada' else 'Salida'} registrada. "
                      f"La existencia quedó en {existencia}.", "success")
                return redirect(url_for("movimientos"))
            except inv.ErrorInventario as error:
                errores["cantidad"] = str(error)

    codigo_http = 422 if errores else 200
    return render_template("movimiento_form.html", piezas=lista, datos=datos,
                           errores=errores), codigo_http


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------
def periodo_del_reporte():
    hoy = date.today()
    hasta = fecha_valida(request.args.get("hasta"), hoy)
    desde = fecha_valida(request.args.get("desde"), hasta - timedelta(days=30))
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


@app.route("/reportes")
@requiere_rol("gerente", "administrador")
def reportes():
    bd = obtener_bd()
    desde, hasta = periodo_del_reporte()
    rango = (f"{desde} 00:00:00", f"{hasta} 23:59:59")

    por_categoria = bd.execute(
        """SELECT categoria, COUNT(*) AS piezas, SUM(cantidad) AS unidades,
                  SUM(cantidad <= minimo) AS alertas
           FROM piezas WHERE activo = 1 GROUP BY categoria ORDER BY categoria""").fetchall()
    resumen_movimientos = {fila["tipo"]: fila for fila in bd.execute(
        """SELECT tipo, COUNT(*) AS movimientos, SUM(cantidad) AS unidades
           FROM movimientos WHERE fecha BETWEEN ? AND ? GROUP BY tipo""", rango)}
    # responde a "¿quién utiliza los materiales?"
    consumo_por_tecnico = bd.execute(
        """SELECT t.nombre, COUNT(*) AS solicitudes, SUM(m.cantidad) AS unidades
           FROM movimientos m
           JOIN solicitudes s ON s.id = m.solicitud_id
           JOIN usuarios t ON t.id = s.tecnico_id
           WHERE m.tipo = 'salida' AND m.fecha BETWEEN ? AND ?
           GROUP BY t.id ORDER BY unidades DESC, t.nombre""", rango).fetchall()
    mas_solicitadas = bd.execute(
        """SELECT p.codigo, p.nombre, SUM(m.cantidad) AS unidades
           FROM movimientos m JOIN piezas p ON p.id = m.pieza_id
           WHERE m.tipo = 'salida' AND m.solicitud_id IS NOT NULL AND m.fecha BETWEEN ? AND ?
           GROUP BY p.id ORDER BY unidades DESC, p.codigo LIMIT 5""", rango).fetchall()
    solicitudes_por_estado = {fila["estado"]: fila["total"] for fila in bd.execute(
        """SELECT estado, COUNT(*) AS total FROM solicitudes
           WHERE fecha BETWEEN ? AND ? GROUP BY estado""", rango)}

    return render_template(
        "reportes.html", desde=desde, hasta=hasta, conteo=contar_estados(bd),
        por_categoria=por_categoria, resumen_movimientos=resumen_movimientos,
        consumo_por_tecnico=consumo_por_tecnico, mas_solicitadas=mas_solicitadas,
        solicitudes_por_estado=solicitudes_por_estado, alertas=piezas_en_alerta(bd),
        generado=datetime.now().strftime("%d/%m/%Y %H:%M"))


def respuesta_csv(nombre_archivo, encabezados, filas):
    """Arma un archivo CSV que Excel y LibreOffice abren con acentos correctos."""
    def celda_segura(valor):
        # evita que una celda que empieza con = + - @ se ejecute como fórmula
        texto = "" if valor is None else str(valor)
        return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto

    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(encabezados)
    for fila in filas:
        escritor.writerow([celda_segura(valor) for valor in fila])
    # "\ufeff" es una marca que le indica a Excel que el archivo usa acentos (UTF-8)
    return Response(
        "\ufeff" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'})


@app.route("/reportes/inventario.csv")
@requiere_rol("gerente", "administrador")
def reporte_inventario_csv():
    filas = obtener_bd().execute(
        f"""SELECT p.codigo, p.nombre, p.categoria, p.cantidad, p.minimo, p.ubicacion,
                   {inv.ESTADO_SQL} AS estado
            FROM piezas p WHERE p.activo = 1 ORDER BY p.codigo""").fetchall()
    return respuesta_csv(
        f"inventario_{date.today()}.csv",
        ["Código", "Nombre", "Categoría", "Cantidad", "Mínimo", "Ubicación", "Estado"],
        [(f["codigo"], f["nombre"], f["categoria"], f["cantidad"], f["minimo"], f["ubicacion"],
          ESTADOS_PIEZA[f["estado"]]) for f in filas])


@app.route("/reportes/movimientos.csv")
@requiere_rol("gerente", "administrador")
def reporte_movimientos_csv():
    desde, hasta = periodo_del_reporte()
    filas = obtener_bd().execute(
        SQL_MOVIMIENTOS + " WHERE m.fecha BETWEEN ? AND ? ORDER BY m.id",
        (f"{desde} 00:00:00", f"{hasta} 23:59:59")).fetchall()
    return respuesta_csv(
        f"movimientos_{desde}_a_{hasta}.csv",
        ["Fecha", "Tipo", "Código", "Pieza", "Cantidad", "Existencia anterior",
         "Existencia nueva", "Motivo", "Registró", "Entregado a"],
        [(f["fecha"], f["tipo"].capitalize(), f["codigo"], f["pieza"], f["cantidad"],
          f["existencia_anterior"], f["existencia_nueva"], f["motivo"], f["usuario"],
          f["entregado_a"] or "") for f in filas])


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def contrasena_valida(contrasena):
    return (8 <= len(contrasena) <= 64 and re.search(r"[A-Za-z]", contrasena)
            and re.search(r"\d", contrasena))


@app.route("/usuarios")
@requiere_rol("administrador")
def usuarios():
    lista = obtener_bd().execute(
        "SELECT id, usuario, nombre, rol, activo FROM usuarios ORDER BY activo DESC, nombre"
    ).fetchall()
    return render_template("usuarios.html", usuarios=lista)


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@requiere_rol("administrador")
def usuario_nuevo():
    bd = obtener_bd()
    datos = {"usuario": "", "nombre": "", "rol": "tecnico"}
    errores = {}
    if request.method == "POST":
        datos = {
            "usuario": request.form.get("usuario", "").strip().lower(),
            "nombre": " ".join(request.form.get("nombre", "").split()),
            "rol": request.form.get("rol", ""),
        }
        contrasena = request.form.get("contrasena", "")
        if not re.fullmatch(r"[a-z0-9._-]{3,20}", datos["usuario"]):
            errores["usuario"] = "Usa de 3 a 20 letras minúsculas, números, punto o guion."
        elif bd.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (datos["usuario"],)).fetchone():
            errores["usuario"] = "Ese nombre de usuario ya existe."
        if not 3 <= len(datos["nombre"]) <= 60:
            errores["nombre"] = "Escribe el nombre completo (de 3 a 60 caracteres)."
        if datos["rol"] not in ROLES:
            errores["rol"] = "Elige un tipo de usuario."
        if not contrasena_valida(contrasena):
            errores["contrasena"] = "Mínimo 8 caracteres, con al menos una letra y un número."
        if not errores:
            with bd:
                bd.execute(
                    "INSERT INTO usuarios (usuario, contrasena_hash, nombre, rol) VALUES (?, ?, ?, ?)",
                    (datos["usuario"], generate_password_hash(contrasena), datos["nombre"],
                     datos["rol"]))
            flash(f"Usuario {datos['usuario']} creado.", "success")
            return redirect(url_for("usuarios"))

    codigo_http = 422 if errores else 200
    return render_template("usuario_form.html", editado=None, datos=datos,
                           errores=errores), codigo_http


@app.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@requiere_rol("administrador")
def usuario_editar(usuario_id):
    bd = obtener_bd()
    editado = bd.execute("SELECT id, usuario, nombre, rol, activo FROM usuarios WHERE id = ?",
                         (usuario_id,)).fetchone()
    if editado is None:
        abort(404)

    es_propio = editado["id"] == g.usuario["id"]
    datos = dict(editado)
    errores = {}
    if request.method == "POST":
        datos = {
            "usuario": editado["usuario"],
            "nombre": " ".join(request.form.get("nombre", "").split()),
            # nadie puede cambiarse su propio rol (evita quedarse sin administrador)
            "rol": editado["rol"] if es_propio else request.form.get("rol", ""),
        }
        contrasena = request.form.get("contrasena", "")
        if not 3 <= len(datos["nombre"]) <= 60:
            errores["nombre"] = "Escribe el nombre completo (de 3 a 60 caracteres)."
        if datos["rol"] not in ROLES:
            errores["rol"] = "Elige un tipo de usuario."
        if contrasena and not contrasena_valida(contrasena):
            errores["contrasena"] = "Mínimo 8 caracteres, con al menos una letra y un número."
        if not errores:
            with bd:
                bd.execute("UPDATE usuarios SET nombre = ?, rol = ? WHERE id = ?",
                           (datos["nombre"], datos["rol"], usuario_id))
                if contrasena:
                    bd.execute(
                        """UPDATE usuarios SET contrasena_hash = ?, intentos_fallidos = 0,
                               bloqueado_hasta = NULL WHERE id = ?""",
                        (generate_password_hash(contrasena), usuario_id))
            flash(f"Usuario {editado['usuario']} actualizado.", "success")
            return redirect(url_for("usuarios"))

    codigo_http = 422 if errores else 200
    return render_template("usuario_form.html", editado=editado, datos=datos, errores=errores,
                           es_propio=es_propio), codigo_http


@app.route("/usuarios/<int:usuario_id>/estado", methods=["POST"])
@requiere_rol("administrador")
def usuario_estado(usuario_id):
    """Activa o desactiva una cuenta. No se borra para conservar su historial."""
    bd = obtener_bd()
    editado = bd.execute("SELECT id, usuario, activo FROM usuarios WHERE id = ?",
                         (usuario_id,)).fetchone()
    if editado is None:
        abort(404)
    if editado["id"] == g.usuario["id"]:
        flash("No puedes desactivar tu propia cuenta.", "danger")
        return redirect(url_for("usuarios"))

    nuevo = 0 if editado["activo"] else 1
    with bd:
        bd.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (nuevo, usuario_id))
    flash(f"Usuario {editado['usuario']} {'activado' if nuevo else 'desactivado'}.", "success")
    return redirect(url_for("usuarios"))


# ---------------------------------------------------------------------------
# Disponibilidad y errores
# ---------------------------------------------------------------------------
@app.route("/salud")
def salud():
    """Un monitor puede consultar esta ruta para saber si el sistema responde."""
    obtener_bd().execute("SELECT 1")
    return {"estado": "ok"}


MENSAJES_ERROR = {
    403: ("No tienes permiso para ver esta página",
          "Esta sección corresponde a otro tipo de usuario."),
    404: ("Esta página no existe",
          "Revisa la dirección o regresa al panel principal."),
    500: ("Algo falló de nuestro lado",
          "Intenta de nuevo en unos minutos. Si el problema sigue, avisa al administrador."),
}


@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def pagina_error(error):
    codigo = getattr(error, "code", 500) or 500
    titulo, mensaje = MENSAJES_ERROR.get(codigo, MENSAJES_ERROR[500])
    return render_template("error.html", codigo=codigo, titulo=titulo, mensaje=mensaje), codigo


if __name__ == "__main__":
    if not os.path.exists(app.config["BASE_DATOS"]):
        from init_db import crear_base
        crear_base(app.config["BASE_DATOS"])
        print("Se creó la base de datos con datos de ejemplo (inventario.db).")
    # el modo debug queda apagado: mostraría el código ante un error
    app.run(debug=os.environ.get("INVENTARIO_DEBUG") == "1")
