import xbmc
import xbmcgui

import time

from . import const, red, repos, sistema, versiones
from .catalogo import ICONO_DEFECTO, Lista
from .descripciones import Descripciones
from .instalador import Instalador, Progreso
from .listas import GestorListas
from .util import T, ajuste, dominio, log, sin_acentos, version_kodi, version_mayor

MAX_DEPS_VISIBLES = 8
CAT_TODOS, CAT_INSTALADOS, CAT_ACTUALIZAR, CAT_PACKS = '__todos__', '__instalados__', '__actualizar__', '__packs__'


class App:
    def __init__(self):
        self.gestor = GestorListas()
        self.lista = Lista()
        self.instalados = {}
        self.categoria = CAT_TODOS
        self.busqueda = ''
        self.version_repo = {}
        self.sin_https = set()
        self._repos_vistos = {}
        self.desc = Descripciones()

    def cargar(self):
        try:
            self.lista = self.gestor.lista_activa()
        except Exception as e:
            log('Error cargando la lista activa: %r' % e, xbmc.LOGERROR)
            xbmcgui.Dialog().ok(const.NOMBRE, T('err_lista_danada', detalle=str(e)[:150]))
            self.gestor.activar(const.ID_DEFECTO)
            self.lista = self.gestor.lista_activa()
        self.refrescar_instalados()
        if self.categoria not in (CAT_TODOS, CAT_INSTALADOS, CAT_ACTUALIZAR, CAT_PACKS) and \
                self.categoria not in {c['id'] for c in self.lista.categorias}:
            self.categoria = CAT_TODOS

    def refrescar_instalados(self):
        self.instalados = sistema.instalados()

    @property
    def entradas(self):
        return self.lista.entradas

    def aviso_vacio(self):
        if not self.lista.entradas and not self.busqueda:
            return T('lista_sin_addons')
        return T('ui_vacio')

    @property
    def lista_editable(self):
        lid = self.gestor.id_activa
        if lid == const.ID_TODAS:
            return False
        m = self.gestor.estado['listas'].get(lid, {})
        return not m.get('solo_lectura')

    @property
    def nombre_lista(self):
        return T('todas_las_listas') if self.gestor.id_activa == const.ID_TODAS else self.lista.nombre

    def estado(self, e):
        info = self.instalados.get(e.id)
        if not info:
            return 'no_instalado', None
        if not info['enabled']:
            return 'desactivado', info
        objetivo = self.version_objetivo(e)
        if objetivo and version_mayor(objetivo, info.get('version', '')):
            return 'actualizable', info
        return 'instalado', info

    def version_objetivo(self, e):
        detectada = self.desc.version_cache(e)
        if e.tipo == 'zip':
            return versiones.version_conocida(e, detectada)
        return self.version_repo.get(e.id) or detectada or versiones.cache_remota(e) or e.version

    def comprobar_repos(self, forzar=False, solo=None):
        cambios = False
        ahora = time.time()
        for e in self.entradas:
            if solo is not None and e.id != solo:
                continue
            if e.tipo == 'zip':
                if e.addon_xml and e.id in self.instalados:
                    antes = versiones.version_conocida(e)
                    versiones.remota(e, forzar=forzar)
                    cambios = cambios or versiones.version_conocida(e) != antes
                continue
            if e.tipo != 'kodi' or e.id not in self.instalados:
                continue
            rid = (e.repositorio or {}).get('id')
            if not rid or rid not in self.instalados:
                continue
            visto = self._repos_vistos.get(rid)
            if visto is None or forzar or ahora - visto[0] > 1800:
                try:
                    visto = (ahora, repos.versiones(rid), bool(repos.indices_inseguros(rid)))
                except Exception as exc:
                    log('Versiones de %s: %r' % (rid, exc))
                    visto = (ahora, {}, False)
                self._repos_vistos[rid] = visto
            if visto[2]:
                self.sin_https.add(e.id)
            else:
                self.sin_https.discard(e.id)
            nueva = visto[1].get(e.id)
            if nueva and self.version_repo.get(e.id) != nueva:
                self.version_repo[e.id] = nueva
                cambios = True
        return cambios

    def actualizables(self):
        return [e for e in self.entradas if self.estado(e)[0] == 'actualizable']

    def accion_principal(self, e):
        est, info = self.estado(e)
        if est == 'no_instalado':
            return 'instalar', T('a_instalar')
        if est == 'actualizable':
            return 'actualizar', T('a_actualizar')
        if est == 'desactivado':
            return 'activar', T('a_activar')
        if sistema.es_skin(info):
            return 'usar_skin', T('a_usar_skin')
        if sistema.es_ejecutable(info):
            return 'abrir', T('a_abrir')
        return 'ajustes', T('a_ajustes')

    def texto_estado(self, est):
        return {'no_instalado': T('e_no_instalado'), 'instalado': T('e_instalado'),
                'actualizable': T('e_actualizable'), 'desactivado': T('e_desactivado')}[est]

    def icono(self, e):
        if e.icono:
            return e.icono
        info = self.instalados.get(e.id)
        if info and info.get('path'):
            return info['path'].rstrip('/\\') + '/icon.png'
        if e.tipo == 'kodi':
            rama = const.RAMAS_KODI.get(version_kodi(), 'omega')
            return 'https://mirrors.kodi.tv/addons/%s/%s/icon.png' % (rama, e.id)
        return self.lista.icono_categoria(e.categoria)

    def icono_respaldo(self, e):
        return self.lista.icono_categoria(e.categoria) or ICONO_DEFECTO

    def origen_texto(self, e, corto=False):
        if e.tipo == 'zip':
            return T('origen_zip_corto') if corto else T('origen_zip', dominio=dominio(e.zip))
        return T('origen_kodi')

    def categorias(self):
        ents = self.entradas
        n_inst = sum(1 for e in ents if e.id in self.instalados)
        n_act = sum(1 for e in ents if self.estado(e)[0] == 'actualizable')
        out = [{'id': CAT_TODOS, 'nombre': T('c_todos'), 'total': len(ents), 'icono': 'DefaultAddonsSearch.png'}]
        n_packs = len(self.lista.packs)
        if n_packs:
            out.append({'id': CAT_PACKS, 'nombre': T('c_packs'), 'total': n_packs,
                        'icono': 'DefaultAddonsInstalled.png'})
        out.append({'id': CAT_INSTALADOS, 'nombre': T('c_instalados'), 'total': n_inst,
                    'icono': 'DefaultAddonsInstalled.png'})
        if n_act:
            out.append({'id': CAT_ACTUALIZAR, 'nombre': T('c_actualizaciones'), 'total': n_act,
                        'icono': 'DefaultAddonsUpdates.png'})
        cuenta = {}
        for e in ents:
            cuenta[e.categoria] = cuenta.get(e.categoria, 0) + 1
        for c in self.lista.categorias:
            if cuenta.get(c['id']):
                out.append({'id': c['id'], 'nombre': c['nombre'], 'total': cuenta[c['id']],
                            'icono': c.get('icono') or ICONO_DEFECTO})
        return out

    def etiqueta_filtro(self):
        if self.busqueda:
            return T('filtro_busqueda', texto=self.busqueda)
        for c in self.categorias():
            if c['id'] == self.categoria:
                return c['nombre']
        return T('c_todos')

    def entradas_visibles(self):
        ents = self.entradas
        if self.categoria == CAT_INSTALADOS:
            ents = [e for e in ents if e.id in self.instalados]
        elif self.categoria == CAT_ACTUALIZAR:
            ents = [e for e in ents if self.estado(e)[0] == 'actualizable']
        elif self.categoria not in (CAT_TODOS, CAT_PACKS):
            ents = [e for e in ents if e.categoria == self.categoria]
        if self.busqueda:
            ents = self.lista.buscar(self.busqueda, ents)
        return sorted(ents, key=lambda e: sin_acentos(e.nombre))

    def packs_visibles(self):
        packs = list(self.lista.packs)
        if self.busqueda:
            fichas = sin_acentos(self.busqueda).split()
            packs = [p for p in packs
                     if all(t in sin_acentos(p['nombre'] + ' ' + p['descripcion']) for t in fichas)]
        return packs

    def entradas_de_pack(self, pack):
        return [e for e in (self.lista.por_id(i) for i in pack['addons']) if e is not None]

    def _confirmar(self, e):
        confirmar = ajuste('confirmar_instalacion', True)
        deps, http = self._analizar(e, con_deps=confirmar)
        if not confirmar and not http:
            return True
        lineas = [T('conf_origen', origen=self.origen_texto(e)),
                  T('conf_lista', lista=e.lista_nombre or self.lista.nombre)]
        ver = self.version_objetivo(e)
        if ver:
            lineas.insert(0, T('conf_version', version=ver))
        if e.tipo == 'zip':
            lineas.append(self._texto_huella(e))
            if (e.lista_id or self.lista.id) != const.ID_DEFECTO:
                lineas.append(T('conf_aviso_externa'))
        etiqueta = T('a_instalar')
        if deps:
            lineas += ['', T('conf_deps', n=len(deps))]
            lineas += ['- %s' % n for _, n in deps[:MAX_DEPS_VISIBLES]]
            if len(deps) > MAX_DEPS_VISIBLES:
                lineas.append(T('y_n_mas', n=len(deps) - MAX_DEPS_VISIBLES))
            etiqueta = T('a_instalar_todo')
        if http:
            lineas += ['', T('conf_http', dominios=', '.join(http))]
            etiqueta = T('a_instalar_igualmente')
        return xbmcgui.Dialog().yesno(T('conf_titulo', nombre=e.nombre), '\n'.join(lineas),
                                      nolabel=T('cancelar'), yeslabel=etiqueta)

    def _texto_huella(self, e, consultar=True):
        if e.sha256:
            return T('conf_sha_si')
        if not consultar and e.zip and red.normalizar_url(e.zip) not in red._HUELLAS:
            return ''
        try:
            tipo, _ = red.huella_remota(versiones.url_zip(e)) if e.zip else (None, '')
        except Exception:
            tipo = None
        return {'sha256': T('conf_sha_remoto'), 'md5': T('conf_md5_remoto')}.get(tipo, T('conf_sha_no'))

    def _fuentes_http(self, e, consultar=True):
        urls = []
        if e.tipo == 'zip':
            urls.append(e.zip or '')
        rep = e.repositorio or {}
        if rep.get('zip') and rep.get('id') not in self.instalados:
            urls.append(rep['zip'])
        if consultar and e.tipo == 'kodi':
            try:
                urls += [t[0] for t in self.desc.urls_indices(e)]
            except Exception as exc:
                log('No se pudieron comprobar los índices de %s: %r' % (e.id, exc))
        return sorted({dominio(u) for u in urls if u.lower().startswith('http://')})

    def _analizar(self, e, con_deps=True):
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
        try:
            http = self._fuentes_http(e)
            if e.tipo == 'zip':
                self._texto_huella(e)
            deps = []
            if con_deps:
                try:
                    deps = self.desc.dependencias_pendientes(e, self.lista, self.instalados)
                except Exception as exc:
                    log('No se pudieron calcular las dependencias de %s: %r' % (e.id, exc))
            return deps, http
        finally:
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')

    def instalar(self, e, preguntar=True):
        if preguntar and not self._confirmar(e):
            return False
        inst = Instalador(self.lista)
        res = inst.instalar(e, actualizar=self.estado(e)[0] in ('actualizable', 'instalado'))
        self.refrescar_instalados()
        if res.ok:
            self.gestor.registrar_deps(e.id, inst.nuevas_deps)
        if res.cancelado:
            sistema.notificar(const.NOMBRE, T('cancelado'), xbmcgui.NOTIFICATION_WARNING)
            return False
        if res.ok:
            sistema.notificar(e.nombre, res.mensaje, ms=5000)
            return True
        xbmcgui.Dialog().ok(T('error_instalar', nombre=e.nombre), res.mensaje)
        return False

    def instalar_varios(self, entradas, titulo=None):
        pendientes = [e for e in entradas if self.estado(e)[0] in ('no_instalado', 'actualizable')]
        if not pendientes:
            xbmcgui.Dialog().ok(const.NOMBRE, T('nada_que_instalar'))
            return False
        nombres = '\n'.join('- %s' % e.nombre for e in pendientes[:14])
        if len(pendientes) > 14:
            nombres += '\n' + T('y_n_mas', n=len(pendientes) - 14)
        externos = [e for e in pendientes if e.tipo == 'zip' and (e.lista_id or self.lista.id) != const.ID_DEFECTO]
        msg = T('lote_conf', n=len(pendientes), nombres=nombres)
        if externos:
            msg += '\n\n' + T('lote_externos', n=len(externos))
        http = sorted({d for e in pendientes for d in self._fuentes_http(e, consultar=False)})
        if http:
            msg += '\n\n' + T('conf_http', dominios=', '.join(http))
        if not xbmcgui.Dialog().yesno(titulo or T('lote_titulo'), msg, nolabel=T('cancelar'),
                                      yeslabel=T('a_instalar')):
            return False
        prog = Progreso(titulo or T('lote_titulo'), modal=True)
        inst = Instalador(self.lista)
        ok, mal = [], []
        try:
            n = len(pendientes)
            for i, e in enumerate(pendientes):
                if prog.cancelado():
                    break
                prog.prefijo = '[%d/%d] %s: ' % (i + 1, n, e.nombre)
                inst.nuevas_deps = []
                res = inst.instalar(e, progreso=prog, tramo=(100.0 * i / n, 100.0 * (i + 1) / n),
                                    actualizar=self.estado(e)[0] == 'actualizable')
                self.refrescar_instalados()
                if res.ok:
                    self.gestor.registrar_deps(e.id, inst.nuevas_deps)
                if res.cancelado:
                    break
                (ok if res.ok else mal).append((e, res))
        finally:
            prog.cerrar()
        informe = [T('lote_resumen', ok=len(ok), mal=len(mal))]
        informe += ['OK: %s' % e.nombre for e, _ in ok]
        informe += ['Error: %s: %s' % (e.nombre, r.mensaje) for e, r in mal]
        xbmcgui.Dialog().textviewer(T('lote_titulo'), '\n'.join(informe))
        return bool(ok)

    def dependencias_desinstalables(self, addon_id):
        registradas = [d for d in self.gestor.deps_registradas(addon_id)
                       if d in self.instalados and sistema.es_de_usuario(self.instalados[d])]
        if not registradas:
            return []
        cand = set(registradas)
        excluidos = {addon_id} | cand
        req = {}
        for aid, info in self.instalados.items():
            if info.get('path'):
                req[aid] = {d for d, _ in Instalador._leer_requeridas(info['path'])}
        en_uso = set()
        for aid, r in req.items():
            if aid not in excluidos:
                en_uso |= r & cand
        crecio = True
        while crecio:
            crecio = False
            for c in list(en_uso):
                for d in req.get(c, set()) & cand:
                    if d not in en_uso:
                        en_uso.add(d)
                        crecio = True
        return [d for d in registradas if d not in en_uso]

    def _nombre_dep(self, did):
        ent = self.lista.por_id(did)
        return ent.nombre if ent else ((self.instalados.get(did) or {}).get('name') or did)

    def desinstalar(self, e):
        info = self.instalados.get(e.id)
        if not info:
            return False
        if not sistema.es_de_usuario(info):
            xbmcgui.Dialog().ok(e.nombre, T('err_addon_sistema'))
            return False
        D = xbmcgui.Dialog()
        if not D.yesno(T('desinst_titulo', nombre=e.nombre), T('desinst_conf'),
                       nolabel=T('cancelar'), yeslabel=T('a_desinstalar')):
            return False
        copia = D.yesno(e.nombre, T('desinst_copia'), nolabel=T('no'), yeslabel=T('si'))
        borrar = D.yesno(e.nombre, T('desinst_datos'), nolabel=T('no'), yeslabel=T('si'))
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
        try:
            deps = self.dependencias_desinstalables(e.id)
        except Exception as exc:
            log('No se pudieron calcular las dependencias de %s: %r' % (e.id, exc))
            deps = []
        finally:
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        quitar = []
        if deps:
            lista = '\n'.join('- %s' % self._nombre_dep(d) for d in deps[:MAX_DEPS_VISIBLES])
            if len(deps) > MAX_DEPS_VISIBLES:
                lista += '\n' + T('y_n_mas', n=len(deps) - MAX_DEPS_VISIBLES)
            if D.yesno(e.nombre, T('desinst_deps', n=len(deps), lista=lista), nolabel=T('no'), yeslabel=T('si')):
                quitar = deps
        inst = Instalador(self.lista)
        res = inst.desinstalar(e.id, borrar_datos=borrar, copia=copia)
        quitadas = 0
        if res.ok:
            for d in quitar:
                if inst.desinstalar(d, borrar_datos=False, copia=False).ok:
                    quitadas += 1
            if quitar and quitadas == len(quitar):
                self.gestor.olvidar_deps(e.id)
        self.refrescar_instalados()
        if res.ok:
            sistema.notificar(e.nombre, T('desinstalado_deps', n=quitadas) if quitadas else res.mensaje)
        else:
            D.ok(e.nombre, res.mensaje)
        return res.ok

    def ejecutar(self, e, clave):
        if clave in ('instalar', 'actualizar', 'reinstalar'):
            return self.instalar(e)
        if clave == 'activar':
            sistema.habilitar(e.id, True)
            self.refrescar_instalados()
            sistema.notificar(e.nombre, T('activado'))
            return True
        if clave == 'desactivar':
            sistema.habilitar(e.id, False)
            self.refrescar_instalados()
            sistema.notificar(e.nombre, T('desactivado'))
            return True
        if clave == 'abrir':
            sistema.abrir(e.id)
            return False
        if clave == 'ajustes':
            sistema.ajustes_addon(e.id)
            return False
        if clave == 'usar_skin':
            if xbmcgui.Dialog().yesno(e.nombre, T('skin_conf'), nolabel=T('cancelar'), yeslabel=T('si')):
                sistema.usar_skin(e.id)
            return False
        if clave == 'buscar_act':
            return self.buscar_actualizacion(e)
        if clave == 'desinstalar':
            return self.desinstalar(e)
        if clave == 'info':
            self.mostrar_info(e)
            return False
        if clave == 'quitar_lista':
            if xbmcgui.Dialog().yesno(e.nombre, T('quitar_conf', lista=self.lista.nombre), nolabel=T('cancelar'),
                                      yeslabel=T('si')):
                self.gestor.quitar_entradas(self.gestor.id_activa, [e.id])
                self.cargar()
                return True
            return False
        return False

    def buscar_actualizacion(self, e):
        sistema.notificar(e.nombre, T('buscando_act'))
        sistema.actualizar_repositorios()
        self.comprobar_repos(forzar=True, solo=e.id)
        if self.estado(e)[0] == 'actualizable':
            return self.instalar(e, preguntar=False)
        sistema.notificar(e.nombre, T('sin_novedades', nombre=e.nombre))
        return False

    def actualizar_todo(self):
        pendientes = self.actualizables()
        if not pendientes:
            xbmcgui.Dialog().ok(const.NOMBRE, T('act_todo_ninguna'))
            return False
        return self.instalar_varios(pendientes, titulo=T('act_todo_titulo'))

    def menu_acciones(self, e):
        est, info = self.estado(e)
        ops = [self.accion_principal(e)]
        if est != 'no_instalado':
            if ops[0][0] != 'ajustes':
                ops.append(('ajustes', T('a_ajustes')))
            if e.tipo == 'zip':
                ops.append(('reinstalar', T('a_reinstalar')))
            else:
                ops.append(('buscar_act', T('a_buscar_act')))
            ops.append(('desactivar', T('a_desactivar')) if info['enabled'] else ('activar', T('a_activar')))
            if sistema.es_de_usuario(info):
                ops.append(('desinstalar', T('a_desinstalar')))
        ops.append(('info', T('a_info')))
        if self.lista_editable:
            ops.append(('quitar_lista', T('a_quitar_lista')))
        vistos, out = set(), []
        for c, t in ops:
            if c not in vistos:
                vistos.add(c)
                out.append((c, t))
        return out

    def menu_contextual(self, e):
        ops = self.menu_acciones(e)
        i = xbmcgui.Dialog().contextmenu([t for _, t in ops])
        if i < 0:
            return False
        return self.ejecutar(e, ops[i][0])

    def mostrar_info(self, e, descripcion=None):
        est, info = self.estado(e)
        l = [T('i_id', id=e.id), T('i_estado', estado=self.texto_estado(est))]
        if info:
            l.append(T('i_version_inst', version=info.get('version', '?')))
        ver = self.version_objetivo(e)
        if ver:
            l.append(T('i_version_cat', version=ver))
        if e.autor:
            l.append(T('i_autor', autor=e.autor))
        l.append(T('i_categoria', categoria=self.lista.nombre_categoria(e.categoria)))
        l.append(T('i_origen', origen=self.origen_texto(e)))
        if e.tipo == 'zip':
            l.append(T('i_zip', url=e.zip))
            huella = self._texto_huella(e, consultar=False)
            if huella:
                l.append(huella)
        if e.repositorio:
            l.append(T('i_repo', id=e.repositorio.get('id')))
        if e.id in self.sin_https:
            l.append(T('aviso_http'))
        if e.etiquetas:
            l.append(T('i_etiquetas', etiquetas=', '.join(e.etiquetas)))
        if e.web:
            l.append(T('i_web', web=e.web))
        l.append(T('i_lista', lista=e.lista_nombre or self.lista.nombre))
        descripcion = descripcion or e.descripcion
        if descripcion:
            l += ['', descripcion]
        xbmcgui.Dialog().textviewer(e.nombre, '\n'.join(l))

    def instalar_pack(self, pack):
        return self.instalar_varios(self.entradas_de_pack(pack), titulo=pack['nombre'])

    def actualizar_listas(self, silencioso=False):
        hechas, errores = self.gestor.actualizar_todas()
        self.cargar()
        if silencioso:
            return hechas, errores
        if errores:
            xbmcgui.Dialog().ok(T('act_listas_titulo'), T('act_listas_errores', n=hechas) + '\n' +
                                '\n'.join('- %s: %s' % x for x in errores[:5]))
        else:
            sistema.notificar(const.NOMBRE, T('act_listas_ok', n=hechas))
        return hechas, errores
