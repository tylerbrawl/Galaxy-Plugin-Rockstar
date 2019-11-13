from galaxy.api.errors import BackendError

import http.server
import logging as log
import os
import shutil


class RockstarAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        return

    def do_GET(self):
        status_code = 200
        content_type = "text/html; charset=UTF-8"

        try:
            log.debug("ROCKSTAR_PATH_TEST: " + os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"))
            file = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), 'rb')
            self.send_response(status_code)
            self.send_header('Content-type', content_type)
            self.end_headers()
            shutil.copyfileobj(file, self.wfile)
        except Exception:
            log.exception("There was an unknown exception when attempting to process the local auth server request. (Is"
                          " index.html located within the plugin root directory?)")
            raise BackendError()
