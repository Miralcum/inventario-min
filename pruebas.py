"""
Pruebas automáticas del sistema de inventario.

Uso:  python3 pruebas.py

Cada prueba trabaja sobre una copia nueva de la base de datos de ejemplo,
así que no modifican inventario.db ni dependen unas de otras.
Los nombres indican el requisito de la actividad que comprueban (r1 a r9).
"""
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

import app as sistema
from init_db import crear_base

CLAVES = {"admin": "Admin2026", "gerente": "Gerente2026",
          "tecnico1": "Tecnico2026", "tecnico2": "Tecnico2026"}


class PruebasInventario(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.carpeta = tempfile.TemporaryDirectory()
        cls.plantilla_bd = os.path.join(cls.carpeta.name, "plantilla.db")
        crear_base(cls.plantilla_bd)

    @classmethod
    def tearDownClass(cls):
        cls.carpeta.cleanup()

    def setUp(self):
        self.ruta_bd = os.path.join(self.carpeta.name, "prueba.db")
        shutil.copy(self.plantilla_bd, self.ruta_bd)
        sistema.app.config.update(BASE_DATOS=self.ruta_bd, TESTING=True)

    # ----- utilidades -----
    def token(self, cliente, url="/login"):
        html = cliente.get(url).get_data(as_text=True)
        return re.search(r'name="csrf" value="([^"]+)"', html).group(1)

    def entrar(self, usuario, contrasena=None):
        """Inicia sesión y devuelve el cliente (un navegador simulado)."""
        cliente = sistema.app.test_client()
        cliente.post("/login", data={"csrf": self.token(cliente), "usuario": usuario,
                                     "contrasena": contrasena or CLAVES[usuario]})
        return cliente

    def enviar(self, cliente, url, datos=None, pagina="/"):
        """Envía un formulario con su token CSRF."""
        datos = dict(datos or {})
        datos["csrf"] = self.token(cliente, pagina)
        return cliente.post(url, data=datos, follow_redirects=True)

    def consultar(self, sql, parametros=()):
        bd = sqlite3.connect(self.ruta_bd)
        bd.row_factory = sqlite3.Row
        filas = bd.execute(sql, parametros).fetchall()
        bd.close()
        return filas

    def pieza(self, codigo):
        return self.consultar("SELECT * FROM piezas WHERE codigo = ?", (codigo,))[0]

    def solicitar(self, tecnico, codigo, cantidad, motivo="Mantenimiento de la línea 1"):
        """El técnico crea una solicitud; devuelve su id."""
        cliente = self.entrar(tecnico)
        self.enviar(cliente, "/solicitudes/nueva",
                    {"pieza_id": self.pieza(codigo)["id"], "cantidad": cantidad, "motivo": motivo})
        return self.consultar("SELECT MAX(id) AS id FROM solicitudes")[0]["id"]

    # ============ Requisito 1: inicio de sesión para los tres tipos de usuario ============
    def test_r1_los_tres_tipos_de_usuario_inician_sesion(self):
        """R1: administrador, gerente y técnico entran y ven su panel"""
        for usuario, nombre in [("admin", "Carlos Mendoza"), ("gerente", "Patricia Salas"),
                                ("tecnico1", "Jorge Luna")]:
            respuesta = self.entrar(usuario).get("/")
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn(nombre, respuesta.get_data(as_text=True))

    def test_r1_contrasena_incorrecta_no_entra(self):
        """R1: con contraseña incorrecta no se entra y el mensaje no revela si el usuario existe"""
        cliente = self.entrar("admin", "incorrecta")
        self.assertEqual(cliente.get("/").status_code, 302)
        for usuario in ("admin", "noexiste"):
            c = sistema.app.test_client()
            html = c.post("/login", data={"csrf": self.token(c), "usuario": usuario,
                                          "contrasena": "x"}).get_data(as_text=True)
            self.assertIn("Usuario o contraseña incorrectos.", html)

    def test_r1_sin_sesion_no_se_ve_nada(self):
        """R1: sin iniciar sesión, todas las páginas mandan al inicio de sesión"""
        cliente = sistema.app.test_client()
        for url in ("/", "/piezas", "/solicitudes", "/movimientos", "/reportes", "/usuarios"):
            respuesta = cliente.get(url)
            self.assertEqual(respuesta.status_code, 302, url)
            self.assertIn("/login", respuesta.headers["Location"])

    def test_r1_bloqueo_tras_cinco_intentos(self):
        """R1: cinco intentos fallidos bloquean la cuenta aunque después se escriba bien"""
        for _ in range(5):
            self.entrar("tecnico2", "incorrecta")
        cliente = self.entrar("tecnico2")
        self.assertEqual(cliente.get("/").status_code, 302)

    # ============ Requisito 2: panel principal con información general ============
    def test_r2_dashboard_con_resumen_del_inventario(self):
        """R2: el Dashboard muestra total de piezas, en stock, stock bajo y agotadas"""
        for usuario in ("admin", "gerente", "tecnico1"):
            html = self.entrar(usuario).get("/").get_data(as_text=True)
            self.assertIn('data-disponibles="18" data-bajas="4"', html)
            self.assertIn('data-agotadas="2"', html)
            self.assertIn("Alertas de inventario", html)

    # ============ Requisito 3: mínimo 20 piezas con todos sus datos ============
    def test_r3_minimo_veinte_piezas_completas(self):
        """R3: hay al menos 20 piezas con código, nombre, categoría, cantidad y ubicación"""
        piezas = self.consultar("SELECT * FROM piezas WHERE activo = 1")
        self.assertGreaterEqual(len(piezas), 20)
        for p in piezas:
            for campo in ("codigo", "nombre", "categoria", "ubicacion"):
                self.assertTrue(p[campo].strip(), f"{p['codigo']} sin {campo}")
            self.assertGreaterEqual(p["cantidad"], 0)
        self.assertEqual(len({p["codigo"] for p in piezas}), len(piezas))  # códigos únicos

    # ============ Requisito 4: consultar, buscar y administrar según permisos ============
    def test_r4_busqueda_y_filtros(self):
        """R4: se puede buscar por texto y filtrar por categoría y estado"""
        cliente = self.entrar("tecnico1")
        html = cliente.get("/piezas?q=sensor").get_data(as_text=True)
        self.assertIn("3 de 24 piezas", html)
        self.assertIn("Sensor óptico", html)
        self.assertNotIn("Fusible 10 A", html)
        self.assertIn("4 de 24 piezas", cliente.get("/piezas?categoria=Rodamientos").get_data(as_text=True))
        self.assertIn("2 de 24 piezas", cliente.get("/piezas?estado=agotada").get_data(as_text=True))
        self.assertIn("Ninguna pieza coincide", cliente.get("/piezas?q=zzzz").get_data(as_text=True))

    def test_r4_busqueda_sin_recargar(self):
        """R4: cuando el JavaScript pide la búsqueda, el servidor devuelve solo la tabla"""
        cliente = self.entrar("gerente")
        html = cliente.get("/piezas?q=motor", headers={"X-Requested-With": "fetch"}).get_data(as_text=True)
        self.assertIn("Motor DC 24 V", html)
        self.assertNotIn("<html", html)

    def test_r4_administrador_registra_modifica_y_elimina(self):
        """R4: el administrador registra, modifica y elimina piezas"""
        cliente = self.entrar("admin")
        self.enviar(cliente, "/piezas/nueva",
                    {"codigo": "p025", "nombre": "Acoplamiento flexible L-100", "categoria": "Bandas y transmisión",
                     "cantidad": "12", "minimo": "4", "ubicacion": "Pasillo E, estante 3"})
        nueva = self.pieza("P025")   # el código se guarda en mayúsculas
        self.assertEqual((nueva["cantidad"], nueva["minimo"]), (12, 4))

        self.enviar(cliente, f"/piezas/{nueva['id']}/editar",
                    {"codigo": "P025", "nombre": "Acoplamiento flexible L-110", "categoria": "Bandas y transmisión",
                     "minimo": "6", "ubicacion": "Pasillo E, estante 4"})
        editada = self.pieza("P025")
        self.assertEqual((editada["nombre"], editada["minimo"]), ("Acoplamiento flexible L-110", 6))
        self.assertEqual(editada["cantidad"], 12)   # editar no cambia la existencia

        self.enviar(cliente, f"/piezas/{nueva['id']}/eliminar")
        self.assertEqual(self.pieza("P025")["activo"], 0)
        self.assertNotIn("P025", cliente.get("/piezas").get_data(as_text=True))

    def test_r4_gerente_y_tecnico_no_administran_piezas(self):
        """R4: el gerente y el técnico reciben error 403 si intentan administrar piezas"""
        for usuario in ("gerente", "tecnico1"):
            cliente = self.entrar(usuario)
            self.assertEqual(cliente.get("/piezas").status_code, 200)   # sí pueden consultar
            self.assertEqual(cliente.get("/piezas/nueva").status_code, 403)
            self.assertEqual(cliente.get("/piezas/1/editar").status_code, 403)
            respuesta = cliente.post("/piezas/1/eliminar", data={"csrf": self.token(cliente, "/")})
            self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.pieza("P001")["activo"], 1)

    def test_r4_datos_invalidos_no_se_guardan(self):
        """R4: un código repetido o una cantidad negativa no se guardan"""
        cliente = self.entrar("admin")
        base = {"nombre": "Pieza de prueba", "categoria": "Filtros", "cantidad": "5",
                "minimo": "1", "ubicacion": "Pasillo Z"}
        html = self.enviar(cliente, "/piezas/nueva", dict(base, codigo="P001")).get_data(as_text=True)
        self.assertIn("ya pertenece a otra pieza", html)
        self.enviar(cliente, "/piezas/nueva", dict(base, codigo="P030", cantidad="-5"))
        self.assertEqual(self.consultar("SELECT COUNT(*) AS n FROM piezas")[0]["n"], 24)

    # ============ Requisito 5: solicitudes de materiales de los técnicos ============
    def test_r5_tecnico_solicita_material(self):
        """R5: el técnico crea una solicitud; queda pendiente y las existencias no cambian"""
        antes = self.pieza("P004")["cantidad"]
        solicitud = self.solicitar("tecnico1", "P004", 10)
        fila = self.consultar("SELECT * FROM solicitudes WHERE id = ?", (solicitud,))[0]
        self.assertEqual((fila["estado"], fila["cantidad"]), ("pendiente", 10))
        self.assertEqual(self.pieza("P004")["cantidad"], antes)

    def test_r5_tecnico_solo_ve_sus_solicitudes(self):
        """R5: cada técnico revisa el estado de sus solicitudes, no las de otros"""
        html = self.entrar("tecnico1").get("/solicitudes").get_data(as_text=True)
        self.assertIn("SOL-0006", html)      # suya
        self.assertNotIn("SOL-0007", html)   # de tecnico2
        self.assertNotIn("Daniela", html)

    def test_r5_no_se_pide_mas_de_lo_que_hay(self):
        """R5: no se puede solicitar una pieza agotada ni más unidades de las que existen"""
        cliente = self.entrar("tecnico1")
        total = self.consultar("SELECT COUNT(*) AS n FROM solicitudes")[0]["n"]
        self.enviar(cliente, "/solicitudes/nueva",
                    {"pieza_id": self.pieza("P011")["id"], "cantidad": "1", "motivo": "Cambio de banda"})
        html = self.enviar(cliente, "/solicitudes/nueva",
                           {"pieza_id": self.pieza("P007")["id"], "cantidad": "99",
                            "motivo": "Cambio de motor"}).get_data(as_text=True)
        self.assertIn("Solo hay 6 en existencia", html)
        self.assertEqual(self.consultar("SELECT COUNT(*) AS n FROM solicitudes")[0]["n"], total)

    def test_r5_solo_los_tecnicos_solicitan(self):
        """R5: el administrador y el gerente no pueden crear solicitudes"""
        for usuario in ("admin", "gerente"):
            self.assertEqual(self.entrar(usuario).get("/solicitudes/nueva").status_code, 403)

    # ============ Requisito 6: el gerente aprueba o rechaza ============
    def test_r6_solo_el_gerente_responde(self):
        """R6: el técnico y el administrador reciben error 403 al intentar aprobar o rechazar"""
        for usuario in ("tecnico1", "admin"):
            cliente = self.entrar(usuario)
            for accion in ("aprobar", "rechazar"):
                respuesta = cliente.post(f"/solicitudes/6/{accion}",
                                         data={"csrf": self.token(cliente, "/"), "comentario": "No procede"})
                self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.consultar("SELECT estado FROM solicitudes WHERE id = 6")[0]["estado"], "pendiente")

    def test_r6_rechazar_guarda_el_motivo_y_no_cambia_existencias(self):
        """R6: al rechazar se guarda el motivo y las existencias quedan igual"""
        antes = self.pieza("P003")["cantidad"]
        movimientos = self.consultar("SELECT COUNT(*) AS n FROM movimientos")[0]["n"]
        gerente = self.entrar("gerente")
        self.enviar(gerente, "/solicitudes/6/rechazar", {"comentario": "Ya se entregaron sensores para esa celda"})
        fila = self.consultar("SELECT * FROM solicitudes WHERE id = 6")[0]
        self.assertEqual(fila["estado"], "rechazada")
        self.assertEqual(fila["comentario"], "Ya se entregaron sensores para esa celda")
        self.assertEqual(self.pieza("P003")["cantidad"], antes)
        self.assertEqual(self.consultar("SELECT COUNT(*) AS n FROM movimientos")[0]["n"], movimientos)
        # el técnico ve el motivo
        self.assertIn("Ya se entregaron sensores", self.entrar("tecnico1").get("/solicitudes").get_data(as_text=True))

    def test_r6_rechazar_exige_motivo(self):
        """R6: no se puede rechazar sin escribir el motivo"""
        self.enviar(self.entrar("gerente"), "/solicitudes/6/rechazar", {"comentario": ""})
        self.assertEqual(self.consultar("SELECT estado FROM solicitudes WHERE id = 6")[0]["estado"], "pendiente")

    def test_r6_una_solicitud_no_se_responde_dos_veces(self):
        """R6: una solicitud ya aprobada no se puede aprobar otra vez (no descuenta doble)"""
        gerente = self.entrar("gerente")
        self.enviar(gerente, "/solicitudes/6/aprobar")
        html = self.enviar(gerente, "/solicitudes/6/aprobar").get_data(as_text=True)
        self.assertIn("ya había sido respondida", html)
        self.assertEqual(self.pieza("P003")["cantidad"], 10)   # 15 - 5, una sola vez

    # ============ Requisito 7: actualizar existencias al autorizar ============
    def test_r7_aprobar_descuenta_existencias_y_registra_la_salida(self):
        """R7: al autorizar, la existencia baja y se registra la salida con quién la autorizó"""
        solicitud = self.solicitar("tecnico1", "P004", 10)
        self.assertEqual(self.pieza("P004")["cantidad"], 50)
        self.enviar(self.entrar("gerente"), f"/solicitudes/{solicitud}/aprobar")

        self.assertEqual(self.pieza("P004")["cantidad"], 40)
        fila = self.consultar("SELECT * FROM solicitudes WHERE id = ?", (solicitud,))[0]
        self.assertEqual(fila["estado"], "aprobada")
        movimiento = self.consultar(
            """SELECT m.*, u.usuario FROM movimientos m JOIN usuarios u ON u.id = m.usuario_id
               WHERE m.solicitud_id = ?""", (solicitud,))[0]
        self.assertEqual((movimiento["tipo"], movimiento["cantidad"]), ("salida", 10))
        self.assertEqual((movimiento["existencia_anterior"], movimiento["existencia_nueva"]), (50, 40))
        self.assertEqual(movimiento["usuario"], "gerente")

    def test_r7_sin_existencias_suficientes_no_se_autoriza(self):
        """R7: si ya no alcanzan las existencias, la solicitud no se autoriza y nada cambia"""
        primera = self.solicitar("tecnico1", "P007", 4)   # hay 6
        segunda = self.solicitar("tecnico2", "P007", 4)
        gerente = self.entrar("gerente")
        self.enviar(gerente, f"/solicitudes/{primera}/aprobar")          # quedan 2
        html = self.enviar(gerente, f"/solicitudes/{segunda}/aprobar").get_data(as_text=True)
        self.assertIn("No se puede autorizar", html)
        self.assertEqual(self.pieza("P007")["cantidad"], 2)
        self.assertEqual(self.consultar("SELECT estado FROM solicitudes WHERE id = ?", (segunda,))[0]["estado"],
                         "pendiente")

    # ============ Requisito 8: alertas de piezas agotadas o con existencias bajas ============
    def test_r8_alertas_de_agotadas_y_stock_bajo(self):
        """R8: la página de alertas separa las piezas agotadas de las de stock bajo"""
        html = self.entrar("gerente").get("/alertas").get_data(as_text=True)
        agotadas, bajas = html.split("Piezas con stock bajo")
        for codigo in ("P011", "P019"):
            self.assertIn(codigo, agotadas)
        for codigo in ("P006", "P008", "P013", "P021"):
            self.assertIn(codigo, bajas)
        self.assertNotIn("P004", html)   # está por encima de su mínimo

    def test_r8_la_alerta_aparece_al_bajar_del_minimo(self):
        """R8: cuando una salida deja la pieza en su mínimo o por debajo, aparece la alerta"""
        solicitud = self.solicitar("tecnico1", "P005", 9)   # hay 12, mínimo 4 -> quedan 3
        self.assertNotIn("P005", self.entrar("admin").get("/alertas").get_data(as_text=True))
        self.enviar(self.entrar("gerente"), f"/solicitudes/{solicitud}/aprobar")
        self.assertIn("P005", self.entrar("admin").get("/alertas").get_data(as_text=True))
        self.assertIn('data-bajas="5"', self.entrar("admin").get("/").get_data(as_text=True))

    # ============ Requisito 9: movimientos de entrada y salida ============
    def test_r9_entrada_y_salida_quedan_registradas(self):
        """R9: el administrador registra una entrada y una salida; ambas quedan en el historial"""
        admin = self.entrar("admin")
        pieza = self.pieza("P011")   # agotada
        self.enviar(admin, "/movimientos/nuevo", {"pieza_id": pieza["id"], "tipo": "entrada",
                                                  "cantidad": "12", "motivo": "Compra a proveedor"})
        self.assertEqual(self.pieza("P011")["cantidad"], 12)
        self.enviar(admin, "/movimientos/nuevo", {"pieza_id": pieza["id"], "tipo": "salida",
                                                  "cantidad": "2", "motivo": "Ajuste: pieza dañada"})
        self.assertEqual(self.pieza("P011")["cantidad"], 10)

        ultimos = self.consultar("SELECT * FROM movimientos WHERE pieza_id = ? ORDER BY id DESC LIMIT 2",
                                 (pieza["id"],))
        self.assertEqual([(m["tipo"], m["existencia_anterior"], m["existencia_nueva"]) for m in ultimos],
                         [("salida", 12, 10), ("entrada", 0, 12)])
        self.assertIn("Compra a proveedor", admin.get("/movimientos?tipo=entrada").get_data(as_text=True))

    def test_r9_no_se_saca_mas_de_lo_que_hay(self):
        """R9: una salida mayor que la existencia se rechaza; la existencia nunca es negativa"""
        admin = self.entrar("admin")
        pieza = self.pieza("P008")   # hay 2
        html = self.enviar(admin, "/movimientos/nuevo", {"pieza_id": pieza["id"], "tipo": "salida",
                                                         "cantidad": "5", "motivo": "Ajuste por conteo"}
                           ).get_data(as_text=True)
        self.assertIn("No hay existencias suficientes", html)
        self.assertEqual(self.pieza("P008")["cantidad"], 2)

    def test_r9_permisos_de_movimientos(self):
        """R9: el gerente consulta los movimientos pero no los registra; el técnico no los ve"""
        gerente = self.entrar("gerente")
        self.assertEqual(gerente.get("/movimientos").status_code, 200)
        self.assertEqual(gerente.get("/movimientos/nuevo").status_code, 403)
        self.assertEqual(self.entrar("tecnico1").get("/movimientos").status_code, 403)

    def test_r9_la_existencia_coincide_con_los_movimientos(self):
        """R9: la existencia de cada pieza es igual a sus entradas menos sus salidas"""
        self.enviar(self.entrar("gerente"), "/solicitudes/6/aprobar")
        diferencias = self.consultar(
            """SELECT p.codigo FROM piezas p
               WHERE p.cantidad != (SELECT COALESCE(SUM(CASE WHEN m.tipo = 'entrada'
                                           THEN m.cantidad ELSE -m.cantidad END), 0)
                                    FROM movimientos m WHERE m.pieza_id = p.id)""")
        self.assertEqual([f["codigo"] for f in diferencias], [])

    # ============ Reportes, usuarios y seguridad ============
    def test_reportes_del_gerente(self):
        """Reportes: el gerente ve el reporte y descarga los archivos CSV; el técnico no"""
        gerente = self.entrar("gerente")
        html = gerente.get("/reportes").get_data(as_text=True)
        self.assertIn("Inventario por categoría", html)
        self.assertIn("Material entregado por técnico", html)
        archivo = gerente.get("/reportes/inventario.csv")
        self.assertIn("text/csv", archivo.headers["Content-Type"])
        self.assertEqual(len(archivo.get_data(as_text=True).strip().splitlines()), 25)   # encabezado + 24
        self.assertIn("SOL-0001", gerente.get("/reportes/movimientos.csv").get_data(as_text=True))
        self.assertEqual(self.entrar("tecnico1").get("/reportes").status_code, 403)

    def test_usuarios_los_administra_el_administrador(self):
        """Usuarios: el administrador crea, edita y desactiva cuentas; los demás no"""
        admin = self.entrar("admin")
        self.enviar(admin, "/usuarios/nuevo", {"usuario": "tecnico3", "nombre": "Mario Vega Soto",
                                               "rol": "tecnico", "contrasena": "Tecnico2027"})
        nuevo = self.entrar("tecnico3", "Tecnico2027")
        self.assertEqual(nuevo.get("/").status_code, 200)

        fila = self.consultar("SELECT id FROM usuarios WHERE usuario = 'tecnico3'")[0]
        self.enviar(admin, f"/usuarios/{fila['id']}/estado")          # desactivar
        self.assertEqual(nuevo.get("/").status_code, 302)             # su sesión se cierra
        self.assertEqual(self.entrar("tecnico3", "Tecnico2027").get("/").status_code, 302)

        self.enviar(admin, "/usuarios/1/estado")                      # no puede desactivarse a sí mismo
        self.assertEqual(self.consultar("SELECT activo FROM usuarios WHERE id = 1")[0]["activo"], 1)
        for usuario in ("gerente", "tecnico1"):
            self.assertEqual(self.entrar(usuario).get("/usuarios").status_code, 403)

    def test_seguridad_contrasenas_y_formularios(self):
        """Seguridad: contraseñas guardadas como hash, token CSRF obligatorio y encabezados"""
        for fila in self.consultar("SELECT contrasena_hash FROM usuarios"):
            self.assertTrue(fila["contrasena_hash"].startswith(("scrypt:", "pbkdf2:")))
            self.assertNotIn("2026", fila["contrasena_hash"][:20])

        gerente = self.entrar("gerente")
        gerente.post("/solicitudes/6/aprobar", data={})                # sin token CSRF
        self.assertEqual(self.consultar("SELECT estado FROM solicitudes WHERE id = 6")[0]["estado"], "pendiente")

        respuesta = gerente.get("/")
        self.assertEqual(respuesta.headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'self'", respuesta.headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
