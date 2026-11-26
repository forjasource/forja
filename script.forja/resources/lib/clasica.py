import xbmc
import xbmcgui

from . import const, copias, gestion
from .app import CAT_PACKS, CAT_TODOS
from .util import T

D = xbmcgui.Dialog


def ejecutar(app):
    app.cargar()
    app.comprobar_repos()
    while True:
        ops = [('explorar', T('cl_explorar', n=len(app.entradas))), ('buscar', T('cl_buscar'))]
        if app.lista.packs:
            ops.append(('packs', T('cl_packs', n=len(app.lista.packs))))
        ops.append(('instalados', T('cl_instalados')))
        if app.actualizables():
            ops.append(('act_todo', T('a_actualizar_todo', n=len(app.actualizables()))))
        ops += [('lote', T('cl_lote')),
                ('lista', T('cl_lista', nombre=app.nombre_lista)), ('gestionar', T('gestionar_listas')),
                ('copias', T('cl_copias')), ('actualizar', T('cl_actualizar')), ('ajustes', T('cl_ajustes'))]
        i = D().select('%s - %s' % (const.NOMBRE, app.nombre_lista), [t for _, t in ops])
        if i < 0:
            return
        clave = ops[i][0]
        if clave == 'explorar':
            app.busqueda = ''
            _explorar(app)
        elif clave == 'buscar':
            txt = D().input(T('buscar_titulo'), defaultt=app.busqueda, type=xbmcgui.INPUT_ALPHANUM).strip()
            if txt:
                app.busqueda, app.categoria = txt, CAT_TODOS
                _listar(app)
                app.busqueda = ''
        elif clave == 'packs':
            _packs(app)
        elif clave == 'instalados':
            app.categoria, app.busqueda = '__instalados__', ''
            _listar(app)
            app.categoria = CAT_TODOS
        elif clave == 'act_todo':
            app.actualizar_todo()
            app.refrescar_instalados()
        elif clave == 'lote':
            _lote(app)
        elif clave == 'lista':
            if gestion.elegir_lista(app):
                app.cargar()
        elif clave == 'gestionar':
            if gestion.gestionar_listas(app):
                app.cargar()
        elif clave == 'copias':
            copias.gestionar(app)
            app.refrescar_instalados()
        elif clave == 'actualizar':
            app.actualizar_listas()
        elif clave == 'ajustes':
            const.ADDON.openSettings()
            app.cargar()


def _explorar(app):
    if not app.top_vigente():
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
        try:
            app.actualizar_top()
        finally:
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    while True:
        cats = app.categorias()
        items = []
        for c in cats:
            li = xbmcgui.ListItem(c['nombre'], T('n_addons', n=c['total']))
            li.setArt({'icon': c['icono'], 'thumb': c['icono']})
            items.append(li)
        i = D().select(T('cl_categorias'), items, useDetails=True)
        if i < 0:
            return
        app.categoria = cats[i]['id']
        if app.categoria == CAT_PACKS:
            _packs(app)
        else:
            _listar(app)


def _listar(app):
    pos = 0
    while True:
        ents = app.entradas_visibles()
        if not ents:
            D().ok(const.NOMBRE, app.aviso_vacio() if not app.busqueda else T('sin_resultados'))
            return
        items = []
        for e in ents:
            est, info = app.estado(e)
            li = xbmcgui.ListItem(app.nombre_visible(e), app.texto_estado(est) + (' - v' + info['version'] if info else ''))
            ic = app.icono(e)
            li.setArt({'icon': ic, 'thumb': ic})
            items.append(li)
        i = D().select('%s - %s' % (app.etiqueta_filtro(), T('n_addons', n=len(ents))), items,
                       preselect=pos, useDetails=True)
        if i < 0:
            return
        pos = i
        app.menu_contextual(ents[i])


def _packs(app):
    while True:
        packs = app.packs_visibles()
        items = []
        for p in packs:
            li = xbmcgui.ListItem(p['nombre'], T('pack_desc', n=len(p['addons'])))
            li.setArt({'icon': p['icono'], 'thumb': p['icono']})
            items.append(li)
        i = D().select(T('c_packs'), items, useDetails=True)
        if i < 0:
            return
        p = packs[i]
        D().textviewer(p['nombre'], p['descripcion'] + '\n\n' + '\n'.join(
            '- %s' % e.nombre for e in app.entradas_de_pack(p)))
        app.instalar_pack(p)


def _lote(app):
    app.categoria = CAT_TODOS
    ents = [e for e in app.entradas if app.estado(e)[0] in ('no_instalado', 'actualizable')]
    ents.sort(key=lambda e: e.nombre.lower())
    if not ents:
        D().ok(const.NOMBRE, T('nada_que_instalar'))
        return
    sel = D().multiselect(T('lote_titulo'), ['%s  [%s]' % (e.nombre, app.lista.nombre_categoria(e.categoria))
                                            for e in ents])
    if sel:
        app.instalar_varios([ents[i] for i in sel])
