# Fixes Aplicados — gemini_agent_bot.py

Este documento describe los 10 bugs críticos corregidos en `gemini_agent_bot.py`.

## BUG #1 — Estado sucio entre sesiones al activar el bot
**Archivo:** `gemini_agent_bot.py` → método `handle_message`  
**Síntoma:** Al escribir `cervo ai`, el bot arrancaba con comportamiento extraño de una sesión anterior.  
**Fix:** Se agregaron `awaiting_class_selection`, `awaiting_class_selection_is_return`, `search_results` y `ai_history` a `keys_to_clear`.

```python
# ANTES — faltaban estas claves:
keys_to_clear = [
    'awaiting_flight_confirmation', ...
    # ← faltaba 'awaiting_class_selection', 'ai_history'
]

# DESPUÉS:
keys_to_clear = [
    ...
    'awaiting_class_selection',
    'awaiting_class_selection_is_return',
    'search_results',
    'ai_history',  # ← CRÍTICO: sin esto el historial contamina sesiones nuevas
]
```

---

## BUG #2 — `pending_flight_index` se pierde al elegir clase inválida
**Archivo:** `gemini_agent_bot.py` → método `_process_with_ai` → bloque `awaiting_class_selection`  
**Síntoma:** Al escribir una clase inexistente, el bot pedía la clase de nuevo pero no recordaba qué vuelo se había seleccionado.  
**Fix:** Se guarda `original_pending_index` antes de llamar `_confirm_flight_selection_function` y se restaura si la clase falla.

```python
# ANTES:
if result.get('success'):
    ...
else:
    session.data['awaiting_class_selection'] = True  # ← pending_flight_index ya perdido

# DESPUÉS:
original_pending_index = session.data.get('pending_flight_index')  # ← guardar antes
# ...llamar función...
if result.get('success'):
    ...
else:
    session.data['awaiting_class_selection'] = True
    session.data['pending_flight_index'] = original_pending_index  # ← restaurar
```

---

## BUG #3 — `manual` tratado como nombre de pasajero
**Archivo:** `gemini_agent_bot.py` → método `_process_with_ai` → bloque `waiting_for_field`  
**Síntoma:** Al escribir `manual` cuando el bot pedía el nombre, era tratado como un nombre de pasajero válido.  
**Fix:** Se agrega `manual` a la lista de `stop_words` de validación de nombre/apellido Y se verifica explícitamente al inicio del bloque `waiting_for_field`.

```python
# AÑADIDO al inicio del bloque waiting_for_field:
if waiting_for_field and message.strip().lower() == 'manual':
    # Reiniciar flujo de ingreso de datos
    session.data['waiting_for_field'] = None
    session.data['extracted_data'] = {}
    session.data['waiting_for_field'] = 'nombre'
    return self._send_response(phone, "Entendido. ¿Cuál es el *nombre* del pasajero?", session)
```

---

## BUG #4 — Búsqueda ejecutada sin datos obligatorios
**Archivo:** `gemini_agent_bot.py` → método `_handle_function_call` → caso `search_flights`  
**Síntoma:** Gemini podía llamar `search_flights` con `origin=None` o `date=''`, generando errores en la API de KIU.  
**Fix:** Validación explícita antes de ejecutar la búsqueda.

```python
# AÑADIDO:
if not origin or not destination or not date:
    missing = [f for f, v in [('origen', origin), ('destino', destination), ('fecha', date)] if not v]
    return self._send_response(
        phone,
        f"Disculpa, me faltó información para buscar: *{', '.join(missing)}*. ¿Puedes confirmarme esos datos?",
        session
    )
```

---

## BUG #5 — Datos de IDA se borran al buscar vuelo de VUELTA
**Archivo:** `gemini_agent_bot.py` → método `_handle_function_call` → caso `search_flights` → bloque vuelta  
**Síntoma:** En viajes de ida y vuelta, al buscar el vuelo de regreso, los datos del vuelo de ida (índice, clase, precios) podían perderse.  
**Fix:** Se consolidan `ida_flight_index` e `ida_flight_class` desde `selected_flight_index`/`selected_flight_class` cuando se busca `trip_type='vuelta'` y esos campos no existen aún.

```python
# AÑADIDO al inicio del bloque trip_type == 'vuelta':
if trip_type == 'vuelta':
    # Asegurarse de preservar los datos de IDA antes de buscar vuelta
    if not session.data.get('ida_flight_index') and session.data.get('selected_flight_index'):
        session.data['ida_flight_index'] = session.data.get('selected_flight_index')
    if not session.data.get('ida_flight_class') and session.data.get('selected_flight_class'):
        session.data['ida_flight_class'] = session.data.get('selected_flight_class')
    if not session.data.get('ida_flight_classes_prices') and session.data.get('flight_classes_prices'):
        session.data['ida_flight_classes_prices'] = session.data.get('flight_classes_prices')
```

