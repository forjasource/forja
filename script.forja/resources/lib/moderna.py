import contextlib
import threading
import time

import xbmc
import xbmcgui

from . import const, copias, gestion, sistema, versiones
from .app import CAT_PACKS, CAT_TODOS
from .util import T, ajuste, log

ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_CONTEXT_MENU, ACTION_SHOW_INFO = 10, 92, 117, 11

ID_CATEGORIAS, ID_PANEL = 100, 200
ID_B_LISTA, ID_B_BUSCAR, ID_B_GESTIONAR, ID_B_ACTUALIZAR, ID_B_AJUSTES, ID_B_LOTE = 301, 302, 303, 304, 305, 306
ID_B_ACT_TODO, ID_B_COPIAS = 307, 308
ID_A_PRINCIPAL, ID_A_MAS, ID_A_INFO = 400, 401, 402

TEXTOS_UI = ('copias', 'buscar', 'gestionar', 'actualizar', 'ajustes', 'lote', 'mas', 'info', 'categorias', 'vacio',
             'cargando', 'autor', 'origen', 'categoria', 'lista_btn', 'version')
INTERVALO_VIGILANCIA = 4.0
ESPERA_DESCRIPCION = 0.35
IDS_LATERAL = (ID_A_PRINCIPAL, ID_A_MAS, ID_A_INFO)


