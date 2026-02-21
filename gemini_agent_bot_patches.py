"""
PARCHES PARA gemini_agent_bot.py
Aplicar estos cambios directamente al archivo gemini_agent_bot.py

Cada sección indica exactamente QUÉ cambiar y DÓNDE.
"""

# =============================================================================
# PATCH #1: handle_message — Limpiar passengers_list al activar el bot
# =============================================================================
# En el método handle_message, en el bloque de activación (message_lower in ['cervo ai', ...]),
# AGREGAR 'passengers_list' a la lista keys_to_clear:
#
# BUSCAR:
#     keys_to_clear = [
#         'awaiting_flight_confirmation', 'flight_selection_fully_confirmed', 
#         ...
#     ]
#
# REEMPLAZAR con (agregar las keys que faltan):
#     keys_to_clear = [
#         'awaiting_flight_confirmation', 'flight_selection_fully_confirmed', 
#         'waiting_for_field', 'passengers_list', 'extracted_data', 
#         'selected_flight', 'selected_flight_index', 'flight_confirmed',
#         'num_passengers', 'num_adults', 'num_children', 'num_infants',
#         'available_flights', 'return_flights', 'pending_flight_index',
#         'ida_class_confirmed', 'return_date', 'is_round_trip',
#         'pending_return_flight_index', 'selected_return_flight',
#         'selected_return_flight_index', 'selected_flight_class',
#         'selected_return_flight_class', 'return_flight_confirmed',
#         'using_document_image', 'document_image_url',
#         'ida_flight_index', 'ida_flight_class', 'ida_flight_classes_prices',
#         'return_flight_fully_confirmed', 'flight_classes_prices',
#         'return_flight_classes_prices', 'waiting_for_cedula_image',
#         'awaiting_class_selection', 'awaiting_class_selection_is_return',  # <-- AGREGAR
#         'search_results',  # <-- AGREGAR
#     ]
# NOTE: passengers_list YA estaba en la lista, correcto.


# =============================================================================
# PATCH #2: _process_with_ai — Mover detección de detected_option DENTRO del guard
# =============================================================================
# BUG: El bloque `awaiting_class_selection` tiene un early return correcto,
# pero el bloque `awaiting_flight_confirmation` calcula detected_confirm/detected_option
# ANTES de revisar si waiting_for_field está activo. Aunque la condición del if lo filtra,
# el código de detección de AI se ejecuta igualmente (costoso y potencialmente peligroso).
# 
# La condición ya es: `if session.data.get('awaiting_flight_confirmation') and not session.data.get('waiting_for_field'):`
# Esto está BIEN. Sin embargo, el problema real es en el bloque de 'manual':
#
# BUSCAR (aproximadamente línea ~790):
#     message_clean = message.lower().strip()
#     if message_clean == 'manual' and session.data.get('awaiting_flight_confirmation'):
#         # Iniciar flujo manual
#         session.data['extracted_data'] = {}  # Limpiar datos previos
#         # Iniciar lista de pasajeros si no existe
#         if not session.data.get('passengers_list'):
#             session.data['passengers_list'] = []
#         
#         # Determinar qué pasajero estamos procesando
#         current_count = len(session.data['passengers_list'])
#         total_passengers = session.data.get('num_passengers', 1)
#         
#         if current_count < total_passengers:
#             # Empezar a pedir datos comenzando por el Nombre
#             session.data['waiting_for_field'] = 'nombre'
#             passenger_label = ...
#             return self._send_response(phone, f"Entendido, ingreso manual...", session)
#
# REEMPLAZAR con (agregar limpieza de awaiting_flight_confirmation):
#     message_clean = message.lower().strip()
#     if message_clean == 'manual' and session.data.get('awaiting_flight_confirmation'):
#         session.data['extracted_data'] = {}
#         if not session.data.get('passengers_list'):
#             session.data['passengers_list'] = []
#         current_count = len(session.data['passengers_list'])
#         total_passengers = session.data.get('num_passengers', 1)
#         if current_count < total_passengers:
#             session.data['waiting_for_field'] = 'nombre'
#             session.data['awaiting_flight_confirmation'] = False  # <-- AGREGAR ESTA LÍNEA
#             passenger_label = ...
#             return self._send_response(...)


