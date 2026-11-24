import sys

import xbmc
import xbmcgui

from resources.lib import const
from resources.lib.util import T, ajuste, log, log_error


def abrir():
    from resources.lib import autoact, clasica, moderna
    from resources.lib.app import App

    if autoact.comprobar_inicio():
        return

    app = App()
    from resources.lib import aviso
    if not aviso.pedir_aceptacion(app):
        return
    if ajuste('modo_ui', 0) == 0:
        if moderna.ejecutar(app):
            return
        xbmcgui.Dialog().notification(const.NOMBRE, 'Interfaz clásica activada (la moderna no se pudo abrir).',
                                      xbmcgui.NOTIFICATION_WARNING, 5000)
    clasica.ejecutar(app)


def accion(nombre):
    from resources.lib.app import App
    app = App()
    if nombre == 'actualizar_listas':
        app.actualizar_listas()
    elif nombre == 'actualizar_forja':
        from resources.lib import autoact
        autoact.comprobar_manual()
    elif nombre == 'copias':
        from resources.lib import copias
        copias.gestionar(app)
    elif nombre == 'limpiar_cache':
        app.gestor.limpiar()
        xbmcgui.Dialog().notification(const.NOMBRE, 'Archivos temporales borrados.', xbmcgui.NOTIFICATION_INFO, 3000)
    elif nombre == 'restaurar_defecto':
        if xbmcgui.Dialog().yesno(T('l_restaurar'), T('restaurar_conf'), nolabel=T('cancelar'), yeslabel=T('si')):
            app.gestor.restaurar_defecto()
            xbmcgui.Dialog().notification(const.NOMBRE, 'Lista por defecto restaurada.', xbmcgui.NOTIFICATION_INFO, 3000)
    else:
        log('Acción desconocida: %s' % nombre, xbmc.LOGWARNING)


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        if args and args[0] != 'abrir':
            accion(args[0])
        else:
            abrir()
    except Exception as e:
        import traceback
        log_error(traceback.format_exc())
        xbmcgui.Dialog().ok(const.NOMBRE, T('err_inesperado', detalle=str(e)[:150]))
