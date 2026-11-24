import os
import re
import shutil
import stat
import time
import xml.etree.ElementTree as ET
import zipfile

import xbmc
import xbmcgui

from . import const, red, sistema, versiones
from .util import T, ajuste, asegurar_dir, borrar_arbol, log, log_error, tam_legible, version_mayor


class Resultado:
    def __init__(self, ok, mensaje='', version='', dependencias=None, fallidas=None, cancelado=False):
        self.ok = ok
        self.mensaje = mensaje
        self.version = version
        self.dependencias = dependencias or []
        self.fallidas = fallidas or []
        self.cancelado = cancelado


class Progreso:

    def __init__(self, titulo, modal=True):
        self.modal = modal
        self.titulo = titulo
        self.dlg = xbmcgui.DialogProgress() if modal else xbmcgui.DialogProgressBG()
        self.dlg.create(titulo, '')
        self.abierto = True
        self.prefijo = ''

    def actualizar(self, pct, mensaje=''):
        if not self.abierto:
            return
        pct = max(0, min(100, int(pct)))
        self.dlg.update(pct, self.prefijo + mensaje)

    def cancelado(self):
        return bool(self.modal and self.abierto and self.dlg.iscanceled())

    def cerrar(self):
        if self.abierto:
            self.dlg.close()
            self.abierto = False


