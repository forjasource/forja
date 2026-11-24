import contextlib

import xbmc
import xbmcgui

from . import const, red, sistema
from .catalogo import ErrorCatalogo
from .util import T, log

D = xbmcgui.Dialog


@contextlib.contextmanager
def ocupado():
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        yield
    finally:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')


def _texto(titulo, defecto=''):
    return D().input(titulo, defaultt=defecto, type=xbmcgui.INPUT_ALPHANUM).strip()


def _item(label, label2='', icono='DefaultAddonsInstalled.png'):
    li = xbmcgui.ListItem(label, label2)
    li.setArt({'icon': icono, 'thumb': icono})
    return li


def _describir(app, l):
    partes = [T('n_addons', n=l['total']), app.gestor.descripcion_origen(l['id'])]
    return ', '.join(partes)


def elegir_lista(app):
    listas = app.gestor.listas()
    items, ids = [], []
    pre = 0
    for l in listas:
        if l['activa']:
            pre = len(items)
        marca = '● ' if l['activa'] else '   '
        etiqueta = marca + l['nombre'] + (' ' + T('por_defecto') if l['id'] == const.ID_DEFECTO else '')
        items.append(_item(etiqueta, _describir(app, l)))
        ids.append(l['id'])
    if len(listas) > 1:
        activa = app.gestor.id_activa == const.ID_TODAS
        if activa:
            pre = len(items)
        total = len({e.id for lid in app.gestor.estado['orden'] for e in app.gestor.cargar(lid).entradas})
        items.append(_item(('● ' if activa else '   ') + T('todas_las_listas'),
                           T('todas_desc', n=total), 'DefaultAddonsSearch.png'))
        ids.append(const.ID_TODAS)
    items.append(_item(T('gestionar_listas'), T('gestionar_desc'), 'DefaultAddonProgram.png'))
    ids.append('__gestionar__')
    i = D().select(T('elegir_lista_titulo'), items, preselect=pre, useDetails=True)
    if i < 0:
        return False
    if ids[i] == '__gestionar__':
        return gestionar_listas(app)
    if ids[i] == app.gestor.id_activa:
        return False
    app.gestor.activar(ids[i])
    return True


def gestionar_listas(app):
    cambio = False
    while True:
        listas = app.gestor.listas()
        items = []
        for l in listas:
            marca = '● ' if l['activa'] else '   '
            items.append(_item(marca + l['nombre'], _describir(app, l)))
        base = len(items)
        items += [
            _item(T('g_anadir_url'), T('g_anadir_url_d'), 'DefaultNetwork.png'),
            _item(T('g_anadir_archivo'), T('g_anadir_archivo_d'), 'DefaultFolder.png'),
            _item(T('g_importar_repo'), T('g_importar_repo_d'), 'DefaultAddonRepository.png'),
            _item(T('g_crear'), T('g_crear_d'), 'DefaultAddSource.png'),
            _item(T('g_actualizar_todas'), T('g_actualizar_todas_d'), 'DefaultAddonsUpdates.png'),
        ]
        i = D().select(T('gestionar_titulo'), items, useDetails=True)
        if i < 0:
            return cambio
        try:
            if i < base:
                cambio |= _menu_lista(app, listas[i]['id'])
            elif i == base:
                cambio |= _anadir_url(app)
            elif i == base + 1:
                cambio |= _anadir_archivo(app)
            elif i == base + 2:
                cambio |= _anadir_url(app, importar=True)
            elif i == base + 3:
                cambio |= _crear(app)
            else:
                with ocupado():
                    hechas, errores = app.gestor.actualizar_todas()
                cambio = True
                if errores:
                    D().ok(T('act_listas_titulo'), T('act_listas_errores', n=hechas) + '\n' +
                           '\n'.join('- %s: %s' % x for x in errores[:5]))
                else:
                    sistema.notificar(const.NOMBRE, T('act_listas_ok', n=hechas))
        except (red.ErrorRed, ErrorCatalogo) as e:
            D().ok(T('error'), str(e))
        except Exception as e:
            log('Gestión de listas: %r' % e, xbmc.LOGERROR)
            D().ok(T('error'), T('err_inesperado', detalle=str(e)[:120]))


def _preguntar_usar(app, lid):
    nombre = app.gestor.estado['listas'][lid]['nombre']
    if D().yesno(T('lista_anadida_titulo'), T('lista_usar_ahora', nombre=nombre),
                 nolabel=T('ahora_no'), yeslabel=T('usarla')):
        app.gestor.activar(lid)
    return True


