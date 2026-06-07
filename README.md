# Sistema Inteligente Municipal - Municipalidad de Llanquihue

Sistema desarrollado en Python con OpenAI y Flask, enfocado en mejorar la atención ciudadana mediante un asistente virtual inteligente con interfaz web.

---

## Objetivo del Proyecto

Mejorar el acceso a información municipal de manera rápida, clara y automatizada mediante un ChatBOT inteligente.

**Capacidades:**
- Responder consultas municipales (permisos, multas, patentes, servicios)
- Conversaciones contextuales con historial por sesión
- Uso de herramientas inteligentes (function calling)

---

## Tecnologías Utilizadas

- Python + Flask
- OpenAI API (Function Calling)
- GPT-4o (GitHub Models)
- HTML, CSS, JavaScript
- python-dotenv

---

## Instalación y Ejecución

### 1. Clonar repositorio

```bash
git clone https://github.com/FcoINF/EVA2_MUNI.git
cd EVA2_MUNI
```

### 2. Instalar dependencias

```bash
pip install flask openai python-dotenv
```

### 3. Configurar API Key

Crea un archivo `.env` en la raíz del proyecto:

```env
OPENAI_API_KEY=tu_token_de_github
OPENAI_BASE_URL=https://models.inference.ai.azure.com
OPENAI_MODEL=gpt-4o
```

> Para obtener un token de GitHub: https://github.com/settings/tokens (token clásico, sin permisos especiales)

### 4. Ejecutar

```bash
python app.py
```

Abrir en el navegador: **http://127.0.0.1:5000**

---

## Estructura del Proyecto

```
├── app.py                  # Servidor web Flask con la API de chat
├── templates/
│   └── index.html          # Interfaz de chat web
├── Municipalidad_EVA2.ipynb # Notebook original (prototipo)
├── requirements.txt        # Dependencias del proyecto
├── .env                    # Variables de entorno (no se sube a git)
└── .gitignore
```

---

## Uso

1. Escribe tu consulta en el chat y presiona Enter
2. El asistente responde usando herramientas especializadas según el tema
3. Usa los botones de sugerencias para consultas rápidas
4. Presiona "Limpiar conversación" para reiniciar el historial

---

## Notebook Original

El archivo `Municipalidad_EVA2.ipynb` contiene el prototipo original con el menú por consola, útil para pruebas rápidas y desarrollo.
