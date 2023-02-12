import sublime
import sublime_plugin
import os.path
import os
import sys
import inspect
from collections import defaultdict
import traceback
import importlib

sys.path.append(os.path.dirname(__file__))
import searchengines


class SearchInProjectCommand(sublime_plugin.WindowCommand):

    # Used to trim lines for the results quick panel. Without trimming Sublime Text
    # *will* hang on long lines - often encountered in minified Javascript, for example.
    MAX_RESULT_LINE_LENGTH = 1000

    def __init__(self, window):
        sublime_plugin.WindowCommand.__init__(self, window)
        self.results = []
        self.last_search_string = ''
        self.last_selected_result_index = 0
        self.saved_view = None
        self.settings = sublime.load_settings(
            'SearchInProject.sublime-settings')

    def run(self, type="search"):
        if type == "search":
            self.search()
        elif type == "clear":
            self.clear_markup()
        elif type == "next":
            self.goto_relative_result(1)
        elif type == "prev":
            self.goto_relative_result(-1)
        else:
            raise Exception("unrecognized type \"%s\"" % type)

    def load_search_engine(self):
        self.engine_name = self.settings.get("search_in_project_engine")
        importlib.import_module("searchengines.%s" % self.engine_name)
        self.engine = searchengines.__dict__[
            self.engine_name].engine_class(self.settings)

    def search(self):
        self.load_search_engine()
        view = self.window.active_view()
        selection_text = view.substr(view.sel()[0])
        self.saved_view = view
        panel_view = self.window.show_input_panel(
            "Search in project:",
            not "\n" in selection_text and selection_text or self.last_search_string,
            self.perform_search, None, None)
        panel_view.run_command("select_all")

    def perform_search(self, text):
        if not text:
            return

        if self.last_search_string != text:
            self.last_selected_result_index = 0
        self.last_search_string = text

        folders = self.search_folders()

        self.common_path = self.engine.commonpath(folders)

        try:
            self.results = self.engine.run(text, folders)
            #self.dprint("Results on search: {}".format(self.results))
            if self.results:
                if self.settings.get('search_in_project_show_list_by_default') == 'true':
                    self.list_in_view()
                else:
                    self.results.append("``` List results in view ```")
                    flags = 0
                    self.window.show_quick_panel(
                        self.results,
                        self.goto_result,
                        flags,
                        self.last_selected_result_index,
                        self.on_highlighted)
            else:
                self.results = []
                sublime.message_dialog('No results')

        except Exception as e:
            self.results = []
            sublime.error_message("%s running search engine %s:" % (
                e.__class__.__name__, self.engine_name) + "\n" + str(e))
            self.dprint(traceback.format_exc())

    def on_highlighted(self, file_no):
        self.last_selected_result_index = file_no
        # last result is "list in view"
        if file_no != -1 and file_no != len(self.results) - 1:
            self.open_and_highlight_file(file_no, transient=True)

    def open_and_highlight_file(self, file_no, transient=False):
        file_name_and_col = self.common_path.replace(
            '\"', '') + self.results[file_no][0]
        flags = sublime.ENCODED_POSITION
        if transient:
            flags |= sublime.TRANSIENT
        view = self.window.open_file(file_name_and_col, flags)

        regions = view.find_all(self.last_search_string, sublime.IGNORECASE)
        view.add_regions("search_in_project", regions,
                         "entity.name.filename.find-in-files", "circle", sublime.DRAW_OUTLINED)

    def goto_result(self, file_no):
        if file_no == -1:
            self.clear_markup()
            self.window.focus_view(self.saved_view)
        else:
            if file_no == len(self.results) - 1:  # last result is "list in view"
                self.list_in_view()
            else:
                self.open_and_highlight_file(file_no)

    def goto_relative_result(self, offset):
        if self.last_search_string:
            new_index = self.last_selected_result_index + offset
            # last result is "list in view"
            if 0 <= new_index < len(self.results) - 1:
                self.last_selected_result_index = new_index
                self.goto_result(new_index)

    def clear_markup(self):
        # every result except the last one (the "list in view")
        for result in self.results[:-1]:
            file_name_and_col = self.common_path.replace('\"', '') + result[0]
            file_name = file_name_and_col.split(':')[0]
            view = self.window.find_open_file(file_name)
            if view:  # if the view is no longer open, do nothing
                view.erase_regions("search_in_project")
        self.results = []

    def list_in_view(self):
        # self.results.pop()
        view = sublime.active_window().new_file()
        view.run_command('search_in_project_results',
                         {'query': self.last_search_string,
                          'results': self.results,
                          'common_path': self.common_path.replace('\"', '')})

    def search_folders(self):
        search_folders = self.window.folders()
        if not search_folders:
            filename = self.window.active_view().file_name()
            if filename:
                search_folders = [os.path.dirname(filename)]
            else:
                search_folders = [os.path.expanduser("~")]
        return search_folders

    def dprint(self, d):
        if self.settings.get("debug", False):
            print(d)


class SearchInProjectResultsCommand(sublime_plugin.TextCommand):
    def format_result(self, common_path, filename, lines):
        lines_text = "\n".join(["  %s: %s" % (location, text)
                                for location, text in lines])
        return "%s:\n%s\n" % (os.path.abspath(os.path.join(common_path, filename)), lines_text)

    def format_results(self, common_path, results, query):
        grouped_by_filename = defaultdict(list)

        for result in results:
            filename, location = result[0], result[1]
            text = result[2]
            grouped_by_filename[filename].append((location, text))
        line_count = len(results)
        file_count = len(grouped_by_filename)

        file_results = [self.format_result(
            common_path, filename, grouped_by_filename[filename]) for filename in grouped_by_filename]
        return ("Search In Project results for \"%s\" (%u lines in %u files):\n\n" % (query, line_count, file_count)) \
            + "\n".join(file_results)

    def run(self, edit, common_path, results, query):
        self.view.set_name('Find Results')
        self.view.set_scratch(True)
        self.view.set_syntax_file(
            'Packages/Default/Find Results.hidden-tmLanguage')
        results_text = self.format_results(common_path, results, query)
        self.view.insert(edit, self.view.text_point(0, 0), results_text)
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(0, 0))