def _resumen_avisos(app, lid):
    lista = app.gestor.cargar(lid)
    if lista.avisos:
        D().textviewer(T('avisos_titulo', nombre=lista.nombre),
                       T('avisos_cabecera', n=len(lista.avisos)) + '\n\n' +
                       '\n'.join('- %s' % a for a in lista.avisos[:40]))


def _anadir_url(app, importar=False):
    url = _texto(T('pedir_url_repo') if importar else T('pedir_url'))
    if not url:
        return False
    datadir = None
    if importar:
        sugerido = url.rsplit('/', 1)[0] + '/'
        datadir = _texto(T('pedir_datadir'), sugerido) or sugerido
    nombre = _texto(T('pedir_nombre_opcional')) or None
    with ocupado():
        lid = app.gestor.anadir_desde_url(url, nombre, datadir)
    meta = app.gestor.estado['listas'][lid]
    D().ok(T('lista_anadida_titulo'), T('lista_anadida', nombre=meta['nombre'], n=meta['total']))
    _resumen_avisos(app, lid)
    return _preguntar_usar(app, lid)


def _anadir_archivo(app):
    ruta = D().browseSingle(1, T('elegir_archivo'), 'files', '.json|.txt', False, False, '')
    if not ruta:
        return False
    nombre = _texto(T('pedir_nombre_opcional')) or None
    lid = app.gestor.anadir_desde_archivo(ruta, nombre)
    meta = app.gestor.estado['listas'][lid]
    D().ok(T('lista_anadida_titulo'), T('lista_anadida', nombre=meta['nombre'], n=meta['total']))
    _resumen_avisos(app, lid)
    return _preguntar_usar(app, lid)


def _crear(app):
    nombre = _texto(T('pedir_nombre'))
    if not nombre:
        return False
    lid = app.gestor.crear_vacia(nombre)
    if D().yesno(T('lista_creada_titulo'), T('lista_creada_anadir', nombre=nombre),
                 nolabel=T('luego'), yeslabel=T('anadir_ahora')):
        _anadir_entradas(app, lid)
    return _preguntar_usar(app, lid)


def _menu_lista(app, lid):
    cambio = False
    while True:
        if lid not in app.gestor.estado['listas']:
            return True
        m = app.gestor.estado['listas'][lid]
        ops = []
        if app.gestor.id_activa != lid:
            ops.append(('usar', T('l_usar')))
        ops.append(('info', T('l_info')))
        if app.gestor.puede_actualizarse(lid):
            ops.append(('actualizar', T('l_actualizar')))
        if not m.get('solo_lectura'):
            ops += [('anadir', T('l_anadir')), ('quitar', T('l_quitar'))]
        if lid != const.ID_DEFECTO:
            ops.append(('renombrar', T('l_renombrar')))
        ops += [('duplicar', T('l_duplicar')), ('exportar', T('l_exportar'))]
        if lid == const.ID_DEFECTO:
            ops.append(('restaurar', T('l_restaurar')))
        else:
            ops.append(('eliminar', T('l_eliminar')))
        i = D().select(m['nombre'], [t for _, t in ops])
        if i < 0:
            return cambio
        clave = ops[i][0]
        try:
            if clave == 'usar':
                app.gestor.activar(lid)
                return True
            if clave == 'info':
                _info(app, lid)
            elif clave == 'actualizar':
                with ocupado():
                    r = app.gestor.actualizar(lid, forzar=True)
                cambio = True
                sistema.notificar(m['nombre'], T('lista_actualizada') if r == 'actualizada' else T('lista_sin_cambios'))
            elif clave == 'anadir':
                cambio |= _anadir_entradas(app, lid)
            elif clave == 'quitar':
                cambio |= _quitar_entradas(app, lid)
            elif clave == 'renombrar':
                n = _texto(T('pedir_nombre'), m['nombre'])
                if n:
                    app.gestor.renombrar(lid, n)
                    cambio = True
            elif clave == 'duplicar':
                n = _texto(T('pedir_nombre'), T('copia_de', nombre=m['nombre']))
                if n:
                    nuevo = app.gestor.duplicar(lid, n)
                    cambio = True
                    _preguntar_usar(app, nuevo)
                    return True
            elif clave == 'exportar':
                carpeta = D().browseSingle(3, T('elegir_carpeta'), 'files', '', False, True, '')
                if carpeta:
                    destino = app.gestor.exportar(lid, sistema_ruta(carpeta))
                    D().ok(T('exportada_titulo'), T('exportada', ruta=destino))
            elif clave == 'restaurar':
                if D().yesno(T('l_restaurar'), T('restaurar_conf'), nolabel=T('cancelar'), yeslabel=T('si')):
                    app.gestor.restaurar_defecto()
                    cambio = True
            elif clave == 'eliminar':
                if D().yesno(T('l_eliminar'), T('eliminar_conf', nombre=m['nombre']),
                             nolabel=T('cancelar'), yeslabel=T('si')):
                    app.gestor.eliminar(lid)
                    return True
        except (red.ErrorRed, ErrorCatalogo) as e:
            D().ok(T('error'), str(e))


