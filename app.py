import os
import json
import uuid
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

solicitudes_frecuentes = {"permiso": 0, "multas": 0, "patentes": 0, "servicios": 0}

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
    }
]

def ejecutar_herramienta(name):
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
    return ""

SYSTEM_PROMPT = (
    "Eres un asistente virtual de la Municipalidad de Llanquihue, Chile. "
    "Responde de forma clara, amable y útil para los ciudadanos. "
    "Cuando te pregunten sobre permisos de circulación, multas, patentes comerciales "
    "o servicios municipales, usa la herramienta correspondiente para entregar "
    "información precisa. Siempre responde en español."
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
                resultado = ejecutar_herramienta(nombre)
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
