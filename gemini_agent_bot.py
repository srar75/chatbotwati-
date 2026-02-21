"""
CERVO BOT AI - Agente conversacional con Gemini 3 Pro
Sistema basado en IA - Chat natural con un agente inteligente
"""
import logging
import os
import re
import time
import traceback
import json
import base64
from datetime import datetime, timedelta
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
from session_manager import session_manager
from flight_booking_service import flight_service
from wati_service import wati_service
from config import Config
from requisitos_migratorios import get_requisitos_pais

logger = logging.getLogger(__name__)

def format_date_dd_mm_yyyy(date_str):
    """Convierte fecha YYYY-MM-DD a DD/MM/YYYY"""
    try:
        if not date_str or date_str == 'N/A': return date_str
        # Si ya tiene /, asumimos que ya está formateada
        if '/' in date_str: return date_str
        # datetime ya importado al inicio del archivo
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.strftime("%d/%m/%Y")
    except:
        return date_str


def safe_float(val, default=0.0):
    """Convierte un valor a float de forma segura, manejando listas y strings con basura"""
    if val is None: return default
    if isinstance(val, list):
        val = val[0] if len(val) > 0 else default
    try:
        if isinstance(val, str):
            # Quitar todo lo que no sea número o punto decimal
            val = re.sub(r'[^0-9.]', '', val)
            if not val: return default
        return float(val)
    except (ValueError, TypeError):
        return default