def sistema_ruta(ruta):
    import xbmcvfs
    return xbmcvfs.translatePath(ruta)


def _info(app, lid):
    m = app.gestor.estado['listas'][lid]
    lista = app.gestor.cargar(lid)
    o = m.get('origen', {})
    l = [T('li_nombre', nombre=m['nombre']), T('li_addons', n=len(lista.entradas)),
         T('li_categorias', n=len(lista.categorias)), T('li_packs', n=len(lista.packs))]
    if lista.autor:
        l.append(T('i_autor', autor=lista.autor))
    if lista.version:
        l.append(T('li_version', version=lista.version))
    l.append(T('li_origen', origen=app.gestor.descripcion_origen(lid)))
    if o.get('valor'):
        l.append(T('li_ruta', ruta=o['valor']))
    if m.get('actualizada'):
        l.append(T('li_actualizada', fecha=m['actualizada'].replace('T', ' ')))
    l.append(T('li_solo_lectura') if m.get('solo_lectura') else T('li_editable'))
    if lista.descripcion:
        l += ['', lista.descripcion]
    if lista.avisos:
        l += ['', T('avisos_cabecera', n=len(lista.avisos))] + ['- %s' % a for a in lista.avisos[:15]]
    D().textviewer(m['nombre'], '\n'.join(l))


def _quitar_entradas(app, lid):
    lista = app.gestor.cargar(lid)
    if not lista.entradas:
        D().ok(T('l_quitar'), T('lista_vacia'))
        return False
    ents = sorted(lista.entradas, key=lambda e: e.nombre.lower())
    sel = D().multiselect(T('l_quitar'), ['%s  (%s)' % (e.nombre, e.id) for e in ents])
    if not sel:
        return False
    app.gestor.quitar_entradas(lid, [ents[i].id for i in sel])
    sistema.notificar(const.NOMBRE, T('quitados', n=len(sel)))
    return True


def _anadir_entradas(app, lid):
    modos = [T('m_kodi'), T('m_zip'), T('m_instalados')]
    i = D().select(T('l_anadir'), modos)
    if i < 0:
        return False
    lista = app.gestor.cargar(lid)
    if i == 2:
        return _desde_instalados(app, lid)
    aid = _texto(T('pedir_id'))
    if not aid:
        return False
    nombre = _texto(T('pedir_nombre_addon'), aid) or aid
    datos = {'id': aid, 'nombre': nombre, 'tipo': 'kodi' if i == 0 else 'zip'}
    if i == 1:
        url = _texto(T('pedir_zip'))
        if not url:
            return False
        datos['zip'] = url
        sha = _texto(T('pedir_sha'))
        if sha:
            datos['sha256'] = sha
        ver = _texto(T('pedir_version'))
        if ver:
            datos['version'] = ver
    cat = _elegir_categoria(lista)
    if cat:
        datos['categoria'] = cat
    desc = _texto(T('pedir_desc'))
    if desc:
        datos['descripcion'] = desc
    app.gestor.anadir_entrada(lid, datos)
    sistema.notificar(const.NOMBRE, T('anadido', nombre=nombre))
    return True


def _elegir_categoria(lista):
    nombres = [c['nombre'] for c in lista.categorias]
    ops = nombres + [T('cat_nueva'), T('cat_sin')]
    i = D().select(T('pedir_categoria'), ops)
    if i < 0 or i == len(ops) - 1:
        return None
    if i == len(ops) - 2:
        return _texto(T('pedir_cat_nombre')) or None
    return lista.categorias[i]['id']


def _desde_instalados(app, lid):
    ins = sistema.instalados()
    cand = sorted([(a, d) for a, d in ins.items()
                   if sistema.es_de_usuario(d) and not a.startswith('script.module.')],
                  key=lambda x: (x[1].get('name') or x[0]).lower())
    if not cand:
        D().ok(T('l_anadir'), T('sin_instalados'))
        return False
    sel = D().multiselect(T('m_instalados'), ['%s  (%s)' % (d.get('name') or a, a) for a, d in cand])
    if not sel:
        return False
    for k in sel:
        a, d = cand[k]
        app.gestor.anadir_entrada(lid, {'id': a, 'nombre': d.get('name') or a, 'tipo': 'kodi',
                                        'version': d.get('version', ''), 'categoria': 'otros'})
    sistema.notificar(const.NOMBRE, T('anadidos', n=len(sel)))
    return True