class VentanaForja(xbmcgui.WindowXML):
    app = None

    def __init__(self, *args, **kwargs):
        try:
            xbmcgui.WindowXML.__init__(self)
        except TypeError:
            xbmcgui.WindowXML.__init__(self, *args)
        self._iniciada = False
        self._cerrando = False
        self._cats = []
        self._visibles = []
        self._modo_packs = False
        self._lock = threading.RLock()
        self._ocupado = False
        self._ultimo_fin = 0.0
        self._firma = None
        self._tarjetas = {}
        self._desc_pos = -1

    def onInit(self):
        if self._iniciada:
            return
        self._iniciada = True
        self.setProperty('Forja.Cargando', '1')
        for k in TEXTOS_UI:
            self.setProperty('Forja.T.' + k, T('ui_' + k))
        self.setProperty('Forja.Version', 'v' + const.VERSION)
        try:
            self.app.cargar()
            self._refrescar_todo()
        finally:
            self.setProperty('Forja.Cargando', '')
        self.setFocusId(ID_PANEL if self._visibles else ID_CATEGORIAS)
        threading.Thread(target=self._vigilar, daemon=True).start()
        threading.Thread(target=self._vigilar_instalados, daemon=True).start()
        threading.Thread(target=self._vigilar_descripcion, daemon=True).start()
        threading.Thread(target=self._comprobar_repos, daemon=True).start()
        threading.Thread(target=self._actualizar_top, daemon=True).start()
        if ajuste('actualizar_al_abrir', True):
            threading.Thread(target=self._actualizar_segundo_plano, daemon=True).start()

    def onClose(self):
        self._cerrando = True

    def _refrescar_todo(self, mantener=False):
        with self._lock:
            app = self.app
            self.setProperty('Forja.Lista', app.nombre_lista)
            self.setProperty('Forja.Subtitulo', T('subtitulo', lista=app.nombre_lista,
                                                  n=len(app.entradas)))
            self._rellenar_categorias()
            self._rellenar_items(mantener)
            n_act = len(app.actualizables())
            self.setProperty('Forja.HayAct', '1' if n_act else '')
            self.setProperty('Forja.T.actualizar_todo', T('a_actualizar_todo', n=n_act))

    def _rellenar_categorias(self):
        ctl = self.getControl(ID_CATEGORIAS)
        self._cats = self.app.categorias()
        items = []
        for c in self._cats:
            li = xbmcgui.ListItem(c['nombre'], str(c['total']))
            li.setArt({'icon': c['icono'], 'thumb': c['icono']})
            if c['id'] == self.app.categoria and not self.app.busqueda:
                li.setProperty('sel', '1')
            items.append(li)
        pos = 0
        for i, c in enumerate(self._cats):
            if c['id'] == self.app.categoria:
                pos = i
        ctl.reset()
        ctl.addItems(items)
        ctl.selectItem(pos)
        self._cat_aplicada = pos

    def _rellenar_items(self, mantener=False):
        app = self.app
        panel = self.getControl(ID_PANEL)
        pos = panel.getSelectedPosition() if mantener else 0
        self._modo_packs = app.categoria == CAT_PACKS and not app.busqueda
        items = []
        self._tarjetas = {}
        self._desc_pos = -1
        if self._modo_packs:
            self._visibles = app.packs_visibles()
            for p in self._visibles:
                li = xbmcgui.ListItem(p['nombre'], T('pack_desc', n=len(p['addons'])))
                li.setArt({'thumb': p['icono'], 'icon': p['icono']})
                li.setProperty('tipo_item', 'pack')
                li.setProperty('estado', 'pack')
                li.setProperty('estado_texto', T('e_pack'))
                li.setProperty('version_texto', '-')
                li.setProperty('accion', T('a_instalar_pack'))
                li.setProperty('descripcion', p['descripcion'] + '\n\n' + '\n'.join(
                    '- %s' % e.nombre for e in app.entradas_de_pack(p)))
                li.setProperty('autor', '')
                li.setProperty('origen', app.nombre_lista)
                li.setProperty('categoria', T('c_packs'))
                items.append(li)
        else:
            self._visibles = app.entradas_visibles()
            for e in self._visibles:
                est, info = app.estado(e)
                sub = self._sub_version(e, est, info)
                li = xbmcgui.ListItem(app.nombre_visible(e), sub)
                li.setArt({'thumb': app.icono(e), 'icon': app.icono_respaldo(e)})
                li.setProperty('tipo_item', 'addon')
                li.setProperty('estado', est)
                li.setProperty('estado_texto', app.texto_estado(est))
                li.setProperty('version_texto', sub or '-')
                li.setProperty('accion', app.accion_principal(e)[1])
                li.setProperty('descripcion', self._texto_descripcion(e, info))
                self._tarjetas[e.id] = li
                li.setProperty('autor', e.autor or '-')
                li.setProperty('origen', app.origen_texto(e, corto=True))
                li.setProperty('categoria', app.lista.nombre_categoria(e.categoria))
                items.append(li)
        panel.reset()
        panel.addItems(items)
        if items:
            panel.selectItem(min(pos, len(items) - 1))
        self.setProperty('Forja.Vacio', '' if items else '1')
        self.setProperty('Forja.T.vacio', '' if items else app.aviso_vacio())
        self.setProperty('Forja.Filtro', app.etiqueta_filtro())
        self.setProperty('Forja.Total', T('n_addons', n=len(items)) if not self._modo_packs
                         else T('n_packs', n=len(items)))
        self.setProperty('Forja.Buscando', '1' if app.busqueda else '')

    def _sub_version(self, e, est, info):
        if info:
            sub = 'v' + info.get('version', '')
            if est == 'actualizable':
                sub += ' → v' + self.app.version_objetivo(e)
            return sub
        ver = self.app.version_objetivo(e)
        return ('v' + ver) if ver else ''

    def _texto_descripcion(self, e, info=None, texto=None):
        base = texto or self.app.desc.rapido(e, info) or e.descripcion or T('sin_descripcion')
        nota = self.app.nota_top(e)
        if nota:
            base = nota + '\n\n' + base
        return (T('aviso_http') + '\n\n' if e.id in self.app.sin_https else '') + base

    def _vigilar_descripcion(self):
        mon = xbmc.Monitor()
        candidato, desde = -1, 0.0
        while not self._cerrando and not mon.abortRequested():
            if mon.waitForAbort(0.15):
                break
            try:
                if self._modo_packs or self.getFocusId() != ID_PANEL:
                    candidato = -1
                    continue
                pos = self.getControl(ID_PANEL).getSelectedPosition()
            except Exception:
                break
            if pos == self._desc_pos or not (0 <= pos < len(self._visibles)):
                candidato = -1
                continue
            if pos != candidato:
                candidato, desde = pos, time.time()
                continue
            if time.time() - desde < ESPERA_DESCRIPCION:
                continue
            candidato = -1
            self._desc_pos = pos
            try:
                self._cargar_descripcion(self._visibles[pos])
            except Exception as e:
                log('Descripción del addon.xml: %r' % e)

    def _cargar_descripcion(self, e):
        info = self.app.instalados.get(e.id)
        texto = self.app.desc.resolver(e, info)
        if e.addon_xml or versiones.tiene_plantilla(e):
            versiones.remota(e)
        if self._cerrando:
            return
        with self._lock:
            li = self._tarjetas.get(e.id)
            if li is None:
                return
            if texto:
                li.setProperty('descripcion', self._texto_descripcion(e, info, texto))
            est, info = self.app.estado(e)
            sub = self._sub_version(e, est, info)
            li.setLabel2(sub)
            li.setProperty('version_texto', sub or '-')
            li.setProperty('estado', est)
            li.setProperty('estado_texto', self.app.texto_estado(est))
            li.setProperty('accion', self.app.accion_principal(e)[1])

    def _actual(self):
        pos = self.getControl(ID_PANEL).getSelectedPosition()
        return self._visibles[pos] if 0 <= pos < len(self._visibles) else None

    def _vigilar(self):
        mon = xbmc.Monitor()
        candidato, desde = None, 0.0
        while not self._cerrando and not mon.abortRequested():
            if mon.waitForAbort(0.12):
                break
            try:
                if self.getFocusId() != ID_CATEGORIAS:
                    candidato = None
                    continue
                pos = self.getControl(ID_CATEGORIAS).getSelectedPosition()
            except Exception:
                break
            if pos == self._cat_aplicada or not (0 <= pos < len(self._cats)):
                candidato = None
                continue
            if pos != candidato:
                candidato, desde = pos, time.time()
            elif time.time() - desde > 0.22:
                self._aplicar_categoria(pos)
                candidato = None

    def _aplicar_categoria(self, pos):
        with self._lock:
            self._cat_aplicada = pos
            self.app.categoria = self._cats[pos]['id']
            if self.app.busqueda:
                self.app.busqueda = ''
                self._rellenar_categorias()
                self._cat_aplicada = pos
                self.getControl(ID_CATEGORIAS).selectItem(pos)
            self._marcar_categoria(pos)
            self._rellenar_items()

    def _actualizar_top(self):
        try:
            if self.app.actualizar_top() and not self._cerrando:
                with self._lock:
                    self._refrescar_todo(mantener=True)
        except Exception as e:
            log('Top de Mundo Kodi: %r' % e)

    def _comprobar_repos(self):
        try:
            if self.app.comprobar_repos() and not self._cerrando:
                with self._lock:
                    self._refrescar_todo(mantener=True)
        except Exception as e:
            log('Comprobación de repositorios: %r' % e)

    def _vigilar_instalados(self):
        mon = xbmc.Monitor()
        self._firma = self._firma_actual()
        while not self._cerrando and not mon.abortRequested():
            if mon.waitForAbort(INTERVALO_VIGILANCIA):
                break
            if self._ocupado or self._cerrando:
                continue
            try:
                nueva = self._firma_actual()
                if nueva is None or nueva == self._firma:
                    continue
                self._firma = nueva
                with self._lock:
                    if self._ocupado or self._cerrando:
                        continue
                    self.app.refrescar_instalados()
                    self._refrescar_todo(mantener=True)
            except Exception as e:
                log('Vigilancia de addons instalados: %r' % e)

    def _firma_actual(self):
        try:
            return {k: (v['version'], v['enabled']) for k, v in sistema.instalados().items()}
        except Exception:
            return None

    def _actualizar_segundo_plano(self):
        try:
            pend = self.app.gestor.pendientes(6)
            if not pend:
                return
            cambios = 0
            for lid in pend:
                try:
                    if self.app.gestor.actualizar(lid) == 'actualizada':
                        cambios += 1
                except Exception as e:
                    log('Actualización silenciosa de %s: %r' % (lid, e))
            if cambios and not self._cerrando:
                self.app.gestor._cache.clear()
                self.app.cargar()
                self._refrescar_todo(mantener=True)
                sistema.notificar(const.NOMBRE, T('act_listas_ok', n=cambios), ms=3000)
        except Exception as e:
            log('Actualización en segundo plano: %r' % e)

    def onAction(self, action):
        aid = action.getId()
        try:
            if aid in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
                if self.getFocusId() in IDS_LATERAL:
                    self.setFocusId(ID_PANEL)
                    return
                if self.app.busqueda:
                    self.app.busqueda = ''
                    self._refrescar_todo()
                    return
                self.close()
                return
            if aid == ACTION_CONTEXT_MENU and self.getFocusId() == ID_PANEL:
                self._ocupado = True
                try:
                    self._menu_tarjeta()
                finally:
                    self._firma = self._firma_actual()
                    self._ocupado = False
                return
            if aid == ACTION_SHOW_INFO and self.getFocusId() == ID_PANEL:
                self._info()
                return
        except Exception as e:
            self._error(e)
            return
        xbmcgui.WindowXML.onAction(self, action)

    def onClick(self, cid):
        self._ocupado = True
        try:
            self._click(cid)
        finally:
            self._firma = self._firma_actual()
            self._ocupado = False

    def _click(self, cid):
        try:
            if cid == ID_PANEL:
                self.setFocusId(ID_A_PRINCIPAL)
            elif cid == ID_A_PRINCIPAL:
                if time.time() - self._ultimo_fin > 0.6:
                    self._principal()
            elif cid == ID_CATEGORIAS:
                self.setFocusId(ID_PANEL)
            elif cid == ID_A_MAS:
                self._menu_tarjeta()
            elif cid == ID_A_INFO:
                self._info()
            elif cid == ID_B_LISTA:
                if gestion.elegir_lista(self.app):
                    self._recargar()
            elif cid == ID_B_BUSCAR:
                self._buscar()
            elif cid == ID_B_GESTIONAR:
                if gestion.gestionar_listas(self.app):
                    self._recargar()
            elif cid == ID_B_ACTUALIZAR:
                self.setProperty('Forja.Cargando', '1')
                try:
                    self.app.actualizar_listas()
                    self.app.gestor._cache.clear()
                    self._recargar()
                finally:
                    self.setProperty('Forja.Cargando', '')
            elif cid == ID_B_AJUSTES:
                const.ADDON.openSettings()
                self._recargar()
            elif cid == ID_B_LOTE:
                self._lote()
            elif cid == ID_B_COPIAS:
                if copias.gestionar(self.app):
                    self._tras_cambio()
            elif cid == ID_B_ACT_TODO:
                with self._trabajando():
                    if self.app.actualizar_todo():
                        self._tras_cambio()
        except Exception as e:
            self._error(e)

    @contextlib.contextmanager
    def _trabajando(self):
        self.setProperty('Forja.Ocupado', '1')
        try:
            yield
        finally:
            self.setProperty('Forja.Ocupado', '')
            self._ultimo_fin = time.time()

    def _marcar_categoria(self, pos):
        ctl = self.getControl(ID_CATEGORIAS)
        for i in range(len(self._cats)):
            ctl.getListItem(i).setProperty('sel', '1' if i == pos and not self.app.busqueda else '')

    def _error(self, e):
        log('Error en la interfaz: %r' % e, xbmc.LOGERROR)
        xbmcgui.Dialog().ok(const.NOMBRE, T('err_inesperado', detalle=str(e)[:120]))

    def _recargar(self):
        self.app.gestor._cache.clear()
        self.app.cargar()
        self._refrescar_todo()

    def _tras_cambio(self):
        self.app.refrescar_instalados()
        self._refrescar_todo(mantener=True)
        threading.Thread(target=self._comprobar_repos, daemon=True).start()

    def _principal(self):
        item = self._actual()
        if item is None:
            return
        with self._trabajando():
            if self._modo_packs:
                self.app.instalar_pack(item)
                self._tras_cambio()
                return
            clave, _ = self.app.accion_principal(item)
            if self.app.ejecutar(item, clave):
                self._tras_cambio()

    def _menu_tarjeta(self):
        item = self._actual()
        if item is None:
            return
        if self._modo_packs:
            xbmcgui.Dialog().textviewer(item['nombre'], item['descripcion'] + '\n\n' + '\n'.join(
                '- %s' % e.nombre for e in self.app.entradas_de_pack(item)))
            return
        with self._trabajando():
            if self.app.menu_contextual(item):
                self._tras_cambio()

    def _info(self):
        item = self._actual()
        if item is not None and not self._modo_packs:
            self.app.mostrar_info(item, self.app.desc.rapido(item, self.app.instalados.get(item.id)))

    def _buscar(self):
        txt = xbmcgui.Dialog().input(T('buscar_titulo'), defaultt=self.app.busqueda,
                                     type=xbmcgui.INPUT_ALPHANUM).strip()
        if txt:
            self.app.busqueda = txt
            self.app.categoria = CAT_TODOS
            self._refrescar_todo()
            self.setFocusId(ID_PANEL)

    def _lote(self):
        app = self.app
        ents = sorted([e for e in app.entradas if app.estado(e)[0] in ('no_instalado', 'actualizable')],
                      key=lambda e: e.nombre.lower())
        if not ents:
            xbmcgui.Dialog().ok(const.NOMBRE, T('nada_que_instalar'))
            return
        sel = xbmcgui.Dialog().multiselect(T('lote_titulo'), [
            '%s  [%s]' % (e.nombre, app.lista.nombre_categoria(e.categoria)) for e in ents])
        if sel:
            with self._trabajando():
                if app.instalar_varios([ents[i] for i in sel]):
                    self._tras_cambio()


def ejecutar(app):
    try:
        v = VentanaForja('forja-main.xml', const.RUTA, 'Default', '1080i')
        v.app = app
        v.doModal()
        v._cerrando = True
        del v
        return True
    except Exception as e:
        log('No se pudo abrir la interfaz moderna: %r' % e, xbmc.LOGERROR)
        return False