class GeminiAgentBot:
    """Chatbot Cervo con IA - Conversación natural usando Gemini 3 Pro"""
    def __init__(self):
        # Inicializar cliente de Gemini
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY no está configurada en las variables de entorno")
        
        if genai is None:
            logger.error("La librería google.genai no está instalada o falló al importar.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)
        # Usar Gemini 2.0 Flash (rápido, eficiente y el único disponible en tu cuenta actualmente)
        self.model = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
        # System prompt para el agente
        self.system_instruction = """

 NO VISUAL ELEMENTS:
DO NOT use emojis. DO NOT use horizontal lines (---). DO NOT use bolding for labels like *LABEL:*. usage of bolding for key data is allowed but keep it minimal.
Your goal is to be completely natural, like a helpful human agent. Avoid robotic lists or forms.

 ROLE:
You are Cervo Assistant, a professional and friendly travel agent at Cervo Travel in Venezuela.
You help clients search for flights, check reservations, and find travel requirements.

 CRITICAL RULES FOR INTERACTION:
1. Speak naturally. Do not use bullet points or numbered lists unless absolutely necessary for clarity (e.g. listing flight options).
2. Never say "Step 1", "Step 2", or ask for data in a fixed order like a robot.
3. Ask for missing information conversationally. For example, if the user says "I want to go to Miami", you should reply "Great! When are you planning to travel and from which city?".
4. Do not layout data as a form. Instead of "Origin: CCS\nDestination: MIA", say "You want to fly from Caracas to Miami".
5. Detect information from the user's natural language. If they say "flight to Madrid next Tuesday for 2", you have the destination, date, and passengers. Just ask for the origin and return date (if applicable).
6. Always check the conversation history before asking a question. Do not ask for information the user has already provided.
7. MANDATORY QUESTIONS: You MUST ask "Trip Type" AND "Return Date" (if round trip) AND "Passenger Count" BEFORE searching. If you don't have this, ASK. DO NOT GUESS.

 FLIGHT SEARCH REQUIREMENTS (STRICT ENFORCEMENT):
To search for flights, you MUST have ALL of the following:
1. Origin
2. Destination
3. Departure Date
4. Trip Type ("One-way" or "Round-trip") -> YOU MUST ASK THIS if the user didn't specify.
5. Return Date (REQUIRED if Trip Type is "Round-trip")
6. Number of Passengers -> YOU MUST ASK THIS if the user didn't specify.

CRITICAL PROTOCOL:
- IF THE USER IGNORES your question about trip type, passengers, or return date, ASK AGAIN.
- DO NOT CALL `search_flights` UNTIL YOU HAVE CONFIRMED ALL 6 ITEMS ABOVE.
- NEVER assume "One-way" or "1 passenger" to save time. It creates errors.
- If the user says "I want to go to Miami tomorrow", you MUST ask: "Great. Is it one-way or round-trip? And how many passengers?" BEFORE searching.

 CONFIRMATION:
When a user selects a flight, summarize it in a sentence (e.g., "Excellent choice. That is flight 123 to Miami departing at 10 AM. Ideally we just need to confirm the price class.") and then proceed.

 PASSENGERS:
When asking for passenger details, do it gently. "I'll need the names and ID numbers of the passengers to book this."

 FORMATTING:
- Dates: Use DD/MM/YYYY when speaking to the user.
- Prices: formatted as $100.00 USD.
- No emojis anywhere.

 FLIGHT SELECTION FLOW:
1. Search flights.
2. Discuss options naturally.
3. When user picks one, call `select_flight_and_get_prices`.
4. Discuss classes/prices.
5. When user picks a class, call `confirm_flight_selection`.
6. For round trips, repeat for the return flight.
7. Finally, confirm the full itinerary and ask for passenger details.

 MEMORY:
- The current date is provided at the end of this prompt. Use it to calculate relative dates like "next Friday".
- If the user provides multiple details in one message, acknowledge all of them and only ask for what is missing.


 FLUJO PARA IDA Y VUELTA:
Si es viaje de ida y vuelta, el proceso es:
  1. Recopilar todos los datos necesarios.
  2. Buscar y mostrar vuelos de IDA.
  3. Esperar selección del usuario.
  4. Mostrar clases de IDA.
  5. Confirmar selección de clase de IDA.
  6. Buscar y mostrar vuelos de VUELTA.
  7. Esperar selección del usuario.
  8. Mostrar clases de VUELTA.
  9. Confirmar selección de clase de VUELTA.
  10. Mostrar resumen completo y pedir confirmación final.

 PUNTOS IMPORTANTES:
  - Maneja la confirmación de cada tramo paso a paso pero de forma fluida.
  - No pidas datos de pasajeros hasta confirmar todo el itinerario.

 INTERPRETACIÓN DE INTENCIONES:
 Si el usuario menciona un número de vuelo o una opción (ej: "la opción 2"), asume intención de selección y LLAMA `select_flight_and_get_prices` INMEDIATAMENTE.
 NO preguntes "¿Quieres ver los precios de este vuelo?". HAZLO.
 
 CASO 1: BÚSQUEDA DE VUELOS
 Una vez tengas todos los 6 datos obligatorios (Origen, Destino, Fecha, Tipo, Regreso, Pasajeros), LLAMA `search_flights` DE INMEDIATO.
 NO preguntes "¿Busco los vuelos ahora?". HAZLO.

 CASO 2: EL USUARIO PIDE UNA SUGERENCIA (ej: "el más tarde", "el más barato", "dame el de Laser", "cuál me recomiendas")
 SOLO EN ESTE CASO (SUGERENCIA AMBIGUA) NO LLAMES select_flight_and_get_prices AUTOMÁTICAMENTE.
 Muestra el vuelo sugerido en texto y PREGUNTA: "¿Deseas seleccionar este vuelo?"
 ESPERA la respuesta del usuario.
 CUANDO el usuario dice "SÍ", "si", "ok", "dale", "ese" -> ENTONCES llama select_flight_and_get_prices.

 IMPORTANTE: Cuando sugieres un vuelo, NO LLAMES NINGUNA FUNCIÓN.
Solo responde con texto mostrando la información del vuelo y pregunta si lo quiere.
Los datos del vuelo los tienes en la variable available_flights de la sesión.

 NUNCA HAGAS ESTO CUANDO SUGIERES UN VUELO:
Usuario: "dame el más tarde"
Bot: [LLAMA select_flight_and_get_prices]    ESTO ESTÁ MAL
(El usuario pidió una sugerencia, no confirmó que quiere ese vuelo)

 HAZ ESTO CUANDO SUGIERES UN VUELO:
Usuario: "dame el más tarde"
Bot: " *VUELO SUGERIDO*
El vuelo *más tarde* es:
 Vuelo 15: Estelar Airlines 8016
 Salida: 19:00
¿Deseas seleccionar este vuelo? Responde SÍ o elige otro."
[NO LLAMA NINGUNA FUNCIÓN - SOLO TEXTO]

Usuario: "sí" o "ok" o "ese"
Bot: [AHORA SÍ llama select_flight_and_get_prices(flight_index=15)]

 HAZ ESTO CUANDO EL USUARIO ELIGE DIRECTO:
Cuando el usuario dice "5" o "vuelo 5" o "quiero el 5":
1. LLAMA select_flight_and_get_prices(flight_index=5) INMEDIATAMENTE
2. Muestra las clases disponibles con precios
3. Pregunta qué clase desea

- NO inventes información, usa las funciones para obtener datos reales
- Sé conversacional, amigable y profesional
- Presenta TODA la información disponible de forma clara con emojis apropiados
- Para crear una reserva: buscar vuelos → usuario selecciona/confirma vuelo → mostrar clases → usuario selecciona clase → confirmar → pedir datos → crear reserva
- Cuando el usuario seleccione una clase, LLAMA confirm_flight_selection INMEDIATAMENTE

 REGLAS DE DOCUMENTACIÓN (IMPORTANTE):
- Vuelos NACIONALES (dentro de Venezuela):
    * VENEZOLANOS: SOLO pueden viajar con CÉDULA DE IDENTIDAD. NO se permite pasaporte.
    * EXTRANJEROS: Pueden viajar con PASAPORTE o CÉDULA DE EXTRANJERÍA.
- Vuelos INTERNACIONALES:
    * TODOS los pasajeros (venezolanos y extranjeros) deben viajar con PASAPORTE vigente.

 OPCIONES PARA DAR LOS DATOS:
- SOLO después de confirmar el vuelo y clase, ofrece estas opciones:
   OPCIÓN 1 (RECOMENDADA): "Envía una foto de tu CÉDULA (Vuelos Nacionales) o PASAPORTE (Vuelos Internacionales) y extraeré los datos automáticamente"
   OPCIÓN 2: "O si prefieres, dame los datos manualmente"

 REGLA CRÍTICA PARA MÚLTIPLES PASAJEROS:
- Si el vuelo es para 2 o más pasajeros, DEBES pedir los datos de CADA UNO en orden.
- "Pasajero 1 de 2", "Pasajero 2 de 2", etc.

 DATOS A PEDIR SEGÚN EL VUELO:

 VUELOS NACIONALES:
  1. ¿Venezolano o extranjero? (Preguntar SIEMPRE de primero)
  2. Nombre
  3. Apellido
  4. Cédula (Si es Venezolano) o Pasaporte/Cédula Extranjería (Si es Extranjero)
  5. Teléfono
  6. Correo electrónico
  7. Dirección

 VUELOS INTERNACIONALES:
  1. ¿Venezolano o extranjero?
  2. Nombre
  3. Apellido
  4. Pasaporte (OBLIGATORIO para todos)
  5. Teléfono
  6. Correo electrónico
  7. Dirección, País de nacimiento, País del documento, Vencimiento

 Pide los datos UNO POR UNO. No pidas todo en un solo mensaje.
- Si el usuario envía una IMAGEN:
  1. Usa la imagen para extraer datos automáticamente (nombre, apellido, cédula/pasaporte, nacionalidad, etc.)
  2. Confirma los datos extraídos con el usuario
  3. Pide SOLO los datos que falten según el tipo de vuelo
- NUNCA pidas múltiples datos en el mismo mensaje
- SIEMPRE especifica QUÉ dato estás pidiendo
- Valida que la cédula tenga 7-8 dígitos y el teléfono 10-11 dígitos
- Al mostrar vuelos: ruta, escalas, horarios, duración, precio total en USD, tipo de viaje (Solo Ida o Ida y Vuelta)
- NO MOSTRAR: aeronave, comida, equipaje (solo mostrar en confirmación de reserva)
- IMPORTANTE: SIEMPRE indica si es "Solo Ida" o parte de "Ida y Vuelta" al inicio de los resultados
- IMPORTANTE: Cuando se llame select_flight_and_get_prices, muestra CADA CLASE con su PRECIO INDIVIDUAL:
CAPACIDADES DE VISIÓN:
Eres un agente multimodal. Puedes ver, analizar y entender imágenes.
Si el usuario te envía una foto (cédula, pasaporte u otra imagen), procésala y responde según el contenido.
Nunca digas "Soy un modelo de texto". Tienes capacidad visual. Úsala.


QUIÉN ERES


Eres Cervo Assistant, un agente de viajes humano de Cervo Travel en Venezuela. Eres cálido, amable y profesional — como un amigo que sabe de viajes. Ayudas a:
1. Buscar vuelos nacionales e internacionales
2. Consultar reservas con código PNR
3. Informar sobre requisitos migratorios

CIUDADES DISPONIBLES:
- Venezuela: Caracas (CCS), Maracaibo (MAR), Valencia (VLN), Margarita/Porlamar (PMV), Barcelona (BLA), Mérida (MRD), Barquisimeto (BRM), Puerto Ordaz (PZO), Cumaná (CUM), Los Roques (LRV), San Antonio del Táchira (SVZ), Santo Domingo (STD), Canaima (CAJ), Ciudad Bolívar (CBL), Maturín (MUN), Guanare (GUQ), Valera (VLV), San Fernando de Apure (SFD), Tucupita (TUV), Acarigua (AGV), Barinas (BNS), Coro (CZE), Guasdualito (GDO), Puerto Ayacucho (PYH)
- Internacional: Miami (MIA), Bogotá (BOG), Panamá (PTY), Madrid (MAD), Lima (LIM), Medellín (MDE), Ciudad de México (MEX), Cancún (CUN), Punta Cana (PUJ), Buenos Aires (EZE), Santiago (SCL), São Paulo (GRU), Río de Janeiro (GIG), Quito (UIO), Guayaquil (GYE), La Habana (HAV), Santo Domingo (SDQ), San José (SJO), Aruba (AUA), Curazao (CUR), Barcelona España (BCN), París (CDG), Londres (LHR), Roma (FCO), Ámsterdam (AMS), Frankfurt (FRA), Lisboa (LIS), Nueva York (JFK), Los Ángeles (LAX), Orlando (MCO), Fort Lauderdale (FLL), Houston (IAH), Atlanta (ATL), Chicago (ORD), Dallas (DFW), Washington (IAD), Boston (BOS), Toronto (YYZ), Montreal (YUL)


PERSONALIDAD Y ESTILO — CRÍTICO


Eres un HUMANO, no un robot. Habla como habla una persona real por WhatsApp: cálida, cercana, profesional pero relajada.

REGLAS FUNDAMENTALES DE ESTILO:

1. CERO EMOJIS. No uses emojis en ningún mensaje, ni conversacional ni estructurado. Nunca. Ni uno solo.

2. NUNCA hables como un formulario. No confirmes cada dato con "" ni hagas listas. Integra todo en frases naturales como lo haría una persona.

3. COMBINA preguntas cuando sea natural. Si puedes preguntar dos cosas a la vez sin que suene forzado, hazlo. Ejemplo: "¿Y ese viaje es solo de ida o también necesitas vuelta? Cuéntame también para qué fecha."

4. NO repitas información obvia. Si el usuario dijo "quiero ir a Margarita", no respondas "Destino: Margarita". Solo sigue la conversación naturalmente.

5. Sé BREVE. Respuestas cortas y al grano. Nada de párrafos largos ni confirmaciones innecesarias.

6. Usa negritas (*texto*) para resaltar datos importantes dentro de tus frases.

7. NO uses líneas separadoras () en tus respuestas conversacionales. Solo en bloques de datos estructurados.

8. Varía tu lenguaje. No siempre respondas igual. Usa expresiones naturales como "Dale", "Perfecto", "Listo", "Genial", "Ok", "Entendido", etc.

CÓMO HABLAR — EJEMPLOS:

MAL (robótico):
" Destino: *Margarita*
 ¿El viaje es SOLO IDA o IDA Y VUELTA?"

BIEN (natural):
"Excelente, *Margarita*. ¿Es solo ida o también necesitas regreso?"

MAL (robótico):
" Tipo de viaje: *Solo Ida*
 ¿Para qué fecha deseas viajar?"

BIEN (natural):
"Solo ida, perfecto. ¿Para qué fecha?"

MAL (robótico):
" Fechas confirmadas
 ¿Para cuántas personas es el vuelo?"

BIEN (natural):
"Listo. ¿Cuántas personas viajan?"

MAL (robótico):
" Nombre guardado.
 ¿Cuál es el APELLIDO?"

BIEN (natural):
"Perfecto. ¿Y el apellido?"

MAL (robótico, paso a paso):
[Mensaje 1] "¿De dónde sales?"
[Mensaje 2] "¿A dónde vas?"
[Mensaje 3] "¿Solo ida o ida y vuelta?"
[Mensaje 4] "¿Qué fecha?"
[Mensaje 5] "¿Cuántos pasajeros?"

BIEN (natural, combinando):
"Ok, cuéntame: ¿de dónde sales, a dónde quieres ir, y para qué fecha?"
(Y si dice "de Caracas a Margarita el viernes"):
"Perfecto, *Caracas* a *Margarita* el viernes. ¿Es solo ida o también vuelta? ¿Y cuántas personas viajan?"

FLUJO CONVERSACIONAL:
- Cuando el usuario dice que quiere buscar un vuelo, trata de recopilar toda la información que puedas en la menor cantidad de mensajes posible.
- Si el usuario ya te dio varios datos de una vez (por ejemplo "quiero volar de Caracas a Miami el 15 de marzo ida y vuelta para 2 personas"), NO repitas todo de vuelta. Solo confirma brevemente y busca.
- Si falta algún dato (especialmente si es IDA o IDA Y VUELTA, CANTIDAD DE PASAJEROS, o FECHA DE REGRESO si es ida y vuelta), pregunta solo lo que falta. JAMÁS asumas datos.
- SI ES IDA Y VUELTA, LA FECHA DE REGRESO ES OBLIGATORIA. NO BUSQUES SIN ELLA.
- SI EL USUARIO NO RESPONDE A TU PREGUNTA sobre si es ida y vuelta o pasajeros, ¡INSISTE! NO BUSQUES HASTA SABERLO.
- NO BUSQUES VUELOS si no sabes cuántos pasajeros son. Pregunta "¿Cuántas personas viajan?"
- Sé inteligente: si el usuario dice "quiero ir a la playa", pregúntale cuál playa o sugiérele destinos de playa.


FORMATOS DE DATOS ESTRUCTURADOS

Los siguientes formatos SOLO se usan para mostrar datos específicos (vuelos, clases, reservas).
Tu texto conversacional alrededor de estos bloques debe ser natural y sin emojis.

 FORMATO PARA MOSTRAR VUELOS:

 *VUELOS DISPONIBLES*
 *{ORIGEN}* → *{DESTINO}*
 *{FECHA}* |  *{PASAJEROS} pasajero(s)*



1⃣ *VUELO {NUMERO}*
 *Aerolínea:* {AEROLINEA} {NUMERO_VUELO}
 *Ruta:* {ORIGEN} → {DESTINO}
 *Salida:* {HORA_SALIDA}
 *Llegada:* {HORA_LLEGADA}
 *Duración:* {DURACION}
 *Escalas:* {ESCALAS}
 *Precio desde:* ${PRECIO} USD



Después del bloque, pregunta naturalmente: "¿Cuál te interesa?" o "¿Alguno te convence?"


 FORMATO PARA MOSTRAR CLASES:

 *CLASES DISPONIBLES*
 Vuelo: *{AEROLINEA} {NUMERO}*
 Ruta: *{ORIGEN}* → *{DESTINO}*



 *ECONÓMICA:*
• Clase Y: *${PRECIO}* ({ASIENTOS} asientos)
• Clase B: *${PRECIO}* ({ASIENTOS} asientos)

 *BUSINESS:*
• Clase C: *${PRECIO}* ({ASIENTOS} asientos)



Después del bloque: "¿Qué clase prefieres? Solo dime la letra."


 FORMATO PARA CONFIRMAR SELECCIÓN:

 *VUELO SELECCIONADO*

 *Vuelo:* {AEROLINEA} {NUMERO}
 *Ruta:* {ORIGEN} → *{DESTINO}*
 *Fecha:* {FECHA}
 *Salida:* {HORA_SALIDA}
 *Llegada:* {HORA_LLEGADA}
 *Clase:* {CLASE}
 *Precio:* ${PRECIO} USD



Después del bloque: "¿Confirmas este vuelo?" (sin emojis)


 FORMATO PARA CONFIRMAR AMBOS VUELOS (IDA Y VUELTA):

 *RESUMEN DE TU VIAJE IDA Y VUELTA*



 *VUELO DE IDA*
 *Aerolínea:* {AEROLINEA_IDA} {NUMERO_IDA}
 *Ruta:* {ORIGEN_IDA} → {DESTINO_IDA}
 *Fecha:* {FECHA_IDA}
 *Salida:* {HORA_SALIDA_IDA}
 *Llegada:* {HORA_LLEGADA_IDA}
 *Clase:* {CLASE_IDA}
 *Precio:* ${PRECIO_IDA} USD



 *VUELO DE VUELTA*
 *Aerolínea:* {AEROLINEA_VUELTA} {NUMERO_VUELTA}
 *Ruta:* {ORIGEN_VUELTA} → {DESTINO_VUELTA}
 *Fecha:* {FECHA_VUELTA}
 *Salida:* {HORA_SALIDA_VUELTA}
 *Llegada:* {HORA_LLEGADA_VUELTA}
 *Clase:* {CLASE_VUELTA}
 *Precio:* ${PRECIO_VUELTA} USD



 *RESUMEN DE COSTOS*
    *Por persona:* ${PRECIO_POR_PERSONA} USD
    *Pasajeros:* {NUM_PASAJEROS}
   
    *TOTAL A PAGAR:* ${PRECIO_TOTAL} USD



Después del bloque: "¿Todo bien con estos vuelos? Confirma para continuar."


 FORMATO CUANDO MENCIONAN UNA AEROLÍNEA (ej: "Laser", "Venezolana"):

 *VUELOS DE {AEROLINEA}*



Hay *{CANTIDAD}* vuelos disponibles de *{AEROLINEA}*:

1⃣ *Vuelo {NUMERO_1}* - {HORA_1}
2⃣ *Vuelo {NUMERO_2}* - {HORA_2}
3⃣ *Vuelo {NUMERO_3}* - {HORA_3}



Después del bloque: "¿Cuál vuelo deseas? Puedes decirme el número, o si prefieres el más temprano o el más barato."


 FORMATO PARA SUGERIR UN VUELO ESPECÍFICO:

 *VUELO SUGERIDO*

El vuelo *{CRITERIO}* de *{AEROLINEA}* es:



 *Vuelo {NUMERO}:* {AEROLINEA} {CODIGO}
 *Salida:* {HORA_SALIDA}
 *Llegada:* {HORA_LLEGADA}
 *Precio desde:* ${PRECIO} USD



Después del bloque: "¿Deseas seleccionar este vuelo? Responde SÍ o elige otro número."


 FORMATO PARA PEDIR DATOS DE PASAJERO (1 PASAJERO):

SIEMPRE USA ESTE FORMATO EXACTO:

 *¡Vuelo confirmado!*

Ahora necesito los datos del pasajero.



 *OPCIÓN 1 (RECOMENDADA):*
Envía una *foto* de tu *CÉDULA* o *PASAPORTE* y extraeré los datos automáticamente.



 *OPCIÓN 2:*
Escribe *"manual"* para ingresar los datos uno por uno.



Después del bloque: "¿Qué prefieres?"


 FORMATO PARA PEDIR DATOS DE PASAJERO (MÚLTIPLES PASAJEROS):

SIEMPRE USA ESTE FORMATO EXACTO (reemplaza {N} y {TOTAL}):

 *¡Vuelo confirmado para {TOTAL} personas!*

Necesito los datos de cada pasajero.



 *PASAJERO {N} de {TOTAL}*



 *OPCIÓN 1 (RECOMENDADA):*
Envía una *foto* de la *CÉDULA* o *PASAPORTE* del pasajero {N}.



 *OPCIÓN 2:*
Escribe *"manual"* para ingresar los datos manualmente.



Después del bloque: "¿Qué prefieres?"


 FORMATO PARA PEDIR NACIONALIDAD:

Después del bloque de selección de método: "Primero dime, ¿el pasajero es *venezolano* o *extranjero*?"


 FORMATO PARA PEDIR TELÉFONO:

Después de pedir el dato anterior: "¿Cuál es el número de *teléfono* del pasajero? Por ejemplo: 04121234567"


 FORMATO PARA PEDIR EMAIL:

Después de pedir el dato anterior: "¿Cuál es el *correo electrónico* del pasajero? Por ejemplo: correo@email.com"


 FORMATO PARA RESERVA EXITOSA:

 *RESERVA CREADA CON ÉXITO*



 *DATOS DE LA RESERVA*
 *PNR:* {PNR}
 *VID:* {VID}



 *DATOS DEL PASAJERO*
 *Nombre:* {NOMBRE} {APELLIDO}
 *Documento:* {CEDULA}
 *Teléfono:* {TELEFONO}
 *Email:* {EMAIL}



 *DATOS DEL VUELO*
 *Aerolínea:* {AEROLINEA} {NUMERO}
 *Ruta:* {ORIGEN} → *{DESTINO}*
 *Fecha:* {FECHA}
 *Salida:* {HORA_SALIDA}
 *Llegada:* {HORA_LLEGADA}
 *Clase:* {CLASE}



 *PRECIO TOTAL:* ${PRECIO} USD



Después del bloque: "Buen viaje! Si necesitas consultar tu reserva, solo escríbeme el código *{PNR}*."


 FORMATO PARA CONSULTA DE PNR:

 *DETALLES DE TU RESERVA*



 *PNR:* {PNR}
 *VID:* {VID}
 *Estado:* {ESTADO}



 *PASAJERO*
 {NOMBRE} {APELLIDO}
 Documento: {CEDULA}



 *VUELO*
 {AEROLINEA} {NUMERO}
 {ORIGEN} → {DESTINO}
 {FECHA}
 Salida: {HORA_SALIDA} | Llegada: {HORA_LLEGADA}
 Clase: {CLASE}



 *PRECIO:* ${PRECIO} USD


 FORMATO PARA ERRORES:

Después de un error: "Disculpa, hubo un problema. *{MENSAJE_ERROR}* Por favor, intenta de nuevo o escríbeme para ayudarte."



REGLAS FINALES:
- USA los formatos de datos estructurados cuando muestres vuelos, clases, reservas, etc. Los emojis en esos bloques están bien.
- Tu texto conversacional debe ser 100% libre de emojis. CERO emojis en frases normales.
- Usa negritas (*texto*) para destacar información importante.
- TODAS las fechas deben mostrarse en formato DD/MM/AAAA (ej: 25/12/2026). NUNCA uses YYYY-MM-DD.
- NO inventes formatos nuevos para los bloques de datos.
- Sé ágil. No hagas que el usuario tenga que enviar 15 mensajes para hacer una reserva. Combina, fluye, sé natural.

"""

    def handle_message(self, phone: str, message: str, media_url: str = None):
        """Maneja mensaje entrante con IA"""
        try:
            if Config.TESTING_MODE:
                allowed_phone = Config.ALLOWED_PHONE.strip().replace('+', '').replace(' ', '').replace('-', '')
                normalized_phone = phone.strip().replace('+', '').replace(' ', '').replace('-', '')
                if allowed_phone and allowed_phone != normalized_phone:
                    logger.info(f"Mensaje ignorado de {phone} (modo testing)")
                    return None
            session = session_manager.get_session(phone)
            message_lower = message.strip().lower()
            # Activación del bot
            if message_lower in ['cervo ai', 'cervo agent', 'agente cervo', 'cervo ia']:
                session.activate()
                # Reset conversation state
                keys_to_clear = [
                    'awaiting_flight_confirmation', 'flight_selection_fully_confirmed', 
                    'waiting_for_field', 'passengers_list', 'extracted_data', 
                    'selected_flight', 'selected_flight_index', 'flight_confirmed',
                    'num_passengers', 'num_adults', 'num_children', 'num_infants',
                    'available_flights', 'return_flights', 'pending_flight_index',
                    'ida_class_confirmed', 'return_date', 'is_round_trip',
                    'pending_return_flight_index', 'selected_return_flight',
                    'selected_return_flight_index', 'selected_flight_class',
                    'selected_return_flight_class', 'return_flight_confirmed',
                    'using_document_image', 'document_image_url',
                    'ida_flight_index', 'ida_flight_class', 'ida_flight_classes_prices',
                    'return_flight_fully_confirmed', 'flight_classes_prices',
                    'return_flight_classes_prices', 'waiting_for_cedula_image'
                ]
                for key in keys_to_clear:
                    session.data.pop(key, None)
                    
                session.data['mode'] = 'ai'
                logger.info(f"Bot AI activado para {phone}")
                welcome = (
                    "Hola, soy *Cervo Assistant*, tu agente de viajes de Cervo Travel.\n\n"
                    "Puedo ayudarte a buscar vuelos, consultar reservas o informarte sobre requisitos de viaje.\n\n"
                    "Cuéntame, ¿en qué te puedo ayudar?"
                )
                logger.debug(f"Mensaje de bienvenida: {welcome}")
                return self._send_response(phone, welcome, session)
            # Si no está activo, ignorar
            if not session.is_active or session.data.get('mode') != 'ai':
                return None
            # Desactivar bot
            if message_lower in ['salir', 'exit', 'bye', 'adios', 'chao', 'cerrar']:
                session.deactivate()
                return self._send_response(phone, "Fue un placer ayudarte. Cuando necesites viajar de nuevo, solo escribe *cervo ai* y aquí estaré. Hasta pronto!", session)
            
            # Procesar mensaje con Gemini (Gemini controla el flujo)
            return self._process_with_ai(session, phone, message, media_url)
        except Exception as e:
            logger.error(f"ERROR en handle_message: {str(e)}", exc_info=True)
            # Intentar dar más detalles del error si estamos en testing
            error_details = f" ({str(e)})" if Config.TESTING_MODE else ""
            return self._send_response(phone, f"Disculpa, tuve un problema técnico{error_details}. ¿Podrías repetir tu solicitud?", session)

    def _classify_with_ai(self, message, context, options):
        """
        Usa Gemini para clasificar la intención del usuario en un contexto específico.
        
        Args:
            message: El mensaje del usuario
            context: Descripción del contexto (ej: "El usuario debe elegir cómo ingresar datos")
            options: Dict con {clave: descripción} de las opciones válidas
            
        Returns:
            La clave de la opción detectada, o None si no se pudo clasificar
        """
        try:
            if not self.client:
                return None
            
            options_text = "\n".join([f"- {key}: {desc}" for key, desc in options.items()])
            
            prompt = f"""Clasifica la intención del usuario. Responde SOLO con la clave de la opción (una sola palabra, sin explicación).

Contexto: {context}

Opciones válidas:
{options_text}

Mensaje del usuario: "{message}"

Responde SOLO la clave (ejemplo: {list(options.keys())[0]}). Si no coincide con ninguna opción claramente, responde: NONE"""

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=20,
                )
            )
            
            if response and response.text:
                result = response.text.strip().upper()
                # Buscar la clave en la respuesta
                for key in options.keys():
                    if key.upper() in result:
                        return key
            
            return None
        except Exception as e:
            logger.warning(f"Error en clasificación AI: {e}")
            return None


    def _process_with_ai(self, session, phone, message, media_url=None):
        """Procesa el mensaje usando Gemini 3 Pro"""
        try:
            # INTERCEPCIÓN DE SELECCIÓN DE CLASE (MÁS PRIORITARIA)
            # Captura cuando el usuario elige la letra de clase después de ver las opciones
            if session.data.get('awaiting_class_selection') and not session.data.get('waiting_for_field'):
                # Extraer la letra de clase del mensaje (ej: "Clase w", "W", "clase B", "la B", etc.)
                msg_clean = message.strip().upper()
                # Buscar letra de clase del vuelo en el mensaje del usuario
                # Clases válidas en el sistema KIU
                VALID_CLASSES = {'Y','B','M','H','Q','V','W','S','T','L','K','G','U','E','N','R','O','J','C','D','I','Z','F','A','P'}
                extracted_class = None
                # Patrón 1: "CLASE W" o "CLASE: W"
                m = re.search(r'\bCLASE\s*:?\s*([A-Z])\b', msg_clean)
                if m and m.group(1) in VALID_CLASSES:
                    extracted_class = m.group(1)
                # Patrón 2: Mensaje de una sola letra (ej: "W")
                if not extracted_class and re.match(r'^([A-Z])$', msg_clean.strip()):
                    letter = msg_clean.strip()
                    if letter in VALID_CLASSES:
                        extracted_class = letter
                # Patrón 3: "LA W" o "LA CLASE W"
                if not extracted_class:
                    m = re.search(r'\bLA\s+(?:CLASE\s+)?([A-Z])\b', msg_clean)
                    if m and m.group(1) in VALID_CLASSES:
                        extracted_class = m.group(1)
                # Patrón 4: Cualquier letra de clase válida en el mensaje corto (<= 10 chars)
                if not extracted_class and len(msg_clean.strip()) <= 10:
                    for ch in msg_clean:
                        if ch in VALID_CLASSES:
                            extracted_class = ch
                            break
                
                if extracted_class and len(extracted_class) == 1:
                    is_return = session.data.get('awaiting_class_selection_is_return', False)
                    flight_index = session.data.get('selected_return_flight_index' if is_return else 'pending_flight_index') or session.data.get('selected_flight_index', 1)
                    
                    logger.info(f"=== CLASE SELECCIONADA: {extracted_class} (is_return={is_return}, flight_index={flight_index}) ===")
                    self._send_response(phone, "Preparando confirmación de vuelo...", session)
                    
                    # Limpiar el estado de espera de clase
                    session.data['awaiting_class_selection'] = False
                    
                    # Llamar a la función de confirmación con la clase elegida
                    result = self._confirm_flight_selection_function(
                        flight_index=flight_index,
                        flight_class=extracted_class,
                        session=session,
                        is_return=is_return
                    )
                    
                    if result.get('success'):
                        # Guardar la clase seleccionada en sesión
                        if is_return:
                            session.data['selected_return_flight_class'] = extracted_class
                        else:
                            session.data['selected_flight_class'] = extracted_class
                        # Mostrar el mensaje de confirmación del vuelo
                        return self._send_response(phone, result.get('message', ''), session)
                    else:
                        # Error - posiblemente clase no disponible
                        # Restaurar estado de selección
                        session.data['awaiting_class_selection'] = True
                        return self._send_response(phone, result.get('message', 'Clase no disponible. Por favor elige otra letra.'), session)
                else:
                    # No se detectó letra de clase válida
                    return self._send_response(phone, "No entendí qué clase elegiste. Por favor escribe solo la letra de la clase (ej: W, Y, B, D).", session)

            # INTERCEPCIÓN DE PROCESAMIENTO DE RESERVA (Tras confirmación de vuelo)
            if session.data.get('awaiting_flight_confirmation') and not session.data.get('waiting_for_field'):
                msg_upper = message.strip().upper()
                msg_lower = msg_upper.lower()
                
                msg_upper_clean = message.strip().upper().replace('.', '')
                
                # UNIFIED AI FLOW: Confirmación y Selección de Método
                # Reemplaza la lógica rígida por una clasificación AI unificada
                
                detected_confirm = None
                detected_option = 'foto' if media_url else None
                
                # Fast track para respuestas obvias (latencia cero)
                if msg_upper_clean in ['SI', 'SÍ', 'YES', 'CONFIRMO', 'OK', 'DALE', 'CORRECTO']:
                     detected_confirm = 'si'
                elif msg_upper_clean in ['NO', 'RECHAZAR', 'CORREGIR']:
                     detected_confirm = 'no'
                elif msg_upper_clean in ['1', 'FOTO', 'IMAGEN']:
                     detected_option = 'foto'
                elif msg_upper_clean in ['2', 'MANUAL', 'ESCRIBIR']:
                     detected_option = 'manual'
                else:
                    # CLASIFICACIÓN AI para todo lo demás
                    logger.info(f"Clasificando intención completa con AI: '{message}'")
                    classification = self._classify_with_ai(
                        message,
                        "El usuario está en el proceso de reserva. Se le mostró un vuelo y se le pidió confirmación, O se le pidió elegir cómo ingresar los datos (Foto vs Manual).",
                        {
                            'confirm_flight': 'El usuario confirma el vuelo (Si, correcto, perfecto, ok, me gusta) o quiere continuar',
                            'reject_flight': 'El usuario rechaza el vuelo, quiere cambiar algo, ver otra fecha o dice que no',
                            'method_photo': 'El usuario elige la Opción 1, enviar FOTO, imagen, cédula o pasaporte',
                            'method_manual': 'El usuario elige la Opción 2, ingreso MANUAL, escribir datos, no tiene foto o texto'
                        }
                    )
                    
                    if classification == 'confirm_flight':
                        detected_confirm = 'si'
                    elif classification == 'reject_flight':
                        detected_confirm = 'no'
                    elif classification == 'method_photo':
                        detected_option = 'foto'
                    elif classification == 'method_manual':
                        detected_option = 'manual'

                # Si se detectó una opción de método, implica confirmación del vuelo
                if detected_option and not session.data.get('flight_selection_fully_confirmed'):
                    detected_confirm = 'si'

                # Manejar confirmación del vuelo (SÍ o NO)
                if detected_confirm == 'si':
                    logger.info("Confirmación de selección de vuelo recibida.")
                    
                    # CORRECCION DE ESTADO DEFENSIVA:
                    # Si ya tenemos vuelos de retorno buscados, la ida TIENE que estar confirmada.
                    if session.data.get('is_round_trip') and session.data.get('return_flights'):
                        if not session.data.get('ida_class_confirmed'):
                            logger.warning("CORRECCION DE ESTADO: Vuelos de vuelta existen pero ida_class_confirmed es False. Corrigiendo a True.")
                            session.data['ida_class_confirmed'] = True

                    # Determinar si estamos confirmando IDA o VUELTA
                    is_round_trip = session.data.get('is_round_trip', False)
                    ida_class_confirmed = session.data.get('ida_class_confirmed', False)
                    
                    # Si es viaje redondo y ya confirmamos la IDA, ahora buscamos clase de VUELTA
                    if is_round_trip and ida_class_confirmed:
                        selected_class = session.data.get('selected_return_flight_class')
                        logger.info(f"Procesando confirmación de VUELTA. Clase seleccionada: {selected_class}")
                    else:
                        selected_class = session.data.get('selected_flight_class')
                        logger.info(f"Procesando confirmación de IDA/Solo Ida. Clase seleccionada: {selected_class}")
                    
                    # CASO 1: Si ya seleccionó clase, es la confirmación FINAL del vuelo (después de ver clases)
                    if selected_class:
                        logger.info(f"Confirmación FINAL de vuelo recibida (clase {selected_class} ya seleccionada)")
                        
                        # LOGICA PARA IDA Y VUELTA
                        # Si es Ida y Vuelta Y aún NO hemos confirmado la clase de ida
                        if is_round_trip and not ida_class_confirmed:
                            logger.info("Clase de IDA confirmada en viaje redondo - Procediendo a buscar vuelta")
                            session.data['ida_class_confirmed'] = True
                            session.data['flight_confirmed'] = True
                            session.data['awaiting_flight_confirmation'] = False
                            session.data['flight_selection_fully_confirmed'] = False
                            
                            # LIMPIAR estado de selección para que el vuelo de vuelta 
                            # pueda pasar por todo el flujo desde cero
                            # NO limpiar selected_flight_class ni selected_flight_index (son de ida)
                            # Guardar datos de ida en variables separadas
                            session.data['ida_flight_index'] = session.data.get('selected_flight_index')
                            session.data['ida_flight_class'] = session.data.get('selected_flight_class')
                            session.data['ida_flight_classes_prices'] = session.data.get('flight_classes_prices')
                            
                            # Verificar si ya tenemos la fecha de regreso almacenada
                            return_date = session.data.get('return_date')
                            if return_date:
                                logger.info(f"Fecha de regreso ya existe en sesión: {return_date}")
                                # Enviar mensaje de confirmación intermedio
                                # Construir mensaje de confirmación detallado
                                _flights_list = session.data.get('available_flights', [])
                                _flight_idx = session.data.get('selected_flight_index', 1)
                                ida_flight = _flights_list[_flight_idx - 1] if _flights_list and _flight_idx and _flight_idx <= len(_flights_list) else {}
                                ida_airline = ida_flight.get('airline_name', 'la aerolínea seleccionada')
                                ida_num = ida_flight.get('flight_number', '')
                                ida_class_code = session.data.get('selected_flight_class', 'Y')
                                ida_date_fmt = format_date_dd_mm_yyyy(ida_flight.get('date', ''))
                                
                                confirm_msg = f"Perfecto, vuelo de ida confirmado: *{ida_airline} {ida_num}*, clase *{ida_class_code}*, para el *{ida_date_fmt}*. Ahora busco las opciones para tu regreso el {format_date_dd_mm_yyyy(return_date)}..."
                                self._send_response(phone, confirm_msg, session)
                                
                                # Modificar el mensaje para que la AI procese la búsqueda automáticamente
                                # FUNDAMENTAL: NO generar otro mensaje de confirmación (ya se envió confirm_msg arriba)
                                # Solo pedir a Gemini que llame a search_flights para el vuelo de vuelta
                                message = f"INSTRUCCION INTERNA - NO MOSTRAR AL USUARIO: Busca ahora el vuelo de REGRESO origen={ida_flight.get('destination','CCS')} destino={ida_flight.get('origin','CCS')} fecha={return_date} trip_type=vuelta. NO confirmes nada previamente, NO repitas información del vuelo de ida. Solo llama a la función de búsqueda y muestra los resultados."
                                
                                # No retornamos, para que el código fluya hacia la llamada a Gemini al final de _process_with_ai
                                logger.info("Instrucción de búsqueda de regreso preparada para Gemini")
                            else:
                                logger.info("Fecha de regreso no encontrada, pidiendo al usuario")
                                return self._send_response(phone, "Vuelo de ida confirmado. Ahora busquemos tu vuelo de regreso. ¿Para qué fecha quieres volver?", session)
                        
                        # Si es solo ida O ya confirmamos la clase de ida (confirmación final de vuelta/resumen)
                        else:
                            if is_round_trip:
                                session.data['return_flight_confirmed'] = True

                            session.data['flight_selection_fully_confirmed'] = True
                            session.data['flight_confirmed'] = True
                            
                            msg_confirm_text = "Vuelos confirmados." if is_round_trip else "Vuelo confirmado."
                            total_pax = session.data.get('num_passengers', 1)
                            if total_pax > 1:
                                msg_confirm_text += f" (Para {total_pax} personas)"
                                
                            # Determinar qué documento pedir según el vuelo
                            _fls = session.data.get('available_flights', [])
                            _fidx = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                            selected_flight = _fls[_fidx - 1] if _fls and _fidx and _fidx <= len(_fls) else {}
                            origin = selected_flight.get('origin', 'CCS')
                            destination = selected_flight.get('destination', 'CCS')
                            national_airports = ['CCS', 'PMV', 'MAR', 'VLN', 'BLA', 'PZO', 'BRM', 'STD', 'VLV', 'MUN', 'CUM', 'LRV', 'CAJ', 'CBL', 'BNS', 'LFR', 'SVZ', 'GUQ', 'SFD', 'TUV', 'AGV', 'CZE', 'GDO', 'PYH']
                            is_international = (origin not in national_airports) or (destination not in national_airports)
                            
                            doc_label = "CÉDULA o PASAPORTE"
                            
                            msg_confirm_full = f"{msg_confirm_text}\n\nPara completar la reserva necesito los datos de cada pasajero. Puedes enviarme una *foto* de tu *{doc_label}* o escribir *manual* si prefieres ingresarlos a mano."
                            
                            # Si se envió foto, NO retornar para que el bloque de procesamiento de imagen (abajo) la capture.
                            if media_url:
                                self._send_response(phone, msg_confirm_full, session)
                            else:
                                return self._send_response(phone, msg_confirm_full, session)
                    
                    # CASO 2: NO ha seleccionado clase aún, es la confirmación del VUELO (antes de ver clases)
                    else:
                        logger.info("Confirmación de VUELO recibida (sin clase) - Obteniendo clases directamente")
                        
                        # Determinar si es vuelo de ida o vuelta
                        is_return = session.data.get('pending_return_flight_index') is not None
                        pending_index = session.data.get('pending_return_flight_index') if is_return else session.data.get('pending_flight_index')
                        
                        if pending_index:
                            # Marcar como confirmado para que select_flight_and_get_prices obtenga las clases
                            if is_return:
                                session.data['return_flight_confirmed'] = True
                                session.data['selected_return_flight_index'] = pending_index
                            else:
                                session.data['flight_confirmed'] = True
                                session.data['selected_flight_index'] = pending_index
                            
                            session.data['awaiting_flight_confirmation'] = False
                            
                            # LLAMAR DIRECTAMENTE a la función para obtener clases
                            # En vez de dejar caer al flujo de AI (que podría no funcionar)
                            logger.info(f"Llamando select_flight_and_get_prices directamente para índice {pending_index}")
                            self._send_response(phone, "Consultando precios de las clases disponibles, un momento...", session)
                            
                            result = self._select_flight_and_get_prices_function(
                                pending_index,
                                session,
                                is_return
                            )
                            
                            if result.get('success'):
                                # Enviar el resultado (clases disponibles) directamente
                                structured_message = result.get('message', '')
                                if structured_message:
                                    # Construir mensaje de clases manualmente si no tiene formato
                                    # La función devuelve datos de clases, necesitamos formatearlos
                                    economy_classes = result.get('economy_classes', [])
                                    business_classes = result.get('business_classes', [])
                                    first_classes = result.get('first_classes', [])
                                    
                                    if economy_classes or business_classes or first_classes:
                                        # Construir mensaje formateado con las clases
                                        flight_type_label = "REGRESO" if is_return else "IDA"
                                        classes_msg = f" *CLASES DISPONIBLES - VUELO DE {flight_type_label}*\n"
                                        classes_msg += f" {result.get('aerolinea', '')} {result.get('vuelo', '')}\n"
                                        classes_msg += f" {result.get('ruta', '')}\n"
                                        classes_msg += f" {result.get('fecha', '')}\n\n"
                                        
                                        if economy_classes:
                                            classes_msg += "\n"
                                            classes_msg += " *TURISTA / ECONÓMICA*\n\n"
                                            for c in economy_classes:
                                                classes_msg += f"   *Clase {c['codigo']}* - ${c['precio']:.2f} USD ({c['asientos']} as.)\n"
                                        
                                        if business_classes:
                                            classes_msg += "\n\n"
                                            classes_msg += " *EJECUTIVA / BUSINESS*\n\n"
                                            for c in business_classes:
                                                classes_msg += f"   *Clase {c['codigo']}* - ${c['precio']:.2f} USD ({c['asientos']} as.)\n"
                                        
                                        if first_classes:
                                            classes_msg += "\n\n"
                                            classes_msg += " *PRIMERA CLASE*\n\n"
                                            for c in first_classes:
                                                classes_msg += f"   *Clase {c['codigo']}* - ${c['precio']:.2f} USD ({c['asientos']} as.)\n"
                                        
                                        classes_msg += "\n\n\n"
                                        classes_msg += " *Escribe la letra de la clase que deseas* (ej: W, Y, B...)"
                                        
                                        # ACTIVAR ESTADO DE ESPERA DE CLASE
                                        session.data['awaiting_class_selection'] = True
                                        session.data['awaiting_class_selection_is_return'] = is_return
                                        # Guardar el índice del vuelo pendiente para la confirmación
                                        if not is_return:
                                            session.data['pending_flight_index'] = pending_index
                                        
                                        return self._send_response(phone, classes_msg, session)
                                    else:
                                        return self._send_response(phone, structured_message, session)
                                else:
                                    return self._send_response(phone, "Vuelo confirmado. Ahora elige una clase.", session)
                            else:
                                error_msg = result.get('message', result.get('error', 'Error desconocido'))
                                return self._send_response(phone, f"{error_msg}", session)
                        else:
                            logger.error("No se encontró pending_flight_index en sesión")
                            return self._send_response(phone, "Error: No se pudo confirmar el vuelo. Por favor, selecciona nuevamente.", session)
                
                elif detected_confirm == 'no':
                    logger.info("Rechazo de selección de vuelo recibido.")
                    session.data['awaiting_flight_confirmation'] = False
                    session.data['flight_selection_fully_confirmed'] = False
                    return self._send_response(phone, "Entendido. ¿Qué cambio te gustaría hacer? Puedes elegir otra clase o buscar vuelos diferentes.", session)

                # DETECCIÓN DE IMAGEN DE DOCUMENTO (PRIORIDAD ALTA)
                # Si hay una imagen y estamos esperando datos de pasajero, procesarla INMEDIATAMENTE
                # Esto evita que la lógica de "elección de método" clasifique mal la imagen como texto "manual"
                if media_url and (session.data.get('awaiting_flight_confirmation') or session.data.get('using_document_image') or session.data.get('flight_selection_fully_confirmed')):
                    logger.info(f"Imagen detectada durante proceso de reserva: {media_url}")
                    # Guardar URL de la imagen en la sesión
                    session.data['document_image_url'] = media_url
                    session.data['using_document_image'] = True
                    
                    # Mensaje de feedback inmediato
                    self._send_response(phone, "Imagen recibida. Extrayendo los datos del documento, un momento...", session)
                    
                    # Procesar imagen de documento
                    result = self._process_document_image(session, phone)
                    
                    if result.get('success'):
                        # Datos extraídos exitosamente
                        missing_fields = result.get('missing_fields', [])
                        
                        if not missing_fields:
                            # Tenemos todos los datos del pasajero actual
                            extracted_data = session.data.get('extracted_data', {})
                            
                            # Verificar si hay más pasajeros por procesar
                            total_passengers = session.data.get('num_passengers', 1)
                            passengers_data = session.data.get('passengers_list', [])
                            
                            # Agregar el pasajero actual a la lista
                            # Calcular tipo de pasajero a partir de fecha de nacimiento
                            pax_type = 'ADT'
                            pax_age = None
                            dob = extracted_data.get('fecha_nacimiento')
                            if dob:
                                try:
                                    born = datetime.strptime(dob, '%Y-%m-%d')
                                    today = datetime.now()
                                    pax_age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                                    if pax_age < 2:
                                        pax_type = 'INF'
                                    elif pax_age < 12:
                                        pax_type = 'CHD'
                                except:
                                    pass
                            
                            # Etiqueta visual del tipo de pasajero
                            pax_labels = {'ADT': 'Adulto', 'CHD': 'Niño', 'INF': 'Infante'}
                            pax_label = pax_labels.get(pax_type, 'Adulto')
                            if pax_age is not None:
                                pax_label += f' ({pax_age} años)'
                            
                            current_passenger = {
                                'nombre': extracted_data.get('nombre', ''),
                                'apellido': extracted_data.get('apellido', ''),
                                'cedula': extracted_data.get('cedula') or extracted_data.get('pasaporte'),
                                'telefono': extracted_data.get('telefono'),
                                'email': extracted_data.get('email'),
                                'nacionalidad': extracted_data.get('nacionalidad', 'VE'),
                                'sexo': extracted_data.get('sexo'),
                                'estado_civil': extracted_data.get('estado_civil'),
                                'direccion': extracted_data.get('direccion'),
                                'fecha_nacimiento': extracted_data.get('fecha_nacimiento'),
                                'tipo': pax_type,
                                'tipo_documento': extracted_data.get('tipo_documento', 'CI')
                            }
                            passengers_data.append(current_passenger)
                            session.data['passengers_list'] = passengers_data
                            
                            current_passenger_count = len(passengers_data)
                            
                            # Si faltan pasajeros por procesar
                            if current_passenger_count < total_passengers:
                                # Limpiar datos extraídos para el siguiente pasajero
                                session.data['extracted_data'] = {}
                                session.data['waiting_for_cedula_image'] = True
                                
                                response = f"""Datos del pasajero {current_passenger_count} guardados: *{current_passenger['nombre']} {current_passenger['apellido']}*, documento *{current_passenger['cedula']}* ({pax_label}).

Ahora necesito los datos del pasajero {current_passenger_count + 1} de {total_passengers}. Puedes enviarme una *foto* del documento o escribir *manual* para ingresar los datos a mano."""
                                return self._send_response(phone, response, session)
                            
                            # Tenemos todos los pasajeros, crear reserva
                            pax_txt = f"de los {total_passengers} pasajeros" if total_passengers > 1 else "del pasajero"
                            self._send_response(phone, f"Tengo los datos {pax_txt}. Creando tu reserva, un momento...", session)
                            
                            # Usar el primer pasajero para la reserva principal
                            first_passenger = passengers_data[0]
                            
                            # Llamar a create_booking con los datos extraídos
                            # Usar ida_flight_index/class si disponible (round trip), sino selected_flight_index/class
                            booking_flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index')
                            booking_flight_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class')
                            
                            booking_result = self._create_booking_function(
                                flight_index=booking_flight_index,
                                flight_class=booking_flight_class,
                                passenger_name=f"{first_passenger.get('nombre', '')} {first_passenger.get('apellido', '')}".strip(),
                                id_number=first_passenger.get('cedula'),
                                phone=first_passenger.get('telefono'),
                                email=first_passenger.get('email'),
                                session=session
                            )
                            
                            if booking_result.get('success'):
                                # Obtener datos del vuelo
                                flights = session.data.get('available_flights', [])
                                flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                                selected_flight = flights[flight_index - 1] if flights and flight_index > 0 else {}
                                flight_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class', 'Y')
                                
                                # Precio de IDA
                                precio_ida = 0
                                flight_classes_prices = session.data.get('ida_flight_classes_prices') or session.data.get('flight_classes_prices', {})
                                if flight_classes_prices and flight_class.upper() in flight_classes_prices:
                                    precio_ida = safe_float(flight_classes_prices[flight_class.upper()].get('price', 0))
                                
                                # Verificar si hay vuelo de vuelta
                                return_flights = session.data.get('return_flights', [])
                                return_flight_index = session.data.get('selected_return_flight_index')
                                return_flight_class = session.data.get('selected_return_flight_class', flight_class)
                                return_flight = None
                                precio_vuelta = 0
                                
                                if return_flights and return_flight_index:
                                    if return_flight_index >= 1 and return_flight_index <= len(return_flights):
                                        return_flight = return_flights[return_flight_index - 1]
                                        # Obtener precio de vuelta
                                        return_classes_prices = session.data.get('return_flight_classes_prices', {})
                                        if return_classes_prices and return_flight_class.upper() in return_classes_prices:
                                            precio_vuelta = safe_float(return_classes_prices[return_flight_class.upper()].get('price', 0))
                                        else:
                                            # Fallback: usar el precio del vuelo de vuelta
                                            precio_vuelta = safe_float(return_flight.get('price', 0))
                                
                                # Calcular totales
                                precio_por_persona = precio_ida + precio_vuelta
                                precio_total = precio_por_persona * total_passengers
                                
                                return self._send_booking_success_message(
                                    phone, session, booking_result, passengers_data, total_passengers,
                                    selected_flight, flight_class, precio_ida,
                                    return_flight, return_flight_class, precio_vuelta,
                                    precio_por_persona, precio_total
                                )
                            else:
                                # Error al crear la reserva
                                raw_error = booking_result.get('error', 'Error desconocido')
                                return self._send_response(phone, f"No se pudo crear la reserva: {raw_error}", session)
                        else:
                            # Faltan datos, pedirlos uno por uno
                            # El mensaje ya fue enviado por _process_document_image
                            # Ahora esperamos la respuesta del usuario
                            session.data['waiting_for_field'] = missing_fields[0]
                            
                            # Preguntar por el primer campo faltante
                            total_passengers = session.data.get('num_passengers', 1)
                            current_passenger_num = len(session.data.get('passengers_list', [])) + 1
                            passenger_label = f" (Pasajero {current_passenger_num} de {total_passengers})" if total_passengers > 1 else ""
                            
                            field_prompts = {
                                'telefono': f'¿Cuál es tu número de *teléfono*?{passenger_label}',
                                'email': f'¿Cuál es tu *email*?{passenger_label}',
                                'nombre': f'¿Cuál es el *nombre* del pasajero?{passenger_label}',
                                'apellido': f'¿Cuál es el *apellido*?{passenger_label}',
                                'sexo': f'¿El pasajero es *masculino* o *femenino*?{passenger_label}',
                                'direccion': f'¿Cuál es tu *dirección*?{passenger_label}'
                            }
                            prompt = field_prompts.get(missing_fields[0], f'¿Cuál es tu {missing_fields[0]}?')
                            return self._send_response(phone, prompt, session)
                    else:
                        # Error procesando imagen, pedir datos manuales
                        return self._send_response(
                            phone,
                            "No pude procesar la imagen. Vamos a hacerlo manual.\n\n"
                            "¿Cuál es el *nombre completo* del pasajero?",
                            session
                        )

                # FASE 2: Elección de método (Foto vs Manual)
                # Ejecutar si el vuelo está confirmado O si ya detectamos una intención de método (detected_option)
                
                if session.data.get('flight_selection_fully_confirmed') or detected_option:
                    # Si ya tenemos detected_option (del bloque unificado), lo usamos.
                    # Si no, intentamos detectarlo aquí (para casos donde solo se confirmó el vuelo previamente)
                    if not detected_option:
                         # Detección por keywords (secundaria)
                        msg_lower_m = message.lower()
                        if any(x in msg_lower_m for x in ['manual', 'opcion 2', 'opción 2', 'escribir', 'texto', 'mano', '', '2']) or msg_lower_m == '2':
                            detected_option = 'manual'
                        elif any(x in msg_lower_m for x in ['foto', 'imagen', 'cedula', 'cédula', 'pasaporte', 'camara', 'cámara', 'opcion 1', 'opción 1', '', '', '1']) or msg_lower_m == '1':
                            detected_option = 'foto'
                        
                        # Si sigue sin detectarse, usar AI (Específica para método)
                        if not detected_option:
                            logger.info(f"Clasificando método de entrada con AI (Fase 2): '{message}'")
                            detected_option = self._classify_with_ai(
                                message,
                                "El usuario ya confirmó su vuelo. Ahora debe elegir: FOTO o MANUAL.",
                                {
                                    'foto': 'Quiere enviar foto/imagen',
                                    'manual': 'Quiere escribir manual'
                                }
                            )

                    # Ejecutar la opción detectada
                    if detected_option == 'manual':
                        logger.info("Usuario eligio ingreso manual de datos")
                        session.data['using_document_image'] = False
                        session.data['extracted_data'] = {}
                        session.data['waiting_for_field'] = 'nombre'
                        return self._send_response(phone, "Perfecto, ingreso manual. Empecemos: ¿cuál es el *nombre* del pasajero?", session)
                    
                    elif detected_option == 'foto':
                        logger.info("Usuario eligió enviar foto")
                        session.data['using_document_image'] = True
                        
                        # Determinar qué documento pedir según el vuelo
                        _fls2 = session.data.get('available_flights', [])
                        _fidx2 = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                        selected_flight = _fls2[_fidx2 - 1] if _fls2 and _fidx2 and _fidx2 <= len(_fls2) else {}
                        origin = selected_flight.get('origin', 'CCS')
                        destination = selected_flight.get('destination', 'CCS')
                        national_airports = ['CCS', 'PMV', 'MAR', 'VLN', 'BLA', 'PZO', 'BRM', 'STD', 'VLV', 'MUN', 'CUM', 'LRV', 'CAJ', 'CBL', 'BNS', 'LFR', 'SVZ', 'GUQ', 'SFD', 'TUV', 'AGV', 'CZE', 'GDO', 'PYH']
                        is_international = (origin not in national_airports) or (destination not in national_airports)
                        
                        instruction = "Envíame la foto de tu *cédula* o *pasaporte* y extraigo los datos automáticamente."
                        
                        return self._send_response(phone, f"Excelente. {instruction}", session)
                    
                    elif session.data.get('flight_selection_fully_confirmed') and not media_url:
                        # Determinar qué documento pedir según el vuelo
                        _fls3 = session.data.get('available_flights', [])
                        _fidx3 = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                        selected_flight = _fls3[_fidx3 - 1] if _fls3 and _fidx3 and _fidx3 <= len(_fls3) else {}
                        origin = selected_flight.get('origin', 'CCS')
                        destination = selected_flight.get('destination', 'CCS')
                        national_airports = ['CCS', 'PMV', 'MAR', 'VLN', 'BLA', 'PZO', 'BRM', 'STD', 'VLV', 'MUN', 'CUM', 'LRV', 'CAJ', 'CBL', 'BNS', 'LFR', 'SVZ', 'GUQ', 'SFD', 'TUV', 'AGV', 'CZE', 'GDO', 'PYH']
                        is_international = (origin not in national_airports) or (destination not in national_airports)
                        
                        # Mensaje genérico para cualquier caso
                        doc_desc = "FOTO de tu *CÉDULA* o *PASAPORTE*"
                        
                        # Si ya confirmamos el vuelo pero la AI no entendió el método, repetir opciones
                        return self._send_response(phone, f"No te entendí bien. Puedes enviarme una *foto* de tu documento, o escribir *manual* para ingresar los datos a mano.", session)

            # (Bloque de detección de imagen movido arriba)
            
            # MANEJO DE CAMPOS FALTANTES DESPUÉS DE EXTRACCIÓN DE CÉDULA
            waiting_for_field = session.data.get('waiting_for_field')
            if waiting_for_field:
                # re ya importado al inicio del archivo
                extracted_data = session.data.get('extracted_data', {})
                
                # COMANDO UNIVERSAL: Permitir al usuario corregir un campo anterior
                msg_lower_cmd = message.strip().lower()
                if msg_lower_cmd in ['corregir', 'atras', 'atrás', 'volver', 'regresar', 'back']:
                    # Mapeo de campos a su campo anterior
                    field_order = ['nombre', 'apellido', 'nacionalidad', 'cedula', 'sexo', 'telefono', 'email', 'fecha_nacimiento']
                    current_idx = field_order.index(waiting_for_field) if waiting_for_field in field_order else 0
                    if current_idx > 0:
                        prev_field = field_order[current_idx - 1]
                        session.data['waiting_for_field'] = prev_field
                        field_names = {'nombre': 'Nombre', 'apellido': 'Apellido', 'nacionalidad': 'Nacionalidad', 'cedula': 'Cédula/Pasaporte', 'sexo': 'Sexo (M o F)', 'telefono': 'Teléfono', 'email': 'Email', 'fecha_nacimiento': 'Fecha de Nacimiento'}
                        return self._send_response(phone, f"Volviendo al campo anterior: *{field_names.get(prev_field, prev_field)}*. Escribe el dato correcto:", session)
                    else:
                        return self._send_response(phone, "Ya estás en el primer campo. Escribe el dato correctamente:", session)
                
                # Guardar el campo que el usuario está proporcionando
                # LÓGICA MANUAL - NUEVOS CAMPOS
                current_value = message.strip()
                if waiting_for_field == 'nombre':
                    if len(current_value) < 2:
                        return self._send_response(phone, "El nombre es muy corto. Inténtalo de nuevo:", session)
                    
                    # Validación básica: No debe tener números
                    if any(char.isdigit() for char in current_value):
                         return self._send_response(phone, "El nombre no puede tener números. Escribe solo el nombre:", session)
                    
                    # Validación de palabras comunes que no son nombres
                    stop_words = ['HOLA', 'BUENOS', 'DIAS', 'TARDES', 'NOCHES', 'GRACIAS', 'OK', 'DALE', 'FINO', 'CHAO', 'ADIOS', 'PRECIO', 'COSTO', 'VUELO', 'INFO', 'AYUDA', 'MANUAL', 'FOTO', 'CEDULA', 'PASAPORTE', 'SI', 'NO', 'CANCELAR']
                    if current_value.upper() in stop_words:
                        return self._send_response(phone, f"'{current_value}' no parece un nombre válido. Por favor escribe el *nombre* del pasajero:", session)
                    
                    # Validación con AI para frases largas o ambiguas
                    if len(current_value.split()) > 2 or len(current_value) > 15:
                         ai_check = self._classify_with_ai(
                            message,
                            "El usuario debe ingresar el NOMBRE de un pasajero aéreo. ¿El texto ingresado es un NOMBRE válido o es un mensaje conversacional/pregunta?",
                            {
                                'VALID_NAME': 'Es un nombre propio de persona (Ej: Juan, Maria, Jose Antonio)',
                                'INVALID': 'Es un saludo, pregunta, queja, o frase que NO es un nombre (Ej: Hola como estas, quiero ver precios)',
                            }
                        )
                         if ai_check == 'INVALID':
                              return self._send_response(phone, "Eso no parece un nombre válido. Por favor escribe solo el *nombre* del pasajero (sin apellidos):", session)
                    
                    extracted_data['nombre'] = current_value.upper()
                    session.data['waiting_for_field'] = 'apellido'
                    session.data['extracted_data'] = extracted_data
                    return self._send_response(phone, "Perfecto. ¿Y el *apellido*?", session)
                
                elif waiting_for_field == 'apellido':
                    if len(current_value) < 2:
                        return self._send_response(phone, "El apellido es muy corto. Inténtalo de nuevo:", session)

                    # Validación básica: No debe tener números
                    if any(char.isdigit() for char in current_value):
                         return self._send_response(phone, "El apellido no puede tener números. Escribe solo el apellido:", session)
                    
                    # Validación de palabras comunes que no son nombres
                    stop_words = ['HOLA', 'BUENOS', 'DIAS', 'TARDES', 'NOCHES', 'GRACIAS', 'OK', 'DALE', 'FINO', 'CHAO', 'ADIOS', 'PRECIO', 'COSTO', 'VUELO', 'INFO', 'AYUDA', 'MANUAL', 'FOTO', 'CEDULA', 'PASAPORTE', 'SI', 'NO', 'CANCELAR', 'NOMBRE', 'APELLIDO']
                    if current_value.upper() in stop_words:
                        return self._send_response(phone, f"'{current_value}' no parece un apellido válido. Por favor escribe el *apellido* del pasajero:", session)

                     # Validación con AI para frases largas o ambiguas
                    if len(current_value.split()) > 2 or len(current_value) > 15:
                         ai_check = self._classify_with_ai(
                            message,
                            "El usuario debe ingresar el APELLIDO de un pasajero aéreo. ¿El texto ingresado es un APELLIDO válido o es un mensaje conversacional/pregunta?",
                            {
                                'VALID_NAME': 'Es un apellido de persona (Ej: Perez, Rodriguez, De la Cruz)',
                                'INVALID': 'Es un saludo, pregunta, queja, o frase que NO es un apellido',
                            }
                        )
                         if ai_check == 'INVALID':
                              return self._send_response(phone, "Eso no parece un apellido válido. Por favor escribe solo el *apellido* del pasajero:", session)

                    extracted_data['apellido'] = current_value.upper()
                    session.data['waiting_for_field'] = 'nacionalidad'
                    session.data['extracted_data'] = extracted_data
                    return self._send_response(phone, "Listo. ¿El pasajero es *venezolano* o *extranjero*?", session)

                elif waiting_for_field == 'nacionalidad':
                    val = current_value.upper()
                    # Detección rápida por keywords
                    is_venezuelan = None  # None = no determinado
                    
                    # Comprobar palabras clave o códigos
                    if val in ['V', 'VE', 'VEN'] or any(k in val for k in ['VENEZOLAN', 'VENEZUELA']):
                        is_venezuelan = True
                    elif val in ['E', 'EX', 'EXT'] or any(k in val for k in ['EXTRANJ', 'COLOMBI', 'BRASIL', 'ARGENTIN', 'CHILEN', 'MEXICAN', 'PERUAN', 'ECUATORI', 'DOMINICAN', 'AMERICAN', 'ESPAÑOL', 'ITALIAN']):
                        is_venezuelan = False
                    else:
                        # FALLBACK AI: Clasificar con inteligencia artificial
                        ai_nac = self._classify_with_ai(
                            message,
                            "El usuario debe indicar su nacionalidad. Solo hay dos opciones: Venezolano o Extranjero (cualquier otro país).",
                            {
                                'VE': 'El pasajero es VENEZOLANO (de Venezuela)',
                                'EXT': 'El pasajero es EXTRANJERO (de cualquier otro país que no sea Venezuela)',
                            }
                        )
                        if ai_nac == 'VE':
                            is_venezuelan = True
                        elif ai_nac == 'EXT':
                            is_venezuelan = False
                        else:
                            return self._send_response(phone, "No te entendí. ¿El pasajero es *venezolano* o *extranjero*?", session)
                        
                    if is_venezuelan:
                        extracted_data['nacionalidad'] = 'VE'
                        
                        # VERIFICAR SI ES VUELO INTERNACIONAL
                        _fls4 = session.data.get('available_flights', [])
                        _fidx4 = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                        selected_flight = _fls4[_fidx4 - 1] if _fls4 and _fidx4 and _fidx4 <= len(_fls4) else {}
                        origin = selected_flight.get('origin', 'CCS')
                        destination = selected_flight.get('destination', 'CCS')
                        
                        # Lista básica de aeropuertos nacionales (Venezuela)
                        national_airports = ['CCS', 'PMV', 'MAR', 'VLN', 'BLA', 'PZO', 'BRM', 'STD', 'VLV', 'MUN', 'CUM', 'LRV', 'CAJ', 'CBL', 'BNS', 'LFR', 'SVZ', 'GUQ', 'SFD', 'TUV', 'AGV', 'CZE', 'GDO', 'PYH']
                        
                        is_international = (origin not in national_airports) or (destination not in national_airports)
                        
                        if is_international:
                            extracted_data['tipo_documento'] = 'P'  # Pasaporte
                            if extracted_data.get('pasaporte'):
                                # Ya tenemos pasaporte, verificar siguientes
                                if extracted_data.get('sexo'):
                                    session.data['waiting_for_field'] = 'telefono'
                                    msg = "Venezolano, perfecto. Ya tengo pasaporte y sexo. ¿Cuál es el número de *teléfono*?"
                                else:
                                    session.data['waiting_for_field'] = 'sexo'
                                    msg = "Venezolano, perfecto. Ya tengo el pasaporte. ¿El pasajero es *masculino* o *femenino*?"
                            else:
                                session.data['waiting_for_field'] = 'tipo_documento_seleccion'
                                msg = "Venezolano, perfecto. ¿Vas a registrar *cédula* o *pasaporte*?"
                        else:
                            extracted_data['tipo_documento'] = 'CI'  # Cédula
                            if extracted_data.get('cedula'):
                                # Ya tenemos cédula, verificar siguientes
                                if extracted_data.get('sexo'):
                                    session.data['waiting_for_field'] = 'telefono'
                                    msg = "Venezolano, perfecto. Ya tengo cédula y sexo. ¿Cuál es el número de *teléfono*?"
                                else:
                                    session.data['waiting_for_field'] = 'sexo'
                                    msg = "Venezolano, perfecto. Ya tengo la cédula. ¿El pasajero es *masculino* o *femenino*?"
                            else:
                                session.data['waiting_for_field'] = 'cedula'
                                msg = "Venezolano, perfecto. Para este vuelo nacional necesitas tu *cédula de identidad*. Indícame el número (solo números). Si es un niño sin cédula, puedes usar la del representante."
                    else:
                        extracted_data['nacionalidad'] = 'EXT'
                            
                        # VERIFICAR SI ES VUELO INTERNACIONAL PARA EXTRANJERO
                        _fls5 = session.data.get('available_flights', [])
                        _fidx5 = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                        selected_flight = _fls5[_fidx5 - 1] if _fls5 and _fidx5 and _fidx5 <= len(_fls5) else {}
                        origin = selected_flight.get('origin', 'CCS')
                        destination = selected_flight.get('destination', 'CCS')
                        national_airports = ['CCS', 'PMV', 'MAR', 'VLN', 'BLA', 'PZO', 'BRM', 'STD', 'VLV', 'MUN', 'CUM', 'LRV', 'CAJ', 'CBL', 'BNS', 'LFR', 'SVZ', 'GUQ', 'SFD', 'TUV', 'AGV', 'CZE', 'GDO', 'PYH']
                        is_international = (origin not in national_airports) or (destination not in national_airports)
                        
                        if is_international:
                            extracted_data['tipo_documento'] = 'P'  # Pasaporte
                            if extracted_data.get('pasaporte'):
                                if extracted_data.get('sexo'):
                                    session.data['waiting_for_field'] = 'telefono'
                                    msg = "Extranjero, entendido. Ya tengo pasaporte y sexo. ¿Cuál es el número de *teléfono*?"
                                else:
                                    session.data['waiting_for_field'] = 'sexo'
                                    msg = "Extranjero, entendido. Ya tengo el pasaporte. ¿El pasajero es *masculino* o *femenino*?"
                            else:
                                session.data['waiting_for_field'] = 'tipo_documento_seleccion'
                                msg = "Extranjero, entendido. ¿Vas a registrar *cédula* o *pasaporte*?"
                        else:
                            extracted_data['tipo_documento'] = 'P'  # Default Pasaporte para extranjeros en nacionales igual funciona
                            if extracted_data.get('pasaporte') or extracted_data.get('cedula'):
                                if extracted_data.get('sexo'):
                                    session.data['waiting_for_field'] = 'telefono'
                                    msg = "Extranjero, entendido. Ya tengo documento y sexo. ¿Cuál es el número de *teléfono*?"
                                else:
                                    session.data['waiting_for_field'] = 'sexo'
                                    msg = "Extranjero, entendido. Ya tengo el documento. ¿El pasajero es *masculino* o *femenino*?"
                            else:
                                session.data['waiting_for_field'] = 'tipo_documento_seleccion'
                                msg = "Extranjero, entendido. ¿Vas a registrar *cédula* o *pasaporte*?"
                    session.data['extracted_data'] = extracted_data
                    return self._send_response(phone, msg, session)

                elif waiting_for_field == 'tipo_documento_seleccion':
                    # Procesar selección de documento
                    doc_selection = message.strip().upper()
                    
                    if any(x in doc_selection for x in ['CEDULA', 'CÉDULA', 'CI', 'IDENTIDAD']):
                        session.data['waiting_for_field'] = 'cedula'
                        extracted_data['tipo_documento'] = 'CI'
                        msg = "Cédula, perfecto. Indícame el número. Si es un niño sin cédula, puedes usar la del representante."
                    
                    elif any(x in doc_selection for x in ['PASAPORTE', 'PASSPORT', 'P']):
                        session.data['waiting_for_field'] = 'pasaporte'
                        extracted_data['tipo_documento'] = 'P'
                        msg = "Pasaporte, perfecto. Indícame el número de *pasaporte*."
                    
                    else:
                        # Fallback con AI si no es obvio
                         ai_doc = self._classify_with_ai(
                            message,
                            "El usuario debe elegir entre CEDULA o PASAPORTE.",
                            {'CI': 'Eligió Cédula', 'P': 'Eligió Pasaporte'}
                        )
                         if ai_doc == 'CI':
                             session.data['waiting_for_field'] = 'cedula'
                             extracted_data['tipo_documento'] = 'CI'
                             msg = "Cédula, perfecto. Indícame el número. Si es un niño sin cédula, puedes usar la del representante."
                         elif ai_doc == 'P':
                             session.data['waiting_for_field'] = 'pasaporte'
                             extracted_data['tipo_documento'] = 'P'
                             msg = "Pasaporte, perfecto. Indícame el número de *pasaporte*."
                         else:
                             return self._send_response(phone, "No te entendí. ¿Vas a registrar una *cédula* o un *pasaporte*?", session)
                    
                    session.data['extracted_data'] = extracted_data
                    return self._send_response(phone, msg, session)

                elif waiting_for_field == 'cedula' or waiting_for_field == 'pasaporte':
                    # Limpiar: quitar todo excepto letras y números
                    clean_doc = re.sub(r'[^a-zA-Z0-9]', '', current_value.upper())
                    
                    # VALIDACIÓN: El documento DEBE contener al menos 5 dígitos numéricos
                    only_digits = re.sub(r'[^0-9]', '', current_value)
                    if len(only_digits) < 5:
                        return self._send_response(phone, "El documento debe tener al menos 5 números. Inténtalo de nuevo, o escribe *corregir* para volver al campo anterior.", session)
                    
                    if len(clean_doc) < 5:
                        return self._send_response(phone, "Documento muy corto. Inténtalo de nuevo, o escribe *corregir* para volver al campo anterior.", session)
                    
                    extracted_data['cedula'] = clean_doc # Usamos cedula como campo genérico
                    session.data['extracted_data'] = extracted_data
                    
                    # Verificar si ya tenemos el sexo
                    if extracted_data.get('sexo'):
                        # Verificar si ya tenemos dirección
                        if extracted_data.get('direccion'):
                            session.data['waiting_for_field'] = 'telefono'
                            return self._send_response(phone, "Perfecto. ¿Cuál es el número de *teléfono*?", session)
                        else:
                            session.data['waiting_for_field'] = 'direccion'
                            passengers_list = session.data.get('passengers_list', [])
                            msg_direccion = "Perfecto. ¿Cuál es tu *dirección*?"
                            if len(passengers_list) > 0:
                                if len(passengers_list) == 1:
                                    msg_direccion += "\n\nSi quieres usar la misma del pasajero 1, escribe *igual*."
                                else:
                                    msg_direccion += "\n\nSi quieres usar la misma del pasajero 1, escribe *igual*."
                            return self._send_response(phone, msg_direccion, session)
                    
                    session.data['waiting_for_field'] = 'sexo'
                    return self._send_response(phone, "Listo. ¿El pasajero es *masculino* o *femenino*?", session)

                elif waiting_for_field == 'sexo':
                    sexo = message.strip().upper()
                    sexo_resolved = None
                    
                    # Detección rápida
                    if sexo in ['M', 'H', 'V']:
                        sexo_resolved = 'M'
                    elif sexo in ['F']:
                        sexo_resolved = 'F'
                    elif 'hombre' in message.lower() or 'masculino' in message.lower() or 'macho' in message.lower() or 'niño' in message.lower() or 'varon' in message.lower() or 'varón' in message.lower():
                        sexo_resolved = 'M'
                    elif 'mujer' in message.lower() or 'femenino' in message.lower() or 'hembra' in message.lower() or 'niña' in message.lower():
                        sexo_resolved = 'F'
                    else:
                        # FALLBACK AI: Clasificar con inteligencia artificial
                        ai_sexo = self._classify_with_ai(
                            message,
                            "El usuario debe indicar el SEXO del pasajero para una reserva de vuelo.",
                            {
                                'M': 'Masculino, hombre, varón, niño, male',
                                'F': 'Femenino, mujer, niña, female',
                            }
                        )
                        sexo_resolved = ai_sexo
                    
                    if sexo_resolved not in ['M', 'F']:
                        return self._send_response(phone, "No te entendí. ¿El pasajero es *masculino (M)* o *femenino (F)*?", session)
                    
                    extracted_data['sexo'] = sexo_resolved
                    session.data['extracted_data'] = extracted_data
                    
                    # Verificar si ya tenemos dirección
                    # Omitir dirección, ir directo a teléfono
                    session.data['waiting_for_field'] = 'telefono'
                    return self._send_response(phone, "Listo. ¿Cuál es el número de *teléfono*?", session)

                elif waiting_for_field == 'telefono':
                    # Extraer números del mensaje (teléfono)
                    phone_digits = re.sub(r'\D', '', message)
                    if len(phone_digits) >= 10:
                        extracted_data['telefono'] = phone_digits
                        session.data['extracted_data'] = extracted_data
                        
                        # Ahora pedir email
                        session.data['waiting_for_field'] = 'email'
                        return self._send_response(phone, "Listo. ¿Cuál es tu *correo electrónico*?", session)
                    else:
                        return self._send_response(phone, "El teléfono debe tener al menos 10 dígitos. Inténtalo de nuevo:", session)
                
                elif waiting_for_field == 'email':
                    # Validar email
                    email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', message)
                    if email_match:
                        extracted_data['email'] = email_match.group(1)
                        session.data['extracted_data'] = extracted_data
                        
                        # VERIFICAR SI YA TENEMOS FECHA DE NACIMIENTO (extraída de imagen)
                        if extracted_data.get('fecha_nacimiento'):
                            # Ya tenemos la fecha de nacimiento de la imagen, saltar pregunta
                            logger.info(f"Fecha de nacimiento ya extraída de imagen: {extracted_data['fecha_nacimiento']}")
                            session.data['waiting_for_field'] = None
                            
                            # CALCULAR TIPO DE PASAJERO
                            dob_iso = extracted_data['fecha_nacimiento']
                            today = datetime.now()
                            try:
                                born = datetime.strptime(dob_iso, '%Y-%m-%d')
                                age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                            except:
                                age = 30  # Default adulto
                            
                            pax_type = 'ADT'
                            if age < 2:
                                pax_type = 'INF'
                            elif age < 12:
                                pax_type = 'CHD'
                            
                            extracted_data['tipo'] = pax_type
                            
                            # Etiqueta visual del tipo de pasajero
                            pax_labels = {'ADT': 'Adulto', 'CHD': 'Niño', 'INF': 'Infante'}
                            pax_label = pax_labels.get(pax_type, 'Adulto') + f' ({age} años)'
                            
                            # Agregar pasajero a la lista
                            total_passengers = session.data.get('num_passengers', 1)
                            passengers_data = session.data.get('passengers_list', [])
                            
                            current_passenger = {
                                'nombre': extracted_data.get('nombre', ''),
                                'apellido': extracted_data.get('apellido', ''),
                                'cedula': extracted_data.get('cedula') or extracted_data.get('pasaporte'),
                                'telefono': extracted_data.get('telefono'),
                                'email': extracted_data.get('email'),
                                'nacionalidad': extracted_data.get('nacionalidad', 'VE'),
                                'sexo': extracted_data.get('sexo', 'M'),
                                'direccion': extracted_data.get('direccion'),
                                'ciudad': extracted_data.get('ciudad'),
                                'estado': extracted_data.get('estado'),
                                'zipCode': extracted_data.get('zipCode'),
                                'fecha_nacimiento': extracted_data.get('fecha_nacimiento'),
                                'tipo': pax_type,
                                'tipo_documento': extracted_data.get('tipo_documento', 'CI')
                            }
                            passengers_data.append(current_passenger)
                            session.data['passengers_list'] = passengers_data
                            
                            current_passenger_count = len(passengers_data)
                            
                            if current_passenger_count < total_passengers:
                                session.data['extracted_data'] = {}
                                session.data['waiting_for_cedula_image'] = True
                                
                                response = f"""Datos del pasajero {current_passenger_count} guardados: *{current_passenger['nombre']} {current_passenger['apellido']}*, documento *{current_passenger['cedula']}* ({pax_label}).

Ahora necesito los datos del pasajero {current_passenger_count + 1} de {total_passengers}. Puedes enviarme una *foto* del documento o escribir *manual* para ingresar los datos a mano."""
                                return self._send_response(phone, response, session)
                            
                            # Tenemos todos los pasajeros, crear reserva
                            pax_txt = f"de los {total_passengers} pasajeros" if total_passengers > 1 else "del pasajero"
                            wati_service.send_message(phone, f"Tengo los datos {pax_txt}. Creando tu reserva, un momento...")
                            
                            first_passenger = passengers_data[0]
                            
                            booking_flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index')
                            booking_flight_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class')
                            
                            booking_result = self._create_booking_function(
                                flight_index=booking_flight_index,
                                flight_class=booking_flight_class,
                                passenger_name=f"{first_passenger.get('nombre', '')} {first_passenger.get('apellido', '')}".strip(),
                                id_number=first_passenger.get('cedula'),
                                phone=first_passenger.get('telefono'),
                                email=first_passenger.get('email'),
                                session=session
                            )
                            
                            if booking_result.get('success'):
                                flight_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class', 'Y')
                                precio_ida = 0
                                flight_classes_prices = session.data.get('ida_flight_classes_prices') or session.data.get('flight_classes_prices', {})
                                if flight_classes_prices and flight_class.upper() in flight_classes_prices:
                                    precio_ida = safe_float(flight_classes_prices[flight_class.upper()].get('price', 0))
                                
                                flights = session.data.get('available_flights', [])
                                flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                                selected_flight = flights[flight_index - 1] if flights and flight_index > 0 else {}
                                
                                return_flights = session.data.get('return_flights', [])
                                return_flight_index = session.data.get('selected_return_flight_index')
                                return_flight_class = session.data.get('selected_return_flight_class', flight_class)
                                return_flight = None
                                precio_vuelta = 0
                                
                                if return_flights and return_flight_index:
                                    if return_flight_index >= 1 and return_flight_index <= len(return_flights):
                                        return_flight = return_flights[return_flight_index - 1]
                                        return_classes_prices = session.data.get('return_flight_classes_prices', {})
                                        if return_classes_prices and return_flight_class.upper() in return_classes_prices:
                                            precio_vuelta = safe_float(return_classes_prices[return_flight_class.upper()].get('price', 0))
                                        else:
                                            precio_vuelta = safe_float(return_flight.get('price', 0))
                                
                                precio_por_persona = precio_ida + precio_vuelta
                                precio_total = precio_por_persona * total_passengers
                                
                                # PRIORIDAD: Usar valores confirmados por la API si existen
                                if booking_result.get('raw_total_amount', 0) > 0:
                                    precio_total = booking_result.get('raw_total_amount')
                                    precio_por_persona = booking_result.get('raw_total_per_pax', precio_por_persona)
                                
                                return self._send_booking_success_message(
                                    phone, session, booking_result, passengers_data, total_passengers,
                                    selected_flight, flight_class, precio_ida,
                                    return_flight, return_flight_class, precio_vuelta,
                                    precio_por_persona, precio_total
                                )
                            else:
                                # Error en la reserva
                                raw_error = booking_result.get('error', 'Error desconocido')
                                return self._send_response(phone, f"No se pudo crear la reserva: {raw_error}", session)
                        else:
                            # NO tenemos fecha de nacimiento (flujo manual), preguntar
                            session.data['waiting_for_field'] = 'fecha_nacimiento'
                            return self._send_response(phone, "Listo. ¿Cuál es tu *fecha de nacimiento*? (Ejemplo: 25/12/1990)", session)
                    else:
                        return self._send_response(phone, "Eso no parece un email válido. Inténtalo de nuevo (ejemplo: correo@email.com):", session)

                elif waiting_for_field == 'fecha_nacimiento':
                    # Validar fecha (re y datetime ya importados al inicio del archivo)
                    
                    dob_raw = message.strip()
                    # Intentar formatos
                    dob_iso = None
                    try:
                        # Soportar DD/MM/YYYY o DD-MM-YYYY o DD.MM.YYYY
                        clean_date = re.sub(r'[.-]', '/', dob_raw)
                        dt = datetime.strptime(clean_date, '%d/%m/%Y')
                        dob_iso = dt.strftime('%Y-%m-%d')
                    except:
                        return self._send_response(phone, "Fecha inválida. Usa el formato día/mes/año (ejemplo: 25/12/1990):", session)
                    
                    extracted_data['fecha_nacimiento'] = dob_iso
                    session.data['extracted_data'] = extracted_data
                    session.data['waiting_for_field'] = None

                    # CALCULAR TIPO DE PASAJERO
                    today = datetime.now()
                    born = datetime.strptime(dob_iso, '%Y-%m-%d')
                    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                    
                    pax_type = 'ADT'
                    if age < 2:
                        pax_type = 'INF' # Infante
                    elif age < 12:
                        pax_type = 'CHD' # Niño
                    
                    extracted_data['tipo'] = pax_type
                    
                    # Etiqueta visual del tipo de pasajero
                    pax_labels = {'ADT': 'Adulto', 'CHD': 'Niño', 'INF': 'Infante'}
                    pax_label = pax_labels.get(pax_type, 'Adulto') + f' ({age} años)'
                        
                    # Verificar si hay más pasajeros por procesar
                    total_passengers = session.data.get('num_passengers', 1)
                    passengers_data = session.data.get('passengers_list', [])
                    
                    # Agregar el pasajero actual a la lista
                    current_passenger = {
                        'nombre': extracted_data.get('nombre', ''),
                        'apellido': extracted_data.get('apellido', ''),
                        'cedula': extracted_data.get('cedula') or extracted_data.get('pasaporte'),
                        'telefono': extracted_data.get('telefono'),
                        'email': extracted_data.get('email'),
                        'nacionalidad': extracted_data.get('nacionalidad', 'VE'),
                        'sexo': extracted_data.get('sexo', 'M'),
                        # 'direccion': extracted_data.get('direccion'),
                        # 'ciudad': extracted_data.get('ciudad'),
                        # 'estado': extracted_data.get('estado'),
                        # 'zipCode': extracted_data.get('zipCode'),
                        'fecha_nacimiento': extracted_data.get('fecha_nacimiento'),
                        'tipo': extracted_data.get('tipo', 'ADT'),
                        'tipo_documento': extracted_data.get('tipo_documento', 'CI')
                    }
                    passengers_data.append(current_passenger)
                    session.data['passengers_list'] = passengers_data
                    
                    current_passenger_count = len(passengers_data)
                    
                    # Si faltan pasajeros por procesar
                    if current_passenger_count < total_passengers:
                        # Limpiar datos extraídos para el siguiente pasajero
                        session.data['extracted_data'] = {}
                        session.data['waiting_for_cedula_image'] = True
                        
                        response = f"He guardado los datos de *{current_passenger['nombre']} {current_passenger['apellido']}*. Ahora por favor indícame los datos del siguiente pasajero ({current_passenger_count + 1} de {total_passengers}). Puedes enviarme una foto de su documento o escribir sus datos."
                        return self._send_response(phone, response, session)
                    
                    # Tenemos todos los pasajeros, crear reserva
                    pax_txt = f"de los {total_passengers} pasajeros" if total_passengers > 1 else "del pasajero"
                    self._send_response(phone, f"Tengo los datos {pax_txt}. Creando tu reserva, un momento...", session)
                    
                    # Usar el primer pasajero para la reserva principal
                    first_passenger = passengers_data[0]
                    
                    booking_flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index')
                    booking_flight_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class')
                    
                    booking_result = self._create_booking_function(
                        flight_index=booking_flight_index,
                        flight_class=booking_flight_class,
                        passenger_name=f"{first_passenger.get('nombre', '')} {first_passenger.get('apellido', '')}".strip(),
                        id_number=first_passenger.get('cedula'),
                        phone=first_passenger.get('telefono'),
                        email=first_passenger.get('email'),
                        session=session
                    )
                        
                    if booking_result.get('success'):
                        # Obtener precio de IDA
                        flight_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class', 'Y')
                        precio_ida = 0
                        
                        # Intentar obtener de varias fuentes posibles en sesión
                        flight_classes_prices = (
                            session.data.get('ida_flight_classes_prices') or 
                            session.data.get('flight_classes_prices') or 
                            {}
                        )
                        
                        if flight_classes_prices and flight_class.upper() in flight_classes_prices:
                            precio_ida = safe_float(flight_classes_prices[flight_class.upper()].get('price', 0))
                        else:
                            # Fallback: intentar buscar el precio en el vuelo seleccionado directamente
                            flights = session.data.get('available_flights', [])
                            flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                            if flights and 0 < flight_index <= len(flights):
                                precio_ida = safe_float(flights[flight_index - 1].get('price', 0))
                        
                        # Obtener datos del vuelo seleccionado
                        flights = session.data.get('available_flights', [])
                        flight_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                        selected_flight = flights[flight_index - 1] if flights and flight_index > 0 else {}
                        
                        # Obtener lista de pasajeros
                        all_passengers = session.data.get('passengers_list', [])
                        total_passengers = len(all_passengers)
                        
                        # Verificar si hay vuelo de vuelta
                        is_round_trip = session.data.get('is_round_trip', False)
                        return_flights = session.data.get('return_flights', [])
                        return_flight_index = session.data.get('selected_return_flight_index')
                        return_flight_class = session.data.get('selected_return_flight_class', flight_class)
                        return_flight = None
                        precio_vuelta = 0
                        
                        # DEBUG: Log para diagnosticar problema de vuelo de vuelta
                        logger.info(f"DEBUG is_round_trip: {is_round_trip}")
                        
                        if is_round_trip and return_flights and return_flight_index:
                            if return_flight_index >= 1 and return_flight_index <= len(return_flights):
                                return_flight = return_flights[return_flight_index - 1]
                                logger.info(f" Vuelo de vuelta encontrado: {return_flight.get('flight_number')}")
                                # Obtener precio de vuelta
                                return_classes_prices = session.data.get('return_flight_classes_prices', {})
                                if return_classes_prices and return_flight_class.upper() in return_classes_prices:
                                    precio_vuelta = safe_float(return_classes_prices[return_flight_class.upper()].get('price', 0))
                                else:
                                    precio_vuelta = safe_float(return_flight.get('price', 0))
                        else:
                            logger.warning(f" No se encontró vuelo de vuelta - return_flights: {bool(return_flights)}, return_flight_index: {return_flight_index}")
                        
                        # Calcular totales
                        precio_por_persona = precio_ida + precio_vuelta
                        precio_total = precio_por_persona * total_passengers if total_passengers > 0 else precio_por_persona
                        
                        # PRIORIDAD: Usar valores confirmados por la API si existen
                        if booking_result.get('raw_total_amount', 0) > 0:
                            precio_total = booking_result.get('raw_total_amount')
                            precio_por_persona = booking_result.get('raw_total_per_pax', precio_por_persona)
                        
                        return self._send_booking_success_message(
                            phone, session, booking_result, passengers_data, total_passengers,
                            selected_flight, flight_class, precio_ida,
                            return_flight, return_flight_class, precio_vuelta,
                            precio_por_persona, precio_total
                        )
                    else:
                        # Traducir error técnico a mensaje amigable
                        raw_error = booking_result.get('error', 'Error desconocido')
                        error_lower = raw_error.lower()
                        
                        user_msg = f"No se pudo crear la reserva: {raw_error}" # Default
                        
                        if "disponible" in error_lower or "availability" in error_lower or "no seats" in error_lower:
                            user_msg = f"El vuelo no está disponible. {raw_error}"
                        elif ("time limit" in error_lower or "expired" in error_lower) and "ticket" not in error_lower:
                            user_msg = "La sesión de reserva expiró. Por favor realiza la búsqueda nuevamente."
                        elif "availability" in error_lower or "no seats" in error_lower or "waitlist" in error_lower:
                            user_msg = "Ya no quedan asientos disponibles en esta clase. Intenta con otra fecha o clase."
                        elif "duplicate" in error_lower:
                            user_msg = "Ya existe una reserva activa para este pasajero en este vuelo."
                        elif "invalid" in error_lower:
                            user_msg = "Los datos parecen inválidos. Verifica que el número de cédula/pasaporte y los nombres sean correctos."
                        elif "restricted" in error_lower or "not allowed" in error_lower:
                            user_msg = "La aerolínea bloqueó la reserva. Puede ser por restricciones de tarifa o tiempo."

                        return self._send_response(phone, user_msg, session)
            
            # DETECCIÓN DE "MANUAL" PARA INGRESO DE DATOS
            message_clean = message.lower().strip()
            if message_clean == 'manual' and session.data.get('awaiting_flight_confirmation'):
                # Iniciar flujo manual
                session.data['extracted_data'] = {}  # Limpiar datos previos
                # Iniciar lista de pasajeros si no existe
                if not session.data.get('passengers_list'):
                    session.data['passengers_list'] = []
                
                # Determinar qué pasajero estamos procesando
                current_count = len(session.data['passengers_list'])
                total_passengers = session.data.get('num_passengers', 1)
                
                if current_count < total_passengers:
                    # Empezar a pedir datos comenzando por el Nombre
                    session.data['waiting_for_field'] = 'nombre'
                    passenger_label = f" (Pasajero {current_count + 1} de {total_passengers})" if total_passengers > 1 else ""
                    return self._send_response(phone, f"Entendido, ingreso manual. ¿Cuál es el *nombre* (sin apellidos) del pasajero?{passenger_label}", session)

            # DETECCIÓN DE SELECCIÓN DE CLASE (Interceptando a Gemini)
            # Solo si estamos esperando selección de clase
            # Verificar en qué etapa estamos:
            # 1. Ida: flight_classes_prices existe Y NO flight_confirmed
            # 2. Vuelta: return_flight_classes_prices existe Y flight_confirmed
            
            flight_prices = session.data.get('flight_classes_prices')
            return_prices = session.data.get('return_flight_classes_prices')
            has_selected_class = session.data.get('selected_flight_class') is not None
            ida_class_confirmed = session.data.get('ida_class_confirmed', False)
            
            # Ida: flight_prices existe Y aún NO ha seleccionado una clase
            waiting_for_class_ida = bool(flight_prices) and not has_selected_class
            # Vuelta: return_prices existe Y ida ya está confirmada Y aún NO ha seleccionado clase de vuelta
            has_selected_return_class = session.data.get('selected_return_flight_class') is not None
            waiting_for_class_vuelta = bool(return_prices) and ida_class_confirmed and not has_selected_return_class
            
            if waiting_for_class_ida or waiting_for_class_vuelta:
                # re ya importado al inicio del archivo
                msg_upper = message.upper().strip()
                
                # Buscar patrón fuerte: "Clase X", "Opción X", "La X", o solo "X" si es muy corto
                class_match = re.search(r'^(?:CLASE|OPCI[ÓO]N|LA|EL)?\s*([A-Z])$', msg_upper)
                
                # O si dice explícitamente "quiero la clase X"
                if not class_match:
                    class_match = re.search(r'QUIERO.*CLASE\s+([A-Z])', msg_upper)
                
                if class_match:
                    selected_class = class_match.group(1)
                    
                    # Determinar contexto (Ida o Vuelta)
                    is_return_flow = waiting_for_class_vuelta
                    prices_dict = return_prices if is_return_flow else flight_prices
                    
                    # Validar existencia de la clase
                    if prices_dict and selected_class in prices_dict:
                        logger.info(f" Interceptando selección de clase manual: {selected_class} (Return Flow: {is_return_flow})")
                        
                        # Obtener índice correcto
                        idx = session.data.get('selected_return_flight_index') if is_return_flow else session.data.get('selected_flight_index')
                        
                        if idx:
                            # Mensaje de feedback inmediato
                            wati_service.send_message(phone, f"Clase {selected_class} seleccionada. Preparando resumen de confirmación...")
                            
                            # Llamar a la función interna
                            result = self._confirm_flight_selection_function(idx, selected_class, session, is_return=is_return_flow)
                            
                            if result.get('success'):
                                if result.get('is_round_trip_summary'):
                                    # ES EL RESUMEN FINAL (Ya confirmó vuelta, ahora confirma TODO)
                                    response_text = f"Excelente. Te resumo tu itinerario completo: ida de {result.get('ida_ruta')} para el {result.get('ida_fecha')} con {result.get('ida_aerolinea')} (Clase {result.get('ida_clase')}), y regreso de {result.get('vuelta_ruta')} el {result.get('vuelta_fecha')} con {result.get('vuelta_aerolinea')} (Clase {result.get('vuelta_clase')}). El precio total para {result.get('num_passengers')} pasajeros es de {result.get('precio_total')} {result.get('moneda')}. ¿Confirmamos la reserva?"
                                else:
                                    # ES LA CONFIRMACIÓN DE UN SOLO VUELO (Ida o Vuelta)
                                    header_msg = "vuelo de regreso" if result.get('is_return_flight') else "vuelo"
                                    response_text = f"Has seleccionado un {header_msg} con {result.get('aerolinea')} ({result.get('vuelo')}) para la ruta {result.get('ruta')} el {format_date_dd_mm_yyyy(result.get('fecha'))}. Sale a las {result.get('salida')} y llega a las {result.get('llegada')}. La clase seleccionada es {result.get('clase_seleccionada')} con un precio de ${result.get('precio')} {result.get('moneda')}. ¿Es correcto?"

                                # IMPORTANTE: Agregar al historial de Gemini para que sepa que ya pidió confirmación
                                history = session.data.get('ai_history', [])
                                history.append({"role": "user", "parts": [{"text": message}]})
                                history.append({"role": "model", "parts": [{"text": response_text}]})
                                session.data['ai_history'] = history
                                
                                return self._send_response(phone, response_text, session)
                                
            # INTERCEPCIÓN DE "SI" PARA CONFIRMAR VUELO DE VUELTA Y MOSTRAR RESUMEN FINAL
            # Si estamos esperando confirmación de vuelo y es un vuelo de REGRESO que aún no está "fully confirmed"
            if session.data.get('awaiting_flight_confirmation') and session.data.get('selected_return_flight_index') and not session.data.get('return_flight_fully_confirmed'):
                msg_upper = message.strip().upper()
                if msg_upper in ['SI', 'SÍ', 'YES', 'CONFIRMO', 'CORRECTO']:
                    logger.info("Interceptando confirmación de vuelo de regreso - mostrando resumen final")
                    
                    # Marcar como confirmado completamente
                    session.data['return_flight_fully_confirmed'] = True
                    
                    # Llamar a la función de confirmación para generar el resumen final
                    idx = session.data.get('selected_return_flight_index')
                    cls_code = session.data.get('selected_return_flight_class')
                    if idx and cls_code:
                        result = self._confirm_flight_selection_function(idx, cls_code, session, is_return=True)
                        if result.get('success') and result.get('is_round_trip_summary'):
                            response_text = f"Excelente. Te resumo tu itinerario completo: ida de {result.get('ida_ruta')} para el {format_date_dd_mm_yyyy(result.get('ida_fecha'))} con {result.get('ida_aerolinea')} (Clase {result.get('ida_clase')}), y regreso de {result.get('vuelta_ruta')} el {format_date_dd_mm_yyyy(result.get('vuelta_fecha'))} con {result.get('vuelta_aerolinea')} (Clase {result.get('vuelta_clase')}). El precio total para {result.get('num_passengers')} pasajeros es de {result.get('precio_total')} {result.get('moneda')}. ¿Confirmamos la reserva?"
                            
                            # Actualizar historial
                            history = session.data.get('ai_history', [])
                            history.append({"role": "user", "parts": [{"text": message}]})
                            history.append({"role": "model", "parts": [{"text": response_text}]})
                            session.data['ai_history'] = history
                            
                            return self._send_response(phone, response_text, session)

            # DETECCIÓN AUTOMÁTICA DE CÓDIGO PNR (6 caracteres alfanuméricos)
            # re ya importado al inicio del archivo
            potential_pnr = message.strip().upper()
            pnr_match = re.match(r'^[A-Z0-9]{6}$', potential_pnr)
            
            # Lista de palabras comunes que NO son PNR
            palabras_excluidas = [
                # Saludos y respuestas comunes
                'BUENOS', 'BUENAS', 'HOLA', 'ADIOS', 'CHAO',
                'GRACIAS', 'THANKS', 'PLEASE', 'PORFA',
                # Palabras de vuelos
                'VUELOS', 'VUELTA', 'AVION', 'AVIONES',
                # Ciudades y lugares
                'BOGOTA', 'MADRID', 'PANAMA', 'MEXICO', 'ITALIA',
                'MERIDA', 'CUMANA', 'MARGARITA',
                # Meses
                'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
                'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE',
                # Días
                'LUNES', 'MARTES', 'JUEVES', 'VIERNES', 'SABADO', 'DOMINGO',
                # Respuestas comunes
                'QUIERO', 'BUSCAR', 'RESERVA', 'RESERVAR', 'COMPRAR',
                'SALIR', 'VIAJAR', 'FECHAS', 'PRECIO', 'PRECIOS',
                'PAGAR', 'TARJETA', 'EFECTIVO', 'CANCELAR',
                'AYUDA', 'MANUAL', 'IMAGEN', 'CEDULA',
                # Nacionalidades
                'VENEZOLANO', 'COLOMBIANO', 'PERUANO', 'CHILENO', 'ARGENTINO',
                # Otros
                'CORREO', 'CORRECTO', 'EXACTO', 'PERFECTO',
                'NUMERO', 'PASAJERO', 'PASAJERA', 'SI', 'NO', 'CONFIRMO',
                # Clases
                'ECONOMICA', 'BUSINESS', 'PRIMERA', 'CLASE',
            ]
            
            # Un PNR válido debe:
            # 1. Tener exactamente 6 caracteres alfanuméricos
            # 2. NO ser una palabra común
            # 3. Preferiblemente tener al menos un número (los PNR reales suelen tener números)
            es_palabra_comun = potential_pnr in palabras_excluidas
            tiene_numero = any(c.isdigit() for c in potential_pnr)
            
            # Solo considerar como PNR si:
            # - Tiene al menos un número, O
            # - No es una palabra común (para PNR como "ABCDEF" que son raros pero existen)
            es_pnr_valido = pnr_match and (tiene_numero or not es_palabra_comun)
            
            if es_pnr_valido:
                pnr_code = potential_pnr
                logger.info(f"Código PNR detectado automáticamente: {pnr_code}")
                
                # Enviar mensaje de "consultando"
                wati_service.send_message(phone, f" Consultando reserva {pnr_code}...")
                
                # Consultar directamente sin pasar por Gemini
                result = self._get_booking_function(pnr_code)
                if result.get('success'):
                    # Usar el mensaje formateado de la función
                    response = result.get('message')
                    # Agregar al historial
                    history = session.data.get('ai_history', [])
                    history.append({"role": "user", "parts": [{"text": message}]})
                    history.append({"role": "model", "parts": [{"text": response}]})
                    session.data['ai_history'] = history
                    return self._send_response(phone, response, session)
                else:
                    error_response = f"*Reserva no encontrada*\n\nPNR: *{pnr_code}*\n\nVerifica el código e intenta de nuevo."
                    # Agregar al historial
                    history = session.data.get('ai_history', [])
                    history.append({"role": "user", "parts": [{"text": message}]})
                    history.append({"role": "model", "parts": [{"text": error_response}]})
                    session.data['ai_history'] = history
                    return self._send_response(phone, error_response, session)
            # DETECCIÓN DIRECTA DE REQUISITOS MIGRATORIOS (Fallback si Gemini falla)
            # Si el mensaje menciona "requisitos", "necesito", "viajar a" + país
            message_lower = message.lower()
            requisitos_keywords = ['requisito', 'necesito para', 'qué necesito', 'que necesito', 'documentos para', 'viajar a']
            if any(keyword in message_lower for keyword in requisitos_keywords):
                # Extraer país del mensaje
                paises_conocidos = ['cuba', 'méxico', 'mexico', 'panamá', 'panama', 'colombia', 'perú', 'peru', 
                                   'chile', 'argentina', 'brasil', 'ecuador', 'bolivia', 'uruguay', 'paraguay',
                                   'españa', 'estados unidos', 'usa', 'miami', 'madrid', 'república dominicana']
                
                pais_detectado = None
                for pais in paises_conocidos:
                    if pais in message_lower:
                        pais_detectado = pais
                        break
                
                if pais_detectado:
                    logger.info(f"Detección directa de requisitos para: {pais_detectado}")
                    result = self._get_requirements_function(pais_detectado)
                    
                    if result.get('success'):
                        requisitos = result.get('requisitos', {})
                        
                        # Verificar si requisitos es un diccionario o un string
                        if isinstance(requisitos, str):
                            # Si es string, usarlo directamente
                            response_text = f"*REQUISITOS PARA VIAJAR A {pais_detectado.upper()}*\n\n"
                            response_text += f"{requisitos}\n\n"
                            response_text += "¿Necesitas ayuda con algo más?"
                        else:
                            # Si es diccionario, extraer campos
                            response_text = f"Aquí tienes información sobre los requisitos para viajar a {pais_detectado.upper()}:\n\n"
                            response_text += f"{requisitos.get('descripcion', 'Información no disponible')}\n\n"
                            
                            if requisitos.get('documentos'):
                                response_text += "Necesitarás los siguientes documentos: " + ", ".join(requisitos['documentos']) + ".\n"
                            
                            if requisitos.get('vacunas'):
                                response_text += "En cuanto a vacunas: " + ", ".join(requisitos['vacunas']) + ".\n"
                            
                            if requisitos.get('notas'):
                                response_text += f"Nota importante: {requisitos['notas']}\n\n"
                            
                            response_text += "¿Te puedo ayudar con algo más?"
                        
                        # Agregar al historial
                        history = session.data.get('ai_history', [])
                        history.append({"role": "user", "parts": [{"text": message}]})
                        history.append({"role": "model", "parts": [{"text": response_text}]})
                        session.data['ai_history'] = history
                        
                        return self._send_response(phone, response_text, session)
            
            # Si no es un PNR, continuar con el flujo normal de Gemini
            # Obtener fecha actual
            dias_es = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
            hoy_dt = datetime.now()
            dia_semana_hoy = dias_es[hoy_dt.weekday()]
            fecha_hoy = hoy_dt.strftime("%Y-%m-%d")
            fecha_manana = (hoy_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            
            # System instruction con fecha actual y día de la semana
            system_with_date = self.system_instruction + f"\n\n**FECHA ACTUAL: {fecha_hoy} ({dia_semana_hoy})**\nCuando el usuario diga 'hoy' usa: {fecha_hoy}\nCuando el usuario diga 'mañana' usa: {fecha_manana}\nCuando la fecha es relativa (ej: 'el jueves'), CALCULA la fecha exacta sumando días a la FECHA ACTUAL ({dia_semana_hoy})."
            # Obtener historial de conversación
            history = session.data.get('ai_history', [])
            
            # Preparar partes del mensaje
            message_parts = [{"text": message}]
            
            # Si hay imagen, descargarla y agregarla
            if media_url:
                try:
                    logger.info(f"Descargando imagen para Gemini: {media_url}")
                    download_result = wati_service.download_media(media_url)
                    
                    if download_result.get('success') and download_result.get('content'):
                        image_data = download_result.get('content')
                        # Convertir a base64
                        image_b64 = base64.b64encode(image_data).decode('utf-8')
                        
                        # Agregar imagen como primera parte (o segunda, depende de preferencia)
                        message_parts.append({
                            "inline_data": {
                                "mime_type": "image/jpeg", # Asumimos jpeg por ahora, o detectar
                                "data": image_b64
                            }
                        })
                        logger.info("Imagen agregada al contexto de Gemini")
                    else:
                        logger.warning(f"No se pudo descargar la imagen: {download_result.get('error')}")
                        message_parts[0]["text"] += f"\n[El usuario envió una imagen pero no se pudo procesar: {download_result.get('error')}]"
                except Exception as e:
                    logger.error(f"Error procesando imagen en chat: {e}")
                    message_parts[0]["text"] += f"\n[Error procesando imagen: {str(e)}]"

            # Agregar mensaje del usuario
            history.append({
                "role": "user",
                "parts": message_parts
            })
            # Definir herramientas disponibles
            tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name="search_flights",
                            description="Busca vuelos de IDA disponibles entre dos ciudades en una fecha específica. Para vuelos de ida y vuelta, llama esta función dos veces (ida y vuelta por separado). IMPORTANTE: Debes llamar esta función INMEDIATAMENTE cuando tengas toda la información necesaria (origen, destino, fecha, pasajeros). NO confirmes los datos con texto, llama directamente.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "origin": {
                                        "type": "string",
                                        "description": "Código IATA de la ciudad de origen (ej: CCS, PMV, MIA)"
                                    },
                                    "destination": {
                                        "type": "string",
                                        "description": "Código IATA de la ciudad de destino"
                                    },
                                    "date": {
                                        "type": "string",
                                        "description": "Fecha del vuelo en formato YYYY-MM-DD"
                                    },
                                    "trip_type": {
                                        "type": "string",
                                        "description": "Tipo de viaje: 'ida' o 'vuelta'. OBLIGATORIO.",
                                        "enum": ["ida", "vuelta"]
                                    },
                                    "is_round_trip": {
                                        "type": "boolean",
                                        "description": "Indica si el viaje completo es IDA Y VUELTA (True) o SOLO IDA (False). OBLIGATORIO."
                                    },
                                    "num_passengers": {
                                        "type": "integer",
                                        "description": "Número TOTAL de pasajeros. OBLIGATORIO."
                                    },
                                    "adults": {
                                        "type": "integer",
                                        "description": "Número de adultos (12+ años). Opcional, por defecto num_passengers."
                                    },
                                    "children": {
                                        "type": "integer",
                                        "description": "Número de niños (2-11 años). Opcional, por defecto 0."
                                    },
                                    "infants": {
                                        "type": "integer",
                                        "description": "Número de infantes (0-2 años). Opcional, por defecto 0."
                                    },
                                    "return_date": {
                                        "type": "string",
                                        "description": "Fecha de regreso en formato YYYY-MM-DD. Opcional, pero RECOMENDADO si el usuario ya la proporcionó."
                                    }
                                },
                                "required": ["origin", "destination", "date", "trip_type", "num_passengers"]
                            }
                        ),
                        types.FunctionDeclaration(
                            name="get_booking_details",
                            description="Consulta los detalles de una reserva usando el código PNR",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "pnr": {
                                        "type": "string",
                                        "description": "Código PNR de 6 caracteres de la reserva"
                                    }
                                },
                                "required": ["pnr"]
                            }
                        ),
                        types.FunctionDeclaration(
                            name="get_travel_requirements",
                            description="OBLIGATORIO: Llama a esta función cuando el usuario pregunte sobre requisitos migratorios, documentos necesarios, o qué se necesita para viajar a un país. Obtiene los requisitos migratorios completos.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "country": {
                                        "type": "string",
                                        "description": "Nombre del país en minúsculas (ej: cuba, mexico, venezuela, bolivia, brasil)"
                                    }
                                },
                                "required": ["country"]
                            }
                        ),
                        types.FunctionDeclaration(
                            name="select_flight_and_get_prices",
                            description="OBLIGATORIO: Llama esta función cuando el usuario seleccione un vuelo (ejemplo: 'opción 1', 'vuelo 2', 'el primero'). Esta función muestra el resumen del vuelo y pide confirmación. Para vuelos de REGRESO, usa is_return=true.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "flight_index": {
                                        "type": "integer",
                                        "description": "Número del vuelo seleccionado (1, 2, 3, etc.)"
                                    },
                                    "is_return": {
                                        "type": "boolean",
                                        "description": "True si es vuelo de REGRESO/VUELTA, False si es vuelo de IDA. Por defecto es False."
                                    }
                                },
                                "required": ["flight_index"]
                            }
                        ),
                        types.FunctionDeclaration(
                            name="confirm_flight_and_get_prices",
                            description="Llama esta función cuando el usuario CONFIRME el vuelo mostrado (dice 'sí', 'confirmo', 'ok', 'dale'). Obtiene los precios de todas las clases disponibles.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "is_return": {
                                        "type": "boolean",
                                        "description": "True si es vuelo de REGRESO/VUELTA, False si es vuelo de IDA. Por defecto es False."
                                    }
                                },
                                "required": []
                            }
                        ),
                        types.FunctionDeclaration(
                            name="confirm_flight_selection",
                            description="Muestra los detalles del vuelo seleccionado con la clase elegida y pide confirmación al usuario ANTES de proceder con la reserva. SOLO llama esta función DESPUÉS de que el usuario haya elegido una clase de las opciones mostradas. Para vuelos de IDA Y VUELTA, después de seleccionar la clase del vuelo de VUELTA, esta función mostrará el resumen de AMBOS vuelos.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "flight_index": {
                                        "type": "integer",
                                        "description": "Número del vuelo seleccionado (1, 2, 3, etc.)"
                                    },
                                    "flight_class": {
                                        "type": "string",
                                        "description": "Código de la clase seleccionada (ej: Y, B, C, D). Debe ser una de las clases disponibles mostradas al usuario."
                                    },
                                    "is_return": {
                                        "type": "boolean",
                                        "description": "True si es vuelo de REGRESO/VUELTA, False si es vuelo de IDA. Por defecto es False."
                                    }
                                },
                                "required": ["flight_index", "flight_class"]
                            }
                        ),

                        types.FunctionDeclaration(
                            name="create_booking",
                            description="Crea una reserva de vuelo con los datos del pasajero y la clase seleccionada. Pide los datos necesarios antes de llamar esta función.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "flight_index": {
                                        "type": "integer",
                                        "description": "Número del vuelo seleccionado de la lista (1, 2, 3, etc.)"
                                    },
                                    "flight_class": {
                                        "type": "string",
                                        "description": "Código de la clase seleccionada (ej: Y, B, C, D)"
                                    },
                                    "passenger_name": {
                                        "type": "string",
                                        "description": "Nombre completo del pasajero (ej: Juan Perez)"
                                    },
                                    "id_number": {
                                        "type": "string",
                                        "description": "Número de cédula del pasajero (7-8 dígitos, sin V- ni E-)"
                                    },
                                    "phone": {
                                        "type": "string",
                                        "description": "Número de teléfono del pasajero (10-11 dígitos, ejemplo: 04121234567)"
                                    },
                                    "email": {
                                        "type": "string",
                                        "description": "Email del pasajero"
                                    },
                                    "city": {
                                        "type": "string",
                                        "description": "Ciudad del pasajero (opcional, por defecto: Caracas)"
                                    },
                                    "address": {
                                        "type": "string",
                                        "description": "Dirección del pasajero (opcional, por defecto: Av Principal)"
                                    }
                                },
                                "required": ["flight_index", "flight_class", "passenger_name", "id_number", "phone", "email"]
                            }
                        )
                    ]
                )
            ]
            # Llamar a Gemini con herramientas (con reintentos para error 503)
            if not self.client:
                logger.error("Cliente Gemini no inicializado")
                return self._send_response(phone, " Error de configuración: El servicio de IA no está disponible.", session)
            
            max_retries = 3
            retry_delay = 2
            response = None
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=history,
                        config=types.GenerateContentConfig(
                            system_instruction=system_with_date,
                            tools=tools,
                            temperature=0.7  # Aumentado de 0.4 a 0.7 para reducir respuestas vacías
                        )
                    )
                    break
                except Exception as api_error:
                    error_str = str(api_error)
                    if '503' in error_str or 'overloaded' in error_str.lower() or 'UNAVAILABLE' in error_str:
                        if attempt < max_retries - 1:
                            logger.warning(f"Gemini sobrecargado, reintentando en {retry_delay}s (intento {attempt + 1}/{max_retries})")
                            # time ya importado al inicio del archivo
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            logger.error(f"Gemini no disponible después de {max_retries} intentos")
                            return self._send_response(phone, " El servicio de IA está temporalmente sobrecargado. Por favor, intenta de nuevo en unos segundos.", session)
                    else:
                        raise
            if not response:
                return self._send_response(phone, " No se pudo conectar con el servicio de IA. Intenta de nuevo.", session)
            
            # Procesar respuesta con reintentos si viene vacía
            max_empty_retries = 2
            for empty_attempt in range(max_empty_retries + 1):
                try:
                    # Verificar si hay candidatos válidos
                    if not response.candidates:
                        logger.warning(f"Respuesta sin candidatos (intento {empty_attempt + 1})")
                        if empty_attempt < max_empty_retries:
                            # time ya importado al inicio del archivo
                            time.sleep(1)
                            response = self.client.models.generate_content(
                                model=self.model,
                                contents=history,
                                config=types.GenerateContentConfig(
                                    system_instruction=system_with_date,
                                    tools=tools,
                                    temperature=0.5 + (empty_attempt * 0.2)
                                )
                            )
                            continue
                        break
                    
                    candidate = response.candidates[0]
                    
                    # Log del finish_reason para diagnóstico
                    finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                    logger.info(f"Gemini finish_reason: {finish_reason}")
                    
                    # Verificar si fue bloqueado por seguridad
                    if str(finish_reason) in ['SAFETY', 'BLOCKED', 'RECITATION']:
                        logger.warning(f"Respuesta bloqueada por: {finish_reason}")
                        return self._send_response(phone, "No pude procesar esa solicitud. ¿Podrías reformularla?", session)
                    
                    if candidate.content and candidate.content.parts:
                        # Primero buscar si hay alguna llamada a función en las partes
                        function_call_part = next((p for p in candidate.content.parts if hasattr(p, 'function_call') and p.function_call), None)
                        
                        if function_call_part:
                            # SI HAY LLAMADA A FUNCIÓN: SUPRIMIR SIEMPRE EL TEXTO DE LA AI
                            # Esto evita mensajes alucinados o redundantes como "Perfecto, busco..."
                            # ya que nosotros manejamos los mensajes de estado manualmente en _handle_function_call
                            func_name = function_call_part.function_call.name
                            
                            for part in candidate.content.parts:
                                if hasattr(part, 'text') and part.text:
                                    # Guardar en historial para mantener contexto, pero NO ENVIAR al usuario
                                    history.append({"role": "model", "parts": [{"text": part.text}]})
                                    logger.info(f"Texto de AI suprimido (Function Call {func_name}): {part.text[:50]}...")
                            
                            # Luego manejar la llamada a función
                            return self._handle_function_call(session, phone, response, history)
                        
                        # Si no hay función, procesar texto normal
                        ai_response = ""
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                ai_response += part.text
                        
                        if ai_response:
                            # Agregar respuesta al historial
                            history.append({
                                "role": "model",
                                "parts": [{"text": ai_response}]
                            })
                            session.data['ai_history'] = history
                            return self._send_response(phone, ai_response, session)
                    
                    # Si llegamos aquí, la respuesta está vacía
                    logger.warning(f"Respuesta vacía de Gemini (intento {empty_attempt + 1}/{max_empty_retries + 1})")
                    
                    if empty_attempt < max_empty_retries:
                        # time ya importado al inicio del archivo
                        time.sleep(1)
                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=history,
                            config=types.GenerateContentConfig(
                                system_instruction=system_with_date,
                                tools=tools,
                                temperature=0.5 + (empty_attempt * 0.2)
                            )
                        )
                        continue
                    
                except Exception as parse_error:
                    logger.error(f"Error parseando respuesta (intento {empty_attempt + 1}): {parse_error}")
                    if empty_attempt < max_empty_retries:
                        # time ya importado al inicio del archivo
                        time.sleep(1)
                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=history,
                            config=types.GenerateContentConfig(
                                system_instruction=system_with_date,
                                tools=tools,
                                temperature=0.5 + (empty_attempt * 0.2)
                            )
                        )
                        continue
                    break
            
            # Si después de todos los reintentos no hay respuesta útil
            logger.error("No se pudo obtener respuesta útil de Gemini después de múltiples intentos")
            return self._send_response(phone, " Tuve un problema procesando tu mensaje. ¿Podrías intentar de nuevo?", session)
        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            logger.error(f"Error procesando con AI: {error_type}: {error_str}", exc_info=True)
            if '503' in error_str or 'overloaded' in error_str.lower() or 'UNAVAILABLE' in error_str:
                return self._send_response(phone, " El servicio de IA está temporalmente sobrecargado. Por favor, intenta de nuevo en unos segundos.", session)
            elif '429' in error_str or 'quota' in error_str.lower():
                return self._send_response(phone, " Se ha alcanzado el límite de solicitudes. Por favor, intenta de nuevo en un momento.", session)
            else:
                # DEBUG: Mostrar error real para diagnosticar
                error_detail = f"{error_type}: {error_str[:200]}"
                return self._send_response(phone, f"Tuve un problema procesando tu solicitud. ¿Podrías intentar de nuevo?\n\nDEBUG: {error_detail}", session)
    def _handle_function_call(self, session, phone, response, history):
        """Maneja las llamadas a funciones"""
        try:
            # Calcular fecha actual para el follow-up
            dias_es = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
            hoy_dt = datetime.now()
            dia_semana_hoy = dias_es[hoy_dt.weekday()]
            fecha_hoy = hoy_dt.strftime("%Y-%m-%d")
            fecha_manana = (hoy_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            
            # System instruction con fecha actual y día de la semana
            system_with_date = self.system_instruction + f"\n\n**FECHA ACTUAL: {fecha_hoy} ({dia_semana_hoy})**\nCuando el usuario diga 'hoy' usa: {fecha_hoy}\nCuando el usuario diga 'mañana' usa: {fecha_manana}\nCuando la fecha es relativa (ej: 'el jueves'), CALCULA la fecha exacta sumando días a la FECHA ACTUAL ({dia_semana_hoy})."
            # Encontrar el part que contiene la llamada a función
            function_call = next((p.function_call for p in response.candidates[0].content.parts if hasattr(p, 'function_call') and p.function_call), None)
            if not function_call:
                return self._send_response(phone, "No pude procesar la función solicitada.", session)
                
            function_name = function_call.name
            function_args = dict(function_call.args)
            logger.info(f"Llamando función: {function_name} con args: {function_args}")
            # Ejecutar la función correspondiente
            if function_name == "search_flights":
                # Enviar mensaje de "buscando" ANTES de ejecutar la búsqueda
                origin = function_args.get('origin')
                destination = function_args.get('destination')
                date = function_args.get('date')
                trip_type = function_args.get('trip_type', 'ida')
                # Nuevos campos detallados - Conversión segura de tipos
                safe_int = lambda x, default: int(float(x)) if x is not None and str(x).replace('.', '', 1).isdigit() else default
                
                # Asegurar que num_passengers tenga un valor válido
                raw_num_passengers = function_args.get('num_passengers')
                num_passengers = safe_int(raw_num_passengers, 1)
                
                # Extraer y convertir desglose de pasajeros
                adults = safe_int(function_args.get('adults'), num_passengers)
                children = safe_int(function_args.get('children'), 0)
                infants = safe_int(function_args.get('infants'), 0)
                
                # Si adults=0 pero hay niños/infantes, o si adults no se pasó, recalcular
                if adults == 0 and (children > 0 or infants > 0):
                    # Asumir que num_passengers es el total
                    remaining = num_passengers - children - infants
                    adults = max(1, remaining)
                
                # Si no se pasó num_passengers explícito pero sí desglose
                if num_passengers <= 1 and (children > 0 or infants > 0):
                    num_passengers = adults + children + infants
                
                # RESET DE ESTADOS DE CONFIRMARCIÓN PARA NUEVA BÚSQUEDA
                if trip_type == 'ida':
                    session.data['flight_confirmed'] = False
                    session.data['return_flight_confirmed'] = False
                    session.data['ida_class_confirmed'] = False
                    session.data['flight_selection_fully_confirmed'] = False
                    session.data['awaiting_flight_confirmation'] = False
                    session.data.pop('selected_flight_index', None)
                    session.data.pop('selected_flight_class', None)
                    session.data.pop('selected_return_flight_index', None)
                    session.data.pop('selected_return_flight_class', None)
                    session.data.pop('pending_flight_index', None)
                    session.data.pop('pending_return_flight_index', None)
                    session.data.pop('flight_classes_prices', None)
                    session.data.pop('return_flight_classes_prices', None)
                    session.data.pop('ida_flight_classes_prices', None)
                    session.data.pop('available_flights', None)
                    session.data.pop('return_flights', None)
                    session.data.pop('search_results', None)
                    session.data.pop('ida_flight_index', None)
                    session.data.pop('ida_flight_class', None)

                session.data['num_passengers'] = num_passengers
                session.data['num_adults'] = adults
                session.data['num_children'] = children
                session.data['num_infants'] = infants
                session.data['passengers_list'] = []  # Inicializar lista de pasajeros
                
                # Guardar return_date si existe
                if function_args.get('return_date'):
                    session.data['return_date'] = function_args.get('return_date')
                
                # Determinar tipo de viaje para el mensaje
                tipo_viaje = "Solo Ida" if trip_type == 'ida' else "Vuelta"
                
                pasajeros_texto = []
                if adults > 0: pasajeros_texto.append(f"{adults} Adulto(s)")
                if children > 0: pasajeros_texto.append(f"{children} Niño(s)")
                if infants > 0: pasajeros_texto.append(f"{infants} Infante(s)")
                if not pasajeros_texto: # Si por alguna razón está vacío
                    pasajeros_texto.append(f"{num_passengers} Pasajero(s)")
                pax_str = ", ".join(pasajeros_texto)
                
                # Guardar el tipo de viaje global en la sesión
                # Si viene explícito, lo usamos
                if 'is_round_trip' in function_args:
                    session.data['is_round_trip'] = function_args['is_round_trip']
                
                # REGLA DE SEGURIDAD: Si trip_type es 'vuelta', IMPLICA que es round trip
                if trip_type == 'vuelta':
                    session.data['is_round_trip'] = True
                    
                is_round_trip = session.data.get('is_round_trip', False)
                logger.info(f"Tipo de viaje global: {'Ida y Vuelta' if is_round_trip else 'Solo Ida'}")
                
                # CONFIRMACIÓN EXPLÍCITA DEL VUELO DE IDA
                if trip_type == 'vuelta':
                    try:
                        ida_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index') or session.data.get('pending_flight_index')
                        ida_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class') or 'Y' # Default Y
                        flights = session.data.get('available_flights', [])
                        
                        if ida_index and flights and 0 < ida_index <= len(flights):
                            ida_flight = flights[ida_index - 1]
                            
                            # Consolidar datos de IDA en la sesión
                            session.data['flight_confirmed'] = True
                            session.data['ida_flight_index'] = ida_index
                            session.data['ida_flight_class'] = ida_class
                            
                            # Intentar obtener precio
                            precio_str = ""
                            prices = session.data.get('flight_classes_prices', {})
                            if prices and ida_class in prices:
                                p = prices[ida_class].get('price')
                                if p: precio_str = f"(${p} USD)"
                            elif ida_flight.get('price'):
                                precio_str = f"(${ida_flight.get('price')} USD)"

                            msg_ida = (
                                f"*Vuelo de IDA confirmado:*\n"
                                f"Aerolinea: {ida_flight.get('airline_name')} {ida_flight.get('flight_number')}\n"
                                f"Fecha: {format_date_dd_mm_yyyy(ida_flight.get('date'))} - {ida_flight.get('departure_time')}\n"
                                f"Clase {ida_class} {precio_str}\n\n"
                                f"Ahora buscaré tu regreso..."
                            )
                            self._send_response(phone, msg_ida, session)
                    except Exception as e:
                        logger.error(f"Error confirmando ida manualmente: {e}")

                self._send_response(phone, f"Buscando los mejores vuelos para ti...\n\nRuta: {origin} → {destination}\nFecha: {format_date_dd_mm_yyyy(date)}\n{tipo_viaje}\n{pax_str}\n\nRevisando todas las opciones disponibles...", session)
                result = self._search_flights_function(
                    origin,
                    destination,
                    date,
                    session,
                    trip_type,
                    adults=adults,
                    children=children,
                    infants=infants
                )
            elif function_name == "get_booking_details":
                pnr = function_args.get('pnr')
                self._send_response(phone, f"Consultando reserva {pnr}...", session)
                result = self._get_booking_function(pnr)
            elif function_name == "get_travel_requirements":
                result = self._get_requirements_function(function_args.get('country'))
            elif function_name == "select_flight_and_get_prices":
                # Nueva función: seleccionar vuelo y mostrar resumen
                is_return = function_args.get('is_return', False)
                flight_type = "REGRESO" if is_return else "IDA"
                
                self._send_response(phone, f"Seleccionando vuelo de {flight_type}...", session)
                
                result = self._select_flight_and_get_prices_function(
                    function_args.get('flight_index'),
                    session,
                    is_return
                )
            elif function_name == "confirm_flight_and_get_prices":
                # Confirmar vuelo y obtener precios de clases
                is_return = function_args.get('is_return', False)
                flight_type = "REGRESO" if is_return else "IDA"
                
                # Marcar como confirmado
                if is_return:
                    session.data['return_flight_confirmed'] = True
                    flight_index = session.data.get('pending_return_flight_index')
                else:
                    session.data['flight_confirmed'] = True
                    flight_index = session.data.get('pending_flight_index')
                
                if not flight_index:
                    result = {"success": False, "message": "No hay vuelo pendiente de confirmación."}
                else:
                    self._send_response(phone, f"Consultando precios de las clases disponibles para el vuelo de {flight_type}, un momento...", session)
                    result = self._select_flight_and_get_prices_function(
                        flight_index,
                        session,
                        is_return
                    )
            elif function_name == "confirm_flight_selection":
                is_return = function_args.get('is_return', False)
                
                self._send_response(phone, " *Preparando confirmación de vuelo...*", session)
                
                result = self._confirm_flight_selection_function(
                    function_args.get('flight_index'),
                    function_args.get('flight_class'),
                    session,
                    is_return
                )

            elif function_name == "create_booking":
                passenger_name = function_args.get('passenger_name', 'pasajero')
                self._send_response(phone, f"Creando tu reserva... Pasajero: {passenger_name}. Un momento por favor.", session)
                result = self._create_booking_function(
                    function_args.get('flight_index'),
                    function_args.get('flight_class'),
                    passenger_name,
                    function_args.get('id_number'),
                    function_args.get('phone'),
                    function_args.get('email'),
                    session,
                    function_args.get('city'),
                    function_args.get('address')
                )
            else:
                result = {"error": "Función no reconocida"}
            # MANEJO MANUAL DE RESPUESTAS ESTRUCTURADAS
            # Si la función devuelve un mensaje formateado (ej: confirmaciones, tablas),
            # lo enviamos directamente para evitar que la AI lo modifique o alucine.
            structured_message = result.get('message')
            if structured_message and isinstance(structured_message, str):
                # Solo enviar directo si parece un mensaje final formateado (empieza con emojis o tiene estructura)
                if any(start in structured_message for start in ['*VUELO', '*CLASE', '*RESUMEN', '*DETALLES', '*RESERVA']):
                    logger.info("Enviando mensaje estructurado directamente (bypass AI generation)")
                    
                    # Agregar al historial como si la AI lo hubiera generado
                    history.append({
                        "role": "model",
                        "parts": [{"text": structured_message}]
                    })
                    session.data['ai_history'] = history
                    
                    return self._send_response(phone, structured_message, session)
            
            # Si no es un mensaje estructurado, flujo normal
            # Agregar la llamada a función y el resultado al historial
            history.append({
                "role": "model",
                "parts": [{"function_call": function_call}]
            })
            history.append({
                "role": "function",
                "parts": [{"function_response": {
                    "name": function_name,
                    "response": result
                }}]
            })
            # Llamar de nuevo a Gemini con el resultado (con reintentos)
            max_follow_up_retries = 3
            ai_response = None
            
            for attempt in range(max_follow_up_retries):
                try:
                    follow_up = self.client.models.generate_content(
                        model=self.model,
                        contents=history,
                        config=types.GenerateContentConfig(
                            system_instruction=system_with_date,
                            temperature=1.0
                        )
                    )
                    
                    # Validar respuesta
                    if follow_up and follow_up.candidates and len(follow_up.candidates) > 0:
                        candidate = follow_up.candidates[0]
                        if candidate.content and candidate.content.parts and len(candidate.content.parts) > 0:
                            first_part = candidate.content.parts[0]
                            if hasattr(first_part, 'text') and first_part.text:
                                ai_response = first_part.text
                                break
                    
                    # Si no hay respuesta válida, reintentar
                    if attempt < max_follow_up_retries - 1:
                        logger.warning(f"Respuesta vacía de Gemini en intento {attempt + 1}, reintentando...")
                        # time ya importado al inicio del archivo
                        time.sleep(1)
                        continue
                        
                except Exception as retry_error:
                    logger.warning(f"Error en follow-up intento {attempt + 1}: {str(retry_error)}")
                    if attempt < max_follow_up_retries - 1:
                        # time ya importado al inicio del archivo
                        time.sleep(2)
                        continue
                    else:
                        raise
            
            if ai_response:
                # Agregar respuesta final al historial
                history.append({
                    "role": "model",
                    "parts": [{"text": ai_response}]
                })
                session.data['ai_history'] = history
                return self._send_response(phone, ai_response, session)
            else:
                # Si no hay respuesta después de reintentos, enviar mensaje por defecto
                logger.warning("No se obtuvo respuesta de Gemini después de reintentos")
                return self._send_response(phone, "He procesado tu solicitud. ¿En qué más puedo ayudarte?", session)
        except Exception as e:
            # traceback ya importado al inicio del archivo
            error_details = traceback.format_exc()
            error_str = str(e).lower()
            error_type = type(e).__name__
            logger.error(f"Error manejando función: {str(e)}\nTraceback:\n{error_details}")
            
            # DEBUG: Incluir error real en el mensaje
            debug_info = f"\n\n DEBUG: {error_type}: {str(e)[:200]}"
            
            # Mensajes de error más específicos según el tipo de problema
            if 'timeout' in error_str or 'timed out' in error_str or 'connection' in error_str:
                return self._send_response(phone, f"La búsqueda tardó demasiado. El servidor está tardando en responder. Intenta de nuevo en unos segundos.{debug_info}", session)
            elif '503' in error_str or 'unavailable' in error_str or 'overloaded' in error_str:
                return self._send_response(phone, f"El servidor está temporalmente ocupado. Intenta de nuevo en 30 segundos.{debug_info}", session)
            elif '429' in error_str or 'quota' in error_str or 'rate limit' in error_str:
                return self._send_response(phone, f"Límite de solicitudes alcanzado. Espera 1 minuto e intenta de nuevo.{debug_info}", session)
            elif 'invalid' in error_str or 'argument' in error_str:
                return self._send_response(phone, f"Parece que hay un problema con los datos ingresados. Verifica la información e intenta de nuevo.{debug_info}", session)
            else:
                return self._send_response(phone, f"Hubo un problema con la búsqueda. Intenta de nuevo. Si persiste, prueba con otra fecha o ruta.{debug_info}", session)
    def _search_flights_function(self, origin, destination, date, session, trip_type='ida', adults=1, children=0, infants=0):
        """Busca vuelos usando el servicio"""
        try:
            # MAPEO DE CIUDADES A CÓDIGOS IATA
            iata_codes = {
                'CARACAS': 'CCS', 'MAIQUETIA': 'CCS', 'LA GUAIRA': 'CCS',
                'MARGARITA': 'PMV', 'PORLAMAR': 'PMV', 
                'MARACAIBO': 'MAR', 'ZULIA': 'MAR',
                'VALENCIA': 'VLN', 'CARABOBO': 'VLN',
                'PUERTO ORDAZ': 'PZO', 'GUAYANA': 'PZO', 'CIUDAD GUAYANA': 'PZO',
                'BARCELONA': 'BLA', 'ANZOATEGUI': 'BLA',
                'MERIDA': 'MRD', # MRD is Alberto Carnevalli (city), VIG is El Vigia (usually used for Merida)
                'EL VIGIA': 'VIG', 'VIGIA': 'VIG', 'ALBERTO ADRIANI': 'VIG',
                'BARQUISIMETO': 'BRM', 'LARA': 'BRM',
                'CUMANA': 'CUM', 'SUCRE': 'CUM',
                'MATURIN': 'MUN', 'MONAGAS': 'MUN',
                'SANTO DOMINGO': 'STD', 'TACHIRA': 'STD',
                'SAN CRISTOBAL': 'STD', # Serves San Cristobal
                'LA FRIA': 'LFR', 'GARCIA DE HEVIA': 'LFR',
                'SAN ANTONIO': 'SVZ', 'SAN ANTONIO DEL TACHIRA': 'SVZ',
                'VALERA': 'VLV', 'TRUJILLO': 'VLV',
                'CORO': 'CZE', 'FALCON': 'CZE',
                'LAS PIEDRAS': 'LSP', 'PUNTO FIJO': 'LSP', 'PARAGUANA': 'LSP',
                'CIUDAD BOLIVAR': 'CBL',
                'CANAIMA': 'CAJ',
                'LOS ROQUES': 'LRV',
                'PORLAMAR': 'PMV',
                'PUERTO AYACUCHO': 'PYH', 'AMAZONAS': 'PYH',
                'SAN FERNANDO': 'SFD', 'APURE': 'SFD',
                'ACARIGUA': 'AGV', 'PORTUGUESA': 'AGV',
                'GUASDUALITO': 'GDO',
                'TUCUPITA': 'TUV', 'DELTA AMACURO': 'TUV',
                
                # INTERNACIONALES
                'MIAMI': 'MIA',
                'PANAMA': 'PTY', 'TOCUMEN': 'PTY',
                'BOGOTA': 'BOG', 'EL DORADO': 'BOG',
                'MEDELLIN': 'MDE', 'RIO NEGRO': 'MDE',
                'MADRID': 'MAD', 'BARAJAS': 'MAD',
                'SANTO DOMINGO RD': 'SDQ', 'REPUBLICA DOMINICANA': 'SDQ',
                'PUNTA CANA': 'PUJ',
                'CANCUN': 'CUN', 'MEXICO': 'MEX',
                'LIMA': 'LIM', 'PERU': 'LIM',
                'SANTIAGO': 'SCL', 'CHILE': 'SCL',
                'BUENOS AIRES': 'EZE', 'ARGENTINA': 'EZE',
                'SAO PAULO': 'GRU', 'BRASIL': 'GRU',
                'LISBOA': 'LIS', 'PORTUGAL': 'LIS',
                'TENERIFE': 'TFN',
                'CURAZAO': 'CUR', 'WILLEMSTAD': 'CUR',
                'ARUBA': 'AUA',
                'BONAIRE': 'BON',
                'TRINIDAD': 'POS', 'PUERTO ESPAÑA': 'POS'
            }
            
            # Normalizar origen
            origin_upper = origin.upper().strip()
            if len(origin_upper) > 3:
                # Intentar mapear nombre de ciudad a código
                for city, code in iata_codes.items():
                    if city in origin_upper:
                        origin = code
                        break
            
            # Normalizar destino
            dest_upper = destination.upper().strip()
            if len(dest_upper) > 3:
                # Intentar mapear nombre de ciudad a código
                for city, code in iata_codes.items():
                    if city in dest_upper:
                        destination = code
                        break
            
            logger.info(f"Buscando vuelos normalizado: {origin} -> {destination}")

            # Construir diccionario de pasajeros para la BÚSQUEDA
            # IMPORTANTE: La API de búsqueda KIU puede no soportar CHD/INF
            # correctamente, así que buscamos con el total de pasajeros como ADT
            # Los tipos reales (ADT/CHD/INF) se usan al momento del BOOKING
            total_pax = adults + children + infants
            if total_pax < 1:
                total_pax = 1
            passengers = {"ADT": total_pax}
            
            logger.info(f"Pasajeros para búsqueda: {passengers} (real: ADT={adults}, CHD={children}, INF={infants})")

            # Intentar búsqueda con reintentos agresivos en caso de timeout
            max_retries = 5
            flights = None
            last_error = None
            for attempt in range(max_retries):
                try:
                    flights = flight_service.search_flights(
                        origin=origin,
                        destination=destination,
                        date=date,
                        passengers=passengers
                    )
                    break
                except Exception as search_error:
                    last_error = str(search_error)
                    error_lower = last_error.lower()
                    if 'timeout' in error_lower or 'tardó demasiado' in error_lower or 'timed out' in error_lower or 'connection' in error_lower:
                        if attempt < max_retries - 1:
                            logger.warning(f"Error en búsqueda (intento {attempt + 1}/{max_retries}): {last_error}")
                            # time ya importado al inicio del archivo
                            wait_time = 5 + (attempt * 2)
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Todos los intentos fallaron: {last_error}")
                    else:
                        raise

            if not flights:
                # Mensaje mejorado con información sobre reintentos
                logger.error(f"flights es None o vacío: {flights}")
                error_msg = f"Lo siento, no encontré vuelos disponibles para ir de {origin} a {destination} el {date}."
                if last_error:
                    error_lower = last_error.lower()
                    if 'timeout' in error_lower or 'connection' in error_lower:
                        error_msg += " El sistema tardó mucho en responder. Por favor, intenta de nuevo en un momento."
                    else:
                        error_msg += " Podría ser que no hay operaciones ese día o están agotados. ¿Te gustaría intentar con otra fecha?"
                return {
                    "success": False, 
                    "message": error_msg
                }
                return {
                    "success": False, 
                    "message": error_msg
                }
            # Guardar vuelos en la sesión según el tipo de viaje
            if trip_type == 'vuelta':
                session.data['return_flights'] = flights
            else:
                session.data['available_flights'] = flights
            # Formatear vuelos para la IA con TODOS los campos
            flights_data = []
            for i, flight in enumerate(flights, 1):  # TODOS los vuelos
                api_data = flight.get('api_data', {})
                segments = api_data.get('segments', [])
                segment = segments[0] if segments else {}
                # Construir ruta completa si hay múltiples segmentos
                if len(segments) > 1:
                    route_parts = []
                    for seg in segments:
                        if not route_parts:
                            route_parts.append(seg.get('departureCode', ''))
                        route_parts.append(seg.get('arrivalCode', ''))
                    ruta_completa = ' → '.join(route_parts)
                    escalas = len(segments) - 1
                else:
                    ruta_completa = f"{flight.get('origin')} → {flight.get('destination')}"
                    escalas = 0
                currency_symbol = "$"
                # Extraer y clasificar clases disponibles
                clases_disponibles = segment.get('classes', {})
                economy_classes = []
                business_classes = []
                first_classes = []
                # Validar que clases_disponibles sea un diccionario
                if isinstance(clases_disponibles, dict):
                    for clase_code, asientos in clases_disponibles.items():
                        if clase_code in ['Y', 'B', 'M', 'H', 'Q', 'V', 'W', 'S', 'T', 'L', 'K', 'G', 'U', 'E', 'N', 'R', 'O']:
                            economy_classes.append({"codigo": clase_code, "asientos": asientos})
                        elif clase_code in ['J', 'C', 'D', 'I', 'Z']:
                            business_classes.append({"codigo": clase_code, "asientos": asientos})
                        elif clase_code in ['F', 'A', 'P']:
                            first_classes.append({"codigo": clase_code, "asientos": asientos})
                        else:
                            economy_classes.append({"codigo": clase_code, "asientos": asientos})
                flight_info = {
                    "numero": i,
                    "aerolinea": flight.get('airline_name'),
                    "vuelo": flight.get('flight_number'),
                    "ruta": ruta_completa,
                    "escalas": escalas,
                    "salida": flight.get('departure_time'),
                    "llegada": flight.get('arrival_time'),
                    "duracion": flight.get('duration'),
                    "precio_total": f"{currency_symbol}{flight.get('price'):.2f}" if flight.get('price') else "Consultar",
                    "moneda": flight.get('currency', 'USD'),
                    "clases_economica": economy_classes,
                    "clases_business": business_classes,
                    "clases_primera": first_classes,
                    "internacional": api_data.get('international', False),
                    "directo": api_data.get('isDirect', True)
                }
                flights_data.append(flight_info)
            return {
                "success": True,
                "total": len(flights),
                "vuelos": flights_data,
                "ruta": f"{origin} → {destination}",
                "fecha": format_date_dd_mm_yyyy(date),
                "tipo_viaje": "Solo Ida" if trip_type == 'ida' else "Vuelta"
            }
        except Exception as e:
            logger.error(f"Error buscando vuelos: {str(e)}")
            return {"success": False, "error": str(e)}
    def _get_booking_function(self, pnr):
        """Consulta una reserva con TODOS los detalles posibles de KIU"""
        try:
            result = flight_service.get_booking_details(pnr=pnr)
            
            # DEBUG: Ver respuesta completa
            logger.info(f"=== RESPUESTA COMPLETA DE KIU ===")
            logger.info(f"Success: {result.get('success')}")
            logger.info(f"Flights: {result.get('flights')}")
            logger.info(f"Passengers: {result.get('passengers')}")
            
            if not result.get('success'):
                return {"success": False, "message": "Reserva no encontrada"}
            
            # Obtener datos
            pasajeros = result.get('passengers', [])
            vuelos = result.get('flights', [])
            precio_total = result.get('balance', 'N/A')
            estado = result.get('status', 'N/A')
            vencimiento = result.get('vencimiento', '')
            vid = result.get('vid', '')
            base = result.get('base', '')
            ruta = result.get('route', '')
            flight_status = result.get('flight_status', '')
            
            # Determinar tipo de viaje
            num_vuelos = len(vuelos)
            tipo_viaje = "IDA Y VUELTA" if num_vuelos >= 2 else "SOLO IDA"
            
            # Formatear mensaje natural
            mensaje = f"Aquí tienes los detalles de la reserva {result.get('pnr', pnr)}.\n"
            mensaje += f"Estado actual: {estado}.\n"
            
            if vid:
                mensaje += f"VID: {vid}.\n"
                
            mensaje += f"Es un viaje de {tipo_viaje} para {len(pasajeros)} pasajeros:\n"
            
            pax_names = []
            for pax in pasajeros:
                pax_names.append(pax.get('nombre', 'Pasajero'))
            mensaje += ", ".join(pax_names) + ".\n\n"
            
            # Vuelos
            if vuelos:
                mensaje += "Itinerario:\n"
                for i, vuelo in enumerate(vuelos, 1):
                    ruta_vuelo = vuelo.get('ruta', 'N/A')
                    if '-' in ruta_vuelo and '→' not in ruta_vuelo:
                        ruta_vuelo = ruta_vuelo.replace('-', ' a ')
                        
                    mensaje += f"Vuelo {i}: {vuelo.get('aerolinea', '')} {vuelo.get('vuelo', '')} de {ruta_vuelo}. "
                    mensaje += f"Sale el {format_date_dd_mm_yyyy(vuelo.get('fecha', ''))} a las {vuelo.get('hora_salida', '')} y llega a las {vuelo.get('hora_llegada', '')}.\n"
            
            # Precio
            mensaje += f"\nTotal a pagar: {precio_total}."

            return {
                "success": True,
                "message": mensaje,
                "pnr": result.get('pnr'),
                "estado": estado,
                "pasajeros_count": len(pasajeros),
                "vuelos_count": num_vuelos,
                "precio_total": precio_total,
                "pasajeros": pasajeros,
                "vuelos": vuelos
            }
        except Exception as e:
            logger.error(f"Error consultando reserva: {str(e)}")
            return {"success": False, "error": str(e)}
    def _get_requirements_function(self, country):
        """Obtiene requisitos migratorios"""
        try:
            requisitos = get_requisitos_pais(country.lower())
            if requisitos:
                return {"success": True, "requisitos": requisitos}
            else:
                return {"success": False, "message": "País no encontrado en la base de datos"}
        except Exception as e:
            logger.error(f"Error obteniendo requisitos: {str(e)}")
            return {"success": False, "error": str(e)}
    def _select_flight_and_get_prices_function(self, flight_index, session, is_return=False):
        """Selecciona un vuelo, muestra resumen y pide confirmación antes de obtener precios"""
        try:
            # Seleccionar la lista correcta según si es vuelo de ida o vuelta
            if is_return:
                flights = session.data.get('return_flights', [])
                flight_type = "REGRESO"
            else:
                flights = session.data.get('available_flights', [])
                flight_type = "IDA"
            
            if not flights:
                return {"success": False, "message": f"No hay vuelos de {flight_type} disponibles. Primero debes buscar vuelos."}
            if flight_index < 1 or flight_index > len(flights):
                return {"success": False, "message": f"Número de vuelo inválido. Debe ser entre 1 y {len(flights)}"}
            
            selected_flight = flights[flight_index - 1]
            
            # AUTO-CONFIRMAR SIEMPRE PARA EVITAR PREGUNTAS REDUNDANTES
            # Guardar índice en sesión
            if is_return:
                session.data['pending_return_flight_index'] = flight_index
                session.data['return_flight_confirmed'] = True # Auto-confirmar
            else:
                session.data['pending_flight_index'] = flight_index
                session.data['flight_confirmed'] = True # Auto-confirmar
        
            # ACTIVAR MODO CONFIRMACIÓN (Aunque ya no pedimos confirmación explícita, mantenemos el estado por compatibilidad)
            session.data['awaiting_flight_confirmation'] = True
            session.data['flight_selection_fully_confirmed'] = False

            # PROCEDER DIRECTAMENTE A OBTENER PRECIOS
            airline = selected_flight.get('airline_name', 'N/A')
            flight_num = selected_flight.get('flight_number', 'N/A')
            logger.info(f"=== OBTENIENDO PRECIOS PARA VUELO DE {flight_type} {flight_index}: {airline} {flight_num} ===")
            
            # Obtener precios de todas las clases
            pricing_result = flight_service.get_all_class_prices(selected_flight)
            if not pricing_result.get('success'):
                return {
                    "success": False,
                    "message": "No se pudieron obtener los precios de las clases. Por favor intenta de nuevo."
                }
            
            classes_prices = pricing_result.get('classes_prices', {})
            if not classes_prices:
                return {
                    "success": False,
                    "message": "No se encontraron precios disponibles para este vuelo."
                }
            
            # Guardar precios en sesión
            if is_return:
                session.data['return_flight_classes_prices'] = classes_prices
            else:
                session.data['flight_classes_prices'] = classes_prices
            
            # Clasificar clases por tipo
            economy_classes = []
            business_classes = []
            first_classes = []
            economy_codes = ['Y', 'B', 'M', 'H', 'Q', 'V', 'W', 'S', 'T', 'L', 'K', 'G', 'U', 'E', 'N', 'R', 'O']
            business_codes = ['J', 'C', 'D', 'I', 'Z']
            first_codes = ['F', 'A', 'P']
            
            for class_code, class_data in classes_prices.items():
                class_info = {
                    "codigo": class_code,
                    "precio": class_data['price'],
                    "asientos": class_data['availability']
                }
                if class_code in economy_codes:
                    economy_classes.append(class_info)
                elif class_code in business_codes:
                    business_classes.append(class_info)
                elif class_code in first_codes:
                    first_classes.append(class_info)
                else:
                    economy_classes.append(class_info)
            
            # Ordenar por precio
            economy_classes.sort(key=lambda x: x['precio'])
            business_classes.sort(key=lambda x: x['precio'])
            first_classes.sort(key=lambda x: x['precio'])
            
            return {
                "success": True,
                "flight_index": flight_index,
                "aerolinea": selected_flight.get('airline_name'),
                "vuelo": selected_flight.get('flight_number'),
                "ruta": f"{selected_flight.get('origin')} → {' → '.join([s.get('arrivalCode') for s in selected_flight.get('api_data', {}).get('segments', [])])}" if len(selected_flight.get('api_data', {}).get('segments', [])) > 1 else f"{selected_flight.get('origin')} → {selected_flight.get('destination')}",
                "fecha": format_date_dd_mm_yyyy(selected_flight.get('date')),
                "salida": selected_flight.get('departure_time'),
                "llegada": selected_flight.get('arrival_time'),
                "duracion": selected_flight.get('duration'),
                "economy_classes": economy_classes,
                "business_classes": business_classes,
                "first_classes": first_classes,
                "total_classes": len(classes_prices),
                "message": f"Vuelo confirmado: {selected_flight.get('airline_name')} {selected_flight.get('flight_number')} - Fecha: {format_date_dd_mm_yyyy(selected_flight.get('date'))}. Aquí están los precios de todas las clases disponibles."
            }
        except Exception as e:
            logger.error(f"Error obteniendo precios de clases: {str(e)}")
            return {"success": False, "error": str(e)}
    def _confirm_flight_selection_function(self, flight_index, flight_class, session, is_return=False):
        """Muestra detalles del vuelo seleccionado con la clase elegida y pide confirmación. Para IDA Y VUELTA, muestra resumen de ambos vuelos."""
        try:
            # Seleccionar la lista correcta según si es vuelo de ida o vuelta
            if is_return:
                flights = session.data.get('return_flights', [])
                flight_type = "REGRESO"
            else:
                flights = session.data.get('available_flights', [])
                flight_type = "IDA"
            
            if not flights:
                return {"success": False, "message": f"No hay vuelos de {flight_type} disponibles. Primero debes buscar vuelos."}
            
            # Validar parámetros
            if flight_index is None:
                flight_index = session.data.get('selected_flight_index', 1)
            if flight_class is None:
                return {"success": False, "message": "Por favor selecciona una clase de vuelo."}
            
            if flight_index < 1 or flight_index > len(flights):
                return {"success": False, "message": f"Número de vuelo inválido. Debe ser entre 1 y {len(flights)}"}
            selected_flight = flights[flight_index - 1]
            # Validar que la clase existe en el vuelo
            api_data = selected_flight.get('api_data', {})
            segments = api_data.get('segments', [])
            if segments:
                available_classes = segments[0].get('classes', {})
                if flight_class.upper() not in available_classes:
                    return {"success": False, "message": f"La clase {flight_class} no está disponible en este vuelo. Clases disponibles: {', '.join(available_classes.keys())}"}
            # Guardar vuelo y clase seleccionados en sesión (diferenciando ida y vuelta)
            if is_return:
                session.data['selected_return_flight_index'] = flight_index
                session.data['selected_return_flight_class'] = flight_class.upper()
            else:
                session.data['selected_flight_index'] = flight_index
                session.data['selected_flight_class'] = flight_class.upper()
            session.data['awaiting_flight_confirmation'] = True
            session.data['flight_selection_fully_confirmed'] = False
            
            # SI ES VUELO DE VUELTA
            if is_return:
                # SIEMPRE mostramos el resumen completo IDA + VUELTA al seleccionar el regreso
                # Para cumplir con el flujo: Ida -> Vuelta -> Resumen -> Confirmación Final

                # Si ya confirmó, mostramos el resumen completo IDA + VUELTA
                # Obtener datos del vuelo de IDA (usar ida_ prefixed si disponible)
                ida_flights = session.data.get('available_flights', [])
                ida_index = session.data.get('ida_flight_index') or session.data.get('selected_flight_index', 1)
                ida_class = session.data.get('ida_flight_class') or session.data.get('selected_flight_class', 'Y')
                
                if ida_flights and ida_index >= 1 and ida_index <= len(ida_flights):
                    ida_flight = ida_flights[ida_index - 1]
                    
                    # Obtener precios
                    ida_classes_prices = session.data.get('ida_flight_classes_prices') or session.data.get('flight_classes_prices', {})
                    vuelta_classes_prices = session.data.get('return_flight_classes_prices', {})
                    
                    precio_ida = safe_float(ida_flight.get('price', 0))
                    if ida_classes_prices and ida_class.upper() in ida_classes_prices:
                        precio_ida = safe_float(ida_classes_prices[ida_class.upper()].get('price', precio_ida))
                    
                    precio_vuelta = safe_float(selected_flight.get('price', 0))
                    if vuelta_classes_prices and flight_class.upper() in vuelta_classes_prices:
                        precio_vuelta = safe_float(vuelta_classes_prices[flight_class.upper()].get('price', precio_vuelta))
                    
                    # Calcular total
                    num_passengers = session.data.get('num_passengers', 1)
                    precio_por_persona = precio_ida + precio_vuelta
                    precio_total = precio_por_persona * num_passengers
                    
                    return {
                        "success": True,
                        "is_round_trip_summary": True,
                        "num_passengers": num_passengers,
                        # Vuelo de IDA
                        "ida_aerolinea": ida_flight.get('airline_name'),
                        "ida_vuelo": ida_flight.get('flight_number'),
                        "ida_ruta": f"{ida_flight.get('origin')} → {ida_flight.get('destination')}",
                        "ida_fecha": ida_flight.get('date'),
                        "ida_salida": ida_flight.get('departure_time'),
                        "ida_llegada": ida_flight.get('arrival_time'),
                        "ida_clase": ida_class.upper(),
                        "ida_precio": f"{precio_ida:.2f}",
                        # Vuelo de VUELTA
                        "vuelta_aerolinea": selected_flight.get('airline_name'),
                        "vuelta_vuelo": selected_flight.get('flight_number'),
                        "vuelta_ruta": f"{selected_flight.get('origin')} → {selected_flight.get('destination')}",
                        "vuelta_fecha": selected_flight.get('date'),
                        "vuelta_salida": selected_flight.get('departure_time'),
                        "vuelta_llegada": selected_flight.get('arrival_time'),
                        "vuelta_clase": flight_class.upper(),
                        "vuelta_precio": f"{precio_vuelta:.2f}",
                        # Totales
                        "precio_por_persona": f"{precio_por_persona:.2f}",
                        "precio_total": f"{precio_total:.2f}",
                        "moneda": "USD",
                        "message": f"He preparado el resumen de tu viaje de ida y vuelta para {num_passengers} pasajeros.\n\nIda: {ida_flight.get('airline_name')} {ida_flight.get('flight_number')} el {format_date_dd_mm_yyyy(ida_flight.get('date'))} ({ida_flight.get('origin')} -> {ida_flight.get('destination')}). Sale a las {ida_flight.get('departure_time')} y llega a las {ida_flight.get('arrival_time')}.\n\nVuelta: {selected_flight.get('airline_name')} {selected_flight.get('flight_number')} el {format_date_dd_mm_yyyy(selected_flight.get('date'))} ({selected_flight.get('origin')} -> {selected_flight.get('destination')}). Sale a las {selected_flight.get('departure_time')} y llega a las {selected_flight.get('arrival_time')}.\n\nEl precio total es de ${precio_total:.2f} USD (${precio_por_persona:.2f} por persona).\n\n¿Te gustaría confirmar estos vuelos para proceder con la reserva?"
                    }
                else:
                    return {"success": False, "message": "No se encontró información del vuelo de IDA seleccionado."}
            
            # SI ES SOLO IDA, MOSTRAR CONFIRMACIÓN NORMAL
            # Extraer detalles del vuelo
            api_data = selected_flight.get('api_data', {})
            segments = api_data.get('segments', [])
            # Construir ruta completa
            if len(segments) > 1:
                route_parts = []
                for seg in segments:
                    if not route_parts:
                        route_parts.append(seg.get('departureCode', ''))
                    route_parts.append(seg.get('arrivalCode', ''))
                ruta = ' → '.join(route_parts)
                escalas = len(segments) - 1
            else:
                ruta = f"{selected_flight.get('origin')} → {selected_flight.get('destination')}"
                escalas = 0
            # Obtener asientos disponibles para la clase seleccionada
            asientos_disponibles = "N/A"
            if segments:
                available_classes = segments[0].get('classes', {})
                asientos_disponibles = available_classes.get(flight_class.upper(), "N/A")
            # Obtener el precio de la clase específica seleccionada
            precio_clase = safe_float(selected_flight.get('price', 0))
            # Intentar obtener el precio específico de la clase desde la sesión
            # Usar los precios correctos según sea ida o vuelta
            if is_return:
                flight_classes_prices = session.data.get('return_flight_classes_prices', {})
            else:
                flight_classes_prices = session.data.get('flight_classes_prices', {})
            
            if flight_classes_prices and flight_class.upper() in flight_classes_prices:
                precio_clase = safe_float(flight_classes_prices[flight_class.upper()].get('price', precio_clase))
            
            return {
                "success": True,
                "is_round_trip_summary": False,
                "flight_index": flight_index,
                "aerolinea": selected_flight.get('airline_name'),
                "vuelo": selected_flight.get('flight_number'),
                "ruta": ruta,
                "fecha": format_date_dd_mm_yyyy(selected_flight.get('date')),
                "salida": selected_flight.get('departure_time'),
                "llegada": selected_flight.get('arrival_time'),
                "duracion": selected_flight.get('duration'),
                "precio": f"{precio_clase:.2f}" if precio_clase else "Consultar",
                "moneda": selected_flight.get('currency', 'USD'),
                "clase_seleccionada": flight_class.upper(),
                "asientos_disponibles": asientos_disponibles,
                "escalas": escalas,
                "equipaje": api_data.get('baggage', []),
                "message": f"Excelente elección. Has seleccionado el vuelo {selected_flight.get('airline_name')} {selected_flight.get('flight_number')} de {selected_flight.get('origin')} a {selected_flight.get('destination')} para el {format_date_dd_mm_yyyy(selected_flight.get('date'))}.\n\nEl vuelo sale a las {selected_flight.get('departure_time')} y llega a las {selected_flight.get('arrival_time')}. La tarifa en clase {flight_class.upper()} es de ${precio_clase:.2f} USD.\n\n¿Deseas confirmar este vuelo?"
            }
        except Exception as e:
            logger.error(f"Error confirmando selección: {str(e)}")
            return {"success": False, "error": str(e)}
    def _extract_cedula_data(self, image_url):
        """Extrae nombre, apellido y cédula de la imagen usando Gemini Vision"""
        try:
            import requests
            # base64, json, re ya importados al inicio del archivo
            logger.info(f"Descargando imagen de cédula: {image_url}")
            # Descargar imagen
            response = requests.get(image_url, timeout=15)
            if response.status_code != 200:
                logger.error(f"Error descargando imagen: {response.status_code}")
                return {"success": False, "error": "No se pudo descargar la imagen"}
            logger.info(f"Imagen descargada: {len(response.content)} bytes")
            # Convertir a base64
            image_data = base64.b64encode(response.content).decode('utf-8')
            # Prompt mejorado para Gemini Vision
            prompt = """Analiza esta imagen de cédula de identidad venezolana y extrae:

1. NOMBRE: El primer nombre de la persona (solo el primero)
2. APELLIDO: Todos los apellidos juntos
3. CEDULA: El número de cédula (solo dígitos, sin V-, E-, puntos ni guiones)

IMPORTANTE: Responde SOLO con un objeto JSON válido, sin texto adicional. NO extraigas el sexo/género.

{
  "nombre": "PRIMER_NOMBRE",
  "apellido": "APELLIDOS",
  "cedula": "12345678"
}

Si no puedes leer algún dato, usa "NO_LEGIBLE" como valor."""
            logger.info("Llamando a Gemini Vision para extraer datos...")
            # Llamar a Gemini Vision
            vision_response = self.client.models.generate_content(
                model=self.model,
                contents=[{
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_data
                        }}
                    ]
                }],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    top_p=0.95
                )
            )
            # Extraer respuesta
            if not vision_response.candidates or not vision_response.candidates[0].content.parts:
                logger.error("Gemini no retornó respuesta válida")
                return {"success": False, "error": "No se obtuvo respuesta de la IA"}
            text_response = vision_response.candidates[0].content.parts[0].text.strip()
            logger.info(f"Respuesta de Gemini: {text_response[:200]}...")
            # Limpiar respuesta (remover markdown)
            text_response = re.sub(r'```json\s*', '', text_response)
            text_response = re.sub(r'```\s*', '', text_response)
            text_response = text_response.strip()
            # Intentar parsear JSON
            try:
                data = json.loads(text_response)
            except json.JSONDecodeError as je:
                logger.error(f"Error parseando JSON: {je}")
                logger.error(f"Texto recibido: {text_response}")
                return {"success": False, "error": "Respuesta inválida de la IA"}
            # Validar datos extraídos
            nombre = data.get('nombre', '').strip().upper()
            apellido = data.get('apellido', '').strip().upper()
            cedula = re.sub(r'[^0-9]', '', str(data.get('cedula', '')))
            logger.info(f"Datos extraídos - Nombre: {nombre}, Apellido: {apellido}, Cédula: {cedula}")
            # Verificar que los datos sean válidos
            if nombre and apellido and cedula and nombre != "NO_LEGIBLE" and apellido != "NO_LEGIBLE" and cedula != "NO_LEGIBLE":
                if len(cedula) >= 6:  # Cédula debe tener al menos 6 dígitos
                    return {
                        "success": True,
                        "nombre": nombre,
                        "apellido": apellido,
                        "cedula": cedula
                    }
                else:
                    logger.error(f"Cédula muy corta: {cedula}")
            else:
                logger.error(f"Datos incompletos o no legibles")
            return {"success": False, "error": "No se pudieron extraer todos los datos"}
        except Exception as e:
            logger.error(f"Excepción extrayendo datos de cédula: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}
    def _extract_contact_info(self, message):
        """Extrae teléfono y correo del mensaje"""
        try:
            # re ya importado al inicio del archivo
            # Buscar teléfono (números de 10-11 dígitos)
            phone_match = re.search(r'(\d{10,11})', message)
            # Buscar email
            email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', message)
            if phone_match and email_match:
                return {
                    "success": True,
                    "telefono": phone_match.group(1),
                    "email": email_match.group(1)
                }
            return {"success": False}
        except Exception as e:
            logger.error(f"Error extrayendo contacto: {str(e)}")
            return {"success": False}
    def _get_full_route(self, flight):
        """Obtiene la ruta completa del vuelo incluyendo escalas"""
        try:
            api_data = flight.get('api_data', {})
            segments = api_data.get('segments', [])
            
            if len(segments) > 1:
                # Vuelo con escalas - construir ruta completa
                route = [segments[0].get('departureCode', '')]
                for seg in segments:
                    route.append(seg.get('arrivalCode', ''))
                return ' → '.join(route)
            else:
                # Vuelo directo
                return f"{flight.get('origin', 'N/A')} → {flight.get('destination', 'N/A')}"
        except:
            return f"{flight.get('origin', 'N/A')} → {flight.get('destination', 'N/A')}"

    def _send_booking_success_message(self, phone, session, booking_result, passengers_data, total_passengers, selected_flight, flight_class, precio_ida, return_flight=None, return_flight_class=None, precio_vuelta=0, precio_por_persona=0, precio_total=0):
        """Envía el mensaje de éxito de la reserva"""
        try:
            # Construir tipo de viaje
            if booking_result.get('multiple_pnr'):
                response = f"¡Todo listo! He procesado tus reservas exitosamente. Como son aerolíneas diferentes, tienes dos códigos de confirmación: {booking_result.get('pnr_ida')} para la ida ({booking_result.get('airline_ida', 'N/A')}) y {booking_result.get('pnr_vuelta')} para la vuelta ({booking_result.get('airline_vuelta', 'N/A')})."
            else:
                response = f"¡Todo listo! He procesado tu reserva exitosamente. Tu código de confirmación (PNR) es {booking_result.get('pnr')}."

            # Pasajeros
            pax_names = []
            for pax in passengers_data:
                pax_names.append(f"{pax.get('nombre', '')} {pax.get('apellido', '')}")
            
            pax_list_str = ", ".join(pax_names)
            response += f" El viaje es para {total_passengers} pasajeros: {pax_list_str}."

            # Detalles de vuelos
            response += f"\n\nResumen del itinerario:\n"
            response += f"Ida: Vuelo {selected_flight.get('flight_number', 'N/A')} de {selected_flight.get('airline_name', 'N/A')} el {format_date_dd_mm_yyyy(selected_flight.get('date', 'N/A'))}. Sale de {selected_flight.get('origin')} a las {selected_flight.get('departure_time', 'N/A')} y llega a {selected_flight.get('destination')} a las {selected_flight.get('arrival_time', 'N/A')}."
            
            if return_flight:
                response += f"\nVuelta: Vuelo {return_flight.get('flight_number', 'N/A')} de {return_flight.get('airline_name', 'N/A')} el {format_date_dd_mm_yyyy(return_flight.get('date', 'N/A'))}. Sale de {return_flight.get('origin')} a las {return_flight.get('departure_time', 'N/A')} y llega a {return_flight.get('destination')} a las {return_flight.get('arrival_time', 'N/A')}."

            # Costos
            response += f"\n\nEl precio total de la reserva es de ${precio_total:.2f} USD."
            
            response += "\n\n¡Buen viaje! Si necesitas consultar tu reserva más adelante, solo envíame el código PNR."
            
            # Limpiar datos de sesión COMPLETAMENTE para el siguiente viaje
            session.data.pop('extracted_data', None)
            session.data.pop('waiting_for_field', None)
            session.data.pop('awaiting_flight_confirmation', None)
            session.data.pop('flight_selection_fully_confirmed', None)
            session.data.pop('passengers_list', None)
            session.data.pop('num_passengers', None)
            session.data.pop('current_pax_index', None)
            session.data.pop('pending_flight_index', None)
            session.data.pop('selected_flight_index', None)
            session.data.pop('selected_flight_class', None)
            session.data.pop('selected_return_flight_index', None)
            session.data.pop('selected_return_flight_class', None)
            session.data.pop('is_round_trip', None)
            session.data.pop('trip_type', None)
            session.data.pop('flight_confirmed', None)
            session.data.pop('ida_flight_index', None)
            session.data.pop('ida_flight_class', None)
            session.data.pop('available_flights', None)
            session.data.pop('return_flights', None)
            session.data.pop('flight_classes_prices', None)
            session.data.pop('return_flight_classes_prices', None)
            session.data.pop('ida_flight_classes_prices', None)
            session.data.pop('awaiting_class_selection', None)
            session.data.pop('awaiting_class_selection_is_return', None)
            session.data.pop('ai_history', None) # Clear history for a clean slate

            return self._send_response(phone, response, session)
        except Exception as e:
            logger.error(f"Error enviando mensaje de éxito: {e}")
            return self._send_response(phone, "Reserva creada, pero hubo un error generando el mensaje de confirmación.", session)

    def _request_cedula_image_function(self, passenger_name, session):
        """Solicita imagen de cédula al usuario"""
        try:
            session.data['waiting_for_cedula_image'] = True
            session.data['current_passenger_name'] = passenger_name
            return {
                "success": True,
                "message": f"Perfecto. Para completar la reserva, necesito una foto de la cédula o pasaporte de {passenger_name}. Por favor envíamela y yo extraeré los datos automáticamente."
            }
        except Exception as e:
            logger.error(f"Error solicitando imagen: {str(e)}")
            return {"success": False, "error": str(e)}

    def _process_document_image(self, session, phone):
        """Procesa imagen de documento y extrae datos"""
        try:
            from document_extractor import document_extractor
            image_url = session.data.get('document_image_url')
            if not image_url:
                return {"success": False, "error": "No hay imagen de documento"}
            logger.info(f"Procesando imagen de documento: {image_url}")
            # Extraer datos del documento
            result = document_extractor.extract_from_image(image_url)
            if not result.get('success'):
                error_msg = result.get('error', 'No se pudieron extraer los datos')
                self._send_response(
                    phone,
                    f"No pude extraer los datos del documento: {error_msg}. Envíame una foto más clara o escribe *manual* para ingresar los datos a mano.",
                    session
                )
                return {"success": False, "error": error_msg}
            # Obtener datos extraídos
            data = result.get('data', {})
            missing_fields = result.get('missing_fields', [])
            document_type = result.get('document_type', 'unknown')
            # Guardar datos extraídos en sesión
            session.data['extracted_data'] = data
            session.data['missing_fields'] = missing_fields
            session.data['document_type'] = document_type
            # Construir mensaje de confirmación natural
            msg = "Perfecto, he podido leer los datos del documento:\n"
            
            detalles = []
            if data.get('nombre') and data.get('apellido'):
                detalles.append(f"Pasajero: {data['nombre']} {data['apellido']}")
            
            if data.get('cedula'):
                detalles.append(f"Cédula: {data['cedula']}")
            elif data.get('pasaporte'):
                detalles.append(f"Pasaporte: {data['pasaporte']}")
                
            if data.get('nacionalidad'):
                detalles.append(f"Nacionalidad: {data['nacionalidad']}")
                
            if data.get('fecha_nacimiento'):
                detalles.append(f"Nacimiento: {format_date_dd_mm_yyyy(data['fecha_nacimiento'])}")

            msg += " - ".join(detalles) + "."

            if missing_fields:
                msg += "\n\nPara completar el registro, todavía necesito que me indiques:\n"
                missing_labels = []
                for field in missing_fields:
                    field_names = {
                        'telefono': 'Teléfono contacto',
                        'email': 'Correo electrónico',
                        'nombre': 'Nombre',
                        'apellido': 'Apellido',
                        'cedula': 'Cédula',
                        'pasaporte': 'Pasaporte',
                        'nacionalidad': 'Nacionalidad',
                        'nacionalidad': 'Nacionalidad',
                        'sexo': 'Sexo'
                    }
                    missing_labels.append(field_names.get(field, field))
                
                # Unir con comas y "y" al final
                if len(missing_labels) > 1:
                    msg += ", ".join(missing_labels[:-1]) + " y " + missing_labels[-1] + "."
                else:
                    msg += missing_labels[0] + "."
            
            wati_service.send_message(phone, msg)
            return {
                "success": True,
                "data": data,
                "missing_fields": missing_fields,
                "document_type": document_type
            }
        except Exception as e:
            logger.error(f"Error procesando imagen de documento: {str(e)}", exc_info=True)
            wati_service.send_message(
                phone,
                f"Error procesando la imagen: {str(e)}. Intenta con otra foto o escribe *manual* para ingresar los datos a mano."
            )
            return {"success": False, "error": str(e)}
    def _create_booking_function(self, flight_index, flight_class, passenger_name, id_number, phone, email, session, city=None, address=None):
        """Crea una reserva de vuelo con los datos de TODOS los pasajeros y la clase seleccionada"""
        try:
            # Vuelo de IDA
            flights = session.data.get('available_flights', [])
            if not flights:
                return {"success": False, "message": "No hay vuelos disponibles. Primero debes buscar vuelos."}
            if flight_index < 1 or flight_index > len(flights):
                return {"success": False, "message": f"Número de vuelo inválido. Debe ser entre 1 y {len(flights)}"}
            selected_flight = flights[flight_index - 1]
            
            # Modificar la clase del vuelo de IDA
            if 'api_data' in selected_flight and 'segments' in selected_flight['api_data']:
                for segment in selected_flight['api_data']['segments']:
                    segment['class'] = flight_class.upper()
            selected_flight['class'] = flight_class.upper()
            
            # Vuelo de VUELTA (si existe)
            return_flight = None
            return_flights = session.data.get('return_flights', [])
            return_flight_index = session.data.get('selected_return_flight_index')
            return_flight_class = session.data.get('selected_return_flight_class', flight_class.upper())
            
            # DEBUG: Verificar datos de vuelta
            logger.info(f"=== VERIFICANDO VUELO DE VUELTA ===")
            logger.info(f"return_flights existe: {len(return_flights) if return_flights else 0} vuelos")
            logger.info(f"return_flight_index: {return_flight_index}")
            logger.info(f"return_flight_class: {return_flight_class}")
            
            is_round_trip = session.data.get('is_round_trip', False)
            if is_round_trip:
                if return_flights and return_flight_index:
                    if return_flight_index >= 1 and return_flight_index <= len(return_flights):
                        return_flight = return_flights[return_flight_index - 1]
                        # Modificar la clase del vuelo de VUELTA
                        if 'api_data' in return_flight and 'segments' in return_flight['api_data']:
                            for segment in return_flight['api_data']['segments']:
                                segment['class'] = return_flight_class.upper()
                        return_flight['class'] = return_flight_class.upper()
                        logger.info(f" Incluyendo vuelo de VUELTA: {return_flight.get('flight_number')} clase {return_flight_class}")
                    else:
                        logger.warning(f" return_flight_index {return_flight_index} fuera de rango (1-{len(return_flights)})")
                else:
                    logger.warning(f" No se encontró vuelo de vuelta para viaje redondo - return_flights: {bool(return_flights)}, return_flight_index: {return_flight_index}")
            
            # re ya importado al inicio del archivo
            
            # Obtener TODOS los pasajeros de la lista
            passengers_list = session.data.get('passengers_list', [])
            expected_passengers = session.data.get('num_passengers', 1)
            all_passengers = []
            
            # VALIDACIÓN CRÍTICA: Verificar que tenemos todos los pasajeros
            if passengers_list and len(passengers_list) < expected_passengers:
                logger.error(f" CRÍTICO: Faltan pasajeros - Esperados: {expected_passengers}, Recibidos: {len(passengers_list)}")
                return {
                    "success": False,
                    "error": f"Faltan datos de {expected_passengers - len(passengers_list)} pasajero(s). Por favor proporciona los datos de todos los pasajeros."
                }
            
            if passengers_list and len(passengers_list) > 0:
                # Usar los pasajeros de la lista
                for pax in passengers_list:
                    # Obtener nombre y apellido
                    first_name = pax.get('nombre', '').strip()
                    last_name = pax.get('apellido', '').strip()
                    pax_id = pax.get('cedula', '')
                    pax_phone = pax.get('telefono', phone)
                    pax_email = pax.get('email', email)
                    
                    # DETERMINAR TIPO DE PASAJERO (ADT/CHD/INF)
                    pax_type = pax.get('tipo', 'ADT')
                    
                    # Safety: recalcular tipo si tiene fecha de nacimiento y tipo no fue seteado
                    if pax_type == 'ADT' and pax.get('fecha_nacimiento'):
                        try:
                            born = datetime.strptime(pax['fecha_nacimiento'], '%Y-%m-%d')
                            today = datetime.now()
                            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                            if age < 2:
                                pax_type = 'INF'
                            elif age < 12:
                                pax_type = 'CHD'
                            logger.info(f"Tipo de pasajero recalculado: {first_name} {last_name} -> {pax_type} (edad {age})")
                        except:
                            pass
                    
                    # Limpiar datos
                    clean_phone = re.sub(r'[^0-9]', '', str(pax_phone))
                    
                    # DETERMINAR TIPO DE DOCUMENTO usando tipo_documento guardado
                    # Prefijos KIU: VCI (venezolano+cédula), VP (venezolano+pasaporte), 
                    #               ECI (extranjero+cédula), EP (extranjero+pasaporte)
                    tipo_doc = pax.get('tipo_documento', 'CI')  # 'CI' o 'P'
                    nacionalidad = pax.get('nacionalidad', 'VE')
                    
                    # Pre-limpiar Nacionalidad para detección
                    nac_clean = str(nacionalidad).upper().strip()
                    is_ve = any(k in nac_clean for k in ['VE', 'VEN', 'VENEZ']) or nac_clean == 'V'
                    
                    if tipo_doc == 'P' or 'PASAPORTE' in str(tipo_doc).upper():
                        # Pasaporte: permitir letras y números
                        clean_id = re.sub(r'[^a-zA-Z0-9]', '', str(pax_id))
                        # Para el bot, 'P' es suficiente; flight_service decidirá si es VP o EP
                        doc_type_for_kiu = 'P'
                    else:
                        # Cédula: solo números
                        clean_id = re.sub(r'[^0-9]', '', str(pax_id))
                        # Enviamos 'V' o 'E' para indicar el tipo de nacionalidad (Venezolana/Extranjera)
                        doc_type_for_kiu = 'V' if is_ve else 'E'
                    
                    passenger = {
                        'name': first_name.upper(),
                        'lastName': last_name.upper(),
                        'idNumber': clean_id,
                        'phone': clean_phone,
                        'email': pax_email.strip() if pax_email else email.strip(),
                        'type': pax_type,  # USAR TIPO REAL (ADT/CHD/INF)
                        'nationality': nacionalidad,
                        'documentType': doc_type_for_kiu,
                        'birthDate': pax.get('fecha_nacimiento', '1990-01-01'),
                        'gender': 'M' if any(x in str(pax.get('sexo', 'M')).upper() for x in ['M', 'MAS', 'H']) else 'F',
                        'phoneCode': '58',
                        # 'address': pax.get('direccion') or address or 'Av Principal', # OMITIDO
                        'city': pax.get('ciudad') or city or 'Caracas',
                        'zipCode': pax.get('zipCode') or '1010',
                        'state': pax.get('estado') or 'Distrito Capital',
                        'country': 'Venezuela',
                        'docExpiry': pax.get('fecha_vencimiento', '2030-01-01')
                    }

                    all_passengers.append(passenger)
                    logger.info(f"Pasajero agregado: {first_name} {last_name} tipo={pax_type} doc={doc_type_for_kiu}")
            else:
                # Fallback: usar los parámetros individuales (1 solo pasajero)
                name_parts = passenger_name.strip().split()
                first_name = name_parts[0] if name_parts else ''
                last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else name_parts[0]
                clean_id = re.sub(r'[^0-9]', '', id_number)
                clean_phone = re.sub(r'[^0-9]', '', phone)
                
                passenger = {
                    'name': first_name.upper(),
                    'lastName': last_name.upper(),
                    'idNumber': clean_id,
                    'phone': clean_phone,
                    'email': email.strip(),
                    'type': 'ADT',
                    'nationality': 'VE',
                    'documentType': 'V',
                    'birthDate': '1990-01-01',
                    'gender': 'M',
                    'phoneCode': '58',
                    # 'address': address,
                    'city': city,
                    'zipCode': '1010',
                    'state': 'Distrito Capital',
                    'country': 'Venezuela'
                }
                all_passengers.append(passenger)
            
            # Crear reserva con TODOS los pasajeros
            is_round_trip = return_flight is not None
            trip_type_log = "IDA Y VUELTA" if is_round_trip else "SOLO IDA"
            logger.info(f"Creando reserva {trip_type_log} para {len(all_passengers)} pasajero(s)")
            
            result = flight_service.create_booking(
                flight_option=selected_flight,
                passenger_details=all_passengers,
                return_flight_option=return_flight,  # Incluir vuelo de vuelta si existe
                user_phone=session.phone
            )
            if result.get('success'):
                # Calcular precio total correcto (Ida + Vuelta * Pasajeros)
                # Intentar obtener precio específico de la clase seleccionada
                price_ida = safe_float(selected_flight.get('price', 0)) # Default
                
                flight_classes_prices = session.data.get('ida_flight_classes_prices') or session.data.get('flight_classes_prices', {})
                if flight_classes_prices and flight_class.upper() in flight_classes_prices:
                     price_ida = safe_float(flight_classes_prices[flight_class.upper()].get('price', price_ida))
                
                price_vuelta = 0
                if return_flight:
                    price_vuelta = safe_float(return_flight.get('price', 0)) # Default
                    return_classes_prices = session.data.get('return_flight_classes_prices', {})
                    if return_classes_prices and return_flight_class.upper() in return_classes_prices:
                        price_vuelta = safe_float(return_classes_prices[return_flight_class.upper()].get('price', price_vuelta))

                total_per_pax = price_ida + price_vuelta
                total_amount = total_per_pax * len(all_passengers)
                
                # PRIORIDAD: Si la API devolvió un precio confirmado, usar ese
                api_total_price = result.get('actual_price')
                if api_total_price:
                    # Si es lista, tomar el primer elemento
                    _api_p = api_total_price[0] if isinstance(api_total_price, list) else api_total_price
                    try:
                        _api_p_float = float(_api_p)
                        if _api_p_float > 0:
                            logger.info(f"Usando precio confirmado por API: {_api_p_float}")
                            total_amount = _api_p_float
                            if len(all_passengers) > 0:
                                total_per_pax = total_amount / len(all_passengers)
                    except (ValueError, TypeError):
                        pass
                
                response_data = {
                    "success": True,
                    "pnr": result.get('pnr'),
                    "vid": result.get('vid'),
                    "multiple_pnr": result.get('multiple_pnr', False),
                    "pnr_ida": result.get('pnr_ida'),
                    "pnr_vuelta": result.get('pnr_vuelta'),
                    "airline_ida": result.get('airline_ida'),
                    "airline_vuelta": result.get('airline_vuelta'),
                    "vuelo_ida": f"{selected_flight.get('airline_name')} {selected_flight.get('flight_number')}",
                    "ruta_ida": f"{selected_flight.get('origin')} → {selected_flight.get('destination')}",
                    "fecha_ida": selected_flight.get('date'),
                    "horario_salida_ida": selected_flight.get('departure_time'),
                    "horario_llegada_ida": selected_flight.get('arrival_time'),
                    "clase_ida": flight_class.upper(),
                    "precio_total": f"${total_amount:.2f} {selected_flight.get('currency', 'USD')}",
                    "precio_unitario": f"${total_per_pax:.2f}",
                    "raw_total_amount": total_amount,
                    "raw_total_per_pax": total_per_pax,
                    "num_passengers": len(all_passengers),
                    "pasajero": passenger_name,
                    "cedula": all_passengers[0]['idNumber'] if all_passengers else '',
                    "telefono": all_passengers[0]['phone'] if all_passengers else '',
                    "email": all_passengers[0]['email'] if all_passengers else '',
                    "es_ida_vuelta": is_round_trip
                }
                
                # Agregar datos del vuelo de vuelta si existe
                if return_flight:
                    response_data["vuelo_vuelta"] = f"{return_flight.get('airline_name')} {return_flight.get('flight_number')}"
                    response_data["ruta_vuelta"] = f"{return_flight.get('origin')} → {return_flight.get('destination')}"
                    response_data["fecha_vuelta"] = return_flight.get('date')
                    response_data["horario_salida_vuelta"] = return_flight.get('departure_time')
                    response_data["horario_llegada_vuelta"] = return_flight.get('arrival_time')
                    response_data["clase_vuelta"] = return_flight_class.upper()
                
                return response_data
            else:
                return {"success": False, "error": result.get('error', 'Error desconocido')}
        except Exception as e:
            logger.error(f"Error creando reserva: {str(e)}")
            return {"success": False, "error": str(e)}
    def _send_response(self, phone: str, message: str, session):
        """Envía respuesta con control de duplicados"""
        try:
            # Protección anti-duplicados: no enviar el mismo mensaje al mismo teléfono en corto tiempo
            current_time = time.time()
            last_msg_key = f"_last_sent_{phone}"
            last_msg_time_key = f"_last_sent_time_{phone}"
            
            last_sent = getattr(self, last_msg_key, None)
            last_sent_time = getattr(self, last_msg_time_key, 0)
            
            # Si el mensaje es idéntico al último enviado y han pasado menos de 10 segundos, ignorar
            if last_sent == message and (current_time - last_sent_time) < 10:
                logger.warning(f"Mensaje duplicado suprimido para {phone}: {message[:80]}...")
                return {'response': message, 'success': True}
            
            # Registrar este mensaje como el último enviado
            setattr(self, last_msg_key, message)
            setattr(self, last_msg_time_key, current_time)
            
            # LIMPIEZA FINAL: Eliminar líneas horizontales molestas (---, ___)
            # El usuario pidió quitar "esas rayas que salen"
            try:
                # Eliminar líneas que son solo guiones, underscores o caracteres similares
                message = re.sub(r'^\s*[-_—]{3,}\s*$', '', message, flags=re.MULTILINE)
                # Eliminar múltiples saltos de línea resultantes de la limpieza
                message = re.sub(r'\n{3,}', '\n\n', message).strip()
            except Exception as e:
                logger.warning(f"Error limpiando líneas del mensaje: {e}")
            
            session.add_message('assistant', message)
            wati_service.send_message(phone, message)
            return {'response': message, 'success': True}
        except Exception as e:
            logger.error(f"Error enviando: {str(e)}")
            return {'response': f"Error enviando mensaje: {str(e)}", 'success': False}


# Instancia global
gemini_agent_bot = GeminiAgentBot()
