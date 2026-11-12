-- Base de datos del sistema de control de inventario (SQLite)
-- Las reglas CHECK, UNIQUE y FOREIGN KEY hacen que la propia base de datos
-- rechace datos inválidos, aunque la aplicación tuviera un error.

PRAGMA foreign_keys = ON;

CREATE TABLE usuarios (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario           TEXT    NOT NULL UNIQUE,
    -- solo se guarda el hash, nunca la contraseña escrita
    contrasena_hash   TEXT    NOT NULL,
    nombre            TEXT    NOT NULL,
    rol               TEXT    NOT NULL CHECK (rol IN ('administrador', 'gerente', 'tecnico')),
    activo            INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    -- control de intentos fallidos para bloquear ataques de fuerza bruta
    intentos_fallidos INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta   TEXT
);

CREATE TABLE piezas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo    TEXT    NOT NULL UNIQUE,
    nombre    TEXT    NOT NULL,
    categoria TEXT    NOT NULL,
    -- la existencia nunca puede ser negativa
    cantidad  INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
    -- cantidad mínima: al llegar a ella se muestra una alerta de stock bajo
    minimo    INTEGER NOT NULL DEFAULT 0 CHECK (minimo >= 0),
    ubicacion TEXT    NOT NULL,
    -- las piezas no se borran: se dan de baja para conservar su historial
    activo    INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE solicitudes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id      INTEGER NOT NULL REFERENCES usuarios(id),
    pieza_id        INTEGER NOT NULL REFERENCES piezas(id),
    cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
    motivo          TEXT    NOT NULL,
    estado          TEXT    NOT NULL DEFAULT 'pendiente'
                            CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
    fecha           TEXT    NOT NULL,
    -- quién la autorizó o rechazó, cuándo y con qué comentario
    gerente_id      INTEGER REFERENCES usuarios(id),
    fecha_respuesta TEXT,
    comentario      TEXT
);

-- Cada entrada o salida del almacén queda registrada con la existencia
-- anterior y la nueva, quién la hizo y por qué.
CREATE TABLE movimientos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pieza_id            INTEGER NOT NULL REFERENCES piezas(id),
    tipo                TEXT    NOT NULL CHECK (tipo IN ('entrada', 'salida')),
    cantidad            INTEGER NOT NULL CHECK (cantidad > 0),
    existencia_anterior INTEGER NOT NULL CHECK (existencia_anterior >= 0),
    existencia_nueva    INTEGER NOT NULL CHECK (existencia_nueva >= 0),
    motivo              TEXT    NOT NULL,
    usuario_id          INTEGER NOT NULL REFERENCES usuarios(id),
    -- si la salida viene de una solicitud autorizada, aquí queda el enlace
    solicitud_id        INTEGER REFERENCES solicitudes(id),
    fecha               TEXT    NOT NULL
);

-- Índices para que las consultas más comunes sean rápidas
CREATE INDEX idx_piezas_activo         ON piezas(activo, codigo);
CREATE INDEX idx_solicitudes_estado    ON solicitudes(estado);
CREATE INDEX idx_solicitudes_tecnico   ON solicitudes(tecnico_id);
CREATE INDEX idx_movimientos_pieza     ON movimientos(pieza_id);
CREATE INDEX idx_movimientos_fecha     ON movimientos(fecha);
