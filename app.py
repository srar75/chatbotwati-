#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Servidor Flask para el Chatbot Cervo
Webhook para recibir mensajes de WATI
# Build: 2026-01-14-2052
"""
import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timedelta, timezone
from config import Config
from cervo_bot import cervo_bot
from gemini_agent_bot import gemini_agent_bot
from agent_bot import agent_bot

# Obtener el directorio donde está la aplicación
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(APP_DIR, 'cervo_bot.log')

# Configurar logging - MOSTRAR TODOS LOS ERRORES EN TERMINAL
logging_level = logging.DEBUG if Config.FLASK_DEBUG else logging.INFO

# Formato detallado para errores
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
detailed_format = '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'

try:
    logging.basicConfig(
        level=logging_level,
        format=detailed_format,
        handlers=[
            logging.StreamHandler(),  # Terminal
            logging.FileHandler(LOG_FILE, encoding='utf-8')  # Archivo
        ]
    )
except PermissionError:
    # Si no hay permisos para escribir el log, usar solo consola
    logging.basicConfig(
        level=logging_level,
        format=detailed_format,
        handlers=[
            logging.StreamHandler()
        ]
    )

# Configurar nivel de logging para módulos específicos
# Reducir verbose de httpx y httpcore (suprimir DEBUG de estos)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# Asegurar que gemini_agent_bot muestre todos los errores
logging.getLogger('gemini_agent_bot').setLevel(logging.DEBUG)
logging.getLogger('kiu_service').setLevel(logging.DEBUG)
logging.getLogger('wati_service').setLevel(logging.DEBUG)
logging.getLogger('flight_booking_service').setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# Crear aplicación Flask
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# Cache de mensajes procesados para evitar duplicados (máximo 1000 mensajes)
processed_messages = set()
# Mensajes actualmente en proceso (para evitar concurrencia)
processing_messages = set()
MAX_CACHE_SIZE = 1000


@app.route('/', methods=['GET'])
def home():
    """Página de inicio"""
    return jsonify({
        'status': 'running',
        'name': 'Cervo Bot',
        'description': 'Chatbot de reservaciones de vuelos para Venezuela',
        'version': '1.0.0',
        'testing_mode': Config.TESTING_MODE,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de health check"""
    return jsonify({
        'status': 'healthy',
        'uptime': 'ok',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/v1/iata-codes/national', methods=['GET'])
@app.route('/v1/iata-codes/international', methods=['GET'])
@app.route('/airports', methods=['GET'])
def get_airports():
    """Endpoint para obtener lista de aeropuertos desde KIU API"""
    try:
        from kiu_service import kiu_service
        
        # Detectar tipo por la ruta
        if 'international' in request.path:
            result = kiu_service.get_international_airports()
        else:
            result = kiu_service.get_national_airports()
        
        if result.get('success'):
            return jsonify(result.get('data', [])), 200
        else:
            return jsonify({'error': result.get('error', 'Error desconocido')}), 500
            
    except Exception as e:
        logger.error(f"Error en /airports: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/diag/booking-test', methods=['GET'])
def diag_booking_test():
    """
    Endpoint de diagnóstico para probar la API de KIU
    Accede a: https://tudominio.com/diag/booking-test
    """
    try:
        from kiu_service import kiu_service
        from flight_booking_service import flight_service
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'tests': []
        }
        
        # Test 1: Health check de KIU
        try:
            health = kiu_service.health_check()
            results['tests'].append({
                'name': 'KIU Health Check',
                'success': health.get('success', False),
                'result': str(health)[:500]
            })
        except Exception as e:
            results['tests'].append({
                'name': 'KIU Health Check',
                'success': False,
                'error': str(e)
            })
        
        # Test 2: Buscar vuelos CCS-PMV para mañana
        try:
            VENEZUELA_TZ = timezone(timedelta(hours=-4))
            tomorrow = (datetime.now(VENEZUELA_TZ) + timedelta(days=1)).strftime('%Y-%m-%d')
            flights = kiu_service.search_flights('CCS', 'PMV', tomorrow)
            results['tests'].append({
                'name': f'Search Flights CCS-PMV {tomorrow}',
                'success': flights.get('success', False),
                'flights_found': len(flights.get('data', {}).get('departureFlight', [])) if flights.get('success') else 0,
                'error': flights.get('error') if not flights.get('success') else None
            })
        except Exception as e:
            results['tests'].append({
                'name': 'Search Flights',
                'success': False,
                'error': str(e)
            })
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Error en diagnóstico: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/webhook', methods=['GET', 'POST', 'OPTIONS'])
def webhook():
    """
    Webhook principal para recibir mensajes de WATI
    Acepta GET (verificación), POST (mensajes) y OPTIONS (CORS preflight)
    """
    # Manejar CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        return response, 200
    
    # Manejar verificación GET
    if request.method == 'GET':
        challenge = request.args.get('challenge', request.args.get('hub.challenge', 'verified'))
        return challenge, 200
    
    # Manejar POST (mensajes de WATI)
    global processed_messages
    
    try:
        # Obtener datos del webhook
        data = request.json
        
        # Extraer información del mensaje
        if not data:
            return jsonify({'status': 'error', 'message': 'No data received'}), 400
        
        # Verificar si es un mensaje propio (del bot) - ignorar
        if data.get('owner') == True:
            return jsonify({'status': 'ignored', 'reason': 'own_message'}), 200
        
        # Verificar mensaje duplicado usando whatsappMessageId
        message_id = data.get('whatsappMessageId', '')
        if message_id:
            # 1. Ya procesado completamente
            if message_id in processed_messages:
                logger.debug(f"Ignorando mensaje ya procesado: {message_id}")
                return jsonify({'status': 'ignored', 'reason': 'already_processed'}), 200
            
            # 2. Actualmente en proceso (evitar concurrencia por reintentos de WATI)
            if message_id in processing_messages:
                logger.info(f"Ignorando reintento concurrente: {message_id}")
                return jsonify({'status': 'ignored', 'reason': 'already_processing'}), 200
            
            # Agregar a proceso
            processing_messages.add(message_id)
        
        # *** FILTRO DE MENSAJES ANTIGUOS ***
        # Ignorar mensajes que tengan más de 60 segundos de antigüedad
        message_timestamp = data.get('timestamp', '')
        if message_timestamp:
            try:
                msg_time = int(message_timestamp)
                current_time = int(datetime.now().timestamp())
                age_seconds = current_time - msg_time
                
                if age_seconds > 60:  # Mensaje de más de 60 segundos
                    logger.info(f"Ignorando mensaje antiguo ({age_seconds}s): {data.get('text', '')[:30]}...")
                    return jsonify({'status': 'ignored', 'reason': 'old_message'}), 200
            except (ValueError, TypeError):
                pass  # Si no se puede parsear, continuar
        
        text_preview = (data.get('text') or '')[:50]
        logger.info(f"Procesando: '{text_preview}...' de {data.get('waId', 'unknown')}")
        
        # WATI puede enviar diferentes estructuras según el tipo de evento
        phone = None
        message_text = None
        media_url = None
        message_type = data.get('type', 'text')
        
        # Intentar extraer datos según diferentes estructuras de WATI
        if 'waId' in data:
            phone = data.get('waId', '')
        elif 'senderPhone' in data:
            phone = data.get('senderPhone', '')
        elif 'from' in data:
            phone = data.get('from', '')
        
        # Extraer mensaje de texto
        if 'text' in data and data.get('text'):
            message_text = data.get('text', '')
        elif 'body' in data:
            message_text = data.get('body', '')
        elif 'message' in data:
            if isinstance(data['message'], str):
                message_text = data['message']
            elif isinstance(data['message'], dict):
                message_text = data['message'].get('text', '') or data['message'].get('body', '')
        
        # Detectar si es una imagen (foto de cédula)
        if message_type == 'image' or data.get('type') == 'image':
            # Es una imagen - extraer URL de varios campos posibles
            logger.info(f"Imagen detectada. Campos de data: {list(data.keys())}")
            
            # Buscar en varios campos posibles de WATI
            media_url = data.get('data')  # WATI pone la URL de la imagen en 'data'
            if not media_url:
                media_url = data.get('mediaUrl')
            if not media_url:
                media_url = data.get('media_url')
            if not media_url and 'media' in data:
                media_url = data.get('media', {}).get('url')
            if not media_url:
                media_url = data.get('url')
            if not media_url:
                media_url = data.get('imageUrl')
            if not media_url:
                media_url = data.get('mediaData', {}).get('url') if isinstance(data.get('mediaData'), dict) else None
            
            # Si no encontramos URL directa, buscar recursivamente en el payload
            if not media_url:
                import json
                data_str = json.dumps(data)
                logger.info(f"Datos completos de imagen: {data_str[:1000]}...")
            
            logger.info(f"Imagen detectada de {phone}: {media_url}")
        
        
        # Verificar que tenemos los datos necesarios
        if not phone:
            logger.warning("No se pudo extraer número de teléfono")
            return jsonify({'status': 'error', 'message': 'No phone number found'}), 400
        
        if not message_text and not media_url:
            logger.warning("No se pudo extraer mensaje ni media")
            return jsonify({'status': 'ok', 'message': 'No message content'}), 200
        
        logger.info(f"Procesando mensaje de {phone}: {message_text or '(media)'}")
        
        # Determinar qué bot usar basado en el mensaje de activación
        result = None
        
        # Prioridad 1: Bot de Agentes
        if message_text and message_text.lower().strip() in ['cervo agent', 'agent panel', 'panel agente']:
            result = agent_bot.handle_message(
                phone=phone,
                message=message_text or '',
                media_url=media_url
            )
        # Prioridad 2: Bot de IA
        elif message_text and message_text.lower().strip() in ['cervo ai', 'agente cervo', 'cervo ia']:
            result = gemini_agent_bot.handle_message(
                phone=phone,
                message=message_text or '',
                media_url=media_url
            )
        else:
            # Verificar modo activo
            from session_manager import session_manager
            session = session_manager.get_session(phone)
            
            if session.is_active and session.data.get('mode') == 'agent':
                # Modo agente activo
                result = agent_bot.handle_message(
                    phone=phone,
                    message=message_text or '',
                    media_url=media_url
                )
            elif session.is_active and session.data.get('mode') == 'ai':
                # Modo AI activo
                result = gemini_agent_bot.handle_message(
                    phone=phone,
                    message=message_text or '',
                    media_url=media_url
                )
            else:
                # Usar bot de comandos por defecto
                result = cervo_bot.handle_message(
                    phone=phone,
                    message=message_text or '',
                    media_url=media_url
                )
        
        if result is not None:
            # Marcar como procesado definitivamente
            if message_id:
                processed_messages.add(message_id)
                if message_id in processing_messages:
                    processing_messages.remove(message_id)
                
                # Limpiar cache si es muy grande
                if len(processed_messages) > MAX_CACHE_SIZE:
                    processed_messages = set(list(processed_messages)[-500:])
        else:
            # Si fue ignorado (modo testing), igual quitar de procesando
            if message_id and message_id in processing_messages:
                processing_messages.remove(message_id)
        
        return jsonify({
            'status': 'success',
            'response': result.get('response', '') if result else '',
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}", exc_info=True)
        # Quitar de procesando en caso de error para permitir reintentos manuales
        if message_id and message_id in processing_messages:
            processing_messages.remove(message_id)
            
        return jsonify({
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/test', methods=['POST'])
def test_message():
    """
    Endpoint de prueba para simular mensajes
    """
    try:
        data = request.json or {}
        phone = data.get('phone', '584121234567')
        message = data.get('message', 'hola')
        media_url = data.get('media_url')
        
        logger.info(f"Test message: {phone} -> {message}")
        
        # Determinar qué bot usar
        bot_type = data.get('bot_type', 'command')  # 'command', 'ai', o 'agent'
        
        result = None
        if bot_type == 'agent':
            result = agent_bot.handle_message(
                phone=phone,
                message=message,
                media_url=media_url
            )
        elif bot_type == 'ai':
            result = gemini_agent_bot.handle_message(
                phone=phone,
                message=message,
                media_url=media_url
            )
        else:
            result = cervo_bot.handle_message(
                phone=phone,
                message=message,
                media_url=media_url
            )
        
        # Manejar caso donde result es None
        if result is None:
            result = {"success": False, "response": "Bot no activado o mensaje ignorado"}
        
        return jsonify({
            'status': 'success',
            'result': result,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error en test: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/test-auto', methods=['GET'])
def test_auto():
    """
    Interfaz de test automático - se ejecuta sin presionar Enter
    """
    try:
        with open(os.path.join(APP_DIR, 'test_auto.html'), 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return jsonify({'error': 'test_auto.html no encontrado'}), 404


@app.route('/test-ui', methods=['GET'])
def test_ui():
    """
    Interfaz web simple para probar el chatbot
    """
    html = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🦌 Cervo Bot - Test UI</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1c2e 0%, #2d3561 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            width: 100%;
            max-width: 500px;
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 25px 50px rgba(0,0,0,0.3);
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            text-align: center;
            color: white;
        }
        .header h1 {
            font-size: 1.8rem;
            margin-bottom: 5px;
        }
        .header p {
            opacity: 0.9;
            font-size: 0.9rem;
        }
        .chat-container {
            height: 400px;
            overflow-y: auto;
            padding: 20px;
            background: #1a1c2e;
        }
        .message {
            margin-bottom: 15px;
            padding: 12px 16px;
            border-radius: 15px;
            max-width: 85%;
            word-wrap: break-word;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .user-message {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            margin-left: auto;
            border-bottom-right-radius: 5px;
        }
        .bot-message {
            background: rgba(255,255,255,0.1);
            color: #e0e0e0;
            border-bottom-left-radius: 5px;
            white-space: pre-wrap;
        }
        .input-container {
            padding: 20px;
            background: rgba(0,0,0,0.3);
            display: flex;
            gap: 10px;
        }
        input {
            flex: 1;
            padding: 15px;
            border: none;
            border-radius: 25px;
            background: rgba(255,255,255,0.1);
            color: white;
            font-size: 1rem;
            outline: none;
        }
        input::placeholder {
            color: rgba(255,255,255,0.5);
        }
        button {
            padding: 15px 25px;
            border: none;
            border-radius: 25px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 1rem;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .phone-input {
            padding: 10px 20px;
            background: rgba(0,0,0,0.2);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .phone-input label {
            color: rgba(255,255,255,0.7);
            font-size: 0.85rem;
        }
        .phone-input input {
            padding: 8px 15px;
            font-size: 0.9rem;
        }
        .status {
            text-align: center;
            padding: 5px;
            font-size: 0.8rem;
            color: #4ade80;
            background: rgba(74, 222, 128, 0.1);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🦌 Cervo Bot</h1>
            <p>Chatbot de Reservaciones de Vuelos - Venezuela</p>
        </div>
        <div class="status">⚡ MODO TESTING ACTIVO</div>
        <div class="phone-input">
            <label>📱 Teléfono:</label>
            <input type="text" id="phone" value="584121234567" placeholder="Número de prueba">
        </div>
        <div class="chat-container" id="chat">
            <div class="message bot-message">
                🦌 ¡Bienvenido al panel de pruebas de Cervo Bot!
                
Escribe "hola" para comenzar.
            </div>
        </div>
        <div class="input-container">
            <input type="text" id="message" placeholder="Escribe tu mensaje..." onkeypress="if(event.key==='Enter')sendMessage()">
            <button onclick="sendMessage()">Enviar</button>
        </div>
    </div>
    
    <script>
        async function sendMessage() {
            const messageInput = document.getElementById('message');
            const phoneInput = document.getElementById('phone');
            const chat = document.getElementById('chat');
            const message = messageInput.value.trim();
            
            if (!message) return;
            
            // Mostrar mensaje del usuario
            chat.innerHTML += `<div class="message user-message">${message}</div>`;
            messageInput.value = '';
            chat.scrollTop = chat.scrollHeight;
            
            try {
                const response = await fetch('/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        phone: phoneInput.value,
                        message: message 
                    })
                });
                
                const data = await response.json();
                const botResponse = data.result?.response || 'Error: Sin respuesta';
                
                // Mostrar respuesta del bot
                chat.innerHTML += `<div class="message bot-message">${botResponse}</div>`;
                chat.scrollTop = chat.scrollHeight;
            } catch (error) {
                chat.innerHTML += `<div class="message bot-message">❌ Error: ${error.message}</div>`;
            }
        }
    </script>
</body>
</html>
    """
    return html


if __name__ == '__main__':
    print("""
    ============================================================
    
       CERVO BOT - Chatbot de Reservaciones de Vuelos
    
       Desarrollado para Venezuela
       
       [BOT] Modo Comandos: Escribe "cervo bot"
       [AI] Modo IA (Gemini): Escribe "cervo ai"
       [AGENT] Modo Agente: Escribe "cervo agent"
    
    ============================================================
    """)
    
    logger.info(f"Iniciando servidor en puerto {Config.FLASK_PORT}")
    logger.info(f"Modo Testing: {Config.TESTING_MODE}")
    logger.info(f"Telefono permitido: {Config.ALLOWED_PHONE}")
    
    app.run(
        host='0.0.0.0',
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG
    )
