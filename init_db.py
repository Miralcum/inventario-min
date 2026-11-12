"""
Crea (o vuelve a crear) la base de datos con datos de ejemplo.

Uso:  python3 init_db.py

ATENCIÓN: borra la base de datos anterior y todos sus cambios.
"""
import os
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

import inventario as inv

CARPETA = os.path.dirname(os.path.abspath(__file__))
RUTA_BD = os.path.join(CARPETA, "inventario.db")
RUTA_ESQUEMA = os.path.join(CARPETA, "schema.sql")

# Usuarios de demostración: usuario, contraseña, nombre, rol
# (cambia las contraseñas antes de usar el sistema en serio)
USUARIOS = [
    ("admin", "Admin2026", "Carlos Mendoza Ruiz", "administrador"),
    ("gerente", "Gerente2026", "Patricia Salas Ortiz", "gerente"),
    ("tecnico1", "Tecnico2026", "Jorge Luna Pérez", "tecnico"),
    ("tecnico2", "Tecnico2026", "Daniela Ríos Campos", "tecnico"),
]

# código, nombre, categoría, existencia inicial, mínimo, ubicación
PIEZAS = [
    ("P001", "Rodamiento de bolas 6204-2RS", "Rodamientos", 42, 10, "Pasillo A, estante 1"),
    ("P002", "Rodamiento de bolas 6205-ZZ", "Rodamientos", 32, 10, "Pasillo A, estante 1"),
    ("P003", "Sensor inductivo M18", "Sensores", 15, 5, "Pasillo C, estante 2"),
    ("P004", "Fusible 10 A", "Material eléctrico", 50, 20, "Pasillo D, gaveta 4"),
    ("P005", "Contactor trifásico 25 A", "Material eléctrico", 12, 4, "Pasillo D, estante 1"),
    ("P006", "Motor DC 24 V", "Motores", 10, 10, "Pasillo B, estante 3"),
    ("P007", "Motor trifásico 5 HP", "Motores", 6, 2, "Pasillo B, piso"),
    ("P008", "Sensor óptico", "Sensores", 5, 5, "Pasillo C, estante 2"),
    ("P009", "Sensor de temperatura PT100", "Sensores", 9, 4, "Pasillo C, estante 3"),
    ("P010", "Banda en V A-42", "Bandas y transmisión", 18, 6, "Pasillo E, estante 1"),
    ("P011", "Banda industrial dentada", "Bandas y transmisión", 5, 5, "Pasillo E, estante 1"),
    ("P012", "Cadena de rodillos ANSI 40", "Bandas y transmisión", 7, 3, "Pasillo E, estante 2"),
    ("P013", "Rodamiento 6001", "Rodamientos", 3, 10, "Pasillo A, estante 2"),
    ("P014", "Chumacera de piso UCP 205", "Rodamientos", 11, 4, "Pasillo A, estante 3"),
    ("P015", "Válvula solenoide 1/2 pulgada", "Hidráulica y neumática", 8, 3, "Pasillo F, estante 1"),
    ("P016", "Cilindro neumático 32 x 100 mm", "Hidráulica y neumática", 5, 2, "Pasillo F, estante 2"),
    ("P017", "Manguera hidráulica 1/2 pulgada (metro)", "Hidráulica y neumática", 25, 10, "Pasillo F, carrete 1"),
    ("P018", "Grasa de litio EP2 (cartucho)", "Lubricantes", 10, 12, "Pasillo G, estante 1"),
    ("P019", "Aceite hidráulico ISO 68 (cubeta)", "Lubricantes", 3, 3, "Pasillo G, piso"),
    ("P020", "Filtro de aire industrial", "Filtros", 14, 6, "Pasillo G, estante 3"),
    ("P021", "Filtro de aceite hidráulico", "Filtros", 5, 5, "Pasillo G, estante 3"),
    ("P022", "Tornillo hexagonal M8 x 40 (caja con 100)", "Tornillería", 22, 8, "Pasillo H, gaveta 2"),
    ("P023", "Relevador 24 V de 8 pines", "Material eléctrico", 16, 6, "Pasillo D, gaveta 6"),
    ("P024", "Interruptor termomagnético 3 x 32 A", "Material eléctrico", 9, 4, "Pasillo D, estante 2"),
]


