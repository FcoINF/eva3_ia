import os
import json
import uuid
import re
import time
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from collections import defaultdict

from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(64)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=100 * 1024,
)

ENV_ERRORS = []
API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://models.inference.ai.azure.com")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

PLACEHOLDER_KEYS = {"", "GITHUB_API_KEY", "TU_TOKEN_DE_GITHUB_AQUI"}
if API_KEY in PLACEHOLDER_KEYS:
    ENV_ERRORS.append("OPENAI_API_KEY no está configurada. Revisa el archivo .env")

if ENV_ERRORS:
    for err in ENV_ERRORS:
        logger.warning("Config: %s", err)

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

EMAIL_REMITENTE = os.getenv("EMAIL_REMITENTE", "botmuni46@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", "")

MAX_MENSAJE_LEN = 2000
MAX_SESIONES_POR_IP = 50
MAX_HISTORIAL = 30
RPM_LIMIT = 20

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|above|prior|instructions)",
    r"(?i)forget\s+(all\s+)?(previous|above|prior|instructions)",
    r"(?i)system\s*(prompt|message|instruction)",
    r"(?i)you\s+are\s+(not\s+)?(a\s+)?(bot|assistant|ai|gpt)",
    r"(?i)new\s+(role|persona|identity)",
    r"(?i)act\s+as\s+\w+",
    r"(?i)bypass|jailbreak|dan\b",
]
RESPONSE_INJECTION = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

BLACKLISTED_DOMAINS = {"tempmail.com", "mailinator.com", "guerrillamail.com", "10minutemail.com"}

class RateLimiter:
    def __init__(self, rpm=RPM_LIMIT):
        self.rpm = rpm
        self.entries = defaultdict(list)
        self._last_cleanup = time.time()

    def is_allowed(self, key):
        now = time.time()
        if now - self._last_cleanup > 300:
            self._cleanup(now)
        window = now - 60
        self.entries[key] = [t for t in self.entries[key] if t > window]
        if len(self.entries[key]) >= self.rpm:
            return False
        self.entries[key].append(now)
        return True

    def _cleanup(self, now):
        cutoff = now - 120
        for k in list(self.entries.keys()):
            self.entries[k] = [t for t in self.entries[k] if t > cutoff]
            if not self.entries[k]:
                del self.entries[k]
        self._last_cleanup = now

rate_limiter = RateLimiter()

solicitudes_frecuentes = {"permiso": 0, "multas": 0, "patentes": 0, "servicios": 0}
suscriptores = []

tools = [
    {
        "type": "function",
        "function": {
            "name": "consultar_permiso_circulacion",
            "description": "Entrega información sobre permisos de circulación vehicular",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_multas",
            "description": "Entrega información sobre pago de multas de tránsito",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_patentes",
            "description": "Entrega información sobre patentes comerciales",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_servicios",
            "description": "Entrega información sobre servicios municipales generales",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suscribir_noticias",
            "description": "Suscribe un correo electrónico para recibir noticias municipales como el horario del camión de la basura. Usa esta herramienta cuando el usuario pida recibir noticias o información del camión de la basura por correo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "correo": {
                        "type": "string",
                        "description": "El correo electrónico del usuario"
                    }
                },
                "required": ["correo"]
            }
        }
    }
]

SYSTEM_PROMPT = (
    "Eres un asistente virtual de la Municipalidad de Llanquihue, Chile. "
    "Responde de forma clara, amable y útil para los ciudadanos. "
    "Cuando te pregunten sobre permisos de circulación, multas, patentes comerciales "
    "o servicios municipales, usa la herramienta correspondiente para entregar "
    "información precisa. "
    "Si el usuario pide recibir noticias del camión de la basura o información "
    "municipal por correo, pídele su correo electrónico y luego usa la herramienta "
    "suscribir_noticias con ese correo para enviarle la información. "
    "Siempre responde en español."
)

SEPARATOR_PROMPT = "\n\n--- INICIO DE CONSULTA CIUDADANA ---\n"

conversaciones = {}

def sanitizar_mensaje(mensaje):
    if not isinstance(mensaje, str):
        return ""
    mensaje = mensaje.strip()
    if len(mensaje) > MAX_MENSAJE_LEN:
        mensaje = mensaje[:MAX_MENSAJE_LEN]
    mensaje = mensaje.replace("\x00", "")
    mensaje = RESPONSE_INJECTION.sub("", mensaje)
    return mensaje

def detectar_inyeccion_prompt(mensaje):
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, mensaje):
            return True
    return False

def validar_email(email):
    if not email or not isinstance(email, str) or len(email) > 254:
        return False
    if not EMAIL_REGEX.match(email):
        return False
    dominio = email.split("@")[1].lower()
    if dominio in BLACKLISTED_DOMAINS:
        return False
    return True

def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"

