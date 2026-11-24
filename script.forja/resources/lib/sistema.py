import json
import os

import xbmc
import xbmcgui

from . import const
from .util import log


class ErrorKodi(Exception):
    pass


TIPOS_EJECUTABLES = ('xbmc.python.script', 'xbmc.python.pluginsource', 'executable')
TIPO_SKIN = 'xbmc.gui.skin'


def jsonrpc(metodo, params=None):
    peticion = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': metodo, 'params': params or {}})
    try:
        resp = json.loads(xbmc.executeJSONRPC(peticion))
    except ValueError as e:
        raise ErrorKodi('Respuesta JSON-RPC no válida: %s' % e)
    if 'error' in resp:
        raise ErrorKodi(str(resp['error'].get('message', resp['error'])))
    return resp.get('result', {})


PROPIEDADES = (['version', 'enabled', 'path', 'name'], ['version', 'enabled', 'name'])


def _ficha(a):
    ruta = a.get('path') or ''
    if not ruta and a.get('addonid'):
        candidata = os.path.join(const.DIR_ADDONS, a['addonid'])
        if os.path.isdir(candidata):
            ruta = candidata + os.sep
    return {'version': a.get('version', ''), 'enabled': bool(a.get('enabled', True)), 'path': ruta,
            'type': a.get('type', ''), 'name': a.get('name', '')}


def instalados():
    res = None
    for props in PROPIEDADES:
        try:
            res = jsonrpc('Addons.GetAddons', {'installed': True, 'properties': props})
            break
        except ErrorKodi as e:
            log('No se pudo leer la lista de addons: %s' % e, xbmc.LOGWARNING)
    if res is None:
        return {}
    return {a.get('addonid'): _ficha(a) for a in res.get('addons', [])}


def detalles(addon_id):
    for props in PROPIEDADES:
        try:
            res = jsonrpc('Addons.GetAddonDetails', {'addonid': addon_id, 'properties': props})
        except ErrorKodi:
            continue
        a = res.get('addon')
        if a:
            a.setdefault('addonid', addon_id)
            return _ficha(a)
    return None


def esta_instalado(addon_id):
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id))


def habilitar(addon_id, estado=True):
    try:
        jsonrpc('Addons.SetAddonEnabled', {'addonid': addon_id, 'enabled': bool(estado)})
        return True
    except ErrorKodi as e:
        log('SetAddonEnabled(%s) falló: %s' % (addon_id, e), xbmc.LOGWARNING)
        return False


def es_de_usuario(info):
    ruta = os.path.normcase(os.path.abspath(info.get('path') or ''))
    base = os.path.normcase(os.path.abspath(const.DIR_ADDONS))
    return bool(ruta) and (ruta + os.sep).startswith(base + os.sep)


def es_ejecutable(info):
    return (info.get('type') or '') in TIPOS_EJECUTABLES


def es_skin(info):
    return (info.get('type') or '') == TIPO_SKIN


def abrir(addon_id):
    xbmc.executebuiltin('RunAddon(%s)' % addon_id)


def ajustes_addon(addon_id):
    xbmc.executebuiltin('Addon.OpenSettings(%s)' % addon_id)


def usar_skin(addon_id):
    try:
        jsonrpc('Settings.SetSettingValue', {'setting': 'lookandfeel.skin', 'value': addon_id})
        return True
    except ErrorKodi as e:
        log('Cambiar skin falló: %s' % e, xbmc.LOGWARNING)
        return False


def actualizar_locales():
    xbmc.executebuiltin('UpdateLocalAddons', True)


def actualizar_repositorios():
    xbmc.executebuiltin('UpdateAddonRepos')


def instalar_desde_repos(addon_id):
    xbmc.executebuiltin('InstallAddon(%s)' % addon_id, True)


def esperar(condicion, timeout, cancelado=None, paso=250):
    monitor = xbmc.Monitor()
    transcurrido = 0
    while transcurrido < timeout * 1000:
        if condicion():
            return True
        if monitor.abortRequested() or (cancelado and cancelado()):
            return False
        xbmc.sleep(paso)
        transcurrido += paso
    return condicion()


def notificar(titulo, mensaje, icono=xbmcgui.NOTIFICATION_INFO, ms=4000):
    xbmcgui.Dialog().notification(titulo, mensaje, icono, ms)
