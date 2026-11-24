import os
import re
import time

import xbmc
import xbmcgui

from . import const, sistema
from .instalador import Instalador
from .util import T, borrar_arbol, log, tam_legible

D = xbmcgui.Dialog
RX_CARPETA = re.compile(r'^(\d{8})-(\d{6})_(.*)$')


def _tam(ruta):
    total = 0
    for base, _, archivos in os.walk(ruta):
        for a in archivos:
            try:
                total += os.path.getsize(os.path.join(base, a))
            except OSError:
                pass
    return total


def listar():
    out = {}
    if not os.path.isdir(const.DIR_COPIAS):
        return out
    for aid in sorted(os.listdir(const.DIR_COPIAS)):
        carpeta = os.path.join(const.DIR_COPIAS, aid)
        if not os.path.isdir(carpeta):
            continue
        filas = []
        for n in sorted(os.listdir(carpeta), reverse=True):
            ruta = os.path.join(carpeta, n)
            if not os.path.isdir(ruta):
                continue
            m = RX_CARPETA.match(n)
            fecha, ver = n, ''
            if m:
                try:
                    fecha = time.strftime('%d/%m/%Y %H:%M', time.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S'))
                except ValueError:
                    pass
                ver = '' if m.group(3) == 'sv' else m.group(3)
            filas.append({'ruta': ruta, 'fecha': fecha, 'version': ver, 'tam': _tam(ruta)})
        if filas:
            out[aid] = filas
    return out


def _nombre(app, addon_id):
    e = app.lista.por_id(addon_id) if app.lista else None
    if e is not None:
        return e.nombre
    return (app.instalados.get(addon_id) or {}).get('name') or addon_id


def _etiqueta(c):
    if c['version']:
        return T('copias_item', fecha=c['fecha'], version=c['version'], tam=tam_legible(c['tam']))
    return T('copias_item_sv', fecha=c['fecha'], tam=tam_legible(c['tam']))


def gestionar(app):
    app.refrescar_instalados()
    cambios = False
    while True:
        datos = listar()
        if not datos:
            D().ok(T('copias_titulo'), T('copias_vacio'))
            return cambios
        total = sum(c['tam'] for filas in datos.values() for c in filas)
        ids = list(datos)
        filas = [T('copias_fila', nombre=_nombre(app, a), n=len(datos[a]),
                   tam=tam_legible(sum(c['tam'] for c in datos[a]))) for a in ids]
        filas.append(T('copias_borrar_todas'))
        i = D().select(T('copias_titulo_total', tam=tam_legible(total)), filas)
        if i < 0:
            return cambios
        if i == len(ids):
            if D().yesno(T('copias_titulo'), T('copias_borrar_todas_conf', tam=tam_legible(total)),
                         nolabel=T('cancelar'), yeslabel=T('copias_borrar')):
                borrar_arbol(const.DIR_COPIAS)
            continue
        if _de_addon(app, ids[i]):
            cambios = True


def _de_addon(app, addon_id):
    cambios = False
    nombre = _nombre(app, addon_id)
    while True:
        copias = listar().get(addon_id, [])
        if not copias:
            return cambios
        filas = [_etiqueta(c) for c in copias] + [T('copias_borrar_addon')]
        i = D().select(nombre, filas)
        if i < 0:
            return cambios
        if i == len(copias):
            if D().yesno(nombre, T('copias_borrar_conf'), nolabel=T('cancelar'), yeslabel=T('copias_borrar')):
                borrar_arbol(os.path.join(const.DIR_COPIAS, addon_id))
            return cambios
        c = copias[i]
        acc = D().select(_etiqueta(c), [T('copias_restaurar'), T('copias_borrar')])
        if acc == 0:
            if D().yesno(nombre, T('copias_restaurar_conf', fecha=c['fecha'], nombre=nombre),
                         nolabel=T('cancelar'), yeslabel=T('copias_restaurar')):
                xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
                try:
                    res = Instalador(app.lista).restaurar_copia(addon_id, c['ruta'])
                finally:
                    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                app.refrescar_instalados()
                if res.ok:
                    sistema.notificar(nombre, res.mensaje, ms=4000)
                    cambios = True
                else:
                    D().ok(nombre, res.mensaje)
        elif acc == 1:
            if D().yesno(nombre, T('copias_borrar_conf'), nolabel=T('cancelar'), yeslabel=T('copias_borrar')):
                borrar_arbol(c['ruta'])