def enviar_correo(destinatario):
    if not EMAIL_PASSWORD:
        logger.warning("Intento de envío sin configurar EMAIL_PASSWORD")
        return "Error: No hay configuración de correo. Revisa las variables EMAIL_REMITENTE y EMAIL_PASSWORD en el archivo .env"

    if not validar_email(destinatario):
        logger.warning("Intento de envío a correo inválido: %s", destinatario[:50])
        return "Error: El correo electrónico proporcionado no es válido."

    if len(destinatario) > 254:
        return "Error: El correo electrónico excede la longitud máxima permitida."

    if "\n" in destinatario or "\r" in destinatario:
        logger.warning("Posible SMTP injection detectada en destinatario: %s", repr(destinatario))
        return "Error: Correo electrónico con formato no válido."

    asunto = "Noticias Municipalidad de Llanquihue"
    cuerpo = (
        "Hola vecino/a de Llanquihue.\n\n"
        "El camión de la basura pasará de lunes a sábado "
        "desde las 09:00 hasta las 18:00 horas.\n\n"
        "Municipalidad de Llanquihue."
    )

    try:
        mensaje = MIMEMultipart()
        mensaje["From"] = EMAIL_REMITENTE
        mensaje["To"] = destinatario
        mensaje["Subject"] = asunto
        mensaje.attach(MIMEText(cuerpo, "plain"))

        servidor = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        servidor.starttls()
        servidor.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
        servidor.sendmail(EMAIL_REMITENTE, [destinatario], mensaje.as_string())
        servidor.quit()

        logger.info("Correo enviado exitosamente a %s", destinatario[:50])
        return f"Correo enviado exitosamente a {destinatario} con la información del camión de la basura."
    except smtplib.SMTPException as e:
        logger.error("Error SMTP al enviar correo a %s: %s", destinatario[:50], str(e)[:100])
        return "Error al enviar el correo. Verifica la configuración de correo en el archivo .env."
    except Exception as e:
        logger.error("Error inesperado al enviar correo: %s", str(e)[:100])
        return "Error interno al enviar el correo. Intenta más tarde."

def ejecutar_herramienta(name, args):
    if name == "consultar_permiso_circulacion":
        solicitudes_frecuentes["permiso"] += 1
        return (
            "Para renovar el permiso de circulación necesitas:\n"
            "- SOAP vigente\n"
            "- Revisión técnica al día\n"
            "- Permiso anterior\n"
            "- Padrón del vehículo\n\n"
            "Puedes realizar el trámite en la Municipalidad de Llanquihue."
        )
    elif name == "consultar_multas":
        solicitudes_frecuentes["multas"] += 1
        return (
            "El pago de multas puede realizarse:\n"
            "- Online\n"
            "- Presencialmente en oficinas municipales\n\n"
            "Debes presentar la información del vehículo o número de infracción."
        )
    elif name == "consultar_patentes":
        solicitudes_frecuentes["patentes"] += 1
        return (
            "Para obtener una patente comercial necesitas:\n"
            "- Inicio de actividades\n"
            "- RUT empresa o persona\n"
            "- Dirección comercial\n"
            "- Permisos sanitarios si corresponde"
        )
    elif name == "consultar_servicios":
        solicitudes_frecuentes["servicios"] += 1
        return (
            "La Municipalidad de Llanquihue ofrece:\n"
            "- Aseo y ornato\n"
            "- Reciclaje\n"
            "- Pago de permisos\n"
            "- Atención social\n"
            "- Información comunitaria"
        )
    elif name == "suscribir_noticias":
        correo = args.get("correo", "")
        if not validar_email(correo):
            return "El correo proporcionado no es válido. Por favor ingresa un correo electrónico real."
        if correo in suscriptores:
            return "Ya estás suscrito a las noticias municipales. Te enviaremos la información del camión de la basura a tu correo."
        suscriptores.append(correo)
        logger.info("Nuevo suscriptor: %s", correo[:50])
        resultado = enviar_correo(correo)
        return resultado

    return ""

def get_conversacion(session_id):
    if session_id not in conversaciones:
        conversaciones[session_id] = []
    return conversaciones[session_id]

@app.before_request
def limitar_sesiones():
    ip = get_client_ip()
    sesiones_activas = sum(1 for sid in conversaciones if sid.startswith(ip + "::"))
    if sesiones_activas > MAX_SESIONES_POR_IP:
        logger.warning("Demasiadas sesiones desde IP %s: %d", ip, sesiones_activas)

@app.before_request
def limitar_tamano():
    if request.content_length and request.content_length > app.config["MAX_CONTENT_LENGTH"]:
        logger.warning("Payload excede límite desde IP %s", get_client_ip())
        return jsonify({"error": "Solicitud demasiado grande"}), 413

@app.after_request
def seguridad_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
    )
    return response

