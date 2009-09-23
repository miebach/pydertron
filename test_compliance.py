# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Pydertron.
#
# The Initial Developer of the Original Code is Mozilla.
# Portions created by the Initial Developer are Copyright (C) 2007
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Atul Varma <atul@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

"""
    CommonJS SecurableModule standard compliance tests for Pydertron.
"""

import os
import sys

import pydermonkey
from pydertron import JsSandbox, jsexposed
from pydertron import LocalFileSystem, HttpFileSystem

def run_test(name, fs):
    sandbox = JsSandbox(fs)
    stats = {'pass': 0, 'fail': 0, 'info': 0}

    @jsexposed(name='print')
    def jsprint(message, label):
        stats[label] += 1
        print "%s %s" % (message, label)

    sandbox.set_globals(
        sys = sandbox.new_object(**{'print': jsprint}),
        environment = sandbox.new_object()
        )

    retval = sandbox.run_script("require('program')")
    sandbox.finish()
    print

    if retval != 0:
        stats['fail'] += 1
    return stats

if __name__ == '__main__':
    base_libpath = os.path.join("interoperablejs-read-only",
                                "compliance")

    if len(sys.argv) == 2 and sys.argv[1] == '--with-http':
        with_http = True
    else:
        with_http = False

    if not os.path.exists(base_libpath) and not with_http:
        print "Please run the following command and then re-run "
        print "this script:"
        print
        print ("svn checkout "
               "http://interoperablejs.googlecode.com/svn/trunk/ "
               "interoperablejs-read-only")
        print
        print "Alternatively, run this script with the '--with-http' "
        print "option to run the tests over http."
        sys.exit(1)

    BASE_URL = "http://interoperablejs.googlecode.com/svn/trunk/compliance/"

    if with_http:
        names = ['absolute', 'cyclic', 'determinism', 'exactExports',
                 'hasOwnProperty', 'method', 'missing', 'monkeys',
                 'nested', 'reflexive', 'relative', 'transitive']
        dirs = [("%s%s/"% (BASE_URL, name), name)
                for name in names]
        fsfactory = HttpFileSystem
    else:
        dirs = [(os.path.join(base_libpath, name), name)
                for name in os.listdir(base_libpath)
                if name not in ['.svn', 'ORACLE']]
        fsfactory = LocalFileSystem

    totals = {'pass': 0, 'fail': 0}

    for libpath, name in dirs:
        fs = fsfactory(libpath)
        stats = run_test(name, fs)
        totals['pass'] += stats['pass']
        totals['fail'] += stats['fail']

    print "passed: %(pass)d  failed: %(fail)d" % totals

    import gc
    gc.collect()
    if pydermonkey.get_debug_info()['runtime_count']:
        sys.stderr.write("WARNING: JS runtime was not destroyed.\n")

    sys.exit(totals['fail'])