def crear_base(ruta=RUTA_BD):
    """Borra la base de datos (si existe) y la crea con los datos de ejemplo."""
    if os.path.exists(ruta):
        os.remove(ruta)

    bd = sqlite3.connect(ruta)
    bd.row_factory = sqlite3.Row
    bd.execute("PRAGMA foreign_keys = ON")
    with open(RUTA_ESQUEMA, encoding="utf-8") as archivo:
        bd.executescript(archivo.read())

    hoy = datetime.now().replace(minute=0, second=0, microsecond=0)

    def hace(dias, hora=9, minuto=0):
        momento = (hoy - timedelta(days=dias)).replace(hour=hora, minute=minuto)
        if momento > datetime.now():  # nunca se generan fechas futuras
            momento = datetime.now() - timedelta(minutes=5)
        return momento.strftime("%Y-%m-%d %H:%M:%S")

    with bd:
        ids = {}
        for usuario, contrasena, nombre, rol in USUARIOS:
            # cada usuario recibe su propio hash (con "sal" aleatoria)
            fila = bd.execute(
                "INSERT INTO usuarios (usuario, contrasena_hash, nombre, rol) VALUES (?, ?, ?, ?)",
                (usuario, generate_password_hash(contrasena), nombre, rol))
            ids[usuario] = fila.lastrowid

        # Las piezas se crean en cero y su existencia inicial entra como movimiento:
        # así el historial explica de dónde salió cada unidad.
        for codigo, nombre, categoria, cantidad, minimo, ubicacion in PIEZAS:
            fila = bd.execute(
                """INSERT INTO piezas (codigo, nombre, categoria, cantidad, minimo, ubicacion)
                   VALUES (?, ?, ?, 0, ?, ?)""",
                (codigo, nombre, categoria, minimo, ubicacion))
            ids[codigo] = fila.lastrowid
            inv.registrar_movimiento(bd, fila.lastrowid, "entrada", cantidad,
                                     "Inventario inicial", ids["admin"], fecha=hace(30, 8))

        # ----- Historial de ejemplo -----
        # SOL-0001: aprobada
        s = inv.crear_solicitud(bd, ids["tecnico1"], ids["P001"], 2,
                                "Cambio de rodamientos en el motor de la banda 3", hace(20, 9, 15))
        inv.aprobar_solicitud(bd, s, ids["gerente"], hace(20, 10, 5))

        # SOL-0002: aprobada (deja el Motor DC en stock bajo)
        s = inv.crear_solicitud(bd, ids["tecnico2"], ids["P006"], 6,
                                "Reemplazo de motores en la línea de empaque 2", hace(15, 11, 30))
        inv.aprobar_solicitud(bd, s, ids["gerente"], hace(15, 12, 10))

        # SOL-0003: aprobada (agota la banda dentada)
        s = inv.crear_solicitud(bd, ids["tecnico1"], ids["P011"], 5,
                                "Mantenimiento preventivo de transportadores", hace(10, 8, 40))
        inv.aprobar_solicitud(bd, s, ids["gerente"], hace(10, 9, 20))

        # SOL-0004: rechazada (no cambia existencias)
        s = inv.crear_solicitud(bd, ids["tecnico2"], ids["P004"], 20,
                                "Reposición de fusibles del tablero principal", hace(8, 14, 0))
        inv.rechazar_solicitud(bd, s, ids["gerente"],
                               "Cantidad excesiva para una sola orden; solicita solo los necesarios.",
                               hace(8, 15, 30))

        # Entrada por compra y salida por ajuste, registradas por el administrador
        inv.registrar_movimiento(bd, ids["P018"], "entrada", 20, "Compra a proveedor",
                                 ids["admin"], fecha=hace(6, 10, 0))
        inv.registrar_movimiento(bd, ids["P019"], "salida", 3,
                                 "Ajuste: cubetas dañadas por derrame", ids["admin"],
                                 fecha=hace(5, 16, 45))

        # SOL-0005: aprobada (deja el sensor óptico en stock bajo)
        s = inv.crear_solicitud(bd, ids["tecnico1"], ids["P008"], 3,
                                "Sustitución de sensores en la etiquetadora", hace(3, 9, 0))
        inv.aprobar_solicitud(bd, s, ids["gerente"], hace(3, 9, 50))

        # SOL-0006 a SOL-0008: pendientes, para que el gerente tenga qué autorizar
        inv.crear_solicitud(bd, ids["tecnico1"], ids["P003"], 5,
                            "Instalación de sensores en la nueva celda de soldadura", hace(1, 13, 20))
        inv.crear_solicitud(bd, ids["tecnico2"], ids["P010"], 4,
                            "Cambio de bandas en ventiladores de extracción", hace(1, 16, 5))
        inv.crear_solicitud(bd, ids["tecnico2"], ids["P013"], 2,
                            "Reparación de la bomba de recirculación", hace(0, 8, 10))

    bd.close()


if __name__ == "__main__":
    crear_base()
    print(f"Base de datos creada en: {RUTA_BD}")
    print("Usuarios de prueba:")
    for usuario, contrasena, nombre, rol in USUARIOS:
        print(f"  {rol:<14} usuario: {usuario:<9} contraseña: {contrasena}")