@app.route("/")
def index():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    ip = get_client_ip()

    if not request.is_json:
        return jsonify({"error": "Solicitud inválida"}), 400

    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        return jsonify({"error": "Solicitud inválida"}), 400

    if not data or not isinstance(data, dict):
        return jsonify({"error": "Solicitud inválida"}), 400

    session_id = data.get("session_id", session.get("session_id", "default"))

    if not rate_limiter.is_allowed(ip):
        logger.warning("Rate limit excedido para IP %s", ip)
        return jsonify({"error": "Demasiadas solicitudes. Intenta de nuevo en un minuto."}), 429

    if not rate_limiter.is_allowed(session_id):
        logger.warning("Rate limit excedido para sesión %s", session_id[:16])
        return jsonify({"error": "Demasiadas solicitudes. Intenta de nuevo en un minuto."}), 429

    mensaje_raw = data.get("message", "")

    if not isinstance(session_id, str) or len(session_id) > 128:
        return jsonify({"error": "Sesión inválida"}), 400

    mensaje = sanitizar_mensaje(mensaje_raw)
    if not mensaje:
        return jsonify({"error": "Mensaje vacío"}), 400

    if detectar_inyeccion_prompt(mensaje_raw):
        logger.warning("Posible inyección de prompt detectada desde IP %s: %s", ip, mensaje_raw[:80])
        return jsonify({
            "response": "He detectado un intento de manipulación en tu mensaje. Por favor, realiza una consulta ciudadana respetuosa y directa. Estoy aquí para ayudarte con trámites municipales."
        }), 200

    historial = get_conversacion(session_id)
    historial.append({"role": "user", "content": mensaje})

    messages = [{"role": "system", "content": SYSTEM_PROMPT + SEPARATOR_PROMPT}]
    for msg in historial[-MAX_HISTORIAL:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    logger.info("Chat desde IP %s | sesión %s | msg: %s", ip, session_id[:16], mensaje[:80])

    try:
        respuesta = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            temperature=0.7,
            max_tokens=500,
            timeout=30,
        )

        choice = respuesta.choices[0]
        msg = choice.message

        if msg.tool_calls:
            for tc in msg.tool_calls:
                nombre = tc.function.name
                if nombre not in {t["function"]["name"] for t in tools}:
                    logger.warning("Tool call no autorizada: %s desde IP %s", nombre, ip)
                    continue
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                resultado = ejecutar_herramienta(nombre, args)
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": nombre, "arguments": json.dumps(args)}}]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": resultado
                })

            respuesta_final = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=500,
                timeout=30,
            )
            texto_respuesta = respuesta_final.choices[0].message.content
        else:
            texto_respuesta = msg.content

        if not texto_respuesta:
            texto_respuesta = "Lo siento, no pude procesar tu solicitud."

        historial.append({"role": "assistant", "content": texto_respuesta})

        return jsonify({
            "response": texto_respuesta,
            "session_id": session_id
        })

    except Exception as e:
        error_str = str(e)
        logger.error("Error en chat (IP %s): %s", ip, error_str[:150])
        if "401" in error_str or "unauthorized" in error_str.lower() or "Bad credentials" in error_str:
            return jsonify({"error": "Error de autenticación con el servicio de IA. Verifica tu OPENAI_API_KEY en el archivo .env."}), 500
        if "429" in error_str or "rate_limit" in error_str.lower():
            return jsonify({"error": "El servicio de IA está temporalmente sobrecargado. Intenta de nuevo en unos segundos."}), 500
        if "timeout" in error_str.lower():
            return jsonify({"error": "El servicio de IA tardó demasiado en responder. Intenta de nuevo."}), 500
        return jsonify({"error": "Error interno al procesar la solicitud. Intenta de nuevo más tarde."}), 500

@app.route("/reset", methods=["POST"])
def reset():
    session_id = session.get("session_id", "default")
    if not request.is_json:
        data = request.get_json(force=True, silent=True)
        if data and isinstance(data, dict):
            session_id = data.get("session_id", session_id)
    if session_id in conversaciones:
        conversaciones[session_id] = []
        logger.info("Conversación reseteada: %s", session_id[:16])
    return jsonify({"status": "ok"})

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(solicitudes_frecuentes)

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso no encontrado"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Método no permitido"}), 405

@app.errorhandler(413)
def payload_too_large(e):
    return jsonify({"error": "Solicitud demasiado grande"}), 413

@app.errorhandler(500)
def internal_error(e):
    logger.error("Error interno del servidor: %s", str(e)[:150])
    return jsonify({"error": "Error interno del servidor"}), 500

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Sistema Inteligente Municipal - Llanquihue")
    logger.info("Modo: %s", "DEBUG" if app.debug else "PRODUCCIÓN")
    if ENV_ERRORS:
        logger.warning("ADVERTENCIA: Hay %d errores de configuración", len(ENV_ERRORS))
        for err in ENV_ERRORS:
            logger.warning("  - %s", err)
    logger.info("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5000)
