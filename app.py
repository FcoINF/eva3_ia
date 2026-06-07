import os
import json
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "GITHUB_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://models.inference.ai.azure.com"),
)

model = os.getenv("OPENAI_MODEL", "gpt-4o")

EMAIL_REMITENTE = os.getenv("EMAIL_REMITENTE", "botmuni46@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", "")

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

def enviar_correo(destinatario):
    if not EMAIL_PASSWORD:
        return "Error: No hay configuración de correo. Revisa las variables EMAIL_REMITENTE y EMAIL_PASSWORD en el archivo .env"

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

        servidor = smtplib.SMTP("smtp.gmail.com", 587)
        servidor.starttls()
        servidor.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
        servidor.sendmail(EMAIL_REMITENTE, destinatario, mensaje.as_string())
        servidor.quit()

        return f"Correo enviado exitosamente a {destinatario} con la información del camión de la basura."
    except Exception as e:
        return f"Error al enviar correo: {e}"

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
        if not correo:
            return "Por favor proporciona un correo electrónico válido."
        if correo not in suscriptores:
            suscriptores.append(correo)
        resultado = enviar_correo(correo)
        return resultado
    return ""

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

conversaciones = {}

def get_conversacion(session_id):
    if session_id not in conversaciones:
        conversaciones[session_id] = []
    return conversaciones[session_id]

@app.route("/")
def index():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    mensaje = data.get("message", "").strip()
    session_id = data.get("session_id", session.get("session_id", "default"))

    if not mensaje:
        return jsonify({"error": "Mensaje vacío"}), 400

    historial = get_conversacion(session_id)
    historial.append({"role": "user", "content": mensaje})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in historial[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    try:
        respuesta = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0.7,
            max_tokens=500,
        )

        choice = respuesta.choices[0]
        msg = choice.message

        if msg.tool_calls:
            for tc in msg.tool_calls:
                nombre = tc.function.name
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
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
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=500,
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
        return jsonify({"error": str(e)}), 500

@app.route("/reset", methods=["POST"])
def reset():
    session_id = session.get("session_id", "default")
    if session_id in conversaciones:
        conversaciones[session_id] = []
    return jsonify({"status": "ok"})

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(solicitudes_frecuentes)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
