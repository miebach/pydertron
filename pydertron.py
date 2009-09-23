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
    Pydertron is a high-level wrapper for Pydermonkey that
    provides convenient, secure object wrapping between JS and Python
    space.
"""

import sys
import threading
import traceback
import weakref
import types
import atexit

import pydermonkey

class ContextWatchdogThread(threading.Thread):
    """
    Watches active JS contexts and triggers their operation callbacks
    at a regular interval.
    """

    # Default interval, in seconds, that the operation callbacks are
    # triggered at.
    DEFAULT_INTERVAL = 0.25

    def __init__(self, interval=DEFAULT_INTERVAL):
        threading.Thread.__init__(self)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._contexts = []
        self.interval = interval

    def add_context(self, cx):
        self._lock.acquire()
        try:
            self._contexts.append(weakref.ref(cx))
        finally:
            self._lock.release()

    def join(self):
        self._stop.set()
        threading.Thread.join(self)

    def run(self):
        while not self._stop.isSet():
            new_list = []
            self._lock.acquire()
            try:
                for weakcx in self._contexts:
                    cx = weakcx()
                    if cx:
                        new_list.append(weakcx)
                        cx.trigger_operation_callback()
                        del cx
                self._contexts = new_list
            finally:
                self._lock.release()
            self._stop.wait(self.interval)

# Create a global watchdog.
watchdog = ContextWatchdogThread()
watchdog.start()
atexit.register(watchdog.join)

class InternalError(BaseException):
    """
    Represents an error in a JS-wrapped Python function that wasn't
    expected to happen; because it's derived from BaseException, it
    unrolls the whole JS/Python stack so that the error can be
    reported to the outermost calling code.
    """

    def __init__(self):
        BaseException.__init__(self)
        self.exc_info = sys.exc_info()

class SafeJsObjectWrapper(object):
    """
    Securely wraps a JS object to behave like any normal Python
    object. Like JS objects, though, accessing undefined object
    results merely in pydermonkey.undefined.

    Object properties may be accessed either via attribute or
    item-based lookup.
    """

    __slots__ = ['_jsobject', '_sandbox', '_this']

    def __init__(self, sandbox, jsobject, this):
        if not isinstance(jsobject, pydermonkey.Object):
            raise TypeError("Cannot wrap '%s' object" %
                            type(jsobject).__name__)
        object.__setattr__(self, '_sandbox', sandbox)
        object.__setattr__(self, '_jsobject', jsobject)
        object.__setattr__(self, '_this', this)

    @property
    def wrapped_jsobject(self):
        return self._jsobject

    def _wrap_to_python(self, jsvalue):
        return self._sandbox.wrap_jsobject(jsvalue, self._jsobject)

    def _wrap_to_js(self, value):
        return self._sandbox.wrap_pyobject(value)

    def __eq__(self, other):
        if isinstance(other, SafeJsObjectWrapper):
            return self._jsobject == other._jsobject
        else:
            return False

    def __str__(self):
        return self.toString()

    def __unicode__(self):
        return self.toString()

    def __setitem__(self, item, value):
        self.__setattr__(item, value)

    def __setattr__(self, name, value):
        cx = self._sandbox.cx
        jsobject = self._jsobject

        cx.define_property(jsobject, name,
                           self._wrap_to_js(value))

    def __getitem__(self, item):
        return self.__getattr__(item)

    def __getattr__(self, name):
        cx = self._sandbox.cx
        jsobject = self._jsobject

        return self._wrap_to_python(cx.get_property(jsobject, name))

    def __contains__(self, item):
        cx = self._sandbox.cx
        jsobject = self._jsobject

        return cx.has_property(jsobject, item)

    def __iter__(self):
        cx = self._sandbox.cx
        jsobject = self._jsobject

        properties = cx.enumerate(jsobject)
        for property in properties:
            yield property

class SafeJsFunctionWrapper(SafeJsObjectWrapper):
    """
    Securely wraps a JS function to behave like any normal Python object.
    """

    def __init__(self, sandbox, jsfunction, this):
        if not isinstance(jsfunction, pydermonkey.Function):
            raise TypeError("Cannot wrap '%s' object" %
                            type(jsobject).__name__)
        SafeJsObjectWrapper.__init__(self, sandbox, jsfunction, this)

    def __call__(self, *args):
        cx = self._sandbox.cx
        jsobject = self._jsobject
        this = self._this

        arglist = []
        for arg in args:
            arglist.append(self._wrap_to_js(arg))

        obj = cx.call_function(this, jsobject, tuple(arglist))
        return self._wrap_to_python(obj)

def format_stack(js_stack, open=open):
    """
    Returns a formatted Python-esque stack traceback of the given
    JS stack.
    """

    STACK_LINE  ="  File \"%(filename)s\", line %(lineno)d, in %(name)s"

    lines = []
    while js_stack:
        script = js_stack['script']
        function = js_stack['function']
        if script:
            frameinfo = dict(filename = script.filename,
                             lineno = js_stack['lineno'],
                             name = '<module>')
        elif function and not function.is_python:
            frameinfo = dict(filename = function.filename,
                             lineno = js_stack['lineno'],
                             name = function.name)
        else:
            frameinfo = None
        if frameinfo:
            lines.insert(0, STACK_LINE % frameinfo)
            try:
                filelines = open(frameinfo['filename']).readlines()
                line = filelines[frameinfo['lineno'] - 1].strip()
                lines.insert(1, "    %s" % line)
            except Exception:
                pass
        js_stack = js_stack['caller']
    lines.insert(0, "Traceback (most recent call last):")
    return '\n'.join(lines)

def jsexposed(name=None, on=None):
    """
    Decorator used to expose the decorated function or method to
    untrusted JS.

    'name' is an optional alternative name for the function.

    'on' is an optional SafeJsObjectWrapper that the function can be
    automatically attached as a property to.
    """

    if callable(name):
        func = name
        func.__jsexposed__ = True
        return func

    def make_exposed(func):
        if name:
            func.__name__ = name
        func.__jsexposed__ = True
        if on:
            on[func.__name__] = func
        return func
    return make_exposed

class JsExposedObject(object):
    """
    Trivial base/mixin class for any Python classes that choose to
    expose themselves to JS code.
    """

    pass

class JsSandbox(object):
    """
    A JS runtime and associated functionality capable of securely
    loading and executing scripts.
    """

    def __init__(self, fs, watchdog=watchdog, opcb=None):
        rt = pydermonkey.Runtime()
        cx = rt.new_context()
        root_proto = cx.new_object()
        cx.init_standard_classes(root_proto)
        root = cx.new_object(None, root_proto)

        cx.set_operation_callback(self._opcb)
        cx.set_throw_hook(self._throwhook)
        watchdog.add_context(cx)

        self.fs = fs
        self.opcb = opcb
        self.rt = rt
        self.cx = cx
        self.curr_exc = None
        self.py_stack = None
        self.js_stack = None
        self.__modules = {}
        self.__py_to_js = {}
        self.__type_protos = {}
        self.__globals = {}
        self.__root_proto = root_proto
        self.root = self.wrap_jsobject(root, root)

    def set_globals(self, **globals):
        """
        Sets the global properties for the root object and all global
        scopes (e.g., SecurableModules).  This should be called before
        any scripts are executed.
        """

        self.__globals.update(globals)
        self._install_globals(self.root)

    def finish(self):
        """
        Cleans up all resources used by the sandbox, breaking any reference
        cycles created due to issue #2 in pydermonkey:

        http://code.google.com/p/pydermonkey/issues/detail?id=2
        """

        for jsobj in self.__py_to_js.values():
            self.cx.clear_object_private(jsobj)
        del self.__py_to_js
        del self.__type_protos
        del self.curr_exc
        del self.py_stack
        del self.js_stack
        del self.cx
        del self.rt

    def _opcb(self, cx):
        # Note that if a keyboard interrupt was triggered,
        # it'll get raised here automatically.
        if self.opcb:
            self.opcb()

    def _throwhook(self, cx):
        curr_exc = cx.get_pending_exception()
        if self.curr_exc != curr_exc:
            self.curr_exc = curr_exc
            self.py_stack = traceback.extract_stack()
            self.js_stack = cx.get_stack()

    def __wrap_pycallable(self, func, pyproto=None):
        if func in self.__py_to_js:
            return self.__py_to_js[func]

        if hasattr(func, '__name__'):
            name = func.__name__
        else:
            name = ""

        if pyproto:
            def wrapper(func_cx, this, args):
                try:
                    arglist = []
                    for arg in args:
                        arglist.append(self.wrap_jsobject(arg))
                    instance = func_cx.get_object_private(this)
                    if instance is None or not isinstance(instance, pyproto):
                        raise pydermonkey.error("Method type mismatch")

                    # TODO: Fill in extra required params with
                    # pymonkey.undefined?  or automatically throw an
                    # exception to calling js code?
                    return self.wrap_pyobject(func(instance, *arglist))
                except pydermonkey.error:
                    raise
                except Exception:
                    raise InternalError()
        else:
            def wrapper(func_cx, this, args):
                try:
                    arglist = []
                    for arg in args:
                        arglist.append(self.wrap_jsobject(arg))

                    # TODO: Fill in extra required params with
                    # pymonkey.undefined?  or automatically throw an
                    # exception to calling js code?
                    return self.wrap_pyobject(func(*arglist))
                except pydermonkey.error:
                    raise
                except Exception:
                    raise InternalError()
        wrapper.wrapped_pyobject = func
        wrapper.__name__ = name

        jsfunc = self.cx.new_function(wrapper, name)
        self.__py_to_js[func] = jsfunc

        return jsfunc

    def __wrap_pyinstance(self, value):
        pyproto = type(value)
        if pyproto not in self.__type_protos:
            jsproto = self.cx.new_object()
            if hasattr(pyproto, '__jsprops__'):
                define_getter = self.cx.get_property(jsproto,
                                                     '__defineGetter__')
                define_setter = self.cx.get_property(jsproto,
                                                     '__defineSetter__')
                for name in pyproto.__jsprops__:
                    prop = getattr(pyproto, name)
                    if not type(prop) == property:
                        raise TypeError("Expected attribute '%s' to "
                                        "be a property" % name)
                    getter = None
                    setter = None
                    if prop.fget:
                        getter = self.__wrap_pycallable(prop.fget,
                                                        pyproto)
                    if prop.fset:
                        setter = self.__wrap_pycallable(prop.fset,
                                                        pyproto)
                    if getter:
                        self.cx.call_function(jsproto,
                                              define_getter,
                                              (name, getter))
                    if setter:
                        self.cx.call_function(jsproto,
                                              define_setter,
                                              (name, setter,))
            for name in dir(pyproto):
                attr = getattr(pyproto, name)
                if (isinstance(attr, types.UnboundMethodType) and
                    hasattr(attr, '__jsexposed__') and
                    attr.__jsexposed__):
                    jsmethod = self.__wrap_pycallable(attr, pyproto)
                    self.cx.define_property(jsproto, name, jsmethod)
            self.__type_protos[pyproto] = jsproto
        return self.cx.new_object(value, self.__type_protos[pyproto])

    def wrap_pyobject(self, value):
        """
        Wraps the given Python object for export to untrusted JS.

        If the Python object isn't of a type that can be exposed to JS,
        a TypeError is raised.
        """

        if (isinstance(value, (int, basestring, float, bool)) or
            value is pydermonkey.undefined or
            value is None):
            return value
        if isinstance(value, SafeJsObjectWrapper):
            # It's already wrapped, just unwrap it.
            return value.wrapped_jsobject
        elif callable(value):
            if not (hasattr(value, '__jsexposed__') and
                    value.__jsexposed__):
                raise ValueError("Callable isn't configured for exposure "
                                 "to untrusted JS code")
            return self.__wrap_pycallable(value)
        elif isinstance(value, JsExposedObject):
            return self.__wrap_pyinstance(value)
        else:
            raise TypeError("Can't expose objects of type '%s' to JS." %
                            type(value).__name__)

    def wrap_jsobject(self, jsvalue, this=None):
        """
        Wraps the given pydermonkey.Object for import to trusted
        Python code. If the type is just a primitive, it's simply
        returned, since no wrapping is needed.
        """

        if this is None:
            this = self.root.wrapped_jsobject
        if isinstance(jsvalue, pydermonkey.Function):
            if jsvalue.is_python:
                # It's a Python function, just unwrap it.
                return self.cx.get_object_private(jsvalue).wrapped_pyobject
            return SafeJsFunctionWrapper(self, jsvalue, this)
        elif isinstance(jsvalue, pydermonkey.Object):
            # It's a wrapped Python object instance, just unwrap it.
            instance = self.cx.get_object_private(jsvalue)
            if instance:
                if not isinstance(instance, JsExposedObject):
                    raise AssertionError("Object private is not of type "
                                         "JsExposedObject")
                return instance
            else:
                return SafeJsObjectWrapper(self, jsvalue, this)
        else:
            # It's a primitive value.
            return jsvalue

    def new_array(self, *contents):
        """
        Creates a new JavaScript array with the given contents and
        returns a wrapper for it.
        """

        array = self.wrap_jsobject(self.cx.new_array_object())
        for item in contents:
            array.push(item)
        return array

    def new_object(self, **contents):
        """
        Creates a new JavaScript object with the given properties and
        returns a wrapper for it.
        """

        obj = self.wrap_jsobject(self.cx.new_object())
        for name in contents:
            obj[name] = contents[name]
        return obj

    def get_calling_script(self):
        """
        Returns the filename of the current stack's most recent
        JavaScript caller.
        """

        frame = self.cx.get_stack()['caller']
        curr_script = None
        while frame and curr_script is None:
            if frame['function'] and frame['function'].filename:
                curr_script = frame['function'].filename
            elif frame['script']:
                curr_script = frame['script'].filename
            frame = frame['caller']

        if curr_script is None:
            raise RuntimeError("Can't find calling script")
        return curr_script

    def _install_globals(self, object):
        for name in self.__globals:
            object[name] = self.__globals[name]
        object['require'] = self._require

    @jsexposed(name='require')
    def _require(self, path):
        """
        Implementation for the global require() function, implemented
        as per the CommonJS SecurableModule specification:

        http://wiki.commonjs.org/wiki/CommonJS/Modules/SecurableModules
        """

        filename = self.fs.find_module(self.get_calling_script(), path)
        if not filename:
            raise pydermonkey.error('Module not found: %s' % path)
        if not filename in self.__modules:
            cx = self.cx
            module = cx.new_object(None, self.__root_proto)
            try: 
              # This throws an exception because it is already done in 
              # the __init__ method:
              cx.init_standard_classes(module)
              # I have not removed the line above, because I don't know if there
              # are cases where it is necessary.  
            except pydermonkey.error:
              try:
                errmsg = sys.exc_info()[1][0]
              except: 
                errmsg = ""
              if (errmsg != "Can't init standard classes on the same context twice."):
                raise
              # Importing standard classes twice is silently ignored at this point
              # All other exceptions are re-raised. km 23.9.2009
            except:
              raise
            exports = cx.new_object()
            cx.define_property(module, 'exports', exports)
            self._install_globals(self.wrap_jsobject(module))
            self.__modules[filename] = self.wrap_jsobject(exports)
            contents = self.fs.open(filename).read()
            cx.evaluate_script(module, contents, filename, 1)
        return self.__modules[filename]

    def run_script(self, contents, filename='<string>', lineno=1,
                   callback=None, stderr=None):
        """
        Runs the given JS script, returning 0 on success, -1 on failure.
        """

        if stderr is None:
            stderr = sys.stderr

        retval = -1
        cx = self.cx
        try:
            result = cx.evaluate_script(self.root.wrapped_jsobject,
                                        contents, filename, lineno)
            if callback:
                callback(self.wrap_jsobject(result))
            retval = 0
        except pydermonkey.error, e:
            params = dict(
                stack_trace = format_stack(self.js_stack, self.fs.open),
                error = e.args[1]
                )
            stderr.write("%(stack_trace)s\n%(error)s\n" % params)
        except InternalError, e:
            stderr.write("An internal error occurred.\n")
            traceback.print_exception(e.exc_info[0], e.exc_info[1],
                                      e.exc_info[2], None, stderr)
        return retval

class HttpFileSystem(object):
    """
    File system through which all resources are loaded over HTTP.
    """

    def __init__(self, base_url):
        self.base_url = base_url

    def find_module(self, curr_url, path):
        import urlparse

        if path.startswith("."):
            base_url = curr_url
        else:
            base_url = self.base_url

        url = "%s.js" % urlparse.urljoin(base_url, path)
        if not url.startswith(self.base_url):
            return None
        return url

    def open(self, url):
        import urllib

        return urllib.urlopen(url)

class LocalFileSystem(object):
    """
    File system through which all resources are loaded over the local
    filesystem.
    """

    def __init__(self, root_dir):
        self.root_dir = root_dir

    def find_module(self, curr_script, path):
        import os

        if path.startswith("."):
            base_dir = os.path.dirname(curr_script)
        else:
            base_dir = self.root_dir

        ospath = path.replace('/', os.path.sep)
        filename = os.path.join(base_dir, "%s.js" % ospath)
        filename = os.path.normpath(filename)
        if (filename.startswith(self.root_dir) and
            (os.path.exists(filename) and
             not os.path.isdir(filename))):
            return filename
        else:
            return None

    def open(self, filename):
        return open(filename, 'r')