class Instalador:
    def __init__(self, catalogo=None):
        self.catalogo = catalogo
        self._profundidad = 0
        self.nuevas_deps = []

    def instalar(self, entrada, progreso=None, tramo=(0, 100), actualizar=False):
        propio = progreso is None
        if propio:
            progreso = Progreso(T('instalando_titulo', nombre=entrada.nombre), modal=(entrada.tipo == 'zip'))
        try:
            res = self._instalar(entrada, progreso, tramo, actualizar)
        except red.Cancelado:
            res = Resultado(False, T('cancelado'), cancelado=True)
        except (red.ErrorRed, sistema.ErrorKodi, ErrorInstalacion) as e:
            res = Resultado(False, str(e))
        except Exception as e:
            log_error('Fallo inesperado instalando %s: %r' % (entrada.id, e))
            res = Resultado(False, T('err_inesperado', detalle=str(e)[:120]))
        finally:
            if propio:
                progreso.cerrar()
        return res

    def desinstalar(self, addon_id, borrar_datos=False, copia=None):
        info = sistema.instalados().get(addon_id)
        if not info:
            return Resultado(False, T('err_no_instalado'))
        if not sistema.es_de_usuario(info):
            return Resultado(False, T('err_addon_sistema'))
        sistema.habilitar(addon_id, False)
        xbmc.sleep(400)
        try:
            if copia is False:
                borrar_arbol(info['path'])
            else:
                self._guardar_copia(addon_id, info['path'], info.get('version', ''), mover=True,
                                    forzar=bool(copia))
        except OSError as e:
            return Resultado(False, T('err_borrar', detalle=str(e)))
        if borrar_datos:
            datos = os.path.join(os.path.dirname(const.PERFIL), addon_id)
            borrar_arbol(datos)
        sistema.actualizar_locales()
        sistema.esperar(lambda: sistema.detalles(addon_id) is None, 15)
        if sistema.detalles(addon_id) is not None:
            return Resultado(False, T('err_desinst_sigue'))
        return Resultado(True, T('desinstalado'))

    def restaurar_copia(self, addon_id, ruta_copia):
        if not os.path.isfile(os.path.join(ruta_copia, 'addon.xml')):
            return Resultado(False, T('err_copia_invalida'))
        previo = sistema.instalados().get(addon_id)
        if previo and not sistema.es_de_usuario(previo):
            return Resultado(False, T('err_addon_sistema'))
        tmp = os.path.join(const.DIR_TEMP, 'rest-%s-%d' % (addon_id, int(time.time())))
        borrar_arbol(tmp)
        asegurar_dir(const.DIR_TEMP)
        try:
            shutil.copytree(ruta_copia, tmp)
            final = os.path.join(const.DIR_ADDONS, addon_id)
            if os.path.isdir(final):
                sistema.habilitar(addon_id, False)
                xbmc.sleep(400)
                self._guardar_copia(addon_id, final, (previo or {}).get('version', ''), mover=True, forzar=True,
                                    podar=False)
            shutil.move(tmp, final)
        except (OSError, shutil.Error) as e:
            return Resultado(False, T('err_restaurar', detalle=str(e)[:120]))
        finally:
            borrar_arbol(tmp)
        sistema.actualizar_locales()
        sistema.esperar(lambda: sistema.detalles(addon_id) is not None, 20)
        sistema.habilitar(addon_id, True)
        det = sistema.detalles(addon_id) or {}
        return Resultado(True, T('copias_restaurada'), version=det.get('version', ''))

    def _pct(self, tramo, frac):
        a, b = tramo
        return a + (b - a) * max(0.0, min(1.0, frac))

    def _instalar(self, e, prog, tramo, actualizar=False):
        if prog.cancelado():
            raise red.Cancelado()
        if e.repositorio:
            self._asegurar_repositorio(e.repositorio, prog, tramo)
        if e.tipo == 'zip':
            return self._instalar_zip(e, prog, tramo)
        return self._instalar_desde_kodi(e.id, e.nombre, prog, tramo, actualizar)

    def _asegurar_repositorio(self, rep, prog, tramo):
        previo = sistema.detalles(rep['id'])
        if previo:
            if not previo['enabled']:
                sistema.habilitar(rep['id'], True)
            return
        if not rep.get('zip'):
            raise ErrorInstalacion(T('err_repo_sin_zip', id=rep['id']))
        prog.actualizar(self._pct(tramo, 0.02), T('prog_repo', id=rep['id']))
        sub = Entrada_Minima(rep['id'], rep['id'], rep['zip'], rep.get('sha256', ''), rep.get('addon_xml', ''))
        r = self._instalar_zip(sub, prog, (tramo[0], self._pct(tramo, 0.3)), es_repositorio=True)
        if not r.ok:
            raise ErrorInstalacion(r.mensaje)
        sistema.habilitar(rep['id'], True)
        sistema.actualizar_repositorios()
        xbmc.sleep(4000)

    def _pedir_a_kodi(self, addon_id, prog, version_previa=None, intentos=3):
        for n in range(intentos):
            if prog.cancelado():
                raise red.Cancelado()
            if n:
                sistema.actualizar_repositorios()
                xbmc.sleep(3000 * n)
            sistema.instalar_desde_repos(addon_id)

            def listo():
                d = sistema.detalles(addon_id)
                return bool(d) and (version_previa is None or version_mayor(d['version'], version_previa))

            if sistema.esperar(listo, 20 if n < intentos - 1 else 45, prog.cancelado):
                return True
        return False

    def _instalar_desde_kodi(self, addon_id, nombre, prog, tramo, actualizar=False):
        sub = (self._pct(tramo, 0.8), self._pct(tramo, 0.98))
        previo = sistema.detalles(addon_id)
        if previo and not actualizar:
            prog.actualizar(self._pct(tramo, 0.3), T('prog_buscando_act'))
            sistema.actualizar_repositorios()
            if not previo['enabled']:
                sistema.habilitar(addon_id, True)
            self._dependencias(previo['path'], prog, tramo)
            return Resultado(True, T('ya_instalado_repos'), version=previo['version'])
        if previo:
            prog.actualizar(self._pct(tramo, 0.1), T('prog_buscando_act'))
            sistema.actualizar_repositorios()
            xbmc.sleep(3000)
            prog.actualizar(self._pct(tramo, 0.3), T('prog_desde_kodi', nombre=nombre))
            self._pedir_a_kodi(addon_id, prog, version_previa=previo['version'], intentos=2)
            nuevo = sistema.detalles(addon_id) or previo
            if version_mayor(nuevo['version'], previo['version']):
                self._dependencias(nuevo['path'], prog, tramo)
                prog.actualizar(self._pct(tramo, 1.0), T('prog_listo'))
                return Resultado(True, T('actualizado_ok', nombre=nombre, version=nuevo['version']),
                                 version=nuevo['version'])
            return Resultado(True, T('sin_novedades', nombre=nombre), version=previo['version'])
        prog.actualizar(self._pct(tramo, 0.1), T('prog_desde_kodi', nombre=nombre))
        if not self._pedir_a_kodi(addon_id, prog):
            if prog.cancelado():
                raise red.Cancelado()
            return Resultado(False, T('err_no_en_repos', nombre=nombre))
        sistema.habilitar(addon_id, True)
        info = sistema.detalles(addon_id) or {}
        deps_ok, deps_mal = self._dependencias(info.get('path', ''), prog, (tramo[0], self._pct(tramo, 1.0)))
        prog.actualizar(self._pct(tramo, 1.0), T('prog_listo'))
        msg = T('instalado_ok', nombre=nombre)
        if deps_mal:
            msg += ' ' + T('aviso_deps', deps=', '.join(deps_mal))
        return Resultado(True, msg, version=info.get('version', ''), dependencias=deps_ok, fallidas=deps_mal)

    def _instalar_zip(self, e, prog, tramo, es_repositorio=False):
        url = red.validar_url(red.normalizar_url(versiones.url_zip(e)))
        sha, md5, origen_huella = e.sha256 or '', '', 'lista' if e.sha256 else ''
        if not sha:
            prog.actualizar(self._pct(tramo, 0.03), T('prog_buscando_huella'))
            tipo, valor = red.huella_remota(url)
            if tipo == 'sha256':
                sha, origen_huella = valor, 'remoto'
            elif tipo == 'md5':
                md5, origen_huella = valor, 'remoto'
        if ajuste('exigir_sha256', False) and not sha and not es_repositorio:
            raise ErrorInstalacion(T('err_sin_sha256'))
        asegurar_dir(const.DIR_TEMP)
        destino = os.path.join(const.DIR_TEMP, '%s-%d.zip' % (e.id, int(time.time())))
        try:
            def avance(hecho, total, vel):
                frac = (hecho / total) if total else 0.5
                msg = T('prog_descargando', hecho=tam_legible(hecho),
                        total=tam_legible(total) if total else '?', vel=tam_legible(vel))
                prog.actualizar(self._pct(tramo, 0.05 + 0.55 * frac), msg)

            red.descargar(url, destino, sha256=sha or None, md5=md5 or None, progreso=avance,
                          cancelado=prog.cancelado)
            prog.actualizar(self._pct(tramo, 0.62), T('prog_verificando') if (sha or md5) else T('prog_leyendo_zip'))
            carpeta, version = self._validar_zip(destino, e.id)
            prog.actualizar(self._pct(tramo, 0.72), T('prog_extrayendo'))
            ruta_final = self._desplegar(destino, e.id, carpeta, version, getattr(e, 'copia_previa', True))
            prog.actualizar(self._pct(tramo, 0.84), T('prog_registrando'))
            sistema.actualizar_locales()
            sistema.esperar(lambda: (sistema.detalles(e.id) or {}).get('version') == version, 20, prog.cancelado)
            if sistema.detalles(e.id) is None and not sistema.esta_instalado(e.id):
                sistema.actualizar_locales()
                sistema.esperar(lambda: sistema.detalles(e.id) is not None or sistema.esta_instalado(e.id), 15,
                                prog.cancelado)
                if sistema.detalles(e.id) is None and not sistema.esta_instalado(e.id):
                    raise ErrorInstalacion(T('err_no_registrado'))
            deps_ok, deps_mal = self._dependencias(ruta_final, prog, tramo)
            prog.actualizar(self._pct(tramo, 0.97), T('prog_activando'))
            for _ in range(4):
                if sistema.habilitar(e.id, True):
                    break
                xbmc.sleep(500)
            prog.actualizar(self._pct(tramo, 1.0), T('prog_listo'))
            msg = T('instalado_ok', nombre=e.nombre)
            if deps_mal:
                msg += ' ' + T('aviso_deps', deps=', '.join(deps_mal))
            return Resultado(True, msg, version=version, dependencias=deps_ok, fallidas=deps_mal)
        finally:
            for r in (destino, destino + '.part'):
                try:
                    os.remove(r)
                except OSError:
                    pass

    def _validar_zip(self, ruta_zip, addon_id):
        try:
            z = zipfile.ZipFile(ruta_zip)
        except zipfile.BadZipFile:
            raise ErrorInstalacion(T('err_zip_corrupto'))
        with z:
            total = 0
            raices = set()
            for info in z.infolist():
                nombre = info.filename.replace('\\', '/')
                partes = [p for p in nombre.split('/') if p]
                if nombre.startswith('/') or '..' in partes or (partes and re.match(r'^[A-Za-z]:', partes[0])):
                    raise ErrorInstalacion(T('err_zip_inseguro'))
                if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                    raise ErrorInstalacion(T('err_zip_inseguro'))
                if partes:
                    raices.add(partes[0])
                total += info.file_size
                if total > const.TAM_MAX_DESCOMPRIMIDO:
                    raise ErrorInstalacion(T('err_zip_enorme'))
            if len(raices) != 1:
                raise ErrorInstalacion(T('err_zip_estructura'))
            carpeta = raices.pop()
            if carpeta != addon_id:
                raise ErrorInstalacion(T('err_zip_id', esperado=addon_id, hallado=carpeta))
            try:
                raiz = ET.fromstring(z.read('%s/addon.xml' % carpeta))
            except (KeyError, ET.ParseError):
                raise ErrorInstalacion(T('err_zip_sin_addonxml'))
            if raiz.get('id') != addon_id:
                raise ErrorInstalacion(T('err_zip_id', esperado=addon_id, hallado=raiz.get('id')))
            return carpeta, raiz.get('version', '')

    def _desplegar(self, ruta_zip, addon_id, carpeta, version, copia_previa=True):
        tmp = os.path.join(const.DIR_TEMP, 'ext-%s-%d' % (addon_id, int(time.time())))
        borrar_arbol(tmp)
        asegurar_dir(tmp)
        try:
            with zipfile.ZipFile(ruta_zip) as z:
                z.extractall(tmp)
            origen = os.path.join(tmp, carpeta)
            final = os.path.join(const.DIR_ADDONS, addon_id)
            previo = sistema.instalados().get(addon_id)
            if previo and not sistema.es_de_usuario(previo):
                raise ErrorInstalacion(T('err_addon_sistema'))
            copia = None
            if os.path.isdir(final):
                if copia_previa:
                    copia = self._guardar_copia(addon_id, final, (previo or {}).get('version', ''), mover=True)
                else:
                    copia = os.path.join(tmp, 'previo')
                    shutil.move(final, copia)
            try:
                shutil.move(origen, final)
            except Exception:
                if copia and os.path.isdir(copia) and not os.path.isdir(final):
                    shutil.move(copia, final)
                raise
            return final
        finally:
            borrar_arbol(tmp)

    def _guardar_copia(self, addon_id, ruta, version, mover=False, forzar=False, podar=True):
        max_copias = ajuste('copias_seguridad', 2)
        if forzar:
            max_copias = max(max_copias, 1)
        if not os.path.isdir(ruta):
            return None
        if max_copias <= 0:
            if mover:
                borrar_arbol(ruta)
            return None
        base = asegurar_dir(os.path.join(const.DIR_COPIAS, addon_id))
        destino = os.path.join(base, '%s_%s' % (time.strftime('%Y%m%d-%H%M%S'), version or 'sv'))
        if mover:
            shutil.move(ruta, destino)
        else:
            shutil.copytree(ruta, destino)
        if podar:
            viejas = sorted(os.listdir(base))
            for v in viejas[:-max_copias]:
                borrar_arbol(os.path.join(base, v))
        return destino

    @staticmethod
    def _leer_requeridas(ruta_addon):
        try:
            raiz = ET.parse(os.path.join(ruta_addon, 'addon.xml')).getroot()
        except (OSError, ET.ParseError, TypeError):
            return []
        out = []
        for imp in raiz.findall('requires/import'):
            did = imp.get('addon')
            if not did or did.startswith(('xbmc.', 'kodi.')):
                continue
            if (imp.get('optional') or 'false').lower() == 'true':
                continue
            out.append((did, imp.get('version') or ''))
        return out

    def _resolver_dependencia(self, did, previo, prog, sub):
        entrada = self.catalogo.por_id(did) if self.catalogo else None
        if entrada is not None:
            return self._instalar(entrada, prog, sub, actualizar=bool(previo))
        if self._pedir_a_kodi(did, prog, version_previa=previo['version'] if previo else None):
            sistema.habilitar(did, True)
            det = sistema.detalles(did) or {}
            if det.get('path'):
                self._dependencias(det['path'], prog, sub)
            return Resultado(True)
        return Resultado(False)

    def _dependencias(self, ruta_addon, prog, tramo):
        ok, mal = [], []
        requeridas = self._leer_requeridas(ruta_addon) if ruta_addon else []
        if not requeridas or self._profundidad >= 4:
            return ok, mal
        self._profundidad += 1
        sub = (self._pct(tramo, 0.86), self._pct(tramo, 0.96))
        try:
            for i, (did, minima) in enumerate(requeridas):
                det = sistema.detalles(did)
                if det and not (minima and version_mayor(minima, det['version'])):
                    if not det['enabled']:
                        sistema.habilitar(did, True)
                    continue
                prog.actualizar(self._pct(tramo, 0.86 + 0.1 * (i / max(len(requeridas), 1))),
                                T('prog_dependencia', id=did))
                try:
                    r = self._resolver_dependencia(did, det, prog, sub)
                except red.Cancelado:
                    raise
                except Exception as exc:
                    log('Dependencia %s falló: %r' % (did, exc), xbmc.LOGWARNING)
                    r = Resultado(False)
                if r.ok:
                    ok.append(did)
                    if det is None and did not in self.nuevas_deps:
                        self.nuevas_deps.append(did)
                else:
                    mal.append(did)
        finally:
            self._profundidad -= 1
        return ok, mal


class Entrada_Minima:
    tipo = 'zip'
    repositorio = None
    descripcion = ''
    addon_xml = ''
    version = ''
    copia_previa = True

    def __init__(self, id_, nombre, zip_, sha256='', addon_xml=''):
        self.id, self.nombre, self.zip, self.sha256 = id_, nombre, zip_, sha256
        self.addon_xml = addon_xml


class ErrorInstalacion(Exception):
    pass