# =============================================================================
# PATCH #3: awaiting_class_selection — Guardar/restaurar pending_flight_index
# =============================================================================
# BUG: Cuando se selecciona una clase inválida, el estado se restaura pero
# pending_flight_index ya fue limpiado.
#
# BUSCAR en el bloque `if session.data.get('awaiting_class_selection')`:
#     # Limpiar el estado de espera de clase
#     session.data['awaiting_class_selection'] = False
#     
#     # Llamar a la función de confirmación con la clase elegida
#     result = self._confirm_flight_selection_function(
#         flight_index=flight_index,
#         ...
#     )
#     
#     if result.get('success'):
#         ...
#     else:
#         # Restaurar estado de selección
#         session.data['awaiting_class_selection'] = True
#         return ...
#
# REEMPLAZAR con:
#     # Guardar backup del índice ANTES de limpiar el estado
#     backup_flight_index = flight_index
#     backup_is_return = is_return
#     session.data['awaiting_class_selection'] = False
#     
#     result = self._confirm_flight_selection_function(...)
#     
#     if result.get('success'):
#         if is_return:
#             session.data['selected_return_flight_class'] = extracted_class
#         else:
#             session.data['selected_flight_class'] = extracted_class
#         return self._send_response(phone, result.get('message', ''), session)
#     else:
#         # Restaurar estado correctamente
#         session.data['awaiting_class_selection'] = True
#         session.data['awaiting_class_selection_is_return'] = backup_is_return
#         if backup_is_return:
#             session.data['selected_return_flight_index'] = backup_flight_index
#         else:
#             session.data['pending_flight_index'] = backup_flight_index
#         return self._send_response(phone, result.get('message', 'Clase no disponible.'), session)


# =============================================================================
# PATCH #4: _handle_function_call search_flights — Validar datos obligatorios
# =============================================================================
# BUG: Gemini puede llamar search_flights sin num_passengers o sin is_round_trip.
# Agregar validación al inicio del handler de search_flights:
#
# BUSCAR:
#     if function_name == "search_flights":
#         # Enviar mensaje de "buscando" ANTES de ejecutar la búsqueda
#         origin = function_args.get('origin')
#         destination = function_args.get('destination')
#         date = function_args.get('date')
#         trip_type = function_args.get('trip_type', 'ida')
#
# AGREGAR VALIDACIÓN JUSTO DESPUÉS (antes del bloque safe_int):
#         # VALIDACIÓN DE DATOS OBLIGATORIOS
#         if not origin or not destination or not date:
#             missing = []
#             if not origin: missing.append('origen')
#             if not destination: missing.append('destino')
#             if not date: missing.append('fecha')
#             return self._send_response(phone, 
#                 f"Necesito más información para buscar vuelos: falta el/la {', '.join(missing)}. ¿Me lo puedes decir?",
#                 session
#             )
#         
#         raw_num_passengers = function_args.get('num_passengers')
#         if not raw_num_passengers or int(float(raw_num_passengers)) < 1:
#             return self._send_response(phone,
#                 "¿Para cuántas personas necesitas el vuelo?",
#                 session
#             )


