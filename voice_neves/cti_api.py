"""API/CTI REST local para integração externa do softphone.

Expõe um endpoint HTTP em loopback (127.0.0.1) para controlar o softphone
(fazer/atender/desligar/colocar em espera uma chamada e consultar o estado).
Pensado para integração CTI (Computer Telephony Integration): um CRM/ERL ou
frontend dispara POSTs e faz polling do estado.

O servidor roda em uma thread daemon. Toda operação sobre o PJSIP precisa
acontecer na main thread (onde roda o mainloop/endpoint), por isso os handlers
invocam o controlador via `controller.cti_invoke(fn, *args)`, que enfileira a
chamada na fila de UI e aguarda o resultado.

Segurança: bind apenas em 127.0.0.1. Se um token for configurado, todo
endpoint (exceto /health) exige o cabeçalho `X-Auth-Token` igual ao token.
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"


def parse_call_request(raw_body):
    """Extrai {number, server} do corpo JSON de POST /call (função pura).

    Retorna um dict normalizado, ou None se o corpo não for um JSON válido
    com um objeto. `server` é opcional (None = usa a conta selecionada).
    """
    if not raw_body:
        return {"number": "", "server": None}
    try:
        if isinstance(raw_body, bytes):
            data = json.loads(raw_body.decode("utf-8"))
        else:
            data = json.loads(raw_body)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    number = str(data.get("number") or "").strip()
    server = data.get("server")
    if isinstance(server, str):
        server = server.strip() or None
    else:
        server = None
    return {"number": number, "server": server}


class _Handler(BaseHTTPRequestHandler):
    """Handler HTTP que delega as ações ao controlador do app."""

    server_version = "VoiceNevesCTI/1.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as e:
            logger.debug("Cliente CTI desconectou ao gravar resposta: %s", e)

    def log_message(self, fmt, *args):
        logger.debug("CTI %s", fmt % args)

    def _token_ok(self):
        token = getattr(self.server, "cti_token", "")
        if not token:
            return True
        supplied = self.headers.get("X-Auth-Token", "")
        return supplied == token

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._send_json(200, {"ok": True, "service": "voice-neves-cti"})
            return
        if not self._token_ok():
            self._send_json(403, {"ok": False, "error": "Token de autenticação inválido"})
            return
        if path == "/status":
            status = self.server.cti_invoke(self.server.controller.cti_status)
            self._send_json(200, status)
            return
        self._send_json(404, {"ok": False, "error": f"Rota não encontrada: {path}"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._token_ok():
            self._send_json(403, {"ok": False, "error": "Token de autenticação inválido"})
            return
        body = self._read_body()
        if path == "/call":
            req = parse_call_request(body)
            if req is None:
                self._send_json(400, {"ok": False, "error": "Corpo JSON inválido (esperado {\"number\": ...})"})
                return
            if not req["number"]:
                self._send_json(400, {"ok": False, "error": "Campo 'number' é obrigatório"})
                return
            result = self.server.cti_invoke(
                self.server.controller.cti_make_call, req["number"], req["server"]
            )
            self._send_result(result)
            return
        if path == "/answer":
            self._send_result(self.server.cti_invoke(self.server.controller.cti_answer))
            return
        if path == "/hangup":
            self._send_result(self.server.cti_invoke(self.server.controller.cti_hangup))
            return
        if path == "/hold":
            self._send_result(self.server.cti_invoke(self.server.controller.cti_hold))
            return
        if path == "/unhold":
            self._send_result(self.server.cti_invoke(self.server.controller.cti_unhold))
            return
        self._send_json(404, {"ok": False, "error": f"Rota não encontrada: {path}"})

    def _send_result(self, result):
        # `result` é (ok: bool, message?: str, extra?: dict) vindo do controller.
        if not isinstance(result, tuple) or not result:
            status, payload = 500, {"ok": False, "error": "Resposta inválida do controlador"}
        else:
            ok = bool(result[0])
            message = result[1] if len(result) > 1 and isinstance(result[1], str) else ""
            extra = result[2] if len(result) > 2 and isinstance(result[2], dict) else {}
            payload = {"ok": ok, **extra}
            if not ok and message:
                payload["error"] = message
            status = 200 if ok else 400
        self._send_json(status, payload)


class CtiServer:
    """Servidor HTTP/CTI local. Roda em grupo:.thread daemon.

    `controller` deve ser a instância do SoftphoneApp, expondo:
      - cti_invoke(fn, *args) -> resultado rodado na main thread
      - cti_status() -> dict de estado
      - cti_make_call(number, server) -> (ok, msg)
      - cti_answer() / cti_hangup() / cti_hold() / cti_unhold() -> (ok, msg)
    """

    def __init__(self, controller, port=9020, token=""):
        self.controller = controller
        self.port = int(port)
        self.token = str(token or "")
        self._server = None
        self._thread = None
        self._httpd = None

    @staticmethod
    def _spawn(fn, *args):
        """Chama fn na main thread via cti_invoke (delegado pelo controlador)."""
        raise NotImplementedError

    def start(self):
        if self._httpd is not None:
            return self._httpd
        self._httpd = ThreadingHTTPServer((DEFAULT_HOST, self.port), _Handler)
        self._httpd.cti_token = self.token
        self._httpd.controller = self.controller
        self._httpd.cti_invoke = self.controller.cti_invoke
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="cti-http",
            daemon=True,
        )
        self._thread.start()
        logger.info("API CTI REST ativa em http://%s:%d", DEFAULT_HOST, self.port)
        return self._httpd

    def stop(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception as e:
                logger.warning("Erro ao parar API CTI: %s", e)
            self._httpd = None
        self._thread = None
