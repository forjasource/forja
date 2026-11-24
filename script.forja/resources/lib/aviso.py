import xbmcgui

from .util import T

VERSION_AVISO = 1


def aceptado(app):
    return int(app.gestor.estado.get('aviso', 0) or 0) >= VERSION_AVISO


def pedir_aceptacion(app):
    if aceptado(app):
        return True
    if xbmcgui.Dialog().yesno(T('aviso_titulo'), T('aviso_texto'),
                              nolabel=T('aviso_salir'), yeslabel=T('aviso_aceptar')):
        app.gestor.estado['aviso'] = VERSION_AVISO
        app.gestor.guardar_estado()
        return True
    return False