# =============================================================================
# PATCH #5: _handle_function_call search_flights — No limpiar datos de IDA al buscar VUELTA
# =============================================================================
# BUG: En el bloque de reset (trip_type == 'ida'), se borra TODO incluyendo
# available_flights que puede ser necesario si el usuario recae en el flujo.
# Además, cuando trip_type == 'vuelta', el reset no debería limpiar datos de ida.
#
# El bloque actual tiene:
#     if trip_type == 'ida':
#         session.data['flight_confirmed'] = False
#         ...
#         session.data.pop('available_flights', None)  # <-- ESTO BORRA LOS VUELOS DE IDA
#
# CORRECCIÓN: Para trip_type == 'vuelta', NO hacer ningún reset.
# Para trip_type == 'ida', el reset está bien EXCEPTO que debe preservar:
# - La lógica ya está, pero agregar seguridad:
#
# AGREGAR justo antes del reset condicional:
#         # Preservar datos de ida si estamos buscando la vuelta
#         if trip_type == 'vuelta':
#             logger.info("Búsqueda de VUELTA: preservando datos de IDA en sesión")
#             # No resetear nada para vuelta
#             pass
#         elif trip_type == 'ida':
#             # Reset completo para nueva búsqueda de ida
#             session.data['flight_confirmed'] = False
#             ...


# =============================================================================
# PATCH #6: Return date — Siempre actualizar desde function_args
# =============================================================================
# BUSCAR:
#     # Guardar return_date si existe
#     if function_args.get('return_date'):
#         session.data['return_date'] = function_args.get('return_date')
#
# REEMPLAZAR con:
#     # Guardar return_date si existe (siempre actualizar para reflejar lo más reciente)
#     new_return_date = function_args.get('return_date')
#     if new_return_date:
#         if session.data.get('return_date') != new_return_date:
#             logger.info(f"Actualizando return_date: {session.data.get('return_date')} -> {new_return_date}")
#         session.data['return_date'] = new_return_date


# =============================================================================
# PATCH #7: Doble mensaje en confirmación de ida (round trip)
# =============================================================================
# BUG: En el bloque `if is_round_trip and not ida_class_confirmed`, se envía
# confirm_msg con _send_response, y luego se modifica `message` para que Gemini
# haga la búsqueda de vuelta. Gemini puede generar OTRO mensaje además de llamar
# a search_flights, causando duplicados.
#
# SOLUCIÓN: Llamar DIRECTAMENTE a _search_flights_function sin pasar por Gemini,
# o hacer que el mensaje de instrucción interna sea más estricto para que Gemini
# SOLO llame a search_flights sin generar texto.
#
# El mensaje de instrucción ya tiene "NO MOSTRAR AL USUARIO" pero Gemini a veces
# genera texto igualmente. Agregar instrucción más fuerte:
#
# BUSCAR:
#     message = f"INSTRUCCION INTERNA - NO MOSTRAR AL USUARIO: Busca ahora el vuelo..."
#
# REEMPLAZAR con: Llamada directa a la función en Python
# (ver implementación en gemini_agent_bot_fixed.py)


# =============================================================================
# PATCH #8: _confirm_flight_selection_function — Asignar clase en sesión ANTES de llamar
# =============================================================================
# En el bloque `if session.data.get('awaiting_class_selection')`, el código hace:
#     result = self._confirm_flight_selection_function(..., extracted_class, ...)
#     if result.get('success'):
#         if is_return:
#             session.data['selected_return_flight_class'] = extracted_class  # DESPUÉS
#         else:
#             session.data['selected_flight_class'] = extracted_class  # DESPUÉS
#
# Esto está bien para el caso de éxito. El bug real es que _confirm_flight_selection_function
# internamente busca session.data.get('selected_flight_class') para ciertos cálculos.
# Si la función necesita la clase antes de que se guarde, puede fallar.
#
# SOLUCIÓN: Guardar la clase en sesión ANTES de llamar la función, y limpiarla si falla:
#     if is_return:
#         session.data['selected_return_flight_class'] = extracted_class  # ANTES
#     else:
#         session.data['selected_flight_class'] = extracted_class  # ANTES
#     
#     result = self._confirm_flight_selection_function(...)
#     
#     if not result.get('success'):
#         # Limpiar si falló
#         if is_return:
#             session.data.pop('selected_return_flight_class', None)
#         else:
#             session.data.pop('selected_flight_class', None)


print("Patches documentados. Ver FIXES.md para detalles completos.")
