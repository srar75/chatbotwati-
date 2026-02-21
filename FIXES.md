# Correcciones Aplicadas al Chatbot Cervo

## Bugs Identificados y Corregidos

### 1. `gemini_agent_bot.py` — Flujo principal

#### BUG #1: `awaiting_class_selection` nunca se limpia cuando hay error de clase
Cuando el usuario escribe una clase inválida (ej: `X`) el estado `awaiting_class_selection` se restaura a `True` pero el índice `pending_flight_index` ya fue consumido, causando que el bot quede atascado.

**Fix:** Guardar el `pending_flight_index` ANTES de llamar `_confirm_flight_selection_function` y restaurarlo si falla.

---

#### BUG #2: Búsqueda se ejecuta sin tener todos los datos (tipo de viaje, pasajeros)
Gemini puede llamar `search_flights` antes de que el usuario responda si es ida/vuelta o cuántos pasajeros son. El system prompt lo previene pero no hay validación en el handler de la función.

**Fix:** En `_handle_function_call` → `search_flights`, validar que `num_passengers >= 1` y que `is_round_trip` esté definido. Si `trip_type` no es ni `'ida'` ni `'vuelta'`, rechazar con mensaje.

---

#### BUG #3: `pending_flight_index` se pierde en el flujo de IDA Y VUELTA
Después de confirmar la clase de ida, al buscar vuelos de vuelta, `pending_flight_index` se resetea junto con el resto del estado, pero `ida_flight_index` no siempre se conserva correctamente.

**Fix:** En el bloque de reset de `search_flights` con `trip_type == 'ida'`, asegurarse de NO limpiar `ida_flight_index`, `ida_flight_class`, `ida_flight_classes_prices` cuando ya estén guardados.

---

#### BUG #4: `selected_return_flight_class` se usa antes de ser asignado
En el flujo de vuelta, se llama `_confirm_flight_selection_function` con `extracted_class` antes de que `session.data['selected_return_flight_class']` sea asignado, causando que la función reciba `None`.

**Fix:** Asignar la clase en sesión ANTES de llamar a la función, no después.

---

#### BUG #5: El flujo de confirmación de pasajeros en manual no limpia `awaiting_flight_confirmation`
Cuando el usuario escribe `manual` para ingresar datos, el flag `awaiting_flight_confirmation` queda en `True` y el bloque de confirmación intercepta los datos del pasajero (nombre, apellido, etc.) clasificándolos erróneamente.

**Fix:** Al iniciar flujo manual (`waiting_for_field = 'nombre'`), poner `awaiting_flight_confirmation = False`.

---

#### BUG #6: `waiting_for_field` y `awaiting_flight_confirmation` activos simultáneamente
Si `waiting_for_field` está activo, el bloque `awaiting_flight_confirmation` no debería ejecutarse. La condición `if session.data.get('awaiting_flight_confirmation') and not session.data.get('waiting_for_field')` estaba bien, pero el problema es que el `detected_option` se calcula SIEMPRE al inicio del bloque, y puede setear variables que afectan el flujo del pasajero.

**Fix:** Mover la detección de `detected_option` dentro de la condición `not waiting_for_field`.

---

#### BUG #7: `return_date` no se guarda cuando Gemini llama `search_flights` con `is_round_trip=True` en el primer vuelo
Si el usuario dice "ida y vuelta el 20/02 regreso el 25/02", Gemini llama `search_flights(trip_type='ida', is_round_trip=True, return_date='2026-02-25')`. La `return_date` se guarda en sesión, pero si el usuario modifica la fecha en conversación posterior, `session.data['return_date']` no se actualiza.

**Fix:** Siempre actualizar `return_date` desde `function_args` si está presente, sin importar si ya existe en sesión.

---

#### BUG #8: `passengers_list` no se reinicia entre reservas
Si el usuario completa una reserva y luego intenta hacer otra, `passengers_list` tiene los datos de la reserva anterior. Esto causa que el bot crea que ya tiene pasajeros y salta pasos.

**Fix:** Reiniciar `passengers_list = []` en el bloque de reset de `search_flights` con `trip_type == 'ida'` (ya está parcialmente, pero falta en el reset de sesión al activar el bot).

---

#### BUG #9: `_send_booking_success_message` puede fallar si `selected_flight` está vacío
Si `available_flights` no está en sesión o el índice está fuera de rango, `selected_flight` queda como `{}` y el formateo del mensaje de éxito falla silenciosamente.

**Fix:** Agregar guards defensivos en `_send_booking_success_message`.

---

#### BUG #10: Doble envío de mensaje en confirmación de vuelo round-trip
En el flujo de `detected_confirm == 'si'` → `is_round_trip and not ida_class_confirmed`, se llama `self._send_response` con `confirm_msg` Y luego se pasa el flujo a Gemini que genera OTRO mensaje. Esto causa que el usuario reciba dos mensajes duplicados.

**Fix:** Usar `return` después de iniciar la búsqueda de vuelo de vuelta cuando Gemini lo manejará, o manejar el flujo completamente en Python sin pasar a Gemini.

---

## Archivo de Correcciones: `gemini_agent_bot_patches.py`

Ver `gemini_agent_bot_patches.py` para los monkey-patches aplicables.
