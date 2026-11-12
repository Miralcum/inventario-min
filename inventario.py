"""
Reglas del inventario: movimientos, solicitudes y estados de las piezas.

Este archivo no tiene nada de web. Lo usan app.py (la página), init_db.py
(los datos de ejemplo) y pruebas.py, para que las reglas estén en un solo lugar.

Ninguna función hace "commit": quien las llama usa  with bd:  para que todos
los cambios de una operación se guarden juntos o no se guarde ninguno.
"""
from datetime import datetime

CANTIDAD_MAXIMA = 100000

# Estado de una pieza según su existencia y su mínimo (se usa dentro del SQL)
ESTADO_SQL = """CASE WHEN p.cantidad = 0 THEN 'agotada'
                     WHEN p.cantidad <= p.minimo THEN 'bajo'
                     ELSE 'disponible' END"""


class ErrorInventario(Exception):
    """Una regla del inventario impidió la operación (el mensaje se muestra al usuario)."""


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def folio(solicitud_id):
    """7 -> 'SOL-0007'."""
    return f"SOL-{solicitud_id:04d}"


def registrar_movimiento(bd, pieza_id, tipo, cantidad, motivo, usuario_id,
                         solicitud_id=None, fecha=None):
    """Suma (entrada) o resta (salida) existencias y deja el movimiento registrado.

    Devuelve la existencia nueva. Es la ÚNICA función que cambia la cantidad de
    una pieza: así toda entrada o salida queda siempre en el historial.
    """
    if tipo not in ("entrada", "salida"):
        raise ErrorInventario("El tipo de movimiento no es válido.")
    if not 1 <= cantidad <= CANTIDAD_MAXIMA:
        raise ErrorInventario("La cantidad debe ser un número entero mayor que cero.")

    pieza = bd.execute("SELECT nombre, cantidad FROM piezas WHERE id = ?", (pieza_id,)).fetchone()
    if pieza is None:
        raise ErrorInventario("La pieza no existe.")

    anterior = pieza["cantidad"]
    nueva = anterior + cantidad if tipo == "entrada" else anterior - cantidad
    if nueva < 0:
        raise ErrorInventario(
            f"No hay existencias suficientes de {pieza['nombre']}: "
            f"hay {anterior} y se quieren sacar {cantidad}.")
    if nueva > CANTIDAD_MAXIMA:
        raise ErrorInventario("La existencia resultante es demasiado grande.")

    # La condición "AND cantidad = ?" evita que dos operaciones simultáneas
    # descuenten la misma existencia
    cambio = bd.execute("UPDATE piezas SET cantidad = ? WHERE id = ? AND cantidad = ?",
                        (nueva, pieza_id, anterior))
    if cambio.rowcount != 1:
        raise ErrorInventario("La existencia cambió mientras se guardaba. Vuelve a intentarlo.")

    bd.execute(
        """INSERT INTO movimientos (pieza_id, tipo, cantidad, existencia_anterior,
               existencia_nueva, motivo, usuario_id, solicitud_id, fecha)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pieza_id, tipo, cantidad, anterior, nueva, motivo, usuario_id, solicitud_id,
         fecha or ahora()))
    return nueva


def crear_solicitud(bd, tecnico_id, pieza_id, cantidad, motivo, fecha=None):
    """El técnico pide material. La solicitud queda pendiente; NO cambia existencias."""
    pieza = bd.execute("SELECT nombre, cantidad, activo FROM piezas WHERE id = ?",
                       (pieza_id,)).fetchone()
    if pieza is None or not pieza["activo"]:
        raise ErrorInventario("La pieza no existe o fue dada de baja.")
    if pieza["cantidad"] == 0:
        raise ErrorInventario(f"{pieza['nombre']} está agotada; por ahora no se puede solicitar.")
    if not 1 <= cantidad <= pieza["cantidad"]:
        raise ErrorInventario(
            f"Solo hay {pieza['cantidad']} en existencia; pide esa cantidad o menos.")

    nueva = bd.execute(
        """INSERT INTO solicitudes (tecnico_id, pieza_id, cantidad, motivo, fecha)
           VALUES (?, ?, ?, ?, ?)""",
        (tecnico_id, pieza_id, cantidad, motivo, fecha or ahora()))
    return nueva.lastrowid


def aprobar_solicitud(bd, solicitud_id, gerente_id, fecha=None):
    """El gerente autoriza: se descuenta la existencia y se registra la salida."""
    solicitud = bd.execute("SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)).fetchone()
    if solicitud is None:
        raise ErrorInventario("La solicitud no existe.")
    if solicitud["estado"] != "pendiente":
        raise ErrorInventario(f"La solicitud {folio(solicitud_id)} ya había sido respondida.")

    pieza = bd.execute("SELECT nombre, cantidad, activo FROM piezas WHERE id = ?",
                       (solicitud["pieza_id"],)).fetchone()
    if not pieza["activo"]:
        raise ErrorInventario("La pieza fue dada de baja; rechaza la solicitud.")
    if pieza["cantidad"] < solicitud["cantidad"]:
        raise ErrorInventario(
            f"No se puede autorizar {folio(solicitud_id)}: hay {pieza['cantidad']} de "
            f"{pieza['nombre']} y se solicitaron {solicitud['cantidad']}. "
            f"Rechaza la solicitud o espera a que se registre una entrada.")

    fecha = fecha or ahora()
    # "AND estado = 'pendiente'" evita autorizar dos veces la misma solicitud
    cambio = bd.execute(
        """UPDATE solicitudes SET estado = 'aprobada', gerente_id = ?, fecha_respuesta = ?
           WHERE id = ? AND estado = 'pendiente'""",
        (gerente_id, fecha, solicitud_id))
    if cambio.rowcount != 1:
        raise ErrorInventario(f"La solicitud {folio(solicitud_id)} ya había sido respondida.")

    return registrar_movimiento(
        bd, solicitud["pieza_id"], "salida", solicitud["cantidad"],
        f"Solicitud {folio(solicitud_id)} autorizada", gerente_id,
        solicitud_id=solicitud_id, fecha=fecha)


def rechazar_solicitud(bd, solicitud_id, gerente_id, comentario, fecha=None):
    """El gerente rechaza: se guarda el motivo y las existencias NO cambian."""
    cambio = bd.execute(
        """UPDATE solicitudes SET estado = 'rechazada', gerente_id = ?, fecha_respuesta = ?,
               comentario = ?
           WHERE id = ? AND estado = 'pendiente'""",
        (gerente_id, fecha or ahora(), comentario, solicitud_id))
    if cambio.rowcount != 1:
        raise ErrorInventario(f"La solicitud {folio(solicitud_id)} no existe o ya fue respondida.")
