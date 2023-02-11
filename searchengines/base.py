from inspect import trace
import subprocess
import re
import shlex
import sys
import os
import shutil
import traceback

class Base:
    """
        This is the base search engine class.
        Override it to define new search engines.
    """

    SETTINGS = [
        "path_to_executable",
        "mandatory_options",
        "common_options", 
    ]
    PARSER_RE = re.compile(r'^((?:\w\:[\\|/]|\/)[^:]+):([\d:]+):(.*)')

    def __init__(self, settings):
        """
            Receives the sublime.Settings object
        """
        self.settings = settings
        for setting_name in self.__class__.SETTINGS:
            setting_value = self.settings.get(
                self._full_settings_name(setting_name), '')
            if sys.version < '3':
                setting_value = setting_value.encode()
            setattr(self, setting_name, setting_value)

        # With this you can add a full path as path_to_executable
        if not os.path.exists(self.path_to_executable) and os.name == "nt":
            self._resolve_windows_path_to_executable()

    def dprint(self, d):
        if self.settings.get("debug", False): 
            print(d)

    def _check_arg_types(self, funcname, *args):
        hasstr = hasbytes = False
        for s in args:
            if isinstance(s, str):
                hasstr = True
            elif isinstance(s, bytes):
                hasbytes = True
            else:
                raise TypeError('%s() argument must be str or bytes, not %r' %
                                (funcname, s.__class__.__name__)) from None
        if hasstr and hasbytes:
            raise TypeError("Can't mix strings and bytes in path components") from None

    def _fspath(self, path):
        """Return the path representation of a path-like object.
        If str or bytes is passed in, it is returned unchanged. Otherwise the
        os.PathLike interface is used to get the path representation. If the
        path representation is not str or bytes, TypeError is raised. If the
        provided path is not str, bytes, or os.PathLike, TypeError is raised.
        """
        if isinstance(path, (str, bytes)):
            return path

        # Work from the object's type to match method resolution of other magic
        # methods.
        path_type = type(path)
        try:
            path_repr = path_type.__fspath__(path)
        except AttributeError:
            if hasattr(path_type, '__fspath__'):
                raise
            else:
                raise TypeError("expected str, bytes or os.PathLike object, "
                                "not " + path_type.__name__)
        if isinstance(path_repr, (str, bytes)):
            return path_repr
        else:
            raise TypeError("expected {}.__fspath__() to return str or bytes, "
                            "not {}".format(path_type.__name__,
                                            type(path_repr).__name__))
                                            
    def commonpath (self, paths):
        """Given a sequence of path names, returns the longest common sub-path."""
        if sys.version_info >= (3,5,0):
            return os.path.commonpath(paths)
       
        if not paths:
            raise ValueError('commonpath() arg is an empty sequence')

        paths = tuple(map(self._fspath, paths))
        sep = os.sep

        if isinstance(paths[0], bytes):
            curdir = b'.'
        else:
            curdir = '.'

        try:
            split_paths = [path.split(sep) for path in paths]

            try:
                isabs, = set(p[:1] == sep for p in paths)
            except ValueError:
                raise ValueError("Can't mix absolute and relative paths") from None

            split_paths = [[c for c in s if c and c != curdir] for s in split_paths]
            s1 = min(split_paths)
            s2 = max(split_paths)
            common = s1
            for i, c in enumerate(s1):
                if c != s2[i]:
                    common = s1[:i]
                    break

            prefix = sep if isabs else sep[:0]
            return prefix + sep.join(common)
        except (TypeError, AttributeError):
            self._check_arg_types('commonpath', *paths)
            raise

    def run(self, query, folders):
        """
            Run the search engine. Return a list of tuples, where first element is
            the absolute file path, and optionally row information, separated
            by a semicolon, and the second element is the result string
        """
        arguments = self._arguments(query, self._remove_subfolders(folders))
        self.vprint("Arguments: {}".format(arguments))
        self.vprint("Running: %s" % " ".join(arguments))

        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            pipe = subprocess.Popen(arguments,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    cwd=self.commonpath(folders), 
                                    startupinfo=startupinfo
                                    )
        except OSError as oe:  # Not FileNotFoundError for compatibility with Sublime Text 2
            self.vprint("Found exception: {}".format(oe))
            self.vprint(traceback.format_exc())
            raise RuntimeError("Could not find executable %s" %
                               self.path_to_executable)

        output, error = pipe.communicate()

        if self._is_search_error(pipe.returncode, output, error):
            raise RuntimeError(self._sanitize_output(error))
        return self._parse_output(self._sanitize_output(output))

    def _remove_subfolders(self, folders):
        """
            Optimize folder list by removing possible subfolders.
        """
        unique_folders = []
        for folder in sorted(folders):
            if (len(unique_folders) == 0 or
                    not folder.startswith(unique_folders[-1])):
                unique_folders.append(folder)
        return unique_folders

    def _arguments(self, query, folders):
        """
            Prepare arguments list for the search engine.
        """
        return (
            [self.path_to_executable] +
            shlex.split(self.mandatory_options) +
            shlex.split(self.common_options) +
            [query] +
            folders )

    def _sanitize_output(self, output):
        return output.decode('utf-8', 'ignore').strip()

    def _parse_output(self, output):
        lines = output.split("\n")
        self.dprint("Parse output lines: {}".format(lines))

        line_parts = [Base.PARSER_RE.findall(line)[0] for line in lines]
        self.dprint("Line parts: {}".format(line_parts))

        return [line for line in line_parts]

    def _is_search_error(self, returncode, output, error):
        returncode != 0

    def _full_settings_name(self, name):
        return "search_in_project_%s_%s" % (self.__class__.__name__, name)

    def _filter_lines_without_matches(self, line_parts):
        return filter(lambda line: len(line) > 2, line_parts)

    def _resolve_windows_path_to_executable(self):
        try:
            if shutil.which(self.path_to_executable):
                self.path_to_executable = shutil.which(self.path_to_executable)

        except Exception as e:
            print("Exception resolving windows path: {}".format(e))
            pass
