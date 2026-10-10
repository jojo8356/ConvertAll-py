#!/usr/bin/env python3
"""
****************************************************************************
 convertall.py, the main program file

 ConvertAll, a units conversion program
 Copyright (C) 2020, Douglas W. Bell

 This is free software; you can redistribute it and/or modify it under the
 terms of the GNU General Public License, either Version 2 or any later
 version.  This program is distributed in the hope that it will be useful,
 but WITTHOUT ANY WARRANTY.  See the included LICENSE file for details.
*****************************************************************************
"""

__progname__ = 'ConvertAll'
__version__ = '0.8.1'
__author__ = 'Doug Bell'

dataFilePath = None    # modified by install script if required
helpFilePath = None    # modified by install script if required
iconPath = None        # modified by install script if required
translationPath = 'translations'
lang = ''

import sys
import os.path
import locale
import getopt
import signal
import builtins
from PyQt5.QtCore import (QCoreApplication, QLibraryInfo, QLocale, QTranslator)

def loadTranslator(fileName, app):
    """Load and install qt translator, return True if sucessful.
    """
    translator = QTranslator(app)
    modPath = os.path.abspath(sys.path[0])
    if modPath.endswith('.zip'):  # for py2exe
        modPath = os.path.dirname(modPath)
    path = os.path.join(modPath, translationPath)
    result = translator.load(fileName, path)
    if not result:
        path = os.path.join(modPath, '..', translationPath)
        result = translator.load(fileName, path)
    if not result:
        path = os.path.join(modPath, '..', 'i18n', translationPath)
        result = translator.load(fileName, path)
    if not result and fileName.startswith('qt_'):
        # Modern Qt5 splits qt_<language> into dependent catalogues. Widgets
        # need qtbase; load it from the pinned Qt runtime rather than shipping
        # an unusable forwarding catalogue with absent dependencies.
        result = translator.load('qtbase_' + fileName[3:],
                                 QLibraryInfo.location(QLibraryInfo.TranslationsPath))
    if result:
        QCoreApplication.installTranslator(translator)
        return True
    else:
        print('Warning: translation file "{0}" could not be loaded'.
              format(fileName))
        return False

def setupTranslator(app):
    """Set language, load translators and setup translator function.
    """
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        pass
    global lang
    lang = os.environ.get('LC_MESSAGES', '')
    if not lang:
        lang = os.environ.get('LANG', '')
        if not lang:
            # Unlike deprecated locale.getdefaultlocale(), QLocale gives a
            # catalogue-compatible language name on Windows as well as Unix.
            lang = QLocale.system().name()
    # Locale suffixes are not part of catalogue names (C.UTF-8 is English).
    lang = lang.split('.', 1)[0].split('@', 1)[0].replace('-', '_')
    numTranslators = 0
    if lang and lang not in ('C', 'POSIX') and lang[:2] != 'en':
        numTranslators += loadTranslator('qt_{0}'.format(lang), app)
        numTranslators += loadTranslator('convertall_{0}'.format(lang), app)

    def translate(text, comment=''):
        """Translation function that sets context to calling module's
           filename.
        """
        try:
            frame = sys._getframe(1)
            fileName = frame.f_code.co_filename
        finally:
            del frame
        context = os.path.basename(os.path.splitext(fileName)[0])
        return QCoreApplication.translate(context, text, comment)

    def markNoTranslate(text, comment=''):
        return text

    if numTranslators:
        builtins._ = translate
    else:
        builtins._ = markNoTranslate


def main():
    guiSmokeTest = '--gui-smoke-test' in sys.argv[1:]
    if len(sys.argv) > 1:
        try:
            opts, args = getopt.gnu_getopt(sys.argv[1:], 'd:fhiqsetv',
                                           ['decimals=', 'fixed-decimals',
                                            'help', 'interactive', 'quiet',
                                            'sci-notation', 'eng-notation',
                                            'test', 'test-all', 'version', 'gui-smoke-test'])
        except getopt.GetoptError:
            # Match complete Qt options, not three-character prefixes:
            # otherwise -nonsense/-bad would accidentally launch the GUI.
            qtOptions = {'background', 'bg', 'button', 'btn', 'cmap', 'display',
                         'dograb', 'foreground', 'fg', 'font', 'fn', 'geometry',
                         'graphicssystem', 'im', 'inputstyle', 'name', 'ncols',
                         'nograb', 'reverse', 'session', 'style', 'stylesheet',
                         'sync', 'title', 'visual', 'widgetcount', 'platform',
                         'platformpluginpath', 'platformtheme', 'plugin',
                         'qmljsdebugger', 'qwindowgeometry', 'qwindowicon',
                         'qwindowtitle', 'testability', 'iconic'}
            if sys.argv[1].lstrip('-').split('=', 1)[0] not in qtOptions:
                app = QCoreApplication(sys.argv)
                setupTranslator(app)
                import cmdline
                cmdline.printUsage()
                return 2
        else:
            if any(opt == '--gui-smoke-test' for opt, value in opts):
                if args or len(opts) != 1:
                    print('--gui-smoke-test does not accept conversion arguments', file=sys.stderr)
                    return 2
                guiSmokeTest = True
            else:
                app = QCoreApplication(sys.argv)
                setupTranslator(app)
                import cmdline
                import unitdata
                unitdata.lang = lang
                unitdata.dataFilePath = dataFilePath
                try:
                    return cmdline.parseArgs(opts, args)
                except EOFError:
                    return 0
                except KeyboardInterrupt:
                    return 130
                except (unitdata.UnitDataError, ArithmeticError, ValueError) as error:
                    print('Error - {0}'.format(error), file=sys.stderr)
                    return 1
    from PyQt5.QtWidgets import QApplication
    userStyle = '-style' in ' '.join(sys.argv)
    app = QApplication(sys.argv)
    setupTranslator(app)  # must be before importing any convertall modules
    import convertdlg
    unitdata = sys.modules['unitdata']
    unitdata.lang = lang
    unitdata.dataFilePath = dataFilePath
    if not userStyle:
        QApplication.setStyle('fusion')
    win = convertdlg.ConvertDlg(showStartupTip=not guiSmokeTest)
    win.show()
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if guiSmokeTest:
        from PyQt5.QtCore import QTimer
        def checkWindow():
            try:
                if not win.isVisible() or win.unitListView.topLevelItemCount() < 1:
                    raise RuntimeError('Unit list was not displayed')
                win.fromGroup.update('in')
                win.toGroup.update('cm')
                win.fromNumEdit.unitUpdate()
                win.toNumEdit.unitUpdate()
                if abs(float(win.toNumEdit.text()) - 2.54) > 1e-9:
                    raise RuntimeError('GUI conversion failed')
                if win.icons['convertall_med'].isNull() or not win.findHelpFile():
                    raise RuntimeError('GUI resources missing')
                print('GUI smoke test passed (Qt5)')
                result = 0
            except Exception as error:
                print('GUI smoke test failed: {0}'.format(error), file=sys.stderr)
                result = 1
            win.close()
            app.exit(result)
        QTimer.singleShot(0, checkWindow)
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
