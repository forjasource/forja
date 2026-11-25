import json
import re
from urllib.parse import urljoin

import xbmcgui

from . import const, huella_arbol, red, sistema
from .instalador import Entrada_Minima, Instalador, Progreso
from .util import T, ajuste, log, version_mayor

RE_SHA = re.compile(r'^[0-9a-fA-F]{64}$')


class Actualizacion:
    def __init__(self, version, zip_, sha256, notas, contenido=''):
        self.version = version
        self.zip = zip_
        self.sha256 = sha256
        self.notas = notas
        self.contenido = contenido


def url_manifiesto():
    return (ajuste('url_actualizacion_forja', '') or const.URL_ACTUALIZACION_FORJA).strip()


def leer_manifiesto(timeout=10):
    url = url_manifiesto()
    texto, _, _ = red.get_texto(url, limite=64 * 1024, timeout=timeout)
    try:
        datos = json.loads(texto)
    except (ValueError, TypeError):
        raise red.ErrorRed(T('err_forja_manifiesto'))
    if not isinstance(datos, dict):
        raise red.ErrorRed(T('err_forja_manifiesto'))
    version = str(datos.get('version') or '').strip()
    zip_ = str(datos.get('zip') or '').strip() or '%s-%s.zip' % (const.ID, version)
    sha = str(datos.get('sha256') or '').strip().lower()
    contenido = str(datos.get('contenido_sha256') or '').strip().lower()
    if not version or not zip_ or not RE_SHA.match(sha):
        raise red.ErrorRed(T('err_forja_manifiesto'))
    if contenido and not RE_SHA.match(contenido):
        contenido = ''
    zip_ = urljoin(url, zip_)
    if not zip_.lower().startswith('https://'):
        raise red.ErrorRed(T('err_forja_manifiesto'))
    notas = str(datos.get('notas') or '').strip()[:600]
    return Actualizacion(version, zip_, sha, notas, contenido)


def consultar(timeout=10):
    act = leer_manifiesto(timeout)
    return act if version_mayor(act.version, const.VERSION) else None


def huella_instalada():
    return huella_arbol.huella_arbol(const.RUTA)


def instalar(act, progreso=None):
    entrada = Entrada_Minima(const.ID, const.NOMBRE, act.zip, act.sha256)
    entrada.copia_previa = False
    return Instalador().instalar(entrada, progreso=progreso)


def _instalar_con_reintento(act, dlg, obligatoria):
    while True:
        prog = Progreso(T('forja_actualizando', version=act.version), modal=True)
        try:
            res = instalar(act, prog)
        finally:
            prog.cerrar()
        if res.ok:
            dlg.ok(const.NOMBRE, T('forja_actualizada', version=act.version))
            return True
        if not dlg.yesno(T('forja_fallo_titulo'), T('forja_fallo', detalle=res.mensaje),
                         nolabel=T('salir') if obligatoria else T('luego'), yeslabel=T('reintentar')):
            return False


def comprobar_inicio():
    dlg = xbmcgui.Dialog()
    while True:
        try:
            act = leer_manifiesto()
            break
        except red.ErrorSinConexion as e:
            log('Forja sin conexión para comprobarse: %s' % e)
            if not dlg.yesno(T('forja_sin_conexion_titulo'), T('forja_sin_conexion'),
                             nolabel=T('salir'), yeslabel=T('reintentar')):
                return True
        except Exception as e:
            log('No se pudo comprobar Forja (se continúa): %s' % e)
            return False
    notas = ('\n\n' + act.notas) if act.notas else ''
    if version_mayor(act.version, const.VERSION):
        forzar = ajuste('forzar_actualizacion_forja', True)
        if forzar:
            dlg.ok(T('forja_nueva_titulo'), T('forja_nueva_forzada', nueva=act.version, actual=const.VERSION) + notas)
        elif not dlg.yesno(T('forja_nueva_titulo'),
                           T('forja_nueva_opcional', nueva=act.version, actual=const.VERSION) + notas,
                           nolabel=T('luego'), yeslabel=T('forja_actualizar')):
            return False
        instalada = _instalar_con_reintento(act, dlg, forzar)
        return instalada or forzar
    if act.version == const.VERSION and act.contenido:
        try:
            coincide = huella_instalada() == act.contenido
        except OSError as e:
            log('No se pudo calcular la huella de Forja: %s' % e)
            return False
        if not coincide:
            log('La huella de Forja no coincide con la de GitHub (versión %s).' % const.VERSION)
            if not dlg.yesno(T('forja_integridad_titulo'), T('forja_integridad', version=const.VERSION),
                             nolabel=T('salir'), yeslabel=T('forja_reinstalar')):
                return True
            _instalar_con_reintento(act, dlg, True)
            return True
    return False


def comprobar_manual():
    dlg = xbmcgui.Dialog()
    try:
        act = consultar(timeout=20)
    except Exception as e:
        dlg.ok(const.NOMBRE, T('forja_no_comprobada', detalle=str(e)[:160]))
        return
    if act is None:
        dlg.ok(const.NOMBRE, T('forja_al_dia', version=const.VERSION))
        return
    if dlg.yesno(T('forja_nueva_titulo'), T('forja_nueva_opcional', nueva=act.version, actual=const.VERSION),
                 nolabel=T('luego'), yeslabel=T('forja_actualizar')):
        prog = Progreso(T('forja_actualizando', version=act.version), modal=True)
        try:
            res = instalar(act, prog)
        finally:
            prog.cerrar()
        dlg.ok(const.NOMBRE, T('forja_actualizada', version=act.version) if res.ok
               else T('forja_fallo', detalle=res.mensaje))


def actualizar_en_silencio():
    act = consultar(timeout=15)
    if act is None:
        return None
    prog = Progreso(T('forja_actualizando', version=act.version), modal=False)
    try:
        res = instalar(act, prog)
    finally:
        prog.cerrar()
    if res.ok:
        sistema.notificar(const.NOMBRE, T('forja_actualizada_corta', version=act.version), ms=6000)
        return act.version
    log('Autoactualización fallida: %s' % res.mensaje)
    return None