---

## BUG #6 — `return_date` no se actualiza si el usuario la corrige
**Archivo:** `gemini_agent_bot.py` → método `_handle_function_call` → caso `search_flights`  
**Síntoma:** Si el usuario corregía la fecha de regreso, la sesión mantenía la fecha anterior.  
**Fix:** El bloque `if function_args.get('return_date')` ya existía pero se verificó que no tenga condiciones adicionales. Se convirtió a una asignación incondicional cuando el argumento existe.

```python
# ANTES (condición que podía no ejecutarse):
if function_args.get('return_date'):
    session.data['return_date'] = function_args.get('return_date')

# DESPUÉS (siempre actualizar si Gemini lo proporciona, incluso si ya existe):
return_date_arg = function_args.get('return_date')
if return_date_arg:  # Siempre sobrescribir - permite corrección de fecha
    session.data['return_date'] = return_date_arg
    logger.info(f"return_date actualizada: {return_date_arg}")
```

---

## BUG #7 — Mensaje doble al confirmar clase de IDA en viaje redondo
**Archivo:** `gemini_agent_bot.py` → método `_process_with_ai` → bloque confirmación IDA + vuelta  
**Síntoma:** Al confirmar la clase del vuelo de ida en un viaje redondo, el bot enviaba 2 mensajes: el de confirmación manual + el texto que generaba Gemini al llamar `search_flights`.  
**Fix:** Se agrega `confirm_msg` al historial de Gemini antes de continuar el flujo, para que Gemini sepa que ya respondió y no genere texto adicional.

```python
# AÑADIDO antes de dejar caer al flujo de Gemini:
confirm_msg = f"Perfecto, vuelo de ida confirmado..."
self._send_response(phone, confirm_msg, session)

# ← NUEVO: registrar en historial para que Gemini no duplique
history = session.data.get('ai_history', [])
history.append({"role": "model", "parts": [{"text": confirm_msg}]})
session.data['ai_history'] = history

message = "INSTRUCCION INTERNA..."
```

---

## BUG #8 — Flujo `manual` interceptado incorrectamente
**Archivo:** `gemini_agent_bot.py` → bloque `awaiting_flight_confirmation` → detección de `detected_option`  
**Síntoma:** Cuando el usuario escribía `manual` y `flight_selection_fully_confirmed=False`, `detected_confirm` se seteaba a `'si'` automáticamente, causando que el bot intentara confirmar el vuelo antes de pedir datos.  
**Fix:** Se agrega condición: `detected_confirm` solo se setea a `'si'` si `detected_option` NO es `'manual'` cuando el vuelo no está completamente confirmado.

```python
# ANTES:
if detected_option and not session.data.get('flight_selection_fully_confirmed'):
    detected_confirm = 'si'

# DESPUÉS:
if detected_option and detected_option != 'manual' and not session.data.get('flight_selection_fully_confirmed'):
    detected_confirm = 'si'
elif detected_option == 'manual':
    # Manual no necesita confirmación de vuelo primero
    detected_confirm = None
```

---

## BUG #9 — `waiting_for_field` no se limpia cuando `create_booking` falla
**Archivo:** `gemini_agent_bot.py` → todos los bloques donde se llama `_create_booking_function`  
**Síntoma:** Si la reserva fallaba, el siguiente mensaje del usuario era interceptado como si fuera un campo de datos de pasajero.  
**Fix:** En todos los bloques de error de `create_booking`, se limpia `waiting_for_field`.

```python
# AÑADIDO en todos los bloques else de booking_result:
else:
    raw_error = booking_result.get('error', 'Error desconocido')
    session.data['waiting_for_field'] = None  # ← NUEVO: limpiar estado
    session.data['extracted_data'] = {}       # ← NUEVO: limpiar datos parciales
    return self._send_response(phone, f"No se pudo crear la reserva: {raw_error}", session)
```

---

## BUG #10 — `num_passengers` silencioso en 1 cuando Gemini no lo pasa
**Archivo:** `gemini_agent_bot.py` → método `_handle_function_call` → caso `search_flights`  
**Síntoma:** Si Gemini llamaba `search_flights` sin pasar `num_passengers`, se usaba `1` en silencio aunque el usuario hubiera dicho "somos 3 personas".  
**Fix:** Se consulta `session.data.get('num_passengers')` como fallback antes de usar el default `1`.

```python
# ANTES:
num_passengers = safe_int(raw_num_passengers, 1)

# DESPUÉS:
if raw_num_passengers:
    num_passengers = safe_int(raw_num_passengers, 1)
else:
    # Recuperar desde sesión si Gemini no lo pasó
    saved_pax = session.data.get('num_passengers', 0)
    if saved_pax and saved_pax > 0:
        num_passengers = saved_pax
        logger.info(f"num_passengers recuperado de sesión: {num_passengers}")
    else:
        num_passengers = 1
```
