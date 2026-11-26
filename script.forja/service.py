import time

import xbmc

from resources.lib.util import ajuste, log

ESPERA_INICIAL = 90
COMPROBAR_CADA = 3600


def main():
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(ESPERA_INICIAL):
        return
    ultima_forja, forja_actualizada = 0.0, False
    while not monitor.abortRequested():
        if not forja_actualizada and time.time() - ultima_forja > max(1, ajuste('horas_comprobar_forja', 6)) * 3600:
            ultima_forja = time.time()
            try:
                if ajuste('autoactualizar_forja', True):
                    from resources.lib import autoact
                    forja_actualizada = bool(autoact.actualizar_en_silencio())
            except Exception as e:
                log('Servicio: autoactualización de Forja: %r' % e)
        try:
            if ajuste('actualizar_en_segundo_plano', True):
                from resources.lib.listas import GestorListas
                gestor = GestorListas()
                for lid in gestor.pendientes(max(1, ajuste('horas_actualizar_listas', 24))):
                    try:
                        gestor.actualizar(lid)
                    except Exception as e:
                        log('Servicio: lista %s no actualizada (%s)' % (lid, e))
        except Exception as e:
            log('Servicio: %r' % e)
        try:
            if ajuste('mostrar_top_mundokodi', True):
                from resources.lib import tops
                tops.actualizar(tops.cargar_cache())
        except Exception as e:
            log('Servicio: top de Mundo Kodi: %r' % e)
        if monitor.waitForAbort(COMPROBAR_CADA):
            break


if __name__ == '__main__':
    main()
